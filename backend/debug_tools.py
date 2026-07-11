"""
Unified debug utility for KSP Crime Intelligence backend.

Combines the functionality of the former standalone scripts:
  - check_table.py     → `tables` subcommand
  - debug_env.py       → `env` subcommand
  - dump_raw_response.py → `rag` subcommand
  - inspect_schema.py  → `schema` subcommand

Usage:
  python debug_tools.py env          # Check .env loading and key vars
  python debug_tools.py db           # Ping DB, measure latency
  python debug_tools.py schema       # Dump all DB columns with narrative flags
  python debug_tools.py tables       # Verify critical tables exist
  python debug_tools.py rag          # Fire a test RAG query and dump raw response
  python debug_tools.py all          # Run all checks sequentially
"""

import asyncio
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from dotenv import load_dotenv

_project_root = os.path.dirname(_here)
_dotenv_path = os.path.join(_project_root, ".env")
load_dotenv(dotenv_path=_dotenv_path)


def _sep(title: str):
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


# ═══════════════════════════════════════════════════════════════════════════════
# ENV — verify .env is loaded and key variables are set
# ═══════════════════════════════════════════════════════════════════════════════


def check_env():
    _sep("Environment Check")
    print(f"  .env path: {_dotenv_path}")
    print(f"  File exists: {os.path.exists(_dotenv_path)}")

    required = [
        "CATALYST_API_TOKEN", "CATALYST_ORG_ID", "CATALYST_PROJECT_ID",
        "QUICKML_LLM_URL", "MODEL_SQL", "MODEL_ANSWER",
        "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER",
        "NOSQL_BASE_URL", "APP_ENV", "APP_SECRET_KEY", "ALLOWED_ORIGINS",
    ]

    missing = []
    for var in required:
        val = os.getenv(var)
        if val:
            # Mask sensitive values
            if any(s in var.lower() for s in ("token", "secret", "password")):
                display = val[:8] + "..." if len(val) > 8 else "***"
            else:
                display = val
            print(f"  [OK]   {var} = {display}")
        else:
            missing.append(var)
            print(f"  [MISS] {var}")

    if missing:
        print(f"\n  ⚠ {len(missing)} variable(s) missing — server will crash on startup.")
    else:
        print(f"\n  ✓ All {len(required)} required variables are set.")


# ═══════════════════════════════════════════════════════════════════════════════
# DB PING — verify DB connectivity and measure latency
# ═══════════════════════════════════════════════════════════════════════════════


async def check_db():
    _sep("Database Connectivity Ping")
    import time
    from db.connection import create_pool, close_pool, execute_query

    host = os.getenv("DB_HOST", "?")
    port = os.getenv("DB_PORT", "?")
    db = os.getenv("DB_NAME", "?")
    print(f"  Target: {host}:{port}/{db}")

    try:
        t0 = time.perf_counter()
        await create_pool()
        pool_time = (time.perf_counter() - t0) * 1000

        # Ping 1: simple SELECT 1
        t1 = time.perf_counter()
        await execute_query("SELECT 1")
        ping1 = (time.perf_counter() - t1) * 1000

        # Ping 2: count a table
        t2 = time.perf_counter()
        rows = await execute_query("SELECT COUNT(*) AS n FROM CaseMaster")
        ping2 = (time.perf_counter() - t2) * 1000
        count = rows[0]["n"] if rows else "?"

        # Ping 3: a JOIN query (realistic workload)
        t3 = time.perf_counter()
        await execute_query("""
            SELECT cm.CaseMasterID, a.AccusedName
            FROM CaseMaster cm
            JOIN Accused a ON a.CaseMasterID = cm.CaseMasterID
            LIMIT 5
        """)
        ping3 = (time.perf_counter() - t3) * 1000

        print(f"  Pool connect:   {pool_time:.0f}ms")
        print(f"  SELECT 1:       {ping1:.0f}ms")
        print(f"  COUNT(*):       {ping2:.0f}ms ({count} rows in CaseMaster)")
        print(f"  JOIN query:     {ping3:.0f}ms")
        avg = (ping1 + ping2 + ping3) / 3
        print(f"  Avg latency:    {avg:.0f}ms")

        if avg < 50:
            print(f"\n  ✓ Excellent — DB is fast ({avg:.0f}ms avg)")
        elif avg < 150:
            print(f"\n  ✓ Good — acceptable latency ({avg:.0f}ms avg)")
        else:
            print(f"\n  ⚠ Slow — consider a closer region ({avg:.0f}ms avg)")

        await close_pool()
    except Exception as e:
        print(f"  ✗ Connection failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA — dump all columns from INFORMATION_SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════


async def check_schema():
    _sep("Database Schema Inspection")
    from db.connection import execute_query, create_pool, close_pool

    await create_pool()
    try:
        columns = await execute_query("""
            SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """)

        current_table = None
        table_count = 0
        for col in columns:
            table = col["TABLE_NAME"]
            if table != current_table:
                print(f"\n  === {table} ===")
                current_table = table
                table_count += 1

            data_type = col["DATA_TYPE"]
            max_len = col["CHARACTER_MAXIMUM_LENGTH"]
            is_text_like = (
                data_type.lower() in ("text", "mediumtext", "longtext")
                or (data_type.lower() == "varchar" and max_len and max_len > 200)
            )
            flag = "  <-- narrative field" if is_text_like else ""
            len_str = f"({max_len})" if max_len else ""
            print(f"    {col['COLUMN_NAME']:30s} {data_type}{len_str}{flag}")

        print(f"\n  ✓ {table_count} tables found, {len(columns)} columns total.")
    except Exception as e:
        print(f"  ✗ Schema inspection failed: {e}")
    finally:
        await close_pool()


# ═══════════════════════════════════════════════════════════════════════════════
# TABLES — verify critical tables exist
# ═══════════════════════════════════════════════════════════════════════════════


async def check_tables():
    _sep("Critical Table Verification")
    from db.connection import execute_query, create_pool, close_pool

    critical_tables = [
        "CaseMaster", "Accused", "Victim", "Employee", "Unit",
        "CrimeSubHead", "CaseStatusMaster", "ArrestSurrender",
        "chat_sessions", "chat_messages", "evidence_media",
        "offender_risk_scores", "audit_log", "chat_evidence_trail",
    ]

    await create_pool()
    try:
        for table in critical_tables:
            rows = await execute_query(
                "SELECT COUNT(*) AS c FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = %s",
                (table,)
            )
            exists = rows[0]["c"] > 0 if rows else False
            status = "✓ EXISTS" if exists else "✗ MISSING"
            # Also get row count if exists
            if exists:
                count_rows = await execute_query(f"SELECT COUNT(*) AS n FROM `{table}`")
                count = count_rows[0]["n"] if count_rows else 0
                print(f"  [{status}] {table:30s} ({count} rows)")
            else:
                print(f"  [{status}] {table}")
    except Exception as e:
        print(f"  ✗ Table check failed: {e}")
    finally:
        await close_pool()


# ═══════════════════════════════════════════════════════════════════════════════
# RAG — fire a test query and dump raw response
# ═══════════════════════════════════════════════════════════════════════════════


async def check_rag():
    _sep("RAG Test Query")
    import httpx

    project_id = os.getenv("CATALYST_PROJECT_ID")
    org_id = os.getenv("CATALYST_ORG_ID")
    access_token = os.getenv("CATALYST_API_TOKEN")

    if not all([project_id, org_id, access_token]):
        print("  ✗ Missing CATALYST_PROJECT_ID, CATALYST_ORG_ID, or CATALYST_API_TOKEN")
        return

    # Try using KB_DOCUMENT_IDS if available
    doc_ids = [d.strip() for d in os.getenv("KB_DOCUMENT_IDS", "").split(",") if d.strip()]

    rag_url = f"https://api.catalyst.zoho.in/quickml/v1/project/{project_id}/rag/answer"
    headers = {
        "CATALYST-ORG": org_id,
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }
    body = {"query": "What happened in the Kavitha Raj case?"}
    if doc_ids:
        body["documents"] = doc_ids
        print(f"  Using {len(doc_ids)} document IDs from KB_DOCUMENT_IDS")
    else:
        print("  No KB_DOCUMENT_IDS set — querying without document filter")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(rag_url, headers=headers, json=body)
            print(f"  Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  Response keys: {list(data.keys())}")
                print(f"  Retrieved nodes: {len(data.get('retrieved_nodes', []))}")
                print(f"\n  Raw response (first 500 chars):")
                print(f"  {json.dumps(data, indent=2)[:500]}")
            else:
                print(f"  ✗ Error: {resp.text[:300]}")
    except Exception as e:
        print(f"  ✗ RAG query failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════


async def run_all():
    check_env()
    await check_db()
    await check_schema()
    await check_tables()
    await check_rag()


def main():
    commands = {
        "env": lambda: asyncio.run(asyncio.coroutine(lambda: check_env())()) if False else check_env(),
        "db": lambda: asyncio.run(check_db()),
        "schema": lambda: asyncio.run(check_schema()),
        "tables": lambda: asyncio.run(check_tables()),
        "rag": lambda: asyncio.run(check_rag()),
        "all": lambda: asyncio.run(run_all()),
    }

    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd not in commands:
        print(f"Unknown command '{cmd}'. Valid: {', '.join(commands.keys())}")
        sys.exit(1)

    print(f"\n  Running debug check: [{cmd}]")

    if cmd == "env":
        check_env()
    elif cmd == "all":
        # env is sync, rest are async
        check_env()
        asyncio.run(check_db())
        asyncio.run(check_schema())
        asyncio.run(check_tables())
        asyncio.run(check_rag())
    else:
        commands[cmd]()

    print("\n  Done.")


if __name__ == "__main__":
    main()
