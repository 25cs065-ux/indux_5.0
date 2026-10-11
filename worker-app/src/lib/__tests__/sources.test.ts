import { describe, expect, it } from 'vitest'
import { pageLabel, uniqueSources } from '../sources.ts'

describe('uniqueSources', () => {
  it('removes exact duplicates and keeps order', () => {
    expect(
      uniqueSources([
        { manual: 'B', page: 2 },
        { manual: 'A', page: 1 },
        { manual: 'B', page: 2 },
        { manual: 'B', page: 3 },
        { manual: 'A', page: null },
        { manual: 'A', page: null },
      ]),
    ).toEqual([
      { manual: 'B', page: 2 },
      { manual: 'A', page: 1 },
      { manual: 'B', page: 3 },
      { manual: 'A', page: null },
    ])
  })
})

describe('pageLabel', () => {
  it('formats a page number', () => expect(pageLabel(42)).toBe('p. 42'))
  it('says when no page was given', () => expect(pageLabel(null)).toBe('page not given'))
})
