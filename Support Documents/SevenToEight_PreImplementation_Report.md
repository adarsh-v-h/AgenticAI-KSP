# SevenToEight.md Pre-Implementation Readiness Report

## Executive Summary

**Overall Status:** ⚠ Ready with Minor Fixes

**Overall Readiness Score:** 92/100

**Confidence Level:** 95/100 (every checklist item below was verified directly against source files, not inferred)

---

## Scope Overview

SevenToEight.md ("Step 3") asks for four things: (1) audit-only verification of two already-live features (offender profiling / Part B, similar-cases / Part C), (2) two new read-only case-lookup routes (`case_timeline.py`, `case_summary.py`) added to the existing `routers/decision_support.py`, (3) a new `evidence_trail.py` write path wired into `routers/chat.py`'s `_persist_turn()`, and (4) a new ownership-scoped read endpoint for that evidence trail. No new tables, no new router registrations, no new dependencies.

---

## Existing Components Available

| Component | Status | Repository Evidence | Notes |
|---|---|---|---|
| `risk_scoring.py` / `routers/profiling.py` (Part B) | ✅ Live | `backend/pipeline/risk_scoring.py` (178 lines); `routers/profiling.py` has `_PLACEHOLDER_NAMES` exclusion and `MIN(AccusedMasterID)`/`GROUP BY AccusedName` dedup exactly as the doc describes | Matches doc's claim precisely |
| `similar_cases.py` + `similar-cases` route (Part C) | ✅ Live | `backend/pipeline/similar_cases.py` implements all four signals (+40/+25/+15/+20) via `AccusedName` set-intersection, no `case_relationships` table reference | Matches doc's claim precisely |
| `routers/decision_support.py` | ✅ Exists, registered | `main.py:90` `app.include_router(decision_support_router)` | New timeline/summary routes slot in without touching `main.py` |
| `routers/chat.py` + `_persist_turn()` | ✅ Exists | `chat.py:106-152`, calls `save_message_pair(...)` (currently return value discarded) | See Risks — return value needs capturing |
| `db.chat_store.save_message_pair` | ✅ Returns assistant `message_id` | `chat_store.py:145-188`, `return assistant_id` | Confirms doc's core wiring assumption |
| `pipeline.media_resolver.collect_case_master_ids` | ✅ Exists, public, single existing caller | `media_resolver.py:17`, used by `query_pipeline.py:397` | Signature (`list[dict] -> list[int]`) matches `evidence_trail.py`'s intended use |
| `pipeline.sql_validator._extract_tables` | ✅ Exists, private, single caller | `sql_validator.py:115`, called at `sql_validator.py:179` inside `validate_sql()` | Confirmed no other internal callers — safe to rename/promote |
| `llm.client.call_llm` / `LLMError` / `MODEL_ANSWER` interface | ✅ Exists | `llm/client.py:100`, signature `(model_key, prompt, system_prompt, max_tokens=4000)` | Matches doc's call exactly, including argument order |
| `chat_evidence_trail` table | ✅ Exists in DDL | `backend/db/schema.sql:313-321`, columns `trail_id, message_id, sql_executed, tables_queried, row_count, case_ids_referenced, created_at` | Column is already `case_ids_referenced`, not `fir_ids_referenced` — confirms doc's claim, no DDL work needed |
| `CaseMaster`, `Accused`, `Victim`, `ArrestSurrender`, `CrimeSubHead`, `CaseStatusMaster`, `Unit` tables | ✅ Exist, schema-verified | `schema.sql` lines 90-260 | All columns referenced in the doc's SQL (`IncidentFromDate`, `CrimeRegisteredDate`, `AccusedName`, `CrimeHeadName` on `CrimeSubHead`, `CaseStatusName`, `UnitName`) exist exactly as named |
| `auth.role_guard.log_action` | ✅ Exists | `role_guard.py:41`, signature `(officer_id, action, resource_type=None, resource_id=None, ...)` | Matches the doc's "optional audit logging" snippet exactly |
| `main.py` router registrations | ✅ Both target routers already registered | `main.py:85` (`chat_router`), `main.py:90` (`decision_support_router`) | Confirms "no new `main.py` registrations" claim |

---

## Components Requiring New Development

| Component | Purpose | Reason |
|---|---|---|
| `backend/pipeline/case_timeline.py` | Chronological case event builder | Confirmed absent — `ls backend/pipeline/` shows no such file |
| `backend/pipeline/case_summary.py` | LLM case brief | Confirmed absent |
| `backend/pipeline/evidence_trail.py` | Evidence-trail write path | Confirmed absent |
| `CASE_SUMMARY_SYSTEM_PROMPT` + `build_case_summary_prompt()` in `llm/prompts.py` | Prompt plumbing for case summary | `llm/prompts.py` currently has `SQL_`, `ANSWER_`, `CORRECTION_`, `ROUTER_`, `DIRECT_ANSWER_` prompts only — no case-summary prompt yet |
| `get_evidence_trail_for_message()` in `db/chat_store.py` | Ownership-scoped read query | Not present in current `chat_store.py` |
| `GET /api/chat/messages/{message_id}/evidence-trail` route | Read endpoint | Not present in `routers/chat.py` |
| `extract_tables()` rename in `sql_validator.py` | Public helper for `evidence_trail.py` | Currently private `_extract_tables()` |

---

## Backend Readiness

| Item | Status | Repository Evidence | Notes |
|---|---|---|---|
| Routers | ✅ Ready | `decision_support.py`, `chat.py` both registered and importable | No structural change needed |
| Async support | ✅ Ready | All target functions (`execute_query`, `execute_write`, `call_llm`) are already `async def` | Consistent with codebase-wide `async`/`await` pattern |
| DB connection layer | ✅ Ready | `db/connection.py` exposes `execute_query` and `execute_write` with the exact signatures the doc's new modules call | `execute_write` raises on non-INSERT/UPDATE — doc's `INSERT INTO chat_evidence_trail` is compliant |
| Auth/authorization pattern | ✅ Ready | `get_current_officer` used consistently; `officer["officer_id"]` key confirmed at `auth/simple_auth.py:152` | New routes use the identical dependency-injection pattern as every existing route |
| Error handling / non-fatal write convention | ✅ Ready, precedent exists | `chat_store.py`'s functions and `role_guard.py`'s `log_action` both catch-and-log rather than raise | `evidence_trail.py`'s try/except-and-log design matches established codebase convention |
| Logging | ✅ Ready | `_log()` pattern (`print(..., file=sys.stderr, flush=True)`) used in both `chat.py` and would-be `evidence_trail.py` | Consistent style |

---

## Database Readiness

| Item | Status | Repository Evidence | Notes |
|---|---|---|---|
| `chat_evidence_trail` schema | ✅ No changes needed | `schema.sql:313-321` | Table and all needed columns already exist; doc's premise confirmed |
| `CaseMaster`/`ArrestSurrender`/`Accused`/`Victim` columns for timeline & summary | ✅ Sufficient | `schema.sql:146-221` | All referenced columns exist; no `ChargesheetDetails` dependency introduced, consistent with doc's explicit avoidance of that deferred table |
| Foreign key path for ownership scoping | ✅ Present | `chat_messages.session_id → chat_sessions.session_id`, `chat_sessions.officer_id → Employee` (`schema.sql:274-303`) | Supports the `JOIN chat_messages → chat_sessions` ownership query in the doc's `get_evidence_trail_for_message()` |
| New indexes needed | Not required | `chat_evidence_trail` already has `INDEX idx_trail_message (message_id)` | Doc's read query filters on `message_id`, already indexed |
| Migrations | Not required | Doc explicitly states no DDL; confirmed by schema already containing the target table | — |

---

## API Readiness

| Endpoint | Status | Repository Evidence | Notes |
|---|---|---|---|
| `GET /api/decision-support/timeline/{case_id}` | New, no conflict | No existing route with this path in `decision_support.py` | Safe to add |
| `GET /api/decision-support/summary/{case_id}` | New, no conflict | Same file, only existing route is `similar-cases/{case_id}` | Safe to add |
| `GET /api/chat/messages/{message_id}/evidence-trail` | New, no conflict | `chat.py` currently has session/message routes but nothing under `/evidence-trail` | Safe to add |
| Naming consistency | ✅ Pass | New routes follow the `/api/<domain>/<resource>/{id}` pattern used everywhere else | — |

---

## Frontend Readiness

Not applicable — the doc explicitly scopes frontend work (`RiskBadge.jsx`, `EvidenceTrail.jsx`, `CaseDetailPanel.jsx` wiring) out of Step 3 and into Step 4. No frontend files were reviewed against this document for that reason, per the doc's own stated scope.

---

## Architecture Compatibility

**PASS**

New backend modules follow the existing `pipeline/*.py` single-responsibility-module pattern (one file, one concern, imported into a router). New routes are added inside already-registered router files rather than creating new routers, matching the doc's own stated constraint and the codebase's existing practice (e.g., `similar-cases` living alongside what will become `timeline`/`summary` in the same file). The proposed `extract_tables()` promotion mirrors an already-completed identical pattern (`collect_case_master_ids()`'s promotion, per `Docs.md` §3.13) — this is not a novel refactor, it's a repeat of an established pattern in this codebase.

---

## Dependency Verification

| Dependency | Status | Repository Evidence |
|---|---|---|
| `fastapi` | ✓ Exists | `requirements.txt: fastapi==0.115.0` |
| `aiomysql` | ✓ Exists | `requirements.txt: aiomysql==0.2.0` |
| `pydantic` | ✓ Exists | `requirements.txt: pydantic==2.8.2` |
| Python 3.10+ syntax (`str \| None`, `list[dict]`) | ✓ Supported | `Dockerfile: FROM python:3.11-slim`; this syntax already used throughout `media_resolver.py`, `chat_store.py` | No new language-version dependency introduced |
| No new third-party packages required | ✓ Confirmed | Doc's new modules only import from existing internal packages (`db.connection`, `pipeline.sql_validator`, `pipeline.media_resolver`, `llm.client`, `llm.prompts`) | — |

---

## Risks

### High

- None identified.

### Medium

- **`chat_store` is not imported as a module in `routers/chat.py`.** The doc's Step 9 snippet calls `chat_store.get_evidence_trail_for_message(...)` and states "`chat_store` to already be imported (it is)." This is only partially accurate: `chat.py` currently does `from db.chat_store import (create_session as create_chat_session_row, update_session_timestamp, save_message_pair, get_sessions_for_officer, get_messages_for_session, verify_session_owner)` — i.e., specific names, not the module itself (`chat.py:28-35`). Implementing the doc verbatim (`chat_store.get_evidence_trail_for_message(...)`) will raise `NameError: name 'chat_store' is not defined`. Fix is trivial (add `get_evidence_trail_for_message` to the existing import tuple, or add `from db import chat_store`), but it is a real discrepancy between the doc's stated assumption and the actual import style, worth flagging before implementation rather than discovering at runtime.
- **`_persist_turn()`'s current call to `save_message_pair()` discards its return value.** The doc's snippet assumes a line `message_id = await chat_store.save_message_pair(...)` already exists; the actual code (`chat.py:138-149`) calls it without capturing the return. This isn't a blocker (`save_message_pair` does return `assistant_id`, confirmed at `chat_store.py:184`), but it means Step 8 requires editing that existing call site to add an assignment, not just inserting a new line after it as the doc's diff-style snippet implies.

### Low

- **`CrimeSubHead.CrimeHeadName` naming.** The doc's `case_summary.py` query selects `csh.CrimeHeadName` from `CrimeSubHead` (aliased `csh`) — this column does exist on that table (`schema.sql:90-96`), but the column name is a pre-existing schema quirk (a "head name" column on the "sub-head" table) unrelated to this doc. Not a blocker, just worth an implementer double-checking they're not confusing it with `CrimeHead.CrimeHeadName` on the different `CrimeHead` table.

---

## Hidden Dependencies

- `save_evidence_trail()`'s no-op behavior for DIRECT-path turns depends on `PipelineResponse.sql_generated` defaulting to `""` (confirmed at `query_pipeline.py:91`), which is falsy in Python — this is what makes `if not sql_generated: return` correctly skip DIRECT-path turns without extra type checking. This dependency is implicit in the doc but does hold up against the actual dataclass default.
- The evidence-trail read endpoint's 404-not-403 behavior depends on `get_evidence_trail_for_message()` returning `None` uniformly for "doesn't exist," "wrong officer," and "no trail row" — the doc's proposed SQL (`JOIN chat_messages → chat_sessions WHERE ... AND cs.officer_id = %s`) does produce that uniform empty-result behavior, consistent with the existing `verify_session_owner()` 404 pattern at `chat.py:159-181`.

---

## Missing Prerequisites

> No missing prerequisites were identified. All modules, functions, tables, and columns the doc assumes to exist were verified present in the current repository.

---

## Expected Results (Predicted)

*These are predicted outcomes based on the implementation plan, not verified functionality — nothing in Step 3 has been built yet.*

- **Backend:** Three new read endpoints (`timeline`, `summary`, `evidence-trail`) and one new write path (evidence-trail insert on every SQL-path chat turn) become live inside already-running routers.
- **Database:** `chat_evidence_trail` — currently empty per the doc's premise — would begin accumulating one row per SQL-executing chat turn.
- **API behavior:** Existing endpoints (chat, analytics, audit-log, profiling, similar-cases) should be unaffected since no shared code paths are modified except `_persist_turn()`, and that change is additive (one new function call after an existing one).
- **User-visible improvement:** None in Step 3 itself — doc explicitly defers all UI surfacing to Step 4.
- **Maintainability:** `extract_tables()` promotion removes upcoming duplicate-parser risk by giving `evidence_trail.py` a shared implementation instead of a second regex parser.

---

## Recommended Actions Before Implementation

1. Resolve the `chat_store` import discrepancy — decide whether to import the module (`from db import chat_store`) or add `get_evidence_trail_for_message` to the existing named-import tuple in `chat.py`, before writing the new route.
2. When editing `_persist_turn()`, explicitly capture `save_message_pair()`'s return value into `message_id` — this is an edit to an existing line, not a pure insertion.
3. Otherwise, proceed directly with Steps 3–9 as written; no other blockers were found.

---

## Final Verdict

⚠ **Resolve the listed issues before implementation.**

Both issues are minor (one incorrect assumption about an existing import statement, one incomplete diff instruction) and are fixable in under five minutes each. No significant architectural issues, missing dependencies, schema gaps, or route conflicts were found. The project is otherwise technically prepared for the implementation described in SevenToEight.md.
