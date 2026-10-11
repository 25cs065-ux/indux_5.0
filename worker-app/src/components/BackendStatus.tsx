import { useEffect, useState } from 'react'
import { getHealth, isApiError } from '../api/index.ts'

type State = 'checking' | 'online' | 'offline'

const LABELS: Record<State, string> = {
  checking: 'Checking',
  online: 'Online',
  offline: 'Unreachable',
}

/** Compact server indicator driven by GET /health. */
export default function BackendStatus() {
  const [state, setState] = useState<State>('checking')

  useEffect(() => {
    const controller = new AbortController()
    getHealth({ signal: controller.signal })
      .then((health) => setState(health.ok ? 'online' : 'offline'))
      .catch((err: unknown) => {
        if (isApiError(err) && err.kind === 'aborted') return
        setState('offline')
      })
    return () => controller.abort()
  }, [])

  return (
    <p className={`server server--${state}`} role="status" aria-label={`Server ${LABELS[state]}`}>
      <span className="server-key">SRV</span>
      <span className="server-dot" aria-hidden="true" />
      <span className="server-value">{LABELS[state]}</span>
    </p>
  )
}
