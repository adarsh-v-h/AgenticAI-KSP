import asyncio
from db.connection import execute_query, create_pool, close_pool
import os

OUTPUT_DIR = "rag_export"


async def main():
    await create_pool()
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(script_dir, OUTPUT_DIR)
        os.makedirs(output_path, exist_ok=True)

        cases = await execute_query("""
            SELECT
                cm.CaseMasterID,
                cm.CrimeNo,
                cm.IncidentFromDate,
                cm.BriefFacts,
                csm.CaseStatusName,
                u.UnitName AS StationName,
                GROUP_CONCAT(DISTINCT a.AccusedName SEPARATOR ', ') AS AccusedNames,
                GROUP_CONCAT(DISTINCT v.VictimName SEPARATOR ', ') AS VictimNames,
                GROUP_CONCAT(DISTINCT s.SectionDescription SEPARATOR '; ') AS Sections
            FROM CaseMaster cm
            LEFT JOIN CaseStatusMaster csm ON cm.CaseStatusID = csm.CaseStatusID
            LEFT JOIN Unit u ON cm.PoliceStationID = u.UnitID
            LEFT JOIN Accused a ON a.CaseMasterID = cm.CaseMasterID
            LEFT JOIN Victim v ON v.CaseMasterID = cm.CaseMasterID
            LEFT JOIN ActSectionAssociation asa ON asa.CaseMasterID = cm.CaseMasterID
            LEFT JOIN Section s ON s.SectionCode = asa.SectionID AND s.ActCode = asa.ActID
            WHERE cm.BriefFacts IS NOT NULL AND cm.BriefFacts != ''
            GROUP BY cm.CaseMasterID
        """)

        print(f"Found {len(cases)} cases with narrative text. Writing files...\n")

        for case in cases:
            filename = f"case_{case['CrimeNo'].replace('/', '_')}.txt"
            filepath = os.path.join(output_path, filename)

            content = f"""CASE REPORT
Station: {case['StationName'] or 'Unknown'}
Crime No: {case['CrimeNo']}
Date of Incident: {case['IncidentFromDate']}
Status: {case['CaseStatusName'] or 'Unknown'}

ACCUSED: {case['AccusedNames'] or 'Not on record'}
VICTIM: {case['VictimNames'] or 'Not on record'}
SECTIONS: {case['Sections'] or 'Not on record'}

BRIEF FACTS:
{case['BriefFacts']}
"""
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

        print(f"Done. {len(cases)} files written to .\\{OUTPUT_DIR}\\")

        # Automatically trigger the consolidation step
        print("\nTriggering automated RAG consolidation...")
        from pathlib import Path
        from consolidate_cases import consolidate
        script_dir = Path(__file__).resolve().parent
        input_dir = script_dir / OUTPUT_DIR
        output_dir = script_dir / "rag_consolidated"
        consolidate(input_dir, output_dir, max_size_kb=100)

    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())

