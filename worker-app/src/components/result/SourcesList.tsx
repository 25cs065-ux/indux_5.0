import type { SourceReference } from '../../api/types.ts'
import { pageLabel, uniqueSources } from '../../lib/sources.ts'

interface Props {
  sources: SourceReference[]
  hasSteps: boolean
}

export default function SourcesList({ sources, hasSteps }: Props) {
  const unique = uniqueSources(sources)

  return (
    <div className="sources">
      <h4 className="sources-heading">References</h4>
      {unique.length > 0 ? (
        <ul className="sources-list">
          {unique.map((s, i) => (
            <li key={`${s.manual}-${s.page ?? 'x'}-${i}`} className="source">
              <span className="source-manual mono">{s.manual}</span>
              <span className={`source-page mono ${s.page === null ? 'is-missing' : ''}`}>{pageLabel(s.page)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="sources-missing">
          No manual reference was returned
          {hasSteps ? '. Check the steps against the equipment manual before acting.' : '.'}
        </p>
      )}
    </div>
  )
}
