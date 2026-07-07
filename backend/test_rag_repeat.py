import asyncio
from llm.rag_client import query_rag

DOC_IDS = [
    "700000000003199", "700000000004191", "700000000004186",
    "700000000003217", "700000000003214", "700000000004179",
    "700000000003208", "700000000003207", "700000000003200",
]

async def main():
    query = "What happened in the Kavitha Raj case?"
    for i in range(1, 4):
        print(f"\n--- Run {i} ---")
        result = await query_rag(query, DOC_IDS)
        print(f"Grounded: {result.grounded}")
        print(f"Response: {result.response}")
        print(f"Sources: {result.sources}")

asyncio.run(main())
