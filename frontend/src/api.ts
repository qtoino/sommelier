export type Choice = 'left' | 'right' | 'depends'
export type Confidence = 'low' | 'medium' | 'high'

export interface Filters {
  category?: string
  source_type?: string
  difficulty?: string
  review?: boolean
}

export interface Served {
  attempt_id: number
  item_id: string
  language: string
  prompt: string
  context_code: string | null
  left: string
  right: string
}

export interface Item {
  id: string
  language: string
  category: string
  difficulty: string
  prompt: string
  context_code: string | null
  version_good: string
  version_bad: string
  is_tradeoff: boolean
  explanation: string
  tell: string
  source_type: 'mined' | 'synthetic'
  repo: string | null
  commit_sha: string | null
  commit_url: string | null
  license_spdx: string | null
  original_path: string | null
  commit_message: string | null
  linked_issue_url: string | null
  generator_model: string | null
  verification_status: string | null
}

export interface Reveal {
  item: Item
  good_side: 'left' | 'right'
  choice: Choice
  confidence: Confidence
  is_correct: boolean
}

export interface Bucket {
  n: number
  correct: number
}

export interface Stats {
  overall: Bucket
  by_category: Record<string, Bucket>
  by_confidence: Record<string, Bucket>
  by_source: Record<string, Bucket>
  by_difficulty: Record<string, Bucket>
  hedge_rate: number
  longer_baseline: number
  review_count: number
  inventory: Record<string, number>
  recent: {
    item_id: string
    prompt: string
    category: string
    choice: Choice
    confidence: Confidence
    is_correct: boolean
    answered_at: string
  }[]
}

export class NotFound extends Error {}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (resp.status === 404) throw new NotFound(await resp.text())
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`)
  return resp.json() as Promise<T>
}

export function nextItem(filters: Filters, exclude?: string): Promise<Served> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, String(value))
  if (exclude) params.set('exclude', exclude)
  return call(`/items/next?${params}`)
}

export function submitAttempt(body: {
  attempt_id: number
  choice: Choice
  confidence: Confidence
  reason_text?: string
}): Promise<{ item_id: string; is_correct: boolean }> {
  return call('/attempts', { method: 'POST', body: JSON.stringify(body) })
}

export const getReveal = (id: string): Promise<Reveal> => call(`/items/${id}/reveal`)

export const flagItem = (id: string, note: string): Promise<unknown> =>
  call(`/items/${id}/flag`, { method: 'POST', body: JSON.stringify({ note }) })

export const getStats = (): Promise<Stats> => call('/stats')
