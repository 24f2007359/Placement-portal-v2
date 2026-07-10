<template>
  <div>
    <h2 class="mb-1">Student Dashboard</h2>
    <p class="text-muted mb-4">{{ auth.user?.profile?.full_name }}</p>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="success" class="alert alert-success">{{ success }}</div>

    <div v-if="loading" class="alert alert-info">Loading dashboard...</div>

    <template v-else>
      <div class="row g-3 mb-4">
        <div class="col-6 col-md">
          <div class="card text-center shadow-sm">
            <div class="card-body">
              <h3 class="text-primary mb-0">{{ stats.available_jobs }}</h3>
              <small class="text-muted">Available Jobs</small>
            </div>
          </div>
        </div>
        <div class="col-6 col-md">
          <div class="card text-center shadow-sm">
            <div class="card-body">
              <h3 class="text-primary mb-0">{{ stats.applications_submitted }}</h3>
              <small class="text-muted">Applications</small>
            </div>
          </div>
        </div>
        <div class="col-6 col-md">
          <div class="card text-center shadow-sm">
            <div class="card-body">
              <h3 class="text-primary mb-0">{{ stats.shortlisted }}</h3>
              <small class="text-muted">Shortlisted</small>
            </div>
          </div>
        </div>
        <div class="col-6 col-md">
          <div class="card text-center shadow-sm">
            <div class="card-body">
              <h3 class="text-primary mb-0">{{ stats.interviews_scheduled }}</h3>
              <small class="text-muted">Interviews</small>
            </div>
          </div>
        </div>
        <div class="col-6 col-md">
          <div class="card text-center shadow-sm">
            <div class="card-body">
              <h3 class="text-success mb-0">{{ stats.placed }}</h3>
              <small class="text-muted">Placed</small>
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

      <div v-show="activeTab === 'profile'" class="card shadow-sm">
        <div class="card-body">
          <h5 class="mb-3">My Profile</h5>
          <form class="row g-3" @submit.prevent="saveProfile">
            <div class="col-md-6">
              <label class="form-label">Full Name</label>
              <input v-model="profileForm.full_name" class="form-control" required />
            </div>
            <div class="col-md-6">
              <label class="form-label">Institute ID</label>
              <input :value="profileForm.institute_id" class="form-control" disabled />
            </div>
            <div class="col-md-4">
              <label class="form-label">Contact</label>
              <input v-model="profileForm.contact" class="form-control" />
            </div>
            <div class="col-md-4">
              <label class="form-label">Branch</label>
              <input v-model="profileForm.branch" class="form-control" placeholder="e.g. CSE" />
            </div>
            <div class="col-md-2">
              <label class="form-label">CGPA</label>
              <input v-model.number="profileForm.cgpa" type="number" step="0.01" min="0" max="10" class="form-control" />
            </div>
            <div class="col-md-2">
              <label class="form-label">Graduation Year</label>
              <input v-model.number="profileForm.graduation_year" type="number" class="form-control" />
            </div>
            <div class="col-12">
              <label class="form-label">Skills</label>
              <textarea v-model="profileForm.skills" class="form-control" rows="2" placeholder="Python, SQL, Vue.js"></textarea>
            </div>
            <div class="col-md-6">
              <label class="form-label">Education</label>
              <textarea v-model="profileForm.education" class="form-control" rows="3"></textarea>
            </div>
            <div class="col-md-6">
              <label class="form-label">Experience</label>
              <textarea v-model="profileForm.experience" class="form-control" rows="3"></textarea>
            </div>
            <div class="col-md-6">
              <label class="form-label">Resume (file upload)</label>
              <input type="file" class="form-control" accept=".pdf,.doc,.docx,.txt" @change="onResumeSelected" />
              <small v-if="profileForm.resume_path" class="text-muted d-block mt-1">
                Current: {{ profileForm.resume_path.split(/[/\\]/).pop() }}
              </small>
            </div>
            <div class="col-12 d-flex gap-2">
              <button class="btn btn-primary" type="submit">Save Profile</button>
              <button
                v-if="selectedResume"
                class="btn btn-outline-primary"
                type="button"
                @click="uploadResume"
              >
                Upload Resume
              </button>
            </div>
          </form>
        </div>
      </div>

      <div v-show="activeTab === 'jobs'" class="card shadow-sm">
        <div class="card-body">
          <form class="row g-2 mb-3" @submit.prevent="loadJobs">
            <div class="col-md-5">
              <input v-model="jobSearch.q" class="form-control" placeholder="Search by title, company, or skills" />
            </div>
            <div class="col-md-5">
              <input v-model="jobSearch.company" class="form-control" placeholder="Filter by company name" />
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
                  <th>Skills</th>
                  <th>Eligibility</th>
                  <th>Deadline</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="job in jobs" :key="job.id">
                  <td>
                    <div>{{ job.title }}</div>
                    <small class="text-muted">{{ formatSalary(job) }}</small>
                  </td>
                  <td>{{ job.company_name }}</td>
                  <td>{{ job.skills_required || '—' }}</td>
                  <td>
                    <small>
                      <span v-if="job.eligibility_cgpa">CGPA ≥ {{ job.eligibility_cgpa }}</span>
                      <span v-if="job.eligibility_branch"><br />Branch: {{ job.eligibility_branch }}</span>
                      <span v-if="job.eligibility_year"><br />Year: {{ job.eligibility_year }}</span>
                      <span v-if="!job.eligibility_cgpa && !job.eligibility_branch && !job.eligibility_year">Open</span>
                    </small>
                  </td>
                  <td>{{ formatDate(job.application_deadline) }}</td>
                  <td>
                    <button
                      v-if="job.already_applied"
                      class="btn btn-sm btn-secondary"
                      disabled
                    >
                      Applied ({{ job.application_status }})
                    </button>
                    <button
                      v-else
                      class="btn btn-sm btn-primary"
                      @click="applyForJob(job)"
                    >
                      Apply
                    </button>
                  </td>
                </tr>
                <tr v-if="!jobs.length">
                  <td colspan="6" class="text-center text-muted">No approved jobs found</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div v-show="activeTab === 'applications'" class="card shadow-sm">
        <div class="card-body">
          <div class="row g-2 mb-3">
            <div class="col-md-4">
              <select v-model="applicationFilter.status" class="form-select" @change="loadApplications">
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
                  <th>Job</th>
                  <th>Company</th>
                  <th>Status</th>
                  <th>Applied On</th>
                  <th>Interview</th>
                  <th>Feedback</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="app in applications" :key="app.id">
                  <td>{{ app.job_title }}</td>
                  <td>{{ app.company_name }}</td>
                  <td><span class="badge" :class="applicationStatusBadge(app.status)">{{ app.status }}</span></td>
                  <td>{{ formatDate(app.applied_at) }}</td>
                  <td>{{ formatDate(app.interview_date) }}</td>
                  <td>{{ app.feedback || '—' }}</td>
                  <td class="d-flex gap-1">
                    <button class="btn btn-sm btn-outline-secondary" @click="openTimeline(app)">
                      Timeline
                    </button>
                    <button
                      v-if="app.has_offer_letter"
                      class="btn btn-sm btn-success"
                      @click="downloadOffer(app)"
                    >
                      Offer Letter
                    </button>
                  </td>
                </tr>
                <tr v-if="!applications.length">
                  <td colspan="7" class="text-center text-muted">No applications yet</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div v-show="activeTab === 'placements'" class="card shadow-sm">
        <div class="card-body">
          <h5 class="mb-3">My Placements</h5>
          <div class="table-responsive">
            <table class="table table-hover align-middle">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Position</th>
                  <th>Salary</th>
                  <th>Joining Date</th>
                  <th>Recorded On</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in placements" :key="p.id">
                  <td>{{ p.company_name }}</td>
                  <td>{{ p.position }}</td>
                  <td>{{ p.salary ? `₹${p.salary}` : '—' }}</td>
                  <td>{{ formatDate(p.joining_date) }}</td>
                  <td>{{ formatDate(p.created_at) }}</td>
                </tr>
                <tr v-if="!placements.length">
                  <td colspan="5" class="text-center text-muted">No placements yet</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </template>

    <!-- Status history timeline modal -->
    <div v-if="timelineApp" class="modal-backdrop-custom" @click.self="timelineApp = null">
      <div class="card shadow modal-card">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start mb-3">
            <div>
              <h5 class="mb-0">Application Timeline</h5>
              <small class="text-muted">{{ timelineApp.job_title }} — {{ timelineApp.company_name }}</small>
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
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useAuth } from '../services/auth'
import { studentApi } from '../services/student'

const auth = useAuth()
const loading = ref(true)
const error = ref('')
const success = ref('')
const stats = reactive({
  available_jobs: 0,
  applications_submitted: 0,
  shortlisted: 0,
  interviews_scheduled: 0,
  placed: 0,
})

const tabs = [
  { id: 'profile', label: 'Profile' },
  { id: 'jobs', label: 'Browse Jobs' },
  { id: 'applications', label: 'My Applications' },
  { id: 'placements', label: 'Placements' },
]
const activeTab = ref('jobs')

const jobs = ref([])
const applications = ref([])
const placements = ref([])
const timelineApp = ref(null)
const timeline = ref([])
const selectedResume = ref(null)

const jobSearch = reactive({ q: '', company: '' })
const applicationFilter = reactive({ status: '' })

const profileForm = reactive({
  full_name: '',
  institute_id: '',
  contact: '',
  branch: '',
  cgpa: null,
  graduation_year: null,
  skills: '',
  education: '',
  experience: '',
  resume_path: '',
})

function clearMessages() {
  error.value = ''
  success.value = ''
}

function formatDate(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function formatSalary(job) {
  if (job.salary_min && job.salary_max) {
    return `₹${job.salary_min} – ₹${job.salary_max}`
  }
  if (job.salary_min) return `From ₹${job.salary_min}`
  if (job.salary_max) return `Up to ₹${job.salary_max}`
  return ''
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
  const { data } = await studentApi.getDashboard()
  Object.assign(stats, data.stats)
}

async function loadProfile() {
  const { data } = await studentApi.getProfile()
  Object.assign(profileForm, data.profile)
}

async function loadJobs() {
  const { data } = await studentApi.getJobs({ ...jobSearch })
  jobs.value = data.jobs
}

async function loadApplications() {
  const params = applicationFilter.status ? { status: applicationFilter.status } : {}
  const { data } = await studentApi.getApplications(params)
  applications.value = data.applications
}

async function loadPlacements() {
  const { data } = await studentApi.getPlacements()
  placements.value = data.placements
}

async function openTimeline(application) {
  clearMessages()
  timelineApp.value = application
  timeline.value = []
  try {
    const { data } = await studentApi.getApplication(application.id)
    timeline.value = data.application.status_history || []
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to load timeline'
  }
}

async function refreshAll() {
  await loadDashboard()
  await loadProfile()
  await loadJobs()
  await loadApplications()
  await loadPlacements()
}

function onResumeSelected(event) {
  selectedResume.value = event.target.files?.[0] || null
}

async function saveProfile() {
  clearMessages()
  try {
    const { data } = await studentApi.updateProfile({ ...profileForm })
    Object.assign(profileForm, data.profile)
    if (auth.user?.profile) {
      Object.assign(auth.user.profile, data.profile)
    }
    success.value = 'Profile updated successfully'
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to update profile'
  }
}

async function uploadResume() {
  if (!selectedResume.value) return
  clearMessages()
  try {
    const { data } = await studentApi.uploadResume(selectedResume.value)
    Object.assign(profileForm, data.profile)
    selectedResume.value = null
    success.value = 'Resume uploaded successfully'
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to upload resume'
  }
}

async function applyForJob(job) {
  clearMessages()
  try {
    await studentApi.applyForJob(job.id)
    success.value = `Applied for ${job.title}`
    await refreshAll()
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to apply for job'
  }
}

async function downloadOffer(application) {
  clearMessages()
  try {
    const { data } = await studentApi.downloadOfferLetter(application.id)
    const url = window.URL.createObjectURL(new Blob([data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `offer_letter_${application.id}.txt`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to download offer letter'
  }
}

onMounted(async () => {
  try {
    await refreshAll()
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to load dashboard'
  } finally {
    loading.value = false
  }
})
</script>
