# Backend Property Tests

Property-based tests for the chat-history-sidebar feature, using
[Hypothesis](https://hypothesis.readthedocs.io/).

## Naming convention

Property test files MUST match the pattern:

```
*_property_test.py
```

This pattern is registered in the repository-root `pytest.ini` (`python_files`),
so any file ending in `_property_test.py` under `backend/tests/` is collected.

Example: `session_metadata_property_test.py`

## Iteration minimum

Every property test runs a minimum of **100 examples**. This is enforced by the
Hypothesis profile registered in `conftest.py` (profile name `chs`,
`max_examples=100`), which is loaded automatically for this directory. Individual
tests do not need to set `max_examples`.

To raise the count for a specific test, layer an explicit `@settings` decorator:

```python
from hypothesis import given, settings, strategies as st

@settings(max_examples=500)
@given(st.text())
def test_title_generation_property(message):
    ...
```

## Running

```bash
pytest backend/tests/properties
```

## Requirement links

Each property test MUST link to the requirement it validates using the format:

```
**Validates: Requirements 1.2**
```
