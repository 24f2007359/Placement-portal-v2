import api from './api'

export const studentApi = {
  getDashboard() {
    return api.get('/student/dashboard')
  },
  getProfile() {
    return api.get('/student/profile')
  },
  updateProfile(payload) {
    return api.put('/student/profile', payload)
  },
  uploadResume(file) {
    const formData = new FormData()
    formData.append('resume', file)
    return api.post('/student/profile/resume', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  getJobs(params = {}) {
    return api.get('/student/jobs', { params })
  },
  applyForJob(jobId) {
    return api.post(`/student/jobs/${jobId}/apply`)
  },
  getApplications(params = {}) {
    return api.get('/student/applications', { params })
  },
  getApplication(id) {
    return api.get(`/student/applications/${id}`)
  },
  downloadOfferLetter(id) {
    return api.get(`/student/applications/${id}/offer-letter`, {
      responseType: 'blob',
    })
  },
}
