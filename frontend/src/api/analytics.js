import { getToken } from './auth'
import { AuthError } from './chat'

const BASE = '/api/analytics'

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function get(path) {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (res.status === 401) throw new AuthError('Session expired')
  if (!res.ok) throw new Error(`Analytics request failed: ${res.status}`)
  return res.json()
}

// Note: Response keys match existing backend API (report.md Priority 2 decision)
// - monthly/crime-type/stations all return {"trend": [...]}
// - station breakdown returns {"unit_id": N, "breakdown": [...]}
// - status/clusters/seasonal use their own keys
export const fetchMonthlyTrend = (monthsBack = 12) => get(`/trends/monthly?months_back=${monthsBack}`)
export const fetchCrimeTypeTrend = () => get('/trends/crime-type')
export const fetchStationTrend = (limit = 10) => get(`/trends/stations?limit=${limit}`)
export const fetchStationBreakdown = (unitId) => get(`/trends/station/${unitId}/breakdown`)
export const fetchStatusBreakdown = () => get('/status-breakdown')
export const fetchMoClusters = (minOccurrences = 2) => get(`/mo-clusters?min_occurrences=${minOccurrences}`)
export const fetchSeasonalPattern = () => get('/seasonal')
