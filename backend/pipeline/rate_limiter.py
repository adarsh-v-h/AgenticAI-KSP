"""
Station-wide request rate limiting.

WHY per-station (not per-officer):
    Officers at a busy station share the same investigative workload. Rather
    than tracking every individual's quota (heavy, and unfair — one officer may
    need far more than another on a given day), we pool a whole police station's
    (Unit.UnitID) quota. The station's cap scales with how many officers work
    there, so a big station gets a big shared budget.

CAP MODEL:
    cap = PER_OFFICER_QUOTA (25) × active_officer_headcount_at_station
    headcount = SELECT COUNT(*) FROM Employee WHERE UnitID = %s AND is_active = TRUE
    Recomputed periodically in the background, never on the request hot path.

WINDOW:
    Fixed 6-hour tumbling window. window_start = floor(now / 6h). All counting
    keys off (unit_id, window_start); when the window rolls over the counter
    naturally resets because the key changes.

TRUST BOUNDARY:
    unit_id ALWAYS comes from the signed JWT (see auth.simple_auth), NEVER from
    the request body/params. A crafted unit_id in a request cannot drain another
    station's budget.

HOT PATH (check_and_increment):
    Pure in-memory dict lookup + compare + increment. Zero network I/O. Returns
    immediately with allow/deny. This is what the request middleware calls.

BACKGROUND SYNC (async loop, ~30s cadence):
    - Flushes each instance's local increments to Catalyst Cache so multiple
      AppSail instances converge on a shared per-station total.
    - Refreshes station caps from MySQL.
    - Drops stale windows from memory.

    User note: async is fine for now. The public surface here
    (check_and_increment / start / stop) is deliberately small so the background
    machinery can later be reimplemented in C/C++ (pthreads/epoll) without
    touching callers.

FAIL-OPEN:
    If Catalyst Cache is unreachable we log a warning and keep serving off the
    last-known in-memory state. Availability of the tool for officers matters
    more than perfectly precise global counting.
"""

import asyncio
import sys
import time
from dataclasses import dataclass

from config.settings import get
from db.cache_client import get_value, put_value, CacheError

import os

# ── Tunables ────────────────────────────────────────────────────────────────
PER_OFFICER_QUOTA = int(os.getenv("PER_OFFICER_QUOTA", "500")) # requests per officer per window
WINDOW_SECONDS = 6 * 60 * 60    # 6-hour tumbling window
SYNC_INTERVAL_SECONDS = 30      # background flush/refresh cadence
CACHE_EXPIRY_HOURS = 7          # > 6h window so the key survives the whole window

# ── In-memory state ───────────────────────────────────────────────────────────
# _local[unit_id] = {
#     "count":        int,   # best-known total for this window (shared + local)
#     "unflushed":    int,   # local increments not yet pushed to Cache
#     "cap":          int|None,  # None = cap not computed yet → fail-open (allow)
#     "window_start": int,   # epoch-seconds floor of the current window
# }
_local: dict[int, dict] = {}
_lock = asyncio.Lock()          # guards flush/refresh; hot path stays lock-light
_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


# CONTRACT
# takes:  now (float | None) — epoch seconds, defaults to time.time()
# returns: (int) — the start (epoch seconds) of the current 6-hour window
# raises:  nothing
def _current_window_start(now: float | None = None) -> int:
    now = time.time() if now is None else now
    return int(now // WINDOW_SECONDS) * WINDOW_SECONDS


# CONTRACT
# takes:  unit_id (int), window_start (int)
# returns: (str) — the Catalyst Cache key for this station+window counter
# raises:  nothing
def _cache_key(unit_id: int, window_start: int) -> str:
    return f"station:{unit_id}:{window_start}"


@dataclass
class RateLimitResult:
    """Outcome of a hot-path check. `allowed=False` → caller returns HTTP 429."""
    allowed: bool
    unit_id: int
    cap: int | None
    used: int
    window_start: int

    # CONTRACT
    # takes:  nothing
    # returns: (int) — epoch seconds when the current window resets
    # raises:  nothing
    @property
    def reset_at(self) -> int:
        return self.window_start + WINDOW_SECONDS

    # CONTRACT
    # takes:  nothing
    # returns: (int) — seconds until the window resets (>= 1), for Retry-After
    # raises:  nothing
    @property
    def retry_after(self) -> int:
        return max(1, self.reset_at - int(time.time()))


# CONTRACT
# takes:  unit_id (int | None) — the officer's station id from the JWT
# returns: (RateLimitResult) — allow/deny plus counters for the response
# raises:  nothing
#
# Pure in-memory, synchronous, no I/O. Safe to call on every request.
def check_and_increment(unit_id: int | None) -> RateLimitResult:
    """
    The hot path. Called by the request middleware for every /api/* request.

    Behaviour:
      - Unknown/missing unit_id → allow (fail-open; can't fairly attribute it).
      - New station or rolled-over window → fresh counter for the window.
      - cap is None (not yet computed) → allow, but still count so the first
        sync can seed the shared total.
      - count >= cap → DENY (over the station's shared budget).
      - otherwise → increment and allow.
    """
    window_start = _current_window_start()

    import os
    if os.getenv("DISABLE_RATE_LIMIT") == "true":
        return RateLimitResult(True, unit_id or -1, 999999, 0, window_start)

    if unit_id is None:
        return RateLimitResult(True, -1, None, 0, window_start)

    entry = _local.get(unit_id)
    if entry is None or entry["window_start"] != window_start:
        # New station, or the previous window rolled over → reset the counter.
        # Preserve a previously computed cap across a rollover so we don't
        # briefly fail-open every 6 hours while the background loop catches up.
        prev_cap = entry["cap"] if entry else None
        entry = {"count": 0, "unflushed": 0, "cap": prev_cap, "window_start": window_start}
        _local[unit_id] = entry

    cap = entry["cap"]
    if cap is not None and entry["count"] >= cap:
        return RateLimitResult(False, unit_id, cap, entry["count"], window_start)

    entry["count"] += 1
    entry["unflushed"] += 1
    return RateLimitResult(True, unit_id, cap, entry["count"], window_start)


# CONTRACT
# takes:  unit_id (int)
# returns: (int) — cap = 25 × active headcount across unit hierarchy, minimum 25
# raises:  nothing (DB errors are swallowed → caller keeps the old cap)
async def _compute_cap(unit_id: int) -> int:
    from db.connection import execute_query  # local import avoids load-time cycle
    from db.lookup_cache import get_descendant_units_mem

    try:
        descendant_ids = get_descendant_units_mem(unit_id)
        if descendant_ids:
            placeholders = ",".join(["%s"] * len(descendant_ids))
            rows = await execute_query(
                f"SELECT COUNT(*) AS n FROM Employee WHERE UnitID IN ({placeholders}) AND is_active = TRUE",
                tuple(descendant_ids),
            )
            headcount = int(rows[0]["n"]) if rows else 0
        else:
            headcount = 0
    except Exception:
        try:
            rows = await execute_query(
                "SELECT COUNT(*) AS n FROM Employee WHERE UnitID = %s AND is_active = TRUE",
                (unit_id,),
            )
            headcount = int(rows[0]["n"]) if rows else 0
        except Exception:
            headcount = 1

    headcount = max(headcount, 1)
    return headcount * PER_OFFICER_QUOTA


# CONTRACT
# takes:  unit_id (int), entry (dict) — the in-memory counter for that station
# returns: nothing (mutates entry in place)
# raises:  nothing (failures are logged; state left intact → fail-open)
async def _flush_unit(unit_id: int, entry: dict) -> None:
    """
    Converge one station's counter with the shared MySQL total for its window.

    Performs an atomic INSERT ... ON DUPLICATE KEY UPDATE in MySQL to prevent
    concurrency race conditions / lost updates when multiple instances flush
    simultaneously.
    """
    from db.connection import execute_query, execute_write

    window_start = entry["window_start"]
    unflushed = entry["unflushed"]

    try:
        if unflushed > 0:
            await execute_write(
                """INSERT INTO rate_limits (unit_id, window_start, count)
                   VALUES (%s, %s, %s)
                   ON DUPLICATE KEY UPDATE count = count + VALUES(count)""",
                (unit_id, window_start, unflushed)
            )
            # Subtract only what we flushed successfully
            entry["unflushed"] -= unflushed

        # Fetch the shared database total for this station+window
        rows = await execute_query(
            "SELECT count FROM rate_limits WHERE unit_id = %s AND window_start = %s",
            (unit_id, window_start)
        )
        shared = int(rows[0]["count"]) if rows else 0

        # Update local count to be the database baseline + any unflushed increments
        entry["count"] = shared + entry["unflushed"]
    except Exception as e:
        print(f"WARNING: rate_limiter DB flush failed for unit {unit_id}: {e}", file=sys.stderr)


# CONTRACT
# takes:  nothing
# returns: nothing
# raises:  nothing (all errors contained so the loop survives)
async def _sync_once() -> None:
    """One background pass: drop stale windows, refresh caps, flush counters."""
    current_window = _current_window_start()

    async with _lock:
        unit_ids = list(_local.keys())

    for unit_id in unit_ids:
        entry = _local.get(unit_id)
        if entry is None:
            continue

        # Drop counters whose window has fully elapsed (keeps memory bounded).
        if entry["window_start"] < current_window and entry["unflushed"] == 0:
            _local.pop(unit_id, None)
            continue

        # Refresh the cap from MySQL (headcount can change between windows).
        try:
            new_cap = await _compute_cap(unit_id)
            if new_cap > 0:
                entry["cap"] = new_cap
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: rate_limiter cap refresh failed for unit {unit_id}: {e}", file=sys.stderr)

        # Push local increments to the shared Cache total.
        await _flush_unit(unit_id, entry)


# CONTRACT
# takes:  nothing
# returns: nothing (runs until the stop event is set)
# raises:  nothing
async def _sync_loop() -> None:
    assert _stop_event is not None
    while not _stop_event.is_set():
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=SYNC_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass  # normal cadence tick
        if _stop_event.is_set():
            break
        try:
            await _sync_once()
        except Exception as e:  # noqa: BLE001 — the loop must never die
            print(f"WARNING: rate_limiter sync pass failed: {e}", file=sys.stderr)


# CONTRACT
# takes:  nothing
# returns: nothing (spawns the background sync task)
# raises:  nothing
def start_rate_limiter() -> None:
    """Start the background sync loop. Call once from the FastAPI lifespan."""
    global _task, _stop_event
    if _task is not None and not _task.done():
        return

    async def _init_and_start():
        from db.connection import execute_write
        try:
            await execute_write(
                """CREATE TABLE IF NOT EXISTS rate_limits (
                    unit_id INT NOT NULL,
                    window_start INT NOT NULL,
                    count INT NOT NULL,
                    PRIMARY KEY (unit_id, window_start)
                )"""
            )
        except Exception as e:
            print(f"WARNING: Failed to initialize rate_limits table: {e}", file=sys.stderr)
        await _sync_loop()

    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_init_and_start())


# CONTRACT
# takes:  nothing
# returns: nothing (stops the loop and flushes any pending deltas)
# raises:  nothing
async def stop_rate_limiter() -> None:
    """Signal the loop to stop, do a final flush, and await task shutdown."""
    global _task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _task.cancel()
        _task = None
    # Best-effort final flush so a graceful shutdown doesn't lose counts.
    try:
        await _sync_once()
    except Exception:  # noqa: BLE001
        pass
    _stop_event = None


# CONTRACT
# takes:  nothing
# returns: nothing (test/helper: clears all in-memory state)
# raises:  nothing
def _reset_for_tests() -> None:
    _local.clear()
