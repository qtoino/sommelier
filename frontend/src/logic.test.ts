import { describe, expect, it } from 'vitest'
import { calibrationNote, keyAction, pct } from './logic'

describe('keyAction', () => {
  it('maps choices and confidence while answering', () => {
    expect(keyAction('1', 'question')).toEqual({ type: 'choose', choice: 'left' })
    expect(keyAction('3', 'question')).toEqual({ type: 'choose', choice: 'depends' })
    expect(keyAction('H', 'question')).toEqual({ type: 'confidence', confidence: 'high' })
    expect(keyAction('Enter', 'question')).toEqual({ type: 'submit' })
    expect(keyAction('n', 'question')).toBeNull()
  })

  it('maps next/flag after reveal and ignores choices', () => {
    expect(keyAction('n', 'revealed')).toEqual({ type: 'next' })
    expect(keyAction('f', 'revealed')).toEqual({ type: 'flag' })
    expect(keyAction('1', 'revealed')).toBeNull()
  })

  it('does not hijack typing in the reason box', () => {
    expect(keyAction('1', 'question', { inField: true })).toBeNull()
    expect(keyAction('Enter', 'question', { inField: true })).toBeNull()
    expect(keyAction('Enter', 'question', { inField: true, ctrl: true })).toEqual({ type: 'submit' })
  })
})

describe('stats helpers', () => {
  it('formats accuracy', () => {
    expect(pct({ n: 0, correct: 0 })).toBe('–')
    expect(pct({ n: 3, correct: 2 })).toBe('67%')
  })

  it('detects overconfidence', () => {
    expect(
      calibrationNote({ low: { n: 5, correct: 4 }, high: { n: 5, correct: 2 } }),
    ).toMatch(/Overconfident/)
    expect(
      calibrationNote({ low: { n: 5, correct: 2 }, high: { n: 5, correct: 5 } }),
    ).toMatch(/calibrated/)
    expect(calibrationNote({})).toMatch(/more items/)
  })
})
