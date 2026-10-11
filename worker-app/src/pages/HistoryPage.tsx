import { HISTORY_LIMIT } from '../api/index.ts'
import type { RepairRecord } from '../api/index.ts'
import MachineBar from '../components/MachineBar.tsx'
import PageHeading from '../components/PageHeading.tsx'
import { useRepairHistory } from '../hooks/useRepairHistory.ts'
import { hrefFor } from '../router/useHashRoute.ts'

interface Props {
  machineId: string
  autoFocus: boolean
  onReachable?: () => void
  onUnreachable?: () => void
}

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

/** Read-only repair history from GET /history/{machine_id}. */
export default function HistoryPage({ machineId, autoFocus, onReachable, onUnreachable }: Props) {
  const { state, retry } = useRepairHistory(machineId, { onReachable, onUnreachable })

  return (
    <div className="page-body page-body--history">
      <PageHeading
        index="03"
        title="Repair history"
        lede="Past maintenance recorded for this machine."
        autoFocus={autoFocus}
      />
      <MachineBar machineId={machineId} />

      <p className="history-disclaimer" role="note">
        <span className="history-disclaimer-code mono">Site records · Context only</span>
        These are historical maintenance records, not verified manufacturer instructions. Always follow the
        equipment manual and site safety procedures.
      </p>

      <section className="history-body" aria-labelledby="history-records-title" aria-busy={state.phase === 'loading'}>
        <h2 id="history-records-title" className="visually-hidden">
          Repair records
        </h2>

        {state.phase === 'no-machine' && (
          <div className="history-state">
            <p className="history-state-title">No machine selected</p>
            <p className="history-state-text">Select a machine to see its repair records.</p>
            <a className="btn btn-secondary history-state-action" href={hrefFor('equipment')}>
              Select machine
            </a>
          </div>
        )}

        {state.phase === 'loading' && (
          <div className="panel-loading" role="status" aria-live="polite">
            <div className="progress" aria-hidden="true">
              <span />
            </div>
            <p className="panel-loading-text">
              Loading repair records for <span className="mono">{state.machineId}</span>…
            </p>
          </div>
        )}

        {state.phase === 'error' && (
          <div className="notice notice--error" role="alert">
            <p className="notice-code">
              Error · {state.error.status !== undefined ? `HTTP ${state.error.status}` : state.error.kind}
            </p>
            <p className="notice-title">Repair history unavailable</p>
            <p className="notice-body">{state.error.message}</p>
            {state.error.kind !== 'validation' && (
              <button type="button" className="btn btn-secondary" onClick={retry}>
                Retry
              </button>
            )}
          </div>
        )}

        {state.phase === 'success' && state.result.records.length === 0 && (
          <div className="history-state" role="status">
            <p className="history-state-title">No repair records</p>
            <p className="history-state-text">
              No repairs have been recorded for <span className="mono">{state.machineId}</span>.
            </p>
          </div>
        )}

        {state.phase === 'success' && state.result.records.length > 0 && (
          <>
            <p className="history-count mono" role="status">
              {state.result.records.length} record{state.result.records.length === 1 ? '' : 's'} · newest first
              {state.result.records.length >= HISTORY_LIMIT && ` · showing the ${HISTORY_LIMIT} most recent`}
            </p>
            {state.result.issues.length > 0 && (
              <p className="history-issues" role="note">
                Some returned data was incomplete. Missing details are shown as not recorded; unreadable entries are
                not shown.
              </p>
            )}
            <ol className="logbook" aria-label={`Repair records for ${state.machineId}`}>
              {state.result.records.map((record) => (
                <RecordEntry key={record.key} record={record} />
              ))}
            </ol>
          </>
        )}
      </section>
    </div>
  )
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="logbook-field">
      <dt>{label}</dt>
      {value ? <dd>{value}</dd> : <dd className="logbook-missing">Not recorded</dd>}
    </div>
  )
}

function RecordEntry({ record }: { record: RepairRecord }) {
  return (
    <li className="logbook-entry">
      <p className="logbook-date mono">
        {record.recordedAt && record.recordedAtRaw ? (
          <time dateTime={record.recordedAtRaw}>{dateFormat.format(record.recordedAt)}</time>
        ) : (
          <span className="logbook-missing">Date not recorded</span>
        )}
      </p>
      <dl className="logbook-fields">
        <Field label="Problem" value={record.problem} />
        <Field label="Action" value={record.action} />
        <Field label="Outcome" value={record.outcome} />
      </dl>
    </li>
  )
}
