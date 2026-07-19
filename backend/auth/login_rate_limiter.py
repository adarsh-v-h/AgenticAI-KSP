"""
Login brute-force rate limiter.

WHY a separate limiter from pipeline/rate_limiter.py:
    The station-wide limiter (pipeline/rate_limiter.py) intentionally exempts
    /api/auth/login (main.py's _RATE_LIMIT_EXEMPT) because it reads the
    station id (unit_id) from the JWT — but there IS no JWT yet at login time.
    A login-specific limiter has to key off something available BEFORE
    authentication: the badge number being attempted.

WHAT THIS PROTECTS AGAINST:
    Officer passwords are currently KGID (badge number) + "123" (see
    migrate_password_hash.py / auth/simple_auth.py::login). That formula is
    guessable from the badge number alone, which is not a secret (it appears
    in the JWT and UI). Without a limiter, an attacker who knows/guesses a
    badge number could script unlimited login attempts. This closes that gap
    by capping attempts per badge number within a rolling window, independent
    of whether the password scheme is later strengthened.

MODEL:
    Fixed window, in-memory, per-instance (no cross-instance sync — login
    volume is low enough that this doesn't need the Cache-backed convergence
    the station limiter uses). Keyed by the *lowercased badge number being
    attempted*, not by IP: the threat is "guess this officer's password",
    which is the same regardless of source IP, and IP-keying would be
    trivially bypassed by rotating source addresses anyway while badge-number
    keying directly protects the actual credential being brute-forced.

FAIL-OPEN:
    Any unexpected internal error in the limiter allows the request through —
    availability for legitimate officers matters more than a perfectly precise
    counter, matching the station limiter's philosophy.
"""

import time
from dataclasses import dataclass

# ── Tunables ────────────────────────────────────────────────────────────────
MAX_ATTEMPTS = 10          # login attempts allowed per badge number per window
WINDOW_SECONDS = 15 * 60   # 15-minute rolling window

# _attempts[badge_number] = {"count": int, "window_start": float}
_attempts: dict[str, dict] = {}


@dataclass
class LoginRateLimitResult:
    """Outcome of a login attempt check. `allowed=False` → caller returns HTTP 429."""
    allowed: bool
    retry_after_seconds: int


# CONTRACT
# takes:  badge_number (str) — the badge number being attempted (case-insensitive key)
# returns: (LoginRateLimitResult) — whether this attempt is allowed, and retry-after if not
# raises:  nothing (fails open on any internal error)
def check_login_attempt(badge_number: str) -> LoginRateLimitResult:
    """
    Call BEFORE verifying credentials for a login attempt. Always increments
    the counter for this badge number (failed and successful attempts both
    count toward the window — this bounds total attempts, not just failures).
    """
    try:
        key = (badge_number or "").strip().lower()
        if not key:
            return LoginRateLimitResult(True, 0)

        now = time.time()
        entry = _attempts.get(key)
        if entry is None or now - entry["window_start"] >= WINDOW_SECONDS:
            entry = {"count": 0, "window_start": now}
            _attempts[key] = entry

        if entry["count"] >= MAX_ATTEMPTS:
            retry_after = max(1, int(entry["window_start"] + WINDOW_SECONDS - now))
            return LoginRateLimitResult(False, retry_after)

        entry["count"] += 1
        return LoginRateLimitResult(True, 0)
    except Exception:  # noqa: BLE001 — never let the limiter block a login
        return LoginRateLimitResult(True, 0)


# CONTRACT
# takes:  badge_number (str) — badge number whose counter should be cleared
# returns: nothing
# raises:  nothing
def reset_login_attempts(badge_number: str) -> None:
    """Call after a SUCCESSFUL login so a legitimate officer isn't left near
    the cap by their own earlier typos."""
    try:
        key = (badge_number or "").strip().lower()
        _attempts.pop(key, None)
    except Exception:  # noqa: BLE001
        pass


# CONTRACT
# takes:  nothing
# returns: nothing (test helper: clears all in-memory state)
# raises:  nothing
def _reset_for_tests() -> None:
    _attempts.clear()
