import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getRepairHistory, isApiError } from '../api/index.ts'
import type { RepairHistoryResult } from '../api/index.ts'

export type RepairHistoryState =
  | { phase: 'no-machine' }
  | { phase: 'loading'; machineId: string }
  | { phase: 'success'; machineId: string; result: RepairHistoryResult }
  | { phase: 'error'; machineId: string; error: ApiError }

interface Options {
  /** Real outcomes keep the shared server indicator current. */
  onReachable?: () => void
  onUnreachable?: () => void
}

/**
 * Loads GET /history/{machineId} for the current machine. A machine change or
 * unmount cancels the outstanding request, and only the response for the
 * current request can update state, so a slow reply for a previous machine is
 * never shown.
 */
export function useRepairHistory(machineId: string, { onReachable, onUnreachable }: Options = {}) {
  const hasMachine = machineId.trim() !== ''
  const [state, setState] = useState<RepairHistoryState>(
    hasMachine ? { phase: 'loading', machineId } : { phase: 'no-machine' },
  )
  const current = useRef<AbortController | null>(null)
  const callbacks = useRef({ onReachable, onUnreachable })
  useEffect(() => {
    callbacks.current = { onReachable, onUnreachable }
  })

  const load = useCallback((id: string) => {
    current.current?.abort()
    if (!id.trim()) {
      current.current = null
      setState({ phase: 'no-machine' })
      return
    }
    const controller = new AbortController()
    current.current = controller
    setState({ phase: 'loading', machineId: id })

    getRepairHistory(id, { signal: controller.signal })
      .then((result) => {
        if (current.current !== controller) return
        callbacks.current.onReachable?.()
        setState({ phase: 'success', machineId: id, result })
      })
      .catch((err: unknown) => {
        if (current.current !== controller) return
        if (isApiError(err) && err.kind === 'aborted') return
        const error = isApiError(err) ? err : new ApiError('http', 'Something went wrong. Please try again.')
        if (error.kind === 'network' || (error.kind === 'unavailable' && (error.status === 502 || error.status === 504))) {
          callbacks.current.onUnreachable?.()
        }
        setState({ phase: 'error', machineId: id, error })
      })
      .finally(() => {
        if (current.current === controller) current.current = null
      })
  }, [])

  useEffect(() => {
    load(machineId)
    return () => {
      current.current?.abort()
      current.current = null
    }
  }, [machineId, load])

  const retry = useCallback(() => {
    // Ignore repeated clicks while a request is already running.
    if (current.current) return
    load(machineId)
  }, [machineId, load])

  return { state, retry }
}
