import { useAuth } from './hooks/useAuth.js'
import LoginPage from './components/LoginPage.jsx'
import ChatWindow from './components/ChatWindow.jsx'

export default function App() {
  const { isAuthenticated, officer, isLoading, error, login, logout } = useAuth()

  if (!isAuthenticated) {
    return <LoginPage onLogin={login} isLoading={isLoading} error={error} />
  }
  return <ChatWindow officer={officer} onLogout={logout} />
}
