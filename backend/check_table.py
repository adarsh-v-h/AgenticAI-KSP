import asyncio
from db.connection import execute_query, create_pool, close_pool


async def main():
    await create_pool()
    try:
        rows = await execute_query(
            "SELECT COUNT(*) AS c FROM information_schema.tables WHERE table_name = 'offender_risk_scores'"
        )
        print(rows)
    finally:
        await close_pool()


asyncio.run(main())
