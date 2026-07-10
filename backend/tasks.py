"""Celery background jobs (Milestone 7).

Three families of jobs:

  1. send_interview_reminders          — scheduled (Beat, daily 09:00 IST)
  2. generate_monthly_placement_reports — scheduled (Beat, 1st of month 06:00)
  3. export_*_csv                       — user-triggered, asynchronous

All datetimes coming out of SQLite are treated as naive UTC; helpers below
normalise before comparing so a tz-aware value stored earlier can't break the
comparison.
"""

import csv
import io
import logging
import os
from datetime import datetime, timedelta, timezone

from jinja2 import Template
from xhtml2pdf import pisa

from celery_app import celery
from config import Config
from mail_utils import send_email
from models import (
    Application,
    ApplicationStatus,
    ApprovalStatus,
    Company,
    JobPosition,
    JobStatus,
    Placement,
    Student,
    User,
)

logger = logging.getLogger(__name__)


# --- helpers ---------------------------------------------------------------


def _naive_utcnow():
    """"now", as a NAIVE datetime in UTC. our one clock.

    everything in this file compares against this. why naive? because sqlite
    hands back naive datetimes, and python refuses to compare naive with
    tz-aware ("can't compare offset-naive and offset-aware datetimes").
    so we strip tzinfo everywhere and agree that all naive datetimes mean UTC.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive(value):
    """Normalise a possibly tz-aware datetime to naive UTC for comparison.

    THE DEFENSIVE ONE. models._utcnow() writes tz-aware values, sqlite reads them
    back naive, but company_routes stores datetime.fromisoformat() output which
    CAN carry an offset. so any given DB column may hand you either flavour.

    this converts the aware ones to UTC first (so we don't just chop off a +05:30
    and shift the time by 5.5 hours), then drops tzinfo. naive ones pass through.

    without this, send_interview_reminders() would raise TypeError on a
    tz-aware interview_date and silently never mail anyone.
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _ensure_dir(path):
    """mkdir -p. exist_ok so two workers racing to create it don't both crash."""
    os.makedirs(path, exist_ok=True)
    return path


def _fmt(value, default="—"):
    """Format anything for display in an email/report/CSV cell.

    datetimes get a human format; None/"" become the default (an em-dash for
    reports, but the CSV writers pass default="" so blanks stay blank).
    """
    if value is None or value == "":
        return default
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %H:%M")
    return str(value)


def _previous_month_window(today=None):
    """Return (start, end, label) for the calendar month before `today`.

    e.g. run on 2026-07-10 -> (2026-06-01 00:00, 2026-07-01 00:00, "June 2026")

    the window is HALF-OPEN: start <= x < end. so a placement created at exactly
    midnight on July 1st belongs to July, not June. no double counting.

    THE DAY-ARITHMETIC TRICK: to get the first of last month, snap to the first
    of THIS month, subtract one day (landing anywhere in last month), then snap
    to day=1 again. this handles 31->30 day months and February without a single
    special case. never do `month - 1` by hand.

    the `today` arg is only there so a test can pin the clock.
    """
    today = today or _naive_utcnow()
    this_month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month_end = this_month_start  # exclusive upper bound
    prev_month_start = (this_month_start - timedelta(days=1)).replace(day=1)
    return prev_month_start, prev_month_end, prev_month_start.strftime("%B %Y")


def _write_csv(filename, header, rows):
    """Write rows to EXPORT_DIR/filename; return (path, csv_bytes).

    returns BOTH because we need the file on disk (for the download endpoint)
    AND the raw bytes (to attach to the completion email). writing then
    re-reading would be wasteful and racy.

    we build it in a StringIO first rather than writing straight to the file, so
    we have the string in hand for the attachment.

    newline="" on open() is REQUIRED by the csv module. without it, on Windows
    you get a blank line between every row (\\r\\r\\n).
    """
    _ensure_dir(Config.EXPORT_DIR)
    path = os.path.join(Config.EXPORT_DIR, filename)

    buffer = io.StringIO()
    writer = csv.writer(buffer)  # handles quoting/escaping commas for us
    writer.writerow(header)
    writer.writerows(rows)
    content = buffer.getvalue()

    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)

    return path, content.encode("utf-8")


def _render_pdf(html):
    """Render HTML to PDF bytes. Returns None if conversion fails.

    xhtml2pdf (pisa) is pure python -- no wkhtmltopdf binary, no weasyprint
    system libs (cairo/pango), which are a nightmare to install on Windows.
    price: it only understands a SUBSET of CSS. no flexbox, no grid. that's why
    _REPORT_HTML below uses inline-block and plain tables like it's 2005.

    returns None (not raises) on failure -> _build_company_report just skips the
    PDF and still writes the HTML + emails without an attachment. a broken PDF
    must not lose the whole monthly report run.
    """
    out = io.BytesIO()
    result = pisa.CreatePDF(html, dest=out)
    if result.err:  # .err is a COUNT of errors, 0 == success
        logger.error("PDF generation failed (%s errors)", result.err)
        return None
    return out.getvalue()


# --- 1. Interview reminder job ---------------------------------------------

_REMINDER_HTML = Template(
    """
    <p>Hello {{ student_name }},</p>
    <p>This is a reminder that you have an interview scheduled:</p>
    <ul>
      <li><strong>Position:</strong> {{ job_title }}</li>
      <li><strong>Company:</strong> {{ company_name }}</li>
      <li><strong>Interview:</strong> {{ interview_date }}</li>
    </ul>
    {% if feedback %}<p><strong>Note from the company:</strong> {{ feedback }}</p>{% endif %}
    <p>All the best!<br/>— Placement Portal</p>
    """
)


@celery.task(name="tasks.send_interview_reminders")
def send_interview_reminders(lookahead_hours=None):
    """Email every student whose interview falls within the next N hours.

    SCHEDULED: Celery Beat, daily 09:00 IST (see celery_app.beat_schedule).
    ALSO manually triggerable: POST /api/admin/reminders/interviews.

    the explicit name="tasks.send_interview_reminders" must match the string in
    beat_schedule -- beat only ships a name over redis, not a python reference.

    WHY THE WINDOW WORKS: 24h lookahead + a once-a-day run means each interview
    falls inside exactly one run's window, so nobody gets mailed twice. change
    one number without the other and you'll spam people.

    THE FILTERING IS TWO-STAGE, on purpose:
      1. SQL: status==INTERVIEW and interview_date IS NOT NULL
      2. PYTHON: the actual date-window check
    stage 2 is in python because the stored datetimes may be naive OR tz-aware
    (see _as_naive), and a SQL BETWEEN would compare them wrong. this loads every
    interview application into memory -- fine at course scale, would need fixing
    at 100k rows.

    returns a dict -> that's what surfaces in the admin UI via the status poll.
    `sent` counts real deliveries; if MAIL_* isn't configured send_email returns
    False and everything lands in `skipped` (the mail body is logged instead).
    """
    hours = lookahead_hours or Config.INTERVIEW_REMINDER_LOOKAHEAD_HOURS
    now = _naive_utcnow()
    horizon = now + timedelta(hours=hours)

    # stage 1: cheap SQL narrowing
    candidates = Application.query.filter(
        Application.status == ApplicationStatus.INTERVIEW,
        Application.interview_date.isnot(None),  # .isnot(None), not `!= None`
    ).all()

    sent, skipped = 0, 0
    for application in candidates:
        # stage 2: the window. note `now <=` excludes interviews already in the
        # past -- no point reminding someone about yesterday.
        interview_at = _as_naive(application.interview_date)
        if not (now <= interview_at <= horizon):
            continue  # not a skip, just not due. doesn't touch the counters.

        student = application.student
        email = student.user.email if student and student.user else None
        if not email:  # orphaned profile / deleted user
            skipped += 1
            continue

        job = application.job_position
        company = job.company if job else None

        html = _REMINDER_HTML.render(
            student_name=student.full_name,
            job_title=job.title if job else "—",
            company_name=company.name if company else "—",
            interview_date=_fmt(interview_at),
            feedback=application.feedback,
        )
        if send_email(email, f"Interview reminder: {job.title if job else 'Interview'}", html):
            sent += 1
        else:
            skipped += 1

    logger.info("Interview reminders: %s sent, %s skipped", sent, skipped)
    return {"checked": len(candidates), "sent": sent, "skipped": skipped, "lookahead_hours": hours}


# --- 2. Monthly placement report job ---------------------------------------

_REPORT_HTML = Template(
    """
<html><head><meta charset="utf-8"/><style>
  body { font-family: Helvetica, Arial, sans-serif; font-size: 11pt; color: #212529; }
  h1 { font-size: 18pt; margin-bottom: 2px; }
  h2 { font-size: 13pt; margin-top: 18px; border-bottom: 1px solid #dee2e6; }
  .muted { color: #6c757d; font-size: 9pt; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { border: 1px solid #dee2e6; padding: 5px 7px; text-align: left; font-size: 9.5pt; }
  th { background-color: #f1f3f5; }
  .stat { display: inline-block; width: 30%; padding: 6px 0; }
  .stat b { font-size: 15pt; color: #0d6efd; }
</style></head><body>
  <h1>Placement Report — {{ company.name }}</h1>
  <div class="muted">Reporting period: {{ period }} &nbsp;|&nbsp; Generated {{ generated_at }}</div>

  <h2>Summary</h2>
  <div>
    <span class="stat"><b>{{ stats.applications_received }}</b><br/>Applications received</span>
    <span class="stat"><b>{{ stats.shortlisted }}</b><br/>Shortlisted</span>
    <span class="stat"><b>{{ stats.interviews }}</b><br/>Interviews</span>
    <span class="stat"><b>{{ stats.offers }}</b><br/>Offers made</span>
    <span class="stat"><b>{{ stats.placed }}</b><br/>Placed</span>
    <span class="stat"><b>{{ stats.rejected }}</b><br/>Rejected</span>
  </div>
  <p class="muted">
    Job postings (all time): {{ stats.jobs_posted }} &nbsp;|&nbsp; Active: {{ stats.active_jobs }}
    &nbsp;|&nbsp; Conversion (placed / applications): {{ stats.conversion_rate }}%
  </p>

  <h2>Placements this period ({{ placements|length }})</h2>
  {% if placements %}
  <table>
    <tr><th>Student</th><th>Position</th><th>Salary</th><th>Joining date</th></tr>
    {% for p in placements %}
    <tr><td>{{ p.student }}</td><td>{{ p.position }}</td><td>{{ p.salary }}</td><td>{{ p.joining }}</td></tr>
    {% endfor %}
  </table>
  {% else %}<p class="muted">No placements recorded in this period.</p>{% endif %}

  <h2>Applications this period ({{ applications|length }})</h2>
  {% if applications %}
  <table>
    <tr><th>Student</th><th>Job</th><th>Status</th><th>Applied on</th></tr>
    {% for a in applications %}
    <tr><td>{{ a.student }}</td><td>{{ a.job }}</td><td>{{ a.status }}</td><td>{{ a.applied }}</td></tr>
    {% endfor %}
  </table>
  {% else %}<p class="muted">No applications received in this period.</p>{% endif %}

  <p class="muted" style="margin-top:24px;">Placement Portal V2 — automated monthly report.</p>
</body></html>
"""
)


def _build_company_report(company, start, end, period_label):
    """Render one company's report to HTML + PDF on disk. Returns a summary dict.

    the workhorse behind BOTH generate_monthly_placement_reports() (loops over
    every approved company) and generate_company_report() (one company, on demand).

    does four things:
      1. bucket this company's applications + placements into [start, end)
      2. crunch the stats
      3. render Jinja HTML -> write .html -> convert to PDF -> write .pdf
      4. email the PDF to the HR contact

    NOT a celery task itself -- it's a plain function the tasks call. so it never
    gets its own task id and can't be triggered directly.

    `start <= (_as_naive(x) or start) < end` -- the `or start` is a nasty little
    guard: if applied_at were somehow NULL it defaults to `start`, which then
    passes the check and includes the row. arguably it should EXCLUDE it, but
    applied_at is nullable=False so this branch is dead code in practice.
    """
    # pull everything for this company, then bucket in python. same trade-off as
    # the reminder job: readable, and fine at course scale.
    company_apps = (
        Application.query.join(JobPosition)
        .filter(JobPosition.company_id == company.id)
        .all()
    )
    # half-open window [start, end) -> no row is counted in two months
    period_apps = [
        a for a in company_apps if start <= (_as_naive(a.applied_at) or start) < end
    ]
    period_placements = [
        p
        for p in Placement.query.filter_by(company_id=company.id).all()
        if start <= (_as_naive(p.created_at) or start) < end
    ]

    def count(status):
        """count applications IN THIS PERIOD with a given CURRENT status.

        subtlety worth knowing: this is the status NOW, not the status during
        the period. someone who applied in June and got placed in July counts as
        'placed' in June's report. a stricter version would walk the
        ApplicationStatusHistory rows and ask what the status was on `end`.
        good enough here; worth mentioning in the viva if asked.
        """
        return sum(1 for a in period_apps if a.status == status)

    received = len(period_apps)
    placed = count(ApplicationStatus.PLACED)
    stats = {
        "jobs_posted": JobPosition.query.filter_by(company_id=company.id).count(),
        "active_jobs": JobPosition.query.filter_by(
            company_id=company.id, status=JobStatus.ACTIVE
        ).count(),
        "applications_received": received,
        "shortlisted": count(ApplicationStatus.SHORTLISTED),
        "interviews": count(ApplicationStatus.INTERVIEW),
        "offers": count(ApplicationStatus.OFFER),
        "placed": placed,
        "rejected": count(ApplicationStatus.REJECTED),
        # the `if received else 0.0` guards ZeroDivisionError on a company that
        # got no applications this month. very common. don't remove it.
        "conversion_rate": round((placed / received) * 100, 1) if received else 0.0,
    }

    html = _REPORT_HTML.render(
        company=company,
        period=period_label,
        generated_at=_fmt(_naive_utcnow()),
        stats=stats,
        placements=[
            {
                "student": p.student.full_name if p.student else "—",
                "position": p.position,
                "salary": _fmt(p.salary),
                "joining": _fmt(p.joining_date),
            }
            for p in period_placements
        ],
        applications=[
            {
                "student": a.student.full_name if a.student else "—",
                "job": a.job_position.title if a.job_position else "—",
                "status": a.status.value,
                "applied": _fmt(_as_naive(a.applied_at)),
            }
            for a in period_apps
        ],
    )

    _ensure_dir(Config.REPORT_DIR)
    # slug -> report_company3_2026-06. the YYYY-MM zero-padding is what lets
    # export_routes.list_reports() reverse-sort lexicographically and get the
    # newest month first, no date parsing needed.
    # re-running the job for the same month OVERWRITES -- reports are derived
    # data, regenerating is always safe.
    slug = f"company{company.id}_{start.strftime('%Y-%m')}"
    html_path = os.path.join(Config.REPORT_DIR, f"report_{slug}.html")
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write(html)

    # PDF is best-effort. if pisa chokes we still have the .html and still email.
    pdf_bytes = _render_pdf(html)
    pdf_path = None
    if pdf_bytes:
        pdf_path = os.path.join(Config.REPORT_DIR, f"report_{slug}.pdf")
        with open(pdf_path, "wb") as handle:  # "wb" -> bytes, not text
            handle.write(pdf_bytes)

    # Email the report to the company (HR contact preferred, else login email).
    # hr_contact is a free-text field -- it might be "Call Priya on 98765..."
    # so we sniff it for an @ before trusting it as an address.
    recipient = company.hr_contact if _looks_like_email(company.hr_contact) else None
    if not recipient and company.user:
        recipient = company.user.email
    attachments = (
        [(f"report_{slug}.pdf", pdf_bytes, "application", "pdf")] if pdf_bytes else []
    )
    emailed = send_email(
        recipient,
        f"Monthly placement report — {period_label}",
        f"<p>Hello {company.name},</p><p>Your placement report for "
        f"<strong>{period_label}</strong> is attached.</p>"
        f"<p>Applications: {stats['applications_received']} · "
        f"Placed: {stats['placed']}</p><p>— Placement Portal</p>",
        attachments=attachments,
    )

    return {
        "company_id": company.id,
        "company": company.name,
        "period": period_label,
        "html_path": html_path,
        "pdf_path": pdf_path,
        "emailed": emailed,
        "stats": stats,
    }


def _looks_like_email(value):
    """Is hr_contact an address or a phone number / free text?

    deliberately dumb: has an @, and a dot after the @. not RFC-compliant and
    doesn't try to be -- we only need to decide "mail it here, or fall back to
    the login email". a false positive just bounces, and send_email() swallows it.
    """
    return bool(value) and "@" in value and "." in value.split("@")[-1]


@celery.task(name="tasks.generate_monthly_placement_reports")
def generate_monthly_placement_reports():
    """Generate + email last month's placement report for every approved company.

    SCHEDULED: Celery Beat, 1st of the month at 06:00 IST.
    ALSO manual: POST /api/admin/reports/monthly.

    running on the 1st and reporting on the PREVIOUS month means you always get
    a complete month, never a partial one.

    skips unapproved and blacklisted companies -- no point mailing a report to
    someone who was thrown off the portal.

    the returned `reports` list is the fat one (every company's full stats).
    AdminDashboard.vue::summariseJob() only reads .companies and .period out of
    it, precisely because dumping the whole blob in the UI would be unreadable.
    """
    start, end, label = _previous_month_window()
    companies = Company.query.filter(
        Company.approval_status == ApprovalStatus.APPROVED,
        Company.is_blacklisted.is_(False),
    ).all()

    # one report each. if one company's PDF fails, _render_pdf returns None and
    # we carry on -- a single bad company can't kill the whole month's run.
    reports = [_build_company_report(c, start, end, label) for c in companies]
    logger.info("Generated %s monthly reports for %s", len(reports), label)
    return {"period": label, "companies": len(reports), "reports": reports}


@celery.task(name="tasks.generate_company_report")
def generate_company_report(company_id):
    """On-demand report for one company (admin-triggered).

    POST /api/admin/reports/company/<id>. same period as the monthly job.

    returns {"error": ...} rather than raising on a bad id. a raise would mark
    the celery task FAILURE and the frontend would show a stack-trace string;
    returning an error dict lets runExport() surface a clean message instead.
    (it checks status.result?.error -- see services/exports.js.)
    """
    company = Company.query.get(company_id)
    if not company:
        return {"error": f"Company {company_id} not found"}
    start, end, label = _previous_month_window()
    return _build_company_report(company, start, end, label)


# --- 3. User-triggered CSV exports -----------------------------------------


@celery.task(name="tasks.export_applications_csv", bind=True)
def export_applications_csv(self, user_id):
    """Export the caller's application history to CSV, then email an alert.

    Students export their own applications; companies export applications
    received against their own job postings.

    USER-TRIGGERED (not scheduled): POST /api/exports/applications -> 202 task_id.

    `bind=True` makes celery pass the task instance as `self`. we don't actually
    use it here -- it's there so you could call self.update_state() to report
    progress, or self.retry() on a transient failure. harmless, and the hook is
    ready.

    we take user_id, NOT a User object. celery pickles args through redis and a
    detached sqlalchemy model won't survive the trip. so: send ids, re-fetch here.

    ROLE-AWARE (Milestone 6's access rules, enforced again at export time):
      student -> only their own applications
      company -> only applications against their own jobs (via the JobPosition join)
      admin   -> rejected. an admin has no applications of their own.

    THE EMAIL IS THE POINT. milestone 7 asks for an "alert sent once the batch job
    is complete" -- that's the send_email() at the bottom, with the CSV attached.
    the polling + auto-download in the UI is a bonus on top.

    returns {filename, rows, path}. the route's status endpoint hoists filename
    and rows to the top level for the frontend.
    """
    user = User.query.get(user_id)
    if not user:
        # error dict, not an exception -- see generate_company_report's note
        return {"error": f"User {user_id} not found"}

    # second-resolution timestamp. two exports in the same second by the same
    # user would collide and overwrite; acceptable, nobody double-clicks that fast
    # (and the button is disabled while one is running anyway).
    timestamp = _naive_utcnow().strftime("%Y%m%d%H%M%S")
    role = user.role.value

    if role == "student":
        student = user.student
        if not student:
            return {"error": "Student profile not found"}
        header = ["Job Title", "Company", "Status", "Applied On", "Interview Date", "Feedback"]
        rows = [
            [
                a.job_position.title if a.job_position else "",
                a.job_position.company.name if a.job_position and a.job_position.company else "",
                a.status.value,
                _fmt(_as_naive(a.applied_at), ""),
                _fmt(_as_naive(a.interview_date), ""),
                a.feedback or "",
            ]
            for a in Application.query.filter_by(student_id=student.id)
            .order_by(Application.applied_at.desc())
            .all()
        ]
    elif role == "company":
        company = user.company
        if not company:
            return {"error": "Company profile not found"}
        header = ["Student", "Institute ID", "Email", "Job Title", "Status", "Applied On", "Interview Date", "Feedback"]
        rows = [
            [
                a.student.full_name if a.student else "",
                a.student.institute_id if a.student else "",
                a.student.user.email if a.student and a.student.user else "",
                a.job_position.title if a.job_position else "",
                a.status.value,
                _fmt(_as_naive(a.applied_at), ""),
                _fmt(_as_naive(a.interview_date), ""),
                a.feedback or "",
            ]
            for a in Application.query.join(JobPosition)
            .filter(JobPosition.company_id == company.id)
            .order_by(Application.applied_at.desc())
            .all()
        ]
    else:
        return {"error": "Only students and companies can export applications"}

    # !! THE FILENAME IS THE ACCESS CONTROL !! `user{id}_` is what
    # export_routes._owns_file() greps for on download. change this format and
    # you silently break the ownership check. keep them in sync.
    filename = f"applications_user{user_id}_{timestamp}.csv"
    path, data = _write_csv(filename, header, rows)

    # the "alert once the batch job is complete" the milestone asks for.
    # if MAIL_* isn't configured this logs to console and returns False -- the
    # export still succeeded, so we ignore the return value.
    send_email(
        user.email,
        "Your applications export is ready",
        f"<p>Your CSV export of <strong>{len(rows)}</strong> application(s) is ready.</p>"
        "<p>It is attached, and also downloadable from your dashboard.</p>"
        "<p>— Placement Portal</p>",
        attachments=[(filename, data, "text", "csv")],
    )

    return {"filename": filename, "rows": len(rows), "path": path}


@celery.task(name="tasks.export_placements_csv", bind=True)
def export_placements_csv(self, user_id):
    """Export placement history for the caller (student, company, or admin).

    USER-TRIGGERED: POST /api/exports/placements.

    UNLIKE the applications export, ADMIN IS ALLOWED here -- and gets EVERY
    placement in the system (`query = Placement.query`, unscoped). that's the
    institute-wide placement register.

    each branch builds a different Query but the row-shaping below is shared,
    which is why we assign `query` rather than returning early.
    """
    user = User.query.get(user_id)
    if not user:
        return {"error": f"User {user_id} not found"}

    timestamp = _naive_utcnow().strftime("%Y%m%d%H%M%S")
    role = user.role.value

    if role == "student":
        if not user.student:
            return {"error": "Student profile not found"}
        query = Placement.query.filter_by(student_id=user.student.id)
    elif role == "company":
        if not user.company:
            return {"error": "Company profile not found"}
        query = Placement.query.filter_by(company_id=user.company.id)
    elif role == "admin":
        query = Placement.query  # unscoped -- everything
    else:
        return {"error": "Unsupported role"}

    header = ["Student", "Company", "Position", "Salary", "Joining Date", "Recorded On"]
    rows = [
        [
            p.student.full_name if p.student else "",
            p.company.name if p.company else "",
            p.position,
            p.salary if p.salary is not None else "",
            _fmt(p.joining_date, ""),
            _fmt(_as_naive(p.created_at), ""),
        ]
        for p in query.order_by(Placement.created_at.desc()).all()
    ]

    filename = f"placements_user{user_id}_{timestamp}.csv"
    path, data = _write_csv(filename, header, rows)

    send_email(
        user.email,
        "Your placements export is ready",
        f"<p>Your CSV export of <strong>{len(rows)}</strong> placement record(s) is ready.</p>"
        "<p>It is attached, and also downloadable from your dashboard.</p>"
        "<p>— Placement Portal</p>",
        attachments=[(filename, data, "text", "csv")],
    )

    return {"filename": filename, "rows": len(rows), "path": path}
