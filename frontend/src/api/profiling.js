import { getToken } from './auth'

const BASE = '/api/profiling'

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
// takes:  accusedId (number|string) — unique identifier of the accused person
// returns: (Promise<object|null>) — parsed JSON risk score data, or null if not found
// throws:  AuthError — when the session token is expired (401)
//          Error — when the server returns a non-OK response other than 404
export async function fetchRiskScore(accusedId) {
  const res = await fetch(`${BASE}/risk/${accusedId}`, { headers: authHeaders() })
  if (res.status === 401) throw new AuthError('Session expired')
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Risk lookup failed: ${res.status}`)
  return res.json()
}

export { AuthError }
