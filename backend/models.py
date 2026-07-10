"""
===============================================================================
FILE : backend/models.py
WHAT : the entire database schema (6 tables) + a few shared serializer helpers.
WHY  : one file, one source of truth. every route file imports from here.

USED BY: literally everything -- app.py, seed_admin.py, all *_routes.py,
         celery_app.py, tasks.py

THE SHAPE OF THE DATA:
    User (1:1) Company (1:n) JobPosition (1:n) Application (1:1) Placement
    User (1:1) Student (1:n) Application (1:n) ApplicationStatusHistory

  User        -> unified login table. ONE table for all 3 roles, told apart by
                 the `role` enum. admins have no profile row at all.
  Company     -> profile. needs admin approval before it can do anything.
  Student     -> profile. self-serve, no approval.
  JobPosition -> a placement drive. needs admin approval before students see it.
  Application -> student applied to a job. UNIQUE(student_id, job_id).
  Placement   -> the final "you're hired" record. created on offer/placed. (M6)
  ApplicationStatusHistory -> audit trail, one row per status change. (M6)

WHY ENUMS AND NOT PLAIN STRINGS? sqlalchemy validates on write, so a typo like
status="shortlited" raises instead of silently rotting in the db. cost: adding a
new enum value means altering the column in postgres (sqlite doesn't care).
===============================================================================
"""

import enum
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

# ONE global db object, bound to an app later via db.init_app(app).
# app.py binds the web app; celery_app.py binds its own context-only app.
# flask-sqlalchemy is fine with the same db serving multiple apps.
db = SQLAlchemy()


def _utcnow():
    """default= for every created_at. ALWAYS UTC, never local time.

    passed as a FUNCTION REFERENCE (default=_utcnow, no parens!). pass
    _utcnow() and python evaluates it once at import, and every row gets the
    same frozen timestamp. classic bug.

    note: sqlite strips the tzinfo on the way back out, so what you read is
    naive-UTC. tasks.py::_as_naive() exists to paper over exactly this.
    """
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# ENUMS. `.value` gives the lowercase string that goes over the wire / into
# the db; the NAME (UserRole.ADMIN) is what you use in python.
# ---------------------------------------------------------------------------


class UserRole(enum.Enum):
    """who you are. set at registration, never changes."""

    ADMIN = "admin"
    COMPANY = "company"
    STUDENT = "student"


class ApprovalStatus(enum.Enum):
    """a COMPANY's standing. pending -> approved (admin) or rejected."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class JobStatus(enum.Enum):
    """a JOB POSTING's lifecycle.

    pending  -> just posted, invisible to students
    approved -> admin okayed it, students can see + apply
    active   -> company flipped it live (approved and active both count as
                "students may apply", see _approved_jobs_query)
    closed   -> done, or admin-rejected (we reuse CLOSED for rejection)
    """

    PENDING = "pending"
    APPROVED = "approved"
    ACTIVE = "active"
    CLOSED = "closed"


class ApplicationStatus(enum.Enum):
    """the recruitment pipeline. companies drive these transitions.

        applied -> shortlisted -> interview -> offer -> placed
                                                  \\-> rejected

    nothing enforces that order in the db -- company_routes just accepts any of
    shortlisted/interview/offer/placed/rejected. the ORDER is a convention,
    the HISTORY table is what actually records what really happened.
    """

    APPLIED = "applied"
    SHORTLISTED = "shortlisted"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    PLACED = "placed"


class User(db.Model):
    """The single login table for all three roles.

    one table + a role column beats three separate login tables: one /api/auth/login
    route, one JWT shape, one uniqueness rule on email across the whole system.

    admins live here with NO profile row hanging off them. companies/students get
    a matching Company/Student row (1:1).
    """

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    # unique -> the db itself blocks duplicate signups (routes.py checks first
    # for a nice 409, but this is the real guarantee under a race).
    # index -> every login does a lookup by email.
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    # 256 chars because werkzeug's scrypt hashes are long. NEVER the plaintext.
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.Enum(UserRole), nullable=False)
    # the kill switch. auth_utils.get_current_user() re-reads this on EVERY
    # request, so flipping it False instantly invalidates a live JWT.
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    # uselist=False turns "a list of Companies" into "one Company or None".
    # that's what makes user.company work instead of user.company[0].
    # for an admin BOTH of these are None -- always guard before touching them.
    company = db.relationship("Company", back_populates="user", uselist=False)
    student = db.relationship("Student", back_populates="user", uselist=False)

    def set_password(self, password):
        """Hash and store. call this, never assign password_hash by hand.
        used by: routes.py register_*, seed_admin.py"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Constant-time compare against the stored hash. used by routes.py login().
        werkzeug reads the algorithm+salt out of the stored string, so old hashes
        keep working if you ever change the default algorithm."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        # only ever shows up in the shell / debugger. handy, not load-bearing.
        return f"<User {self.email} ({self.role.value})>"


class Company(db.Model):
    """Recruiter profile. GATED: useless until an admin approves it."""

    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    # unique on the FK is what makes this 1:1 rather than 1:n. one User = one Company.
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False, index=True)  # indexed: admin searches it
    industry = db.Column(db.String(100))
    location = db.Column(db.String(150))
    website = db.Column(db.String(200))
    # if this looks like an email, tasks.py mails the monthly PDF report here.
    # otherwise it falls back to user.email.
    hr_contact = db.Column(db.String(120))
    description = db.Column(db.Text)

    # THE GATE. company_routes._ensure_company_access() 403s anything not APPROVED.
    approval_status = db.Column(
        db.Enum(ApprovalStatus), default=ApprovalStatus.PENDING, nullable=False
    )
    # harsher than rejected. also hides their jobs from student search.
    is_blacklisted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    user = db.relationship("User", back_populates="company")
    # cascade delete-orphan: nuking a company nukes its job postings, and
    # (transitively) their applications. that's why admin remove_company works.
    job_positions = db.relationship(
        "JobPosition", back_populates="company", cascade="all, delete-orphan"
    )
    # NO cascade here on purpose -- placements are historical records. admin
    # remove_company() deletes them explicitly, by hand, first.
    placements = db.relationship("Placement", back_populates="company")

    def __repr__(self):
        return f"<Company {self.name}>"


class Student(db.Model):
    """Candidate profile. NOT gated -- students are usable the second they register."""

    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    full_name = db.Column(db.String(150), nullable=False, index=True)
    # nullable BUT unique -> optional roll number, yet no two students can share
    # one. sqlite allows many NULLs in a unique column, which is what we want.
    institute_id = db.Column(db.String(50), unique=True, index=True)
    contact = db.Column(db.String(20))

    # --- THE ELIGIBILITY TRIO ---
    # student_routes._check_eligibility() tests these against the job's
    # eligibility_branch / eligibility_cgpa / eligibility_year on Apply.
    # all nullable, so a half-filled profile just can't apply to gated jobs.
    branch = db.Column(db.String(100))
    cgpa = db.Column(db.Float)
    graduation_year = db.Column(db.Integer)

    # free text, comma-separated by convention. student search does an ILIKE on
    # skills, which is why it's Text and not a proper tags table -- good enough.
    skills = db.Column(db.Text)
    education = db.Column(db.Text)
    experience = db.Column(db.Text)
    # server-side filesystem path, NOT a URL. instance/uploads/resumes/...
    resume_path = db.Column(db.String(300))

    is_blacklisted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    user = db.relationship("User", back_populates="student")
    # cascade -> deleting a student deletes their applications (and, via
    # Application's own cascade, that application's status history).
    applications = db.relationship(
        "Application", back_populates="student", cascade="all, delete-orphan"
    )
    placements = db.relationship("Placement", back_populates="student")

    def __repr__(self):
        return f"<Student {self.full_name}>"


class JobPosition(db.Model):
    """A placement drive. GATED: pending until an admin approves it."""

    __tablename__ = "job_positions"

    id = db.Column(db.Integer, primary_key=True)
    # indexed: every company query filters on this
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text)
    # both nullable -> "salary negotiable" is a legal posting.
    # also: salary_max is what tasks._upsert_placement() uses as the default
    # placement salary if HR doesn't type one in.
    salary_min = db.Column(db.Integer)
    salary_max = db.Column(db.Integer)
    skills_required = db.Column(db.Text)
    experience_required = db.Column(db.String(100))

    # --- ELIGIBILITY RULES (all optional; null = no restriction) ---
    # eligibility_branch is a COMMA-SEPARATED list, case-insensitive, and the
    # magic word "all" lets everyone through. see _check_eligibility().
    eligibility_branch = db.Column(db.String(200))
    eligibility_cgpa = db.Column(db.Float)  # minimum
    eligibility_year = db.Column(db.Integer)  # exact match, not minimum

    benefits = db.Column(db.Text)
    # naive datetime. student_routes strips tzinfo before comparing -- see the
    # deadline check in apply_for_job().
    application_deadline = db.Column(db.DateTime)
    # starts PENDING. admin -> APPROVED. company -> ACTIVE or CLOSED.
    status = db.Column(db.Enum(JobStatus), default=JobStatus.PENDING, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    company = db.relationship("Company", back_populates="job_positions")
    # delete a job -> its applications go too (and their history rows, via
    # Application's cascade). so admin remove_job() is a one-liner.
    applications = db.relationship(
        "Application", back_populates="job_position", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<JobPosition {self.title}>"


class Application(db.Model):
    """A student applied to a job. The join table with a life of its own."""

    __tablename__ = "applications"
    # !! THE DUPLICATE-APPLICATION GUARD (Milestone 6 requirement) !!
    # student_routes.apply_for_job() ALSO checks for an existing row first, for a
    # friendly 409. this constraint is the real backstop: two simultaneous
    # requests both pass the check, then one COMMIT loses and raises
    # IntegrityError, which the route catches and turns into the same 409.
    # belt AND braces. never rely on the app-level check alone.
    __table_args__ = (
        db.UniqueConstraint("student_id", "job_id", name="uq_student_job_application"),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    job_id = db.Column(db.Integer, db.ForeignKey("job_positions.id"), nullable=False, index=True)
    # the CURRENT state. the full path taken to get here lives in status_history.
    status = db.Column(
        db.Enum(ApplicationStatus), default=ApplicationStatus.APPLIED, nullable=False
    )
    applied_at = db.Column(db.DateTime, default=_utcnow, nullable=False)
    # last message the company left. shown to the student, and copied into the
    # history row's `note` on each transition.
    feedback = db.Column(db.Text)
    # set when status -> interview. THE M7 REMINDER JOB SCANS THIS COLUMN:
    # tasks.send_interview_reminders() looks for status==INTERVIEW and this
    # date landing in the next 24h. no date = no reminder email.
    interview_date = db.Column(db.DateTime)

    student = db.relationship("Student", back_populates="applications")
    job_position = db.relationship("JobPosition", back_populates="applications")
    # uselist=False -> 1:1. an application yields at most ONE placement, which is
    # why _upsert_placement() can safely update-in-place instead of duplicating.
    placement = db.relationship("Placement", back_populates="application", uselist=False)
    # order_by in the relationship means the timeline arrives pre-sorted, so
    # serialize_status_history() doesn't have to sort it.
    status_history = db.relationship(
        "ApplicationStatusHistory",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationStatusHistory.created_at",
    )

    def __repr__(self):
        return f"<Application student={self.student_id} job={self.job_id}>"


class ApplicationStatusHistory(db.Model):
    """Audit trail: one row per application status change (Milestone 6).

    THE POINT: `Application.status` only tells you where a candidate is NOW.
    this table tells you how they got there, when, and who did it. that's the
    whole "complete application history" requirement of M6.

    written by: models.change_application_status() and log_application_status()
    read by   : models.serialize_status_history() -> the Timeline modals

    append-only. nothing ever updates or deletes a row here (except the cascade
    when the parent application is deleted).
    """

    __tablename__ = "application_status_history"

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(
        db.Integer, db.ForeignKey("applications.id"), nullable=False, index=True
    )
    # NULL only on the very first row (the "applied" one) -- there's no previous
    # state to come from. the UI uses that to hide the "from x" label.
    from_status = db.Column(db.Enum(ApplicationStatus))  # null for the first "applied" entry
    to_status = db.Column(db.Enum(ApplicationStatus), nullable=False)
    # stored as a plain string, not the UserRole enum, so it survives the user
    # being deleted later. same reason changed_by_user_id has no cascade.
    changed_by_role = db.Column(db.String(20))  # admin / company / student
    changed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    # usually the feedback the company typed on that transition
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    application = db.relationship("Application", back_populates="status_history")

    def __repr__(self):
        return f"<StatusHistory app={self.application_id} -> {self.to_status.value}>"


class Placement(db.Model):
    """The "you're hired" record. Created when a company marks offer or placed.

    existed since M1 but NOTHING ever wrote a row until M6 wired up
    company_routes._upsert_placement().
    """

    __tablename__ = "placements"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    # unique + nullable -> at most one Placement per Application (the 1:1), but a
    # placement could theoretically be recorded without one (off-portal hire).
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id"), unique=True)
    # required. defaults to the job title if HR doesn't override it.
    position = db.Column(db.String(200), nullable=False)
    salary = db.Column(db.Integer)
    # db.Date not DateTime -- nobody joins at 14:32.
    joining_date = db.Column(db.Date)
    # if set, student_routes.download_offer_letter() serves this real file.
    # if null, it generates a plain-text letter on the fly instead.
    offer_letter_path = db.Column(db.String(300))
    # tasks.py buckets placements into months using THIS for the monthly report.
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    student = db.relationship("Student", back_populates="placements")
    company = db.relationship("Company", back_populates="placements")
    application = db.relationship("Application", back_populates="placement")

    def __repr__(self):
        return f"<Placement student={self.student_id} company={self.company_id}>"


# ===========================================================================
# MILESTONE 6 HELPERS: status tracking + history
#
# these live in models.py (not in a route file) because ALL THREE route files
# plus tasks.py need them. putting them in, say, company_routes.py would mean
# admin_routes.py importing from company_routes.py, which is gross.
# ===========================================================================


def log_application_status(
    application,
    to_status,
    from_status=None,
    changed_by_role=None,
    changed_by_user_id=None,
    note=None,
):
    """Append a status-history row for an application.

    Only stages the row on the session (no commit) so callers can commit it
    together with the status change in one transaction.

    NO COMMIT IN HERE. that's deliberate. the caller commits once, so the status
    change and its history row land atomically -- you can never end up with a
    status that has no matching audit entry.

    called directly by: student_routes.apply_for_job() for the very first
    "applied" row (from_status stays None -- there's no previous state).
    everyone else goes through change_application_status() below.

    note we pass `application=` (the object) not `application_id=`. sqlalchemy
    then wires up the FK for us even if the parent hasn't been INSERTed yet and
    has no id. that's what lets apply_for_job() add both rows before commit.
    """
    entry = ApplicationStatusHistory(
        application=application,
        from_status=from_status,
        to_status=to_status,
        changed_by_role=changed_by_role,
        changed_by_user_id=changed_by_user_id,
        note=note,
    )
    db.session.add(entry)
    return entry


def change_application_status(
    application, new_status, changed_by_role=None, changed_by_user_id=None, note=None
):
    """Update an application's status and record the transition in history.

    THE ONE FUNCTION every status change should go through. it snapshots the old
    status BEFORE overwriting it, so from_status is correct.

    used by: company_routes.update_application_status()

    if you ever set `application.status = X` by hand anywhere, you've silently
    broken the audit trail. don't.
    """
    old_status = application.status  # grab it first! next line clobbers it.
    application.status = new_status
    return log_application_status(
        application,
        to_status=new_status,
        from_status=old_status,
        changed_by_role=changed_by_role,
        changed_by_user_id=changed_by_user_id,
        note=note,
    )


def serialize_status_history(application):
    """Return the status timeline for an application.

    Falls back to a synthetic "applied" entry for legacy applications created
    before history tracking existed (so old data still renders a timeline).

    THE FALLBACK IS THE INTERESTING BIT. applications created in M1-M5 have zero
    history rows, because the table didn't exist yet. rather than run a data
    migration (or show an empty modal), we fabricate the one row we KNOW is
    true: they applied, at applied_at. no lying, no backfill script.

    read by: student/company/admin _serialize_application(include_history=True)
    """
    if application.status_history:
        return [
            {
                "id": entry.id,
                # .value on the enum, but only if it's not None (first row)
                "from_status": entry.from_status.value if entry.from_status else None,
                "to_status": entry.to_status.value,
                "changed_by_role": entry.changed_by_role,
                "note": entry.note,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            }
            for entry in application.status_history  # already ordered by created_at
        ]

    # legacy row -> synthesise the single entry we can prove
    return [
        {
            "id": None,  # not a real db row, hence no id
            "from_status": None,
            "to_status": ApplicationStatus.APPLIED.value,
            "changed_by_role": "student",
            "note": "Application submitted",
            "created_at": application.applied_at.isoformat()
            if application.applied_at
            else None,
        }
    ]


def serialize_placement(placement):
    """Serialize a placement record for API responses (Milestone 6).

    shared by ALL of: student_routes, company_routes, admin_routes, tasks.py.
    one shape everywhere, so the three Placements tables in the frontend can be
    near-identical.

    the `if student else None` guards look paranoid but a placement can outlive
    a deleted student/company (no cascade on those relationships).
    .isoformat() -> JSON has no date type, so everything goes over as a string.
    """
    student = placement.student
    company = placement.company
    return {
        "id": placement.id,
        "student_id": placement.student_id,
        "student_name": student.full_name if student else None,
        "company_id": placement.company_id,
        "company_name": company.name if company else None,
        "application_id": placement.application_id,
        "position": placement.position,
        "salary": placement.salary,
        "joining_date": placement.joining_date.isoformat() if placement.joining_date else None,
        "created_at": placement.created_at.isoformat() if placement.created_at else None,
    }
