"""Tests for the network graph builder (graph.network_builder).

Covers the pure node/edge construction and trimming logic directly, and the
async builders with `execute_query` monkeypatched so no DB is needed. Each
async test drives its body with asyncio.run (no pytest-asyncio), matching the
rest of the suite.
"""

import asyncio

import graph.network_builder as nb


# --------------------------------------------------------------------------- #
# _build_nodes_and_edges
# --------------------------------------------------------------------------- #


def test_build_nodes_and_edges_namespaces_ids_by_type():
    rels = [
        {
            "rel_id": 1,
            "entity_a_type": "fir", "entity_a_id": 2,
            "entity_b_type": "accused", "entity_b_id": 2,
            "relationship_type": "co_accused",
        }
    ]
    labels = {("fir", 2): "FIR/2024/KOR/0042", ("accused", 2): "Mahesh Gowda"}

    graph = nb._build_nodes_and_edges(rels, labels, center_id="fir_2")

    node_ids = {n["id"] for n in graph["nodes"]}
    # Same numeric id (2) on different entity types must NOT collide.
    assert node_ids == {"fir_2", "accused_2"}
    assert {"id": "fir_2", "label": "FIR/2024/KOR/0042", "group": "fir"} in graph["nodes"]
    assert graph["edges"] == [{"from": "fir_2", "to": "accused_2", "label": "co_accused"}]


def test_build_nodes_and_edges_dedupes_edges():
    rels = [
        {"rel_id": 1, "entity_a_type": "accused", "entity_a_id": 1,
         "entity_b_type": "accused", "entity_b_id": 2, "relationship_type": "co_accused"},
        {"rel_id": 2, "entity_a_type": "accused", "entity_a_id": 1,
         "entity_b_type": "accused", "entity_b_id": 2, "relationship_type": "co_accused"},
    ]
    graph = nb._build_nodes_and_edges(rels, {}, center_id="accused_1")
    assert len(graph["edges"]) == 1


def test_build_nodes_and_edges_skips_invalid_entity_types():
    rels = [
        {"rel_id": 1, "entity_a_type": "bogus", "entity_a_id": 1,
         "entity_b_type": "accused", "entity_b_id": 2, "relationship_type": "x"},
    ]
    graph = nb._build_nodes_and_edges(rels, {}, center_id="accused_2")
    assert graph["nodes"] == []
    assert graph["edges"] == []


def test_build_nodes_uses_fallback_label_when_missing():
    rels = [
        {"rel_id": 1, "entity_a_type": "fir", "entity_a_id": 7,
         "entity_b_type": "accused", "entity_b_id": 9, "relationship_type": "related_case"},
    ]
    graph = nb._build_nodes_and_edges(rels, {}, center_id="fir_7")
    labels = {n["id"]: n["label"] for n in graph["nodes"]}
    assert labels["fir_7"] == "Fir 7"
    assert labels["accused_9"] == "Accused 9"


# --------------------------------------------------------------------------- #
# _trim_to_max_nodes
# --------------------------------------------------------------------------- #


def test_trim_keeps_center_node_even_if_low_degree(monkeypatch):
    monkeypatch.setattr(nb, "MAX_NODES", 3)

    # center has degree 0; four other nodes form a connected clump.
    nodes = [{"id": f"accused_{i}", "label": str(i), "group": "accused"} for i in range(5)]
    nodes.append({"id": "accused_center", "label": "C", "group": "accused"})
    edges = [
        {"from": "accused_0", "to": "accused_1", "label": "x"},
        {"from": "accused_1", "to": "accused_2", "label": "x"},
        {"from": "accused_2", "to": "accused_3", "label": "x"},
    ]

    kept_nodes, kept_edges = nb._trim_to_max_nodes(nodes, edges, "accused_center")

    kept_ids = {n["id"] for n in kept_nodes}
    assert len(kept_nodes) == 3
    assert "accused_center" in kept_ids, "center node must always survive trimming"
    # Every kept edge references only kept nodes.
    for e in kept_edges:
        assert e["from"] in kept_ids and e["to"] in kept_ids


def test_trim_noop_when_within_cap():
    nodes = [{"id": "a", "label": "a", "group": "accused"}]
    edges = []
    kept_nodes, kept_edges = nb._trim_to_max_nodes(nodes, edges, "a")
    assert kept_nodes == nodes
    assert kept_edges == edges


# --------------------------------------------------------------------------- #
# build_graph_for_fir / build_graph_for_accused (async, DB monkeypatched)
# --------------------------------------------------------------------------- #


def test_build_graph_for_fir_combines_fir_and_accused_links(monkeypatch):
    async def scenario():
        async def fake_execute(sql, params=()):
            s = sql.lower()
            if "from accused where fir_id" in s:
                return [{"accused_id": 5}]
            if "from case_relationships" in s:
                # FIR-side query and accused-side query both hit this; return
                # different rows depending on the entity type param (first param).
                etype = params[0]
                if etype == "fir":
                    return [{
                        "rel_id": 10, "entity_a_type": "fir", "entity_a_id": 2,
                        "entity_b_type": "fir", "entity_b_id": 3,
                        "relationship_type": "related_case",
                    }]
                return [{
                    "rel_id": 20, "entity_a_type": "accused", "entity_a_id": 5,
                    "entity_b_type": "accused", "entity_b_id": 6,
                    "relationship_type": "co_accused",
                }]
            if "from fir_master" in s:
                return [{"eid": 2, "label": "FIR-2"}, {"eid": 3, "label": "FIR-3"}]
            if "from accused where accused_id" in s:
                return [{"eid": 5, "label": "Mahesh"}, {"eid": 6, "label": "Ravi"}]
            return []

        monkeypatch.setattr(nb, "execute_query", fake_execute)

        graph = await nb.build_graph_for_fir(2)
        node_ids = {n["id"] for n in graph["nodes"]}
        # FIR-side link (fir_2↔fir_3) and accused-side link (accused_5↔accused_6).
        assert {"fir_2", "fir_3", "accused_5", "accused_6"} == node_ids
        rel_labels = {e["label"] for e in graph["edges"]}
        assert rel_labels == {"related_case", "co_accused"}

    asyncio.run(scenario())


def test_build_graph_for_fir_empty_when_no_relationships(monkeypatch):
    async def scenario():
        async def fake_execute(sql, params=()):
            if "from accused where fir_id" in sql.lower():
                return []
            return []

        monkeypatch.setattr(nb, "execute_query", fake_execute)
        graph = await nb.build_graph_for_fir(999)
        assert graph == {"nodes": [], "edges": []}

    asyncio.run(scenario())


def test_build_graph_never_raises_on_db_error(monkeypatch):
    async def scenario():
        async def boom(sql, params=()):
            raise RuntimeError("db down")

        monkeypatch.setattr(nb, "execute_query", boom)
        graph = await nb.build_graph_for_accused(1)
        assert graph == {"nodes": [], "edges": []}

    asyncio.run(scenario())


def test_build_graph_for_accused_resolves_labels(monkeypatch):
    async def scenario():
        async def fake_execute(sql, params=()):
            s = sql.lower()
            if "from case_relationships" in s:
                return [{
                    "rel_id": 1, "entity_a_type": "accused", "entity_a_id": 1,
                    "entity_b_type": "fir", "entity_b_id": 8,
                    "relationship_type": "related_case",
                }]
            if "from accused where accused_id" in s:
                return [{"eid": 1, "label": "Suresh Nayak"}]
            if "from fir_master" in s:
                return [{"eid": 8, "label": "FIR/2024/JAY/0008"}]
            return []

        monkeypatch.setattr(nb, "execute_query", fake_execute)
        graph = await nb.build_graph_for_accused(1)
        labels = {n["id"]: n["label"] for n in graph["nodes"]}
        assert labels["accused_1"] == "Suresh Nayak"
        assert labels["fir_8"] == "FIR/2024/JAY/0008"

    asyncio.run(scenario())
