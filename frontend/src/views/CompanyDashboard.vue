<!--
  =============================================================================
  FILE : src/views/CompanyDashboard.vue
  ROUTE: /company/dashboard   (meta: requiresAuth + role:'company')
  WHAT : the recruiter's console. 4 stat cards + 4 tabs.
           My Jobs      -> list/search own postings, close/activate, see applicants
           Post Job     -> create OR edit a posting (same form, jobForm.id decides)
           Applications -> move candidates along the pipeline + Timeline/Profile modals
           Placements   -> who you actually hired (M6)

  TALKS TO: services/company.js -> /api/company/*  (backend/company_routes.py)
            services/exports.js -> /api/exports/*  (backend/export_routes.py, M7)

  !! THE APPROVAL GATE !!
  a freshly-registered company has approval_status=PENDING. every /api/company/*
  route runs _ensure_company_access() which 403s them. so onMounted() below
  catches a 403 and flips `pendingApproval` -> we render the yellow banner and
  NOTHING else. no tabs, no stats. an admin has to hit Approve first.

  PIPELINE this view drives (the heart of M6):
    applied -> shortlisted -> interview -> offer -> placed
                                              \-> rejected
  every button here writes an ApplicationStatusHistory row backend-side, and
  offer/placed also upserts a Placement row.
  =============================================================================
-->
<template>
  <div>
    <h2 class="mb-1">Company Dashboard</h2>
    <!-- company profile uses .name; student uses .full_name. different shapes. -->
    <p class="text-muted mb-4">{{ auth.user?.profile?.name }}</p>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="success" class="alert alert-success">{{ success }}</div>

    <!-- three-way render: loading / blocked / actual dashboard.
         the v-if..v-else-if..v-else chain means only ONE ever shows. -->
    <div v-if="loading" class="alert alert-info">Loading dashboard...</div>

    <!-- the 403 wall. approvalStatus comes off the error body, so it says
         "pending" or "rejected" accurately instead of a generic message. -->
    <div v-else-if="pendingApproval" class="alert alert-warning">
      Your company profile is <strong>{{ approvalStatus }}</strong>.
      Dashboard access is available only after admin approval.
    </div>

    <template v-else>
      <!-- ===================== STAT CARDS =====================
           from GET /api/company/dashboard. only 4 -> col-md-3 fits them in one
           row exactly (12/4=3). student dash needed `col-md` because it has 5. -->
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

      <!-- ===================== TAB 1: MY JOBS =====================
           backend scopes everything by company_id from the JWT, so you can
           never see or touch another company's postings. -->
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
                    <!-- Edit -> loads this job INTO jobForm and jumps to the
                         Post Job tab, which then acts as an edit form. -->
                    <button class="btn btn-sm btn-outline-primary" @click="openJobEditor(job)">Edit</button>
                    <button
                      v-if="job.status !== 'closed'"
                      class="btn btn-sm btn-warning"
                      @click="changeJobStatus(job, 'closed')"
                    >
                      Close
                    </button>
                    <!-- "Set Active" ONLY shows on status==='approved'.
                         you cannot go pending -> active; the backend rejects it
                         ("Pending jobs must be approved by admin before activation").
                         so: post -> admin approves -> THEN you can activate. -->
                    <button
                      v-if="job.status === 'approved'"
                      class="btn btn-sm btn-success"
                      @click="changeJobStatus(job, 'active')"
                    >
                      Set Active
                    </button>
                    <!-- jumps to the Applications tab, pre-filtered to THIS job.
                         sets selectedJob so later refreshes stay scoped to it. -->
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

      <!-- ===================== TAB 2: POST / EDIT JOB =====================
           ONE form does double duty. `jobForm.id` is the switch:
             id === null -> POST /api/company/jobs   (create, lands as 'pending')
             id !== null -> PUT  /api/company/jobs/:id (edit)
           that's why the heading + button label are ternaries. -->
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
              <!-- type=datetime-local wants 'YYYY-MM-DDTHH:MM' (no timezone, no
                   seconds). backend stores ISO. toDateTimeLocal() converts one
                   way, submitJob() does .toISOString() the other way. -->
              <input v-model="jobForm.application_deadline" type="datetime-local" class="form-control" />
            </div>
            <div class="col-12 d-flex gap-2">
              <!-- type="submit" -> triggers @submit.prevent="submitJob" -->
              <button class="btn btn-primary" type="submit">
                {{ jobForm.id ? 'Update Job' : 'Post Job (for Admin Approval)' }}
              </button>
              <!-- type="button" is MANDATORY here. default type inside a <form>
                   is "submit", so without it Cancel would fire submitJob(). -->
              <button v-if="jobForm.id" class="btn btn-secondary" type="button" @click="resetJobForm">
                Cancel Edit
              </button>
            </div>
          </form>
        </div>
      </div>

      <!-- ===================== TAB 3: APPLICATIONS =====================
           shows EITHER all applications across all your jobs, OR just one job's
           applicants if you arrived via the "Applicants" button (selectedJob set).
           changing the status filter clears selectedJob -> back to global view. -->
      <div v-show="activeTab === 'applications'" class="card shadow-sm">
        <div class="card-body">
          <div class="row g-2 mb-3 align-items-center">
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
            <div class="col-md-8 text-md-end">
              <button class="btn btn-outline-primary" :disabled="exporting" @click="exportApplications">
                <span v-if="exporting" class="spinner-border spinner-border-sm me-1"></span>
                {{ exporting ? exportState : 'Export Applications (CSV)' }}
              </button>
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
                  <!--
                    THE PIPELINE BUTTONS. all but "Place" go straight through
                    setApplicationStatus() which window.prompt()s for feedback.
                    "Interview" additionally prompts for a date-time -- that date
                    is what the M7 daily celery job scans to email reminders.

                    "Place" is special: it needs position + salary + joining date,
                    which is too much for a prompt(), so it opens a proper modal
                    (openPlacementModal -> confirmPlacement).

                    note there's no "un-reject". status changes are one-way in the
                    UI, though the backend would happily accept going backwards.
                  -->
                  <td class="d-flex flex-wrap gap-1">
                    <button class="btn btn-sm btn-primary" @click="setApplicationStatus(app, 'shortlisted')">Shortlist</button>
                    <button class="btn btn-sm btn-secondary" @click="setApplicationStatus(app, 'interview')">Interview</button>
                    <button class="btn btn-sm btn-success" @click="setApplicationStatus(app, 'offer')">Offer</button>
                    <button class="btn btn-sm btn-outline-success" @click="openPlacementModal(app)">Place</button>
                    <button class="btn btn-sm btn-danger" @click="setApplicationStatus(app, 'rejected')">Reject</button>
                    <!-- read-only modals (M6) -->
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

      <!-- ===================== TAB 4: PLACEMENTS (M6) =====================
           Placement rows appear the moment you mark someone offer or placed.
           read-only here -- to change one, re-run the Place action on the
           application (backend UPDATES the existing row, never duplicates). -->
      <div v-show="activeTab === 'placements'" class="card shadow-sm">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <h5 class="mb-0">Placed Candidates</h5>
            <button class="btn btn-outline-primary btn-sm" :disabled="exporting" @click="exportPlacements">
              <span v-if="exporting" class="spinner-border spinner-border-sm me-1"></span>
              {{ exporting ? exportState : 'Export Placements (CSV)' }}
            </button>
          </div>
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

    <!-- ===================== MODAL 1: RECORD PLACEMENT (M6) =====================
         placementModal.app doubles as the open/closed flag AND the payload target.
         submitting PUTs status:'placed' + position/salary/joining_date, which
         makes the backend upsert a Placement row and log the history entry. -->
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

    <!-- ===================== MODAL 2: STATUS TIMELINE (M6) =====================
         same markup as the one in StudentDashboard.vue, just labelled with the
         student's name instead of the company's. fed by
         GET /api/company/applications/:id -> status_history[] -->
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

    <!-- ===================== MODAL 3: APPLICANT PROFILE (M6) =====================
         GET /api/company/students/:id
         SECURITY: backend 404s unless this student applied to one of YOUR jobs.
         you can't walk student ids and scrape the whole batch. -->
    <div v-if="profileStudent" class="modal-backdrop-custom" @click.self="profileStudent = null">
      <div class="card shadow modal-card">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start mb-3">
            <h5 class="mb-0">Applicant Profile</h5>
            <button class="btn-close" @click="profileStudent = null"></button>
          </div>
          <!-- <dl> = description list. dt = term, dd = definition. semantic
               key/value markup, beats a table for a single record. -->
          <dl class="row mb-0">
            <dt class="col-sm-4">Name</dt><dd class="col-sm-8">{{ profileStudent.full_name }}</dd>
            <dt class="col-sm-4">Email</dt><dd class="col-sm-8">{{ profileStudent.email || '—' }}</dd>
            <dt class="col-sm-4">Institute ID</dt><dd class="col-sm-8">{{ profileStudent.institute_id || '—' }}</dd>
            <dt class="col-sm-4">Contact</dt><dd class="col-sm-8">{{ profileStudent.contact || '—' }}</dd>
            <dt class="col-sm-4">Branch</dt><dd class="col-sm-8">{{ profileStudent.branch || '—' }}</dd>
            <!-- ?? not || here! a CGPA of 0 is falsy, so `0 || '—'` would print
                 a dash. ?? only falls through on null/undefined. -->
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
import { downloadExport, exportApi, runExport } from '../services/exports'

const auth = useAuth()

// --- top level ui state ------------------------------------------------------
const loading = ref(true)
const error = ref('')
const success = ref('')

// the 403 wall. set by onMounted() when the dashboard call comes back 403.
// approvalStatus holds 'pending' | 'rejected' straight from the error body.
const pendingApproval = ref(false)
const approvalStatus = ref('')

// mirrors GET /api/company/dashboard -> stats{}
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

// --- table data --------------------------------------------------------------
const jobs = ref([])
const applications = ref([])
const placements = ref([])

// selectedJob: non-null means the Applications tab is scoped to ONE job (you got
// there via the "Applicants" button). refreshApplications() reads this to decide
// whether to re-fetch that job's applicants or the global list.
const selectedJob = ref(null)

// --- modal state (each *App / *Student ref doubles as the open/closed flag) ---
const timelineApp = ref(null)
const timeline = ref([])
const profileStudent = ref(null)
const exporting = ref(false)
const exportState = ref('')

// the Record Placement modal. `app` null = closed. the rest is the form.
const placementModal = reactive({
  app: null,
  position: '',
  salary: null,
  joining_date: '',
  feedback: '',
})

const jobSearch = reactive({ q: '', status: '' })
const applicationFilter = reactive({ status: '' })

// the create/edit job form. `id` is the create-vs-edit switch (null = create).
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

/** wipe both alert bars. first line of basically every action fn. */
function clearMessages() {
  error.value = ''
  success.value = ''
}

/** ISO -> readable local string, em-dash when null. */
function formatDate(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

/**
 * toDateTimeLocal(isoString) -> 'YYYY-MM-DDTHH:MM'
 * what : convert a backend ISO timestamp into the exact format that
 *        <input type="datetime-local"> demands. anything else = blank input.
 * where: openJobEditor(), when loading an existing job into the form.
 *
 * the timezone dance:
 *   .toISOString() always spits out UTC ('...Z'). but datetime-local expects
 *   LOCAL wall-clock time. so we subtract the offset first, THEN call
 *   toISOString(), which effectively bakes local time into the UTC-shaped string.
 *   getTimezoneOffset() is in MINUTES, hence * 60000 to get ms.
 *   .slice(0,16) chops off ':ss.sssZ' -> leaves 'YYYY-MM-DDTHH:MM'.
 *
 * submitJob() does the reverse: new Date(local).toISOString().
 */
function toDateTimeLocal(value) {
  if (!value) return ''
  const d = new Date(value)
  const tzOffset = d.getTimezoneOffset() * 60000
  return new Date(d.getTime() - tzOffset).toISOString().slice(0, 16)
}

/** JOB status -> badge colour. pending=yellow (waiting on admin),
 *  approved=green, active=blue (live, students can apply), closed=grey. */
function jobStatusBadge(status) {
  return {
    pending: 'bg-warning text-dark',
    approved: 'bg-success',
    active: 'bg-primary',
    closed: 'bg-secondary',
  }[status] || 'bg-secondary'
}

/** APPLICATION status -> badge colour. (different enum from jobStatusBadge!)
 *  same fn also lives in StudentDashboard.vue + AdminDashboard.vue. */
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

/** GET /api/company/dashboard -> stat cards.
 *  ALSO the tripwire: this is the first call onMounted fires, so its 403 is
 *  what triggers the pendingApproval banner. */
async function loadDashboard() {
  const { data } = await companyApi.getDashboard()
  Object.assign(stats, data.stats)
}

/** GET /api/company/jobs?q=&status= -> My Jobs table (own postings only). */
async function loadJobs() {
  const { data } = await companyApi.getJobs({ ...jobSearch })
  jobs.value = data.jobs
}

/** GET /api/company/applications[?status=] -> ALL applicants across all jobs. */
async function loadApplications() {
  const params = applicationFilter.status ? { status: applicationFilter.status } : {}
  const { data } = await companyApi.getApplications(params)
  applications.value = data.applications
}

/** GET /api/company/placements -> Placements tab. (M6) */
async function loadPlacements() {
  const { data } = await companyApi.getPlacements()
  placements.value = data.placements
}

/**
 * onFilterChange()
 * what : @change handler on the status dropdown.
 * why not just call loadApplications directly? because if you'd previously hit
 *        "Applicants" on one job, selectedJob is still set and refreshApplications()
 *        would keep snapping you back to that single job. clearing it first means
 *        "filter by status" searches ALL your applications, which is what a user
 *        expects when they touch a global filter.
 */
function onFilterChange() {
  // Filtering shows all matching applications, not just the last opened job.
  selectedJob.value = null
  loadApplications()
}

/** re-pull everything. used on mount and after any job create/edit/status change. */
async function refreshAll() {
  await loadDashboard()
  await loadJobs()
  await loadApplications()
  await loadPlacements()
}

/**
 * runAndDownload(startFn, label)   [M7]
 * identical twin of the one in StudentDashboard.vue -- queue a celery export,
 * poll it, download the CSV. see services/exports.js::runExport() for the guts.
 * kept duplicated (not hoisted into a composable) so each dashboard stays
 * readable on its own. if it grows a third copy, refactor it out.
 */
async function runAndDownload(startFn, label) {
  clearMessages()
  exporting.value = true
  exportState.value = 'Queued...'
  try {
    const status = await runExport(startFn, {
      onState: (state) => {
        exportState.value = state === 'SUCCESS' ? 'Downloading...' : `${state}...`
      },
    })
    await downloadExport(status.filename)
    success.value = `${label} exported (${status.rows} rows). A copy was emailed to you.`
  } catch (err) {
    error.value = err.response?.data?.error || err.message || 'Export failed'
  } finally {
    exporting.value = false
    exportState.value = ''
  }
}

const exportApplications = () =>
  runAndDownload(exportApi.startApplicationsExport, 'Applications')
const exportPlacements = () =>
  runAndDownload(exportApi.startPlacementsExport, 'Placements')

/** blank the job form back to "create" mode (id=null).
 *  called after a successful save, and by the Cancel Edit button.
 *  Object.assign, not reassignment -- jobForm is a reactive const. */
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

/**
 * openJobEditor(job)
 * what : the "Edit" button on My Jobs. copies the row into jobForm and yanks
 *        you over to the Post Job tab, which morphs into an edit form because
 *        jobForm.id is now set.
 * `|| ''` on every string -> the API sends null for empty columns, and binding
 *        null into an <input> renders the literal text "null". '' is what we want.
 * deadline needs the toDateTimeLocal() conversion, see that fn's notes.
 */
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

/**
 * submitJob()
 * what : the one submit handler for BOTH create and edit.
 *        jobForm.id truthy -> PUT (update). falsy -> POST (create).
 * deadline: datetime-local gives us local wall-clock; .toISOString() converts to
 *        UTC for the backend. empty string -> send null, not ''.
 * after: reset the form, bounce back to the My Jobs tab, refresh everything
 *        (a new job changes both the jobs table AND the stat cards).
 * remember: a newly created job is 'pending'. it is INVISIBLE to students until
 *        an admin approves it.
 */
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

/**
 * changeJobStatus(job, status)  -> PUT /api/company/jobs/:id { status }
 * what : the Close / Set Active buttons.
 * only 'active' and 'closed' are legal here. and pending -> active is refused
 *        backend-side, which is exactly why "Set Active" only renders on approved.
 */
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

/**
 * openJobApplications(job) -> GET /api/company/jobs/:id/applications
 * what : the "Applicants" button. shows only THIS job's applicants.
 * side effect: sets selectedJob, which makes refreshApplications() keep the view
 *        scoped to this job after every status change. onFilterChange() clears it.
 * note : it overwrites the same `applications` ref the global list uses -- the
 *        table doesn't know or care which one it's showing.
 */
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

/**
 * setApplicationStatus(application, status)
 *   -> PUT /api/company/applications/:id/status
 * what : Shortlist / Interview / Offer / Reject buttons.
 *
 * the prompt() dance:
 *   window.prompt returns null if you hit Cancel, '' if you hit OK on an empty
 *   box. we check `!== null` so an intentional empty feedback still gets sent
 *   (backend turns '' into None and clears the old feedback). crude, yes --
 *   proper modals would be nicer, but this keeps the demo simple.
 *
 * interview_date: only asked for on 'interview'. THIS DATE MATTERS -- the M7
 *   celery beat job (tasks.send_interview_reminders, daily 9am) scans for
 *   applications with status=interview and interview_date within 24h, and mails
 *   the student. no date = no reminder.
 *
 * backend side effects: writes an ApplicationStatusHistory row, and on
 *   offer/placed also upserts the Placement.
 */
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

/**
 * refreshApplications()
 * what : reload after a status change, WITHOUT losing your place.
 *        if you were looking at one job's applicants -> re-fetch that job's list.
 *        otherwise -> re-fetch the global list.
 * also refreshes stats (shortlisted count moved) and placements (an offer/placed
 * may have just created a Placement row).
 * why not refreshAll()? it'd re-fetch jobs and, worse, clobber the single-job
 *        view back to the global one.
 */
async function refreshApplications() {
  if (selectedJob.value) {
    await openJobApplications(selectedJob.value)
  } else {
    await loadApplications()
  }
  await loadDashboard()
  await loadPlacements()
}

/** openTimeline(app) -> GET /api/company/applications/:id, pull status_history.
 *  same pattern as StudentDashboard: open modal instantly, blank the old rows,
 *  then fill. (list endpoint omits history, so this second call is required.) */
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

/** openProfile(app) -> GET /api/company/students/:id
 *  null it first so the modal doesn't flash the PREVIOUS applicant's details
 *  while the new request is in flight (v-if keeps it shut until data lands). */
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

/**
 * openPlacementModal(application)
 * what : the "Place" button. purely local -- no API call yet.
 * prefills position with the job title (99% of the time that's right, and HR
 * can overwrite it). explicitly blanks salary/date/feedback so leftovers from
 * the LAST candidate you placed don't leak into this one.
 */
function openPlacementModal(application) {
  clearMessages()
  placementModal.app = application
  placementModal.position = application.job_title || ''
  placementModal.salary = null
  placementModal.joining_date = ''
  placementModal.feedback = ''
}

/**
 * confirmPlacement() -> PUT /api/company/applications/:id/status
 * what : submit handler for the Record Placement modal.
 * sends status:'placed' plus the placement fields. backend then:
 *   1. logs the history row (offer -> placed)
 *   2. _upsert_placement() creates the Placement, or UPDATES it if this
 *      application already had one (from an earlier 'offer'). never duplicates,
 *      because Application <-> Placement is 1:1.
 * `joining_date || null` -> an empty date input is '', and backend wants null.
 * feedback only included when non-empty, so we don't wipe existing feedback.
 */
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
    placementModal.app = null // close the modal
    await refreshApplications()
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to record placement'
  }
}

/**
 * onMounted -> boot.
 * THE IMPORTANT BIT: a 403 here is not an error, it's a STATE. an unapproved
 * company hits this every time. so we sniff err.response.status === 403 and
 * render the yellow "pending approval" banner instead of a scary red one.
 * any other failure (500, network) falls through to the normal red bar.
 * finally{} kills the spinner either way.
 */
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
