import type { TroubleshootingAnswer } from '../api/types.ts'

/**
 * - flagged:     backend marked the job dangerous, or sent safety checks.
 * - uncertain:   is_dangerous was missing or not a boolean. Treat as unknown.
 * - not_flagged: backend explicitly sent is_dangerous=false with no checks.
 *                This is NOT a safety clearance and must never be shown as one.
 */
export type SafetyState = 'flagged' | 'uncertain' | 'not_flagged'

export function safetyStateOf(answer: TroubleshootingAnswer): SafetyState {
  if (answer.isDangerous === true) return 'flagged'
  if (answer.isDangerous === null) return 'uncertain'
  // is_dangerous=false but checks were sent: trust the checks.
  if (answer.safetyChecklist.length > 0) return 'flagged'
  return 'not_flagged'
}

/**
 * Whether actionable steps may be shown, before any acknowledgement:
 * - none:          no steps to show (NOT_FOUND or empty list)
 * - withheld:      safety is uncertain; steps must not be shown
 * - requires_ack:  safety checks must be acknowledged first
 * - allowed:       steps may be shown
 */
export type StepsGate = 'none' | 'withheld' | 'requires_ack' | 'allowed'

export function stepsGateOf(answer: TroubleshootingAnswer): StepsGate {
  if (answer.status !== 'OK' || answer.steps.length === 0) return 'none'
  const state = safetyStateOf(answer)
  if (state === 'uncertain') return 'withheld'
  if (state === 'flagged') return 'requires_ack'
  return 'allowed'
}
