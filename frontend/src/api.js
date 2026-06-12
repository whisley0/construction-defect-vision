/**
 * API client — upload + crosscheck (pattern from FullStack_RAG frontend/src/api.js).
 */

const API_BASE = ''

async function parseApiError(res, data) {
  const msg = data?.detail?.message || data?.detail || data?.message || res.statusText
  throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
}

export async function extractRfiPdf(file, { signal } = {}) {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`${API_BASE}/api/rfi/extract`, {
    method: 'POST',
    body: fd,
    signal,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

/** Upload multiple PDFs (multi-select or folder). Non-PDF files are skipped client-side. */
export async function extractRfiPdfBatch(files, { signal, failFast = false } = {}) {
  const pdfs = [...files].filter((f) => f.name?.toLowerCase().endsWith('.pdf'))
  if (!pdfs.length) throw new Error('No PDF files selected.')

  const fd = new FormData()
  for (const file of pdfs) {
    fd.append('files', file)
  }
  if (failFast) fd.append('fail_fast', 'true')

  const res = await fetch(`${API_BASE}/api/rfi/extract-batch`, {
    method: 'POST',
    body: fd,
    signal,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function getRfiExtraction(uploadId, { signal } = {}) {
  const res = await fetch(`${API_BASE}/api/rfi/${encodeURIComponent(uploadId)}/extraction`, { signal })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export function pdfPreviewUrl(uploadId) {
  return `${API_BASE}/api/rfi/${encodeURIComponent(uploadId)}/file`
}

export function imageUrl(uploadId, imageFilename) {
  return `${API_BASE}/api/rfi/${encodeURIComponent(uploadId)}/images/${encodeURIComponent(imageFilename)}`
}

export async function checkHealth() {
  const res = await fetch(`${API_BASE}/health`)
  return res.ok
}

export async function testDataStatus() {
  const res = await fetch(`${API_BASE}/api/test-data/status`)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function setTestDataLocalDir(localDir) {
  const res = await fetch(`${API_BASE}/api/test-data/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ local_dir: localDir }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function scanTestDataFolder() {
  const res = await fetch(`${API_BASE}/api/test-data/scan`, { method: 'POST' })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function inspectoMetadataStatus() {
  const res = await fetch(`${API_BASE}/api/test-data/inspecto-metadata/status`)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function uploadInspectoMetadata(file) {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`${API_BASE}/api/test-data/inspecto-metadata/upload`, {
    method: 'POST',
    body: fd,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function clearTestDataExtractions() {
  const res = await fetch(`${API_BASE}/api/test-data/clear-extractions`, { method: 'POST' })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function extractTestDataFiles({ relativePaths = [], limit = 100 } = {}) {
  const res = await fetch(`${API_BASE}/api/test-data/extract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      relative_paths: relativePaths,
      limit,
    }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function testDataAuthStatus() {
  const res = await fetch(`${API_BASE}/api/test-data/auth/status`)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function setTestDataSessionCookie(cookie) {
  const res = await fetch(`${API_BASE}/api/test-data/session`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookie }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function signOutTestDataAuth() {
  const res = await fetch(`${API_BASE}/api/test-data/auth/sign-out`, { method: 'POST' })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function refreshSharePointList() {
  const res = await fetch(`${API_BASE}/api/test-data/remote/refresh`, { method: 'POST' })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function probeSharePointList() {
  const res = await fetch(`${API_BASE}/api/test-data/remote/probe`)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function compareTestData({
  syncStatus = '',
  localStatus = '',
  hasLocal = false,
  extractedFirst = false,
  search = '',
  page = 1,
  pageSize = 100,
} = {}) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (syncStatus) params.set('sync_status', syncStatus)
  if (localStatus) params.set('local_status', localStatus)
  if (hasLocal) params.set('has_local', 'true')
  if (extractedFirst) params.set('extracted_first', 'true')
  if (search) params.set('search', search)
  const res = await fetch(`${API_BASE}/api/test-data/compare?${params}`)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function downloadTestDataFiles({ relativePaths = [], downloadAllMissing = false, limit = 50 } = {}) {
  const res = await fetch(`${API_BASE}/api/test-data/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      relative_paths: relativePaths,
      download_all_missing: downloadAllMissing,
      limit,
    }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function getTestDataJob(jobId) {
  const res = await fetch(`${API_BASE}/api/test-data/jobs/${encodeURIComponent(jobId)}`)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function datasetSummary() {
  const res = await fetch(`${API_BASE}/api/dataset/summary`)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function datasetImages({
  search = '',
  imageType = '',
  inspectionOutcome = '',
  folder = '',
  trainableOnly = false,
  manualOnly = false,
  multiRevisionOnly = false,
  minRevisions = 2,
  page = 1,
  pageSize = 48,
} = {}) {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  })
  if (search) params.set('search', search)
  if (imageType) params.set('image_type', imageType)
  if (inspectionOutcome) params.set('inspection_outcome', inspectionOutcome)
  if (folder !== undefined && folder !== '') params.set('folder', folder)
  if (trainableOnly) params.set('trainable_only', 'true')
  if (manualOnly) params.set('manual_only', 'true')
  if (multiRevisionOnly) {
    params.set('multi_revision_only', 'true')
    params.set('min_revisions', String(minRevisions))
  }
  const res = await fetch(`${API_BASE}/api/dataset/images?${params}`)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function datasetRfiChain(uploadId) {
  const params = new URLSearchParams({ upload_id: uploadId })
  const res = await fetch(`${API_BASE}/api/dataset/rfi-chain?${params}`)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data
}

export async function updateDatasetImageLabel(uploadId, imageId, imageType) {
  const res = await fetch(
    `${API_BASE}/api/dataset/images/${encodeURIComponent(uploadId)}/${encodeURIComponent(imageId)}/label`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_type: imageType }),
    },
  )
  const data = await res.json().catch(() => ({}))
  if (!res.ok) await parseApiError(res, data)
  return data.image
}
