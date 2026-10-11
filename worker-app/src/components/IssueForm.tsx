import { useId } from 'react'
import type { FormEvent, KeyboardEvent, Ref } from 'react'
import type { RecordingStatus } from '../hooks/useSpeechRecognition.ts'
import type { SpeechSupport } from '../speech/support.ts'
import { SPEECH_LANG } from '../speech/support.ts'
import type { SpeechError } from '../speech/transcript.ts'

export const QUESTION_MAX_LENGTH = 1000

export interface SpeechControls {
  support: SpeechSupport
  status: RecordingStatus
  interim: string
  error: SpeechError | null
  onToggle: () => void
}

interface Props {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  isLoading: boolean
  error?: string | null
  speech: SpeechControls
  /** Lets the page focus the field, e.g. after New question. */
  textareaRef?: Ref<HTMLTextAreaElement>
}

export default function IssueForm({ value, onChange, onSubmit, isLoading, error, speech, textareaRef }: Props) {
  const id = useId()
  const errorId = `${id}-error`
  const voiceNoteId = `${id}-voice`
  const recording = speech.status !== 'idle'
  const supported = speech.support.status === 'supported'

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit()
  }

  // Ctrl/Cmd+Enter submits from the textarea.
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      onSubmit()
    }
  }

  return (
    <form className="issue" onSubmit={handleSubmit} noValidate>
      <div className="field">
        <div className="field-head">
          <label htmlFor={id} className="field-label">
            Describe the issue
          </label>
          <span className="field-count" aria-hidden="true">
            {value.length}/{QUESTION_MAX_LENGTH}
          </span>
        </div>
        <textarea
          ref={textareaRef}
          id={id}
          className={`textarea ${recording ? 'is-recording' : ''}`}
          rows={5}
          maxLength={QUESTION_MAX_LENGTH}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="What do you see, hear or smell? Include alarm codes or gauge readings."
          aria-invalid={!!error}
          aria-describedby={error ? errorId : undefined}
          // Locked while listening so typed edits cannot clash with recognised text.
          readOnly={isLoading || recording}
        />
        {recording && <ListeningStrip status={speech.status} interim={speech.interim} />}
        {error && (
          <p id={errorId} className="field-error" role="alert">
            {error}
          </p>
        )}
      </div>

      <div className="actions">
        <RecordButton
          status={speech.status}
          supported={supported}
          disabled={isLoading}
          onToggle={speech.onToggle}
          describedBy={voiceNoteId}
        />
        <button type="submit" className="btn btn-primary" disabled={isLoading} aria-busy={isLoading}>
          <span>{isLoading ? 'Diagnosing…' : 'Diagnose'}</span>
          {!isLoading && (
            <span className="btn-arrow" aria-hidden="true">
              →
            </span>
          )}
        </button>
      </div>

      {speech.error && (
        <p className={`speech-error speech-error--${speech.error.kind}`} role="alert">
          {speech.error.message}
        </p>
      )}
      <p id={voiceNoteId} className="field-note">
        {!supported
          ? speech.support.status !== 'supported' && speech.support.message
          : recording
            ? 'Recognised speech is added to the issue text. Check and edit it before pressing Diagnose.'
            : 'Speak the issue, then check and edit the text. Nothing is sent until you press Diagnose.'}
      </p>
    </form>
  )
}

function RecordButton({
  status,
  supported,
  disabled,
  onToggle,
  describedBy,
}: {
  status: RecordingStatus
  supported: boolean
  disabled: boolean
  onToggle: () => void
  describedBy: string
}) {
  if (!supported) {
    return (
      <button type="button" className="btn btn-secondary btn-record" disabled aria-describedby={describedBy}>
        <span className="btn-glyph" aria-hidden="true" />
        Record issue
        <span className="btn-tag">Unavailable</span>
      </button>
    )
  }

  const active = status === 'listening' || status === 'starting'
  const label =
    status === 'starting' ? 'Starting microphone…' : status === 'listening' ? 'Stop recording' : status === 'stopping' ? 'Finishing…' : 'Record issue'

  return (
    <button
      type="button"
      className={`btn btn-secondary btn-record ${active ? 'is-recording' : ''}`}
      onClick={onToggle}
      disabled={disabled || status === 'stopping'}
      aria-describedby={describedBy}
    >
      <span className={active ? 'btn-glyph btn-glyph--stop' : 'btn-glyph'} aria-hidden="true" />
      {label}
    </button>
  )
}

function ListeningStrip({ status, interim }: { status: RecordingStatus; interim: string }) {
  const label = status === 'starting' ? 'Starting' : status === 'stopping' ? 'Finishing' : 'Listening'
  return (
    <div className={`listening listening--${status}`}>
      <div className="listening-head" role="status">
        <span className="listening-meter" aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
          <i />
        </span>
        <span className="listening-label mono">{label}</span>
        <span className="listening-lang mono" aria-hidden="true">
          {SPEECH_LANG}
        </span>
      </div>
      <p className="listening-interim" aria-hidden="true">
        {interim || (status === 'listening' ? 'Speak now…' : ' ')}
      </p>
    </div>
  )
}
