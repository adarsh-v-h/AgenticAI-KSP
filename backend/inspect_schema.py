import asyncio
from db.connection import execute_query, create_pool, close_pool


async def main():
    await create_pool()
    try:
        columns = await execute_query("""
            SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """)

        current_table = None
        for col in columns:
            table = col["TABLE_NAME"]
            if table != current_table:
                print(f"\n=== {table} ===")
                current_table = table

            data_type = col["DATA_TYPE"]
            max_len = col["CHARACTER_MAXIMUM_LENGTH"]

            is_text_like = (
                data_type.lower() in ("text", "mediumtext", "longtext")
                or (data_type.lower() == "varchar" and max_len and max_len > 200)
            )
            flag = "  <-- possible narrative field" if is_text_like else ""
            len_str = f"({max_len})" if max_len else ""
            print(f"  {col['COLUMN_NAME']:30s} {data_type}{len_str}{flag}")
    finally:
        await close_pool()


asyncio.run(main())
