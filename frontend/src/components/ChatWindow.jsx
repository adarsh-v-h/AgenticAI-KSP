import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AuthError,
  fetchMessages,
  fetchSessions,
  startChatStream,
  exportSession,
} from '../api/chat.js'
import MessageBubble from './MessageBubble.jsx'
import SessionList from './SessionList.jsx'
import WelcomeScreen from './WelcomeScreen.jsx'
import Composer from './Composer.jsx'
import OfficerRow from './OfficerRow.jsx'
import { IconSidebarOpen, IconSidebarClose, IconNewChat, IconDownload } from './Icons.jsx'

const SIDEBAR_COLLAPSED_KEY = 'chs.sidebarCollapsed'

const SIDEBAR_WIDTH_KEY = 'chs.sidebarWidth'
const SIDEBAR_MIN_WIDTH = 220
const SIDEBAR_MAX_WIDTH = 480
const SIDEBAR_DEFAULT_WIDTH = 260

function readSidebarCollapsed() {
  if (typeof window === 'undefined' || !window.localStorage) return false
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}

function readSidebarWidth() {
  if (typeof window === 'undefined' || !window.localStorage) return SIDEBAR_DEFAULT_WIDTH
  try {
    const raw = window.localStorage.getItem(SIDEBAR_WIDTH_KEY)
    const parsed = Number.parseInt(raw, 10)
    if (Number.isNaN(parsed)) return SIDEBAR_DEFAULT_WIDTH
    return Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, parsed))
  } catch {
    return SIDEBAR_DEFAULT_WIDTH
  }
}

function newSessionId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return 'sess-' + Math.random().toString(36).slice(2) + Date.now().toString(36)
}

function newMessageId() {
  return 'm-' + Math.random().toString(36).slice(2) + Date.now().toString(36)
}

export default function ChatWindow({ officer, onLogout }) {
  const [activeSessionId, setActiveSessionId] = useState(() => newSessionId())
  const [messages, setMessages] = useState([])
  const [inputValue, setInputValue] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [statusText, setStatusText] = useState('')
  const [isExportingActive, setIsExportingActive] = useState(false)

  const [sessionError, setSessionError] = useState(null)
  const [sessionsError, setSessionsError] = useState(null)
  const [messagesError, setMessagesError] = useState(null)

  const [sessions, setSessions] = useState([])
  const [isLoadingSessions, setIsLoadingSessions] = useState(false)
  const [isLoadingMessages, setIsLoadingMessages] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed)
  const [sidebarWidth, setSidebarWidth] = useState(readSidebarWidth)
  const [isResizing, setIsResizing] = useState(false)

  const activeSessionIdRef = useRef(activeSessionId)
  useEffect(() => {
    activeSessionIdRef.current = activeSessionId
  }, [activeSessionId])

  const draftInputsRef = useRef(new Map())

  const cancelRef = useRef(null)
  const scrollRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    return () => {
      if (cancelRef.current) cancelRef.current()
    }
  }, [])

  const loadSessions = useCallback(() => {
    setIsLoadingSessions(true)
    setSessionsError(null)
    return fetchSessions()
      .then((loaded) => {
        setSessions(loaded)
      })
      .catch((err) => {
        if (err instanceof AuthError) {
          onLogout()
        } else {
          console.error('ChatWindow: failed to load sessions', err)
          setSessionsError('Failed to load conversations.')
        }
      })
      .finally(() => {
        setIsLoadingSessions(false)
      })
  }, [onLogout])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  useEffect(() => {
    if (typeof window === 'undefined' || !window.localStorage) return
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(sidebarCollapsed))
    } catch {
      // Ignore storage write failures (e.g. private mode / quota).
    }
  }, [sidebarCollapsed])

  useEffect(() => {
    if (typeof window === 'undefined' || !window.localStorage) return
    try {
      window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth))
    } catch {
      // Ignore storage write failures (e.g. private mode / quota).
    }
  }, [sidebarWidth])

  const handleResizeStart = useCallback((e) => {
    e.preventDefault()
    setIsResizing(true)

    const onMove = (moveEvent) => {
      const clientX = moveEvent.touches ? moveEvent.touches[0].clientX : moveEvent.clientX
      const next = Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, clientX))
      setSidebarWidth(next)
    }

    const onUp = () => {
      setIsResizing(false)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      window.removeEventListener('touchmove', onMove)
      window.removeEventListener('touchend', onUp)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }

    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    window.addEventListener('touchmove', onMove)
    window.addEventListener('touchend', onUp)
  }, [])

  const handleResizeReset = useCallback(() => {
    setSidebarWidth(SIDEBAR_DEFAULT_WIDTH)
  }, [])

  useEffect(() => {
    if (!sessionError) return
    const timer = setTimeout(() => setSessionError(null), 5000)
    return () => clearTimeout(timer)
  }, [sessionError])

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

  const deriveTitle = useCallback((firstUserMessage) => {
    const trimmed = (firstUserMessage || '').trim()
    if (!trimmed) return 'New chat'
    if (trimmed.length <= 60) return trimmed
    return trimmed.slice(0, 57) + '...'
  }, [])

  const bumpSessionMetadata = useCallback(
    (sessionId, firstUserMessage) => {
      if (!sessionId) return
      const nowIso = new Date().toISOString()
      setSessions((prev) => {
        const idx = prev.findIndex((s) => s.session_id === sessionId)
        let next
        if (idx === -1) {
          next = [
            {
              session_id: sessionId,
              title: deriveTitle(firstUserMessage),
              created_at: nowIso,
              updated_at: nowIso,
              message_count: 2,
            },
            ...prev,
          ]
        } else {
          const existing = prev[idx]
          const updated = {
            ...existing,
            updated_at: nowIso,
            message_count: (existing.message_count || 0) + 2,
          }
          next = prev.slice()
          next[idx] = updated
        }
        return next
          .slice()
          .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
      })
    },
    [deriveTitle],
  )


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
      setStatusText('Sending...')

      const turnSessionId = activeSessionId

      cancelRef.current = startChatStream(question, activeSessionId, {
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
          bumpSessionMetadata(turnSessionId, question)
          fetchSessions()
            .then((loaded) => setSessions(loaded))
            .catch(() => {})
          requestAnimationFrame(() => textareaRef.current?.focus())
        },
      })
    },
    [
      inputValue,
      isStreaming,
      activeSessionId,
      updateLastAssistant,
      onLogout,
      bumpSessionMetadata,
    ],
  )

  const loadSessionMessages = useCallback(
    (sessionId) => {
      setMessagesError(null)
      setIsLoadingMessages(true)
      return fetchMessages(sessionId)
        .then(({ messages: fetched }) => {
          const mapped = fetched.map((m) => ({
            id: m.message_id,
            role: m.role,
            content: m.content,
            tableData:
              Array.isArray(m.table_data) && m.table_data.length > 0
                ? m.table_data
                : null,
            mediaAttachments:
              Array.isArray(m.media_attachments) && m.media_attachments.length > 0
                ? m.media_attachments
                : null,
            isStreaming: false,
            error: false,
          }))
          setMessages(mapped)

          requestAnimationFrame(() => {
            if (scrollRef.current) {
              scrollRef.current.scrollTop = scrollRef.current.scrollHeight
            }
          })
        })
        .catch((err) => {
          if (err instanceof AuthError) {
            onLogout()
          } else {
            console.error('ChatWindow: failed to load messages', err)
            setMessagesError('Failed to load messages.')
          }
        })
        .finally(() => {
          setIsLoadingMessages(false)
        })
    },
    [onLogout],
  )

  const retryLoadMessages = useCallback(() => {
    loadSessionMessages(activeSessionIdRef.current)
  }, [loadSessionMessages])

  const handleExportActiveSession = useCallback(async () => {
    if (isExportingActive) return
    setIsExportingActive(true)
    try {
      await exportSession(activeSessionId)
    } catch (err) {
      console.error('Export failed:', err)
      setSessionError('Failed to export PDF.')
    } finally {
      setIsExportingActive(false)
    }
  }, [activeSessionId, isExportingActive])

  const handleSelectSession = useCallback(
    (sessionId) => {
      if (sessionId === activeSessionId) return

      if (isStreaming) {
        cancelRef.current?.()
        cancelRef.current = null
        setIsStreaming(false)
        setStatusText('')
      }

      draftInputsRef.current.set(activeSessionId, inputValue)
      const restoredDraft = draftInputsRef.current.get(sessionId)
      setInputValue(restoredDraft || '')

      activeSessionIdRef.current = sessionId
      setActiveSessionId(sessionId)
      setMessages([])
      setMessagesError(null)
      loadSessionMessages(sessionId)
    },
    [activeSessionId, isStreaming, inputValue, loadSessionMessages],
  )

  const handleNewChat = useCallback(() => {
    if (messages.length === 0 && !isStreaming) {
      return
    }

    if (isStreaming) {
      cancelRef.current?.()
      cancelRef.current = null
      setIsStreaming(false)
      setStatusText('')
    }

    setSessionError(null)

    const freshId = newSessionId()
    activeSessionIdRef.current = freshId
    setActiveSessionId(freshId)
    setMessages([])
    setInputValue('')
    setStatusText('')
    setMessagesError(null)  }, [messages.length, isStreaming])

  const isEmpty = messages.length === 0

  const sidebarOpen = !sidebarCollapsed

  const currentSessionTitle = useMemo(() => {
    const active = sessions.find((s) => s.session_id === activeSessionId)
    return active?.title || ''
  }, [sessions, activeSessionId])

  return (
    <div className="app-shell">
      <aside
        className={`sidebar ${sidebarOpen ? 'expanded' : 'collapsed'}${isResizing ? ' resizing' : ''}`}
        style={sidebarOpen ? { width: sidebarWidth } : undefined}
      >
        <div className="sidebar-top">
          <button
            className="sidebar-icon-btn"
            onClick={() => setSidebarCollapsed((c) => !c)}
            title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
          >
            {sidebarOpen ? <IconSidebarClose /> : <IconSidebarOpen />}
          </button>
        </div>

        <button
          className="new-chat-row"
          onClick={handleNewChat}
          title="New chat"
        >
          <span className="new-chat-row__icon">
            <IconNewChat />
          </span>
          {sidebarOpen && <span className="new-chat-row__label">New chat</span>}
        </button>

        <div className="session-list-container">
          {sidebarOpen && <div className="recents-label">Recents</div>}
          <SessionList
            sessions={sessions}
            activeSessionId={activeSessionId}
            onSelect={handleSelectSession}
            isLoading={isLoadingSessions}
            error={sessionsError}
            onRetry={loadSessions}
          />
        </div>

        <div className="sidebar-bottom">
          <OfficerRow officer={officer} onSignOut={onLogout} />
        </div>

        {sidebarOpen && (
          <div
            className="sidebar-resize-handle"
            onMouseDown={handleResizeStart}
            onTouchStart={handleResizeStart}
            onDoubleClick={handleResizeReset}
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize sidebar"
            title="Drag to resize"
          />
        )}
      </aside>

      <main className="main-content">
        {!sidebarOpen && currentSessionTitle && (
          <div
            style={{
              padding: '12px 20px 0',
              fontSize: 13,
              color: 'var(--text-secondary)',
              fontWeight: 500,
              flexShrink: 0,
            }}
          >
            {currentSessionTitle}
          </div>
        )}

        {sessionError ? (
          <div className="toast toast--error" role="alert">
            <span className="toast__message">{sessionError}</span>
            <button
              type="button"
              className="toast__dismiss"
              onClick={() => setSessionError(null)}
              aria-label="Dismiss notification"
            >
              x
            </button>
          </div>
        ) : null}

        {isEmpty && !messagesError ? (
          <div className="welcome-screen">
            <WelcomeScreen officer={officer} onSuggestion={handleSend} isStreaming={isStreaming} />
            <Composer
              value={inputValue}
              onChange={setInputValue}
              onSend={handleSend}
              disabled={isStreaming}
              statusText={statusText}            />
          </div>
        ) : (
          <div className="chat-area">
            <div className="chat-header">
              <h2 className="chat-header__title">{currentSessionTitle || 'Conversation'}</h2>
              <button
                type="button"
                className="chat-header__export-btn"
                title="Export as PDF"
                onClick={handleExportActiveSession}
                disabled={isExportingActive || isStreaming}
              >
                {isExportingActive ? (
                  <span className="spinner" style={{ marginRight: 6 }} />
                ) : (
                  <IconDownload size={16} />
                )}
                <span>Export PDF</span>
              </button>
            </div>
            <div className="messages-scroll" ref={scrollRef}>
              <div className="messages-inner">
                {messagesError ? (
                  <div className="chat-error" role="alert">
                    <span className="chat-error__message">{messagesError}</span>
                    <button
                      type="button"
                      className="chat-error__retry"
                      onClick={retryLoadMessages}
                      disabled={isLoadingMessages}
                    >
                      {isLoadingMessages ? 'Retrying...' : 'Retry'}
                    </button>
                  </div>
                ) : null}

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
            </div>

            <Composer
              value={inputValue}
              onChange={setInputValue}
              onSend={handleSend}
              disabled={isStreaming}
              statusText={statusText}            />
          </div>
        )}
      </main>
    </div>
  )
}


