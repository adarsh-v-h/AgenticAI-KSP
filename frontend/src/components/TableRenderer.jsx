const MAX_ROWS = 50
const TRUNCATE_AT = 100

function formatCell(value) {
  if (value === null || value === undefined) return { text: '—', full: '' }
  if (typeof value === 'boolean') return { text: value ? 'Yes' : 'No', full: '' }
  if (typeof value === 'number') return { text: String(value), full: '' }
  if (typeof value === 'object') {
    const json = JSON.stringify(value)
    if (json.length > TRUNCATE_AT) {
      return { text: json.slice(0, TRUNCATE_AT - 1) + '…', full: json }
    }
    return { text: json, full: '' }
  }
  const s = String(value)
  if (s.length > TRUNCATE_AT) {
    return { text: s.slice(0, TRUNCATE_AT - 1) + '…', full: s }
  }
  return { text: s, full: '' }
}

export default function TableRenderer({ data }) {
  if (!Array.isArray(data) || data.length === 0) return null

  const rows = data.slice(0, MAX_ROWS)
  const columns = Object.keys(rows[0] ?? {})
  if (columns.length === 0) return null

  const truncated = data.length > rows.length

  return (
    <div className="table-card">
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri}>
                {columns.map((c) => {
                  const cell = formatCell(row[c])
                  return (
                    <td key={c} title={cell.full || undefined}>
                      {cell.text}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-footer">
        {truncated
          ? `Showing first ${rows.length} of ${data.length} records.`
          : `${rows.length} record${rows.length === 1 ? '' : 's'}.`}
      </div>
    </div>
  )
}
