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
