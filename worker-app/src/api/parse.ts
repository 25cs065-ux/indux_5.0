import { ApiError } from './errors.ts'
import type {
  AnswerFormat,
  AnswerStatus,
  AskResult,
  SourceReference,
  TroubleshootingAnswer,
  TroubleshootingStep,
} from './types.ts'

// Turns an untrusted /ask body into an AskResult. Accepts the legacy and the
// current answer formats (see types.ts).
//
// Policy:
// - The envelope and `answer` must be objects, and `answer.status` must be a
//   known status (OK/SUCCESS, NOT_FOUND, SAFETY_ALERT, case-insensitive).
//   Anything else is rejected as malformed: rendering steps from a response
//   we cannot interpret is unsafe.
// - Field names are read from either format (step_number/step_no,
//   manual_title/manual, page_number/page). Nothing is invented: missing
//   lists become [], missing strings "", invalid items are dropped, and each
//   repair is recorded in `issues`, but only for fields the detected format
//   actually requires.
// - Safety facts are passed through untouched (is_dangerous stays null when
//   absent). src/lib/safety.ts decides what they mean.
// - NOT_FOUND always escalates and never carries steps.
// - Internal backend errors placed in `summary` (e.g. "Failed to parse AI
//   response: ...") are detected and discarded, never shown or spoken.

type Json = Record<string, unknown>

const MALFORMED_MESSAGE = 'The assistant sent a response the app could not read. Please try again.'

const STATUS_MAP: Record<string, AnswerStatus> = {
  OK: 'OK',
  SUCCESS: 'OK',
  NOT_FOUND: 'NOT_FOUND',
  SAFETY_ALERT: 'SAFETY_ALERT',
}

/** Keys only the legacy format sends. */
const LEGACY_KEYS = ['is_dangerous', 'history_note'] as const
/** Keys only the current format sends. */
const CURRENT_KEYS = ['search_score'] as const

/**
 * Patterns that identify backend error text rather than a diagnosis:
 * ai/brain.py's parse-failure summary, Python tracebacks, and
 * "SomethingError: ..." / "Exception: ..." messages.
 */
const INTERNAL_ERROR_PATTERNS = [
  /^\s*failed to parse ai response/i,
  /traceback \(most recent call last\)/i,
  /\b[A-Z][A-Za-z]*(Error|Exception):\s/,
  /^\s*Exception:\s/,
]

export function looksLikeInternalError(text: string): boolean {
  return INTERNAL_ERROR_PATTERNS.some((re) => re.test(text))
}

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : null
}

function has(obj: Json, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key)
}

/** First key present on the object, so issues can name the real field. */
function firstKey(obj: Json, keys: string[]): string {
  return keys.find((k) => has(obj, k) && obj[k] !== undefined && obj[k] !== null) ?? keys[0]!
}

function readString(obj: Json, key: string, issues: string[], prefix: string, required = true): string {
  const value = obj[key]
  if (typeof value === 'string') return value.trim()
  if (value !== undefined && value !== null) issues.push(`${prefix}${key} is not a string`)
  else if (required) issues.push(`${prefix}${key} is missing`)
  return ''
}

function readBoolean(obj: Json, key: string, issues: string[], prefix: string): boolean {
  const value = obj[key]
  if (typeof value === 'boolean') return value
  issues.push(`${prefix}${key} is ${value === undefined ? 'missing' : 'not a boolean'}`)
  return false
}

function readOptionalBoolean(
  obj: Json,
  key: string,
  issues: string[],
  prefix: string,
  required: boolean,
): boolean | null {
  const value = obj[key]
  if (typeof value === 'boolean') return value
  if (value !== undefined) issues.push(`${prefix}${key} is not a boolean`)
  else if (required) issues.push(`${prefix}${key} is missing`)
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

function toDistance(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
}

function detectFormat(raw: Json, rawStatus: string): AnswerFormat {
  const steps = Array.isArray(raw.steps) ? raw.steps.filter(isObject) : []
  const sources = Array.isArray(raw.sources) ? raw.sources.filter(isObject) : []

  const legacy =
    LEGACY_KEYS.some((k) => has(raw, k)) ||
    rawStatus === 'OK' ||
    steps.some((s) => has(s, 'step_no')) ||
    sources.some((s) => has(s, 'manual') || has(s, 'page'))
  const current =
    CURRENT_KEYS.some((k) => has(raw, k)) ||
    rawStatus === 'SUCCESS' ||
    rawStatus === 'SAFETY_ALERT' ||
    steps.some((s) => has(s, 'step_number')) ||
    sources.some((s) => has(s, 'manual_title') || has(s, 'page_number') || has(s, 'section'))

  if (current && !legacy) return 'current'
  if (legacy && !current) return 'legacy'
  // Both or neither: unclear contract, safety.ts treats this strictly.
  return 'mixed'
}

function parseSteps(raw: unknown[], issues: string[], legacy: boolean): TroubleshootingStep[] {
  const keys = legacy ? ['step_no', 'step_number'] : ['step_number', 'step_no']
  const steps: TroubleshootingStep[] = []
  raw.forEach((item, index) => {
    const instruction = isObject(item) ? nonEmptyString(item.instruction) : null
    if (!isObject(item) || !instruction) {
      issues.push(`answer.steps[${index}] has no instruction and was dropped`)
      return
    }
    const key = firstKey(item, keys)
    const stepNo = toPositiveInt(item[key])
    if (stepNo === null) issues.push(`answer.steps[${index}].${key} is invalid`)
    const checkQuestion = typeof item.check_question === 'string' ? item.check_question.trim() : ''
    steps.push({ stepNo: stepNo ?? index + 1, instruction, checkQuestion })
  })
  // Stable sort keeps backend order for equal step numbers.
  return steps.sort((a, b) => a.stepNo - b.stepNo)
}

function parseSources(raw: unknown[], issues: string[], legacy: boolean): SourceReference[] {
  const pageKeys = legacy ? ['page', 'page_number'] : ['page_number', 'page']
  const sources: SourceReference[] = []
  raw.forEach((item, index) => {
    const manual = isObject(item) ? (nonEmptyString(item.manual_title) ?? nonEmptyString(item.manual)) : null
    if (!isObject(item) || !manual) {
      issues.push(`answer.sources[${index}] has no ${legacy ? 'manual' : 'manual_title'} and was dropped`)
      return
    }
    const pageKey = firstKey(item, pageKeys)
    const page = toPositiveInt(item[pageKey])
    if (page === null) issues.push(`answer.sources[${index}].${pageKey} is invalid`)
    const section = nonEmptyString(item.section)
    sources.push({ manual, page, section })
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
  const rawStatus = typeof raw.status === 'string' ? raw.status.trim() : ''
  const status = STATUS_MAP[rawStatus.toUpperCase()]
  if (!status) throw new ApiError('malformed', MALFORMED_MESSAGE)

  const format = detectFormat(raw, rawStatus.toUpperCase())
  const legacy = format === 'legacy'

  const problemType = nonEmptyString(raw.problem_type)
  if (raw.problem_type !== null && raw.problem_type !== undefined && !problemType) {
    issues.push(`${p}problem_type is invalid`)
  }

  let summary = readString(raw, 'summary', issues, p)
  let internalError = false
  if (summary && looksLikeInternalError(summary)) {
    // Never keep the raw error text.
    summary = ''
    internalError = true
    issues.push('internal error text from the backend was hidden')
  }

  const answer: TroubleshootingAnswer = {
    status,
    rawStatus,
    format,
    problemType: problemType ?? 'other',
    summary,
    isDangerous: readOptionalBoolean(raw, 'is_dangerous', issues, p, legacy),
    safetyChecklist: parseChecklist(readArray(raw, 'safety_checklist', issues, p), issues),
    historyNote: readString(raw, 'history_note', issues, p, legacy),
    steps: parseSteps(readArray(raw, 'steps', issues, p), issues, legacy),
    sources: parseSources(readArray(raw, 'sources', issues, p), issues, legacy),
    escalate: readBoolean(raw, 'escalate', issues, p),
    searchScore: toDistance(raw.search_score),
    internalError,
  }

  // NOT_FOUND means the manuals had no answer: always escalate, never show steps.
  if (answer.status === 'NOT_FOUND') {
    if (!answer.escalate) issues.push('answer.escalate was false for NOT_FOUND')
    answer.escalate = true
    if (answer.steps.length > 0) issues.push('answer.steps were ignored for NOT_FOUND')
    answer.steps = []
  }

  // A backend failure is not guidance: no steps, no references, escalate.
  if (internalError) {
    answer.steps = []
    answer.sources = []
    answer.escalate = true
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
