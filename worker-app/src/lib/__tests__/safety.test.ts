import { describe, expect, it } from 'vitest'
import type { TroubleshootingAnswer } from '../../api/types.ts'
import {
  CURRENT_FORMAT_EMPTY_CHECKLIST_MEANS_NOT_FLAGGED,
  acknowledgementItemsOf,
  escalationRequired,
  safetyStateOf,
  stepsGateOf,
} from '../safety.ts'

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
    rawStatus: overrides.status ?? 'OK',
    format: 'legacy',
    searchScore: null,
    internalError: false,
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

describe('current-format safety rules', () => {
  const current = (o: Partial<TroubleshootingAnswer> = {}) =>
    answer({ format: 'current', rawStatus: 'SUCCESS', isDangerous: null, ...o })

  it('SAFETY_ALERT is an alert and withholds steps, whatever else is set', () => {
    for (const o of [{}, { isDangerous: false }, { isDangerous: true, safetyChecklist: ['Stop'] }]) {
      const a = current({ status: 'SAFETY_ALERT', rawStatus: 'SAFETY_ALERT', ...o })
      expect(safetyStateOf(a)).toBe('alert')
      expect(stepsGateOf(a)).toBe('withheld_safety_alert')
      expect(acknowledgementItemsOf(a)).toEqual([])
      expect(escalationRequired(a)).toBe(true)
    }
  })

  // Regression: the policy stays strict until the backend team confirms it.
  it('current SUCCESS with no checklist: unverified, steps withheld', () => {
    expect(CURRENT_FORMAT_EMPTY_CHECKLIST_MEANS_NOT_FLAGGED).toBe(false)
    expect(safetyStateOf(current())).toBe('uncertain')
    expect(stepsGateOf(current())).toBe('withheld')
    expect(acknowledgementItemsOf(current())).toEqual([])
  })

  it('current SUCCESS never yields not_flagged or allowed, with or without escalate', () => {
    for (const o of [{}, { escalate: true }, { safetyChecklist: ['Stop'] }]) {
      expect(safetyStateOf(current(o))).toBe('uncertain')
      expect(stepsGateOf(current(o))).toBe('withheld')
    }
  })

  it('current SUCCESS with a checklist: uncertain, withheld', () => {
    const a = current({ safetyChecklist: ['Release pressure'] })
    expect(safetyStateOf(a)).toBe('uncertain')
    expect(stepsGateOf(a)).toBe('withheld')
  })

  it('mixed format without is_dangerous: uncertain, withheld', () => {
    const a = current({ format: 'mixed' })
    expect(safetyStateOf(a)).toBe('uncertain')
    expect(stepsGateOf(a)).toBe('withheld')
  })

  it('internal error: uncertain, no steps, escalation required', () => {
    const a = current({ internalError: true })
    expect(safetyStateOf(a)).toBe('uncertain')
    expect(stepsGateOf(a)).toBe('none')
    expect(escalationRequired(a)).toBe(true)
  })

  it('escalation is required for NOT_FOUND and optional for OK', () => {
    expect(escalationRequired(current({ status: 'NOT_FOUND' }))).toBe(true)
    expect(escalationRequired(current())).toBe(false)
    expect(escalationRequired(current({ escalate: true }))).toBe(true)
  })
})
