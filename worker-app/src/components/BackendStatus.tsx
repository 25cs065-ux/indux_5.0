import { useEffect, useState } from 'react'
import { getHealth, isApiError } from '../api/index.ts'

type State = 'checking' | 'online' | 'offline'

/** Small indicator showing whether GET /health succeeds. */
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

  const label = {
    checking: 'Checking server…',
    online: 'Server online',
    offline: 'Server unreachable',
  }[state]

  return (
    <p className={`backend-status backend-status--${state}`} role="status">
      <span className="backend-status-dot" aria-hidden="true" />
      {label}
    </p>
  )
}
