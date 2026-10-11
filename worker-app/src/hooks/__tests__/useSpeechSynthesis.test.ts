// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeSynthesis, FakeUtterance } from '../../speech/__tests__/fakeSynthesis.ts'
import { cancelAllSpeech } from '../../speech/synthesis.ts'
import { useSpeechSynthesis } from '../useSpeechSynthesis.ts'

let synth: FakeSynthesis

beforeEach(() => {
  synth = new FakeSynthesis()
  vi.stubGlobal('speechSynthesis', synth)
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
})

afterEach(() => vi.unstubAllGlobals())

describe('useSpeechSynthesis', () => {
  it('queues each segment and reports speaking until the last one ends', () => {
    const { result } = renderHook(() => useSpeechSynthesis())
    act(() => void result.current.speak(['One.', 'Two.', 'Three.']))
    expect(synth.texts).toEqual(['One.', 'Two.', 'Three.'])
    expect(result.current.isSpeaking).toBe(true)

    act(() => synth.finishNext())
    act(() => synth.finishNext())
    expect(result.current.isSpeaking).toBe(true)
    act(() => synth.finishNext())
    expect(result.current.isSpeaking).toBe(false)
  })

  it('uses an en-IN voice when available', () => {
    synth.voices = [
      { lang: 'en-US', name: 'US' },
      { lang: 'en-IN', name: 'India' },
    ]
    const { result } = renderHook(() => useSpeechSynthesis())
    act(() => void result.current.speak(['Hello.']))
    expect(synth.spoken[0]!.lang).toBe('en-IN')
  })

  it('stop() cancels playback and returns to idle', () => {
    const { result } = renderHook(() => useSpeechSynthesis())
    act(() => void result.current.speak(['One.', 'Two.']))
    const before = synth.cancelCalls
    act(() => result.current.stop())
    expect(synth.cancelCalls).toBe(before + 1)
    expect(result.current.isSpeaking).toBe(false)
  })

  it('ignores repeated speak() calls while playing (no overlap, no restart)', () => {
    const { result } = renderHook(() => useSpeechSynthesis())
    let second: boolean | undefined
    act(() => {
      void result.current.speak(['One.'])
      second = result.current.speak(['One.'])
    })
    expect(second).toBe(false)
    expect(synth.spoken).toHaveLength(1)
  })

  it('can play again after stopping', () => {
    const { result } = renderHook(() => useSpeechSynthesis())
    act(() => void result.current.speak(['One.']))
    act(() => result.current.stop())
    act(() => void result.current.speak(['Two.']))
    expect(synth.texts).toEqual(['One.', 'Two.'])
    expect(result.current.isSpeaking).toBe(true)
  })

  it('ignores end events from a stopped session', () => {
    const { result } = renderHook(() => useSpeechSynthesis())
    act(() => void result.current.speak(['Old.']))
    const old = synth.spoken[0]!
    act(() => result.current.stop())
    act(() => void result.current.speak(['New one.', 'New two.']))
    act(() => old.onend?.(new Event('end')))
    expect(result.current.isSpeaking).toBe(true)
  })

  it('stops on unmount', () => {
    const { result, unmount } = renderHook(() => useSpeechSynthesis())
    act(() => void result.current.speak(['One.']))
    const before = synth.cancelCalls
    unmount()
    expect(synth.cancelCalls).toBe(before + 1)
  })

  it('resets when all speech is cancelled elsewhere (e.g. microphone starts)', () => {
    const { result } = renderHook(() => useSpeechSynthesis())
    act(() => void result.current.speak(['One.']))
    act(() => cancelAllSpeech())
    expect(result.current.isSpeaking).toBe(false)
  })

  it('reports a real error but not our own interruption', () => {
    const { result } = renderHook(() => useSpeechSynthesis())
    act(() => void result.current.speak(['One.']))
    act(() => synth.failNext('interrupted'))
    expect(result.current.error).toBeNull()
    expect(result.current.isSpeaking).toBe(false)

    act(() => void result.current.speak(['Two.']))
    act(() => synth.failNext('audio-busy'))
    expect(result.current.error?.kind).toBe('unavailable')
    expect(result.current.isSpeaking).toBe(false)
  })

  it('handles browsers without speech synthesis', () => {
    vi.stubGlobal('speechSynthesis', undefined)
    const { result } = renderHook(() => useSpeechSynthesis())
    expect(result.current.supported).toBe(false)
    let started: boolean | undefined
    act(() => {
      started = result.current.speak(['One.'])
    })
    expect(started).toBe(false)
    expect(() => result.current.stop()).not.toThrow()
  })
})
