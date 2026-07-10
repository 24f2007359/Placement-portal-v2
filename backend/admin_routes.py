from flask import Blueprint, jsonify, request

from auth_utils import role_required
from models import (
    Application,
    ApprovalStatus,
    Company,
    JobPosition,
    JobStatus,
    Placement,
    Student,
    User,
    db,
    serialize_placement,
    serialize_status_history,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _company_dict(company):
    return {
        "id": company.id,
        "name": company.name,
        "industry": company.industry,
        "location": company.location,
        "website": company.website,
        "hr_contact": company.hr_contact,
        "email": company.user.email if company.user else None,
        "approval_status": company.approval_status.value,
        "is_blacklisted": company.is_blacklisted,
        "is_active": company.user.is_active if company.user else False,
        "created_at": company.created_at.isoformat() if company.created_at else None,
    }


def _student_dict(student):
    return {
        "id": student.id,
        "full_name": student.full_name,
        "institute_id": student.institute_id,
        "contact": student.contact,
        "branch": student.branch,
        "email": student.user.email if student.user else None,
        "is_blacklisted": student.is_blacklisted,
        "is_active": student.user.is_active if student.user else False,
        "created_at": student.created_at.isoformat() if student.created_at else None,
    }


def _job_dict(job):
    return {
        "id": job.id,
        "title": job.title,
        "company_id": job.company_id,
        "company_name": job.company.name if job.company else None,
        "status": job.status.value,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "skills_required": job.skills_required,
        "application_deadline": job.application_deadline.isoformat()
        if job.application_deadline
        else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "applications_count": len(job.applications),
    }


def _application_dict(app_record):
    return {
        "id": app_record.id,
        "student_name": app_record.student.full_name if app_record.student else None,
        "student_id": app_record.student_id,
        "job_title": app_record.job_position.title if app_record.job_position else None,
        "job_id": app_record.job_id,
        "company_name": app_record.job_position.company.name
        if app_record.job_position and app_record.job_position.company
        else None,
        "status": app_record.status.value,
        "applied_at": app_record.applied_at.isoformat() if app_record.applied_at else None,
    }


@admin_bp.route("/dashboard", methods=["GET"])
@role_required("admin")
def admin_dashboard():
    return jsonify(
        {
            "message": "Welcome to the Admin dashboard",
            "stats": {
                "students": Student.query.count(),
                "companies": Company.query.count(),
                "job_postings": JobPosition.query.count(),
                "applications": Application.query.count(),
                "pending_companies": Company.query.filter_by(
                    approval_status=ApprovalStatus.PENDING
                ).count(),
                "pending_jobs": JobPosition.query.filter_by(status=JobStatus.PENDING).count(),
            },
        }
    )


@admin_bp.route("/companies", methods=["GET"])
@role_required("admin")
def list_companies():
    query = Company.query.join(User)

    search = (request.args.get("q") or "").strip()
    industry = (request.args.get("industry") or "").strip()

    if search:
        query = query.filter(Company.name.ilike(f"%{search}%"))
    if industry:
        query = query.filter(Company.industry.ilike(f"%{industry}%"))

    status = (request.args.get("status") or "").strip()
    if status:
        try:
            query = query.filter(Company.approval_status == ApprovalStatus(status))
        except ValueError:
            return jsonify({"error": "Invalid status filter"}), 400

    companies = query.order_by(Company.created_at.desc()).all()
    return jsonify({"companies": [_company_dict(c) for c in companies]})


@admin_bp.route("/companies/<int:company_id>/approve", methods=["PUT"])
@role_required("admin")
def approve_company(company_id):
    company = Company.query.get_or_404(company_id)
    company.approval_status = ApprovalStatus.APPROVED
    company.is_blacklisted = False
    if company.user:
        company.user.is_active = True
    db.session.commit()
    return jsonify({"message": "Company approved", "company": _company_dict(company)})


@admin_bp.route("/companies/<int:company_id>/reject", methods=["PUT"])
@role_required("admin")
def reject_company(company_id):
    company = Company.query.get_or_404(company_id)
    company.approval_status = ApprovalStatus.REJECTED
    db.session.commit()
    return jsonify({"message": "Company rejected", "company": _company_dict(company)})


@admin_bp.route("/companies/<int:company_id>/blacklist", methods=["PUT"])
@role_required("admin")
def blacklist_company(company_id):
    company = Company.query.get_or_404(company_id)
    company.is_blacklisted = True
    company.approval_status = ApprovalStatus.REJECTED
    if company.user:
        company.user.is_active = False
    db.session.commit()
    return jsonify({"message": "Company blacklisted", "company": _company_dict(company)})


@admin_bp.route("/companies/<int:company_id>", methods=["DELETE"])
@role_required("admin")
def remove_company(company_id):
    company = Company.query.get_or_404(company_id)

    Placement.query.filter_by(company_id=company.id).delete()
    user = company.user
    db.session.delete(company)
    if user:
        db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "Company removed"})


@admin_bp.route("/students", methods=["GET"])
@role_required("admin")
def list_students():
    query = Student.query.join(User)

    search = (request.args.get("q") or "").strip()
    if search:
        query = query.filter(
            db.or_(
                Student.full_name.ilike(f"%{search}%"),
                Student.institute_id.ilike(f"%{search}%"),
                Student.contact.ilike(f"%{search}%"),
            )
        )

    students = query.order_by(Student.created_at.desc()).all()
    return jsonify({"students": [_student_dict(s) for s in students]})


@admin_bp.route("/students/<int:student_id>/blacklist", methods=["PUT"])
@role_required("admin")
def blacklist_student(student_id):
    student = Student.query.get_or_404(student_id)
    student.is_blacklisted = True
    if student.user:
        student.user.is_active = False
    db.session.commit()
    return jsonify({"message": "Student blacklisted", "student": _student_dict(student)})


@admin_bp.route("/students/<int:student_id>/deactivate", methods=["PUT"])
@role_required("admin")
def deactivate_student(student_id):
    student = Student.query.get_or_404(student_id)
    if student.user:
        student.user.is_active = False
    db.session.commit()
    return jsonify({"message": "Student deactivated", "student": _student_dict(student)})


@admin_bp.route("/students/<int:student_id>/activate", methods=["PUT"])
@role_required("admin")
def activate_student(student_id):
    student = Student.query.get_or_404(student_id)
    if student.is_blacklisted:
        return jsonify({"error": "Cannot activate a blacklisted student"}), 400
    if student.user:
        student.user.is_active = True
    db.session.commit()
    return jsonify({"message": "Student activated", "student": _student_dict(student)})


@admin_bp.route("/students/<int:student_id>", methods=["DELETE"])
@role_required("admin")
def remove_student(student_id):
    student = Student.query.get_or_404(student_id)

    Placement.query.filter_by(student_id=student.id).delete()
    user = student.user
    db.session.delete(student)
    if user:
        db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "Student removed"})


@admin_bp.route("/jobs", methods=["GET"])
@role_required("admin")
def list_jobs():
    query = JobPosition.query.join(Company)

    status = (request.args.get("status") or "").strip()
    if status:
        try:
            query = query.filter(JobPosition.status == JobStatus(status))
        except ValueError:
            return jsonify({"error": "Invalid status filter"}), 400

    search = (request.args.get("q") or "").strip()
    if search:
        query = query.filter(JobPosition.title.ilike(f"%{search}%"))

    jobs = query.order_by(JobPosition.created_at.desc()).all()
    return jsonify({"jobs": [_job_dict(j) for j in jobs]})


@admin_bp.route("/jobs/<int:job_id>/approve", methods=["PUT"])
@role_required("admin")
def approve_job(job_id):
    job = JobPosition.query.get_or_404(job_id)
    company = job.company
    if not company or company.approval_status != ApprovalStatus.APPROVED:
        return jsonify({"error": "Company must be approved before approving its jobs"}), 400
    job.status = JobStatus.APPROVED
    db.session.commit()
    return jsonify({"message": "Job posting approved", "job": _job_dict(job)})


@admin_bp.route("/jobs/<int:job_id>/reject", methods=["PUT"])
@role_required("admin")
def reject_job(job_id):
    job = JobPosition.query.get_or_404(job_id)
    job.status = JobStatus.CLOSED
    db.session.commit()
    return jsonify({"message": "Job posting rejected", "job": _job_dict(job)})


@admin_bp.route("/jobs/<int:job_id>", methods=["DELETE"])
@role_required("admin")
def remove_job(job_id):
    job = JobPosition.query.get_or_404(job_id)
    db.session.delete(job)
    db.session.commit()
    return jsonify({"message": "Job posting removed"})


@admin_bp.route("/applications", methods=["GET"])
@role_required("admin")
def list_applications():
    applications = Application.query.order_by(Application.applied_at.desc()).all()
    return jsonify({"applications": [_application_dict(a) for a in applications]})


@admin_bp.route("/applications/<int:application_id>", methods=["GET"])
@role_required("admin")
def get_application_detail(application_id):
    application = Application.query.get_or_404(application_id)
    detail = _application_dict(application)
    detail["feedback"] = application.feedback
    detail["interview_date"] = (
        application.interview_date.isoformat() if application.interview_date else None
    )
    detail["status_history"] = serialize_status_history(application)
    detail["placement"] = (
        serialize_placement(application.placement) if application.placement else None
    )
    return jsonify(
        {
            "application": detail,
            "student": _student_profile_dict(application.student)
            if application.student
            else None,
        }
    )


def _student_profile_dict(student):
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


@admin_bp.route("/students/<int:student_id>", methods=["GET"])
@role_required("admin")
def get_student_detail(student_id):
    student = Student.query.get_or_404(student_id)
    applications = (
        Application.query.filter_by(student_id=student.id)
        .order_by(Application.applied_at.desc())
        .all()
    )
    placements = (
        Placement.query.filter_by(student_id=student.id)
        .order_by(Placement.created_at.desc())
        .all()
    )
    return jsonify(
        {
            "student": _student_profile_dict(student),
            "applications": [_application_dict(a) for a in applications],
            "placements": [serialize_placement(p) for p in placements],
        }
    )


@admin_bp.route("/placements", methods=["GET"])
@role_required("admin")
def list_placements():
    placements = Placement.query.order_by(Placement.created_at.desc()).all()
    return jsonify({"placements": [serialize_placement(p) for p in placements]})
