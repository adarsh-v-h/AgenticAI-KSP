import sys
import json
import httpx
from config.settings import get

class NoSQLError(Exception):
    """Raised when an operation on Catalyst NoSQL fails."""
    pass

def _get_base_project_url() -> str:
    nosql_base = get("NOSQL_BASE_URL").rstrip("/")
    if nosql_base.endswith("/nosql"):
        return nosql_base[:-6]
    return nosql_base

def _nosql_headers() -> dict:
    return {
        "Authorization": f"Zoho-oauthtoken {get('CATALYST_API_TOKEN')}",
        "Content-Type": "application/json",
        "CATALYST-ORG": get("CATALYST_ORG_ID"),
    }

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

def deserialize_item(item_data: dict) -> dict:
    if not item_data:
        return {}
    res = {}
    for k, v in item_data.items():
        res[k] = deserialize_from_catalyst(v)
    return res

async def get_document(table_name: str, document_id: str, timeout: float = 5.0) -> dict | None:
    """
    Fetch a single item from the NoSQL table.
    """
    url = f"{_get_base_project_url()}/nosqltable/{table_name}/item/fetch"
    payload = {
        "keys": [{"id": {"S": document_id}}],
        "required_attributes": []
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
            if isinstance(data, list) and len(data) > 0:
                item_data = data[0].get("item")
                if item_data:
                    return deserialize_item(item_data)
            elif isinstance(data, dict):
                item_data = data.get("item")
                if item_data:
                    return deserialize_item(item_data)
            return None
        elif response.status_code == 404:
            return None
        else:
            raise NoSQLError(f"Fetch item {document_id} failed with status {response.status_code}: {response.text}")

async def insert_document(table_name: str, document_id: str, document_data: dict, timeout: float = 5.0) -> bool:
    """
    Insert a document into NoSQL.
    """
    url = f"{_get_base_project_url()}/nosqltable/{table_name}/item"
    doc_copy = dict(document_data)
    doc_copy["id"] = document_id
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

async def update_document(table_name: str, document_id: str, updates: dict, timeout: float = 5.0) -> bool:
    """
    Update attributes of a document in NoSQL.
    """
    url = f"{_get_base_project_url()}/nosqltable/{table_name}/item"
    update_attrs = []
    for k, v in updates.items():
        if k == "id":
            continue
        update_attrs.append({
            "operation_type": "PUT",
            "attribute_path": [k],
            "update_value": serialize_to_catalyst(v)
        })
    payload = [{
        "keys": {"id": {"S": document_id}},
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

async def delete_document(table_name: str, document_id: str, timeout: float = 5.0) -> bool:
    """
    Delete a document in NoSQL.
    """
    url = f"{_get_base_project_url()}/nosqltable/{table_name}/item"
    payload = [{
        "keys": {"id": {"S": document_id}}
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
