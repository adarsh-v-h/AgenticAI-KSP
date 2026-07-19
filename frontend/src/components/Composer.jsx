import { useEffect, useRef, useState } from 'react'
import { IconArrowUp, IconPaperclip } from './Icons.jsx'
import VoiceInput from './VoiceInput.jsx'
import { useLang } from '../context/LangContext.jsx'
import { analyzeReport, validateReportFile, AuthError } from '../api/reports.js'

const COMPOSER_MAX_HEIGHT = 160

/**
 * Composer — the message input box, always at the bottom of the screen.
 *
 * Props:
 *   value: string
 *   onChange: (val: string) => void
 *   onSend: (text: string) => void
 *   onStop: () => void — called when the stop button is clicked while streaming
 *   disabled: bool — true while streaming
 *   statusText: string | null — pipeline status shown above composer
 *   sessionId: string — active chat session, needed to attach an uploaded report to it
 *   onReportAnalyzed: (result: {answer_text, extracted_chars, file_name, warning}, fileName: string) => void
 *     — called with the backend's analysis once a report upload succeeds
 *   onAuthExpired: () => void — called if the report upload gets a 401
 *
 * Features:
 *   - Textarea auto-grows up to 160px, then scrolls
 *   - Enter sends, Shift+Enter adds newline
 *   - Attach button — opens a file picker, uploads the report to
 *     POST /api/reports/analyze (see backend/routers/reports.py), and surfaces
 *     the analysis or any error inline above the composer
 *   - Voice button (mic → Zia STT)
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
  rateLimitInfo,
  sessionId,
  onReportAnalyzed,
  onAuthExpired,
}) {
  const textareaRef = useRef(null)
  const fileInputRef = useRef(null)
  const isRateLimited = Boolean(rateLimitInfo)
  const inputDisabled = disabled || isRateLimited
  const canSend = !inputDisabled && value.trim()
  const { lang } = useLang()

  // Report upload state: idle while nothing is happening, uploading while a
  // request is in flight, and an inline error message on failure. Success
  // doesn't need its own state — the result is handed to the parent via
  // onReportAnalyzed and rendered as a normal assistant message, same as any
  // other chat turn.
  const [isUploadingReport, setIsUploadingReport] = useState(false)
  const [uploadError, setUploadError] = useState(null)

  // CONTRACT
  // takes:  nothing
  // returns: nothing (opens the browser's native file picker)
  // throws:  never
  function handleAttachClick() {
    if (inputDisabled || isUploadingReport) return
    setUploadError(null)
    fileInputRef.current?.click()
  }

  // CONTRACT
  // takes:  event (Event) — the file input's change event
  // returns: (Promise<void>) — resolves once the upload attempt finishes
  // throws:  never (all failures are caught and surfaced via uploadError / onAuthExpired)
  async function handleFileSelected(event) {
    const file = event.target.files?.[0]
    // Always reset the input value so selecting the SAME file again still
    // fires a change event (browsers don't fire `change` if the value is
    // unchanged, which would otherwise make a retry-after-error impossible
    // without picking a different file first).
    event.target.value = ''
    if (!file) return

    const validationError = validateReportFile(file)
    if (validationError) {
      setUploadError(validationError)
      return
    }

    setUploadError(null)
    setIsUploadingReport(true)
    try {
      const result = await analyzeReport(file, sessionId, value.trim())
      onReportAnalyzed?.(result, file.name)
      // Clear the composer's text input too, mirroring onSend's behavior —
      // any instruction the officer typed was sent as the analysis prompt.
      onChange('')
    } catch (err) {
      if (err instanceof AuthError) {
        onAuthExpired?.()
        return
      }
      setUploadError(err?.message || 'Report analysis failed.')
    } finally {
      setIsUploadingReport(false)
    }
  }

  // Append a voice transcript into the composer instead of auto-sending, so the
  // officer can review/edit before sending. A trailing space keeps typing fluid.
  function handleVoiceTranscript(text) {
    if (!text) return
    const next = value && value.trim() ? `${value.trim()} ${text}` : text
    onChange(next)
    requestAnimationFrame(() => textareaRef.current?.focus())
  }

  // Auto-resize textarea up to 160px, then scroll.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, COMPOSER_MAX_HEIGHT)}px`
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
        {/* Station-wide rate limit reached — tell the officer what happened */}
        {isRateLimited && (
          <p
            role="alert"
            style={{
              fontSize: 12,
              color: 'var(--text-danger, #c0392b)',
              marginBottom: 6,
              paddingLeft: 4,
            }}
          >
            {rateLimitInfo.detail ||
              'Your station has reached its shared request limit for this 6-hour window.'}
          </p>
        )}

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

        {/* Report upload feedback */}
        {isUploadingReport && (
          <p
            style={{
              fontSize: 12,
              color: 'var(--text-tertiary)',
              marginBottom: 6,
              paddingLeft: 4,
            }}
          >
            Analyzing report...
          </p>
        )}
        {uploadError && (
          <p
            role="alert"
            style={{
              fontSize: 12,
              color: 'var(--text-danger, #c0392b)',
              marginBottom: 6,
              paddingLeft: 4,
            }}
          >
            {uploadError}
          </p>
        )}

        <div className="composer-box">
          <textarea
            ref={textareaRef}
            className="composer-textarea"
            placeholder={
              isRateLimited
                ? 'Station request limit reached — try again after the window resets.'
                : 'Ask about cases, accused, officers, evidence...'
            }
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={inputDisabled}
            rows={1}
          />

          <div className="composer-actions">
            <div className="composer-left-actions">
              {/* Attach report — POST /api/reports/analyze (backend/routers/reports.py).
                  Any text typed in the composer is sent along as the analysis
                  prompt (e.g. "focus on repeat offenders"); an empty composer
                  falls back to the backend's default prompt. */}
              <input
                ref={fileInputRef}
                type="file"
                accept=".docx,.txt,.md,.markdown,.csv,.log,.json,.html,.htm"
                style={{ display: 'none' }}
                onChange={handleFileSelected}
              />
              <button
                className="composer-action-btn"
                title="Attach report for analysis"
                onClick={handleAttachClick}
                disabled={inputDisabled || isUploadingReport}
                type="button"
              >
                {isUploadingReport ? (
                  <span className="voice-spinner" />
                ) : (
                  <IconPaperclip size={18} />
                )}
              </button>

              {/* Voice input — Zia STT (+ Kannada translation when lang=kn) */}
              <VoiceInput
                onTranscript={handleVoiceTranscript}
                language={lang}
                disabled={inputDisabled}
              />
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

