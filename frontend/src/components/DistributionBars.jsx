const OUTCOME_COLORS = {
  accepted: '#22c55e',
  conditionally_accepted_no_reinspection: '#84cc16',
  conditionally_accepted_reinspection: '#eab308',
  rejected: '#ef4444',
  unknown: '#9ca3af',
}

const IMAGE_TYPE_COLORS = {
  site_photo: '#2563eb',
  drawing: '#7c3aed',
  logo: '#db2777',
  stamp: '#ea580c',
  unknown: '#6b7280',
  skip: '#d1d5db',
}

function colorFor(key, palette) {
  return palette[key] || '#94a3b8'
}

function DistributionBar({ title, segments, palette, total }) {
  const active = (segments || []).filter((seg) => seg.count > 0)
  if (!total || !active.length) {
    return (
      <div className="distribution-block">
        <h3>{title}</h3>
        <p className="muted">No data</p>
      </div>
    )
  }

  return (
    <div className="distribution-block">
      <h3>
        {title} <span className="muted">({total.toLocaleString()} images)</span>
      </h3>
      <div className="distribution-track" role="img" aria-label={title}>
        {active.map((seg) => (
          <div
            key={seg.key}
            className="distribution-segment"
            style={{ width: `${seg.percent}%`, backgroundColor: colorFor(seg.key, palette) }}
            title={`${seg.label}: ${seg.count} (${seg.percent}%)`}
          />
        ))}
      </div>
      <ul className="distribution-legend">
        {active.map((seg) => (
          <li key={seg.key}>
            <span className="swatch" style={{ backgroundColor: colorFor(seg.key, palette) }} />
            <span className="legend-label">{seg.label}</span>
            <span className="legend-value">
              {seg.count.toLocaleString()} ({seg.percent}%)
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function DistributionBars({ distributions }) {
  if (!distributions?.total) return null

  return (
    <section className="panel full distribution-panel">
      <DistributionBar
        title="Inspection outcomes"
        segments={distributions.outcomes}
        palette={OUTCOME_COLORS}
        total={distributions.total}
      />
      <DistributionBar
        title="Image types"
        segments={distributions.image_types}
        palette={IMAGE_TYPE_COLORS}
        total={distributions.total}
      />
    </section>
  )
}
