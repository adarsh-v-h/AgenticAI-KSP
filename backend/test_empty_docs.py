import asyncio
from llm.rag_client import query_rag

async def main():
    result = await query_rag("What happened in the Kavitha Raj case?", [])
    print(f"Grounded: {result.grounded}")
    print(f"Response: {result.response}")
    print(f"Sources: {result.sources}")

asyncio.run(main())
