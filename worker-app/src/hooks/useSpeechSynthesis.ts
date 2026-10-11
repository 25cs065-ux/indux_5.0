import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  SPEECH_SYNTHESIS_LANG,
  onSpeechCancelled,
  pickVoice,
  synthesisErrorFrom,
  synthesisSupported,
} from '../speech/synthesis.ts'
import type { SynthesisError } from '../speech/synthesis.ts'

export type SpeakingStatus = 'idle' | 'speaking'

/**
 * Reads text aloud with the browser's speechSynthesis. speak() is ignored
 * while a session is playing, so repeated clicks never overlap or restart.
 * Speech stops on stop(), on unmount, and when cancelAllSpeech() is called.
 */
export function useSpeechSynthesis() {
  const supported = useMemo(() => synthesisSupported(window), [])
  const [status, setStatus] = useState<SpeakingStatus>('idle')
  const [error, setError] = useState<SynthesisError | null>(null)
  // Incremented per session so events from cancelled sessions are ignored.
  const session = useRef(0)
  const active = useRef(false)

  const reset = useCallback(() => {
    session.current += 1
    active.current = false
    setStatus('idle')
  }, [])

  const stop = useCallback(() => {
    if (!supported) return
    if (active.current) window.speechSynthesis.cancel()
    reset()
  }, [supported, reset])

  const speak = useCallback(
    (segments: string[]): boolean => {
      if (!supported || segments.length === 0 || active.current) return false
      const synth = window.speechSynthesis
      // Clear anything another page or tab left in the shared queue.
      synth.cancel()
      session.current += 1
      const id = session.current
      active.current = true
      setError(null)
      setStatus('speaking')

      const voice = pickVoice(synth.getVoices?.() ?? [])
      segments.forEach((text, index) => {
        const utterance = new window.SpeechSynthesisUtterance(text)
        utterance.lang = voice?.lang ?? SPEECH_SYNTHESIS_LANG
        if (voice) utterance.voice = voice
        utterance.rate = 0.95
        const isLast = index === segments.length - 1
        utterance.onend = () => {
          if (session.current === id && isLast) reset()
        }
        utterance.onerror = (event) => {
          if (session.current !== id) return
          const mapped = synthesisErrorFrom(event.error)
          if (mapped) setError(mapped)
          synth.cancel()
          reset()
        }
        synth.speak(utterance)
      })
      return true
    },
    [supported, reset],
  )

  // Another part of the app (e.g. the microphone) silenced all speech.
  useEffect(() => onSpeechCancelled(() => active.current && reset()), [reset])

  useEffect(
    () => () => {
      if (active.current && synthesisSupported(window)) window.speechSynthesis.cancel()
      session.current += 1
      active.current = false
    },
    [],
  )

  return { supported, status, error, speak, stop, isSpeaking: status === 'speaking' }
}
