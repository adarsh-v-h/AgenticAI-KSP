"""Unit tests for `conversation.session_store.generate_title`.

Covers the session title generation algorithm described in the design
"Session Title Generation" section and Requirements 6.1-6.5.
"""

from conversation.session_store import generate_title


def test_removes_stop_words_and_capitalizes():
    # "how", "many", "are" are stop words; "?" is stripped.
    assert generate_title("How many theft cases are open?") == "Theft cases open"


def test_strips_leading_stop_words():
    assert generate_title("Show me all cases involving Mahesh Gowda") == (
        "Cases involving mahesh gowda"
    )


def test_only_stop_words_falls_back():
    assert generate_title("the is are how many show me all") == "New chat"


def test_empty_message_falls_back():
    assert generate_title("") == "New chat"


def test_whitespace_only_falls_back():
    assert generate_title("   ") == "New chat"


def test_takes_at_most_eight_words():
    message = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    title = generate_title(message)
    assert len(title.split()) == 8


def test_fewer_than_three_significant_words_returns_available():
    # Only one significant word remains after dropping stop words.
    title = generate_title("show me theft")
    assert title == "Theft"


def test_title_does_not_exceed_sixty_characters():
    message = " ".join(["constabulary"] * 8)  # long words, > 60 chars when joined
    title = generate_title(message)
    assert len(title) <= 60
    assert title.endswith("...")


def test_punctuation_is_stripped_from_words():
    title = generate_title("theft, cases. open!")
    assert title == "Theft cases open"


def test_first_letter_capitalized():
    title = generate_title("vehicle theft cases")
    assert title[0].isupper()
