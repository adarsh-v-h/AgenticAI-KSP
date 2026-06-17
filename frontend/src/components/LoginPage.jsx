import React, { useState } from 'react';
import { useLang } from '../hooks/useLang';

export default function LoginPage({ onLogin, isLoading, error }) {
  const { t } = useLang();
  const [badgeNumber, setBadgeNumber] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);

  const canSubmit = badgeNumber.trim().length > 0 && password.length > 0 && !isLoading;

  async function handleSubmit(e) {
    e.preventDefault();
    if (!canSubmit) return;
    await onLogin(badgeNumber.trim(), password);
  }

  return (
    <div id="login-panel" style={{ display: 'block', opacity: 1, transform: 'translateY(0)' }}>
      <form onSubmit={handleSubmit} noValidate>
        <section className="login-card">
          <h2>{t('Authorized Sign In', 'ಅಧಿಕೃತ ಸೈನ್ ಇನ್')}</h2>
          
          <div className="form-group">
            <label className="form-label">{t('Badge number', 'ಬ್ಯಾಡ್ಜ್ ಸಂಖ್ಯೆ')}</label>
            <input
              className="form-input"
              type="text"
              placeholder="KSP-YYYY-NNNN"
              value={badgeNumber}
              onChange={(e) => setBadgeNumber(e.target.value)}
              disabled={isLoading}
              autoComplete="username"
              spellCheck="false"
            />
          </div>

          <div className="form-group">
            <label className="form-label">{t('Password', 'ಗುಪ್ತಪದ')}</label>
            <div className="password-wrap">
              <input
                className="form-input"
                type={showPw ? 'text' : 'password'}
                placeholder={t('Enter your password', 'ನಿಮ್ಮ ಗುಪ್ತಪದವನ್ನು ನಮೂದಿಸಿ')}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isLoading}
                autoComplete="current-password"
              />
              <button
                type="button"
                className="eye-btn"
                onClick={() => setShowPw(!showPw)}
                aria-label="Toggle password"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              </button>
            </div>
          </div>

          <button
            type="submit"
            className="sign-in-btn"
            disabled={!canSubmit}
          >
            {t(isLoading ? 'Authenticating…' : 'Sign in', isLoading ? 'ದೃಢೀಕರಿಸಲಾಗುತ್ತಿದೆ…' : 'ಸೈನ್ ಇನ್')}
          </button>

          {error && (
            <p className="login-error" role="alert" style={{ marginTop: '12px', textAlign: 'center', color: '#c64545', fontSize: '0.875rem' }}>
              {error}
            </p>
          )}

          <div className="system-notice">
            <p>
              <span>
                {t(
                  'This system is for authorized KSP personnel only. Unauthorized access is a punishable offence under the ',
                  'ಈ ವ್ಯವಸ್ಥೆಯು ಅಧಿಕೃತ ಕೆ.ಎಸ್.ಪಿ ಸಿಬ್ಬಂದಿಗೆ ಮಾತ್ರ ಸೀಮಿತವಾಗಿದೆ. ಅನಧಿಕೃತ ಪ್ರವೇಶವು '
                )}
              </span>
              <a href="#" onClick={(e) => e.preventDefault()}>
                {t('Information Technology Act, 2000', 'ಮಾಹಿತಿ ತಂತ್ರಜ್ಞಾನ ಕಾಯ್ದೆ, ೨೦೦೦')}
              </a>
              <span>
                {t(
                  ' and Karnataka Police Act. All sessions are monitored and logged.',
                  ' ಮತ್ತು ಕರ್ನಾಟಕ ಪೊಲೀಸ್ ಕಾಯ್ದೆಯಡಿ ಶಿಕ್ಷಾರ್ಹ ಅಪರಾಧವಾಗಿದೆ. ಎಲ್ಲಾ ಸೆಷನ್‌ಗಳನ್ನು ಮೇಲ್ವಿಚಾರಣೆ ಮಾಡಲಾಗುತ್ತದೆ ಮತ್ತು ರೆಕಾರ್ಡ್ ಮಾಡಲಾಗುತ್ತದೆ.'
                )}
              </span>
            </p>
          </div>
        </section>
      </form>
    </div>
  );
}
