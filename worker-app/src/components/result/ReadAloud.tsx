import type { SynthesisError } from '../../speech/synthesis.ts'

interface Props {
  supported: boolean
  speaking: boolean
  error: SynthesisError | null
  onRead: () => void
  onStop: () => void
}

export default function ReadAloud({ supported, speaking, error, onRead, onStop }: Props) {
  return (
    <div className="readout" role="group" aria-label="Read aloud">
      <div className="readout-controls">
        <button
          type="button"
          className="btn btn-secondary readout-btn"
          onClick={onRead}
          disabled={!supported || speaking}
        >
          <span className="readout-glyph" aria-hidden="true" />
          Read aloud
        </button>
        <button
          type="button"
          className="btn btn-secondary readout-btn readout-btn--stop"
          onClick={onStop}
          disabled={!speaking}
        >
          <span className="btn-glyph btn-glyph--stop" aria-hidden="true" />
          Stop speaking
        </button>
      </div>

      {speaking && (
        <p className="readout-status" role="status">
          <span className="listening-meter" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
            <i />
          </span>
          <span className="mono">Speaking</span>
        </p>
      )}
      {!supported && <p className="field-note">Read aloud is not available in this browser.</p>}
      {error && (
        <p className="speech-error" role="alert">
          {error.message}
        </p>
      )}
    </div>
  )
}
