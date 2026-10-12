// @vitest-environment jsdom
// Regression: latest main (ai/schemas.py @ 0eaa11f) returns the new-format
// statuses together with is_dangerous / history_note. A SUCCESS with an
// explicit is_dangerous: false, an empty checklist and valid steps must NOT
// reveal or read aloud actionable steps until the safety policy is confirmed.
// All responses here are MOCKS shaped like main's brain.py output.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  envelope,
  jsonResponse,
  mainNotFoundAnswer,
  mainSafetyAlertAnswer,
  mainSuccessAnswer,
  okAnswer,
} from '../api/__tests__/fixtures.ts'
import { parseAskResponse } from '../api/parse.ts'
import type { AskResult } from '../api/types.ts'
import App from '../App.tsx'
import ResultView from '../components/result/ResultView.tsx'
import { CURRENT_FORMAT_EMPTY_CHECKLIST_MEANS_NOT_FLAGGED, safetyStateOf, stepsGateOf } from '../lib/safety.ts'
import { buildReadAloudScript } from '../speech/readAloud.ts'
import { FakeRecognition } from '../speech/__tests__/fakeRecognition.ts'
import { FakeSynthesis, FakeUtterance } from '../speech/__tests__/fakeSynthesis.ts'

let synth: FakeSynthesis

function fromWire(answer: unknown): AskResult {
  return parseAskResponse(envelope(answer), { question: 'q', machineId: 'compressor-01' })
}

const STEP_1 = 'Inspect intake air filter cartridge for dust accumulation.'
const STEP_2 = 'Clean cartridge with compressed air or replace if saturated.'

beforeEach(() => {
  synth = new FakeSynthesis()
  vi.stubGlobal('speechSynthesis', synth)
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

describe('latest-main SUCCESS with is_dangerous: false, empty checklist, valid steps', () => {
  it('is parsed with its steps intact (nothing discarded)', () => {
    const { answer, issues } = fromWire(mainSuccessAnswer())
    expect(answer.rawStatus).toBe('SUCCESS')
    expect(answer.isDangerous).toBe(false)
    expect(answer.safetyChecklist).toEqual([])
    expect(answer.steps.map((s) => s.instruction)).toEqual([STEP_1, STEP_2])
    expect(issues).toEqual([])
  })

  it('is an unverified safety state with steps withheld', () => {
    expect(CURRENT_FORMAT_EMPTY_CHECKLIST_MEANS_NOT_FLAGGED).toBe(false)
    const { answer } = fromWire(mainSuccessAnswer())
    expect(safetyStateOf(answer)).toBe('uncertain')
    expect(stepsGateOf(answer)).toBe('withheld')
  })

  it.each([['SUCCESS'], ['success'], [' Success ']])('status %j is treated the same way', (status) => {
    const { answer } = fromWire({ ...mainSuccessAnswer(), status })
    expect(stepsGateOf(answer)).toBe('withheld')
  })

  it('does not show the steps on screen, and offers no way to reveal them', () => {
    render(<ResultView result={fromWire(mainSuccessAnswer())} />)
    expect(screen.queryByRole('list', { name: 'Troubleshooting steps' })).toBeNull()
    expect(screen.queryByText(STEP_1)).toBeNull()
    expect(screen.queryByText(STEP_2)).toBeNull()
    expect(screen.getByText('Withheld · 2 steps')).toBeTruthy()
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    expect(screen.queryAllByRole('button').map((b) => b.textContent?.trim())).toEqual(['Read aloud', 'Stop speaking'])
    // Never presented as "no hazard flagged".
    expect(screen.queryByText(/No hazard flagged/)).toBeNull()
    expect(screen.getByText('Safety status could not be determined')).toBeTruthy()
    expect(screen.getByText(/does not give a verified safety status/)).toBeTruthy()
  })

  it('keeps the summary and references visible', () => {
    render(<ResultView result={fromWire(mainSuccessAnswer())} />)
    expect(screen.getByText('Intake air filter is clogged causing insufficient pressure build-up.')).toBeTruthy()
    expect(screen.getByText('GA15-26_Instruction_Book')).toBeTruthy()
    expect(screen.getByText('p. 8')).toBeTruthy()
    expect(screen.getByText('Section: Pressure System')).toBeTruthy()
  })

  it('keeps an escalation notice visible', () => {
    render(<ResultView result={fromWire({ ...mainSuccessAnswer(), escalate: true })} />)
    expect(screen.getByText('Escalation recommended')).toBeTruthy()
    expect(screen.queryByRole('list', { name: 'Troubleshooting steps' })).toBeNull()
  })

  it('does not read the steps aloud (script and real button)', () => {
    const script = buildReadAloudScript(fromWire(mainSuccessAnswer()), { stepsVisible: true }).join(' ')
    expect(script).not.toContain(STEP_1)
    expect(script).not.toContain('Step 1.')
    expect(script).not.toContain('No hazard was flagged')
    expect(script).toContain('2 troubleshooting steps are withheld because the safety status is unknown.')

    render(<ResultView result={fromWire(mainSuccessAnswer())} />)
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    const spoken = synth.texts.join(' ')
    expect(spoken).not.toContain(STEP_1)
    expect(spoken).not.toContain(STEP_2)
  })

  it('a non-empty checklist with is_dangerous: false is also withheld (no acknowledgement unlock)', () => {
    const { answer } = fromWire({ ...mainSuccessAnswer(), safety_checklist: ['Release pressure'] })
    expect(stepsGateOf(answer)).toBe('withheld')
    render(<ResultView result={fromWire({ ...mainSuccessAnswer(), safety_checklist: ['Release pressure'] })} />)
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
  })

  it('is withheld through the full app (POST /ask -> render -> read aloud)', async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) =>
      String(input).endsWith('/health') ? jsonResponse({ status: 'ok' }) : jsonResponse(envelope(mainSuccessAnswer())),
    )
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {} })
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('matchMedia', () => ({ matches: false }))
    vi.stubGlobal('scrollTo', () => {})
    Element.prototype.scrollIntoView = () => {}
    window.history.replaceState(null, '', '/?machine=compressor-01#/diagnose')

    render(<App />)
    fireEvent.change(screen.getByLabelText('Describe the issue'), { target: { value: 'Pressure is low' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Diagnose' }))
    })
    expect(screen.getByText('Withheld · 2 steps')).toBeTruthy()
    expect(screen.queryByText(STEP_1)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
    expect(synth.texts.join(' ')).not.toContain(STEP_1)
  })
})

describe('protections that must stay unchanged', () => {
  it('latest-main SAFETY_ALERT (is_dangerous: true) stays an alert with steps withheld', () => {
    const { answer } = fromWire(mainSafetyAlertAnswer())
    expect(safetyStateOf(answer)).toBe('alert')
    expect(stepsGateOf(answer)).toBe('withheld_safety_alert')
  })

  it('latest-main NOT_FOUND escalates with no steps', () => {
    render(<ResultView result={fromWire(mainNotFoundAnswer())} />)
    expect(screen.getByRole('heading', { name: 'No verified manual guidance found' })).toBeTruthy()
    expect(screen.getByText('Escalation required')).toBeTruthy()
    expect(screen.queryByRole('list', { name: 'Troubleshooting steps' })).toBeNull()
  })

  it('latest-main SUCCESS with is_dangerous: true and a checklist still requires acknowledgement', () => {
    const answer = { ...mainSuccessAnswer(), is_dangerous: true, safety_checklist: ['Stop the compressor'] }
    render(<ResultView result={fromWire(answer)} />)
    expect(screen.queryByRole('list', { name: 'Troubleshooting steps' })).toBeNull()
    fireEvent.click(screen.getByRole('checkbox'))
    expect(screen.getByRole('list', { name: 'Troubleshooting steps' })).toBeTruthy()
  })

  it('legacy OK with is_dangerous: false and an empty checklist still shows steps', () => {
    render(<ResultView result={fromWire(okAnswer())} />)
    const list = screen.getByRole('list', { name: 'Troubleshooting steps' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(1)
    expect(screen.getByText('This is not a safety clearance.')).toBeTruthy()
  })

  it('legacy OK with is_dangerous: false and a checklist still requires acknowledgement', () => {
    render(<ResultView result={fromWire({ ...okAnswer(), safety_checklist: ['Isolate power'] })} />)
    expect(screen.getAllByRole('checkbox')).toHaveLength(1)
  })
})
