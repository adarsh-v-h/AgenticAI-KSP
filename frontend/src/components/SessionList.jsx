import { memo } from 'react'
import SessionItem from './SessionItem.jsx'

// Renders a scrollable list of chat sessions.
//   - Shows an error message with a Retry action when `error` is set
//     (Requirements 15.1, 15.4). Error takes precedence over loading/empty so
//     a failed sessions load surfaces immediately in the sidebar.
//   - Shows a loading indicator while sessions are being fetched.
//   - Shows an empty-state message when there are no sessions.
//   - Sessions are rendered in the order provided (backend orders by
//     updated_at DESC), so we do not re-sort here.
//
// `error` and `onRetry` are optional and backward-compatible: when `error` is
// falsy the component behaves exactly as before.
//
// Wrapped in React.memo: combined with the memoized SessionItem rows, this
// avoids re-rendering the whole list when unrelated ChatWindow state changes
// (streaming tokens, composer input). Props are stable for shallow comparison —
// `sessions` only gets a new array reference when the list actually changes,
// and `onSelectSession`/`onRetry` come from useCallback upstream.
function SessionList({
  sessions = [],
  activeSessionId,
  onSelect,
  onSelectSession,
  isLoading = false,
  error = null,
  onRetry,
}) {
  // Accept either `onSelect` (new sidebar) or `onSelectSession` (legacy) so
  // both call sites keep working.
  const handleSelect = onSelect || onSelectSession

  if (error) {
    return (
      <div className="session-list session-list__error" role="alert">
        <span className="session-list__error-text">{error}</span>
        {onRetry ? (
          <button type="button" className="session-list__retry" onClick={onRetry}>
            Retry
          </button>
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
          onClick={handleSelect}
        />
      ))}
    </div>
  )
}

export default memo(SessionList)
