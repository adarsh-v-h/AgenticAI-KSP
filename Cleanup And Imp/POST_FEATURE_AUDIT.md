# Post-Feature Codebase Audit Checklist
> Run this after every feature implementation. Go through every section. Do not skip sections because they "seem fine." The goal is zero dead weight and zero structural debt left behind.

**Stack:** Vite + React · FastAPI · MySQL · NoSQL (document/cache store) · Conversational AI  
**Trigger:** After any new feature is merged or implemented via AI assistance.

---

## How to Use This Document

Paste this entire file into your AI assistant with the instruction:

> "Audit the entire codebase using every item in this checklist. For each issue found, show me: (1) the file and line, (2) what the problem is, (3) the fix. Do not summarize — go file by file."

Then apply fixes, re-run, and repeat until the AI reports zero findings.

---

## SECTION 1 — Dead Code & Unused Artifacts

### 1.1 Unused Imports
- [ ] Scan every `.tsx`, `.ts`, `.jsx`, `.js` file for imports that are never referenced in the file body.
- [ ] Scan every `.py` file for `import` and `from ... import` statements where the imported name is never used.
- [ ] Check for wildcard imports (`from module import *`) — identify exactly what is actually used and replace with explicit imports.

### 1.2 Unused Variables & Constants
- [ ] Find all variables declared but never read (including `const`, `let`, Python locals, module-level constants).
- [ ] Find all environment variables referenced in code but not defined in `.env` / `.env.example`, and vice versa — `.env` keys that nothing reads.
- [ ] Find Python function arguments that are accepted but never used inside the function body (consider `_` prefix or removal).

### 1.3 Unreachable & Dead Functions
- [ ] Find all functions/methods defined but never called anywhere in the codebase (not exported, not called internally, not referenced in routes).
- [ ] Find all React components defined but never rendered anywhere (not in JSX, not in lazy imports, not in route configs).
- [ ] Find all FastAPI route handler functions that are defined but the route is not registered (`@router.get(...)` decorator missing or router not included in the app).
- [ ] Find all Pydantic models defined but never used as a type annotation, `response_model`, or `request body`.
- [ ] Find all SQLAlchemy / ORM models or raw table definitions that no query, route, or service touches.
- [ ] Find all helper/utility functions that were created for a previous approach and replaced — check if the old version still exists alongside the new one.

### 1.4 Dead Routes
- [ ] List all FastAPI routes. Cross-check each against the React frontend — identify routes the frontend never calls.
- [ ] List all React Router routes. Identify pages/components that no navigation, link, or redirect ever points to.
- [ ] Find all API endpoint URLs hardcoded in the frontend and verify each still exists on the backend.

### 1.5 Unused Files
- [ ] Find `.py` files that are never imported by anything.
- [ ] Find `.tsx`/`.ts`/`.jsx`/`.js` files that are never imported and not entry points.
- [ ] Find CSS/SCSS files or Tailwind config entries that no component references.
- [ ] Find migration files that were created and then superseded — verify they were actually applied and are not duplicated.
- [ ] Find config files (e.g., `vite.config.ts` plugins, FastAPI middleware registrations) for features that no longer exist.

### 1.6 Commented-Out Code
- [ ] Find all blocks of commented-out code (not documentation comments). Remove them. If they need to be preserved, move them to a git branch or a `DEPRECATED.md` note instead.

---

## SECTION 2 — Redundancy & Duplication

### 2.1 Duplicate Logic
- [ ] Find functions that do the same thing under different names — common after AI adds a "new" helper that already existed.
- [ ] Find identical or near-identical API call patterns repeated in multiple React components instead of being in a shared hook or service.
- [ ] Find the same SQL query or NoSQL query written inline in multiple places — extract to a repository/service function.
- [ ] Find the same prompt template or system prompt string duplicated across multiple files — centralize into a constants file.
- [ ] Find the same validation logic written both on the frontend (React) and the backend (FastAPI/Pydantic) in inconsistent ways — align them and remove redundancy where the backend is the source of truth.

### 2.2 Duplicate State
- [ ] Find the same piece of data stored in both React component state and a global store (Zustand/Redux/Context) simultaneously — pick one owner.
- [ ] Find the same data fetched by multiple sibling components independently when it could be fetched once by a parent or shared store.
- [ ] Find any conversation/session state that is tracked in both the frontend and duplicated in the NoSQL store without a clear sync strategy.

### 2.3 Duplicate Type Definitions
- [ ] Find TypeScript interfaces or types that describe the same shape as a Pydantic model but are defined separately and have drifted out of sync.
- [ ] Find the same enum or constant defined in both Python and TypeScript — establish a single source of truth (e.g., generate TS types from Python models or maintain a shared constants file).

### 2.4 Duplicate Database Concerns
- [ ] Find MySQL tables or columns that store the same logical data as a field in the NoSQL store without a documented reason.
- [ ] Find soft-delete patterns inconsistently applied — some tables use `deleted_at`, others use `is_deleted` bool, others just hard-delete.

---

## SECTION 3 — Structural & Architectural Issues

### 3.1 Python / FastAPI Structure
- [ ] Verify that business logic is not written directly inside route handler functions — routes should only parse input, call a service, and return output. Extract any inline logic to a service layer.
- [ ] Verify that database session management follows one consistent pattern (e.g., `Depends(get_db)`) and is not mixed with manual session creation inside functions.
- [ ] Find any `try/except` blocks that silently swallow exceptions (`except: pass` or `except Exception: pass`) — replace with proper logging and re-raise or return structured error responses.
- [ ] Find any hardcoded configuration values (URLs, credentials, timeouts, model names, prompt lengths) inside route handlers or service functions — move to config/settings.
- [ ] Find any synchronous blocking I/O calls (e.g., `requests.get`, `time.sleep`) inside `async def` route handlers — replace with `httpx.AsyncClient`, `asyncio.sleep`, etc.
- [ ] Find circular imports between Python modules and resolve with restructuring or deferred imports.
- [ ] Verify all FastAPI routers have consistent prefix and tag naming, and are registered in a single `main.py` or `app.py` — not scattered.

### 3.2 React / Vite Structure
- [ ] Find components that are doing too many things (fetching data, managing complex local state, AND rendering UI) — split into container/presentational or use custom hooks.
- [ ] Find all `useEffect` hooks with missing or incorrect dependency arrays — this is the most common AI-introduced bug in React.
- [ ] Find `useEffect` hooks that exist only to sync one piece of state to another piece of state — replace with derived state or `useMemo`.
- [ ] Find all `any` type annotations in TypeScript files — replace with proper types.
- [ ] Find props being drilled more than 2 levels deep — consider Context, Zustand, or restructuring.
- [ ] Find inline arrow functions passed as props inside JSX that cause unnecessary re-renders — extract or memoize.
- [ ] Find `useCallback` or `useMemo` used without a performance reason (premature optimization adds noise — remove if there is no measurable benefit).
- [ ] Find all hardcoded API base URLs, model names, or configuration strings in component files — move to `constants.ts` or `env`.
- [ ] Verify that loading states, error states, and empty states are handled for every data-fetching operation — AI often implements the happy path only.

### 3.3 Conversational AI Specific
- [ ] Find all locations where the AI system prompt or prompt template is constructed — verify they are built in one place and not assembled differently in multiple locations.
- [ ] Find any message history or context window management logic — verify there is a single, consistent truncation/pruning strategy, not multiple ad-hoc approaches.
- [ ] Find any streaming response handling code — verify it correctly handles partial chunks, connection drops, and cleanup on component unmount.
- [ ] Find all token counting or length-checking logic — verify it uses one consistent method, not a mix of character counts and token estimates.
- [ ] Find any retry logic for AI API calls — verify it has exponential backoff and a max retry limit, not infinite loops.
- [ ] Find any places where raw user input is inserted directly into a prompt without sanitization — flag these for review.
- [ ] Find any conversation session IDs or user IDs used to key NoSQL documents — verify the key schema is consistent across all write/read operations.

### 3.4 Database & Data Layer
- [ ] Find all raw SQL strings in Python code — verify they use parameterized queries (never f-strings or `.format()` with user input).
- [ ] Find all MySQL queries that load entire rows or tables when only specific columns are needed — add column selection.
- [ ] Find missing indexes: any column used in a `WHERE`, `JOIN`, or `ORDER BY` clause in a frequent query that does not have an index.
- [ ] Find NoSQL queries that use full collection scans — verify indexes exist for frequent query patterns.
- [ ] Find any N+1 query patterns: a query inside a loop where a single batched query could replace it.
- [ ] Find database connection logic that is not using connection pooling — verify the pool is configured and reused.
- [ ] Find any migration scripts that alter data (not just schema) and verify they are idempotent.
- [ ] Verify that all NoSQL document schemas used in the conversational AI (conversation history, sessions, user context) have a consistent, documented structure — AI assistants frequently add fields inconsistently over time.

---

## SECTION 4 — Merge & Consolidation Opportunities

### 4.1 Functions That Should Be Merged
- [ ] Find pairs of functions that are always called together — consider merging into one.
- [ ] Find functions that are wrappers around other functions with no added logic — remove the wrapper.
- [ ] Find utility functions that are slight variations of each other (e.g., `formatDate` and `formatDateWithTime`) — unify with an options parameter.

### 4.2 Files That Should Be Merged or Split
- [ ] Find files with a single tiny function that could live in an existing utilities file.
- [ ] Find files that have grown beyond a single responsibility — split them.
- [ ] Find `types.ts` / `interfaces.ts` / `models.py` files that have become dumping grounds — organize by domain.

### 4.3 Hooks & Services That Can Be Shared
- [ ] Find two or more React components that contain nearly identical `useEffect` + `useState` fetch logic — extract to a shared `useXxx` hook.
- [ ] Find FastAPI routes in different routers that use the same service call pattern — extract to a shared service function.

---

## SECTION 5 — Code Quality & Simplification

### 5.1 Overly Complex Logic
- [ ] Find any function longer than 50 lines — it almost certainly does more than one thing. Break it up.
- [ ] Find deeply nested conditionals (more than 3 levels) — flatten using early returns or guard clauses.
- [ ] Find any boolean logic that took you more than 5 seconds to parse — simplify or add a named variable that describes the condition.
- [ ] Find any regex pattern used more than once without being defined as a named constant.

### 5.2 Replaceable Patterns
- [ ] Find manual array loops that can be replaced with `.map()`, `.filter()`, `.reduce()`, or list comprehensions.
- [ ] Find Promise chains (`.then().then()`) that can be replaced with `async/await`.
- [ ] Find repeated `if/else if` chains checking the same variable that can be replaced with a lookup object/dict or `match` statement (Python 3.10+).
- [ ] Find any `setTimeout(..., 0)` hacks in React — these usually indicate a state update timing problem that should be solved properly.
- [ ] Find manual deep-clone patterns (`JSON.parse(JSON.stringify(...))`) — replace with `structuredClone()` or a proper utility.
- [ ] Find any `console.log`, `print()`, or debug statements left in the code — remove or replace with proper logging.

### 5.3 Error Handling Consistency
- [ ] Verify that FastAPI returns consistent error response shapes across all endpoints (same JSON structure for 400, 404, 500 errors).
- [ ] Verify that the React frontend has one centralized error handler for API failures, not ad-hoc `catch` blocks that each show different error UI.
- [ ] Find any unhandled promise rejections in the frontend (`.then()` without `.catch()`, or `async` functions without try/catch).
- [ ] Find async FastAPI route handlers that don't properly handle and return errors from downstream AI API calls (timeouts, rate limits, content policy errors).

---

## SECTION 6 — Security & Safety (Quick Pass)

- [ ] Find any API keys, secrets, or credentials hardcoded in any file — move to environment variables immediately.
- [x] ~~Find any FastAPI routes that are missing authentication/authorization checks that should have them — AI often skips auth when adding new endpoints.~~ **FIXED:** All session-referencing routes now enforce object-level authorization (BOLA/IDOR mitigation). Read paths (`GET .../messages`, `POST .../export`) verify ownership via `verify_session_owner` → 404 on mismatch. Write paths (`POST /api/chat`, `GET /api/chat/stream`, `POST /api/reports/analyze`) check ownership before expensive work, reusing the existence result to avoid duplicate queries. Tested in `test_session_authz.py` (6 tests).
- [ ] Find any MySQL queries built with string concatenation involving user-supplied values — parameterize them.
- [ ] Find any CORS configuration that uses `allow_origins=["*"]` in a non-development context — restrict it.
- [ ] Find any NoSQL keys that include unescaped user input directly — sanitize or hash them.
- [ ] Find any places where full conversation history (potentially containing PII) is logged to stdout or a log file without redaction.

---

## SECTION 7 — Consistency Audit

- [ ] Verify naming conventions are consistent: `camelCase` for JS/TS variables and functions, `snake_case` for Python, `PascalCase` for React components and TypeScript interfaces/types.
- [ ] Verify API response field names use a consistent casing convention (choose `snake_case` or `camelCase` and apply it everywhere — do not mix).
- [ ] Verify date/time values are stored and returned in a consistent format (preferably ISO 8601 UTC everywhere).
- [ ] Verify that all API endpoints follow a consistent REST or RPC naming pattern — no mix of `/getUser`, `/users/{id}`, and `/user/fetch`.
- [ ] Verify that pagination is implemented consistently across all list endpoints (same parameter names: `page`/`limit` or `cursor`/`after` — not a mix).
- [ ] Verify all React components use either all function declarations or all arrow functions — not a mix.
- [ ] Verify that one state management approach is used consistently (not a mix of Zustand + Context + local useState for the same category of state).

---

## SECTION 8 — Dependency & Configuration Hygiene

- [ ] Run `npm ls` or check `package.json` — find packages that are installed but not imported anywhere in the codebase.
- [ ] Check `requirements.txt` or `pyproject.toml` — find packages that are listed but not imported anywhere.
- [ ] Find any package that is used in only one place for a utility function that could be written natively (e.g., a full date library imported just for one `format()` call).
- [ ] Find duplicate functionality across packages (e.g., two different HTTP client libraries, two different date libraries).
- [ ] Verify `vite.config.ts` aliases and plugins are all still relevant — remove any added for a feature that was removed.
- [ ] Verify that `tsconfig.json` `paths` entries all point to directories/files that actually exist.

---

## Final Checklist Before Signing Off

After the AI has addressed all findings above, do a final pass:

- [ ] The codebase builds without errors or warnings (`npm run build`, `python -m py_compile` or equivalent).
- [ ] No TypeScript errors (`tsc --noEmit`).
- [ ] No unused exports remain (run a linter pass: `eslint --rule 'no-unused-vars: error'` equivalent).
- [ ] Git diff of this audit session shows only removals, simplifications, or consolidations — no unintended behavior changes.
- [ ] All API contracts between frontend and backend are still intact (smoke-test the main conversational flow end-to-end).

---

*This document should be version-controlled alongside your codebase and updated whenever your stack or architectural patterns evolve.*
