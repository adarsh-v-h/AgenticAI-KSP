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

  // Rotate labels when there are many categories to prevent overlap
  const shouldRotateLabels = data.length > 8

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
                {shouldRotateLabels ? (
                  <text
                    x={x + barW / 2}
                    y={innerH + 8}
                    textAnchor="end"
                    fontSize="11"
                    fill="var(--text-secondary)"
                    transform={`rotate(-45 ${x + barW / 2} ${innerH + 8})`}
                  >
                    {labelText.slice(0, 18)}
                  </text>
                ) : (
                  <text
                    x={x + barW / 2}
                    y={innerH + 14}
                    textAnchor="middle"
                    fontSize="12"
                    fill="var(--text-secondary)"
                  >
                    {labelText.slice(0, 10)}
                  </text>
                )}
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
                fontSize="12"
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
