import { useMemo } from 'react'

// Using design system colors: primary, primary-active, accent-teal, accent-amber, success
// Reuses defined tokens instead of arbitrary hex values not in DESIGN.md
const PALETTE = [
  'var(--primary)',
  'var(--primary-active)',
  'var(--accent-teal)',
  'var(--accent-amber)',
  'var(--success)',
  'var(--muted-soft)',
]

export default function TrendChart({
  data,
  xKey,
  yKey,
  type = 'bar',
  height = 250,
  padding,
  color = 'var(--primary)',
  onBarClick,
  formatX = (v) => v,
  emptyLabel = 'No data yet',
}) {
  const width = 560
  const defaultPadding = { top: 16, right: 28, bottom: 65, left: 65 }
  const pad = { ...defaultPadding, ...padding }
  const innerW = width - pad.left - pad.right
  const innerH = height - pad.top - pad.bottom

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
      <g transform={`translate(${pad.left},${pad.top})`}>
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
            const labelText = String(formatX(d[xKey]))
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
                  <title>{`${labelText}: ${d[yKey]}`}</title>
                </rect>
                <text
                  x={x + barW / 2}
                  y={innerH + 10}
                  textAnchor="end"
                  fontSize="11"
                  fill="var(--text-secondary)"
                  transform={`rotate(-45 ${x + barW / 2} ${innerH + 10})`}
                >
                  {labelText.length > 22 ? `${labelText.slice(0, 20)}…` : labelText}
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
            {data.map((d, i) => {
              const labelText = String(formatX(d[xKey]))
              const xPos = i * stepX + stepX / 2
              return (
                <text
                  key={`lbl-${i}`}
                  x={xPos}
                  y={innerH + 10}
                  textAnchor="end"
                  fontSize="11"
                  fill="var(--text-secondary)"
                  transform={`rotate(-45 ${xPos} ${innerH + 10})`}
                >
                  {labelText.length > 22 ? `${labelText.slice(0, 20)}…` : labelText}
                </text>
              )
            })}
          </>
        )}
      </g>
    </svg>
  )
}
