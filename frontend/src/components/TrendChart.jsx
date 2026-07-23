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

const MONTH_NAMES = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
]

/**
 * Formats YYYY-MM dates (e.g. "2025-07") into abbreviated "Jul '25" format.
 */
function formatLabel(val, customFormatX) {
  const formatted = customFormatX ? customFormatX(val) : val
  const str = String(formatted)

  const match = str.match(/^(\d{4})-(\d{2})$/)
  if (match) {
    const yr = match[1].slice(2)
    const monthIdx = parseInt(match[2], 10) - 1
    if (monthIdx >= 0 && monthIdx < 12) {
      return `${MONTH_NAMES[monthIdx]} '${yr}`
    }
  }
  return str
}

/**
 * Wraps text into up to 2 horizontal lines breaking at word boundaries.
 * If a single word exceeds maxCharsPerLine, truncates only that word with an ellipsis.
 */
function wrapLabel(text, maxCharsPerLine = 10) {
  const str = String(text).trim()
  if (!str) return ['']

  if (str.length <= maxCharsPerLine) {
    return [str]
  }

  const words = str.split(/\s+/)
  if (words.length === 1) {
    const w = words[0]
    if (w.length > maxCharsPerLine) {
      return [w.slice(0, maxCharsPerLine - 1) + '…']
    }
    return [w]
  }

  // Find optimal split point between words for 2 lines
  let bestSplit = 1
  let minPenalty = Infinity

  for (let i = 1; i < words.length; i++) {
    const l1 = words.slice(0, i).join(' ')
    const l2 = words.slice(i).join(' ')

    const overflow1 = Math.max(0, l1.length - maxCharsPerLine)
    const overflow2 = Math.max(0, l2.length - maxCharsPerLine)
    const diff = Math.abs(l1.length - l2.length)

    const penalty = overflow1 * 20 + overflow2 * 20 + diff
    if (penalty < minPenalty) {
      minPenalty = penalty
      bestSplit = i
    }
  }

  let line1 = words.slice(0, bestSplit).join(' ')
  let line2 = words.slice(bestSplit).join(' ')

  function fitLine(l) {
    if (l.length <= maxCharsPerLine) return l
    return l.slice(0, Math.max(1, maxCharsPerLine - 1)).trimEnd() + '…'
  }

  return [fitLine(line1), fitLine(line2)]
}

export default function TrendChart({
  data,
  xKey,
  yKey,
  type = 'bar',
  height = 240,
  padding,
  color = 'var(--primary)',
  onBarClick,
  formatX = (v) => v,
  emptyLabel = 'No data yet',
}) {
  const width = 640
  const defaultPadding = { top: 16, right: 24, bottom: 42, left: 36 }
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
            const barW = stepX * 0.48
            const x = i * stepX + (stepX - barW) / 2
            const y = scaleY(d[yKey])
            const h = innerH - y
            const labelText = formatLabel(d[xKey], formatX)
            const xCenter = x + barW / 2
            const shouldWrap = data.length >= 8

            const maxChars = Math.max(8, Math.floor((stepX - 4) / 5.2))
            const lines = shouldWrap ? wrapLabel(labelText, maxChars) : [labelText]

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
                  x={xCenter}
                  y={innerH + 12}
                  textAnchor="middle"
                  fontSize={shouldWrap ? '10.5' : '11'}
                  fill="var(--text-secondary)"
                >
                  {lines.map((lineStr, lineIdx) => (
                    <tspan
                      key={lineIdx}
                      x={xCenter}
                      dy={lineIdx === 0 ? 0 : 13}
                    >
                      {lineStr}
                    </tspan>
                  ))}
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
                <title>{`${formatLabel(d[xKey], formatX)}: ${d[yKey]}`}</title>
              </circle>
            ))}
            {data.map((d, i) => {
              if (data.length > 8 && i % 2 !== 0) return null
              const labelText = formatLabel(d[xKey], formatX)
              const xPos = i * stepX + stepX / 2
              return (
                <text
                  key={`lbl-${i}`}
                  x={xPos}
                  y={innerH + 12}
                  textAnchor="middle"
                  fontSize="10"
                  fill="var(--text-secondary)"
                >
                  {labelText}
                </text>
              )
            })}
          </>
        )}
      </g>
    </svg>
  )
}
