// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { hasOuterWhitespace, initialMachineId, machineFromSearch, saveLastMachine } from '../machineParam.ts'

// Node 25 exposes its own (non-functional without a file) localStorage that
// shadows jsdom's, so use a small in-memory Storage for these tests.
function memoryStorage(): Storage {
  const data = new Map<string, string>()
  return {
    get length() {
      return data.size
    },
    clear: () => data.clear(),
    getItem: (k) => data.get(k) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (k) => void data.delete(k),
    setItem: (k, v) => void data.set(k, String(v)),
  }
}

beforeEach(() => vi.stubGlobal('localStorage', memoryStorage()))
afterEach(() => vi.unstubAllGlobals())

describe('machineFromSearch', () => {
  it('reads ?machine= exactly as given', () => {
    expect(machineFromSearch('?machine=compressor-01')).toBe('compressor-01')
    expect(machineFromSearch('?machine=compressor_01')).toBe('compressor_01')
    expect(machineFromSearch('?machine=Compressor-01')).toBe('Compressor-01')
  })

  it('does not trim or normalize', () => {
    expect(machineFromSearch('?machine=%20compressor-01')).toBe(' compressor-01')
  })

  it('returns null when absent or blank', () => {
    expect(machineFromSearch('')).toBeNull()
    expect(machineFromSearch('?machine=')).toBeNull()
    expect(machineFromSearch('?machine=%20%20')).toBeNull()
  })
})

describe('initialMachineId', () => {
  it('prefers the QR link over the last used machine', () => {
    saveLastMachine('compressor-02')
    expect(initialMachineId('?machine=compressor-01')).toBe('compressor-01')
  })

  it('falls back to the last used machine', () => {
    saveLastMachine('compressor_02')
    expect(initialMachineId('')).toBe('compressor_02')
  })

  it('has no default machine', () => {
    expect(initialMachineId('')).toBe('')
  })
})

describe('hasOuterWhitespace', () => {
  it('detects leading or trailing spaces', () => {
    expect(hasOuterWhitespace(' a')).toBe(true)
    expect(hasOuterWhitespace('a ')).toBe(true)
    expect(hasOuterWhitespace('a b')).toBe(false)
  })
})
