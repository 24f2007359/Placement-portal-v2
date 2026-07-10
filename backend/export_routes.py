"""Async export + report endpoints (Milestone 7).

Pattern: the client POSTs to trigger a job and immediately gets a `task_id`.
It then polls GET /api/exports/status/<task_id> until `ready` is true, and
finally downloads the produced file. The user is also emailed when the job
finishes, satisfying the milestone's "alert sent once the batch job is
complete" requirement.
"""

import os

from celery.result import AsyncResult
from flask import Blueprint, g, jsonify, send_file
from werkzeug.utils import secure_filename

from auth_utils import role_required, token_required
from cache_utils import bump_all, cache_stats
from celery_app import celery
from config import Config
from tasks import (
    export_applications_csv,
    export_placements_csv,
    generate_company_report,
    generate_monthly_placement_reports,
    send_interview_reminders,
)

export_bp = Blueprint("exports", __name__, url_prefix="/api")


def _owns_file(filename):
    """Non-admins may only touch files stamped with their own user id.

    tasks.py names every export `applications_user<uid>_<timestamp>.csv`, so the
    owner is baked into the filename. student 7 asking for
    `applications_user8_...csv` fails this check -> 403.

    crude but effective. the alternative (an exports table with an owner FK) is
    the proper fix if this ever grows up. one wart: a user id of 1 also matches
    "user1_" inside "...user12_..."? no -- the trailing underscore prevents it.
    user1_ vs user12_ differ at the underscore. good.

    admins bypass entirely -- they can pull any export or report.
    """
    if g.current_user.role.value == "admin":
        return True
    return f"user{g.current_user.id}_" in filename


def _safe_path(directory, filename):
    """Resolve filename inside `directory`, refusing traversal attempts.

    THE PATH-TRAVERSAL GUARD. two layers:
      1. secure_filename() strips "../", slashes, null bytes, unicode tricks.
      2. THEN we realpath() the result and assert it still lives under
         `directory`. belt and braces -- if secure_filename ever missed
         something, or `directory` itself is a symlink, this catches it.

    the `+ os.sep` matters! without it, "/exports_evil/x" would startswith
    "/exports" and slip through. the separator forces a real directory boundary.

    returns (safe_name, abs_path) or (None, None) if it tried to escape.
    verified in the live test: GET /api/exports/download/..%2f..%2fconfig.py -> 404.
    """
    safe = secure_filename(filename)
    path = os.path.realpath(os.path.join(directory, safe))
    if not path.startswith(os.path.realpath(directory) + os.sep):
        return None, None
    return safe, path


# --- trigger ---------------------------------------------------------------


@export_bp.route("/exports/applications", methods=["POST"])
@role_required("student", "company")
def trigger_applications_export():
    """POST /api/exports/applications -> 202 { task_id }. RETURNS IMMEDIATELY.

    .delay() = "put this on the redis queue and give me a ticket". it does NOT
    run the task. a Celery worker in another process picks it up.
    this handler finishes in ~5ms even if the export takes 30 seconds.

    202 Accepted, not 200 OK -- "I've taken your request, it isn't done yet".
    the correct status code for exactly this, and worth saying in the viva.

    we pass g.current_user.id, NOT the User object. celery has to pickle the
    args through redis, and a sqlalchemy model tied to a dead session won't
    survive that. the task re-fetches it. always send ids to tasks.

    no admin here: an admin has no applications of their own to export.
    the task itself decides student-vs-company from the user's role.
    """
    task = export_applications_csv.delay(g.current_user.id)
    return jsonify({"message": "Export started", "task_id": task.id}), 202


@export_bp.route("/exports/placements", methods=["POST"])
@role_required("student", "company", "admin")
def trigger_placements_export():
    """POST /api/exports/placements -> 202 { task_id }.

    admin IS allowed here -> they get every placement in the system.
    student -> own, company -> own. the task branches on role.
    """
    task = export_placements_csv.delay(g.current_user.id)
    return jsonify({"message": "Export started", "task_id": task.id}), 202


# --- poll ------------------------------------------------------------------


@export_bp.route("/exports/status/<task_id>", methods=["GET"])
@token_required
def export_status(task_id):
    """GET /api/exports/status/<task_id> -> "is the worker done yet?"

    polled once a second by services/exports.js -> runExport().
    @token_required only (any role) -- reminders/reports jobs poll this too.

    AsyncResult just reads the RESULT BACKEND (redis db 1). it does not talk to
    the worker.

    states: PENDING -> STARTED -> SUCCESS | FAILURE
    !! 'PENDING' IS A LIE-ISH !! celery cannot distinguish "queued, not started"
    from "I have never heard of this task id". both read PENDING. so a DEAD
    WORKER looks exactly like a slow one -- which is why runExport() gives up
    after 60 polls and blames the worker in its error message.

    result.successful() -> the task returned normally. but the task may STILL
    have returned {"error": "..."} as its value (business failure, not a crash),
    which is why we hand the whole dict back as `result` and let the frontend
    check for .error.

    result.failed() -> the task raised. result.result is then the EXCEPTION
    object, hence str().

    SECURITY WART: no ownership check on task_id. anyone logged in who guesses a
    uuid4 could read another user's task result (a filename + a row count).
    low impact -- the actual download IS ownership-checked -- but a real system
    would store owner-per-task.
    """
    result = AsyncResult(task_id, app=celery)
    payload = {"task_id": task_id, "state": result.state, "ready": result.ready()}

    if result.successful():
        value = result.result or {}
        payload["result"] = value
        # hoist filename/rows to the top level so the frontend doesn't have to
        # dig, and so report jobs (which return no filename) simply omit them.
        if isinstance(value, dict) and value.get("filename"):
            payload["filename"] = value["filename"]
            payload["rows"] = value.get("rows")
    elif result.failed():
        payload["error"] = str(result.result)  # result.result is the exception

    return jsonify(payload)


# --- download --------------------------------------------------------------


@export_bp.route("/exports/download/<filename>", methods=["GET"])
@token_required
def download_export(filename):
    """GET /api/exports/download/<filename> -> the CSV bytes.

    called by: services/exports.js -> exportApi.download() (responseType blob)

    TWO INDEPENDENT GUARDS, both required:
      1. _owns_file()  -> 403. is this file stamped with your user id?
      2. _safe_path()  -> 404. does it resolve inside EXPORT_DIR?
    ownership first, so a traversal attempt from a non-admin dies at the 403
    without us even touching the filesystem.

    note this can't be a plain <a href> on the frontend -- @token_required means
    the request needs an Authorization header, which link navigation won't send.
    hence the saveBlob() dance in exports.js.
    """
    if not _owns_file(filename):
        return jsonify({"error": "You do not have access to this export"}), 403

    safe, path = _safe_path(Config.EXPORT_DIR, filename)
    if not path or not os.path.exists(path):
        # same 404 for "escaped the directory" and "genuinely missing" -- don't
        # leak which one it was.
        return jsonify({"error": "Export file not found"}), 404

    return send_file(path, as_attachment=True, download_name=safe)


# --- admin: reports + manual job triggers ----------------------------------


@export_bp.route("/admin/reports/monthly", methods=["POST"])
@role_required("admin")
def trigger_monthly_reports():
    """POST /api/admin/reports/monthly -> run the monthly report job NOW.

    the same task Celery Beat fires on the 1st at 06:00. this button exists so
    you don't have to wait a month to demo it (or change your system clock).
    generates last month's report for EVERY approved company + emails each.
    """
    task = generate_monthly_placement_reports.delay()
    return jsonify({"message": "Monthly report generation started", "task_id": task.id}), 202


@export_bp.route("/admin/reports/company/<int:company_id>", methods=["POST"])
@role_required("admin")
def trigger_company_report(company_id):
    """POST .../reports/company/<id> -> one company's report on demand.
    not wired to a button yet; adminApi.runCompanyReport() is ready for it."""
    task = generate_company_report.delay(company_id)
    return jsonify({"message": "Report generation started", "task_id": task.id}), 202


@export_bp.route("/admin/reminders/interviews", methods=["POST"])
@role_required("admin")
def trigger_interview_reminders():
    """POST /api/admin/reminders/interviews -> run the reminder job NOW.

    same task Beat fires daily at 09:00. mails every student whose interview
    lands in the next 24h. returns {checked, sent, skipped} via the status poll.
    """
    task = send_interview_reminders.delay()
    return jsonify({"message": "Interview reminder job started", "task_id": task.id}), 202


@export_bp.route("/admin/reports", methods=["GET"])
@role_required("admin")
def list_reports():
    """GET /api/admin/reports -> just an `ls` of instance/reports/.

    no db table behind this; the filesystem IS the index. filenames look like
    report_company3_2026-06.pdf, so reverse-sorting puts the newest month first
    (lexicographic works because of the YYYY-MM zero padding).

    returns [] rather than 404ing when the dir doesn't exist yet -- it's only
    created on the first report run.
    """
    directory = Config.REPORT_DIR
    if not os.path.isdir(directory):
        return jsonify({"reports": []})

    reports = sorted(
        (f for f in os.listdir(directory) if f.endswith((".pdf", ".html"))),
        reverse=True,
    )
    return jsonify({"reports": reports})


# --- admin: redis cache introspection (Milestone 8) -------------------------


@export_bp.route("/admin/cache/stats", methods=["GET"])
@role_required("admin")
def get_cache_stats():
    """GET /api/admin/cache/stats -> is the cache alive, and what's in it?

    called by: services/admin.js -> getCacheStats() <- the admin "Reports & Jobs" tab.

    returns per-namespace: current version number, live key count, TTL.
    the version numbers are the interesting part for a demo -- approve a job,
    refresh, and watch `jobs.version` tick up by one.

    NOT cached (obviously). caching your cache stats would be a cruel joke.
    """
    return jsonify({"cache": cache_stats()})


@export_bp.route("/admin/cache/flush", methods=["POST"])
@role_required("admin")
def flush_cache():
    """POST /api/admin/cache/flush -> invalidate every namespace at once.

    the manual escape hatch: if you ever suspect a stale entry, one click and
    every cached response is logically gone.

    implemented as three INCRs (bump_all), NOT redis FLUSHDB. that guarantees it
    can never touch the celery broker (db 0) or task results (db 1), even if
    someone fat-fingers CACHE_REDIS_URL. a FLUSHDB pointed at db 0 would silently
    delete queued jobs.
    """
    bump_all()
    return jsonify({"message": "Cache flushed", "cache": cache_stats()})


@export_bp.route("/admin/reports/download/<filename>", methods=["GET"])
@role_required("admin")
def download_report(filename):
    """GET .../reports/download/<filename> -> the PDF/HTML bytes.

    no _owns_file() call here -- @role_required("admin") already means you own
    everything. but we still run _safe_path(), because "trusted user" and
    "trusted input" are different things. an admin can still be phished into
    clicking a crafted link.
    """
    safe, path = _safe_path(Config.REPORT_DIR, filename)
    if not path or not os.path.exists(path):
        return jsonify({"error": "Report not found"}), 404
    return send_file(path, as_attachment=True, download_name=safe)
