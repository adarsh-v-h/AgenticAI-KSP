import sys
import os
import grpc

# Add backend/protos to sys.path for compiled imports
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_THIS_DIR)
_PROTOS_DIR = os.path.join(_BACKEND_DIR, "protos")
if _PROTOS_DIR not in sys.path:
    sys.path.insert(0, _PROTOS_DIR)

import services_pb2
import services_pb2_grpc

class LLMError(Exception):
    """Raised when an LLM call fails or returns an unexpected response."""
    pass


_channels = {}  # loop -> channel
_stubs = {}     # loop -> stub

def _get_grpc_stub() -> services_pb2_grpc.LLMServiceStub:
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
        channel = grpc.aio.insecure_channel('localhost:50051')
        _channels[loop] = channel
        _stubs[loop] = services_pb2_grpc.LLMServiceStub(channel)
    return _stubs[loop]

async def close_llm_client() -> None:
    global _channels, _stubs
    for channel in list(_channels.values()):
        try:
            await channel.close()
        except Exception:
            pass
    _channels.clear()
    _stubs.clear()


# CONTRACT
# takes:  model_key (str) — environment variable name resolving to model name
# returns: (bool) — True if model is available, False otherwise
# raises:  nothing
async def ping_model(model_key: str) -> bool:
    """Ping the standalone gRPC LLM Service."""
    stub = _get_grpc_stub()
    request = services_pb2.PingModelRequest(model_key=model_key)
    try:
        response = await stub.PingModel(request, timeout=30.0)
        return response.success
    except grpc.RpcError as e:
        print(f"WARNING: gRPC LLM ping failed for {model_key}: {e.details()}", file=sys.stderr)
        return False


# CONTRACT
# takes:  model_key (str) — env var name resolving to the model identifier (e.g. "MODEL_SQL"),
#          prompt (str) — user/task prompt to send to the model,
#          system_prompt (str) — system instruction for the model,
#          max_tokens (int) — maximum tokens to generate in the response
# returns: (str) — the model's non-empty response text
# raises:  LLMError — on gRPC error or empty response
async def call_llm(
    model_key: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int = 4000,
) -> str:
    """Call the standalone gRPC LLM Service."""
    stub = _get_grpc_stub()
    request = services_pb2.CallLLMRequest(
        model_key=model_key,
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens
    )
    try:
        response = await stub.CallLLM(request, timeout=180.0)
        if not response.text:
            raise LLMError("LLM Service returned empty response.")
        return response.text
    except grpc.RpcError as e:
        raise LLMError(f"gRPC LLM Service call failed: {e.details()}") from e
