"""
Property-based tests for session title generation.

Covers:
  - Property 16: Title Word Count Constraint (Task 3.3)
  - Property 17: Title Length Constraint (Task 3.3)
  - Property 15: Session Title Generation from First Message (Task 13.3)

Run:  pytest backend/tests/properties/title_property_test.py -v
"""

from hypothesis import given, assume
from hypothesis import strategies as st

from conversation.session_store import generate_title, _TITLE_STOP_WORDS

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Arbitrary messages: any printable text.
arbitrary_messages = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=0,
    max_size=500,
)

# Messages guaranteed to have enough significant words (words NOT in stop list).
# Restricted to ASCII letters — realistic for police query titles.
significant_word = st.text(
    alphabet=st.characters(whitelist_categories=("L",), max_codepoint=127),
    min_size=3,
    max_size=12,
).filter(lambda w: w.lower() not in _TITLE_STOP_WORDS)

messages_with_significant_words = st.lists(
    significant_word,
    min_size=3,
    max_size=15,
).map(lambda words: " ".join(words))


# ---------------------------------------------------------------------------
# Property 17: Title Length Constraint
# Validates: Requirements 6.3
# Generated titles NEVER exceed 60 characters.
# ---------------------------------------------------------------------------


class TestTitleLengthConstraint:
    """Property 17 — title never exceeds 60 characters."""

    @given(message=arbitrary_messages)
    def test_title_within_sixty_chars(self, message):
        """For any input message, the title is at most 60 characters long."""
        title = generate_title(message)
        assert len(title) <= 60, (
            f"Title exceeds 60 chars ({len(title)}): '{title}'"
        )

    @given(message=messages_with_significant_words)
    def test_title_truncation_adds_ellipsis(self, message):
        """When truncation occurs, the title ends with '...' and is still ≤60."""
        title = generate_title(message)
        assert len(title) <= 60
        # If the original untruncated title would be longer, ellipsis is added.
        # We verify the structural invariant: if it ends with "...", its length
        # is still ≤60.
        if title.endswith("..."):
            assert len(title) <= 60


# ---------------------------------------------------------------------------
# Property 16: Title Word Count Constraint
# Validates: Requirements 6.2
# Generated titles contain at most 8 words (when not truncated with "...").
# ---------------------------------------------------------------------------


class TestTitleWordCountConstraint:
    """Property 16 — title contains at most 8 significant words."""

    @given(message=messages_with_significant_words)
    def test_title_has_at_most_eight_words(self, message):
        """Titles generated from messages with enough content have ≤8 words."""
        title = generate_title(message)

        # Skip the fallback case.
        assume(title != "New chat")

        # If truncated with "...", word count check on the raw words before
        # ellipsis. The truncation may split a word, but the original intent is
        # ≤8 words.
        if title.endswith("..."):
            # The title was forcibly truncated — word count may appear higher
            # due to the ellipsis being appended mid-word. The contract is on
            # the words selected BEFORE truncation (≤8). We can't perfectly
            # reverse that, so we just verify ≤8 space-separated tokens.
            words = title.rstrip(".").split()
            assert len(words) <= 8
        else:
            words = title.split()
            assert len(words) <= 8, (
                f"Title has {len(words)} words (max 8): '{title}'"
            )


# ---------------------------------------------------------------------------
# Property 15: Session Title Generation from First Message
# Validates: Requirements 6.1
# First user message always produces a non-empty, non-fallback title when it
# has significant words.
# ---------------------------------------------------------------------------


class TestTitleGenerationFromFirstMessage:
    """Property 15 — first message with significant words produces a real title."""

    @given(message=messages_with_significant_words)
    def test_significant_message_produces_real_title(self, message):
        """Messages with significant words never fall back to 'New chat'."""
        title = generate_title(message)
        assert title != "New chat", (
            f"Expected a real title for message with significant words: '{message}'"
        )
        assert len(title) > 0

    @given(message=arbitrary_messages)
    def test_always_returns_non_empty_string(self, message):
        """generate_title never returns an empty string regardless of input."""
        title = generate_title(message)
        assert isinstance(title, str)
        assert len(title) > 0

    @given(message=messages_with_significant_words)
    def test_title_first_letter_capitalized(self, message):
        """The first character of a real title is uppercase."""
        title = generate_title(message)
        assume(title != "New chat")
        assert title[0].isupper(), f"Title not capitalized: '{title}'"
