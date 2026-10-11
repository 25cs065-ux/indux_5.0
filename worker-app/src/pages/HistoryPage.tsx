import MachineBar from '../components/MachineBar.tsx'
import PageHeading from '../components/PageHeading.tsx'

/**
 * Placeholder until the read-only repair history (GET /history/{machine_id})
 * is implemented. Shows no records of any kind.
 */
export default function HistoryPage({ machineId, autoFocus }: { machineId: string; autoFocus: boolean }) {
  return (
    <div className="page-body page-body--history">
      <PageHeading
        index="03"
        title="Repair history"
        lede="Past repairs recorded for this machine. Context only, not manufacturer instructions."
        autoFocus={autoFocus}
      />
      <MachineBar machineId={machineId} />
      <div className="unavailable" role="note">
        <p className="unavailable-code mono">Not available yet</p>
        <p className="unavailable-text">Repair records will appear here in a later build of the worker app.</p>
      </div>
    </div>
  )
}
