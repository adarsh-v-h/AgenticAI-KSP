import asyncio
from llm.rag_client import query_rag

DOCS = [
    "700000000003185","700000000003183","700000000003179","700000000003175",
    "700000000003170","700000000003161","700000000003159","700000000003155",
    "700000000003152","700000000003151","700000000003132","700000000003131",
    "700000000003128","700000000003124","700000000003111","700000000003110",
    "700000000003109","700000000003108","700000000003107","700000000003100"
]


async def main():
    result = await query_rag(
        "Which cases involve Chethan Shetty, and is there a pattern in how these crimes were committed?",
        DOCS
    )
    print(f"Grounded: {result.grounded}")
    print(f"Response: {result.response}")
    print(f"Sources: {result.sources}")

    print("\n--- Testing grounding block with an unanchored vague query ---")
    result2 = await query_rag("Are there any cases with similar modus operandi?", DOCS)
    print(f"Grounded: {result2.grounded}")
    print(f"Response: {result2.response}")


asyncio.run(main())
