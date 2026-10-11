import { useCallback, useSyncExternalStore } from 'react'

// Minimal hash router: #/equipment, #/diagnose, #/history.
// Hash routes need no server rewrites (static hosting, Vercel) and leave the
// ?machine= query from QR codes untouched.

export const ROUTES = ['equipment', 'diagnose', 'history'] as const
export type Route = (typeof ROUTES)[number]

export const DEFAULT_ROUTE: Route = 'equipment'

export function routeFromHash(hash: string): Route {
  const name = hash.replace(/^#\/?/, '').split(/[/?#]/)[0]?.toLowerCase() ?? ''
  return (ROUTES as readonly string[]).includes(name) ? (name as Route) : DEFAULT_ROUTE
}

export function hrefFor(route: Route): string {
  return `#/${route}`
}

function subscribe(onChange: () => void) {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

const getSnapshot = () => routeFromHash(window.location.hash)

export function useHashRoute(): [Route, (route: Route) => void] {
  const route = useSyncExternalStore(subscribe, getSnapshot, () => DEFAULT_ROUTE)
  const navigate = useCallback((next: Route) => {
    const href = hrefFor(next)
    if (window.location.hash !== href) window.location.hash = href
  }, [])
  return [route, navigate]
}
