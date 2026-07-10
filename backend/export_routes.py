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
    """Non-admins may only touch files stamped with their own user id."""
    if g.current_user.role.value == "admin":
        return True
    return f"user{g.current_user.id}_" in filename


def _safe_path(directory, filename):
    """Resolve filename inside `directory`, refusing traversal attempts."""
    safe = secure_filename(filename)
    path = os.path.realpath(os.path.join(directory, safe))
    if not path.startswith(os.path.realpath(directory) + os.sep):
        return None, None
    return safe, path


# --- trigger ---------------------------------------------------------------


@export_bp.route("/exports/applications", methods=["POST"])
@role_required("student", "company")
def trigger_applications_export():
    task = export_applications_csv.delay(g.current_user.id)
    return jsonify({"message": "Export started", "task_id": task.id}), 202


@export_bp.route("/exports/placements", methods=["POST"])
@role_required("student", "company", "admin")
def trigger_placements_export():
    task = export_placements_csv.delay(g.current_user.id)
    return jsonify({"message": "Export started", "task_id": task.id}), 202


# --- poll ------------------------------------------------------------------


@export_bp.route("/exports/status/<task_id>", methods=["GET"])
@token_required
def export_status(task_id):
    result = AsyncResult(task_id, app=celery)
    payload = {"task_id": task_id, "state": result.state, "ready": result.ready()}

    if result.successful():
        value = result.result or {}
        payload["result"] = value
        if isinstance(value, dict) and value.get("filename"):
            payload["filename"] = value["filename"]
            payload["rows"] = value.get("rows")
    elif result.failed():
        payload["error"] = str(result.result)

    return jsonify(payload)


# --- download --------------------------------------------------------------


@export_bp.route("/exports/download/<filename>", methods=["GET"])
@token_required
def download_export(filename):
    if not _owns_file(filename):
        return jsonify({"error": "You do not have access to this export"}), 403

    safe, path = _safe_path(Config.EXPORT_DIR, filename)
    if not path or not os.path.exists(path):
        return jsonify({"error": "Export file not found"}), 404

    return send_file(path, as_attachment=True, download_name=safe)


# --- admin: reports + manual job triggers ----------------------------------


@export_bp.route("/admin/reports/monthly", methods=["POST"])
@role_required("admin")
def trigger_monthly_reports():
    task = generate_monthly_placement_reports.delay()
    return jsonify({"message": "Monthly report generation started", "task_id": task.id}), 202


@export_bp.route("/admin/reports/company/<int:company_id>", methods=["POST"])
@role_required("admin")
def trigger_company_report(company_id):
    task = generate_company_report.delay(company_id)
    return jsonify({"message": "Report generation started", "task_id": task.id}), 202


@export_bp.route("/admin/reminders/interviews", methods=["POST"])
@role_required("admin")
def trigger_interview_reminders():
    task = send_interview_reminders.delay()
    return jsonify({"message": "Interview reminder job started", "task_id": task.id}), 202


@export_bp.route("/admin/reports", methods=["GET"])
@role_required("admin")
def list_reports():
    directory = Config.REPORT_DIR
    if not os.path.isdir(directory):
        return jsonify({"reports": []})

    reports = sorted(
        (f for f in os.listdir(directory) if f.endswith((".pdf", ".html"))),
        reverse=True,
    )
    return jsonify({"reports": reports})


@export_bp.route("/admin/reports/download/<filename>", methods=["GET"])
@role_required("admin")
def download_report(filename):
    safe, path = _safe_path(Config.REPORT_DIR, filename)
    if not path or not os.path.exists(path):
        return jsonify({"error": "Report not found"}), 404
    return send_file(path, as_attachment=True, download_name=safe)
