// Intelligence Ticker API
// Fetches the pre-computed station briefing sentence from the backend,
// caching it in localStorage for 5 minutes (same TTL as analytics).

import { getToken } from './auth'
import { AuthError } from './chat'
import { API_BASE } from '../config.js'

const TICKER_TTL_MS = 5 * 60 * 1000 // 5 minutes

function _tickerKey(officerId) {
  return `ksp_ticker_${officerId}`
}

// CONTRACT
// takes:  officer (object) — authenticated officer with officer_id, role, unit_id
// returns: (Promise<string|null>) — ticker sentence, or null if unavailable
// throws:  never
export async function fetchTicker(officer) {
  if (!officer?.officer_id) return null

  // 1. Check localStorage cache first (5-min TTL)
  if (typeof window !== 'undefined') {
    try {
      const cached = localStorage.getItem(_tickerKey(officer.officer_id))
      if (cached) {
        const { text, timestamp } = JSON.parse(cached)
        if (Date.now() - timestamp < TICKER_TTL_MS) {
          return text
        }
      }
    } catch {
      // ignore parse errors — treat as cache miss
    }
  }

  // 2. Fetch from backend
  try {
    const token = getToken()
    if (!token) return null

    const res = await fetch(`${API_BASE}/api/ticker`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (res.status === 401) throw new AuthError('Session expired')
    if (!res.ok) return null

    const data = await res.json()
    const text = data?.text ?? null

    // 3. Write to localStorage
    if (typeof window !== 'undefined' && text) {
      try {
        localStorage.setItem(
          _tickerKey(officer.officer_id),
          JSON.stringify({ text, timestamp: Date.now() })
        )
      } catch {
        // ignore quota errors
      }
    }

    return text
  } catch (err) {
    if (err instanceof AuthError) throw err
    return null
  }
}

// CONTRACT
// takes:  officerId (number|string) — the officer's ID
// returns: nothing
// throws:  never
export function clearTickerCache(officerId) {
  if (typeof window === 'undefined' || !officerId) return
  try {
    localStorage.removeItem(_tickerKey(officerId))
  } catch {
    // ignore
  }
}
