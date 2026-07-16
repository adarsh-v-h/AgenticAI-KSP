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
  fetchAccusedAgeDistribution,
  fetchCrimeByGender,
  fetchCrimeByOccupation,
  fetchVictimProfile,
  fetchDemographicRiskProfile,
  fetchForecastingSummary,
} from '../api/analytics'
import { AuthError } from '../api/chat'

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
  const [accusedAge, setAccusedAge] = useState(null)
  const [crimeByGender, setCrimeByGender] = useState(null)
  const [crimeByOccupation, setCrimeByOccupation] = useState(null)
  const [victimProfile, setVictimProfile] = useState(null)
  const [riskProfile, setRiskProfile] = useState(null)
  const [forecasting, setForecasting] = useState(null)

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
        const results = await Promise.allSettled([
          fetchMonthlyTrend(12),
          fetchCrimeTypeTrend(),
          fetchStationTrend(10),
          fetchStatusBreakdown(),
          fetchMoClusters(2),
          fetchSeasonalPattern(),
          fetchAccusedAgeDistribution(),
          fetchCrimeByGender(),
          fetchCrimeByOccupation(10),
          fetchVictimProfile(),
          fetchDemographicRiskProfile(),
          fetchForecastingSummary(),
        ])
        if (cancelled) return

        // Check for auth failures first — these should fail the whole dashboard
        const authFailure = results.find(
          (r) => r.status === 'rejected' && r.reason instanceof AuthError
        )
        if (authFailure) {
          onAuthExpired?.()
          return
        }

        // Extract fulfilled values; failed panels get null
        const [m, c, s, st, mo, se, aa, cg, co, vp, rp, fc] = results.map((r) =>
          r.status === 'fulfilled' ? r.value : null
        )

        // Note: All responses use 'trend' key except status/clusters/seasonal
        // (frontend adapted to existing backend response shapes)
        setMonthly(m?.trend ?? null)
        setCrimeType(c?.trend ?? null)
        setStations(s?.trend ?? null)
        setStatusBreakdown(st?.breakdown ?? null)
        setMoClusters(mo?.clusters ?? null)
        setSeasonal(se?.pattern ?? null)
        setAccusedAge(aa?.data ?? null)
        setCrimeByGender(cg?.data ?? null)
        setCrimeByOccupation(co?.data ?? null)
        setVictimProfile(vp?.data ?? null)
        setRiskProfile(rp?.data ?? null)
        setForecasting(fc ?? null)
      } catch (err) {
        if (cancelled) return
        // Fallback for unexpected errors not caught by allSettled
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
            {monthly === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">
                Could not load this panel
              </div>
            ) : (
              <TrendChart
                data={monthly}
                xKey="month"
                yKey="count"
                type="line"
                emptyLabel="No cases registered in this window"
              />
            )}
          </Panel>

          <Panel title="Cases by Crime Type" subtitle="All time">
            {crimeType === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">
                Could not load this panel
              </div>
            ) : (
              <TrendChart data={crimeType} xKey="crime_type" yKey="count" type="bar" />
            )}
          </Panel>

          <Panel
            title="Top Police Stations by Case Count"
            subtitle="Click a bar to see that station's crime-type breakdown"
          >
            {stations === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">
                Could not load this panel
              </div>
            ) : (
              <TrendChart
                data={stations}
                xKey="station"
                yKey="count"
                type="bar"
                onBarClick={handleStationClick}
              />
            )}
          </Panel>

          <Panel title="Case Status Breakdown">
            {statusBreakdown === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">
                Could not load this panel
              </div>
            ) : (
              <TrendChart data={statusBreakdown} xKey="status" yKey="count" type="bar" />
            )}
          </Panel>

          <Panel
            title="Repeated Pattern Clusters"
            subtitle="Same crime type + same station, min. 2 occurrences"
          >
            {moClusters === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">
                Could not load this panel
              </div>
            ) : moClusters.length > 0 ? (
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
            {seasonal === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">
                Could not load this panel
              </div>
            ) : (
              <TrendChart
                data={seasonal}
                xKey="month_name"
                yKey="count"
                type="bar"
                formatX={(v) => String(v).slice(0, 3)}
              />
            )}
          </Panel>

          <Panel title="Accused Age Distribution" subtitle="Sociological insight — offender demographics">
            {accusedAge === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">Could not load this panel</div>
            ) : (
              <TrendChart data={accusedAge} xKey="age_group" yKey="count" type="bar" />
            )}
          </Panel>

          <Panel title="Crime by Gender" subtitle="Crime type breakdown by accused gender">
            {crimeByGender === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">Could not load this panel</div>
            ) : crimeByGender.length > 0 ? (
              <table className="analytics-table">
                <thead><tr><th>Crime Type</th><th>Gender</th><th>Count</th></tr></thead>
                <tbody>
                  {crimeByGender.slice(0, 20).map((row, i) => (
                    <tr key={i}><td>{row.crime_type}</td><td>{row.gender}</td><td>{row.count}</td></tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="analytics-panel__state">No data available</div>
            )}
          </Panel>

          <Panel title="Crime by Occupation" subtitle="Top occupations in complainant data">
            {crimeByOccupation === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">Could not load this panel</div>
            ) : (
              <TrendChart data={crimeByOccupation} xKey="occupation" yKey="count" type="bar" />
            )}
          </Panel>

          <Panel title="Victim Profile" subtitle="Victim demographics by crime type, age group, and gender">
            {victimProfile === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">Could not load this panel</div>
            ) : victimProfile.length > 0 ? (
              <table className="analytics-table">
                <thead><tr><th>Crime Type</th><th>Age Group</th><th>Gender</th><th>Count</th></tr></thead>
                <tbody>
                  {victimProfile.slice(0, 20).map((row, i) => (
                    <tr key={i}><td>{row.crime_type}</td><td>{row.age_group}</td><td>{row.gender}</td><td>{row.count}</td></tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="analytics-panel__state">No data available</div>
            )}
          </Panel>

          <Panel title="Demographic Risk Profile" subtitle="Crime type × age group × gender for accused — social risk factors">
            {riskProfile === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">Could not load this panel</div>
            ) : riskProfile.length > 0 ? (
              <table className="analytics-table">
                <thead><tr><th>Crime Type</th><th>Age Group</th><th>Gender</th><th>Count</th></tr></thead>
                <tbody>
                  {riskProfile.slice(0, 20).map((row, i) => (
                    <tr key={i}><td>{row.crime_type}</td><td>{row.age_group}</td><td>{row.gender}</td><td>{row.count}</td></tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="analytics-panel__state">No data available</div>
            )}
          </Panel>

          {/* ─── Crime Forecasting / Early Warning ─────────────────── */}

          <Panel title="🔴 Hotspot Alerts" subtitle="Stations with ≥50% crime increase, latest quarter vs previous">
            {forecasting === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">Could not load this panel</div>
            ) : forecasting.hotspot_alerts.length > 0 ? (
              <table className="analytics-table">
                <thead>
                  <tr>
                    <th>Station</th>
                    <th>Recent</th>
                    <th>Previous</th>
                    <th>Change %</th>
                    <th>Level</th>
                  </tr>
                </thead>
                <tbody>
                  {forecasting.hotspot_alerts.slice(0, 20).map((row, i) => (
                    <tr key={i}>
                      <td>{row.station}</td>
                      <td>{row.recent_count}</td>
                      <td>{row.previous_count}</td>
                      <td style={{ fontWeight: 600 }}>+{row.change_pct}%</td>
                      <td>
                        <span className={`alert-badge alert-badge--${row.alert_level}`}>
                          {row.alert_level}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="analytics-panel__state">No hotspot alerts — all stations within normal range</div>
            )}
          </Panel>

          <Panel title="🔁 Repeat Crime Clusters" subtitle="Crime type + station combos with 3+ cases in last 90 days">
            {forecasting === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">Could not load this panel</div>
            ) : forecasting.repeat_crime_alerts.length > 0 ? (
              <table className="analytics-table">
                <thead>
                  <tr>
                    <th>Crime Type</th>
                    <th>Station</th>
                    <th>Count</th>
                  </tr>
                </thead>
                <tbody>
                  {forecasting.repeat_crime_alerts.slice(0, 20).map((row, i) => (
                    <tr key={i}>
                      <td>{row.crime_type}</td>
                      <td>{row.station}</td>
                      <td>{row.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="analytics-panel__state">No repeat crime clusters detected</div>
            )}
          </Panel>

          <Panel title="👥 Gang Activity Alerts" subtitle="Accused in 2+ cases within last 90 days — potential organized crime">
            {forecasting === null ? (
              <div className="analytics-panel__state analytics-panel__state--error">Could not load this panel</div>
            ) : forecasting.gang_activity_alerts.length > 0 ? (
              <table className="analytics-table">
                <thead>
                  <tr>
                    <th>Accused</th>
                    <th>Cases</th>
                    <th>Crime Types</th>
                    <th>Stations</th>
                  </tr>
                </thead>
                <tbody>
                  {forecasting.gang_activity_alerts.map((row, i) => (
                    <tr key={i}>
                      <td>{row.accused_name}</td>
                      <td style={{ fontWeight: 600 }}>{row.case_count}</td>
                      <td>{row.crime_types}</td>
                      <td>{row.stations}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="analytics-panel__state">No gang activity alerts</div>
            )}
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
