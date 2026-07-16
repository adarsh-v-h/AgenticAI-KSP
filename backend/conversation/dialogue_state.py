"""
Structured dialogue state — extracted from conversation history.
Provides compact, machine-readable context for LLM prompts instead of
dumping raw history turns.
"""
import re


# CONTRACT
# takes:  history (list[dict]) — conversation history with role/content/table fields
# returns: (dict) — structured state with last_crime_type, last_station, last_accused, etc.
# raises:  nothing
def extract_state(history: list[dict]) -> dict:
    """
    Parse conversation history and extract structured dialogue state.
    Walks newest-first to get the most recent context.
    """
    state = {
        "last_crime_type": None,
        "last_station": None,
        "last_accused": None,
        "last_case_id": None,
        "result_count": None,
        "topic": None,
    }

    crime_types = [
        "Theft", "Assault", "Murder", "Robbery", "Fraud", "Drug Offense",
        "Vehicle Theft", "Domestic Violence", "Missing Person", "Phishing",
        "Online Harassment", "Hacking", "Identity Theft",
    ]

    for turn in reversed(history or []):
        content = turn.get("content", "")
        role = turn.get("role", "")

        if role == "user" and not state["topic"]:
            state["topic"] = content.strip()[:80]

        if role == "assistant":
            # Extract crime type
            if not state["last_crime_type"]:
                for ct in crime_types:
                    if ct.lower() in content.lower():
                        state["last_crime_type"] = ct
                        break

            # Extract station names (patterns like "X PS" or "X Police Station")
            if not state["last_station"]:
                station_match = re.search(r"([\w\s]+(?:PS|Police Station))", content)
                if station_match:
                    state["last_station"] = station_match.group(1).strip()

            # Extract accused names (multi-word capitalized, skip common false positives)
            if not state["last_accused"]:
                skip = {"Crime Type", "Police Station", "Case Status", "Under Investigation",
                        "Crime No", "Case Master", "Accused Name"}
                name_match = re.search(r"\b([A-Z][a-z]+ [A-Z][a-z]+(?:\s+\([^)]+\))?)\b", content)
                if name_match and name_match.group(1) not in skip:
                    state["last_accused"] = name_match.group(1)

            # Extract result count from table snapshot
            table = turn.get("table")
            if isinstance(table, list) and not state["result_count"]:
                state["result_count"] = len(table)

    return state


# CONTRACT
# takes:  state (dict) — structured state dict from extract_state()
# returns: (str) — compact multi-line context block for LLM prompt injection, empty string if no state
# raises:  nothing
def state_to_prompt_block(state: dict) -> str:
    """
    Convert structured state into a compact prompt injection block.
    Only includes non-None fields. Returns "" if nothing to inject.
    """
    lines = []
    if state.get("topic"):
        lines.append(f"Current topic: {state['topic']}")
    if state.get("last_crime_type"):
        lines.append(f"Crime type in focus: {state['last_crime_type']}")
    if state.get("last_station"):
        lines.append(f"Station in focus: {state['last_station']}")
    if state.get("last_accused"):
        lines.append(f"Accused in focus: {state['last_accused']}")
    if state.get("result_count") is not None:
        lines.append(f"Last result set: {state['result_count']} rows")

    if not lines:
        return ""
    return "Conversation context:\n" + "\n".join(lines)
