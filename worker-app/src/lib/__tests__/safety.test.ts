import { describe, expect, it } from 'vitest'
import type { TroubleshootingAnswer } from '../../api/types.ts'
import { acknowledgementItemsOf, safetyStateOf, stepsGateOf } from '../safety.ts'

function answer(overrides: Partial<TroubleshootingAnswer> = {}): TroubleshootingAnswer {
  return {
    status: 'OK',
    problemType: 'overheating',
    summary: 'Check the cooler.',
    isDangerous: false,
    safetyChecklist: [],
    historyNote: '',
    steps: [{ stepNo: 1, instruction: 'Check oil.', checkQuestion: '' }],
    sources: [],
    escalate: false,
    ...overrides,
  }
}

describe('safetyStateOf', () => {
  it('is flagged when is_dangerous is true', () => {
    expect(safetyStateOf(answer({ isDangerous: true }))).toBe('flagged')
  })

  it('is uncertain when is_dangerous is unknown (missing or malformed)', () => {
    expect(safetyStateOf(answer({ isDangerous: null }))).toBe('uncertain')
  })

  it('stays uncertain even if a checklist is present', () => {
    expect(safetyStateOf(answer({ isDangerous: null, safetyChecklist: ['Isolate power'] }))).toBe('uncertain')
  })

  it('is flagged when is_dangerous is false but safety checks were sent', () => {
    expect(safetyStateOf(answer({ isDangerous: false, safetyChecklist: ['Isolate power'] }))).toBe('flagged')
  })

  it('is not_flagged only for an explicit false with no checks', () => {
    expect(safetyStateOf(answer({ isDangerous: false }))).toBe('not_flagged')
  })
})

describe('stepsGateOf', () => {
  it('withholds steps when safety is uncertain', () => {
    expect(stepsGateOf(answer({ isDangerous: null }))).toBe('withheld')
  })

  it('withholds steps when a hazard is flagged without a checklist', () => {
    expect(stepsGateOf(answer({ isDangerous: true, safetyChecklist: [] }))).toBe('withheld_no_checklist')
  })

  it('requires acknowledgement when flagged', () => {
    expect(stepsGateOf(answer({ isDangerous: true, safetyChecklist: ['Stop'] }))).toBe('requires_ack')
  })

  it('allows steps only when explicitly not flagged', () => {
    expect(stepsGateOf(answer())).toBe('allowed')
  })

  it('has no steps for NOT_FOUND', () => {
    expect(stepsGateOf(answer({ status: 'NOT_FOUND', steps: [] }))).toBe('none')
  })

  it('has no steps for an empty step list', () => {
    expect(stepsGateOf(answer({ steps: [] }))).toBe('none')
  })
})

describe('acknowledgementItemsOf', () => {
  it('uses the backend checklist when a hazard is flagged', () => {
    const a = answer({ isDangerous: true, safetyChecklist: ['Stop', 'Release pressure'] })
    expect(acknowledgementItemsOf(a)).toEqual(['Stop', 'Release pressure'])
  })

  // Regression: a flagged hazard without a checklist must not be unlockable
  // through a generic acknowledgement.
  it('offers nothing to acknowledge when a hazard is flagged without a checklist', () => {
    expect(acknowledgementItemsOf(answer({ isDangerous: true, safetyChecklist: [] }))).toEqual([])
  })

  it('needs no acknowledgement when nothing is gated', () => {
    expect(acknowledgementItemsOf(answer())).toEqual([])
    expect(acknowledgementItemsOf(answer({ isDangerous: null }))).toEqual([])
    expect(acknowledgementItemsOf(answer({ isDangerous: true, steps: [] }))).toEqual([])
  })
})
