# EightToNine — Step 4 of 4 (BLUEPRINT2 Build) — FINAL STEP

> **Context:** `SevenToEight.md` (Step 3) is done and fully audited — all 11 verification tests
> passed, including the ownership-scoping and DIRECT-path edge cases. Confirmed state heading into
> this step, cross-checked against `CONTRACTS.md`:
>
> | Backend piece | Status | Confirmed shape |
> |---|---|---|
> | `GET /api/profiling/risk/{accused_id}` | ✅ Live | Not in `CONTRACTS.md` — assumed flat `compute_risk_for_accused()` dict, **verify in Step 1 below** |
> | `GET /api/profiling/top-risk` | ✅ Live | Ranked list, dedup'd by `AccusedName`, placeholders excluded |
> | `GET /api/decision-support/timeline/{case_id}` | ✅ Live | `{"case_id": int, "timeline": list[dict]}` |
> | `GET /api/decision-support/summary/{case_id}` | ✅ Live | `{"case_id": int, "summary": str\|None, "error": str\|None}` |
> | `GET /api/decision-support/similar-cases/{case_id}` | ✅ Live | `{"case_id": int, "similar_cases": list[dict]}` |
> | `GET /api/chat/messages/{message_id}/evidence-trail` | ✅ Live | `{trail_id, message_id, sql_executed, tables_queried, row_count, case_ids_referenced, created_at}`, 404 if not found/owned/no-trail |
>
> **`CaseDetailPanel.jsx` does not exist.** `BLUEPRINT2_PATCH.md` and `SevenToEight.md` both assumed
> it already existed per a `MIGRATE.md` §10 reference — confirmed via direct filesystem search that
> this was a planning assumption that never got built. Officers currently see cases only as rows in
> `TableRenderer.jsx`, with a "View network" button as the only per-message action. This step builds
> `CaseDetailPanel.jsx` from scratch, not as an extension.
>
> **This step needs zero backend changes.** Every endpoint it wires against already exists and is
> already tested. Getting there required one design decision worth knowing before reading the
> instructions: `EvidenceTrail` needs a `message_id` that isn't available at SSE `done` time (per
> `Docs.md` §4.2, persistence — which is what creates the `message_id` — happens *after* `done` is
> sent, not before). Rather than reordering the stream generator to fix that, the frontend just
> calls the already-existing `GET /api/chat/sessions/{id}/messages` right after `onDone` and reads
> the real `message_id` off the last assistant row. One extra fast fetch, zero backend risk.

---

## What Step 4 Is

Three frontend components, wired into the existing message/session architecture, no backend work:

1. **`RiskBadge.jsx`** — a small, self-contained pill component. Triggers inline inside
   `MessageBubble.jsx` whenever a chat answer's `table_data` contains an `AccusedMasterID` column
   — mirrors exactly how "View network" already triggers off `firstFirId(tableData)`, via a new
   parallel helper `firstAccusedId(tableData)`. Click to expand the five contributing factors.
2. **`CaseDetailPanel.jsx`** — a new lazy-loaded modal, same `React.lazy()` + `Suspense` pattern as
   `NetworkGraph.jsx`. Three tabs — Timeline, Summary, Similar Cases — each backed by one of the
   three already-tested `decision-support` endpoints. Triggered by a new "View case details"
   button in `MessageBubble.jsx`, reusing the *existing* `firstFirId(tableData)` (no new
   extraction logic needed — same condition "View network" already uses).
3. **`EvidenceTrail.jsx`** — an inline expandable section on `MessageBubble.jsx` (not a modal —
   "why did it say this" is tied to one specific message, doesn't warrant a full overlay). Needs
   `message_id`, sourced via the fetch-after-`done` approach described above.

---

## What "Done" Looks Like for Step 4

- [ ] Step 1's curl check confirms the exact `/api/profiling/risk/{accused_id}` response shape
- [ ] `RiskBadge.jsx` renders inline whenever a table result contains a valid `AccusedMasterID`
- [ ] Clicking a `RiskBadge` expands to show all `contributing_factors` with their point values
- [ ] `CaseDetailPanel.jsx` opens via "View case details," all three tabs load independently
      (Timeline doesn't block Summary from being clickable while it's still loading)
- [ ] Summary tab correctly shows the `error` message (not a blank/crash) when `case_summary.py`
      returns `{"summary": None, "error": "..."}`
- [ ] `EvidenceTrail` appears on freshly-streamed messages within ~1 fetch of the stream finishing,
      *and* on messages loaded from session history — same code path, same `messageId` field
- [ ] `EvidenceTrail` on a DIRECT-path message (no SQL) shows "No SQL ran for this answer," not an
      error and not a blank state
- [ ] `npm run build` succeeds with no import errors
- [ ] No changes to any backend file
- [ ] All previously-working functionality (chat, analytics dashboard, network graph, sessions)
      still works exactly as before

---

## Critical Context — Read Before Writing Code

- **Verify the risk endpoint's shape before writing `RiskBadge.jsx`.** This is the one contract in
  this step that isn't independently confirmed in `CONTRACTS.md`. Step 1 below is a curl check,
  not optional — if the real shape differs from the flat-dict assumption, adjust `RiskBadge.jsx`'s
  field access before building the rest around it.
- **`RiskBadge` triggers from table data, not from inside `CaseDetailPanel`.** Risk is
  accused-scoped; cases don't have a "list accused for this case" endpoint. Building one just for
  this would be backend work this step shouldn't need. `RiskBadge` shows up wherever a query
  naturally surfaces `AccusedMasterID` rows (e.g. "who are the top offenders," "show accused in
  case X") — same trigger mechanism as `firstFirId`, applied to a different column.
- **`firstAccusedId(tableData)` must mirror `firstFirId(tableData)`'s exact contract** — same
  input type (`Array<object>|any`), same `number|null` return, same "never raises" guarantee (per
  `CONTRACTS.md`'s existing entry for `firstFirId`). Consistency here matters more than cleverness.
- **The `message_id`-after-`done` fetch is non-fatal by design.** If it fails (network blip,
  session got deleted mid-stream, whatever), the turn itself is completely unaffected — the
  officer just doesn't get an evidence-trail button on that one message until the next session
  reload. Don't let a failure here touch `isStreaming`, `statusText`, or any other stream-lifecycle
  state.
- **`CaseDetailPanel`'s three tabs load independently, not all at once.** Same philosophy as
  `AnalyticsDashboard.jsx`'s `Promise.allSettled()` per-panel isolation, but stronger here — Summary
  is LLM-backed (multi-second latency), Timeline and Similar Cases are fast SQL. Blocking the tab
  switcher on the slowest one would be a worse experience than Step 2's original `Promise.all()`
  problem. Load a tab's data only when it's first activated, cache it per-`caseId`, don't refetch
  on every tab switch.
- **`generate_case_summary()` can return `{"summary": None, "error": "..."}`** — this is a designed
  failure path (LLM unavailable), not an exception. The Summary tab must render `error` distinctly
  from both the loading state and a successful summary — don't let a falsy `summary` silently
  render nothing.
- **Evidence trail 404 means two different things and the UI shouldn't distinguish them.** Per
  `Docs.md`'s own reasoning for `message_evidence_trail`, a 404 covers "message doesn't exist,"
  "belongs to another officer," and "no trail row (DIRECT-path)" identically, on purpose — the
  frontend should just show "No SQL ran for this answer" for any 404, not try to guess which case
  it is.
- **No backend changes, no new DDL, no new router registrations.** Every fetch in this step hits
  an endpoint that already exists and was already exercised by `SevenToEight.md`'s own
  verification tests.

---

## Step-by-Step Instructions

### 1. Confirm the risk endpoint's exact response shape

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"badge_number": "7295834", "password": "7295834123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/profiling/risk/1" | python3 -m json.tool
```
Confirm the response is a flat object with `accused_id`, `risk_score`, `risk_tier`,
`contributing_factors` at the top level (matching `compute_risk_for_accused()`'s documented return
shape) — not wrapped inside e.g. `{"risk": {...}}`. If it's wrapped, adjust the field access in
`RiskBadge.jsx` (Step 4 below) accordingly before proceeding.

### 2. Create `frontend/src/api/profiling.js`

```javascript
import { getToken } from './auth'

const BASE = '/api/profiling'

class AuthError extends Error {}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function fetchRiskScore(accusedId) {
  const res = await fetch(`${BASE}/risk/${accusedId}`, { headers: authHeaders() })
  if (res.status === 401) throw new AuthError('Session expired')
  if (res.status === 404) return null // accused doesn't exist -- badge just won't render
  if (!res.ok) throw new Error(`Risk lookup failed: ${res.status}`)
  return res.json()
}

export { AuthError }
```

### 3. Create `frontend/src/api/decisionSupport.js`

```javascript
import { getToken } from './auth'

const BASE = '/api/decision-support'

class AuthError extends Error {}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function get(path) {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (res.status === 401) throw new AuthError('Session expired')
  if (!res.ok) throw new Error(`Decision support request failed: ${res.status}`)
  return res.json()
}

export const fetchCaseTimeline = (caseId) => get(`/timeline/${caseId}`)
export const fetchCaseSummary = (caseId) => get(`/summary/${caseId}`)
export const fetchSimilarCases = (caseId, limit = 5) => get(`/similar-cases/${caseId}?limit=${limit}`)

export { AuthError }
```

### 4. Create `frontend/src/api/evidenceTrail.js`

```javascript
import { getToken } from './auth'

class AuthError extends Error {}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function fetchEvidenceTrail(messageId) {
  const res = await fetch(`/api/chat/messages/${messageId}/evidence-trail`, { headers: authHeaders() })
  if (res.status === 401) throw new AuthError('Session expired')
  if (res.status === 404) return null // no trail -- DIRECT-path, not found, or not owned; UI treats these the same
  if (!res.ok) throw new Error(`Evidence trail request failed: ${res.status}`)
  return res.json()
}

export { AuthError }
```

### 5. Create `frontend/src/components/RiskBadge.jsx`

```jsx
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

  if (failed || !data) return null // a missing badge isn't worth an error state

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
                <span>{f.points}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </span>
  )
}
```

### 6. Create `frontend/src/components/EvidenceTrail.jsx`

```jsx
import { useEffect, useState } from 'react'
import { fetchEvidenceTrail, AuthError } from '../api/evidenceTrail'

export default function EvidenceTrail({ messageId, onAuthExpired }) {
  const [data, setData] = useState(null)
  const [status, setStatus] = useState('loading') // loading | ready | empty | error

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
```

### 7. Create `frontend/src/components/CaseDetailPanel.jsx`

```jsx
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
            : <div className="analytics-panel__state">{cache.Summary?.error || 'No summary available'}</div>
        )}

        {!loading[activeTab] && !error[activeTab] && activeTab === 'Similar Cases' && (
          <table className="analytics-table">
            <thead><tr><th>Crime No</th><th>Match Score</th><th>Why</th></tr></thead>
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
```

### 8. Wire everything into `MessageBubble.jsx`

Add the new helper (mirrors `firstFirId`'s exact contract) and the three conditional renders:

```jsx
// New helper, same shape as the existing firstFirId:
function firstAccusedId(tableData) {
  if (!Array.isArray(tableData)) return null
  for (const row of tableData) {
    const raw = row?.AccusedMasterID ?? row?.accused_master_id
    const id = Number(raw)
    if (Number.isFinite(id) && id > 0) return id
  }
  return null
}
```

New props `MessageBubble` needs to accept: `onCaseDetailRequest`, `messageId`, `onAuthExpired`
(some of these may already be threaded through for the network graph — reuse rather than
duplicate). In the render, alongside the existing "View network" button:

```jsx
const accusedId = firstAccusedId(tableData)
const caseId = firstFirId(tableData) // already exists — same helper "View network" uses

{accusedId && <RiskBadge accusedId={accusedId} onAuthExpired={onAuthExpired} />}

{caseId && (
  <button className="message-action-btn" onClick={() => onCaseDetailRequest?.(caseId)}>
    View case details
  </button>
)}

{messageId && (
  <button className="message-action-btn" onClick={() => setEvidenceOpen((v) => !v)}>
    Why this answer?
  </button>
)}
{evidenceOpen && messageId && (
  <EvidenceTrail messageId={messageId} onAuthExpired={onAuthExpired} />
)}
```

`evidenceOpen` is local `useState(false)` inside `MessageBubble` — collapsed by default so it
doesn't clutter every message.

### 9. Wire `CaseDetailPanel` into `ChatWindow.jsx` — same pattern as `NetworkGraph`

```jsx
// near the other lazy imports:
const CaseDetailPanel = lazy(() => import('./CaseDetailPanel'))

// state, mirroring the existing graph state pair:
const [caseDetailOpen, setCaseDetailOpen] = useState(false)
const [caseDetailId, setCaseDetailId] = useState(null)

// passed down to each MessageBubble:
onCaseDetailRequest={(caseId) => { setCaseDetailId(caseId); setCaseDetailOpen(true) }}

// modal render, alongside the existing NetworkGraph <Suspense> block:
{caseDetailOpen && (
  <Suspense fallback={<div className="modal-loading">Loading case details…</div>}>
    <CaseDetailPanel
      caseId={caseDetailId}
      onClose={() => setCaseDetailOpen(false)}
      onAuthExpired={onLogout}
    />
  </Suspense>
)}
```

### 10. Wire `message_id` sourcing in `ChatWindow.jsx`

For **freshly-streamed** messages — after the existing `onDone` handling completes, fetch the
real `message_id` and attach it to the just-finished assistant message:

```jsx
// Inside the onDone callback, after existing bumpSessionMetadata()/fetchSessions() logic:
try {
  const { messages: freshMessages } = await fetchMessages(activeSessionIdRef.current)
  const lastAssistant = [...freshMessages].reverse().find((m) => m.role === 'assistant')
  if (lastAssistant) {
    updateLastAssistant((msg) => ({ ...msg, messageId: lastAssistant.message_id }))
  }
} catch {
  // Non-fatal -- the evidence-trail button just won't appear on this message until
  // the next session reload. Does not touch isStreaming/statusText/anything else.
}
```

Uses the already-existing `fetchMessages()` (from `api/chat.js`) and `updateLastAssistant()`
(already documented as "the mechanism behind all streaming callbacks") — no new client helpers
needed for this part.

For **reloaded history** messages — `loadSessionMessages()` already maps each row's fields onto
the local message shape (`table_data` → `tableData`, etc., per `Docs.md` §6.7). Add `message_id`
→ `messageId` to that same mapping, so both code paths converge on the identical `messageId` prop
name `MessageBubble` reads from.

### 11. CSS additions to `frontend/src/styles/main.css`

- `.risk-badge` (small pill, background from the `--risk-color` CSS var set inline per tier),
  `.risk-badge-wrap` (positioning context for the popover), `.risk-badge__popover` (small
  absolutely-positioned card), `.risk-badge__score`, `.risk-badge__factors`
- `.case-detail-panel` (full overlay, same z-index tier as `.analytics-dashboard` and the network
  graph modal), `.case-detail-panel__header`, `.case-detail-panel__tabs` (underline-style tab
  bar, `.active` modifier), `.case-detail-panel__body`, `.case-timeline`, `.case-summary-text`
  (reuse `.analytics-table` for the Similar Cases tab rather than a new table style)
- `.evidence-trail` (inline card, not an overlay — sits directly under the message it belongs to),
  `.evidence-trail--state`, `.evidence-trail__row`, `.evidence-trail__sql` (monospace, scrollable,
  reuse `--font-mono`)
- `.message-action-btn` (shared small-button style for "View case details" / "Why this answer?",
  sitting alongside the existing "View network" button — same row, same sizing)

---

## Verify Step 4 — Manual QA Checklist

This step is pure frontend, so verification is a UI walkthrough rather than curl tests (Step 1's
curl check already confirmed the one contract that mattered).

```bash
cd frontend
npm run build
```
Expected: clean build, no import errors from any of the four new files.

Then, manually, logged in as an officer:

1. **Risk badge:** Ask *"Who are the top 5 repeat offenders?"* (a `SixToSeven.md`-era seeded
   suggestion, known to surface `AccusedMasterID` rows). Confirm a colored risk pill appears next
   to each relevant row's entry, and clicking one expands the five contributing factors with
   point values.
2. **Case details — Timeline:** Ask a question that returns case rows (e.g. *"Show me all vehicle
   theft cases"*). Click "View case details" on one row's result. Confirm the Timeline tab loads
   first and shows chronologically ordered events.
3. **Case details — Summary:** Switch to the Summary tab. Confirm it loads independently (doesn't
   wait on Timeline), shows a 3–5 sentence prose brief, and doesn't re-fetch if you switch away and
   back.
4. **Case details — Similar Cases:** Switch to that tab, confirm ranked matches with visible
   match reasons.
5. **Evidence trail — fresh message:** Ask any SQL-backed question. Once the answer finishes
   streaming, click "Why this answer?" — confirm it shows the SQL, tables queried, and row count
   (allow a brief moment for the post-`done` message-id fetch to land).
6. **Evidence trail — DIRECT-path message:** Send an obvious follow-up like *"thanks, what else
   can you help with?"* in the same session. Confirm its "Why this answer?" (if shown at all) leads
   to "No SQL ran for this answer" — not an error, not a blank panel.
7. **Evidence trail — after reload:** Reload the page, reopen the same session from the sidebar.
   Confirm "Why this answer?" still works on the older messages via the history-reload code path.
8. **Regression:** Confirm "View network" still works exactly as before, the analytics dashboard
   still opens and loads all 6 panels, and switching sessions doesn't leak state between them
   (e.g. a `RiskBadge` popover left open in one session doesn't carry into the next).

All 8 passing = Step 4 done — **BLUEPRINT2 complete.**

---

## What Is Explicitly NOT in Step 4

- No backend changes of any kind — every endpoint this step uses already exists and was already
  verified in `SevenToEight.md`
- No caching layer for risk scores or summaries on the frontend beyond `CaseDetailPanel`'s
  per-`caseId` in-memory tab cache — nothing persisted across page reloads
- No bulk "recompute all risk scores" UI — `POST /api/profiling/recompute-all` stays a
  backend/ops tool, not exposed to officers in this step
- No changes to `TableRenderer.jsx` itself — `RiskBadge` renders in `MessageBubble`, not as an
  extra table column, so the generic table renderer stays untouched

---

## BLUEPRINT2 — Complete

With Step 4 done, all five BLUEPRINT2 feature areas are live: Roles & Audit (Step 1), Crime Trend
Analytics (Step 2), Offender Risk Profiling + Decision Support + Evidence Trail (Steps 3–4). The
`ksp_crime_db` schema, the chat pipeline, and every BLUEPRINT2 addition are now running against
the same AWS RDS deployment with no outstanding backend work queued from any of the four steps.
