// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { envelope, jsonResponse, okAnswer } from '../../api/__tests__/fixtures.ts'
import { useDiagnosis } from '../useDiagnosis.ts'

const fetchMock = vi.fn<typeof fetch>()
const request = { question: 'Compressor is overheating', machineId: 'compressor-01' }

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => vi.unstubAllGlobals())

/** Returns a fetch whose response is released manually. */
function deferredFetch() {
  let release: (r: Response) => void = () => {}
  fetchMock.mockImplementation(
    (_input, init) =>
      new Promise<Response>((resolve, reject) => {
        release = resolve
        init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      }),
  )
  return (r: Response) => release(r)
}

describe('useDiagnosis', () => {
  it('starts idle', () => {
    const { result } = renderHook(() => useDiagnosis())
    expect(result.current.state.phase).toBe('idle')
  })

  it('goes loading -> success with the parsed result', async () => {
    const release = deferredFetch()
    const { result } = renderHook(() => useDiagnosis())

    act(() => void result.current.submit(request))
    expect(result.current.state.phase).toBe('loading')
    expect(result.current.isLoading).toBe(true)

    await act(async () => release(jsonResponse(envelope(okAnswer()))))
    await waitFor(() => expect(result.current.state.phase).toBe('success'))
    const state = result.current.state
    expect(state.phase === 'success' && state.result.answer.summary).toBe('Check the cooler and oil level.')
  })

  it('ignores a second submit while a request is in flight', async () => {
    const release = deferredFetch()
    const { result } = renderHook(() => useDiagnosis())

    let second: boolean | undefined
    act(() => {
      void result.current.submit(request)
    })
    await act(async () => {
      second = await result.current.submit({ ...request, question: 'Again' })
    })

    expect(second).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await act(async () => release(jsonResponse(envelope(okAnswer()))))
  })

  it('ignores two submits fired in the same tick', async () => {
    deferredFetch()
    const { result } = renderHook(() => useDiagnosis())
    act(() => {
      void result.current.submit(request)
      void result.current.submit(request)
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('surfaces 503 as an error and retries the same request', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: 'The AI or database service is temporarily unavailable.' }, 503),
    )
    const { result } = renderHook(() => useDiagnosis())

    await act(async () => void (await result.current.submit(request)))
    const failed = result.current.state
    expect(failed.phase).toBe('error')
    expect(failed.phase === 'error' && failed.error.kind).toBe('unavailable')

    fetchMock.mockResolvedValueOnce(jsonResponse(envelope(okAnswer())))
    await act(async () => void (await result.current.retry()))
    expect(result.current.state.phase).toBe('success')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(JSON.parse(fetchMock.mock.calls[1]![1]?.body as string)).toEqual({
      question: 'Compressor is overheating',
      machine_id: 'compressor-01',
    })
  })

  it('surfaces network failures', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    const { result } = renderHook(() => useDiagnosis())
    await act(async () => void (await result.current.submit(request)))
    const state = result.current.state
    expect(state.phase === 'error' && state.error.kind).toBe('network')
  })

  it('cancel returns to idle and allows a new submit', async () => {
    deferredFetch()
    const { result } = renderHook(() => useDiagnosis())
    act(() => void result.current.submit(request))
    await act(async () => result.current.cancel())
    await waitFor(() => expect(result.current.state.phase).toBe('idle'))

    fetchMock.mockResolvedValueOnce(jsonResponse(envelope(okAnswer())))
    await act(async () => void (await result.current.submit(request)))
    expect(result.current.state.phase).toBe('success')
  })

  it('aborts the request on unmount', () => {
    deferredFetch()
    const { result, unmount } = renderHook(() => useDiagnosis())
    act(() => void result.current.submit(request))
    const signal = fetchMock.mock.calls[0]![1]?.signal
    unmount()
    expect(signal?.aborted).toBe(true)
  })
})
