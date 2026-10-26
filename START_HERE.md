# Run the ExamAI Python project on your computer

This is the **same Online Examination and Assessment System** from the earlier ExamAI project, implemented with Python for your Python course and retaining the AI features for AIP. It is separate from the Result System. It uses your existing **MySQL Server 8.0.46** and Python 3; you do not need XAMPP or another server.

## What is in the ZIP

`ExamAI_Python.zip` contains the Python/Flask app, MySQL setup scripts, demo data, templates, screenshots, tests and the combined Python + AIP report.

## First-time setup (Windows, MySQL Workbench)

### 1. Extract the project

Download `ExamAI_Python.zip`, right-click it → **Extract All…** → choose a folder you can find, such as Desktop. Open the extracted **ExamAI_Python** folder.

### 2. Start the MySQL Server

Your Installer showed **MySQL Server 8.0.46**, so it is already installed. Press `Win + R`, type `services.msc`, press Enter, find **MySQL80**, and check that its status is **Running**. If it is stopped, right-click it → **Start**.

Open MySQL Workbench and connect to **Local instance MySQL80** as root/admin.

### 3. Run the two SQL setup files

Run these **in this order** in Workbench:

1. **File → Open SQL Script** → `01_schema.sql` → press **Ctrl + Shift + Enter**. This creates the `examai_python` database and tables.
2. **File → Open SQL Script** → `02_create_db_user.sql` → press **Ctrl + Shift + Enter**. This creates the limited app account.

Do **not** run the old Java project's SQL file for this Python edition. These scripts are safe to rerun and do not drop other databases.

### 4. Install the Python packages and load the demo data

In File Explorer, open the `ExamAI_Python` project folder. Click the address bar, type `cmd`, and press Enter. In the black Command Prompt, run:

```bat
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r requirements.txt
py seed_demo.py
```

The seed step should print that it prepared **1 teacher, 4 students, 4 exams, 15 questions and 3 sample attempts**. These are ordinary demo records, not AI-generated questions.

### 5. Start the website

In the same Command Prompt:

```bat
py app.py
```

Leave the window open and visit **http://localhost:5000** in your browser. To stop the website, press `Ctrl + C` in the Command Prompt.

## Demo logins

| Role | Email | Password |
|---|---|---|
| Teacher | `teacher@examai.edu` | `Teacher@123` |
| Student (sample result) | `student@examai.edu` | `Student@123` |
| Student (ready to take an exam) | `newstudent@examai.edu` | `Student@123` |

The teacher can create a draft, add questions, edit/delete questions before any attempt, and publish it. The student can start a timed paper, answer questions, submit, and view the result and topic breakdown.

## Turn on real Gemini AI features

Gemini question drafting and feedback need internet access and a valid API key. The hosted preview was verified with real Gemini requests: one question draft was saved in the teacher review queue, and student feedback was saved for a submitted demo attempt. The ZIP contains **no API key**. To enable AI on your own computer, add your own private key locally:

1. In the Command Prompt, run `copy .env.example .env`.
2. Run `notepad .env`.
3. Replace the placeholder on the `FLASK_SECRET_KEY=` line with a long random value. Add your key after `GEMINI_API_KEY=`; do not add quotes. Save and close Notepad.
4. Start or restart the server with `py app.py`.

`.env` is ignored by Git and is **not** inside the ZIP. Never publish it or paste the key into a report, screenshot, template, or GitHub repository. The default model is Gemini 3.8 Flash, with Gemini Flash Lite fallbacks for high demand/timeouts; the hosted verification used `gemini-3.1-flash-lite`. If the key previously pasted in chat is still in use, rotate it and use the replacement only in your local `.env`.

Once configured, the teacher's Gemini drafts stay in the review queue until approved. The AI feedback is based on the student's actual wrong answers. Python—not Gemini—calculates the marks.

## Troubleshooting

| Message | What to do |
|---|---|
| `Can't connect to MySQL` | Start **MySQL80** in `services.msc` and retry. |
| `Access denied for user 'examai_app'` | Re-run `02_create_db_user.sql` in Workbench. |
| `Unknown database 'examai_python'` | Run `01_schema.sql` first. |
| `ModuleNotFoundError` | Activate `.venv`, then run `py -m pip install -r requirements.txt`. |
| Gemini says key is missing | Add your key locally to `.env` as described above; the API key is not embedded in the ZIP. |
| Port 5000 is already in use | Stop the other Flask app first, or set `PORT=5001` in the Command Prompt before running `py app.py`. |

## Tests

After setup, run the unit tests with:

```bat
py -m unittest discover -s tests -v
```

For a database-backed teacher/student workflow test, run `py tools\smoke_test_web.py`. It creates and deletes one temporary exam and attempt.
