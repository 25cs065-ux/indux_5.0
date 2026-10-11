import { useEffect, useState } from 'react'
import type { AskResult } from '../../api/index.ts'
import { useSpeechSynthesis } from '../../hooks/useSpeechSynthesis.ts'
import { acknowledgementItemsOf, safetyStateOf, stepsGateOf } from '../../lib/safety.ts'
import { buildReadAloudScript } from '../../speech/readAloud.ts'
import ReadAloud from './ReadAloud.tsx'
import SafetyPanel from './SafetyPanel.tsx'
import SourcesList from './SourcesList.tsx'
import StepsList from './StepsList.tsx'

interface Props {
  result: AskResult
}

/**
 * One diagnosis. Mount with a fresh `key` per response so acknowledgement
 * never carries over from a previous answer. Unmounting also stops any
 * speech, so a new diagnosis or a changed answer always silences the old one.
 */
export default function ResultView({ result }: Props) {
  const { answer } = result
  const found = answer.status === 'OK'
  const safety = safetyStateOf(answer)
  const gate = stepsGateOf(answer)
  const ackItems = acknowledgementItemsOf(answer)
  const [checked, setChecked] = useState<boolean[]>(() => ackItems.map(() => false))
  const acknowledged = ackItems.length > 0 && checked.length === ackItems.length && checked.every(Boolean)

  const toggle = (index: number) =>
    setChecked((prev) => prev.map((value, i) => (i === index ? !value : value)))

  const stepsVisible = gate === 'allowed' || (gate === 'requires_ack' && acknowledged)
  const tts = useSpeechSynthesis()
  const { stop: stopSpeaking } = tts

  // What is being read must match the screen: if steps lock or unlock while
  // speaking, stop rather than read a script that is now out of date.
  useEffect(() => {
    stopSpeaking()
  }, [stepsVisible, stopSpeaking])

  return (
    <article className="result">
      <dl className="result-meta">
        <div>
          <dt>Machine</dt>
          <dd className="mono">{result.machineId}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd className={`status status--${found ? 'ok' : 'not-found'}`}>
            <span className="mono">{answer.status}</span>
            <span>{found ? 'Manual match' : 'Not in manuals'}</span>
          </dd>
        </div>
        {found && (
          <div>
            <dt>Category</dt>
            <dd className="mono">{answer.problemType}</dd>
          </div>
        )}
      </dl>

      {result.isDemo && (
        <p className="demo-stamp" role="note">
          <span className="mono">DEMO</span> This is a demo response, not a live diagnosis.
        </p>
      )}

      <blockquote className="result-question">
        <span className="visually-hidden">Your question: </span>
        {result.question}
      </blockquote>

      <ReadAloud
        supported={tts.supported}
        speaking={tts.isSpeaking}
        error={tts.error}
        onRead={() => void tts.speak(buildReadAloudScript(result, { stepsVisible }))}
        onStop={tts.stop}
      />

      {result.issues.length > 0 && <ResponseIssues issues={result.issues} />}

      <SafetyPanel
        state={safety}
        checklist={answer.safetyChecklist}
        ackItems={ackItems}
        checked={checked}
        onToggle={toggle}
      />

      {found ? (
        <>
          {answer.escalate && (
            <div className="notice notice--escalate" role="note">
              <p className="notice-code">Escalate</p>
              <p className="notice-title">Escalation recommended</p>
              <p className="notice-body">
                The assistant recommends involving the lead engineer for this issue.
              </p>
            </div>
          )}

          <section className="guidance" aria-labelledby="guidance-title">
            <header className="block-head">
              <h3 id="guidance-title" className="block-title">
                Manual guidance
              </h3>
              <span className="block-note">Generated from equipment manuals</span>
            </header>

            {answer.summary ? (
              <p className="result-summary-text">{answer.summary}</p>
            ) : (
              <p className="result-summary-text result-summary-text--empty">The assistant returned no summary.</p>
            )}

            <StepsList steps={answer.steps} gate={gate} acknowledged={acknowledged} />
            <SourcesList sources={answer.sources} hasSteps={answer.steps.length > 0} />
          </section>
        </>
      ) : (
        <section className="not-found" aria-labelledby="not-found-title">
          <p className="not-found-code mono">NOT_FOUND</p>
          <h3 id="not-found-title" className="not-found-title">
            No answer found in the manuals
          </h3>
          {answer.summary && <p className="not-found-summary">{answer.summary}</p>}
          <div className="not-found-action">
            <p className="notice-code">Escalation required</p>
            <p>
              <strong>Contact the lead engineer.</strong> Do not attempt a repair based on this response.
            </p>
          </div>
        </section>
      )}

      {answer.historyNote && (
        <aside className="history" aria-labelledby="history-title">
          <header className="block-head">
            <h3 id="history-title" className="block-title">
              Repair history
            </h3>
            <span className="block-note">Context from site records · not manual guidance</span>
          </header>
          <p className="history-text">{answer.historyNote}</p>
        </aside>
      )}
    </article>
  )
}

function ResponseIssues({ issues }: { issues: string[] }) {
  return (
    <div className="notice notice--incomplete" role="note">
      <p className="notice-code">Incomplete response</p>
      <p className="notice-body">
        Part of this response was missing or invalid. Missing items are shown as absent, not filled in. Review
        carefully and escalate if anything is unclear.
      </p>
      <details className="issues-details">
        <summary>
          {issues.length} technical detail{issues.length === 1 ? '' : 's'}
        </summary>
        <ul>
          {issues.map((issue) => (
            <li key={issue} className="mono">
              {issue}
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}
