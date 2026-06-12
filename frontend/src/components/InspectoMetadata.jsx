const REVISION_FIELDS = [
  ['Previous Risc No.', 'Previous Risc No.'],
  ['Is Last Revision', 'Is Last Revision'],
  ['Related Risc', 'Related Risc'],
]

const INSPECTION_DETAIL_FIELDS = [
  ['Form No.', 'Form No.'],
  ['Status', 'Status'],
  ['Inspected Result', 'Inspected Result'],
  ['Type', 'Type'],
  ['Inspection Type', 'Inspection Type'],
  ['Location', 'Location'],
  ['Work To Be Inspected', 'Work To Be Inspected'],
  ['Work Proposed', 'Work Proposed'],
  ['Inspection Detail', 'Inspection Detail'],
  ['ITP No.', 'ITP No.'],
  ['ITP Title', 'ITP Title'],
  ['ITP Item No.', 'ITP Item No.'],
  ['ITP Item Description', 'ITP Item Description'],
  ['Remarks', 'Remarks'],
  ['Reason', 'Reason'],
  ['Reject Reason', 'Reject Reason'],
  ['Inspected By', 'Inspected By'],
  ['Inspector Title', 'Inspector Title'],
  ['Inspected Date', 'Inspected Date'],
  ['Inspected Time', 'Inspected Time'],
  ['Submitted By', 'Submitted By'],
  ['Submitted Date', 'Submitted Date'],
  ['Submitted Time', 'Submitted Time'],
  ['First Submitted Date', 'First Submitted Date'],
  ['First Submitted Time', 'First Submitted Time'],
  ['Contract', 'Contract'],
  ['Contract No.', 'Contract No.'],
]

const FULL_WIDTH_KEYS = new Set([
  'Work To Be Inspected',
  'Work Proposed',
  'Inspection Detail',
  'ITP Item Description',
  'Remarks',
  'Reason',
  'Reject Reason',
])

function FieldGrid({ fields, inspecto }) {
  const rows = fields
    .map(([label, key]) => {
      const value = inspecto[key]
      if (!value) return null
      return (
        <div key={key} className={FULL_WIDTH_KEYS.has(key) ? 'full' : undefined}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      )
    })
    .filter(Boolean)

  if (!rows.length) return null

  return <dl className="dataset-meta">{rows}</dl>
}

export default function InspectoMetadata({ inspecto, title = 'Inspecto export metadata' }) {
  if (!inspecto) return null

  const hasRevision = REVISION_FIELDS.some(([, key]) => inspecto[key])
  const hasInspection = INSPECTION_DETAIL_FIELDS.some(([, key]) => inspecto[key])
  if (!hasRevision && !hasInspection) return null

  return (
    <section className="panel full inspecto-panel">
      <h2>{title}</h2>
      {hasRevision && (
        <>
          <h3 className="inspecto-subheading">Revision</h3>
          <FieldGrid fields={REVISION_FIELDS} inspecto={inspecto} />
        </>
      )}
      {hasInspection && (
        <>
          <h3 className="inspecto-subheading">Inspection details</h3>
          <FieldGrid fields={INSPECTION_DETAIL_FIELDS} inspecto={inspecto} />
        </>
      )}
    </section>
  )
}
