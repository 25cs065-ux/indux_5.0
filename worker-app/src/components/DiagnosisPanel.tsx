import type { ApiError } from '../api/index.ts'
import type { DiagnosisState } from '../hooks/useDiagnosis.ts'
import ResultView from './result/ResultView.tsx'

interface Props {
  state: DiagnosisState
  onRetry: () => void
  onCancel: () => void
}

export default function DiagnosisPanel({ state, onRetry, onCancel }: Props) {
  switch (state.phase) {
    case 'idle':
      return <Idle />
    case 'loading':
      return <Loading machineId={state.request.machineId} onCancel={onCancel} />
    case 'error':
      return <ErrorBlock error={state.error} onRetry={onRetry} />
    case 'success':
      return <ResultView key={state.id} result={state.result} />
  }
}

/** What a diagnosis contains, in the order it appears. Describes, never invents. */
const REPORT_KEY = [
  ['Safety', 'Hazard checks to complete before any work'],
  ['Steps', 'Numbered actions, each with a check question'],
  ['References', 'Manual name and page for the guidance'],
  ['Escalation', 'When to stop and call the lead engineer'],
] as const

function Idle() {
  return (
    <div className="panel-empty">
      <p className="panel-empty-title">Awaiting diagnosis</p>
      <p className="panel-empty-lede">
        Select a machine and describe the issue. The report will appear here.
      </p>
      <dl className="report-key">
        {REPORT_KEY.map(([term, desc], i) => (
          <div key={term} className="report-key-row">
            <dt>
              <span className="mono report-key-index">{String(i + 1).padStart(2, '0')}</span>
              {term}
            </dt>
            <dd>{desc}</dd>
          </div>
        ))}
      </dl>
      <p className="panel-empty-hint mono">Ctrl + Enter submits from the issue field</p>
    </div>
  )
}

function Loading({ machineId, onCancel }: { machineId: string; onCancel: () => void }) {
  return (
    <div className="panel-loading" role="status" aria-live="polite">
      <div className="progress" aria-hidden="true">
        <span />
      </div>
      <p className="panel-loading-text">
        Searching manuals and repair history for <span className="mono">{machineId}</span>…
      </p>
      <p className="field-note">This can take up to 45 seconds.</p>
      <button type="button" className="btn btn-ghost" onClick={onCancel}>
        Cancel
      </button>
    </div>
  )
}

const ERROR_TITLES: Record<ApiError['kind'], string> = {
  validation: 'Request not accepted',
  unavailable: 'Assistant unavailable',
  http: 'Server error',
  network: 'No connection to the server',
  timeout: 'No response in time',
  aborted: 'Request cancelled',
  malformed: 'Unreadable response',
}

function ErrorBlock({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  const canRetry = error.kind !== 'validation' && error.kind !== 'aborted'
  return (
    <div className="notice notice--error" role="alert">
      <p className="notice-code">Error · {error.status !== undefined ? `HTTP ${error.status}` : error.kind}</p>
      <p className="notice-title">{ERROR_TITLES[error.kind]}</p>
      <p className="notice-body">{error.message}</p>
      {canRetry && (
        <button type="button" className="btn btn-secondary" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  )
}
