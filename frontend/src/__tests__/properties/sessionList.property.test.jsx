/**
 * Property-based tests for the SessionList / SessionItem components.
 *
 * Covers:
 *   - Property 2: Session List Completeness (Task 6.7)
 *   - Property 3: Session Metadata Rendering (Task 6.7)
 *   - Property 4: Session List Ordering (Task 6.7)
 *
 * Validates: Requirements 1.1, 1.2, 1.3, 9.3
 *
 * Run:  cd frontend && npm test -- --run sessionList.property
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import fc from 'fast-check'
import { PROPERTY_CONFIG } from './config.js'
import SessionList from '../../components/SessionList.jsx'

// ---------------------------------------------------------------------------
// Arbitraries (generators)
// ---------------------------------------------------------------------------

/** Generate a realistic session metadata object. */
const arbSession = fc.record({
  session_id: fc.uuid(),
  title: fc.string({ minLength: 1, maxLength: 60 }),
  created_at: fc.date({ min: new Date('2023-01-01'), max: new Date('2026-12-31') }).map(
    (d) => d.toISOString(),
  ),
  updated_at: fc.date({ min: new Date('2023-01-01'), max: new Date('2026-12-31') }).map(
    (d) => d.toISOString(),
  ),
  message_count: fc.nat({ max: 500 }),
  officer_id: fc.nat({ max: 999999 }),
})

/** Generate a list of sessions with unique IDs. */
const arbSessionList = fc.array(arbSession, { minLength: 1, maxLength: 30 }).map((sessions) => {
  // Ensure unique session_ids.
  const seen = new Set()
  return sessions.filter((s) => {
    if (seen.has(s.session_id)) return false
    seen.add(s.session_id)
    return true
  })
})

// ---------------------------------------------------------------------------
// Property 2: Session List Completeness
// All sessions passed to the component are rendered in the DOM.
// ---------------------------------------------------------------------------

describe('Property 2: Session List Completeness', () => {
  it('renders exactly one item per session', () => {
    fc.assert(
      fc.property(arbSessionList, (sessions) => {
        const { container } = render(
          <SessionList
            sessions={sessions}
            activeSessionId={sessions[0]?.session_id}
            onSelect={() => {}}
          />,
        )

        // Each session should produce a .session-item element.
        const items = container.querySelectorAll('.session-item')
        expect(items.length).toBe(sessions.length)
      }),
      PROPERTY_CONFIG,
    )
  })

  it('renders empty state when sessions array is empty', () => {
    fc.assert(
      fc.property(fc.constant([]), (sessions) => {
        const { container } = render(
          <SessionList sessions={sessions} activeSessionId="" onSelect={() => {}} />,
        )
        expect(container.querySelector('.session-list__empty')).not.toBeNull()
        expect(container.querySelectorAll('.session-item').length).toBe(0)
      }),
      PROPERTY_CONFIG,
    )
  })
})

// ---------------------------------------------------------------------------
// Property 3: Session Metadata Rendering
// Each rendered item displays the session title and message count.
// ---------------------------------------------------------------------------

describe('Property 3: Session Metadata Rendering', () => {
  it('displays the title for every session', () => {
    fc.assert(
      fc.property(arbSessionList, (sessions) => {
        const { container } = render(
          <SessionList
            sessions={sessions}
            activeSessionId=""
            onSelect={() => {}}
          />,
        )

        const titleElements = container.querySelectorAll('.session-item__title')
        expect(titleElements.length).toBe(sessions.length)

        sessions.forEach((session, i) => {
          const expected = session.title || 'New chat'
          expect(titleElements[i].textContent).toBe(expected)
        })
      }),
      PROPERTY_CONFIG,
    )
  })

  it('displays the message count for every session', () => {
    fc.assert(
      fc.property(arbSessionList, (sessions) => {
        const { container } = render(
          <SessionList
            sessions={sessions}
            activeSessionId=""
            onSelect={() => {}}
          />,
        )

        const countElements = container.querySelectorAll('.session-item__count')
        expect(countElements.length).toBe(sessions.length)

        sessions.forEach((session, i) => {
          const count = session.message_count
          const expectedText = `${count} ${count === 1 ? 'message' : 'messages'}`
          expect(countElements[i].textContent).toBe(expectedText)
        })
      }),
      PROPERTY_CONFIG,
    )
  })
})

// ---------------------------------------------------------------------------
// Property 4: Session List Ordering
// Sessions are rendered in the order provided (caller sorts by updated_at).
// ---------------------------------------------------------------------------

describe('Property 4: Session List Ordering', () => {
  it('renders sessions in the same order they are provided', () => {
    fc.assert(
      fc.property(arbSessionList, (sessions) => {
        const { container } = render(
          <SessionList
            sessions={sessions}
            activeSessionId=""
            onSelect={() => {}}
          />,
        )

        const titleElements = container.querySelectorAll('.session-item__title')

        sessions.forEach((session, i) => {
          const expected = session.title || 'New chat'
          expect(titleElements[i].textContent).toBe(expected)
        })
      }),
      PROPERTY_CONFIG,
    )
  })

  it('marks only the active session with the active class', () => {
    fc.assert(
      fc.property(
        arbSessionList.filter((s) => s.length >= 2),
        fc.nat(),
        (sessions, indexSeed) => {
          const activeIndex = indexSeed % sessions.length
          const activeId = sessions[activeIndex].session_id

          const { container } = render(
            <SessionList
              sessions={sessions}
              activeSessionId={activeId}
              onSelect={() => {}}
            />,
          )

          const items = container.querySelectorAll('.session-item')
          items.forEach((item, i) => {
            if (i === activeIndex) {
              expect(item.classList.contains('session-item--active')).toBe(true)
            } else {
              expect(item.classList.contains('session-item--active')).toBe(false)
            }
          })
        },
      ),
      PROPERTY_CONFIG,
    )
  })
})
