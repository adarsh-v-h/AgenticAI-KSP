"""
Builds vis.js-compatible network graphs from `case_relationships`.

A graph is a dict of the shape::

    {"nodes": [{"id": "fir_2", "label": "FIR/2024/KOR/0042", "group": "fir"}, ...],
     "edges": [{"from": "fir_2", "to": "accused_5", "label": "co_accused"}, ...]}

Node ids are namespaced by entity type (`fir_{id}`, `accused_{id}`, ...) so the
same numeric id across different entity tables never collides.

Both public builders NEVER raise — on any error or when no relationships exist
they return an empty graph (`{"nodes": [], "edges": []}`), because the graph is
a non-critical enhancement and must never break a request.
"""

import sys

from db.connection import execute_query

MAX_NODES = 50

# Entity types stored in case_relationships.entity_a_type / entity_b_type.
_VALID_ENTITY_TYPES = {"accused", "fir", "victim", "officer"}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _node_id(entity_type: str, entity_id: int) -> str:
    return f"{entity_type}_{entity_id}"


def _fallback_label(entity_type: str, entity_id: int) -> str:
    """Human-readable label used when a DB label lookup misses (e.g. row
    deleted). Keeps node labels readable instead of showing the raw node id."""
    return f"{entity_type.capitalize()} {entity_id}"


async def _fetch_relationships(entity_type: str, entity_ids: list[int]) -> list[dict]:
    """
    Return every case_relationships row where one side matches
    (entity_type, entity_id) for any id in `entity_ids`. Parameterized — never
    interpolates ids into SQL. Returns [] when entity_ids is empty.
    """
    if not entity_ids:
        return []
    placeholders = ",".join(["%s"] * len(entity_ids))
    sql = (
        "SELECT rel_id, entity_a_type, entity_a_id, entity_b_type, entity_b_id, "
        "relationship_type "
        "FROM case_relationships "
        f"WHERE (entity_a_type = %s AND entity_a_id IN ({placeholders})) "
        f"   OR (entity_b_type = %s AND entity_b_id IN ({placeholders}))"
    )
    params = (entity_type, *entity_ids, entity_type, *entity_ids)
    return await execute_query(sql, params)


async def _label_lookup(entity_refs: set[tuple[str, int]]) -> dict[tuple[str, int], str]:
    """
    Resolve a human-readable label for each (entity_type, entity_id) reference.

    - fir      → fir_master.fir_number
    - accused  → accused.full_name
    - victim   → victims.full_name
    - officer  → officers.full_name

    Falls back to a generic "{Type} {id}" label when the row is missing. One
    grouped query per entity type (at most four small queries total).
    """
    labels: dict[tuple[str, int], str] = {}

    by_type: dict[str, list[int]] = {}
    for etype, eid in entity_refs:
        by_type.setdefault(etype, []).append(eid)

    table_col = {
        "fir": ("fir_master", "fir_id", "fir_number"),
        "accused": ("accused", "accused_id", "full_name"),
        "victim": ("victims", "victim_id", "full_name"),
        "officer": ("officers", "officer_id", "full_name"),
    }

    for etype, ids in by_type.items():
        spec = table_col.get(etype)
        if not spec or not ids:
            continue
        table, id_col, label_col = spec
        placeholders = ",".join(["%s"] * len(ids))
        sql = (
            f"SELECT {id_col} AS eid, {label_col} AS label "
            f"FROM {table} WHERE {id_col} IN ({placeholders})"
        )
        try:
            rows = await execute_query(sql, tuple(ids))
        except Exception as e:
            _log(f"graph label lookup failed for {etype}: {e}")
            rows = []
        found = {row["eid"]: row.get("label") for row in rows}
        for eid in ids:
            label = found.get(eid)
            labels[(etype, eid)] = label if label else _fallback_label(etype, eid)

    return labels


def _build_nodes_and_edges(
    relationships: list[dict],
    labels: dict[tuple[str, int], str],
    center_id: str,
) -> dict:
    """
    Turn raw relationship rows into vis.js nodes + edges, then trim to MAX_NODES
    (always keeping the center node). De-duplicates nodes by id and edges by the
    (from, to, label) triple.
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen_edges: set[tuple[str, str, str]] = set()

    for rel in relationships:
        a_type = rel.get("entity_a_type")
        b_type = rel.get("entity_b_type")
        a_id = rel.get("entity_a_id")
        b_id = rel.get("entity_b_id")
        rel_type = rel.get("relationship_type") or "linked"

        if a_type not in _VALID_ENTITY_TYPES or b_type not in _VALID_ENTITY_TYPES:
            continue
        if a_id is None or b_id is None:
            continue

        a_node = _node_id(a_type, a_id)
        b_node = _node_id(b_type, b_id)

        nodes.setdefault(
            a_node,
            {"id": a_node, "label": labels.get((a_type, a_id)) or _fallback_label(a_type, a_id), "group": a_type},
        )
        nodes.setdefault(
            b_node,
            {"id": b_node, "label": labels.get((b_type, b_id)) or _fallback_label(b_type, b_id), "group": b_type},
        )

        edge_key = (a_node, b_node, rel_type)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        edges.append({"from": a_node, "to": b_node, "label": rel_type})

    node_list = list(nodes.values())
    node_list, edges = _trim_to_max_nodes(node_list, edges, center_id)
    return {"nodes": node_list, "edges": edges}


def _trim_to_max_nodes(
    nodes: list[dict], edges: list[dict], center_id: str
) -> tuple[list[dict], list[dict]]:
    """
    If len(nodes) > MAX_NODES: keep the MAX_NODES highest-degree nodes (by edge
    count), always retaining the center node, then drop edges that reference a
    removed node. Returns (kept_nodes, kept_edges) unchanged when already within
    the cap.
    """
    if len(nodes) <= MAX_NODES:
        return nodes, edges

    degree: dict[str, int] = {n["id"]: 0 for n in nodes}
    for e in edges:
        if e["from"] in degree:
            degree[e["from"]] += 1
        if e["to"] in degree:
            degree[e["to"]] += 1

    # Sort by degree desc, but force the center node to the front so it survives.
    def sort_key(node: dict) -> tuple[int, int]:
        is_center = 1 if node["id"] == center_id else 0
        return (is_center, degree.get(node["id"], 0))

    ranked = sorted(nodes, key=sort_key, reverse=True)
    kept = ranked[:MAX_NODES]
    kept_ids = {n["id"] for n in kept}

    kept_edges = [e for e in edges if e["from"] in kept_ids and e["to"] in kept_ids]
    return kept, kept_edges


async def build_graph_for_fir(fir_id: int) -> dict:
    """
    Build a network graph centered on a FIR.

    Includes:
      - relationships directly involving this FIR (related_case, etc.)
      - the accused linked to this FIR, and any relationships those accused
        participate in (co_accused links, etc.)

    Returns {"nodes": [...], "edges": [...]}; empty graph on error or no links.
    Never raises.
    """
    try:
        center = _node_id("fir", fir_id)

        # Accused attached to this FIR — their links extend the network.
        try:
            accused_rows = await execute_query(
                "SELECT accused_id FROM accused WHERE fir_id = %s", (fir_id,)
            )
        except Exception as e:
            _log(f"graph: accused lookup failed for fir {fir_id}: {e}")
            accused_rows = []
        accused_ids = [r["accused_id"] for r in accused_rows if r.get("accused_id") is not None]

        fir_rels = await _fetch_relationships("fir", [fir_id])
        accused_rels = await _fetch_relationships("accused", accused_ids)

        relationships = _dedupe_relationships(fir_rels + accused_rels)
        if not relationships:
            return {"nodes": [], "edges": []}

        labels = await _label_lookup(_collect_entity_refs(relationships))
        return _build_nodes_and_edges(relationships, labels, center)
    except Exception as e:
        _log(f"build_graph_for_fir failed for {fir_id}: {e}")
        return {"nodes": [], "edges": []}


async def build_graph_for_accused(accused_id: int) -> dict:
    """
    Build a network graph centered on an accused person.

    Includes every relationship that this accused participates in (on either
    side), with related entities (other accused, FIRs) resolved to display
    labels.

    Returns {"nodes": [...], "edges": [...]}; empty graph on error or no links.
    Never raises.
    """
    try:
        center = _node_id("accused", accused_id)
        relationships = await _fetch_relationships("accused", [accused_id])
        if not relationships:
            return {"nodes": [], "edges": []}

        labels = await _label_lookup(_collect_entity_refs(relationships))
        return _build_nodes_and_edges(relationships, labels, center)
    except Exception as e:
        _log(f"build_graph_for_accused failed for {accused_id}: {e}")
        return {"nodes": [], "edges": []}


def _dedupe_relationships(relationships: list[dict]) -> list[dict]:
    """Drop duplicate rows that can appear when FIR-side and accused-side
    queries both return the same rel_id."""
    seen: set = set()
    out: list[dict] = []
    for rel in relationships:
        key = rel.get("rel_id")
        if key is None:
            # No rel_id (shouldn't happen) — fall back to a structural key.
            key = (
                rel.get("entity_a_type"), rel.get("entity_a_id"),
                rel.get("entity_b_type"), rel.get("entity_b_id"),
                rel.get("relationship_type"),
            )
        if key in seen:
            continue
        seen.add(key)
        out.append(rel)
    return out


def _collect_entity_refs(relationships: list[dict]) -> set[tuple[str, int]]:
    """Gather every (entity_type, entity_id) reference appearing in the rows so
    labels can be resolved in grouped queries."""
    refs: set[tuple[str, int]] = set()
    for rel in relationships:
        a_type, a_id = rel.get("entity_a_type"), rel.get("entity_a_id")
        b_type, b_id = rel.get("entity_b_type"), rel.get("entity_b_id")
        if a_type in _VALID_ENTITY_TYPES and a_id is not None:
            refs.add((a_type, a_id))
        if b_type in _VALID_ENTITY_TYPES and b_id is not None:
            refs.add((b_type, b_id))
    return refs
