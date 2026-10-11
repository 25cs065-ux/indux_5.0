import type { Route } from '../router/useHashRoute.ts'
import { hrefFor } from '../router/useHashRoute.ts'

const ITEMS: ReadonlyArray<{ route: Route; index: string; label: string }> = [
  { route: 'equipment', index: '01', label: 'Equipment' },
  { route: 'diagnose', index: '02', label: 'Diagnose' },
  { route: 'history', index: '03', label: 'History' },
]

interface Props {
  route: Route
  /** 'top' renders in the masthead (desktop); 'bottom' is the fixed mobile bar. */
  variant: 'top' | 'bottom'
}

export default function AppNav({ route, variant }: Props) {
  return (
    <nav className={`nav nav--${variant}`} aria-label={variant === 'top' ? 'Main' : 'Main (bottom)'}>
      <ul className="nav-list">
        {ITEMS.map((item) => {
          const active = item.route === route
          return (
            <li key={item.route}>
              <a
                href={hrefFor(item.route)}
                className={`nav-link ${active ? 'is-active' : ''}`}
                aria-current={active ? 'page' : undefined}
              >
                <span className="nav-index mono" aria-hidden="true">
                  {item.index}
                </span>
                <span className="nav-label">{item.label}</span>
              </a>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
