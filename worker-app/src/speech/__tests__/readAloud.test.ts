import { describe, expect, it } from 'vitest'
import type { AskResult, TroubleshootingAnswer } from '../../api/types.ts'
import { SPOKEN_DISCLAIMER, SPOKEN_NOT_A_CLEARANCE, buildReadAloudScript, chunkForSpeech } from '../readAloud.ts'

// Test-only data.
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
      summary: 'Likely a blocked oil cooler.',
      isDangerous: false,
      safetyChecklist: [],
      historyNote: '',
      steps: [
        { stepNo: 1, instruction: 'Check the oil level', checkQuestion: 'Is it between the marks?' },
        { stepNo: 2, instruction: 'Inspect the cooler fins', checkQuestion: '' },
      ],
      sources: [{ manual: 'GA15-26_Instruction_Book.pdf', page: 42 }],
      escalate: false,
      ...answer,
    },
  }
}

const dangerous = { isDangerous: true, safetyChecklist: ['Stop the compressor and let it cool', 'Release all pressure'] }
const read = (r: AskResult, stepsVisible = false) => buildReadAloudScript(r, { stepsVisible }).join(' ')
const indexOf = (text: string, part: string) => {
  const i = text.indexOf(part)
  if (i < 0) throw new Error(`"${part}" not spoken in: ${text}`)
  return i
}

describe('buildReadAloudScript: order and content', () => {
  it('reads safety, summary and steps in displayed order when steps are visible', () => {
    const text = read(result(), true)
    const safety = indexOf(text, 'No hazard was flagged')
    const summary = indexOf(text, 'Summary. Likely a blocked oil cooler.')
    const step1 = indexOf(text, 'Step 1. Check the oil level.')
    const check1 = indexOf(text, 'Check: Is it between the marks?')
    const step2 = indexOf(text, 'Step 2. Inspect the cooler fins.')
    expect(safety).toBeLessThan(summary)
    expect(summary).toBeLessThan(step1)
    expect(step1).toBeLessThan(check1)
    expect(check1).toBeLessThan(step2)
    expect(text).toContain(SPOKEN_NOT_A_CLEARANCE)
    expect(text.endsWith(SPOKEN_DISCLAIMER)).toBe(true)
  })

  it('speaks the safety warning and every check before any guidance for dangerous answers', () => {
    const text = read(result({ ...dangerous, escalate: true }), true)
    const warning = indexOf(text, 'Safety warning. A hazard was flagged.')
    const check2 = indexOf(text, 'Check 2. Release all pressure.')
    expect(warning).toBeLessThan(check2)
    expect(check2).toBeLessThan(indexOf(text, 'Escalation recommended'))
    expect(check2).toBeLessThan(indexOf(text, 'Summary.'))
    expect(check2).toBeLessThan(indexOf(text, 'Step 1.'))
  })

  it('reads repair history last, labelled as context', () => {
    const text = read(result({ historyNote: 'Cooler cleaned on 2 Oct.' }), true)
    expect(indexOf(text, 'Step 2.')).toBeLessThan(indexOf(text, 'Repair history, for context only, not manual guidance.'))
  })
})

describe('buildReadAloudScript: safety gating', () => {
  it('does not read unacknowledged steps', () => {
    const text = read(result(dangerous), false)
    expect(text).not.toContain('Check the oil level')
    expect(text).not.toContain('Step 1')
    expect(text).toContain('2 troubleshooting steps are locked until every safety check is confirmed on screen.')
  })

  it('reads steps once they are acknowledged on screen', () => {
    expect(read(result(dangerous), true)).toContain('Step 1. Check the oil level.')
  })

  it('never reads steps withheld for unknown safety, even if marked visible', () => {
    const text = read(result({ isDangerous: null }), true)
    expect(text).not.toContain('Check the oil level')
    expect(text).toContain('Safety status could not be determined')
    expect(text).toContain('withheld because the safety status is unknown')
  })

  it('never reads steps withheld for a hazard without a checklist, even if marked visible', () => {
    const text = read(result({ isDangerous: true, safetyChecklist: [] }), true)
    expect(text).not.toContain('Check the oil level')
    expect(text).toContain('no safety checklist was provided')
    expect(text).toContain('qualified supervisor')
  })
})

describe('buildReadAloudScript: NOT_FOUND', () => {
  it('says no verified manual guidance was found and escalation is required', () => {
    const text = read(
      result({ status: 'NOT_FOUND', summary: 'Not found in manual.', steps: [], sources: [], escalate: true }),
      true,
    )
    expect(text).toContain('No verified manual guidance was found for this issue.')
    expect(text).toContain('Escalation is required. Contact the lead engineer.')
    expect(text).not.toContain('Summary.')
    expect(text).not.toContain('Step')
  })
})

describe('buildReadAloudScript: never speaks raw data', () => {
  const variants: Array<[string, AskResult]> = [
    ['ok', result()],
    ['dangerous', result(dangerous)],
    ['uncertain', result({ isDangerous: null })],
    ['not found', result({ status: 'NOT_FOUND', steps: [], sources: [], escalate: true })],
    ['incomplete', result({}, { issues: ['answer.summary is missing'] })],
  ]

  it.each(variants)('%s: no IDs, codes, field names, file names or JSON', (_label, r) => {
    const text = read(r, true)
    for (const raw of [
      'compressor-01',
      'NOT_FOUND',
      'overheating',
      'GA15-26',
      'Instruction_Book',
      '.pdf',
      'page 42',
      'answer.',
      'is_dangerous',
      'safety_checklist',
      '{',
      '}',
      '_',
    ]) {
      expect(text).not.toContain(raw)
    }
  })

  it('mentions references without reading identifiers', () => {
    expect(read(result(), true)).toContain('Manual references are listed on screen.')
  })

  it('never says the equipment is safe outside the fixed disclaimers', () => {
    for (const [, r] of variants) {
      const text = read(r, true).replaceAll(SPOKEN_DISCLAIMER, '').replaceAll(SPOKEN_NOT_A_CLEARANCE, '')
      expect(text).not.toMatch(/\bsafe\b/i)
    }
  })

  it('labels demo responses', () => {
    expect(read(result({}, { isDemo: true }))).toContain('This is a demo response, not a live diagnosis.')
  })
})

describe('chunkForSpeech', () => {
  it('splits long text at sentence boundaries', () => {
    const chunks = chunkForSpeech('One two three. Four five six. Seven eight nine.', 20)
    expect(chunks).toEqual(['One two three.', 'Four five six.', 'Seven eight nine.'])
  })

  it('keeps short text as one chunk', () => {
    expect(chunkForSpeech('Check the oil. Then the belt.')).toEqual(['Check the oil. Then the belt.'])
  })
})
