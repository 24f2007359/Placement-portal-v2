<!--
  =============================================================================
  FILE : src/views/AdminDashboard.vue
  ROUTE: /admin/dashboard   (meta: requiresAuth + role:'admin')
  WHAT : the institute placement cell's god-mode panel. 4 stat cards + 6 tabs.
           Companies      -> approve / reject / blacklist / delete
           Students       -> search, blacklist / deactivate / delete
           Job Postings   -> approve or reject placement drives
           Applications   -> read-only list + History modal (M6)
           Placements     -> every placement in the system (M6)
           Reports & Jobs -> fire Celery jobs by hand, download PDFs (M7)

  TALKS TO: services/admin.js  -> /api/admin/*   (backend/admin_routes.py)
            services/exports.js -> /api/exports/* (backend/export_routes.py)

  WHO IS ADMIN? there is NO admin registration route. the single admin row is
  created by backend/seed_admin.py at setup (admin@placement.local / admin123).

  ADMIN IS THE GATEKEEPER. two things do not happen without a click here:
    1. a company can't log into its dashboard until approveCompany()
    2. a job posting is invisible to students until approveJob()
  and approveJob() itself refuses if the parent company isn't approved yet.

  NOTE: this view is deliberately dumb about optimistic updates -- every action
  goes through withAction(), which just re-fetches EVERYTHING afterwards.
  slow, but impossible to get out of sync. fine for an admin panel.
  =============================================================================
-->
<template>
  <div>
    <h2 class="mb-1">Admin Dashboard</h2>
    <p class="text-muted mb-4">Institute placement cell control panel</p>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="success" class="alert alert-success">{{ success }}</div>

    <!-- ===================== STAT CARDS =====================
         v-if="stats" because stats starts as null (ref(null)), not an object of
         zeros like the other dashboards. so the whole row just doesn't render
         until loadDashboard() lands. no ?. needed inside. -->
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

    <!-- ===================== TAB 1: COMPANIES =====================
         the approval queue. a PENDING company is locked out of its own dashboard
         until you hit Approve here.
         reject   -> soft, reversible (they just can't get in)
         blacklist-> hard: also is_active=False so LOGIN itself fails, and their
                     jobs vanish from student search
         remove   -> DELETE, cascades jobs + placements. confirm() first. -->
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
                  <!-- Approve/Reject only make sense while still pending.
                       Blacklist/Remove always available. -->
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

    <!-- ===================== TAB 2: STUDENTS =====================
         note the 3-state status column: Blacklisted (red) / Inactive (grey) /
         Active (green). deactivate is reversible, blacklist is NOT -- backend
         400s if you try to activate a blacklisted student. -->
    <div v-show="activeTab === 'students'" class="card shadow-sm">
      <div class="card-body">
        <form class="row g-2 mb-3" @submit.prevent="loadStudents">
          <div class="col-md-8">
            <!-- one box, `q` searches name OR institute_id OR contact backend-side -->
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
                <!-- order matters: blacklisted implies !is_active, so check
                     blacklisted FIRST or every banned student shows "Inactive". -->
                <td>
                  <span v-if="s.is_blacklisted" class="badge bg-danger">Blacklisted</span>
                  <span v-else-if="!s.is_active" class="badge bg-secondary">Inactive</span>
                  <span v-else class="badge bg-success">Active</span>
                </td>
                <td class="d-flex flex-wrap gap-1">
                  <!-- Activate only offered when inactive AND not blacklisted --
                       matches the backend rule, so the button can't 400. -->
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

    <!-- ===================== TAB 3: JOB POSTINGS =====================
         THE SECOND GATE. a company posts a job -> it's 'pending' -> invisible to
         students. you approve it here -> 'approved' -> now students see it and
         the company may flip it to 'active'.
         backend refuses approveJob() if the parent company isn't approved yet. -->
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

    <!-- ===================== TAB 4: APPLICATIONS (read-only) =====================
         admin can LOOK at every application but can't change its status --
         that's the company's job. the only action is "History", which opens the
         M6 audit-trail modal (timeline + applicant summary). -->
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

    <!-- ===================== TAB 5: REPORTS & BACKGROUND JOBS (M7) =====================
         these buttons DON'T do the work. they POST, get a task_id back in ~5ms,
         and then we poll until the Celery worker (a totally separate process)
         finishes. see services/exports.js -> runExport().

         !! if redis or the celery worker isn't running, these hang on PENDING
            and fail after 60s with "Is the Celery worker running?" !!
         start them with:
            sudo service redis-server start
            celery -A celery_app.celery worker --loglevel=info
    -->
    <div v-show="activeTab === 'reports'" class="card shadow-sm">
      <div class="card-body">
        <h5 class="mb-3">Background Jobs</h5>
        <p class="text-muted small">
          These jobs also run automatically on a schedule via Celery Beat
          (reminders daily at 09:00, monthly reports on the 1st at 06:00).
          Trigger them here on demand. Requires the Celery worker and Redis to be running.
        </p>
        <div class="d-flex flex-wrap gap-2 mb-4">
          <!-- jobBusy holds the KEY of the running job ('reminders'|'reports'), so
               :disabled="jobBusy" (truthy string) greys out BOTH buttons, while
               the spinner only shows on the one actually running. neat trick. -->
          <button class="btn btn-primary" :disabled="jobBusy" @click="runInterviewReminders">
            <span v-if="jobBusy === 'reminders'" class="spinner-border spinner-border-sm me-1"></span>
            Send Interview Reminders
          </button>
          <button class="btn btn-success" :disabled="jobBusy" @click="runMonthlyReports">
            <span v-if="jobBusy === 'reports'" class="spinner-border spinner-border-sm me-1"></span>
            Generate Monthly Reports
          </button>
          <button class="btn btn-outline-primary" :disabled="exporting" @click="exportPlacements">
            <span v-if="exporting" class="spinner-border spinner-border-sm me-1"></span>
            {{ exporting ? exportState : 'Export All Placements (CSV)' }}
          </button>
        </div>

        <div v-if="jobResult" class="alert alert-info small">
          <strong>Last job result:</strong> {{ jobResult }}
        </div>

        <!-- ============ REDIS CACHE PANEL (Milestone 8) ============
             `version` is the invalidation counter. every write bumps it, which
             orphans all keys built against the old version. approve a job then
             hit Refresh -> jobs.version goes up by one. that's the demo. -->
        <hr class="my-4" />
        <div class="d-flex justify-content-between align-items-center mb-2">
          <h5 class="mb-0">Redis Cache</h5>
          <div class="d-flex gap-2">
            <button class="btn btn-sm btn-outline-secondary" @click="loadCacheStats">Refresh</button>
            <button class="btn btn-sm btn-outline-danger" :disabled="flushing" @click="flushCache">
              <span v-if="flushing" class="spinner-border spinner-border-sm me-1"></span>
              Flush Cache
            </button>
          </div>
        </div>

        <div v-if="cache && !cache.connected" class="alert alert-warning small">
          Redis is <strong>not reachable</strong> — the app still works, every request just
          reads straight from the database (cache degrades, never fails).
        </div>

        <div v-else-if="cache" class="table-responsive mb-4">
          <table class="table table-sm align-middle">
            <thead>
              <tr>
                <th>Namespace</th>
                <th>Version</th>
                <th>Live keys</th>
                <th>TTL</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(ns, name) in cache.namespaces" :key="name">
                <td><code>{{ name }}</code></td>
                <td>v{{ ns.version }}</td>
                <td>{{ ns.keys }}</td>
                <td>{{ ns.ttl_seconds }}s</td>
              </tr>
            </tbody>
          </table>
          <small v-if="cache.redis" class="text-muted">
            Redis server-wide: {{ cache.redis.keyspace_hits }} hits /
            {{ cache.redis.keyspace_misses }} misses
            ({{ cache.redis.hit_rate_pct }}% hit rate — includes Celery's databases)
          </small>
        </div>

        <hr class="my-4" />

        <!-- just an `ls` of backend/instance/reports/. filenames look like
             report_company3_2026-06.pdf (and a .html twin). generated by the
             monthly job above. -->
        <h5 class="mb-3">Generated Reports</h5>
        <button class="btn btn-sm btn-outline-secondary mb-2" @click="loadReports">Refresh list</button>
        <ul class="list-group">
          <!-- :key="file" -> the filename IS the unique id here, no .id field -->
          <li
            v-for="file in reports"
            :key="file"
            class="list-group-item d-flex justify-content-between align-items-center"
          >
            <span>{{ file }}</span>
            <!-- goes through saveBlob() so the JWT header rides along.
                 a plain <a href> would 401. -->
            <button class="btn btn-sm btn-outline-primary" @click="getReport(file)">Download</button>
          </li>
          <li v-if="!reports.length" class="list-group-item text-muted text-center">
            No reports generated yet
          </li>
        </ul>
      </div>
    </div>

    <!-- ===================== MODAL: APPLICATION HISTORY (M6) =====================
         GET /api/admin/applications/:id -> { application:{status_history}, student }
         so ONE call fills both the applicant summary line and the timeline. -->
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
          <!-- one-line applicant summary above the timeline.
               `cgpa != null` (loose !=) catches BOTH null and undefined, and
               still shows a legit CGPA of 0. plain `v-if="cgpa"` would hide 0. -->
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
import { downloadExport, exportApi, runExport, saveBlob } from '../services/exports'

const tabs = [
  { id: 'companies', label: 'Companies' },
  { id: 'students', label: 'Students' },
  { id: 'jobs', label: 'Job Postings' },
  { id: 'applications', label: 'Applications' },
  { id: 'placements', label: 'Placements' },
  { id: 'reports', label: 'Reports & Jobs' },
]

const activeTab = ref('companies') // land on the approval queue -- that's the job

// stats starts NULL (not zeros) -> the whole stat row is v-if'd off until loaded
const stats = ref(null)

// --- table data --------------------------------------------------------------
const companies = ref([])
const students = ref([])
const jobs = ref([])
const applications = ref([])
const placements = ref([])

// --- History modal (M6). detailApp non-null = modal open ---------------------
const detailApp = ref(null)
const detailTimeline = ref([])
const detailStudent = ref(null)

// --- M7 background-job UI state ---------------------------------------------
const reports = ref([]) // filenames in instance/reports/
const jobBusy = ref('') // '' | 'reminders' | 'reports' -> which job is running
const jobResult = ref('') // human summary of the last job's return value
const exporting = ref(false)
const exportState = ref('')

// --- M8 cache panel state ----------------------------------------------------
const cache = ref(null) // null until first load; {enabled, connected, namespaces}
const flushing = ref(false)

const error = ref('')
const success = ref('')

const companySearch = reactive({ q: '', industry: '', status: '' })
const studentSearch = reactive({ q: '' })
const jobSearch = reactive({ q: '', status: '' })

/** COMPANY approval_status -> badge colour (pending/approved/rejected) */
function statusBadge(status) {
  return { pending: 'bg-warning text-dark', approved: 'bg-success', rejected: 'bg-danger' }[status] || 'bg-secondary'
}

/** JOB status -> badge colour (pending/approved/active/closed) */
function jobStatusBadge(status) {
  return { pending: 'bg-warning text-dark', approved: 'bg-success', active: 'bg-primary', closed: 'bg-secondary' }[status] || 'bg-secondary'
}

/** APPLICATION status -> badge colour. three different enums, three different
 *  badge fns. don't mix them up -- 'approved' isn't an application status. */
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

/** ISO -> local readable string. em-dash on null. */
function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

function clearMessages() {
  error.value = ''
  success.value = ''
}

/**
 * withAction(fn, message)
 * what : the wrapper EVERY admin mutation goes through.
 *        clear alerts -> run the API call -> show a success msg -> refetch all.
 * why  : approving a company changes the companies table, the stat cards, AND
 *        potentially which jobs are approvable. rather than surgically patching
 *        state, we just reload everything. dumb but bulletproof.
 * where: approveCompany, rejectCompany, blacklistStudent, approveJob, ... all of them.
 * cost : ~7 API calls per click. totally fine for an admin panel with one user.
 */
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

/**
 * openApplicationDetail(application)   [M6]
 * what : the "History" button. one call gives us BOTH the timeline and the
 *        applicant's profile (backend returns {application, student}).
 * order: open the modal instantly, blank the previous rows/student so the old
 *        applicant's data doesn't flash while the new request is in flight.
 */
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

/** GET /api/admin/reports -> list of filenames sitting in instance/reports/. */
async function loadReports() {
  const { data } = await adminApi.getReports()
  reports.value = data.reports
}

/**
 * summariseJob(result)
 * what : turn a Celery task's raw return dict into one readable line.
 * why  : the monthly-report task returns a big nested blob (every company, every
 *        stat). JSON.stringify'ing that into the UI is unreadable garbage. so we
 *        sniff which task it was by looking for a signature key and format it.
 *          'sent'      in result -> it was send_interview_reminders
 *          'companies' in result -> it was generate_monthly_placement_reports
 * fallback 'done' for anything unrecognised.
 */
function summariseJob(result) {
  if (!result || typeof result !== 'object') return 'done'
  if ('sent' in result) {
    return `${result.sent} reminder(s) sent, ${result.skipped} skipped (of ${result.checked} checked)`
  }
  if ('companies' in result) {
    return `${result.companies} report(s) generated for ${result.period}`
  }
  return 'done'
}

/** download a generated .pdf/.html report. saveBlob does the authed-fetch +
 *  fake-anchor-click dance (see services/exports.js). */
function getReport(filename) {
  return saveBlob(() => adminApi.downloadReport(filename), filename)
}

/**
 * loadCacheStats() -> GET /api/admin/cache/stats   [M8]
 * fills the Redis Cache table. swallows its own errors into `cache.connected`
 * rather than the red alert bar -- a dead redis is a *state* to display, not a
 * dashboard failure. that mirrors the backend, which degrades instead of 500ing.
 */
async function loadCacheStats() {
  try {
    const { data } = await adminApi.getCacheStats()
    cache.value = data.cache
  } catch {
    cache.value = { enabled: false, connected: false, namespaces: {} }
  }
}

/**
 * flushCache() -> POST /api/admin/cache/flush   [M8]
 * bumps every namespace version. next read of anything is a MISS.
 * after: reload stats so you can watch the version numbers jump.
 */
async function flushCache() {
  clearMessages()
  flushing.value = true
  try {
    const { data } = await adminApi.flushCache()
    cache.value = data.cache
    success.value = 'Cache flushed — every namespace version bumped'
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to flush cache'
  } finally {
    flushing.value = false
  }
}

/**
 * runJob(key, startFn, label)   [M7]
 * what : fire a Celery job, poll till done, show a summary.
 * args : key   -> 'reminders'|'reports', drives which spinner shows
 *        startFn -> adminApi.runInterviewReminders | runMonthlyReports
 *        label -> prefix for the result line
 * reuses runExport() from services/exports.js -- it doesn't care that this is a
 *        report job rather than a CSV export, the poll protocol is identical.
 * after: reload the reports list, since the monthly job just wrote new files.
 * err  : `err.message` catches runExport's own throws (timeout / worker down).
 */
async function runJob(key, startFn, label) {
  clearMessages()
  jobBusy.value = key
  jobResult.value = ''
  try {
    const status = await runExport(startFn)
    jobResult.value = `${label} — ${summariseJob(status.result)}`
    success.value = `${label} completed`
    await loadReports()
  } catch (err) {
    error.value = err.response?.data?.error || err.message || `${label} failed`
  } finally {
    jobBusy.value = '' // always re-enable the buttons
  }
}

const runInterviewReminders = () =>
  runJob('reminders', adminApi.runInterviewReminders, 'Interview reminders')
const runMonthlyReports = () =>
  runJob('reports', adminApi.runMonthlyReports, 'Monthly report generation')

/**
 * exportPlacements()   [M7]
 * admin flavour -> the backend gives admin EVERY placement, not just one org's.
 * same queue/poll/download flow as the other dashboards.
 */
async function exportPlacements() {
  clearMessages()
  exporting.value = true
  exportState.value = 'Queued...'
  try {
    const status = await runExport(exportApi.startPlacementsExport, {
      onState: (state) => {
        exportState.value = state === 'SUCCESS' ? 'Downloading...' : `${state}...`
      },
    })
    await downloadExport(status.filename)
    success.value = `Placements exported (${status.rows} rows)`
  } catch (err) {
    error.value = err.response?.data?.error || err.message || 'Export failed'
  } finally {
    exporting.value = false
    exportState.value = ''
  }
}

/** re-pull EVERY tab's data. called on mount and after every withAction().
 *  7 sequential requests. yes it's heavy. no, it doesn't matter here. */
async function refreshAll() {
  await loadDashboard()
  await loadCompanies()
  await loadStudents()
  await loadJobs()
  await loadApplications()
  await loadPlacements()
  await loadReports()
  await loadCacheStats()
}

// ---------------------------------------------------------------------------
// ACTION HANDLERS
// all one-liners because withAction() already owns the try/catch + refresh.
// the () => arrow inside withAction is a THUNK -- we hand withAction a function
// to call, not the promise itself, so it controls when it fires.
//
// the destructive ones (remove*) guard with a native confirm() first, and
// `return` early -- note they don't await, they're fire-and-forget void fns.
// ---------------------------------------------------------------------------

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

/** boot. no `loading` flag here (unlike the other two dashboards) -- the stat
 *  row is v-if'd on `stats` being non-null, and empty tables render their own
 *  "no rows" placeholder, so there's nothing to gate. */
onMounted(async () => {
  try {
    await refreshAll()
  } catch (err) {
    error.value = err.response?.data?.error || 'Failed to load dashboard'
  }
})
</script>
