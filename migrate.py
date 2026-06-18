import asyncio

env = {}
with open('.env') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()

async def run():
    import aiomysql
    conn = await aiomysql.connect(
        host=env['DB_HOST'], port=int(env['DB_PORT']),
        user=env['DB_USER'], password=env['DB_PASSWORD'], db=env['DB_NAME']
    )
    async with conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_NAME='chat_messages' AND COLUMN_NAME='table_data_json'")
        row = await cur.fetchone()
        if row[0] == 0:
            await cur.execute('ALTER TABLE chat_messages ADD COLUMN table_data_json MEDIUMTEXT DEFAULT NULL')
            await conn.commit()
            print('Done - column added')
        else:
            print('Column already exists - skipping')
    conn.close()

asyncio.run(run())
