import type { TroubleshootingAnswer } from '../api/types.ts'

/**
 * - alert:       SAFETY_ALERT. Escalation required; steps always withheld.
 * - flagged:     a hazard was flagged with a usable signal (legacy
 *                is_dangerous=true, or a checklist with is_dangerous=false).
 * - uncertain:   no reliable safety signal, or signals contradict each other.
 *                Treated as unknown; steps withheld.
 * - not_flagged: the backend explicitly indicated no hazard. This is NOT a
 *                safety clearance and must never be shown as one.
 */
export type SafetyState = 'alert' | 'flagged' | 'uncertain' | 'not_flagged'

/**
 * PENDING CONTRACT DECISION (current format): there is no is_dangerous field.
 * brain.py sets SAFETY_ALERT when its keyword checks trigger a checklist, and
 * docs/json-format.md on main says the checklist is "[] if safe", but the
 * backend team has not confirmed that an empty checklist authorises repair
 * steps. Until they do, a current-format SUCCESS with an empty checklist is
 * an unverified safety state: steps are withheld, while the summary,
 * references and escalation stay visible.
 *
 * Only change this to true once the safety policy is confirmed in writing.
 */
export const CURRENT_FORMAT_EMPTY_CHECKLIST_MEANS_NOT_FLAGGED = false

export function safetyStateOf(answer: TroubleshootingAnswer): SafetyState {
  if (answer.status === 'SAFETY_ALERT') return 'alert'
  if (answer.internalError) return 'uncertain'

  if (answer.isDangerous === true) return 'flagged'
  if (answer.isDangerous === false) {
    // is_dangerous=false but checks were sent: trust the checks.
    return answer.safetyChecklist.length > 0 ? 'flagged' : 'not_flagged'
  }

  // is_dangerous not provided.
  if (
    answer.format === 'current' &&
    answer.safetyChecklist.length === 0 &&
    CURRENT_FORMAT_EMPTY_CHECKLIST_MEANS_NOT_FLAGGED
  ) {
    return 'not_flagged'
  }
  // Legacy or mixed without is_dangerous, or a current-format checklist
  // without SAFETY_ALERT (contradicts the contract): unknown.
  return 'uncertain'
}

/**
 * Whether actionable steps may be shown, before any acknowledgement:
 * - none:                  no steps to show (NOT_FOUND, error or empty list)
 * - withheld_safety_alert: SAFETY_ALERT; withheld until the team defines a
 *                          policy for acting on safety alerts
 * - withheld:              safety is uncertain; steps must not be shown
 * - withheld_no_checklist: hazard flagged without a checklist; there is
 *                          nothing specific to acknowledge, so steps stay
 *                          withheld and the worker is sent to a supervisor
 * - requires_ack:          every checklist item must be acknowledged first
 * - allowed:               steps may be shown
 */
export type StepsGate =
  | 'none'
  | 'withheld_safety_alert'
  | 'withheld'
  | 'withheld_no_checklist'
  | 'requires_ack'
  | 'allowed'

export function stepsGateOf(answer: TroubleshootingAnswer): StepsGate {
  if (answer.steps.length === 0 || answer.status === 'NOT_FOUND' || answer.internalError) return 'none'
  const state = safetyStateOf(answer)
  if (state === 'alert') return 'withheld_safety_alert'
  if (state === 'uncertain') return 'withheld'
  if (state === 'flagged') {
    return answer.safetyChecklist.length > 0 ? 'requires_ack' : 'withheld_no_checklist'
  }
  return 'allowed'
}

/** Checklist items the worker must tick before steps are revealed. */
export function acknowledgementItemsOf(answer: TroubleshootingAnswer): string[] {
  return stepsGateOf(answer) === 'requires_ack' ? answer.safetyChecklist : []
}

/** SAFETY_ALERT, NOT_FOUND and backend errors always require escalation. */
export function escalationRequired(answer: TroubleshootingAnswer): boolean {
  return answer.escalate || answer.status !== 'OK' || answer.internalError
}
