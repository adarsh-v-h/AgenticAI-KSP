import TableRenderer from './TableRenderer.jsx'

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

  return (
    <div className="message message--assistant">
      <div className="message__meta">Assistant</div>
      <div className={`message__body ${error ? 'message__body--error' : ''}`}>
        {content}
        {isStreaming ? <span className="message__caret">▍</span> : null}
      </div>

      {Array.isArray(tableData) && tableData.length > 0 ? (
        <TableRenderer data={tableData} />
      ) : null}

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
