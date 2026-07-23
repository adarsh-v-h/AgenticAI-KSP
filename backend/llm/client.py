import sys
import httpx
from config.settings import get
from config.catalyst_token import get_access_token
from http_client import get_http_client


class LLMError(Exception):
    """Raised when an LLM call fails or returns an unexpected response."""
    pass


# CONTRACT
# takes:  nothing
# returns: (dict) — authorization and content-type headers for Catalyst QuickML API calls
# raises:  ValueError — when CATALYST_ORG_ID is not set,
#           RuntimeError — when no Catalyst access token can be obtained
async def _llm_headers() -> dict:
    """Build the auth + org headers required by every Catalyst QuickML call."""
    return {
        "Authorization": f"Zoho-oauthtoken {await get_access_token()}",
        "Content-Type": "application/json",
        "CATALYST-ORG": get("CATALYST_ORG_ID"),
    }


# CONTRACT
# takes:  data (dict) — raw JSON response body from a GLM chat completion endpoint
# returns: (str) — extracted assistant response text, or empty string if not found
# raises:  nothing
def _extract_response_text(data: dict) -> str:
    """
    Extract the assistant's text from a GLM chat completion response.

    Handles two response shapes:
    1. Direct format: {"response": "..."}
    2. OpenAI-compatible format: {"choices": [{"message": {"content": "..."}}]}
    """
    # Shape 1: direct "response" field (observed in production)
    if "response" in data and isinstance(data["response"], str):
        return data["response"].strip()

    # Shape 2: OpenAI choices format (per Zoho docs sample)
    choices = data.get("choices")
    if choices and isinstance(choices, list):
        message = choices[0].get("message", {})
        content = message.get("content", "")
        return content.strip() if content else ""

    return ""


# CONTRACT
# takes:  model_key (str) — environment variable name that resolves to the model identifier
# returns: (bool) — True if model responded with non-empty 200, False otherwise
# raises:  nothing (catches all exceptions internally)
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
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say OK."},
            ],
            "max_tokens": 32,
            "temperature": 0,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }

        client = get_http_client()
        response = await client.post(
            url, json=payload, headers=await _llm_headers(), timeout=30.0
        )
        data = response.json()
        if response.status_code == 200 and _extract_response_text(data):
            return True
        print(
            f"WARNING: LLM ping got unexpected response: {data}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"WARNING: LLM ping failed for {model_key}: {e}", file=sys.stderr)

    return False


# CONTRACT
# takes:  model_key (str) — env var name resolving to the model identifier (e.g. "MODEL_SQL"),
#          prompt (str) — user/task prompt to send to the model,
#          system_prompt (str) — system instruction for the model,
#          max_tokens (int) — maximum tokens to generate in the response
# returns: (str) — the model's non-empty response text
# raises:  LLMError — on network failure, bad HTTP status, invalid JSON, or empty response
async def call_llm(
    model_key: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int = 4000,
) -> str:
    """
    Call the GLM model via Catalyst QuickML.

    Args:
        model_key: env var name — "MODEL_SQL" or "MODEL_ANSWER"
        prompt: the user/task prompt
        system_prompt: the system instruction
        max_tokens: maximum tokens to generate in the response.

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
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    import random
    max_retries = 3
    base_delay = 1.0
    response = None

    for attempt in range(max_retries + 1):
        try:
            client = get_http_client()
            response = await client.post(
                url, json=payload, headers=await _llm_headers(), timeout=180.0
            )
            # If rate limited (429) or transient gateway/server error (5xx or 408), retry with backoff
            if response.status_code in (429, 408) or response.status_code >= 500:
                if attempt < max_retries:
                    sleep_time = base_delay * (2 ** attempt) + random.uniform(0.1, 0.5)
                    print(
                        f"WARNING: LLM call got HTTP {response.status_code}, retrying in {sleep_time:.2f}s (attempt {attempt + 1}/{max_retries})...",
                        file=sys.stderr,
                        flush=True
                    )
                    await asyncio.sleep(sleep_time)
                    continue

            if response.status_code != 200:
                body_preview = response.text[:500] if response.text else "<empty>"
                raise LLMError(
                    f"LLM returned HTTP {response.status_code}: {body_preview}"
                )
            break
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            if attempt < max_retries:
                sleep_time = base_delay * (2 ** attempt) + random.uniform(0.1, 0.5)
                print(
                    f"WARNING: LLM call got error: {e}, retrying in {sleep_time:.2f}s (attempt {attempt + 1}/{max_retries})...",
                    file=sys.stderr,
                    flush=True
                )
                await asyncio.sleep(sleep_time)
                continue
            raise LLMError(f"LLM call failed after {max_retries} retries: {e}") from e

    try:
        data = response.json()
    except ValueError as e:
        raise LLMError(f"LLM response was not valid JSON: {e}") from e

    text = _extract_response_text(data)
    if not text:
        raise LLMError(f"LLM returned empty or missing content: {data}")

    return text
