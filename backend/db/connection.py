import asyncio
import aiomysql
from config.settings import get

_pool = None

async def create_pool() -> aiomysql.Pool:
    """
    Create the global connection pool.
    Called once during FastAPI startup in main.py lifespan.
    Stores pool in module-level _pool variable.
    Pool settings: minsize=3, maxsize=10, autocommit=True.
    connect_timeout=5 seconds.
    """
    global _pool
    
    host = get("DB_HOST")
    port = int(get("DB_PORT"))
    user = get("DB_USER")
    password = get("DB_PASSWORD")
    db = get("DB_NAME")
    
    _pool = await aiomysql.create_pool(
        host=host,
        port=port,
        user=user,
        password=password,
        db=db,
        minsize=3,
        maxsize=10,
        autocommit=True,
        connect_timeout=5
    )
    return _pool

async def get_pool() -> aiomysql.Pool:
    """
    Return the existing pool.
    Raises RuntimeError if pool has not been created yet.
    """
    if _pool is None:
        raise RuntimeError("Database connection pool has not been created yet.")
    return _pool

def _normalize_bit_fields(row: dict) -> dict:
    return {
        k: (v == b'\x01' if isinstance(v, bytes) and len(v) == 1 else v)
        for k, v in row.items()
    }

async def execute_query(sql: str, params: tuple = ()) -> list[dict]:
    """
    Execute a SELECT-only query using the global pool.
    - Gets a connection from pool
    - Executes query with params (use parameterized queries always)
    - Returns list of dicts (column_name → value)
    - Enforces 5-second query execution timeout
    - Raises ValueError if sql does not start with SELECT (case-insensitive after strip)
    - Releases connection back to pool in finally block always
    """
    if _pool is None:
        raise RuntimeError("Database connection pool has not been created yet.")
        
    # Check if SQL starts with SELECT
    stripped_sql = sql.strip()
    if not stripped_sql.upper().startswith("SELECT"):
        raise ValueError("Security violation: Only SELECT queries are allowed.")
        
    async def _run():
        async with _pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                if params:
                    await cur.execute(stripped_sql, params)
                else:
                    await cur.execute(stripped_sql)
                rows = await cur.fetchall()
                return [_normalize_bit_fields(row) for row in rows]
                
    try:
        return await asyncio.wait_for(_run(), timeout=5.0)
    except asyncio.TimeoutError:
        raise TimeoutError("Database query execution timed out (5s limit reached).")

async def execute_write(sql: str, params: tuple = ()) -> int:
    """
    Execute an INSERT or UPDATE statement.
    Returns lastrowid for INSERT, rowcount for UPDATE.
    Never accepts SELECT — raises ValueError if sql starts with SELECT.
    Uses same pool as execute_query.
    5-second timeout enforced.
    Releases connection in finally block always.
    """
    if _pool is None:
        raise RuntimeError("Database connection pool has not been created yet.")

    stripped = sql.strip()
    if stripped.upper().startswith("SELECT"):
        raise ValueError("Use execute_query() for SELECT statements.")

    async def _run():
        async with _pool.acquire() as conn:
            async with conn.cursor() as cur:
                if params:
                    await cur.execute(stripped, params)
                else:
                    await cur.execute(stripped)
                await conn.commit()
                return cur.lastrowid if stripped.upper().startswith("INSERT") else cur.rowcount

    try:
        return await asyncio.wait_for(_run(), timeout=5.0)
    except asyncio.TimeoutError:
        raise TimeoutError("Database write timed out (5s limit).")

async def close_pool():
    """
    Close the pool. Called during FastAPI shutdown in main.py lifespan.
    """
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
