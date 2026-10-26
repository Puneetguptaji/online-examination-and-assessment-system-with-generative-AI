"""Load a small idempotent classroom dataset for a first-run demo.

The seeded attempts and questions are ordinary demo data, not AI output. AI drafts
are created only after a real Gemini API call and remain subject to teacher review.
"""
from datetime import datetime, timedelta
import json

import pymysql
from pymysql.cursors import DictCursor
from werkzeug.security import generate_password_hash

from config import DB_CONFIG


def connect():
    cfg = dict(DB_CONFIG)
    cfg["cursorclass"] = DictCursor
    cfg["autocommit"] = True
    return pymysql.connect(**cfg)


PEOPLE = [
    ("Maya Kapoor", "teacher@examai.edu", "Teacher@123", "TEACHER", None),
    ("Demo Student", "student@examai.edu", "Student@123", "STUDENT", "26MCI10246"),
    ("Practice Student", "newstudent@examai.edu", "Student@123", "STUDENT", "26MCI10247"),
    ("Aisha Verma", "aisha@examai.edu", "Student@123", "STUDENT", "26MCI10248"),
    ("Ravi Mehta", "ravi@examai.edu", "Student@123", "STUDENT", "26MCI10249"),
]

EXAMS = [
    {
        "title": "Python Fundamentals — Quiz 1", "subject": "Python Programming",
        "description": "Variables, functions, collections and core Python syntax.", "duration": 15,
        "status": "PUBLISHED", "questions": [
            ("What does len([3, 5, 7]) return?", ["2", "3", "4", "5"], "B", "Lists", "The list contains three elements, so len returns 3."),
            ("Which keyword is used to define a function in Python?", ["def", "func", "function", "lambda"], "A", "Functions", "The def keyword begins a function definition."),
            ("Which built-in collection is immutable?", ["list", "dictionary", "set", "tuple"], "D", "Collections", "A tuple cannot be modified after it is created."),
            ("What values are produced by range(3)?", ["1, 2, 3", "0, 1, 2", "0, 1, 2, 3", "3 only"], "B", "Iteration", "range(3) starts at zero and stops before three."),
            ("Which operator tests whether two values are equal?", ["=", "==", "!=", "=>"], "B", "Operators", "The equality comparison operator is ==; one = assigns a value."),
        ]
    },
    {
        "title": "Database Essentials", "subject": "Database Management",
        "description": "A short test on relational databases and SQL basics.", "duration": 12,
        "status": "PUBLISHED", "questions": [
            ("Which SQL statement creates a new table?", ["SELECT", "INSERT", "CREATE TABLE", "UPDATE"], "C", "SQL DDL", "CREATE TABLE defines a new table and its columns."),
            ("What is the main purpose of a primary key?", ["Allow duplicate rows", "Uniquely identify a row", "Sort every query", "Encrypt the table"], "B", "Keys", "A primary key uniquely identifies each row in a table."),
            ("Which clause filters rows before they are returned?", ["WHERE", "ORDER BY", "GROUP BY", "LIMIT"], "A", "SQL Queries", "WHERE applies a condition to rows in a query."),
            ("A foreign key is used to…", ["Compress data", "Link related tables", "Rename a column", "Remove duplicates"], "B", "Relationships", "A foreign key references a key in another table to maintain a relationship."),
            ("What does COUNT(*) return?", ["Number of columns", "Number of rows", "Largest value", "Average value"], "B", "Aggregate Functions", "COUNT(*) counts the rows in the result set."),
        ]
    },
    {
        "title": "AI and Machine Learning Basics", "subject": "Artificial Intelligence",
        "description": "Core concepts in supervised learning, model evaluation and language technology.", "duration": 15,
        "status": "PUBLISHED", "questions": [
            ("In supervised learning, training examples include…", ["Only input features", "Inputs and target labels", "Only model weights", "No data"], "B", "Supervised Learning", "Supervised examples pair inputs with known target labels."),
            ("What is overfitting?", ["A model performs well on new data only", "A model learns training details too closely", "The dataset has no labels", "The model is not trained"], "B", "Model Evaluation", "Overfitting occurs when a model memorises training patterns and generalises poorly."),
            ("Which set is used to estimate performance during model development?", ["Validation set", "Source code", "Target variable", "Output layer"], "A", "Model Evaluation", "Validation data helps compare model choices before final testing."),
            ("A confusion matrix summarizes…", ["Storage capacity", "Classification predictions and actual labels", "Training time only", "Database indexes"], "B", "Classification", "A confusion matrix counts true and false predictions by class."),
            ("Natural language processing focuses on…", ["Text and human language", "Computer hardware", "Network cables", "Relational keys"], "A", "NLP", "NLP covers computational methods for understanding and generating language."),
        ]
    },
    {
        "title": "Python Functions — Practice Paper", "subject": "Python Programming",
        "description": "Draft paper. Add questions and publish it when ready.", "duration": 10,
        "status": "DRAFT", "questions": []
    },
]


def main():
    conn = connect()
    try:
        with conn.cursor() as cur:
            for name, email, password, role, roll in PEOPLE:
                cur.execute(
                    "INSERT INTO users(full_name,email,password_hash,role,roll_no) VALUES(%s,%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE full_name=VALUES(full_name),password_hash=VALUES(password_hash),role=VALUES(role),roll_no=VALUES(roll_no)",
                    (name, email, generate_password_hash(password), role, roll),
                )
            cur.execute("SELECT id FROM users WHERE email=%s", (PEOPLE[0][1],))
            teacher_id = cur.fetchone()["id"]
            exam_ids = {}
            for exam in EXAMS:
                cur.execute("SELECT id FROM exams WHERE title=%s AND created_by=%s", (exam["title"], teacher_id))
                row = cur.fetchone()
                if row:
                    exam_id = row["id"]
                else:
                    cur.execute(
                        "INSERT INTO exams(title,subject,description,duration_minutes,status,created_by) VALUES(%s,%s,%s,%s,%s,%s)",
                        (exam["title"], exam["subject"], exam["description"], exam["duration"], exam["status"], teacher_id),
                    )
                    exam_id = cur.lastrowid
                exam_ids[exam["title"]] = exam_id
                cur.execute("SELECT COUNT(*) AS n FROM questions WHERE exam_id=%s", (exam_id,))
                if cur.fetchone()["n"] == 0 and exam["questions"]:
                    for text, options, correct, topic, explanation in exam["questions"]:
                        cur.execute(
                            "INSERT INTO questions(exam_id,question_text,option_a,option_b,option_c,option_d,correct_option,topic,marks,explanation,source) "
                            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1,%s,'MANUAL')",
                            (exam_id, text, *options, correct, topic, explanation),
                        )
                cur.execute("UPDATE exams SET total_marks=(SELECT COALESCE(SUM(marks),0) FROM questions WHERE exam_id=%s) WHERE id=%s",
                            (exam_id, exam_id))

            # A few ordinary completed attempts power the example analytics/result pages.
            exam_id = exam_ids[EXAMS[0]["title"]]
            cur.execute("SELECT id FROM users WHERE email=%s", ("student@examai.edu",))
            demo_student = cur.fetchone()["id"]
            cur.execute("SELECT id FROM users WHERE email=%s", ("aisha@examai.edu",))
            aisha = cur.fetchone()["id"]
            cur.execute("SELECT id FROM users WHERE email=%s", ("ravi@examai.edu",))
            ravi = cur.fetchone()["id"]
            cur.execute("SELECT id,correct_option,marks FROM questions WHERE exam_id=%s ORDER BY id", (exam_id,))
            qrows = cur.fetchall()
            if len(qrows) >= 5:
                demo_patterns = [
                    (demo_student, ["B", "A", "D", "A", "B"], 0),
                    (aisha, ["B", "A", "D", "B", "B"], 1),
                    (ravi, ["A", "A", "D", "B", "C"], 2),
                ]
                for student_id, selected, days_ago in demo_patterns:
                    cur.execute("SELECT id FROM attempts WHERE exam_id=%s AND student_id=%s", (exam_id, student_id))
                    if cur.fetchone():
                        continue
                    now = datetime.now() - timedelta(days=days_ago + 1)
                    deadline = now + timedelta(minutes=15)
                    order = [q["id"] for q in qrows]
                    total = sum(int(q["marks"]) for q in qrows)
                    score = sum(int(q["marks"]) for q, choice in zip(qrows, selected) if q["correct_option"] == choice)
                    pct = round(score * 100 / total, 2) if total else 0
                    cur.execute(
                        "INSERT INTO attempts(exam_id,student_id,started_at,deadline_at,submitted_at,score,total_marks,percentage,status,question_order) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'SUBMITTED',%s)",
                        (exam_id, student_id, now, deadline, deadline, score, total, pct, json.dumps(order)),
                    )
                    attempt_id = cur.lastrowid
                    for q, choice in zip(qrows, selected):
                        cur.execute("INSERT INTO answers(attempt_id,question_id,selected_option,is_correct) VALUES(%s,%s,%s,%s)",
                                    (attempt_id, q["id"], choice, choice == q["correct_option"]))
        print("Demo data ready: 1 teacher, 4 students, 4 exams, 15 questions, 3 sample attempts.")
        print("AI draft queue remains empty until a real Gemini request is made.")
        print("Teacher: teacher@examai.edu / Teacher@123")
        print("Student: student@examai.edu / Student@123")
        print("Practice student (no completed attempt): newstudent@examai.edu / Student@123")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
