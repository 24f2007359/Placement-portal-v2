"""
===============================================================================
FILE : backend/company_routes.py
WHAT : every /api/company/* endpoint. jobs, applicants, the status pipeline,
       placements.
WHY  : Milestone 4 (+ M6 history/placements/profile bolted on).

BLUEPRINT: company_bp, url_prefix="/api/company"
FRONTEND COUNTERPART: src/services/company.js <- views/CompanyDashboard.vue

THIS FILE DRIVES THE PIPELINE. it's the only place application statuses change:
    applied -> shortlisted -> interview -> offer -> placed
                                            \\-> rejected
and update_application_status() is the single door all of it goes through.

TWO GATES YOU'LL SEE EVERYWHERE:
  1. _ensure_company_access() -> 403 unless approval_status == APPROVED.
     an unapproved company can log in and hold a valid JWT, but cannot read or
     write a single byte here. that 403 is what draws the yellow banner in the UI.
  2. every query is scoped by company_id from the JWT. a company can never see
     or touch another company's jobs, applicants, or placements. there is no
     route that takes a company_id from the client.
===============================================================================
"""

from datetime import datetime

from flask import Blueprint, g, jsonify, request

from auth_utils import role_required
from cache_utils import NS_JOBS, bump_jobs, cached
from models import (
    Application,
    ApplicationStatus,
    ApprovalStatus,
    Company,
    JobPosition,
    JobStatus,
    Placement,
    Student,
    change_application_status,
    db,
    serialize_placement,
    serialize_status_history,
)

company_bp = Blueprint("company", __name__, url_prefix="/api/company")


def _ensure_company_access():
    """THE APPROVAL GATE. Returns (company, None) or (None, error_tuple).

    called first thing by EVERY route in this file. same two-value pattern as
    student_routes._ensure_student_access():
        company, error_response = _ensure_company_access()
        if error_response:
            return error_response

    blocks you unless ALL of: profile exists, APPROVED, not blacklisted, user active.

    THE 403 BODY IS SPECIAL. it carries `approval_status` and `approved: False`,
    not just an error string. CompanyDashboard.vue's onMounted() sniffs for
    status===403, reads approval_status out of the body, and renders
    "Your company profile is pending" instead of a red error. so this response
    is a UI state, not a failure. don't "simplify" it to a bare message.
    """
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
    """JobPosition -> JSON for the My Jobs table.

    `len(job.applications)` loads the whole relationship just to count it. that's
    an N+1 across the list. fine for a course project; a .count() subquery would
    be the grown-up fix.
    """
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


def _serialize_application(application, include_history=False):
    """Application -> JSON for the Applications table.

    same include_history=False default as the student version: the LIST endpoint
    omits the timeline, the DETAIL endpoint asks for it. that's why the frontend
    fires a second request when you click "Timeline".

    unlike the student flavour, this one exposes the STUDENT's name/contact/email
    (the company needs to reach them) but never the full profile -- that's behind
    the separate, guarded /company/students/<id> route.
    """
    student = application.student
    placement = application.placement
    data = {
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
        "placement": serialize_placement(placement) if placement else None,
    }
    if include_history:
        data["status_history"] = serialize_status_history(application)
    return data


def _serialize_student_profile(student):
    """Full applicant profile for the Profile modal. (Milestone 6)

    NOTE the omission: no is_blacklisted. that's admin-only information; a
    company has no business knowing the institute banned someone. compare with
    admin_routes._student_profile_dict(), which does include it.
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
    }


@company_bp.route("/dashboard", methods=["GET"])
@role_required("company")
def company_dashboard():
    """GET /api/company/dashboard -> the 4 stat cards.

    called by: services/company.js -> getDashboard()

    ALSO THE TRIPWIRE. this is the first call CompanyDashboard.vue makes on
    mount, so for an unapproved company it's the one that returns the 403 that
    flips the pending-approval banner. that's by design.

    the .join(JobPosition) is how we scope applications to this company --
    Application has no company_id of its own, it reaches it through the job.
    """
    company, error_response = _ensure_company_access()
    if error_response:
        return error_response

    # both are lazy Queries -> the .count()s below are SELECT COUNT(*), no rows loaded
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
@cached(NS_JOBS, vary_on_user=True)  # M8. vary_on_user is load-bearing, see below
def list_company_jobs():
    """GET /api/company/jobs?q=&status= -> the "My Jobs" tab.

    !! CACHED, vary_on_user=True IS LOAD-BEARING !! (Milestone 8)
    this only ever returns THIS company's postings. share one key across
    companies and Acme sees Globex's job list. the user id in the key keeps
    them apart.

    the early `return error_response` for an unapproved company is a TUPLE, and
    @cached refuses to cache tuples -- so a 403 never gets stored and later
    served to an approved company. that's not luck, it's the rule in cache_utils.
    """
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
    """POST /api/company/jobs -> 201, a new placement drive.

    called by: services/company.js -> createJob() <- submitJob() when id is null

    !! IT LANDS AS status=PENDING !! (Milestone 6: "only approved companies can
    create placement drives" -- and even then an admin must approve each drive.)
    the company cannot self-approve; there is no code path from here to APPROVED.
    students won't see this job until admin_routes.approve_job() runs.

    company_id comes from the JWT, never the request body -- you can't post a
    job on someone else's behalf.

    .replace("Z", "+00:00") because python's fromisoformat() choked on a trailing
    Z until 3.11, and the frontend's toISOString() always emits one.
    """
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
    bump_jobs()  # M8: new posting -> company + admin job lists are stale
    return jsonify({"message": "Job posted and sent for admin approval", "job": _serialize_job(job)}), 201


@company_bp.route("/jobs/<int:job_id>", methods=["PUT"])
@role_required("company")
def update_job(job_id):
    """PUT /api/company/jobs/<id> -> edit details AND/OR flip status.

    called by: services/company.js -> updateJob(), from BOTH
      submitJob()      (edit fields)
      changeJobStatus() (send just {status: 'active'|'closed'})

    filter_by(id=..., company_id=...) is the ownership check -- editing another
    company's job gives a 404, not a 403.

    same "key present?" partial-update pattern as the student profile route.
    """
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

    # --- the status flip. TWO rules, both important. ---
    if "status" in data:
        status_raw = (data.get("status") or "").strip().lower()
        # rule 1: a company may only ever set ACTIVE or CLOSED. it can never set
        # PENDING or APPROVED -- those belong to the admin. so a company can't
        # rubber-stamp its own drive.
        allowed_statuses = {JobStatus.ACTIVE.value, JobStatus.CLOSED.value}
        if status_raw not in allowed_statuses:
            return jsonify({"error": "Status can only be active or closed"}), 400
        # rule 2: no pending -> active shortcut. you must go through admin
        # approval first. this is the line that makes the whole approval gate
        # meaningful; without it a company would just activate its own posting.
        # (CompanyDashboard.vue hides "Set Active" unless status==='approved',
        #  but that's cosmetic -- THIS is the enforcement.)
        if job.status == JobStatus.PENDING and status_raw == JobStatus.ACTIVE.value:
            return jsonify({"error": "Pending jobs must be approved by admin before activation"}), 400
        job.status = JobStatus(status_raw)

    db.session.commit()
    # M8: title/salary edits AND status flips (active/closed) both change what
    # students see in _approved_jobs_query(). closing a job must remove it from
    # every student's cached Browse Jobs list immediately.
    bump_jobs()
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


@company_bp.route("/applications/<int:application_id>", methods=["GET"])
@role_required("company")
def get_company_application(application_id):
    company, error_response = _ensure_company_access()
    if error_response:
        return error_response

    application = (
        Application.query.join(JobPosition)
        .filter(Application.id == application_id, JobPosition.company_id == company.id)
        .first_or_404()
    )
    return jsonify(
        {
            "application": _serialize_application(application, include_history=True),
            "student": _serialize_student_profile(application.student)
            if application.student
            else None,
        }
    )


@company_bp.route("/students/<int:student_id>", methods=["GET"])
@role_required("company")
def view_student_profile(student_id):
    """GET /api/company/students/<id> -> full applicant profile. (Milestone 6)

    called by: services/company.js -> getStudent() <- the Profile modal

    !! THE SECURITY BIT !! we do NOT just Student.query.get(student_id). that
    would let any approved company walk 1,2,3... and scrape every student in the
    institute.

    instead: prove they applied to one of OUR jobs first. the join + double
    filter is that proof. no application -> 404, and we never confirm the
    student exists at all.

    (Milestone 6: "Admin and Company can view student profiles" -- for a company
    that's scoped to its own applicants.)
    """
    company, error_response = _ensure_company_access()
    if error_response:
        return error_response

    # A company may only view profiles of students who applied to one of its jobs.
    application = (
        Application.query.join(JobPosition)
        .filter(JobPosition.company_id == company.id, Application.student_id == student_id)
        .first()
    )
    if not application:
        return jsonify({"error": "No applicant found with this student id"}), 404

    return jsonify({"student": _serialize_student_profile(application.student)})


@company_bp.route("/placements", methods=["GET"])
@role_required("company")
def list_company_placements():
    company, error_response = _ensure_company_access()
    if error_response:
        return error_response

    placements = (
        Placement.query.filter_by(company_id=company.id)
        .order_by(Placement.created_at.desc())
        .all()
    )
    return jsonify({"placements": [serialize_placement(p) for p in placements]})


@company_bp.route("/applications/<int:application_id>/status", methods=["PUT"])
@role_required("company")
def update_application_status(application_id):
    """PUT /api/company/applications/<id>/status -> THE PIPELINE DOOR.

    called by: services/company.js -> updateApplicationStatus(), from BOTH
      setApplicationStatus()  (Shortlist / Interview / Offer / Reject buttons)
      confirmPlacement()      (the Record Placement modal, status='placed')

    body: { status, feedback?, interview_date?, position?, salary?, joining_date? }

    the only place in the codebase an ApplicationStatus ever changes. that's not
    an accident -- it means EVERY transition gets an audit-trail row, because
    they all funnel through change_application_status().

    THREE SIDE EFFECTS, in order:
      1. feedback / interview_date get written onto the Application.
         interview_date is what the M7 daily celery job scans to send reminders.
      2. if the status actually CHANGED, log a history row (M6). the
         `if application.status != new_status` guard stops a re-click from
         spamming the timeline with identical entries.
      3. if the new status is offer|placed, upsert the Placement row.

    ownership: the join + company_id filter. someone else's application -> 404.

    NOTE the ordering: we mutate feedback/interview_date BEFORE calling
    change_application_status(), but everything shares one commit at the end, so
    it's all atomic. if _upsert_placement bails with a 400, nothing is saved.
    """
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
    # note: APPLIED is NOT in here. only a student creates that, by applying.
    # a company can't reset someone back to "applied".
    allowed_statuses = {
        ApplicationStatus.SHORTLISTED.value,
        ApplicationStatus.INTERVIEW.value,
        ApplicationStatus.OFFER.value,
        ApplicationStatus.PLACED.value,  # added in M6
        ApplicationStatus.REJECTED.value,
    }
    if status_raw not in allowed_statuses:
        return (
            jsonify(
                {"error": "Invalid status. Use shortlisted, interview, offer, placed, or rejected"}
            ),
            400,
        )

    # nothing enforces the ORDER. you can jump applied -> offer. the history
    # table records whatever actually happened, which is the honest thing to do.
    new_status = ApplicationStatus(status_raw)

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

    # the feedback doubles as the history entry's note -- "why did they move?"
    note = (data.get("feedback") or "").strip() or None

    # guard: only log when it ACTUALLY moved. re-clicking Shortlist on an
    # already-shortlisted candidate updates their feedback but doesn't spam the
    # timeline with a shortlisted->shortlisted row.
    if application.status != new_status:
        change_application_status(  # models.py: sets status AND writes history
            application,
            new_status,
            changed_by_role="company",
            changed_by_user_id=g.current_user.id,
            note=note,
        )

    # Create/refresh a Placement record when a candidate is offered or placed.
    # returns an error tuple (not raises) on a bad joining_date -> bail before
    # commit, so nothing at all is saved.
    if new_status in (ApplicationStatus.OFFER, ApplicationStatus.PLACED):
        error = _upsert_placement(company, application, data)
        if error:
            return error

    db.session.commit()  # status + history + placement, all one transaction
    return jsonify(
        {
            "message": "Application status updated",
            "application": _serialize_application(application, include_history=True),
        }
    )


def _upsert_placement(company, application, data):
    """Create or update the Placement tied to an offered/placed application.

    "upsert" = UPDATE if it exists, INSERT if not. Application <-> Placement is
    1:1 (uselist=False + a unique FK), so a candidate who goes offer -> placed
    must NOT end up with two placement rows. hence the create-or-update branch.

    called ONLY by update_application_status(), when the new status is offer|placed.

    returns None on success, or a flask (jsonify, 400) tuple on a bad date. it
    RETURNS rather than raises so the caller can bail out before commit -- and
    since nothing is committed yet, sqlalchemy just discards the pending changes.

    DEFAULTS when HR leaves fields blank:
      position -> the job title (right ~99% of the time)
      salary   -> the job's advertised salary_max
    the Place modal in the UI lets them override both.

    the `if salary is not None` / `if joining_date is not None` on the UPDATE
    path is deliberate: marking someone 'offer' (no placement fields sent) and
    then 'placed' (with them) must not wipe values set earlier. only overwrite
    what was actually supplied.

    note joining_date is a DATE not a datetime -> .date() strips the time.
    """
    job = application.job_position
    placement = application.placement

    position = (data.get("position") or "").strip() or (job.title if job else "Position")
    salary = data.get("salary")
    if salary in (None, ""):  # "" comes from an empty number input
        salary = job.salary_max if job else None

    joining_date = None
    # the double .get() guards against joining_date being None (json null),
    # which would explode on .strip()
    joining_raw = (data.get("joining_date") or "").strip() if data.get("joining_date") else ""
    if joining_raw:
        try:
            joining_date = datetime.fromisoformat(joining_raw.replace("Z", "+00:00")).date()
        except ValueError:
            return jsonify({"error": "Invalid joining date format"}), 400

    if placement is None:
        # INSERT path -- first time this candidate hit offer or placed
        placement = Placement(
            student_id=application.student_id,
            company_id=company.id,
            application_id=application.id,
            position=position,
            salary=salary,
            joining_date=joining_date,
        )
        db.session.add(placement)
    else:
        # UPDATE path -- they were already 'offer', now they're 'placed'.
        # only overwrite what was actually sent (see docstring).
        placement.position = position
        if salary is not None:
            placement.salary = salary
        if joining_date is not None:
            placement.joining_date = joining_date

    return None  # no error
