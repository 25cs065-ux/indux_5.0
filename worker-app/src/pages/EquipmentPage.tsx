import MachineDetails from '../components/MachineDetails.tsx'
import MachineSelect from '../components/MachineSelect.tsx'
import PageHeading from '../components/PageHeading.tsx'
import Section from '../components/Section.tsx'
import { findMachine } from '../data/machines.ts'

interface Props {
  machineId: string
  onMachineChange: (machineId: string) => void
  qrMachineId: string | null
  error: string | null
  onStartDiagnosis: () => void
  autoFocus: boolean
}

export default function EquipmentPage({
  machineId,
  onMachineChange,
  qrMachineId,
  error,
  onStartDiagnosis,
  autoFocus,
}: Props) {
  const machine = findMachine(machineId)
  const fromQr = qrMachineId !== null && machineId === qrMachineId

  return (
    <div className="page-body page-body--equipment">
      <PageHeading
        index="01"
        title="Equipment"
        lede="Identify the machine you are working on."
        autoFocus={autoFocus}
      />

      <div className="split">
        <div className="split-primary">
          <Section index="A" title="Select machine">
            <MachineSelect value={machineId} onChange={onMachineChange} error={error} />
          </Section>
        </div>

        <div className="split-secondary">
          <Section index="B" title="Machine details">
            <MachineDetails machineId={machineId} machine={machine} fromQr={fromQr} />
            <div className="start">
              <button type="button" className="btn btn-primary btn-block" onClick={onStartDiagnosis}>
                <span>Start diagnosis</span>
                <span className="btn-arrow" aria-hidden="true">
                  →
                </span>
              </button>
            </div>
          </Section>
        </div>
      </div>
    </div>
  )
}
