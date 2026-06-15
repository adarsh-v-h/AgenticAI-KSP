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
      if (controller.signal.aborted) return
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
  // A frame can contain multiple `data:` lines — concat them per the SSE spec.
  const lines = frame.split('\n')
  let payload = ''
  for (const line of lines) {
    if (line.startsWith('data:')) {
      payload += line.slice(5).trimStart()
    }
  }
  if (!payload) return

  let event
  try {
    event = JSON.parse(payload)
  } catch (err) {
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
