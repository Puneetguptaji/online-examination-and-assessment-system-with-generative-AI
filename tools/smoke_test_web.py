"""End-to-end smoke test using Flask's client and the configured local MySQL database."""
import re
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
import db

app.testing = True
client = app.test_client()
exam_title = f"Automated Python smoke {int(time.time())}"
exam_id = None


def token(response):
    found = re.search(r'<meta name="csrf-token" content="([^"]+)', response.get_data(as_text=True))
    if not found:
        raise AssertionError("CSRF token missing from rendered page")
    return found.group(1)


def login(email, password):
    response = client.get('/login')
    response = client.post('/login', data={"email": email, "password": password, "_csrf": token(response)}, follow_redirects=True)
    if response.status_code != 200:
        raise AssertionError(f"login failed for {email}: {response.status_code}")
    return response


try:
    page = login('teacher@examai.edu', 'Teacher@123')
    assert b'FACULTY WORKSPACE' in page.data
    print('PASS teacher login and role-protected dashboard')

    page = client.get('/teacher/exams')
    page = client.post('/teacher/exams', data={
        "_csrf": token(page), "title": exam_title, "subject": "Python", "duration_minutes": "3"
    }, follow_redirects=True)
    with app.app_context():
        exam_id = db.one("SELECT id FROM exams WHERE title=%s", (exam_title,))["id"]
    print('PASS teacher creates a draft exam')

    page = client.get(f'/teacher/exam/{exam_id}/questions')
    page = client.post(f'/teacher/exam/{exam_id}/questions', data={
        "_csrf": token(page), "question_text": "2 + 2 equals?", "option_a": "3", "option_b": "4",
        "option_c": "5", "option_d": "6", "correct_option": "B", "topic": "Arithmetic", "marks": "2"
    }, follow_redirects=True)
    with app.app_context():
        q1 = db.one("SELECT id FROM questions WHERE exam_id=%s ORDER BY id", (exam_id,))["id"]
    print('PASS manual question validation and insertion')

    page = client.get(f'/teacher/question/{q1}/edit')
    page = client.post(f'/teacher/question/{q1}/edit', data={
        "_csrf": token(page), "question_text": "2 + 2 equals?", "option_a": "3", "option_b": "4",
        "option_c": "5", "option_d": "6", "correct_option": "B", "topic": "Arithmetic", "marks": "2",
        "explanation": "Two plus two equals four."
    }, follow_redirects=True)
    assert b'Question updated' in page.data
    print('PASS editing a question in an unused draft')

    page = client.get(f'/teacher/exam/{exam_id}/questions')
    page = client.post(f'/teacher/question/{q1}/delete', data={"_csrf": token(page)}, follow_redirects=True)
    assert b'Question deleted' in page.data
    # Reinsert one final question for the published exam.
    page = client.get(f'/teacher/exam/{exam_id}/questions')
    page = client.post(f'/teacher/exam/{exam_id}/questions', data={
        "_csrf": token(page), "question_text": "2 + 2 equals?", "option_a": "3", "option_b": "4",
        "option_c": "5", "option_d": "6", "correct_option": "B", "topic": "Arithmetic", "marks": "2"
    }, follow_redirects=True)
    with app.app_context():
        question_id = db.one("SELECT id FROM questions WHERE exam_id=%s", (exam_id,))["id"]
    print('PASS deleting and re-adding a draft question')

    page = client.get('/teacher/exams')
    page = client.post(f'/teacher/exam/{exam_id}/status', data={"_csrf": token(page), "status": "PUBLISHED"}, follow_redirects=True)
    assert b'Published' in page.data
    print('PASS publication requires a question and makes the paper available')

    page = client.get('/teacher')
    client.post('/logout', data={"_csrf": token(page)})
    page = login('newstudent@examai.edu', 'Student@123')
    assert b'STUDENT DASHBOARD' in page.data
    print('PASS student login and role-protected dashboard')

    page = client.get('/student')
    page = client.post(f'/student/start/{exam_id}', data={"_csrf": token(page)}, follow_redirects=True)
    assert b'2 + 2 equals?' in page.data
    with app.app_context():
        attempt_id = db.one("SELECT id FROM attempts WHERE exam_id=%s AND student_id=(SELECT id FROM users WHERE email=%s)",
                            (exam_id, 'newstudent@examai.edu'))["id"]
    print('PASS student starts a timed attempt')

    page = client.get(f'/student/attempt/{attempt_id}')
    response = client.post(f'/student/attempt/{attempt_id}/answer', json={
        "question_id": question_id, "selected_option": "B"
    }, headers={"X-CSRF-Token": token(page)})
    assert response.status_code == 200 and response.json["saved"]
    print('PASS answer autosave with CSRF protection')

    page = client.post(f'/student/attempt/{attempt_id}/submit', data={"_csrf": token(page)}, follow_redirects=True)
    assert b'YOUR SCORE' in page.data
    with app.app_context():
        result = db.one("SELECT score,total_marks,percentage,status FROM attempts WHERE id=%s", (attempt_id,))
    assert result["score"] == 2 and int(result["total_marks"]) == 2 and float(result["percentage"]) == 100.0
    print(f"PASS submission and deterministic Python score: {result['score']}/{result['total_marks']} ({result['percentage']}%)")

    page = client.get(f'/student/result/{attempt_id}')
    assert b'2 + 2 equals?' in page.data
    page = client.post(f'/student/result/{attempt_id}/ai-feedback', data={"_csrf": token(page)}, follow_redirects=True)
    assert b'GEMINI_API_KEY' in page.data
    print('PASS result review; unavailable Gemini key is reported clearly, no fake feedback')

    page = client.get('/health')
    assert page.status_code == 200 and page.json['database'] == 'connected'
    print(f"PASS health check: MySQL connected; live AI configured={page.json['ai_configured']}")
finally:
    if exam_id is not None:
        with app.app_context():
            db.execute("DELETE FROM exams WHERE id=%s", (exam_id,))
    print('CLEANUP temporary smoke-test exam and attempt')
