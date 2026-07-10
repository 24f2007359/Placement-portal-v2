import api from './api'

export const exportApi = {
  startApplicationsExport() {
    return api.post('/exports/applications')
  },
  startPlacementsExport() {
    return api.post('/exports/placements')
  },
  getStatus(taskId) {
    return api.get(`/exports/status/${taskId}`)
  },
  download(filename) {
    return api.get(`/exports/download/${filename}`, { responseType: 'blob' })
  },
}

/**
 * Trigger an async Celery export, then poll until the worker finishes.
 * `onState` receives the Celery task state (PENDING / STARTED / SUCCESS).
 * Resolves with the status payload (contains `filename` and `rows`).
 */
export async function runExport(startFn, { onState, attempts = 60, intervalMs = 1000 } = {}) {
  const { data } = await startFn()
  const taskId = data.task_id

  for (let i = 0; i < attempts; i += 1) {
    const { data: status } = await exportApi.getStatus(taskId)
    onState?.(status.state)

    if (status.ready) {
      if (status.state !== 'SUCCESS') {
        throw new Error(status.error || 'Export failed')
      }
      if (status.result?.error) {
        throw new Error(status.result.error)
      }
      return status
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }

  throw new Error('Export timed out. Is the Celery worker running?')
}

/** Fetch a generated file through the authenticated API and save it. */
export async function saveBlob(fetcher, filename) {
  const { data } = await fetcher()
  const url = window.URL.createObjectURL(new Blob([data]))
  const link = document.createElement('a')
  link.href = url
  link.setAttribute('download', filename)
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

export function downloadExport(filename) {
  return saveBlob(() => exportApi.download(filename), filename)
}
