"""Property-based test configuration for the chat-history-sidebar backend suite.

This conftest registers a Hypothesis settings profile that enforces the
project-wide convention of running a minimum of 100 examples per property.
All property tests in this directory follow the ``*_property_test.py`` naming
pattern (configured in the repository-root ``pytest.ini``).

Usage in a property test module::

    from hypothesis import given, strategies as st

    @given(st.integers())
    def test_some_property(value):
        ...

The "chs" (chat-history-sidebar) profile is loaded automatically below, so the
``max_examples=100`` minimum applies without per-test configuration.
"""

from hypothesis import HealthCheck, settings

# Minimum number of generated examples for every property test in this suite.
MIN_PROPERTY_ITERATIONS = 100

# Register and activate a profile enforcing the 100-iteration minimum.
settings.register_profile(
    "chs",
    max_examples=MIN_PROPERTY_ITERATIONS,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("chs")
