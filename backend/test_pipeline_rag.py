import asyncio
from pipeline.query_pipeline import run_pipeline
from db.connection import create_pool, close_pool

async def main():
    await create_pool()
    try:
        queries = [
            "Tell me a story about a brave police officer.",
            "Write a detailed narrative analysis of the Kavitha Raj case documents."
        ]
        for question in queries:
            print(f"\n========================================\nQuerying pipeline: '{question}'...")
            response = await run_pipeline(question=question)
            print(f"Response Text:\n{response.answer_text}")
            print(f"SQL Generated: '{response.sql_generated}'")
            print(f"Error: {response.error}")
            print(f"Suggested Follow-ups: {response.suggested_follow_ups}")
    finally:
        await close_pool()

if __name__ == "__main__":
    asyncio.run(main())
