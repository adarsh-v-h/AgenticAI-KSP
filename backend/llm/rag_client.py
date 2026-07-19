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

from config.catalyst_token import get_access_token
from http_client import get_http_client

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_dotenv_path = os.path.join(_project_root, ".env")
_loaded = load_dotenv(dotenv_path=_dotenv_path)

CATALYST_ORG = os.getenv("CATALYST_ORG_ID", "") or os.getenv("KSP_CATALYST_ORG_ID", "")
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

    # CONTRACT
    # takes:  nothing
    # returns: (dict) — dictionary with grounded, response, and sources fields
    # raises:  nothing
    def to_dict(self):
        return {"grounded": self.grounded, "response": self.response, "sources": self.sources}


# CONTRACT
# takes:  text (str) — text to extract multi-word capitalized phrases and long numbers from
# returns: (set) — lowercased significant phrases and long numeric strings found in the text
# raises:  nothing
def _significant_phrases(text: str) -> set:
    phrases = _PHRASE_PATTERN.findall(text)
    numbers = _LONG_NUMBER_PATTERN.findall(text)
    return {p.lower() for p in phrases} | set(numbers)


# CONTRACT
# takes:  node_content (str) — text content of a retrieved RAG node,
#          response_phrases (set) — significant phrases extracted from the RAG response
# returns: (bool) — True if the node shares at least one significant phrase with the response
# raises:  nothing
def _node_supports_response(node_content: str, response_phrases: set) -> bool:
    if not response_phrases:
        return True
    node_phrases = _significant_phrases(node_content)
    return len(response_phrases & node_phrases) >= 1


# CONTRACT
# takes:  response_text (str) — RAG response text to check for negative/absence claims
# returns: (bool) — True if the response matches a negative claim pattern
# raises:  nothing
def _is_negative_claim(response_text: str) -> bool:
    lowered = response_text.lower()
    return any(re.search(pat, lowered) for pat in _NEGATIVE_CLAIM_PATTERNS)


# CONTRACT
# takes:  query (str) — raw user query potentially containing filler/hedging language
# returns: (str) — cleaned query with filler patterns removed and whitespace normalized
# raises:  nothing
def normalize_query(query: str) -> str:
    cleaned = query
    for pat in _FILLER_PATTERNS:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s+\?", "?", cleaned)
    return cleaned


# CONTRACT
# takes:  query (str) — the search query to send to the RAG endpoint,
#          document_ids (list[str]) — document IDs to scope the retrieval
# returns: (RagResult) — grounding status, response text, and filtered source references
# raises:  RuntimeError — when no Catalyst access token can be obtained,
#           httpx.HTTPStatusError — when the RAG API returns a non-2xx status
async def _query_rag_once(query: str, document_ids: list[str]) -> RagResult:
    access_token = await get_access_token()

    headers = {
        "CATALYST-ORG": CATALYST_ORG,
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }
    body = {"query": query, "documents": document_ids}

    client = get_http_client()
    resp = await client.post(RAG_URL, headers=headers, json=body, timeout=30.0)
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


# CONTRACT
# takes:  query (str) — the user's search query,
#          document_ids (list[str]) — document IDs to scope the retrieval
# returns: (RagResult) — grounding status, response text, and filtered source references
# raises:  RuntimeError — when no Catalyst access token can be obtained,
#           httpx.HTTPStatusError — when the RAG API returns a non-2xx status
async def query_rag(query: str, document_ids: list[str]) -> RagResult:
    result = await _query_rag_once(query, document_ids)
    if result.grounded:
        return result

    cleaned_query = normalize_query(query)
    if cleaned_query.lower() == query.strip().lower() or not cleaned_query:
        return result

    return await _query_rag_once(cleaned_query, document_ids)
