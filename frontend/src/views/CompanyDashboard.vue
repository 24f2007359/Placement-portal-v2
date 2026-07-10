<template>
  <div>
    <h2 class="mb-1">Company Dashboard</h2>
    <p class="text-muted mb-4">{{ auth.user?.profile?.name }}</p>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="success" class="alert alert-success">{{ success }}</div>

    <div v-if="loading" class="alert alert-info">Loading dashboard...</div>
    <div v-else-if="pendingApproval" class="alert alert-warning">
      Your company profile is <strong>{{ approvalStatus }}</strong>.
      Dashboard access is available only after admin approval.
    </div>

    <template v-else>
      <div class="row g-3 mb-4">
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
              <h3 class="text-primary mb-0">{{ stats.active_jobs }}</h3>
              <small class="text-muted">Active Jobs</small>
            </div>
          </div>
        </div>
        <div class="col-md-3 col-6">
          <div class="card text-center shadow-sm">
            <div class="card-body">
              <h3 class="text-primary mb-0">{{ stats.received_applications }}</h3>
              <small class="text-muted">Applications</small>
            </div>
          </div>
        </div>
        <div class="col-md-3 col-6">
          <div class="card text-center shadow-sm">
            <div class="card-body">
              <h3 class="text-primary mb-0">{{ stats.shortlisted_candidates }}</h3>
              <small class="text-muted">Shortlisted</small>
            </div>
          </div>
        </div>
      </div>

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

      <div v-show="activeTab === 'jobs'" class="card shadow-sm">
        <div class="card-body">
          <form class="row g-2 mb-3" @submit.prevent="loadJobs">
            <div class="col-md-6">
              <input v-model="jobSearch.q" class="form-control" placeholder="Search by title" />
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
                  <th>Status</th>
                  <th>Applications</th>
                  <th>Deadline</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="job in jobs" :key="job.id">
                  <td>{{ job.title }}</td>
                  <td><span class="badge" :class="jobStatusBadge(job.status)">{{ job.status }}</span></td>
                  <td>{{ job.applications_count }}</td>
                  <td>{{ formatDate(job.application_deadline) }}</td>
                  <td class="d-flex flex-wrap gap-1">
                    <button class="btn btn-sm btn-outline-primary" @click="openJobEditor(job)">Edit</button>
                    <button
                      v-if="job.status !== 'closed'"
                      class="btn btn-sm btn-warning"
                      @click="changeJobStatus(job, 'closed')"
                    >
                      Close
                    </button>
                    <button
                      v-if="job.status === 'approved'"
                      class="btn btn-sm btn-success"
                      @click="changeJobStatus(job, 'active')"
                    >
                      Set Active
                    </button>
                    <button class="btn btn-sm btn-info text-white" @click="openJobApplications(job)">
                      Applicants
                    </button>
                  </td>
                </tr>
                <tr v-if="!jobs.length">
                  <td colspan="5" class="text-center text-muted">No jobs found</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div v-show="activeTab === 'post-job'" class="card shadow-sm">
        <div class="card-body">
          <h5 class="mb-3">{{ jobForm.id ? 'Edit Job Posting' : 'Post New Job' }}</h5>
          <form class="row g-3" @submit.prevent="submitJob">
            <div class="col-md-6">
              <label class="form-label">Title</label>
              <input v-model="jobForm.title" class="form-control" required />
            </div>
            <div class="col-md-3">
              <label class="form-label">Min Salary</label>
              <input v-model.number="jobForm.salary_min" type="number" class="form-control" min="0" />
            </div>
            <div class="col-md-3">
              <label class="form-label">Max Salary</label>
              <input v-model.number="jobForm.salary_max" type="number" class="form-control" min="0" />
            </div>
            <div class="col-12">
              <label class="form-label">Description</label>
              <textarea v-model="jobForm.description" class="form-control" rows="3"></textarea>
            </div>
            <div class="col-md-6">
              <label class="form-label">Skills Required</label>
              <input v-model="jobForm.skills_required" class="form-control" />
            </div>
            <div class="col-md-6">
              <label class="form-label">Experience Required</label>
              <input v-model="jobForm.experience_required" class="form-control" />
            </div>
            <div class="col-md-6">
              <label class="form-label">Benefits</label>
              <input v-model="jobForm.benefits" class="form-control" />
            </div>
            <div class="col-md-6">
              <label class="form-label">Application Deadline</label>
              <input v-model="jobForm.application_deadline" type="datetime-local" class="form-control" />
            </div>
            <div class="col-12 d-flex gap-2">
              <button class="btn btn-primary" type="submit">
                {{ jobForm.id ? 'Update Job' : 'Post Job (for Admin Approval)' }}
              </button>
              <button v-if="jobForm.id" class="btn btn-secondary" type="button" @click="resetJobForm">
                Cancel Edit
              </button>
            </div>
          </form>
        </div>
      </div>

      <div v-show="activeTab === 'applications'" class="card shadow-sm">
        <div class="card-body">
          <div class="row g-2 mb-3">
            <div class="col-md-4">
              <select v-model="applicationFilter.status" class="form-select" @change="onFilterChange">
                <option value="">All statuses</option>
                <option value="applied">Applied</option>
                <option value="shortlisted">Shortlisted</option>
                <option value="interview">Interview</option>
                <option value="offer">Offer</option>
                <option value="placed">Placed</option>
                <option value="rejected">Rejected</option>
              </select>
            </div>
          </div>
          <div class="table-responsive">
            <table class="table table-hover align-middle">
              <thead>
                <tr>
                  <th>Student</th>
                  <th>Job</th>
                  <th>Status</th>
                  <th>Interview</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="app in applications" :key="app.id">
                  <td>
                    <div>{{ app.student_name }}</div>
                    <small class="text-muted">{{ app.student_email || app.student_contact || '—' }}</small>
                  </td>
                  <td>{{ app.job_title }}</td>
                  <td><span class="badge" :class="applicationStatusBadge(app.status)">{{ app.status }}</span></td>
                  <td>{{ formatDate(app.interview_date) }}</td>
                  <td class="d-flex flex-wrap gap-1">
                    <button class="btn btn-sm btn-primary" @click="setApplicationStatus(app, 'shortlisted')">Shortlist</button>
                    <button class="btn btn-sm btn-secondary" @click="setApplicationStatus(app, 'interview')">Interview</button>
                    <button class="btn btn-sm btn-success" @click="setApplicationStatus(app, 'offer')">Offer</button>
                    <button class="btn btn-sm btn-outline-success" @click="openPlacementModal(app)">Place</button>
                    <button class="btn btn-sm btn-danger" @click="setApplicationStatus(app, 'rejected')">Reject</button>
                    <button class="btn btn-sm btn-outline-secondary" @click="openTimeline(app)">Timeline</button>
                    <button class="btn btn-sm btn-outline-info" @click="openProfile(app)">Profile</button>
                  </td>
                </tr>
                <tr v-if="!applications.length">
                  <td colspan="5" class="text-center text-muted">No applications found</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div v-show="activeTab === 'placements'" class="card shadow-sm">
        <div class="card-body">
          <h5 class="mb-3">Placed Candidates</h5>
          <div class="table-responsive">
            <table class="table table-hover align-middle">
              <thead>
                <tr>
                  <th>Student</th>
                  <th>Position</th>
                  <th>Salary</th>
                  <th>Joining Date</th>
                  <th>Recorded On</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in placements" :key="p.id">
                  <td>{{ p.student_name }}</td>
                  <td>{{ p.position }}</td>
                  <td>{{ p.salary ? `₹${p.salary}` : '—' }}</td>
                  <td>{{ formatDate(p.joining_date) }}</td>
                  <td>{{ formatDate(p.created_at) }}</td>
                </tr>
                <tr v-if="!placements.length">
                  <td colspan="5" class="text-center text-muted">No placements recorded yet</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </template>

    <!-- Placement details modal -->
    <div v-if="placementModal.app" class="modal-backdrop-custom" @click.self="placementModal.app = null">
      <div class="card shadow modal-card">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start mb-3">
            <h5 class="mb-0">Record Placement</h5>
            <button class="btn-close" @click="placementModal.app = null"></button>
          </div>
          <p class="text-muted small">{{ placementModal.app.student_name }} — {{ placementModal.app.job_title }}</p>
          <form class="row g-3" @submit.prevent="confirmPlacement">
            <div class="col-12">
              <label class="form-label">Position</label>
              <input v-model="placementModal.position" class="form-control" required />
            </div>
            <div class="col-md-6">
              <label class="form-label">Salary</label>
              <input v-model.number="placementModal.salary" type="number" min="0" class="form-control" />
            </div>
            <div class="col-md-6">
              <label class="form-label">Joining Date</label>
              <input v-model="placementModal.joining_date" type="date" class="form-control" />
            </div>
            <div class="col-12">
              <label class="form-label">Feedback (optional)</label>
              <input v-model="placementModal.feedback" class="form-control" />
            </div>
            <div class="col-12">
              <button class="btn btn-success" type="submit">Mark as Placed</button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- Status history timeline modal -->
    <div v-if="timelineApp" class="modal-backdrop-custom" @click.self="timelineApp = null">
      <div class="card shadow modal-card">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start mb-3">
            <div>
              <h5 class="mb-0">Application Timeline</h5>
              <small class="text-muted">{{ timelineApp.student_name }} — {{ timelineApp.job_title }}</small>
            </div>
            <button class="btn-close" @click="timelineApp = null"></button>
          </div>
          <ul class="list-unstyled timeline">
            <li v-for="(entry, i) in timeline" :key="i" class="mb-3">
              <span class="badge" :class="applicationStatusBadge(entry.to_status)">{{ entry.to_status }}</span>
              <span v-if="entry.from_status" class="text-muted small ms-2">from {{ entry.from_status }}</span>
              <div class="small text-muted">{{ formatDate(entry.created_at) }}
                <span v-if="entry.changed_by_role">· by {{ entry.changed_by_role }}</span></div>
              <div v-if="entry.note" class="small">{{ entry.note }}</div>
            </li>
            <li v-if="!timeline.length" class="text-muted">No history available</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- Student profile modal -->
    <div v-if="profileStudent" class="modal-backdrop-custom" @click.self="profileStudent = null">
      <div class="card shadow modal-card">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start mb-3">
            <h5 class="mb-0">Applicant Profile</h5>
            <button class="btn-close" @click="profileStudent = null"></button>
          </div>
          <dl class="row mb-0">
            <dt class="col-sm-4">Name</dt><dd class="col-sm-8">{{ profileStudent.full_name }}</dd>
            <dt class="col-sm-4">Email</dt><dd class="col-sm-8">{{ profileStudent.email || '—' }}</dd>
            <dt class="col-sm-4">Institute ID</dt><dd class="col-sm-8">{{ profileStudent.institute_id || '—' }}</dd>
            <dt class="col-sm-4">Contact</dt><dd class="col-sm-8">{{ profileStudent.contact || '—' }}</dd>
            <dt class="col-sm-4">Branch</dt><dd class="col-sm-8">{{ profileStudent.branch || '—' }}</dd>
            <dt class="col-sm-4">CGPA</dt><dd class="col-sm-8">{{ profileStudent.cgpa ?? '—' }}</dd>
            <dt class="col-sm-4">Grad. Year</dt><dd class="col-sm-8">{{ profileStudent.graduation_year || '—' }}</dd>
            <dt class="col-sm-4">Skills</dt><dd class="col-sm-8">{{ profileStudent.skills || '—' }}</dd>
            <dt class="col-sm-4">Education</dt><dd class="col-sm-8">{{ profileStudent.education || '—' }}</dd>
            <dt class="col-sm-4">Experience</dt><dd class="col-sm-8">{{ profileStudent.experience || '—' }}</dd>
          </dl>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useAuth } from '../services/auth'
import { companyApi } from '../services/company'

const auth = useAuth()
const loading = ref(true)
const error = ref('')
const success = ref('')
const pendingApproval = ref(false)
const approvalStatus = ref('')
const stats = reactive({
  job_postings: 0,
  active_jobs: 0,
  received_applications: 0,
  shortlisted_candidates: 0,
})

const tabs = [
  { id: 'jobs', label: 'My Jobs' },
  { id: 'post-job', label: 'Post Job' },
  { id: 'applications', label: 'Applications' },
  { id: 'placements', label: 'Placements' },
]
const activeTab = ref('jobs')

const jobs = ref([])
const applications = ref([])
const placements = ref([])
const selectedJob = ref(null)

const timelineApp = ref(null)
const timeline = ref([])
const profileStudent = ref(null)
const placementModal = reactive({
  app: null,
  position: '',
  salary: null,
  joining_date: '',
  feedback: '',
})

const jobSearch = reactive({ q: '', status: '' })
const applicationFilter = reactive({ status: '' })
const jobForm = reactive({
  id: null,
  title: '',
  description: '',
  salary_min: null,
  salary_max: null,
  skills_required: '',
  experience_required: '',
  benefits: '',
  application_deadline: '',
})

function clearMessages() {
  error.value = ''
  success.value = ''
}

function formatDate(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function toDateTimeLocal(value) {
  if (!value) return ''
  const d = new Date(value)
  const tzOffset = d.getTimezoneOffset() * 60000
  return new Date(d.getTime() - tzOffset).toISOString().slice(0, 16)
}

function jobStatusBadge(status) {
  return {
    pending: 'bg-warning text-dark',
    approved: 'bg-success',
    active: 'bg-primary',
    closed: 'bg-secondary',
  }[status] || 'bg-secondary'
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

async function loadDashboard() {
  const { data } = await companyApi.getDashboard()
  Object.assign(stats, data.stats)
}

async function loadJobs() {
  const { data } = await companyApi.getJobs({ ...jobSearch })
  jobs.value = data.jobs
}

async function loadApplications() {
  const params = applicationFilter.status ? { status: applicationFilter.status } : {}
  const { data } = await companyApi.getApplications(params)
  applications.value = data.applications
}

async function loadPlacements() {
  const { data } = await companyApi.getPlacements()
  placements.value = data.placements
}

function onFilterChange() {
  // Filtering shows all matching applications, not just the last opened job.
  selectedJob.value = null
  loadApplications()
}

async function refreshAll() {
  await loadDashboard()
  await loadJobs()
  await loadApplications()
  await loadPlacements()
}

function resetJobForm() {
  Object.assign(jobForm, {
    id: null,
    title: '',
    description: '',
    salary_min: null,
    salary_max: null,
    skills_required: '',
    experience_required: '',
    benefits: '',
    application_deadline: '',
  })
}

function openJobEditor(job) {
  Object.assign(jobForm, {
    id: job.id,
    title: job.title || '',
    description: job.description || '',
    salary_min: job.salary_min,
    salary_max: job.salary_max,
    skills_required: job.skills_required || '',
    experience_required: job.experience_required || '',
    benefits: job.benefits || '',
    application_deadline: toDateTimeLocal(job.application_deadline),
  })
  activeTab.value = 'post-job'
}

async function submitJob() {
  clearMessages()
  try {
    const payload = {
      title: jobForm.title,
      description: jobForm.description,
      salary_min: jobForm.salary_min,
      salary_max: jobForm.salary_max,
      skills_required: jobForm.skills_required,
      experience_required: jobForm.experience_required,
      benefits: jobForm.benefits,
      application_deadline: jobForm.application_deadline
        ? new Date(jobForm.application_deadline).toISOString()
        : null,
    }
    if (jobForm.id) {
      await companyApi.updateJob(jobForm.id, payload)
      success.value = 'Job updated successfully'
    } else {
      await companyApi.createJob(payload)
      success.value = 'Job posted and sent for admin approval'
    }
    resetJobForm()
    activeTab.value = 'jobs'
    await refreshAll()
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to save job'
  }
}

async function changeJobStatus(job, status) {
  clearMessages()
  try {
    await companyApi.updateJob(job.id, { status })
    success.value = `Job marked as ${status}`
    await refreshAll()
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to update job status'
  }
}

async function openJobApplications(job) {
  clearMessages()
  try {
    selectedJob.value = job
    const { data } = await companyApi.getJobApplications(job.id)
    applications.value = data.applications
    activeTab.value = 'applications'
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to load applicants'
  }
}

async function setApplicationStatus(application, status) {
  clearMessages()
  const payload = { status }
  const feedback = window.prompt('Optional feedback for student:')
  if (feedback !== null) {
    payload.feedback = feedback
  }
  if (status === 'interview') {
    const interviewDate = window.prompt('Interview date-time (YYYY-MM-DDTHH:MM):')
    if (interviewDate) {
      payload.interview_date = new Date(interviewDate).toISOString()
    }
  }
  try {
    await companyApi.updateApplicationStatus(application.id, payload)
    success.value = `Application marked as ${status}`
    await refreshApplications()
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to update application'
  }
}

async function refreshApplications() {
  if (selectedJob.value) {
    await openJobApplications(selectedJob.value)
  } else {
    await loadApplications()
  }
  await loadDashboard()
  await loadPlacements()
}

async function openTimeline(application) {
  clearMessages()
  timelineApp.value = application
  timeline.value = []
  try {
    const { data } = await companyApi.getApplication(application.id)
    timeline.value = data.application.status_history || []
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to load timeline'
  }
}

async function openProfile(application) {
  clearMessages()
  profileStudent.value = null
  try {
    const { data } = await companyApi.getStudent(application.student_id)
    profileStudent.value = data.student
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to load profile'
  }
}

function openPlacementModal(application) {
  clearMessages()
  placementModal.app = application
  placementModal.position = application.job_title || ''
  placementModal.salary = null
  placementModal.joining_date = ''
  placementModal.feedback = ''
}

async function confirmPlacement() {
  clearMessages()
  const payload = {
    status: 'placed',
    position: placementModal.position,
    salary: placementModal.salary,
    joining_date: placementModal.joining_date || null,
  }
  if (placementModal.feedback) {
    payload.feedback = placementModal.feedback
  }
  try {
    await companyApi.updateApplicationStatus(placementModal.app.id, payload)
    success.value = 'Candidate marked as placed'
    placementModal.app = null
    await refreshApplications()
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to record placement'
  }
}

onMounted(async () => {
  try {
    await refreshAll()
  } catch (err) {
    if (err.response?.status === 403) {
      pendingApproval.value = true
      approvalStatus.value = err.response?.data?.approval_status || 'pending'
    } else {
      error.value = err.response?.data?.error || 'Failed to load dashboard'
    }
  } finally {
    loading.value = false
  }
})
</script>
