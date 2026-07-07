import asyncio
from db.connection import execute_write, create_pool, close_pool


async def main():
    await create_pool()
    try:
        await execute_write("""
            CREATE TABLE IF NOT EXISTS offender_risk_scores (
                AccusedMasterID      INT PRIMARY KEY,
                risk_score           DECIMAL(5,2) NOT NULL,
                risk_tier            ENUM('low', 'medium', 'high', 'critical') NOT NULL,
                contributing_factors TEXT,
                computed_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (AccusedMasterID) REFERENCES Accused(AccusedMasterID)
            )
        """)
        print("Table created (or already existed).")
    finally:
        await close_pool()


asyncio.run(main())
