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
  const kind = resultKindOf(answer)
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
          <dd className={`status status--${kind}`}>
            {kind !== 'error' && <span className="mono">{answer.rawStatus}</span>}
            <span>{STATUS_LABELS[kind]}</span>
          </dd>
        </div>
        {(kind === 'ok' || kind === 'alert') && (
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

      {/* A backend failure has its own block; the incomplete notice would only repeat it. */}
      {kind !== 'error' && result.issues.length > 0 && <ResponseIssues issues={result.issues} />}

      <SafetyPanel
        state={safety}
        checklist={answer.safetyChecklist}
        ackItems={ackItems}
        checked={checked}
        onToggle={toggle}
      />

      {kind === 'ok' && answer.escalate && (
        <div className="notice notice--escalate" role="note">
          <p className="notice-code">Escalate</p>
          <p className="notice-title">Escalation recommended</p>
          <p className="notice-body">The assistant recommends involving the lead engineer for this issue.</p>
        </div>
      )}

      {kind === 'alert' && (
        <div className="notice notice--alert" role="alert">
          <p className="notice-code">Safety alert · Escalation required</p>
          <p className="notice-title">Do not start work. Contact the lead engineer.</p>
          <p className="notice-body">
            Troubleshooting steps are withheld for safety alerts. Complete the safety actions above and follow
            the applicable site safety procedures.
          </p>
        </div>
      )}

      {(kind === 'ok' || kind === 'alert') && (
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
      )}

      {kind === 'not-found' && (
        <section className="not-found" aria-labelledby="not-found-title">
          <p className="not-found-code mono">{answer.rawStatus}</p>
          <h3 id="not-found-title" className="not-found-title">
            No verified manual guidance found
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

      {kind === 'error' && (
        <section className="not-found not-found--error" aria-labelledby="error-title">
          <p className="not-found-code mono">Assistant error</p>
          <h3 id="error-title" className="not-found-title">
            The assistant could not complete this diagnosis
          </h3>
          <p className="not-found-summary">
            This is a system problem, not a finding about the machine. Press Diagnose to try again.
          </p>
          <div className="not-found-action">
            <p className="notice-code">Escalation required</p>
            <p>
              <strong>If it happens again, contact the lead engineer.</strong> Do not attempt a repair based on
              this response.
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

type ResultKind = 'ok' | 'alert' | 'not-found' | 'error'

const STATUS_LABELS: Record<ResultKind, string> = {
  ok: 'Manual match',
  alert: 'Safety alert',
  'not-found': 'Not in manuals',
  error: 'Could not complete',
}

function resultKindOf(answer: AskResult['answer']): ResultKind {
  if (answer.internalError) return 'error'
  if (answer.status === 'SAFETY_ALERT') return 'alert'
  if (answer.status === 'NOT_FOUND') return 'not-found'
  return 'ok'
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
