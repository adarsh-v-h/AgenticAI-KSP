import { useEffect, useState } from 'react'
import { fetchRiskScore, AuthError } from '../api/profiling'

const TIER_COLORS = {
  low: '#8a9b6e',
  medium: '#c9a15a',
  high: '#cc785c',
  critical: '#a9583e',
}

export default function RiskBadge({ accusedId, onAuthExpired }) {
  const [data, setData] = useState(null)
  const [expanded, setExpanded] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setFailed(false)
    fetchRiskScore(accusedId)
      .then((res) => {
        if (cancelled) return
        if (res === null) { setFailed(true); return }
        setData(res)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof AuthError) { onAuthExpired?.(); return }
        setFailed(true)
      })
    return () => { cancelled = true }
  }, [accusedId, onAuthExpired])

  if (failed || !data) return null

  return (
    <span className="risk-badge-wrap">
      <button
        type="button"
        className={`risk-badge risk-badge--${data.risk_tier}`}
        style={{ '--risk-color': TIER_COLORS[data.risk_tier] || '#999' }}
        onClick={() => setExpanded((v) => !v)}
        title={`Risk score: ${data.risk_score}/100`}
      >
        {data.risk_tier} risk
      </button>
      {expanded && (
        <div className="risk-badge__popover">
          <div className="risk-badge__score">{data.risk_score}/100</div>
          <ul className="risk-badge__factors">
            {(data.contributing_factors || []).map((f, i) => (
              <li key={i}>
                <span>{f.factor}</span>
                <span className="risk-badge__points">{f.points} pts</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </span>
  )
}
