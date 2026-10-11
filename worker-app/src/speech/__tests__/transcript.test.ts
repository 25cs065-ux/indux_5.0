import { describe, expect, it } from 'vitest'
import { getRecognitionCtor, speechSupport } from '../support.ts'
import { collapseFinals, composeQuestion, speechErrorFrom } from '../transcript.ts'

describe('collapseFinals', () => {
  it('joins finals in order', () => {
    expect(collapseFinals(['Compressor is', 'overheating'])).toBe('Compressor is overheating')
  })

  it('drops a re-delivered identical final', () => {
    expect(collapseFinals(['oil leak', 'oil leak'])).toBe('oil leak')
    expect(collapseFinals(['Oil leak', 'oil leak '])).toBe('Oil leak')
  })

  it('replaces cumulative finals instead of repeating them', () => {
    expect(collapseFinals(['check oil', 'check oil level', 'check oil level now'])).toBe('check oil level now')
  })

  it('ignores a shorter repeat of the previous final', () => {
    expect(collapseFinals(['pressure is low', 'pressure is'])).toBe('pressure is low')
  })

  it('ignores empty finals and collapses whitespace', () => {
    expect(collapseFinals(['  ', ' belt   is  worn ', ''])).toBe('belt is worn')
  })
})

describe('composeQuestion', () => {
  it('appends spoken text to existing text with one space', () => {
    expect(composeQuestion('Alarm E12.  ', 'compressor is hot', 1000)).toBe('Alarm E12. compressor is hot')
  })

  it('uses spoken text alone for an empty field', () => {
    expect(composeQuestion('', 'compressor is hot', 1000)).toBe('compressor is hot')
  })

  it('keeps the base when nothing was recognised', () => {
    expect(composeQuestion('typed text', '', 1000)).toBe('typed text')
  })

  it('is idempotent for the same input (no duplication on repeated events)', () => {
    const once = composeQuestion('base', 'spoken words', 1000)
    expect(composeQuestion('base', 'spoken words', 1000)).toBe(once)
  })

  it('respects the maximum length', () => {
    expect(composeQuestion('abc', 'defgh', 6)).toBe('abc de')
  })
})

describe('speechErrorFrom', () => {
  it.each([
    ['not-allowed', 'permission'],
    ['service-not-allowed', 'permission'],
    ['audio-capture', 'no-microphone'],
    ['no-speech', 'no-speech'],
    ['network', 'network'],
    ['language-not-supported', 'language'],
    ['bad-grammar', 'failed'],
    ['something-new', 'failed'],
  ])('%s -> %s', (code, kind) => {
    const err = speechErrorFrom(code)
    expect(err.kind).toBe(kind)
    expect(err.message.length).toBeGreaterThan(10)
  })
})

describe('speech support detection', () => {
  class Ctor {}

  it('prefers the standard constructor and falls back to webkit', () => {
    expect(getRecognitionCtor({ SpeechRecognition: Ctor })).toBe(Ctor)
    expect(getRecognitionCtor({ webkitSpeechRecognition: Ctor })).toBe(Ctor)
    expect(getRecognitionCtor({})).toBeNull()
  })

  it('reports unsupported browsers', () => {
    expect(speechSupport({ isSecureContext: true }).status).toBe('unsupported')
  })

  it('reports insecure (non-HTTPS) contexts', () => {
    expect(speechSupport({ webkitSpeechRecognition: Ctor, isSecureContext: false }).status).toBe('insecure')
  })

  it('reports support in a secure context', () => {
    expect(speechSupport({ webkitSpeechRecognition: Ctor, isSecureContext: true }).status).toBe('supported')
  })
})
