"""Shared pytest configuration for the backend test suite.

Ensures the ``backend`` directory is importable so test modules can import
application packages (e.g. ``conversation.session_store``) the same way the
application does at runtime.
"""

import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
