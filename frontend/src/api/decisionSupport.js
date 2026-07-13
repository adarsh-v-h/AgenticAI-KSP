import { getToken } from './auth'

const BASE = '/api/decision-support'

class AuthError extends Error {}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function get(path) {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (res.status === 401) throw new AuthError('Session expired')
  if (!res.ok) throw new Error(`Decision support request failed: ${res.status}`)
  return res.json()
}

export const fetchCaseTimeline = (caseId) => get(`/timeline/${caseId}`)
export const fetchCaseSummary = (caseId) => get(`/summary/${caseId}`)
export const fetchSimilarCases = (caseId, limit = 5) => get(`/similar-cases/${caseId}?limit=${limit}`)

export { AuthError }
