import { useId, useState } from 'react'
import { MACHINES } from '../data/machines.ts'
import { hasOuterWhitespace } from '../lib/machineParam.ts'

interface Props {
  value: string
  onChange: (machineId: string) => void
  error?: string | null
  disabled?: boolean
}

const OTHER = '__other__'

export default function MachineSelect({ value, onChange, error, disabled }: Props) {
  const baseId = useId()
  const isPreset = MACHINES.some((m) => m.machine_id === value)
  const [otherMode, setOtherMode] = useState(!isPreset && value !== '')
  const selected = otherMode ? OTHER : isPreset ? value : ''
  const groupName = `${baseId}-machine`
  const otherInputId = `${baseId}-other`
  const errorId = `${baseId}-error`

  return (
    <fieldset className="machine" disabled={disabled} aria-describedby={error ? errorId : undefined}>
      <legend className="visually-hidden">Machine</legend>

      <div className="plates">
        {MACHINES.map((m) => (
          <label key={m.machine_id} className={`plate ${selected === m.machine_id ? 'is-selected' : ''}`}>
            <input
              type="radio"
              name={groupName}
              value={m.machine_id}
              checked={selected === m.machine_id}
              onChange={() => {
                setOtherMode(false)
                onChange(m.machine_id)
              }}
            />
            <span className="plate-id">{m.machine_id}</span>
            <span className="plate-name">{m.name}</span>
            <span className="plate-spec">
              {m.model} <span aria-hidden="true">·</span> {m.location}
            </span>
          </label>
        ))}

        <label className={`plate plate--other ${selected === OTHER ? 'is-selected' : ''}`}>
          <input
            type="radio"
            name={groupName}
            value={OTHER}
            checked={selected === OTHER}
            onChange={() => {
              setOtherMode(true)
              if (isPreset) onChange('')
            }}
          />
          <span className="plate-id">Other ID</span>
          <span className="plate-spec">A machine not listed here</span>
        </label>
      </div>

      {otherMode && (
        <div className="field">
          <label htmlFor={otherInputId} className="field-label">
            Machine ID
          </label>
          <input
            id={otherInputId}
            className="input input--mono"
            type="text"
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="e.g. compressor-03"
            aria-invalid={!!error}
          />
          <p className="field-note">
            Sent exactly as typed.
            {hasOuterWhitespace(value) && <strong> Contains leading or trailing spaces.</strong>}
          </p>
        </div>
      )}

      {error && (
        <p id={errorId} className="field-error" role="alert">
          {error}
        </p>
      )}
    </fieldset>
  )
}
