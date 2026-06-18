"""Unit tests for db.nosql_client.

Tests cover:
  1. Custom serialization (serialize_to_catalyst) for every supported type.
  2. Deserialization (deserialize_from_catalyst) round-trips.
  3. URL construction (_get_base_project_url strips /nosql suffix).
  4. Document CRUD methods with mocked httpx responses.

pytest-asyncio is intentionally NOT required: each test wraps its async body
in asyncio.run(...), matching the pattern used in test_session_lifecycle.py.
"""

import asyncio
import json
import os

import pytest

# ── Ensure backend is importable ────────────────────────────────────────────
import sys
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


# ── Stub out config.settings.get before importing nosql_client ──────────────
# nosql_client calls get("NOSQL_BASE_URL") and get("CATALYST_API_TOKEN") at
# function call time, so we monkeypatch os.environ and let the real `get()`
# read from it.
_ENV_DEFAULTS = {
    "NOSQL_BASE_URL": "https://api.catalyst.zoho.in/baas/v1/project/123/nosql",
    "CATALYST_API_TOKEN": "test-token-abc",
    "CATALYST_ORG_ID": "org-789",
}


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    for k, v in _ENV_DEFAULTS.items():
        monkeypatch.setenv(k, v)


# Import the module under test AFTER the fixture-setup strategy is defined.
# The module-level imports inside nosql_client only call get() lazily (inside
# functions), so importing here is safe.
from db.nosql_client import (
    serialize_to_catalyst,
    deserialize_from_catalyst,
    deserialize_item,
    _get_base_project_url,
    _nosql_headers,
    NoSQLError,
    get_document,
    insert_document,
    update_document,
    delete_document,
    list_documents,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Serialization
# ═══════════════════════════════════════════════════════════════════════════════


class TestSerializeToCatalyst:
    def test_string(self):
        assert serialize_to_catalyst("hello") == {"S": "hello"}

    def test_integer(self):
        assert serialize_to_catalyst(42) == {"N": "42"}

    def test_float(self):
        assert serialize_to_catalyst(3.14) == {"N": "3.14"}

    def test_bool_true(self):
        assert serialize_to_catalyst(True) == {"BOOL": True}

    def test_bool_false(self):
        assert serialize_to_catalyst(False) == {"BOOL": False}

    def test_none(self):
        assert serialize_to_catalyst(None) == {"NULL": True}

    def test_list(self):
        result = serialize_to_catalyst(["a", 1])
        assert result == {"L": [{"S": "a"}, {"N": "1"}]}

    def test_dict(self):
        result = serialize_to_catalyst({"key": "val"})
        assert result == {"M": {"key": {"S": "val"}}}

    def test_nested(self):
        result = serialize_to_catalyst({"items": [1, "two", None]})
        expected = {
            "M": {
                "items": {
                    "L": [{"N": "1"}, {"S": "two"}, {"NULL": True}]
                }
            }
        }
        assert result == expected

    def test_unknown_type_falls_back_to_string(self):
        """Types not explicitly handled are cast to str and wrapped as S."""
        result = serialize_to_catalyst(b"bytes-value")
        assert result == {"S": "b'bytes-value'"}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Deserialization
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeserializeFromCatalyst:
    def test_string(self):
        assert deserialize_from_catalyst({"S": "hello"}) == "hello"

    def test_integer(self):
        assert deserialize_from_catalyst({"N": "42"}) == 42

    def test_float(self):
        assert deserialize_from_catalyst({"N": "3.14"}) == 3.14

    def test_bool(self):
        assert deserialize_from_catalyst({"BOOL": True}) is True

    def test_null(self):
        assert deserialize_from_catalyst({"NULL": True}) is None

    def test_list(self):
        val = {"L": [{"S": "a"}, {"N": "1"}]}
        assert deserialize_from_catalyst(val) == ["a", 1]

    def test_map(self):
        val = {"M": {"key": {"S": "val"}}}
        assert deserialize_from_catalyst(val) == {"key": "val"}

    def test_passthrough_non_dict(self):
        """Non-dict values are returned as-is."""
        assert deserialize_from_catalyst("raw") == "raw"
        assert deserialize_from_catalyst(123) == 123

    def test_passthrough_multi_key_dict(self):
        """Dicts with != 1 key are returned as-is (not Catalyst-encoded)."""
        val = {"S": "a", "N": "1"}
        assert deserialize_from_catalyst(val) == val


class TestDeserializeItem:
    def test_empty(self):
        assert deserialize_item({}) == {}
        assert deserialize_item(None) == {}

    def test_full_document(self):
        raw = {
            "id": {"S": "sess-001"},
            "count": {"N": "5"},
            "active": {"BOOL": True},
        }
        result = deserialize_item(raw)
        assert result == {"id": "sess-001", "count": 5, "active": True}


class TestRoundTrip:
    """Serialize → deserialize must yield the original value."""

    @pytest.mark.parametrize("value", [
        "hello",
        42,
        3.14,
        True,
        False,
        None,
        ["a", 1, None],
        {"nested": {"key": "val"}},
    ])
    def test_round_trip(self, value):
        serialized = serialize_to_catalyst(value)
        assert deserialize_from_catalyst(serialized) == value


# ═══════════════════════════════════════════════════════════════════════════════
# 3. URL construction & headers
# ═══════════════════════════════════════════════════════════════════════════════


class TestURLConstruction:
    def test_strips_nosql_suffix(self):
        """NOSQL_BASE_URL ending with /nosql should have that suffix removed."""
        url = _get_base_project_url()
        assert url == "https://api.catalyst.zoho.in/baas/v1/project/123"

    def test_no_nosql_suffix(self, monkeypatch):
        monkeypatch.setenv(
            "NOSQL_BASE_URL",
            "https://api.catalyst.zoho.in/baas/v1/project/456"
        )
        url = _get_base_project_url()
        assert url == "https://api.catalyst.zoho.in/baas/v1/project/456"

    def test_trailing_slash_stripped(self, monkeypatch):
        monkeypatch.setenv(
            "NOSQL_BASE_URL",
            "https://api.catalyst.zoho.in/baas/v1/project/789/nosql/"
        )
        url = _get_base_project_url()
        assert url == "https://api.catalyst.zoho.in/baas/v1/project/789"


class TestHeaders:
    def test_zoho_oauthtoken_scheme(self):
        headers = _nosql_headers()
        assert headers["Authorization"] == "Zoho-oauthtoken test-token-abc"
        assert headers["Content-Type"] == "application/json"
        assert headers["CATALYST-ORG"] == "org-789"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Document CRUD (mocked HTTP)
# ═══════════════════════════════════════════════════════════════════════════════


class _MockResponse:
    """Minimal mock for httpx.Response."""

    def __init__(self, status_code: int, body: dict | str | bytes | None = None):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, dict):
            return self._body
        return json.loads(self._body)

    @property
    def text(self):
        if isinstance(self._body, str):
            return self._body
        return json.dumps(self._body) if self._body else ""

    @property
    def content(self):
        if isinstance(self._body, bytes):
            return self._body
        return self.text.encode()


class _FakeAsyncClient:
    """Drop-in replacement for httpx.AsyncClient context manager.

    Accepts a callable(method, url, **kwargs) -> _MockResponse that the test
    can use to assert correct requests and return canned responses.
    """

    def __init__(self, handler):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        return self._handler("POST", url, **kwargs)

    async def put(self, url, **kwargs):
        return self._handler("PUT", url, **kwargs)

    async def get(self, url, **kwargs):
        return self._handler("GET", url, **kwargs)

    async def request(self, method, url, **kwargs):
        return self._handler(method, url, **kwargs)


class TestGetDocument:
    def test_returns_deserialized_item(self, monkeypatch):
        def handler(method, url, **kw):
            assert method == "POST"
            assert "/nosqltable/my_table/item/fetch" in url
            return _MockResponse(200, {
                "data": [{"item": {"id": {"S": "doc-1"}, "name": {"S": "Alice"}}}]
            })

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient(handler))

        result = asyncio.run(get_document("my_table", "doc-1"))
        assert result == {"id": "doc-1", "name": "Alice"}

    def test_returns_none_on_404(self, monkeypatch):
        def handler(method, url, **kw):
            return _MockResponse(404)

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient(handler))

        result = asyncio.run(get_document("my_table", "nonexistent"))
        assert result is None

    def test_raises_on_server_error(self, monkeypatch):
        def handler(method, url, **kw):
            return _MockResponse(500, "Internal Server Error")

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient(handler))

        with pytest.raises(NoSQLError, match="500"):
            asyncio.run(get_document("my_table", "doc-1"))

    def test_returns_none_on_empty_data(self, monkeypatch):
        def handler(method, url, **kw):
            return _MockResponse(200, {"data": []})

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient(handler))

        result = asyncio.run(get_document("my_table", "doc-1"))
        assert result is None


class TestInsertDocument:
    def test_insert_success(self, monkeypatch):
        captured = {}

        def handler(method, url, **kw):
            captured["method"] = method
            captured["url"] = url
            captured["json"] = kw.get("json")
            return _MockResponse(201)

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient(handler))

        result = asyncio.run(insert_document("my_table", "doc-1", {"name": "Bob"}))
        assert result is True
        assert captured["method"] == "POST"
        assert "/nosqltable/my_table/item" in captured["url"]
        # Verify the serialized payload includes the id
        payload = captured["json"]
        assert isinstance(payload, list)
        item = payload[0]["item"]
        assert item["id"] == {"S": "doc-1"}
        assert item["name"] == {"S": "Bob"}

    def test_insert_raises_on_error(self, monkeypatch):
        def handler(method, url, **kw):
            return _MockResponse(400, "Bad Request")

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient(handler))

        with pytest.raises(NoSQLError, match="400"):
            asyncio.run(insert_document("my_table", "doc-1", {"name": "Bob"}))


class TestUpdateDocument:
    def test_update_success(self, monkeypatch):
        captured = {}

        def handler(method, url, **kw):
            captured["method"] = method
            captured["json"] = kw.get("json")
            return _MockResponse(200)

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient(handler))

        result = asyncio.run(update_document("my_table", "doc-1", {"status": "done"}))
        assert result is True
        assert captured["method"] == "PUT"
        # Verify payload structure
        payload = captured["json"]
        assert payload[0]["keys"]["id"] == {"S": "doc-1"}
        attrs = payload[0]["update_attributes"]
        assert len(attrs) == 1
        assert attrs[0]["attribute_path"] == ["status"]
        assert attrs[0]["update_value"] == {"S": "done"}

    def test_update_skips_id_field(self, monkeypatch):
        """The 'id' key in updates should be skipped (it's the key, not an attribute)."""
        captured = {}

        def handler(method, url, **kw):
            captured["json"] = kw.get("json")
            return _MockResponse(200)

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient(handler))

        asyncio.run(update_document("my_table", "doc-1", {"id": "doc-1", "name": "test"}))
        attrs = captured["json"][0]["update_attributes"]
        attr_paths = [a["attribute_path"] for a in attrs]
        assert ["id"] not in attr_paths
        assert ["name"] in attr_paths


class TestDeleteDocument:
    def test_delete_success(self, monkeypatch):
        captured = {}

        def handler(method, url, **kw):
            captured["method"] = method
            return _MockResponse(204)

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient(handler))

        result = asyncio.run(delete_document("my_table", "doc-1"))
        assert result is True
        assert captured["method"] == "DELETE"

    def test_delete_raises_on_error(self, monkeypatch):
        def handler(method, url, **kw):
            return _MockResponse(403, "Forbidden")

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient(handler))

        with pytest.raises(NoSQLError, match="403"):
            asyncio.run(delete_document("my_table", "doc-1"))


class TestListDocuments:
    def test_list_returns_deserialized_items(self, monkeypatch):
        def handler(method, url, **kw):
            assert method == "GET"
            return _MockResponse(200, {
                "data": [
                    {"item": {"id": {"S": "doc-1"}, "val": {"N": "10"}}},
                    {"item": {"id": {"S": "doc-2"}, "val": {"N": "20"}}},
                ]
            })

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient(handler))

        result = asyncio.run(list_documents("my_table"))
        assert len(result) == 2
        assert result[0] == {"id": "doc-1", "val": 10}
        assert result[1] == {"id": "doc-2", "val": 20}

    def test_list_returns_empty_on_404(self, monkeypatch):
        def handler(method, url, **kw):
            return _MockResponse(404)

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient(handler))

        result = asyncio.run(list_documents("my_table"))
        assert result == []

    def test_list_raises_on_server_error(self, monkeypatch):
        def handler(method, url, **kw):
            return _MockResponse(500, "Error")

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeAsyncClient(handler))

        with pytest.raises(NoSQLError, match="500"):
            asyncio.run(list_documents("my_table"))
