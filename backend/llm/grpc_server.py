import sys
import os
import asyncio
import grpc

# Add backend/protos to sys.path for compiled imports
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_THIS_DIR)
_PROTOS_DIR = os.path.join(_BACKEND_DIR, "protos")
if _PROTOS_DIR not in sys.path:
    sys.path.insert(0, _PROTOS_DIR)

import services_pb2
import services_pb2_grpc
from llm.client_real import call_llm, ping_model

class LLMServiceServicer(services_pb2_grpc.LLMServiceServicer):
    async def CallLLM(self, request, context):
        try:
            text = await call_llm(
                model_key=request.model_key,
                prompt=request.prompt,
                system_prompt=request.system_prompt,
                max_tokens=request.max_tokens or 4000
            )
            return services_pb2.CallLLMResponse(text=text)
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return services_pb2.CallLLMResponse()

    async def PingModel(self, request, context):
        try:
            success = await ping_model(request.model_key)
            return services_pb2.PingModelResponse(success=success)
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return services_pb2.PingModelResponse(success=False)


_server = None

async def start_llm_grpc_server(port: int = 50051):
    global _server
    _server = grpc.aio.server()
    services_pb2_grpc.add_LLMServiceServicer_to_server(LLMServiceServicer(), _server)
    _server.add_insecure_port(f'[::]:{port}')
    await _server.start()
    print(f"gRPC LLM Service listening on port {port}", file=sys.stderr, flush=True)

async def stop_llm_grpc_server():
    global _server
    if _server is not None:
        await _server.stop(0)
        _server = None
