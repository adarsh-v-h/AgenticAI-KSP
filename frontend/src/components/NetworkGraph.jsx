/*
NetworkGraph — renders a vis-network graph in a modal overlay.

Props:
  - firId: number | null        (exactly one of firId / accusedId is set)
  - accusedId: number | null
  - onClose: () => void

Fetches GET /api/graph/fir/{id} or /api/graph/accused/{id}, then renders the
returned {nodes, edges} with vis-network. Shows loading / empty / error states.
The network instance is destroyed on unmount to avoid leaking canvas/listeners.
*/
import { useEffect, useRef, useState } from 'react'
import { Network } from 'vis-network/standalone'
import { getToken } from '../api/auth.js'

// Node colors by entity group — coral matches the app primary for accused
// (the entity an officer most often centers a search on).
const GROUP_COLORS = {
  fir: '#9e9890',
  accused: '#cc785c',
  victim: '#5b8ab0',
  officer: '#5a9e6f',
}

export default function NetworkGraph({ firId, accusedId, onClose }) {
  const containerRef = useRef(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let networkInstance = null
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const path = firId
          ? `/api/graph/fir/${firId}`
          : `/api/graph/accused/${accusedId}`
        const res = await fetch(path, {
          headers: { Authorization: `Bearer ${getToken()}` },
        })

        if (!res.ok) {
          if (!cancelled) {
            setError('Failed to load network graph.')
            setLoading(false)
          }
          return
        }

        const data = await res.json()
        if (cancelled) return

        if (!data.nodes || data.nodes.length === 0) {
          setError('No network connections found for this record.')
          setLoading(false)
          return
        }

        // ponytail: single-pass node normalization, ceiling: <300 nodes, upgrade: use a dedicated mapper if graph schema grows.
        const nodes = data.nodes.map((n) => {
          const type = n.group || n.type
          const colorKey = type === 'case' ? 'fir' : type
          return {
            ...n,
            color: GROUP_COLORS[colorKey] || GROUP_COLORS.fir,
          }
        })

        // vis-network mutates the data objects; pass plain arrays (the
        // standalone build accepts arrays directly without DataSet).
        networkInstance = new Network(
          containerRef.current,
          { nodes, edges: data.edges || [] },
          {
            nodes: { shape: 'dot', size: 16, font: { size: 13, color: '#2b2b2b' } },
            edges: {
              font: { size: 10, color: '#6b6b6b', strokeWidth: 2, strokeColor: '#ffffff' },
              color: { color: '#d8d2c8', highlight: '#cc785c' },
              arrows: { to: { enabled: false } },
              smooth: { type: 'continuous' },
            },
            physics: {
              stabilization: { iterations: 150 },
              barnesHut: { gravitationalConstant: -3000, springLength: 120 },
            },
            interaction: { hover: true, tooltipDelay: 120 },
          },
        )
        setLoading(false)
      } catch (e) {
        if (!cancelled) {
          setError('Failed to load network graph.')
          setLoading(false)
        }
      }
    }

    load()
    return () => {
      cancelled = true
      if (networkInstance) networkInstance.destroy()
    }
  }, [firId, accusedId])

  return (
    <div className="graph-overlay" onClick={onClose}>
      <div className="graph-panel" onClick={(e) => e.stopPropagation()}>
        <div className="graph-panel-header">
          <span>Network Analysis</span>
          <button
            className="graph-close-btn"
            onClick={onClose}
            aria-label="Close network analysis"
            type="button"
          >
            ×
          </button>
        </div>
        {loading ? <div className="graph-loading">Loading network...</div> : null}
        {error ? <div className="graph-error">{error}</div> : null}
        <div
          ref={containerRef}
          className="graph-canvas"
          style={{ visibility: loading || error ? 'hidden' : 'visible' }}
        />
      </div>
    </div>
  )
}
