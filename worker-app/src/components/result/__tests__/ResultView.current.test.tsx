// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  currentNotFoundAnswer,
  envelope,
  parseFailureAnswer,
  safetyAlertAnswer,
  successAnswer,
} from '../../../api/__tests__/fixtures.ts'
import { parseAskResponse } from '../../../api/parse.ts'
import type { AskResult } from '../../../api/types.ts'
import { FakeSynthesis, FakeUtterance } from '../../../speech/__tests__/fakeSynthesis.ts'
import ResultView from '../ResultView.tsx'

let synth: FakeSynthesis

beforeEach(() => {
  synth = new FakeSynthesis()
  vi.stubGlobal('speechSynthesis', synth)
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

/** Runs the real parser on a wire-format answer, as the app does. */
function fromWire(answer: unknown, extra: Record<string, unknown> = {}): AskResult {
  return parseAskResponse(envelope(answer, extra), { question: 'q', machineId: 'compressor-01' })
}

const stepsList = () => screen.queryByRole('list', { name: 'Troubleshooting steps' })
const readAloud = () => {
  fireEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
  return synth.texts.join(' ')
}

describe('ResultView with the current backend format', () => {
  // Regression: SUCCESS with an empty checklist is an unverified safety state.
  it('SUCCESS: safety unverified, steps withheld; summary and references visible', () => {
    render(<ResultView result={fromWire(successAnswer())} />)
    expect(screen.getByText('SUCCESS')).toBeTruthy()
    expect(screen.getByText('Manual match')).toBeTruthy()
    expect(screen.getByText('Safety status could not be determined')).toBeTruthy()
    expect(screen.getByText('Withheld · 2 steps')).toBeTruthy()
    expect(stepsList()).toBeNull()
    expect(screen.queryByText(/Inspect intake air filter/)).toBeNull()
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    expect(screen.queryByText('No hazard flagged', { exact: false })).toBeNull()
    // Summary and references stay visible.
    expect(screen.getByText('Intake air filter is clogged causing insufficient pressure build-up.')).toBeTruthy()
    expect(screen.getByText('GA15-26_Instruction_Book')).toBeTruthy()
    expect(screen.getByText('p. 8')).toBeTruthy()
    expect(screen.getByText('Section: Pressure System')).toBeTruthy()
    // Fields the current format omits by design do not trigger a warning.
    expect(screen.queryByText('Incomplete response')).toBeNull()
  })

  it('SUCCESS with escalate: escalation notice stays visible while steps are withheld', () => {
    render(<ResultView result={fromWire({ ...successAnswer(), escalate: true })} />)
    expect(screen.getByText('Escalation recommended')).toBeTruthy()
    expect(stepsList()).toBeNull()
  })

  it('legacy is_dangerous=false still shows steps (old format unchanged)', () => {
    const legacy = {
      status: 'OK',
      problem_type: 'overheating',
      summary: 'Check the cooler.',
      is_dangerous: false,
      safety_checklist: [],
      history_note: '',
      steps: [{ step_no: 1, instruction: 'Check oil.', check_question: '' }],
      sources: [{ manual: 'GA15-26_Instruction_Book', page: 12 }],
      escalate: false,
    }
    render(<ResultView result={fromWire(legacy)} />)
    expect(within(stepsList()!).getAllByRole('listitem')).toHaveLength(1)
  })

  it('never shows search_score in any form', () => {
    const { container } = render(<ResultView result={fromWire(successAnswer())} />)
    const text = container.textContent ?? ''
    expect(text).not.toContain('0.312')
    expect(text).not.toMatch(/31(\.2)?\s*%/)
    expect(text).not.toMatch(/confidence|score/i)
  })

  it('SAFETY_ALERT: alert panel, required escalation, steps withheld with no way to reveal them', () => {
    render(<ResultView result={fromWire(safetyAlertAnswer())} />)
    expect(screen.getByText('SAFETY_ALERT')).toBeTruthy()
    expect(screen.getByText('Safety alert. Escalation required.')).toBeTruthy()
    expect(screen.getByText('Isolate power and lock out')).toBeTruthy()
    expect(screen.getByText('Do not start work. Contact the lead engineer.')).toBeTruthy()
    expect(screen.getByText('Withheld · 2 steps')).toBeTruthy()
    expect(stepsList()).toBeNull()
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    expect(screen.queryAllByRole('button').map((b) => b.textContent?.trim())).toEqual([
      'Read aloud',
      'Stop speaking',
    ])
    // Summary and references stay visible.
    expect(screen.getByText('Motor terminal fault suspected.')).toBeTruthy()
    expect(screen.getByText('GA15-26_Instruction_Book')).toBeTruthy()
  })

  it('SUCCESS with a checklist but no SAFETY_ALERT: safety unknown, steps withheld', () => {
    render(<ResultView result={fromWire({ ...successAnswer(), safety_checklist: ['Release all pressure'] })} />)
    expect(screen.getByText('Safety status could not be determined')).toBeTruthy()
    expect(screen.getByText('Withheld · 2 steps')).toBeTruthy()
    expect(stepsList()).toBeNull()
  })

  it('NOT_FOUND: distinct not-found block with the backend summary', () => {
    render(<ResultView result={fromWire(currentNotFoundAnswer())} />)
    expect(screen.getByRole('heading', { name: 'No verified manual guidance found' })).toBeTruthy()
    expect(screen.getByText('This issue or error code was not found in the verified manual.')).toBeTruthy()
    expect(screen.getByText('Escalation required')).toBeTruthy()
    expect(screen.queryByRole('heading', { name: /could not complete/ })).toBeNull()
  })

  it('internal error: distinct failure state, raw error never shown', () => {
    const { container } = render(<ResultView result={fromWire(parseFailureAnswer())} />)
    expect(screen.getByRole('heading', { name: 'The assistant could not complete this diagnosis' })).toBeTruthy()
    expect(screen.getByText('Could not complete')).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'No verified manual guidance found' })).toBeNull()
    expect(screen.queryByText('NOT_FOUND')).toBeNull()
    expect(screen.queryByText('Incomplete response')).toBeNull()
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/Failed to parse|KeyError|Expecting value/)
  })

  it('keeps the DEMO label', () => {
    render(<ResultView result={fromWire(successAnswer(), { is_demo: true })} />)
    expect(screen.getByText(/This is a demo response/)).toBeTruthy()
  })
})

describe('read aloud with the current backend format', () => {
  it('SUCCESS: does not read withheld steps; never reads search_score, section or manual names', () => {
    render(<ResultView result={fromWire(successAnswer())} />)
    const text = readAloud()
    expect(text).toContain('Safety status could not be determined.')
    expect(text).toContain('Summary. Intake air filter is clogged causing insufficient pressure build-up.')
    expect(text).toContain('2 troubleshooting steps are withheld because the safety status is unknown.')
    expect(text).not.toContain('Inspect intake air filter')
    expect(text).not.toContain('No hazard was flagged')
    for (const raw of ['0.312', 'Pressure System', 'GA15-26', 'SUCCESS', 'low_pressure']) {
      expect(text).not.toContain(raw)
    }
  })

  it('SAFETY_ALERT: alert and checklist first, steps never read', () => {
    render(<ResultView result={fromWire(safetyAlertAnswer())} />)
    const text = readAloud()
    expect(text.startsWith('Safety alert. Escalation is required.')).toBe(true)
    expect(text).toContain('Check 1. Isolate power and lock out.')
    expect(text).toContain('withheld because of the safety alert')
    expect(text).not.toContain('Inspect intake air filter')
  })

  it('internal error: says the assistant could not complete; never reads the error', () => {
    render(<ResultView result={fromWire(parseFailureAnswer())} />)
    const text = readAloud()
    expect(text).toContain('The assistant could not complete this diagnosis.')
    expect(text).not.toMatch(/Failed to parse|KeyError|Expecting value|No verified manual guidance/)
  })

  it('NOT_FOUND: says no verified manual guidance and escalation', () => {
    render(<ResultView result={fromWire(currentNotFoundAnswer())} />)
    const text = readAloud()
    expect(text).toContain('No verified manual guidance was found for this issue.')
    expect(text).toContain('Escalation is required.')
  })
})
