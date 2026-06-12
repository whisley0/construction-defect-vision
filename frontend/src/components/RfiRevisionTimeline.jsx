import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { datasetRfiChain, imageUrl } from '../api.js'

export default function RfiRevisionTimeline({ uploadId, title = 'RFI revision history' }) {
  const [timeline, setTimeline] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!uploadId) {
      setTimeline(null)
      setError('')
      return
    }

    let cancelled = false
    setError('')
    datasetRfiChain(uploadId)
      .then((data) => {
        if (!cancelled) setTimeline(data)
      })
      .catch((err) => {
        if (!cancelled) {
          setTimeline(null)
          setError(err.message || 'Failed to load revision history')
        }
      })

    return () => {
      cancelled = true
    }
  }, [uploadId])

  if (!uploadId || error) return null
  if (!timeline) return <p className="muted">Loading revision history…</p>
  if (timeline.revision_count <= 1 && timeline.revisions.every((r) => !r.images.length)) {
    return null
  }

  return (
    <section className="panel full revision-timeline">
      <h2>
        {title}{' '}
        <span className="pill">
          {timeline.revision_count} revision{timeline.revision_count === 1 ? '' : 's'}
        </span>
      </h2>
      <p className="muted">
        Ordered oldest → newest using Inspecto <code>Previous Risc No.</code>
      </p>
      <div className="revision-track">
        {timeline.revisions.map((revision) => (
          <article
            key={revision.form_no}
            className={`revision-step${revision.is_current ? ' current' : ''}`}
          >
            <header className="revision-step-header">
              <span className="revision-position">#{revision.position}</span>
              <div>
                <strong>{revision.form_no}</strong>
                {revision.is_last_revision && <span className="badge ok">Latest</span>}
                {revision.is_current && <span className="badge">Current</span>}
              </div>
              <div className="revision-meta">
                {revision.inspected_date && <span>{revision.inspected_date}</span>}
                {revision.inspected_result && <span>{revision.inspected_result}</span>}
              </div>
            </header>
            {revision.images.length > 0 ? (
              <div className="revision-images">
                {revision.images.map((img) => (
                  <a
                    key={`${img.upload_id}:${img.image_id}`}
                    href={imageUrl(img.upload_id, img.image_filename)}
                    target="_blank"
                    rel="noreferrer"
                    className="revision-thumb"
                    title={img.image_id}
                  >
                    <img src={imageUrl(img.upload_id, img.image_filename)} alt={img.image_id} loading="lazy" />
                    <span>p.{img.page_number}</span>
                  </a>
                ))}
              </div>
            ) : (
              <p className="muted revision-empty">
                {revision.upload_id ? 'No site photos in this revision.' : 'PDF not extracted locally.'}
              </p>
            )}
            {revision.upload_id && revision.upload_id !== uploadId && (
              <Link to={`/crosscheck?upload_id=${encodeURIComponent(revision.upload_id)}`} className="link-btn">
                Open revision
              </Link>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}
