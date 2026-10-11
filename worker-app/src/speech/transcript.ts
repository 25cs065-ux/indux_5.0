// Pure helpers for turning recognition results into question text.

function normalize(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/**
 * Joins final results in order, removing repeats. Some engines (notably
 * Chrome on Android) re-deliver a final result, or deliver cumulative finals
 * ("check oil", "check oil level") at new indices.
 */
export function collapseFinals(finals: string[]): string {
  const out: string[] = []
  for (const raw of finals) {
    const text = normalize(raw)
    if (!text) continue
    const prev = out[out.length - 1]
    if (prev !== undefined) {
      const a = prev.toLowerCase()
      const b = text.toLowerCase()
      if (a === b) continue
      if (b.startsWith(a)) {
        out[out.length - 1] = text
        continue
      }
      if (a.startsWith(b)) continue
    }
    out.push(text)
  }
  return out.join(' ')
}

/**
 * Builds the question from what was in the field when recording started plus
 * this session's recognised text. Always recomputed from `base`, so repeated
 * recognition events can never append the same words twice.
 */
export function composeQuestion(base: string, spoken: string, maxLength: number): string {
  const head = base.trimEnd()
  const tail = normalize(spoken)
  const joined = head && tail ? `${head} ${tail}` : head || tail
  return joined.slice(0, maxLength)
}

export type SpeechErrorKind = 'permission' | 'no-microphone' | 'no-speech' | 'network' | 'language' | 'failed'

export interface SpeechError {
  kind: SpeechErrorKind
  message: string
}

const MESSAGES: Record<SpeechErrorKind, string> = {
  permission:
    'Microphone access is blocked. Allow the microphone for this site in your browser settings, or type the issue.',
  'no-microphone': 'No microphone was found. Check that one is connected and not in use by another app.',
  'no-speech': 'No speech was detected. Press Record issue and speak clearly, close to the device.',
  network: 'Voice input needs an internet connection in this browser. Check the connection or type the issue.',
  language: 'Voice input is not available for this language in this browser. Type the issue instead.',
  failed: 'Voice input stopped unexpectedly. Try again or type the issue.',
}

/** Maps a SpeechRecognitionErrorEvent.error code to a worker-facing error. */
export function speechErrorFrom(code: string): SpeechError {
  const kind: SpeechErrorKind =
    code === 'not-allowed' || code === 'service-not-allowed'
      ? 'permission'
      : code === 'audio-capture'
        ? 'no-microphone'
        : code === 'no-speech'
          ? 'no-speech'
          : code === 'network'
            ? 'network'
            : code === 'language-not-supported'
              ? 'language'
              : 'failed'
  return { kind, message: MESSAGES[kind] }
}
