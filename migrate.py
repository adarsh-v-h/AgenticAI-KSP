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
        await cur.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='chat_messages' AND COLUMN_NAME='table_data_json'")
        row = await cur.fetchone()
        if row[0] == 0:
            await cur.execute('ALTER TABLE chat_messages ADD COLUMN table_data_json MEDIUMTEXT DEFAULT NULL')
            await conn.commit()
            print('Done - table_data_json column added')
        else:
            print('table_data_json already exists - skipping')

        await cur.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='chat_messages' AND COLUMN_NAME='follow_ups_json'")
        row = await cur.fetchone()
        if row[0] == 0:
            await cur.execute('ALTER TABLE chat_messages ADD COLUMN follow_ups_json TEXT DEFAULT NULL')
            await conn.commit()
            print('Done - follow_ups_json column added')
        else:
            print('follow_ups_json already exists - skipping')

        await cur.execute("SELECT CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='chat_sessions' AND COLUMN_NAME='session_id'")
        row = await cur.fetchone()
        if row is not None and row[0] is not None and row[0] < 50:
            await cur.execute('ALTER TABLE chat_sessions MODIFY session_id VARCHAR(50) NOT NULL')
            await conn.commit()
            print('Done - chat_sessions.session_id widened to VARCHAR(50)')
        else:
            print('chat_sessions.session_id already VARCHAR(50) or wider - skipping')

        await cur.execute("SELECT CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='chat_messages' AND COLUMN_NAME='session_id'")
        row = await cur.fetchone()
        if row is not None and row[0] is not None and row[0] < 50:
            await cur.execute('ALTER TABLE chat_messages MODIFY session_id VARCHAR(50) NOT NULL')
            await conn.commit()
            print('Done - chat_messages.session_id widened to VARCHAR(50)')
        else:
            print('chat_messages.session_id already VARCHAR(50) or wider - skipping')
    conn.close()

asyncio.run(run())
