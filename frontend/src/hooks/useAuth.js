import { useCallback, useState } from 'react'
import {
  login as apiLogin,
  logout as apiLogout,
  isLoggedIn,
  getOfficer,
} from '../api/auth.js'

export function useAuth() {
  const [isAuthenticated, setIsAuthenticated] = useState(isLoggedIn())
  const [officer, setOfficer] = useState(getOfficer())
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  const login = useCallback(async (badgeNumber, password) => {
    setError(null)
    setIsLoading(true)
    try {
      const result = await apiLogin(badgeNumber, password)
      if (result.success) {
        setIsAuthenticated(true)
        setOfficer(result.officer || null)
        return true
      }
      setError(result.message || 'Login failed.')
      return false
    } finally {
      setIsLoading(false)
    }
  }, [])

  const logout = useCallback(async () => {
    await apiLogout()
    setIsAuthenticated(false)
    setOfficer(null)
    setError(null)
  }, [])

  return { isAuthenticated, officer, isLoading, error, login, logout }
}
