import httpx
from config.settings import get

class NoSQLError(Exception):
    """Raised when an operation on Catalyst NoSQL fails."""
    pass

# CONTRACT
# takes:  nothing
# returns: (str) — base project URL with /nosql suffix stripped if present
# raises:  ValueError — when NOSQL_BASE_URL env var is not set
def _get_base_project_url() -> str:
    nosql_base = get("NOSQL_BASE_URL").rstrip("/")
    if nosql_base.endswith("/nosql"):
        return nosql_base[:-6]
    return nosql_base

# CONTRACT
# takes:  nothing
# returns: (dict) — authorization and content-type headers for Catalyst NoSQL API calls
# raises:  ValueError — when required env vars are not set
def _nosql_headers() -> dict:
    return {
        "Authorization": f"Zoho-oauthtoken {get('CATALYST_API_TOKEN')}",
        "Content-Type": "application/json",
        "CATALYST-ORG": get("CATALYST_ORG_ID"),
    }

# CONTRACT
# takes:  val (any) — Python value to serialize into Catalyst NoSQL typed format
# returns: (dict) — Catalyst-typed wrapper (e.g. {"S": ...}, {"N": ...}, {"BOOL": ...})
# raises:  nothing
def serialize_to_catalyst(val):
    if isinstance(val, bool):
        return {"BOOL": val}
    elif isinstance(val, (int, float)):
        return {"N": str(val)}
    elif isinstance(val, str):
        return {"S": val}
    elif isinstance(val, list):
        return {"L": [serialize_to_catalyst(x) for x in val]}
    elif isinstance(val, dict):
        return {"M": {k: serialize_to_catalyst(v) for k, v in val.items()}}
    elif val is None:
        return {"NULL": True}
    else:
        return {"S": str(val)}

# CONTRACT
# takes:  c_val (dict) — Catalyst-typed value wrapper to deserialize
# returns: (any) — native Python value extracted from the typed wrapper
# raises:  nothing
def deserialize_from_catalyst(c_val):
    if not isinstance(c_val, dict) or len(c_val) != 1:
        return c_val
    t, v = list(c_val.items())[0]
    if t == "S":
        return v
    elif t == "N":
        if "." in v:
            return float(v)
        return int(v)
    elif t == "BOOL":
        return bool(v)
    elif t == "NULL":
        return None
    elif t == "L":
        return [deserialize_from_catalyst(x) for x in v]
    elif t == "M":
        return {k: deserialize_from_catalyst(val) for k, val in v.items()}
    return c_val

# CONTRACT
# takes:  item_data (dict) — raw Catalyst NoSQL item with typed attribute values
# returns: (dict) — deserialized item with native Python values
# raises:  nothing
def deserialize_item(item_data: dict) -> dict:
    if not item_data:
        return {}
    return {k: deserialize_from_catalyst(v) for k, v in item_data.items()}

# CONTRACT
# takes:  table_name (str) — NoSQL table to fetch from,
#          document_id (str) — primary key value of the document,
#          timeout (float) — HTTP request timeout in seconds,
#          key_name (str) — name of the primary key attribute
# returns: (dict | None) — deserialized document, or None if not found
# raises:  NoSQLError — when the API returns a non-success/non-404 status
async def get_document(table_name: str, document_id: str, timeout: float = 5.0, key_name: str = "id") -> dict | None:
    """
    Fetch a single item from the NoSQL table.
    """
    url = f"{_get_base_project_url()}/nosqltable/{table_name}/item/fetch"
    payload = {
        "keys": [{key_name: {"S": document_id}}]
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers=_nosql_headers(),
            json=payload,
            timeout=timeout
        )
        if response.status_code == 200:
            res_json = response.json()
            data = res_json.get("data")
            if isinstance(data, dict) and isinstance(data.get("get"), list) and len(data["get"]) > 0:
                item_data = data["get"][0].get("item")
                if item_data:
                    return deserialize_item(item_data)
            elif isinstance(data, list) and len(data) > 0:
                item_data = data[0].get("item")
                if item_data:
                    return deserialize_item(item_data)
            elif isinstance(data, dict) and "item" in data:
                item_data = data.get("item")
                if item_data:
                    return deserialize_item(item_data)
            return None
        elif response.status_code == 404:
            return None
        else:
            raise NoSQLError(f"Fetch item {document_id} failed with status {response.status_code}: {response.text}")

# CONTRACT
# takes:  table_name (str) — NoSQL table to insert into,
#          document_id (str) — primary key value for the new document,
#          document_data (dict) — key-value pairs to store in the document,
#          timeout (float) — HTTP request timeout in seconds,
#          key_name (str) — name of the primary key attribute
# returns: (bool) — True on successful insert
# raises:  NoSQLError — when the API returns a non-success status
async def insert_document(table_name: str, document_id: str, document_data: dict, timeout: float = 5.0, key_name: str = "id") -> bool:
    """
    Insert a document into NoSQL.
    """
    url = f"{_get_base_project_url()}/nosqltable/{table_name}/item"
    doc_copy = dict(document_data)
    doc_copy[key_name] = document_id
    serialized = {k: serialize_to_catalyst(v) for k, v in doc_copy.items()}
    payload = [{"item": serialized}]
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers=_nosql_headers(),
            json=payload,
            timeout=timeout
        )
        if response.status_code in (200, 201, 204):
            return True
        raise NoSQLError(f"Insert item {document_id} failed with status {response.status_code}: {response.text}")

# CONTRACT
# takes:  table_name (str) — NoSQL table containing the document,
#          document_id (str) — primary key value of the document to update,
#          updates (dict) — key-value pairs to update on the document,
#          timeout (float) — HTTP request timeout in seconds,
#          key_name (str) — name of the primary key attribute
# returns: (bool) — True on successful update
# raises:  NoSQLError — when the API returns a non-success status
async def update_document(table_name: str, document_id: str, updates: dict, timeout: float = 5.0, key_name: str = "id") -> bool:
    """
    Update attributes of a document in NoSQL.
    """
    url = f"{_get_base_project_url()}/nosqltable/{table_name}/item"
    update_attrs = []
    for k, v in updates.items():
        if k == key_name:
            continue
        update_attrs.append({
            "operation_type": "PUT",
            "attribute_path": [k],
            "update_value": serialize_to_catalyst(v)
        })
    payload = [{
        "keys": {key_name: {"S": document_id}},
        "update_attributes": update_attrs
    }]
    async with httpx.AsyncClient() as client:
        response = await client.put(
            url,
            headers=_nosql_headers(),
            json=payload,
            timeout=timeout
        )
        if response.status_code in (200, 201, 204):
            return True
        raise NoSQLError(f"Update item {document_id} failed with status {response.status_code}: {response.text}")

# CONTRACT
# takes:  table_name (str) — NoSQL table containing the document,
#          document_id (str) — primary key value of the document to delete,
#          timeout (float) — HTTP request timeout in seconds,
#          key_name (str) — name of the primary key attribute
# returns: (bool) — True on successful deletion
# raises:  NoSQLError — when the API returns a non-success status
async def delete_document(table_name: str, document_id: str, timeout: float = 5.0, key_name: str = "id") -> bool:
    """
    Delete a document in NoSQL.
    """
    url = f"{_get_base_project_url()}/nosqltable/{table_name}/item"
    payload = [{
        "keys": {key_name: {"S": document_id}}
    }]
    async with httpx.AsyncClient() as client:
        response = await client.request(
            "DELETE",
            url,
            headers=_nosql_headers(),
            json=payload,
            timeout=timeout
        )
        if response.status_code in (200, 201, 204):
            return True
        raise NoSQLError(f"Delete item {document_id} failed with status {response.status_code}: {response.text}")

# CONTRACT
# takes:  table_name (str) — NoSQL table to list documents from,
#          timeout (float) — HTTP request timeout in seconds
# returns: (list[dict]) — list of deserialized documents from the table
# raises:  NoSQLError — when the API returns a non-success/non-404 status
async def list_documents(table_name: str, timeout: float = 5.0) -> list[dict]:
    """
    List all documents in a table using GET /item.
    """
    url = f"{_get_base_project_url()}/nosqltable/{table_name}/item"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers=_nosql_headers(),
            timeout=timeout
        )
        if response.status_code == 200:
            payload = response.json()
            raw = payload.get("data")
            if isinstance(raw, list):
                return [deserialize_item(item.get("item", item)) for item in raw]
            elif isinstance(raw, dict):
                item_data = raw.get("item")
                return [deserialize_item(item_data)] if item_data else []
            return []
        elif response.status_code == 404:
            return []
        else:
            raise NoSQLError(f"List items for {table_name} failed with status {response.status_code}: {response.text}")
