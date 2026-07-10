"""
===============================================================================
FILE : backend/app.py
WHAT : the Flask entry point. builds the `app` object, bolts on the DB + CORS,
       and registers all 5 blueprints.
WHY  : one place where the whole API gets assembled.

RUN  : python app.py     -> dev server on http://127.0.0.1:5000

WHO IMPORTS THIS?
  - seed_admin.py  -> `from app import app` to get an app context for create_all()
  - the M6/M7 test suites -> app.test_client()
  - gunicorn/flask CLI in prod

WHO DOES *NOT* IMPORT THIS?
  - celery_app.py / tasks.py. they deliberately build their OWN tiny Flask app.
    if tasks.py did `from app import app`, we'd get a cycle:
        app.py -> export_routes.py -> tasks.py -> app.py   (boom)
    read the celery_app.py docstring for the full story.

BLUEPRINT MAP (which file owns which URL prefix):
  routes.py         -> /api/auth/*      (login, register, me)   + /api dashboards
  admin_routes.py   -> /api/admin/*     (approvals, CRUD, M6 detail views)
  company_routes.py -> /api/company/*   (jobs, applications, placements)
  student_routes.py -> /api/student/*   (profile, jobs, applications, placements)
  export_routes.py  -> /api/exports/*   + /api/admin/reports|reminders  (M7 celery)
===============================================================================
"""

import os

from flask import Flask
from flask_cors import CORS

from config import Config
from models import db
from admin_routes import admin_bp
from company_routes import company_bp
from export_routes import export_bp
from routes import auth_bp, dashboard_bp
from student_routes import student_bp

app = Flask(__name__)
app.config.from_object(Config)  # pulls in SECRET_KEY, DB URI, celery/mail settings

# instance/ holds placement.db + uploads/ + exports/ + reports/.
# flask does NOT create it for us, and SQLite will not create a missing folder,
# so this must run before the first db call or you get "unable to open database".
os.makedirs(app.instance_path, exist_ok=True)

# bind SQLAlchemy to this app. `db` itself is defined in models.py (one global
# object). celery_app.py binds the SAME db to its own app -- that's allowed.
db.init_app(app)

# the Vue dev server runs on :5173 and the API on :5000 -> different origin ->
# browser blocks it unless we whitelist. both spellings of localhost because
# some browsers resolve 'localhost' and some send '127.0.0.1'.
# (in prod they'd be same-origin behind nginx and this becomes a no-op.)
CORS(app, origins=["http://localhost:5173", "http://127.0.0.1:5173"])

# order doesn't matter -- flask routes by URL rule, not registration order.
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(company_bp)
app.register_blueprint(student_bp)
app.register_blueprint(export_bp)  # Milestone 7


@app.route("/api/health")
def health():
    """Liveness probe. no auth. handy for `curl localhost:5000/api/health` to
    check the server is actually up before debugging anything else."""
    return {"status": "ok", "message": "Placement Portal API"}


if __name__ == "__main__":
    # debug=True gives the auto-reloader + the werkzeug traceback page.
    # NEVER ship this -- the debugger lets anyone run python in your process.
    app.run(debug=True, port=5000)
