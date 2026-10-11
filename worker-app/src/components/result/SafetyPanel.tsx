import { useId } from 'react'
import type { SafetyState } from '../../lib/safety.ts'

interface Props {
  state: SafetyState
  /** Checklist from the backend (shown read-only unless acknowledgement applies). */
  checklist: string[]
  /** Items requiring acknowledgement. Empty when no acknowledgement is needed. */
  ackItems: string[]
  checked: boolean[]
  onToggle: (index: number) => void
}

export const SAFETY_DISCLAIMER =
  'The assistant cannot confirm that equipment is safe. Follow your site lockout/tagout procedure.'

export const ACK_MEANING =
  'Ticking a box records that you have carried out that check. It does not mean the machine is safe.'

export default function SafetyPanel({ state, checklist, ackItems, checked, onToggle }: Props) {
  const baseId = useId()

  if (state === 'flagged') {
    const done = checked.filter(Boolean).length
    const total = ackItems.length
    return (
      <section className="safety safety--flagged" aria-labelledby={`${baseId}-title`}>
        <p className="safety-code">Safety · Hazard flagged</p>
        <h3 id={`${baseId}-title`} className="safety-title">
          Stop. Complete these safety checks before any work.
        </h3>

        {total > 0 ? (
          <>
            <ul className="ack-list">
              {ackItems.map((item, i) => {
                const id = `${baseId}-ack-${i}`
                return (
                  <li key={i} className={`ack-item ${checked[i] ? 'is-checked' : ''}`}>
                    <input id={id} type="checkbox" checked={!!checked[i]} onChange={() => onToggle(i)} />
                    <label htmlFor={id}>
                      <span className="ack-index" aria-hidden="true">
                        {String(i + 1).padStart(2, '0')}
                      </span>
                      <span className="ack-text">{item}</span>
                    </label>
                  </li>
                )
              })}
            </ul>
            <p className="ack-progress" aria-live="polite">
              <span className="mono">
                {done}/{total}
              </span>{' '}
              {done === total ? 'checks confirmed. Steps are shown below.' : 'checks confirmed. Steps stay locked until all are ticked.'}
            </p>
            <p className="safety-body safety-body--small">{ACK_MEANING}</p>
          </>
        ) : checklist.length > 0 ? (
          <SafetyList items={checklist} />
        ) : (
          <p className="safety-body">
            The assistant flagged this job as hazardous but provided no safety checklist. Do not start work.
            Contact a qualified supervisor and follow the applicable site safety procedures.
          </p>
        )}

        <p className="safety-foot">{SAFETY_DISCLAIMER}</p>
      </section>
    )
  }

  if (state === 'uncertain') {
    return (
      <section className="safety safety--uncertain" aria-labelledby={`${baseId}-title`}>
        <p className="safety-code">Safety · Status unknown</p>
        <h3 id={`${baseId}-title`} className="safety-title">
          Safety status could not be determined
        </h3>
        <p className="safety-body">
          The response did not say whether this job is hazardous, so repair steps are withheld. Treat the machine
          as hazardous and contact the lead engineer.
        </p>
        {checklist.length > 0 && (
          <>
            <p className="safety-sub">Safety checks returned with this response</p>
            <SafetyList items={checklist} />
          </>
        )}
        <p className="safety-foot">{SAFETY_DISCLAIMER}</p>
      </section>
    )
  }

  return (
    <section className="safety safety--neutral" aria-label="Safety">
      <p className="safety-code">Safety · No hazard flagged</p>
      <p className="safety-body">
        The assistant did not flag a hazard. <strong>This is not a safety clearance.</strong>
      </p>
      <p className="safety-foot">{SAFETY_DISCLAIMER}</p>
    </section>
  )
}

function SafetyList({ items }: { items: string[] }) {
  return (
    <ol className="safety-list">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ol>
  )
}
