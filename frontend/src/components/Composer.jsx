import { useEffect, useRef } from 'react'
import { IconPaperclip, IconMic, IconArrowUp } from './Icons.jsx'

/**
 * Composer — the message input box, always at the bottom of the screen.
 *
 * Props:
 *   value: string
 *   onChange: (val: string) => void
 *   onSend: (text: string) => void
 *   disabled: bool — true while streaming
 *   statusText: string | null — pipeline status shown above composer
 *
 * Features:
 *   - Textarea auto-grows up to 160px, then scrolls
 *   - Enter sends, Shift+Enter adds newline
 *   - Attach + Voice buttons (placeholders — not yet functional)
 *   - Send button (coral, arrow icon, disabled while streaming or input empty)
 *   - Status text shown above the box while streaming
 */
export default function Composer({ value, onChange, onSend, disabled, statusText }) {
  const textareaRef = useRef(null)

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
      if (!disabled && value.trim()) {
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
              {/* Attach — placeholder, not yet functional */}
              <button
                className="composer-action-btn not-yet"
                title="Attach file (coming soon)"
                onClick={() => {}}
                type="button"
              >
                <IconPaperclip size={18} />
              </button>

              {/* Voice — placeholder, not yet functional */}
              <button
                className="composer-action-btn not-yet"
                title="Voice input (coming soon)"
                onClick={() => {}}
                type="button"
              >
                <IconMic size={18} />
              </button>
            </div>

            {/* Send */}
            <button
              className="send-btn"
              onClick={() => value.trim() && onSend(value.trim())}
              disabled={disabled || !value.trim()}
              type="button"
            >
              <IconArrowUp size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
