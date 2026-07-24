"""
Unit tests for the station-wide rate limiter (pipeline/rate_limiter.py).

Focus is the hot path (check_and_increment) and the flush/convergence logic,
both of which are pure/mockable and don't need a live DB or Catalyst Cache.

Run: pytest backend/tests/test_rate_limiter.py -v
"""

import asyncio
import os
from unittest.mock import AsyncMock, patch
# pyrefly: ignore [missing-import]
import pytest

os.environ["APP_SECRET_KEY"] = "test_secret_key_for_testing_purposes"

from pipeline import rate_limiter as rl


@pytest.fixture(autouse=True)
def _clean_state():
    """Every test starts with an empty in-memory counter table."""
    rl._reset_for_tests()
    yield
    rl._reset_for_tests()


class TestCheckAndIncrement:
    def test_missing_unit_id_fails_open(self):
        # No station attributable → allow, never block a request we can't scope.
        result = rl.check_and_increment(None)
        assert result.allowed is True
        assert result.cap is None

    def test_first_request_allowed_and_counts(self):
        result = rl.check_and_increment(42)
        assert result.allowed is True
        assert result.used == 1

    def test_cap_none_still_allows_and_counts(self):
        # Cap not computed yet (background loop hasn't run) → allow but count so
        # the first sync can seed the shared total.
        for i in range(1, 6):
            result = rl.check_and_increment(7)
            assert result.allowed is True
            assert result.used == i

    def test_blocks_when_over_cap(self):
        rl.check_and_increment(1)  # create entry
        rl._local[1]["cap"] = 3
        rl._local[1]["count"] = 0
        # 3 allowed...
        assert rl.check_and_increment(1).allowed is True
        assert rl.check_and_increment(1).allowed is True
        assert rl.check_and_increment(1).allowed is True
        # ...4th blocked
        blocked = rl.check_and_increment(1)
        assert blocked.allowed is False
        assert blocked.used == 3
        assert blocked.cap == 3

    def test_separate_stations_have_separate_budgets(self):
        rl.check_and_increment(1)
        rl._local[1]["cap"] = 1
        rl._local[1]["count"] = 1  # station 1 maxed
        assert rl.check_and_increment(1).allowed is False
        # Station 2 untouched.
        assert rl.check_and_increment(2).allowed is True

    def test_window_rollover_resets_count_but_keeps_cap(self):
        rl.check_and_increment(5)
        rl._local[5]["cap"] = 100
        rl._local[5]["count"] = 100
        assert rl.check_and_increment(5).allowed is False
        # Simulate the window having rolled over.
        rl._local[5]["window_start"] -= rl.WINDOW_SECONDS
        after = rl.check_and_increment(5)
        assert after.allowed is True       # fresh window
        assert after.used == 1
        assert after.cap == 100            # cap carried across the rollover


class TestResultHelpers:
    def test_reset_at_and_retry_after(self):
        result = rl.check_and_increment(9)
        assert result.reset_at == result.window_start + rl.WINDOW_SECONDS
        assert 0 < result.retry_after <= rl.WINDOW_SECONDS


class TestWindowMath:
    def test_window_start_is_aligned(self):
        ws = rl._current_window_start(now=rl.WINDOW_SECONDS * 3 + 123)
        assert ws == rl.WINDOW_SECONDS * 3

    def test_cache_key_shape(self):
        assert rl._cache_key(12, 3600) == "station:12:3600"


class TestFlush:
    def test_flush_converges_with_shared_total(self):
        async def scenario():
            ws = rl._current_window_start()
            entry = {"count": 5, "unflushed": 5, "cap": 100, "window_start": ws}
            with patch("db.connection.execute_write", new=AsyncMock(return_value=1)) as pw, \
                 patch("db.connection.execute_query", new=AsyncMock(return_value=[{"count": 15}])):
                await rl._flush_unit(1, entry)
            # new shared = 15; local adopts it, unflushed cleared.
            assert entry["count"] == 15
            assert entry["unflushed"] == 0
            pw.assert_awaited_once()

        asyncio.run(scenario())

    def test_flush_fails_open_on_db_error(self):
        async def scenario():
            ws = rl._current_window_start()
            entry = {"count": 5, "unflushed": 5, "cap": 100, "window_start": ws}
            with patch("db.connection.execute_write", new=AsyncMock(side_effect=Exception("down"))):
                await rl._flush_unit(1, entry)
            # Unflushed delta preserved for retry; nothing crashed.
            assert entry["unflushed"] == 5

        asyncio.run(scenario())

    def test_compute_cap_multiplies_headcount(self):
        async def scenario():
            # _compute_cap imports execute_query locally from db.connection.
            with patch("db.connection.execute_query", new=AsyncMock(return_value=[{"n": 4}])):
                cap = await rl._compute_cap(1)
            assert cap == 4 * rl.PER_OFFICER_QUOTA

        asyncio.run(scenario())


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: End-to-end middleware test (real HTTP, real JWT, no DB/Cache/deploy)
#
# Mounts the REAL _StationRateLimitMiddleware from main.py onto a tiny app with a
# dummy /api route, then drives it over real HTTP with the TestClient using a
# real signed JWT. This proves the full request path: header parse → JWT decode
# → in-memory check → 429 body + Retry-After header — all locally.
# ═══════════════════════════════════════════════════════════════════════════════

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.simple_auth import create_access_token


# CONTRACT
# takes:  unit_id (int | None), unit_name (str | None)
# returns: (str) — a real signed JWT carrying the station claims
# raises:  nothing
def _make_token(unit_id, unit_name="Koramangala PS"):
    return create_access_token(
        officer_id=1, badge_number="TEST123", role="investigator",
        unit_id=unit_id, unit_name=unit_name,
    )


# CONTRACT
# takes:  nothing
# returns: (TestClient) — client wrapping a minimal app with the real middleware
# raises:  nothing
def _build_client():
    # Import here so the module import cost is only paid when this test runs.
    from main import _StationRateLimitMiddleware

    app = FastAPI()
    app.add_middleware(_StationRateLimitMiddleware)

    @app.get("/api/chat")
    async def chat_probe():
        return {"ok": True}

    @app.get("/api/chat/sessions")
    async def sessions_probe():   # exempt path (reading history never limited)
        return {"sessions": []}

    @app.get("/health")
    async def health():        # non-/api path
        return {"health": True}

    # NOT using `with TestClient(...)` so the app's lifespan (DB pool, NoSQL,
    # rate-limiter background task) never starts — we test the middleware alone.
    return TestClient(app)


class TestMiddlewareEndToEnd:
    def test_allows_until_cap_then_429(self):
        rl._reset_for_tests()
        client = _build_client()
        token = _make_token(unit_id=42)
        headers = {"Authorization": f"Bearer {token}"}

        # Seed a small cap so we don't have to fire hundreds of requests.
        rl.check_and_increment(42)         # create the entry
        rl._local[42]["cap"] = 2
        rl._local[42]["count"] = 0

        # Two allowed...
        assert client.get("/api/chat", headers=headers).status_code == 200
        assert client.get("/api/chat", headers=headers).status_code == 200

        # ...third blocked with the informative body + Retry-After header.
        resp = client.get("/api/chat", headers=headers)
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        body = resp.json()
        assert body["error"] == "rate_limit_exceeded"
        assert body["station"] == "Koramangala PS"
        assert body["unit_id"] == 42
        assert body["limit"] == 2
        assert body["window_reset_at"] > 0

    def test_exempt_and_non_api_paths_never_limited(self):
        rl._reset_for_tests()
        client = _build_client()
        token = _make_token(unit_id=7)
        headers = {"Authorization": f"Bearer {token}"}

        # Max out station 7.
        rl.check_and_increment(7)
        rl._local[7]["cap"] = 1
        rl._local[7]["count"] = 1

        # /api/chat is blocked...
        assert client.get("/api/chat", headers=headers).status_code == 429
        # ...but sessions and health paths sail through.
        assert client.get("/api/chat/sessions", headers=headers).status_code == 200
        assert client.get("/health", headers=headers).status_code == 200

    def test_crafted_unit_id_in_body_is_ignored(self):
        # The middleware reads ONLY the JWT. A body/param claiming a different
        # unit_id must not affect which station gets charged.
        rl._reset_for_tests()
        client = _build_client()
        token = _make_token(unit_id=100)   # real station from the signed token
        headers = {"Authorization": f"Bearer {token}"}

        rl.check_and_increment(100)
        rl._local[100]["cap"] = 1
        rl._local[100]["count"] = 1        # station 100 maxed

        # Attacker tries to spend station 999's budget via query param.
        resp = client.get("/api/chat?unit_id=999", headers=headers)
        assert resp.status_code == 429            # still charged to 100
        assert resp.json()["unit_id"] == 100
        # Station 999 was never touched.
        assert 999 not in rl._local

    def test_no_token_fails_open(self):
        rl._reset_for_tests()
        client = _build_client()
        # No Authorization header at all → can't attribute a station → allow.
        assert client.get("/api/chat").status_code == 200
