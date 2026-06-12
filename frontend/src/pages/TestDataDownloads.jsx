import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  compareTestData,
  downloadTestDataFiles,
  getTestDataJob,
  inspectoMetadataStatus,
  probeSharePointList,
  refreshSharePointList,
  scanTestDataFolder,
  uploadInspectoMetadata,
  setTestDataLocalDir,
  setTestDataSessionCookie,
  signOutTestDataAuth,
  testDataAuthStatus,
  testDataStatus,
} from '../api.js'

const SYNC_LABELS = {
  downloaded: 'Downloaded',
  missing: 'Not downloaded',
  local_only: 'Local only',
}

const LOCAL_STATUS_LABELS = {
  downloaded: 'Ready to extract',
  extracted: 'Extracted',
  error: 'Error',
}

function formatBytes(n) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function formatWhen(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function useJobPoller(onDone) {
  const timerRef = useRef(null)

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const start = useCallback(
    (jobId) => {
      stop()
      timerRef.current = setInterval(async () => {
        try {
          const job = await getTestDataJob(jobId)
          onDone(job)
          if (job.status === 'done' || job.status === 'error') {
            stop()
          }
        } catch {
          stop()
        }
      }, 1500)
    },
    [onDone, stop],
  )

  useEffect(() => stop, [stop])
  return { start, stop }
}

export default function TestDataDownloads() {
  const [status, setStatus] = useState(null)
  const [auth, setAuth] = useState(null)
  const [compare, setCompare] = useState(null)
  const [localDirInput, setLocalDirInput] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [cookieInput, setCookieInput] = useState('')
  const [job, setJob] = useState(null)
  const [filter, setFilter] = useState('missing')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(new Set())
  const [downloadLimit, setDownloadLimit] = useState(50)
  const [inspecto, setInspecto] = useState(null)
  const inspectoInputRef = useRef(null)

  const refreshCompare = useCallback(async (pageNum = page) => {
    const data = await compareTestData({ syncStatus: filter, search, page: pageNum, pageSize: 100 })
    setCompare(data)
    setSelected(new Set())
  }, [filter, search, page])

  const refreshAll = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [statusData, authData, inspectoData] = await Promise.all([
        testDataStatus(),
        testDataAuthStatus(),
        inspectoMetadataStatus(),
      ])
      setStatus(statusData)
      setAuth(authData)
      setInspecto(inspectoData)
      setLocalDirInput(statusData.local_dir || '')
      if (statusData.remote_total > 0 || statusData.total_files > 0) {
        await refreshCompare(1)
      } else {
        setCompare(null)
      }
    } catch (err) {
      setError(err.message || 'Failed to load status')
    } finally {
      setLoading(false)
    }
  }, [refreshCompare])

  useEffect(() => {
    refreshAll()
  }, [refreshAll])

  useEffect(() => {
    if (status?.remote_total || status?.total_files) {
      refreshCompare(page).catch((err) => setError(err.message || 'Compare failed'))
    }
  }, [filter, search, page, status?.remote_total, status?.total_files, refreshCompare])

  const { start: startJobPoll } = useJobPoller((jobUpdate) => {
    setJob(jobUpdate)
    if (jobUpdate.status === 'done') {
      refreshAll()
      setMessage(jobUpdate.message)
      setBusy('')
    } else if (jobUpdate.status === 'error') {
      setError(jobUpdate.error || jobUpdate.message)
      setBusy('')
    }
  })

  const onSaveDir = async (e) => {
    e.preventDefault()
    setBusy('save')
    setMessage('')
    setError('')
    try {
      await setTestDataLocalDir(localDirInput.trim())
      await refreshAll()
      setMessage('Local folder saved.')
    } catch (err) {
      setError(err.message || 'Failed to save folder')
    } finally {
      setBusy('')
    }
  }

  const onScan = async () => {
    setBusy('scan')
    setMessage('')
    setError('')
    try {
      const data = await scanTestDataFolder()
      setStatus(data.status)
      setMessage(data.message)
      await refreshCompare(1)
    } catch (err) {
      setError(err.message || 'Scan failed')
    } finally {
      setBusy('')
    }
  }

  const onSaveCookie = async (e) => {
    e.preventDefault()
    setBusy('cookie')
    setMessage('')
    setError('')
    try {
      const data = await setTestDataSessionCookie(cookieInput.trim())
      setAuth(await testDataAuthStatus())
      setCookieInput('')
      setMessage(`SharePoint session saved for ${data.account}.`)
    } catch (err) {
      setError(err.message || 'Could not save cookie')
    } finally {
      setBusy('')
    }
  }

  const onSignOut = async () => {
    await signOutTestDataAuth()
    setAuth(await testDataAuthStatus())
    setMessage('Session cleared.')
  }

  const onProbe = async () => {
    setBusy('probe')
    setError('')
    setMessage('')
    try {
      const data = await probeSharePointList()
      const lines = (data.sources || []).map((s) => {
        const exts = s.stream_extensions
          ? Object.entries(s.stream_extensions)
              .map(([k, v]) => `.${k}(${v})`)
              .join(', ')
          : 'none'
        return `${s.label}: ${s.folder_item_count ?? '?'} items in folder, ${s.stream_file_rows ?? 0} files on first stream page [${exts}]`
      })
      setMessage(lines.join(' · ') || 'Probe complete — see browser console for details.')
      console.log('SharePoint probe', data)
    } catch (err) {
      setError(err.message || 'Probe failed')
    } finally {
      setBusy('')
    }
  }

  const onUploadInspecto = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setBusy('inspecto')
    setError('')
    setMessage('')
    try {
      const data = await uploadInspectoMetadata(file)
      setInspecto(data.status)
      setMessage(data.message)
      await refreshCompare(page)
    } catch (err) {
      setError(err.message || 'Inspecto CSV upload failed')
    } finally {
      setBusy('')
    }
  }

  const onRefreshRemote = async () => {
    setBusy('remote')
    setError('')
    setMessage('Indexing SharePoint folder — this may take several minutes for ~6000 files…')
    try {
      const data = await refreshSharePointList()
      startJobPoll(data.job_id)
      setJob({ status: 'running', message: data.message, completed: 0, total: 0 })
    } catch (err) {
      setError(err.message || 'SharePoint refresh failed')
      setBusy('')
    }
  }

  const onDownloadSelected = async () => {
    if (!selected.size) return
    setBusy('download')
    setError('')
    try {
      const data = await downloadTestDataFiles({ relativePaths: [...selected] })
      startJobPoll(data.job_id)
      setJob({ status: 'running', message: data.message, completed: 0, total: selected.size })
    } catch (err) {
      setError(err.message || 'Download failed')
      setBusy('')
    }
  }

  const onDownloadMissingBatch = async () => {
    setBusy('download')
    setError('')
    try {
      const data = await downloadTestDataFiles({ downloadAllMissing: true, limit: downloadLimit })
      startJobPoll(data.job_id)
      setJob({ status: 'running', message: data.message, completed: 0, total: downloadLimit })
    } catch (err) {
      setError(err.message || 'Download failed')
      setBusy('')
    }
  }

  const toggleSelect = (path) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const toggleSelectAll = () => {
    const missingOnPage = compare?.files?.filter((f) => f.sync_status === 'missing') || []
    if (missingOnPage.every((f) => selected.has(f.relative_path))) {
      setSelected(new Set())
    } else {
      setSelected(new Set(missingOnPage.map((f) => f.relative_path)))
    }
  }

  const source = status?.source

  return (
    <>
      <header>
        <h1>Test Data Downloads</h1>
        <p className="subtitle">
          Compare SharePoint against your local folder, see what is missing, and download the rest — no OneDrive app
          required.
        </p>
      </header>

      {error && <div className="banner err">{error}</div>}
      {message && !error && <div className="banner ok-banner">{message}</div>}
      {job?.status === 'running' && (
        <div className="banner warn">
          {job.message}
          {job.total > 0 && ` (${job.completed}/${job.total})`}
        </div>
      )}

      <section className="panel full source-panel">
        <h2>Inspecto metadata CSV</h2>
        <p className="muted">
          Upload an Inspecto export CSV (e.g. <code>result 1.csv</code>). The first column{' '}
          <code>pdf_url</code> is split on the first comma — the second part is the PDF filename used to
          join metadata to downloaded files.
        </p>
        {inspecto?.imported ? (
          <p className="dir-status">
            Loaded: <code>{inspecto.source_file}</code> · {inspecto.record_count} records ·{' '}
            {inspecto.imported_at ? new Date(inspecto.imported_at).toLocaleString() : '—'}
          </p>
        ) : (
          <p className="muted">No Inspecto metadata loaded yet.</p>
        )}
        <div className="action-bar">
          <input
            ref={inspectoInputRef}
            type="file"
            accept=".csv,text/csv"
            style={{ display: 'none' }}
            onChange={onUploadInspecto}
          />
          <button type="button" disabled={!!busy} onClick={() => inspectoInputRef.current?.click()}>
            {busy === 'inspecto' ? 'Uploading…' : 'Upload Inspecto CSV'}
          </button>
        </div>
      </section>

      <section className="panel full source-panel">
        <h2>SharePoint browser session</h2>
        <p className="muted">
          No Azure app needed. Copy the <code>Cookie</code> header from your browser while logged into SharePoint — the
          app reuses that session to list and download files.
        </p>
        {auth?.authenticated ? (
          <div className="auth-row">
            <span className="pill ok">Session active{auth.account ? ` — ${auth.account}` : ''}</span>
            <button type="button" className="secondary-btn" onClick={onSignOut}>
              Clear session
            </button>
          </div>
        ) : (
          <form className="cookie-form" onSubmit={onSaveCookie}>
            <textarea
              className="cookie-input"
              placeholder="Paste Cookie header value here (FedAuth=…; rtFa=…; etc.)"
              value={cookieInput}
              onChange={(e) => setCookieInput(e.target.value)}
              rows={4}
            />
            <button type="submit" disabled={busy === 'cookie' || !cookieInput.trim()}>
              Save session
            </button>
          </form>
        )}
        <details className="cookie-help">
          <summary>How to copy your Cookie (Edge / Chrome)</summary>
          <ol className="steps">
            <li>
              Open{' '}
              <a href={source?.share_url} target="_blank" rel="noreferrer">
                the SharePoint folder
              </a>{' '}
              and confirm you can see the files.
            </li>
            <li>Press <strong>F12</strong> → <strong>Network</strong> tab → refresh the page.</li>
            <li>Click any request to <code>gammon-my.sharepoint.com</code> (while the folder is open).</li>
            <li>
              Under <strong>Request Headers</strong> (not Response Headers), find the line{' '}
              <code>cookie:</code> and copy its full value — it should look like{' '}
              <code>FedAuth=…; rtFa=…; …</code> with no <code>expires=</code> or <code>domain=</code> in it.
            </li>
            <li>
              If you only see <code>set-cookie</code> under Response Headers, you can still paste that — the app
              extracts <code>FedAuth</code> and <code>rtFa</code> automatically.
            </li>
          </ol>
        </details>
      </section>

      <section className="panel full source-panel">
        <h2>SharePoint source</h2>
        {source && (
          <dl className="meta-list">
            <div>
              <dt>Dataset</dt>
              <dd>{source.name}</dd>
            </div>
            <div>
              <dt>Folder</dt>
              <dd>{source.synced_folder_name}</dd>
            </div>
            <div>
              <dt>SharePoint path</dt>
              <dd className="mono">{source.folder_path}</dd>
            </div>
          </dl>
        )}
        {source?.share_url && (
          <p>
            <a className="ext-link" href={source.share_url} target="_blank" rel="noreferrer">
              Open folder in SharePoint
            </a>
          </p>
        )}
        <ol className="steps">
          <li>Paste your browser cookie above, then click <strong>Refresh SharePoint list</strong> to index all PDFs (~6000).</li>
          <li>Set your local download folder (browser saves or app downloads go here).</li>
          <li>Click <strong>Scan local folder</strong> if you also download manually in the browser.</li>
          <li>Use the compare table to see missing files and download them in batches.</li>
          <li>
            Open <Link to="/crosscheck">RFI Crosscheck</Link> to extract metadata and review site photos from downloaded PDFs.
          </li>
        </ol>
        <div className="action-bar">
          <button type="button" disabled={!!busy || !auth?.authenticated} onClick={onRefreshRemote}>
            {busy === 'remote' || job?.kind === 'remote_refresh' ? 'Indexing…' : 'Refresh SharePoint list'}
          </button>
          <button type="button" className="secondary-btn" disabled={!!busy || !auth?.authenticated} onClick={onProbe}>
            {busy === 'probe' ? 'Diagnosing…' : 'Diagnose folder'}
          </button>
          {status?.remote_inventory_at && (
            <span className="file-meta">Remote index: {formatWhen(status.remote_inventory_at)} · {status.remote_total} PDFs</span>
          )}
        </div>
      </section>

      <section className="panel full">
        <h2>Local download folder</h2>
        <form className="dir-form" onSubmit={onSaveDir}>
          <input
            type="text"
            className="dir-input"
            placeholder="Folder where downloaded PDFs are saved"
            value={localDirInput}
            onChange={(e) => setLocalDirInput(e.target.value)}
          />
          <button type="submit" disabled={busy === 'save' || !localDirInput.trim()}>
            Save path
          </button>
        </form>
        {status?.local_dir && (
          <p className="dir-status">
            Using: <code>{status.local_dir}</code>
            {status.local_dir_exists ? <span className="pill ok">found</span> : <span className="pill warn">not found</span>}
          </p>
        )}
        <div className="action-bar">
          <button type="button" disabled={!!busy} onClick={onScan}>
            {busy === 'scan' ? 'Scanning…' : 'Scan local folder'}
          </button>
          {status?.pending_extract_count > 0 && (
            <Link to="/crosscheck" className="secondary-btn link-btn">
              Extract & review ({status.pending_extract_count} pending)
            </Link>
          )}
          {status?.extracted_count > 0 && (
            <Link to="/dataset" className="secondary-btn link-btn">
              Browse images ({status.extracted_count} PDFs)
            </Link>
          )}
        </div>
      </section>

      <section className="panel full">
        <h2>
          Compare SharePoint vs local{' '}
          {compare && (
            <span className={compare.missing_count ? 'pill warn' : 'pill ok'}>
              {compare.downloaded_count}/{compare.remote_total || compare.local_total} downloaded
            </span>
          )}
        </h2>

        {status && (
          <p className="muted summary-line">
            SharePoint: {status.remote_total} · Local: {status.local_total || status.total_files} · Missing:{' '}
            {status.missing_count} · Extra local-only: {status.local_only_count}
          </p>
        )}

        <div className="filter-bar">
          <label>
            Show
            <select value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1) }}>
              <option value="">All files</option>
              <option value="missing">Not downloaded</option>
              <option value="downloaded">Downloaded</option>
              <option value="local_only">Local only</option>
            </select>
          </label>
          <input
            type="search"
            className="search-input"
            placeholder="Search filename…"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }}
          />
          <label className="limit-label">
            Batch size
            <input
              type="number"
              min="1"
              max="200"
              value={downloadLimit}
              onChange={(e) => setDownloadLimit(Number(e.target.value) || 50)}
            />
          </label>
          <button type="button" disabled={!!busy || !compare?.missing_count || !auth?.authenticated} onClick={onDownloadMissingBatch}>
            Download next {downloadLimit} missing
          </button>
          <button type="button" className="secondary-btn" disabled={!!busy || !selected.size || !auth?.authenticated} onClick={onDownloadSelected}>
            Download selected ({selected.size})
          </button>
        </div>

        {loading ? (
          <p className="muted">Loading…</p>
        ) : !compare?.files?.length ? (
          <p className="muted">
            No comparison data yet. Save your browser cookie and refresh the SharePoint list, then scan your local folder.
          </p>
        ) : (
          <>
            <table className="batch-table compare-table">
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      aria-label="Select all missing on page"
                      onChange={toggleSelectAll}
                      checked={
                        compare.files.filter((f) => f.sync_status === 'missing').length > 0 &&
                        compare.files.filter((f) => f.sync_status === 'missing').every((f) => selected.has(f.relative_path))
                      }
                    />
                  </th>
                  <th>File</th>
                  <th>Size</th>
                  <th>SharePoint status</th>
                  <th>Local status</th>
                  <th>Preview</th>
                </tr>
              </thead>
              <tbody>
                {compare.files.map((file) => (
                  <tr key={file.relative_path} className={file.sync_status === 'missing' ? 'row-missing' : ''}>
                    <td>
                      {file.sync_status === 'missing' ? (
                        <input
                          type="checkbox"
                          checked={selected.has(file.relative_path)}
                          onChange={() => toggleSelect(file.relative_path)}
                        />
                      ) : null}
                    </td>
                    <td>
                      <div className="file-name">
                        {file.filename}
                        {file.inspecto && <span className="badge ok">Inspecto</span>}
                      </div>
                      {file.relative_path !== file.filename && (
                        <div className="muted file-path">{file.relative_path}</div>
                      )}
                    </td>
                    <td>{formatBytes(file.size_bytes)}</td>
                    <td>
                      <span className={`pill sync-${file.sync_status}`}>
                        {SYNC_LABELS[file.sync_status] || file.sync_status}
                      </span>
                    </td>
                    <td>
                      {file.local_status ? (
                        <span className={`pill status-${file.local_status}`}>
                          {LOCAL_STATUS_LABELS[file.local_status] || file.local_status}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td>
                      {file.upload_id ? (
                        <Link to={`/crosscheck?upload_id=${encodeURIComponent(file.upload_id)}`} className="link-btn">
                          Crosscheck
                        </Link>
                      ) : file.local_status === 'downloaded' ? (
                        <Link to="/crosscheck" className="link-btn">
                          Extract
                        </Link>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {compare.total_pages > 1 && (
              <div className="pager">
                <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </button>
                <span>
                  Page {compare.page} of {compare.total_pages} ({compare.total_filtered} shown)
                </span>
                <button type="button" disabled={page >= compare.total_pages} onClick={() => setPage((p) => p + 1)}>
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </section>
    </>
  )
}
