import { memo } from 'react'
import SessionItem from './SessionItem.jsx'

function SessionList({ sessions = [], activeSessionId, onSelect, isLoading = false, error = null, onRetry }) {
  if (error) {
    return (
      <div className="session-list session-list__error" role="alert">
        <span className="session-list__error-text">{error}</span>
        {onRetry ? (
          <button type="button" className="session-list__retry" onClick={onRetry}>Retry</button>
        ) : null}
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="session-list session-list__loading" role="status" aria-live="polite">
        Loading conversations…
      </div>
    )
  }

  if (!sessions || sessions.length === 0) {
    return (
      <div className="session-list session-list__empty">
        No conversations yet. Start a new chat!
      </div>
    )
  }

  return (
    <div className="session-list" role="list">
      {sessions.map((session) => (
        <SessionItem
          key={session.session_id}
          session={session}
          isActive={session.session_id === activeSessionId}
          onClick={onSelect}
        />
      ))}
    </div>
  )
}

export default memo(SessionList)
