import { describe, expect, it } from 'vitest'
import { safetyStateOf, stepsGateOf } from '../../lib/safety.ts'
import { ApiError } from '../errors.ts'
import { looksLikeInternalError, parseAskResponse } from '../parse.ts'
import {
  currentNotFoundAnswer,
  envelope,
  okAnswer,
  parseFailureAnswer,
  safetyAlertAnswer,
  successAnswer,
} from './fixtures.ts'

const req = { question: 'Pressure is low', machineId: 'compressor-01' }
const parse = (answer: unknown, extra: Record<string, unknown> = {}) =>
  parseAskResponse(envelope(answer, extra), req)

function expectMalformed(answer: unknown) {
  try {
    parse(answer)
    expect.unreachable('expected malformed')
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError)
    expect((e as ApiError).kind).toBe('malformed')
  }
}

describe('current format: SUCCESS', () => {
  it('normalizes SUCCESS to OK and keeps the received status', () => {
    const { answer } = parse(successAnswer())
    expect(answer.status).toBe('OK')
    expect(answer.rawStatus).toBe('SUCCESS')
    expect(answer.format).toBe('current')
  })

  it('reads step_number, instruction and check_question', () => {
    const { answer } = parse(successAnswer())
    expect(answer.steps).toEqual([
      {
        stepNo: 1,
        instruction: 'Inspect intake air filter cartridge for dust accumulation.',
        checkQuestion: 'Is the filter cartridge clogged with debris?',
      },
      {
        stepNo: 2,
        instruction: 'Clean cartridge with compressed air or replace if saturated.',
        checkQuestion: 'Is the replacement cartridge seated securely in the housing?',
      },
    ])
  })

  it('reads manual_title, page_number and section exactly as returned', () => {
    expect(parse(successAnswer()).answer.sources).toEqual([
      { manual: 'GA15-26_Instruction_Book', page: 8, section: 'Pressure System' },
    ])
  })

  it('does not flag fields the current format omits by design', () => {
    const { answer, issues } = parse(successAnswer())
    expect(issues).toEqual([])
    expect(answer.isDangerous).toBeNull()
    expect(answer.historyNote).toBe('')
  })

  it('stores search_score as a distance only', () => {
    expect(parse(successAnswer()).answer.searchScore).toBe(0.312)
  })

  it('keeps problem_type as received', () => {
    expect(parse({ ...successAnswer(), problem_type: 'low pressure' }).answer.problemType).toBe('low pressure')
  })

  // Regression: SUCCESS with an empty checklist is NOT a safety authorisation
  // until the backend team confirms the policy.
  it('treats SUCCESS with an empty checklist as unverified and withholds steps', () => {
    const { answer } = parse(successAnswer())
    expect(safetyStateOf(answer)).toBe('uncertain')
    expect(stepsGateOf(answer)).toBe('withheld')
    // The steps are still parsed (not discarded), just not shown.
    expect(answer.steps).toHaveLength(2)
  })

  it('treats SUCCESS with a checklist as uncertain and withholds steps', () => {
    const { answer } = parse({ ...successAnswer(), safety_checklist: ['Release all pressure'] })
    expect(safetyStateOf(answer)).toBe('uncertain')
    expect(stepsGateOf(answer)).toBe('withheld')
  })

  it('accepts status in any letter case', () => {
    expect(parse({ ...successAnswer(), status: 'success' }).answer.status).toBe('OK')
    expect(parse({ ...successAnswer(), status: ' Safety_Alert ' }).answer.status).toBe('SAFETY_ALERT')
  })
})

describe('current format: SAFETY_ALERT', () => {
  it('is recognised, keeps its checklist and withholds steps', () => {
    const { answer } = parse(safetyAlertAnswer())
    expect(answer.status).toBe('SAFETY_ALERT')
    expect(answer.safetyChecklist).toEqual(['Isolate power and lock out', 'Do not touch cables'])
    expect(safetyStateOf(answer)).toBe('alert')
    expect(stepsGateOf(answer)).toBe('withheld_safety_alert')
  })

  it('withholds steps even with an empty checklist', () => {
    const { answer } = parse({ ...safetyAlertAnswer(), safety_checklist: [] })
    expect(stepsGateOf(answer)).toBe('withheld_safety_alert')
  })

  it('cannot be unlocked by is_dangerous=false', () => {
    const { answer } = parse({ ...safetyAlertAnswer(), is_dangerous: false })
    expect(safetyStateOf(answer)).toBe('alert')
    expect(stepsGateOf(answer)).toBe('withheld_safety_alert')
  })
})

describe('current format: NOT_FOUND', () => {
  it('escalates, has no steps and shows the backend summary', () => {
    const { answer, issues } = parse(currentNotFoundAnswer())
    expect(answer.status).toBe('NOT_FOUND')
    expect(answer.format).toBe('current')
    expect(answer.escalate).toBe(true)
    expect(answer.steps).toEqual([])
    expect(answer.summary).toBe('This issue or error code was not found in the verified manual.')
    expect(answer.internalError).toBe(false)
    expect(answer.searchScore).toBeNull()
    expect(issues).toEqual([])
  })
})

describe('internal backend errors', () => {
  it('hides the raw parse-failure text and marks an internal error', () => {
    const { answer, issues } = parse(parseFailureAnswer())
    expect(answer.internalError).toBe(true)
    expect(answer.summary).toBe('')
    expect(JSON.stringify(answer)).not.toMatch(/Failed to parse|KeyError|Expecting value/)
    expect(issues).toContain('internal error text from the backend was hidden')
    expect(issues.join(' ')).not.toMatch(/KeyError|Expecting value/)
  })

  it('is distinct from a real NOT_FOUND', () => {
    expect(parse(currentNotFoundAnswer()).answer.internalError).toBe(false)
    expect(parse(parseFailureAnswer()).answer.internalError).toBe(true)
  })

  it('drops any steps and references that came with an error', () => {
    const { answer } = parse({ ...successAnswer(), summary: 'Traceback (most recent call last): ...' })
    expect(answer.internalError).toBe(true)
    expect(answer.steps).toEqual([])
    expect(answer.sources).toEqual([])
    expect(answer.escalate).toBe(true)
    expect(stepsGateOf(answer)).toBe('none')
    expect(safetyStateOf(answer)).toBe('uncertain')
  })

  it.each([
    ['Failed to parse AI response: boom', true],
    ['Traceback (most recent call last):\n  File "x"', true],
    ["KeyError: 'steps'", true],
    ['JSONDecodeError: Expecting value', true],
    ['Exception: something', true],
    ['Error E12: high discharge temperature. Check the cooler.', false],
    ['Pressure error on the gauge; check the inlet filter.', false],
    ['Intake air filter is clogged.', false],
  ])('looksLikeInternalError(%j) = %s', (text, expected) => {
    expect(looksLikeInternalError(text)).toBe(expected)
  })
})

describe('search_score', () => {
  it.each([[-1], ['0.3'], [Number.NaN], [Number.POSITIVE_INFINITY], [null], [undefined]])(
    'invalid value %j becomes null',
    (value) => {
      expect(parse({ ...successAnswer(), search_score: value }).answer.searchScore).toBeNull()
    },
  )

  it('accepts 0 for exact matches', () => {
    expect(parse({ ...successAnswer(), search_score: 0 }).answer.searchScore).toBe(0)
  })
})

describe('format detection and mixed responses', () => {
  it('detects legacy answers', () => {
    expect(parse(okAnswer()).answer.format).toBe('legacy')
  })

  it('treats a mix of legacy and current fields as mixed and stays strict', () => {
    const { answer } = parse({ ...successAnswer(), status: 'OK' })
    expect(answer.format).toBe('mixed')
    expect(safetyStateOf(answer)).toBe('uncertain')
    expect(stepsGateOf(answer)).toBe('withheld')
  })

  it('reads steps and sources that mix old and new field names', () => {
    const { answer } = parse({
      ...successAnswer(),
      steps: [
        { step_no: 2, instruction: 'Second' },
        { step_number: 1, instruction: 'First' },
      ],
      sources: [
        { manual: 'Old_Manual', page: 3 },
        { manual_title: 'New_Manual', page_number: 4 },
      ],
    })
    expect(answer.steps.map((s) => s.instruction)).toEqual(['First', 'Second'])
    expect(answer.sources).toEqual([
      { manual: 'Old_Manual', page: 3, section: null },
      { manual: 'New_Manual', page: 4, section: null },
    ])
  })
})

describe('current format: missing and invalid fields', () => {
  it('flags required fields that are missing, without inventing them', () => {
    const { answer, issues } = parse({ status: 'SUCCESS', search_score: 0.2 })
    expect(answer.summary).toBe('')
    expect(answer.steps).toEqual([])
    expect(answer.sources).toEqual([])
    expect(answer.safetyChecklist).toEqual([])
    expect(issues).toEqual(
      expect.arrayContaining([
        'answer.summary is missing',
        'answer.safety_checklist is missing',
        'answer.steps is missing',
        'answer.sources is missing',
        'answer.escalate is missing',
      ]),
    )
    expect(issues).not.toContain('answer.is_dangerous is missing')
    expect(issues).not.toContain('answer.history_note is missing')
  })

  it('uses current field names in issue messages', () => {
    const { issues } = parse({
      ...successAnswer(),
      steps: [{ instruction: 'No number' }],
      sources: [{ page_number: 3 }, { manual_title: 'M', page_number: 'x' }],
    })
    expect(issues).toContain('answer.steps[0].step_number is invalid')
    expect(issues).toContain('answer.sources[0] has no manual_title and was dropped')
    expect(issues).toContain('answer.sources[1].page_number is invalid')
  })

  it('shows a source with no page as page=null and an empty section as null', () => {
    const { answer } = parse({ ...successAnswer(), sources: [{ manual_title: 'M', section: '  ' }] })
    expect(answer.sources).toEqual([{ manual: 'M', page: null, section: null }])
  })

  it('keeps DEMO labels with the current format', () => {
    expect(parse(successAnswer(), { is_demo: true }).isDemo).toBe(true)
  })

  it.each([
    ['unknown status', { ...successAnswer(), status: 'MAYBE' }],
    ['empty status', { ...successAnswer(), status: '' }],
    ['missing status', { ...successAnswer(), status: undefined }],
    ['ERROR status', { ...successAnswer(), status: 'ERROR' }],
  ])('rejects %s as malformed', (_label, answer) => expectMalformed(answer))
})
