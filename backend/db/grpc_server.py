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
from db.connection_real import execute_query

import decimal
from datetime import date, datetime

def _default_serialize(obj):
    if isinstance(obj, decimal.Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)

class SQLServiceServicer(services_pb2_grpc.SQLServiceServicer):
    async def ExecuteQuery(self, request, context):
        try:
            params = tuple(json.loads(request.params_json)) if request.params_json else ()
            rows = await execute_query(request.query, params)
            rows_json = orjson.dumps(rows, default=_default_serialize).decode()
            return services_pb2.ExecuteQueryResponse(rows_json=rows_json)
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return services_pb2.ExecuteQueryResponse()


_server = None

async def start_sql_grpc_server(port: int = 50052):
    global _server
    _server = grpc.aio.server()
    services_pb2_grpc.add_SQLServiceServicer_to_server(SQLServiceServicer(), _server)
    _server.add_insecure_port(f'[::]:{port}')
    await _server.start()
    print(f"gRPC SQL Service listening on port {port}", file=sys.stderr, flush=True)

async def stop_sql_grpc_server():
    global _server
    if _server is not None:
        await _server.stop(0)
        _server = None
