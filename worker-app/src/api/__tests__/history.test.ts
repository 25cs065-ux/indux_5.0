// Mock-response tests for the repair-history parser and client.
// These do NOT verify the real backend; see README "Repair history".
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HISTORY_TIMEOUT_MS, getRepairHistory } from '../client.ts'
import { ApiError } from '../errors.ts'
import { HISTORY_LIMIT, parseRepairHistory } from '../history.ts'
import { historyEnvelope, historyRow, jsonResponse } from './fixtures.ts'

const parse = (history: unknown, machineId = 'compressor-01') =>
  parseRepairHistory(historyEnvelope(history, machineId), machineId)

describe('parseRepairHistory', () => {
  it('parses records with date, problem, action and outcome', () => {
    const { records, issues } = parse([historyRow()])
    expect(issues).toEqual([])
    expect(records).toHaveLength(1)
    const r = records[0]!
    expect(r.key).toBe('a1')
    expect(r.problem).toBe('TEST: High temperature warning')
    expect(r.action).toBe('TEST: Cleaned cooler fins')
    expect(r.outcome).toBe('TEST: Resolved')
    expect(r.recordedAtRaw).toBe('2026-05-06T09:30:00+00:00')
    expect(r.recordedAt?.toISOString()).toBe('2026-05-06T09:30:00.000Z')
  })

  it('keeps the backend order (newest first) without re-sorting', () => {
    const { records } = parse([
      historyRow({ id: 'new', created_at: '2026-05-06T00:00:00Z' }),
      historyRow({ id: 'old', created_at: '2026-01-12T00:00:00Z' }),
    ])
    expect(records.map((r) => r.key)).toEqual(['new', 'old'])
  })

  it('returns an empty list for an empty history', () => {
    expect(parse([]).records).toEqual([])
  })

  it('leaves missing or empty fields as null instead of inventing values', () => {
    const { records } = parse([
      historyRow({ id: 'x', problem: '  ', action: undefined, outcome: '' , created_at: '2026-01-01T00:00:00Z' }),
      historyRow({ id: 'y', outcome: null }),
      historyRow({ id: 'z', problem: 'Only a problem', action: '', outcome: '' }),
    ])
    // The all-empty row is dropped rather than shown with invented text.
    expect(records.map((r) => r.key)).toEqual(['y', 'z'])
    expect(records[0]!.outcome).toBeNull()
    expect(records[1]).toMatchObject({ problem: 'Only a problem', action: null, outcome: null })
  })

  it('keeps a record with only some fields', () => {
    const { records } = parse([{ machine_id: 'compressor-01', action: 'Replaced belt' }])
    expect(records).toHaveLength(1)
    expect(records[0]).toMatchObject({ problem: null, action: 'Replaced belt', outcome: null, recordedAt: null })
  })

  it('drops rows with no problem, action or outcome', () => {
    const { records, issues } = parse([historyRow({ problem: '', action: '', outcome: '' })])
    expect(records).toEqual([])
    expect(issues).toContain('history[0] has no problem, action or outcome and was dropped')
  })

  it('never shows a row for another machine', () => {
    const { records, issues } = parse([historyRow(), historyRow({ id: 'b', machine_id: 'compressor-02' })])
    expect(records.map((r) => r.key)).toEqual(['a1'])
    expect(issues).toContain('history[1] is for a different machine and was dropped')
  })

  it('matches machine IDs exactly (no normalization)', () => {
    const { records } = parse([historyRow({ machine_id: 'compressor_01' })], 'compressor-01')
    expect(records).toEqual([])
  })

  it('drops rows that are not objects', () => {
    const { records, issues } = parse(['text', null, 42, historyRow()])
    expect(records).toHaveLength(1)
    expect(issues.filter((i) => i.includes('is not a record'))).toHaveLength(3)
  })

  it('treats a missing or invalid created_at as not recorded', () => {
    const { records, issues } = parse([historyRow({ created_at: undefined }), historyRow({ id: 'b', created_at: 'yesterday' })])
    expect(records[0]!.recordedAt).toBeNull()
    expect(records[0]!.recordedAtRaw).toBeNull()
    expect(records[1]!.recordedAt).toBeNull()
    expect(issues).toContain('history[0].created_at is missing')
    expect(issues).toContain('history[1].created_at is invalid')
  })

  it('ignores unknown columns', () => {
    const { records } = parse([historyRow({ technician: 'X', severity: 'high', resolved: true })])
    expect(Object.keys(records[0]!).sort()).toEqual(
      ['action', 'key', 'outcome', 'problem', 'recordedAt', 'recordedAtRaw'].sort(),
    )
  })

  it('uses the row position as key when there is no id', () => {
    expect(parse([historyRow({ id: undefined })]).records[0]!.key).toBe('row-0')
    expect(parse([historyRow({ id: 7 })]).records[0]!.key).toBe('7')
  })

  it('notes a non-success status', () => {
    const body = { status: 'partial', machine_id: 'compressor-01', history: [] }
    expect(parseRepairHistory(body, 'compressor-01').issues).toContain('status is not "success"')
  })

  it.each([
    ['null body', null],
    ['missing history', { status: 'success', machine_id: 'compressor-01' }],
    ['history is not a list', { status: 'success', history: {} }],
    ['history is null', { status: 'success', history: null }],
    ['string body', 'Internal Server Error'],
  ])('rejects %s as malformed', (_label, body) => {
    try {
      parseRepairHistory(body, 'compressor-01')
      expect.unreachable('expected malformed')
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError)
      expect((e as ApiError).kind).toBe('malformed')
    }
  })

  it('exposes the backend row limit', () => {
    expect(HISTORY_LIMIT).toBe(50)
  })
})

describe('getRepairHistory', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('GETs /api/history/{machine_id} through the proxy', async () => {
    fetchMock.mockResolvedValue(jsonResponse(historyEnvelope([historyRow()])))
    const result = await getRepairHistory('compressor-01')
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/history/compressor-01')
    expect(init?.method).toBe('GET')
    expect(init?.body).toBeUndefined()
    expect(result.records).toHaveLength(1)
  })

  it('URL-encodes the machine ID without changing it', async () => {
    fetchMock.mockResolvedValue(jsonResponse(historyEnvelope([], 'Compressor 09/B')))
    await getRepairHistory('Compressor 09/B')
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/history/Compressor%2009%2FB')
  })

  it('rejects an empty machine ID without calling the server', async () => {
    await expect(getRepairHistory('  ')).rejects.toMatchObject({ kind: 'validation' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('maps 503 to unavailable with the backend message', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Could not retrieve repair history.' }, 503))
    await expect(getRepairHistory('compressor-01')).rejects.toMatchObject({
      kind: 'unavailable',
      status: 503,
      message: 'Could not retrieve repair history.',
    })
  })

  it('maps network failures', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(getRepairHistory('compressor-01')).rejects.toMatchObject({ kind: 'network' })
  })

  it('times out after HISTORY_TIMEOUT_MS', async () => {
    vi.useFakeTimers()
    fetchMock.mockImplementation(
      (_i, init) =>
        new Promise((_res, rej) =>
          init?.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError'))),
        ),
    )
    const pending = getRepairHistory('compressor-01').catch((e: unknown) => e)
    await vi.advanceTimersByTimeAsync(HISTORY_TIMEOUT_MS)
    expect(await pending).toMatchObject({ kind: 'timeout' })
  })
})
