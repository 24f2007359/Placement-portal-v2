// =============================================================================
// FILE   : src/services/admin.js
// WHAT   : wrapper over every /api/admin/* endpoint. the institute placement
//          cell's god-mode API.
// USED BY: views/AdminDashboard.vue
//
// BACKEND COUNTERPART:
//   backend/admin_routes.py  (admin_bp, /api/admin)  -> CRUD + approvals
//   backend/export_routes.py (export_bp)             -> the M7 job triggers at
//                                                       the bottom of this file
// AUTH   : everything here is @role_required("admin"). admin is pre-seeded by
//          backend/seed_admin.py -- there is NO admin registration route.
// =============================================================================

import api from './api'

export const adminApi = {
  /**
   * getDashboard() -> GET /api/admin/dashboard
   * what : the top stat cards -> students, companies, job_postings, applications,
   *        + pending_companies / pending_jobs (your approval queue counters).
   * where: AdminDashboard.vue -> loadDashboard()
   */
  getDashboard() {
    return api.get('/admin/dashboard')
  },

  // ---------------------------------------------------------------------------
  // COMPANIES -- approve / reject / blacklist / delete
  // milestone 3 stuff. a company literally cannot log into its dashboard until
  // approveCompany() is called on it.
  // ---------------------------------------------------------------------------

  /**
   * getCompanies(params) -> GET /api/admin/companies?q=&industry=&status=
   * where: AdminDashboard.vue -> loadCompanies(), Companies tab search form.
   */
  getCompanies(params = {}) {
    return api.get('/admin/companies', { params })
  },

  /**
   * approveCompany(id) -> PUT /api/admin/companies/:id/approve
   * what : approval_status -> APPROVED, un-blacklists, reactivates the user.
   * knock-on: NOW they can hit /api/company/dashboard, and now you're allowed to
   *        approve their jobs (approve_job refuses if the company isn't approved).
   */
  approveCompany(id) {
    return api.put(`/admin/companies/${id}/approve`)
  },

  /** rejectCompany(id) -> PUT .../reject. sets status REJECTED. they stay in the
   *  list, just locked out. reversible -- you can approve them later. */
  rejectCompany(id) {
    return api.put(`/admin/companies/${id}/reject`)
  },

  /** blacklistCompany(id) -> PUT .../blacklist. harsher than reject: sets
   *  is_blacklisted + REJECTED + user.is_active=False, so login itself 403s.
   *  their jobs also vanish from student search (_approved_jobs_query filters
   *  on is_blacklisted). */
  blacklistCompany(id) {
    return api.put(`/admin/companies/${id}/blacklist`)
  },

  /** removeCompany(id) -> DELETE. NUKES the company + its user + its jobs
   *  (cascade) + its placements. irreversible. AdminDashboard confirm()s first. */
  removeCompany(id) {
    return api.delete(`/admin/companies/${id}`)
  },

  // ---------------------------------------------------------------------------
  // STUDENTS -- search / blacklist / deactivate / delete
  // ---------------------------------------------------------------------------

  /**
   * getStudents(params) -> GET /api/admin/students?q=
   * note : `q` searches name OR institute_id OR contact (one box, 3 columns).
   */
  getStudents(params = {}) {
    return api.get('/admin/students', { params })
  },

  /** blacklistStudent(id) -> permanent-ish ban. is_blacklisted + is_active=False.
   *  can't be undone via activateStudent() -- backend 400s on blacklisted. */
  blacklistStudent(id) {
    return api.put(`/admin/students/${id}/blacklist`)
  },

  /** deactivateStudent(id) -> soft off-switch. is_active=False only. reversible. */
  deactivateStudent(id) {
    return api.put(`/admin/students/${id}/deactivate`)
  },

  /** activateStudent(id) -> turn 'em back on. refuses if blacklisted. */
  activateStudent(id) {
    return api.put(`/admin/students/${id}/activate`)
  },

  /** removeStudent(id) -> DELETE, cascades applications + placements. */
  removeStudent(id) {
    return api.delete(`/admin/students/${id}`)
  },

  // ---------------------------------------------------------------------------
  // JOB POSTINGS -- the approval gate for placement drives
  // ---------------------------------------------------------------------------

  /** getJobs(params) -> GET /api/admin/jobs?q=&status= (all companies' jobs) */
  getJobs(params = {}) {
    return api.get('/admin/jobs', { params })
  },

  /** approveJob(id) -> status pending -> approved. ONLY now do students see it.
   *  backend 400s if the parent company isn't approved yet. */
  approveJob(id) {
    return api.put(`/admin/jobs/${id}/approve`)
  },

  /** rejectJob(id) -> status -> closed (we reuse CLOSED as "rejected"). */
  rejectJob(id) {
    return api.put(`/admin/jobs/${id}/reject`)
  },

  /** removeJob(id) -> DELETE, cascades its applications. */
  removeJob(id) {
    return api.delete(`/admin/jobs/${id}`)
  },

  // ---------------------------------------------------------------------------
  // APPLICATIONS + PLACEMENTS (Milestone 6 -- history / audit trail)
  // ---------------------------------------------------------------------------

  /** getApplications() -> GET /api/admin/applications. every application in the
   *  system, flat list. no filters, admin sees all. */
  getApplications() {
    return api.get('/admin/applications')
  },

  /**
   * getApplication(id) -> GET /api/admin/applications/:id   [M6]
   * what : one application + `status_history` + the student profile.
   * where: AdminDashboard.vue -> openApplicationDetail(), the History modal.
   */
  getApplication(id) {
    return api.get(`/admin/applications/${id}`)
  },

  /** getStudent(id) -> GET /api/admin/students/:id  [M6]
   *  full profile + all their applications + all their placements in one shot. */
  getStudent(id) {
    return api.get(`/admin/students/${id}`)
  },

  /** getPlacements() -> GET /api/admin/placements. every placement, all companies.
   *  where: AdminDashboard.vue -> loadPlacements(), Placements tab. */
  getPlacements() {
    return api.get('/admin/placements')
  },

  // ---------------------------------------------------------------------------
  // MILESTONE 7 -- Celery background jobs
  //
  // these all live in backend/export_routes.py, NOT admin_routes.py.
  // they return 202 + a task_id INSTANTLY -- they do NOT wait for the job.
  // the actual work happens in a separate Celery worker process.
  // AdminDashboard.vue -> runJob() then polls /api/exports/status/<task_id>
  // (see services/exports.js -> runExport()) until it flips to SUCCESS.
  //
  // PREREQ: redis must be up AND `celery -A celery_app.celery worker` running,
  //         otherwise the task just sits PENDING forever and runExport() times
  //         out after 60s with "Is the Celery worker running?".
  // ---------------------------------------------------------------------------

  /**
   * runInterviewReminders() -> POST /api/admin/reminders/interviews
   * what : fires tasks.send_interview_reminders NOW instead of waiting for the
   *        9am cron. emails every student whose interview is within 24h.
   * where: AdminDashboard.vue -> "Send Interview Reminders" button.
   * result: { checked, sent, skipped, lookahead_hours }
   */
  runInterviewReminders() {
    return api.post('/admin/reminders/interviews')
  },

  /**
   * runMonthlyReports() -> POST /api/admin/reports/monthly
   * what : fires tasks.generate_monthly_placement_reports for LAST calendar
   *        month, for every approved company. writes .html + .pdf into
   *        backend/instance/reports/ and emails each company's HR contact.
   * where: AdminDashboard.vue -> "Generate Monthly Reports" button.
   * result: { period, companies, reports[] }
   */
  runMonthlyReports() {
    return api.post('/admin/reports/monthly')
  },

  /** runCompanyReport(id) -> POST /api/admin/reports/company/:id
   *  same report but for one company on demand. (not wired to a button yet,
   *  kept for the viva demo / future per-company button.) */
  runCompanyReport(companyId) {
    return api.post(`/admin/reports/company/${companyId}`)
  },

  /** getReports() -> GET /api/admin/reports. just an ls of instance/reports/,
   *  filenames only. where: AdminDashboard.vue -> loadReports(). */
  getReports() {
    return api.get('/admin/reports')
  },

  /**
   * downloadReport(filename) -> GET /api/admin/reports/download/:filename
   * gotcha: responseType blob, else the PDF gets mangled into a string.
   * SECURITY: backend runs secure_filename() + checks the resolved realpath is
   *        still inside instance/reports/, so ../../config.py -> 404.
   * where: AdminDashboard.vue -> getReport(), via exports.js saveBlob().
   */
  downloadReport(filename) {
    return api.get(`/admin/reports/download/${filename}`, { responseType: 'blob' })
  },

  // ---------------------------------------------------------------------------
  // MILESTONE 8 -- redis cache introspection
  // ---------------------------------------------------------------------------

  /**
   * getCacheStats() -> GET /api/admin/cache/stats
   * what : is redis alive, and per-namespace: version number, live key count, TTL.
   * where: AdminDashboard.vue -> loadCacheStats(), the "Redis Cache" panel.
   * demo tip: approve a job, hit Refresh, watch jobs.version tick up by one --
   *           that single INCR is what invalidates every cached job list at once.
   */
  getCacheStats() {
    return api.get('/admin/cache/stats')
  },

  /**
   * flushCache() -> POST /api/admin/cache/flush
   * what : invalidate every namespace. the manual escape hatch for a stale entry.
   * note : implemented server-side as 3 INCRs, NOT redis FLUSHDB -- so it can
   *        never wipe the celery job queue (db 0) or task results (db 1).
   */
  flushCache() {
    return api.post('/admin/cache/flush')
  },
}
