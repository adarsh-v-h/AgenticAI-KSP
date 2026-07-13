# EightToNine.md Pre-Implementation Readiness Report

## Executive Summary

### Overall Status
✅ **Ready to Implement**

### Overall Readiness Score
92/100

### Confidence Level
90/100

*(Confidence is not higher because the repository does not contain a running database/API instance in this review environment — Step 1's curl verification against a live server could not be executed as part of this review. See "Missing Prerequisites.")*

---

## Scope Overview

`EightToNine.md` describes Step 4 of 4 in the BLUEPRINT2 build — a **frontend-only** step with **no backend changes**. It wires three new UI surfaces into the existing chat/session architecture:

1. `RiskBadge.jsx` — inline pill on `MessageBubble.jsx`, triggered when table rows contain `AccusedMasterID`, backed by `GET /api/profiling/risk/{accused_id}`.
2. `CaseDetailPanel.jsx` — a new lazy-loaded modal with three independently-loading tabs (Timeline, Summary, Similar Cases), backed by the three `decision-support` endpoints.
3. `EvidenceTrail.jsx` — an inline expandable section on `MessageBubble.jsx` showing SQL/evidence metadata for a message, backed by `GET /api/chat/messages/{message_id}/evidence-trail`, with `message_id` sourced via a post-`done` fetch of `GET /api/chat/sessions/{id}/messages`.

The plan explicitly claims zero backend work and zero new dependencies.

---

## Existing Components Available

| Component | Status | Repository Evidence | Notes |
| --------- | ------ | ------------------- | ----- |
| `GET /api/profiling/risk/{accused_id}` | ✅ Live, flat shape confirmed | `backend/routers/profiling.py` — `get_risk_score()` returns `result` (from `compute_risk_for_accused()`) directly, not wrapped | Matches plan's assumed flat dict (`accused_id`, `risk_score`, `risk_tier`, `contributing_factors`) exactly; also cross-checked against `CONTRACTS.md` entry for `compute_risk_for_accused` |
| `GET /api/decision-support/timeline/{case_id}` | ✅ Live | `backend/routers/decision_support.py` — `case_timeline()` returns `{"case_id": ..., "timeline": events}` | Matches `CONTRACTS.md` and plan's `fetchCaseTimeline` usage |
| `GET /api/decision-support/summary/{case_id}` | ✅ Live | `backend/routers/decision_support.py` — `case_summary()` returns `{"case_id": ..., **result}` where `result` is `{"summary": str\|None, "error": str\|None}` from `generate_case_summary()` | Matches plan's `error`-vs-`summary` handling |
| `GET /api/decision-support/similar-cases/{case_id}` | ✅ Live | `backend/routers/decision_support.py` — `similar_cases()` returns `{"case_id": ..., "similar_cases": results}` | Matches `fetchSimilarCases` usage |
| `GET /api/chat/messages/{message_id}/evidence-trail` | ✅ Live | `backend/routers/chat.py` line 340-347 — `message_evidence_trail()`, uses `get_evidence_trail_for_message()` from `db/chat_store.py`, 404 on not-found/not-owned/no-trail | Matches plan's "404 means all three things, UI doesn't distinguish" design |
| All four routers registered | ✅ Confirmed | `backend/main.py` lines 23-24, 90-91 — `decision_support_router` and `profiling_router` both included | No router-registration work needed |
| `firstFirId(tableData)` helper | ✅ Exists | `frontend/src/components/MessageBubble.jsx` lines 14-19 | Confirmed exact contract plan expects `firstAccusedId` to mirror: `Array<object>\|any` in, `number\|null` out, never throws |
| "View network" trigger pattern | ✅ Exists | `MessageBubble.jsx` — `graphAvailable && firstFirId(tableData) != null` gates the button | Confirmed as the pattern plan says `firstAccusedId`/new buttons should mirror |
| `React.lazy()` + `Suspense` modal pattern | ✅ Exists | `frontend/src/components/ChatWindow.jsx` line 19 (`NetworkGraph`), line 20 (`AnalyticsDashboard`); render blocks at lines 617-632 | `CaseDetailPanel` can follow the identical pattern |
| Per-panel independent loading / `Promise.allSettled` philosophy | ✅ Exists | `frontend/src/components/AnalyticsDashboard.jsx` line 52 (`Promise.allSettled`) | Confirms the "don't block on the slowest panel" precedent the plan cites |
| Shared `AuthError` class | ✅ Exists, but see Architecture note below | `frontend/src/api/chat.js` lines 182-186; re-used via `import { AuthError } from './chat'` in `frontend/src/api/analytics.js` line 2, and in `AnalyticsDashboard.jsx` line 12 | The codebase convention is **one shared `AuthError`**, not a new class per file |
| `fetchMessages()` | ✅ Exists | `frontend/src/api/chat.js` line 330 (`export async function fetchMessages(sessionId)`) | Plan's Step 10 correctly reuses this, no new helper needed |
| `updateLastAssistant()` | ✅ Exists | `ChatWindow.jsx` line 200 | Plan's Step 10 correctly reuses this |
| `loadSessionMessages()` message-field mapping | ✅ Exists, needs one added field | `ChatWindow.jsx` lines 328-368 — maps `m.message_id → id`, `m.table_data → tableData`, `m.media_attachments → mediaAttachments`, etc., but **does not currently map `m.message_id → messageId`** | Confirms plan's Step 10 instruction ("add `message_id → messageId` to that same mapping") is necessary, real, and correctly scoped — it is new work, not already done |
| `getToken()` | ✅ Exists | `frontend/src/api/auth.js` line 10 | All three new API files (`profiling.js`, `decisionSupport.js`, `evidenceTrail.js`) can import this as shown in the plan |
| CSS tokens/classes for reuse | ✅ Confirmed present | `frontend/src/styles/main.css`: `--font-mono` (line 51), `.analytics-panel__state` (line 2414), `.analytics-panel__state--error` (line 2421), `.analytics-table` (line 2426), `.analytics-dashboard` z-index tier 900 (line 2321), `.message-action-btn` already used for the "Read aloud" button in `MessageBubble.jsx` | Plan's intent to reuse `.analytics-table` for Similar Cases and `.message-action-btn` for the two new buttons is valid and avoids duplicate styling |
| React version / build tooling | ✅ Compatible | `frontend/package.json` — `"react": "^18.3.1"`, `"react-dom": "^18.3.1"`, `"build": "vite build"` script present | React 18.3 fully supports `React.lazy`/`Suspense`; `npm run build` is a valid verification command per the plan |

---

## Components Requiring New Development

| Component | Purpose | Reason |
| --------- | ------- | ------ |
| `frontend/src/api/profiling.js` | Fetch wrapper for risk endpoint | Does not exist in repository (confirmed via directory listing) |
| `frontend/src/api/decisionSupport.js` | Fetch wrappers for timeline/summary/similar-cases | Does not exist in repository |
| `frontend/src/api/evidenceTrail.js` | Fetch wrapper for evidence-trail endpoint | Does not exist in repository |
| `frontend/src/components/RiskBadge.jsx` | Inline risk pill component | Does not exist in repository |
| `frontend/src/components/EvidenceTrail.jsx` | Inline expandable evidence section | Does not exist in repository |
| `frontend/src/components/CaseDetailPanel.jsx` | Confirmed genuinely absent — plan's own preamble states this correctly | `find`/`ls` over `frontend/src/components/` shows no `CaseDetailPanel.jsx`; plan's claim that `MIGRATE.md §10`'s assumption of pre-existing implementation was incorrect is consistent with what the repository shows |
| `firstAccusedId(tableData)` helper | New parallel helper to `firstFirId` | Confirmed absent from `MessageBubble.jsx`; must be added as new code, mirroring the existing helper's contract |
| `MessageBubble.jsx` prop additions (`onCaseDetailRequest`, `messageId`, `onAuthExpired`) and new local `evidenceOpen` state | Wire new buttons/sections into the bubble | Confirmed `MessageBubble.jsx`'s current prop list (`role, content, tableData, mediaAttachments, graphAvailable, onOpenGraph, suggestedFollowUps, onFollowUpClick, isStreaming, error`) has none of these three new props today |
| `ChatWindow.jsx` modifications: lazy import + state pair for `CaseDetailPanel`, `onDone` post-fetch of `message_id`, `loadSessionMessages` field-mapping addition | Wire the modal and the two `messageId`-sourcing code paths together | Confirmed via direct inspection that none of these three pieces currently exist in `ChatWindow.jsx` |
| CSS additions to `main.css` | Styling for all new UI elements | Confirmed none of the specific new class names (`.risk-badge`, `.case-detail-panel`, `.evidence-trail`, etc.) exist yet in `main.css` |

---

## Backend Readiness

| Item | Status | Repository Evidence | Notes |
| ---- | ------ | ------------------- | ----- |
| Routers | ✅ No changes needed | `backend/main.py` lines 16-24, 83-91 | All eight routers already registered, including `profiling_router` and `decision_support_router` |
| Authentication | ✅ Compatible | `backend/auth/simple_auth.py` — `get_current_officer` used as a `Depends()` on every relevant endpoint in `profiling.py`, `decision_support.py`, and `chat.py`'s evidence-trail route | Frontend's `Authorization: Bearer <token>` header pattern (via `getToken()`) matches what these endpoints expect |
| Authorization / ownership scoping | ✅ Already enforced server-side | `get_evidence_trail_for_message(message_id, officer_id)` in `db/chat_store.py`, per its `CONTRACTS.md` entry, scopes lookups to the requesting officer and returns `None` for not-found/not-owned/no-trail uniformly | This is exactly the 404 behavior the plan's frontend is designed around |
| Dependency Injection | ✅ Consistent | All three routers use `Depends(get_current_officer)` uniformly | No new DI wiring required |
| Async support | ✅ Consistent | All relevant endpoint functions are `async def` calling awaited pipeline functions (`compute_risk_for_accused`, `build_case_timeline`, `generate_case_summary`, `find_similar_cases`) | No async/sync mismatch risk |
| Background jobs | N/A | Not referenced by this step | `POST /api/profiling/recompute-all` exists but plan explicitly excludes it from officer-facing UI |
| Existing APIs | ✅ All four confirmed live and match documented shapes | See "Existing Components Available" table | — |
| Error handling | ✅ Consistent with plan's expectations | `profiling.py`'s `get_risk_score` raises `HTTPException(404, ...)` only when the accused genuinely doesn't exist; `chat.py`'s evidence-trail route raises 404 for three collapsed cases | Matches plan's null-safe frontend handling |
| Logging | ✅ Present, non-blocking | `save_evidence_trail()` (`pipeline/evidence_trail.py`) is documented as non-fatal, logs failures to stderr | Consistent with plan's "message_id-after-done fetch is non-fatal by design" philosophy |

**No missing backend prerequisites were identified.** This confirms the plan's own claim: "This step needs zero backend changes."

---

## Database Readiness

| Item | Status | Repository Evidence | Notes |
| ---- | ------ | ------------------- | ----- |
| Tables referenced (`offender_risk_scores`, `Accused`, `evidence_trail`-backing table) | ⚠ Referenced consistently in code, DDL not present in repository | `backend/routers/profiling.py`, `backend/pipeline/risk_scoring.py`, `backend/db/chat_store.py`, `backend/pipeline/evidence_trail.py` all reference these tables by name | **Unable to verify from the current repository** whether the live schema (stated by the plan to be on AWS RDS) matches these column references exactly, since no schema/migration SQL file was found in the repo. This is out of scope for Step 4 regardless, since Step 4 makes no DB changes. |
| Schema changes required for Step 4 | ✅ None | Plan explicitly states "No backend changes of any kind... no new DDL" and all three consumed endpoints are pre-existing and already tested per `SevenToEight.md` | Confirmed no new queries are introduced by this step — only existing endpoint responses are consumed |
| Indexes required | N/A for this step | Step 4 adds no new queries | — |
| Existing queries support the proposed features | ✅ Yes | `profiling.py`'s `top_risk_offenders` query and `risk_scoring.py`'s `compute_risk_for_accused` already return the exact fields (`risk_score`, `risk_tier`, `contributing_factors`) `RiskBadge.jsx` needs | — |

---

## API Readiness

| Endpoint | Status | Repository Evidence | Notes |
| -------- | ------ | ------------------- | ----- |
| `GET /api/profiling/risk/{accused_id}` | ✅ Live, shape confirmed flat | `backend/routers/profiling.py` lines 22-33 | Step 1's curl check in the plan is still worth running against a live server as a final sanity check, but static code inspection already confirms the flat shape |
| `GET /api/profiling/top-risk` | ✅ Live (not used by Step 4, but confirms profiling.py health) | `backend/routers/profiling.py` lines 36-50 | — |
| `GET /api/decision-support/timeline/{case_id}` | ✅ Live | `backend/routers/decision_support.py` lines 22-25 | — |
| `GET /api/decision-support/summary/{case_id}` | ✅ Live | `backend/routers/decision_support.py` lines 28-31 | — |
| `GET /api/decision-support/similar-cases/{case_id}` | ✅ Live | `backend/routers/decision_support.py` lines 13-19 | — |
| `GET /api/chat/messages/{message_id}/evidence-trail` | ✅ Live | `backend/routers/chat.py` lines 340-347 | — |
| `GET /api/chat/sessions/{id}/messages` (used for post-`done` message_id fetch) | ✅ Live | `frontend/src/api/chat.js` line 330, `fetchMessages()`, already used elsewhere in `ChatWindow.jsx` (`loadSessionMessages`) | Confirmed already exercised in production code paths, not a new endpoint |
| Route conflicts | ✅ None found | No overlapping paths between new frontend fetch targets and any other router | — |
| Request validation | ✅ Consistent | All endpoints use FastAPI path/query params with type hints (`case_id: int`, `limit: int = 5`, etc.) | — |
| Response schema naming consistency | ✅ Consistent | All decision-support endpoints echo `case_id` plus a named payload key (`timeline`, `summary`/`error`, `similar_cases`) | Matches plan's destructuring (`.timeline`, `.summary`, `.similar_cases`) |
| Existing API client compatibility | ✅ Compatible | New API modules follow the same `fetch` + `authHeaders()` + status-code-branching pattern already used in `frontend/src/api/analytics.js` and `frontend/src/api/chat.js` | Structurally consistent, see Architecture Compatibility for one deviation |

---

## Frontend Readiness

| Component | Status | Repository Evidence | Notes |
| --------- | ------ | ------------------- | ----- |
| Pages/Shell | ✅ Unaffected | `frontend/src/components/PortalShell.jsx`, `App.jsx` | Step 4 doesn't touch these |
| `MessageBubble.jsx` | ⚠ Requires modification | Current file confirmed at `frontend/src/components/MessageBubble.jsx` (176 lines) — missing the three new props and `evidenceOpen` state the plan requires | New development, correctly scoped by the plan |
| `ChatWindow.jsx` | ⚠ Requires modification | 639 lines; confirmed missing `CaseDetailPanel` lazy import/state, post-`done` message_id fetch, and `messageId` field mapping | New development, correctly scoped |
| Hooks | ✅ Unaffected | `frontend/src/hooks/useAuth.js` | Not referenced by Step 4 |
| State management | ✅ Compatible | Local `useState`/`useEffect` pattern used throughout (`AnalyticsDashboard.jsx`, `NetworkGraph.jsx`); plan's new components follow the same local-state-only approach, no global store introduced | Consistent with existing architecture |
| API layer | ✅ Compatible (with one convention note) | See Architecture Compatibility below | — |
| Routing | N/A | App has no client-side router state affected by this step | — |
| Lazy loading | ✅ Pattern exists and is directly reusable | `ChatWindow.jsx` lines 19-20, 617-632 | `CaseDetailPanel` plan Step 9 mirrors this exactly |
| Existing modal architecture | ✅ Confirmed reusable | `NetworkGraph` and `AnalyticsDashboard` both use `{condition && <Suspense><Component/></Suspense>}` | `CaseDetailPanel` plan follows identically |
| Existing styling approach | ✅ Confirmed reusable | CSS variables + BEM-like class naming in `main.css` | New class names in plan follow the same naming convention (`.case-detail-panel__header`, etc.) |
| Shared utilities | ✅ `firstFirId` reusable, `firstAccusedId` net-new | `MessageBubble.jsx` lines 14-19 | Confirmed |
| Existing component reuse | ✅ `.analytics-table` reuse for Similar Cases tab is valid | `main.css` line 2426 | Confirmed class exists with appropriate table styling already defined |

---

## Architecture Compatibility

**PASS**, with one minor, non-blocking naming/convention deviation flagged below.

Reasoning:
- Folder structure: new files land in the existing `frontend/src/api/` and `frontend/src/components/` directories, consistent with every other feature area (`analytics.js`/`AnalyticsDashboard.jsx`, `chat.js`/`ChatWindow.jsx`).
- Naming conventions: `camelCase.js` for API modules, `PascalCase.jsx` for components — matches `decisionSupport.js`/`CaseDetailPanel.jsx` naming exactly against existing `voice.js`/`VoiceInput.jsx`, `auth.js`/`LoginPage.jsx`, etc.
- Backend architecture: zero backend changes proposed; existing router/service/pipeline layering is left untouched.
- Frontend architecture: the plan's lazy-loading, per-tab-cache, and `Promise.allSettled`-style independent loading exactly mirror `AnalyticsDashboard.jsx`'s existing pattern (`Promise.allSettled` — `AnalyticsDashboard.jsx` line 52).
- Existing design patterns: `firstAccusedId` is designed as a structural mirror of `firstFirId` (same signature, same null-safety guarantee) — this is a correct, low-risk pattern match, confirmed against the live code in `MessageBubble.jsx`.

**Deviation noted (does not fail the check, but is worth flagging):** The codebase's established convention is a **single shared `AuthError` class**, defined in `frontend/src/api/chat.js` (lines 182-186) and re-exported/imported everywhere else that needs `instanceof AuthError` checks (e.g., `frontend/src/api/analytics.js` line 2: `import { AuthError } from './chat'`; `AnalyticsDashboard.jsx` line 12: `import { AuthError } from '../api/chat'`). `EightToNine.md`'s code for `profiling.js`, `decisionSupport.js`, and `evidenceTrail.js` each defines its **own local** `class AuthError extends Error {}`. This works correctly in isolation (each new component only ever checks `instanceof` against the class from its own sibling API file), so it is **not a functional blocker** — but it introduces three additional, structurally-identical-but-distinct `AuthError` classes where the rest of the codebase uses one. This is a stylistic/architectural inconsistency, not a runtime risk, and does not need to block implementation, but a reviewer may want to have the new files import the shared `AuthError` from `api/chat.js` instead, for consistency.

---

## Dependency Verification

| Dependency | Status | Repository Evidence |
| ---------- | ------ | ------------------- |
| `react` (for `useState`, `useEffect`, `lazy`, `Suspense`) | ✓ Exists | `frontend/package.json` — `"react": "^18.3.1"` |
| `react-dom` | ✓ Exists | `frontend/package.json` — `"react-dom": "^18.3.1"` |
| `getToken` from `api/auth.js` | ✓ Exists | `frontend/src/api/auth.js` line 10 |
| `fetchMessages` from `api/chat.js` | ✓ Exists | `frontend/src/api/chat.js` line 330 |
| Backend endpoints (all four consumed) | ✓ Exist | See "API Readiness" table |
| `vite` build tooling | ✓ Exists | `frontend/package.json` scripts, `frontend/vite.config.js` |
| No new npm packages required | ✓ Confirmed | Plan introduces no new imports beyond React and existing local `api/*` modules; no `package.json` changes proposed or needed |

---

## Risks

### High
None identified.

### Medium
- **`AuthError` class duplication across new API modules** — Functionally safe (each file's `instanceof` check only ever compares against errors thrown by that same file), but introduces three parallel error classes instead of reusing the shared one in `api/chat.js`. Low runtime risk, but a maintainability inconsistency if a future component tries to catch a `profiling.js`-thrown `AuthError` using the class imported from `api/chat.js` — that check would silently fail (`instanceof` false), because they are different classes despite identical names. Rated Medium because this specific failure mode (silent `instanceof` mismatch) is the kind of bug that's easy to introduce later and hard to notice in review.

### Low
- **Live-server verification not performed in this review** — Step 1's curl check against `http://localhost:8000` could not be executed in this static repository review (no running server in this environment). Code-level inspection of `profiling.py` already confirms the flat response shape, so risk of surprise here is low, but it is not equivalent to an actual runtime check.
- **DB schema DDL not present in repository** — Table/column existence for `offender_risk_scores`, `Accused`, and the evidence-trail table is inferred from consistent code references across multiple files, not from a schema file. Irrelevant to Step 4's actual work (no DB changes), but noted for completeness per the review's database-readiness checklist.
- **`message_id`-after-`done` fetch adds one extra network round trip per turn** — By design, per the plan's own reasoning, and explicitly scoped as non-fatal/non-blocking. Minor latency addition only affects when the "Why this answer?" button appears, not the main answer stream.

---

## Hidden Dependencies

- `EvidenceTrail`'s correct behavior on freshly-streamed messages depends on `ChatWindow.jsx`'s `onDone` callback ordering: the plan requires the message_id fetch to happen **after** `bumpSessionMetadata()`/`fetchSessions()` in the existing `onDone` handler (`ChatWindow.jsx` lines 305-315). This ordering is implicit in the plan's prose ("after the existing `onDone` handling completes") rather than being enforced by any test — it's a hidden sequencing dependency to watch during implementation.
- `RiskBadge` and "View case details" both key off table columns (`AccusedMasterID` and `CaseMasterID` respectively) that must co-occur or not, depending on the query — this is a data-shape dependency on whatever SQL the LLM pipeline generates for a given question, not something enforced anywhere in code. Not a blocker, but worth knowing this is inherently query-dependent, matching the plan's own framing ("wherever a query naturally surfaces `AccusedMasterID` rows").

---

## Missing Prerequisites

> No missing prerequisites were identified for implementation to begin.

The one caveat is procedural, not code-related: Step 1's curl-based live verification of the risk endpoint's response shape should still be run against a real running instance before or immediately after `RiskBadge.jsx` is built, per the plan's own instruction — static analysis in this review corroborates the expected flat shape, but a live check is a cheap, explicitly-required confirmation step the plan itself calls out as "not optional."

---

# Expected Results (Predicted)

*The following describes predicted outcomes based on reading `EightToNine.md`. These are not verified functionality — they are the intended behavior if the plan is implemented exactly as written.*

- **Backend capabilities:** Unchanged. No new endpoints, no new DDL, no new router registrations.
- **Frontend capabilities:** Officers would gain three new interactive surfaces — an inline risk pill with an expandable factor breakdown, a tabbed case-detail modal (Timeline/Summary/Similar Cases), and an inline "why this answer" evidence panel — each triggered contextually from existing chat message rows.
- **API behaviour:** The four consumed endpoints would see additional read traffic from the new frontend components but no behavioral change themselves.
- **Database behaviour:** No change — all reads go through already-existing, already-tested query paths.
- **User-visible improvements:** Officers could assess offender risk and case context without leaving the chat interface, and could audit exactly what SQL/data backed any given chat answer.
- **Performance impact:** One additional fetch per finished streaming turn (the post-`done` message_id lookup) and per-tab lazy loads inside the new modal; the plan is designed to avoid blocking the main chat stream or blocking tab switching on the slowest tab (Summary, LLM-backed).
- **Integration outcome:** If built as specified, this would complete all five BLUEPRINT2 feature areas (per the plan's closing section), with all four steps' frontend and backend pieces running against the same deployment.
- **Maintainability improvements:** Consistent helper contracts (`firstAccusedId` mirroring `firstFirId`) and consistent modal/lazy-loading patterns would keep the new code stylistically aligned with the rest of the codebase, aside from the `AuthError` duplication noted above.

---

## Recommended Actions Before Implementation

1. Run Step 1's curl check against a live backend instance to get a live-traffic confirmation of the risk endpoint shape (static analysis already supports it, but the plan itself treats this as mandatory, not optional).
2. Decide whether to keep the plan's three new local `AuthError` classes as-written, or have `profiling.js`, `decisionSupport.js`, and `evidenceTrail.js` import the existing shared `AuthError` from `api/chat.js` for consistency with `analytics.js`'s established pattern. Either choice is functionally safe; this is a style decision, not a blocker.
3. During implementation of Step 8 (`MessageBubble.jsx` wiring), confirm which of `onCaseDetailRequest`, `messageId`, `onAuthExpired` are "already threaded through for the network graph" as the plan hedges — direct inspection in this review found **none** of the three currently passed to `MessageBubble.jsx`, so treat all three as net-new prop wiring, not partial reuse.
4. Preserve the exact `onDone` ordering described in the plan (message_id fetch after existing session-metadata bump) to avoid the hidden sequencing dependency noted above.

---

## Final Verdict

✅ **Ready to begin implementation immediately.**
