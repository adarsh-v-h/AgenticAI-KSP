import { getToken } from './auth'

const BASE = '/api/profiling'

class AuthError extends Error {}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function fetchRiskScore(accusedId) {
  const res = await fetch(`${BASE}/risk/${accusedId}`, { headers: authHeaders() })
  if (res.status === 401) throw new AuthError('Session expired')
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Risk lookup failed: ${res.status}`)
  return res.json()
}

export { AuthError }
