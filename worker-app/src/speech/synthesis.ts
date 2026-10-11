// Browser text-to-speech (speechSynthesis) helpers. Free, built into the
// browser; no external service is called by the app.

export const SPEECH_SYNTHESIS_LANG = 'en-IN'

interface SynthesisWindow {
  speechSynthesis?: SpeechSynthesis
  SpeechSynthesisUtterance?: typeof SpeechSynthesisUtterance
}

export function synthesisSupported(win: unknown): boolean {
  const w = win as SynthesisWindow
  return !!w.speechSynthesis && typeof w.SpeechSynthesisUtterance === 'function'
}

/** Prefers an en-IN voice, then any English voice; null lets the browser choose. */
export function pickVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  return (
    voices.find((v) => v.lang.replace('_', '-').toLowerCase() === 'en-in') ??
    voices.find((v) => v.lang.toLowerCase().startsWith('en')) ??
    null
  )
}

// speechSynthesis is one global queue. Anything that must silence it (e.g.
// starting the microphone) calls cancelAllSpeech(), and every reader resets.
const listeners = new Set<() => void>()

export function onSpeechCancelled(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function cancelAllSpeech(): void {
  if (synthesisSupported(window)) window.speechSynthesis.cancel()
  for (const listener of [...listeners]) listener()
}

export type SynthesisErrorKind = 'blocked' | 'unavailable' | 'failed'

export interface SynthesisError {
  kind: SynthesisErrorKind
  message: string
}

/** Maps SpeechSynthesisErrorEvent.error. Returns null for our own cancellations. */
export function synthesisErrorFrom(code: string): SynthesisError | null {
  if (code === 'interrupted' || code === 'canceled') return null
  if (code === 'not-allowed') {
    return { kind: 'blocked', message: 'The browser blocked audio playback. Press Read aloud again.' }
  }
  if (code === 'audio-busy' || code === 'audio-hardware' || code === 'voice-unavailable' || code === 'language-unavailable') {
    return {
      kind: 'unavailable',
      message: 'No speech voice or audio output is available. Check the device volume and sound output.',
    }
  }
  return { kind: 'failed', message: 'Reading aloud stopped unexpectedly. Try again.' }
}
