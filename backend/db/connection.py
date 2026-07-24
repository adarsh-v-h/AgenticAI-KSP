import sys
import os
import json
import grpc
import orjson

# Add backend/protos to sys.path for compiled imports
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_THIS_DIR)
_PROTOS_DIR = os.path.join(_BACKEND_DIR, "protos")
if _PROTOS_DIR not in sys.path:
    sys.path.insert(0, _PROTOS_DIR)

import services_pb2
import services_pb2_grpc

# Re-export lifespan management and execute_write from connection_real
from db.connection_real import create_pool, close_pool, get_pool, execute_write

_channels = {}  # loop -> channel
_stubs = {}     # loop -> stub

def _get_grpc_stub() -> services_pb2_grpc.SQLServiceStub:
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    
    global _channels, _stubs
    if loop not in _stubs:
        channel = grpc.aio.insecure_channel('localhost:50052')
        _channels[loop] = channel
        _stubs[loop] = services_pb2_grpc.SQLServiceStub(channel)
    return _stubs[loop]

async def close_sql_client() -> None:
    global _channels, _stubs
    for channel in list(_channels.values()):
        try:
            await channel.close()
        except Exception:
            pass
    _channels.clear()
    _stubs.clear()


# CONTRACT
# takes:  sql (str) — SELECT query to execute,
#          params (tuple) — parameterized query values
# returns: (list[dict]) — list of row dicts (column_name → value)
# raises:  RuntimeError — when query execution fails
async def execute_query(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a query via gRPC SQL Service."""
    # 1. Try to serve from local in-memory lookup cache first
    try:
        from db.lookup_cache import intercept_lookup_query
        cached_result = intercept_lookup_query(sql, params)
        if cached_result is not None:
            return cached_result
    except Exception as e:
        print(f"WARNING: Lookup cache interception failed: {e}", file=sys.stderr)

    stub = _get_grpc_stub()
    params_json = json.dumps(params) if params else ""
    request = services_pb2.ExecuteQueryRequest(query=sql, params_json=params_json)
    try:
        response = await stub.ExecuteQuery(request, timeout=5.0)
        if not response.rows_json:
            return []
        return orjson.loads(response.rows_json)
    except Exception as e:
        try:
            from db.connection_real import execute_query as execute_query_real
            return await execute_query_real(sql, params)
        except Exception as fallback_err:
            raise RuntimeError(f"Database query execution failed: {e}") from fallback_err
