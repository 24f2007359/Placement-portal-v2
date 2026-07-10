"""
===============================================================================
FILE : backend/admin_routes.py
WHAT : every /api/admin/* endpoint. approvals, user management, oversight.
WHY  : Milestone 3 (+ M6 detail/history/placements views).

BLUEPRINT: admin_bp, url_prefix="/api/admin"
FRONTEND COUNTERPART: src/services/admin.js <- views/AdminDashboard.vue

(the M7 job triggers -- /api/admin/reports, /api/admin/reminders -- live in
 export_routes.py, NOT here, because they share the celery polling machinery.)

ADMIN IS THE GATEKEEPER. two chains of consequence run through this file:
  approve_company()  -> unlocks the company's dashboard (_ensure_company_access)
  approve_job()      -> makes the drive visible to students (_approved_jobs_query)
and approve_job() refuses unless the parent company is already approved, so you
can't sneak a drive in under an unapproved company.

NO _ensure_admin_access() HELPER HERE. unlike students/companies, an admin has
no profile row and no blacklist flag -- @role_required("admin") plus the
is_active check inside get_current_user() is the whole gate.

DESTRUCTIVE ROUTES: the DELETEs really do delete. cascades on the relationships
handle the children (jobs, applications, history); placements are cleared by
hand first because they deliberately have no cascade.
===============================================================================
"""

from flask import Blueprint, jsonify, request

from auth_utils import role_required
from cache_utils import (
    NS_COMPANIES,
    NS_JOBS,
    NS_STUDENTS,
    bump_companies,
    bump_jobs,
    bump_students,
    cached,
)
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


# --- serializers. small and dumb on purpose; the admin tables are flat. -------


def _company_dict(company):
    """Company -> JSON row for the Companies tab.
    exposes is_blacklisted + is_active, which the company itself never sees."""
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
    """GET /api/admin/dashboard -> the stat cards + the approval-queue counters.

    called by: services/admin.js -> getDashboard()

    pending_companies / pending_jobs are the ones that matter -- they're the
    admin's actual TODO list. everything else is vanity metrics.
    all plain COUNT(*)s, no rows loaded.
    """
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
@cached(NS_COMPANIES)  # M8: company search. shared key -- see below.
def list_companies():
    """GET /api/admin/companies?q=&industry=&status= -> the Companies tab.

    !! CACHED, vary_on_user=False !! (Milestone 8)
    unlike the job lists, this body is IDENTICAL for every caller -- there's
    exactly one admin, and the response doesn't depend on who's asking. so all
    admins share one entry per query-string. no user id in the key.

    the ?q=/?industry=/?status= args are hashed into the key, so each distinct
    search is its own entry.

    invalidated by: register_company, approve, reject, blacklist, remove.
    """
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
    """PUT .../approve -> THE UNLOCK. company can now use its dashboard.

    also un-blacklists and re-activates the login, so Approve doubles as
    "undo a blacklist". that's why it clears both flags, not just the status.
    knock-on: only now can approve_job() succeed for any of their drives.
    """
    company = Company.query.get_or_404(company_id)
    company.approval_status = ApprovalStatus.APPROVED
    company.is_blacklisted = False
    if company.user:  # guard: profile could exist with a deleted user row
        company.user.is_active = True
    db.session.commit()
    # M8: BOTH namespaces. obvious -> the companies list changed. subtle ->
    # approving a company makes its APPROVED jobs visible to students, because
    # _approved_jobs_query() filters on the company's status. miss bump_jobs()
    # here and students keep seeing a stale "no jobs" list for up to 60s.
    bump_companies()
    bump_jobs()
    return jsonify({"message": "Company approved", "company": _company_dict(company)})


@admin_bp.route("/companies/<int:company_id>/reject", methods=["PUT"])
@role_required("admin")
def reject_company(company_id):
    """PUT .../reject -> SOFT no. they can still log in, just get the 403 banner.
    reversible: approve_company() undoes it. does NOT touch is_active."""
    company = Company.query.get_or_404(company_id)
    company.approval_status = ApprovalStatus.REJECTED
    db.session.commit()
    bump_companies()
    bump_jobs()  # M8: their jobs must vanish from student search right now
    return jsonify({"message": "Company rejected", "company": _company_dict(company)})


@admin_bp.route("/companies/<int:company_id>/blacklist", methods=["PUT"])
@role_required("admin")
def blacklist_company(company_id):
    """PUT .../blacklist -> HARD no. strictly worse than reject:

      is_blacklisted=True -> their jobs vanish from student search
                             (_approved_jobs_query filters on it)
      approval_status=REJECTED -> dashboard 403
      user.is_active=False -> LOGIN itself now fails, and every existing JWT
                             they hold dies on the next request
                             (auth_utils.get_current_user re-checks is_active)

    nothing is deleted. reversible via approve_company().
    """
    company = Company.query.get_or_404(company_id)
    company.is_blacklisted = True
    company.approval_status = ApprovalStatus.REJECTED
    if company.user:
        company.user.is_active = False
    db.session.commit()
    bump_companies()
    bump_jobs()  # M8: blacklisting must pull their drives from student view NOW
    return jsonify({"message": "Company blacklisted", "company": _company_dict(company)})


@admin_bp.route("/companies/<int:company_id>", methods=["DELETE"])
@role_required("admin")
def remove_company(company_id):
    """DELETE /api/admin/companies/<id> -> IRREVERSIBLE. gone.

    AdminDashboard.vue confirm()s before calling this.

    ORDER MATTERS:
      1. placements first, by hand. Company.placements has NO cascade (they're
         historical records we didn't want auto-deleted), so leaving them would
         violate the company_id FK.
      2. delete the company -> cascade takes its job_positions -> cascade takes
         each job's applications -> cascade takes each application's
         status_history. one line, four tables.
      3. delete the User row too, else an orphan login lingers.

    .delete() on a Query issues a bulk DELETE, bypassing the ORM's per-object
    cascade -- which is exactly what we want for step 1 (fast, no cascade).
    """
    company = Company.query.get_or_404(company_id)

    Placement.query.filter_by(company_id=company.id).delete()
    user = company.user
    db.session.delete(company)  # cascades: jobs -> applications -> history
    if user:
        db.session.delete(user)
    db.session.commit()
    bump_companies()
    bump_jobs()  # M8: the cascade took their jobs with them
    return jsonify({"message": "Company removed"})


@admin_bp.route("/students", methods=["GET"])
@role_required("admin")
@cached(NS_STUDENTS)  # M8: student search. shared key, same reasoning as companies.
def list_students():
    """GET /api/admin/students?q= -> the Students tab.

    ONE search box, THREE columns (name OR institute_id OR contact) via db.or_().
    Milestone 3 asked for "search students by name / ID / contact" -- this is it.
    ilike + %...% = case-insensitive substring.

    CACHED (M8), vary_on_user=False -- body is the same for any admin.
    invalidated by: register_student, student profile update, blacklist,
    deactivate, activate, remove.
    """
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
    bump_students()  # M8
    return jsonify({"message": "Student blacklisted", "student": _student_dict(student)})


@admin_bp.route("/students/<int:student_id>/deactivate", methods=["PUT"])
@role_required("admin")
def deactivate_student(student_id):
    student = Student.query.get_or_404(student_id)
    if student.user:
        student.user.is_active = False
    db.session.commit()
    bump_students()  # M8
    return jsonify({"message": "Student deactivated", "student": _student_dict(student)})


@admin_bp.route("/students/<int:student_id>/activate", methods=["PUT"])
@role_required("admin")
def activate_student(student_id):
    """PUT .../activate -> undo a deactivate.

    !! REFUSES on a blacklisted student. !! that's the asymmetry:
    deactivate is a reversible pause, blacklist is a one-way door. to undo a
    blacklist you'd have to clear the flag directly in the db.
    AdminDashboard.vue mirrors this by only rendering Activate when
    (!is_active && !is_blacklisted).
    """
    student = Student.query.get_or_404(student_id)
    if student.is_blacklisted:
        return jsonify({"error": "Cannot activate a blacklisted student"}), 400
    if student.user:
        student.user.is_active = True
    db.session.commit()
    bump_students()  # M8
    return jsonify({"message": "Student activated", "student": _student_dict(student)})


@admin_bp.route("/students/<int:student_id>", methods=["DELETE"])
@role_required("admin")
def remove_student(student_id):
    """DELETE /api/admin/students/<id> -> IRREVERSIBLE.

    same shape as remove_company(): placements by hand first (no cascade on that
    relationship), then the student -> cascade takes their applications ->
    cascade takes each application's status_history. then the User row.
    """
    student = Student.query.get_or_404(student_id)

    Placement.query.filter_by(student_id=student.id).delete()
    user = student.user
    db.session.delete(student)  # cascades: applications -> status_history
    if user:
        db.session.delete(user)
    db.session.commit()
    bump_students()
    bump_jobs()  # M8: their applications went too -> applications_count changed
    return jsonify({"message": "Student removed"})


@admin_bp.route("/jobs", methods=["GET"])
@role_required("admin")
@cached(NS_JOBS)  # M8: same body for any admin -> shared key
def list_jobs():
    """GET /api/admin/jobs?q=&status= -> every company's postings.

    CACHED (M8), vary_on_user=False. shares the NS_JOBS namespace with the
    student/company job lists, so ANY job write invalidates all three at once.
    that's the right coarseness -- three separate namespaces would mean three
    bumps per write and a real chance of forgetting one.
    """
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
    """PUT .../approve -> THE SECOND GATE. the drive becomes visible to students.

    !! THE GUARD IS THE POINT !! we refuse to approve a job whose company isn't
    itself approved. that's Milestone 6's "ensure only approved companies can
    create placement drives" -- enforced here rather than at creation time, so a
    company can draft jobs while its own approval is still pending.

    after this, _approved_jobs_query() starts returning the job, so students can
    see and apply. the company may now also flip it to ACTIVE.
    """
    job = JobPosition.query.get_or_404(job_id)
    company = job.company
    if not company or company.approval_status != ApprovalStatus.APPROVED:
        return jsonify({"error": "Company must be approved before approving its jobs"}), 400
    job.status = JobStatus.APPROVED
    db.session.commit()
    # M8: THE headline invalidation. the drive is now visible to every student.
    # without this bump they'd keep getting the cached "not there yet" list.
    bump_jobs()
    return jsonify({"message": "Job posting approved", "job": _job_dict(job)})


@admin_bp.route("/jobs/<int:job_id>/reject", methods=["PUT"])
@role_required("admin")
def reject_job(job_id):
    """PUT .../reject -> we REUSE JobStatus.CLOSED as "rejected".

    there's no dedicated REJECTED value in JobStatus, and we don't need one:
    both mean "students can't see it" (_approved_jobs_query only lets through
    approved|active). saves an enum value; slightly lossy, since you can't later
    tell a rejected drive from one the company closed itself.
    """
    job = JobPosition.query.get_or_404(job_id)
    job.status = JobStatus.CLOSED
    db.session.commit()
    bump_jobs()  # M8
    return jsonify({"message": "Job posting rejected", "job": _job_dict(job)})


@admin_bp.route("/jobs/<int:job_id>", methods=["DELETE"])
@role_required("admin")
def remove_job(job_id):
    """DELETE a posting. cascade takes its applications and their history rows.

    no manual Placement cleanup needed here -- Placement.application_id is
    nullable, so an orphaned placement just loses its link. the hire still
    happened; we keep the record.
    """
    job = JobPosition.query.get_or_404(job_id)
    db.session.delete(job)
    db.session.commit()
    bump_jobs()  # M8
    return jsonify({"message": "Job posting removed"})


@admin_bp.route("/applications", methods=["GET"])
@role_required("admin")
def list_applications():
    """GET /api/admin/applications -> EVERY application in the system.

    no filters, no scoping -- admin sees all. read-only: there is no admin route
    to change an application's status. that's the company's call.
    """
    applications = Application.query.order_by(Application.applied_at.desc()).all()
    return jsonify({"applications": [_application_dict(a) for a in applications]})


@admin_bp.route("/applications/<int:application_id>", methods=["GET"])
@role_required("admin")
def get_application_detail(application_id):
    """GET /api/admin/applications/<id> -> the History modal. (Milestone 6)

    called by: services/admin.js -> getApplication() <- openApplicationDetail()

    returns { application: {...,status_history, placement}, student: {...} }
    -- ONE request fills both the applicant summary line AND the timeline.

    plain .get_or_404(): no ownership filter, because admin owns everything.
    """
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
    """Full student profile for admin eyes.

    same as company_routes._serialize_student_profile() EXCEPT it also exposes
    is_blacklisted. companies don't get to see that; the institute does.
    (defined below its first use -- python resolves names at call time, so this
    is legal, if a bit rude to the reader.)
    """
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
    """GET /api/admin/students/<id> -> profile + ALL their applications + placements.

    (Milestone 6: "Admin and Company can view student profiles and applications".)
    the whole 360 view in one request. no ownership guard -- unlike the company
    version, which has to prove the student applied to one of its jobs first.
    """
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
