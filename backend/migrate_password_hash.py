"""
One-time migration: add Employee.password_hash and backfill every existing
officer with a bcrypt hash of their current password (KGID + "123").

Why this exists (see Cleanup And Imp/WorkInPrg.md — auth security finding):
auth/simple_auth.py::login() used to compare the typed password against the
plaintext string `badge_number + "123"` computed at request time. That means
every officer's password was a public, guessable formula derived from their
own badge number (which appears in the JWT and UI). This migration adds a
real password_hash column and backfills it with a bcrypt hash of that SAME
password value, so:
  - No officer's login credential or experience changes today.
  - The plaintext formula is no longer reconstructable from the DB alone.
  - login() (updated separately) now does a real bcrypt.checkpw() comparison.
Stronger/officer-chosen passwords are a separate future step — not in scope
here.

Usage:
  python backend/migrate_password_hash.py

Safe to re-run: skips the ALTER TABLE if the column already exists (scoped to
the current database via TABLE_SCHEMA = DATABASE(), per the schema-drift bug
documented in Docs.md §10.13), and only backfills rows where password_hash
IS NULL.
"""

import asyncio
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import bcrypt
from dotenv import load_dotenv

_project_root = os.path.dirname(_here)
load_dotenv(dotenv_path=os.path.join(_project_root, ".env"))


async def main():
    import aiomysql

    host = os.getenv("DB_HOST")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    db = os.getenv("DB_NAME")

    print(f"Connecting to {user}@{host}:{port}/{db}...")
    conn = await aiomysql.connect(
        host=host, port=port, user=user, password=password, db=db,
        connect_timeout=10,
    )

    async with conn.cursor() as cur:
        # 1. Add the column only if it doesn't already exist (guarded,
        #    scoped to the current database — see Docs.md §10.13 for why the
        #    TABLE_SCHEMA filter matters).
        await cur.execute(
            """SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE()
                 AND TABLE_NAME = 'Employee'
                 AND COLUMN_NAME = 'password_hash'"""
        )
        (exists,) = await cur.fetchone()
        if exists:
            print("[SKIP] Employee.password_hash already exists.")
        else:
            await cur.execute(
                "ALTER TABLE Employee ADD COLUMN password_hash VARCHAR(255)"
            )
            await conn.commit()
            print("[OK] Added Employee.password_hash column.")

        # 2. Backfill every officer that doesn't have a hash yet with a
        #    bcrypt hash of their current password (KGID + "123"). Existing
        #    login behavior is unchanged — this only stops the password from
        #    being derivable from the badge number by anyone reading the DB.
        await cur.execute(
            "SELECT EmployeeID, KGID FROM Employee WHERE password_hash IS NULL"
        )
        rows = await cur.fetchall()

        if not rows:
            print("[OK] No officers need backfilling.")
        else:
            print(f"Backfilling password_hash for {len(rows)} officer(s)...")
            for employee_id, kgid in rows:
                plaintext = f"{kgid}123"
                hashed = bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt())
                await cur.execute(
                    "UPDATE Employee SET password_hash = %s WHERE EmployeeID = %s",
                    (hashed.decode("utf-8"), employee_id),
                )
            await conn.commit()
            print(f"[OK] Backfilled {len(rows)} officer(s).")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
