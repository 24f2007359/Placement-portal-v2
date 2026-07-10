// =============================================================================
// FILE   : src/services/student.js
// WHAT   : thin wrapper over every /api/student/* endpoint. one method per route.
// WHY    : keeps raw URLs out of the .vue files. if the backend route changes,
//          you fix it HERE once instead of hunting through the template.
// USED BY: views/StudentDashboard.vue  (that's it -- only students call these)
//
// BACKEND COUNTERPART: backend/student_routes.py (student_bp, /api/student)
// AUTH   : every route below is @role_required("student") on the backend.
//          the JWT gets attached automatically by services/api.js interceptor.
// =============================================================================

import api from './api'

export const studentApi = {
  /**
   * getDashboard() -> GET /api/student/dashboard
   * what : the 5 stat cards up top -> available_jobs, applications_submitted,
   *        shortlisted, interviews_scheduled, placed.
   * where: StudentDashboard.vue -> loadDashboard()
   */
  getDashboard() {
    return api.get('/student/dashboard')
  },

  /**
   * getProfile() -> GET /api/student/profile
   * what : full student row (branch, cgpa, skills, education, resume_path...).
   * where: StudentDashboard.vue -> loadProfile(), fills the Profile tab form.
   * note : this is FATTER than auth.user.profile -- use this one for the form.
   */
  getProfile() {
    return api.get('/student/profile')
  },

  /**
   * updateProfile(payload) -> PUT /api/student/profile
   * what : save the Profile tab. backend only touches keys you actually send
   *        (it does `if "branch" in data`), so partial updates are fine.
   * where: StudentDashboard.vue -> saveProfile()
   * why it matters: cgpa / branch / graduation_year feed the ELIGIBILITY check
   *        in backend/student_routes.py::_check_eligibility(). blank profile =
   *        can't apply to jobs that have eligibility rules.
   */
  updateProfile(payload) {
    return api.put('/student/profile', payload)
  },

  /**
   * uploadResume(file) -> POST /api/student/profile/resume
   * what : multipart file upload. saved to backend/instance/uploads/resumes/.
   * where: StudentDashboard.vue -> uploadResume()
   * gotcha: MUST be FormData + multipart header, NOT json. axios won't guess.
   *         backend whitelist: .pdf .doc .docx .txt (ALLOWED_RESUME_EXTENSIONS)
   */
  uploadResume(file) {
    const formData = new FormData()
    formData.append('resume', file)
    return api.post('/student/profile/resume', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  /**
   * getJobs(params) -> GET /api/student/jobs?q=&company=
   * what : the Browse Jobs table.
   * where: StudentDashboard.vue -> loadJobs()
   * params: { q: 'search title/skills/company', company: 'filter by co name' }
   * IMPORTANT: backend only returns jobs where company is APPROVED + not
   *        blacklisted AND job status is approved|active (_approved_jobs_query).
   *        so a student physically cannot see a pending/rejected drive. (M6 req)
   * each job carries `already_applied` + `application_status` so we can grey out
   *        the Apply button instead of letting them spam it.
   */
  getJobs(params = {}) {
    return api.get('/student/jobs', { params })
  },

  /**
   * applyForJob(jobId) -> POST /api/student/jobs/:id/apply
   * what : creates an Application row with status='applied' + writes the first
   *        row into ApplicationStatusHistory (M6 audit trail).
   * where: StudentDashboard.vue -> applyForJob()
   * backend rejects with:
   *   400 -> deadline passed / not eligible (cgpa, branch, grad year)
   *   409 -> already applied (unique constraint on student_id+job_id)
   *   404 -> job not approved / doesn't exist
   */
  applyForJob(jobId) {
    return api.post(`/student/jobs/${jobId}/apply`)
  },

  /**
   * getApplications(params) -> GET /api/student/applications?status=
   * what : the "My Applications" table.
   * where: StudentDashboard.vue -> loadApplications()
   * params: { status: 'applied'|'shortlisted'|'interview'|'offer'|'placed'|'rejected' }
   *         omit it for all.
   */
  getApplications(params = {}) {
    return api.get('/student/applications', { params })
  },

  /**
   * getApplication(id) -> GET /api/student/applications/:id
   * what : ONE application, and crucially it includes `status_history` --
   *        the full applied -> shortlisted -> interview -> offer -> placed chain.
   * where: StudentDashboard.vue -> openTimeline(), feeds the Timeline modal.
   * note : the list endpoint above does NOT include history (too heavy). that's
   *        why the modal does a second fetch when you click Timeline.
   */
  getApplication(id) {
    return api.get(`/student/applications/${id}`)
  },

  /**
   * getPlacements() -> GET /api/student/placements   [added in Milestone 6]
   * what : the student's Placement rows (company, position, salary, joining date).
   * where: StudentDashboard.vue -> loadPlacements(), the Placements tab.
   * note : a Placement row only exists once a company marks you offer/placed.
   */
  getPlacements() {
    return api.get('/student/placements')
  },

  /**
   * downloadOfferLetter(id) -> GET /api/student/applications/:id/offer-letter
   * what : pulls down the offer letter file.
   * where: StudentDashboard.vue -> downloadOffer()
   * gotcha: responseType 'blob' is mandatory. without it axios treats the bytes
   *         as a utf-8 string and the downloaded file is corrupt.
   * note : backend 400s unless status is offer|placed. if no real file was ever
   *        uploaded it generates a plain-text one on the fly.
   */
  downloadOfferLetter(id) {
    return api.get(`/student/applications/${id}/offer-letter`, {
      responseType: 'blob',
    })
  },
}
