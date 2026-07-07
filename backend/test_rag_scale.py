import asyncio
from llm.rag_client import query_rag

DOC_IDS = [
    "700000000003199", "700000000004191", "700000000004186",
    "700000000003217", "700000000003214", "700000000004179",
    "700000000003208", "700000000003207", "700000000003200",
]

async def run(label, query):
    print(f"\n--- {label} ---")
    print(f"Query: {query}")
    result = await query_rag(query, DOC_IDS)
    print(f"Grounded: {result.grounded}")
    print(f"Response: {result.response}")
    print(f"Sources: {result.sources}")

async def main():
    await run("Known-good anchored query", "What happened in the Kavitha Raj case?")
    await run("Known-absent anchored query", "What cases involve Ramesh Kulkarni?")
    await run("Vague query", "Are there any cases with a similar pattern of behavior?")
    await run("Partial-match query", "Is there a fraud case involving bank officers where the suspect is Manjunath Rao?")

asyncio.run(main())
