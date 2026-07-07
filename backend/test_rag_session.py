import asyncio
from llm.rag_session import RagSession

DOC_IDS = [
    "700000000003199", "700000000004191", "700000000004186",
    "700000000003217", "700000000003214", "700000000004179",
    "700000000003208", "700000000003207", "700000000003200",
]

async def main():
    session = RagSession(DOC_IDS)

    print("--- Turn 1 ---")
    r1 = await session.ask("What happened in the Kavitha Raj case?")
    print(f"Response: {r1['response']}")
    print(f"Sources: {r1['sources']}")
    print(f"Follow-ups: {r1['suggested_follow_ups']}")

    print("\n--- Turn 2 (follow-up) ---")
    r2 = await session.ask("Was that suspect involved in any other reported cases?")
    print(f"Response: {r2['response']}")
    print(f"Sources: {r2['sources']}")
    print(f"Follow-ups: {r2['suggested_follow_ups']}")

asyncio.run(main())
