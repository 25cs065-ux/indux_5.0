// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { envelope, jsonResponse, okAnswer } from '../api/__tests__/fixtures.ts'
import App from '../App.tsx'
import { FakeRecognition } from '../speech/__tests__/fakeRecognition.ts'
import { FakeSynthesis, FakeUtterance } from '../speech/__tests__/fakeSynthesis.ts'

const fetchMock = vi.fn<typeof fetch>()
let synth: FakeSynthesis

function memoryStorage(): Storage {
  const data = new Map<string, string>()
  return {
    get length() {
      return data.size
    },
    clear: () => data.clear(),
    getItem: (k) => data.get(k) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (k) => void data.delete(k),
    setItem: (k, v) => void data.set(k, String(v)),
  }
}

beforeEach(() => {
  FakeRecognition.reset()
  fetchMock.mockReset()
  // /health is called on mount; answer it so the header settles.
  fetchMock.mockImplementation(async (input) =>
    String(input).endsWith('/health') ? jsonResponse({ status: 'ok' }) : jsonResponse(envelope(okAnswer())),
  )
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('localStorage', memoryStorage())
  vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
  vi.stubGlobal('isSecureContext', true)
  synth = new FakeSynthesis()
  vi.stubGlobal('speechSynthesis', synth)
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
  vi.stubGlobal('matchMedia', () => ({ matches: false }))
  Element.prototype.scrollIntoView = () => {}
  window.history.replaceState(null, '', '/?machine=compressor-01')
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const textarea = () => screen.getByLabelText('Describe the issue') as HTMLTextAreaElement
const recordButton = () => screen.getByRole('button', { name: /Record issue|Stop recording|Starting microphone|Finishing/ })
const askCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/ask'))

function startListening() {
  fireEvent.click(screen.getByRole('button', { name: 'Record issue' }))
  act(() => FakeRecognition.last.emitStart())
}

describe('App voice input', () => {
  it('does not create a recognizer on page load', () => {
    render(<App />)
    expect(FakeRecognition.instances).toHaveLength(0)
    expect(screen.getByRole('button', { name: 'Record issue' })).toBeTruthy()
  })

  it('is a native, keyboard-focusable button with an accessible name', () => {
    render(<App />)
    const button = screen.getByRole('button', { name: 'Record issue' }) as HTMLButtonElement
    expect(button.tagName).toBe('BUTTON')
    expect(button.type).toBe('button')
    expect(button.disabled).toBe(false)
    button.focus()
    expect(document.activeElement).toBe(button)
    expect(button.getAttribute('aria-describedby')).toBeTruthy()
  })

  it('shows LISTENING and a Stop recording control while recording', () => {
    render(<App />)
    startListening()
    expect(screen.getByRole('status', { name: '' }).textContent).toMatch(/Listening/i)
    expect(screen.getByRole('button', { name: 'Stop recording' })).toBeTruthy()
    expect(textarea().readOnly).toBe(true)
  })

  it('shows interim text and puts final text in the editable field', () => {
    render(<App />)
    startListening()
    act(() => FakeRecognition.last.emitResult(0, [['compressor is', false]]))
    expect(screen.getByText('compressor is')).toBeTruthy()
    expect(textarea().value).toBe('')

    act(() => FakeRecognition.last.emitResult(0, [['compressor is overheating', true]]))
    expect(textarea().value).toBe('compressor is overheating')
  })

  it('does not duplicate the question on repeated recognition events', () => {
    render(<App />)
    startListening()
    const rec = FakeRecognition.last
    act(() => rec.emitResult(0, [['oil is leaking', true]]))
    act(() => rec.emitResult(0, [['oil is leaking', true]]))
    act(() => rec.emitResult(1, [['oil is leaking', true], ['oil is leaking', true]]))
    expect(textarea().value).toBe('oil is leaking')
  })

  it('appends dictation to text typed before recording', () => {
    render(<App />)
    fireEvent.change(textarea(), { target: { value: 'Alarm E12.' } })
    startListening()
    act(() => FakeRecognition.last.emitResult(0, [['compressor stopped', true]]))
    expect(textarea().value).toBe('Alarm E12. compressor stopped')
  })

  it('stops on Stop recording, then lets the worker edit before submitting', () => {
    render(<App />)
    startListening()
    const rec = FakeRecognition.last
    act(() => rec.emitResult(0, [['belt is squeaking', true]]))
    fireEvent.click(screen.getByRole('button', { name: 'Stop recording' }))
    expect(rec.stopCalls).toBe(1)
    act(() => rec.emitEnd())

    expect(screen.getByRole('button', { name: 'Record issue' })).toBeTruthy()
    expect(textarea().readOnly).toBe(false)
    fireEvent.change(textarea(), { target: { value: 'belt is squeaking at start-up' } })
    expect(textarea().value).toBe('belt is squeaking at start-up')
  })

  it('never submits automatically after recording', () => {
    render(<App />)
    startListening()
    const rec = FakeRecognition.last
    act(() => rec.emitResult(0, [['compressor is overheating', true]]))
    fireEvent.click(screen.getByRole('button', { name: 'Stop recording' }))
    act(() => rec.emitEnd())
    expect(askCalls()).toHaveLength(0)
  })

  it('stops recording when Diagnose is pressed and submits the recognised text', async () => {
    render(<App />)
    startListening()
    const rec = FakeRecognition.last
    act(() => rec.emitResult(0, [['pressure is low', true], ['and', false]]))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Diagnose' }))
    })
    expect(rec.abortCalls).toBe(1)
    expect(askCalls()).toHaveLength(1)
    expect(JSON.parse(askCalls()[0]![1]?.body as string).question).toBe('pressure is low')

    // Late events after the abort must not change the question.
    act(() => rec.emitResult(0, [['pressure is low and rising', true]]))
    expect(textarea().value).toBe('pressure is low')
  })

  it('shows a permission error and returns to idle', () => {
    render(<App />)
    startListening()
    act(() => FakeRecognition.last.emitError('not-allowed'))
    act(() => FakeRecognition.last.emitEnd())
    expect(screen.getByRole('alert').textContent).toMatch(/Microphone access is blocked/)
    expect(screen.getByRole('button', { name: 'Record issue' })).toBeTruthy()
  })

  it('shows a no-microphone error', () => {
    render(<App />)
    startListening()
    act(() => FakeRecognition.last.emitError('audio-capture'))
    act(() => FakeRecognition.last.emitEnd())
    expect(screen.getByRole('alert').textContent).toMatch(/No microphone was found/)
  })

  it('shows a no-speech message', () => {
    render(<App />)
    startListening()
    act(() => FakeRecognition.last.emitError('no-speech'))
    act(() => FakeRecognition.last.emitEnd())
    expect(screen.getByRole('alert').textContent).toMatch(/No speech was detected/)
  })

  it('ignores repeated clicks while the microphone is starting', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Record issue' }))
    // Second click during "Starting" acts as stop, never as a second start.
    fireEvent.click(recordButton())
    expect(FakeRecognition.instances).toHaveLength(1)
    expect(FakeRecognition.last.startCalls).toBe(1)
  })

  it('disables Record issue with an explanation in unsupported browsers', () => {
    vi.stubGlobal('webkitSpeechRecognition', undefined)
    render(<App />)
    const button = screen.getByRole('button', { name: /Record issue/ }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(screen.getByText(/not supported in this browser/)).toBeTruthy()
  })

  it('disables Record issue over plain HTTP', () => {
    vi.stubGlobal('isSecureContext', false)
    render(<App />)
    expect((screen.getByRole('button', { name: /Record issue/ }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText(/needs a secure \(HTTPS\) connection/)).toBeTruthy()
  })

  it('aborts recognition when the app unmounts', () => {
    const { unmount } = render(<App />)
    startListening()
    const rec = FakeRecognition.last
    unmount()
    expect(rec.abortCalls).toBe(1)
  })
})

describe('App read aloud coordination', () => {
  async function diagnose(text: string) {
    fireEvent.change(textarea(), { target: { value: text } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Diagnose' }))
    })
  }

  it('stops reading aloud when recording starts, so the mic does not hear it', async () => {
    render(<App />)
    await diagnose('Compressor is overheating')
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    expect(screen.getByText('Speaking')).toBeTruthy()

    const before = synth.cancelCalls
    fireEvent.click(screen.getByRole('button', { name: 'Record issue' }))
    expect(synth.cancelCalls).toBeGreaterThan(before)
    expect(screen.queryByText('Speaking')).toBeNull()
  })

  it('stops reading aloud when a new diagnosis starts', async () => {
    render(<App />)
    await diagnose('Compressor is overheating')
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    const before = synth.cancelCalls
    await diagnose('Pressure is low')
    expect(synth.cancelCalls).toBeGreaterThan(before)
    expect(screen.queryByText('Speaking')).toBeNull()
  })
})
