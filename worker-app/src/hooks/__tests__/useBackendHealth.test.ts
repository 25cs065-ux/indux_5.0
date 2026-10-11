// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { jsonResponse } from '../../api/__tests__/fixtures.ts'
import { useBackendHealth } from '../useBackendHealth.ts'

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => vi.unstubAllGlobals())

describe('useBackendHealth', () => {
  it('checks /health on mount: online', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }))
    const { result } = renderHook(() => useBackendHealth())
    expect(result.current.status).toBe('checking')
    await waitFor(() => expect(result.current.status).toBe('online'))
    expect(String(fetchMock.mock.calls[0]![0])).toBe('/api/health')
  })

  it('reports offline when the server is unreachable', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    const { result } = renderHook(() => useBackendHealth())
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })

  it('reports offline for an unexpected health body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 'degraded' }))
    const { result } = renderHook(() => useBackendHealth())
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })

  it('recheck() checks again', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    const { result } = renderHook(() => useBackendHealth())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 'ok' }))
    act(() => result.current.recheck())
    expect(result.current.status).toBe('checking')
    await waitFor(() => expect(result.current.status).toBe('online'))
  })

  it('markOnline / markOffline update from real request outcomes', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }))
    const { result } = renderHook(() => useBackendHealth())
    await waitFor(() => expect(result.current.status).toBe('online'))
    act(() => result.current.markOffline())
    expect(result.current.status).toBe('offline')
    act(() => result.current.markOnline())
    expect(result.current.status).toBe('online')
  })
})
