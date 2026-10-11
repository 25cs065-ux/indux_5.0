import { describe, expect, it } from 'vitest'
import { pageLabel, uniqueSources } from '../sources.ts'

describe('uniqueSources', () => {
  it('removes exact duplicates and keeps order', () => {
    expect(
      uniqueSources([
        { manual: 'B', page: 2, section: null },
        { manual: 'A', page: 1, section: null },
        { manual: 'B', page: 2, section: null },
        { manual: 'B', page: 3, section: null },
        { manual: 'A', page: null, section: null },
        { manual: 'A', page: null, section: null },
      ]),
    ).toEqual([
      { manual: 'B', page: 2, section: null },
      { manual: 'A', page: 1, section: null },
      { manual: 'B', page: 3, section: null },
      { manual: 'A', page: null, section: null },
    ])
  })
})

describe('pageLabel', () => {
  it('formats a page number', () => expect(pageLabel(42)).toBe('p. 42'))
  it('says when no page was given', () => expect(pageLabel(null)).toBe('page not given'))
})

describe('uniqueSources with sections', () => {
  it('keeps the same page with different sections', () => {
    expect(
      uniqueSources([
        { manual: 'M', page: 8, section: 'Pressure System' },
        { manual: 'M', page: 8, section: 'Cooling' },
        { manual: 'M', page: 8, section: 'Pressure System' },
      ]),
    ).toEqual([
      { manual: 'M', page: 8, section: 'Pressure System' },
      { manual: 'M', page: 8, section: 'Cooling' },
    ])
  })
})
