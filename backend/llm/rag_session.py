"""
Conversational wrapper around rag_client.query_rag.

Zoho's /rag/answer endpoint is single-turn/stateless. This module:
1. Resolves pronouns/references ("that suspect", "him", "the accused") to
   the last concretely named entity from the prior turn, BEFORE sending to
   retrieval -- retrieval needs the explicit name to anchor on, a stitched
   prose context alone is not enough signal (confirmed via testing).
2. Stitches prior Q&A into each new query for connective reasoning.
3. Prompts the model to suggest follow-up questions after a grounded answer.

`history`, when provided, is the raw conversation-history list produced by
conversation.history.get_history() -- a list of {message_id, role, content,
timestamp, ...} dicts, alternating role="user"/"assistant". It is converted
to internal {"query": ..., "response": ...} turn pairs so contextual
stitching actually reflects prior chat turns, instead of always starting
empty (the previous bug: a fresh RagSession() was created per-request with
no history ever passed in).
"""
import re

from llm.rag_client import query_rag, RagResult
from llm.answer_formatter import generate_follow_ups


_REFERENCE_PATTERNS = [
    r"\bthat suspect\b", r"\bthe suspect\b", r"\bthe accused\b",
    r"\bthat person\b", r"\bthat individual\b", r"\bthem\b",
    r"\bhe\b", r"\bshe\b", r"\bhim\b", r"\bher\b", r"\bthey\b",
]

_NAME_PATTERN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")


class RagSession:
    def __init__(self, document_ids: list[str], history: list[dict] | None = None):
        self.document_ids = document_ids
        self.history: list[dict] = self._convert_history(history) if history else []
        self.last_entity: str | None = None
        # Seed last_entity from the most recent turn's response, if any, so
        # reference resolution ("that suspect") works on the very first
        # .ask() call of a session seeded with prior chat history.
        for turn in reversed(self.history):
            entity = self._extract_primary_entity(turn.get("response", ""))
            if entity:
                self.last_entity = entity
                break

    # CONTRACT
    # takes:  raw_history (list[dict]) — raw conversation history with role/content fields
    # returns: (list[dict]) — list of {"query": ..., "response": ...} turn pairs
    # raises:  nothing
    @staticmethod
    def _convert_history(raw_history: list[dict]) -> list[dict]:
        """
        Convert a raw {message_id, role, content, timestamp} history list
        (as returned by conversation.history.get_history()) into this
        class's internal {"query": ..., "response": ...} turn-pair format,
        pairing each user message with the assistant message that
        immediately follows it. Unpaired/trailing messages are dropped.
        """
        pairs: list[dict] = []
        pending_query: str | None = None
        for msg in raw_history:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "user":
                pending_query = content
            elif role == "assistant" and pending_query is not None:
                pairs.append({"query": pending_query, "response": content})
                pending_query = None
        return pairs

    # CONTRACT
    # takes:  text (str) — text to extract a primary named entity from
    # returns: (str | None) — first multi-word capitalized name found, or None
    # raises:  nothing
    def _extract_primary_entity(self, text: str) -> str | None:
        """First multi-word capitalized phrase in the text -- a simple but
        effective heuristic for 'Kavitha Raj', 'Puneeth Bhat' style names."""
        match = _NAME_PATTERN.search(text)
        return match.group(0) if match else None

    # CONTRACT
    # takes:  query (str) — user query potentially containing pronoun references
    # returns: (str) — query with pronoun references replaced by the last known entity name
    # raises:  nothing
    def _resolve_references(self, query: str) -> str:
        if not self.last_entity:
            return query
        resolved = query
        for pat in _REFERENCE_PATTERNS:
            resolved = re.sub(pat, self.last_entity, resolved, count=1, flags=re.IGNORECASE)
        return resolved

    # CONTRACT
    # takes:  resolved_query (str) — reference-resolved user query
    # returns: (str) — query with prior conversation context prepended for RAG
    # raises:  nothing
    def _build_contextual_query(self, resolved_query: str) -> str:
        if not self.history:
            return resolved_query
        context_lines = []
        for turn in self.history[-2:]:
            context_lines.append(f"Previous question: {turn['query']}")
            context_lines.append(f"Previous answer: {turn['response']}")
        context_block = "\n".join(context_lines)
        return (
            f"{context_block}\n\n"
            f"Follow-up question: {resolved_query}\n"
            f"(Answer the follow-up question using the case records. "
            f"If the follow-up relates to the previous answer, connect them explicitly.)"
        )

    # CONTRACT
    # takes:  case_context (str) — latest RAG response text to generate follow-ups from
    # returns: (list[str]) — up to 3 suggested follow-up questions for the investigator
    # raises:  nothing (delegates to answer_formatter.generate_follow_ups, which never raises)
    async def _generate_follow_ups(self, case_context: str) -> list[str]:
        """
        Generate 3 follow-up questions via the shared
        answer_formatter.generate_follow_ups() helper (a direct call_llm()
        under the hood — NOT query_rag(), which would try to "ground" a
        meta-instruction against case documents and silently return []).

        Includes the full conversation arc (self.history), not just the latest
        answer, so suggestions can reference earlier turns.
        """
        history_block = ""
        if self.history:
            lines = []
            for turn in self.history[-5:]:
                lines.append(f"Q: {turn['query']}")
                lines.append(f"A: {turn['response']}")
            history_block = "Conversation so far:\n" + "\n".join(lines) + "\n\n"

        return await generate_follow_ups(
            context_block=f"Latest case information: {case_context}",
            history_block=history_block,
        )

    # CONTRACT
    # takes:  query (str) — the user's raw question
    # returns: (dict) — response dict with grounded, response, sources, resolved_query, suggested_follow_ups
    # raises:  RuntimeError — when no Catalyst access token can be obtained,
    #           httpx.HTTPStatusError — when the RAG API returns a non-2xx status
    async def ask(self, query: str) -> dict:
        resolved_query = self._resolve_references(query)
        contextual_query = self._build_contextual_query(resolved_query)
        result: RagResult = await query_rag(contextual_query, self.document_ids)

        self.history.append({"query": query, "response": result.response})

        if result.grounded:
            entity = self._extract_primary_entity(result.response)
            if entity:
                self.last_entity = entity

        follow_ups = []
        if result.grounded:
            follow_ups = await self._generate_follow_ups(result.response)

        return {
            "grounded": result.grounded,
            "response": result.response,
            "sources": result.sources,
            "resolved_query": resolved_query,
            "suggested_follow_ups": follow_ups,
        }
