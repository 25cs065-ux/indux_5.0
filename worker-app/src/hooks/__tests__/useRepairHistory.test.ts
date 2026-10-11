// @vitest-environment jsdom
// Mock-response tests; they do not verify the real backend.
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { historyEnvelope, historyRow, jsonResponse } from '../../api/__tests__/fixtures.ts'
import { useRepairHistory } from '../useRepairHistory.ts'

const fetchMock = vi.fn<typeof fetch>()

/** Each call returns a promise released manually; rejects on abort like real fetch. */
function controlledFetch() {
  const releases: Array<(r: Response) => void> = []
  fetchMock.mockImplementation(
    (_input, init) =>
      new Promise<Response>((resolve, reject) => {
        releases.push(resolve)
        init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      }),
  )
  return releases
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => vi.unstubAllGlobals())

describe('useRepairHistory', () => {
  it('does nothing without a machine', () => {
    const { result } = renderHook(() => useRepairHistory(''))
    expect(result.current.state.phase).toBe('no-machine')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('loads, then shows the records', async () => {
    const releases = controlledFetch()
    const { result } = renderHook(() => useRepairHistory('compressor-01'))
    expect(result.current.state.phase).toBe('loading')
    await act(async () => releases[0]!(jsonResponse(historyEnvelope([historyRow()]))))
    const s = result.current.state
    expect(s.phase).toBe('success')
    expect(s.phase === 'success' && s.result.records).toHaveLength(1)
  })

  it('shows an empty result', async () => {
    fetchMock.mockResolvedValue(jsonResponse(historyEnvelope([])))
    const { result } = renderHook(() => useRepairHistory('compressor-01'))
    await waitFor(() => expect(result.current.state.phase).toBe('success'))
    const s = result.current.state
    expect(s.phase === 'success' && s.result.records).toEqual([])
  })

  it('cancels the previous request when the machine changes and ignores its late reply', async () => {
    const releases = controlledFetch()
    const { result, rerender } = renderHook(({ id }) => useRepairHistory(id), { initialProps: { id: 'compressor-01' } })
    const firstSignal = fetchMock.mock.calls[0]![1]?.signal

    rerender({ id: 'compressor-02' })
    expect(firstSignal?.aborted).toBe(true)
    expect(String(fetchMock.mock.calls[1]![0])).toBe('/api/history/compressor-02')

    // A late reply for compressor-01 must never appear.
    await act(async () => releases[0]!(jsonResponse(historyEnvelope([historyRow()]))))
    expect(result.current.state).toEqual({ phase: 'loading', machineId: 'compressor-02' })

    await act(async () =>
      releases[1]!(jsonResponse(historyEnvelope([historyRow({ id: 'z', machine_id: 'compressor-02' })], 'compressor-02'))),
    )
    const s = result.current.state
    expect(s.phase === 'success' && s.machineId).toBe('compressor-02')
    expect(s.phase === 'success' && s.result.records[0]!.key).toBe('z')
  })

  it('clearing the machine cancels the request', () => {
    controlledFetch()
    const { result, rerender } = renderHook(({ id }) => useRepairHistory(id), { initialProps: { id: 'compressor-01' } })
    const signal = fetchMock.mock.calls[0]![1]?.signal
    rerender({ id: '' })
    expect(signal?.aborted).toBe(true)
    expect(result.current.state.phase).toBe('no-machine')
  })

  it('cancels the request on unmount (leaving the History page)', () => {
    controlledFetch()
    const { unmount } = renderHook(() => useRepairHistory('compressor-01'))
    const signal = fetchMock.mock.calls[0]![1]?.signal
    unmount()
    expect(signal?.aborted).toBe(true)
  })

  it('shows errors and retries once even if Retry is pressed twice', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Could not retrieve repair history.' }, 503))
    const { result } = renderHook(() => useRepairHistory('compressor-01'))
    await waitFor(() => expect(result.current.state.phase).toBe('error'))

    const releases = controlledFetch()
    act(() => {
      result.current.retry()
      result.current.retry()
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    await act(async () => releases[0]!(jsonResponse(historyEnvelope([]))))
    expect(result.current.state.phase).toBe('success')
  })

  it('reports reachability from real outcomes', async () => {
    const onReachable = vi.fn()
    const onUnreachable = vi.fn()
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    const { result } = renderHook(() => useRepairHistory('compressor-01', { onReachable, onUnreachable }))
    await waitFor(() => expect(result.current.state.phase).toBe('error'))
    expect(onUnreachable).toHaveBeenCalledTimes(1)

    fetchMock.mockResolvedValueOnce(jsonResponse(historyEnvelope([])))
    act(() => result.current.retry())
    await waitFor(() => expect(result.current.state.phase).toBe('success'))
    expect(onReachable).toHaveBeenCalledTimes(1)
  })

  it('a malformed body is an error, not an empty history', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 'success' }))
    const { result } = renderHook(() => useRepairHistory('compressor-01'))
    await waitFor(() => expect(result.current.state.phase).toBe('error'))
    const s = result.current.state
    expect(s.phase === 'error' && s.error.kind).toBe('malformed')
  })
})
