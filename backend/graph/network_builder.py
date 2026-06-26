"""
Builds vis.js-compatible network graphs.
Deprecated case_relationships implementation has been stubbed for Step 3.
The real relationship derivation logic will be implemented in Step 4.
"""

async def build_graph_for_fir(fir_id: int) -> dict:
    """
    Build a network graph centered on a FIR.
    
    TODO: Step 4 — derive graph edges from Accused/CaseMaster per MIGRATE_STEP4.md
    """
    return {"nodes": [], "edges": []}


async def build_graph_for_accused(accused_id: int) -> dict:
    """
    Build a network graph centered on an accused person.
    
    TODO: Step 4 — derive graph edges from Accused/CaseMaster per MIGRATE_STEP4.md
    """
    return {"nodes": [], "edges": []}
