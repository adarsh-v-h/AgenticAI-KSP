import { getToken } from './auth'
import { API_BASE } from '../config.js'

const BASE = `${API_BASE}/api/decision-support`

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
// takes:  path (string) — API sub-path to append to the decision-support base URL
// returns: (Promise<object>) — parsed JSON response body
// throws:  AuthError — when the session token is expired (401)
//          Error — when the server returns a non-OK response
async function get(path) {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (res.status === 401) throw new AuthError('Session expired')
  if (!res.ok) throw new Error(`Decision support request failed: ${res.status}`)
  return res.json()
}

// CONTRACT
// takes:  caseId (number|string) — unique identifier of the case
// returns: (Promise<object>) — parsed JSON timeline data for the case
// throws:  AuthError — when the session token is expired (401)
//          Error — when the server returns a non-OK response
export const fetchCaseTimeline = (caseId) => get(`/timeline/${caseId}`)

// CONTRACT
// takes:  caseId (number|string) — unique identifier of the case
// returns: (Promise<object>) — parsed JSON summary data for the case
// throws:  AuthError — when the session token is expired (401)
//          Error — when the server returns a non-OK response
export const fetchCaseSummary = (caseId) => get(`/summary/${caseId}`)

// CONTRACT
// takes:  caseId (number|string) — unique identifier of the case
//         limit (number) — max number of similar cases to return (default 5)
// returns: (Promise<object>) — parsed JSON list of similar cases
// throws:  AuthError — when the session token is expired (401)
//          Error — when the server returns a non-OK response
export const fetchSimilarCases = (caseId, limit = 5) => get(`/similar-cases/${caseId}?limit=${limit}`)

export { AuthError }
