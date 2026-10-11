import { useEffect, useMemo, useRef, useState } from 'react'
import AppNav from './components/AppNav.tsx'
import Header from './components/Header.tsx'
import { QUESTION_MAX_LENGTH } from './components/IssueForm.tsx'
import { useBackendHealth } from './hooks/useBackendHealth.ts'
import { useDiagnosis } from './hooks/useDiagnosis.ts'
import { useSpeechRecognition } from './hooks/useSpeechRecognition.ts'
import { initialMachineId, machineFromSearch, saveLastMachine } from './lib/machineParam.ts'
import DiagnosePage from './pages/DiagnosePage.tsx'
import EquipmentPage from './pages/EquipmentPage.tsx'
import HistoryPage from './pages/HistoryPage.tsx'
import type { Route } from './router/useHashRoute.ts'
import { useHashRoute } from './router/useHashRoute.ts'
import { cancelAllSpeech } from './speech/synthesis.ts'
import { composeQuestion } from './speech/transcript.ts'

const PAGE_TITLES: Record<Route, string> = {
  equipment: 'Equipment',
  diagnose: 'Diagnose',
  history: 'Repair history',
}

const MACHINE_REQUIRED = 'Select or enter a machine ID.'

/**
 * App frame. Owns the state that must survive page changes: the selected
 * machine, the question, the current diagnosis and voice input. Per-answer
 * state (safety acknowledgement, read-aloud) lives in the diagnosis view,
 * which unmounts when the worker leaves Diagnose, so it always resets.
 */
export default function App() {
  const [route, navigate] = useHashRoute()
  const qrMachineId = useMemo(() => machineFromSearch(window.location.search), [])
  const [machineId, setMachineId] = useState(() => initialMachineId(window.location.search))
  const [question, setQuestion] = useState('')
  const [machineError, setMachineError] = useState<string | null>(null)
  const [questionError, setQuestionError] = useState<string | null>(null)
  const { state, submit, cancel, retry, reset, isLoading } = useDiagnosis()
  const health = useBackendHealth()
  const { markOnline, markOffline } = health

  // Real /ask outcomes are fresher evidence than the last health check.
  useEffect(() => {
    if (state.phase === 'success') markOnline()
    if (state.phase === 'error') {
      const { kind, status } = state.error
      if (kind === 'network' || (kind === 'unavailable' && (status === 502 || status === 504))) markOffline()
    }
  }, [state, markOnline, markOffline])

  // Text in the field when recording started. Each recognition update
  // rebuilds the question from this, so duplicate events cannot repeat words.
  const dictationBase = useRef('')
  const speech = useSpeechRecognition({
    onTranscript: (spoken) => setQuestion(composeQuestion(dictationBase.current, spoken, QUESTION_MAX_LENGTH)),
  })
  const { abort: abortRecording } = speech

  // Leaving Diagnose stops the microphone and any read-aloud.
  useEffect(() => {
    if (route !== 'diagnose') {
      abortRecording()
      cancelAllSpeech()
    }
  }, [route, abortRecording])

  // Page changes: title, scroll to top, and focus the new page heading.
  // Not on first load, so the initial page does not steal focus.
  const initialRoute = useRef(route)
  const hasNavigated = useRef(false)
  if (route !== initialRoute.current) hasNavigated.current = true
  useEffect(() => {
    document.title = `${PAGE_TITLES[route]} · INDUX Field Assistant`
    if (hasNavigated.current) window.scrollTo(0, 0)
  }, [route])

  const handleMachineChange = (id: string) => {
    setMachineId(id)
    if (machineError) setMachineError(null)
  }

  const handleStartDiagnosis = () => {
    if (!machineId.trim()) {
      setMachineError(MACHINE_REQUIRED)
      return
    }
    saveLastMachine(machineId)
    setMachineError(null)
    navigate('diagnose')
  }

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

  /** Clears the question and diagnosis; keeps the machine. */
  const handleNewQuestion = () => {
    speech.abort()
    cancelAllSpeech()
    reset()
    dictationBase.current = ''
    setQuestion('')
    setQuestionError(null)
    setMachineError(null)
  }

  const handleSubmit = () => {
    if (isLoading) return
    // Never keep listening into a diagnosis; text already recognised stays.
    speech.abort()
    cancelAllSpeech()
    const mError = machineId.trim() ? null : MACHINE_REQUIRED
    const qError = question.trim() ? null : 'Describe the issue before diagnosing.'
    setMachineError(mError)
    setQuestionError(qError)
    if (mError || qError) return

    saveLastMachine(machineId)
    void submit({ question, machineId })
  }

  const autoFocus = hasNavigated.current

  return (
    <div className="page">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <Header route={route} health={health.status} />

      <main id="main" className="page-main" tabIndex={-1}>
        {route === 'equipment' && (
          <EquipmentPage
            machineId={machineId}
            onMachineChange={handleMachineChange}
            qrMachineId={qrMachineId}
            error={machineError}
            onStartDiagnosis={handleStartDiagnosis}
            autoFocus={autoFocus}
          />
        )}

        {route === 'diagnose' && (
          <DiagnosePage
            machineId={machineId}
            machineError={machineError}
            question={question}
            onQuestionChange={(q) => {
              setQuestion(q)
              if (questionError) setQuestionError(null)
            }}
            questionError={questionError}
            onSubmit={handleSubmit}
            isLoading={isLoading}
            speech={{
              support: speech.support,
              status: speech.status,
              interim: speech.interim,
              error: speech.error,
              onToggle: handleRecordToggle,
            }}
            diagnosis={state}
            onRetry={() => void retry()}
            onCancel={cancel}
            onNewQuestion={handleNewQuestion}
            health={health.status}
            onRecheckHealth={health.recheck}
            autoFocus={autoFocus}
          />
        )}

        {route === 'history' && <HistoryPage machineId={machineId} autoFocus={autoFocus} />}
      </main>

      <footer className="colophon">
        <p>
          Guidance is generated from equipment manuals and may be incomplete. Always follow site safety rules.
          If unsure, stop and call the lead engineer.
        </p>
      </footer>

      <AppNav route={route} variant="bottom" />
    </div>
  )
}
