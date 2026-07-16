# Rule Engine Before LLM

## What it does

A lightweight pattern-matching layer that intercepts obvious non-data requests BEFORE they hit the LLM. Greetings, help requests, thanks, and simple navigation never burn an LLM call — they get instant deterministic responses.

## Why it matters

- **Latency:** 0ms vs 3-4s for a "hello" or "thank you"
- **Cost:** Zero tokens used on trivial messages
- **Reliability:** Deterministic responses never hallucinate on greetings

## Current state

We partially have this — `NARRATIVE_KEYWORDS` in `query_pipeline.py` routes summarization questions to RAG before SQL. But greetings, thanks, help, and other non-data messages still go through the full LLM router → DIRECT answer path (2 LLM calls wasted).

## Implementation

### File: `backend/pipeline/rule_engine.py`

```python
"""
Lightweight rule engine — intercepts trivial messages before LLM.
Returns an instant response or None (pass-through to the pipeline).
"""
import re

# Pattern → response pairs. Checked in order, first match wins.
_RULES = [
    # Greetings
    (r"^(hi|hello|hey|good\s*(morning|afternoon|evening)|namaste)\b",
     "Hello! I'm your crime intelligence assistant. Ask me about cases, accused persons, crime trends, or anything from the KSP database."),

    # Thanks
    (r"^(thanks?|thank\s*you|thx|cheers|great|perfect|ok\s*thanks)\b",
     "You're welcome. Let me know if you need anything else."),

    # Help / capabilities
    (r"^(help|what\s*can\s*you\s*do|capabilities|features)\b",
     "I can help you with:\n• Query crime records (FIRs, accused, victims)\n• Crime trend analytics and patterns\n• Offender risk profiling\n• Case timelines and summaries\n• Finding similar cases\n• Voice input in English and Kannada\n\nJust ask a question in natural language."),

    # Who are you
    (r"^(who\s*are\s*you|what\s*are\s*you)\b",
     "I'm the KSP Crime Intelligence Assistant — a natural language interface to the Karnataka State Police crime database."),

    # Bye
    (r"^(bye|goodbye|see\s*you|quit|exit)\b",
     "Goodbye! Stay safe."),
]

_COMPILED_RULES = [(re.compile(pattern, re.IGNORECASE), response) for pattern, response in _RULES]


def try_rule_response(question: str) -> str | None:
    """
    Check the question against the rule engine.
    Returns a response string if matched, None if the question should
    proceed to the full LLM pipeline.
    """
    stripped = question.strip()
    if not stripped:
        return None
    for pattern, response in _COMPILED_RULES:
        if pattern.search(stripped):
            return response
    return None
```

### Wire into `pipeline/query_pipeline.py`

At the very top of `run_pipeline()`, before the narrative keyword check:

```python
from pipeline.rule_engine import try_rule_response

# Right after `response = PipelineResponse()`:
rule_answer = try_rule_response(question)
if rule_answer is not None:
    response.answer_text = rule_answer
    return response
```

### Changes summary

| File | Change |
|------|--------|
| `backend/pipeline/rule_engine.py` | New file (~40 lines) |
| `backend/pipeline/query_pipeline.py` | Add 4 lines at top of `run_pipeline()` |

### What it does NOT change

- No LLM prompt changes
- No router changes
- No frontend changes
- No DB changes
- Passes through cleanly to the existing pipeline for any real data question

### Testing

- "hello" → instant response, no LLM call
- "thanks" → instant response
- "How many theft cases?" → passes through to pipeline (returns None)
- "help" → instant capability list

### Effort: ~30 minutes
