// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { AskResult, TroubleshootingAnswer } from '../../../api/types.ts'
import ResultView from '../ResultView.tsx'
import { ACK_MEANING, SAFETY_DISCLAIMER } from '../SafetyPanel.tsx'

afterEach(cleanup)

// Test-only data. Never imported by application code.
function result(answer: Partial<TroubleshootingAnswer> = {}, extra: Partial<AskResult> = {}): AskResult {
  return {
    machineId: 'compressor-01',
    question: 'Compressor is overheating',
    isDemo: false,
    issues: [],
    ...extra,
    answer: {
      status: 'OK',
      problemType: 'overheating',
      summary: 'Check the cooler and oil level.',
      isDangerous: false,
      safetyChecklist: [],
      historyNote: '',
      steps: [
        { stepNo: 1, instruction: 'Check the oil level.', checkQuestion: 'Is the oil between the marks?' },
        { stepNo: 2, instruction: 'Inspect the oil cooler.', checkQuestion: '' },
      ],
      sources: [{ manual: 'GA15-26_Instruction_Book', page: 42 }],
      escalate: false,
      ...answer,
    },
  }
}

const dangerous = {
  isDangerous: true,
  safetyChecklist: ['Stop the compressor and let it cool', 'Release all pressure'],
}

const stepsList = () => screen.queryByRole('list', { name: 'Troubleshooting steps' })

/** Visible text with the known disclaimers removed. */
function textWithoutDisclaimers(container: HTMLElement): string {
  return (container.textContent ?? '')
    .replaceAll(SAFETY_DISCLAIMER, '')
    .replaceAll(ACK_MEANING, '')
    .replaceAll('This is not a safety clearance.', '')
}

describe('ResultView: hazard flagged', () => {
  it('shows the checklist and locks steps until every box is ticked', () => {
    render(<ResultView result={result(dangerous)} />)

    expect(screen.getByText('Safety · Hazard flagged')).toBeTruthy()
    expect(stepsList()).toBeNull()
    expect(screen.getByText('Locked · 2 steps')).toBeTruthy()

    const boxes = screen.getAllByRole('checkbox')
    expect(boxes).toHaveLength(2)

    fireEvent.click(screen.getByLabelText(/Stop the compressor/))
    expect(stepsList()).toBeNull()
    expect(screen.getByText(/checks confirmed\. Steps stay locked/)).toBeTruthy()

    fireEvent.click(screen.getByLabelText(/Release all pressure/))
    const list = stepsList()
    expect(list).not.toBeNull()
    expect(within(list!).getAllByRole('listitem')).toHaveLength(2)
  })

  it('re-locks steps when a box is unticked', () => {
    render(<ResultView result={result(dangerous)} />)
    for (const box of screen.getAllByRole('checkbox')) fireEvent.click(box)
    expect(stepsList()).not.toBeNull()

    fireEvent.click(screen.getAllByRole('checkbox')[0]!)
    expect(stepsList()).toBeNull()
  })

  // Regression: a flagged hazard with no checklist must keep steps withheld.
  // There is no checkbox or other control that can reveal them.
  it('withholds steps when a hazard is flagged without a checklist', () => {
    render(<ResultView result={result({ isDangerous: true, safetyChecklist: [] })} />)
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    // Only the read-aloud controls exist; nothing can reveal the steps.
    expect(screen.queryAllByRole('button').map((b) => b.textContent?.trim())).toEqual(['Read aloud', 'Stop speaking'])
    expect(stepsList()).toBeNull()
    expect(screen.getByText('Withheld · 2 steps')).toBeTruthy()
    expect(screen.getAllByText(/qualified supervisor/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/applicable site safety procedures/).length).toBeGreaterThan(0)
    // Summary and references remain visible.
    expect(screen.getByText('Check the cooler and oil level.')).toBeTruthy()
    expect(screen.getByText('GA15-26_Instruction_Book')).toBeTruthy()
  })

  it('treats is_dangerous=false with a checklist as flagged', () => {
    render(<ResultView result={result({ isDangerous: false, safetyChecklist: ['Isolate power'] })} />)
    expect(screen.getAllByRole('checkbox')).toHaveLength(1)
    expect(stepsList()).toBeNull()
  })

  it('does not carry acknowledgement over to a new response', () => {
    const { rerender } = render(<ResultView key={1} result={result(dangerous)} />)
    for (const box of screen.getAllByRole('checkbox')) fireEvent.click(box)
    expect(stepsList()).not.toBeNull()

    rerender(<ResultView key={2} result={result(dangerous)} />)
    expect(stepsList()).toBeNull()
    expect(screen.getAllByRole('checkbox').every((b) => !(b as HTMLInputElement).checked)).toBe(true)
  })

  it('shows summary, escalation and references while steps are locked', () => {
    render(<ResultView result={result({ ...dangerous, escalate: true })} />)
    expect(stepsList()).toBeNull()
    expect(screen.getByText('Check the cooler and oil level.')).toBeTruthy()
    expect(screen.getByText('Escalation recommended')).toBeTruthy()
    expect(screen.getByText('GA15-26_Instruction_Book')).toBeTruthy()
    expect(screen.getByText('p. 42')).toBeTruthy()
  })
})

describe('ResultView: safety uncertain', () => {
  it('withholds steps with no way to reveal them', () => {
    render(<ResultView result={result({ isDangerous: null })} />)
    expect(screen.getByText('Safety status could not be determined')).toBeTruthy()
    expect(screen.getByText('Withheld · 2 steps')).toBeTruthy()
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    expect(stepsList()).toBeNull()
  })

  it('shows any returned checklist read-only', () => {
    render(<ResultView result={result({ isDangerous: null, safetyChecklist: ['Isolate power'] })} />)
    expect(screen.getByText('Isolate power')).toBeTruthy()
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    expect(stepsList()).toBeNull()
  })
})

describe('ResultView: no hazard flagged', () => {
  it('shows numbered steps immediately, with check questions', () => {
    render(<ResultView result={result()} />)
    const list = stepsList()!
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]!.textContent).toContain('01')
    expect(items[0]!.textContent).toContain('Check the oil level.')
    expect(items[0]!.textContent).toContain('Is the oil between the marks?')
    expect(items[1]!.textContent).toContain('02')
  })

  it('labels the absence of a hazard flag as not a safety clearance', () => {
    render(<ResultView result={result()} />)
    expect(screen.getByText('This is not a safety clearance.')).toBeTruthy()
  })
})

describe('ResultView: never implies the equipment is safe', () => {
  it.each([
    ['flagged', dangerous],
    ['flagged, no checklist', { isDangerous: true, safetyChecklist: [] }],
    ['uncertain', { isDangerous: null }],
    ['not flagged', {}],
    ['not found', { status: 'NOT_FOUND' as const, steps: [], escalate: true }],
  ])('%s', (_label, answer) => {
    const { container } = render(<ResultView result={result(answer)} />)
    for (const box of screen.queryAllByRole('checkbox')) fireEvent.click(box)
    expect(textWithoutDisclaimers(container)).not.toMatch(/\bsafe\b/i)
    expect(container.textContent).toContain(SAFETY_DISCLAIMER)
  })
})

describe('ResultView: references', () => {
  it('lists unique manual references with pages', () => {
    render(
      <ResultView
        result={result({
          sources: [
            { manual: 'GA15-26_Instruction_Book', page: 42 },
            { manual: 'GA15-26_Instruction_Book', page: 42 },
            { manual: 'Compressed_Air_Manual.pdf', page: null },
          ],
        })}
      />,
    )
    expect(screen.getAllByText('GA15-26_Instruction_Book')).toHaveLength(1)
    expect(screen.getByText('Compressed_Air_Manual.pdf')).toBeTruthy()
    expect(screen.getByText('page not given')).toBeTruthy()
  })

  it('warns when steps came without any reference', () => {
    render(<ResultView result={result({ sources: [] })} />)
    expect(screen.getByText(/No manual reference was returned\. Check the steps/)).toBeTruthy()
  })
})

describe('ResultView: NOT_FOUND', () => {
  const notFound = {
    status: 'NOT_FOUND' as const,
    summary: 'Not found in manual.',
    steps: [],
    sources: [],
    escalate: true,
  }

  it('shows a distinct not-found block with required escalation and no guidance', () => {
    render(<ResultView result={result(notFound)} />)
    expect(screen.getByRole('heading', { name: 'No answer found in the manuals' })).toBeTruthy()
    expect(screen.getByText('Escalation required')).toBeTruthy()
    expect(screen.getByText('Not found in manual.')).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Manual guidance' })).toBeNull()
    expect(screen.queryByText('References')).toBeNull()
    expect(stepsList()).toBeNull()
  })

  it('does not ask for acknowledgement when there are no steps to unlock', () => {
    render(<ResultView result={result({ ...notFound, ...dangerous })} />)
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    expect(screen.getByText('Stop the compressor and let it cool')).toBeTruthy()
  })
})

describe('ResultView: repair history', () => {
  it('keeps history separate from manual guidance', () => {
    render(<ResultView result={result({ historyNote: 'Cooler cleaned on 2 Oct.' })} />)
    const history = screen.getByRole('complementary', { name: 'Repair history' })
    expect(within(history).getByText('Cooler cleaned on 2 Oct.')).toBeTruthy()
    expect(within(history).getByText(/not manual guidance/i)).toBeTruthy()

    const guidance = screen.getByRole('region', { name: 'Manual guidance' })
    expect(within(guidance).queryByText('Cooler cleaned on 2 Oct.')).toBeNull()
  })

  it('omits the history block when there is no note', () => {
    render(<ResultView result={result()} />)
    expect(screen.queryByRole('complementary', { name: 'Repair history' })).toBeNull()
  })
})

describe('ResultView: incomplete and demo responses', () => {
  it('shows an incomplete-response notice with technical details', () => {
    render(<ResultView result={result({}, { issues: ['answer.summary is missing', 'answer.steps[1] has no instruction and was dropped'] })} />)
    expect(screen.getByText('Incomplete response')).toBeTruthy()
    expect(screen.getByText('2 technical details')).toBeTruthy()
    expect(screen.getByText('answer.summary is missing')).toBeTruthy()
  })

  it('says when no summary was returned instead of inventing one', () => {
    render(<ResultView result={result({ summary: '' })} />)
    expect(screen.getByText('The assistant returned no summary.')).toBeTruthy()
  })

  it('says when no steps were returned', () => {
    render(<ResultView result={result({ steps: [] })} />)
    expect(screen.getByText('No troubleshooting steps were returned.')).toBeTruthy()
  })

  it('labels demo responses', () => {
    render(<ResultView result={result({}, { isDemo: true })} />)
    expect(screen.getByText(/This is a demo response/)).toBeTruthy()
  })
})
