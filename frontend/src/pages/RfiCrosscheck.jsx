import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import InspectoMetadata from '../components/InspectoMetadata.jsx'
import RfiRevisionTimeline from '../components/RfiRevisionTimeline.jsx'
import {
  clearTestDataExtractions,
  compareTestData,
  extractTestDataFiles,
  getRfiExtraction,
  imageUrl,
  pdfPreviewUrl,
  scanTestDataFolder,
  testDataStatus,
} from '../api.js'

const OUTCOME_LABELS = {
  accepted: 'Accepted',
  conditionally_accepted_no_reinspection: 'Conditionally accepted (no re-inspection)',
  conditionally_accepted_reinspection: 'Conditionally accepted (re-inspection required)',
  rejected: 'Rejected',
  unknown: 'Unknown',
}

const LOCAL_STATUS_LABELS = {
  downloaded: 'Ready to extract',
  extracted: 'Extracted',
  error: 'Error',
}

function FieldRow({ field }) {
  return (
    <tr className={field.found ? 'row-ok' : field.required ? 'row-miss' : 'row-optional'}>
      <td className="field-label">
        {field.label}
        {field.required && <span className="req">*</span>}
      </td>
      <td className="field-status">{field.found ? '✓' : field.required ? '✗' : '—'}</td>
      <td className="field-value">{field.value || <em className="muted">Not extracted</em>}</td>
    </tr>
  )
}

function ImageCard({ uploadId, image }) {
  const name = image.image_path.split(/[/\\]/).pop()
  const src = imageUrl(uploadId, name)
  const trainable = image.image_type === 'site_photo' && !image.filter_reason
  return (
    <div className={`image-card type-${image.image_type}`}>
      <img src={src} alt={image.image_id} loading="lazy" />
      <div className="image-meta">
        <strong>{image.image_id}</strong>
        <span>
          p.{image.page_number} · {image.width}×{image.height}
        </span>
        <span className="badge">{image.image_type}</span>
        {image.filter_reason && <span className="badge warn">{image.filter_reason}</span>}
        {trainable && <span className="badge ok">training candidate</span>}
      </div>
    </div>
  )
}

function ExtractionDetail({ result, showPages, onTogglePages }) {
  const sitePhotos = result?.images?.filter((i) => i.image_type === 'site_photo') || []
  const filtered = result?.images?.filter((i) => i.image_type !== 'site_photo') || []

  return (
    <div className="layout">
      <section className="panel">
        <h2>
          Metadata crosscheck{' '}
          <span className={result.crosscheck.complete ? 'pill ok' : 'pill warn'}>
            {result.crosscheck.required_found}/{result.crosscheck.required_total} required
          </span>
        </h2>
        <table className="fields-table">
          <thead>
            <tr>
              <th>Field</th>
              <th></th>
              <th>Extracted value</th>
            </tr>
          </thead>
          <tbody>
            {result.crosscheck.fields.map((f) => (
              <FieldRow key={f.key} field={f} />
            ))}
          </tbody>
        </table>
        <p className="outcome">
          Outcome:{' '}
          <strong>
            {OUTCOME_LABELS[result.inspection.inspection_outcome] || result.inspection.inspection_outcome}
          </strong>
        </p>
        {result.parse_status && !result.parse_status.ok && (
          <p className="parse-hint">{result.parse_status.message}</p>
        )}
      </section>

      <section className="panel pdf-panel">
        <h2>PDF preview</h2>
        <iframe title="PDF preview" src={pdfPreviewUrl(result.upload_id)} className="pdf-frame" />
      </section>

      <section className="panel full">
        <h2>
          Extracted images ({result.images.length}) — site photos: {sitePhotos.length}
        </h2>
        {result.images.length === 0 ? (
          <p className="muted">No embedded images found in this PDF.</p>
        ) : (
          <>
            {sitePhotos.length > 0 && (
              <>
                <h3>Site photos</h3>
                <div className="image-grid">
                  {sitePhotos.map((img) => (
                    <ImageCard key={img.image_id} uploadId={result.upload_id} image={img} />
                  ))}
                </div>
              </>
            )}
            {filtered.length > 0 && (
              <>
                <h3>Filtered (drawings / logos / other)</h3>
                <div className="image-grid">
                  {filtered.map((img) => (
                    <ImageCard key={img.image_id} uploadId={result.upload_id} image={img} />
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </section>

      <InspectoMetadata inspecto={result.inspecto} />
      <RfiRevisionTimeline uploadId={result.upload_id} title="RFI evolution" />

      <section className="panel full">
        <button type="button" className="link-btn" onClick={onTogglePages}>
          {showPages ? 'Hide' : 'Show'} per-page text ({result.page_previews.length} pages)
        </button>
        {showPages && (
          <div className="page-text">
            {result.page_previews.map((p) => (
              <details key={p.page_number} open={p.page_number <= 2}>
                <summary>
                  Page {p.page_number} ({p.char_count} chars)
                </summary>
                <pre>{p.text || '(empty)'}</pre>
              </details>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

export default function RfiCrosscheck() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [status, setStatus] = useState(null)
  const [compare, setCompare] = useState(null)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [localFilter, setLocalFilter] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [selected, setSelected] = useState(new Set())
  const [selectedPath, setSelectedPath] = useState('')
  const [activeResult, setActiveResult] = useState(null)
  const [showPages, setShowPages] = useState(false)
  const [extractLimit, setExtractLimit] = useState(50)
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [clearConfirmInput, setClearConfirmInput] = useState('')

  const loadStatus = useCallback(async () => {
    const data = await testDataStatus()
    setStatus(data)
    return data
  }, [])

  const refreshCompare = useCallback(
    async (pageNum = page) => {
      const data = await compareTestData({
        search,
        localStatus: localFilter,
        hasLocal: true,
        extractedFirst: true,
        page: pageNum,
        pageSize: 100,
      })
      setCompare(data)
      return data
    },
    [localFilter, page, search],
  )

  const loadExtraction = useCallback(async (uploadId) => {
    const data = await getRfiExtraction(uploadId)
    setActiveResult(data)
    setShowPages(false)
    setSearchParams({ upload_id: uploadId }, { replace: true })
  }, [setSearchParams])

  const openFile = useCallback(
    async (file) => {
      setSelectedPath(file.relative_path)
      setError('')
      if (file.upload_id && file.local_status === 'extracted') {
        setBusy('load')
        try {
          await loadExtraction(file.upload_id)
        } catch (err) {
          setError(err.message || 'Failed to load extraction')
        } finally {
          setBusy('')
        }
        return
      }

      setBusy('extract')
      try {
        const data = await extractTestDataFiles({ relativePaths: [file.relative_path], limit: 1 })
        setStatus(data.status)
        if (data.results?.length) {
          await loadExtraction(data.results[0].upload_id)
          setMessage(`Extracted ${file.filename}`)
        } else {
          const errMsg = data.errors?.[0]?.message || 'Extraction failed'
          setError(errMsg)
        }
        await refreshCompare(page)
      } catch (err) {
        setError(err.message || 'Extraction failed')
      } finally {
        setBusy('')
      }
    },
    [loadExtraction, page, refreshCompare],
  )

  useEffect(() => {
    loadStatus().catch((err) => setError(err.message || 'Failed to load status'))
  }, [loadStatus])

  useEffect(() => {
    refreshCompare(page).catch((err) => setError(err.message || 'Failed to load files'))
  }, [page, refreshCompare])

  useEffect(() => {
    const uploadId = searchParams.get('upload_id')
    if (!uploadId) return
    loadExtraction(uploadId).catch((err) => setError(err.message || 'Failed to load extraction'))
  }, [loadExtraction, searchParams])

  const onScan = async () => {
    setBusy('scan')
    setError('')
    try {
      const data = await scanTestDataFolder()
      setStatus(data.status)
      setMessage(data.message)
      await refreshCompare(1)
      setPage(1)
    } catch (err) {
      setError(err.message || 'Scan failed')
    } finally {
      setBusy('')
    }
  }

  const onExtractPending = async () => {
    setBusy('extract')
    setError('')
    setMessage('')
    try {
      const data = await extractTestDataFiles({ limit: extractLimit })
      setStatus(data.status)
      setMessage(`Extracted ${data.succeeded}/${data.attempted} file(s).`)
      if (data.results?.length && !activeResult) {
        await loadExtraction(data.results[0].upload_id)
        setSelectedPath(data.results[0].filename)
      }
      await refreshCompare(page)
    } catch (err) {
      setError(err.message || 'Extraction failed')
    } finally {
      setBusy('')
    }
  }

  const onOpenClearConfirm = () => {
    setClearConfirmInput('')
    setShowClearConfirm(true)
  }

  const onCloseClearConfirm = () => {
    setShowClearConfirm(false)
    setClearConfirmInput('')
  }

  const onConfirmClearExtractions = async () => {
    if (clearConfirmInput !== 'delete') return
    setBusy('clear')
    setError('')
    setMessage('')
    setActiveResult(null)
    setSelectedPath('')
    onCloseClearConfirm()
    try {
      const data = await clearTestDataExtractions()
      setStatus(data.status)
      setMessage(data.message)
      await refreshCompare(1)
      setPage(1)
    } catch (err) {
      setError(err.message || 'Clear failed')
    } finally {
      setBusy('')
    }
  }

  const onExtractSelected = async () => {
    if (!selected.size) return
    setBusy('extract')
    setError('')
    try {
      const data = await extractTestDataFiles({ relativePaths: [...selected], limit: selected.size })
      setStatus(data.status)
      setMessage(`Extracted ${data.succeeded}/${data.attempted} selected file(s).`)
      if (data.results?.length) {
        await loadExtraction(data.results[0].upload_id)
        setSelectedPath(data.results[0].filename)
      }
      setSelected(new Set())
      await refreshCompare(page)
    } catch (err) {
      setError(err.message || 'Extraction failed')
    } finally {
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

  const localFiles = compare?.files || []

  return (
    <>
      <header>
        <h1>RFI Extraction Crosscheck</h1>
        <p className="subtitle">
          Review metadata and photo extraction for PDFs in your test data download folder. Download files on{' '}
          <Link to="/">Test Data Downloads</Link> first, then browse extracted images on{' '}
          <Link to="/dataset">Image Dataset</Link>.
        </p>
      </header>

      {error && <div className="banner err">{error}</div>}
      {message && !error && <div className="banner ok-banner">{message}</div>}
      {activeResult?.warnings?.map((w) => (
        <div key={w} className="banner warn">
          <strong>{activeResult.filename}:</strong> {w}
        </div>
      ))}

      <section className="panel full">
        <h2>Local download folder</h2>
        {status?.local_dir ? (
          <p className="dir-status">
            Using: <code>{status.local_dir}</code>
            {status.local_dir_exists ? <span className="pill ok">found</span> : <span className="pill warn">not found</span>}
          </p>
        ) : (
          <p className="muted">
            No download folder configured yet. Set it on the <Link to="/">Test Data Downloads</Link> page.
          </p>
        )}
        {status && (
          <p className="muted summary-line">
            Local PDFs: {status.total_files} · Ready to extract: {status.pending_extract_count} · Extracted:{' '}
            {status.extracted_count} · Errors: {status.error_count}
          </p>
        )}
        <div className="action-bar">
          <button type="button" disabled={!!busy} onClick={onScan}>
            {busy === 'scan' ? 'Scanning…' : 'Scan local folder'}
          </button>
          <button
            type="button"
            className="secondary-btn"
            disabled={!!busy || !status?.pending_extract_count}
            onClick={onExtractPending}
          >
            {busy === 'extract' ? 'Extracting…' : `Extract next ${extractLimit} pending`}
          </button>
          <label className="limit-label">
            Batch size
            <input
              type="number"
              min="1"
              max="500"
              value={extractLimit}
              onChange={(e) => setExtractLimit(Number(e.target.value) || 50)}
            />
          </label>
          <button type="button" className="secondary-btn" disabled={!!busy || !selected.size} onClick={onExtractSelected}>
            Extract selected ({selected.size})
          </button>
          <button
            type="button"
            className="danger-btn"
            disabled={!!busy || !(status?.extracted_count || status?.error_count)}
            onClick={onOpenClearConfirm}
          >
            {busy === 'clear' ? 'Clearing…' : 'Clear all extractions'}
          </button>
        </div>
      </section>

      {showClearConfirm && (
        <div className="confirm-overlay" role="dialog" aria-modal="true" aria-labelledby="clear-extractions-title">
          <div className="panel confirm-dialog">
            <h2 id="clear-extractions-title">Clear all extractions?</h2>
            <p>
              This removes extracted metadata, images, and manual labels for{' '}
              <strong>{(status?.extracted_count ?? 0) + (status?.error_count ?? 0)}</strong> PDF(s). Downloaded
              PDF files on disk are not deleted.
            </p>
            <p className="muted">Type <strong>delete</strong> to confirm:</p>
            <input
              type="text"
              className="confirm-input"
              value={clearConfirmInput}
              onChange={(e) => setClearConfirmInput(e.target.value)}
              placeholder="delete"
              autoFocus
            />
            <div className="action-bar">
              <button type="button" className="secondary-btn" onClick={onCloseClearConfirm}>
                Cancel
              </button>
              <button
                type="button"
                className="danger-btn"
                disabled={clearConfirmInput !== 'delete' || busy === 'clear'}
                onClick={onConfirmClearExtractions}
              >
                Clear all extractions
              </button>
            </div>
          </div>
        </div>
      )}

      {activeResult && (
        <ExtractionDetail
          result={activeResult}
          showPages={showPages}
          onTogglePages={() => setShowPages((v) => !v)}
        />
      )}

      <section className="panel full batch-panel">
        <h2>Downloaded PDFs</h2>
        <div className="filter-bar">
          <input
            type="search"
            className="search-input"
            placeholder="Search filename…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
          />
          <label>
            Extraction status
            <select
              value={localFilter}
              onChange={(e) => {
                setLocalFilter(e.target.value)
                setPage(1)
              }}
            >
              <option value="">All local files</option>
              <option value="downloaded">Ready to extract</option>
              <option value="extracted">Extracted</option>
              <option value="error">Error</option>
            </select>
          </label>
        </div>

        {!localFiles.length ? (
          <p className="muted">
            No local PDFs yet. Download files from <Link to="/">Test Data Downloads</Link>, then scan this folder.
          </p>
        ) : (
          <>
            <table className="batch-table">
              <thead>
                <tr>
                  <th></th>
                  <th>File</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {localFiles.map((file) => {
                  const selectedRow = selectedPath === file.relative_path
                  const canSelect = file.local_status === 'downloaded' || file.local_status === 'error'
                  return (
                    <tr
                      key={file.relative_path}
                      className={`batch-row ${selectedRow ? 'selected' : ''} ${file.local_status === 'error' ? 'incomplete' : ''}`}
                      onClick={() => openFile(file)}
                    >
                      <td onClick={(e) => e.stopPropagation()}>
                        {canSelect ? (
                          <input
                            type="checkbox"
                            checked={selected.has(file.relative_path)}
                            onChange={() => toggleSelect(file.relative_path)}
                          />
                        ) : null}
                      </td>
                      <td>
                        <div className="file-name">{file.filename}</div>
                        {file.relative_path !== file.filename && (
                          <div className="muted file-path">{file.relative_path}</div>
                        )}
                      </td>
                      <td>
                        <span className={`pill status-${file.local_status || 'downloaded'}`}>
                          {LOCAL_STATUS_LABELS[file.local_status] || file.local_status || 'Ready to extract'}
                        </span>
                      </td>
                      <td>{file.local_status === 'extracted' ? 'Open crosscheck' : 'Extract & review'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p className="muted batch-hint">
              Click a row to extract (if pending) or open the crosscheck view. Select rows to extract in batch.
            </p>
            {compare?.total_pages > 1 && (
              <div className="pager">
                <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </button>
                <span>
                  Page {compare.page} of {compare.total_pages}
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
