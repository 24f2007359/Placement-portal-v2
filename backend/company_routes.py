from datetime import datetime

from flask import Blueprint, g, jsonify, request

from auth_utils import role_required
from models import Application, ApplicationStatus, ApprovalStatus, Company, JobPosition, JobStatus, Student, db

company_bp = Blueprint("company", __name__, url_prefix="/api/company")


def _ensure_company_access():
    company = g.current_user.company
    if not company:
        return None, (jsonify({"error": "Company profile not found"}), 404)

    approved = company.approval_status == ApprovalStatus.APPROVED
    if not approved or company.is_blacklisted or not g.current_user.is_active:
        return None, (
            jsonify(
                {
                    "error": "Dashboard access requires admin approval",
                    "approval_status": company.approval_status.value,
                    "approved": False,
                }
            ),
            403,
        )

    return company, None


def _serialize_job(job):
    return {
        "id": job.id,
        "title": job.title,
        "description": job.description,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "skills_required": job.skills_required,
        "experience_required": job.experience_required,
        "benefits": job.benefits,
        "application_deadline": job.application_deadline.isoformat() if job.application_deadline else None,
        "status": job.status.value,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "applications_count": len(job.applications),
    }


def _serialize_application(application):
    student = application.student
    return {
        "id": application.id,
        "job_id": application.job_id,
        "job_title": application.job_position.title if application.job_position else None,
        "student_id": application.student_id,
        "student_name": student.full_name if student else None,
        "student_contact": student.contact if student else None,
        "student_email": student.user.email if student and student.user else None,
        "status": application.status.value,
        "feedback": application.feedback,
        "interview_date": application.interview_date.isoformat() if application.interview_date else None,
        "applied_at": application.applied_at.isoformat() if application.applied_at else None,
    }


@company_bp.route("/dashboard", methods=["GET"])
@role_required("company")
def company_dashboard():
    company, error_response = _ensure_company_access()
    if error_response:
        return error_response

    jobs_query = JobPosition.query.filter_by(company_id=company.id)
    apps_query = (
        Application.query.join(JobPosition)
        .filter(JobPosition.company_id == company.id)
    )

    return jsonify(
        {
            "message": "Welcome to the Company dashboard",
            "role": "company",
            "approved": True,
            "approval_status": company.approval_status.value,
            "stats": {
                "job_postings": jobs_query.count(),
                "active_jobs": jobs_query.filter(JobPosition.status == JobStatus.ACTIVE).count(),
                "received_applications": apps_query.count(),
                "shortlisted_candidates": apps_query.filter(
                    Application.status == ApplicationStatus.SHORTLISTED
                ).count(),
            },
        }
    )


@company_bp.route("/jobs", methods=["GET"])
@role_required("company")
def list_company_jobs():
    company, error_response = _ensure_company_access()
    if error_response:
        return error_response

    query = JobPosition.query.filter_by(company_id=company.id)

    q = (request.args.get("q") or "").strip()
    if q:
        query = query.filter(JobPosition.title.ilike(f"%{q}%"))

    status = (request.args.get("status") or "").strip()
    if status:
        try:
            query = query.filter(JobPosition.status == JobStatus(status))
        except ValueError:
            return jsonify({"error": "Invalid status filter"}), 400

    jobs = query.order_by(JobPosition.created_at.desc()).all()
    return jsonify({"jobs": [_serialize_job(job) for job in jobs]})


@company_bp.route("/jobs", methods=["POST"])
@role_required("company")
def create_job():
    company, error_response = _ensure_company_access()
    if error_response:
        return error_response

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Job title is required"}), 400

    application_deadline = None
    deadline_raw = (data.get("application_deadline") or "").strip()
    if deadline_raw:
        try:
            application_deadline = datetime.fromisoformat(deadline_raw.replace("Z", "+00:00"))
        except ValueError:
            return jsonify({"error": "Invalid application deadline format"}), 400

    job = JobPosition(
        company_id=company.id,
        title=title,
        description=(data.get("description") or "").strip() or None,
        salary_min=data.get("salary_min"),
        salary_max=data.get("salary_max"),
        skills_required=(data.get("skills_required") or "").strip() or None,
        experience_required=(data.get("experience_required") or "").strip() or None,
        benefits=(data.get("benefits") or "").strip() or None,
        application_deadline=application_deadline,
        status=JobStatus.PENDING,
    )
    db.session.add(job)
    db.session.commit()
    return jsonify({"message": "Job posted and sent for admin approval", "job": _serialize_job(job)}), 201


@company_bp.route("/jobs/<int:job_id>", methods=["PUT"])
@role_required("company")
def update_job(job_id):
    company, error_response = _ensure_company_access()
    if error_response:
        return error_response

    job = JobPosition.query.filter_by(id=job_id, company_id=company.id).first_or_404()
    data = request.get_json(silent=True) or {}

    title = data.get("title")
    if title is not None:
        title = title.strip()
        if not title:
            return jsonify({"error": "Job title cannot be empty"}), 400
        job.title = title

    for field in ["description", "skills_required", "experience_required", "benefits"]:
        if field in data:
            value = data.get(field)
            job.__setattr__(field, value.strip() if isinstance(value, str) and value.strip() else None)

    for field in ["salary_min", "salary_max"]:
        if field in data:
            job.__setattr__(field, data.get(field))

    if "application_deadline" in data:
        deadline_raw = (data.get("application_deadline") or "").strip()
        if not deadline_raw:
            job.application_deadline = None
        else:
            try:
                job.application_deadline = datetime.fromisoformat(deadline_raw.replace("Z", "+00:00"))
            except ValueError:
                return jsonify({"error": "Invalid application deadline format"}), 400

    if "status" in data:
        status_raw = (data.get("status") or "").strip().lower()
        allowed_statuses = {JobStatus.ACTIVE.value, JobStatus.CLOSED.value}
        if status_raw not in allowed_statuses:
            return jsonify({"error": "Status can only be active or closed"}), 400
        if job.status == JobStatus.PENDING and status_raw == JobStatus.ACTIVE.value:
            return jsonify({"error": "Pending jobs must be approved by admin before activation"}), 400
        job.status = JobStatus(status_raw)

    db.session.commit()
    return jsonify({"message": "Job updated successfully", "job": _serialize_job(job)})


@company_bp.route("/jobs/<int:job_id>/applications", methods=["GET"])
@role_required("company")
def list_job_applications(job_id):
    company, error_response = _ensure_company_access()
    if error_response:
        return error_response

    job = JobPosition.query.filter_by(id=job_id, company_id=company.id).first_or_404()
    applications = (
        Application.query.filter_by(job_id=job.id)
        .order_by(Application.applied_at.desc())
        .all()
    )
    return jsonify(
        {
            "job": _serialize_job(job),
            "applications": [_serialize_application(app) for app in applications],
        }
    )


@company_bp.route("/applications", methods=["GET"])
@role_required("company")
def list_company_applications():
    company, error_response = _ensure_company_access()
    if error_response:
        return error_response

    status = (request.args.get("status") or "").strip().lower()
    query = Application.query.join(JobPosition).filter(JobPosition.company_id == company.id)

    if status:
        try:
            query = query.filter(Application.status == ApplicationStatus(status))
        except ValueError:
            return jsonify({"error": "Invalid application status filter"}), 400

    applications = query.order_by(Application.applied_at.desc()).all()
    return jsonify({"applications": [_serialize_application(app) for app in applications]})


@company_bp.route("/applications/<int:application_id>/status", methods=["PUT"])
@role_required("company")
def update_application_status(application_id):
    company, error_response = _ensure_company_access()
    if error_response:
        return error_response

    application = (
        Application.query.join(JobPosition)
        .filter(Application.id == application_id, JobPosition.company_id == company.id)
        .first_or_404()
    )
    data = request.get_json(silent=True) or {}

    status_raw = (data.get("status") or "").strip().lower()
    allowed_statuses = {
        ApplicationStatus.SHORTLISTED.value,
        ApplicationStatus.INTERVIEW.value,
        ApplicationStatus.OFFER.value,
        ApplicationStatus.REJECTED.value,
    }
    if status_raw not in allowed_statuses:
        return jsonify({"error": "Invalid status. Use shortlisted, interview, offer, or rejected"}), 400

    application.status = ApplicationStatus(status_raw)
    if "feedback" in data:
        feedback = data.get("feedback")
        application.feedback = feedback.strip() if isinstance(feedback, str) and feedback.strip() else None

    interview_date = data.get("interview_date")
    if interview_date is not None:
        interview_date = interview_date.strip()
        if interview_date:
            try:
                application.interview_date = datetime.fromisoformat(interview_date.replace("Z", "+00:00"))
            except ValueError:
                return jsonify({"error": "Invalid interview date format"}), 400
        else:
            application.interview_date = None

    db.session.commit()
    return jsonify({"message": "Application status updated", "application": _serialize_application(application)})
