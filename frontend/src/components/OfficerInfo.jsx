// OfficerInfo
//
// Displays the authenticated officer's identity at the bottom of the chat
// history sidebar (Requirement 7). Renders the officer's full name and rank,
// with a small avatar circle showing their initials. When officer data is
// missing or incomplete, sensible placeholders are shown instead (Req 7.3).
//
// Positioning (sticky at the bottom of the sidebar so it stays visible while
// the session list scrolls — Req 7.4) is handled by the `officer-info` and
// `officer-info--sticky` classes; the actual CSS arrives in a later styling
// task.

const NAME_PLACEHOLDER = 'Officer'
const RANK_PLACEHOLDER = 'Not signed in'

// Derive up to two uppercase initials from a full name. Falls back to a
// neutral marker when no usable name is available.
function getInitials(fullName) {
  if (!fullName || typeof fullName !== 'string') return '–'
  const parts = fullName.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '–'
  const first = parts[0].charAt(0)
  const last = parts.length > 1 ? parts[parts.length - 1].charAt(0) : ''
  const initials = (first + last).toUpperCase()
  return initials || '–'
}

export default function OfficerInfo({ officer }) {
  const fullName =
    officer && typeof officer.full_name === 'string' && officer.full_name.trim().length > 0
      ? officer.full_name.trim()
      : null
  const rank =
    officer && typeof officer.rank === 'string' && officer.rank.trim().length > 0
      ? officer.rank.trim()
      : null

  const displayName = fullName ?? NAME_PLACEHOLDER
  const displayRank = rank ?? RANK_PLACEHOLDER
  const initials = getInitials(fullName)

  return (
    <div className="officer-info officer-info--sticky">
      <div className="officer-info__avatar" aria-hidden="true">
        {initials}
      </div>
      <div className="officer-info__details">
        <div className="officer-info__name">{displayName}</div>
        <div className="officer-info__rank">{displayRank}</div>
      </div>
    </div>
  )
}
