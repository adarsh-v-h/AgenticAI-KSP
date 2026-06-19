"""Tests for the voice pipeline (voice.zia_voice + routers.voice).

Pure helpers (envelope unwrap, transcript/translation extraction) are tested
directly. The async network functions are exercised with a fake httpx client,
and the routes with the zia_voice functions monkeypatched — so no real Zia /
network calls happen. Async bodies run via asyncio.run (no pytest-asyncio),
matching the rest of the suite.
"""

import asyncio
import io

import pytest
from fastapi import HTTPException

import voice.zia_voice as zv
import routers.voice as vr


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def test_unwrap_returns_inner_data():
    assert zv._unwrap({"data": {"transcript": "hi"}}) == {"transcript": "hi"}


def test_unwrap_passthrough_when_not_wrapped():
    assert zv._unwrap({"transcript": "hi"}) == {"transcript": "hi"}
    assert zv._unwrap("nope") == {}


def test_extract_transcript_tolerates_field_names():
    assert zv._extract_transcript({"data": {"transcript": "a"}}) == "a"
    assert zv._extract_transcript({"text": "b"}) == "b"
    assert zv._extract_transcript({"data": {"transcription": "c"}}) == "c"
    assert zv._extract_transcript({"data": {}}) == ""


def test_extract_translation_tolerates_field_names():
    assert zv._extract_translation({"data": {"translated_text": "x"}}) == "x"
    assert zv._extract_translation({"translation": "y"}) == "y"
    assert zv._extract_translation({"data": {}}) == ""


# --------------------------------------------------------------------------- #
# Fake httpx client
# --------------------------------------------------------------------------- #


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, content=b"", text=""):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class _FakeClient:
    """Stands in for httpx.AsyncClient; returns a preset response from post()."""
    def __init__(self, resp=None, raise_exc=None):
        self._resp = resp
        self._raise = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *args, **kwargs):
        if self._raise:
            raise self._raise
        return self._resp


def _patch_client(monkeypatch, resp=None, raise_exc=None):
    monkeypatch.setattr(
        zv.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp, raise_exc)
    )


def _patch_env(monkeypatch):
    # zia_voice.get(...) reads env URLs/token; stub them so no real .env needed.
    monkeypatch.setattr(zv, "get", lambda key: f"http://fake/{key}")


# --------------------------------------------------------------------------- #
# transcribe_audio
# --------------------------------------------------------------------------- #


def test_transcribe_returns_transcript(monkeypatch):
    _patch_env(monkeypatch)
    _patch_client(monkeypatch, _FakeResp(200, {"data": {"transcript": "how many thefts"}}))
    result = asyncio.run(zv.transcribe_audio(b"audio", "en"))
    assert result == "how many thefts"


def test_transcribe_raises_on_non_200(monkeypatch):
    _patch_env(monkeypatch)
    _patch_client(monkeypatch, _FakeResp(500, text="server error"))
    with pytest.raises(zv.VoiceError):
        asyncio.run(zv.transcribe_audio(b"audio", "en"))


def test_transcribe_raises_on_empty_transcript(monkeypatch):
    _patch_env(monkeypatch)
    _patch_client(monkeypatch, _FakeResp(200, {"data": {}}))
    with pytest.raises(zv.VoiceError):
        asyncio.run(zv.transcribe_audio(b"audio", "en"))


# --------------------------------------------------------------------------- #
# translate_to_english — graceful degradation
# --------------------------------------------------------------------------- #


def test_translate_returns_translation(monkeypatch):
    _patch_env(monkeypatch)
    _patch_client(monkeypatch, _FakeResp(200, {"data": {"translated_text": "how many thefts"}}))
    out = asyncio.run(zv.translate_to_english("ಎಷ್ಟು ಕಳ್ಳತನ", "kn"))
    assert out == "how many thefts"


def test_translate_passthrough_on_failure(monkeypatch):
    _patch_env(monkeypatch)
    _patch_client(monkeypatch, raise_exc=RuntimeError("network down"))
    original = "ಎಷ್ಟು ಕಳ್ಳತನ"
    # Never raises; returns the original text so the pipeline still runs.
    out = asyncio.run(zv.translate_to_english(original, "kn"))
    assert out == original


def test_translate_skips_when_already_english(monkeypatch):
    # Should not even attempt a call when source is English.
    _patch_env(monkeypatch)
    _patch_client(monkeypatch, raise_exc=AssertionError("must not call translate for en"))
    out = asyncio.run(zv.translate_to_english("hello", "en"))
    assert out == "hello"


# --------------------------------------------------------------------------- #
# synthesize_speech
# --------------------------------------------------------------------------- #


def test_synthesize_returns_audio_bytes(monkeypatch):
    _patch_env(monkeypatch)
    _patch_client(monkeypatch, _FakeResp(200, content=b"\x00\x01audio"))
    out = asyncio.run(zv.synthesize_speech("read this aloud", "en"))
    assert out == b"\x00\x01audio"


def test_synthesize_raises_on_empty_text(monkeypatch):
    _patch_env(monkeypatch)
    with pytest.raises(zv.VoiceError):
        asyncio.run(zv.synthesize_speech("   ", "en"))


def test_synthesize_raises_on_non_200(monkeypatch):
    _patch_env(monkeypatch)
    _patch_client(monkeypatch, _FakeResp(502, text="bad gateway"))
    with pytest.raises(zv.VoiceError):
        asyncio.run(zv.synthesize_speech("hello", "en"))


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


class _FakeUpload:
    def __init__(self, data: bytes):
        self._data = data

    async def read(self):
        return self._data


def test_transcribe_route_translates_kannada(monkeypatch):
    async def scenario():
        async def fake_transcribe(audio_bytes, language="en"):
            return "ಪ್ರಶ್ನೆ"

        async def fake_translate(text, source_language="kn"):
            return "question in english"

        monkeypatch.setattr(vr, "transcribe_audio", fake_transcribe)
        monkeypatch.setattr(vr, "translate_to_english", fake_translate)

        resp = await vr.transcribe(
            audio=_FakeUpload(b"audio"), language="kn", officer={"officer_id": 1}
        )
        assert resp.transcript == "ಪ್ರಶ್ನೆ"
        assert resp.translated == "question in english"

    asyncio.run(scenario())


def test_transcribe_route_english_no_translation(monkeypatch):
    async def scenario():
        async def fake_transcribe(audio_bytes, language="en"):
            return "how many theft cases"

        async def fake_translate(text, source_language="kn"):
            raise AssertionError("translation must not run for English")

        monkeypatch.setattr(vr, "transcribe_audio", fake_transcribe)
        monkeypatch.setattr(vr, "translate_to_english", fake_translate)

        resp = await vr.transcribe(
            audio=_FakeUpload(b"audio"), language="en", officer={"officer_id": 1}
        )
        assert resp.transcript == "how many theft cases"
        assert resp.translated is None

    asyncio.run(scenario())


def test_transcribe_route_502_on_voice_error(monkeypatch):
    async def scenario():
        async def fake_transcribe(audio_bytes, language="en"):
            raise zv.VoiceError("stt down")

        monkeypatch.setattr(vr, "transcribe_audio", fake_transcribe)

        with pytest.raises(HTTPException) as exc:
            await vr.transcribe(
                audio=_FakeUpload(b"audio"), language="en", officer={"officer_id": 1}
            )
        assert exc.value.status_code == 502

    asyncio.run(scenario())


def test_transcribe_route_400_on_empty_audio(monkeypatch):
    async def scenario():
        with pytest.raises(HTTPException) as exc:
            await vr.transcribe(
                audio=_FakeUpload(b""), language="en", officer={"officer_id": 1}
            )
        assert exc.value.status_code == 400

    asyncio.run(scenario())


def test_speak_route_streams_audio(monkeypatch):
    async def scenario():
        async def fake_synth(text, language="en"):
            return b"audio-bytes"

        monkeypatch.setattr(vr, "synthesize_speech", fake_synth)

        req = vr.SpeakRequest(text="read this", language="en")
        resp = await vr.speak(req, officer={"officer_id": 1})
        assert resp.media_type == "audio/mpeg"

    asyncio.run(scenario())


def test_speak_route_502_on_voice_error(monkeypatch):
    async def scenario():
        async def fake_synth(text, language="en"):
            raise zv.VoiceError("tts down")

        monkeypatch.setattr(vr, "synthesize_speech", fake_synth)

        req = vr.SpeakRequest(text="read this", language="en")
        with pytest.raises(HTTPException) as exc:
            await vr.speak(req, officer={"officer_id": 1})
        assert exc.value.status_code == 502

    asyncio.run(scenario())
