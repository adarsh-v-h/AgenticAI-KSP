"""Shared pytest configuration for the backend test suite.

Ensures the ``backend`` directory is importable so test modules can import
application packages (e.g. ``conversation.session_store``) the same way the
application does at runtime.
"""

import os
import sys
import pytest

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


@pytest.fixture(autouse=True)
def clear_db_caches():
    """Clear all database caches before every test for test isolation."""
    from db.chat_store import clear_caches
    clear_caches()
    yield
    clear_caches()
