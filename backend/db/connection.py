import asyncio
import aiomysql
from config.settings import get

_pool = None

# CONTRACT
# takes:  nothing
# returns: (aiomysql.Pool) — newly created MySQL connection pool
# raises:  ValueError — when required DB env vars are not set,
#           aiomysql.Error — when database connection fails
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
    
    import os
    max_size = int(os.getenv("DB_POOL_MAXSIZE", "10"))
    min_size = int(os.getenv("DB_POOL_MINSIZE", "5"))

    _pool = await aiomysql.create_pool(
        host=host,
        port=port,
        user=user,
        password=password,
        db=db,
        minsize=min_size,
        maxsize=max_size,
        autocommit=True,
        connect_timeout=5
    )
    return _pool

# CONTRACT
# takes:  nothing
# returns: (aiomysql.Pool) — the existing global connection pool
# raises:  RuntimeError — when pool has not been created yet
async def get_pool() -> aiomysql.Pool:
    """
    Return the existing pool.
    Raises RuntimeError if pool has not been created yet.
    """
    if _pool is None:
        raise RuntimeError("Database connection pool has not been created yet.")
    return _pool

# CONTRACT
# takes:  row (dict) — a single database row with potential BIT field bytes
# returns: (dict) — the row with single-byte BIT fields converted to booleans
# raises:  nothing
def _normalize_bit_fields(row: dict) -> dict:
    return {
        k: (v == b'\x01' if isinstance(v, bytes) and len(v) == 1 else v)
        for k, v in row.items()
    }

# CONTRACT
# takes:  sql (str) — SELECT query to execute,
#          params (tuple) — parameterized query values
# returns: (list[dict]) — list of row dicts (column_name → value)
# raises:  RuntimeError — when pool has not been created,
#           ValueError — when sql is not a SELECT statement,
#           TimeoutError — when query exceeds 5-second timeout
import re

_READ_ONLY_PREFIXES = ("SELECT", "WITH")
_FORBIDDEN_STATEMENTS = (
    r"\bINSERT\s+INTO\b",
    r"\bUPDATE\s+`?[A-Za-z0-9_]+`?\s+SET\b",
    r"\bDELETE\s+FROM\b",
    r"\bDROP\s+(?:TABLE|DATABASE|INDEX|VIEW)\b",
    r"\bALTER\s+(?:TABLE|DATABASE)\b",
    r"\bTRUNCATE\s+(?:TABLE)?\b",
    r"\bCREATE\s+(?:TABLE|DATABASE|INDEX|VIEW)\b",
    r"\bREPLACE\s+INTO\b",
)

def _validate_read_only_sql(sql: str) -> str:
    stripped = sql.strip()
    upper_sql = stripped.upper()
    if not upper_sql.startswith(_READ_ONLY_PREFIXES):
        raise ValueError("Security violation: Only SELECT and WITH (read-only) queries are allowed.")
    for pattern in _FORBIDDEN_STATEMENTS:
        if re.search(pattern, upper_sql):
            raise ValueError("Security violation: Data modification statements are forbidden in execute_query.")
    return stripped

async def execute_query(sql: str, params: tuple = ()) -> list[dict]:
    """
    Execute a SELECT-only or WITH (read-only) query using the global pool.
    - Gets a connection from pool
    - Executes query with params (use parameterized queries always)
    - Returns list of dicts (column_name → value)
    - Enforces 5-second query execution timeout
    - Raises ValueError if sql does not start with SELECT or WITH
    - Releases connection back to pool in finally block always
    """
    # 1. Try to serve from local in-memory lookup cache first
    try:
        from db.lookup_cache import intercept_lookup_query
        cached_result = intercept_lookup_query(sql, params)
        if cached_result is not None:
            return cached_result
    except Exception as e:
        import sys
        print(f"WARNING: Lookup cache interception failed: {e}", file=sys.stderr)

    if _pool is None:
        raise RuntimeError("Database connection pool has not been created yet.")
        
    stripped_sql = _validate_read_only_sql(sql)

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

# CONTRACT
# takes:  sql (str) — INSERT or UPDATE statement to execute,
#          params (tuple) — parameterized query values
# returns: (int) — lastrowid for INSERT, rowcount for UPDATE
# raises:  RuntimeError — when pool has not been created,
#           ValueError — when sql is a SELECT statement,
#           TimeoutError — when write exceeds 5-second timeout
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

# CONTRACT
# takes:  nothing
# returns: nothing
# raises:  nothing
async def close_pool():
    """
    Close the pool. Called during FastAPI shutdown in main.py lifespan.
    """
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
