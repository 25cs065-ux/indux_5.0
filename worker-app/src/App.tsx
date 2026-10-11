import { useEffect, useRef, useState } from 'react'
import DiagnosisPanel from './components/DiagnosisPanel.tsx'
import Header from './components/Header.tsx'
import IssueForm, { QUESTION_MAX_LENGTH } from './components/IssueForm.tsx'
import MachineSelect from './components/MachineSelect.tsx'
import Section from './components/Section.tsx'
import { useDiagnosis } from './hooks/useDiagnosis.ts'
import { useSpeechRecognition } from './hooks/useSpeechRecognition.ts'
import { initialMachineId, saveLastMachine } from './lib/machineParam.ts'
import { cancelAllSpeech } from './speech/synthesis.ts'
import { composeQuestion } from './speech/transcript.ts'

export default function App() {
  const [machineId, setMachineId] = useState(() => initialMachineId(window.location.search))
  const [question, setQuestion] = useState('')
  const [machineError, setMachineError] = useState<string | null>(null)
  const [questionError, setQuestionError] = useState<string | null>(null)
  const { state, submit, cancel, retry, isLoading } = useDiagnosis()
  const outputRef = useRef<HTMLDivElement>(null)

  // Text in the field when recording started. Each recognition update
  // rebuilds the question from this, so duplicate events cannot repeat words.
  const dictationBase = useRef('')
  const speech = useSpeechRecognition({
    onTranscript: (spoken) => setQuestion(composeQuestion(dictationBase.current, spoken, QUESTION_MAX_LENGTH)),
  })

  const handleRecordToggle = () => {
    if (speech.isActive) {
      speech.stop()
      return
    }
    // Silence read-aloud so the microphone does not pick it up.
    cancelAllSpeech()
    dictationBase.current = question
    setQuestionError(null)
    speech.start()
  }

  // On narrow screens the diagnosis sits below the form: jump to it when a
  // request starts and when it settles, so the worker sees progress and the
  // result. An instant jump is used because smooth scrolling is unreliable.
  useEffect(() => {
    if (state.phase === 'idle') return
    const el = outputRef.current
    if (!el || window.matchMedia('(min-width: 960px)').matches) return
    el.scrollIntoView({ block: 'start' })
  }, [state.phase])

  const handleSubmit = () => {
    if (isLoading) return
    // Never keep listening into a diagnosis; text already recognised stays.
    speech.abort()
    cancelAllSpeech()
    const mError = machineId.trim() ? null : 'Select or enter a machine ID.'
    const qError = question.trim() ? null : 'Describe the issue before diagnosing.'
    setMachineError(mError)
    setQuestionError(qError)
    if (mError || qError) return

    saveLastMachine(machineId)
    void submit({ question, machineId })
  }

  return (
    <div className="page">
      <Header />

      <main className="layout">
        <div className="layout-input">
          <Section index="01" title="Machine">
            <MachineSelect
              value={machineId}
              onChange={(id) => {
                setMachineId(id)
                if (machineError) setMachineError(null)
              }}
              error={machineError}
              disabled={isLoading}
            />
          </Section>

          <Section index="02" title="Issue">
            <IssueForm
              value={question}
              onChange={(q) => {
                setQuestion(q)
                if (questionError) setQuestionError(null)
              }}
              onSubmit={handleSubmit}
              isLoading={isLoading}
              error={questionError}
              speech={{
                support: speech.support,
                status: speech.status,
                interim: speech.interim,
                error: speech.error,
                onToggle: handleRecordToggle,
              }}
            />
          </Section>
        </div>

        <div className="layout-output" ref={outputRef}>
          <Section index="03" title="Diagnosis">
            <DiagnosisPanel state={state} onRetry={() => void retry()} onCancel={cancel} />
          </Section>
        </div>
      </main>

      <footer className="colophon">
        <p>
          Guidance is generated from equipment manuals and may be incomplete. Always follow site safety rules.
          If unsure, stop and call the lead engineer.
        </p>
      </footer>
    </div>
  )
}
