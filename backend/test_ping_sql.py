import asyncio
from llm.client import ping_model

async def main():
    print("Checking MODEL_SQL...")
    ok = await ping_model("MODEL_SQL")
    print(f"MODEL_SQL reachable: {ok}")

asyncio.run(main())
