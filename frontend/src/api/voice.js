// Voice API client — Zia STT (transcribe) and TTS (speak) via the backend.
// Tokens are read through getToken() to stay consistent with the rest of the
// app. The backend talks to Catalyst Zia with its own auth; the browser only
// ever uses the app JWT (Bearer) against our own API.

import { getToken } from './auth.js'
import { API_BASE } from '../config.js'

// Convert WebM audio blob to WAV format using AudioContext and DataView.
async function convertWebmToWav(webmBlob) {
  if (typeof window === 'undefined') return webmBlob
  const AudioContextClass = window.AudioContext || window.webkitAudioContext
  if (!AudioContextClass) return webmBlob

  const audioContext = new AudioContextClass()
  if (audioContext.state === 'suspended') {
    await audioContext.resume()
  }
  let audioBuffer
  try {
    const arrayBuffer = await webmBlob.arrayBuffer()
    audioBuffer = await audioContext.decodeAudioData(arrayBuffer)
  } finally {
    audioContext.close().catch(() => {})
  }

  const numOfChan = audioBuffer.numberOfChannels
  const sampleRate = audioBuffer.sampleRate
  const format = 1 // Raw PCM
  const bitDepth = 16

  let result
  if (numOfChan === 2) {
    const l = audioBuffer.getChannelData(0)
    const r = audioBuffer.getChannelData(1)
    result = new Float32Array(l.length + r.length)
    let index = 0
    let inputIndex = 0
    while (index < result.length) {
      result[index++] = l[inputIndex]
      result[index++] = r[inputIndex]
      inputIndex++
    }
  } else {
    result = audioBuffer.getChannelData(0)
  }

  const bufferLength = result.length * 2
  const fileLength = bufferLength + 44
  const ab = new ArrayBuffer(fileLength)
  const view = new DataView(ab)

  const writeString = (v, offset, string) => {
    for (let i = 0; i < string.length; i++) {
      v.setUint8(offset + i, string.charCodeAt(i))
    }
  }

  writeString(view, 0, 'RIFF')
  view.setUint32(4, fileLength - 8, true)
  writeString(view, 8, 'WAVE')
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, format, true)
  view.setUint16(22, numOfChan, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * numOfChan * (bitDepth / 8), true)
  view.setUint16(32, numOfChan * (bitDepth / 8), true)
  view.setUint16(34, bitDepth, true)
  writeString(view, 36, 'data')
  view.setUint32(40, bufferLength, true)

  const offset = 44
  for (let i = 0; i < result.length; i++) {
    const s = Math.max(-1, Math.min(1, result[i]))
    view.setInt16(offset + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }

  return new Blob([view], { type: 'audio/wav' })
}

// CONTRACT
// takes:  audioBlob (Blob) — recorded audio in webm format, language ('en'|'kn') — spoken language code
// returns: (Promise<{transcript: string, translated: string|null}>) — transcription result
// throws:  Error — with user-friendly message on network or transcription failure
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
  
  let processedBlob = audioBlob
  try {
    processedBlob = await convertWebmToWav(audioBlob)
  } catch (e) {
    console.error('WAV conversion failed, uploading raw audio', e)
  }

  const formData = new FormData()
  formData.append('audio', processedBlob, 'recording.wav')
  formData.append('language', language)

  let res
  try {
    res = await fetch(`${API_BASE}/api/voice/transcribe`, {
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

// CONTRACT
// takes:  text (string) — text to synthesize into speech, language ('en'|'kn') — target language
// returns: (Promise<boolean>) — true if audio played successfully, false otherwise
// throws:  never
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
    const res = await fetch(`${API_BASE}/api/voice/speak`, {
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
