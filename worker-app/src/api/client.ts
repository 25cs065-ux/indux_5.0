import { apiUrl } from '../config.ts'
import { ApiError } from './errors.ts'
import { parseRepairHistory } from './history.ts'
import type { RepairHistoryResult } from './history.ts'
import { parseAskResponse } from './parse.ts'
import type { AskRequest, AskResult, ErrorResponseWire, HealthResult } from './types.ts'

/** Gemini plus retrieval can take a while; give /ask generous headroom. */
export const ASK_TIMEOUT_MS = 45_000
export const HEALTH_TIMEOUT_MS = 5_000

export interface RequestOptions {
  /** Cancels the request, e.g. when the worker submits a newer question. */
  signal?: AbortSignal
  timeoutMs?: number
}

const DEFAULT_MESSAGES = {
  unavailable: 'The assistant is temporarily unavailable. Please try again in a moment.',
  network: 'Cannot reach the Indux server. Check your connection and try again.',
  gateway: 'The Indux server is not responding. Please try again in a moment.',
  timeout: 'The assistant took too long to respond. Please try again.',
  aborted: 'The request was cancelled.',
  validation: 'The request was not accepted. Please check your question and machine ID.',
  http: 'Something went wrong on the server. Please try again.',
} as const

/** Extracts a readable message from a FastAPI `detail` (string or 422 array). */
function detailMessage(body: unknown): string | null {
  if (typeof body !== 'object' || body === null) return null
  const detail = (body as ErrorResponseWire).detail
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (Array.isArray(detail)) {
    const messages = detail
      .map((d) => (d && typeof d.msg === 'string' ? d.msg : null))
      .filter((m): m is string => !!m)
    if (messages.length) return messages.join('; ')
  }
  return null
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return undefined
  }
}

function errorForStatus(status: number, body: unknown): ApiError {
  const detail = detailMessage(body)
  if (status === 422) return new ApiError('validation', detail ?? DEFAULT_MESSAGES.validation, status)
  // The backend's 503 detail is already written for end users.
  if (status === 503) return new ApiError('unavailable', detail ?? DEFAULT_MESSAGES.unavailable, status)
  // 502/504 come from a gateway or the dev proxy when the backend is down.
  if (status === 502 || status === 504) return new ApiError('unavailable', DEFAULT_MESSAGES.gateway, status)
  // Other statuses may carry internal details; show a generic message.
  return new ApiError('http', DEFAULT_MESSAGES.http, status)
}

/**
 * fetch() with a timeout and caller cancellation, translating every failure
 * into an ApiError. Resolves with the parsed JSON body of a 2xx response
 * (undefined if the body is not JSON).
 *
 * Cancellation and timeouts do not depend on fetch() honouring the abort
 * signal: both the request and the body read are raced against it, so a
 * network layer that never settles cannot leave the app stuck loading.
 */
async function requestJson(path: string, init: RequestInit, options: RequestOptions, defaultTimeout: number): Promise<unknown> {
  if (options.signal?.aborted) throw new ApiError('aborted', DEFAULT_MESSAGES.aborted)

  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, options.timeoutMs ?? defaultTimeout)

  const onCallerAbort = () => controller.abort()
  options.signal?.addEventListener('abort', onCallerAbort, { once: true })

  const aborted = new Promise<never>((_, reject) => {
    controller.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {
      once: true,
    })
  })
  // Avoid an unhandled rejection when the request finishes normally.
  aborted.catch(() => {})

  try {
    let response: Response
    try {
      response = await Promise.race([
        fetch(apiUrl(path), {
          ...init,
          headers: { Accept: 'application/json', ...init.headers },
          signal: controller.signal,
        }),
        aborted,
      ])
    } catch {
      if (timedOut) throw new ApiError('timeout', DEFAULT_MESSAGES.timeout)
      if (controller.signal.aborted) throw new ApiError('aborted', DEFAULT_MESSAGES.aborted)
      throw new ApiError('network', DEFAULT_MESSAGES.network)
    }

    let body: unknown
    try {
      body = await Promise.race([readJson(response), aborted])
    } catch {
      // Only the abort race can reject here; readJson never throws.
      body = undefined
    }
    // A timeout can fire while the body is still downloading.
    if (timedOut) throw new ApiError('timeout', DEFAULT_MESSAGES.timeout)
    if (controller.signal.aborted) throw new ApiError('aborted', DEFAULT_MESSAGES.aborted)

    if (!response.ok) throw errorForStatus(response.status, body)
    return body
  } finally {
    clearTimeout(timer)
    options.signal?.removeEventListener('abort', onCallerAbort)
  }
}

/**
 * POST /ask. Used for both typed and transcribed questions.
 * The machine ID is sent exactly as given (no normalization).
 */
export async function askQuestion(question: string, machineId: string, options: RequestOptions = {}): Promise<AskResult> {
  const trimmedQuestion = question.trim()
  if (!trimmedQuestion) throw new ApiError('validation', 'Please describe the problem before sending.')
  if (!machineId.trim()) throw new ApiError('validation', 'Please enter the machine ID before sending.')

  const payload: AskRequest = { question: trimmedQuestion, machine_id: machineId }
  const body = await requestJson(
    '/ask',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    options,
    ASK_TIMEOUT_MS,
  )
  return parseAskResponse(body, { question: trimmedQuestion, machineId })
}

/** GET /health. Resolves with ok=false instead of throwing on unexpected bodies. */
export async function getHealth(options: RequestOptions = {}): Promise<HealthResult> {
  const body = await requestJson('/health', { method: 'GET' }, options, HEALTH_TIMEOUT_MS)
  const status =
    typeof body === 'object' && body !== null && typeof (body as { status?: unknown }).status === 'string'
      ? (body as { status: string }).status
      : 'unknown'
  return { ok: status === 'ok', status }
}

export const HISTORY_TIMEOUT_MS = 15_000

/**
 * GET /history/{machine_id}. Read-only. The machine ID is sent exactly as
 * given (URL-encoded, never normalized).
 */
export async function getRepairHistory(machineId: string, options: RequestOptions = {}): Promise<RepairHistoryResult> {
  if (!machineId.trim()) throw new ApiError('validation', 'Select a machine to see its repair history.')
  const body = await requestJson(
    `/history/${encodeURIComponent(machineId)}`,
    { method: 'GET' },
    options,
    HISTORY_TIMEOUT_MS,
  )
  return parseRepairHistory(body, machineId)
}
