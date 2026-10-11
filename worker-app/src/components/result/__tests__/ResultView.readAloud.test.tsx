// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AskResult, TroubleshootingAnswer } from '../../../api/types.ts'
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

// Test-only data.
function result(answer: Partial<TroubleshootingAnswer> = {}): AskResult {
  return {
    machineId: 'compressor-01',
    question: 'Compressor is overheating',
    isDemo: false,
    issues: [],
    answer: {
      status: 'OK',
      problemType: 'overheating',
      summary: 'Likely a blocked oil cooler.',
      isDangerous: false,
      safetyChecklist: [],
      historyNote: '',
      steps: [{ stepNo: 1, instruction: 'Check the oil level', checkQuestion: '' }],
      sources: [{ manual: 'GA15-26_Instruction_Book', page: 42 }],
      escalate: false,
      ...answer,
    },
  }
}

const dangerous = { isDangerous: true, safetyChecklist: ['Stop the compressor', 'Release all pressure'] }
const readButton = () => screen.getByRole('button', { name: 'Read aloud' }) as HTMLButtonElement
const stopButton = () => screen.getByRole('button', { name: 'Stop speaking' }) as HTMLButtonElement
const spoken = () => synth.texts.join(' ')

describe('ResultView read aloud', () => {
  it('reads the diagnosis and shows a speaking state', () => {
    render(<ResultView result={result()} />)
    expect(stopButton().disabled).toBe(true)
    fireEvent.click(readButton())
    expect(spoken()).toContain('Summary. Likely a blocked oil cooler.')
    expect(spoken()).toContain('Step 1. Check the oil level.')
    expect(screen.getByText('Speaking')).toBeTruthy()
    expect(readButton().disabled).toBe(true)
    expect(stopButton().disabled).toBe(false)

    act(() => synth.finishAll())
    expect(screen.queryByText('Speaking')).toBeNull()
    expect(readButton().disabled).toBe(false)
  })

  it('Stop speaking cancels playback', () => {
    render(<ResultView result={result()} />)
    fireEvent.click(readButton())
    const before = synth.cancelCalls
    fireEvent.click(stopButton())
    expect(synth.cancelCalls).toBeGreaterThan(before)
    expect(stopButton().disabled).toBe(true)
    expect(readButton().disabled).toBe(false)
  })

  it('repeated clicks do not start overlapping sessions', () => {
    render(<ResultView result={result()} />)
    fireEvent.click(readButton())
    const count = synth.spoken.length
    fireEvent.click(readButton())
    fireEvent.click(readButton())
    expect(synth.spoken).toHaveLength(count)
  })

  it('does not read steps until the safety checks are acknowledged', () => {
    render(<ResultView result={result(dangerous)} />)
    fireEvent.click(readButton())
    expect(spoken()).toContain('Safety warning')
    expect(spoken()).not.toContain('Check the oil level')
    expect(spoken()).toContain('locked until every safety check is confirmed')
  })

  it('reads steps after acknowledgement, safety warning first', () => {
    render(<ResultView result={result(dangerous)} />)
    for (const box of screen.getAllByRole('checkbox')) fireEvent.click(box)
    fireEvent.click(readButton())
    const text = spoken()
    expect(text.indexOf('Safety warning')).toBeLessThan(text.indexOf('Step 1. Check the oil level.'))
  })

  it('stops speaking when a safety box is unticked and steps lock again', () => {
    render(<ResultView result={result(dangerous)} />)
    for (const box of screen.getAllByRole('checkbox')) fireEvent.click(box)
    fireEvent.click(readButton())
    expect(stopButton().disabled).toBe(false)

    fireEvent.click(screen.getAllByRole('checkbox')[0]!)
    expect(stopButton().disabled).toBe(true)
  })

  it('never reads withheld steps', () => {
    render(<ResultView result={result({ isDangerous: null })} />)
    fireEvent.click(readButton())
    expect(spoken()).not.toContain('Check the oil level')
    expect(spoken()).toContain('withheld because the safety status is unknown')
  })

  it('says no verified guidance and escalation for NOT_FOUND', () => {
    render(<ResultView result={result({ status: 'NOT_FOUND', steps: [], sources: [], escalate: true })} />)
    fireEvent.click(readButton())
    expect(spoken()).toContain('No verified manual guidance was found for this issue.')
    expect(spoken()).toContain('Escalation is required.')
  })

  it('stops when the answer changes (new response mounts a new view)', () => {
    const { rerender } = render(<ResultView key={1} result={result()} />)
    fireEvent.click(readButton())
    const before = synth.cancelCalls
    rerender(<ResultView key={2} result={result({ summary: 'Different answer.' })} />)
    expect(synth.cancelCalls).toBeGreaterThan(before)
    expect(screen.queryByText('Speaking')).toBeNull()
  })

  it('disables read aloud where speech synthesis is unavailable', () => {
    vi.stubGlobal('speechSynthesis', undefined)
    render(<ResultView result={result()} />)
    expect(readButton().disabled).toBe(true)
    expect(stopButton().disabled).toBe(true)
    expect(screen.getByText('Read aloud is not available in this browser.')).toBeTruthy()
  })
})
