import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { SPEECH_LANG, getRecognitionCtor, speechSupport } from '../speech/support.ts'
import type { SpeechSupport } from '../speech/support.ts'
import { collapseFinals, speechErrorFrom } from '../speech/transcript.ts'
import type { SpeechError } from '../speech/transcript.ts'
import type { SpeechRecognitionLike } from '../speech/types.ts'

export type RecordingStatus = 'idle' | 'starting' | 'listening' | 'stopping'

interface Options {
  /** Called with this session's full final transcript whenever it changes. */
  onTranscript: (text: string) => void
  lang?: string
}

/** If a browser never fires `end` after stop(), force-close after this long. */
const STOP_GRACE_MS = 3000

function detach(rec: SpeechRecognitionLike) {
  rec.onstart = null
  rec.onresult = null
  rec.onerror = null
  rec.onend = null
}

/**
 * Browser speech-to-text. The recognizer is only created when start() is
 * called, so the microphone permission prompt never appears on page load.
 */
export function useSpeechRecognition({ onTranscript, lang = SPEECH_LANG }: Options) {
  const support: SpeechSupport = useMemo(() => speechSupport(window), [])
  const [status, setStatus] = useState<RecordingStatus>('idle')
  const [interim, setInterim] = useState('')
  const [error, setError] = useState<SpeechError | null>(null)
  const recRef = useRef<SpeechRecognitionLike | null>(null)
  const stopTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onTranscriptRef = useRef(onTranscript)

  useEffect(() => {
    onTranscriptRef.current = onTranscript
  })

  const clearStopTimer = () => {
    if (stopTimer.current) clearTimeout(stopTimer.current)
    stopTimer.current = null
  }

  /** Ends the session immediately and ignores any late events. */
  const teardown = useCallback((rec: SpeechRecognitionLike, mode: 'abort' | 'ended') => {
    detach(rec)
    if (recRef.current === rec) recRef.current = null
    clearStopTimer()
    if (mode === 'abort') {
      try {
        rec.abort()
      } catch {
        // Already stopped.
      }
    }
    setStatus('idle')
    setInterim('')
  }, [])

  const start = useCallback((): boolean => {
    // Repeated clicks while a session exists are ignored.
    if (recRef.current) return false
    if (support.status !== 'supported') {
      setError({ kind: 'failed', message: support.message })
      return false
    }
    const Ctor = getRecognitionCtor(window)
    if (!Ctor) return false

    const rec = new Ctor()
    rec.lang = lang
    rec.continuous = true
    rec.interimResults = true
    rec.maxAlternatives = 1

    // Final results keyed by result index: re-delivered events overwrite
    // rather than append, so duplicates cannot grow the transcript.
    const finals = new Map<number, string>()
    let lastEmitted = ''

    rec.onstart = () => {
      if (recRef.current === rec) setStatus((s) => (s === 'starting' ? 'listening' : s))
    }

    rec.onresult = (event) => {
      if (recRef.current !== rec) return
      let interimText = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i]
        const transcript = result?.[0]?.transcript ?? ''
        if (result?.isFinal) finals.set(i, transcript)
        else interimText += transcript
      }
      setInterim(interimText.replace(/\s+/g, ' ').trim())

      const ordered = [...finals.entries()].sort((a, b) => a[0] - b[0]).map(([, t]) => t)
      const text = collapseFinals(ordered)
      if (text !== lastEmitted) {
        lastEmitted = text
        onTranscriptRef.current(text)
      }
    }

    rec.onerror = (event) => {
      if (recRef.current !== rec) return
      // 'aborted' follows our own abort(); not an error for the worker.
      if (event.error === 'aborted') return
      setError(speechErrorFrom(event.error))
    }

    rec.onend = () => {
      if (recRef.current === rec) teardown(rec, 'ended')
    }

    recRef.current = rec
    setError(null)
    setInterim('')
    setStatus('starting')
    try {
      rec.start()
    } catch {
      teardown(rec, 'ended')
      setError(speechErrorFrom('start-failed'))
      return false
    }
    return true
  }, [lang, support, teardown])

  /** Stops listening and keeps any final text still being delivered. */
  const stop = useCallback(() => {
    const rec = recRef.current
    if (!rec) return
    setStatus('stopping')
    try {
      rec.stop()
    } catch {
      teardown(rec, 'abort')
      return
    }
    clearStopTimer()
    stopTimer.current = setTimeout(() => {
      if (recRef.current === rec) teardown(rec, 'abort')
    }, STOP_GRACE_MS)
  }, [teardown])

  /** Stops immediately and discards anything not yet final. */
  const abort = useCallback(() => {
    const rec = recRef.current
    if (rec) teardown(rec, 'abort')
  }, [teardown])

  const clearError = useCallback(() => setError(null), [])

  useEffect(
    () => () => {
      const rec = recRef.current
      if (rec) {
        detach(rec)
        recRef.current = null
        try {
          rec.abort()
        } catch {
          // Ignore.
        }
      }
      if (stopTimer.current) clearTimeout(stopTimer.current)
    },
    [],
  )

  return { support, status, interim, error, start, stop, abort, clearError, isActive: status !== 'idle' }
}
