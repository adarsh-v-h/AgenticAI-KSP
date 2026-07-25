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
from config.catalyst_token import get_access_token
from http_client import get_http_client


class VoiceError(Exception):
    """Raised when a Zia STT/TTS call fails or returns an unusable response."""
    pass


# Cap the text we send to TTS — synthesizing a huge answer is impractical and
# likely rejected by the service.
_TTS_MAX_CHARS = 400


# CONTRACT
# takes:  msg (str) — message to log
# returns: nothing
# raises:  nothing
def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# CONTRACT
# takes:  extra (dict | None) — additional headers to merge
# returns: (dict) — HTTP headers with Catalyst OAuth token and org ID
# raises:  RuntimeError — when no Catalyst access token can be obtained
async def _zia_headers(extra: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Zoho-oauthtoken {await get_access_token()}",
        "CATALYST-ORG": get("CATALYST_ORG_ID"),
    }
    if extra:
        headers.update(extra)
    return headers


# CONTRACT
# takes:  data (dict) — raw Catalyst API response
# returns: (dict) — inner data object unwrapped from the Catalyst envelope
# raises:  nothing
def _unwrap(data: dict) -> dict:
    """Return the inner `data` object of a Catalyst response envelope, or the
    payload itself if it isn't wrapped."""
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return data if isinstance(data, dict) else {}


# CONTRACT
# takes:  payload (dict) — raw STT API response
# returns: (str) — extracted transcript text, or empty string if not found
# raises:  nothing
def _extract_transcript(payload: dict) -> str:
    """Pull the transcript text from a STT response, tolerating a few likely
    field names so a minor contract difference doesn't break us."""
    inner = _unwrap(payload)
    for key in ("transcript", "text", "transcription", "result"):
        val = inner.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


# CONTRACT
# takes:  payload (dict) — raw Translation API response
# returns: (str) — extracted translated text, or empty string if not found
# raises:  nothing
def _extract_translation(payload: dict) -> str:
    inner = _unwrap(payload)
    for key in ("translated_text", "translation", "text", "result"):
        val = inner.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


async def _ensure_wav(audio_bytes: bytes) -> bytes:
    """Ensure audio bytes are in standard 16kHz mono WAV format. Converts via ffmpeg if needed."""
    if audio_bytes.startswith(b"RIFF") and b"WAVE" in audio_bytes[:16]:
        return audio_bytes
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", "pipe:0", "-f", "wav", "-ac", "1", "-ar", "16000", "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate(input=audio_bytes)
        if proc.returncode == 0 and stdout.startswith(b"RIFF"):
            return stdout
    except Exception as e:
        _log(f"ffmpeg conversion to wav failed: {e}")
    return audio_bytes


# CONTRACT
# takes:  audio_bytes (bytes) — recorded audio data, language (str) — language code of the audio
# returns: (str) — transcription text
# raises:  VoiceError — when STT is not configured, request fails, or transcript is empty
async def transcribe_audio(audio_bytes: bytes, language: str = "en") -> str:
    """
    Send recorded audio to Zia STT as multipart/form-data and return the
    transcript string. Auto-converts WebM/Ogg/MP3 audio to WAV via ffmpeg if needed.

    Raises VoiceError on transport error, non-200, or an empty/unparseable
    transcript — the caller (router) turns that into a graceful 502 so the UI
    can tell the officer to type instead. Timeout 20s (audio is slower).
    """
    try:
        url = get("ZIA_STT_URL")
    except ValueError as e:
        raise VoiceError(f"STT not configured: {e}") from e

    wav_bytes = await _ensure_wav(audio_bytes)
    files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
    data = {"language": language}

    try:
        client = get_http_client()
        resp = await client.post(
            url, headers=await _zia_headers(), files=files, data=data, timeout=20.0
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


# CONTRACT
# takes:  text (str) — text to translate, source_language (str) — ISO language code of source text
# returns: (str) — English translation, or original text on any failure
# raises:  nothing (degrades gracefully, never raises)
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

    # Zia Translate uses src_lang/tgt_lang, NOT source_language/target_language.
    # Confirmed via Catalyst console sample request.
    payload = {
        "text": text,
        "src_lang": source_language,
        "tgt_lang": "en",
    }

    try:
        client = get_http_client()
        resp = await client.post(
            url,
            headers=await _zia_headers({"Content-Type": "application/json"}),
            json=payload,
            timeout=10.0,
        )
        if resp.status_code == 200:
            # Response shape: {"status": "success", "translated_text": "...", ...}
            # translated_text is top-level, NOT nested under a "data" key.
            data = resp.json()
            translated = data.get("translated_text")
            if translated:
                return translated
            _log("translation returned empty result; passing original text through")
        else:
            _log(f"translation returned HTTP {resp.status_code}; passing original text through")
    except Exception as e:
        _log(f"translation failed, passing original text through: {e}")

    return text

# CONTRACT
# takes:  text (str) — markdown-containing answer text
# returns: (str) — text with table pipes, headers, and markdown symbols removed
# raises:  nothing
def _strip_markdown_for_speech(text: str) -> str:
    """Remove table pipes, headers, and markdown symbols before TTS."""
    import re
    text = re.sub(r'\|.*\|', '', text)
    text = re.sub(r'^\s*[-:]+\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'[*_#`]', '', text)
    # Collapse multiple blank lines left behind by stripped table rows
    text = re.sub(r'\n{2,}', ' ', text)
    return text.strip()

# CONTRACT
# takes:  text (str) — text containing abbreviations TTS engines mispronounce
# returns: (str) — text with abbreviations expanded to phonetic spellings
# raises:  nothing
def _normalize_for_speech(text: str) -> str:
    """
    Expand abbreviations TTS engines mispronounce into phonetic spellings
    or full words, since Zia has no SSML/phoneme control we can hook into.
    """
    replacements = {
    r'\bFIR\b': 'F I R',
    r'\bWHI\b': 'Whitefield',
    r'\bKOR\b': 'Koramangala',
    r'\bBTM\b': 'B T M Layout',
    r'\bHSR\b': 'H S R Layout',
    r'\bJPN\b': 'J P Nagar',
    r'\bRAJ\b': 'Rajajinagar',
    r'\bMAL\b': 'Malleshwaram',
    r'\bYES\b': 'Yeshwanthpur',
    r'\bECE\b': 'Electronic City',
    r'\bHEB\b': 'Hebbal',
    r'\bSHI\b': 'Shivajinagar',
}   
    import re
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    return text

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

def _int_to_words(n: int) -> str:
    if n < 0:
        return "minus " + _int_to_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens_part = _TENS[n // 10]
        rem = n % 10
        return f"{tens_part}-{_ONES[rem]}" if rem else tens_part
    if n < 1000:
        hundreds = _ONES[n // 100] + " hundred"
        rem = n % 100
        return f"{hundreds} {_int_to_words(rem)}" if rem else hundreds
    if n < 1000000:
        thousands = _int_to_words(n // 1000) + " thousand"
        rem = n % 1000
        return f"{thousands} {_int_to_words(rem)}" if rem else thousands
    return str(n)

def _number_match_to_natural_words(match) -> str:
    num_str = match.group(0)
    try:
        n = int(num_str)
    except ValueError:
        return num_str

    # Spoken years (e.g. 2024 -> "twenty twenty-four", 2026 -> "twenty twenty-six")
    if 1900 <= n <= 2099:
        if n == 2000:
            return "two thousand"
        if 2001 <= n <= 2009:
            return f"two thousand {_ONES[n - 2000]}"
        first_two = n // 100
        last_two = n % 100
        return f"{_int_to_words(first_two)} {_int_to_words(last_two)}"

    return _int_to_words(n)

# CONTRACT
# takes:  text (str) — text containing numbers
# returns: (str) — text with numbers converted to natural spoken English words (e.g. 47 -> forty-seven, 2024 -> twenty twenty-four)
# raises:  nothing
def _numbers_to_words(text: str) -> str:
    """
    Convert numbers into natural spoken English words (e.g. 47 -> "forty-seven",
    2024 -> "twenty twenty-four") so text-to-speech sounds natural and fluent.
    """
    import re
    return re.sub(r'\b\d+\b', _number_match_to_natural_words, text)

_TTS_MAX_CHARS = 200

# CONTRACT
# takes:  text (str) — text to synthesize into speech, language (str) — language code for TTS
# returns: (bytes) — raw audio bytes (MP3/WAV)
# raises:  VoiceError — when TTS is not configured, text is empty, request fails, or response is empty
async def synthesize_speech(text: str, language: str = "en") -> bytes:
    """
    Convert `text` to speech audio via Zia TTS. Returns raw audio bytes
    (format set by Zia — typically MP3/WAV; the route serves it as audio/wav).

    Truncates to _TTS_MAX_CHARS first. Raises VoiceError on failure — TTS is an
    enhancement, so the route turns this into a quiet 502 and the UI simply
    doesn't play audio. Timeout 30s.
    """
    raw_text = (text or "").strip()
    if language == "kn" and raw_text:
        raw_text = await translate_to_english(raw_text, source_language="kn")

    clipped = _normalize_for_speech(_numbers_to_words(_strip_markdown_for_speech(raw_text)))[:_TTS_MAX_CHARS]
    if not clipped:
        raise VoiceError("No text to synthesize.")

    try:
        url = get("ZIA_TTS_URL")
    except ValueError as e:
        raise VoiceError(f"TTS not configured: {e}") from e

    # Zia QuickML TTS only supports English speaker 'Mary'.
    payload = {
        "text": clipped,
        "language": "en",
        "speaker": "Mary",
        "pitch": "moderate",
        "speed": "moderate",
        "emotion": "neutral",
    }

    try:
        client = get_http_client()
        resp = await client.post(
            url,
            headers=await _zia_headers({"Content-Type": "application/json"}),
            json=payload,
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        raise VoiceError(f"TTS request failed: {e}") from e

    if resp.status_code != 200:
        body = resp.text[:300] if resp.text else "<empty>"
        raise VoiceError(f"TTS returned HTTP {resp.status_code}: {body}")

    if not resp.content:
        raise VoiceError("TTS returned empty audio.")
    return resp.content


async def ping_voice() -> None:
    """
    Ping Zia translation, speech-to-text, and text-to-speech services to warm
    their serverless endpoints/lambdas, mitigating cold start latency.
    """
    # 1. Warm Translation
    try:
        await translate_to_english("ನಮಸ್ಕಾರ", source_language="kn")
    except Exception as e:
        _log(f"Zia Translation warm-up ping failed: {e}")

    # 2. Warm TTS (text-to-speech)
    try:
        await synthesize_speech("OK", language="en")
    except Exception as e:
        _log(f"Zia TTS warm-up ping failed: {e}")

    # 3. Warm STT (speech-to-text) by sending a tiny dummy audio payload.
    # Even if STT fails or returns an error on dummy data, hitting the endpoint
    # warms the Zoho Catalyst serverless container.
    try:
        dummy_webm = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x11\x2b\x00\x00\x11\x2b\x00\x00\x01\x00\x08\x00data\x00\x00\x00\x00"
        await transcribe_audio(dummy_webm, language="en")
    except Exception as e:
        _log(f"Zia STT warm-up ping (expected result/warmup): {e}")

