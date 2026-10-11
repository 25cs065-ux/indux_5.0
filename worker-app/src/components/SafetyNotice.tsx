import type { SafetyState } from '../lib/safety.ts'

interface Props {
  state: SafetyState
  checklist: string[]
}

const CLOSING =
  'The assistant cannot confirm that equipment is safe. Follow your site lockout/tagout procedure.'

export default function SafetyNotice({ state, checklist }: Props) {
  if (state === 'flagged') {
    return (
      <div className="safety safety--flagged" role="alert">
        <p className="safety-code">Safety · Hazard flagged</p>
        <p className="safety-title">Complete these safety checks before any work</p>
        {checklist.length > 0 ? (
          <ol className="safety-list">
            {checklist.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ol>
        ) : (
          <p className="safety-body">
            The assistant flagged this job as dangerous but sent no checklist. Do not proceed without your
            supervisor.
          </p>
        )}
        <p className="safety-foot">{CLOSING}</p>
      </div>
    )
  }

  if (state === 'uncertain') {
    return (
      <div className="safety safety--uncertain" role="alert">
        <p className="safety-code">Safety · Status unknown</p>
        <p className="safety-title">Safety status could not be determined</p>
        <p className="safety-body">
          The response did not say whether this job is hazardous, so repair steps are withheld. Treat the
          machine as hazardous and consult your supervisor.
        </p>
        <p className="safety-foot">{CLOSING}</p>
      </div>
    )
  }

  return (
    <div className="safety safety--neutral">
      <p className="safety-code">Safety · No hazard flagged</p>
      <p className="safety-body">
        The assistant did not flag a hazard. <strong>This is not a safety clearance.</strong>
      </p>
      <p className="safety-foot">{CLOSING}</p>
    </div>
  )
}
