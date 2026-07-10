// =============================================================================
// FILE   : src/services/company.js
// WHAT   : wrapper over every /api/company/* endpoint.
// WHY    : same deal as student.js -- URLs live here, not in the template.
// USED BY: views/CompanyDashboard.vue
//
// BACKEND COUNTERPART: backend/company_routes.py (company_bp, /api/company)
// AUTH   : all @role_required("company") AND gated by _ensure_company_access(),
//          which 403s unless approval_status == APPROVED and not blacklisted.
//          -> that 403 is what CompanyDashboard.vue turns into the yellow
//             "awaiting admin approval" banner.
// =============================================================================

import api from './api'

export const companyApi = {
  /**
   * getDashboard() -> GET /api/company/dashboard
   * what : the 4 stat cards -> job_postings, active_jobs, received_applications,
   *        shortlisted_candidates.
   * where: CompanyDashboard.vue -> loadDashboard()
   * gotcha: this is the FIRST call on mount, so it's the one that throws the
   *         403 for unapproved companies. onMounted() catches it -> pendingApproval.
   */
  getDashboard() {
    return api.get('/company/dashboard')
  },

  /**
   * getJobs(params) -> GET /api/company/jobs?q=&status=
   * what : this company's own job postings (never anyone else's -- backend
   *        filters by company_id from the JWT).
   * where: CompanyDashboard.vue -> loadJobs(), the "My Jobs" tab.
   * params: { q: 'title search', status: 'pending|approved|active|closed' }
   */
  getJobs(params = {}) {
    return api.get('/company/jobs', { params })
  },

  /**
   * createJob(payload) -> POST /api/company/jobs
   * what : post a new placement drive.
   * where: CompanyDashboard.vue -> submitJob() (when jobForm.id is null)
   * IMPORTANT: it lands as status='pending'. an ADMIN must approve it before
   *        students can see it. you can't self-approve. (M6 requirement)
   */
  createJob(payload) {
    return api.post('/company/jobs', payload)
  },

  /**
   * updateJob(id, payload) -> PUT /api/company/jobs/:id
   * what : two jobs in one route ->
   *          a) edit the job details (title/salary/skills/deadline)
   *          b) flip status: send { status: 'active' } or { status: 'closed' }
   * where: CompanyDashboard.vue -> submitJob() (edit) and changeJobStatus()
   * gotcha: backend only accepts 'active' or 'closed' here. and it refuses to
   *         go pending -> active (admin must approve first). anything else 400s.
   */
  updateJob(id, payload) {
    return api.put(`/company/jobs/${id}`, payload)
  },

  /**
   * getJobApplications(jobId) -> GET /api/company/jobs/:id/applications
   * what : applicants for ONE specific job.
   * where: CompanyDashboard.vue -> openJobApplications(), the "Applicants" button.
   * note : sets selectedJob so later status updates re-fetch this same list
   *        instead of the global one.
   */
  getJobApplications(jobId) {
    return api.get(`/company/jobs/${jobId}/applications`)
  },

  /**
   * getApplications(params) -> GET /api/company/applications?status=
   * what : ALL applications across all of this company's jobs.
   * where: CompanyDashboard.vue -> loadApplications(), the Applications tab.
   */
  getApplications(params = {}) {
    return api.get('/company/applications', { params })
  },

  /**
   * updateApplicationStatus(id, payload) -> PUT /api/company/applications/:id/status
   * what : THE money endpoint. moves a candidate along the pipeline.
   * where: CompanyDashboard.vue -> setApplicationStatus() and confirmPlacement()
   *
   * payload:
   *   { status: 'shortlisted' | 'interview' | 'offer' | 'placed' | 'rejected' }
   *   + optional feedback        -> shown to the student, also saved as the
   *                                 history entry's `note`
   *   + optional interview_date  -> ISO string, only makes sense for 'interview'
   *   + optional position/salary/joining_date -> only for 'offer'/'placed'
   *
   * SIDE EFFECTS on the backend (this is the M6/M7 glue):
   *   1. writes a row into ApplicationStatusHistory (who changed it + when)
   *   2. if status is offer|placed -> upserts a Placement row (never duplicates,
   *      it's 1:1 with the application)
   *   3. 'interview' + a date makes this application eligible for the daily
   *      Celery reminder job (tasks.send_interview_reminders)
   */
  updateApplicationStatus(id, payload) {
    return api.put(`/company/applications/${id}/status`, payload)
  },

  /**
   * getApplication(id) -> GET /api/company/applications/:id   [Milestone 6]
   * what : one application + its full `status_history` + the student blob.
   * where: CompanyDashboard.vue -> openTimeline(), the Timeline modal.
   */
  getApplication(id) {
    return api.get(`/company/applications/${id}`)
  },

  /**
   * getStudent(id) -> GET /api/company/students/:id   [Milestone 6]
   * what : full applicant profile (cgpa, skills, education, experience).
   * where: CompanyDashboard.vue -> openProfile(), the Profile modal.
   * SECURITY: backend 404s unless that student actually applied to one of YOUR
   *        jobs. you can't just enumerate student ids and scrape the whole
   *        batch. (see view_student_profile in company_routes.py)
   */
  getStudent(id) {
    return api.get(`/company/students/${id}`)
  },

  /**
   * getPlacements() -> GET /api/company/placements   [Milestone 6]
   * what : everyone this company has actually placed.
   * where: CompanyDashboard.vue -> loadPlacements(), the Placements tab.
   */
  getPlacements() {
    return api.get('/company/placements')
  },
}
