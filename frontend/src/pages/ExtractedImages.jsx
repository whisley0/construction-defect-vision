import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import DistributionBars from '../components/DistributionBars.jsx'
import InspectoMetadata from '../components/InspectoMetadata.jsx'
import RfiRevisionTimeline from '../components/RfiRevisionTimeline.jsx'
import {
  datasetImages,
  datasetSummary,
  imageUrl,
  updateDatasetImageLabel,
} from '../api.js'

const OUTCOME_LABELS = {
  accepted: 'Accepted',
  conditionally_accepted_no_reinspection: 'Conditionally accepted (no re-inspection)',
  conditionally_accepted_reinspection: 'Conditionally accepted (re-inspection)',
  rejected: 'Rejected',
  unknown: 'Unknown',
}

const IMAGE_TYPE_OPTIONS = [
  { value: 'site_photo', label: 'Site photo' },
  { value: 'drawing', label: 'Drawing' },
  { value: 'logo', label: 'Logo' },
  { value: 'stamp', label: 'Stamp' },
  { value: 'unknown', label: 'Unknown' },
  { value: 'skip', label: 'Skip' },
]

const IMAGE_TYPE_LABELS = Object.fromEntries(IMAGE_TYPE_OPTIONS.map((o) => [o.value, o.label]))

function folderLabel(folder) {
  return folder ? folder : '(root)'
}

function itemKey(item) {
  return `${item.upload_id}:${item.image_id}`
}

function MetadataBlock({ item }) {
  return (
    <dl className="dataset-meta">
      <div>
        <dt>Inspection No.</dt>
        <dd>{item.inspection_id || '—'}</dd>
      </div>
      <div>
        <dt>Outcome</dt>
        <dd>{OUTCOME_LABELS[item.inspection_outcome] || item.inspection_outcome}</dd>
      </div>
      <div>
        <dt>Location</dt>
        <dd>{item.location || '—'}</dd>
      </div>
      <div>
        <dt>Description of works</dt>
        <dd>{item.description_of_works || '—'}</dd>
      </div>
      <div>
        <dt>Subsequent work</dt>
        <dd>{item.subsequent_work || '—'}</dd>
      </div>
      <div>
        <dt>Inspector comments</dt>
        <dd>{item.inspector_comments || '—'}</dd>
      </div>
      <div>
        <dt>Inspected by</dt>
        <dd>{item.inspected_by || '—'}</dd>
      </div>
      <div>
        <dt>Inspection date</dt>
        <dd>{item.inspection_date || '—'}</dd>
      </div>
      <div>
        <dt>Reference drawing(s)</dt>
        <dd>{item.reference_drawing_nos || '—'}</dd>
      </div>
      <div>
        <dt>Source PDF</dt>
        <dd>{item.pdf_filename}</dd>
      </div>
      <div>
        <dt>Original folder</dt>
        <dd className="mono">{folderLabel(item.source_folder)}</dd>
      </div>
      <div className="full">
        <dt>Source path</dt>
        <dd className="mono">{item.source_relative_path || '—'}</dd>
      </div>
      <div className="full">
        <dt>Download root</dt>
        <dd className="mono">{item.local_dir || '—'}</dd>
      </div>
    </dl>
  )
}

function ImageCard({ item, selected, onSelect }) {
  return (
    <button type="button" className={`dataset-card ${selected ? 'selected' : ''}`} onClick={() => onSelect(item)}>
      <img src={imageUrl(item.upload_id, item.image_filename)} alt={item.image_id} loading="lazy" />
      <div className="dataset-card-body">
        <strong>{item.image_id}</strong>
        <span className="badge">{IMAGE_TYPE_LABELS[item.image_type] || item.image_type}</span>
        {item.label_source === 'manual' && <span className="badge ok">edited</span>}
        {item.revision_count > 1 && (
          <span className="badge">{item.revision_count} revisions</span>
        )}
        {item.trainable && <span className="badge ok">trainable</span>}
        <div className="muted">{item.inspection_id || 'No inspection ID'}</div>
        <div className="muted file-path">{item.source_relative_path}</div>
      </div>
    </button>
  )
}

export default function ExtractedImages() {
  const [summary, setSummary] = useState(null)
  const [data, setData] = useState(null)
  const [selected, setSelected] = useState(null)
  const [search, setSearch] = useState('')
  const [imageType, setImageType] = useState('')
  const [outcome, setOutcome] = useState('')
  const [folder, setFolder] = useState('__all__')
  const [trainableOnly, setTrainableOnly] = useState(false)
  const [manualOnly, setManualOnly] = useState(false)
  const [multiRevisionOnly, setMultiRevisionOnly] = useState(false)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [savingLabel, setSavingLabel] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async (pageNum = page) => {
    setLoading(true)
    setError('')
    try {
      const imageData = await datasetImages({
        search,
        imageType,
        inspectionOutcome: outcome,
        folder: folder === '__all__' ? undefined : folder,
        trainableOnly,
        manualOnly,
        multiRevisionOnly,
        page: pageNum,
        pageSize: 48,
      })
      setData(imageData)
      setLoading(false)
      datasetSummary()
        .then(setSummary)
        .catch(() => {})
    } catch (err) {
      setError(err.message || 'Failed to load dataset')
      setLoading(false)
    }
  }, [folder, imageType, manualOnly, multiRevisionOnly, outcome, page, search, trainableOnly])

  const refreshSummary = useCallback(async () => {
    try {
      setSummary(await datasetSummary())
    } catch {
      /* ignore */
    }
  }, [])

  const applyUpdatedImage = useCallback((updated) => {
    setSelected(updated)
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        images: prev.images.map((img) =>
          img.upload_id === updated.upload_id && img.image_id === updated.image_id ? updated : img,
        ),
      }
    })
    refreshSummary()
  }, [refreshSummary])

  const onLabelChange = async (newType) => {
    if (!selected || savingLabel) return
    const resetToAuto = newType === selected.auto_image_type
    setSavingLabel(true)
    setError('')
    try {
      const updated = await updateDatasetImageLabel(
        selected.upload_id,
        selected.image_id,
        resetToAuto ? null : newType,
      )
      applyUpdatedImage(updated)
    } catch (err) {
      setError(err.message || 'Failed to save label')
    } finally {
      setSavingLabel(false)
    }
  }

  const selectByOffset = useCallback(
    (offset) => {
      if (!data?.images?.length || !selected) return
      const idx = data.images.findIndex(
        (item) => item.upload_id === selected.upload_id && item.image_id === selected.image_id,
      )
      if (idx < 0) return
      const next = data.images[idx + offset]
      if (next) setSelected(next)
    },
    [data, selected],
  )

  useEffect(() => {
    load(page)
  }, [load, page])

  useEffect(() => {
    setPage(1)
  }, [search, imageType, outcome, folder, trainableOnly, manualOnly, multiRevisionOnly])

  useEffect(() => {
    if (!data?.images?.length) {
      setSelected(null)
      return
    }
    if (
      !selected ||
      !data.images.some((item) => item.upload_id === selected.upload_id && item.image_id === selected.image_id)
    ) {
      setSelected(data.images[0])
    }
  }, [data, selected])

  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.target.closest('input, select, textarea')) return
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        selectByOffset(-1)
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        selectByOffset(1)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [selectByOffset])

  return (
    <>
      <header>
        <h1>Extracted Image Dataset</h1>
        <p className="subtitle">
          Browse extracted images, correct their category labels, and review RFI metadata. Use ← → to move between
          images. Extract PDFs on <Link to="/crosscheck">RFI Crosscheck</Link> first.
        </p>
      </header>

      {error && <div className="banner err">{error}</div>}

      {summary && (
        <section className="panel full dataset-summary">
          <p className="muted summary-line">
            Download root: <code>{summary.local_dir || '—'}</code> · PDFs extracted: {summary.extracted_pdfs} · Images:{' '}
            {summary.total_images} · Site photos: {summary.site_photos} · Trainable: {summary.trainable_images} ·
            Manually labeled: {summary.manually_labeled}
          </p>
        </section>
      )}

      <section className="panel full">
        <div className="filter-bar">
          <input
            type="search"
            className="search-input"
            placeholder="Search inspection ID, location, filename, folder…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <label>
            Image type
            <select value={imageType} onChange={(e) => setImageType(e.target.value)}>
              <option value="">All types</option>
              {IMAGE_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Outcome
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="">All outcomes</option>
              <option value="accepted">Accepted</option>
              <option value="conditionally_accepted_no_reinspection">Cond. accepted (no re-inspection)</option>
              <option value="conditionally_accepted_reinspection">Cond. accepted (re-inspection)</option>
              <option value="rejected">Rejected</option>
              <option value="unknown">Unknown</option>
            </select>
          </label>
          <label>
            Folder
            <select value={folder} onChange={(e) => setFolder(e.target.value)}>
              <option value="__all__">All folders</option>
              {(summary?.folders || []).map((entry) => (
                <option key={entry || '__root__'} value={entry}>
                  {folderLabel(entry)}
                </option>
              ))}
            </select>
          </label>
          <label className="checkbox-label">
            <input type="checkbox" checked={trainableOnly} onChange={(e) => setTrainableOnly(e.target.checked)} />
            Trainable only
          </label>
          <label className="checkbox-label">
            <input type="checkbox" checked={manualOnly} onChange={(e) => setManualOnly(e.target.checked)} />
            Manually labeled
          </label>
          <label className="checkbox-label" title="Requires Inspecto metadata with linked Previous Risc No.">
            <input
              type="checkbox"
              checked={multiRevisionOnly}
              onChange={(e) => setMultiRevisionOnly(e.target.checked)}
            />
            2+ revisions
          </label>
        </div>

        {loading ? (
          <p className="muted">Loading images…</p>
        ) : !data?.total_filtered ? (
          <p className="muted">
            No extracted images yet. Download PDFs and run extraction on the <Link to="/crosscheck">Crosscheck</Link>{' '}
            page.
          </p>
        ) : (
          <>
            <DistributionBars distributions={data.distributions} />
            <p className="muted summary-line">
              Showing {data.images.length} of {data.total_filtered} matching images ({data.total_images} total extracted)
              · Use ← → to step through images
            </p>
            <div className="dataset-layout">
              <div className="dataset-grid">
                {data.images.map((item) => (
                  <ImageCard
                    key={itemKey(item)}
                    item={item}
                    selected={
                      selected?.upload_id === item.upload_id && selected?.image_id === item.image_id
                    }
                    onSelect={setSelected}
                  />
                ))}
              </div>

              {selected && (
                <aside className="panel dataset-detail">
                  <div className="dataset-detail-nav">
                    <button type="button" className="secondary-btn" onClick={() => selectByOffset(-1)}>
                      ← Prev
                    </button>
                    <h2>{selected.image_id}</h2>
                    <button type="button" className="secondary-btn" onClick={() => selectByOffset(1)}>
                      Next →
                    </button>
                  </div>
                  <img
                    className="dataset-detail-image"
                    src={imageUrl(selected.upload_id, selected.image_filename)}
                    alt={selected.image_id}
                  />

                  <div className="label-editor">
                    <label>
                      Category
                      <select
                        value={selected.image_type}
                        disabled={savingLabel}
                        onChange={(e) => onLabelChange(e.target.value)}
                      >
                        {IMAGE_TYPE_OPTIONS.map((opt) => (
                          <option key={opt.value} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    {selected.label_source === 'manual' ? (
                      <p className="muted label-hint">
                        Manual label · auto was {IMAGE_TYPE_LABELS[selected.auto_image_type] || selected.auto_image_type}
                        {selected.auto_image_type !== selected.image_type && (
                          <>
                            {' '}
                            ·{' '}
                            <button
                              type="button"
                              className="link-btn"
                              disabled={savingLabel}
                              onClick={() => onLabelChange(selected.auto_image_type)}
                            >
                              Reset to auto
                            </button>
                          </>
                        )}
                      </p>
                    ) : (
                      <p className="muted label-hint">Auto-classified — change the dropdown to override.</p>
                    )}
                  </div>

                  <p>
                    <span className="badge">{IMAGE_TYPE_LABELS[selected.image_type] || selected.image_type}</span>
                    {selected.trainable && <span className="badge ok">trainable</span>}
                    {selected.filter_reason && selected.label_source !== 'manual' && (
                      <span className="badge warn">{selected.filter_reason}</span>
                    )}
                    <span className="file-meta">
                      p.{selected.page_number} · {selected.width}×{selected.height}
                    </span>
                  </p>
                  <MetadataBlock item={selected} />
                  <InspectoMetadata inspecto={selected.inspecto} title="Inspecto metadata" />
                  <RfiRevisionTimeline uploadId={selected.upload_id} title="RFI evolution" />
                  <div className="action-bar">
                    <Link to={selected.crosscheck_url} className="link-btn">
                      Open RFI crosscheck
                    </Link>
                  </div>
                </aside>
              )}
            </div>

            {data.total_pages > 1 && (
              <div className="pager">
                <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </button>
                <span>
                  Page {data.page} of {data.total_pages}
                </span>
                <button type="button" disabled={page >= data.total_pages} onClick={() => setPage((p) => p + 1)}>
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
