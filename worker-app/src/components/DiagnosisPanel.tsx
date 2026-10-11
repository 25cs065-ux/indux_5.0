import type { ApiError, AskResult } from '../api/index.ts'
import type { DiagnosisState } from '../hooks/useDiagnosis.ts'
import { safetyStateOf, stepsGateOf } from '../lib/safety.ts'
import SafetyNotice from './SafetyNotice.tsx'

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
      return <Result result={state.result} />
  }
}

function Idle() {
  return (
    <div className="panel-empty">
      <p className="panel-empty-title">No diagnosis yet</p>
      <ol className="panel-empty-steps">
        <li>Select the machine</li>
        <li>Describe what is wrong</li>
        <li>Press Diagnose</li>
      </ol>
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
      <p className="notice-code">
        Error · {error.status !== undefined ? `HTTP ${error.status}` : error.kind}
      </p>
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

function Result({ result }: { result: AskResult }) {
  const { answer } = result
  const found = answer.status === 'OK'
  const safety = safetyStateOf(answer)
  const gate = stepsGateOf(answer)

  return (
    <article className="result" aria-live="polite">
      <dl className="result-meta">
        <div>
          <dt>Machine</dt>
          <dd className="mono">{result.machineId}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd className={`status status--${found ? 'ok' : 'not-found'}`}>
            <span className="mono">{answer.status}</span>
            <span>{found ? 'Manual match' : 'Not in manuals'}</span>
          </dd>
        </div>
        {found && answer.problemType && (
          <div>
            <dt>Category</dt>
            <dd className="mono">{answer.problemType}</dd>
          </div>
        )}
      </dl>

      {result.isDemo && (
        <p className="demo-stamp" role="note">
          <span className="mono">DEMO</span> This is a demo response, not a live diagnosis.
        </p>
      )}

      <blockquote className="result-question">
        <span className="visually-hidden">Your question: </span>
        {result.question}
      </blockquote>

      <SafetyNotice state={safety} checklist={answer.safetyChecklist} />

      <div className="result-summary">
        <h3 className="result-heading">{found ? 'Summary' : 'Not found in the manuals'}</h3>
        {answer.summary ? (
          <p className="result-summary-text">{answer.summary}</p>
        ) : (
          <p className="result-summary-text result-summary-text--empty">The assistant returned no summary.</p>
        )}
      </div>

      {answer.escalate && (
        <div className="notice notice--escalate">
          <p className="notice-code">Escalate</p>
          <p className="notice-title">Contact the lead engineer</p>
          <p className="notice-body">
            {found
              ? 'The assistant recommends escalating this issue.'
              : 'The manuals do not cover this issue. Do not attempt a repair without the lead engineer.'}
          </p>
        </div>
      )}

      {answer.historyNote && (
        <div className="result-history">
          <h3 className="result-heading">Repair history</h3>
          <p>{answer.historyNote}</p>
        </div>
      )}

      <StepsNotice gate={gate} count={answer.steps.length} />

      {result.issues.length > 0 && (
        <details className="result-issues">
          <summary>Incomplete response · {result.issues.length} field(s) missing or invalid</summary>
          <ul>
            {result.issues.map((issue) => (
              <li key={issue} className="mono">
                {issue}
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  )
}

/** Stage 3 shows no steps; this states honestly what was returned and why. */
function StepsNotice({ gate, count }: { gate: ReturnType<typeof stepsGateOf>; count: number }) {
  if (gate === 'none') return null
  const label = `${count} step${count === 1 ? '' : 's'}`
  const text = {
    withheld: `${label} returned but withheld because the safety status is unknown.`,
    requires_ack: `${label} returned. Step display with safety acknowledgement is coming in the next build.`,
    allowed: `${label} returned. Step display is coming in the next build.`,
  }[gate]
  return <p className="steps-notice mono">{text}</p>
}
