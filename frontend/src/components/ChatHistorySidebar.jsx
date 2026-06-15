import { useCallback } from 'react'
import NewChatButton from './NewChatButton.jsx'
import SessionList from './SessionList.jsx'
import OfficerInfo from './OfficerInfo.jsx'

// ChatHistorySidebar
//
// Top-level container for the chat history sidebar (Requirements 8, 14). It
// composes the New chat button, the scrollable session list, and the officer
// info footer, and owns the collapse/expand affordance.
//
// Layout:
//   - Header  → NewChatButton + collapse toggle
//   - Body    → scrollable SessionList
//   - Footer  → OfficerInfo (sticky at the bottom)
//
// Width is controlled by the `chat-sidebar` (280px expanded) and
// `chat-sidebar--collapsed` (minimal rail) classes. The actual CSS, including
// the responsive overlay behaviour for narrow viewports, arrives in a later
// styling task — here we only apply the structure and class names.
//
// On small viewports (< 768px) selecting a session also closes the sidebar so
// the chat is immediately visible; we wrap onSelectSession to add that
// behaviour, guarding for environments without a `window` (SSR/tests).

const MOBILE_QUERY = '(max-width: 767px)'

function isMobileViewport() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false
  }
  return window.matchMedia(MOBILE_QUERY).matches
}

export default function ChatHistorySidebar({
  sessions = [],
  activeSessionId,
  officer,
  collapsed = false,
  isLoading = false,
  error = null,
  onRetry,
  onNewChat,
  onSelectSession,
  onToggleCollapse,
}) {
  // Wrap session selection so that, on mobile, the sidebar auto-closes after a
  // session is chosen (Req 14.4/14.5).
  const handleSelectSession = useCallback(
    (sessionId) => {
      if (onSelectSession) onSelectSession(sessionId)
      if (isMobileViewport() && !collapsed && onToggleCollapse) {
        onToggleCollapse()
      }
    },
    [onSelectSession, onToggleCollapse, collapsed],
  )

  const rootClassName = `chat-sidebar${collapsed ? ' chat-sidebar--collapsed' : ''}`
  const toggleLabel = collapsed ? 'Expand sidebar' : 'Collapse sidebar'

  if (collapsed) {
    // Minimal rail: just the controls needed to reopen the sidebar or start a
    // new chat. The full session list and officer info are hidden.
    return (
      <aside className={rootClassName} aria-label="Chat history">
        <div className="chat-sidebar__header">
          <button
            type="button"
            className="chat-sidebar__toggle"
            onClick={onToggleCollapse}
            aria-label={toggleLabel}
            aria-expanded="false"
          >
            <span aria-hidden="true">☰</span>
          </button>
          <NewChatButton onClick={onNewChat} />
        </div>
      </aside>
    )
  }

  return (
    <aside className={rootClassName} aria-label="Chat history">
      <div className="chat-sidebar__header">
        <NewChatButton onClick={onNewChat} />
        <button
          type="button"
          className="chat-sidebar__toggle"
          onClick={onToggleCollapse}
          aria-label={toggleLabel}
          aria-expanded="true"
        >
          <span aria-hidden="true">⟨</span>
        </button>
      </div>

      <div className="chat-sidebar__session-list">
        <SessionList
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
          isLoading={isLoading}
          error={error}
          onRetry={onRetry}
        />
      </div>

      <div className="chat-sidebar__footer">
        <OfficerInfo officer={officer} />
      </div>
    </aside>
  )
}
