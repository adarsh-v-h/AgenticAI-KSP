/*
VoiceInput — mic recording button, used inside Composer.

Props:
  onTranscript: (text: string) => void  — called with the final transcript
                                            (English translation when lang=kn)
  language: 'en' | 'kn'
  disabled: bool                         — disabled while a chat is streaming

Flow:
  idle → click → getUserMedia → MediaRecorder records
  recording → click (or 30s auto-stop) → stop → POST to STT
  processing → onTranscript(result) → idle

Degrades gracefully: mic-permission denial or STT failure shows a brief inline
tip and returns to idle. The officer can always type instead — voice never
blocks the composer.
*/
import { useEffect, useRef, useState } from 'react'
import { recordAndTranscribe } from '../api/voice.js'
import { IconMic } from './Icons.jsx'

const MAX_RECORDING_MS = 30000

export default function VoiceInput({ onTranscript, language = 'en', disabled = false }) {
  const [state, setState] = useState('idle') // idle | recording | processing
  const [errorMsg, setErrorMsg] = useState(null)
  const mediaRecorderRef = useRef(null)
  const chunksRef = useRef([])
  const streamRef = useRef(null)
  const autoStopRef = useRef(null)

  // Clean up the mic stream + timer if the component unmounts mid-recording.
  useEffect(() => {
    return () => {
      if (autoStopRef.current) clearTimeout(autoStopRef.current)
      stopTracks()
    }
  }, [])

  function stopTracks() {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
  }

  async function startRecording() {
    setErrorMsg(null)
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setErrorMsg('Voice input not supported in this browser.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data)
      }
      recorder.onstop = handleStop
      recorder.start()
      mediaRecorderRef.current = recorder
      setState('recording')
      // Safety auto-stop so a forgotten recording doesn't run forever.
      autoStopRef.current = setTimeout(() => stopRecording(), MAX_RECORDING_MS)
    } catch (e) {
      setErrorMsg('Microphone access denied.')
      stopTracks()
    }
  }

  function stopRecording() {
    if (autoStopRef.current) {
      clearTimeout(autoStopRef.current)
      autoStopRef.current = null
    }
    const recorder = mediaRecorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop()
    }
  }

  async function handleStop() {
    stopTracks()
    setState('processing')
    const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
    chunksRef.current = []

    if (blob.size === 0) {
      setErrorMsg("Didn't catch any audio — try again.")
      setState('idle')
      return
    }

    try {
      const data = await recordAndTranscribe(blob, language)
      const text = (data.translated || data.transcript || '').trim()
      if (text) {
        onTranscript?.(text)
      } else {
        setErrorMsg("Couldn't hear that — try typing instead.")
      }
    } catch (e) {
      setErrorMsg(e?.message || "Couldn't hear that — try typing instead.")
    } finally {
      setState('idle')
    }
  }

  const isRecording = state === 'recording'
  const isProcessing = state === 'processing'

  const title = isRecording
    ? 'Stop recording'
    : isProcessing
      ? 'Transcribing...'
      : 'Voice input'

  return (
    <div className="voice-input-wrap">
      <button
        className={`composer-action-btn${isRecording ? ' recording' : ''}`}
        title={title}
        aria-label={title}
        onClick={isRecording ? stopRecording : startRecording}
        disabled={disabled || isProcessing}
        type="button"
      >
        {isProcessing ? <span className="voice-spinner" /> : <IconMic size={18} />}
      </button>
      {errorMsg ? <span className="voice-error-tip">{errorMsg}</span> : null}
    </div>
  )
}
