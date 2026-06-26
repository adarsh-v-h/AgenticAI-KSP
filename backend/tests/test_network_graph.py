"""Tests for stubbed network_builder during Step 3 migration."""
import asyncio
import pytest
import graph.network_builder as nb


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_build_graph_for_fir_returns_empty():
    """Verify build_graph_for_fir returns empty structure and does not raise."""
    graph = _run_async(nb.build_graph_for_fir(123))
    assert graph == {"nodes": [], "edges": []}


def test_build_graph_for_accused_returns_empty():
    """Verify build_graph_for_accused returns empty structure and does not raise."""
    graph = _run_async(nb.build_graph_for_accused(456))
    assert graph == {"nodes": [], "edges": []}
