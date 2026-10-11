// Test-only fixtures. Shapes follow ai/schemas.py and the envelope in
// backend/main.py, mirroring backend/tests/test_voice_ask.py.
// Never import this file from application code.

export function okAnswer() {
  return {
    status: 'OK',
    problem_type: 'overheating',
    summary: 'Check the cooler and oil level.',
    is_dangerous: false,
    safety_checklist: [],
    history_note: '',
    steps: [{ step_no: 1, instruction: 'Check oil.', check_question: 'Is oil level normal?' }],
    sources: [{ manual: 'GA15-26_Instruction_Book', page: 12 }],
    escalate: false,
  }
}

export function notFoundAnswer() {
  return {
    status: 'NOT_FOUND',
    problem_type: 'other',
    summary: 'Not found in manual.',
    is_dangerous: false,
    safety_checklist: [],
    history_note: '',
    steps: [],
    sources: [],
    escalate: true,
  }
}

export function dangerousAnswer() {
  return {
    ...okAnswer(),
    is_dangerous: true,
    safety_checklist: ['Stop the machine and allow it to cool completely.', 'Release all pressure'],
  }
}

export function envelope(answer: unknown, overrides: Record<string, unknown> = {}) {
  return {
    status: 'success',
    machine_id: 'compressor-01',
    question: 'Compressor is overheating',
    answer,
    is_demo: false,
    ...overrides,
  }
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

// ---- Current format (ai/schemas.py + ai/brain.py after the AI integration) ----

export function successAnswer() {
  return {
    status: 'SUCCESS',
    problem_type: 'low_pressure',
    summary: 'Intake air filter is clogged causing insufficient pressure build-up.',
    safety_checklist: [] as string[],
    steps: [
      {
        step_number: 1,
        instruction: 'Inspect intake air filter cartridge for dust accumulation.',
        check_question: 'Is the filter cartridge clogged with debris?',
      },
      {
        step_number: 2,
        instruction: 'Clean cartridge with compressed air or replace if saturated.',
        check_question: 'Is the replacement cartridge seated securely in the housing?',
      },
    ],
    sources: [{ manual_title: 'GA15-26_Instruction_Book', page_number: 8, section: 'Pressure System' }],
    escalate: false,
    search_score: 0.312,
  }
}

/** brain.py upgrades SUCCESS to SAFETY_ALERT when safety keywords trigger a checklist. */
export function safetyAlertAnswer() {
  return {
    ...successAnswer(),
    status: 'SAFETY_ALERT',
    problem_type: 'electrical',
    summary: 'Motor terminal fault suspected.',
    safety_checklist: ['Isolate power and lock out', 'Do not touch cables'],
  }
}

/** brain.py's no-chunks response. */
export function currentNotFoundAnswer() {
  return {
    status: 'NOT_FOUND',
    problem_type: 'other',
    summary: 'This issue or error code was not found in the verified manual.',
    safety_checklist: [] as string[],
    steps: [],
    sources: [],
    escalate: true,
    search_score: null,
  }
}

/** brain.py's parse-failure response: an internal error inside `summary`. */
export function parseFailureAnswer() {
  return {
    status: 'NOT_FOUND',
    problem_type: 'other',
    summary: "Failed to parse AI response: Expecting value: line 1 column 1 (char 0) KeyError: 'steps'",
    safety_checklist: [] as string[],
    steps: [],
    sources: [],
    escalate: true,
    search_score: 0.41,
  }
}
