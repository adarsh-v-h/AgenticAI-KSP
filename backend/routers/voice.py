"""
Voice routes — Catalyst Zia speech services.

POST /api/voice/transcribe — multipart audio upload → transcript (+ English
                             translation when language == "kn").
POST /api/voice/speak      — text → synthesized speech audio stream.

Both are auth-protected. Voice is an enhancement layer: failures return a clear
502 so the frontend can degrade gracefully (fall back to typing for STT; simply
not play audio for TTS) rather than breaking the composer.
"""

import io
import sys

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth.simple_auth import get_current_officer
from voice.zia_voice import (
    VoiceError,
    synthesize_speech,
    transcribe_audio,
    translate_to_english,
)

router = APIRouter()

# Audio upload cap — recordings are short questions, not files.
MAX_AUDIO_BYTES = 10 * 1024 * 1024


class TranscribeResponse(BaseModel):
    transcript: str
    translated: str | None = None


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    language: str = Field(default="en", max_length=8)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


@router.post("/api/voice/transcribe", response_model=TranscribeResponse)
async def transcribe(
    audio: UploadFile,
    language: str = Form(default="en"),
    officer: dict = Depends(get_current_officer),
) -> TranscribeResponse:
    """
    Transcribe a recorded audio blob via Zia STT. When `language == "kn"` the
    transcript is also translated to English (the NL2SQL pipeline works in
    English). Returns {transcript, translated}.

    HTTP 413 if the audio exceeds the size cap. HTTP 502 on Zia failure with a
    type-friendly message so the mic button degrades to "please type" rather
    than breaking the composer.
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio upload.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio file too large (max 10 MB).")

    try:
        transcript = await transcribe_audio(audio_bytes, language=language)
    except VoiceError as e:
        _log(f"transcribe failed: {e}")
        raise HTTPException(
            status_code=502,
            detail="Voice transcription unavailable. Please type your question.",
        ) from e

    translated = None
    if language == "kn" and transcript:
        # Never raises — returns original text on failure.
        translated = await translate_to_english(transcript, source_language="kn")

    return TranscribeResponse(transcript=transcript, translated=translated)


@router.post("/api/voice/speak")
async def speak(
    request: SpeakRequest,
    officer: dict = Depends(get_current_officer),
):
    """
    Synthesize `text` to speech via Zia TTS and stream the audio back.
    HTTP 502 on Zia failure — the frontend simply doesn't play audio (TTS is an
    enhancement, not core functionality), so no user-facing error is required.
    """
    try:
        audio_bytes = await synthesize_speech(request.text, language=request.language)
    except VoiceError as e:
        _log(f"speak failed: {e}")
        raise HTTPException(status_code=502, detail="Speech synthesis unavailable.") from e

    return StreamingResponse(io.BytesIO(audio_bytes), media_type="audio/mpeg")
