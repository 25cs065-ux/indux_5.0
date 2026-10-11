import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, askQuestion, isApiError } from '../api/index.ts'
import type { AskResult } from '../api/index.ts'

export interface DiagnosisRequest {
  question: string
  machineId: string
}

export type DiagnosisState =
  | { phase: 'idle' }
  | { phase: 'loading'; request: DiagnosisRequest }
  | { phase: 'success'; request: DiagnosisRequest; result: AskResult }
  | { phase: 'error'; request: DiagnosisRequest; error: ApiError }

/**
 * Owns the /ask request lifecycle. Only one request can be in flight:
 * submit() while loading is ignored and returns false.
 */
export function useDiagnosis() {
  const [state, setState] = useState<DiagnosisState>({ phase: 'idle' })
  const inFlight = useRef<AbortController | null>(null)

  useEffect(() => () => inFlight.current?.abort(), [])

  const submit = useCallback(async (request: DiagnosisRequest): Promise<boolean> => {
    if (inFlight.current) return false
    const controller = new AbortController()
    inFlight.current = controller
    setState({ phase: 'loading', request })

    try {
      const result = await askQuestion(request.question, request.machineId, { signal: controller.signal })
      setState({ phase: 'success', request, result })
    } catch (err) {
      if (isApiError(err) && err.kind === 'aborted') {
        setState({ phase: 'idle' })
      } else {
        const error = isApiError(err)
          ? err
          : new ApiError('http', 'Something went wrong. Please try again.')
        setState({ phase: 'error', request, error })
      }
    } finally {
      if (inFlight.current === controller) inFlight.current = null
    }
    return true
  }, [])

  const cancel = useCallback(() => {
    inFlight.current?.abort()
  }, [])

  const retry = useCallback(() => {
    if (state.phase === 'error') return submit(state.request)
    return Promise.resolve(false)
  }, [state, submit])

  return { state, submit, cancel, retry, isLoading: state.phase === 'loading' }
}
