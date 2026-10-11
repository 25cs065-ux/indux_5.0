import { useCallback, useEffect, useRef, useState } from 'react'
import { getHealth, isApiError } from '../api/index.ts'

export type BackendHealth = 'checking' | 'online' | 'offline'

/**
 * Whether the Indux server answers GET /health. Checked on load and on demand.
 * Real /ask outcomes also update it (markOnline / markOffline), since they are
 * more recent evidence than the last health check.
 */
export function useBackendHealth() {
  const [status, setStatus] = useState<BackendHealth>('checking')
  const controller = useRef<AbortController | null>(null)

  const recheck = useCallback(() => {
    controller.current?.abort()
    const c = new AbortController()
    controller.current = c
    setStatus('checking')
    getHealth({ signal: c.signal })
      .then((health) => {
        if (controller.current === c) setStatus(health.ok ? 'online' : 'offline')
      })
      .catch((err: unknown) => {
        if (isApiError(err) && err.kind === 'aborted') return
        if (controller.current === c) setStatus('offline')
      })
  }, [])

  useEffect(() => {
    recheck()
    return () => controller.current?.abort()
  }, [recheck])

  // A real request outcome is newer than any health check still in flight,
  // so cancel that check rather than let its older answer overwrite this one.
  const markOnline = useCallback(() => {
    controller.current?.abort()
    controller.current = null
    setStatus('online')
  }, [])
  const markOffline = useCallback(() => {
    controller.current?.abort()
    controller.current = null
    setStatus('offline')
  }, [])

  return { status, recheck, markOnline, markOffline }
}
