import asyncio
from llm.rag_client import query_rag

async def main():
    tests = [
        ("Known-good", "What happened in the Kavitha Raj case?"),
        ("Known-absent", "What cases involve Ramesh Kulkarni?"),
        ("Vague", "Are there any cases with a similar pattern of behavior?"),
        ("Partial-match", "Is there a fraud case involving bank officers where the suspect is Manjunath Rao?"),
        ("Messy grammar", "um so like was there any case where someone got scammed by fake bank people or something"),
    ]
    for label, query in tests:
        print(f"\n--- {label} ---")
        result = await query_rag(query, [])
        print(f"Grounded: {result.grounded}")
        print(f"Response: {result.response}")
        print(f"Sources: {result.sources}")

asyncio.run(main())
