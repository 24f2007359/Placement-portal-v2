import os
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request, send_file
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from auth_utils import role_required
from models import (
    Application,
    ApplicationStatus,
    ApprovalStatus,
    Company,
    JobPosition,
    JobStatus,
    Placement,
    Student,
    db,
    log_application_status,
    serialize_placement,
    serialize_status_history,
)

student_bp = Blueprint("student", __name__, url_prefix="/api/student")

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "instance", "uploads", "resumes")
ALLOWED_RESUME_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt"}


def _ensure_student_access():
    student = g.current_user.student
    if not student:
        return None, (jsonify({"error": "Student profile not found"}), 404)

    if student.is_blacklisted or not g.current_user.is_active:
        return None, (jsonify({"error": "Student account is deactivated or blacklisted"}), 403)

    return student, None


def _serialize_student(student):
    return {
        "id": student.id,
        "full_name": student.full_name,
        "email": student.user.email if student.user else None,
        "institute_id": student.institute_id,
        "contact": student.contact,
        "branch": student.branch,
        "cgpa": student.cgpa,
        "graduation_year": student.graduation_year,
        "skills": student.skills,
        "education": student.education,
        "experience": student.experience,
        "resume_path": student.resume_path,
        "is_blacklisted": student.is_blacklisted,
    }


def _serialize_job_for_student(job, student):
    applied = Application.query.filter_by(student_id=student.id, job_id=job.id).first()
    return {
        "id": job.id,
        "title": job.title,
        "description": job.description,
        "company_id": job.company_id,
        "company_name": job.company.name if job.company else None,
        "company_location": job.company.location if job.company else None,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "skills_required": job.skills_required,
        "experience_required": job.experience_required,
        "eligibility_branch": job.eligibility_branch,
        "eligibility_cgpa": job.eligibility_cgpa,
        "eligibility_year": job.eligibility_year,
        "benefits": job.benefits,
        "application_deadline": job.application_deadline.isoformat()
        if job.application_deadline
        else None,
        "status": job.status.value,
        "already_applied": applied is not None,
        "application_status": applied.status.value if applied else None,
    }


def _serialize_application(application, include_history=False):
    job = application.job_position
    company = job.company if job else None
    placement = application.placement
    data = {
        "id": application.id,
        "job_id": application.job_id,
        "job_title": job.title if job else None,
        "company_name": company.name if company else None,
        "status": application.status.value,
        "applied_at": application.applied_at.isoformat() if application.applied_at else None,
        "feedback": application.feedback,
        "interview_date": application.interview_date.isoformat()
        if application.interview_date
        else None,
        "has_offer_letter": application.status in (
            ApplicationStatus.OFFER,
            ApplicationStatus.PLACED,
        )
        or (placement is not None),
        "placement_id": placement.id if placement else None,
        "placement": serialize_placement(placement) if placement else None,
    }
    if include_history:
        data["status_history"] = serialize_status_history(application)
    return data


def _approved_jobs_query():
    return (
        JobPosition.query.join(Company)
        .filter(Company.approval_status == ApprovalStatus.APPROVED)
        .filter(Company.is_blacklisted.is_(False))
        .filter(JobPosition.status.in_([JobStatus.APPROVED, JobStatus.ACTIVE]))
    )


def _check_eligibility(student, job):
    if job.eligibility_cgpa is not None:
        if student.cgpa is None:
            return False, "CGPA is required in your profile to apply for this job"
        if student.cgpa < job.eligibility_cgpa:
            return False, f"Minimum CGPA required is {job.eligibility_cgpa}"

    if job.eligibility_year is not None:
        if student.graduation_year is None:
            return False, "Graduation year is required in your profile to apply for this job"
        if student.graduation_year != job.eligibility_year:
            return False, f"Only graduation year {job.eligibility_year} is eligible"

    if job.eligibility_branch:
        if not student.branch:
            return False, "Branch is required in your profile to apply for this job"
        allowed = [b.strip().lower() for b in job.eligibility_branch.split(",")]
        if student.branch.lower() not in allowed and "all" not in allowed:
            return False, "Your branch is not eligible for this job"

    return True, None


def _generate_offer_letter_text(student, application):
    job = application.job_position
    company = job.company if job else None
    lines = [
        "OFFER LETTER",
        "============",
        "",
        f"Date: {datetime.now(timezone.utc).strftime('%d %B %Y')}",
        f"Student: {student.full_name}",
        f"Institute ID: {student.institute_id or 'N/A'}",
        "",
        f"We are pleased to offer you the position of {job.title if job else 'N/A'}",
        f"at {company.name if company else 'N/A'}.",
        "",
        f"Application Status: {application.status.value.upper()}",
        "",
        "Congratulations on your placement!",
        "",
        "— Placement Portal",
    ]
    return "\n".join(lines)


@student_bp.route("/dashboard", methods=["GET"])
@role_required("student")
def student_dashboard():
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    applications = Application.query.filter_by(student_id=student.id)
    return jsonify(
        {
            "message": "Welcome to the Student dashboard",
            "role": "student",
            "stats": {
                "available_jobs": _approved_jobs_query().count(),
                "applications_submitted": applications.count(),
                "shortlisted": applications.filter_by(
                    status=ApplicationStatus.SHORTLISTED
                ).count(),
                "interviews_scheduled": applications.filter(
                    Application.status == ApplicationStatus.INTERVIEW
                ).count(),
                "placed": applications.filter(
                    Application.status == ApplicationStatus.PLACED
                ).count(),
            },
        }
    )


@student_bp.route("/profile", methods=["GET"])
@role_required("student")
def get_profile():
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response
    return jsonify({"profile": _serialize_student(student)})


@student_bp.route("/profile", methods=["PUT"])
@role_required("student")
def update_profile():
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    data = request.get_json(silent=True) or {}

    if "full_name" in data:
        full_name = (data.get("full_name") or "").strip()
        if not full_name:
            return jsonify({"error": "Full name cannot be empty"}), 400
        student.full_name = full_name

    if "contact" in data:
        student.contact = (data.get("contact") or "").strip() or None

    if "branch" in data:
        student.branch = (data.get("branch") or "").strip() or None

    if "cgpa" in data:
        cgpa = data.get("cgpa")
        student.cgpa = float(cgpa) if cgpa not in (None, "") else None

    if "graduation_year" in data:
        year = data.get("graduation_year")
        student.graduation_year = int(year) if year not in (None, "") else None

    for field in ["skills", "education", "experience", "resume_path"]:
        if field in data:
            value = data.get(field)
            student.__setattr__(
                field, value.strip() if isinstance(value, str) and value.strip() else None
            )

    db.session.commit()
    return jsonify({"message": "Profile updated successfully", "profile": _serialize_student(student)})


@student_bp.route("/profile/resume", methods=["POST"])
@role_required("student")
def upload_resume():
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    if "resume" not in request.files:
        return jsonify({"error": "No resume file uploaded"}), 400

    file = request.files["resume"]
    if not file or not file.filename:
        return jsonify({"error": "No resume file selected"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_RESUME_EXTENSIONS:
        return jsonify({"error": "Allowed formats: pdf, doc, docx, txt"}), 400

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    filename = secure_filename(f"student_{student.id}_{file.filename}")
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    student.resume_path = filepath
    db.session.commit()
    return jsonify(
        {
            "message": "Resume uploaded successfully",
            "profile": _serialize_student(student),
        }
    )


@student_bp.route("/jobs", methods=["GET"])
@role_required("student")
def list_jobs():
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    query = _approved_jobs_query()

    q = (request.args.get("q") or "").strip()
    if q:
        query = query.filter(
            db.or_(
                JobPosition.title.ilike(f"%{q}%"),
                JobPosition.skills_required.ilike(f"%{q}%"),
                Company.name.ilike(f"%{q}%"),
            )
        )

    company_name = (request.args.get("company") or "").strip()
    if company_name:
        query = query.filter(Company.name.ilike(f"%{company_name}%"))

    jobs = query.order_by(JobPosition.created_at.desc()).all()
    return jsonify({"jobs": [_serialize_job_for_student(job, student) for job in jobs]})


@student_bp.route("/jobs/<int:job_id>/apply", methods=["POST"])
@role_required("student")
def apply_for_job(job_id):
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    job = _approved_jobs_query().filter(JobPosition.id == job_id).first()
    if not job:
        return jsonify({"error": "Job not found or not available for application"}), 404

    if job.application_deadline:
        deadline = job.application_deadline
        if deadline.tzinfo is not None:
            deadline = deadline.replace(tzinfo=None)
        if deadline < datetime.now(timezone.utc).replace(tzinfo=None):
            return jsonify({"error": "Application deadline has passed"}), 400

    existing = Application.query.filter_by(student_id=student.id, job_id=job.id).first()
    if existing:
        return jsonify({"error": "You have already applied for this job"}), 409

    eligible, reason = _check_eligibility(student, job)
    if not eligible:
        return jsonify({"error": reason}), 400

    application = Application(student_id=student.id, job_id=job.id)
    db.session.add(application)
    log_application_status(
        application,
        to_status=ApplicationStatus.APPLIED,
        changed_by_role="student",
        changed_by_user_id=g.current_user.id,
        note="Application submitted",
    )
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "You have already applied for this job"}), 409

    return (
        jsonify(
            {
                "message": "Application submitted successfully",
                "application": _serialize_application(application),
            }
        ),
        201,
    )


@student_bp.route("/applications", methods=["GET"])
@role_required("student")
def list_applications():
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    status = (request.args.get("status") or "").strip().lower()
    query = Application.query.filter_by(student_id=student.id)

    if status:
        try:
            query = query.filter(Application.status == ApplicationStatus(status))
        except ValueError:
            return jsonify({"error": "Invalid status filter"}), 400

    applications = query.order_by(Application.applied_at.desc()).all()
    return jsonify({"applications": [_serialize_application(app) for app in applications]})


@student_bp.route("/applications/<int:application_id>", methods=["GET"])
@role_required("student")
def get_application(application_id):
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    application = Application.query.filter_by(
        id=application_id, student_id=student.id
    ).first_or_404()
    return jsonify({"application": _serialize_application(application, include_history=True)})


@student_bp.route("/placements", methods=["GET"])
@role_required("student")
def list_student_placements():
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    placements = (
        Placement.query.filter_by(student_id=student.id)
        .order_by(Placement.created_at.desc())
        .all()
    )
    return jsonify({"placements": [serialize_placement(p) for p in placements]})


@student_bp.route("/applications/<int:application_id>/offer-letter", methods=["GET"])
@role_required("student")
def download_offer_letter(application_id):
    student, error_response = _ensure_student_access()
    if error_response:
        return error_response

    application = Application.query.filter_by(
        id=application_id, student_id=student.id
    ).first_or_404()

    if application.status not in (ApplicationStatus.OFFER, ApplicationStatus.PLACED):
        return jsonify({"error": "Offer letter is available only for offer/placed applications"}), 400

    placement = application.placement
    if placement and placement.offer_letter_path and os.path.exists(placement.offer_letter_path):
        return send_file(
            placement.offer_letter_path,
            as_attachment=True,
            download_name=f"offer_letter_{application_id}.txt",
        )

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    temp_path = os.path.join(UPLOAD_FOLDER, f"offer_{application_id}.txt")
    with open(temp_path, "w", encoding="utf-8") as handle:
        handle.write(_generate_offer_letter_text(student, application))

    return send_file(
        temp_path,
        as_attachment=True,
        download_name=f"offer_letter_{application_id}.txt",
    )
