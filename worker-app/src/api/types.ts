// Types mirroring the backend contract.
//
// Wire types (`*Wire`) describe exactly what FastAPI sends, from
// backend/main.py (AskRequest, /ask envelope) and ai/schemas.py (QueryResponse).
// The app never renders wire types directly: they are run through
// parseAskResponse() first, which produces the normalized types below.

// ---------- Request ----------

/** Body of POST /ask (backend/main.py `AskRequest`). */
export interface AskRequest {
  question: string
  machine_id: string
}

// ---------- Wire response ----------

/** ai/schemas.py `StepItem`. */
export interface StepItemWire {
  step_no: number
  instruction: string
  check_question: string
}

/** ai/schemas.py `SourceReference`. `page` is the PDF page number. */
export interface SourceReferenceWire {
  manual: string
  page: number
}

export type AnswerStatus = 'OK' | 'NOT_FOUND'

/** ai/schemas.py `QueryResponse`, nested under `answer` in the envelope. */
export interface QueryResponseWire {
  status: AnswerStatus
  problem_type: string | null
  summary: string
  is_dangerous: boolean
  safety_checklist: string[]
  history_note: string
  steps: StepItemWire[]
  sources: SourceReferenceWire[]
  escalate: boolean
}

/** Envelope returned by POST /ask (and /voice-ask) on HTTP 200. */
export interface AskResponseWire {
  status: 'success'
  machine_id: string
  question: string
  answer: QueryResponseWire
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
}

export interface TroubleshootingAnswer {
  status: AnswerStatus
  problemType: string
  summary: string
  /**
   * true/false only when the backend sent a real boolean. null means the
   * safety state is unknown and must be treated as uncertain, never as safe.
   */
  isDangerous: boolean | null
  safetyChecklist: string[]
  historyNote: string
  steps: TroubleshootingStep[]
  sources: SourceReference[]
  escalate: boolean
}

export interface AskResult {
  machineId: string
  question: string
  isDemo: boolean
  answer: TroubleshootingAnswer
  /**
   * Fields that were missing or invalid and had to be defaulted or dropped.
   * Empty for a response that fully matches the contract.
   */
  issues: string[]
}

export interface HealthResult {
  ok: boolean
  status: string
}
