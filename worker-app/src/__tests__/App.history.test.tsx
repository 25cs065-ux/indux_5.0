// @vitest-environment jsdom
// History page through the real App with MOCK responses. These tests do not
// verify the real FastAPI backend or the Supabase repair_history table.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { historyEnvelope, historyRow, jsonResponse } from '../api/__tests__/fixtures.ts'
import App from '../App.tsx'

const fetchMock = vi.fn<typeof fetch>()
let historyHandler: (url: string, init?: RequestInit) => Response | Promise<Response>

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
  fetchMock.mockReset()
  historyHandler = () => jsonResponse(historyEnvelope([historyRow()]))
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input)
    if (url.endsWith('/health')) return jsonResponse({ status: 'ok' })
    if (url.includes('/history/')) return historyHandler(url, init)
    throw new Error(`unexpected request ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('localStorage', memoryStorage())
  vi.stubGlobal('matchMedia', () => ({ matches: false }))
  vi.stubGlobal('scrollTo', () => {})
  Element.prototype.scrollIntoView = () => {}
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

const historyCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).includes('/history/'))

function go(route: string) {
  act(() => {
    window.history.pushState(null, '', `#/${route}`)
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
}

describe('History page', () => {
  it('asks for a machine when none is selected and makes no request', () => {
    window.history.replaceState(null, '', '/#/history')
    render(<App />)
    expect(screen.getAllByText('No machine selected').length).toBeGreaterThan(0)
    const links = screen.getAllByRole('link', { name: 'Select machine' })
    expect(links.length).toBeGreaterThan(0)
    expect(links.every((l) => l.getAttribute('href') === '#/equipment')).toBe(true)
    expect(historyCalls()).toHaveLength(0)
  })

  it('labels the records as historical, not manufacturer instructions', async () => {
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    expect(screen.getByText(/not verified manufacturer instructions/)).toBeTruthy()
    expect(screen.getByText('Site records · Context only')).toBeTruthy()
  })

  it('shows loading, then the returned records with date, problem, action and outcome', async () => {
    let release: (r: Response) => void = () => {}
    historyHandler = (_url, init) =>
      new Promise<Response>((resolve, reject) => {
        release = resolve
        init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      })
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    expect(screen.getByText(/Loading repair records for/)).toBeTruthy()
    expect(String(historyCalls()[0]![0])).toBe('/api/history/compressor-01')

    await act(async () =>
      release(
        jsonResponse(
          historyEnvelope([
            historyRow(),
            historyRow({ id: 'b', problem: 'TEST: Oil under filter', action: 'TEST: Replaced seal', outcome: '', created_at: '2026-02-20T08:00:00Z' }),
          ]),
        ),
      ),
    )

    const log = screen.getByRole('list', { name: 'Repair records for compressor-01' })
    const entries = within(log).getAllByRole('listitem')
    expect(entries).toHaveLength(2)
    expect(within(entries[0]!).getByText('TEST: High temperature warning')).toBeTruthy()
    expect(within(entries[0]!).getByText('TEST: Cleaned cooler fins')).toBeTruthy()
    expect(within(entries[0]!).getByText('TEST: Resolved')).toBeTruthy()
    const time = entries[0]!.querySelector('time')!
    expect(time.getAttribute('dateTime')).toBe('2026-05-06T09:30:00+00:00')
    expect(time.textContent).toMatch(/2026/)
    // Empty outcome is shown as not recorded, never filled in.
    expect(within(entries[1]!).getByText('Not recorded')).toBeTruthy()
    expect(screen.getByText(/2 records · newest first/)).toBeTruthy()
  })

  it('shows only returned records: one row in, one entry out', async () => {
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    await waitFor(() => expect(screen.getByRole('list', { name: /Repair records/ })).toBeTruthy())
    expect(within(screen.getByRole('list', { name: /Repair records/ })).getAllByRole('listitem')).toHaveLength(1)
  })

  it('shows "Date not recorded" when created_at is missing', async () => {
    historyHandler = () => jsonResponse(historyEnvelope([historyRow({ created_at: undefined })]))
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    await waitFor(() => expect(screen.getByText('Date not recorded')).toBeTruthy())
    expect(screen.getByText(/Some returned data was incomplete/)).toBeTruthy()
  })

  it('shows an empty state', async () => {
    historyHandler = () => jsonResponse(historyEnvelope([]))
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    await waitFor(() => expect(screen.getByText('No repair records')).toBeTruthy())
    expect(screen.queryByRole('list', { name: /Repair records/ })).toBeNull()
  })

  it('notes the backend limit when 50 records are returned', async () => {
    historyHandler = () =>
      jsonResponse(historyEnvelope(Array.from({ length: 50 }, (_, i) => historyRow({ id: `r${i}` }))))
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    await waitFor(() => expect(screen.getByText(/showing the 50 most recent/)).toBeTruthy())
  })

  it('shows a 503 error and retries', async () => {
    historyHandler = () => jsonResponse({ detail: 'Could not retrieve repair history.' }, 503)
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    await waitFor(() => expect(screen.getByText('Repair history unavailable')).toBeTruthy())
    expect(screen.getByText('Could not retrieve repair history.')).toBeTruthy()

    historyHandler = () => jsonResponse(historyEnvelope([historyRow()]))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    })
    await waitFor(() => expect(screen.getByRole('list', { name: /Repair records/ })).toBeTruthy())
    expect(historyCalls()).toHaveLength(2)
  })

  it('a network failure marks the server unreachable', async () => {
    historyHandler = () => {
      throw new TypeError('Failed to fetch')
    }
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    await waitFor(() => expect(screen.getByText('Repair history unavailable')).toBeTruthy())
    expect(screen.getByText(/Cannot reach the Indux server/)).toBeTruthy()
    expect(screen.getByLabelText('Server Unreachable')).toBeTruthy()
  })

  it('cancels the request when leaving the History page', () => {
    historyHandler = (_url, init) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      })
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    const signal = historyCalls()[0]![1]?.signal
    go('equipment')
    expect(signal?.aborted).toBe(true)
  })

  it('loads the newly selected machine after changing machines', async () => {
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    await waitFor(() => expect(screen.getByRole('list', { name: 'Repair records for compressor-01' })).toBeTruthy())

    historyHandler = () =>
      jsonResponse(historyEnvelope([historyRow({ id: 'z', machine_id: 'compressor-02', problem: 'TEST: Belt noise' })], 'compressor-02'))
    go('equipment')
    fireEvent.click(screen.getByLabelText(/Compressor #02/))
    go('history')
    await waitFor(() => expect(screen.getByRole('list', { name: 'Repair records for compressor-02' })).toBeTruthy())
    expect(screen.getByText('TEST: Belt noise')).toBeTruthy()
    expect(screen.queryByText('TEST: High temperature warning')).toBeNull()
  })

  it('never writes history (no POST /history)', async () => {
    window.history.replaceState(null, '', '/?machine=compressor-01#/history')
    render(<App />)
    await waitFor(() => expect(screen.getByRole('list', { name: /Repair records/ })).toBeTruthy())
    expect(fetchMock.mock.calls.every(([, init]) => (init?.method ?? 'GET') === 'GET')).toBe(true)
    expect(screen.queryByRole('button', { name: /add|save|record repair/i })).toBeNull()
  })
})
