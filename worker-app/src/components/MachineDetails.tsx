import type { Machine } from '../data/machines.ts'

interface Props {
  machineId: string
  machine: Machine | null
  fromQr: boolean
}

/** Shows only what the site machine list records. No status, health or readings. */
export default function MachineDetails({ machineId, machine, fromQr }: Props) {
  if (!machineId.trim()) {
    return (
      <div className="details details--empty">
        <p className="details-empty-title">No machine selected</p>
        <p className="details-empty-text">
          Choose a machine from the list, enter its ID, or scan the QR code on the machine with your phone camera.
        </p>
      </div>
    )
  }

  return (
    <div className="details">
      {fromQr && (
        <p className="details-tag mono" role="note">
          Selected from QR code
        </p>
      )}

      <dl className="details-list">
        <div className="details-row">
          <dt>Machine ID</dt>
          <dd className="mono details-id">{machineId}</dd>
        </div>
        {machine ? (
          <>
            <div className="details-row">
              <dt>Name</dt>
              <dd>{machine.name}</dd>
            </div>
            <div className="details-row">
              <dt>Model</dt>
              <dd>{machine.model}</dd>
            </div>
            <div className="details-row">
              <dt>Location</dt>
              <dd>{machine.location}</dd>
            </div>
          </>
        ) : null}
      </dl>

      {machine ? (
        <p className="details-source mono">Source: site machine list</p>
      ) : (
        <p className="details-unlisted">
          This ID is not in the site machine list, so no machine details are available. It will be sent exactly as
          entered.
        </p>
      )}
    </div>
  )
}
