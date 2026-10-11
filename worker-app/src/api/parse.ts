import { ApiError } from './errors.ts'
import type {
  AnswerStatus,
  AskResult,
  SourceReference,
  TroubleshootingAnswer,
  TroubleshootingStep,
} from './types.ts'

// Turns an untrusted /ask body into an AskResult.
//
// Policy:
// - The envelope and `answer` must be objects and `answer.status` must be
//   OK or NOT_FOUND; otherwise the response is rejected as malformed, because
//   rendering steps from a response we cannot interpret is unsafe.
// - Everything else is repaired field by field (missing list -> [], missing
//   string -> "", invalid items dropped) and each repair is recorded in
//   `issues` so the UI can flag an incomplete answer.
// - Safety flags fail safe: NOT_FOUND always escalates, and a missing or
//   non-boolean is_dangerous becomes null (unknown), never false.

type Json = Record<string, unknown>

const MALFORMED_MESSAGE = 'The assistant sent a response the app could not read. Please try again.'

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : null
}

function readString(obj: Json, key: string, issues: string[], prefix: string): string {
  const value = obj[key]
  if (typeof value === 'string') return value.trim()
  if (value !== undefined && value !== null) issues.push(`${prefix}${key} is not a string`)
  else issues.push(`${prefix}${key} is missing`)
  return ''
}

function readBoolean(obj: Json, key: string, issues: string[], prefix: string): boolean {
  const value = obj[key]
  if (typeof value === 'boolean') return value
  issues.push(`${prefix}${key} is ${value === undefined ? 'missing' : 'not a boolean'}`)
  return false
}

function readOptionalBoolean(obj: Json, key: string, issues: string[], prefix: string): boolean | null {
  const value = obj[key]
  if (typeof value === 'boolean') return value
  issues.push(`${prefix}${key} is ${value === undefined ? 'missing' : 'not a boolean'}`)
  return null
}

function readArray(obj: Json, key: string, issues: string[], prefix: string): unknown[] {
  const value = obj[key]
  if (Array.isArray(value)) return value
  issues.push(`${prefix}${key} is ${value === undefined || value === null ? 'missing' : 'not a list'}`)
  return []
}

function toPositiveInt(value: unknown): number | null {
  const n = typeof value === 'string' && value.trim() !== '' ? Number(value) : value
  return typeof n === 'number' && Number.isInteger(n) && n > 0 ? n : null
}

function parseSteps(raw: unknown[], issues: string[]): TroubleshootingStep[] {
  const steps: TroubleshootingStep[] = []
  raw.forEach((item, index) => {
    const instruction = isObject(item) ? nonEmptyString(item.instruction) : null
    if (!isObject(item) || !instruction) {
      issues.push(`answer.steps[${index}] has no instruction and was dropped`)
      return
    }
    const stepNo = toPositiveInt(item.step_no)
    if (stepNo === null) issues.push(`answer.steps[${index}].step_no is invalid`)
    const checkQuestion = typeof item.check_question === 'string' ? item.check_question.trim() : ''
    steps.push({ stepNo: stepNo ?? index + 1, instruction, checkQuestion })
  })
  // Stable sort keeps backend order for equal step numbers.
  return steps.sort((a, b) => a.stepNo - b.stepNo)
}

function parseSources(raw: unknown[], issues: string[]): SourceReference[] {
  const sources: SourceReference[] = []
  raw.forEach((item, index) => {
    const manual = isObject(item) ? nonEmptyString(item.manual) : null
    if (!isObject(item) || !manual) {
      issues.push(`answer.sources[${index}] has no manual and was dropped`)
      return
    }
    const page = toPositiveInt(item.page)
    if (page === null) issues.push(`answer.sources[${index}].page is invalid`)
    sources.push({ manual, page })
  })
  return sources
}

function parseChecklist(raw: unknown[], issues: string[]): string[] {
  const items: string[] = []
  raw.forEach((item, index) => {
    const text = nonEmptyString(item)
    if (text) items.push(text)
    else issues.push(`answer.safety_checklist[${index}] is empty and was dropped`)
  })
  return items
}

function parseAnswer(raw: Json, issues: string[]): TroubleshootingAnswer {
  const p = 'answer.'
  const status = raw.status
  if (status !== 'OK' && status !== 'NOT_FOUND') {
    throw new ApiError('malformed', MALFORMED_MESSAGE)
  }

  const problemType = nonEmptyString(raw.problem_type)
  if (raw.problem_type !== null && raw.problem_type !== undefined && !problemType) {
    issues.push(`${p}problem_type is invalid`)
  }

  const answer: TroubleshootingAnswer = {
    status: status as AnswerStatus,
    problemType: problemType ?? 'other',
    summary: readString(raw, 'summary', issues, p),
    isDangerous: readOptionalBoolean(raw, 'is_dangerous', issues, p),
    safetyChecklist: parseChecklist(readArray(raw, 'safety_checklist', issues, p), issues),
    historyNote: readString(raw, 'history_note', issues, p),
    steps: parseSteps(readArray(raw, 'steps', issues, p), issues),
    sources: parseSources(readArray(raw, 'sources', issues, p), issues),
    escalate: readBoolean(raw, 'escalate', issues, p),
  }

  // NOT_FOUND means the manuals had no answer: always escalate, never show steps.
  if (answer.status === 'NOT_FOUND') {
    if (!answer.escalate) issues.push('answer.escalate was false for NOT_FOUND')
    answer.escalate = true
    if (answer.steps.length > 0) issues.push('answer.steps were ignored for NOT_FOUND')
    answer.steps = []
  }

  return answer
}

/**
 * Validates and normalizes a /ask (or /voice-ask) response body.
 * `request` supplies fallbacks for echoed fields the backend may omit.
 * @throws ApiError('malformed') if the body cannot be interpreted safely.
 */
export function parseAskResponse(
  body: unknown,
  request: { question: string; machineId: string },
): AskResult {
  if (!isObject(body) || !isObject(body.answer)) {
    throw new ApiError('malformed', MALFORMED_MESSAGE)
  }

  const issues: string[] = []
  if (body.status !== 'success') issues.push('status is not "success"')

  const answer = parseAnswer(body.answer, issues)

  const machineId = typeof body.machine_id === 'string' ? body.machine_id : request.machineId
  if (typeof body.machine_id !== 'string') issues.push('machine_id is missing')

  const question = typeof body.question === 'string' ? body.question : request.question
  if (typeof body.question !== 'string') issues.push('question is missing')

  if (typeof body.is_demo !== 'boolean') issues.push('is_demo is missing')
  const isDemo = body.is_demo === true

  return { machineId, question, isDemo, answer, issues }
}
