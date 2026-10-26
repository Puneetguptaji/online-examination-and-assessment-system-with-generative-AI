"""Capture real pages from the local running Flask app for the report."""
from pathlib import Path
import os
from playwright.sync_api import sync_playwright

BASE = os.getenv("EXAMAI_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
OUT = Path(__file__).resolve().parents[1] / "screenshots"
OUT.mkdir(exist_ok=True)


def login(page, email, password):
    page.goto(BASE + "/login", wait_until="networkidle")
    page.get_by_label("Email address").fill(email)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_load_state("networkidle")


def shot(page, name):
    page.screenshot(path=str(OUT / name), full_page=True, animations="disabled")
    print("captured", name, page.url)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1365, "height": 960}, device_scale_factor=1.35)
    page.goto(BASE + "/login", wait_until="networkidle")
    shot(page, "01-login.png")

    login(page, "teacher@examai.edu", "Teacher@123")
    page.goto(BASE + "/teacher", wait_until="networkidle")
    shot(page, "02-teacher-dashboard.png")
    page.goto(BASE + "/teacher/exams", wait_until="networkidle")
    shot(page, "03-teacher-exams.png")
    page.goto(BASE + "/teacher/exam/4/questions", wait_until="networkidle")
    shot(page, "04-question-bank-and-ai.png")
    page.goto(BASE + "/teacher/drafts", wait_until="networkidle")
    shot(page, "05-ai-review-queue.png")
    page.goto(BASE + "/teacher/exam/1/analytics", wait_until="networkidle")
    shot(page, "06-teacher-analytics.png")

    # Use the student demo account that has no completed attempt to show the full flow.
    page.context.clear_cookies()
    login(page, "newstudent@examai.edu", "Student@123")
    page.goto(BASE + "/student", wait_until="networkidle")
    shot(page, "07-student-dashboard.png")
    page.locator('form[action="/student/start/1"] button[type="submit"]').click()
    page.wait_for_url("**/student/attempt/**")
    page.wait_for_load_state("networkidle")
    first_q = page.locator(".live-question").first
    first_q.locator('input[type="radio"]').first.check()
    page.wait_for_timeout(500)
    shot(page, "08-exam-in-progress.png")
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator(".submit-exam-form button[type='submit']").click()
    page.wait_for_url("**/student/result/**")
    page.wait_for_load_state("networkidle")
    shot(page, "09-result-and-ai-state.png")
    browser.close()
