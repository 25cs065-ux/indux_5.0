import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ASK_TIMEOUT_MS, askQuestion, getHealth } from '../client.ts'
import { ApiError } from '../errors.ts'
import { envelope, jsonResponse, notFoundAnswer, okAnswer } from './fixtures.ts'

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

async function catchApiError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError)
    return e as ApiError
  }
  throw new Error('expected promise to reject')
}

/** A fetch that never resolves until its signal aborts, like a hung server. */
function hangingFetch() {
  fetchMock.mockImplementation(
    (_input, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () =>
          reject(new DOMException('The operation was aborted.', 'AbortError')),
        )
      }),
  )
}

describe('askQuestion request', () => {
  it('POSTs JSON to /api/ask through the dev proxy', async () => {
    fetchMock.mockResolvedValue(jsonResponse(envelope(okAnswer())))
    await askQuestion('Compressor is overheating', 'compressor-01')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/ask')
    expect(init?.method).toBe('POST')
    expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json')
    expect(JSON.parse(init?.body as string)).toEqual({
      question: 'Compressor is overheating',
      machine_id: 'compressor-01',
    })
  })

  it('trims the question but sends the machine ID unchanged', async () => {
    fetchMock.mockResolvedValue(jsonResponse(envelope(okAnswer())))
    await askQuestion('  Pressure kam aa raha hai  ', 'Compressor_01')
    const body = JSON.parse(fetchMock.mock.calls[0]![1]?.body as string)
    expect(body).toEqual({ question: 'Pressure kam aa raha hai', machine_id: 'Compressor_01' })
  })

  it.each([
    ['empty question', '', 'compressor-01'],
    ['whitespace question', '   \n', 'compressor-01'],
    ['empty machine ID', 'Overheating', ''],
    ['whitespace machine ID', 'Overheating', '   '],
  ])('rejects %s without calling the server', async (_label, question, machineId) => {
    const err = await catchApiError(askQuestion(question, machineId))
    expect(err.kind).toBe('validation')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('askQuestion responses', () => {
  it('returns the parsed nested answer', async () => {
    fetchMock.mockResolvedValue(jsonResponse(envelope(okAnswer())))
    const result = await askQuestion('Compressor is overheating', 'compressor-01')
    expect(result.answer.status).toBe('OK')
    expect(result.answer.steps[0]?.instruction).toBe('Check oil.')
    expect(result.answer.sources[0]).toEqual({ manual: 'GA15-26_Instruction_Book', page: 12 })
  })

  it('returns NOT_FOUND answers as results, not errors', async () => {
    fetchMock.mockResolvedValue(jsonResponse(envelope(notFoundAnswer())))
    const result = await askQuestion('How to bake cookies', 'compressor-01')
    expect(result.answer.status).toBe('NOT_FOUND')
    expect(result.answer.escalate).toBe(true)
  })

  it('maps 422 with a string detail to a validation error', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'transcript must not be empty.' }, 422))
    const err = await catchApiError(askQuestion('x', 'compressor-01'))
    expect(err.kind).toBe('validation')
    expect(err.status).toBe(422)
    expect(err.message).toBe('transcript must not be empty.')
  })

  it('maps 422 with a Pydantic detail array to a validation error', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          detail: [
            { loc: ['body', 'question'], msg: 'Field required', type: 'missing' },
            { loc: ['body', 'machine_id'], msg: 'Input should be a valid string', type: 'string_type' },
          ],
        },
        422,
      ),
    )
    const err = await catchApiError(askQuestion('x', 'compressor-01'))
    expect(err.kind).toBe('validation')
    expect(err.message).toBe('Field required; Input should be a valid string')
  })

  it('maps 503 to unavailable using the backend detail', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: 'The AI or database service is temporarily unavailable.' }, 503),
    )
    const err = await catchApiError(askQuestion('x', 'compressor-01'))
    expect(err.kind).toBe('unavailable')
    expect(err.status).toBe(503)
    expect(err.retryable).toBe(true)
    expect(err.message).toBe('The AI or database service is temporarily unavailable.')
  })

  it('maps 503 without a JSON body to a default message', async () => {
    fetchMock.mockResolvedValue(new Response('Service Unavailable', { status: 503 }))
    const err = await catchApiError(askQuestion('x', 'compressor-01'))
    expect(err.kind).toBe('unavailable')
    expect(err.message).toMatch(/temporarily unavailable/i)
  })

  it('does not leak internal details from other error statuses', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Traceback: KeyError SUPABASE_KEY' }, 500))
    const err = await catchApiError(askQuestion('x', 'compressor-01'))
    expect(err.kind).toBe('http')
    expect(err.status).toBe(500)
    expect(err.message).not.toContain('SUPABASE')
  })

  it('maps a proxy 502 (backend down in dev) to an http error', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 502 }))
    const err = await catchApiError(askQuestion('x', 'compressor-01'))
    expect(err.kind).toBe('http')
    expect(err.status).toBe(502)
  })

  it('maps fetch failures to network errors', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    const err = await catchApiError(askQuestion('x', 'compressor-01'))
    expect(err.kind).toBe('network')
    expect(err.retryable).toBe(true)
  })

  it('rejects a 200 response with a non-JSON body as malformed', async () => {
    fetchMock.mockResolvedValue(new Response('<html>oops</html>', { status: 200 }))
    const err = await catchApiError(askQuestion('x', 'compressor-01'))
    expect(err.kind).toBe('malformed')
  })

  it('rejects a 200 response with an unknown answer status as malformed', async () => {
    fetchMock.mockResolvedValue(jsonResponse(envelope({ ...okAnswer(), status: 'ERROR' })))
    const err = await catchApiError(askQuestion('x', 'compressor-01'))
    expect(err.kind).toBe('malformed')
  })
})

describe('askQuestion timeout and cancellation', () => {
  it('times out after ASK_TIMEOUT_MS by default', async () => {
    vi.useFakeTimers()
    hangingFetch()
    const pending = catchApiError(askQuestion('x', 'compressor-01'))
    await vi.advanceTimersByTimeAsync(ASK_TIMEOUT_MS - 1)
    expect(fetchMock.mock.calls[0]![1]?.signal?.aborted).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    const err = await pending
    expect(err.kind).toBe('timeout')
    expect(err.retryable).toBe(true)
  })

  it('honours a custom timeout', async () => {
    vi.useFakeTimers()
    hangingFetch()
    const pending = catchApiError(askQuestion('x', 'compressor-01', { timeoutMs: 100 }))
    await vi.advanceTimersByTimeAsync(100)
    expect((await pending).kind).toBe('timeout')
  })

  it('reports caller cancellation as aborted, not timeout or network', async () => {
    hangingFetch()
    const controller = new AbortController()
    const pending = catchApiError(askQuestion('x', 'compressor-01', { signal: controller.signal }))
    controller.abort()
    const err = await pending
    expect(err.kind).toBe('aborted')
    expect(err.retryable).toBe(false)
  })

  it('does not send a request if the signal is already aborted', async () => {
    hangingFetch()
    const controller = new AbortController()
    controller.abort()
    const err = await catchApiError(askQuestion('x', 'compressor-01', { signal: controller.signal }))
    expect(err.kind).toBe('aborted')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('getHealth', () => {
  it('GETs /api/health and reports ok', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }))
    await expect(getHealth()).resolves.toEqual({ ok: true, status: 'ok' })
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/health')
    expect(init?.method).toBe('GET')
  })

  it('reports ok=false for an unexpected body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ message: 'hi' }))
    await expect(getHealth()).resolves.toEqual({ ok: false, status: 'unknown' })
  })

  it('throws a network error when the server is unreachable', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    expect((await catchApiError(getHealth())).kind).toBe('network')
  })

  it('times out after 5 seconds', async () => {
    vi.useFakeTimers()
    hangingFetch()
    const pending = catchApiError(getHealth())
    await vi.advanceTimersByTimeAsync(5_000)
    expect((await pending).kind).toBe('timeout')
  })
})
