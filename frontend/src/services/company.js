import api from './api'

export const companyApi = {
  getDashboard() {
    return api.get('/company/dashboard')
  },
  getJobs(params = {}) {
    return api.get('/company/jobs', { params })
  },
  createJob(payload) {
    return api.post('/company/jobs', payload)
  },
  updateJob(id, payload) {
    return api.put(`/company/jobs/${id}`, payload)
  },
  getJobApplications(jobId) {
    return api.get(`/company/jobs/${jobId}/applications`)
  },
  getApplications(params = {}) {
    return api.get('/company/applications', { params })
  },
  updateApplicationStatus(id, payload) {
    return api.put(`/company/applications/${id}/status`, payload)
  },
  getApplication(id) {
    return api.get(`/company/applications/${id}`)
  },
  getStudent(id) {
    return api.get(`/company/students/${id}`)
  },
  getPlacements() {
    return api.get('/company/placements')
  },
}
