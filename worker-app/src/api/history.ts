import { ApiError } from './errors.ts'

// GET /history/{machine_id} (backend/main.py):
//   200 { status: "success", machine_id, history: rows[] }
//   503 { detail: "Could not retrieve repair history." }
// Rows are select("*") from the Supabase repair_history table, newest first
// (order by created_at desc), at most 50. The repo has no table definition;
// the backend only guarantees machine_id, problem, action, outcome (POST
// /history writes these; outcome defaults to "") and created_at (used for
// ordering). Unknown columns are ignored, never interpreted.

/** Backend row limit for GET /history/{machine_id}. */
export const HISTORY_LIMIT = 50

export interface RepairRecord {
  /** Stable key: the row id when present, otherwise the row position. */
  key: string
  /** created_at exactly as received, or null if missing/invalid. */
  recordedAtRaw: string | null
  recordedAt: Date | null
  /** null means the field was missing or empty; it is shown as absent. */
  problem: string | null
  action: string | null
  outcome: string | null
}

export interface RepairHistoryResult {
  machineId: string
  records: RepairRecord[]
  /** Rows that were dropped or fields that were unusable. */
  issues: string[]
}

type Json = Record<string, unknown>

const MALFORMED_MESSAGE = 'The repair history could not be read. Please try again.'

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : null
}

function parseTimestamp(value: unknown): { raw: string | null; date: Date | null } {
  if (typeof value !== 'string' || value.trim() === '') return { raw: null, date: null }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? { raw: null, date: null } : { raw: value, date }
}

/**
 * Validates GET /history/{machine_id}. Keeps backend order (newest first).
 * @throws ApiError('malformed') if there is no `history` list.
 */
export function parseRepairHistory(body: unknown, requestedMachineId: string): RepairHistoryResult {
  if (!isObject(body) || !Array.isArray(body.history)) {
    throw new ApiError('malformed', MALFORMED_MESSAGE)
  }

  const issues: string[] = []
  if (body.status !== 'success') issues.push('status is not "success"')

  const records: RepairRecord[] = []
  body.history.forEach((row, index) => {
    if (!isObject(row)) {
      issues.push(`history[${index}] is not a record and was dropped`)
      return
    }
    // The backend filters by machine_id; a row for another machine must never be shown.
    if (row.machine_id !== undefined && row.machine_id !== requestedMachineId) {
      issues.push(`history[${index}] is for a different machine and was dropped`)
      return
    }

    const problem = text(row.problem)
    const action = text(row.action)
    const outcome = text(row.outcome)
    if (!problem && !action && !outcome) {
      issues.push(`history[${index}] has no problem, action or outcome and was dropped`)
      return
    }

    const { raw, date } = parseTimestamp(row.created_at)
    if (!date) issues.push(`history[${index}].created_at is ${row.created_at === undefined ? 'missing' : 'invalid'}`)

    const id = typeof row.id === 'string' || typeof row.id === 'number' ? String(row.id) : null
    records.push({
      key: id ?? `row-${index}`,
      recordedAtRaw: raw,
      recordedAt: date,
      problem,
      action,
      outcome,
    })
  })

  return { machineId: requestedMachineId, records, issues }
}
