import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'placement.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Default admin credentials (override via env in production)
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@placement.local")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

    JWT_ALGORITHM = "HS256"
    JWT_EXPIRATION_HOURS = int(os.environ.get("JWT_EXPIRATION_HOURS", 24))

    # --- Milestone 7: Celery + Redis background jobs ---
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", f"{REDIS_URL}/0")
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", f"{REDIS_URL}/1")
    # Set to 1 to run tasks synchronously in-process (testing without Redis).
    CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "0") == "1"

    # Email delivery (Gmail SMTP). Use a Gmail *App Password*, never the account
    # password. If MAIL_USERNAME/MAIL_PASSWORD are unset, mail_utils logs the
    # message to the console instead of sending, so jobs never crash.
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") == "1"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER", MAIL_USERNAME or "noreply@placement.local"
    )

    # Generated artefacts (CSV exports, monthly reports)
    EXPORT_DIR = os.path.join(BASE_DIR, "instance", "exports")
    REPORT_DIR = os.path.join(BASE_DIR, "instance", "reports")

    # Interview reminders: notify students whose interview is within N hours.
    INTERVIEW_REMINDER_LOOKAHEAD_HOURS = int(
        os.environ.get("INTERVIEW_REMINDER_LOOKAHEAD_HOURS", 24)
    )
