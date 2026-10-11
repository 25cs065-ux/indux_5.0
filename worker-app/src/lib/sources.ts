import type { SourceReference } from '../api/types.ts'

/** Removes exact duplicate references while keeping backend order. */
export function uniqueSources(sources: SourceReference[]): SourceReference[] {
  const seen = new Set<string>()
  return sources.filter((s) => {
    const key = `${s.manual}\u0000${s.page ?? ''}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/** "p. 42", or a clear note when the backend sent no usable page. */
export function pageLabel(page: number | null): string {
  return page === null ? 'page not given' : `p. ${page}`
}
