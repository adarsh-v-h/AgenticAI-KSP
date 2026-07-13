import { getToken } from './auth'

class AuthError extends Error {}

// CONTRACT
// takes:  nothing
// returns: (object) — headers object with Authorization bearer token if available, empty object otherwise
// throws:  never
function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// CONTRACT
// takes:  messageId (string|number) — unique identifier of the chat message
// returns: (Promise<object|null>) — parsed JSON evidence trail, or null if not found
// throws:  AuthError — when the session token is expired (401)
//          Error — when the server returns a non-OK response other than 404
export async function fetchEvidenceTrail(messageId) {
  const res = await fetch(`/api/chat/messages/${messageId}/evidence-trail`, { headers: authHeaders() })
  if (res.status === 401) throw new AuthError('Session expired')
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Evidence trail request failed: ${res.status}`)
  return res.json()
}

export { AuthError }
