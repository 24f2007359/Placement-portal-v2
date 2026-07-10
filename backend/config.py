"""
===============================================================================
FILE : backend/config.py
WHAT : every knob in the app, in one class. read once at import time.
WHY  : `app.config.from_object(Config)` in app.py slurps all the UPPERCASE
       attrs. celery_app.py, tasks.py, mail_utils.py and export_routes.py also
       import Config directly.

THE PATTERN: os.environ.get("NAME", <sane default>)
  -> works out of the box with zero setup (good for the viva demo)
  -> but every single value can be overridden by an env var in prod

!! GOTCHA !! this class body runs ONCE, at import. so `export MAIL_USERNAME=...`
must happen BEFORE python starts. exporting it in a shell after the worker is
already running does nothing. restart the process.

WHO READS WHAT:
  SECRET_KEY / JWT_*   -> auth_utils.py (sign + verify the token)
  SQLALCHEMY_*         -> models.py via app.py
  CELERY_* / REDIS_URL -> celery_app.py
  MAIL_*               -> mail_utils.py
  EXPORT_DIR/REPORT_DIR-> tasks.py (writes) + export_routes.py (serves)
  ADMIN_EMAIL/PASSWORD -> seed_admin.py
===============================================================================
"""

import os

from dotenv import load_dotenv

# the backend/ folder, absolute. every path below hangs off this, so the app
# works no matter which directory you launch it from.
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# load backend/.env into os.environ BEFORE the Config class body runs below.
#
# !! ALWAYS PASS THE EXPLICIT PATH !! bare load_dotenv() searches from the
# CURRENT WORKING DIRECTORY. so `python app.py` from backend/ would find it, but
# `celery -A celery_app.celery worker` launched from the project root would not,
# and the worker would silently fall back to console-logging every email.
# pinning it to BASE_DIR means it works no matter where you launch from.
#
# override=False (the default) -> a real env var already set in the shell WINS
# over the .env file. that's what lets the test suites force
# CELERY_TASK_ALWAYS_EAGER=1 and DATABASE_URL=<tmp> without editing .env.
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Config:
    # signs the JWTs. change this in prod and every existing token dies
    # (which is the point -- it's your emergency "log everyone out" button).
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    # sqlite:///<abs path>. three slashes + an absolute path = four total.
    # the M6/M7 test suites override DATABASE_URL to point at a temp file so
    # they never touch the real placement.db.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'placement.db')}"
    )
    # off = don't emit change signals we never listen to. saves memory, kills a
    # startup warning. no downside.
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Default admin credentials (override via env in production)
    # there is NO admin registration route -- seed_admin.py creates this one row.
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@placement.local")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

    # HS256 = symmetric, one secret signs AND verifies. fine for a single-service
    # app. (RS256 would matter if a different service had to verify our tokens.)
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRATION_HOURS = int(os.environ.get("JWT_EXPIRATION_HOURS", 24))

    # --- Milestone 7: Celery + Redis background jobs ---
    # note the /0 and /1 on the end -- those are redis DATABASE NUMBERS, not paths.
    # broker (db 0) = the job queue Flask pushes onto.
    # result backend (db 1) = where the worker parks each task's return value,
    #                         which is what GET /api/exports/status/<id> reads.
    # kept separate so `redis-cli -n 0 FLUSHDB` doesn't nuke your results.
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", f"{REDIS_URL}/0")
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", f"{REDIS_URL}/1")
    CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "0") == "1"

    # Email delivery (Gmail SMTP). Values come from backend/.env (gitignored).
    # Use a Gmail *App Password*, never the account password.
    # If MAIL_USERNAME/MAIL_PASSWORD are unset, mail_utils logs the message to
    # the console instead of sending, so jobs never crash.
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))  # 587 = STARTTLS. 465 would be SSL.
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "1") == "1"
    MAIL_USERNAME = (os.getenv("MAIL_USERNAME") or "").strip() or None
    MAIL_PASSWORD = (os.getenv("MAIL_PASSWORD") or "").replace(" ", "").strip() or None
    MAIL_DEFAULT_SENDER = os.getenv(
        "MAIL_DEFAULT_SENDER", MAIL_USERNAME or "noreply@placement.local"
    )

    # Generated artefacts (CSV exports, monthly reports)
    EXPORT_DIR = os.path.join(BASE_DIR, "instance", "exports")
    REPORT_DIR = os.path.join(BASE_DIR, "instance", "reports")

    # Interview reminders: notify students whose interview is within N hours.
    INTERVIEW_REMINDER_LOOKAHEAD_HOURS = int(
        os.environ.get("INTERVIEW_REMINDER_LOOKAHEAD_HOURS", 24)
    )

    # --- Milestone 8: Redis response caching ---
    # db 2. deliberately NOT 0 (celery broker) or 1 (celery results) -- so
    # flushing the cache can never eat a queued job or a pending task result.
    CACHE_REDIS_URL = os.environ.get("CACHE_REDIS_URL", f"{REDIS_URL}/2")
    # kill switch. set CACHE_ENABLED=0 to bypass the cache entirely (handy when
    # you're debugging "why is my data stale" and want to rule the cache out).
    CACHE_ENABLED = os.environ.get("CACHE_ENABLED", "1") == "1"

    # TTLs in seconds. these are the "expiry policy" half of the milestone; the
    # "refresh policy" half is the explicit invalidation in cache_utils.bump_*().
    #
    # WHY THESE NUMBERS: TTL is the worst-case staleness IF an invalidation is
    # ever missed. job listings change often and matter most, so 60s. the admin
    # search lists are lower-stakes, so 120s. everything is ALSO invalidated the
    # instant the underlying data changes, so in practice you never wait the TTL.
    CACHE_TTL_JOBS = int(os.environ.get("CACHE_TTL_JOBS", 60))
    CACHE_TTL_COMPANIES = int(os.environ.get("CACHE_TTL_COMPANIES", 120))
    CACHE_TTL_STUDENTS = int(os.environ.get("CACHE_TTL_STUDENTS", 120))
    CACHE_TTL_DEFAULT = int(os.environ.get("CACHE_TTL_DEFAULT", 60))
