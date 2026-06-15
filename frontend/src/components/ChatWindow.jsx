import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AuthError, createSession, fetchMessages, fetchSessions, startChatStream } from '../api/chat.js'
import MessageBubble from './MessageBubble.jsx'
import ChatHistorySidebar from './ChatHistorySidebar.jsx'

// localStorage key for persisting the sidebar collapsed state across reloads
// (Requirements 8.4, 8.5).
const SIDEBAR_COLLAPSED_KEY = 'chs.sidebarCollapsed'

// Number of messages loaded per page for bottom-to-top pagination. The initial
// session load fetches the 50 most recent messages (Requirement 4.1), and the
// scroll-triggered "load older" flow (task 8.4) reuses the same page size so
// the contract stays self-documenting in one place.
const PAGE_SIZE = 50

// Lazy initializer for sidebarCollapsed: read the persisted value from
// localStorage, guarding for environments without `window` (SSR/tests).
function readSidebarCollapsed() {
  if (typeof window === 'undefined' || !window.localStorage) return false
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}

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
  const [activeSessionId, setActiveSessionId] = useState(() => newSessionId())
  const [messages, setMessages] = useState([])
  const [inputValue, setInputValue] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [statusText, setStatusText] = useState('')

  // Transient error surfaced when session creation fails (Requirement 15.3).
  // Presented as a toast-style notification (see render below): auto-dismisses
  // after a few seconds and is manually dismissable. We retain the current
  // Active_Session on failure rather than switching.
  const [sessionError, setSessionError] = useState(null)

  // Error surfaced when the mount sessions load fails (Requirement 15.1). When
  // set, the sidebar renders an error message + Retry (re-runs loadSessions).
  // We do NOT clear the existing sessions list on failure (Req 15.1).
  const [sessionsError, setSessionsError] = useState(null)

  // Error surfaced when loading a session's messages fails (Requirement 15.2).
  // Displayed inside the chat scroll area with a Retry button that re-attempts
  // loading the active session's messages. The session list is left intact.
  const [messagesError, setMessagesError] = useState(null)

  // --- Chat-history sidebar state (Requirements 13.1, 13.2, 13.4, 8.4, 8.5) ---
  // List of the officer's chat sessions, loaded from the backend on mount.
  const [sessions, setSessions] = useState([])
  // Loading flags for the two async data sources surfaced by the sidebar/chat.
  const [isLoadingSessions, setIsLoadingSessions] = useState(false)
  const [isLoadingMessages, setIsLoadingMessages] = useState(false)
  // Sidebar collapse state, restored from localStorage on mount and persisted
  // whenever it changes (see effects below).
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed)

  // Per-session pagination state, keyed by session_id with value
  // {hasMore, oldestMessageId}. We use a ref (not state) because pagination is
  // tracked independently per session (Requirement 13.4) and updated frequently
  // during scroll-triggered loading — keeping it in a ref avoids unnecessary
  // re-renders. The ref is the source of truth for load bookkeeping; the UI
  // reacts to the *active* session's hasMore via `activeHasMore` state below.
  const paginationRef = useRef(new Map())

  // React state mirroring the ACTIVE session's `hasMore` pagination flag. A ref
  // alone can't drive re-renders, so the "load older" affordances (task 8.3/8.4)
  // need a reactive value. We keep this in sync with paginationRef for whichever
  // session is currently active (Requirement 13.4).
  const [activeHasMore, setActiveHasMore] = useState(false)

  // Whether an older-messages page is currently being loaded for the active
  // session. Used by the scroll-triggered pagination flow (task 8.4) to prevent
  // overlapping loads; declared here so the structure is ready.
  const [isLoadingOlder, setIsLoadingOlder] = useState(false)

  // Mirror of `activeSessionId` in a ref so the pagination helpers can compare
  // against the current active session without going stale inside async
  // callbacks (e.g. fetchMessages.then). Kept in sync via the effect below and
  // updated eagerly in the switch/new-chat handlers.
  const activeSessionIdRef = useRef(activeSessionId)
  useEffect(() => {
    activeSessionIdRef.current = activeSessionId
  }, [activeSessionId])

  // --- Pagination bookkeeping helpers (Requirement 13.4) -------------------
  // Centralize read/write of per-session pagination so tasks 8.3 (scroll
  // observer) and 8.4 (loadOlderMessages) don't duplicate this logic.

  // Read the pagination entry for a session, defaulting to a "no history loaded
  // yet" state when the session hasn't been initialized.
  const getPagination = useCallback(
    (sessionId) =>
      paginationRef.current.get(sessionId) || { hasMore: false, oldestMessageId: null },
    [],
  )

  // Write the pagination entry for a session. When the mutated session is the
  // active one, also update `activeHasMore` so the UI re-renders its
  // "load older"/"no more messages" affordances.
  const setPagination = useCallback((sessionId, { hasMore, oldestMessageId }) => {
    paginationRef.current.set(sessionId, { hasMore, oldestMessageId })
    if (sessionId === activeSessionIdRef.current) {
      setActiveHasMore(hasMore)
    }
  }, [])

  // Per-session unsent input drafts, keyed by session_id -> input text. When
  // switching away from a session we stash the current composer text here, and
  // restore it when the officer returns to that session (Requirement 3.2,
  // Property 8: State Preservation During Session Switch). A ref is used because
  // drafts don't need to trigger re-renders — they're read/written imperatively
  // during the switch handler.
  const draftInputsRef = useRef(new Map())

  const cancelRef = useRef(null)
  const scrollRef = useRef(null)
  const textareaRef = useRef(null)
  // Sentinel element rendered at the very TOP of the message list. Task 8.3
  // attaches an IntersectionObserver to it to auto-trigger loadOlderMessages
  // when the officer scrolls to the top. Declared here so 8.3 can reuse it.
  const topSentinelRef = useRef(null)

  // Cancel any active stream on unmount.
  useEffect(() => {
    return () => {
      if (cancelRef.current) cancelRef.current()
    }
  }, [])

  // Load the officer's sessions (Requirements 13.1, 13.2). Extracted into a
  // reusable callback so the sidebar's Retry action can re-run it (Req 15.4).
  // An expired session (AuthError) triggers logout; other failures are logged
  // (Req 15.5) and surfaced via `sessionsError` for the sidebar to render with
  // a Retry affordance (Req 15.1). On failure we deliberately do NOT clear the
  // existing `sessions` list — the current state is maintained (Req 15.1).
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
          // Maintain current sessions state; surface an error in the sidebar.
          setSessionsError('Failed to load conversations.')
        }
      })
      .finally(() => {
        setIsLoadingSessions(false)
      })
  }, [onLogout])

  // Load the officer's sessions once on mount (Requirements 13.1, 13.2) by
  // delegating to the reusable loadSessions callback above.
  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  // Persist the sidebar collapse state to localStorage whenever it changes
  // (Requirements 8.4, 8.5).
  useEffect(() => {
    if (typeof window === 'undefined' || !window.localStorage) return
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(sidebarCollapsed))
    } catch {
      // Ignore storage write failures (e.g. private mode / quota).
    }
  }, [sidebarCollapsed])

  // Auto-dismiss the session-creation error toast after ~5s (Req 15.3). The
  // officer can also dismiss it manually via the toast's close button. We clear
  // the timer on change/unmount to avoid dismissing a newer toast prematurely.
  useEffect(() => {
    if (!sessionError) return
    const timer = setTimeout(() => setSessionError(null), 5000)
    return () => clearTimeout(timer)
  }, [sessionError])

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

  // Derive a lightweight session title from the first user message, mirroring
  // the backend's simple heuristic (trim to ~60 chars). Used only when injecting
  // a provisional session entry that the backend hasn't created yet (see
  // bumpSessionMetadata). Falls back to "New chat" when the message is empty.
  const deriveTitle = useCallback((firstUserMessage) => {
    const trimmed = (firstUserMessage || '').trim()
    if (!trimmed) return 'New chat'
    if (trimmed.length <= 60) return trimmed
    return trimmed.slice(0, 57) + '…'
  }, [])

  // Optimistic Session_Metadata update (Requirement 13.5). Called when a message
  // turn completes so the sidebar reflects the just-persisted turn without
  // waiting for a backend round-trip / refetch. We deliberately do NOT refetch
  // sessions here — the optimistic values persist until the next natural
  // fetchSessions (e.g. on reload), which reconciles against the backend.
  //
  // Behavior:
  //   - message_count is incremented by 2 per completed turn (one user + one
  //     assistant). We bump at turn completion (onDone) rather than at send time
  //     so counts reflect fully persisted turns.
  //   - updated_at is set to the current ISO timestamp, and the list is re-sorted
  //     by updated_at DESC so the active session bubbles to the top (Req 13.5,
  //     matching the backend's ordering).
  //
  // Edge case: the active session may not be in `sessions` yet. This happens for
  // the very first provisional client-side chat — the initial activeSessionId
  // from newSessionId() that was never created via createSession. In that case
  // we inject a lightweight session entry (title derived from the first user
  // message) so it appears in the sidebar after the first message. This
  // provisional id won't match a backend session_metadata doc, but get_session
  // tolerates missing metadata for legacy sessions, and the next fetchSessions
  // on reload reconciles it.
  const bumpSessionMetadata = useCallback(
    (sessionId, firstUserMessage) => {
      if (!sessionId) return
      const nowIso = new Date().toISOString()
      setSessions((prev) => {
        const idx = prev.findIndex((s) => s.session_id === sessionId)
        let next
        if (idx === -1) {
          // Provisional session not yet in the list — inject a lightweight entry.
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
        // Re-sort newest-first by updated_at so the active session bubbles up.
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
      setStatusText('Sending…')

      // Capture the session this turn belongs to so the optimistic metadata
      // bump in onDone targets the correct session even if the active session
      // changes before the stream completes.
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
          // Optimistically update Session_Metadata for the turn that just
          // completed (Req 13.5): bump message_count, refresh updated_at, and
          // re-sort the sidebar. The captured question seeds the title when the
          // session is a provisional client-side chat not yet in the list.
          bumpSessionMetadata(turnSessionId, question)
          requestAnimationFrame(() => textareaRef.current?.focus())
        },
      })
    },
    [inputValue, isStreaming, activeSessionId, updateLastAssistant, onLogout, bumpSessionMetadata],
  )

  // Load the most recent page of messages for a session (Requirements 4.1,
  // 13.3). Extracted into a reusable callback so the chat-area Retry button can
  // re-attempt the load after a failure (Req 15.4). Initial load: 50 most
  // recent messages, no before_message_id cursor. PAGE_SIZE is passed
  // explicitly so the "50 most recent" contract is self-documenting and shared
  // with loadOlderMessages.
  //
  // On failure: an expired token logs out; other errors are logged (Req 15.5)
  // and surfaced via `messagesError` for the chat-area banner (Req 15.2). We do
  // NOT clear the session list on this error — only the message view is
  // affected (Req 15.2).
  const loadSessionMessages = useCallback(
    (sessionId) => {
      setMessagesError(null)
      setIsLoadingMessages(true)
      return fetchMessages(sessionId, PAGE_SIZE, null)
        .then(({ messages: fetched, has_more }) => {
          // Backend is newest-first; reverse to oldest-first for display.
          const oldestFirst = fetched.slice().reverse()
          const mapped = oldestFirst.map((m) => ({
            id: m.message_id,
            role: m.role,
            content: m.content,
            tableData: null,
            mediaAttachments: null,
            isStreaming: false,
            error: false,
          }))
          setMessages(mapped)

          // The oldest loaded message is the LAST element of the newest-first
          // response (equivalently the first element of oldest-first). Record
          // pagination via the helper, which also syncs activeHasMore when this
          // session is active.
          const oldestLoaded = fetched.length > 0 ? fetched[fetched.length - 1] : null
          setPagination(sessionId, {
            hasMore: has_more,
            oldestMessageId: oldestLoaded ? oldestLoaded.message_id : null,
          })

          // Show newest at the bottom: defer to the next frame so the list has
          // rendered before we scroll (the messages-keyed effect also handles
          // this, but rAF guards against timing races).
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
            // Keep the session list intact; surface an error in the chat area.
            setMessagesError('Failed to load messages.')
          }
        })
        .finally(() => {
          setIsLoadingMessages(false)
        })
    },
    [onLogout, setPagination],
  )

  // Retry handler for the chat-area message-load error (Req 15.4). Re-attempts
  // loading the currently active session's messages.
  const retryLoadMessages = useCallback(() => {
    loadSessionMessages(activeSessionIdRef.current)
  }, [loadSessionMessages])

  // Switch the active session in response to a sidebar selection
  // (Requirements 3.1–3.5, 13.3). Steps, in order:
  //   1. No-op if the session is already active.
  //   2. Cancel any in-flight stream and reset streaming UI flags.
  //   3. Stash the current unsent input under the OLD session, then restore the
  //      draft (if any) for the NEW session (Property 8: state preservation).
  //   4. Clear the message list and switch activeSessionId.
  //   5. Load the most recent page of messages for the new session.
  //
  // Message ordering decision (kept consistent for task 8.x pagination):
  //   The backend returns messages NEWEST-FIRST (descending by timestamp). The
  //   chat view reads top→bottom with the newest message at the bottom, so we
  //   reverse the response into OLDEST-FIRST before storing in `messages`.
  //   Pagination bookkeeping records `oldestMessageId` as the oldest loaded
  //   message — i.e. the LAST element of the newest-first response array.
  const handleSelectSession = useCallback(
    (sessionId) => {
      // (1) Selecting the already-active session is a no-op.
      if (sessionId === activeSessionId) return

      // (2) Cancel any active stream and reset streaming state.
      if (isStreaming) {
        cancelRef.current?.()
        cancelRef.current = null
        setIsStreaming(false)
        setStatusText('')
      }

      // (3) Save the current draft under the OLD session, restore the NEW one.
      draftInputsRef.current.set(activeSessionId, inputValue)
      const restoredDraft = draftInputsRef.current.get(sessionId)
      setInputValue(restoredDraft || '')

      // (4) Switch active session and clear the message list (Requirement 13.3).
      // Update the ref eagerly so the async load below can compare against the
      // correct active session when calling setPagination.
      activeSessionIdRef.current = sessionId
      setActiveSessionId(sessionId)
      setMessages([])
      // Reset the reactive hasMore until the load resolves to avoid showing a
      // stale "load older" affordance from the previous session.
      setActiveHasMore(false)
      // Clear any prior message-load error before the new load (Req 15.2).
      setMessagesError(null)

      // (5) Load the most recent page of messages for the selected session.
      loadSessionMessages(sessionId)
    },
    [activeSessionId, isStreaming, inputValue, loadSessionMessages],
  )

  // Create a brand-new chat session (Requirements 2.1–2.5). Steps, in order:
  //   1. Cancel any in-flight stream and reset streaming UI flags.
  //   2. Ask the backend to create a session (createSession) so it owns the
  //      session_id, title, and timestamps (Req 2.1, 2.2).
  //   3. Prepend the new session to `sessions` so it appears in the sidebar
  //      immediately. The list is ordered newest-first by updated_at, and a
  //      brand-new session has the latest updated_at, so it belongs at the top
  //      (Req 2.4).
  //   4. Make the new session active, clear the message view and composer, and
  //      reset status (Req 2.5).
  //
  // Req 2.3 ("preserve the current Active_Session in Message_History"): messages
  // are persisted server-side as they stream (save_turn), and any session that
  // had messages already exists in `sessions` (loaded from the backend). So
  // "saving the current session" reduces to not losing it from the list — which
  // we don't, since we only prepend. We deliberately avoid synthesizing a
  // placeholder for the previous client-only session: real sessions come from
  // the backend, and adding a fake entry risks an id that doesn't exist
  // server-side.
  //
  // On failure we retain the current Active_Session (Req 15.3): an expired token
  // logs out; any other error is logged and surfaced via a minimal transient
  // `sessionError` (full UI in task 11.2). We do NOT clear messages or switch
  // sessions on the failure path.
  const handleNewChat = useCallback(async () => {
    // (1) Cancel any active stream and reset streaming state.
    if (isStreaming) {
      cancelRef.current?.()
      cancelRef.current = null
      setIsStreaming(false)
      setStatusText('')
    }

    // Clear any stale session error from a previous failed attempt.
    setSessionError(null)

    // (2) Create the session on the backend.
    let newSession
    try {
      newSession = await createSession()
    } catch (err) {
      if (err instanceof AuthError) {
        onLogout()
      } else {
        // Full error UI arrives in task 11.2; log + minimal transient state for
        // now. Retain the current Active_Session (Req 15.3).
        console.error('ChatWindow: failed to create session', err)
        setSessionError('Failed to create a new chat. Please try again.')
      }
      return
    }

    // (3) Surface the new session in the sidebar immediately (newest-first).
    setSessions((prev) => [newSession, ...prev])

    // (4) Make it active and reset the chat view + composer. A brand-new
    // session has no history, so pagination starts empty. setPagination keeps
    // activeHasMore in sync once we mark the session active below.
    activeSessionIdRef.current = newSession.session_id
    setActiveSessionId(newSession.session_id)
    setPagination(newSession.session_id, {
      hasMore: false,
      oldestMessageId: null,
    })
    setMessages([])
    setInputValue('')
    setStatusText('')
  }, [isStreaming, onLogout, setPagination])

  // Load the previous page of OLDER messages for the active session, triggered
  // either by the "Load older messages" button or the scroll observer (task
  // 8.3). Implements bottom-to-top pagination while keeping the viewport
  // anchored to the same content (Requirements 4.3, 4.4, 4.5).
  //
  // Flow, in order:
  //   - Guard against redundant/overlapping loads: bail if there's nothing
  //     older to load (hasMore false / no cursor) or a load is in flight.
  //   - Capture the scroll container's height BEFORE prepending so we can
  //     restore the relative scroll position afterwards.
  //   - Fetch the next page older than oldestMessageId. The response is
  //     newest-first and entirely older than the cursor; reverse to oldest-first
  //     and map into the component message shape before PREPENDING.
  //   - Advance the cursor to the oldest of the freshly fetched page (the LAST
  //     element of the newest-first response); keep the previous cursor if the
  //     page came back empty. Update has_more so the affordances re-render.
  //   - After the DOM paints, restore scrollTop to newHeight - prevHeight so the
  //     content the officer was viewing stays put instead of jumping to the top.
  const loadOlderMessages = useCallback(async () => {
    const sessionId = activeSessionIdRef.current
    const pagination = getPagination(sessionId)

    // Nothing older to load, no cursor to page from, or a load already running.
    if (!pagination.hasMore || isLoadingOlder || !pagination.oldestMessageId) {
      return
    }

    setIsLoadingOlder(true)

    // Capture height before prepend so we can restore the scroll position.
    const prevScrollHeight = scrollRef.current ? scrollRef.current.scrollHeight : 0

    try {
      const { messages: fetched, has_more } = await fetchMessages(
        sessionId,
        PAGE_SIZE,
        pagination.oldestMessageId,
      )

      // Backend is newest-first and all OLDER than the cursor; reverse to
      // oldest-first for display, then map into the component message shape.
      const older = fetched
        .slice()
        .reverse()
        .map((m) => ({
          id: m.message_id,
          role: m.role,
          content: m.content,
          tableData: null,
          mediaAttachments: null,
          isStreaming: false,
          error: false,
        }))

      // Prepend the older messages ahead of the existing ones.
      setMessages((prev) => [...older, ...prev])

      // Advance the cursor to the oldest of this page (last element of the
      // newest-first response). Keep the previous cursor if the page was empty.
      const newOldest =
        fetched.length > 0 ? fetched[fetched.length - 1].message_id : pagination.oldestMessageId
      setPagination(sessionId, { hasMore: has_more, oldestMessageId: newOldest })

      // Restore scroll position AFTER the DOM updates so the viewport stays
      // anchored to the same content rather than jumping to the top (Req 4.4).
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          const newScrollHeight = scrollRef.current.scrollHeight
          scrollRef.current.scrollTop = newScrollHeight - prevScrollHeight
        }
      })
    } catch (err) {
      if (err instanceof AuthError) {
        onLogout()
      } else {
        // Full error UI arrives in task 11.2; log for now.
        console.error('ChatWindow: failed to load older messages', err)
      }
    } finally {
      setIsLoadingOlder(false)
    }
  }, [getPagination, setPagination, isLoadingOlder, onLogout])

  // Scroll-triggered "load older" via IntersectionObserver (Requirements 4.2,
  // 4.3). When the top sentinel scrolls into view inside the chat scroll
  // container, auto-trigger loadOlderMessages so history streams in as the
  // officer scrolls up, complementing the manual "Load older messages" button.
  //
  // Dependencies: we re-create the observer when `messages.length` changes
  // because the sentinel only mounts once the list is non-empty (so it isn't in
  // the DOM on an empty session). Re-running on `activeHasMore`/`isLoadingOlder`
  // re-evaluates the guard as pages are exhausted or a load is in flight. The
  // `loadOlderMessages` callback is stable but listed so the latest closure is
  // observed.
  useEffect(() => {
    // Guard for SSR/test environments without IntersectionObserver.
    if (typeof IntersectionObserver === 'undefined') return
    // The sentinel only renders when there are messages; nothing to observe.
    if (!topSentinelRef.current) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && activeHasMore && !isLoadingOlder) {
          // loadOlderMessages also no-ops internally when there's nothing to
          // load or a load is already running, so this is safe either way.
          loadOlderMessages()
        }
      },
      {
        // Use the chat scroll container as the viewport root, and prefetch a
        // little before the very top is reached.
        root: scrollRef.current,
        rootMargin: '100px 0px 0px 0px',
        threshold: 0.1,
      },
    )

    observer.observe(topSentinelRef.current)

    return () => observer.disconnect()
  }, [loadOlderMessages, activeHasMore, isLoadingOlder, messages.length])

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

  // session_id generation note (Requirements 1.1, 8.3):
  //   The initial `activeSessionId` is generated client-side via newSessionId()
  //   so a brand-new, unsaved chat can stream immediately — the backend's
  //   save_turn persists this provisional id on the first message. New chats
  //   started from the sidebar/topbar "New chat" button use the backend-created
  //   session_id (handleNewChat → createSession), so all explicitly-created
  //   sessions are backed by a server-owned id. We intentionally leave the
  //   provisional client id for the very first fresh chat rather than
  //   auto-selecting an existing session, so the empty state is shown on load.
  return (
    <div className="app-layout">
      <ChatHistorySidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        officer={officer}
        collapsed={sidebarCollapsed}
        isLoading={isLoadingSessions}
        error={sessionsError}
        onRetry={loadSessions}
        onNewChat={handleNewChat}
        onSelectSession={handleSelectSession}
        onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
      />
      <div className="chat-shell">
      <header className="topbar">
        <div className="topbar__brand">
          <span className="topbar__mark" aria-hidden="true">✱</span>
          <div className="topbar__titles">
            <div className="topbar__title">KSP Crime Intelligence</div>
            <div className="topbar__subtitle">
              Session {activeSessionId.slice(0, 8)}
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

      {sessionError ? (
        <div className="toast toast--error" role="alert">
          <span className="toast__message">{sessionError}</span>
          <button
            type="button"
            className="toast__dismiss"
            onClick={() => setSessionError(null)}
            aria-label="Dismiss notification"
          >
            ✕
          </button>
        </div>
      ) : null}

      <main className="chat-scroll" ref={scrollRef}>
        {messagesError ? (
          <div className="chat-error" role="alert">
            <span className="chat-error__message">{messagesError}</span>
            <button
              type="button"
              className="chat-error__retry"
              onClick={retryLoadMessages}
              disabled={isLoadingMessages}
            >
              {isLoadingMessages ? 'Retrying…' : 'Retry'}
            </button>
          </div>
        ) : null}
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
            {/* Top sentinel + load-older affordances (Req 4.5). The sentinel is
                observed by the IntersectionObserver wired up in task 8.3 to
                auto-trigger loadOlderMessages; the button offers a manual
                fallback. */}
            <div ref={topSentinelRef} className="chat-messages__top-sentinel" aria-hidden="true" />
            {activeHasMore ? (
              <button
                type="button"
                className="load-older-btn"
                onClick={loadOlderMessages}
                disabled={isLoadingOlder}
              >
                {isLoadingOlder ? 'Loading…' : 'Load older messages'}
              </button>
            ) : (
              <div className="no-older-indicator">No older messages</div>
            )}
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
    </div>
  )
}
