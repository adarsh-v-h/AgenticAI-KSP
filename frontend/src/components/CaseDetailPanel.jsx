import { useEffect, useRef, useState } from 'react'
import { fetchCaseTimeline, fetchCaseSummary, fetchSimilarCases, AuthError } from '../api/decisionSupport'

const TABS = ['Timeline', 'Summary', 'Similar Cases']

// Single case card — self-contained tab loader for one caseId
function CaseCard({ caseId, onAuthExpired }) {
  const [activeTab, setActiveTab] = useState('Timeline')
  const [cache, setCache] = useState({})
  const [loading, setLoading] = useState({})
  const [error, setError] = useState({})
  const cardRef = useRef(null)
  const [visible, setVisible] = useState(false)

  // Trigger initial Timeline load only when the card scrolls into view
  useEffect(() => {
    const el = cardRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) setVisible(true) },
      { threshold: 0.1 }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (visible) loadTab('Timeline')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible])

  async function loadTab(tab) {
    if (cache[tab] !== undefined || loading[tab]) return
    setLoading((s) => ({ ...s, [tab]: true }))
    try {
      let data
      if (tab === 'Timeline') data = (await fetchCaseTimeline(caseId)).timeline
      else if (tab === 'Summary') data = await fetchCaseSummary(caseId)
      else data = (await fetchSimilarCases(caseId)).similar_cases
      setCache((c) => ({ ...c, [tab]: data }))
    } catch (err) {
      if (err instanceof AuthError) { onAuthExpired?.(); return }
      setError((e) => ({ ...e, [tab]: true }))
    } finally {
      setLoading((s) => ({ ...s, [tab]: false }))
    }
  }

  function selectTab(tab) {
    setActiveTab(tab)
    loadTab(tab)
  }

  return (
    <div className="case-card" ref={cardRef}>
      <h3 className="case-card__title">Case #{caseId}</h3>

      <nav className="case-detail-panel__tabs">
        {TABS.map((tab) => (
          <button
            key={tab}
            className={tab === activeTab ? 'active' : ''}
            onClick={() => selectTab(tab)}
          >
            {tab}
          </button>
        ))}
      </nav>

      <div className="case-detail-panel__body">
        {loading[activeTab] && <div className="analytics-panel__state">Loading…</div>}
        {error[activeTab] && (
          <div className="analytics-panel__state analytics-panel__state--error">Could not load this tab</div>
        )}

        {!loading[activeTab] && !error[activeTab] && activeTab === 'Timeline' && (
          <ul className="case-timeline">
            {(cache.Timeline || []).map((ev, i) => (
              <li key={i}><strong>{ev.date}</strong> — {ev.event}</li>
            ))}
            {cache.Timeline && cache.Timeline.length === 0 && (
              <div className="analytics-panel__state">No timeline events on record</div>
            )}
          </ul>
        )}

        {!loading[activeTab] && !error[activeTab] && activeTab === 'Summary' && (
          cache.Summary?.summary
            ? <p className="case-summary-text">{cache.Summary.summary}</p>
            : cache.Summary && <div className="analytics-panel__state">{cache.Summary.error || 'No summary available'}</div>
        )}

        {!loading[activeTab] && !error[activeTab] && activeTab === 'Similar Cases' && (
          cache['Similar Cases'] && cache['Similar Cases'].length > 0 ? (
            <table className="analytics-table">
              <thead><tr><th>Crime No</th><th>Score</th><th>Reasons</th></tr></thead>
              <tbody>
                {cache['Similar Cases'].map((c, i) => (
                  <tr key={i}>
                    <td>{c.crime_no}</td>
                    <td>{c.match_score}</td>
                    <td>{(c.match_reasons || []).join(', ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="analytics-panel__state">No similar cases found in your station's DB or crime records</div>
          )
        )}
      </div>
    </div>
  )
}

// CONTRACT
// takes:  caseIds (number[]) — ordered list of all CaseMasterIDs to display
//         onClose (function) — called when user closes the panel
//         onAuthExpired (function) — called on 401 responses
// returns: JSX — a scrollable panel rendering one CaseCard per caseId, stacked vertically
// throws:  never
export default function CaseDetailPanel({ caseIds = [], onClose, onAuthExpired }) {
  return (
    <div className="case-detail-panel">
      <header className="case-detail-panel__header">
        <h2>
          {caseIds.length === 1
            ? `Case #${caseIds[0]}`
            : `${caseIds.length} Cases`}
        </h2>
        <button onClick={onClose} aria-label="Close case details">×</button>
      </header>

      <div className="case-detail-panel__scroll">
        {caseIds.map((id) => (
          <CaseCard key={id} caseId={id} onAuthExpired={onAuthExpired} />
        ))}
      </div>
    </div>
  )
}
