# Conversation State Engine

## What it does

Instead of reparsing raw conversation history every turn, maintain a **structured dialogue state** that tracks what the officer is currently focused on. This gives the LLM compact, precise context instead of a wall of prior messages.

## Why it matters

- **Smaller prompts:** Instead of sending 5 turns of raw history (hundreds of tokens), send a 5-line state summary
- **Better follow-ups:** "Show me only the open ones" works reliably because the state tracks which crime type/station was last discussed
- **Context persistence:** Switching tabs and coming back doesn't lose what the officer was working on

## Current state

`conversation/history.py` stores raw `{role, content, sql, table}` turns (max 10). The pipeline dumps the last few turns into the SQL prompt and answer prompt as raw text. This works but is verbose and the LLM sometimes loses track of context in longer sessions.

## Implementation

### File: `backend/conversation/dialogue_state.py`

```python
"""
Structured dialogue state — extracted from conversation history.
Provides compact, machine-readable context for LLM prompts.
"""
import re


def extract_state(history: list[dict]) -> dict:
    """
    Parse the conversation history and extract a structured state dict.
    
    Returns:
    {
        "last_crime_type": str | None,   # e.g. "Theft", "Assault"
        "last_station": str | None,      # e.g. "Koramangala PS"
        "last_accused": str | None,      # e.g. "Mahesh Gowda"
        "last_case_id": int | None,      # CaseMasterID if discussed
        "date_range": str | None,        # e.g. "2024" or "last 6 months"
        "result_count": int | None,      # how many rows the last query returned
        "topic": str | None,             # general topic: "theft cases", "repeat offenders"
    }
    """
    state = {
        "last_crime_type": None,
        "last_station": None,
        "last_accused": None,
        "last_case_id": None,
        "date_range": None,
        "result_count": None,
        "topic": None,
    }

    # Walk history newest-first to extract the most recent context
    for turn in reversed(history or []):
        content = turn.get("content", "")
        role = turn.get("role", "")
        
        if role == "user" and not state["topic"]:
            # Use the last user question as the topic
            state["topic"] = content.strip()[:80]

        if role == "assistant":
            # Extract crime type mentions
            if not state["last_crime_type"]:
                for ct in ["Theft", "Assault", "Murder", "Robbery", "Fraud", "Drug", "Vehicle Theft", "Domestic Violence", "Missing Person"]:
                    if ct.lower() in content.lower():
                        state["last_crime_type"] = ct
                        break

            # Extract station names
            if not state["last_station"]:
                station_match = re.search(r"([\w\s]+ PS|[\w\s]+ Police Station)", content)
                if station_match:
                    state["last_station"] = station_match.group(1).strip()

            # Extract accused names (capitalized multi-word)
            if not state["last_accused"]:
                name_match = re.search(r"\b([A-Z][a-z]+ [A-Z][a-z]+(?:\s+\([^)]+\))?)\b", content)
                if name_match and name_match.group(1) not in ("Crime Type", "Police Station", "Case Status"):
                    state["last_accused"] = name_match.group(1)

            # Extract result count from table data
            table = turn.get("table")
            if isinstance(table, list) and not state["result_count"]:
                state["result_count"] = len(table)

    return state


def state_to_prompt_block(state: dict) -> str:
    """
    Convert the structured state into a compact prompt injection block.
    Only includes non-None fields.
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
        lines.append(f"Last result: {state['result_count']} rows")
    
    if not lines:
        return ""
    return "Conversation context:\n" + "\n".join(lines)
```

### Wire into `llm/prompts.py`

In `build_sql_prompt()`, replace the raw history dump with the compact state block:

```python
from conversation.dialogue_state import extract_state, state_to_prompt_block

# Instead of dumping raw history messages:
state = extract_state(history)
state_block = state_to_prompt_block(state)
if state_block:
    user_prompt_parts.append(state_block)
```

### Changes summary

| File | Change |
|------|--------|
| `backend/conversation/dialogue_state.py` | New file (~80 lines) |
| `backend/llm/prompts.py` | Replace raw history formatting in `build_sql_prompt()` with state extraction (~10 lines changed) |

### What it does NOT change

- No DB schema changes
- No frontend changes
- No conversation storage changes (raw history still saved as-is)
- No router changes
- The DIRECT answer path still uses full history for context (it needs the actual content)

### Testing

- Multi-turn: "Show theft cases" → "how many are open?" → second query should use Theft context from state
- State extraction from "There are 36 open theft cases at Koramangala PS" → crime_type=Theft, station=Koramangala PS

### Effort: ~1.5 hours
