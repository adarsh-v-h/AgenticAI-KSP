import sys
import httpx
from config.settings import get


class LLMError(Exception):
    """Raised when an LLM call fails or returns an unexpected response."""
    pass


def _llm_headers() -> dict:
    """Build the auth + org headers required by every Catalyst QuickML call."""
    return {
        "Authorization": f"Bearer {get('CATALYST_API_TOKEN')}",
        "Content-Type": "application/json",
        "CATALYST-ORG": get("CATALYST_ORG_ID"),
    }


async def ping_model(model_key: str) -> bool:
    """
    Send a minimal test message to the given model.
    Returns True on a non-empty 200 response, False on any other outcome.
    Never raises — health checks must report status, not crash.
    """
    try:
        model_name = get(model_key)
        url = get("QUICKML_LLM_URL")

        payload = {
            "model": model_name,
            "prompt": "Say OK.",
            "system_prompt": "You are a helpful assistant.",
            "max_tokens": 1000,
            "temperature": 1,
            "top_p": 0.95,
            "top_k": 120,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, json=payload, headers=_llm_headers(), timeout=120.0
            )
            data = response.json()
            if response.status_code == 200 and data.get("response"):
                return True
            print(
                f"WARNING: LLM ping got unexpected response: {data}",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"WARNING: LLM ping failed for {model_key}: {e}", file=sys.stderr)

    return False


async def call_llm(
    model_key: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int = 4000,
) -> str:
    """
    Call a Catalyst QuickML LLM model.

    Args:
        model_key: env var name — "MODEL_SQL" or "MODEL_ANSWER"
        prompt: the user/task prompt
        system_prompt: the system instruction
        max_tokens: max output tokens (default 2000)

    Returns:
        The model's response text as a string.

    Raises:
        LLMError: on any failure (network, bad status, missing/empty response).
        Never returns an empty string.
    """
    try:
        model_name = get(model_key)
        url = get("QUICKML_LLM_URL")
    except ValueError as e:
        raise LLMError(f"LLM config missing: {e}") from e

    payload = {
        "model": model_name,
        "prompt": prompt,
        "system_prompt": system_prompt,
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "top_p": 0.95,
        "top_k": 40,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, json=payload, headers=_llm_headers(), timeout=180.0
            )
    except httpx.TimeoutException as e:
        raise LLMError(f"LLM call timed out after 180s: {e}") from e
    except httpx.HTTPError as e:
        raise LLMError(f"LLM HTTP transport error: {e}") from e

    if response.status_code != 200:
        # Truncate body to avoid logging huge HTML error pages
        body_preview = response.text[:500] if response.text else "<empty>"
        raise LLMError(
            f"LLM returned HTTP {response.status_code}: {body_preview}"
        )

    try:
        data = response.json()
    except ValueError as e:
        raise LLMError(f"LLM response was not valid JSON: {e}") from e

    text = data.get("response")
    if not text or not isinstance(text, str) or not text.strip():
        raise LLMError(f"LLM returned empty or missing 'response' field: {data}")

    return text.strip()
