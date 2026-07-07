import asyncio
import json
import os
import httpx
from dotenv import load_dotenv

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(_project_root, ".env"))

CATALYST_ORG = os.getenv("CATALYST_ORG_ID", "60073906151")
CATALYST_PROJECT_ID = os.getenv("CATALYST_PROJECT_ID")
RAG_URL = f"https://api.catalyst.zoho.in/quickml/v1/project/{CATALYST_PROJECT_ID}/rag/answer"

DOC_IDS = [
    "700000000003199", "700000000004191", "700000000004186",
    "700000000003217", "700000000003214", "700000000004179",
    "700000000003208", "700000000003207", "700000000003200",
]

async def main():
    access_token = os.getenv("CATALYST_API_TOKEN")
    headers = {
        "CATALYST-ORG": CATALYST_ORG,
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }
    body = {"query": "What happened in the Kavitha Raj case?", "documents": DOC_IDS}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(RAG_URL, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

    print(json.dumps(data, indent=2))

asyncio.run(main())
