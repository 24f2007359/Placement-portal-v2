<!--
  =============================================================================
  FILE : src/views/StudentDashboard.vue
  ROUTE: /student/dashboard   (meta: requiresAuth + role:'student')
  WHAT : the student's whole world. 5 stat cards + 4 tabs.
           Profile      -> edit cgpa/branch/skills, upload resume
           Browse Jobs  -> search approved drives, hit Apply
           Applications -> track status, view Timeline modal, grab offer letter
           Placements   -> your placement records (M6)

  TALKS TO: services/student.js  -> /api/student/*   (backend/student_routes.py)
            services/exports.js  -> /api/exports/*   (backend/export_routes.py, M7)
            services/auth.js     -> just to read the logged-in name

  BIG PICTURE: this view is READ-heavy. the only things a student can WRITE are
  their own profile, their resume, and an Application row. everything else
  (status changes, placements) is done TO them by a company/admin -- they just
  watch it happen through the Timeline.
  =============================================================================
-->
<template>
  <div>
    <h2 class="mb-1">Student Dashboard</h2>
    <!-- ?.?. chain: on first paint auth.user may be null, and a fresh student
         may have no .profile yet. one missing ?. = white screen of death. -->
    <p class="text-muted mb-4">{{ auth.user?.profile?.full_name }}</p>

    <!-- the two universal message bars. every action sets one or the other via
         error.value / success.value. clearMessages() wipes both first. -->
    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="success" class="alert alert-success">{{ success }}</div>

    <div v-if="loading" class="alert alert-info">Loading dashboard...</div>

    <!-- v-else on a <template> = "render this whole block once loading is done"
         without adding a junk wrapper <div> to the DOM. -->
    <template v-else>
      <!-- ===================== STAT CARDS =====================
           `col-6 col-md` -> 2-per-row on mobile, 5 equal columns on desktop.
           (plain col-md-3 would only fit 4 and wrap the 5th onto its own row)
           data comes from GET /api/student/dashboard -> stats{} -->
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
        <!-- green, not blue -> this is the one that actually matters (M6) -->
        <div class="col-6 col-md">
          <div class="card text-center shadow-sm">
            <div class="card-body">
              <h3 class="text-success mb-0">{{ stats.placed }}</h3>
              <small class="text-muted">Placed</small>
            </div>
          </div>
        </div>
      </div>

      <!-- ===================== TAB STRIP =====================
           dead simple: activeTab is a string, buttons set it, panels v-show on it.
           no vue-router child routes, no bootstrap JS tab plugin. -->
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

      <!-- ===================== TAB 1: PROFILE =====================
           v-show not v-if -> panels stay mounted, so switching tabs doesn't
           blow away half-typed form state. -->
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
              <!-- :value + disabled (NOT v-model) -> read-only. institute_id is a
                   unique key set at registration, students can't rewrite it. -->
              <input :value="profileForm.institute_id" class="form-control" disabled />
            </div>
            <div class="col-md-4">
              <label class="form-label">Contact</label>
              <input v-model="profileForm.contact" class="form-control" />
            </div>

            <!-- === THE ELIGIBILITY TRIO ===
                 branch + cgpa + graduation_year are what
                 student_routes.py::_check_eligibility() tests when you click
                 Apply. leave them blank and any job with eligibility rules will
                 reject you with "CGPA is required in your profile to apply". -->
            <div class="col-md-4">
              <label class="form-label">Branch</label>
              <input v-model="profileForm.branch" class="form-control" placeholder="e.g. CSE" />
            </div>
            <div class="col-md-2">
              <label class="form-label">CGPA</label>
              <!-- .number modifier -> vue casts the input string to a Number.
                   without it you'd POST "8.5" and the float compare gets weird. -->
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
              <!-- you CANNOT v-model a file input (security). so we listen to
                   @change and pull the File object out ourselves -> onResumeSelected -->
              <input type="file" class="form-control" accept=".pdf,.doc,.docx,.txt" @change="onResumeSelected" />
              <small v-if="profileForm.resume_path" class="text-muted d-block mt-1">
                <!-- resume_path is a full server path. split on / or \ (windows vs
                     linux) and take the last chunk = just the filename. -->
                Current: {{ profileForm.resume_path.split(/[/\\]/).pop() }}
              </small>
            </div>
            <div class="col-12 d-flex gap-2">
              <button class="btn btn-primary" type="submit">Save Profile</button>
              <!-- upload is a SEPARATE call from save (multipart vs json), so it
                   gets its own button, and only once a file is actually picked. -->
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

      <!-- ===================== TAB 2: BROWSE JOBS =====================
           only shows APPROVED drives from APPROVED, non-blacklisted companies.
           that filtering happens backend-side in _approved_jobs_query(). -->
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

          <!-- table-responsive -> horizontal scroll on phones instead of the
               whole page blowing out sideways -->
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
                <!-- :key="job.id" -> lets vue reuse DOM nodes instead of
                     re-rendering the whole tbody on every search -->
                <tr v-for="job in jobs" :key="job.id">
                  <td>
                    <div>{{ job.title }}</div>
                    <small class="text-muted">{{ formatSalary(job) }}</small>
                  </td>
                  <td>{{ job.company_name }}</td>
                  <td>{{ job.skills_required || '—' }}</td>
                  <td>
                    <!-- show whichever eligibility rules exist; if none, "Open" -->
                    <small>
                      <span v-if="job.eligibility_cgpa">CGPA ≥ {{ job.eligibility_cgpa }}</span>
                      <span v-if="job.eligibility_branch"><br />Branch: {{ job.eligibility_branch }}</span>
                      <span v-if="job.eligibility_year"><br />Year: {{ job.eligibility_year }}</span>
                      <span v-if="!job.eligibility_cgpa && !job.eligibility_branch && !job.eligibility_year">Open</span>
                    </small>
                  </td>
                  <td>{{ formatDate(job.application_deadline) }}</td>
                  <td>
                    <!-- backend sends already_applied per job, so we grey the
                         button out instead of letting them fire a doomed 409.
                         (backend still blocks it -- this is just UX) -->
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
                <!-- empty-state row. colspan must match the th count or the
                     table borders go crooked. -->
                <tr v-if="!jobs.length">
                  <td colspan="6" class="text-center text-muted">No approved jobs found</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ===================== TAB 3: MY APPLICATIONS ===================== -->
      <div v-show="activeTab === 'applications'" class="card shadow-sm">
        <div class="card-body">
          <div class="row g-2 mb-3 align-items-center">
            <div class="col-md-4">
              <!-- @change fires loadApplications immediately -> server-side filter
                   (?status=), not a client-side .filter(). keeps it honest. -->
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
            <div class="col-md-8 text-md-end">
              <!-- M7 ASYNC EXPORT. this does NOT block. it queues a celery job,
                   polls, then downloads. label live-updates PENDING.. -> Downloading..
                   needs redis + `celery worker` running or it times out at 60s. -->
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
                  <!-- :class binds the bootstrap colour class from the lookup fn -->
                  <td><span class="badge" :class="applicationStatusBadge(app.status)">{{ app.status }}</span></td>
                  <td>{{ formatDate(app.applied_at) }}</td>
                  <td>{{ formatDate(app.interview_date) }}</td>
                  <td>{{ app.feedback || '—' }}</td>
                  <td class="d-flex gap-1">
                    <!-- M6: opens the audit-trail modal. fires a 2nd API call
                         because the LIST payload deliberately omits history. -->
                    <button class="btn btn-sm btn-outline-secondary" @click="openTimeline(app)">
                      Timeline
                    </button>
                    <!-- has_offer_letter is true only for offer|placed -->
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

      <!-- ===================== TAB 4: PLACEMENTS (M6) =====================
           a Placement row only springs into existence when a company marks you
           offer/placed. so this is empty for most students. -->
      <div v-show="activeTab === 'placements'" class="card shadow-sm">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <h5 class="mb-0">My Placements</h5>
            <button class="btn btn-outline-primary btn-sm" :disabled="exporting" @click="exportPlacements">
              <span v-if="exporting" class="spinner-border spinner-border-sm me-1"></span>
              {{ exporting ? exportState : 'Export Placements (CSV)' }}
            </button>
          </div>
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
                  <!-- salary can legitimately be null -> show a dash, not "₹null" -->
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

    <!-- ===================== TIMELINE MODAL (M6) =====================
         hand-rolled modal, NOT bootstrap's JS modal -- we just need a fixed
         overlay + a card. styles live in assets/main.css
         (.modal-backdrop-custom / .modal-card / .timeline).

         v-if="timelineApp" -> the object doubles as the open/closed flag.
         @click.self -> only closes when you click the BACKDROP itself, not when
         the click bubbles up from the card inside it. drop `.self` and clicking
         anything in the modal shuts it. -->
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
          <!-- one <li> per status transition, oldest first (backend orders by
               created_at). the little dots + vertical line are CSS ::before. -->
          <ul class="list-unstyled timeline">
            <li v-for="(entry, i) in timeline" :key="i" class="mb-3">
              <span class="badge" :class="applicationStatusBadge(entry.to_status)">{{ entry.to_status }}</span>
              <!-- first entry ('applied') has from_status null -> hide the "from x" -->
              <span v-if="entry.from_status" class="text-muted small ms-2">from {{ entry.from_status }}</span>
              <div class="small text-muted">{{ formatDate(entry.created_at) }}
                <span v-if="entry.changed_by_role">· by {{ entry.changed_by_role }}</span></div>
              <!-- note = whatever feedback the company typed on that transition -->
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
import { downloadExport, exportApi, runExport } from '../services/exports'

const auth = useAuth()

// --- top-level ui state ------------------------------------------------------
const loading = ref(true) // true until the first refreshAll() settles
const error = ref('') // red bar text
const success = ref('') // green bar text

// mirrors GET /api/student/dashboard -> stats{}. pre-seeded with 0s so the
// cards render "0" instead of "undefined" during the first paint.
const stats = reactive({
  available_jobs: 0,
  applications_submitted: 0,
  shortlisted: 0,
  interviews_scheduled: 0,
  placed: 0,
})

// plain const array, not reactive -- the tab list never changes at runtime.
const tabs = [
  { id: 'profile', label: 'Profile' },
  { id: 'jobs', label: 'Browse Jobs' },
  { id: 'applications', label: 'My Applications' },
  { id: 'placements', label: 'Placements' },
]
const activeTab = ref('jobs') // land on Browse Jobs -- that's why they're here

// --- table data (all filled by the load* fns below) --------------------------
const jobs = ref([])
const applications = ref([])
const placements = ref([])

// --- timeline modal state ----------------------------------------------------
const timelineApp = ref(null) // the application whose modal is open (null = closed)
const timeline = ref([]) // its status_history rows, fetched separately

// --- misc --------------------------------------------------------------------
const selectedResume = ref(null) // the File object picked in the file input
const exporting = ref(false) // disables BOTH export buttons while one runs
const exportState = ref('') // live celery state text on the button

const jobSearch = reactive({ q: '', company: '' })
const applicationFilter = reactive({ status: '' })

// shape must match what GET /api/student/profile returns, because loadProfile()
// does a blind Object.assign(profileForm, data.profile).
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

/** wipe both message bars. call at the top of every action so a stale red
 *  error doesn't sit under a fresh green success. */
function clearMessages() {
  error.value = ''
  success.value = ''
}

/** ISO string (or null) -> readable local date-time. em-dash for empty.
 *  used all over the templates above. toLocaleString() respects the user's
 *  browser locale/timezone -- backend always sends UTC ISO. */
function formatDate(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

/** build the salary line under a job title. handles all 4 cases:
 *  both bounds / only min / only max / neither (returns '' -> renders nothing). */
function formatSalary(job) {
  if (job.salary_min && job.salary_max) {
    return `₹${job.salary_min} – ₹${job.salary_max}`
  }
  if (job.salary_min) return `From ₹${job.salary_min}`
  if (job.salary_max) return `Up to ₹${job.salary_max}`
  return ''
}

/**
 * status string -> bootstrap badge class.
 * object-literal-as-switch. the `|| 'bg-secondary'` catches any status the
 * backend adds later that we forgot to map here.
 * NOTE: same fn is duplicated in CompanyDashboard.vue + AdminDashboard.vue.
 *       kept local on purpose so each dashboard stays self-contained.
 */
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

// --- loaders: one per API endpoint, each just fills a ref -------------------

/** GET /api/student/dashboard -> the 5 stat cards.
 *  Object.assign (not stats = data.stats) -> we must MUTATE the reactive object,
 *  reassigning the const would break reactivity (and throw). */
async function loadDashboard() {
  const { data } = await studentApi.getDashboard()
  Object.assign(stats, data.stats)
}

/** GET /api/student/profile -> fills the Profile tab form. */
async function loadProfile() {
  const { data } = await studentApi.getProfile()
  Object.assign(profileForm, data.profile)
}

/** GET /api/student/jobs?q=&company= -> Browse Jobs table.
 *  {...jobSearch} spreads the reactive proxy into a plain object for axios. */
async function loadJobs() {
  const { data } = await studentApi.getJobs({ ...jobSearch })
  jobs.value = data.jobs
}

/** GET /api/student/applications[?status=] -> My Applications table.
 *  we only send `status` when it's non-empty, else backend 400s on ''. */
async function loadApplications() {
  const params = applicationFilter.status ? { status: applicationFilter.status } : {}
  const { data } = await studentApi.getApplications(params)
  applications.value = data.applications
}

/** GET /api/student/placements -> Placements tab. (M6) */
async function loadPlacements() {
  const { data } = await studentApi.getPlacements()
  placements.value = data.placements
}

/**
 * openTimeline(application)   [M6]
 * what : pop the modal, then fetch that ONE application's status_history.
 * why a 2nd request? the /applications list endpoint omits history to keep the
 *      payload small -- no point shipping 6 history rows x 40 applications.
 * order: we set timelineApp FIRST (modal opens instantly, feels snappy) and
 *      blank `timeline` so the previous application's rows don't flash.
 */
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

/**
 * refreshAll()
 * what : re-pull every table + the stats. called on mount and after any action
 *        that could change more than one thing (e.g. applying to a job bumps
 *        stats AND the jobs table AND the applications table).
 * note : sequential awaits, not Promise.all. slower, but 5 parallel requests on
 *        a school laptop + SQLite isn't worth the race-condition risk.
 */
async function refreshAll() {
  await loadDashboard()
  await loadProfile()
  await loadJobs()
  await loadApplications()
  await loadPlacements()
}

/**
 * runAndDownload(startFn, label)     [M7 -- the async export dance]
 * what : queue a celery job -> poll it -> auto-download the CSV when done.
 * args : startFn = exportApi.startApplicationsExport | startPlacementsExport
 *        label   = just for the success message text
 * flow : runExport() (services/exports.js) does the POST + the polling loop and
 *        hands back { filename, rows }. we then pull the bytes down.
 * the onState callback rewrites the button label live as celery moves
 *        PENDING -> STARTED -> SUCCESS.
 * err  : could be an axios error (has .response) OR a plain Error thrown by
 *        runExport ("Export timed out. Is the Celery worker running?"), hence
 *        the `err.response?.data?.error || err.message ||` ladder.
 * finally: ALWAYS un-disable the buttons, even if it blew up.
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

// thin arrow wrappers so the template's @click stays clean
const exportApplications = () =>
  runAndDownload(exportApi.startApplicationsExport, 'Applications')
const exportPlacements = () =>
  runAndDownload(exportApi.startPlacementsExport, 'Placements')

/**
 * onResumeSelected(event)
 * what : @change handler for the file input. stash the File object in a ref.
 * why  : v-model doesn't work on <input type=file> (browsers won't let JS set
 *        a file input's value). so we reach into event.target.files ourselves.
 * `?.[0] || null` -> user can cancel the picker, leaving files empty.
 * setting selectedResume also makes the "Upload Resume" button appear (v-if).
 */
function onResumeSelected(event) {
  selectedResume.value = event.target.files?.[0] || null
}

/**
 * saveProfile() -> PUT /api/student/profile
 * what : Save Profile button. sends the whole form; backend only applies keys
 *        that are present, so this doubles as a partial update.
 * extra: we also patch auth.user.profile so the navbar / greeting name update
 *        without a page reload. (guarded by ?. -- profile may not exist yet)
 */
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

/**
 * uploadResume() -> POST /api/student/profile/resume (multipart)
 * guard: bail early if no file picked (button shouldn't even render, but still).
 * after: backend returns the refreshed profile (with the new resume_path), so we
 *        Object.assign it and null out selectedResume -> the button disappears.
 */
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

/**
 * applyForJob(job) -> POST /api/student/jobs/:id/apply
 * what : the Apply button.
 * after: full refreshAll() -- because this touches stats (applications+1), the
 *        jobs table (already_applied flips true) and the applications table.
 * errors you'll actually see here:
 *   "You have already applied for this job"          (409, dup guard)
 *   "Minimum CGPA required is 8.0"                   (400, eligibility)
 *   "Application deadline has passed"                (400)
 */
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

/**
 * downloadOffer(application) -> GET /api/student/applications/:id/offer-letter
 * what : the blob-download dance, same idea as exports.js::saveBlob().
 *        fetch bytes with axios (so the JWT header rides along), wrap in a Blob,
 *        make a temp <a download>, click it, then clean up the object URL.
 * why not a plain <a href>? a normal link navigation sends NO Authorization
 *        header -> the backend would 401.
 * note : this predates saveBlob() and is left inline. could be refactored to use
 *        it, but the filename convention differs (offer_letter_<id>.txt).
 */
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

/**
 * onMounted -> the boot sequence.
 * finally{} sets loading=false NO MATTER WHAT, so a failed API call shows the
 * red error bar instead of an eternal "Loading dashboard...".
 * (a blacklisted/deactivated student gets 403 here and sees the error.)
 */
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
