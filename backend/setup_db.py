"""
Create all tables on the configured database (local or Catalyst Data Store).

Reads DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD from .env and executes
backend/db/schema.sql statement-by-statement.

Usage:
  python backend/setup_db.py              # Create all tables
  python backend/setup_db.py --seed       # Create tables + seed data
  python backend/setup_db.py --migrate    # Run migrations (add missing columns)

This works on both local MySQL AND Catalyst Data Store — just point your .env
at the right host/credentials.
"""

import asyncio
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from dotenv import load_dotenv

_project_root = os.path.dirname(_here)
load_dotenv(dotenv_path=os.path.join(_project_root, ".env"))


async def create_tables():
    """Read schema.sql and execute each CREATE statement."""
    import aiomysql

    host = os.getenv("DB_HOST")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    db = os.getenv("DB_NAME")

    print(f"Connecting to {user}@{host}:{port}/{db}...")

    conn = await aiomysql.connect(
        host=host, port=port, user=user, password=password, db=db,
        connect_timeout=10
    )

    schema_path = os.path.join(_here, "db", "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    # Split on semicolons but skip empty statements and comments-only blocks
    statements = [s.strip() for s in schema_sql.split(";") if s.strip()]

    created = 0
    skipped = 0
    errors = 0

    async with conn.cursor() as cur:
        for stmt in statements:
            # Skip pure comment blocks
            lines = [l for l in stmt.split("\n") if l.strip() and not l.strip().startswith("--")]
            if not lines:
                continue

            try:
                await cur.execute(stmt)
                await conn.commit()
                # Extract table/index name for reporting
                upper = stmt.upper().strip()
                if "CREATE TABLE" in upper:
                    # Extract table name
                    parts = stmt.split("(")[0]
                    name = parts.split()[-1].strip("`")
                    print(f"  [CREATED] {name}")
                    created += 1
                elif "CREATE INDEX" in upper:
                    print(f"  [INDEX]   {stmt[:60]}...")
                    created += 1
                else:
                    created += 1
            except Exception as e:
                err_str = str(e)
                if "already exists" in err_str.lower() or "1050" in err_str:
                    # Table already exists
                    parts = stmt.split("(")[0] if "(" in stmt else stmt
                    name = parts.split()[-1].strip("`") if parts.split() else "?"
                    print(f"  [EXISTS]  {name}")
                    skipped += 1
                elif "Duplicate" in err_str or "1061" in err_str:
                    # Index already exists
                    skipped += 1
                else:
                    print(f"  [ERROR]   {err_str[:100]}")
                    print(f"            Statement: {stmt[:80]}...")
                    errors += 1

    conn.close()
    print(f"\nDone: {created} created, {skipped} already existed, {errors} errors.")
    return errors == 0


async def run_seed():
    """Import and run the seeder."""
    from db.seed import main as seed_main
    await seed_main()


async def run_migrate():
    """Run the migration script."""
    # Import and run migrate.py logic
    migrate_path = os.path.join(_project_root, "migrate.py")
    if os.path.exists(migrate_path):
        import importlib.util
        spec = importlib.util.spec_from_file_location("migrate", migrate_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    else:
        print("migrate.py not found at project root")


def main():
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    do_seed = "--seed" in args
    do_migrate = "--migrate" in args

    async def run():
        success = await create_tables()
        if not success:
            print("\nSome tables failed to create. Fix errors above before seeding.")
            return

        if do_migrate:
            print("\n--- Running migrations ---")
            await run_migrate()

        if do_seed:
            print("\n--- Running seeder ---")
            await run_seed()

    asyncio.run(run())


if __name__ == "__main__":
    main()
