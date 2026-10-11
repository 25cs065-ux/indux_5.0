// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { envelope, jsonResponse, okAnswer, successAnswer } from '../api/__tests__/fixtures.ts'
import App from '../App.tsx'
import { FakeRecognition } from '../speech/__tests__/fakeRecognition.ts'
import { FakeSynthesis, FakeUtterance } from '../speech/__tests__/fakeSynthesis.ts'

const fetchMock = vi.fn<typeof fetch>()
let synth: FakeSynthesis
let askBody: unknown = envelope(okAnswer())

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

function setUrl(url: string) {
  window.history.replaceState(null, '', url)
}

/** Navigates like a nav link click does, and lets the router react. */
function go(route: string) {
  act(() => {
    window.history.pushState(null, '', `#/${route}`)
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
}

beforeEach(() => {
  FakeRecognition.reset()
  fetchMock.mockReset()
  askBody = envelope(okAnswer())
  fetchMock.mockImplementation(async (input) =>
    String(input).endsWith('/health') ? jsonResponse({ status: 'ok' }) : jsonResponse(askBody),
  )
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
  setUrl('/')
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  setUrl('/')
})

const pageHeading = () => screen.getByRole('heading', { level: 1 })
const topNav = () => screen.getByRole('navigation', { name: 'Main' })
const bottomNav = () => screen.getByRole('navigation', { name: 'Main (bottom)' })
const askCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/ask'))

async function diagnose(text: string) {
  fireEvent.change(screen.getByLabelText('Describe the issue'), { target: { value: text } })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Diagnose' }))
  })
}

describe('navigation', () => {
  it('opens on Equipment by default', () => {
    render(<App />)
    expect(pageHeading().textContent).toBe('Equipment')
    expect(document.title).toBe('Equipment · INDUX Field Assistant')
  })

  it('has top and bottom navigation with the active page marked', () => {
    setUrl('/#/diagnose')
    render(<App />)
    for (const nav of [topNav(), bottomNav()]) {
      const links = within(nav).getAllByRole('link')
      expect(links.map((l) => l.textContent)).toEqual(['01Equipment', '02Diagnose', '03History'])
      expect(within(nav).getByRole('link', { name: /Diagnose/ }).getAttribute('aria-current')).toBe('page')
      expect(within(nav).getByRole('link', { name: /Equipment/ }).getAttribute('aria-current')).toBeNull()
    }
  })

  it('nav links point at hash routes', () => {
    render(<App />)
    const hrefs = within(topNav())
      .getAllByRole('link')
      .map((l) => l.getAttribute('href'))
    expect(hrefs).toEqual(['#/equipment', '#/diagnose', '#/history'])
  })

  it('switches pages on hash change and focuses the new heading', () => {
    render(<App />)
    go('diagnose')
    expect(pageHeading().textContent).toBe('Diagnose')
    expect(document.activeElement).toBe(pageHeading())
    go('history')
    expect(pageHeading().textContent).toBe('Repair history')
    go('equipment')
    expect(pageHeading().textContent).toBe('Equipment')
  })

  it('opens the requested page from a direct link', () => {
    setUrl('/#/history')
    render(<App />)
    expect(pageHeading().textContent).toBe('Repair history')
  })

  it('falls back to Equipment for unknown routes', () => {
    setUrl('/#/dashboard')
    render(<App />)
    expect(pageHeading().textContent).toBe('Equipment')
  })
})

describe('Equipment page', () => {
  it('lists the machines from the site machine list', () => {
    render(<App />)
    expect(screen.getByText('Compressor #01')).toBeTruthy()
    expect(screen.getByText('Compressor #02')).toBeTruthy()
    expect(screen.getByText('No machine selected')).toBeTruthy()
  })

  it('shows only recorded details for a selected machine', () => {
    render(<App />)
    fireEvent.click(screen.getByLabelText(/Compressor #02/))
    const details = screen.getByText('Source: site machine list').closest('.details') as HTMLElement
    expect(within(details).getByText('compressor-02')).toBeTruthy()
    expect(within(details).getByText('Compressor #02')).toBeTruthy()
    expect(within(details).getByText('Atlas Copco GA 22')).toBeTruthy()
    expect(within(details).getByText('Plant Room A')).toBeTruthy()
    // No invented status, health or readings.
    expect(details.textContent).not.toMatch(/status|health|online|running|hours|temperature|pressure|%/i)
  })

  it('preselects the machine from a QR link and labels it', () => {
    setUrl('/?machine=compressor-02')
    render(<App />)
    expect((screen.getByLabelText(/Compressor #02/) as HTMLInputElement).checked).toBe(true)
    expect(screen.getByText('Selected from QR code')).toBeTruthy()
  })

  it('keeps an unlisted QR machine ID exactly and says no details are available', () => {
    setUrl('/?machine=Compressor_09')
    render(<App />)
    expect((screen.getByLabelText('Machine ID') as HTMLInputElement).value).toBe('Compressor_09')
    expect(screen.getByText(/not in the site machine list/)).toBeTruthy()
    expect(screen.getByText('Selected from QR code')).toBeTruthy()
  })

  it('removes the QR label when another machine is chosen', () => {
    setUrl('/?machine=compressor-02')
    render(<App />)
    fireEvent.click(screen.getByLabelText(/Compressor #01/))
    expect(screen.queryByText('Selected from QR code')).toBeNull()
  })

  it('Start diagnosis requires a machine', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: /Start diagnosis/ }))
    expect(screen.getByRole('alert').textContent).toBe('Select or enter a machine ID.')
    expect(pageHeading().textContent).toBe('Equipment')
  })

  it('Start diagnosis opens Diagnose for the selected machine', () => {
    render(<App />)
    fireEvent.click(screen.getByLabelText(/Compressor #01/))
    fireEvent.click(screen.getByRole('button', { name: /Start diagnosis/ }))
    act(() => void window.dispatchEvent(new HashChangeEvent('hashchange')))
    expect(window.location.hash).toBe('#/diagnose')
    expect(pageHeading().textContent).toBe('Diagnose')
    expect(screen.getByText('compressor-01', { selector: '.machine-bar-id' })).toBeTruthy()
  })
})

describe('Diagnose page', () => {
  it('shows the selected machine with a link back to Equipment', () => {
    setUrl('/?machine=compressor-01#/diagnose')
    render(<App />)
    const link = screen.getByRole('link', { name: 'Change' })
    expect(link.getAttribute('href')).toBe('#/equipment')
    expect(screen.getByText('Compressor #01', { selector: '.machine-bar-name' })).toBeTruthy()
  })

  it('prompts for a machine when none is selected and blocks Diagnose', async () => {
    setUrl('/#/diagnose')
    render(<App />)
    expect(screen.getByText('No machine selected')).toBeTruthy()
    await diagnose('Compressor is hot')
    expect(screen.getAllByRole('alert').some((a) => a.textContent === 'Select or enter a machine ID.')).toBe(true)
    expect(askCalls()).toHaveLength(0)
  })
})

describe('state across pages', () => {
  it('keeps the machine, question and diagnosis when leaving and returning', async () => {
    setUrl('/?machine=compressor-01#/diagnose')
    render(<App />)
    await diagnose('Compressor is overheating')
    expect(screen.getByText('Check the cooler and oil level.')).toBeTruthy()

    go('equipment')
    expect((screen.getByLabelText(/Compressor #01/) as HTMLInputElement).checked).toBe(true)
    go('history')
    go('diagnose')

    expect((screen.getByLabelText('Describe the issue') as HTMLTextAreaElement).value).toBe('Compressor is overheating')
    expect(screen.getByText('Check the cooler and oil level.')).toBeTruthy()
    expect(askCalls()).toHaveLength(1)
  })

  it('resets safety acknowledgement when leaving Diagnose', async () => {
    askBody = envelope({ ...okAnswer(), is_dangerous: true, safety_checklist: ['Stop the compressor', 'Release pressure'] })
    setUrl('/?machine=compressor-01#/diagnose')
    render(<App />)
    await diagnose('Compressor is overheating')
    for (const box of screen.getAllByRole('checkbox')) fireEvent.click(box)
    expect(screen.getByRole('list', { name: 'Troubleshooting steps' })).toBeTruthy()

    go('equipment')
    go('diagnose')
    expect(screen.queryByRole('list', { name: 'Troubleshooting steps' })).toBeNull()
    expect(screen.getAllByRole('checkbox').every((b) => !(b as HTMLInputElement).checked)).toBe(true)
  })

  it('stops recording when leaving Diagnose and keeps recognised text', () => {
    setUrl('/?machine=compressor-01#/diagnose')
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Record issue' }))
    const rec = FakeRecognition.last
    act(() => rec.emitStart())
    act(() => rec.emitResult(0, [['oil is leaking', true]]))

    go('equipment')
    expect(rec.abortCalls).toBe(1)
    go('diagnose')
    expect((screen.getByLabelText('Describe the issue') as HTMLTextAreaElement).value).toBe('oil is leaking')
    expect(screen.getByRole('button', { name: 'Record issue' })).toBeTruthy()
  })

  it('stops read-aloud when leaving Diagnose', async () => {
    setUrl('/?machine=compressor-01#/diagnose')
    render(<App />)
    await diagnose('Compressor is overheating')
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    const before = synth.cancelCalls
    go('history')
    expect(synth.cancelCalls).toBeGreaterThan(before)
  })

  it('notes when the shown diagnosis is for a different machine', async () => {
    setUrl('/?machine=compressor-01#/diagnose')
    render(<App />)
    await diagnose('Compressor is overheating')
    go('equipment')
    fireEvent.click(screen.getByLabelText(/Compressor #02/))
    go('diagnose')
    expect(screen.getByText(/This diagnosis is for/).textContent).toContain('compressor-01')
  })

  it('a current-format answer keeps steps withheld across navigation', async () => {
    askBody = envelope(successAnswer())
    setUrl('/?machine=compressor-01#/diagnose')
    render(<App />)
    await diagnose('Pressure is low')
    expect(screen.getByText('Withheld · 2 steps')).toBeTruthy()
    go('equipment')
    go('diagnose')
    expect(screen.getByText('Withheld · 2 steps')).toBeTruthy()
    expect(screen.queryByRole('list', { name: 'Troubleshooting steps' })).toBeNull()
  })
})
