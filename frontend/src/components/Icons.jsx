/**
 * Inline SVG icons — no icon library, keeps the bundle small.
 * Each icon takes a `size` prop (default 20) and inherits color via
 * `currentColor`, so callers control color through CSS `color`.
 */

export function IconSidebarOpen({ size = 20 }) {
  // Panel with a right-pointing chevron — "open / expand the sidebar".
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2.5" y="3.5" width="15" height="13" rx="2" />
      <line x1="7.5" y1="3.5" x2="7.5" y2="16.5" />
      <polyline points="10.5,7.5 13,10 10.5,12.5" />
    </svg>
  )
}

export function IconSidebarClose({ size = 20 }) {
  // Panel with a left-pointing chevron — "collapse the sidebar".
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2.5" y="3.5" width="15" height="13" rx="2" />
      <line x1="7.5" y1="3.5" x2="7.5" y2="16.5" />
      <polyline points="13,7.5 10.5,10 13,12.5" />
    </svg>
  )
}

export function IconNewChat({ size = 20 }) {
  // Pencil writing on a line — "compose a new chat".
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12.5 3.5l4 4L8 16l-4.5 1 1-4.5z" />
      <line x1="11" y1="5" x2="15" y2="9" />
    </svg>
  )
}

export function IconLogOut({ size = 20 }) {
  // Door frame with an arrow leaving — "sign out".
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12.5 3.5h-7a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h7" />
      <polyline points="13,7 16.5,10 13,13" />
      <line x1="16.5" y1="10" x2="8" y2="10" />
    </svg>
  )
}

export function IconPaperclip({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M15.5 9.5l-5.7 5.7a3 3 0 0 1-4.3-4.3l6-6a2 2 0 0 1 2.9 2.9l-6 6a1 1 0 0 1-1.5-1.5l5.3-5.3" />
    </svg>
  )
}

export function IconMic({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="7.5" y="2.5" width="5" height="9" rx="2.5" />
      <path d="M5 9.5a5 5 0 0 0 10 0" />
      <line x1="10" y1="14.5" x2="10" y2="17.5" />
      <line x1="7" y1="17.5" x2="13" y2="17.5" />
    </svg>
  )
}

export function IconArrowUp({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="10" y1="16" x2="10" y2="4" />
      <polyline points="4,10 10,4 16,10" />
    </svg>
  )
}

export function IconDownload({ size = 20 }) {
  // Arrow into a tray — "download / export".
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 3v10M6 9l4 4 4-4" />
      <path d="M3 16h14" />
    </svg>
  )
}
