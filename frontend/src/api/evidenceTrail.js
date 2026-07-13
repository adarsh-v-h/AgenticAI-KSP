import { getToken } from './auth'

class AuthError extends Error {}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function fetchEvidenceTrail(messageId) {
  const res = await fetch(`/api/chat/messages/${messageId}/evidence-trail`, { headers: authHeaders() })
  if (res.status === 401) throw new AuthError('Session expired')
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Evidence trail request failed: ${res.status}`)
  return res.json()
}

export { AuthError }
