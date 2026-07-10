import api from './api'

export const adminApi = {
  getDashboard() {
    return api.get('/admin/dashboard')
  },
  getCompanies(params = {}) {
    return api.get('/admin/companies', { params })
  },
  approveCompany(id) {
    return api.put(`/admin/companies/${id}/approve`)
  },
  rejectCompany(id) {
    return api.put(`/admin/companies/${id}/reject`)
  },
  blacklistCompany(id) {
    return api.put(`/admin/companies/${id}/blacklist`)
  },
  removeCompany(id) {
    return api.delete(`/admin/companies/${id}`)
  },
  getStudents(params = {}) {
    return api.get('/admin/students', { params })
  },
  blacklistStudent(id) {
    return api.put(`/admin/students/${id}/blacklist`)
  },
  deactivateStudent(id) {
    return api.put(`/admin/students/${id}/deactivate`)
  },
  activateStudent(id) {
    return api.put(`/admin/students/${id}/activate`)
  },
  removeStudent(id) {
    return api.delete(`/admin/students/${id}`)
  },
  getJobs(params = {}) {
    return api.get('/admin/jobs', { params })
  },
  approveJob(id) {
    return api.put(`/admin/jobs/${id}/approve`)
  },
  rejectJob(id) {
    return api.put(`/admin/jobs/${id}/reject`)
  },
  removeJob(id) {
    return api.delete(`/admin/jobs/${id}`)
  },
  getApplications() {
    return api.get('/admin/applications')
  },
  getApplication(id) {
    return api.get(`/admin/applications/${id}`)
  },
  getStudent(id) {
    return api.get(`/admin/students/${id}`)
  },
  getPlacements() {
    return api.get('/admin/placements')
  },
  // Milestone 7 — background jobs
  runInterviewReminders() {
    return api.post('/admin/reminders/interviews')
  },
  runMonthlyReports() {
    return api.post('/admin/reports/monthly')
  },
  runCompanyReport(companyId) {
    return api.post(`/admin/reports/company/${companyId}`)
  },
  getReports() {
    return api.get('/admin/reports')
  },
  downloadReport(filename) {
    return api.get(`/admin/reports/download/${filename}`, { responseType: 'blob' })
  },
}
