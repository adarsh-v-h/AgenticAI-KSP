/**
 * IntelligenceTicker — a scrolling station intelligence strip displayed on
 * the WelcomeScreen. Styled after the DESIGN.md badge-pill + surface-card
 * design tokens: cream-card background, hairline border, pill radius.
 *
 * The text scrolls left via a pure-CSS @keyframes animation (no JS interval).
 * Animation speed is proportional to text length for a consistent reading pace.
 * Renders nothing if text is null (graceful absence during cache warm-up).
 */

export default function IntelligenceTicker({ text }) {
  if (!text) return null

  // ~5px per character at a comfortable reading pace
  const durationSecs = Math.max(12, Math.min(30, Math.round(text.length * 0.22)))

  return (
    <div className="intelligence-ticker" role="marquee" aria-live="polite" aria-label="Station intelligence update">
      <div className="intelligence-ticker__badge">
        <span className="intelligence-ticker__dot" aria-hidden="true" />
        <span className="intelligence-ticker__label">LIVE</span>
      </div>
      <div className="intelligence-ticker__track">
        <span
          className="intelligence-ticker__text"
          style={{ animationDuration: `${durationSecs}s` }}
        >
          {text}
          {/* Duplicate for seamless loop */}
          <span aria-hidden="true">&nbsp;&nbsp;·&nbsp;&nbsp;{text}</span>
        </span>
      </div>
    </div>
  )
}
