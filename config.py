"""Environment-based configuration for ExamAI Python Edition."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv is listed in requirements; environment variables still work without it.
    pass

APP_NAME = "ExamAI — AI-Powered Online Examination System"
SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-only-change-this-before-deployment")
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "examai_app"),
    "password": os.getenv("DB_PASSWORD", "examai_app_2026"),
    "database": os.getenv("DB_NAME", "examai_python"),
    "charset": "utf8mb4",
    "cursorclass": None,  # replaced by db.py with DictCursor
    "autocommit": True,
    "connect_timeout": 5,
}
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
GEMINI_FALLBACK_MODELS = tuple(
    model.strip() for model in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite,gemini-flash-lite-latest").split(",") if model.strip()
)

# Use a project-specific cookie name to avoid stale/generic `session` cookies.
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "examai_python_session").strip()
# Local HTTP defaults remain browser-friendly. HTTPS previews can opt into
# cross-site, partitioned session cookies with the environment variables below.
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax").strip()
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
SESSION_COOKIE_PARTITIONED = os.getenv("SESSION_COOKIE_PARTITIONED", "false").strip().lower() in {"1", "true", "yes", "on"}
# Disposable hosted-preview mode uses a short-lived signed URL token because some
# embedded browsers disable all cookies. Leave disabled for normal/local use.
PREVIEW_TOKEN_AUTH = os.getenv("EXAMAI_PREVIEW_TOKEN_AUTH", "false").strip().lower() in {"1", "true", "yes", "on"}
