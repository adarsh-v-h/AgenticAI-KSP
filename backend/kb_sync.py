"""
Sync KB_DOCUMENT_IDS in .env with the actual Zoho Catalyst Knowledge Base.

This script:
  1. Calls the Catalyst QuickML RAG API to list all documents in the KB.
  2. Extracts their document IDs.
  3. Updates KB_DOCUMENT_IDS in the project .env file.

Run after uploading consolidated documents to the Zoho Catalyst console.

USAGE:
  python kb_sync.py [--env-file ../.env] [--dry-run]
"""

import argparse
import os
import sys
import httpx
from pathlib import Path
from dotenv import load_dotenv


# CONTRACT
# takes:  key (str) — environment variable name, required (bool) — whether to exit on missing value
# returns: (str) — environment variable value
# raises:  SystemExit — when required=True and the variable is not set
def _get_env(key: str, required: bool = True) -> str:
    val = os.getenv(key, "")
    if required and not val:
        print(f"ERROR: {key} not set in .env", file=sys.stderr)
        sys.exit(1)
    return val


# CONTRACT
# takes:  env_path (Path) — path to .env file to write the new token to
# returns: (str) — the new access token
# raises:  SystemExit — when refresh token env vars are missing or response lacks access_token
def refresh_token(env_path: Path) -> str:
    """
    Refresh the Catalyst OAuth access token using the refresh token.
    Updates the .env file with the new token and returns it.
    """
    client_id = _get_env("CATALYST_CLIENT_ID")
    client_secret = _get_env("CATALYST_CLIENT_SECRET")
    refresh_tok = _get_env("CATALYST_REFRESH_TOKEN")

    print("Refreshing OAuth token...")
    resp = httpx.post(
        "https://accounts.zoho.in/oauth/v2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_tok,
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()

    new_token = data.get("access_token")
    if not new_token:
        print(f"ERROR: No access_token in response: {data}", file=sys.stderr)
        sys.exit(1)

    # Update .env
    _update_env_var(env_path, "CATALYST_API_TOKEN", new_token)
    os.environ["CATALYST_API_TOKEN"] = new_token
    print("Token refreshed and saved to .env")
    return new_token


# CONTRACT
# takes:  project_id (str) — Catalyst project ID, org_id (str) — Catalyst org ID, token (str) — OAuth access token
# returns: (list[dict]) — list of document metadata dicts with at least document_id
# raises:  nothing (returns empty list on failure)
def list_kb_documents(project_id: str, org_id: str, token: str) -> list[dict]:
    """
    List all documents in the QuickML RAG Knowledge Base.
    
    Tries the v1 RAG documents endpoint. If it fails (Early Access
    limitations), falls back to parsing document IDs from a test
    query's retrieved_nodes response.
    """
    headers = {
        "CATALYST-ORG": org_id,
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json",
    }

    # Attempt 1: Direct document listing endpoint
    list_url = f"https://api.catalyst.zoho.in/quickml/v1/project/{project_id}/rag/documents"
    try:
        resp = httpx.get(list_url, headers=headers, timeout=30.0)
        if resp.status_code == 200:
            data = resp.json()
            docs = data if isinstance(data, list) else data.get("documents", data.get("data", []))
            if docs:
                print(f"Listed {len(docs)} documents via /rag/documents endpoint")
                return docs
    except Exception as e:
        print(f"  /rag/documents endpoint not available: {e}", file=sys.stderr)

    # Attempt 2: Discovery via a broad query — the RAG answer endpoint
    # returns retrieved_nodes with document_id and document_title
    print("Falling back to document discovery via RAG query...")
    answer_url = f"https://api.catalyst.zoho.in/quickml/v1/project/{project_id}/rag/answer"
    discovery_queries = [
        "List all cases",
        "What are the case reports available?",
        "Show me all documents",
    ]

    all_docs: dict[str, dict] = {}
    for query in discovery_queries:
        try:
            resp = httpx.post(
                answer_url,
                headers=headers,
                json={"query": query},
                timeout=30.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                for node in data.get("retrieved_nodes", []):
                    doc_id = node.get("document_id")
                    if doc_id and doc_id not in all_docs:
                        all_docs[doc_id] = {
                            "document_id": doc_id,
                            "document_title": node.get("document_title", ""),
                        }
        except Exception as e:
            print(f"  Discovery query failed: {e}", file=sys.stderr)

    if all_docs:
        print(f"Discovered {len(all_docs)} documents via RAG queries")
        return list(all_docs.values())

    print("WARNING: Could not discover any documents. "
          "Make sure documents are uploaded in the Zoho Catalyst console.",
          file=sys.stderr)
    return []


# CONTRACT
# takes:  env_path (Path) — path to the .env file to update, key (str) — variable name, value (str) — new value
# returns: nothing
# raises:  OSError — when file cannot be read or written
def _update_env_var(env_path: Path, key: str, value: str) -> None:
    """Update or append a key=value pair in the .env file."""
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"{key}={value}\n")
    env_path.write_text("".join(new_lines), encoding="utf-8")


# CONTRACT
# takes:  nothing
# returns: nothing
# raises:  SystemExit — via argparse on invalid arguments or missing env vars
def main():
    parser = argparse.ArgumentParser(
        description="Sync KB_DOCUMENT_IDS in .env with Zoho Catalyst KB."
    )
    parser.add_argument(
        "--env-file", default=None,
        help="Path to .env file (default: project root .env)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print discovered IDs without updating .env",
    )
    parser.add_argument(
        "--refresh-token", action="store_true",
        help="Refresh the OAuth token before querying",
    )
    args = parser.parse_args()

    # Resolve .env path
    script_dir = Path(__file__).resolve().parent
    if args.env_file:
        env_path = Path(args.env_file).resolve()
    else:
        env_path = script_dir.parent / ".env"
        if not env_path.exists():
            env_path = script_dir / ".env"

    if not env_path.exists():
        print(f"ERROR: .env not found at {env_path}", file=sys.stderr)
        sys.exit(1)

    load_dotenv(dotenv_path=str(env_path))

    # Optionally refresh token first
    if args.refresh_token:
        refresh_token(env_path)

    project_id = _get_env("CATALYST_PROJECT_ID")
    org_id = _get_env("CATALYST_ORG_ID")
    token = _get_env("CATALYST_API_TOKEN")

    # Discover documents
    docs = list_kb_documents(project_id, org_id, token)

    if not docs:
        print("No documents found. Exiting without changes.")
        return

    # Extract IDs
    doc_ids = []
    for doc in docs:
        did = doc.get("document_id") or doc.get("id") or doc.get("documentId")
        if did:
            doc_ids.append(str(did))

    doc_ids = sorted(set(doc_ids))

    print(f"\nDiscovered {len(doc_ids)} document IDs:")
    for did in doc_ids:
        title = next(
            (d.get("document_title", "") for d in docs
             if str(d.get("document_id", d.get("id", ""))) == did),
            ""
        )
        print(f"  {did}  {title}")

    ids_string = ",".join(doc_ids)
    current_ids = os.getenv("KB_DOCUMENT_IDS", "")

    if ids_string == current_ids:
        print("\nKB_DOCUMENT_IDS is already up to date.")
        return

    if args.dry_run:
        print(f"\n[DRY RUN] Would set KB_DOCUMENT_IDS={ids_string}")
        return

    _update_env_var(env_path, "KB_DOCUMENT_IDS", ids_string)
    print(f"\nUpdated KB_DOCUMENT_IDS in {env_path}")
    print(f"  Old: {current_ids}")
    print(f"  New: {ids_string}")


if __name__ == "__main__":
    main()
