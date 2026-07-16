# Dynamic Few-Shot Retrieval

## What it does

Instead of scoring few-shot examples by table overlap (current approach), score them by **semantic similarity to the current question**. The LLM sees the 3 most relevant NL→SQL examples for each question, improving SQL generation accuracy for unusual phrasings.

## Why it matters

- **SQL accuracy:** The right examples prime the LLM to generate correct patterns
- **Handles variety:** "Show me robbery cases" and "List all dacoity FIRs" should get the same examples, but keyword overlap misses this
- **Self-improving:** Adding new examples to the bank improves accuracy without changing prompts

## Current state

`db/schema_catalog.py` has a `_FEW_SHOT_BANK` (11 examples). `get_few_shot_examples(table_names)` scores by table-set overlap — if your selected tables match the example's tables, it scores higher. This works for simple cases but fails when:
- The user's phrasing doesn't map to table keywords cleanly
- Multiple examples tie on table score (falls back to insertion order)

## Implementation

### Approach: TF-IDF similarity (no external deps)

Use Python's `difflib.SequenceMatcher` or a simple TF-IDF with `sklearn` — but since we want zero new deps, use a **word-overlap Jaccard score** as a fast proxy for semantic similarity. This is not as good as embeddings but is dramatically better than table-only matching, and costs zero extra infrastructure.

### File: modify `backend/db/schema_catalog.py`

```python
def _question_similarity(q1: str, q2: str) -> float:
    """Jaccard similarity between two questions' word sets (case-insensitive, stop-words removed)."""
    stop = {"the", "a", "an", "is", "are", "how", "many", "show", "me", "all", "in", "of", "to", "for", "with", "what"}
    words1 = {w.lower().strip("?.,!") for w in q1.split()} - stop
    words2 = {w.lower().strip("?.,!") for w in q2.split()} - stop
    if not words1 or not words2:
        return 0.0
    return len(words1 & words2) / len(words1 | words2)


def get_few_shot_examples(table_names: list[str], question: str = "") -> str:
    """
    Return 3 example NL→SQL pairs relevant to the selected tables AND
    semantically similar to the current question.
    
    Scoring: table_overlap_score + question_similarity_score (weighted 0.4 / 0.6)
    """
    selected = set(table_names) | {"CaseMaster"}

    scored = []
    for idx, ex in enumerate(_FEW_SHOT_BANK):
        # Table overlap (existing logic)
        table_score = len(ex["tables"] & selected)
        unknown = ex["tables"] - selected
        if unknown:
            table_score -= len(unknown)
        
        # Question similarity (new)
        q_score = _question_similarity(question, ex["q"]) if question else 0.0
        
        # Combined score (question similarity weighted higher)
        combined = (table_score * 0.4) + (q_score * 5.0 * 0.6)
        scored.append((combined, idx, ex))

    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen = [ex for _score, _idx, ex in scored[:3]]

    blocks = []
    for ex in chosen:
        blocks.append(f"-- Q: {ex['q']}\n-- SQL:\n{ex['sql']}")
    return "\n\n".join(blocks)
```

### Wire the question into the call

In `backend/llm/sql_generator.py`, `generate_sql()` already calls:
```python
few_shots = get_few_shot_examples(table_names)
```

Change to:
```python
few_shots = get_few_shot_examples(table_names, question=question)
```

### Changes summary

| File | Change |
|------|--------|
| `backend/db/schema_catalog.py` | Add `_question_similarity()`, modify `get_few_shot_examples()` signature and scoring |
| `backend/llm/sql_generator.py` | Pass `question` to `get_few_shot_examples()` call (1 line) |

### What it does NOT change

- No new dependencies
- No frontend changes
- No DB changes
- Backward compatible (question param defaults to empty string)
- Same function interface, just smarter selection

### Testing

- "Show me robbery cases" → should select the "Mahesh Gowda" or "at large" examples (crime-related)
- "Who is investigating the most cases?" → should select the Employee/Rank example
- "List theft cases" → should select the "List theft cases" example (exact match scores highest)

### Effort: ~45 minutes
