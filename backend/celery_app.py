"""Celery application, beat schedule, and Flask app-context glue (Milestone 7).

Why this module builds its own Flask app instead of importing `app.py`:
`app.py` registers the blueprints, and those blueprints import `tasks` so they
can call `.delay()`. If `tasks` (or this module) imported `app.py` back, we'd
have a circular import. A small context-only Flask app — same config, same
`db` object, no blueprints — gives tasks their database session without the
cycle. Flask-SQLAlchemy supports binding one `db` to multiple apps.

Run the worker and scheduler from the `backend/` directory:

    celery -A celery_app.celery worker --loglevel=info
    celery -A celery_app.celery beat   --loglevel=info

On Windows (not WSL) the prefork pool is unsupported; add `--pool=solo`.
"""

from celery import Celery
from celery.schedules import crontab
from flask import Flask

from config import Config
from models import db


def create_context_app():
    """Minimal Flask app used only to give Celery tasks a DB app-context."""
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    return app


flask_app = create_context_app()

celery = Celery(
    "ppa_v2",
    broker=Config.CELERY_BROKER_URL,
    backend=Config.CELERY_RESULT_BACKEND,
    include=["tasks"],
)

celery.conf.update(
    task_always_eager=Config.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=Config.CELERY_TASK_ALWAYS_EAGER,
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    result_expires=3600,
)

# Scheduled (Celery Beat) jobs.
celery.conf.beat_schedule = {
    # Daily at 09:00 IST — remind students of interviews in the next 24h.
    "interview-reminders-daily": {
        "task": "tasks.send_interview_reminders",
        "schedule": crontab(hour=9, minute=0),
    },
    # 1st of every month at 06:00 IST — monthly placement report per company.
    "monthly-placement-reports": {
        "task": "tasks.generate_monthly_placement_reports",
        "schedule": crontab(day_of_month=1, hour=6, minute=0),
    },
}


class ContextTask(celery.Task):
    """Run every task inside a Flask application context."""

    def __call__(self, *args, **kwargs):
        with flask_app.app_context():
            return self.run(*args, **kwargs)


celery.Task = ContextTask
