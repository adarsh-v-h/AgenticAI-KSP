import { memo, useState } from 'react'
import { exportSession } from '../api/chat.js'
import { IconDownload } from './Icons.jsx'

// Format an ISO 8601 timestamp into a short, human-friendly relative label.
//   - Today        â†’ time, e.g. "12:30 PM"
//   - Yesterday    â†’ "Yesterday"
//   - This week    â†’ weekday name, e.g. "Monday"
//   - Older        â†’ short date, e.g. "Jan 15"
// Returns an empty string when the timestamp is missing or unparseable.
function formatRelativeTimestamp(iso) {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''

  const now = new Date()
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const dayMs = 24 * 60 * 60 * 1000
  const diffDays = Math.round((startOfDay(now) - startOfDay(date)) / dayMs)

  if (diffDays <= 0) {
    return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  }
  if (diffDays === 1) {
    return 'Yesterday'
  }
  if (diffDays < 7) {
    return date.toLocaleDateString(undefined, { weekday: 'long' })
  }
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function SessionItem({ session, isActive, onClick }) {
  const [isExporting, setIsExporting] = useState(false)

  if (!session) return null

  const { session_id, title, updated_at, message_count } = session
  const timestamp = formatRelativeTimestamp(updated_at)
  const count = typeof message_count === 'number' ? message_count : 0

  function handleClick() {
    if (onClick) onClick(session_id)
  }

  async function handleExport(e) {
    // Don't trigger session selection when clicking the export button.
    e.stopPropagation()
    if (isExporting) return
    setIsExporting(true)
    try {
      await exportSession(session_id)
    } catch (err) {
      console.error('Export failed:', err)
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      className={`session-item${isActive ? ' session-item--active' : ''}`}
      onClick={handleClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          handleClick()
        }
      }}
      aria-current={isActive ? 'true' : undefined}
    >
      <span className="session-item__title">{title || 'New chat'}</span>
      <span className="session-item__meta">
        {timestamp ? <span className="session-item__time">{timestamp}</span> : null}
        <span className="session-item__count">
          {count} {count === 1 ? 'message' : 'messages'}
        </span>
      </span>
      <button
        type="button"
        className="session-export-btn"
        title="Export conversation"
        aria-label="Export conversation"
        onClick={handleExport}
        disabled={isExporting}
      >
        <IconDownload size={14} />
      </button>
    </div>
  )
}

// Memoized to avoid re-rendering every session row when unrelated ChatWindow
// state changes (e.g. streaming tokens, input text). The session list can hold
// 100+ items, so skipping rows whose props are unchanged keeps switching/typing
// smooth. Props are stable enough for shallow comparison: `session` keeps object
// identity across renders (only the mutated entry gets a new reference in
// bumpSessionMetadata), `isActive` is a boolean, and `onClick`
// (handleSelectSession) is wrapped in useCallback upstream. For 100+ sessions
// this memoization mitigates re-render cost; list virtualization (react-window)
// is a documented future enhancement, not required for the MVP.
export default memo(SessionItem)

