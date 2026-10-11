import { useEffect, useRef } from 'react'
import DiagnosisPanel from '../components/DiagnosisPanel.tsx'
import IssueForm from '../components/IssueForm.tsx'
import type { SpeechControls } from '../components/IssueForm.tsx'
import MachineBar from '../components/MachineBar.tsx'
import PageHeading from '../components/PageHeading.tsx'
import Section from '../components/Section.tsx'
import type { DiagnosisState } from '../hooks/useDiagnosis.ts'

interface Props {
  machineId: string
  machineError: string | null
  question: string
  onQuestionChange: (question: string) => void
  questionError: string | null
  onSubmit: () => void
  isLoading: boolean
  speech: SpeechControls
  diagnosis: DiagnosisState
  onRetry: () => void
  onCancel: () => void
  autoFocus: boolean
}

export default function DiagnosePage(props: Props) {
  const { machineId, diagnosis } = props
  const outputRef = useRef<HTMLDivElement>(null)

  // On narrow screens the diagnosis sits below the form: jump to it when a
  // request starts and when it settles, so the worker sees progress and the
  // result. An instant jump is used because smooth scrolling is unreliable.
  useEffect(() => {
    if (diagnosis.phase === 'idle') return
    const el = outputRef.current
    if (!el || window.matchMedia('(min-width: 960px)').matches) return
    el.scrollIntoView({ block: 'start' })
  }, [diagnosis.phase])

  const resultMachine = diagnosis.phase === 'success' ? diagnosis.result.machineId : null
  const machineChanged = resultMachine !== null && resultMachine !== machineId

  return (
    <div className="page-body page-body--diagnose">
      <PageHeading index="02" title="Diagnose" autoFocus={props.autoFocus} />

      <MachineBar machineId={machineId} />
      {props.machineError && (
        <p className="field-error" role="alert">
          {props.machineError}
        </p>
      )}

      <div className="layout">
        <div className="layout-input">
          <Section index="A" title="Issue">
            <IssueForm
              value={props.question}
              onChange={props.onQuestionChange}
              onSubmit={props.onSubmit}
              isLoading={props.isLoading}
              error={props.questionError}
              speech={props.speech}
            />
          </Section>
        </div>

        <div className="layout-output" ref={outputRef}>
          <Section index="B" title="Diagnosis">
            {machineChanged && (
              <p className="machine-mismatch" role="note">
                This diagnosis is for <span className="mono">{resultMachine}</span>, not the machine now selected.
              </p>
            )}
            <DiagnosisPanel state={diagnosis} onRetry={props.onRetry} onCancel={props.onCancel} />
          </Section>
        </div>
      </div>
    </div>
  )
}
