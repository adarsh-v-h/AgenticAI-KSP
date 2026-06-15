import { useState } from 'react'

export default function LoginPage({ onLogin, isLoading, error }) {
  const [badgeNumber, setBadgeNumber] = useState('')
  const [password, setPassword] = useState('')

  const canSubmit =
    badgeNumber.trim().length > 0 && password.length > 0 && !isLoading

  async function handleSubmit(e) {
    e.preventDefault()
    if (!canSubmit) return
    await onLogin(badgeNumber.trim(), password)
  }

  return (
    <div className="login-shell">
      <form className="login-card" onSubmit={handleSubmit} noValidate>
        <div className="login-brand">
          <span className="login-brand__mark" aria-hidden="true">
            ✱
          </span>
          <span className="login-brand__name">Karnataka State Police</span>
        </div>

        <h1 className="login-title">Crime Intelligence Platform</h1>
        <p className="login-subtitle">
          Authorized personnel only. Sign in with your station credentials.
        </p>

        <label className="field">
          <span className="field__label">Badge number</span>
          <input
            type="text"
            value={badgeNumber}
            onChange={(e) => setBadgeNumber(e.target.value)}
            autoComplete="username"
            placeholder="KSP-2019-0042"
            spellCheck="false"
            disabled={isLoading}
          />
        </label>

        <label className="field">
          <span className="field__label">Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            disabled={isLoading}
          />
        </label>

        <button
          type="submit"
          className="btn btn--primary btn--block"
          disabled={!canSubmit}
        >
          {isLoading ? 'Authenticating…' : 'Sign in'}
        </button>

        {error ? <p className="login-error" role="alert">{error}</p> : null}
      </form>
    </div>
  )
}
