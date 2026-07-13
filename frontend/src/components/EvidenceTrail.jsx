import { useEffect, useState } from 'react'
import { fetchEvidenceTrail, AuthError } from '../api/evidenceTrail'

export default function EvidenceTrail({ messageId, onAuthExpired }) {
  const [data, setData] = useState(null)
  const [status, setStatus] = useState('loading')

  useEffect(() => {
    let cancelled = false
    setStatus('loading')
    fetchEvidenceTrail(messageId)
      .then((res) => {
        if (cancelled) return
        if (res === null) { setStatus('empty'); return }
        setData(res)
        setStatus('ready')
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof AuthError) { onAuthExpired?.(); return }
        setStatus('error')
      })
    return () => { cancelled = true }
  }, [messageId, onAuthExpired])

  if (status === 'loading') return <div className="evidence-trail evidence-trail--state">Loading…</div>
  if (status === 'empty') return <div className="evidence-trail evidence-trail--state">No SQL ran for this answer.</div>
  if (status === 'error') return <div className="evidence-trail evidence-trail--state">Could not load evidence trail.</div>

  return (
    <div className="evidence-trail">
      <div className="evidence-trail__row"><span>Tables queried</span><span>{data.tables_queried}</span></div>
      <div className="evidence-trail__row"><span>Rows returned</span><span>{data.row_count}</span></div>
      {data.case_ids_referenced && (
        <div className="evidence-trail__row"><span>Cases referenced</span><span>{data.case_ids_referenced}</span></div>
      )}
      <pre className="evidence-trail__sql">{data.sql_executed}</pre>
    </div>
  )
}
