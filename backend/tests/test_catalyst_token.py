"""
Unit tests for the Catalyst OAuth token manager (config/catalyst_token.py).

Verifies: caching, transparent refresh, the fail-safe fallbacks (cached →
static), static-only mode when refresh creds are absent, and invalidate().

Run: pytest backend/tests/test_catalyst_token.py -v
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from config import catalyst_token as ct


@pytest.fixture(autouse=True)
def _clean_state():
    ct._reset_for_tests()
    yield
    ct._reset_for_tests()


def _run(coro):
    return asyncio.run(coro)


class TestStaticFallback:
    def test_no_refresh_creds_uses_static_token(self):
        with patch.object(ct, "_refresh_credentials", return_value=None), \
             patch.object(ct, "_static_token", return_value="static-xyz"):
            token = _run(ct.get_access_token())
        assert token == "static-xyz"

    def test_no_creds_and_no_static_raises(self):
        with patch.object(ct, "_refresh_credentials", return_value=None), \
             patch.object(ct, "_static_token", return_value=None):
            with pytest.raises(RuntimeError):
                _run(ct.get_access_token())


class TestRefresh:
    def test_mints_and_caches_token(self):
        creds = ("cid", "csecret", "rtok")
        with patch.object(ct, "_refresh_credentials", return_value=creds), \
             patch.object(ct, "_accounts_url", return_value="https://accounts.zoho.in/oauth/v2/token"), \
             patch.object(ct, "httpx") as mock_httpx:
            resp = AsyncMock()
            resp.raise_for_status = lambda: None
            resp.json = lambda: {"access_token": "fresh-1", "expires_in": 3600}
            client = AsyncMock()
            client.post = AsyncMock(return_value=resp)
            mock_httpx.AsyncClient.return_value.__aenter__.return_value = client

            first = _run(ct.get_access_token())
            assert first == "fresh-1"
            # Second call is served from cache — no second network hit.
            second = _run(ct.get_access_token())
            assert second == "fresh-1"
            assert client.post.await_count == 1

    def test_expired_cache_triggers_new_refresh(self):
        creds = ("cid", "csecret", "rtok")
        with patch.object(ct, "_refresh_credentials", return_value=creds), \
             patch.object(ct, "_accounts_url", return_value="https://accounts.zoho.in/oauth/v2/token"), \
             patch.object(ct, "httpx") as mock_httpx:
            resp = AsyncMock()
            resp.raise_for_status = lambda: None
            resp.json = lambda: {"access_token": "fresh-2", "expires_in": 3600}
            client = AsyncMock()
            client.post = AsyncMock(return_value=resp)
            mock_httpx.AsyncClient.return_value.__aenter__.return_value = client

            _run(ct.get_access_token())
            # Force expiry.
            ct._expires_at = time.time() - 1
            _run(ct.get_access_token())
            assert client.post.await_count == 2


class TestFailSafe:
    def test_refresh_failure_reuses_cached_token(self):
        creds = ("cid", "csecret", "rtok")
        # Seed a cached token, then force expiry so a refresh is attempted.
        ct._cached_token = "cached-old"
        ct._expires_at = time.time() - 1
        with patch.object(ct, "_refresh_credentials", return_value=creds), \
             patch.object(ct, "_refresh_access_token", new=AsyncMock(side_effect=RuntimeError("boom"))):
            token = _run(ct.get_access_token())
        assert token == "cached-old"

    def test_refresh_failure_falls_back_to_static(self):
        creds = ("cid", "csecret", "rtok")
        with patch.object(ct, "_refresh_credentials", return_value=creds), \
             patch.object(ct, "_refresh_access_token", new=AsyncMock(side_effect=RuntimeError("boom"))), \
             patch.object(ct, "_static_token", return_value="static-fallback"):
            token = _run(ct.get_access_token())
        assert token == "static-fallback"


class TestInvalidate:
    def test_invalidate_clears_cache(self):
        ct._cached_token = "something"
        ct._expires_at = time.time() + 9999
        ct.invalidate()
        assert ct._cached_token is None
        assert ct._expires_at == 0.0


class TestAccountsUrlDerivation:
    def test_explicit_url_wins(self):
        with patch.object(ct, "get", side_effect=lambda k: "https://explicit/token" if k == "CATALYST_ACCOUNTS_URL" else (_ for _ in ()).throw(Exception())):
            assert ct._accounts_url() == "https://explicit/token"

    def test_derives_from_base_url_in(self):
        def fake_get(k):
            if k == "CATALYST_ACCOUNTS_URL":
                raise Exception("unset")
            if k == "CATALYST_BASE_URL":
                return "https://api.catalyst.zoho.in"
            raise Exception("unset")
        with patch.object(ct, "get", side_effect=fake_get):
            assert ct._accounts_url() == "https://accounts.zoho.in/oauth/v2/token"
