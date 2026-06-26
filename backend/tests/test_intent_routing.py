"""Tests for the intent-routing layer in the query pipeline.

These verify that:
  1. A DIRECT classification skips SQL entirely and answers from context.
  2. A SQL classification still runs the full NL2SQL pipeline.
  3. A CANNOT_ANSWER from the SQL chain falls back to a direct answer.
  4. The most-recent table snapshot is recovered from history for follow-ups.

The LLM and DB boundaries are monkeypatched so no network/DB is needed. Each
test drives its async body with asyncio.run (no pytest-asyncio dependency,
matching the rest of the suite).
"""

import asyncio

import pipeline.query_pipeline as qp


def test_most_recent_table_returns_latest_snapshot():
    history = [
        {"role": "user", "content": "theft cases"},
        {"role": "assistant", "content": "Found 3.", "table": [{"fir_id": 1}]},
        {"role": "user", "content": "robbery cases"},
        {"role": "assistant", "content": "Found 2.", "table": [{"fir_id": 9}]},
    ]
    assert qp._most_recent_table(history) == [{"fir_id": 9}]


def test_most_recent_table_empty_when_no_snapshot():
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert qp._most_recent_table(history) == []


def test_direct_route_skips_sql(monkeypatch):
    async def scenario():
        calls = {"sql": 0}

        async def fake_route(question, history, has_recent_data):
            return "DIRECT"

        async def fake_direct(question, history, recent_table):
            return "Here is a summary of the data."

        async def fake_generate_sql(*args, **kwargs):
            calls["sql"] += 1
            raise AssertionError("SQL chain must not run on a DIRECT route")

        monkeypatch.setattr(qp, "route_intent", fake_route)
        monkeypatch.setattr(qp, "generate_direct_answer", fake_direct)
        monkeypatch.setattr(qp, "generate_sql", fake_generate_sql)

        history = [
            {"role": "user", "content": "theft cases"},
            {"role": "assistant", "content": "Found 3.", "table": [{"fir_id": 1}]},
        ]
        resp = await qp.run_pipeline("summarize that", history=history)

        assert resp.error is None
        assert resp.answer_text == "Here is a summary of the data."
        assert resp.sql_generated == ""
        assert resp.table_data == []
        assert calls["sql"] == 0

    asyncio.run(scenario())


def test_sql_route_runs_pipeline(monkeypatch):
    async def scenario():
        async def fake_route(question, history, has_recent_data):
            return "SQL"

        async def fake_generate_sql(question, table_names, history, officer=None):
            return "SELECT 1 AS fir_id", 1

        async def fake_execute(sql, params=()):
            return [{"fir_id": 1}]

        async def fake_format(question, results, media_attachments, history):
            return "One theft case found."

        async def fake_graph(fir_ids):
            return False

        async def fake_resolve(results):
            return []

        monkeypatch.setattr(qp, "route_intent", fake_route)
        monkeypatch.setattr(qp, "generate_sql", fake_generate_sql)
        monkeypatch.setattr(qp, "execute_query", fake_execute)
        monkeypatch.setattr(qp, "format_answer", fake_format)
        monkeypatch.setattr(qp, "_check_graph_available", fake_graph)
        monkeypatch.setattr(qp, "resolve_media", fake_resolve)
        monkeypatch.setattr(qp, "select_relevant_tables", lambda q: ["CaseMaster"])

        resp = await qp.run_pipeline("show theft cases", history=[])

        assert resp.error is None
        assert resp.answer_text == "One theft case found."
        assert resp.sql_generated == "SELECT 1 AS fir_id"
        assert resp.table_data == [{"fir_id": 1}]

    asyncio.run(scenario())


def test_cannot_answer_falls_back_to_direct(monkeypatch):
    async def scenario():
        async def fake_route(question, history, has_recent_data):
            return "SQL"

        async def fake_generate_sql(*args, **kwargs):
            raise qp.CannotAnswerError("nope")

        async def fake_direct(question, history, recent_table):
            return "I can't pull that from the database, but here's what I know."

        monkeypatch.setattr(qp, "route_intent", fake_route)
        monkeypatch.setattr(qp, "generate_sql", fake_generate_sql)
        monkeypatch.setattr(qp, "generate_direct_answer", fake_direct)
        monkeypatch.setattr(qp, "select_relevant_tables", lambda q: ["CaseMaster"])

        resp = await qp.run_pipeline("what is your name?", history=[])

        assert resp.error is None
        assert "can't pull that" in resp.answer_text
        assert resp.sql_generated == ""

    asyncio.run(scenario())


def test_direct_answer_llm_failure_is_graceful(monkeypatch):
    async def scenario():
        async def fake_route(question, history, has_recent_data):
            return "DIRECT"

        async def fake_direct(question, history, recent_table):
            raise qp.LLMError("model down")

        monkeypatch.setattr(qp, "route_intent", fake_route)
        monkeypatch.setattr(qp, "generate_direct_answer", fake_direct)

        # History present so the router runs (an empty-history turn skips the
        # router and goes straight to SQL — see run_pipeline optimization).
        history = [
            {"role": "user", "content": "theft cases"},
            {"role": "assistant", "content": "Found 3.", "table": [{"fir_id": 1}]},
        ]
        resp = await qp.run_pipeline("summarize that", history=history)

        # Never raises — surfaces a friendly error instead.
        assert resp.error is not None
        assert resp.answer_text

    asyncio.run(scenario())


def test_empty_history_skips_router(monkeypatch):
    """A brand-new chat (no history) must NOT call the router — it goes
    straight to SQL, saving one LLM round-trip on the common first turn."""
    async def scenario():
        calls = {"router": 0}

        async def fake_route(question, history, has_recent_data):
            calls["router"] += 1
            return "SQL"

        async def fake_generate_sql(question, table_names, history, officer=None):
            return "SELECT 1 AS fir_id", 1

        async def fake_execute(sql, params=()):
            return [{"fir_id": 1}]

        async def fake_format(question, results, media_attachments, history):
            return "One case found."

        async def fake_graph(fir_ids):
            return False

        async def fake_resolve(results):
            return []

        monkeypatch.setattr(qp, "route_intent", fake_route)
        monkeypatch.setattr(qp, "generate_sql", fake_generate_sql)
        monkeypatch.setattr(qp, "execute_query", fake_execute)
        monkeypatch.setattr(qp, "format_answer", fake_format)
        monkeypatch.setattr(qp, "_check_graph_available", fake_graph)
        monkeypatch.setattr(qp, "resolve_media", fake_resolve)
        monkeypatch.setattr(qp, "select_relevant_tables", lambda q: ["CaseMaster"])

        resp = await qp.run_pipeline("show theft cases", history=[])

        assert calls["router"] == 0, "router must be skipped when there's no history"
        assert resp.sql_generated == "SELECT 1 AS fir_id"

    asyncio.run(scenario())
