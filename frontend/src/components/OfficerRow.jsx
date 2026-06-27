import { useEffect, useRef, useState } from 'react'
import { IconLogOut } from './Icons.jsx'

/**
 * OfficerRow — officer avatar + name at the sidebar bottom.
 * Clicking opens a popup menu with a sign out option.
 *
 * Props:
 *   officer: { full_name, rank, badge_number }
 *   onSignOut: () => void
 *
 * The popup appears ABOVE the officer row and closes on outside click or sign out.
 */
export default function OfficerRow({ officer, onSignOut }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  // Close on outside click.
  useEffect(() => {
    function handleClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  // ponytail: two-word initials only, ceiling: <100 names, upgrade: share a formatter once more avatar cases appear.
  const initials =
    officer?.full_name
      ?.split(' ')
      .map((w) => w[0])
      .slice(0, 2)
      .join('')
      .toUpperCase() ?? 'KP'

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      {open && (
        <div className="officer-popup">
          <div
            style={{
              padding: '8px 10px 6px',
              borderBottom: '1px solid var(--border)',
              marginBottom: 4,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>
              {officer?.full_name}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
              {officer?.badge_number}
            </div>
          </div>
          <button
            className="officer-popup-item danger"
            onClick={() => {
              setOpen(false)
              onSignOut()
            }}
          >
            <IconLogOut size={15} />
            Sign out
          </button>
        </div>
      )}

      <div className="officer-row" onClick={() => setOpen((o) => !o)}>
        <div className="officer-avatar">{initials}</div>
        <div className="officer-info">
          <div className="officer-name">{officer?.full_name ?? 'Officer'}</div>
          <div className="officer-rank">{officer?.rank ?? ''}</div>
        </div>
      </div>
    </div>
  )
}
