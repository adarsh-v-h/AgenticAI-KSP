import asyncio
import json
from datetime import date, datetime, timedelta

env = {}
with open('.env') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()

def serialize(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        total = int(obj.total_seconds())
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02}:{m:02}:{s:02}"
    raise TypeError(f"Not serializable: {type(obj)}")

async def run():
    import aiomysql
    conn = await aiomysql.connect(
        host=env['DB_HOST'], port=int(env['DB_PORT']),
        user=env['DB_USER'], password=env['DB_PASSWORD'], db=env['DB_NAME']
    )
    async with conn.cursor(aiomysql.DictCursor) as cur:
        await cur.execute('SELECT message_id, sql_generated FROM chat_messages WHERE has_table=1 AND table_data_json IS NULL')
        rows = await cur.fetchall()
        print(f'Found {len(rows)} messages to backfill')
        for row in rows:
            msg_id = row['message_id']
            sql = row['sql_generated'].strip()
            if not sql or not sql.upper().startswith('SELECT'):
                print(f'  Skipping {msg_id}')
                continue
            try:
                await cur.execute(sql)
                results = await cur.fetchall()
                table_json = json.dumps(results, default=serialize)
                await cur.execute('UPDATE chat_messages SET table_data_json=%s WHERE message_id=%s', (table_json, msg_id))
                await conn.commit()
                print(f'  Backfilled message {msg_id} - {len(results)} rows')
            except Exception as e:
                print(f'  Failed message {msg_id}: {e}')
    conn.close()
    print('Done')

asyncio.run(run())
