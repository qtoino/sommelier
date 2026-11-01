import type { Bucket, Choice, Confidence } from './api'

export type Phase = 'question' | 'revealed'

export type Action =
  | { type: 'choose'; choice: Choice }
  | { type: 'confidence'; confidence: Confidence }
  | { type: 'submit' }
  | { type: 'next' }
  | { type: 'flag' }

const CHOICE_KEYS: Record<string, Choice> = { '1': 'left', '2': 'right', '3': 'depends' }
const CONFIDENCE_KEYS: Record<string, Confidence> = { l: 'low', m: 'medium', h: 'high' }

/** Map a keypress to an action. Typing in a text field only honours Ctrl/Cmd+Enter. */
export function keyAction(
  key: string,
  phase: Phase,
  opts: { inField?: boolean; ctrl?: boolean } = {},
): Action | null {
  if (opts.inField) return key === 'Enter' && opts.ctrl && phase === 'question' ? { type: 'submit' } : null
  const k = key.toLowerCase()
  if (phase === 'question') {
    if (k in CHOICE_KEYS) return { type: 'choose', choice: CHOICE_KEYS[k] }
    if (k in CONFIDENCE_KEYS) return { type: 'confidence', confidence: CONFIDENCE_KEYS[k] }
    if (key === 'Enter') return { type: 'submit' }
    return null
  }
  if (k === 'n') return { type: 'next' }
  if (k === 'f') return { type: 'flag' }
  return null
}

export function pct(b: Bucket | undefined): string {
  return b && b.n ? `${Math.round((100 * b.correct) / b.n)}%` : '–'
}

export function ratio(b: Bucket | undefined): number {
  return b && b.n ? b.correct / b.n : 0
}

/** Calibrated means accuracy does not drop as stated confidence rises. Needs data at ≥2 levels. */
export function calibrationNote(by: Record<string, Bucket>): string {
  const levels = (['low', 'medium', 'high'] as const).filter((l) => (by[l]?.n ?? 0) >= 3)
  if (levels.length < 2) return 'Answer a few more items at different confidence levels.'
  const accs = levels.map((l) => ratio(by[l]))
  const monotone = accs.every((a, i) => i === 0 || a >= accs[i - 1] - 0.05)
  if (!monotone) return 'Overconfident: you are not more accurate when you feel more sure.'
  const high = by.high
  if (high && high.n >= 3 && ratio(high) < 0.8) return 'High confidence is right less than 80% of the time.'
  return 'Reasonably calibrated: accuracy rises with confidence.'
}
