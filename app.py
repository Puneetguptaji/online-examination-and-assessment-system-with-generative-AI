"""ExamAI Python Edition: Flask + MySQL + optional live Gemini API.

Exact marks are computed by this server-side Python application. Gemini is used
only for question drafts and study feedback; teachers approve every AI question.
"""
from datetime import datetime, timedelta
from functools import wraps
import hmac
import json
import re
import secrets

from flask import (Flask, abort, flash, g, has_request_context, jsonify, redirect, render_template,
                   request, session, url_for)
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.serving import WSGIRequestHandler

import config
import db
from db import DatabaseUnavailable
from ai_service import GeminiService, AIServiceError
from scoring import calculate_score

app = Flask(__name__)
app.config.update(
    SECRET_KEY=config.SECRET_KEY,
    DB_CONFIG=config.DB_CONFIG,
    SESSION_COOKIE_NAME=config.SESSION_COOKIE_NAME,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=config.SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,
    SESSION_COOKIE_PARTITIONED=config.SESSION_COOKIE_PARTITIONED,
    MAX_CONTENT_LENGTH=1_000_000,
)
db.init_app(app)
PREVIEW_TOKEN_MAX_AGE = 4 * 60 * 60
preview_token_serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="examai-preview-auth")


# ------------------------------- request/security helpers
def active_user():
    """Return the cookie session user, or the signed preview identity if enabled."""
    return getattr(g, "preview_user", None) or session.get("user")


def issue_preview_token(user_id):
    return preview_token_serializer.dumps({"uid": int(user_id)})


def wants_json_response():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")


@app.context_processor
def inject_globals():
    return {
        "current_user": active_user(),
        "preview_token": getattr(g, "preview_token", None),
        "csrf_token": lambda: "" if config.PREVIEW_TOKEN_AUTH else session.setdefault("_csrf", secrets.token_urlsafe(32)),
        "app_name": config.APP_NAME,
    }


@app.url_defaults
def preserve_preview_token(endpoint, values):
    if not config.PREVIEW_TOKEN_AUTH or endpoint == "static" or not has_request_context():
        return
    token = getattr(g, "preview_token", None)
    if token:
        values.setdefault("preview_token", token)


@app.before_request
def verify_csrf():
    g.preview_token = None
    g.preview_user = None
    if config.PREVIEW_TOKEN_AUTH:
        token = request.args.get("preview_token", "") or request.form.get("preview_token", "")
        if token:
            try:
                payload = preview_token_serializer.loads(token, max_age=PREVIEW_TOKEN_MAX_AGE)
                uid = int(payload["uid"])
                row = db.one("SELECT id,full_name,email,role,roll_no FROM users WHERE id=%s", (uid,))
                if row:
                    g.preview_token = token
                    g.preview_user = {
                        "id": row["id"], "name": row["full_name"], "email": row["email"],
                        "role": row["role"], "roll_no": row["roll_no"],
                    }
            except (BadSignature, KeyError, TypeError, ValueError):
                pass

    if request.method != "POST":
        return
    if config.PREVIEW_TOKEN_AUTH:
        # The hosted preview runs in a browser that blocks cookies. Authentication
        # is instead carried by a short-lived signed URL token. This relaxed mode
        # is for the disposable sandbox demo only; local/installed mode keeps CSRF.
        if request.path in {"/login", "/register"} or active_user():
            return
        flash("Your preview sign-in expired. Please sign in again.", "warning")
        return redirect(url_for("login"))

    expected = session.get("_csrf", "")
    submitted = request.form.get("_csrf", "") or request.headers.get("X-CSRF-Token", "")
    if not expected or not submitted or not hmac.compare_digest(expected, submitted):
        # Log only presence/match metadata, never the CSRF/session values.
        app.logger.warning(
            "CSRF rejected path=%s cookie_present=%s expected_present=%s submitted_present=%s match=%s origin=%s",
            request.path,
            bool(request.cookies.get(app.config["SESSION_COOKIE_NAME"])),
            bool(expected),
            bool(submitted),
            bool(expected and submitted and hmac.compare_digest(expected, submitted)),
            request.headers.get("Origin", ""),
        )
        abort(400, description="The form expired or its security token was missing. Refresh and retry.")


@app.after_request
def protect_preview_tokens(response):
    if config.PREVIEW_TOKEN_AUTH:
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
    return response


def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = active_user()
            if not user:
                flash("Please sign in first.", "warning")
                return redirect(url_for("login", next=request.path))
            if role and user.get("role") != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def current_user_id():
    user = active_user() or {}
    return int(user.get("id", 0))


def owned_exam(exam_id):
    exam = db.one("SELECT * FROM exams WHERE id=%s AND created_by=%s", (exam_id, current_user_id()))
    if not exam:
        abort(404)
    return exam


def exam_is_editable(exam_id, exam=None):
    exam = exam or owned_exam(exam_id)
    attempts = db.one("SELECT COUNT(*) AS n FROM attempts WHERE exam_id=%s", (exam_id,))["n"]
    return exam["status"] == "DRAFT" and attempts == 0


def owned_attempt(attempt_id):
    attempt = db.one(
        "SELECT a.*, e.title, e.subject, e.duration_minutes FROM attempts a "
        "JOIN exams e ON e.id=a.exam_id WHERE a.id=%s AND a.student_id=%s",
        (attempt_id, current_user_id()),
    )
    if not attempt:
        abort(404)
    return attempt


def recalc_exam_total(exam_id):
    db.execute("UPDATE exams SET total_marks=(SELECT COALESCE(SUM(marks),0) FROM questions WHERE exam_id=%s) WHERE id=%s",
                (exam_id, exam_id))


def option_text(question, letter):
    if not letter:
        return "Not answered"
    return question.get("option_" + letter.lower(), "Not answered")


def finalize_attempt(attempt_id, force=False):
    """Compute the exact score from MySQL answer keys; never trust browser scores or AI."""
    attempt = db.one("SELECT * FROM attempts WHERE id=%s AND student_id=%s",
                     (attempt_id, current_user_id()))
    if not attempt:
        abort(404)
    if attempt["status"] != "IN_PROGRESS":
        return attempt
    now = datetime.now()
    expired = now >= attempt["deadline_at"]
    if not force and not expired:
        return attempt
    # Exact scoring is performed by this Python function from the stored answer key.
    # Gemini is never given authority to award marks.
    rows = db.all_rows(
        "SELECT q.id,q.marks,q.correct_option,a.selected_option FROM questions q "
        "LEFT JOIN answers a ON a.question_id=q.id AND a.attempt_id=%s WHERE q.exam_id=%s",
        (attempt_id, attempt["exam_id"]),
    )
    score, total, pct = calculate_score(rows)
    for row in rows:
        if row.get("selected_option"):
            db.execute("UPDATE answers SET is_correct=%s WHERE attempt_id=%s AND question_id=%s",
                       (row["selected_option"] == row["correct_option"], attempt_id, row["id"]))
    status = "AUTO_SUBMITTED" if expired else "SUBMITTED"
    db.execute(
        "UPDATE attempts SET score=%s,total_marks=%s,percentage=%s,status=%s,submitted_at=%s WHERE id=%s",
        (score, total, pct, status, now, attempt_id),
    )
    return db.one("SELECT * FROM attempts WHERE id=%s", (attempt_id,))


def result_reviews(attempt):
    ids = attempt.get("question_order") or []
    if isinstance(ids, str):
        try:
            ids = json.loads(ids)
        except ValueError:
            ids = []
    if not ids:
        return []
    marks = ",".join(["%s"] * len(ids))
    rows = db.all_rows(
        "SELECT q.*, a.selected_option, a.is_correct FROM questions q "
        "LEFT JOIN answers a ON a.question_id=q.id AND a.attempt_id=%s "
        f"WHERE q.id IN ({marks})", (attempt["id"], *ids),
    )
    by_id = {r["id"]: r for r in rows}
    review = []
    for qid in ids:
        q = by_id.get(int(qid))
        if not q:
            continue
        selected = q.get("selected_option")
        review.append({
            **q,
            "selected_text": option_text(q, selected),
            "correct_text": option_text(q, q["correct_option"]),
            "is_correct": bool(selected and selected == q["correct_option"]),
        })
    return review


# ------------------------------------------- public/auth
@app.get("/")
def index():
    user = active_user()
    if not user:
        return redirect(url_for("login"))
    return redirect(url_for("teacher_dashboard" if user["role"] == "TEACHER" else "student_dashboard"))


@app.get("/health")
def health():
    db.one("SELECT 1 AS ok")
    return jsonify(status="ok", database="connected", ai_configured=GeminiService().configured)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.one("SELECT id,full_name,email,password_hash,role,roll_no FROM users WHERE email=%s", (email,))
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Email or password is incorrect.", "error")
        else:
            if config.PREVIEW_TOKEN_AUTH:
                g.preview_user = {"id": user["id"], "name": user["full_name"], "email": user["email"],
                                  "role": user["role"], "roll_no": user["roll_no"]}
                g.preview_token = issue_preview_token(user["id"])
                endpoint = "teacher_dashboard" if user["role"] == "TEACHER" else "student_dashboard"
                return redirect(url_for(endpoint))
            session.clear()
            session["user"] = {"id": user["id"], "name": user["full_name"], "email": user["email"],
                               "role": user["role"], "roll_no": user["roll_no"]}
            session["_csrf"] = secrets.token_urlsafe(32)
            next_url = request.args.get("next", "")
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("teacher_dashboard" if user["role"] == "TEACHER" else "student_dashboard")
            return redirect(next_url)
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        roll = request.form.get("roll_no", "").strip()
        password = request.form.get("password", "")
        if len(name) < 2 or "@" not in email or len(password) < 8:
            flash("Enter your name, a valid email and a password with at least 8 characters.", "error")
        else:
            try:
                uid, _ = db.execute(
                    "INSERT INTO users(full_name,email,password_hash,role,roll_no) VALUES(%s,%s,%s,'STUDENT',%s)",
                    (name, email, generate_password_hash(password), roll or None),
                )
                if config.PREVIEW_TOKEN_AUTH:
                    g.preview_user = {"id": uid, "name": name, "email": email, "role": "STUDENT", "roll_no": roll}
                    g.preview_token = issue_preview_token(uid)
                    return redirect(url_for("student_dashboard"))
                session.clear()
                session["user"] = {"id": uid, "name": name, "email": email, "role": "STUDENT", "roll_no": roll}
                session["_csrf"] = secrets.token_urlsafe(32)
                return redirect(url_for("student_dashboard"))
            except Exception as exc:
                if "Duplicate" in str(exc):
                    flash("That email is already registered. Sign in instead.", "error")
                else:
                    raise
    return render_template("register.html")


@app.post("/logout")
@login_required()
def logout():
    session.clear()
    if config.PREVIEW_TOKEN_AUTH:
        g.preview_user = None
        g.preview_token = None
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


# --------------------------------------------- teacher
@app.get("/teacher")
@login_required("TEACHER")
def teacher_dashboard():
    uid = current_user_id()
    stats = db.one(
        "SELECT COUNT(DISTINCT e.id) AS exams, "
        "COALESCE(SUM(a.status IN ('SUBMITTED','AUTO_SUBMITTED')),0) AS submissions, "
        "COALESCE(AVG(CASE WHEN a.status IN ('SUBMITTED','AUTO_SUBMITTED') THEN a.percentage END),0) AS avg_percent "
        "FROM exams e LEFT JOIN attempts a ON a.exam_id=e.id WHERE e.created_by=%s", (uid,)
    )
    pending = db.one("SELECT COUNT(*) AS n FROM ai_drafts WHERE teacher_id=%s AND status='PENDING'", (uid,))["n"]
    exams = db.all_rows("SELECT e.*, (SELECT COUNT(*) FROM questions q WHERE q.exam_id=e.id) AS question_count, "
                        "(SELECT COUNT(*) FROM attempts a WHERE a.exam_id=e.id AND a.status<>'IN_PROGRESS') AS attempts "
                        "FROM exams e WHERE e.created_by=%s ORDER BY e.updated_at DESC LIMIT 6", (uid,))
    return render_template("teacher_dashboard.html", stats=stats, pending=pending, exams=exams)


@app.route("/teacher/exams", methods=["GET", "POST"])
@login_required("TEACHER")
def teacher_exams():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        subject = request.form.get("subject", "").strip()
        description = request.form.get("description", "").strip()
        try:
            duration = int(request.form.get("duration_minutes", "30"))
        except ValueError:
            duration = 0
        if not title or not subject or not 1 <= duration <= 240:
            flash("Enter a title, subject and duration between 1 and 240 minutes.", "error")
        else:
            exam_id, _ = db.execute(
                "INSERT INTO exams(title,subject,description,duration_minutes,created_by) VALUES(%s,%s,%s,%s,%s)",
                (title, subject, description or None, duration, current_user_id()),
            )
            flash("Draft exam created. Add questions before publishing.", "success")
            return redirect(url_for("teacher_questions", exam_id=exam_id))
    exams = db.all_rows("SELECT e.*, (SELECT COUNT(*) FROM questions q WHERE q.exam_id=e.id) AS question_count, "
                        "(SELECT COUNT(*) FROM attempts a WHERE a.exam_id=e.id AND a.status<>'IN_PROGRESS') AS attempts "
                        "FROM exams e WHERE e.created_by=%s ORDER BY e.updated_at DESC", (current_user_id(),))
    return render_template("teacher_exams.html", exams=exams)


@app.post("/teacher/exam/<int:exam_id>/status")
@login_required("TEACHER")
def exam_status(exam_id):
    exam = owned_exam(exam_id)
    status = request.form.get("status")
    if status == "PUBLISHED":
        count = db.one("SELECT COUNT(*) AS n FROM questions WHERE exam_id=%s", (exam_id,))["n"]
        if not count:
            flash("Add at least one question before publishing.", "error")
            return redirect(url_for("teacher_exams"))
    if status not in ("DRAFT", "PUBLISHED", "CLOSED"):
        abort(400)
    if status == "DRAFT" and not exam_is_editable(exam_id, exam):
        flash("A paper with attempts cannot be returned to draft because that could change its marking record.", "error")
        return redirect(url_for("teacher_exams"))
    db.execute("UPDATE exams SET status=%s WHERE id=%s", (status, exam["id"]))
    flash(f"Exam status changed to {status.title()}.", "success")
    return redirect(url_for("teacher_exams"))


@app.route("/teacher/exam/<int:exam_id>/questions", methods=["GET", "POST"])
@login_required("TEACHER")
def teacher_questions(exam_id):
    exam = owned_exam(exam_id)
    if request.method == "POST":
        if not exam_is_editable(exam_id, exam):
            flash("Questions can only be changed while the exam is an unused draft.", "error")
            return redirect(url_for("teacher_questions", exam_id=exam_id))
        text = request.form.get("question_text", "").strip()
        options = [request.form.get(f"option_{letter.lower()}", "").strip() for letter in "ABCD"]
        correct = request.form.get("correct_option", "")
        topic = request.form.get("topic", "General").strip()[:100] or "General"
        explanation = request.form.get("explanation", "").strip()
        try:
            marks = int(request.form.get("marks", "1"))
        except ValueError:
            marks = 0
        if not text or any(not x for x in options) or correct not in "ABCD" or not 1 <= marks <= 100:
            flash("Complete the question, all four options, answer and valid marks.", "error")
        elif len({o.casefold() for o in options}) != 4:
            flash("The four answer options must be different.", "error")
        else:
            db.execute(
                "INSERT INTO questions(exam_id,question_text,option_a,option_b,option_c,option_d,correct_option,topic,marks,explanation,source) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'MANUAL')",
                (exam_id, text, *options, correct, topic, marks, explanation or None),
            )
            recalc_exam_total(exam_id)
            flash("Question added to the draft.", "success")
            return redirect(url_for("teacher_questions", exam_id=exam_id))
    questions = db.all_rows("SELECT * FROM questions WHERE exam_id=%s ORDER BY id", (exam_id,))
    return render_template("teacher_questions.html", exam=exam, questions=questions,
                           ai_configured=GeminiService().configured)


@app.post("/teacher/exam/<int:exam_id>/ai-generate")
@login_required("TEACHER")
def ai_generate_questions(exam_id):
    exam = owned_exam(exam_id)
    if not exam_is_editable(exam_id, exam):
        message = "AI drafts can only be added to an unused draft exam."
        if wants_json_response():
            return jsonify(ok=False, error=message), 409
        flash(message, "error")
        return redirect(url_for("teacher_questions", exam_id=exam_id))
    topic = request.form.get("topic", "").strip()
    difficulty = request.form.get("difficulty", "Medium").title()
    try:
        count = int(request.form.get("count", "3"))
    except ValueError:
        count = 0
    if not topic or difficulty not in ("Easy", "Medium", "Hard") or not 1 <= count <= 10:
        message = "Enter a topic, choose a difficulty and request 1–10 questions."
        if wants_json_response():
            return jsonify(ok=False, error=message), 400
        flash(message, "error")
        return redirect(url_for("teacher_questions", exam_id=exam_id))
    try:
        gemini = GeminiService()
        generated = gemini.generate_questions(exam["subject"], topic, difficulty, count)
        for item in generated:
            options = item["options"]
            db.execute(
                "INSERT INTO ai_drafts(teacher_id,exam_id,topic,difficulty,question_text,option_a,option_b,option_c,option_d,correct_option,explanation,model) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (current_user_id(), exam_id, item["topic"], difficulty, item["question_text"],
                 *options, item["correct_option"], item["explanation"], gemini.last_model),
            )
        if wants_json_response():
            return jsonify(ok=True, count=len(generated), model=gemini.last_model,
                           redirect=url_for("teacher_drafts"))
        flash(f"Gemini generated {len(generated)} draft question(s). Review each before adding it to the exam.", "success")
        return redirect(url_for("teacher_drafts"))
    except AIServiceError as exc:
        app.logger.warning("Gemini question-generation request failed: %s", type(exc).__name__)
        if wants_json_response():
            return jsonify(ok=False, error=str(exc)), 502
        flash(str(exc), "error")
        return redirect(url_for("teacher_questions", exam_id=exam_id))


@app.route("/teacher/question/<int:question_id>/edit", methods=["GET", "POST"])
@login_required("TEACHER")
def edit_question(question_id):
    q = db.one("SELECT q.*,e.created_by,e.status AS exam_status FROM questions q JOIN exams e ON e.id=q.exam_id "
               "WHERE q.id=%s AND e.created_by=%s", (question_id, current_user_id()))
    if not q:
        abort(404)
    if not exam_is_editable(q["exam_id"]):
        flash("Questions can only be edited in an unused draft exam.", "error")
        return redirect(url_for("teacher_questions", exam_id=q["exam_id"]))
    if request.method == "POST":
        text = request.form.get("question_text", "").strip()
        options = [request.form.get(f"option_{letter.lower()}", "").strip() for letter in "ABCD"]
        correct = request.form.get("correct_option", "")
        topic = request.form.get("topic", "General").strip()[:100] or "General"
        explanation = request.form.get("explanation", "").strip()
        try:
            marks = int(request.form.get("marks", "1"))
        except ValueError:
            marks = 0
        if not text or any(not x for x in options) or correct not in "ABCD" or not 1 <= marks <= 100:
            flash("Complete all required fields and choose valid marks.", "error")
        elif len({x.casefold() for x in options}) != 4:
            flash("The four answer options must be different.", "error")
        else:
            db.execute("UPDATE questions SET question_text=%s,option_a=%s,option_b=%s,option_c=%s,option_d=%s,"
                       "correct_option=%s,topic=%s,marks=%s,explanation=%s WHERE id=%s",
                       (text, *options, correct, topic, marks, explanation or None, question_id))
            recalc_exam_total(q["exam_id"])
            flash("Question updated.", "success")
            return redirect(url_for("teacher_questions", exam_id=q["exam_id"]))
    return render_template("teacher_question_edit.html", q=q)


@app.post("/teacher/question/<int:question_id>/delete")
@login_required("TEACHER")
def delete_question(question_id):
    q = db.one("SELECT q.id,q.exam_id,e.created_by FROM questions q JOIN exams e ON e.id=q.exam_id "
               "WHERE q.id=%s AND e.created_by=%s", (question_id, current_user_id()))
    if not q:
        abort(404)
    if not exam_is_editable(q["exam_id"]):
        flash("Questions can only be deleted from an unused draft exam.", "error")
        return redirect(url_for("teacher_questions", exam_id=q["exam_id"]))
    db.execute("DELETE FROM questions WHERE id=%s", (question_id,))
    recalc_exam_total(q["exam_id"])
    flash("Question deleted.", "success")
    return redirect(url_for("teacher_questions", exam_id=q["exam_id"]))


@app.get("/teacher/drafts")
@login_required("TEACHER")
def teacher_drafts():
    drafts = db.all_rows(
        "SELECT d.*,e.title AS exam_title FROM ai_drafts d JOIN exams e ON e.id=d.exam_id "
        "WHERE d.teacher_id=%s AND d.status='PENDING' ORDER BY d.created_at DESC", (current_user_id(),)
    )
    return render_template("teacher_drafts.html", drafts=drafts)


@app.post("/teacher/draft/<int:draft_id>/<decision>")
@login_required("TEACHER")
def review_draft(draft_id, decision):
    if decision not in ("approve", "reject"):
        abort(400)
    draft = db.one("SELECT d.*,e.status AS exam_status FROM ai_drafts d JOIN exams e ON e.id=d.exam_id "
                   "WHERE d.id=%s AND d.teacher_id=%s AND e.created_by=%s",
                   (draft_id, current_user_id(), current_user_id()))
    if not draft or draft["status"] != "PENDING":
        abort(404)
    if decision == "approve":
        if draft["exam_status"] != "DRAFT" or not exam_is_editable(draft["exam_id"]):
            flash("This draft cannot be approved after the exam is published or attempted.", "error")
            return redirect(url_for("teacher_drafts"))
        db.execute(
            "INSERT INTO questions(exam_id,question_text,option_a,option_b,option_c,option_d,correct_option,topic,marks,explanation,source) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1,%s,'AI')",
            (draft["exam_id"], draft["question_text"], draft["option_a"], draft["option_b"],
             draft["option_c"], draft["option_d"], draft["correct_option"], draft["topic"], draft["explanation"]),
        )
        db.execute("UPDATE ai_drafts SET status='APPROVED' WHERE id=%s", (draft_id,))
        recalc_exam_total(draft["exam_id"])
        flash("Approved question added to the exam. Please verify its answer key before publishing.", "success")
    else:
        db.execute("UPDATE ai_drafts SET status='REJECTED' WHERE id=%s", (draft_id,))
        flash("Draft rejected; it was not added to the student paper.", "success")
    return redirect(url_for("teacher_drafts"))


@app.get("/teacher/exam/<int:exam_id>/analytics")
@login_required("TEACHER")
def teacher_analytics(exam_id):
    exam = owned_exam(exam_id)
    stats = db.one(
        "SELECT COUNT(*) AS attempts, COALESCE(AVG(percentage),0) AS average, "
        "COALESCE(MAX(percentage),0) AS highest, COALESCE(MIN(percentage),0) AS lowest "
        "FROM attempts WHERE exam_id=%s AND status IN ('SUBMITTED','AUTO_SUBMITTED')", (exam_id,)
    )
    students = db.all_rows(
        "SELECT u.full_name,u.roll_no,a.score,a.total_marks,a.percentage,a.status,a.submitted_at "
        "FROM attempts a JOIN users u ON u.id=a.student_id WHERE a.exam_id=%s "
        "AND a.status IN ('SUBMITTED','AUTO_SUBMITTED') ORDER BY a.percentage DESC,u.full_name", (exam_id,)
    )
    topics = db.all_rows(
        "SELECT q.topic,COUNT(a.id) AS responses, "
        "ROUND(100*SUM(CASE WHEN a.selected_option=q.correct_option THEN 1 ELSE 0 END)/NULLIF(COUNT(a.id),0),1) AS accuracy "
        "FROM questions q LEFT JOIN attempts t ON t.exam_id=q.exam_id AND t.status IN ('SUBMITTED','AUTO_SUBMITTED') "
        "LEFT JOIN answers a ON a.question_id=q.id AND a.attempt_id=t.id "
        "WHERE q.exam_id=%s GROUP BY q.topic ORDER BY accuracy ASC", (exam_id,)
    )
    return render_template("teacher_analytics.html", exam=exam, stats=stats, students=students, topics=topics)


# ----------------------------------------------- student
@app.get("/student")
@login_required("STUDENT")
def student_dashboard():
    uid = current_user_id()
    exams = db.all_rows(
        "SELECT e.*,u.full_name AS teacher_name,(SELECT COUNT(*) FROM questions q WHERE q.exam_id=e.id) AS question_count, "
        "a.id AS attempt_id,a.status AS attempt_status,a.percentage AS attempt_percentage "
        "FROM exams e JOIN users u ON u.id=e.created_by LEFT JOIN attempts a ON a.exam_id=e.id AND a.student_id=%s "
        "WHERE e.status='PUBLISHED' ORDER BY e.created_at DESC", (uid,)
    )
    history = db.all_rows(
        "SELECT a.*,e.title,e.subject FROM attempts a JOIN exams e ON e.id=a.exam_id "
        "WHERE a.student_id=%s AND a.status<>'IN_PROGRESS' ORDER BY a.submitted_at DESC LIMIT 8", (uid,)
    )
    return render_template("student_dashboard.html", exams=exams, history=history)


@app.post("/student/start/<int:exam_id>")
@login_required("STUDENT")
def start_exam(exam_id):
    exam = db.one("SELECT * FROM exams WHERE id=%s AND status='PUBLISHED'", (exam_id,))
    if not exam:
        abort(404)
    existing = db.one("SELECT id,status,deadline_at FROM attempts WHERE exam_id=%s AND student_id=%s",
                      (exam_id, current_user_id()))
    if existing:
        if existing["status"] == "IN_PROGRESS":
            if datetime.now() >= existing["deadline_at"]:
                finalize_attempt(existing["id"], force=True)
                return redirect(url_for("student_result", attempt_id=existing["id"]))
            return redirect(url_for("student_exam", attempt_id=existing["id"]))
        flash("This exam has already been attempted. You can review the result.", "info")
        return redirect(url_for("student_result", attempt_id=existing["id"]))
    qs = db.all_rows("SELECT id FROM questions WHERE exam_id=%s", (exam_id,))
    if not qs:
        flash("This exam does not have questions yet.", "warning")
        return redirect(url_for("student_dashboard"))
    ids = [q["id"] for q in qs]
    if exam["randomize"]:
        import random
        random.shuffle(ids)
    now = datetime.now()
    deadline = now + timedelta(minutes=exam["duration_minutes"])
    try:
        attempt_id, _ = db.execute(
            "INSERT INTO attempts(exam_id,student_id,started_at,deadline_at,total_marks,question_order) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (exam_id, current_user_id(), now, deadline, exam["total_marks"], json.dumps(ids)),
        )
    except Exception as exc:
        if "Duplicate" in str(exc):
            return redirect(url_for("student_dashboard"))
        raise
    for qid in ids:
        db.execute("INSERT INTO answers(attempt_id,question_id) VALUES(%s,%s)", (attempt_id, qid))
    return redirect(url_for("student_exam", attempt_id=attempt_id))


@app.get("/student/attempt/<int:attempt_id>")
@login_required("STUDENT")
def student_exam(attempt_id):
    attempt = owned_attempt(attempt_id)
    if attempt["status"] != "IN_PROGRESS":
        return redirect(url_for("student_result", attempt_id=attempt_id))
    if datetime.now() >= attempt["deadline_at"]:
        finalize_attempt(attempt_id, force=True)
        flash("Time expired. The exam was auto-submitted.", "warning")
        return redirect(url_for("student_result", attempt_id=attempt_id))
    ids = attempt["question_order"]
    if isinstance(ids, str):
        ids = json.loads(ids)
    marks = ",".join(["%s"] * len(ids))
    qs = db.all_rows(
        "SELECT q.id,q.question_text,q.option_a,q.option_b,q.option_c,q.option_d,q.topic,q.marks,a.selected_option "
        "FROM questions q JOIN answers a ON a.question_id=q.id AND a.attempt_id=%s "
        f"WHERE q.id IN ({marks})", (attempt_id, *ids)
    )
    by_id = {q["id"]: q for q in qs}
    questions = [by_id[i] for i in ids if i in by_id]
    remaining = max(0, int((attempt["deadline_at"] - datetime.now()).total_seconds()))
    return render_template("student_exam.html", attempt=attempt, questions=questions, remaining=remaining)


@app.post("/student/attempt/<int:attempt_id>/answer")
@login_required("STUDENT")
def save_answer(attempt_id):
    attempt = owned_attempt(attempt_id)
    if attempt["status"] != "IN_PROGRESS" or datetime.now() >= attempt["deadline_at"]:
        if attempt["status"] == "IN_PROGRESS":
            finalize_attempt(attempt_id, force=True)
        return jsonify(ok=False, error="The exam is closed."), 409
    payload = request.get_json(silent=True) or request.form
    try:
        question_id = int(payload.get("question_id", 0))
    except (ValueError, TypeError):
        return jsonify(ok=False, error="Invalid question."), 400
    selected = str(payload.get("selected_option", "")).upper() or None
    if selected not in (None, "A", "B", "C", "D"):
        return jsonify(ok=False, error="Choose one of the four options."), 400
    row = db.one("SELECT id FROM answers WHERE attempt_id=%s AND question_id=%s", (attempt_id, question_id))
    if not row:
        abort(404)
    db.execute("UPDATE answers SET selected_option=%s WHERE attempt_id=%s AND question_id=%s",
               (selected, attempt_id, question_id))
    return jsonify(ok=True, saved=True)


@app.post("/student/attempt/<int:attempt_id>/submit")
@login_required("STUDENT")
def submit_exam(attempt_id):
    attempt = owned_attempt(attempt_id)
    if attempt["status"] == "IN_PROGRESS":
        expired = datetime.now() >= attempt["deadline_at"]
        finalize_attempt(attempt_id, force=True)
        flash("Time expired; the paper was submitted automatically." if expired else "Your exam was submitted.",
              "warning" if expired else "success")
    return redirect(url_for("student_result", attempt_id=attempt_id))


@app.get("/student/result/<int:attempt_id>")
@login_required("STUDENT")
def student_result(attempt_id):
    attempt = owned_attempt(attempt_id)
    if attempt["status"] == "IN_PROGRESS":
        return redirect(url_for("student_exam", attempt_id=attempt_id))
    reviews = result_reviews(attempt)
    topics_map = {}
    for r in reviews:
        topic = r["topic"] or "General"
        bucket = topics_map.setdefault(topic, [0, 0])
        bucket[1] += 1
        bucket[0] += int(r["is_correct"])
    topics = [{"topic": k, "correct": v[0], "total": v[1],
               "accuracy": round(v[0] * 100 / v[1]) if v[1] else 0}
              for k, v in topics_map.items()]
    feedback_row = db.one("SELECT content,model,generated_at FROM ai_feedback WHERE attempt_id=%s", (attempt_id,))
    feedback = feedback_row["content"] if feedback_row else None
    if isinstance(feedback, str):
        feedback = json.loads(feedback)
    return render_template("student_result.html", attempt=attempt, reviews=reviews, topics=topics,
                           feedback=feedback, feedback_model=feedback_row["model"] if feedback_row else None,
                           ai_configured=GeminiService().configured)


@app.post("/student/result/<int:attempt_id>/ai-feedback")
@login_required("STUDENT")
def ai_feedback(attempt_id):
    attempt = owned_attempt(attempt_id)
    if attempt["status"] == "IN_PROGRESS":
        message = "Submit the exam before requesting feedback."
        if wants_json_response():
            return jsonify(ok=False, error=message), 409
        abort(400, description=message)
    cached = db.one("SELECT content,model FROM ai_feedback WHERE attempt_id=%s", (attempt_id,))
    if cached:
        if wants_json_response():
            return jsonify(ok=True, cached=True, model=cached["model"],
                           redirect=url_for("student_result", attempt_id=attempt_id))
        flash("Your saved Gemini feedback is already available below.", "info")
        return redirect(url_for("student_result", attempt_id=attempt_id))
    try:
        exam = db.one("SELECT title,subject FROM exams WHERE id=%s", (attempt["exam_id"],))
        reviews = result_reviews(attempt)
        gemini = GeminiService()
        feedback = gemini.generate_feedback(exam, attempt, reviews)
        db.execute("INSERT INTO ai_feedback(attempt_id,content,model) VALUES(%s,%s,%s)",
                   (attempt_id, json.dumps(feedback, ensure_ascii=False), gemini.last_model))
        if wants_json_response():
            return jsonify(ok=True, cached=False, model=gemini.last_model,
                           redirect=url_for("student_result", attempt_id=attempt_id))
        flash("Gemini prepared your learning report from your actual answers.", "success")
    except AIServiceError as exc:
        app.logger.warning("Gemini student-feedback request failed: %s", type(exc).__name__)
        if wants_json_response():
            return jsonify(ok=False, error=str(exc)), 502
        flash(str(exc), "error")
    return redirect(url_for("student_result", attempt_id=attempt_id))


# ----------------------------------------------- errors
@app.errorhandler(DatabaseUnavailable)
def database_unavailable(error):
    app.logger.error("Database connection unavailable: %s", error)
    return render_template("error.html", code=503,
                           message="The MySQL database is not reachable. Start MySQL and check the database setup."), 503


@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, message=getattr(error, "description", "Bad request.")), 400


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="You do not have permission to open this page."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="That page or record could not be found."), 404


@app.errorhandler(500)
def internal_error(error):
    app.logger.exception("Unhandled application error: %s", error)
    return render_template("error.html", code=500, message="Something went wrong. Check the terminal output for details."), 500


class RedactingPreviewRequestHandler(WSGIRequestHandler):
    """Keep short-lived bearer tokens out of the disposable preview access log."""
    def log_request(self, code="-", size="-"):
        original_path = getattr(self, "path", None)
        if config.PREVIEW_TOKEN_AUTH and original_path and "preview_token=" in original_path:
            self.path = re.sub(r"([?&]preview_token=)[^&\s]+", r"\1[redacted]", original_path)
        try:
            return super().log_request(code, size)
        finally:
            if original_path is not None:
                self.path = original_path


if __name__ == "__main__":
    run_options = {
        "host": "0.0.0.0",
        "port": int(__import__("os").getenv("PORT", "5000")),
        "debug": False,
    }
    if config.PREVIEW_TOKEN_AUTH:
        run_options["request_handler"] = RedactingPreviewRequestHandler
    app.run(**run_options)
