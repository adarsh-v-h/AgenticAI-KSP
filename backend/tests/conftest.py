"""Shared pytest configuration for the backend test suite.

Ensures the ``backend`` directory is importable so test modules can import
application packages (e.g. ``conversation.session_store``) the same way the
application does at runtime.
"""

import os
import sys
import pytest
import threading
import asyncio

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


class GrpcServerThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.loop = None
        self.daemon = True

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        from db.connection_real import create_pool
        from llm.grpc_server import start_llm_grpc_server
        from db.grpc_server import start_sql_grpc_server
        from http_client import init_http_client

        init_http_client()
        try:
            self.loop.run_until_complete(create_pool())
        except Exception:
            pass

        self.loop.run_until_complete(start_llm_grpc_server())
        self.loop.run_until_complete(start_sql_grpc_server())
        self.loop.run_forever()

    def stop(self):
        if self.loop:
            from llm.grpc_server import stop_llm_grpc_server
            from db.grpc_server import stop_sql_grpc_server
            from db.connection_real import close_pool
            from http_client import close_http_client
            
            async def cleanup():
                await stop_llm_grpc_server()
                await stop_sql_grpc_server()
                try:
                    await close_pool()
                except Exception:
                    pass
                await close_http_client()
            
            try:
                future = asyncio.run_coroutine_threadsafe(cleanup(), self.loop)
                future.result(timeout=5.0)
            except Exception:
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)


@pytest.fixture(autouse=True)
def clear_db_caches():
    """Clear all database caches before every test for test isolation."""
    from db.chat_store import clear_caches
    clear_caches()
    yield
    clear_caches()


@pytest.fixture(scope="session", autouse=True)
def run_grpc_servers():
    """Start gRPC servers in background thread so they remain unblocked during pytest asyncio.run() tests."""
    from llm.client import close_llm_client
    from db.connection import close_sql_client

    t = GrpcServerThread()
    t.start()
    
    # Let gRPC servers initialize
    import time
    time.sleep(0.5)
    
    yield
    
    t.stop()
    t.join(timeout=5.0)
    
    # Close clients on the main thread loops
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(close_llm_client())
    loop.run_until_complete(close_sql_client())
