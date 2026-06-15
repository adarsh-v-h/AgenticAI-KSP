import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { startChatStream } from '../api/chat.js'
import MessageBubble from './MessageBubble.jsx'

function newSessionId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return 'sess-' + Math.random().toString(36).slice(2) + Date.now().toString(36)
}

function newMessageId() {
  return 'm-' + Math.random().toString(36).slice(2) + Date.now().toString(36)
}

const SAMPLE_QUESTIONS = [
  'How many theft cases are open?',
  'Show me all cases involving Mahesh Gowda',
  'List all vehicle theft cases with the registration number',
  'Who are the top 5 repeat offenders?',
]

export default function ChatWindow({ officer, onLogout }) {
  const [sessionId, setSessionId] = useState(() => newSessionId())
  const [messages, setMessages] = useState([])
  const [inputValue, setInputValue] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [statusText, setStatusText] = useState('')

  const cancelRef = useRef(null)
  const scrollRef = useRef(null)
  const textareaRef = useRef(null)

  // Cancel any active stream on unmount.
  useEffect(() => {
    return () => {
      if (cancelRef.current) cancelRef.current()
    }
  }, [])

  // Auto-scroll to bottom when content arrives.
  useEffect(() => {
    if (!scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, statusText])

  const updateLastAssistant = useCallback((updater) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev
      const next = prev.slice()
      for (let i = next.length - 1; i >= 0; i--) {
        if (next[i].role === 'assistant') {
          next[i] = { ...next[i], ...updater(next[i]) }
          break
        }
      }
      return next
    })
  }, [])

  const handleSend = useCallback(
    (override) => {
      const question = (override ?? inputValue).trim()
      if (!question || isStreaming) return

      const userMsg = {
        id: newMessageId(),
        role: 'user',
        content: question,
      }
      const assistantMsg = {
        id: newMessageId(),
        role: 'assistant',
        content: '',
        tableData: null,
        mediaAttachments: null,
        isStreaming: true,
        error: false,
      }

      setMessages((prev) => [...prev, userMsg, assistantMsg])
      setInputValue('')
      setIsStreaming(true)
      setStatusText('Sending…')

      cancelRef.current = startChatStream(question, sessionId, {
        onStatus: (msg) => setStatusText(msg),
        onToken: (chunk) =>
          updateLastAssistant((m) => ({ content: (m.content || '') + chunk })),
        onTable: (rows) => updateLastAssistant(() => ({ tableData: rows })),
        onMedia: (refs) => updateLastAssistant(() => ({ mediaAttachments: refs })),
        onError: (msg) =>
          updateLastAssistant((m) => ({
            content: (m.content && m.content.length > 0 ? m.content + '\n\n' : '') + msg,
            error: true,
          })),
        onAuthExpired: () => {
          if (cancelRef.current) cancelRef.current()
          onLogout()
        },
        onDone: () => {
          updateLastAssistant(() => ({ isStreaming: false }))
          setIsStreaming(false)
          setStatusText('')
          cancelRef.current = null
          requestAnimationFrame(() => textareaRef.current?.focus())
        },
      })
    },
    [inputValue, isStreaming, sessionId, updateLastAssistant, onLogout],
  )

  function handleNewChat() {
    if (isStreaming && cancelRef.current) cancelRef.current()
    setMessages([])
    setSessionId(newSessionId())
    setStatusText('')
    setInputValue('')
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const isEmpty = messages.length === 0

  const officerLabel = useMemo(() => {
    if (!officer) return ''
    const parts = [officer.full_name, officer.rank].filter(Boolean)
    return parts.join(' · ')
  }, [officer])

  return (
    <div className="chat-shell">
      <header className="topbar">
        <div className="topbar__brand">
          <span className="topbar__mark" aria-hidden="true">✱</span>
          <div className="topbar__titles">
            <div className="topbar__title">KSP Crime Intelligence</div>
            <div className="topbar__subtitle">
              Session {sessionId.slice(0, 8)}
              {officerLabel ? ` · ${officerLabel}` : ''}
            </div>
          </div>
        </div>
        <div className="topbar__actions">
          <button className="btn btn--ghost" onClick={handleNewChat} disabled={isStreaming}>
            New chat
          </button>
          <button className="btn btn--ghost" onClick={onLogout}>
            Sign out
          </button>
        </div>
      </header>

      <main className="chat-scroll" ref={scrollRef}>
        {isEmpty ? (
          <div className="chat-empty">
            <h2>Ask about cases, accused, or evidence.</h2>
            <p>Plain English works. Try one of these to get started:</p>
            <div className="suggestions">
              {SAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q}
                  className="suggestion-chip"
                  onClick={() => handleSend(q)}
                  disabled={isStreaming}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="chat-messages">
            {messages.map((m) => (
              <MessageBubble
                key={m.id}
                role={m.role}
                content={m.content}
                tableData={m.tableData}
                mediaAttachments={m.mediaAttachments}
                isStreaming={m.isStreaming}
                error={m.error}
              />
            ))}
          </div>
        )}
      </main>

      <footer className="composer">
        {statusText ? <div className="composer__status">{statusText}</div> : null}
        <div className="composer__row">
          <textarea
            ref={textareaRef}
            className="composer__input"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question…"
            rows={1}
            disabled={isStreaming}
          />
          <button
            className="btn btn--primary"
            onClick={() => handleSend()}
            disabled={isStreaming || inputValue.trim().length === 0}
          >
            {isStreaming ? 'Working…' : 'Send'}
          </button>
        </div>
        <div className="composer__hint">
          Press Enter to send · Shift+Enter for a new line
        </div>
      </footer>
    </div>
  )
}
