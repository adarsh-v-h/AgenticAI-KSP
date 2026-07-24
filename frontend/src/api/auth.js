// Auth API. Token is persisted in localStorage to survive page refreshes.

import { API_BASE } from '../config.js'

let _token = typeof window !== 'undefined' ? localStorage.getItem('ksp_auth_token') : null
let _officer = null

if (typeof window !== 'undefined') {
  try {
    const raw = localStorage.getItem('ksp_officer_profile')
    if (raw) {
      _officer = JSON.parse(raw)
    }
  } catch (e) {
    // ignore parsing errors
  }
}

// CONTRACT
// takes:  nothing
// returns: (string|null) — the current JWT access token
// throws:  never
export function getToken() {
  return _token
}

// CONTRACT
// takes:  nothing
// returns: (object|null) — the authenticated officer's profile object
// throws:  never
export function getOfficer() {
  return _officer
}

// CONTRACT
// takes:  token (string|null) — JWT access token to store, officer (object|null) — officer profile to store
// returns: nothing
// throws:  never
export function setToken(token, officer) {
  _token = token || null
  _officer = officer || null
  if (typeof window !== 'undefined') {
    if (_token) {
      localStorage.setItem('ksp_auth_token', _token)
    } else {
      localStorage.removeItem('ksp_auth_token')
    }
    if (_officer) {
      localStorage.setItem('ksp_officer_profile', JSON.stringify(_officer))
    } else {
      localStorage.removeItem('ksp_officer_profile')
    }
  }
}

// CONTRACT
// takes:  nothing
// returns: nothing
// throws:  never
export function clearToken() {
  _token = null
  _officer = null
  if (typeof window !== 'undefined') {
    localStorage.removeItem('ksp_auth_token')
    localStorage.removeItem('ksp_officer_profile')
    // Clear cached analytics data on logout
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i)
      if (key && key.startsWith('ksp_analytics_cache_')) {
        localStorage.removeItem(key)
      }
    }
  }
}

// CONTRACT
// takes:  nothing
// returns: (boolean) — true if a token is currently held
// throws:  never
export function isLoggedIn() {
  return _token !== null
}

// CONTRACT
// takes:  badgeNumber (string) — officer's badge ID, password (string) — plaintext password
// returns: (Promise<{success: boolean, message?: string, officer?: object}>) — login result
// throws:  never
/**
 * POST /api/auth/login
 * Returns { success: boolean, message?: string, officer?: object }.
 * Never throws.
 */
export async function login(badgeNumber, password) {
  try {
    const response = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        badge_number: badgeNumber,
        password,
      }),
    })

    if (response.status === 401) {
      return { success: false, message: 'Invalid badge number or password.' }
    }
    if (!response.ok) {
      return { success: false, message: 'Login failed. Please try again.' }
    }

    const data = await response.json()
    if (!data?.access_token) {
      return { success: false, message: 'Login failed. Please try again.' }
    }

    setToken(data.access_token, data.officer || null)
    return { success: true, officer: data.officer || null }
  } catch (err) {
    return {
      success: false,
      message: 'Cannot reach the server. Please try again.',
    }
  }
}

// CONTRACT
// takes:  nothing
// returns: (Promise<void>) — resolves after local state is cleared and server notified best-effort
// throws:  never
/**
 * POST /api/auth/logout — best effort. Always clears local state.
 */
export async function logout() {
  const token = _token
  clearToken()
  if (!token) return
  try {
    await fetch(`${API_BASE}/api/auth/logout`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
  } catch (err) {
    // Stateless logout — server doesn't actually need to know.
  }
}
