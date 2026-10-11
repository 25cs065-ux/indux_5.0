// Test-only stand-ins for window.speechSynthesis and SpeechSynthesisUtterance.

export class FakeUtterance {
  text: string
  lang = ''
  rate = 1
  voice: unknown = null
  onend: ((event: Event) => void) | null = null
  onerror: ((event: { error: string }) => void) | null = null

  constructor(text: string) {
    this.text = text
  }
}

export class FakeSynthesis {
  queue: FakeUtterance[] = []
  spoken: FakeUtterance[] = []
  cancelCalls = 0
  voices: Array<{ lang: string; name: string }> = []

  speak(u: FakeUtterance) {
    this.queue.push(u)
    this.spoken.push(u)
  }

  cancel() {
    this.cancelCalls += 1
    this.queue = []
  }

  getVoices() {
    return this.voices
  }

  /** Finishes the current utterance, firing its end event. */
  finishNext() {
    const u = this.queue.shift()
    u?.onend?.(new Event('end'))
  }

  finishAll() {
    while (this.queue.length) this.finishNext()
  }

  failNext(error: string) {
    const u = this.queue[0]
    u?.onerror?.({ error })
  }

  get texts() {
    return this.spoken.map((u) => u.text)
  }
}
