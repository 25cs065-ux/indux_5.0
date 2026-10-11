// @vitest-environment jsdom
// End-to-end worker workflow through the real App, with the network, the
// microphone and the speech engine replaced by test doubles.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { envelope, jsonResponse, okAnswer, safetyAlertAnswer, successAnswer } from '../api/__tests__/fixtures.ts'
import App from '../App.tsx'
import { FakeRecognition } from '../speech/__tests__/fakeRecognition.ts'
import { FakeSynthesis, FakeUtterance } from '../speech/__tests__/fakeSynthesis.ts'

const fetchMock = vi.fn<typeof fetch>()
let synth: FakeSynthesis
let healthOk = true
let askResponses: Array<(init?: RequestInit) => Response | Promise<Response>> = []

/** A response released manually; rejects on abort like a real fetch. */
function pending(init: RequestInit | undefined, onRelease: (release: (r: Response) => void) => void) {
  return new Promise<Response>((resolve, reject) => {
    onRelease(resolve)
    init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  })
}

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
  healthOk = true
  askResponses = []
  fetchMock.mockImplementation(async (input, init) => {
    if (String(input).endsWith('/health')) {
      if (!healthOk) throw new TypeError('Failed to fetch')
      return jsonResponse({ status: 'ok' })
    }
    const next = askResponses.shift()
    return next ? next(init) : jsonResponse(envelope(okAnswer()))
  })
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('localStorage', memoryStorage())
  vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
  vi.stubGlobal('isSecureContext', true)
  synth = new FakeSynthesis()
  vi.stubGlobal('speechSynthesis', synth)
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
  vi.stubGlobal('matchMedia', () => ({ matches: false }))
  vi.stubGlobal('scrollTo', () => {})
  Element.prototype.scrollIntoView = () => {}
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

const textarea = () => screen.getByLabelText('Describe the issue') as HTMLTextAreaElement
const askCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/ask'))
const askBody = (i: number) => JSON.parse(askCalls()[i]![1]?.body as string)

async function clickDiagnose() {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Diagnose' }))
  })
}

function followHash() {
  act(() => void window.dispatchEvent(new HashChangeEvent('hashchange')))
}

describe('complete worker workflow', () => {
  it('Equipment -> Diagnose -> record -> edit -> Diagnose -> answer -> read aloud -> New question', async () => {
    render(<App />)

    // 1-2. Select a machine and start diagnosis.
    fireEvent.click(screen.getByLabelText(/Compressor #02/))
    fireEvent.click(screen.getByRole('button', { name: /Start diagnosis/ }))
    followHash()
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Diagnose')

    // 3-4. Record; interim then final text; nothing is submitted.
    fireEvent.click(screen.getByRole('button', { name: 'Record issue' }))
    const rec = FakeRecognition.last
    act(() => rec.emitStart())
    act(() => rec.emitResult(0, [['compressor is', false]]))
    expect(screen.getByText('compressor is')).toBeTruthy()
    act(() => rec.emitResult(0, [['compressor is overheating', true]]))
    fireEvent.click(screen.getByRole('button', { name: 'Stop recording' }))
    act(() => rec.emitEnd())
    expect(askCalls()).toHaveLength(0)

    // Edit the recognised text.
    fireEvent.change(textarea(), { target: { value: 'compressor is overheating near the cooler' } })

    // 5-6. Submit through /ask with the machine ID exactly as selected.
    await clickDiagnose()
    expect(askCalls()).toHaveLength(1)
    expect(askBody(0)).toEqual({ question: 'compressor is overheating near the cooler', machine_id: 'compressor-02' })

    // 7. The answer renders.
    expect(screen.getByText('Check the cooler and oil level.')).toBeTruthy()
    expect(screen.getByRole('list', { name: 'Troubleshooting steps' })).toBeTruthy()

    // 8. Read aloud and stop.
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    expect(synth.texts.join(' ')).toContain('Summary. Check the cooler and oil level.')
    fireEvent.click(screen.getByRole('button', { name: 'Stop speaking' }))
    expect(screen.queryByText('Speaking')).toBeNull()

    // 9. New question keeps the machine and clears the rest.
    fireEvent.click(screen.getByRole('button', { name: /New question/ }))
    expect(textarea().value).toBe('')
    expect(screen.getByText('Awaiting diagnosis')).toBeTruthy()
    expect(screen.getByText('compressor-02', { selector: '.machine-bar-id' })).toBeTruthy()
    expect(document.activeElement).toBe(textarea())
    expect(askCalls()).toHaveLength(1)
  })
})

describe('New question', () => {
  beforeEach(() => window.history.replaceState(null, '', '/?machine=compressor-01#/diagnose'))

  it('is hidden until there is something to clear', () => {
    render(<App />)
    expect(screen.queryByRole('button', { name: /New question/ })).toBeNull()
    fireEvent.change(textarea(), { target: { value: 'typed text' } })
    expect(screen.getByRole('button', { name: /New question/ })).toBeTruthy()
  })

  it('clears typed text without sending anything', () => {
    render(<App />)
    fireEvent.change(textarea(), { target: { value: 'typed text' } })
    fireEvent.click(screen.getByRole('button', { name: /New question/ }))
    expect(textarea().value).toBe('')
    expect(askCalls()).toHaveLength(0)
  })

  it('stops speech playback', async () => {
    render(<App />)
    fireEvent.change(textarea(), { target: { value: 'Compressor is overheating' } })
    await clickDiagnose()
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    const before = synth.cancelCalls
    fireEvent.click(screen.getByRole('button', { name: /New question/ }))
    expect(synth.cancelCalls).toBeGreaterThan(before)
    expect(screen.queryByText('Speaking')).toBeNull()
  })

  it('stops recording and later dictation starts from an empty field', () => {
    render(<App />)
    fireEvent.change(textarea(), { target: { value: 'old text' } })
    fireEvent.click(screen.getByRole('button', { name: 'Record issue' }))
    const first = FakeRecognition.last
    act(() => first.emitStart())
    fireEvent.click(screen.getByRole('button', { name: /New question/ }))
    expect(first.abortCalls).toBe(1)
    expect(textarea().value).toBe('')

    // Late events from the old session are ignored.
    act(() => first.emitResult(0, [['late words', true]]))
    expect(textarea().value).toBe('')

    fireEvent.click(screen.getByRole('button', { name: 'Record issue' }))
    act(() => FakeRecognition.last.emitResult(0, [['new words', true]]))
    expect(textarea().value).toBe('new words')
  })

  it('resets safety acknowledgements for the next diagnosis', async () => {
    const dangerous = { ...okAnswer(), is_dangerous: true, safety_checklist: ['Stop the compressor'] }
    askResponses = [() => jsonResponse(envelope(dangerous)), () => jsonResponse(envelope(dangerous))]
    render(<App />)
    fireEvent.change(textarea(), { target: { value: 'Compressor is hot' } })
    await clickDiagnose()
    fireEvent.click(screen.getByRole('checkbox'))
    expect(screen.getByRole('list', { name: 'Troubleshooting steps' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /New question/ }))
    fireEvent.change(textarea(), { target: { value: 'Compressor is hot again' } })
    await clickDiagnose()
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false)
    expect(screen.queryByRole('list', { name: 'Troubleshooting steps' })).toBeNull()
  })

  it('Cancel stops a request in flight and ignores its late response', async () => {
    let release: (r: Response) => void = () => {}
    askResponses = [(init) => pending(init, (r) => (release = r))]
    render(<App />)
    fireEvent.change(textarea(), { target: { value: 'Compressor is hot' } })
    await clickDiagnose()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy()
    // While loading, Cancel is the control; New question appears again after.
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.getByText('Awaiting diagnosis')).toBeTruthy())
    await act(async () => release(jsonResponse(envelope(okAnswer()))))
    expect(screen.getByText('Awaiting diagnosis')).toBeTruthy()
  })
})

describe('Retry', () => {
  beforeEach(() => window.history.replaceState(null, '', '/?machine=compressor-01#/diagnose'))

  it('retries a failed request once, even if Retry is clicked twice', async () => {
    let release: (r: Response) => void = () => {}
    askResponses = [
      () => jsonResponse({ detail: 'The AI or database service is temporarily unavailable.' }, 503),
      (init) => pending(init, (r) => (release = r)),
    ]
    render(<App />)
    fireEvent.change(textarea(), { target: { value: 'Compressor is hot' } })
    await clickDiagnose()
    expect(screen.getByText('Assistant unavailable')).toBeTruthy()

    const retry = screen.getByRole('button', { name: 'Retry' })
    await act(async () => {
      fireEvent.click(retry)
      fireEvent.click(retry)
    })
    expect(askCalls()).toHaveLength(2)
    expect(askBody(1)).toEqual(askBody(0))

    await act(async () => release(jsonResponse(envelope(okAnswer()))))
    expect(screen.getByText('Check the cooler and oil level.')).toBeTruthy()
  })

  it('double-clicking Diagnose sends one request', async () => {
    render(<App />)
    fireEvent.change(textarea(), { target: { value: 'Compressor is hot' } })
    await act(async () => {
      const button = screen.getByRole('button', { name: 'Diagnose' })
      fireEvent.click(button)
      fireEvent.click(button)
    })
    expect(askCalls()).toHaveLength(1)
  })
})

describe('backend unavailable', () => {
  beforeEach(() => window.history.replaceState(null, '', '/?machine=compressor-01#/diagnose'))

  it('shows a clear notice on Diagnose when /health fails, and still allows typing', async () => {
    healthOk = false
    render(<App />)
    await waitFor(() => expect(screen.getByText('Server unreachable')).toBeTruthy())
    expect(screen.getByLabelText('Server Unreachable')).toBeTruthy()
    fireEvent.change(textarea(), { target: { value: 'still typing' } })
    expect(textarea().value).toBe('still typing')
  })

  it('Check again clears the notice once the server answers', async () => {
    healthOk = false
    render(<App />)
    await waitFor(() => expect(screen.getByText('Server unreachable')).toBeTruthy())
    healthOk = true
    fireEvent.click(screen.getByRole('button', { name: 'Check again' }))
    await waitFor(() => expect(screen.queryByText('Server unreachable')).toBeNull())
  })

  it('a network failure on /ask shows the error and the server notice', async () => {
    askResponses = [
      () => {
        throw new TypeError('Failed to fetch')
      },
    ]
    render(<App />)
    await waitFor(() => expect(screen.getByLabelText('Server Online')).toBeTruthy())
    fireEvent.change(textarea(), { target: { value: 'Compressor is hot' } })
    await clickDiagnose()
    expect(screen.getByText('No connection to the server')).toBeTruthy()
    expect(screen.getByText('Server unreachable')).toBeTruthy()
  })

  it('a proxy 502 (backend down) marks the server unreachable', async () => {
    askResponses = [() => new Response('', { status: 502 })]
    render(<App />)
    fireEvent.change(textarea(), { target: { value: 'Compressor is hot' } })
    await clickDiagnose()
    expect(screen.getByText('Server unreachable')).toBeTruthy()
  })

  it('a successful answer clears the notice', async () => {
    healthOk = false
    render(<App />)
    await waitFor(() => expect(screen.getByText('Server unreachable')).toBeTruthy())
    fireEvent.change(textarea(), { target: { value: 'Compressor is hot' } })
    await clickDiagnose()
    expect(screen.queryByText('Server unreachable')).toBeNull()
  })
})

describe('safe rendering through the full app', () => {
  beforeEach(() => window.history.replaceState(null, '', '/?machine=compressor-01#/diagnose'))

  it.each([
    ['SUCCESS', successAnswer, 'Safety status could not be determined'],
    ['SAFETY_ALERT', safetyAlertAnswer, 'Safety alert. Escalation required.'],
  ])('%s never reveals steps on screen or in read-aloud', async (_label, make, heading) => {
    askResponses = [() => jsonResponse(envelope(make()))]
    render(<App />)
    fireEvent.change(textarea(), { target: { value: 'Pressure is low' } })
    await clickDiagnose()
    expect(screen.getByText(heading)).toBeTruthy()
    expect(screen.queryByRole('list', { name: 'Troubleshooting steps' })).toBeNull()
    expect(screen.queryByText(/Inspect intake air filter/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    expect(synth.texts.join(' ')).not.toContain('Inspect intake air filter')
  })
})
