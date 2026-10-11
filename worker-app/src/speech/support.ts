import type { SpeechRecognitionConstructor } from './types.ts'

/** Recognition language. en-IN copes best with Indian English and Hinglish. */
export const SPEECH_LANG = 'en-IN'

export type SpeechSupport =
  | { status: 'supported' }
  | { status: 'unsupported'; message: string }
  | { status: 'insecure'; message: string }

interface SpeechWindow {
  SpeechRecognition?: SpeechRecognitionConstructor
  webkitSpeechRecognition?: SpeechRecognitionConstructor
  isSecureContext?: boolean
}

export function getRecognitionCtor(win: unknown): SpeechRecognitionConstructor | null {
  const w = win as SpeechWindow
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

/** Checks support without touching the microphone or asking for permission. */
export function speechSupport(win: unknown): SpeechSupport {
  if (!getRecognitionCtor(win)) {
    return {
      status: 'unsupported',
      message: 'Voice input is not supported in this browser. Use Chrome or Edge, or type the issue.',
    }
  }
  if ((win as SpeechWindow).isSecureContext === false) {
    return {
      status: 'insecure',
      message: 'Voice input needs a secure (HTTPS) connection. Type the issue, or open the app over HTTPS.',
    }
  }
  return { status: 'supported' }
}
