import { findMachine } from '../data/machines.ts'
import { hrefFor } from '../router/useHashRoute.ts'

/** Which machine the diagnosis is for, with a link back to Equipment. */
export default function MachineBar({ machineId }: { machineId: string }) {
  const selected = machineId.trim() !== ''
  const machine = findMachine(machineId)

  return (
    <div className={`machine-bar ${selected ? '' : 'machine-bar--empty'}`}>
      <p className="machine-bar-label mono">Machine</p>
      {selected ? (
        <p className="machine-bar-value">
          <span className="mono machine-bar-id">{machineId}</span>
          {machine && <span className="machine-bar-name">{machine.name}</span>}
        </p>
      ) : (
        <p className="machine-bar-value machine-bar-value--empty">No machine selected</p>
      )}
      <a className="machine-bar-link" href={hrefFor('equipment')}>
        {selected ? 'Change' : 'Select machine'}
      </a>
    </div>
  )
}
