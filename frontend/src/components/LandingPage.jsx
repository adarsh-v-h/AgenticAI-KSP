import React from 'react';
import { useLang } from '../hooks/useLang';

export default function LandingPage({ onEnter }) {
  const { t } = useLang();

  return (
    <div id="landing-panel">
      <div className="landing-grid">
        {/* Left Side Info */}
        <div className="landing-info">
          <span className="welcome-tag">{t('WELCOME', 'ಸ್ವಾಗತ')}</span>
          <h2 className="landing-hero-title">{t('Karnataka State Police', 'ಕರ್ನಾಟಕ ರಾಜ್ಯ ಪೊಲೀಸ್')}</h2>
          <p className="landing-hero-subtitle">{t('SECURE INTERNAL PORTAL', 'ಸುರಕ್ಷಿತ ಆಂತರಿಕ ಪೋರ್ಟಲ್')}</p>
          <div className="hero-divider"></div>
          
          <p className="landing-description">
            {t(
              'A secure and integrated platform for Karnataka State Police personnel to access critical systems and manage operations efficiently.',
              'ಕರ್ನಾಟಕ ರಾಜ್ಯ ಪೊಲೀಸ್ ಸಿಬ್ಬಂದಿಗೆ ನಿರ್ಣಾಯಕ ವ್ಯವಸ್ಥೆಗಳನ್ನು ಪ್ರವೇಶಿಸಲು ಮತ್ತು ಕಾರ್ಯಾಚರಣೆಗಳನ್ನು ಸಮರ್ಥವಾಗಿ ನಿರ್ವಹಿಸಲು ಒಂದು ಸುರಕ್ಷಿತ ಮತ್ತು ಸಂಯೋಜಿತ ವೇದಿಕೆ.'
            )}
          </p>

          {/* 4 Features Grid */}
          <div className="features-grid">
            <div className="feature-item">
              <div className="feature-icon">
                {/* Shield Icon */}
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                </svg>
              </div>
              <div className="feature-text">
                <h3>{t('Secure Access', 'ಸುರಕ್ಷಿತ ಪ್ರವೇಶ')}</h3>
                <p>{t('Role-based secure access to authorized systems and data.', 'ಅಧಿಕೃತ ವ್ಯವಸ್ಥೆಗಳು ಮತ್ತು ಡೇಟಾಗೆ ಪಾತ್ರ-ಆಧಾರಿತ ಸುರಕ್ಷಿತ ಪ್ರವೇಶ.')}</p>
              </div>
            </div>

            <div className="feature-item">
              <div className="feature-icon">
                {/* Document Icon */}
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14 2 14 8 20 8"/>
                  <line x1="16" y1="13" x2="8" y2="13"/>
                  <line x1="16" y1="17" x2="8" y2="17"/>
                </svg>
              </div>
              <div className="feature-text">
                <h3>{t('Operational Tools', 'ಕಾರ್ಯಾಚರಣೆಯ ಪರಿಕರಗಳು')}</h3>
                <p>{t('Access to operational tools, dashboards and case management systems.', 'ಕಾರ್ಯಾಚರಣೆಯ ಪರಿಕರಗಳು, ಡ್ಯಾಶ್‌ಬೋರ್ಡ್‌ಗಳು ಮತ್ತು ಪ್ರಕರಣ ನಿರ್ವಹಣಾ ವ್ಯವಸ್ಥೆಗಳ ಪ್ರವೇಶ.')}</p>
              </div>
            </div>

            <div className="feature-item">
              <div className="feature-icon">
                {/* Analytics Bar Chart Icon */}
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="20" x2="18" y2="10"/>
                  <line x1="12" y1="20" x2="12" y2="4"/>
                  <line x1="6" y1="20" x2="6" y2="14"/>
                </svg>
              </div>
              <div className="feature-text">
                <h3>{t('Data & Insights', 'ಡೇಟಾ ಮತ್ತು ಒಳನೋಟಗಳು')}</h3>
                <p>{t('Real-time data and insights to support informed decision making.', 'ಮಾಹಿತಿಯುಕ್ತ ನಿರ್ಧಾರ ಕೈಗೊಳ್ಳುವುದನ್ನು ಬೆಂಬಲಿಸಲು ನೈಜ-ಸಮಯದ ಡೇಟಾ ಮತ್ತು ಒಳನೋಟಗಳು.')}</p>
              </div>
            </div>

            <div className="feature-item">
              <div className="feature-icon">
                {/* Alert / Rapid Response Icon */}
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
                </svg>
              </div>
              <div className="feature-text">
                <h3>{t('Rapid Response', 'ತ್ವರಿತ ಪ್ರತಿಕ್ರಿಯೆ')}</h3>
                <p>{t('Streamlined incident reporting and rapid deployment coordination tools.', 'ಸರಳೀಕೃತ ಘಟನಾ ವರದಿ ಮತ್ತು ತ್ವರಿತ ನಿಯೋಜನೆ ಸಮನ್ವಯ ಪರಿಕರಗಳು.')}</p>
              </div>
            </div>
          </div>
        </div>

        {/* Right Side Landing Card */}
        <div className="landing-card-wrapper">
          <div className="landing-logo-container">
            <img
              src="logo.jpeg"
              alt="Government of Karnataka Coat of Arms"
              className="landing-logo"
              onError={(e) => {
                e.target.onerror = null;
                e.target.src = 'https://upload.wikimedia.org/wikipedia/commons/thumb/b/be/Seal_of_Karnataka.svg/240px-Seal_of_Karnataka.svg.png';
              }}
            />
            <h3 className="card-logo-title">{t('Karnataka State Police', 'ಕರ್ನಾಟಕ ರಾಜ್ಯ ಪೊಲೀಸ್')}</h3>
            <p className="card-logo-subtitle">{t('Secure Internal Portal', 'ಸುರಕ್ಷಿತ ಆಂತರಿಕ ಪೋರ್ಟಲ್')}</p>
            <button onClick={onEnter} className="portal-login-btn">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
              </svg>
              <span>{t('Access Secure Login', 'ಸುರಕ್ಷಿತ ಲಾಗಿನ್ ಪ್ರವೇಶಿಸಿ')}</span>
            </button>
            <div className="card-footer-note">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
              <span>{t('This portal is for authorized Karnataka State Police personnel only.', 'ಈ ಪೋರ್ಟಲ್ ಅಧಿಕೃತ ಕರ್ನಾಟಕ ರಾಜ್ಯ ಪೊಲೀಸ್ ಸಿಬ್ಬಂದಿಗೆ ಮಾತ್ರ ಸೀಮಿತವಾಗಿದೆ.')}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom Info Bar */}
      <div className="info-bar">
        <div className="info-bar-item">
          <div className="info-bar-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
              <circle cx="12" cy="7" r="4"/>
            </svg>
          </div>
          <div className="info-bar-text">
            <span className="info-bar-label">{t('KSP Personnel', 'ಕೆ.ಎಸ್.ಪಿ ಸಿಬ್ಬಂದಿ')}</span>
            <span className="info-bar-val">
              <span className="underline">{t('Serving with Pride', 'ಹೆಮ್ಮೆಯ ಸೇವೆ')}</span>
            </span>
          </div>
        </div>
        <div className="info-bar-item">
          <div className="info-bar-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
              <circle cx="12" cy="10" r="3"/>
            </svg>
          </div>
          <div className="info-bar-text">
            <span className="info-bar-label">{t('Units & Districts', 'ಘಟಕಗಳು ಮತ್ತು ಜಿಲ್ಲೆಗಳು')}</span>
            <span className="info-bar-val">{t('Statewide Connectivity', 'ರಾಜ್ಯಾದ್ಯಂತ ಸಂಪರ್ಕ')}</span>
          </div>
        </div>
        <div className="info-bar-item">
          <div className="info-bar-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
          </div>
          <div className="info-bar-text">
            <span className="info-bar-label">{t('Integrity • Service • Protection', 'ಸತ್ಯನಿಷ್ಠೆ • ಸೇವೆ • ರಕ್ಷಣೆ')}</span>
            <span className="info-bar-val">{t('Our Commitment', 'ನಮ್ಮ ಬದ್ಧತೆ')}</span>
          </div>
        </div>
        <div className="info-bar-item">
          <div className="info-bar-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
              <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
            </svg>
          </div>
          <div className="info-bar-text">
            <span className="info-bar-label">{t('Always Alert. Always Ready.', 'ಯಾವಾಗಲೂ ಜಾಗರೂಕ. ಯಾವಾಗಲೂ ಸಿದ್ಧ.')}</span>
            <span className="info-bar-val">{t('For a Safer Karnataka', 'ಸುರಕ್ಷಿತ ಕರ್ನಾಟಕಕ್ಕಾಗಿ')}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
