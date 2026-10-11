import BackendStatus from './components/BackendStatus.tsx'
import { API_BASE_URL, IS_DEV } from './config.ts'

const FEATURES = [
  {
    title: 'Speak or type',
    body: 'Describe the fault in your own words. Edit the text before you send it.',
  },
  {
    title: 'Safety first',
    body: 'Hazards and safety checks appear before any repair steps.',
  },
  {
    title: 'Manual-backed steps',
    body: 'Numbered steps with the manual name and page for every answer.',
  },
]

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">I</span>
          <div>
            <h1 className="brand-name">Indux Assistant</h1>
            <p className="brand-tagline">Air compressor troubleshooting</p>
          </div>
        </div>
      </header>

      <main className="app-main">
        <section className="hero" aria-labelledby="hero-title">
          <h2 id="hero-title">What is wrong with the machine?</h2>
          <p>
            Enter the machine ID, describe the problem, and get safe, step-by-step
            guidance from the equipment manuals.
          </p>
          <button type="button" className="btn btn-primary btn-block" disabled>
            Start troubleshooting
          </button>
          <p className="hint">Question entry arrives in the next stage.</p>
        </section>

        <ul className="feature-list">
          {FEATURES.map((f) => (
            <li key={f.title} className="card">
              <h3>{f.title}</h3>
              <p>{f.body}</p>
            </li>
          ))}
        </ul>
      </main>

      <footer className="app-footer">
        <BackendStatus />
        <p>Always follow site safety rules. If unsure, stop and call your lead engineer.</p>
        {IS_DEV && (
          <p className="dev-note">
            API: <code>{API_BASE_URL}</code>
          </p>
        )}
      </footer>
    </div>
  )
}
