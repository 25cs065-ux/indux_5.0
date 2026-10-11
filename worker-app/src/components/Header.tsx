import BackendStatus from './BackendStatus.tsx'

export default function Header() {
  return (
    <header className="masthead">
      <div className="masthead-inner">
        <div className="wordmark">
          <span className="wordmark-name">INDUX</span>
          <span className="wordmark-divider" aria-hidden="true" />
          <span className="wordmark-product">Field Assistant</span>
        </div>
        <div className="masthead-meta">
          <span className="masthead-scope">Air compressors</span>
          <BackendStatus />
        </div>
      </div>
    </header>
  )
}
