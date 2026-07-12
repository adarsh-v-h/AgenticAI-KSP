# SixToSeven — Step 2 of 4 (BLUEPRINT2 Build)

> **Context:** `MIGRATE.md` is done. `FiveToSix.md` (Step 1 of 4) is done — `offender_risk_scores`,
> `chat_evidence_trail`, `audit_log` tables exist; `Employee.role` is populated with a spread of
> roles; `require_role()` and `log_action()` exist in `backend/auth/role_guard.py`; JWTs now carry
> a `role` field; `GET /api/audit-log` is live and gated to `supervisor`.
>
> This is Step 2 of 4 in building BLUEPRINT2. **Read `BLUEPRINT2.md` Part A first, then
> `BLUEPRINT2_PATCH.md` Patch 2 — apply the patch's corrected queries, not BLUEPRINT2's originals.**
> This step builds Part A (Crime Pattern & Trend Analytics) end to end: the 7-function
> `trend_analytics.py` module, the `analytics.py` router, and the `AnalyticsDashboard.jsx` +
> `TrendChart.jsx` frontend.
>
> Do not start Part B, C, or D's logic yet — that's Steps 3 and 4. This step is analytics only.

---

## What Step 2 Is

Three things, in order:
1. **`backend/pipeline/trend_analytics.py`** — 7 pure-SQL aggregation functions against
   `CaseMaster` and its lookup tables (`CrimeSubHead`, `CaseStatusMaster`, `Unit`). No ML, no LLM
   calls — this whole module is deterministic SQL, same spirit as `sql_validator.py`.
2. **`backend/routers/analytics.py`** — 7 GET endpoints, one per analytics function, all gated by
   plain authentication (`get_current_officer`) — no `require_role()` gate, since trend data is
   station-level aggregate, not per-accused sensitive data (contrast with `governance.py`'s
   audit log, which *is* `require_role("supervisor")`-gated).
3. **Frontend `AnalyticsDashboard.jsx` + `TrendChart.jsx`** — a new dashboard view with 6 panels
   (monthly trend, crime-type breakdown, top stations with drill-down, status breakdown, MO
   clusters, seasonal pattern), reachable from a new sidebar icon, lazy-loaded the same way
   `NetworkGraph.jsx` is.

---

## What "Done" Looks Like for Step 2

- [ ] `backend/pipeline/trend_analytics.py` exists with all 7 functions, each returning `list[dict]`
- [ ] `backend/routers/analytics.py` exists with 7 GET routes, registered in `main.py`
- [ ] All 7 routes return HTTP 200 with real data against the seeded DB
- [ ] `GET /api/analytics/trends/station/{unit_id}/breakdown` correctly takes an integer `Unit.UnitID`, not a free-text location string
- [ ] `AnalyticsDashboard.jsx` renders all 6 panels using live data from the 7 endpoints
- [ ] Clicking a bar in the "Top Police Stations" panel drills down into that station's crime-type breakdown, using `unit_id` (an integer already in hand from the API response — no URL-encoding needed)
- [ ] `TrendChart.jsx` is a dependency-free reusable SVG chart (bar + line modes) — no charting library added
- [ ] Existing chat endpoints and Step 1's audit-log endpoint still work exactly as before

---

## Critical Context — Read Before Writing Code

- **Use `BLUEPRINT2_PATCH.md`'s corrected queries, not `BLUEPRINT2.md`'s originals.** Every query
  in BLUEPRINT2's own Part A section targets the old `fir_master`/`case_type`/`incident_location`
  schema. Patch 2 has the full corrected `trend_analytics.py` — use it verbatim as the starting
  point below.
- **Location is `Unit.UnitName`, not a free-text column.** `CaseMaster` has no
  `incident_location` field in the official schema. Every "location" concept in this step is
  really "police station" via `PoliceStationID` → `Unit.UnitID`/`UnitName`. This is why the
  drill-down endpoint's signature changed from `location: str` to `station_unit_id: int` — the
  route param is a real FK value, not a string that needs escaping/encoding.
- **Crime type is never a direct column.** Every query that groups by crime type joins
  `CrimeSubHead` on `CaseMaster.CrimeMinorHeadID = CrimeSubHead.CrimeSubHeadID` and reads
  `CrimeSubHead.CrimeHeadName`.
- **`case_relationships` no longer exists.** The old "MO clustering" concept from BLUEPRINT2 relied
  on a relationships table that MIGRATE.md removed (see MIGRATE.md §7, Option A). Patch 2's
  `get_modus_operandi_clusters()` is a *reworked proxy*: it groups cases by same crime sub-head +
  same station, not by an actual relationships table. Don't try to resurrect the old table.
- **No new DDL in this step.** Step 1 already created every table BLUEPRINT2's four feature areas
  need (`offender_risk_scores`, `chat_evidence_trail`, `audit_log`). Analytics reads only from
  `CaseMaster` and its existing lookup tables — nothing new to create.
- **No `require_role()` gate on analytics routes.** Unlike `governance.py`'s audit log
  (`supervisor`-only), analytics endpoints are station-level aggregates any authenticated officer
  can see. If this changes later (e.g. policymaker-only dashboards), it's a one-line addition to
  each route's `Depends(...)` — not part of this step.
- **No audit logging on analytics reads.** `log_action()` (built in Step 1) is reserved for
  sensitive/role-gated actions per its own docstring — risk scores, evidence trails, exports.
  Viewing an aggregate trend chart isn't that; Step 2 does not call `log_action()` anywhere.
- **No charting library.** The frontend has zero chart dependencies today (same "keep the bundle
  small" convention as `Icons.jsx`'s inline SVGs — `vis-network` was only pulled in for the graph
  feature and is lazy-loaded so it doesn't bloat the main bundle). `TrendChart.jsx` in this step is
  a small dependency-free SVG component — don't add `recharts`/`chart.js`/etc.

---

## Step-by-Step Instructions

### 1. Confirm Step 1 is in place

```bash
mysql -u adarsh -proot ksp_crime_db_v2 -e "SHOW TABLES;" | grep -E "offender_risk_scores|chat_evidence_trail|audit_log"
mysql -u adarsh -proot ksp_crime_db_v2 -e "SELECT role, COUNT(*) FROM Employee GROUP BY role;"
```
Expected: all three tables present, and at least `investigator` + `supervisor` roles show non-zero counts. If either check fails, finish `FiveToSix.md` before continuing.

### 2. Create `backend/pipeline/trend_analytics.py`

```python
"""
Crime pattern and trend analytics — pure SQL aggregation, no ML.
All queries read from CaseMaster and its classification lookup tables
(CrimeHead/CrimeSubHead/CaseStatusMaster) per the official KSP schema.
Location concept is Unit.UnitName via PoliceStationID — CaseMaster has
no free-text location column.
"""
from db.connection import execute_query


async def get_trend_by_month(months_back: int = 12) -> list[dict]:
    """
    Crime count per month for the last `months_back` months.
    Returns: [{"month": "2025-06", "count": 34}, ...]
    """
    return await execute_query(
        """SELECT DATE_FORMAT(CrimeRegisteredDate, '%Y-%m') AS month, COUNT(*) AS count
           FROM CaseMaster
           WHERE CrimeRegisteredDate >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
           GROUP BY month
           ORDER BY month ASC""",
        (months_back,)
    )


async def get_trend_by_crime_type() -> list[dict]:
    """
    Total count per crime sub-head (the actual crime type), all time.
    Returns: [{"crime_type": "Theft", "count": 45}, ...]
    """
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           GROUP BY csh.CrimeHeadName
           ORDER BY count DESC"""
    )


async def get_trend_by_location(limit: int = 10) -> list[dict]:
    """
    Crime count per police station (closest available "location" concept —
    CaseMaster has no free-text location column in the official schema).
    Returns: [{"station": "Koramangala Police Station", "count": 28, "unit_id": 4}, ...]
    """
    return await execute_query(
        """SELECT u.UnitID AS unit_id, u.UnitName AS station, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN Unit u ON u.UnitID = cm.PoliceStationID
           GROUP BY u.UnitID, u.UnitName
           ORDER BY count DESC
           LIMIT %s""",
        (limit,)
    )


async def get_crime_type_by_location(station_unit_id: int) -> list[dict]:
    """
    Breakdown of crime types within a single police station — for drill-down.
    Signature takes `station_unit_id: int` (Unit.UnitID) since location is
    represented by a real FK, not a free-text string.
    Returns: [{"crime_type": "Theft", "count": 12}, ...]
    """
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           WHERE cm.PoliceStationID = %s
           GROUP BY csh.CrimeHeadName
           ORDER BY count DESC""",
        (station_unit_id,)
    )


async def get_status_breakdown() -> list[dict]:
    """
    Count of cases by investigation status.
    Returns: [{"status": "Open", "count": 132}, ...]
    """
    return await execute_query(
        """SELECT csm.CaseStatusName AS status, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CaseStatusMaster csm ON csm.CaseStatusID = cm.CaseStatusID
           GROUP BY csm.CaseStatusName
           ORDER BY count DESC"""
    )


async def get_modus_operandi_clusters(min_occurrences: int = 2) -> list[dict]:
    """
    REWORKED — case_relationships no longer exists (MIGRATE.md §7, Option A).
    Proxy for "MO clustering": groups cases by the SAME crime sub-head AND
    SAME police station, surfacing repeated patterns at a given station.
    Returns: [{"crime_type": "Theft", "station": "Koramangala...", "count": 6}, ...]
    Only returns groups with count >= min_occurrences.
    """
    return await execute_query(
        """SELECT csh.CrimeHeadName AS crime_type, u.UnitName AS station, COUNT(*) AS count
           FROM CaseMaster cm
           JOIN CrimeSubHead csh ON csh.CrimeSubHeadID = cm.CrimeMinorHeadID
           JOIN Unit u ON u.UnitID = cm.PoliceStationID
           GROUP BY csh.CrimeHeadName, u.UnitName
           HAVING count >= %s
           ORDER BY count DESC""",
        (min_occurrences,)
    )


async def get_seasonal_pattern() -> list[dict]:
    """
    Crime count grouped by month-of-year, irrespective of which year.
    Returns: [{"month_num": 1, "month_name": "January", "count": 18}, ...]
    """
    return await execute_query(
        """SELECT MONTH(CrimeRegisteredDate) AS month_num,
                  MONTHNAME(CrimeRegisteredDate) AS month_name,
                  COUNT(*) AS count
           FROM CaseMaster
           GROUP BY month_num, month_name
           ORDER BY month_num ASC"""
    )
```

> **Note vs. Patch 2's original text:** `get_trend_by_location()` here additionally selects
> `u.UnitID AS unit_id` (and groups by it) so the frontend can pass a real integer straight into
> the drill-down call without a second lookup. Patch 2's version only returned `station`/`count`;
> this small addition is what makes "click a bar → drill down" a zero-extra-request interaction on
> the frontend.

### 3. Create `backend/routers/analytics.py`

```python
"""
Analytics API routes — crime pattern and trend endpoints.
No SQL lives here; every route just calls the corrected functions in
pipeline/trend_analytics.py and shapes the JSON response.

Auth: plain authentication only (get_current_officer). Trend/pattern data
is station-level aggregate data, not per-accused sensitive data, so no
require_role() gate is applied here — unlike governance.py's audit log,
which is require_role("supervisor")-gated.
"""
from fastapi import APIRouter, Depends, Query
from auth.simple_auth import get_current_officer
from pipeline.trend_analytics import (
    get_trend_by_month,
    get_trend_by_crime_type,
    get_trend_by_location,
    get_crime_type_by_location,
    get_status_breakdown,
    get_modus_operandi_clusters,
    get_seasonal_pattern,
)

router = APIRouter()


@router.get("/api/analytics/trends/monthly")
async def trend_monthly(
    months_back: int = Query(12, ge=1, le=60),
    officer: dict = Depends(get_current_officer),
):
    data = await get_trend_by_month(months_back)
    return {"months_back": months_back, "trend": data}


@router.get("/api/analytics/trends/crime-type")
async def trend_crime_type(officer: dict = Depends(get_current_officer)):
    data = await get_trend_by_crime_type()
    return {"breakdown": data}


@router.get("/api/analytics/trends/stations")
async def trend_stations(
    limit: int = Query(10, ge=1, le=50),
    officer: dict = Depends(get_current_officer),
):
    data = await get_trend_by_location(limit)
    return {"stations": data}


@router.get("/api/analytics/trends/station/{unit_id}/breakdown")
async def station_breakdown(unit_id: int, officer: dict = Depends(get_current_officer)):
    """
    NOTE: route param is an integer Unit.UnitID, NOT a free-text location
    string. This is the corrected route per BLUEPRINT2_PATCH.md Patch 2 —
    the old `/trends/location/{location}/breakdown` string-param route is
    gone; there is no free-text location column to key off of anymore.
    """
    data = await get_crime_type_by_location(unit_id)
    return {"unit_id": unit_id, "breakdown": data}


@router.get("/api/analytics/status-breakdown")
async def status_breakdown(officer: dict = Depends(get_current_officer)):
    data = await get_status_breakdown()
    return {"breakdown": data}


@router.get("/api/analytics/mo-clusters")
async def mo_clusters(
    min_occurrences: int = Query(2, ge=1, le=100),
    officer: dict = Depends(get_current_officer),
):
    data = await get_modus_operandi_clusters(min_occurrences)
    return {"min_occurrences": min_occurrences, "clusters": data}


@router.get("/api/analytics/seasonal")
async def seasonal_pattern(officer: dict = Depends(get_current_officer)):
    data = await get_seasonal_pattern()
    return {"pattern": data}
```

### 4. Register the router in `backend/main.py`

```python
from routers.analytics import router as analytics_router
app.include_router(analytics_router)
```

Add this alongside the existing `auth_router`, `chat_router`, `export_router`, `reports_router`,
`voice_router`, `governance_router` registrations — same pattern as Step 1's
`governance_router`.

### 5. Create `frontend/src/api/analytics.js`

A small REST client mirroring the fetch/error conventions already used in `api/chat.js`
(`authHeaders`, `AuthError` on 401, `fetchWithRetry` for transient failures).

```javascript
import { getToken } from './auth'

const BASE = '/api/analytics'

class AuthError extends Error {}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function get(path) {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (res.status === 401) throw new AuthError('Session expired')
  if (!res.ok) throw new Error(`Analytics request failed: ${res.status}`)
  return res.json()
}

export const fetchMonthlyTrend = (monthsBack = 12) => get(`/trends/monthly?months_back=${monthsBack}`)
export const fetchCrimeTypeTrend = () => get('/trends/crime-type')
export const fetchStationTrend = (limit = 10) => get(`/trends/stations?limit=${limit}`)
export const fetchStationBreakdown = (unitId) => get(`/trends/station/${unitId}/breakdown`)
export const fetchStatusBreakdown = () => get('/status-breakdown')
export const fetchMoClusters = (minOccurrences = 2) => get(`/mo-clusters?min_occurrences=${minOccurrences}`)
export const fetchSeasonalPattern = () => get('/seasonal')

export { AuthError }
```

### 6. Create `frontend/src/components/TrendChart.jsx`

Dependency-free SVG chart. Supports `type="bar"` (vertical bars, optional click handler for
drill-down) and `type="line"` (for the monthly trend). No external chart library.

```jsx
import { useMemo } from 'react'

const PALETTE = ['#cc785c', '#a9583e', '#8a9b6e', '#5b7c99', '#c9a15a', '#7a6a8f']

export default function TrendChart({
  data,
  xKey,
  yKey,
  type = 'bar',
  height = 220,
  color = 'var(--primary)',
  onBarClick,
  formatX = (v) => v,
  emptyLabel = 'No data yet',
}) {
  const width = 560
  const padding = { top: 16, right: 16, bottom: 36, left: 40 }
  const innerW = width - padding.left - padding.right
  const innerH = height - padding.top - padding.bottom

  const maxY = useMemo(() => {
    if (!data || data.length === 0) return 1
    return Math.max(...data.map((d) => Number(d[yKey]) || 0), 1)
  }, [data, yKey])

  if (!data || data.length === 0) {
    return <div className="trend-chart trend-chart--empty">{emptyLabel}</div>
  }

  const stepX = innerW / data.length
  const scaleY = (v) => innerH - (Number(v) / maxY) * innerH

  return (
    <svg
      className="trend-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Trend chart"
    >
      <g transform={`translate(${padding.left},${padding.top})`}>
        {/* gridlines */}
        {[0, 0.5, 1].map((t) => (
          <line
            key={t}
            x1={0}
            x2={innerW}
            y1={innerH * t}
            y2={innerH * t}
            stroke="var(--hairline)"
            strokeDasharray="2,3"
          />
        ))}

        {type === 'bar' &&
          data.map((d, i) => {
            const barW = stepX * 0.6
            const x = i * stepX + (stepX - barW) / 2
            const y = scaleY(d[yKey])
            const h = innerH - y
            return (
              <g key={i}>
                <rect
                  x={x}
                  y={y}
                  width={barW}
                  height={h}
                  fill={PALETTE[i % PALETTE.length]}
                  rx={3}
                  style={{ cursor: onBarClick ? 'pointer' : 'default' }}
                  onClick={onBarClick ? () => onBarClick(d) : undefined}
                >
                  <title>{`${formatX(d[xKey])}: ${d[yKey]}`}</title>
                </rect>
                <text
                  x={x + barW / 2}
                  y={innerH + 14}
                  textAnchor="middle"
                  fontSize="9"
                  fill="var(--text-secondary)"
                >
                  {String(formatX(d[xKey])).slice(0, 10)}
                </text>
              </g>
            )
          })}

        {type === 'line' && (
          <>
            <polyline
              fill="none"
              stroke={color}
              strokeWidth="2"
              points={data
                .map((d, i) => `${i * stepX + stepX / 2},${scaleY(d[yKey])}`)
                .join(' ')}
            />
            {data.map((d, i) => (
              <circle
                key={i}
                cx={i * stepX + stepX / 2}
                cy={scaleY(d[yKey])}
                r={3}
                fill={color}
              >
                <title>{`${formatX(d[xKey])}: ${d[yKey]}`}</title>
              </circle>
            ))}
            {data.map((d, i) => (
              <text
                key={`lbl-${i}`}
                x={i * stepX + stepX / 2}
                y={innerH + 14}
                textAnchor="middle"
                fontSize="9"
                fill="var(--text-secondary)"
              >
                {String(formatX(d[xKey])).slice(0, 10)}
              </text>
            ))}
          </>
        )}
      </g>
    </svg>
  )
}
```

### 7. Create `frontend/src/components/AnalyticsDashboard.jsx`

```jsx
import { useEffect, useState } from 'react'
import TrendChart from './TrendChart'
import {
  fetchMonthlyTrend,
  fetchCrimeTypeTrend,
  fetchStationTrend,
  fetchStationBreakdown,
  fetchStatusBreakdown,
  fetchMoClusters,
  fetchSeasonalPattern,
  AuthError,
} from '../api/analytics'

function Panel({ title, subtitle, children }) {
  return (
    <section className="analytics-panel">
      <h3 className="analytics-panel__title">{title}</h3>
      {subtitle && <p className="analytics-panel__subtitle">{subtitle}</p>}
      {children}
    </section>
  )
}

function PanelState({ isLoading, error }) {
  if (isLoading) return <div className="analytics-panel__state">Loading…</div>
  if (error) return <div className="analytics-panel__state analytics-panel__state--error">{error}</div>
  return null
}

export default function AnalyticsDashboard({ onAuthExpired, onClose }) {
  const [monthly, setMonthly] = useState(null)
  const [crimeType, setCrimeType] = useState(null)
  const [stations, setStations] = useState(null)
  const [statusBreakdown, setStatusBreakdown] = useState(null)
  const [moClusters, setMoClusters] = useState(null)
  const [seasonal, setSeasonal] = useState(null)

  const [selectedStation, setSelectedStation] = useState(null) // {unit_id, station}
  const [drilldown, setDrilldown] = useState(null)
  const [drilldownLoading, setDrilldownLoading] = useState(false)

  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    async function loadAll() {
      setIsLoading(true)
      setError(null)
      try {
        const [m, c, s, st, mo, se] = await Promise.all([
          fetchMonthlyTrend(12),
          fetchCrimeTypeTrend(),
          fetchStationTrend(10),
          fetchStatusBreakdown(),
          fetchMoClusters(2),
          fetchSeasonalPattern(),
        ])
        if (cancelled) return
        setMonthly(m.trend)
        setCrimeType(c.breakdown)
        setStations(s.stations)
        setStatusBreakdown(st.breakdown)
        setMoClusters(mo.clusters)
        setSeasonal(se.pattern)
      } catch (err) {
        if (cancelled) return
        if (err instanceof AuthError) {
          onAuthExpired?.()
          return
        }
        setError('Could not load analytics. Please try again.')
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    loadAll()
    return () => {
      cancelled = true
    }
  }, [onAuthExpired])

  async function handleStationClick(row) {
    setSelectedStation(row)
    setDrilldown(null)
    setDrilldownLoading(true)
    try {
      const res = await fetchStationBreakdown(row.unit_id)
      setDrilldown(res.breakdown)
    } catch (err) {
      if (err instanceof AuthError) {
        onAuthExpired?.()
        return
      }
      setDrilldown([])
    } finally {
      setDrilldownLoading(false)
    }
  }

  return (
    <div className="analytics-dashboard">
      <header className="analytics-dashboard__header">
        <h2>Crime Pattern &amp; Trend Analytics</h2>
        <button className="analytics-dashboard__close" onClick={onClose} aria-label="Close analytics">
          ×
        </button>
      </header>

      <PanelState isLoading={isLoading} error={error} />

      {!isLoading && !error && (
        <div className="analytics-dashboard__grid">
          <Panel title="Cases per Month" subtitle="Last 12 months">
            <TrendChart
              data={monthly}
              xKey="month"
              yKey="count"
              type="line"
              emptyLabel="No cases registered in this window"
            />
          </Panel>

          <Panel title="Cases by Crime Type" subtitle="All time">
            <TrendChart data={crimeType} xKey="crime_type" yKey="count" type="bar" />
          </Panel>

          <Panel
            title="Top Police Stations by Case Count"
            subtitle="Click a bar to see that station's crime-type breakdown"
          >
            <TrendChart
              data={stations}
              xKey="station"
              yKey="count"
              type="bar"
              onBarClick={handleStationClick}
            />
          </Panel>

          <Panel title="Case Status Breakdown">
            <TrendChart data={statusBreakdown} xKey="status" yKey="count" type="bar" />
          </Panel>

          <Panel
            title="Repeated Pattern Clusters"
            subtitle="Same crime type + same station, min. 2 occurrences"
          >
            {moClusters && moClusters.length > 0 ? (
              <table className="analytics-table">
                <thead>
                  <tr>
                    <th>Crime Type</th>
                    <th>Station</th>
                    <th>Count</th>
                  </tr>
                </thead>
                <tbody>
                  {moClusters.map((row, i) => (
                    <tr key={i}>
                      <td>{row.crime_type}</td>
                      <td>{row.station}</td>
                      <td>{row.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="analytics-panel__state">No repeated clusters found</div>
            )}
          </Panel>

          <Panel title="Seasonal Pattern" subtitle="Case count by month-of-year, all years combined">
            <TrendChart
              data={seasonal}
              xKey="month_name"
              yKey="count"
              type="bar"
              formatX={(v) => String(v).slice(0, 3)}
            />
          </Panel>
        </div>
      )}

      {selectedStation && (
        <div className="analytics-drilldown">
          <div className="analytics-drilldown__header">
            <h3>{selectedStation.station} — crime type breakdown</h3>
            <button onClick={() => setSelectedStation(null)} aria-label="Close breakdown">
              ×
            </button>
          </div>
          {drilldownLoading ? (
            <div className="analytics-panel__state">Loading…</div>
          ) : (
            <TrendChart data={drilldown} xKey="crime_type" yKey="count" type="bar" />
          )}
        </div>
      )}
    </div>
  )
}
```

### 8. Wire the dashboard into `ChatWindow.jsx`

Add a lazy-loaded modal, same pattern as the existing network graph modal:

```jsx
// near the other lazy imports
const AnalyticsDashboard = lazy(() => import('./AnalyticsDashboard'))

// state
const [analyticsOpen, setAnalyticsOpen] = useState(false)

// sidebar addition, alongside the existing new-chat-row / OfficerRow:
<button
  className="sidebar-action-row"
  onClick={() => setAnalyticsOpen(true)}
  title="Crime Pattern & Trend Analytics"
>
  <IconAnalytics size={18} />
  {sidebarOpen && <span>Analytics</span>}
</button>

// modal render, alongside the existing NetworkGraph <Suspense> block:
{analyticsOpen && (
  <Suspense fallback={<div className="modal-loading">Loading analytics…</div>}>
    <AnalyticsDashboard
      onClose={() => setAnalyticsOpen(false)}
      onAuthExpired={onLogout}
    />
  </Suspense>
)}
```

Add `IconAnalytics` to `frontend/src/components/Icons.jsx` (simple bar-chart glyph, same
`size`/`stroke="currentColor"` convention as the other icons).

### 9. CSS additions to `frontend/src/styles/main.css`

Add: `.analytics-dashboard` (full-screen overlay, same z-index tier as the network graph modal),
`.analytics-dashboard__header`, `.analytics-dashboard__grid` (responsive 2-column grid, 1-column
under ~900px), `.analytics-panel`, `.analytics-panel__title`, `.analytics-panel__subtitle`,
`.analytics-panel__state` (+ `--error` modifier), `.analytics-table` (reuse the existing
`TableRenderer` striped/hover styling rather than duplicating it), `.analytics-drilldown` (slide-up
panel anchored to the bottom of the grid), `.trend-chart` and `.trend-chart--empty`,
`.sidebar-action-row` (mirrors `.new-chat-row` styling so the new Analytics button matches the
existing sidebar buttons).

---

## Verify Step 2 — Run These Tests in Order

Restart the backend first:
```bash
pkill -f uvicorn
cd /home/venzz/Work/Dataathon
.venv/bin/uvicorn backend.main:app --reload --port 8000
```

Get a token:
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"badge_number": "7295834", "password": "7295834123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

**Test 1 — Monthly trend:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/analytics/trends/monthly?months_back=12" | python3 -m json.tool
```
Expected: `{"months_back": 12, "trend": [{"month": "2025-08", "count": ...}, ...]}`

**Test 2 — Crime type breakdown:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/analytics/trends/crime-type | python3 -m json.tool
```
Expected: `{"breakdown": [{"crime_type": "Theft", "count": 50}, ...]}` — counts should roughly
match `db/seed.py`'s distribution (Theft 50, Assault 35, Vehicle Theft 30, etc.).

**Test 3 — Top stations, and capture a `unit_id`:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/analytics/trends/stations?limit=5" | python3 -m json.tool

UNIT_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/analytics/trends/stations?limit=1" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['stations'][0]['unit_id'])")
echo "Top station unit_id: $UNIT_ID"
```
Expected: 5 stations with `unit_id`, `station`, `count`.

**Test 4 — Station drill-down (integer route param):**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/analytics/trends/station/$UNIT_ID/breakdown" | python3 -m json.tool
```
Expected: `{"unit_id": N, "breakdown": [{"crime_type": "...", "count": ...}, ...]}` — a subset of
Test 2's totals, scoped to just that station.

**Test 5 — Status breakdown:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/analytics/status-breakdown | python3 -m json.tool
```
Expected: `{"breakdown": [{"status": "Open", "count": ...}, ...]}` covering all 4 seeded
`CaseStatusMaster` values.

**Test 6 — MO clusters:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/analytics/mo-clusters?min_occurrences=2" | python3 -m json.tool
```
Expected: `{"min_occurrences": 2, "clusters": [{"crime_type": "...", "station": "...", "count": 2+}, ...]}`.
Every row's `count` must be `>= 2`.

**Test 7 — Seasonal pattern:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/analytics/seasonal | python3 -m json.tool
```
Expected: `{"pattern": [{"month_num": 1, "month_name": "January", "count": ...}, ..., {"month_num": 12, ...}]}` —
up to 12 rows, `month_num` ascending.

**Test 8 — No-auth rejection (regression check on the new routes):**
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/analytics/status-breakdown
```
Expected: `401` — confirms the new routes are actually behind `get_current_officer` and not
accidentally left open.

**Test 9 — Existing endpoints still work (regression check):**
```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/chat/sessions | python3 -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/audit-log | python3 -m json.tool
```
Expected: sessions list still returns normally (or `403` for `audit-log` if this officer isn't a
supervisor — either is fine, the point is the route still resolves and enforces Step 1's role
gate correctly, not a 404/500).

**Test 10 — Frontend build sanity:**
```bash
cd frontend
npm run build
```
Expected: builds cleanly with no import errors from `AnalyticsDashboard.jsx` / `TrendChart.jsx` /
`api/analytics.js`. Then manually: log in, click the new "Analytics" sidebar button, confirm all
6 panels render, click a bar in "Top Police Stations" and confirm the drill-down panel appears
with that station's crime-type breakdown.

All 10 passing = Step 2 done.

---

## What Is Explicitly NOT in Step 2

- No offender risk profiling (`risk_scoring.py`, `routers/profiling.py`) — Step 3
- No decision support (`case_timeline.py`, `similar_cases.py`, `case_summary.py`) — Step 4
- No evidence trail logic (`save_evidence_trail`, `chat_evidence_trail` writes) — Step 3
- No new DDL — Step 1 already created everything BLUEPRINT2 needs
- No `require_role()` gating on any analytics route — a deliberate design choice for this step,
  not an oversight; revisit only if a later requirement calls for restricting specific panels

---

## What Step 3 Will Build

Step 3 builds Part B (Offender Profiling) and Part D's evidence-trail half end to end:
`risk_scoring.py`'s five-factor explainable scoring model (using `BLUEPRINT2_PATCH.md` Patch 3's
corrected live-derived `prior_case_count`/`at_large_status`), the `profiling.py` router
(`/api/profiling/risk/{accused_id}`, `/api/profiling/top-risk`, `/api/profiling/recompute-all`),
`save_evidence_trail()` writing into Step 1's `chat_evidence_trail` table from the chat pipeline,
and the `RiskBadge.jsx` + `EvidenceTrail.jsx` frontend components.
