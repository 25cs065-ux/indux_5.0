// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { hrefFor, routeFromHash, useHashRoute } from '../useHashRoute.ts'

afterEach(() => window.history.replaceState(null, '', '/'))

describe('routeFromHash', () => {
  it.each([
    ['#/equipment', 'equipment'],
    ['#/diagnose', 'diagnose'],
    ['#/history', 'history'],
    ['#/DIAGNOSE', 'diagnose'],
    ['#diagnose', 'diagnose'],
    ['#/diagnose/extra', 'diagnose'],
    ['', 'equipment'],
    ['#', 'equipment'],
    ['#/', 'equipment'],
    ['#/unknown', 'equipment'],
    ['#/settings', 'equipment'],
  ])('%j -> %s', (hash, route) => {
    expect(routeFromHash(hash)).toBe(route)
  })

  it('builds hrefs', () => {
    expect(hrefFor('history')).toBe('#/history')
  })
})

describe('useHashRoute', () => {
  it('reads the current hash and follows hashchange (back/forward)', () => {
    window.history.replaceState(null, '', '/#/history')
    const { result } = renderHook(() => useHashRoute())
    expect(result.current[0]).toBe('history')

    act(() => {
      window.history.replaceState(null, '', '/#/diagnose')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(result.current[0]).toBe('diagnose')
  })

  it('navigate() updates the hash and keeps the ?machine= query', () => {
    window.history.replaceState(null, '', '/?machine=compressor-02#/equipment')
    const { result } = renderHook(() => useHashRoute())
    act(() => {
      result.current[1]('diagnose')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(window.location.hash).toBe('#/diagnose')
    expect(window.location.search).toBe('?machine=compressor-02')
    expect(result.current[0]).toBe('diagnose')
  })
})
