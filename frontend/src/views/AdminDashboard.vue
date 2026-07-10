<template>
  <div>
    <h2 class="mb-1">Admin Dashboard</h2>
    <p class="text-muted mb-4">Institute placement cell control panel</p>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="success" class="alert alert-success">{{ success }}</div>

    <!-- Stats -->
    <div v-if="stats" class="row g-3 mb-4">
      <div class="col-md-3 col-6">
        <div class="card text-center shadow-sm">
          <div class="card-body">
            <h3 class="text-primary mb-0">{{ stats.students }}</h3>
            <small class="text-muted">Students</small>
          </div>
        </div>
      </div>
      <div class="col-md-3 col-6">
        <div class="card text-center shadow-sm">
          <div class="card-body">
            <h3 class="text-primary mb-0">{{ stats.companies }}</h3>
            <small class="text-muted">Companies</small>
          </div>
        </div>
      </div>
      <div class="col-md-3 col-6">
        <div class="card text-center shadow-sm">
          <div class="card-body">
            <h3 class="text-primary mb-0">{{ stats.job_postings }}</h3>
            <small class="text-muted">Job Postings</small>
          </div>
        </div>
      </div>
      <div class="col-md-3 col-6">
        <div class="card text-center shadow-sm">
          <div class="card-body">
            <h3 class="text-primary mb-0">{{ stats.applications }}</h3>
            <small class="text-muted">Applications</small>
          </div>
        </div>
      </div>
    </div>

    <!-- Tabs -->
    <ul class="nav nav-tabs mb-3">
      <li class="nav-item" v-for="tab in tabs" :key="tab.id">
        <button
          class="nav-link"
          :class="{ active: activeTab === tab.id }"
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
        </button>
      </li>
    </ul>

    <!-- Companies -->
    <div v-show="activeTab === 'companies'" class="card shadow-sm">
      <div class="card-body">
        <form class="row g-2 mb-3" @submit.prevent="loadCompanies">
          <div class="col-md-4">
            <input v-model="companySearch.q" class="form-control" placeholder="Search by name" />
          </div>
          <div class="col-md-3">
            <input v-model="companySearch.industry" class="form-control" placeholder="Industry" />
          </div>
          <div class="col-md-3">
            <select v-model="companySearch.status" class="form-select">
              <option value="">All statuses</option>
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
            </select>
          </div>
          <div class="col-md-2">
            <button class="btn btn-primary w-100" type="submit">Search</button>
          </div>
        </form>
        <div class="table-responsive">
          <table class="table table-hover align-middle">
            <thead>
              <tr>
                <th>Name</th>
                <th>Industry</th>
                <th>Email</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in companies" :key="c.id">
                <td>{{ c.name }}</td>
                <td>{{ c.industry || '—' }}</td>
                <td>{{ c.email }}</td>
                <td><span class="badge" :class="statusBadge(c.approval_status)">{{ c.approval_status }}</span></td>
                <td class="d-flex flex-wrap gap-1">
                  <button v-if="c.approval_status === 'pending'" class="btn btn-sm btn-success" @click="approveCompany(c.id)">Approve</button>
                  <button v-if="c.approval_status === 'pending'" class="btn btn-sm btn-warning" @click="rejectCompany(c.id)">Reject</button>
                  <button class="btn btn-sm btn-outline-danger" @click="blacklistCompany(c.id)">Blacklist</button>
                  <button class="btn btn-sm btn-danger" @click="removeCompany(c.id)">Remove</button>
                </td>
              </tr>
              <tr v-if="!companies.length">
                <td colspan="5" class="text-center text-muted">No companies found</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Students -->
    <div v-show="activeTab === 'students'" class="card shadow-sm">
      <div class="card-body">
        <form class="row g-2 mb-3" @submit.prevent="loadStudents">
          <div class="col-md-8">
            <input v-model="studentSearch.q" class="form-control" placeholder="Search by name, institute ID, or contact" />
          </div>
          <div class="col-md-4">
            <button class="btn btn-primary w-100" type="submit">Search</button>
          </div>
        </form>
        <div class="table-responsive">
          <table class="table table-hover align-middle">
            <thead>
              <tr>
                <th>Name</th>
                <th>Institute ID</th>
                <th>Contact</th>
                <th>Email</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in students" :key="s.id">
                <td>{{ s.full_name }}</td>
                <td>{{ s.institute_id || '—' }}</td>
                <td>{{ s.contact || '—' }}</td>
                <td>{{ s.email }}</td>
                <td>
                  <span v-if="s.is_blacklisted" class="badge bg-danger">Blacklisted</span>
                  <span v-else-if="!s.is_active" class="badge bg-secondary">Inactive</span>
                  <span v-else class="badge bg-success">Active</span>
                </td>
                <td class="d-flex flex-wrap gap-1">
                  <button v-if="!s.is_active && !s.is_blacklisted" class="btn btn-sm btn-success" @click="activateStudent(s.id)">Activate</button>
                  <button v-if="s.is_active" class="btn btn-sm btn-warning" @click="deactivateStudent(s.id)">Deactivate</button>
                  <button class="btn btn-sm btn-outline-danger" @click="blacklistStudent(s.id)">Blacklist</button>
                  <button class="btn btn-sm btn-danger" @click="removeStudent(s.id)">Remove</button>
                </td>
              </tr>
              <tr v-if="!students.length">
                <td colspan="6" class="text-center text-muted">No students found</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Jobs -->
    <div v-show="activeTab === 'jobs'" class="card shadow-sm">
      <div class="card-body">
        <form class="row g-2 mb-3" @submit.prevent="loadJobs">
          <div class="col-md-6">
            <input v-model="jobSearch.q" class="form-control" placeholder="Search by job title" />
          </div>
          <div class="col-md-4">
            <select v-model="jobSearch.status" class="form-select">
              <option value="">All statuses</option>
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="active">Active</option>
              <option value="closed">Closed</option>
            </select>
          </div>
          <div class="col-md-2">
            <button class="btn btn-primary w-100" type="submit">Search</button>
          </div>
        </form>
        <div class="table-responsive">
          <table class="table table-hover align-middle">
            <thead>
              <tr>
                <th>Title</th>
                <th>Company</th>
                <th>Status</th>
                <th>Applications</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="j in jobs" :key="j.id">
                <td>{{ j.title }}</td>
                <td>{{ j.company_name }}</td>
                <td><span class="badge" :class="jobStatusBadge(j.status)">{{ j.status }}</span></td>
                <td>{{ j.applications_count }}</td>
                <td class="d-flex flex-wrap gap-1">
                  <button v-if="j.status === 'pending'" class="btn btn-sm btn-success" @click="approveJob(j.id)">Approve</button>
                  <button v-if="j.status === 'pending'" class="btn btn-sm btn-warning" @click="rejectJob(j.id)">Reject</button>
                  <button class="btn btn-sm btn-danger" @click="removeJob(j.id)">Remove</button>
                </td>
              </tr>
              <tr v-if="!jobs.length">
                <td colspan="5" class="text-center text-muted">No job postings found</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Applications -->
    <div v-show="activeTab === 'applications'" class="card shadow-sm">
      <div class="card-body">
        <div class="table-responsive">
          <table class="table table-hover align-middle">
            <thead>
              <tr>
                <th>Student</th>
                <th>Job</th>
                <th>Company</th>
                <th>Status</th>
                <th>Applied At</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in applications" :key="a.id">
                <td>{{ a.student_name }}</td>
                <td>{{ a.job_title }}</td>
                <td>{{ a.company_name }}</td>
                <td><span class="badge" :class="applicationStatusBadge(a.status)">{{ a.status }}</span></td>
                <td>{{ formatDate(a.applied_at) }}</td>
                <td>
                  <button class="btn btn-sm btn-outline-secondary" @click="openApplicationDetail(a)">History</button>
                </td>
              </tr>
              <tr v-if="!applications.length">
                <td colspan="6" class="text-center text-muted">No applications found</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Placements -->
    <div v-show="activeTab === 'placements'" class="card shadow-sm">
      <div class="card-body">
        <div class="table-responsive">
          <table class="table table-hover align-middle">
            <thead>
              <tr>
                <th>Student</th>
                <th>Company</th>
                <th>Position</th>
                <th>Salary</th>
                <th>Joining Date</th>
                <th>Recorded On</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in placements" :key="p.id">
                <td>{{ p.student_name }}</td>
                <td>{{ p.company_name }}</td>
                <td>{{ p.position }}</td>
                <td>{{ p.salary ? `₹${p.salary}` : '—' }}</td>
                <td>{{ formatDate(p.joining_date) }}</td>
                <td>{{ formatDate(p.created_at) }}</td>
              </tr>
              <tr v-if="!placements.length">
                <td colspan="6" class="text-center text-muted">No placements recorded yet</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Application detail + status history modal -->
    <div v-if="detailApp" class="modal-backdrop-custom" @click.self="detailApp = null">
      <div class="card shadow modal-card">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start mb-3">
            <div>
              <h5 class="mb-0">Application History</h5>
              <small class="text-muted">{{ detailApp.student_name }} — {{ detailApp.job_title }}</small>
            </div>
            <button class="btn-close" @click="detailApp = null"></button>
          </div>
          <div v-if="detailStudent" class="mb-3 small">
            <strong>Applicant:</strong> {{ detailStudent.full_name }}
            <span v-if="detailStudent.branch">· {{ detailStudent.branch }}</span>
            <span v-if="detailStudent.cgpa != null">· CGPA {{ detailStudent.cgpa }}</span>
            <span v-if="detailStudent.email">· {{ detailStudent.email }}</span>
          </div>
          <ul class="list-unstyled timeline">
            <li v-for="(entry, i) in detailTimeline" :key="i" class="mb-3">
              <span class="badge" :class="applicationStatusBadge(entry.to_status)">{{ entry.to_status }}</span>
              <span v-if="entry.from_status" class="text-muted small ms-2">from {{ entry.from_status }}</span>
              <div class="small text-muted">{{ formatDate(entry.created_at) }}
                <span v-if="entry.changed_by_role">· by {{ entry.changed_by_role }}</span></div>
              <div v-if="entry.note" class="small">{{ entry.note }}</div>
            </li>
            <li v-if="!detailTimeline.length" class="text-muted">No history available</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { adminApi } from '../services/admin'

const tabs = [
  { id: 'companies', label: 'Companies' },
  { id: 'students', label: 'Students' },
  { id: 'jobs', label: 'Job Postings' },
  { id: 'applications', label: 'Applications' },
  { id: 'placements', label: 'Placements' },
]

const activeTab = ref('companies')
const stats = ref(null)
const companies = ref([])
const students = ref([])
const jobs = ref([])
const applications = ref([])
const placements = ref([])
const detailApp = ref(null)
const detailTimeline = ref([])
const detailStudent = ref(null)
const error = ref('')
const success = ref('')

const companySearch = reactive({ q: '', industry: '', status: '' })
const studentSearch = reactive({ q: '' })
const jobSearch = reactive({ q: '', status: '' })

function statusBadge(status) {
  return { pending: 'bg-warning text-dark', approved: 'bg-success', rejected: 'bg-danger' }[status] || 'bg-secondary'
}

function jobStatusBadge(status) {
  return { pending: 'bg-warning text-dark', approved: 'bg-success', active: 'bg-primary', closed: 'bg-secondary' }[status] || 'bg-secondary'
}

function applicationStatusBadge(status) {
  return {
    applied: 'bg-secondary',
    shortlisted: 'bg-info text-dark',
    interview: 'bg-primary',
    offer: 'bg-success',
    placed: 'bg-success',
    rejected: 'bg-danger',
  }[status] || 'bg-secondary'
}

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

function clearMessages() {
  error.value = ''
  success.value = ''
}

async function withAction(fn, message) {
  clearMessages()
  try {
    await fn()
    success.value = message
    await refreshAll()
  } catch (err) {
    error.value = err.response?.data?.error || 'Action failed'
  }
}

async function loadDashboard() {
  const { data } = await adminApi.getDashboard()
  stats.value = data.stats
}

async function loadCompanies() {
  const { data } = await adminApi.getCompanies({ ...companySearch })
  companies.value = data.companies
}

async function loadStudents() {
  const { data } = await adminApi.getStudents({ ...studentSearch })
  students.value = data.students
}

async function loadJobs() {
  const { data } = await adminApi.getJobs({ ...jobSearch })
  jobs.value = data.jobs
}

async function loadApplications() {
  const { data } = await adminApi.getApplications()
  applications.value = data.applications
}

async function loadPlacements() {
  const { data } = await adminApi.getPlacements()
  placements.value = data.placements
}

async function openApplicationDetail(application) {
  clearMessages()
  detailApp.value = application
  detailTimeline.value = []
  detailStudent.value = null
  try {
    const { data } = await adminApi.getApplication(application.id)
    detailTimeline.value = data.application.status_history || []
    detailStudent.value = data.student
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to load application history'
  }
}

async function refreshAll() {
  await loadDashboard()
  await loadCompanies()
  await loadStudents()
  await loadJobs()
  await loadApplications()
  await loadPlacements()
}

const approveCompany = (id) => withAction(() => adminApi.approveCompany(id), 'Company approved')
const rejectCompany = (id) => withAction(() => adminApi.rejectCompany(id), 'Company rejected')
const blacklistCompany = (id) => withAction(() => adminApi.blacklistCompany(id), 'Company blacklisted')
const removeCompany = (id) => {
  if (!confirm('Remove this company permanently?')) return
  withAction(() => adminApi.removeCompany(id), 'Company removed')
}

const blacklistStudent = (id) => withAction(() => adminApi.blacklistStudent(id), 'Student blacklisted')
const deactivateStudent = (id) => withAction(() => adminApi.deactivateStudent(id), 'Student deactivated')
const activateStudent = (id) => withAction(() => adminApi.activateStudent(id), 'Student activated')
const removeStudent = (id) => {
  if (!confirm('Remove this student permanently?')) return
  withAction(() => adminApi.removeStudent(id), 'Student removed')
}

const approveJob = (id) => withAction(() => adminApi.approveJob(id), 'Job posting approved')
const rejectJob = (id) => withAction(() => adminApi.rejectJob(id), 'Job posting rejected')
const removeJob = (id) => {
  if (!confirm('Remove this job posting?')) return
  withAction(() => adminApi.removeJob(id), 'Job posting removed')
}

onMounted(async () => {
  try {
    await refreshAll()
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to load dashboard'
  }
})
</script>
