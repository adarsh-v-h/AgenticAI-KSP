# Implementation Plan - Aggressive Caching at DB Layer

We will implement in-process caching for database queries related to session ownership, conversation message history, and the sidebar sessions list. Since the database is external, this avoids unnecessary round-trips during message turns, significantly reducing latency.

## Proposed Changes

### Database Layer

#### [MODIFY] [chat_store.py](file:///home/venzz/Work/Dataathon/backend/db/chat_store.py)
1. Add an `LRUCache` class using `collections.OrderedDict` to perform $O(1)$ operations with bounded sizes and Time-To-Live (TTL) expiration support:
   - `_session_owner_cache` (`session_id` -> `officer_id`) - capacity 500, TTL 1 hour (ownership is immutable once created).
   - `_session_messages_cache` (`session_id` -> list of messages) - capacity 100, TTL 10 minutes.
   - `_officer_sessions_cache` (`(officer_id, limit)` -> list of sessions) - capacity 100, TTL 5 minutes.
2. Expose a `clear_caches()` function to clear all caches. This is critical for preventing cross-test state leakage.
3. Expose a helper function `_invalidate_officer_sessions(officer_id: int)` to evict any cached sessions lists matching that officer's ID.
4. Implement a new helper `get_session_owner(session_id: str) -> int | None` that reads from `_session_owner_cache` and falls back to a query.
5. Update `verify_session_owner(session_id: str, officer_id: int) -> bool` to use `get_session_owner`.
6. Update `create_session(session_id: str, officer_id: int, title: str) -> bool` to cache session ownership and invalidate the officer's sessions list cache.
7. Update `update_session_timestamp(session_id: str, increment_count: bool = True)` to lookup the session's owner and invalidate their sessions list cache.
8. Update `get_sessions_for_officer(officer_id: int, limit: int = 30) -> list[dict]` to cache results on a miss and read from cache on a hit.
9. Update `get_messages_for_session(session_id: str) -> list[dict]` to cache results on a miss and read from cache on a hit.
10. Update `save_message_pair` to invalidate the messages cache for the corresponding `session_id`.

### Routing / Authorization Layer

#### [MODIFY] [chat.py](file:///home/venzz/Work/Dataathon/backend/routers/chat.py)
Update `_authorize_session_write` to check the `_session_owner_cache` first. On a miss, execute the module's `execute_query` (retaining full compatibility with test monkeypatches) and cache the owner result.

#### [MODIFY] [reports.py](file:///home/venzz/Work/Dataathon/backend/routers/reports.py)
Update the session ownership authorization check in `analyze_report` to check the `_session_owner_cache` first, fall back to the module's `execute_query` on a miss, and cache the owner result.

### Test Configuration

#### [MODIFY] [conftest.py](file:///home/venzz/Work/Dataathon/backend/tests/conftest.py)
Add an autouse fixture `clear_db_caches` that clears all database caches before every test run. This guarantees test isolation.

---

## Verification Plan

### Automated Tests
- Run all existing pytest suites (`.venv/bin/pytest backend/tests/`).
- Create additional unit tests for cache hits, misses, and invalidations to ensure correct cache behavior.

### Manual Verification
- We can run manual requests or print logs showing when DB queries are hit versus when the cache is hit to verify that query count goes to 0 on subsequent turns.
