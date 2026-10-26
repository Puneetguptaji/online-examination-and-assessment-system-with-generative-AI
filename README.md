# ExamAI — Python Edition

**One project for Python Programming and Advanced Internet Programming (AIP).**
This is the Python/Flask implementation of the ExamAI online examination and assessment system: teachers build papers, Gemini can draft questions and student learning feedback, and students take timed assessments with server-side scoring.

> This is the same ExamAI project concept as the earlier Java version, rewritten with Python as the main application language. It is not the Online Examination Result System. Its database is called `examai_python`, so it does not alter the older Java database (`examai`) or the Result System (`result_system`).

## What it does

### Teacher / faculty
- Sign in to a role-protected faculty area.
- Create exams as drafts, add/edit/delete manual questions, set durations and publish/close papers.
- Request 1–10 four-option questions from Google Gemini by subject, topic and difficulty.
- AI output is validated and stored in a **pending review queue**; it is not published until a teacher approves it.
- View attempts, class average, highest/lowest score and topic accuracy.

### Student
- Register as a student and see published assessments.
- Start one timed attempt per exam; the question order is frozen for that attempt.
- Answers autosave as choices are made; the countdown is visible and the server enforces the deadline.
- Receive a score calculated by Python from the stored answer key. Gemini never awards marks.
- Review each answer, see topic accuracy and optionally request a personalised Gemini study report grounded in actual incorrect answers.

## Stack
- Python 3.10+ · Flask · PyMySQL · Werkzeug password hashing
- MySQL Server 8.0+ (tested here on 8.0.46) · MySQL Workbench for SQL setup
- HTML · CSS · JavaScript · Google Gemini REST API (`generateContent`)

## Setup on Windows (MySQL Workbench + Python)

### 1. Start the MySQL server

Open **Services** (`Win + R` → `services.msc`) and ensure **MySQL80** is running. Open Workbench and connect to your local MySQL 8 server as `root` or an administrator.

### 2. Create the database tables

In Workbench, choose **File → Open SQL Script**, open `01_schema.sql`, then press **Ctrl + Shift + Enter** to execute the full script. This creates the separate `examai_python` database and its tables; it does **not** drop or change either of the older project databases.

### 3. Create the app database account

Open and run `02_create_db_user.sql` the same way. Expected final row: `ExamAI app database user ready`.

### 4. Install Python packages and load demo data

Open the project folder in File Explorer, type `cmd` in the address bar and press Enter. In the Command Prompt run:

```bat
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r requirements.txt
```

Optional local settings: copy `.env.example` to `.env`. The defaults match the SQL app account. Never commit `.env` to GitHub; `.gitignore` excludes it.

Load the demo data:

```bat
py seed_demo.py
```

It safely creates the example accounts, 4 exams and 15 hand-authored questions, plus a few ordinary sample attempts for analytics. It does **not** label sample content as Gemini output. It can be run again without creating duplicate exams or attempts.

### 5. Start the website

```bat
py app.py
```

Leave the Command Prompt window open, then visit **http://localhost:5000**. Press `Ctrl + C` to stop the server.

## Demo logins

| Role | Email | Password |
|---|---|---|
| Teacher | `teacher@examai.edu` | `Teacher@123` |
| Student with a sample result | `student@examai.edu` | `Student@123` |
| Student ready to take a paper | `newstudent@examai.edu` | `Student@123` |

Change demo passwords before using the app outside a classroom demonstration.

## Enable real Gemini features

The app sends real requests to Google's Gemini REST API only from the Python server. It uses `gemini-3.8-flash` by default and can retry with the configured Gemini Flash Lite fallback models after a high-demand response or timeout. All saved drafts and feedback come from actual API responses; the fallback never substitutes sample output. Change `GEMINI_MODEL` in `.env` if your API key does not have access to the default model.

1. Copy `.env.example` to `.env` if you have not already.
2. Add the Gemini key to the local `.env` file: `GEMINI_API_KEY=your_key_here`.
3. Stop and restart `py app.py`.

Do not put the key into a template, JavaScript file, screenshot, source-control repository or report. The app checks for a key; without one, it keeps the exam features working and shows a clear setup message. **It does not invent or simulate Gemini responses.** A live AI request requires an internet connection and a valid Google AI Studio API key.

## Tests

```bat
py -m unittest discover -s tests -v
```

Tests cover deterministic scoring, option validation, JSON response parsing, missing-key handling and a rate-limit response. The Gemini API call is exercised with a mocked HTTP response in the unit test; a real live API call must be verified with your private key.

For an optional database-backed web-flow test (the test creates and removes one temporary exam):

```bat
py tools\smoke_test_web.py
```

## Safety and design notes

- The app uses a new schema named `examai_python`; the supplied setup SQL contains no `DROP DATABASE` statement.
- Passwords are stored as Werkzeug-generated hashes, not plaintext.
- Student/teacher routes are role-protected; each student can access only their own attempt.
- Each answer save and submission is checked on the server; the browser never sends a score.
- Scoring is deterministic Python logic in `scoring.py`. Gemini cannot change the grade.
- AI question drafts are structurally validated, labeled by source, and require teacher approval before they enter a paper.
- AI feedback includes only question/answer context required to explain mistakes; student names and emails are not sent to Gemini.
- The sample database is for classroom demonstration, not production deployment. A production system also needs deployment-grade secrets, HTTPS, backups, monitoring and institutional privacy review.
- `EXAMAI_PREVIEW_TOKEN_AUTH` is a **sandbox-only** fallback for embedded previews that block cookies. It passes a short-lived signed token in URLs; keep it disabled for local and production deployments (the supplied `.env.example` sets it to `false`).

## Files

- `app.py` — Flask routes, authentication, teacher and student workflows.
- `ai_service.py` — Gemini request, JSON parsing, validation and readable errors.
- `scoring.py` — deterministic mark calculation.
- `01_schema.sql`, `02_create_db_user.sql` — MySQL setup scripts.
- `seed_demo.py` — idempotent classroom demo data.
- `templates/`, `static/` — offline-friendly HTML/CSS/JavaScript pages.
- `tests/` — Python unit tests.
- `docs/dfd.png` and `docs/dfd.svg` — project data-flow diagram.
- `report/` — combined Python + AIP mini-project report (DOCX/PDF).
