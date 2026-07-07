import asyncio
from llm.sql_generator import generate_sql

async def main():
    try:
        sql = await generate_sql(
            question="How many theft cases are open?",
            table_names=["casemaster"],
            history=None,
        )
        print("SQL generated successfully:")
        print(sql)
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")

asyncio.run(main())
