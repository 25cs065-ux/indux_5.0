import { useId } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'

export const QUESTION_MAX_LENGTH = 1000

interface Props {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  isLoading: boolean
  error?: string | null
}

export default function IssueForm({ value, onChange, onSubmit, isLoading, error }: Props) {
  const id = useId()
  const errorId = `${id}-error`
  const voiceNoteId = `${id}-voice`

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
          id={id}
          className="textarea"
          rows={5}
          maxLength={QUESTION_MAX_LENGTH}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="What do you see, hear or smell? Include alarm codes or gauge readings."
          aria-invalid={!!error}
          aria-describedby={error ? errorId : undefined}
          readOnly={isLoading}
        />
        {error && (
          <p id={errorId} className="field-error" role="alert">
            {error}
          </p>
        )}
      </div>

      <div className="actions">
        <button type="button" className="btn btn-secondary" disabled aria-describedby={voiceNoteId}>
          <span className="btn-glyph" aria-hidden="true" />
          Record issue
          <span className="btn-tag">Not available yet</span>
        </button>
        <button type="submit" className="btn btn-primary" disabled={isLoading} aria-busy={isLoading}>
          <span>{isLoading ? 'Diagnosing…' : 'Diagnose'}</span>
          {!isLoading && (
            <span className="btn-arrow" aria-hidden="true">
              →
            </span>
          )}
        </button>
      </div>
      <p id={voiceNoteId} className="field-note">
        Voice recording is not available in this build. Type the issue instead.
      </p>
    </form>
  )
}
