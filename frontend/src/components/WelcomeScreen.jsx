/**
 * WelcomeScreen — the greeting + suggestion chips shown when a new chat has no
 * messages yet. Returns just the heading, intelligence ticker, and chips;
 * ChatWindow wraps these together with the Composer in a single vertically +
 * horizontally centered group so the input sits directly below the suggestions.
 */
import { useState, useEffect } from 'react'
import IntelligenceTicker from './IntelligenceTicker.jsx'
import { fetchTicker } from '../api/ticker.js'

export default function WelcomeScreen({ officer, onSuggestion, isStreaming }) {
  const firstName = officer?.full_name?.split(' ')[0] ?? 'Officer'
  const [tickerText, setTickerText] = useState(null)

  // Fetch the ticker once on mount (served from localStorage if within TTL)
  useEffect(() => {
    let cancelled = false
    fetchTicker(officer)
      .then((text) => {
        if (!cancelled) setTickerText(text)
      })
      .catch(() => {
        // Graceful: ticker is optional — never block the welcome screen
      })
    return () => { cancelled = true }
  }, [officer?.officer_id]) // eslint-disable-line react-hooks/exhaustive-deps

  const suggestions = [
    'How many theft cases are open?',
    'Show me all cases involving Mahesh Gowda',
    'List all vehicle theft cases with registration numbers',
    'Who are the top 5 repeat offenders?',
  ]

  return (
    <>
      <div className="welcome-text">
        <h1 className="welcome-heading">Good day, {firstName}.</h1>
        <IntelligenceTicker text={tickerText} />
        <p className="welcome-subheading">What would you like to look up today?</p>
      </div>

      <div className="suggestion-chips">
        {suggestions.map((s) => (
          <button
            key={s}
            className="suggestion-chip"
            onClick={() => onSuggestion(s)}
            disabled={isStreaming}
          >
            {s}
          </button>
        ))}
      </div>
    </>
  )
}
