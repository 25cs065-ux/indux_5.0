// Test-only stand-in for the browser SpeechRecognition object.
import type {
  SpeechRecognitionErrorEventLike,
  SpeechRecognitionEventLike,
  SpeechRecognitionLike,
  SpeechRecognitionResultLike,
} from '../types.ts'

export class FakeRecognition implements SpeechRecognitionLike {
  static instances: FakeRecognition[] = []

  static reset() {
    FakeRecognition.instances = []
  }

  static get last(): FakeRecognition {
    const rec = FakeRecognition.instances[FakeRecognition.instances.length - 1]
    if (!rec) throw new Error('No FakeRecognition created')
    return rec
  }

  lang = ''
  continuous = false
  interimResults = false
  maxAlternatives = 1
  onstart: ((event: Event) => void) | null = null
  onresult: ((event: SpeechRecognitionEventLike) => void) | null = null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null = null
  onend: ((event: Event) => void) | null = null

  startCalls = 0
  stopCalls = 0
  abortCalls = 0
  /** Set to make start() throw, like a browser refusing to start. */
  throwOnStart = false

  constructor() {
    FakeRecognition.instances.push(this)
  }

  start() {
    this.startCalls += 1
    if (this.throwOnStart || this.startCalls > 1) throw new DOMException('already started', 'InvalidStateError')
  }

  stop() {
    this.stopCalls += 1
  }

  abort() {
    this.abortCalls += 1
  }

  // ---- event helpers ----

  emitStart() {
    this.onstart?.(new Event('start'))
  }

  /** results: [transcript, isFinal] pairs for the whole session so far. */
  emitResult(resultIndex: number, results: Array<[string, boolean]>) {
    const list = results.map(([transcript, isFinal]) => {
      const r: SpeechRecognitionResultLike = { isFinal, length: 1, 0: { transcript } }
      return r
    })
    const event: SpeechRecognitionEventLike = {
      resultIndex,
      results: Object.assign([...list], { length: list.length }),
    }
    this.onresult?.(event)
  }

  emitError(error: string) {
    this.onerror?.({ error })
  }

  emitEnd() {
    this.onend?.(new Event('end'))
  }
}
