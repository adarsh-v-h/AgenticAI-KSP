"""
Consolidated unit tests — pure functions and isolated module tests.

Merges the former:
  - test_generate_title.py
  - test_backward_compat.py
  - test_nosql_client.py
  - test_media_resolver.py
  - test_network_graph.py
  - test_export.py
  - test_report_extraction.py
  - test_voice.py

Run: pytest backend/tests/test_unit.py -v
"""

import asyncio
import io
import json
import os
import sys
import zipfile

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: Session Title Generation
# ═══════════════════════════════════════════════════════════════════════════════

from conversation.session_store import generate_title


class TestGenerateTitle:
    def test_removes_stop_words_and_capitalizes(self):
        assert generate_title("How many theft cases are open?") == "Theft cases open"

    def test_strips_leading_stop_words(self):
        assert generate_title("Show me all cases involving Mahesh Gowda") == (
            "Cases involving mahesh gowda"
        )

    def test_only_stop_words_falls_back(self):
        assert generate_title("the is are how many show me all") == "New chat"

    def test_empty_message_falls_back(self):
        assert generate_title("") == "New chat"

    def test_whitespace_only_falls_back(self):
        assert generate_title("   ") == "New chat"

    def test_takes_at_most_eight_words(self):
        message = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        title = generate_title(message)
        assert len(title.split()) == 8

    def test_fewer_than_three_significant_words(self):
        title = generate_title("show me theft")
        assert title == "Theft"

    def test_title_does_not_exceed_sixty_characters(self):
        message = " ".join(["constabulary"] * 8)
        title = generate_title(message)
        assert len(title) <= 60
        assert title.endswith("...")

    def test_punctuation_is_stripped(self):
        title = generate_title("theft, cases. open!")
        assert title == "Theft cases open"

    def test_first_letter_capitalized(self):
        title = generate_title("vehicle theft cases")
        assert title[0].isupper()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: Backward Compatibility (History Migration)
# ═══════════════════════════════════════════════════════════════════════════════

from conversation import history


class TestHistoryMigration:
    def test_legacy_messages_gain_id_and_timestamp(self):
        legacy = [
            {"role": "user", "content": "How many theft cases are open?"},
            {"role": "assistant", "content": "There are 23 open theft cases."},
        ]
        migrated = history._migrate_messages(legacy)
        assert len(migrated) == len(legacy)
        for original, msg in zip(legacy, migrated):
            assert msg.get("message_id")
            assert msg.get("timestamp")
            assert msg["role"] == original["role"]
            assert msg["content"] == original["content"]

    def test_migrated_message_ids_are_unique(self):
        legacy = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i}"}
            for i in range(20)
        ]
        migrated = history._migrate_messages(legacy)
        ids = [m["message_id"] for m in migrated]
        assert all(ids)
        assert len(set(ids)) == len(ids)

    def test_already_enhanced_messages_left_unchanged(self):
        enhanced = [
            {"message_id": "m-existing-1", "role": "user", "content": "hi",
             "timestamp": "2024-01-15T10:35:00+00:00"},
            {"message_id": "m-existing-2", "role": "assistant", "content": "hello",
             "timestamp": "2024-01-15T10:35:15+00:00", "sql": "SELECT 1"},
        ]
        migrated = history._migrate_messages(enhanced)
        assert migrated[0]["message_id"] == "m-existing-1"
        assert migrated[1]["sql"] == "SELECT 1"

    def test_migration_does_not_mutate_input(self):
        legacy = [{"role": "user", "content": "no id here"}]
        history._migrate_messages(legacy)
        assert "message_id" not in legacy[0]

    def test_migration_is_deterministic(self):
        legacy = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        first = history._migrate_messages(legacy)
        second = history._migrate_messages(legacy)
        assert [m["message_id"] for m in first] == [m["message_id"] for m in second]

    def test_migration_skips_non_dict_entries(self):
        turns = [{"role": "user", "content": "ok"}, "not-a-dict", None]
        migrated = history._migrate_messages(turns)
        assert len(migrated) == 1

    def test_get_history_returns_stored_from_memory(self, monkeypatch):
        # Simulate NoSQL being unavailable: get_document raises, so get_history
        # must fall back to the in-memory store.
        async def _raise(*a, **k):
            raise RuntimeError("NoSQL unavailable")

        monkeypatch.setattr(history, "get_document", _raise)
        session_id = "sess-backward-compat"
        stored = [
            {"message_id": "m-1", "role": "user", "content": "stored",
             "timestamp": "2024-01-15T10:35:00+00:00"},
        ]

        async def scenario():
            await history._local_set(session_id, stored)
            result = await history.get_history(session_id)
            await history._local_clear(session_id)
            return result

        result = asyncio.run(scenario())
        assert result == stored


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: NoSQL Client
# ═══════════════════════════════════════════════════════════════════════════════

from db.nosql_client import (
    serialize_to_catalyst, deserialize_from_catalyst, deserialize_item,
    _get_base_project_url, _nosql_headers, NoSQLError,
    get_document, insert_document, update_document, delete_document, list_documents,
)

_ENV_DEFAULTS = {
    "NOSQL_BASE_URL": "https://api.catalyst.zoho.in/baas/v1/project/123/nosql",
    "CATALYST_API_TOKEN": "test-token-abc",
    "CATALYST_ORG_ID": "org-789",
}


@pytest.fixture
def nosql_env(monkeypatch):
    for k, v in _ENV_DEFAULTS.items():
        monkeypatch.setenv(k, v)


class TestNoSQLSerialization:
    def test_string(self):
        assert serialize_to_catalyst("hello") == {"S": "hello"}

    def test_integer(self):
        assert serialize_to_catalyst(42) == {"N": "42"}

    def test_bool(self):
        assert serialize_to_catalyst(True) == {"BOOL": True}

    def test_none(self):
        assert serialize_to_catalyst(None) == {"NULL": True}

    def test_list(self):
        assert serialize_to_catalyst(["a", 1]) == {"L": [{"S": "a"}, {"N": "1"}]}

    def test_dict(self):
        assert serialize_to_catalyst({"key": "val"}) == {"M": {"key": {"S": "val"}}}

    @pytest.mark.parametrize("value", ["hello", 42, 3.14, True, False, None, ["a", 1]])
    def test_round_trip(self, value):
        assert deserialize_from_catalyst(serialize_to_catalyst(value)) == value


class TestNoSQLURLConstruction:
    def test_strips_nosql_suffix(self, nosql_env):
        assert _get_base_project_url() == "https://api.catalyst.zoho.in/baas/v1/project/123"

    def test_headers(self, nosql_env):
        # _nosql_headers() is async now (it awaits the token manager). Force
        # static-only mode (no refresh creds) so it uses CATALYST_API_TOKEN.
        from unittest.mock import patch
        import config.catalyst_token as ct
        ct._reset_for_tests()
        with patch.object(ct, "_refresh_credentials", return_value=None):
            headers = asyncio.run(_nosql_headers())
        assert headers["Authorization"] == "Zoho-oauthtoken test-token-abc"
        assert headers["CATALYST-ORG"] == "org-789"


class _MockResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body if isinstance(self._body, dict) else json.loads(self._body)

    @property
    def text(self):
        return json.dumps(self._body) if self._body else ""


class _FakeAsyncClient:
    """Stands in for the shared http_client.get_http_client() singleton."""
    def __init__(self, handler):
        self._handler = handler
    async def post(self, url, **kw): return self._handler("POST", url, **kw)
    async def put(self, url, **kw): return self._handler("PUT", url, **kw)
    async def get(self, url, **kw): return self._handler("GET", url, **kw)
    async def request(self, method, url, **kw): return self._handler(method, url, **kw)


class TestNoSQLCRUD:
    def test_get_document(self, monkeypatch, nosql_env):
        def handler(method, url, **kw):
            return _MockResponse(200, {"data": [{"item": {"id": {"S": "doc-1"}, "name": {"S": "Alice"}}}]})
        import db.nosql_client as nosql_mod
        monkeypatch.setattr(nosql_mod, "get_http_client", lambda: _FakeAsyncClient(handler))
        result = asyncio.run(get_document("my_table", "doc-1"))
        assert result == {"id": "doc-1", "name": "Alice"}

    def test_get_document_404(self, monkeypatch, nosql_env):
        def handler(method, url, **kw):
            return _MockResponse(404)
        import db.nosql_client as nosql_mod
        monkeypatch.setattr(nosql_mod, "get_http_client", lambda: _FakeAsyncClient(handler))
        assert asyncio.run(get_document("my_table", "x")) is None

    def test_insert_document(self, monkeypatch, nosql_env):
        def handler(method, url, **kw):
            return _MockResponse(201)
        import db.nosql_client as nosql_mod
        monkeypatch.setattr(nosql_mod, "get_http_client", lambda: _FakeAsyncClient(handler))
        assert asyncio.run(insert_document("my_table", "doc-1", {"name": "Bob"})) is True

    def test_delete_document(self, monkeypatch, nosql_env):
        def handler(method, url, **kw):
            return _MockResponse(204)
        import db.nosql_client as nosql_mod
        monkeypatch.setattr(nosql_mod, "get_http_client", lambda: _FakeAsyncClient(handler))
        assert asyncio.run(delete_document("my_table", "doc-1")) is True


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: Media Resolver
# ═══════════════════════════════════════════════════════════════════════════════

from pipeline.media_resolver import collect_case_master_ids, resolve_media


class TestMediaResolver:
    def test_collect_basic(self):
        results = [{"case_master_id": 1}, {"CaseMasterID": 2}, {"case_master_id": 1}]
        assert collect_case_master_ids(results) == [1, 2]

    def test_collect_no_column(self):
        assert collect_case_master_ids([{"name": "x"}]) == []

    def test_collect_empty(self):
        assert collect_case_master_ids([]) == []

    def test_resolve_empty(self):
        assert asyncio.run(resolve_media([])) == []

    def test_resolve_with_media(self, monkeypatch):
        mock_rows = [{"media_id": 1, "case_master_id": 100, "media_type": "image",
                      "file_name": "p.jpg", "stratus_folder_id": "f1",
                      "stratus_file_id": "file123", "description": "Crime scene"}]
        async def mock_exec(sql, params): return mock_rows
        monkeypatch.setattr("pipeline.media_resolver.execute_query", mock_exec)
        media = asyncio.run(resolve_media([{"case_master_id": 100}]))
        assert len(media) == 1
        assert media[0]["url"].startswith("https://picsum.photos/seed/file123")

    def test_resolve_document_unavailable(self, monkeypatch):
        mock_rows = [{"media_id": 4, "case_master_id": 300, "media_type": "document",
                      "file_name": "r.pdf", "stratus_folder_id": "f3",
                      "stratus_file_id": "file999", "description": "Report"}]
        async def mock_exec(sql, params): return mock_rows
        monkeypatch.setattr("pipeline.media_resolver.execute_query", mock_exec)
        media = asyncio.run(resolve_media([{"case_master_id": 300}]))
        assert media[0]["url"] == "/api/media/unavailable?file=file999"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: Network Graph
# ═══════════════════════════════════════════════════════════════════════════════

import graph.network_builder as nb


class TestNetworkGraph:
    def test_build_graph_for_fir_empty(self, monkeypatch):
        async def fake_exec(sql, params=()): return []
        monkeypatch.setattr(nb, "execute_query", fake_exec)
        assert asyncio.run(nb.build_graph_for_fir(123)) == {"nodes": [], "edges": []}

    def test_build_graph_for_accused_empty(self, monkeypatch):
        async def fake_exec(sql, params=()): return []
        monkeypatch.setattr(nb, "execute_query", fake_exec)
        assert asyncio.run(nb.build_graph_for_accused(456)) == {"nodes": [], "edges": []}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: Export HTML
# ═══════════════════════════════════════════════════════════════════════════════

from routers.export import _build_html, _merge_history_tables


class TestExport:
    def test_merge_history_tables(self):
        messages = [{"role": "assistant", "content": "29 cases.", "has_table": True, "table_data": []}]
        hist = [{"role": "assistant", "content": "29 cases.",
                 "table": [{"FIR": "001", "MAKE": "Honda"}]}]
        merged = _merge_history_tables(messages, hist)
        assert merged[0]["table_data"] == hist[0]["table"]

    def test_build_html_escapes(self):
        html = _build_html("Officer <One>", "KSP-1", "Test <title>", [
            {"role": "user", "content": "show <all>"},
            {"role": "assistant", "content": "Found", "table_data": [
                {"FIR": "001", "MAKE": "<Tata>"}
            ]},
        ])
        assert "&lt;Tata&gt;" in html
        assert "Officer &lt;One&gt;" in html


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: Report Extraction
# ═══════════════════════════════════════════════════════════════════════════════

from routers.reports import UnsupportedReportFormat, extract_report_text


def _make_docx(paragraphs):
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    doc_xml = f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


class TestReportExtraction:
    def test_docx(self):
        raw = _make_docx(["First paragraph.", "Second paragraph."])
        text = extract_report_text(raw, "report.docx", "")
        assert "First paragraph." in text

    def test_plain_text(self):
        raw = "Incident report: thefts in Koramangala.".encode()
        text = extract_report_text(raw, "notes.txt", "text/plain")
        assert "thefts in Koramangala" in text

    def test_html_tags_stripped(self):
        raw = "<html><body><h1>Title</h1><p>Body &amp; text</p></body></html>".encode()
        text = extract_report_text(raw, "page.html", "text/html")
        assert "Title" in text
        assert "<h1>" not in text

    def test_pdf_rejected(self):
        with pytest.raises(UnsupportedReportFormat):
            extract_report_text(b"%PDF-1.7\n...", "report.pdf", "application/pdf")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: Voice Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

import voice.zia_voice as zv
import routers.voice as vr


class TestVoiceHelpers:
    def test_unwrap(self):
        assert zv._unwrap({"data": {"transcript": "hi"}}) == {"transcript": "hi"}
        assert zv._unwrap({"transcript": "hi"}) == {"transcript": "hi"}

    def test_extract_transcript(self):
        assert zv._extract_transcript({"data": {"transcript": "a"}}) == "a"
        assert zv._extract_transcript({"text": "b"}) == "b"

    def test_extract_translation(self):
        assert zv._extract_translation({"data": {"translated_text": "x"}}) == "x"
        assert zv._extract_translation({"translation": "y"}) == "y"

    def test_strip_markdown(self):
        text = "## Heading\n| FIR | Status |\n|---|---|\nSome **bold** text"
        out = zv._strip_markdown_for_speech(text)
        assert "|" not in out
        assert "*" not in out

    def test_numbers_to_words(self):
        assert zv._numbers_to_words("42 cases") == "four two cases"


class TestVoiceTranscribe:
    class _FakeResp:
        def __init__(self, status_code=200, json_data=None, content=b"", text=""):
            self.status_code = status_code
            self._json = json_data
            self.content = content
            self.text = text
        def json(self):
            return self._json

    class _FakeClient:
        def __init__(self, resp):
            self._resp = resp
        async def post(self, *a, **kw): return self._resp

    def test_transcribe_returns_transcript(self, monkeypatch):
        monkeypatch.setattr(zv, "get", lambda key: f"http://fake/{key}")
        monkeypatch.setattr(zv, "get_http_client",
                          lambda: self._FakeClient(
                              self._FakeResp(200, {"data": {"transcript": "how many thefts"}})))
        result = asyncio.run(zv.transcribe_audio(b"audio", "en"))
        assert result == "how many thefts"

    def test_translate_skips_english(self, monkeypatch):
        monkeypatch.setattr(zv, "get", lambda key: f"http://fake/{key}")
        out = asyncio.run(zv.translate_to_english("hello", "en"))
        assert out == "hello"

    def test_ping_voice(self, monkeypatch):
        called_urls = []

        class _FakeClient:
            async def post(self, url, **kw):
                called_urls.append(url)
                if "translate" in url or "TRANSLATE" in url:
                    return TestVoiceTranscribe._FakeResp(200, {"translated_text": "hello"})
                elif "tts" in url or "TTS" in url:
                    return TestVoiceTranscribe._FakeResp(200, content=b"audio_bytes")
                elif "stt" in url or "STT" in url:
                    return TestVoiceTranscribe._FakeResp(200, {"data": {"transcript": "hello"}})
                return TestVoiceTranscribe._FakeResp(200)

        monkeypatch.setattr(zv, "get", lambda key: f"http://fake/{key}")
        monkeypatch.setattr(zv, "get_http_client", lambda: _FakeClient())

        asyncio.run(zv.ping_voice())
        assert len(called_urls) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: PDF Export
# ═══════════════════════════════════════════════════════════════════════════════

from routers.export import _build_pdf, _safe_text


class TestPDFExport:
    def test_build_pdf_returns_bytes(self):
        messages = [
            {"role": "user", "content": "How many cases?"},
            {"role": "assistant", "content": "There are 10 cases.",
             "table_data": [{"count": 10}], "sql_generated": "SELECT COUNT(*) FROM CaseMaster",
             "media_attachments": []},
        ]
        result = _build_pdf("Test Officer", "1234567", "Test Session", messages)
        assert isinstance(result, (bytes, bytearray))
        assert len(result) > 100
        # PDF magic bytes
        assert result[:4] == b"%PDF"

    def test_build_pdf_handles_empty_messages(self):
        result = _build_pdf("Officer", "000", "Empty", [])
        assert isinstance(result, (bytes, bytearray))
        assert result[:4] == b"%PDF"

    def test_build_pdf_handles_table_data(self):
        messages = [
            {"role": "assistant", "content": "Results:",
             "table_data": [
                 {"Name": "Mahesh Gowda", "Cases": 8},
                 {"Name": "Ravi Kumar", "Cases": 5},
             ],
             "sql_generated": "", "media_attachments": []},
        ]
        result = _build_pdf("Officer", "000", "Table Test", messages)
        assert isinstance(result, (bytes, bytearray))
        assert len(result) > 200

    def test_build_pdf_handles_media_placeholders(self):
        messages = [
            {"role": "assistant", "content": "Evidence found.",
             "table_data": [], "sql_generated": "",
             "media_attachments": [
                 {"media_type": "image", "description": "Crime scene photo"},
                 {"media_type": "video", "description": "CCTV footage"},
             ]},
        ]
        result = _build_pdf("Officer", "000", "Media Test", messages)
        assert isinstance(result, (bytes, bytearray))

    def test_safe_text_handles_unicode(self):
        assert _safe_text("Hello") == "Hello"
        assert _safe_text("") == ""
        assert _safe_text(None) == ""
        # Non-latin chars get replaced
        result = _safe_text("ಕನ್ನಡ text")
        assert "text" in result

    def test_build_pdf_with_sql_generated(self):
        messages = [
            {"role": "assistant", "content": "Found 36 cases.",
             "table_data": [{"count": 36}],
             "sql_generated": "SELECT COUNT(*) AS count FROM CaseMaster WHERE CaseStatusID = 4",
             "media_attachments": []},
        ]
        result = _build_pdf("Officer", "000", "SQL Test", messages)
        assert isinstance(result, (bytes, bytearray))
        assert len(result) > 200


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: Sociological Analytics
# ═══════════════════════════════════════════════════════════════════════════════

from pipeline.sociological_analytics import (
    get_accused_age_distribution,
    get_crime_by_gender,
    get_victim_demographics,
    get_crime_by_occupation,
    get_demographic_risk_profile,
)


class TestSociologicalAnalytics:
    def test_accused_age_distribution(self, monkeypatch):
        mock_data = [{"age_group": "18-25", "count": 43}, {"age_group": "26-35", "count": 69}]
        async def mock_exec(sql, params=()): return mock_data
        monkeypatch.setattr("pipeline.sociological_analytics.execute_query", mock_exec)
        result = asyncio.run(get_accused_age_distribution())
        assert result == mock_data
        assert result[0]["age_group"] == "18-25"

    def test_crime_by_gender(self, monkeypatch):
        mock_data = [{"crime_type": "Theft", "gender": "Male", "count": 60}]
        async def mock_exec(sql, params=()): return mock_data
        monkeypatch.setattr("pipeline.sociological_analytics.execute_query", mock_exec)
        result = asyncio.run(get_crime_by_gender())
        assert len(result) == 1
        assert result[0]["gender"] == "Male"

    def test_victim_demographics(self, monkeypatch):
        mock_data = [{"crime_type": "Assault", "age_group": "18-35", "gender": "Male", "count": 15}]
        async def mock_exec(sql, params=()): return mock_data
        monkeypatch.setattr("pipeline.sociological_analytics.execute_query", mock_exec)
        result = asyncio.run(get_victim_demographics())
        assert result[0]["crime_type"] == "Assault"

    def test_crime_by_occupation(self, monkeypatch):
        mock_data = [{"occupation": "Farmer", "count": 39}, {"occupation": "Student", "count": 35}]
        async def mock_exec(sql, params=()): return mock_data
        monkeypatch.setattr("pipeline.sociological_analytics.execute_query", mock_exec)
        result = asyncio.run(get_crime_by_occupation(10))
        assert result[0]["occupation"] == "Farmer"

    def test_demographic_risk_profile(self, monkeypatch):
        mock_data = [{"crime_type": "Theft", "age_group": "36-50", "gender": "Male", "count": 20}]
        async def mock_exec(sql, params=()): return mock_data
        monkeypatch.setattr("pipeline.sociological_analytics.execute_query", mock_exec)
        result = asyncio.run(get_demographic_risk_profile())
        assert result[0]["age_group"] == "36-50"
        assert result[0]["count"] == 20


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: Lookup Cache
# ═══════════════════════════════════════════════════════════════════════════════

import db.lookup_cache as lc

class TestLookupCache:
    def test_intercept_lookup_query(self):
        # Setup mock cache state
        lc._units = {1: {"UnitID": 1, "UnitName": "Station A", "ParentUnit": None}}
        lc._units_list = [{"UnitID": 1, "UnitName": "Station A", "ParentUnit": None}]
        
        # Test Unit Name Match
        res = lc.intercept_lookup_query("SELECT UnitID FROM Unit WHERE UnitName = %s", ("Station A",))
        assert res == [{"UnitID": 1}]

        # Test Unit ID Match
        res = lc.intercept_lookup_query("SELECT UnitID FROM Unit WHERE UnitID = %s", (1,))
        assert res == [{"UnitID": 1}]

        # Test List all
        res = lc.intercept_lookup_query("SELECT UnitID FROM Unit")
        assert res == [{"UnitID": 1}]

        # Test no match fallback
        res = lc.intercept_lookup_query("SELECT * FROM CaseMaster")
        assert res is None

    def test_get_descendant_units_mem(self):
        lc._units = {
            1: {"UnitID": 1, "UnitName": "HQ", "ParentUnit": None},
            2: {"UnitID": 2, "UnitName": "Station A", "ParentUnit": 1},
            3: {"UnitID": 3, "UnitName": "Substation B", "ParentUnit": 2},
        }
        
        desc = lc.get_descendant_units_mem(1)
        assert set(desc) == {1, 2, 3}

        desc = lc.get_descendant_units_mem(2)
        assert set(desc) == {2, 3}

