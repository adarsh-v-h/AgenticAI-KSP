// Voice API client — Zia STT (transcribe) and TTS (speak) via the backend.
// Tokens are read through getToken() to stay consistent with the rest of the
// app. The backend talks to Catalyst Zia with its own auth; the browser only
// ever uses the app JWT (Bearer) against our own API.

import { getToken } from './auth.js'

/**
 * Transcribe a recorded audio blob.
 *
 * POST /api/voice/transcribe (multipart/form-data: audio, language)
 *
 * @param {Blob} audioBlob - recorded audio (webm)
 * @param {'en'|'kn'} language - spoken language; 'kn' also returns English translation
 * @returns {Promise<{transcript: string, translated: string|null}>}
 * @throws {Error} with a user-friendly message on failure
 */
export async function recordAndTranscribe(audioBlob, language = 'en') {
  const token = getToken()
  const formData = new FormData()
  formData.append('audio', audioBlob, 'recording.webm')
  formData.append('language', language)

  let res
  try {
    res = await fetch('/api/voice/transcribe', {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    })
  } catch (err) {
    throw new Error('Cannot reach the server.')
  }

  if (!res.ok) {
    // 502 carries the backend's "please type" message; surface it when present.
    let detail = 'Transcription failed.'
    try {
      const data = await res.json()
      if (data?.detail) detail = data.detail
    } catch {
      // ignore parse error, keep default
    }
    throw new Error(detail)
  }

  const data = await res.json()
  return {
    transcript: data?.transcript || '',
    translated: data?.translated ?? null,
  }
}

/**
 * Synthesize speech for `text` and play it. Best-effort: resolves to true when
 * audio played, false when synthesis was unavailable. Never throws — TTS is an
 * enhancement, so callers can ignore the result.
 *
 * POST /api/voice/speak (JSON: {text, language}) → audio stream
 *
 * @param {string} text
 * @param {'en'|'kn'} language
 * @returns {Promise<boolean>}
 */
export async function speakText(text, language = 'en') {
  const token = getToken()
  try {
    const res = await fetch('/api/voice/speak', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ text, language }),
    })
    if (!res.ok) return false

    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    // Revoke the object URL once playback ends to avoid leaking blob memory.
    audio.addEventListener('ended', () => URL.revokeObjectURL(url), { once: true })
    await audio.play()
    return true
  } catch (err) {
    return false
  }
}
