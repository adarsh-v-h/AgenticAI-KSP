import TableRenderer from './TableRenderer.jsx'

// Defense-in-depth filter for Bug 1 (Duplicate Table Rendering).
//
// Even with the answer-formatter system prompt updated to forbid markdown
// tables, the LLM occasionally still emits one. When `tableData` is non-empty
// we strip any markdown-table fragment from the prose so the rows appear
// only once on screen, via TableRenderer.
//
// We're intentionally surgical:
//   - A "table line" = a non-empty line whose first AND last non-whitespace
//     characters are both `|`.
//   - A "divider line" = a table line whose interior is only `-`, `:`, `|`,
//     and whitespace.
// We drop runs of >=2 consecutive table lines (a real table needs at least
// header + body OR header + divider + body). Lone pipe-bearing sentences
// like `He said "she said | maybe"` survive untouched.
function stripMarkdownTable(text) {
  if (!text || typeof text !== 'string') return text
  if (!text.includes('|')) return text

  const lines = text.split('\n')
  const isTableLine = (line) => {
    const trimmed = line.trim()
    if (trimmed.length < 3) return false
    if (!trimmed.startsWith('|') || !trimmed.endsWith('|')) return false
    return true
  }

  const out = []
  let i = 0
  let stripped = false
  while (i < lines.length) {
    if (isTableLine(lines[i])) {
      let j = i
      while (j < lines.length && isTableLine(lines[j])) j++
      const runLength = j - i
      if (runLength >= 2) {
        // Drop the whole run; collapse surrounding blank lines so the prose
        // flows cleanly afterwards.
        if (out.length > 0 && out[out.length - 1].trim() === '') {
          // keep one blank line above
        }
        stripped = true
        i = j
        // Skip a single trailing blank line too, if present, to avoid
        // double-blank gaps.
        if (i < lines.length && lines[i].trim() === '') i++
        continue
      }
    }
    out.push(lines[i])
    i++
  }

  if (!stripped) return text
  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

export default function MessageBubble({
  role,
  content,
  tableData,
  mediaAttachments,
  isStreaming,
  error,
}) {
  const isUser = role === 'user'

  if (isUser) {
    return (
      <div className="message message--user">
        <div className="message__bubble">{content}</div>
      </div>
    )
  }

  // Only strip markdown tables when we're going to render the structured
  // table separately. With no tableData, leave the prose alone (a markdown
  // table in a no-data answer is unusual but harmless and not a duplicate).
  const hasTable = Array.isArray(tableData) && tableData.length > 0
  const renderedContent = hasTable ? stripMarkdownTable(content) : content

  return (
    <div className="message message--assistant">
      <div className="message__meta">Assistant</div>
      <div className={`message__body ${error ? 'message__body--error' : ''}`}>
        {renderedContent}
        {isStreaming ? <span className="message__caret">▍</span> : null}
      </div>

      {hasTable ? <TableRenderer data={tableData} /> : null}

      {Array.isArray(mediaAttachments) && mediaAttachments.length > 0 ? (
        <div className="media-list">
          <div className="media-list__title">Evidence attachments</div>
          <ul>
            {mediaAttachments.map((m, i) => (
              <li key={i}>
                <span className={`media-pill media-pill--${m.media_type}`}>
                  {m.media_type}
                </span>
                <span className="media-list__desc">
                  {m.description || m.url || 'attachment'}
                </span>
                {m.fir_id ? (
                  <span className="media-list__fir">FIR #{m.fir_id}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
