// Types mirroring the backend contract.
//
// Wire types (`*Wire`) describe exactly what FastAPI sends. The envelope comes
// from backend/main.py; the nested `answer` comes from ai/brain.py using
// ai/schemas.py `QueryResponse`. Two answer formats exist:
//
// - legacy:  the original contract (OK/NOT_FOUND, is_dangerous, history_note,
//            step_no, manual/page).
// - current: ai/schemas.py after the AI integration (SUCCESS/NOT_FOUND/
//            SAFETY_ALERT, step_number, manual_title/page_number/section,
//            search_score; no is_dangerous or history_note).
//
// The app never renders wire types directly: they are run through
// parseAskResponse() first, which produces the normalized types below.

// ---------- Request ----------

/** Body of POST /ask (backend/main.py `AskRequest`). */
export interface AskRequest {
  question: string
  machine_id: string
}

// ---------- Wire response: legacy answer ----------

export interface LegacyStepItemWire {
  step_no: number
  instruction: string
  check_question: string
}

export interface LegacySourceReferenceWire {
  manual: string
  page: number
}

export interface LegacyQueryResponseWire {
  status: 'OK' | 'NOT_FOUND'
  problem_type: string | null
  summary: string
  is_dangerous: boolean
  safety_checklist: string[]
  history_note: string
  steps: LegacyStepItemWire[]
  sources: LegacySourceReferenceWire[]
  escalate: boolean
}

// ---------- Wire response: current answer (ai/schemas.py) ----------

export interface StepItemWire {
  step_number: number
  instruction: string
  check_question: string
}

export interface SourceReferenceWire {
  manual_title: string
  page_number: number
  section?: string | null
}

export interface QueryResponseWire {
  /** Filled by the model; 'SUCCESS' | 'NOT_FOUND' | 'SAFETY_ALERT' expected. */
  status: string
  problem_type?: string | null
  summary: string
  safety_checklist: string[]
  steps: StepItemWire[]
  sources: SourceReferenceWire[]
  escalate: boolean
  /** Vector distance of the best manual chunk. Not a confidence or safety value. */
  search_score?: number | null
}

// ---------- Envelope ----------

/** Envelope returned by POST /ask (and /voice-ask) on HTTP 200. */
export interface AskResponseWire {
  status: 'success'
  machine_id: string
  question: string
  answer: QueryResponseWire | LegacyQueryResponseWire
  is_demo: boolean
}

/** GET /health. */
export interface HealthResponseWire {
  status: string
}

/** FastAPI error body. 422 validation errors use the array form. */
export interface ErrorResponseWire {
  detail?: string | Array<{ loc?: unknown[]; msg?: string; type?: string }>
}

// ---------- Normalized (what the UI consumes) ----------

export interface TroubleshootingStep {
  stepNo: number
  instruction: string
  checkQuestion: string
}

export interface SourceReference {
  manual: string
  /** PDF page number, or null if the backend sent an unusable value. */
  page: number | null
  /** Manual section, or null when not provided. */
  section: string | null
}

/**
 * Normalized status. 'OK' covers legacy OK and current SUCCESS.
 * 'SAFETY_ALERT' always requires escalation and withholds steps.
 */
export type AnswerStatus = 'OK' | 'NOT_FOUND' | 'SAFETY_ALERT'

/** Which contract the answer appears to follow; see the header comment. */
export type AnswerFormat = 'legacy' | 'current' | 'mixed'

export interface TroubleshootingAnswer {
  status: AnswerStatus
  /** Status exactly as received (trimmed), e.g. 'SUCCESS'. */
  rawStatus: string
  format: AnswerFormat
  problemType: string
  summary: string
  /**
   * true/false only when the backend sent a real boolean (legacy format).
   * null means not provided; safety.ts decides what that implies.
   */
  isDangerous: boolean | null
  safetyChecklist: string[]
  historyNote: string
  steps: TroubleshootingStep[]
  sources: SourceReference[]
  escalate: boolean
  /** Retrieval distance (lower = closer). Never shown to workers. */
  searchScore: number | null
  /**
   * The backend reported an internal failure (e.g. it could not parse the AI
   * output). The raw error text is discarded and never shown or spoken.
   */
  internalError: boolean
}

export interface AskResult {
  machineId: string
  question: string
  isDemo: boolean
  answer: TroubleshootingAnswer
  /**
   * Fields that were missing or invalid and had to be defaulted or dropped.
   * Empty for a response that fully matches its contract.
   */
  issues: string[]
}

export interface HealthResult {
  ok: boolean
  status: string
}
