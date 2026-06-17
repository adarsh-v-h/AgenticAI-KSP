import React, { useState } from 'react';
import { useLang } from '../hooks/useLang';

export default function PortalShell({ children, showHomeLink, onHome }) {
  const { lang, setLang, t } = useLang();
  const [logo1Error, setLogo1Error] = useState(false);
  const [logo2Error, setLogo2Error] = useState(false);

  function setFontSize(size) {
    const map = { large: '18px', normal: '16px', small: '14px' };
    document.documentElement.style.setProperty('--font-size-base', map[size] || '16px');
  }

  return (
    <div className="ksp-portal-root">
      {/* Top bar */}
      <div className="topbar">
        <div className="topbar-left">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#6c6a64" strokeWidth="1.5" strokeLinecap="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
          <span>
            {t(
              'Government of Karnataka \u00a0·\u00a0 Home Department \u00a0·\u00a0 Karnataka State Police',
              'ಕರ್ನಾಟಕ ಸರ್ಕಾರ \u00a0·\u00a0 ಗೃಹ ಇಲಾಖೆ \u00a0·\u00a0 ಕರ್ನಾಟಕ ರಾಜ್ಯ ಪೊಲೀಸ್'
            )}
          </span>
        </div>
        <div className="topbar-right">
          <a onClick={() => setFontSize('large')} aria-label="Increase Font Size">A+</a>
          <span style={{ color: 'var(--border-color)' }}>|</span>
          <a onClick={() => setFontSize('normal')} aria-label="Reset Font Size">A</a>
          <span style={{ color: 'var(--border-color)' }}>|</span>
          <a onClick={() => setFontSize('small')} aria-label="Decrease Font Size">A-</a>
        </div>
      </div>

      {/* Header Banner */}
      <header className="header-banner">
        <div className="header-left">
          <div className="header-emblem-circle">
            {logo1Error ? (
              <svg width={36} height={36} viewBox="0 0 36 36">
                <text x={18} y={22} textAnchor="middle" fontSize="9" fill="#cc785c" fontFamily="Inter">KA</text>
              </svg>
            ) : (
              <img src="logo.jpeg" alt="Seal of Karnataka" onError={() => setLogo1Error(true)} />
            )}
          </div>
          <div className="header-title-group">
            <h1>{t('Karnataka State Police', 'ಕರ್ನಾಟಕ ರಾಜ್ಯ ಪೊಲೀಸ್')}</h1>
            <p>{t('Secure Internal Portal \u00a0·\u00a0 Government of Karnataka', 'ಸುರಕ್ಷಿತ ಆಂತರಿಕ ಪೋರ್ಟಲ್ \u00a0·\u00a0 ಕರ್ನಾಟಕ ಸರ್ಕಾರ')}</p>
          </div>
        </div>
        <div className="header-right">
          <div className="lang-selector-container">
            {showHomeLink && (
              <>
                <a href="#" onClick={(e) => { e.preventDefault(); onHome(); }} id="header-home-link" className="header-link-right">
                  {t('Portal Home', 'ಪೋರ್ಟಲ್ ಮುಖಪುಟ')}
                </a>
                <span style={{ opacity: 0.5, color: 'var(--white)' }}>|</span>
              </>
            )}
            <span>{t('Select Language:', 'ಭಾಷೆ ಆಯ್ಕೆಮಾಡಿ:')}</span>
            <label htmlFor="lang-select" style={{ display: 'none' }}>Select Language</label>
            <select id="lang-select" className="lang-select" value={lang} onChange={(e) => setLang(e.target.value)}>
              <option value="en">English</option>
              <option value="kn">ಕನ್ನಡ</option>
            </select>
          </div>
          <div className="right-emblems">
            <div className="right-emblem-circle" title="Government of Karnataka">
              {logo2Error ? (
                <svg width={28} height={28} viewBox="0 0 36 36">
                  <text x={18} y={22} textAnchor="middle" fontSize="9" fill="#cc785c" fontFamily="Inter">KA</text>
                </svg>
              ) : (
                <img src="logo.jpeg" alt="Seal of Karnataka" onError={() => setLogo2Error(true)} />
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main Content Container */}
      <main className="main-container">
        {children}
      </main>

      {/* Footer */}
      <footer className="footer">
        <span className="footer-left">
          {t('© 2026 Karnataka State Police, Government of Karnataka', '© ೨೦೨೬ ಕರ್ನಾಟಕ ರಾಜ್ಯ ಪೊಲೀಸ್, ಕರ್ನಾಟಕ ಸರ್ಕಾರ')}
        </span>
        <span className="footer-right">
          {t(
            'Zoho Dataathon 2026 \u00a0·\u00a0 Powered by Catalyst QuickML',
            'ಜೋಹೋ ಡೇಟಾಥಾನ್ ೨೦೨೬ \u00a0·\u00a0 ಕ್ಯಾಟಲಿಸ್ಟ್ ಕ್ವಿಕ್-ಎಮ್ಎಲ್ ಮೂಲಕ ಚಾಲಿತವಾಗಿದೆ'
          )}
        </span>
      </footer>
    </div>
  );
}
