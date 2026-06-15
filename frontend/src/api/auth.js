// Auth API. Token lives in memory only — never localStorage / sessionStorage.

let _token = null
let _officer = null

export function getToken() {
  return _token
}

export function getOfficer() {
  return _officer
}

export function setToken(token, officer) {
  _token = token || null
  _officer = officer || null
}

export function clearToken() {
  _token = null
  _officer = null
}

export function isLoggedIn() {
  return _token !== null
}

/**
 * POST /api/auth/login
 * Returns { success: boolean, message?: string, officer?: object }.
 * Never throws.
 */
export async function login(badgeNumber, password) {
  try {
    const response = await fetch('/api/auth/login', {
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

/**
 * POST /api/auth/logout — best effort. Always clears local state.
 */
export async function logout() {
  const token = _token
  clearToken()
  if (!token) return
  try {
    await fetch('/api/auth/logout', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
  } catch (err) {
    // Stateless logout — server doesn't actually need to know.
  }
}
