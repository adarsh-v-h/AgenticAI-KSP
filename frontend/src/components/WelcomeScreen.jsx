/**
 * WelcomeScreen — the greeting + suggestion chips shown when a new chat has no
 * messages yet. Returns just the heading and chips; ChatWindow wraps these
 * together with the Composer in a single vertically + horizontally centered
 * group so the input sits directly below the suggestions.
 */
export default function WelcomeScreen({ officer, onSuggestion, isStreaming }) {
  const firstName = officer?.full_name?.split(' ')[0] ?? 'Officer'

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
