import { describe, expect, it } from 'vitest'
import { ApiError } from '../errors.ts'
import { parseAskResponse } from '../parse.ts'
import { dangerousAnswer, envelope, notFoundAnswer, okAnswer } from './fixtures.ts'

const req = { question: 'Compressor is overheating', machineId: 'compressor-01' }

function expectMalformed(body: unknown) {
  try {
    parseAskResponse(body, req)
    expect.unreachable('expected parseAskResponse to throw')
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError)
    expect((e as ApiError).kind).toBe('malformed')
  }
}

describe('parseAskResponse: valid responses', () => {
  it('parses an OK answer nested under `answer`', () => {
    const result = parseAskResponse(envelope(okAnswer()), req)
    expect(result.issues).toEqual([])
    expect(result.machineId).toBe('compressor-01')
    expect(result.question).toBe('Compressor is overheating')
    expect(result.isDemo).toBe(false)
    expect(result.answer).toEqual({
      status: 'OK',
      rawStatus: 'OK',
      format: 'legacy',
      searchScore: null,
      internalError: false,
      problemType: 'overheating',
      summary: 'Check the cooler and oil level.',
      isDangerous: false,
      safetyChecklist: [],
      historyNote: '',
      steps: [{ stepNo: 1, instruction: 'Check oil.', checkQuestion: 'Is oil level normal?' }],
      sources: [{ manual: 'GA15-26_Instruction_Book', page: 12, section: null }],
      escalate: false,
    })
  })

  it('recognises NOT_FOUND with escalate', () => {
    const { answer, issues } = parseAskResponse(envelope(notFoundAnswer()), req)
    expect(answer.status).toBe('NOT_FOUND')
    expect(answer.escalate).toBe(true)
    expect(answer.steps).toEqual([])
    expect(issues).toEqual([])
  })

  it('recognises is_dangerous and keeps the safety checklist', () => {
    const { answer } = parseAskResponse(envelope(dangerousAnswer()), req)
    expect(answer.isDangerous).toBe(true)
    expect(answer.safetyChecklist).toEqual([
      'Stop the machine and allow it to cool completely.',
      'Release all pressure',
    ])
  })

  it('recognises is_demo=true', () => {
    expect(parseAskResponse(envelope(okAnswer(), { is_demo: true }), req).isDemo).toBe(true)
  })

  it('keeps the machine ID exactly as the backend echoed it', () => {
    const result = parseAskResponse(envelope(okAnswer(), { machine_id: 'compressor_01' }), req)
    expect(result.machineId).toBe('compressor_01')
  })

  it('accepts manual names with or without .pdf', () => {
    const answer = { ...okAnswer(), sources: [{ manual: 'GA15-26_Instruction_Book.pdf', page: 1 }] }
    expect(parseAskResponse(envelope(answer), req).answer.sources[0]?.manual).toBe(
      'GA15-26_Instruction_Book.pdf',
    )
  })

  it('sorts steps by step_no', () => {
    const answer = {
      ...okAnswer(),
      steps: [
        { step_no: 2, instruction: 'Second', check_question: '' },
        { step_no: 1, instruction: 'First', check_question: '' },
      ],
    }
    expect(parseAskResponse(envelope(answer), req).answer.steps.map((s) => s.instruction)).toEqual([
      'First',
      'Second',
    ])
  })
})

describe('parseAskResponse: malformed responses are rejected', () => {
  it.each([
    ['null body', null],
    ['string body', 'Internal Server Error'],
    ['array body', []],
    ['missing answer', { status: 'success', machine_id: 'x', question: 'q', is_demo: false }],
    ['answer is a string', envelope('OK')],
    ['answer is null', envelope(null)],
    ['unknown answer status', envelope({ ...okAnswer(), status: 'MAYBE' })],
    ['status with a typo', envelope({ ...okAnswer(), status: 'SUCESS' })],
    ['status as a number', envelope({ ...okAnswer(), status: 200 })],
    ['missing answer status', envelope({ ...okAnswer(), status: undefined })],
  ])('%s', (_label, body) => expectMalformed(body))
})

describe('parseAskResponse: incomplete responses are repaired and flagged', () => {
  it('defaults missing lists, strings and booleans', () => {
    const { answer, issues } = parseAskResponse(envelope({ status: 'OK' }), req)
    expect(answer).toEqual({
      status: 'OK',
      rawStatus: 'OK',
      format: 'legacy',
      searchScore: null,
      internalError: false,
      problemType: 'other',
      summary: '',
      isDangerous: null,
      safetyChecklist: [],
      historyNote: '',
      steps: [],
      sources: [],
      escalate: false,
    })
    expect(issues).toEqual(
      expect.arrayContaining([
        'answer.summary is missing',
        'answer.is_dangerous is missing',
        'answer.steps is missing',
        'answer.sources is missing',
      ]),
    )
  })

  it('treats null lists as empty', () => {
    const answer = { ...okAnswer(), steps: null, sources: null, safety_checklist: null }
    const parsed = parseAskResponse(envelope(answer), req).answer
    expect(parsed.steps).toEqual([])
    expect(parsed.sources).toEqual([])
    expect(parsed.safetyChecklist).toEqual([])
  })

  it('drops steps without an instruction and numbers missing step_no by position', () => {
    const answer = {
      ...okAnswer(),
      steps: [
        { step_no: 1, instruction: '  ', check_question: 'q' },
        'not a step',
        { instruction: 'Check belt tension.' },
      ],
    }
    const { answer: parsed, issues } = parseAskResponse(envelope(answer), req)
    expect(parsed.steps).toEqual([{ stepNo: 3, instruction: 'Check belt tension.', checkQuestion: '' }])
    expect(issues).toContain('answer.steps[0] has no instruction and was dropped')
    expect(issues).toContain('answer.steps[2].step_no is invalid')
  })

  it('keeps sources with an invalid page as page=null and drops sources without a manual', () => {
    const answer = {
      ...okAnswer(),
      sources: [{ manual: 'Manual A', page: 'twelve' }, { page: 4 }, { manual: 'Manual B', page: '7' }],
    }
    expect(parseAskResponse(envelope(answer), req).answer.sources).toEqual([
      { manual: 'Manual A', page: null, section: null },
      { manual: 'Manual B', page: 7, section: null },
    ])
  })

  it('drops empty safety checklist items', () => {
    const answer = { ...dangerousAnswer(), safety_checklist: ['Isolate power', '', 42, '  '] }
    expect(parseAskResponse(envelope(answer), req).answer.safetyChecklist).toEqual(['Isolate power'])
  })

  it.each([['yes'], ['false'], [0], [null]])('treats is_dangerous=%j as unknown (null), not safe', (value) => {
    const { answer, issues } = parseAskResponse(envelope({ ...okAnswer(), is_dangerous: value }), req)
    expect(answer.isDangerous).toBeNull()
    expect(issues).toContain('answer.is_dangerous is not a boolean')
  })

  it('forces escalate=true and no steps for NOT_FOUND even if the backend disagrees', () => {
    const answer = { ...notFoundAnswer(), escalate: false, steps: okAnswer().steps }
    const { answer: parsed, issues } = parseAskResponse(envelope(answer), req)
    expect(parsed.escalate).toBe(true)
    expect(parsed.steps).toEqual([])
    expect(issues).toContain('answer.escalate was false for NOT_FOUND')
  })

  it('falls back to request values for missing echoed fields', () => {
    const body = { status: 'success', answer: okAnswer() }
    const result = parseAskResponse(body, req)
    expect(result.machineId).toBe('compressor-01')
    expect(result.question).toBe('Compressor is overheating')
    expect(result.isDemo).toBe(false)
    expect(result.issues).toEqual(
      expect.arrayContaining(['machine_id is missing', 'question is missing', 'is_demo is missing']),
    )
  })

  it('treats a non-boolean is_demo as not demo', () => {
    expect(parseAskResponse(envelope(okAnswer(), { is_demo: 'true' }), req).isDemo).toBe(false)
  })
})
