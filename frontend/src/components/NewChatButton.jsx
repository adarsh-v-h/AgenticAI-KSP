export default function NewChatButton({ onClick, disabled = false }) {
  return (
    <button
      type="button"
      className="btn btn--ghost new-chat-button"
      onClick={onClick}
      disabled={disabled}
      aria-label="Start new chat"
    >
      <span className="new-chat-button__icon" aria-hidden="true">
        +
      </span>
      <span className="new-chat-button__label">New chat</span>
    </button>
  )
}
