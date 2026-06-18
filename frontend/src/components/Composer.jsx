import { useEffect, useRef } from 'react'
import { IconMic, IconArrowUp, IconPaperclip } from './Icons.jsx'

/**
 * Composer – the message input box, always at the bottom of the screen.
 *
 * Props:
 *   value: string
 *   onChange: (val: string) => void
 *   onSend: (text: string) => void
 *   onStop: () => void – called when the stop button is clicked while streaming
 *   disabled: bool – true while streaming
 *   statusText: string | null – pipeline status shown above composer
 *
 * Features:
 *   - Textarea auto-grows up to 160px, then scrolls
 *   - Enter sends, Shift+Enter adds newline
 *   - Voice button (placeholder – not yet functional)
 *   - Send button (coral, arrow icon, disabled while streaming or input empty)
 *   - While streaming, the send button is replaced by a stop button so the
 *     officer can cancel a long-running query
 *   - Status text shown above the box while streaming
 */

function IconStop({ size = 14 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="currentColor"
      aria-hidden="true"
    >
      <rect x="3" y="3" width="10" height="10" rx="2" />
    </svg>
  )
}

export default function Composer({
  value,
  onChange,
  onSend,
  onStop,
  disabled,
  statusText,
}) {
  const textareaRef = useRef(null)
  const canSend = !disabled && value.trim()

  // Auto-resize textarea up to 160px, then scroll.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }, [value])

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (canSend) {
        onSend(value.trim())
      }
    }
  }

  return (
    <div className="composer-area">
      <div className="composer-inner">
        {/* Status text while the pipeline runs */}
        {statusText && (
          <p
            style={{
              fontSize: 12,
              color: 'var(--text-tertiary)',
              marginBottom: 6,
              paddingLeft: 4,
            }}
          >
            {statusText}
          </p>
        )}

        <div className="composer-box">
          <textarea
            ref={textareaRef}
            className="composer-textarea"
            placeholder="Ask about cases, accused, officers, evidence..."
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            rows={1}
          />

          <div className="composer-actions">
            <div className="composer-left-actions">
              {/* Attach – UI only, file analysis coming via Zoho Catalyst */}
              <button
                className="composer-action-btn not-yet"
                title="Attach report (coming soon)"
                onClick={() => {}}
                disabled={disabled}
                type="button"
              >
                <IconPaperclip size={18} />
              </button>

              {/* Voice – placeholder, not yet functional */}
              <button
                className="composer-action-btn not-yet"
                title="Voice input (coming soon)"
                onClick={() => {}}
                type="button"
              >
                <IconMic size={18} />
              </button>
            </div>

            {disabled ? (
              <button
                className="send-btn send-btn--stop"
                onClick={() => onStop?.()}
                type="button"
                title="Stop generating"
              >
                <IconStop size={14} />
              </button>
            ) : (
              <button
                className="send-btn"
                onClick={() => canSend && onSend(value.trim())}
                disabled={!canSend}
                type="button"
                title="Send message"
              >
                <IconArrowUp size={16} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

