import type { AskResult } from '../api/types.ts'
import { safetyStateOf, stepsGateOf } from '../lib/safety.ts'

// Builds the text read aloud for a diagnosis, in the order shown on screen:
// safety, escalation, summary, steps, references note, repair history.
// Locked or withheld steps are described, never read. No machine IDs,
// status codes, field names or manual file names are spoken.

export const SPOKEN_DISCLAIMER =
  'The assistant cannot confirm that equipment is safe. Follow your site lockout and tagout procedure.'

export const SPOKEN_NOT_A_CLEARANCE = 'This is not a safety clearance.'

function sentence(text: string): string {
  const t = text.replace(/\s+/g, ' ').trim()
  if (!t) return ''
  return /[.!?]$/.test(t) ? t : `${t}.`
}

/** Splits long text at sentence boundaries; Chrome truncates long utterances. */
export function chunkForSpeech(text: string, maxLength = 220): string[] {
  const parts = text.replace(/\s+/g, ' ').trim().match(/[^.!?]+[.!?]*/g) ?? []
  const chunks: string[] = []
  let current = ''
  for (const raw of parts) {
    const part = raw.trim()
    if (!part) continue
    if (current && current.length + part.length + 1 > maxLength) {
      chunks.push(current)
      current = part
    } else {
      current = current ? `${current} ${part}` : part
    }
  }
  if (current) chunks.push(current)
  return chunks
}

export interface ReadAloudOptions {
  /** True only when steps are currently shown on screen. */
  stepsVisible: boolean
}

export function buildReadAloudScript(result: AskResult, { stepsVisible }: ReadAloudOptions): string[] {
  const { answer } = result
  const found = answer.status === 'OK'
  const safety = safetyStateOf(answer)
  const gate = stepsGateOf(answer)
  const out: string[] = []
  const say = (text: string) => {
    const s = sentence(text)
    if (s) out.push(s)
  }

  if (result.isDemo) say('This is a demo response, not a live diagnosis')
  if (result.issues.length > 0) say('Note: part of this response was missing or invalid. Review it carefully')

  // Safety is always spoken before any guidance.
  if (safety === 'flagged') {
    if (answer.safetyChecklist.length > 0) {
      say('Safety warning. A hazard was flagged. Complete these safety checks before any work')
      answer.safetyChecklist.forEach((item, i) => say(`Check ${i + 1}. ${item}`))
    } else {
      say(
        'Safety warning. A hazard was flagged, but no safety checklist was provided. Do not start work. ' +
          'Contact a qualified supervisor and follow the applicable site safety procedures',
      )
    }
  } else if (safety === 'uncertain') {
    say('Safety status could not be determined. Treat the machine as hazardous and contact the lead engineer')
    if (answer.safetyChecklist.length > 0) {
      say('Safety checks returned with this response')
      answer.safetyChecklist.forEach((item, i) => say(`Check ${i + 1}. ${item}`))
    }
  } else {
    say(`No hazard was flagged by the assistant. ${SPOKEN_NOT_A_CLEARANCE}`)
  }

  if (!found) {
    say('No verified manual guidance was found for this issue')
    say('Escalation is required. Contact the lead engineer. Do not attempt a repair based on this response')
  } else {
    if (answer.escalate) say('Escalation recommended. Involve the lead engineer for this issue')
    say(answer.summary ? `Summary. ${answer.summary}` : 'The assistant returned no summary')

    const count = answer.steps.length
    const plural = count === 1 ? 'step is' : 'steps are'
    if (gate === 'none') {
      say('No troubleshooting steps were returned')
    } else if (gate === 'withheld') {
      say(`${count} troubleshooting ${plural} withheld because the safety status is unknown`)
    } else if (gate === 'withheld_no_checklist') {
      say(`${count} troubleshooting ${plural} withheld because a hazard was flagged without a safety checklist`)
    } else if (gate === 'requires_ack' && !stepsVisible) {
      say(`${count} troubleshooting ${plural} locked until every safety check is confirmed on screen`)
    } else {
      for (const step of answer.steps) {
        say(`Step ${step.stepNo}. ${step.instruction}`)
        if (step.checkQuestion) say(`Check: ${step.checkQuestion}`)
      }
    }

    if (answer.sources.length > 0) say('Manual references are listed on screen')
    else if (count > 0) say('No manual reference was returned. Check the steps against the equipment manual')
  }

  if (answer.historyNote) {
    say(`Repair history, for context only, not manual guidance. ${answer.historyNote}`)
  }

  say(SPOKEN_DISCLAIMER)
  return out.flatMap((s) => chunkForSpeech(s))
}
