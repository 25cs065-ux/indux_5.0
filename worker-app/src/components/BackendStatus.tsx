import type { BackendHealth } from '../hooks/useBackendHealth.ts'

const LABELS: Record<BackendHealth, string> = {
  checking: 'Checking',
  online: 'Online',
  offline: 'Unreachable',
}

/** Compact server indicator for the masthead. */
export default function BackendStatus({ status }: { status: BackendHealth }) {
  return (
    <p className={`server server--${status}`} role="status" aria-label={`Server ${LABELS[status]}`}>
      <span className="server-key">SRV</span>
      <span className="server-dot" aria-hidden="true" />
      <span className="server-value">{LABELS[status]}</span>
    </p>
  )
}
