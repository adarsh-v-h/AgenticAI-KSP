"""
RAG client for KSP case-report retrieval via Zoho Catalyst QuickML.

Grounding rule 1: zero retrieved_nodes -> honest "not found" fallback.
Grounding rule 2: sources are filtered to nodes that actually share
multi-word phrases (names, locations) or long crime numbers with the
response -- NOT single capitalized words. Single-word matching was found
to false-positive on words that repeat across many documents in this
dataset (e.g. "Koramangala" as a shared police station name, or a bare
year like "2022" appearing in nearly every case). Multi-word phrases like
"Kavitha Raj" or "Electronic City" are a much more reliable fingerprint
that a specific document actually contributed to a specific response.
Grounding rule 3: negative/absence-style responses never carry sources,
since such a claim summarizes an absence across the whole retrieved set,
not a fact restated from one specific document.
Query robustness: if ungrounded, retry once with filler/hedging language
stripped, without lowering the grounding bar on the retry itself.
"""
import os
import re
import httpx
from dotenv import load_dotenv

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_dotenv_path = os.path.join(_project_root, ".env")
_loaded = load_dotenv(dotenv_path=_dotenv_path)

CATALYST_ORG = os.getenv("CATALYST_ORG_ID", "60073906151")
CATALYST_PROJECT_ID = os.getenv("CATALYST_PROJECT_ID")
RAG_URL = f"https://api.catalyst.zoho.in/quickml/v1/project/{CATALYST_PROJECT_ID}/rag/answer"

_NEGATIVE_CLAIM_PATTERNS = [
    r"\bno other\b", r"\bnot listed\b", r"\bno relevant\b",
    r"\bnone (of|are) listed\b", r"\bno record[s]? (of|found)\b",
    r"\bare not (any|found)\b", r"\bno (case|cases) (found|listed|involving)\b",
]

_FILLER_PATTERNS = [
    r"\bkind of\b", r"\bsort of\b", r"\byou know\b", r"\bi think\b",
    r"\bmaybe\b", r"\bbasically\b", r"\bactually\b", r"\blike\b",
    r"\bum+\b", r"\buh+\b", r"\bplease\b", r"\bcan you\b", r"\bcould you\b",
    r"\bi (want|wanted|would like) to (know|ask)\b", r"\bjust wondering\b",
]

# Multi-word capitalized phrases (names, locations) -- a single capitalized
# word is too common across a shared dataset to be a reliable fingerprint.
_PHRASE_PATTERN = re.compile(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+\b")
# Crime/case numbers in this dataset run ~18 digits -- long enough to be
# unique. A bare 4-digit year is NOT unique (nearly every case is the same year).
_LONG_NUMBER_PATTERN = re.compile(r"\d{10,}")


class RagResult:
    def __init__(self, grounded: bool, response: str, sources: list):
        self.grounded = grounded
        self.response = response
        self.sources = sources

    def to_dict(self):
        return {"grounded": self.grounded, "response": self.response, "sources": self.sources}


def _significant_phrases(text: str) -> set:
    phrases = _PHRASE_PATTERN.findall(text)
    numbers = _LONG_NUMBER_PATTERN.findall(text)
    return set(p.lower() for p in phrases) | set(numbers)


def _node_supports_response(node_content: str, response_phrases: set) -> bool:
    if not response_phrases:
        return True
    node_phrases = _significant_phrases(node_content)
    return len(response_phrases & node_phrases) >= 1


def _is_negative_claim(response_text: str) -> bool:
    lowered = response_text.lower()
    return any(re.search(pat, lowered) for pat in _NEGATIVE_CLAIM_PATTERNS)


def normalize_query(query: str) -> str:
    cleaned = query
    for pat in _FILLER_PATTERNS:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s+\?", "?", cleaned)
    return cleaned


async def _query_rag_once(query: str, document_ids: list[str]) -> RagResult:
    access_token = os.getenv("CATALYST_API_TOKEN")
    if not access_token:
        raise RuntimeError(
            f"CATALYST_API_TOKEN not set. .env path tried: {_dotenv_path} "
            f"(exists: {os.path.exists(_dotenv_path)}, load_dotenv returned: {_loaded})"
        )

    headers = {
        "CATALYST-ORG": CATALYST_ORG,
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }
    body = {"query": query, "documents": document_ids}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(RAG_URL, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

    retrieved = data.get("retrieved_nodes", [])

    if not retrieved:
        return RagResult(
            grounded=False,
            response="No relevant case records were found for this query. "
                     "Try rephrasing with a specific name, location, or crime type.",
            sources=[],
        )

    response_text = data.get("response", "")

    if _is_negative_claim(response_text):
        return RagResult(grounded=True, response=response_text, sources=[])

    response_phrases = _significant_phrases(response_text)
    sources = [
        {"document_title": node.get("document_title"), "document_id": node.get("document_id")}
        for node in retrieved
        if _node_supports_response(node.get("content", ""), response_phrases)
    ]

    return RagResult(grounded=True, response=response_text, sources=sources)


async def query_rag(query: str, document_ids: list[str]) -> RagResult:
    result = await _query_rag_once(query, document_ids)
    if result.grounded:
        return result

    cleaned_query = normalize_query(query)
    if cleaned_query.lower() == query.strip().lower() or not cleaned_query:
        return result

    return await _query_rag_once(cleaned_query, document_ids)
