// =============================================================================
// FILE   : src/services/exports.js                          [Milestone 7]
// WHAT   : client side of the async CSV export flow + a generic "download a
//          blob through an authed request" helper.
// USED BY:
//   views/StudentDashboard.vue -> exportApplications() / exportPlacements()
//   views/CompanyDashboard.vue -> exportApplications() / exportPlacements()
//   views/AdminDashboard.vue   -> exportPlacements(), runJob(), getReport()
//
// BACKEND COUNTERPART: backend/export_routes.py + backend/tasks.py
//
// -----------------------------------------------------------------------------
// WHY IS THIS ASYNC AT ALL? (the whole point of milestone 7)
//
// building a CSV for 500 applications + emailing it takes seconds. if we did it
// inside the HTTP request, the browser would just hang and gunicorn would tie up
// a worker. so instead:
//
//   1. POST /api/exports/applications
//        -> Flask shoves a job onto REDIS and immediately returns 202 {task_id}
//        -> request is DONE in ~5ms. nothing has been generated yet.
//
//   2. a separate CELERY WORKER process picks the job off redis, builds the CSV,
//      writes it to backend/instance/exports/, emails it, and stores its return
//      value ({filename, rows, path}) back in redis (the "result backend").
//
//   3. we POLL GET /api/exports/status/<task_id> every 1s.
//        state goes PENDING -> (STARTED) -> SUCCESS
//        once ready:true + SUCCESS, the payload has `filename`.
//
//   4. GET /api/exports/download/<filename> -> actual bytes.
//
// the email in step 2 is the milestone's required "alert once the batch job is
// complete". the polling here is just so the UI can auto-download too.
// =============================================================================

import api from './api'

export const exportApi = {
  /**
   * startApplicationsExport() -> POST /api/exports/applications
   * what : queue the job. returns { message, task_id }. does NOT return a file.
   * who  : student -> their own applications.
   *        company -> applications received on their own jobs.
   *        (backend decides based on the JWT role, we send no body at all)
   */
  startApplicationsExport() {
    return api.post('/exports/applications')
  },

  /**
   * startPlacementsExport() -> POST /api/exports/placements
   * same deal. student -> own placements, company -> own, admin -> ALL of them.
   */
  startPlacementsExport() {
    return api.post('/exports/placements')
  },

  /**
   * getStatus(taskId) -> GET /api/exports/status/:taskId
   * what : ask redis "is celery done with this job yet?"
   * returns: { task_id, state, ready, filename?, rows?, result?, error? }
   *   state  -> 'PENDING' (queued OR unknown id!), 'STARTED', 'SUCCESS', 'FAILURE'
   *   ready  -> true once it's finished, success or fail
   * gotcha: celery can't tell "queued" apart from "bogus task id" -- both read
   *         PENDING. so a dead worker looks identical to a slow one. that's why
   *         runExport() below gives up after N attempts.
   */
  getStatus(taskId) {
    return api.get(`/exports/status/${taskId}`)
  },

  /**
   * download(filename) -> GET /api/exports/download/:filename
   * gotcha: responseType 'blob'. without it axios decodes bytes as utf-8 text
   *         and your CSV/PDF comes out garbled.
   * SECURITY (backend side): non-admins can only pull files whose name contains
   *         "user<their id>_" -- filenames are stamped like
   *         applications_user7_20260710051237.csv. so student 7 can't guess
   *         student 8's export. plus path-traversal is blocked (../ -> 404).
   */
  download(filename) {
    return api.get(`/exports/download/${filename}`, { responseType: 'blob' })
  },
}

/**
 * runExport(startFn, opts)
 * -----------------------------------------------------------------------------
 * what : the "fire the job, then sit and poll till it's cooked" loop.
 *        this is the function that hides ALL the async ugliness from the .vue files.
 *
 * where: called by every dashboard.
 *          StudentDashboard.vue / CompanyDashboard.vue -> runAndDownload()
 *          AdminDashboard.vue -> runJob() (reminders, monthly reports) and
 *                                exportPlacements()
 *
 * args :
 *   startFn   -> a function that POSTs and resolves to { data: { task_id } }.
 *                we take a FUNCTION not a task_id so the caller can just pass
 *                `exportApi.startApplicationsExport` and we own the whole flow.
 *   onState   -> optional callback, gets the raw celery state string each poll.
 *                dashboards use it to live-update the button label
 *                ("PENDING..." -> "Downloading...").
 *   attempts  -> how many polls before we bail (default 60)
 *   intervalMs-> gap between polls (default 1000ms) -> so ~60s ceiling total.
 *
 * returns: the final status payload -> { state:'SUCCESS', ready:true, filename, rows, result }
 *
 * throws (all caught by the caller's try/catch and shown in the red alert bar):
 *   - 'Export failed'      -> celery state came back FAILURE (task raised)
 *   - result.error         -> task ran fine but returned {error: '...'},
 *                             e.g. "Student profile not found"
 *   - 'Export timed out...' -> we polled 60x and it never left PENDING.
 *                             99% of the time this means THE CELERY WORKER
 *                             ISN'T RUNNING. that's why the message says so.
 *
 * note : it's a plain for-loop + await sleep, not setInterval. reason -> we want
 *        the requests SERIAL (next poll only after the previous resolves), so a
 *        slow network can't stack up 60 in-flight requests.
 */
export async function runExport(startFn, { onState, attempts = 60, intervalMs = 1000 } = {}) {
  // step 1: queue the job, grab the ticket number.
  const { data } = await startFn()
  const taskId = data.task_id

  // step 2: poll redis via the status endpoint until it's done (or we give up).
  for (let i = 0; i < attempts; i += 1) {
    const { data: status } = await exportApi.getStatus(taskId)
    onState?.(status.state) // ?. -> caller may not care about live state

    if (status.ready) {
      // finished, but "finished" != "worked". could be FAILURE.
      if (status.state !== 'SUCCESS') {
        throw new Error(status.error || 'Export failed')
      }
      // task returned normally but with a business-logic error inside.
      // e.g. tasks.export_applications_csv returns {"error": "User not found"}
      if (status.result?.error) {
        throw new Error(status.result.error)
      }
      return status
    }

    // not ready -> nap 1s. this is the "await sleep" idiom, JS has no sleep().
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }

  throw new Error('Export timed out. Is the Celery worker running?')
}

/**
 * saveBlob(fetcher, filename)
 * -----------------------------------------------------------------------------
 * what : yank a file down through an AUTHENTICATED axios call and make the
 *        browser save it.
 *
 * WHY NOT just <a href="/api/exports/download/foo.csv">? because a plain anchor
 *        navigation carries NO Authorization header -> backend 401s. so we have
 *        to fetch it with axios (interceptor adds the JWT), get raw bytes, and
 *        fake a click on a temporary object-URL link.
 *
 * args : fetcher  -> zero-arg fn returning an axios promise with responseType:'blob'
 *                    (we take a fn so this works for BOTH exports and reports)
 *        filename -> what to name it on disk
 *
 * where: downloadExport() below, and AdminDashboard.vue -> getReport() for PDFs.
 *
 * cleanup: revokeObjectURL + link.remove() -> otherwise every download leaks a
 *        blob in memory until the tab is closed.
 */
export async function saveBlob(fetcher, filename) {
  const { data } = await fetcher()
  const url = window.URL.createObjectURL(new Blob([data]))
  const link = document.createElement('a')
  link.href = url
  link.setAttribute('download', filename)
  document.body.appendChild(link)
  link.click() // programmatic click = browser's Save dialog
  link.remove()
  window.URL.revokeObjectURL(url) // free the blob
}

/**
 * downloadExport(filename)
 * what : sugar. saveBlob() pre-wired to the /exports/download route.
 * where: StudentDashboard / CompanyDashboard / AdminDashboard, right after
 *        runExport() resolves and hands us status.filename.
 */
export function downloadExport(filename) {
  return saveBlob(() => exportApi.download(filename), filename)
}
