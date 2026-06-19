"""
Catalyst Zia voice services: speech-to-text, translation, text-to-speech.

Auth convention matches every other Catalyst call in this codebase:
`Authorization: Zoho-oauthtoken {token}` plus the `CATALYST-ORG` header (see
llm/client.py and db/nosql_client.py). Catalyst responses use a `{"data": ...}`
envelope, which we unwrap defensively.

IMPORTANT — endpoint contract is best-effort:
The exact Zia REST request/response shapes are not published in the
fetchable docs (they're behind the console), so the request bodies and the
response field names below are best-guesses based on Catalyst conventions.
Every function is written to DEGRADE GRACEFULLY and LOG the raw response shape
on a parse miss, so when tested against the live endpoint the only thing that
may need adjusting is the field-name extraction in `_extract_*` — not the
calling code or the routes. STT/TTS raise VoiceError (caller decides fallback);
translation returns the original text unchanged on any failure so the pipeline
keeps running untranslated.
"""

import sys

import httpx

from config.settings import get


class VoiceError(Exception):
    """Raised when a Zia STT/TTS call fails or returns an unusable response."""
    pass


# Cap the text we send to TTS — synthesizing a huge answer is impractical and
# likely rejected by the service.
_TTS_MAX_CHARS = 1000


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _zia_headers(extra: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Zoho-oauthtoken {get('CATALYST_API_TOKEN')}",
        "CATALYST-ORG": get("CATALYST_ORG_ID"),
    }
    if extra:
        headers.update(extra)
    return headers


def _unwrap(data: dict) -> dict:
    """Return the inner `data` object of a Catalyst response envelope, or the
    payload itself if it isn't wrapped."""
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return data if isinstance(data, dict) else {}


def _extract_transcript(payload: dict) -> str:
    """Pull the transcript text from a STT response, tolerating a few likely
    field names so a minor contract difference doesn't break us."""
    inner = _unwrap(payload)
    for key in ("transcript", "text", "transcription", "result"):
        val = inner.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _extract_translation(payload: dict) -> str:
    inner = _unwrap(payload)
    for key in ("translated_text", "translation", "text", "result"):
        val = inner.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


async def transcribe_audio(audio_bytes: bytes, language: str = "en") -> str:
    """
    Send recorded audio to Zia STT as multipart/form-data and return the
    transcript string.

    Raises VoiceError on transport error, non-200, or an empty/unparseable
    transcript — the caller (router) turns that into a graceful 502 so the UI
    can tell the officer to type instead. Timeout 20s (audio is slower).
    """
    try:
        url = get("ZIA_STT_URL")
    except ValueError as e:
        raise VoiceError(f"STT not configured: {e}") from e

    files = {"file": ("audio.webm", audio_bytes, "audio/webm")}
    data = {"language": language}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=_zia_headers(), files=files, data=data, timeout=20.0
            )
    except httpx.HTTPError as e:
        raise VoiceError(f"STT request failed: {e}") from e

    if resp.status_code != 200:
        body = resp.text[:300] if resp.text else "<empty>"
        raise VoiceError(f"STT returned HTTP {resp.status_code}: {body}")

    try:
        payload = resp.json()
    except ValueError as e:
        raise VoiceError(f"STT response was not valid JSON: {e}") from e

    transcript = _extract_transcript(payload)
    if not transcript:
        # Log the shape so the field-name mapping can be corrected if the live
        # contract differs from our best guess.
        _log(f"STT returned no transcript; raw response keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload)}")
        raise VoiceError("STT returned an empty transcript.")
    return transcript


async def translate_to_english(text: str, source_language: str = "kn") -> str:
    """
    Translate `text` (default Kannada) to English via Zia Translation.

    Degrades gracefully: on ANY failure returns the original text unchanged so
    the NL2SQL pipeline still runs (just untranslated) rather than blocking the
    officer. Never raises. Timeout 10s.
    """
    if not text or not text.strip():
        return text
    if source_language == "en":
        return text

    try:
        url = get("ZIA_TRANSLATE_URL")
    except ValueError as e:
        _log(f"translation not configured, passing text through: {e}")
        return text

    payload = {
        "text": text,
        "source_language": source_language,
        "target_language": "en",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers=_zia_headers({"Content-Type": "application/json"}),
                json=payload,
                timeout=10.0,
            )
        if resp.status_code == 200:
            translated = _extract_translation(resp.json())
            if translated:
                return translated
            _log("translation returned empty result; passing original text through")
        else:
            _log(f"translation returned HTTP {resp.status_code}; passing original text through")
    except Exception as e:
        _log(f"translation failed, passing original text through: {e}")

    return text


async def synthesize_speech(text: str, language: str = "en") -> bytes:
    """
    Convert `text` to speech audio via Zia TTS. Returns raw audio bytes
    (format set by Zia — typically MP3/WAV; the route serves it as audio/mpeg).

    Truncates to _TTS_MAX_CHARS first. Raises VoiceError on failure — TTS is an
    enhancement, so the route turns this into a quiet 502 and the UI simply
    doesn't play audio. Timeout 20s.
    """
    clipped = (text or "").strip()[:_TTS_MAX_CHARS]
    if not clipped:
        raise VoiceError("No text to synthesize.")

    try:
        url = get("ZIA_TTS_URL")
    except ValueError as e:
        raise VoiceError(f"TTS not configured: {e}") from e

    payload = {"text": clipped, "language": language}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers=_zia_headers({"Content-Type": "application/json"}),
                json=payload,
                timeout=20.0,
            )
    except httpx.HTTPError as e:
        raise VoiceError(f"TTS request failed: {e}") from e

    if resp.status_code != 200:
        body = resp.text[:300] if resp.text else "<empty>"
        raise VoiceError(f"TTS returned HTTP {resp.status_code}: {body}")

    if not resp.content:
        raise VoiceError("TTS returned empty audio.")
    return resp.content
