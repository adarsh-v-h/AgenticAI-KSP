// SSE-style streaming consumer for GET /api/chat/stream.
//
// Browser EventSource cannot set custom headers, so we use fetch with a
// ReadableStream and parse `data: ...` lines manually. The backend also
// accepts the JWT as a `?token=` query param (see auth.simple_auth) so we
// pass the token there in addition to the Authorization header — useful in
// case some proxies strip headers from long-lived streams.

import { getToken } from './auth.js'

/**
 * @param {string} question
 * @param {string} sessionId
 * @param {{
 *   onStatus?: (msg: string) => void,
 *   onToken?:  (chunk: string) => void,
 *   onTable?:  (rows: object[]) => void,
 *   onMedia?:  (refs: object[]) => void,
 *   onSql?:    (sql: string) => void,
 *   onGraphAvailable?: () => void,
 *   onError?:  (msg: string) => void,
 *   onAuthExpired?: () => void,
 *   onDone?:   () => void,
 * }} callbacks
 * @returns {() => void} cancel function
 */
export function startChatStream(question, sessionId, callbacks = {}) {
  const controller = new AbortController()
  const token = getToken()

  const url =
    `/api/chat/stream?` +
    `question=${encodeURIComponent(question)}` +
    `&session_id=${encodeURIComponent(sessionId)}` +
    (token ? `&token=${encodeURIComponent(token)}` : '')

  ;(async () => {
    let response
    try {
      response = await fetch(url, {
        method: 'GET',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal,
      })
    } catch (err) {
      if (controller.signal.aborted) {
        callbacks.onDone?.()
        return
      }
      callbacks.onError?.('Cannot reach the server. Please try again.')
      callbacks.onDone?.()
      return
    }

    if (response.status === 401 || response.status === 403) {
      callbacks.onError?.('Session expired. Please log in again.')
      callbacks.onAuthExpired?.()
      callbacks.onDone?.()
      return
    }

    if (!response.ok || !response.body) {
      callbacks.onError?.(
        `Server returned an unexpected error (HTTP ${response.status}).`,
      )
      callbacks.onDone?.()
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // SSE frames are separated by a blank line ("\n\n").
        let idx
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, idx)
          buffer = buffer.slice(idx + 2)
          handleFrame(frame, callbacks)
        }
      }
      // Drain any trailing partial frame on close.
      if (buffer.trim()) {
        handleFrame(buffer, callbacks)
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        callbacks.onError?.('Connection lost.')
      }
    } finally {
      callbacks.onDone?.()
    }
  })()

  return () => controller.abort()
}

function handleFrame(frame, callbacks) {
  const payload = frame
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('')
  if (!payload) return

  let event
  try {
    event = JSON.parse(payload)
  } catch {
    return
  }

  switch (event.type) {
    case 'status':
      callbacks.onStatus?.(event.content || '')
      break
    case 'token':
      callbacks.onToken?.(event.content || '')
      break
    case 'table':
      callbacks.onTable?.(Array.isArray(event.data) ? event.data : [])
      break
    case 'media':
      callbacks.onMedia?.(
        Array.isArray(event.attachments) ? event.attachments : [],
      )
      break
    case 'sql':
      callbacks.onSql?.(event.content || '')
      break
    case 'graph_available':
      callbacks.onGraphAvailable?.()
      break
    case 'error':
      callbacks.onError?.(event.message || 'An error occurred.')
      break
    case 'done':
      // onDone is fired in the finally block of the consumer loop too — no-op here.
      break
    default:
      break
  }
}

// ---------------------------------------------------------------------------
// Session management API client
//
// These functions back the chat-history sidebar: listing an officer's
// sessions, creating new ones, and loading paginated message history.
//
// All requests carry the JWT via the `Authorization: Bearer` header. The token
// is read through getToken() (auth.js) rather than localStorage directly so we
// stay consistent with how the rest of the app abstracts token storage.
//
// A 401 surfaces as an AuthError so callers can detect an expired session and
// trigger logout. Other failures (404, non-ok status, network errors) throw a
// plain Error with a friendly message after logging details to the console.
// ---------------------------------------------------------------------------

/**
 * Thrown when the backend rejects a request with HTTP 401. Callers can catch
 * this specific type to redirect to login / clear the auth state.
 */
export class AuthError extends Error {
  constructor(message = 'Your session has expired. Please log in again.') {
    super(message)
    this.name = 'AuthError'
  }
}

function authHeaders(extra = {}) {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}`, ...extra } : { ...extra }
}

/**
 * Resolve after `ms` milliseconds. Small Promise wrapper around setTimeout so
 * the backoff loop can `await` between retries.
 *
 * @param {number} ms
 * @returns {Promise<void>}
 */
function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * Run an async fetch with exponential-backoff retry for TRANSIENT failures
 * only.
 *
 * A failure is treated as transient when either:
 *   - `doFetch` throws (e.g. the network is unreachable / fetch rejected), or
 *   - it resolves with a 5xx server response.
 *
 * Non-transient responses (status < 500, which includes 401 and 404) are
 * returned immediately so callers can apply their existing AuthError / 404 /
 * non-ok handling. We never retry these because client errors won't fix
 * themselves on a repeat request.
 *
 * Backoff between attempt `n` (0-indexed) is `baseDelayMs * 2^n`, so with the
 * defaults the added latency is bounded at 300ms + 600ms = 900ms across the
 * two retries.
 *
 * @param {() => Promise<Response>} doFetch async function returning a Response
 * @param {{ retries?: number, baseDelayMs?: number }} [options]
 * @returns {Promise<Response>} the final Response (5xx included once retries
 *   are exhausted)
 * @throws re-throws the last network error if every attempt threw
 */
async function fetchWithRetry(doFetch, { retries = 2, baseDelayMs = 300 } = {}) {
  let lastError
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const response = await doFetch()
      // Only 5xx is transient; everything else (2xx, 3xx, 4xx incl. 401/404)
      // is returned for the caller to handle.
      if (response.status < 500) {
        return response
      }
      // Out of retries — surface the 5xx response as-is.
      if (attempt === retries) {
        return response
      }
    } catch (err) {
      lastError = err
      // Out of retries — propagate the network error to the caller.
      if (attempt === retries) {
        throw err
      }
    }
    await delay(baseDelayMs * 2 ** attempt)
  }
  // Unreachable in practice (loop always returns/throws on the last attempt),
  // but keep a defensive fallback.
  throw lastError ?? new Error('Request failed after retries.')
}

/**
 * Fetch all chat sessions for the authenticated officer.
 *
 * GET /api/chat/sessions
 *
 * @returns {Promise<Array<object>>} array of session metadata objects
 *   ({session_id, title, created_at, updated_at, message_count})
 * @throws {AuthError} on 401
 * @throws {Error} on other non-ok responses or network failure
 */
export async function fetchSessions() {
  let response
  try {
    response = await fetchWithRetry(() =>
      fetch('/api/chat/sessions', {
        method: 'GET',
        headers: authHeaders(),
      }),
    )
  } catch (err) {
    console.error('fetchSessions: network error', err)
    throw new Error('Cannot reach the server. Please try again.')
  }

  if (response.status === 401) {
    throw new AuthError()
  }
  if (!response.ok) {
    console.error(`fetchSessions: unexpected status ${response.status}`)
    throw new Error(`Failed to load sessions (HTTP ${response.status}).`)
  }

  try {
    const data = await response.json()
    return Array.isArray(data?.sessions) ? data.sessions : []
  } catch (err) {
    console.error('fetchSessions: failed to parse response', err)
    throw new Error('Received an invalid response from the server.')
  }
}


/**
 * Fetch all messages for a session.
 *
 * GET /api/chat/sessions/{sessionId}/messages
 *
 * The backend returns the full message list oldest-first.
 *
 * @param {string} sessionId
 * @returns {Promise<{messages: Array<object>}>}
 * @throws {AuthError} on 401
 * @throws {Error} on 404 (session not found), other non-ok, or network failure
 */
export async function fetchMessages(sessionId) {
  const url = `/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`

  let response
  try {
    response = await fetchWithRetry(() =>
      fetch(url, {
        method: 'GET',
        headers: authHeaders(),
      }),
    )
  } catch (err) {
    console.error('fetchMessages: network error', err)
    throw new Error('Cannot reach the server. Please try again.')
  }

  if (response.status === 401) {
    throw new AuthError()
  }
  if (response.status === 404) {
    console.error(`fetchMessages: session not found (${sessionId})`)
    throw new Error('Session not found.')
  }
  if (!response.ok) {
    console.error(`fetchMessages: unexpected status ${response.status}`)
    throw new Error(`Failed to load messages (HTTP ${response.status}).`)
  }

  try {
    const data = await response.json()
    return {
      messages: Array.isArray(data?.messages) ? data.messages : [],
    }
  } catch (err) {
    console.error('fetchMessages: failed to parse response', err)
    throw new Error('Received an invalid response from the server.')
  }
}

/**
 * Export a chat session as a downloadable PDF (or HTML fallback).
 *
 * POST /api/chat/sessions/{sessionId}/export
 *
 * Fetches the export blob from the backend and triggers a browser download.
 * The filename is taken from the Content-Disposition header when present,
 * falling back to a sensible default.
 *
 * @param {string} sessionId
 * @returns {Promise<void>}
 * @throws {AuthError} on 401
 * @throws {Error} on other non-ok responses or network failure
 */
export async function exportSession(sessionId) {
  let response
  try {
    response = await fetch(
      `/api/chat/sessions/${encodeURIComponent(sessionId)}/export`,
      {
        method: 'POST',
        headers: authHeaders(),
      },
    )
  } catch (err) {
    console.error('exportSession: network error', err)
    throw new Error('Cannot reach the server. Please try again.')
  }

  if (response.status === 401) {
    throw new AuthError()
  }
  if (!response.ok) {
    console.error(`exportSession: unexpected status ${response.status}`)
    throw new Error(`Export failed (HTTP ${response.status}).`)
  }

  let blob
  try {
    blob = await response.blob()
  } catch (err) {
    console.error('exportSession: failed to read blob', err)
    throw new Error('Received an invalid response from the server.')
  }

  const contentDisposition = response.headers.get('Content-Disposition')
  const filename =
    contentDisposition?.match(/filename="(.+)"/)?.[1] ?? 'KSP-Export.pdf'

  // Trigger a browser download.
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

