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
    """Minimal Flask app used only to give Celery tasks a DB app-context.

    NO blueprints, no CORS, no routes. it exists purely so `db.session` knows
    which database it's talking to inside a worker process.

    flask-sqlalchemy lets one `db` object serve many apps -- app.py binds the
    real web app, this binds a throwaway one. they never collide because they
    live in different processes.
    """
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    return app


flask_app = create_context_app()

# the celery instance itself. `celery -A celery_app.celery worker` finds it by
# this module path + variable name.
celery = Celery(
    "ppa_v2",
    broker=Config.CELERY_BROKER_URL,  # redis db 0 -> the job QUEUE
    backend=Config.CELERY_RESULT_BACKEND,  # redis db 1 -> the RESULTS
    include=["tasks"],  # import tasks.py on worker startup so @celery.task registers
)

celery.conf.update(
    # eager = run tasks synchronously, in-process, no redis, no worker.
    # the M7 test suite sets CELERY_TASK_ALWAYS_EAGER=1 so .delay() just calls
    # the function. eager_propagates makes a task exception actually raise
    # instead of being swallowed into a FAILURE result -- so tests fail loudly.
    task_always_eager=Config.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=Config.CELERY_TASK_ALWAYS_EAGER,
    # crontab() below is interpreted in THIS timezone. so hour=9 means 9am IST,
    # not 9am UTC. enable_utc keeps the internal message timestamps in UTC,
    # which is what you want -- only the SCHEDULE is localised.
    timezone="Asia/Kolkata",
    enable_utc=True,
    # without this there's no STARTED state -- a running task still reads
    # PENDING, and the frontend can't tell "queued" from "working".
    task_track_started=True,
    # results self-destruct from redis after 1h. otherwise redis slowly fills
    # with dead task results forever.
    result_expires=3600,
)

# ---------------------------------------------------------------------------
# CELERY BEAT -- the cron scheduler.
# beat is a SEPARATE PROCESS from the worker. it doesn't run anything; it just
# drops a message on the queue when the clock says so, and a worker picks it up.
# so you need BOTH running for scheduled jobs to actually fire:
#     celery -A celery_app.celery worker   # does the work
#     celery -A celery_app.celery beat     # decides when
# the "task" values are the task NAMES (set via @celery.task(name=...) in
# tasks.py), not python references -- beat only ships a string over redis.
# ---------------------------------------------------------------------------
celery.conf.beat_schedule = {
    # Daily at 09:00 IST — remind students of interviews in the next 24h.
    # (24h lookahead + daily cadence = every interview gets exactly one reminder)
    "interview-reminders-daily": {
        "task": "tasks.send_interview_reminders",
        "schedule": crontab(hour=9, minute=0),
    },
    # 1st of every month at 06:00 IST — monthly placement report per company.
    # reports on the PREVIOUS calendar month, which is why running it on the 1st
    # gives a complete month.
    "monthly-placement-reports": {
        "task": "tasks.generate_monthly_placement_reports",
        "schedule": crontab(day_of_month=1, hour=6, minute=0),
    },
}


class ContextTask(celery.Task):
    """Run every task inside a Flask application context.

    THE GLUE. without this, any task touching `Application.query` blows up with
    "Working outside of application context" -- because a worker process has no
    HTTP request to hang a context off.

    by overriding celery.Task, EVERY task gets wrapped automatically. no
    `with app.app_context():` boilerplate at the top of each one in tasks.py.

    self.run() is the original undecorated function body.
    """

    def __call__(self, *args, **kwargs):
        with flask_app.app_context():
            return self.run(*args, **kwargs)


# swap in our base class. must happen BEFORE tasks.py is imported (it is --
# `include=["tasks"]` is lazy, resolved on worker boot, after this line).
celery.Task = ContextTask
