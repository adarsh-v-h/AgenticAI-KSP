import { useEffect, useState } from 'react'
import { fetchCaseTimeline, fetchCaseSummary, fetchSimilarCases, AuthError } from '../api/decisionSupport'

const TABS = ['Timeline', 'Summary', 'Similar Cases']

export default function CaseDetailPanel({ caseId, onClose, onAuthExpired }) {
  const [activeTab, setActiveTab] = useState('Timeline')
  const [cache, setCache] = useState({})
  const [loading, setLoading] = useState({})
  const [error, setError] = useState({})

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

  useEffect(() => {
    loadTab('Timeline')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId])

  return (
    <div className="case-detail-panel">
      <header className="case-detail-panel__header">
        <h2>Case #{caseId}</h2>
        <button onClick={onClose} aria-label="Close case details">×</button>
      </header>

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
          <table className="analytics-table">
            <thead><tr><th>Crime No</th><th>Score</th><th>Reasons</th></tr></thead>
            <tbody>
              {(cache['Similar Cases'] || []).map((c, i) => (
                <tr key={i}>
                  <td>{c.crime_no}</td>
                  <td>{c.match_score}</td>
                  <td>{(c.match_reasons || []).join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
