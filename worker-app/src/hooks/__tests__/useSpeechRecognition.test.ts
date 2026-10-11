// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeRecognition } from '../../speech/__tests__/fakeRecognition.ts'
import { useSpeechRecognition } from '../useSpeechRecognition.ts'

function setup() {
  const onTranscript = vi.fn<(text: string) => void>()
  const hook = renderHook(() => useSpeechRecognition({ onTranscript }))
  return { onTranscript, ...hook }
}

beforeEach(() => {
  FakeRecognition.reset()
  vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
  vi.stubGlobal('isSecureContext', true)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useSpeechRecognition: lifecycle', () => {
  it('does not create a recognizer (or touch the mic) until start()', () => {
    const { result } = setup()
    expect(result.current.support.status).toBe('supported')
    expect(result.current.status).toBe('idle')
    expect(FakeRecognition.instances).toHaveLength(0)
  })

  it('configures and starts recognition, then reports listening', () => {
    const { result } = setup()
    act(() => void result.current.start())
    const rec = FakeRecognition.last
    expect(rec.startCalls).toBe(1)
    expect(rec.lang).toBe('en-IN')
    expect(rec.continuous).toBe(true)
    expect(rec.interimResults).toBe(true)
    expect(result.current.status).toBe('starting')

    act(() => rec.emitStart())
    expect(result.current.status).toBe('listening')
  })

  it('shows interim text and emits final text', () => {
    const { result, onTranscript } = setup()
    act(() => void result.current.start())
    const rec = FakeRecognition.last
    act(() => rec.emitStart())

    act(() => rec.emitResult(0, [['compressor is', false]]))
    expect(result.current.interim).toBe('compressor is')
    expect(onTranscript).not.toHaveBeenCalled()

    act(() => rec.emitResult(0, [['compressor is overheating', true]]))
    expect(onTranscript).toHaveBeenLastCalledWith('compressor is overheating')
    expect(result.current.interim).toBe('')

    act(() => rec.emitResult(1, [['compressor is overheating', true], ['near the cooler', false]]))
    expect(result.current.interim).toBe('near the cooler')
  })

  it('stop() waits for final results, then returns to idle on end', () => {
    const { result, onTranscript } = setup()
    act(() => void result.current.start())
    const rec = FakeRecognition.last
    act(() => rec.emitStart())
    act(() => result.current.stop())
    expect(rec.stopCalls).toBe(1)
    expect(result.current.status).toBe('stopping')

    act(() => rec.emitResult(0, [['belt is slipping', true]]))
    expect(onTranscript).toHaveBeenLastCalledWith('belt is slipping')

    act(() => rec.emitEnd())
    expect(result.current.status).toBe('idle')
  })

  it('force-closes if the browser never ends after stop()', () => {
    vi.useFakeTimers()
    const { result } = setup()
    act(() => void result.current.start())
    const rec = FakeRecognition.last
    act(() => result.current.stop())
    act(() => void vi.advanceTimersByTime(3000))
    expect(rec.abortCalls).toBe(1)
    expect(result.current.status).toBe('idle')
  })

  it('returns to idle when the browser ends the session on its own', () => {
    const { result } = setup()
    act(() => void result.current.start())
    act(() => FakeRecognition.last.emitStart())
    act(() => FakeRecognition.last.emitEnd())
    expect(result.current.status).toBe('idle')
  })

  it('abort() stops immediately and ignores late results', () => {
    const { result, onTranscript } = setup()
    act(() => void result.current.start())
    const rec = FakeRecognition.last
    act(() => result.current.abort())
    expect(rec.abortCalls).toBe(1)
    expect(result.current.status).toBe('idle')

    act(() => rec.emitResult(0, [['late words', true]]))
    expect(onTranscript).not.toHaveBeenCalled()
  })

  it('aborts on unmount', () => {
    const { result, unmount } = setup()
    act(() => void result.current.start())
    const rec = FakeRecognition.last
    unmount()
    expect(rec.abortCalls).toBe(1)
  })

  it('can record a second session after the first ends', () => {
    const { result } = setup()
    act(() => void result.current.start())
    act(() => FakeRecognition.last.emitEnd())
    act(() => void result.current.start())
    expect(FakeRecognition.instances).toHaveLength(2)
    expect(result.current.status).toBe('starting')
  })
})

describe('useSpeechRecognition: repeated clicks and duplicates', () => {
  it('ignores start() while a session is active', () => {
    const { result } = setup()
    let second: boolean | undefined
    act(() => {
      void result.current.start()
      second = result.current.start()
    })
    expect(second).toBe(false)
    expect(FakeRecognition.instances).toHaveLength(1)
    expect(FakeRecognition.last.startCalls).toBe(1)
  })

  it('does not duplicate text when the same final result is delivered twice', () => {
    const { result, onTranscript } = setup()
    act(() => void result.current.start())
    const rec = FakeRecognition.last
    act(() => rec.emitResult(0, [['oil is leaking', true]]))
    act(() => rec.emitResult(0, [['oil is leaking', true]]))
    expect(onTranscript).toHaveBeenCalledTimes(1)
    expect(onTranscript).toHaveBeenLastCalledWith('oil is leaking')
  })

  it('does not duplicate cumulative finals delivered at new indices (Android Chrome)', () => {
    const { result, onTranscript } = setup()
    act(() => void result.current.start())
    const rec = FakeRecognition.last
    act(() => rec.emitResult(0, [['pressure', true]]))
    act(() => rec.emitResult(1, [['pressure', true], ['pressure is low', true]]))
    expect(onTranscript).toHaveBeenLastCalledWith('pressure is low')
  })

  it('accumulates distinct finals across results', () => {
    const { result, onTranscript } = setup()
    act(() => void result.current.start())
    const rec = FakeRecognition.last
    act(() => rec.emitResult(0, [['compressor is hot', true]]))
    act(() => rec.emitResult(1, [['compressor is hot', true], ['and smells burnt', true]]))
    expect(onTranscript).toHaveBeenLastCalledWith('compressor is hot and smells burnt')
  })
})

describe('useSpeechRecognition: errors and support', () => {
  it.each([
    ['not-allowed', 'permission'],
    ['service-not-allowed', 'permission'],
    ['audio-capture', 'no-microphone'],
    ['no-speech', 'no-speech'],
    ['network', 'network'],
  ])('maps %s to a %s error and ends cleanly', (code, kind) => {
    const { result } = setup()
    act(() => void result.current.start())
    const rec = FakeRecognition.last
    act(() => rec.emitError(code))
    act(() => rec.emitEnd())
    expect(result.current.error?.kind).toBe(kind)
    expect(result.current.status).toBe('idle')
  })

  it('does not report our own abort as an error', () => {
    const { result } = setup()
    act(() => void result.current.start())
    const rec = FakeRecognition.last
    act(() => rec.emitError('aborted'))
    expect(result.current.error).toBeNull()
  })

  it('clears the previous error when a new session starts', () => {
    const { result } = setup()
    act(() => void result.current.start())
    act(() => FakeRecognition.last.emitError('no-speech'))
    act(() => FakeRecognition.last.emitEnd())
    expect(result.current.error).not.toBeNull()
    act(() => void result.current.start())
    expect(result.current.error).toBeNull()
  })

  it('reports a failure if the browser refuses to start', () => {
    const OriginalStart = FakeRecognition.prototype.start
    FakeRecognition.prototype.start = function () {
      throw new DOMException('nope', 'InvalidStateError')
    }
    try {
      const { result } = setup()
      let started: boolean | undefined
      act(() => {
        started = result.current.start()
      })
      expect(started).toBe(false)
      expect(result.current.status).toBe('idle')
      expect(result.current.error?.kind).toBe('failed')
    } finally {
      FakeRecognition.prototype.start = OriginalStart
    }
  })

  it('reports unsupported browsers without creating a recognizer', () => {
    vi.stubGlobal('webkitSpeechRecognition', undefined)
    const { result } = setup()
    expect(result.current.support.status).toBe('unsupported')
    let started: boolean | undefined
    act(() => {
      started = result.current.start()
    })
    expect(started).toBe(false)
    expect(FakeRecognition.instances).toHaveLength(0)
  })

  it('reports insecure contexts', () => {
    vi.stubGlobal('isSecureContext', false)
    const { result } = setup()
    expect(result.current.support.status).toBe('insecure')
  })
})
