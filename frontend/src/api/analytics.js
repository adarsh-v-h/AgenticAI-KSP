import { getToken } from './auth'
import { AuthError } from './chat'
import { API_BASE } from '../config.js'

const BASE = `${API_BASE}/api/analytics`

// CONTRACT
// takes:  nothing
// returns: (object) — headers object with Authorization bearer token if available
// raises:  never
function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// CONTRACT
// takes:  path (string) — relative API path to fetch from
// returns: (Promise<object>) — parsed JSON response from the analytics endpoint
// raises:  AuthError — when session has expired (401), Error — when request fails
async function get(path) {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (res.status === 401) throw new AuthError('Session expired')
  if (!res.ok) throw new Error(`Analytics request failed: ${res.status}`)
  return res.json()
}

// Note: Response keys match existing backend API
// - monthly/crime-type/stations all return {"trend": [...]}
// - station breakdown returns {"unit_id": N, "breakdown": [...]}
// - status/clusters/seasonal use their own keys

// CONTRACT
// takes:  monthsBack (number) — number of months to look back (default 12)
// returns: (Promise<object>) — {"trend": array} with monthly crime counts
// raises:  AuthError — when session expired, Error — when request fails
export const fetchMonthlyTrend = (monthsBack = 12) => get(`/trends/monthly?months_back=${monthsBack}`)

// CONTRACT
// takes:  nothing
// returns: (Promise<object>) — {"trend": array} with crime type counts
// raises:  AuthError — when session expired, Error — when request fails
export const fetchCrimeTypeTrend = () => get('/trends/crime-type')

// CONTRACT
// takes:  limit (number) — maximum number of stations to return (default 10)
// returns: (Promise<object>) — {"trend": array} with station case counts
// raises:  AuthError — when session expired, Error — when request fails
export const fetchStationTrend = (limit = 10) => get(`/trends/stations?limit=${limit}`)

// CONTRACT
// takes:  unitId (number) — police station UnitID to drill into
// returns: (Promise<object>) — {"unit_id": number, "breakdown": array} with crime types for that station
// raises:  AuthError — when session expired, Error — when request fails
export const fetchStationBreakdown = (unitId) => get(`/trends/station/${unitId}/breakdown`)

// CONTRACT
// takes:  nothing
// returns: (Promise<object>) — {"breakdown": array} with case status counts
// raises:  AuthError — when session expired, Error — when request fails
export const fetchStatusBreakdown = () => get('/status-breakdown')

// CONTRACT
// takes:  minOccurrences (number) — minimum cluster size threshold (default 2)
// returns: (Promise<object>) — {"clusters": array} with repeated crime-type/station patterns
// raises:  AuthError — when session expired, Error — when request fails
export const fetchMoClusters = (minOccurrences = 2) => get(`/mo-clusters?min_occurrences=${minOccurrences}`)

// CONTRACT
// takes:  nothing
// returns: (Promise<object>) — {"pattern": array} with monthly seasonal crime counts
// raises:  AuthError — when session expired, Error — when request fails
export const fetchSeasonalPattern = () => get('/seasonal')


// ─── Sociological / Demographic endpoints ───────────────────────────────────

export const fetchAccusedAgeDistribution = () => get('/demographics/accused-age')
export const fetchCrimeByGender = () => get('/demographics/crime-by-gender')

// CONTRACT
// takes:  nothing
// returns: (Promise<object>) — {"data": array} with victim demographics by crime type, age group, and gender
// raises:  AuthError — when session expired, Error — when request fails
export const fetchVictimProfile = () => get('/demographics/victim-profile')

export const fetchCrimeByOccupation = (limit = 10) => get(`/demographics/crime-by-occupation?limit=${limit}`)

// CONTRACT
// takes:  nothing
// returns: (Promise<object>) — {"data": array} with crime type × age group × gender for accused
// raises:  AuthError — when session expired, Error — when request fails
export const fetchDemographicRiskProfile = () => get('/demographics/risk-profile')

// ─── Crime Forecasting / Early Warning ──────────────────────────────────────

export const fetchForecastingSummary = () => get('/forecasting/summary')
