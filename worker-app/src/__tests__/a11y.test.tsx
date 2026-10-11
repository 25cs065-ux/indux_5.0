// @vitest-environment jsdom
// Automated accessibility checks (axe-core) on every page and key state, with
// MOCK responses. Colour contrast is checked in a real browser instead, as
// jsdom cannot compute rendered colours.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import axe from 'axe-core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  currentNotFoundAnswer,
  envelope,
  historyEnvelope,
  historyRow,
  jsonResponse,
  okAnswer,
  parseFailureAnswer,
  safetyAlertAnswer,
  successAnswer,
} from '../api/__tests__/fixtures.ts'
import App from '../App.tsx'
import { FakeRecognition } from '../speech/__tests__/fakeRecognition.ts'
import { FakeSynthesis, FakeUtterance } from '../speech/__tests__/fakeSynthesis.ts'

const fetchMock = vi.fn<typeof fetch>()
let askBody: unknown
let historyBody: () => Response

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

async function expectNoViolations() {
  const results = await axe.run(document.body, {
    rules: { 'color-contrast': { enabled: false } },
    resultTypes: ['violations'],
  })
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`,
  )
  expect(summary).toEqual([])
}

beforeEach(() => {
  FakeRecognition.reset()
  fetchMock.mockReset()
  askBody = envelope(okAnswer())
  historyBody = () => jsonResponse(historyEnvelope([historyRow(), historyRow({ id: 'b', outcome: '' })]))
  fetchMock.mockImplementation(async (input) => {
    const url = String(input)
    if (url.endsWith('/health')) return jsonResponse({ status: 'ok' })
    if (url.includes('/history/')) return historyBody()
    return jsonResponse(askBody)
  })
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('localStorage', memoryStorage())
  vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
  vi.stubGlobal('isSecureContext', true)
  vi.stubGlobal('speechSynthesis', new FakeSynthesis())
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
  vi.stubGlobal('matchMedia', () => ({ matches: false }))
  vi.stubGlobal('scrollTo', () => {})
  Element.prototype.scrollIntoView = () => {}
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

async function diagnoseWith(body: unknown) {
  askBody = body
  window.history.replaceState(null, '', '/?machine=compressor-01#/diagnose')
  render(<App />)
  fireEvent.change(screen.getByLabelText('Describe the issue'), { target: { value: 'Compressor is hot' } })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Diagnose' }))
  })
}

describe('accessibility (axe-core)', () => {
  it('Equipment page, no machine', async () => {
    render(<App />)
    await expectNoViolations()
  })

  it('Equipment page, QR machine selected', async () => {
    window.history.replaceState(null, '', '/?machine=compressor-02')
    render(<App />)
    await expectNoViolations()
  })

  it('Equipment page, unlisted ID and validation error', async () => {
    window.history.replaceState(null, '', '/?machine=Compressor_09')
    render(<App />)
    fireEvent.change(screen.getByLabelText('Machine ID'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /Start diagnosis/ }))
    await expectNoViolations()
  })

  it('Diagnose page, idle with question validation error', async () => {
    window.history.replaceState(null, '', '/?machine=compressor-01#/diagnose')
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Diagnose' }))
    await expectNoViolations()
  })

  it('Diagnose page, listening', async () => {
    window.history.replaceState(null, '', '/?machine=compressor-01#/diagnose')
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Record issue' }))
    act(() => FakeRecognition.last.emitStart())
    act(() => FakeRecognition.last.emitResult(0, [['compressor is', false]]))
    await expectNoViolations()
  })

  it.each([
    ['legacy flagged (checklist to acknowledge)', () => envelope({ ...okAnswer(), is_dangerous: true, safety_checklist: ['Stop'], history_note: 'Cleaned' })],
    ['current SUCCESS (steps withheld)', () => envelope(successAnswer(), { is_demo: true })],
    ['SAFETY_ALERT', () => envelope(safetyAlertAnswer())],
    ['NOT_FOUND', () => envelope(currentNotFoundAnswer())],
    ['internal error', () => envelope(parseFailureAnswer())],
  ])('Diagnose page, %s', async (_label, body) => {
    await diagnoseWith(body())
    await expectNoViolations()
  })

  it('Diagnose page, steps unlocked and reading aloud', async () => {
    await diagnoseWith(envelope({ ...okAnswer(), is_dangerous: true, safety_checklist: ['Stop'] }))
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    expect(screen.getByRole('list', { name: 'Troubleshooting steps' })).toBeTruthy()
    await expectNoViolations()
  })

  it('Diagnose page, backend error with Retry', async () => {
    fetchMock.mockImplementation(async (input) =>
      String(input).endsWith('/health')
        ? jsonResponse({ status: 'ok' })
        : jsonResponse({ detail: 'The AI or database service is temporarily unavailable.' }, 503),
    )
    window.history.replaceState(null, '', '/?machine=compressor-01#/diagnose')
    render(<App />)
    fireEvent.change(screen.getByLabelText('Describe the issue'), { target: { value: 'x' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Diagnose' }))
    })
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
    await expectNoViolations()
  })

  it('Diagnose page, server unreachable notice', async () => {
    fetchMock.mockImplementation(async () => {
      throw new TypeError('Failed to fetch')
    })
    window.history.replaceState(null, '', '/?machine=compressor-01#/diagnose')
    render(<App />)
    await waitFor(() => expect(screen.getByText('Server unreachable')).toBeTruthy())
    await expectNoViolations()
  })

  it('History page, records', async () => {
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    await waitFor(() => expect(screen.getByRole('list', { name: /Repair records/ })).toBeTruthy())
    await expectNoViolations()
  })

  it('History page, empty', async () => {
    historyBody = () => jsonResponse(historyEnvelope([]))
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    await waitFor(() => expect(screen.getByText('No repair records')).toBeTruthy())
    await expectNoViolations()
  })

  it('History page, error', async () => {
    historyBody = () => jsonResponse({ detail: 'Could not retrieve repair history.' }, 503)
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    await waitFor(() => expect(screen.getByText('Repair history unavailable')).toBeTruthy())
    await expectNoViolations()
  })

  it('History page, no machine', async () => {
    window.history.replaceState(null, '', '/#/history')
    render(<App />)
    await expectNoViolations()
  })
})

describe('accessible names of key controls', () => {
  it('the Diagnose button and both navigations have names', () => {
    window.history.replaceState(null, '', '/?machine=compressor-01#/diagnose')
    render(<App />)
    expect(screen.getByRole('button', { name: 'Diagnose' })).toBeTruthy()
    for (const nav of ['Main', 'Main (bottom)']) {
      const region = screen.getByRole('navigation', { name: nav })
      for (const name of ['Equipment', 'Diagnose', 'History']) {
        const links = [...region.querySelectorAll('a')].filter((a) => a.textContent?.includes(name))
        expect(links).toHaveLength(1)
        expect(links[0]!.textContent?.replace(/^\d+/, '')).toBe(name)
      }
    }
  })

  it('there is exactly one h1 per page', () => {
    for (const route of ['equipment', 'diagnose', 'history']) {
      window.history.replaceState(null, '', `/?machine=compressor-01#/${route}`)
      const { unmount } = render(<App />)
      expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
      unmount()
    }
  })
})

describe('axe harness control', () => {
  it('does detect violations in this environment (so passing results are meaningful)', async () => {
    render(
      <div>
        <button type="button" />
        <img src="x.png" />
        <a href="#x" />
      </div>,
    )
    const results = await axe.run(document.body, { resultTypes: ['violations'] })
    const ids = results.violations.map((v) => v.id)
    expect(ids).toEqual(expect.arrayContaining(['button-name', 'image-alt', 'link-name']))
  })
})
