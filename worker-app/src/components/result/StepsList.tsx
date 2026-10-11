import type { TroubleshootingStep } from '../../api/types.ts'
import type { StepsGate } from '../../lib/safety.ts'

interface Props {
  steps: TroubleshootingStep[]
  gate: StepsGate
  acknowledged: boolean
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

export default function StepsList({ steps, gate, acknowledged }: Props) {
  const count = steps.length
  const label = `${count} step${count === 1 ? '' : 's'}`

  if (gate === 'none') {
    return <p className="steps-empty">No troubleshooting steps were returned.</p>
  }

  if (gate === 'withheld') {
    return (
      <div className="steps-locked steps-locked--withheld" role="note">
        <p className="steps-locked-code mono">Withheld · {label}</p>
        <p className="steps-locked-text">
          Steps are not shown because the safety status of this job is unknown. Contact the lead engineer.
        </p>
      </div>
    )
  }

  if (gate === 'withheld_no_checklist') {
    return (
      <div className="steps-locked steps-locked--withheld" role="note">
        <p className="steps-locked-code mono">Withheld · {label}</p>
        <p className="steps-locked-text">
          Steps are not shown because a hazard was flagged without a safety checklist. Contact a qualified
          supervisor and follow the applicable site safety procedures.
        </p>
      </div>
    )
  }

  if (gate === 'requires_ack' && !acknowledged) {
    return (
      <div className="steps-locked" role="note">
        <p className="steps-locked-code mono">Locked · {label}</p>
        <p className="steps-locked-text">Complete every safety check above to view the steps.</p>
      </div>
    )
  }

  return (
    <ol className="steps" aria-label="Troubleshooting steps">
      {steps.map((step, i) => (
        <li key={`${step.stepNo}-${i}`} className="step">
          <span className="step-no mono" aria-hidden="true">
            {pad(step.stepNo)}
          </span>
          <div className="step-body">
            <p className="step-instruction">
              <span className="visually-hidden">Step {step.stepNo}: </span>
              {step.instruction}
            </p>
            {step.checkQuestion && (
              <p className="step-check">
                <span className="step-check-label mono">Check</span>
                {step.checkQuestion}
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}
