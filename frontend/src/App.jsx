import React, { useState, useEffect } from 'react'
import { useAuth } from './hooks/useAuth.js'
import LandingPage from './components/LandingPage.jsx'
import LoginPage from './components/LoginPage.jsx'
import PortalShell from './components/PortalShell.jsx'
import ChatWindow from './components/ChatWindow.jsx'

export default function App() {
  const { isAuthenticated, officer, isLoading, error, login, logout } = useAuth()
  const [showLogin, setShowLogin] = useState(false)

  // Reset showLogin to false whenever user becomes unauthenticated (e.g. after logout)
  useEffect(() => {
    if (!isAuthenticated) {
      setShowLogin(false)
    }
  }, [isAuthenticated])

  // Already authenticated -> go straight to chat
  if (isAuthenticated) {
    return <ChatWindow officer={officer} onLogout={logout} />
  }

  // Not authenticated -> show landing or login inside the portal shell
  return (
    <PortalShell
      showHomeLink={showLogin}
      onHome={() => setShowLogin(false)}
    >
      {showLogin ? (
        <LoginPage onLogin={login} isLoading={isLoading} error={error} />
      ) : (
        <LandingPage onEnter={() => setShowLogin(true)} />
      )}
    </PortalShell>
  )
}
