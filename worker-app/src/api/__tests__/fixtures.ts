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
