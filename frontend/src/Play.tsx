import { useCallback, useEffect, useState } from 'react'
import {
  type Choice,
  type Confidence,
  type Filters,
  type Reveal,
  type Served,
  NotFound,
  flagItem,
  getReveal,
  nextItem,
  submitAttempt,
} from './api'
import { CodePane, DiffPane } from './Code'
import { Inline } from './Inline'
import { keyAction } from './logic'

const CHOICES: [Choice, string, string][] = [
  ['left', 'A is better', '1'],
  ['right', 'B is better', '2'],
  ['depends', 'It depends', '3'],
]
const CONFIDENCES: [Confidence, string][] = [
  ['low', 'L'],
  ['medium', 'M'],
  ['high', 'H'],
]

const btn = 'rounded-md border px-3 py-1.5 text-sm transition-colors disabled:opacity-40'
const idle = 'border-zinc-300 hover:bg-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-800'
const active = 'border-indigo-600 bg-indigo-600 text-white dark:border-indigo-500 dark:bg-indigo-500'
const kbd = 'ml-1.5 rounded bg-black/10 px-1 font-mono text-xs dark:bg-white/15'

export function Play({ filters, dark }: { filters: Filters; dark: boolean }) {
  const [served, setServed] = useState<Served | null>(null)
  const [empty, setEmpty] = useState<string | null>(null)
  const [choice, setChoice] = useState<Choice | null>(null)
  const [confidence, setConfidence] = useState<Confidence | null>(null)
  const [reason, setReason] = useState('')
  const [reveal, setReveal] = useState<Reveal | null>(null)
  const [busy, setBusy] = useState(false)
  const [flagOpen, setFlagOpen] = useState(false)
  const [flagNote, setFlagNote] = useState('')
  const [flagged, setFlagged] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    async (exclude?: string) => {
      setBusy(true)
      setError(null)
      try {
        const s = await nextItem(filters, exclude)
        setServed(s)
        setEmpty(null)
      } catch (e) {
        setServed(null)
        if (e instanceof NotFound)
          setEmpty(filters.review ? 'Nothing to review. Every item you answered last was right.' : 'No items match these filters.')
        else setError(String(e))
      }
      setChoice(null)
      setConfidence(null)
      setReason('')
      setReveal(null)
      setFlagOpen(false)
      setFlagNote('')
      setFlagged(false)
      setBusy(false)
      window.scrollTo({ top: 0 })
    },
    [filters],
  )

  useEffect(() => {
    load()
  }, [load])

  async function submit() {
    if (!served || !choice || !confidence || busy) return
    setBusy(true)
    try {
      await submitAttempt({ attempt_id: served.attempt_id, choice, confidence, reason_text: reason || undefined })
      setReveal(await getReveal(served.item_id))
    } catch (e) {
      setError(String(e))
    }
    setBusy(false)
  }

  async function sendFlag() {
    if (!served || !flagNote.trim()) return
    await flagItem(served.item_id, flagNote.trim())
    setFlagged(true)
    setFlagOpen(false)
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.altKey || (e.metaKey && e.key !== 'Enter')) return
      const target = e.target as HTMLElement
      const inField = target.tagName === 'TEXTAREA' || target.tagName === 'INPUT' || target.tagName === 'SELECT'
      const action = keyAction(e.key, reveal ? 'revealed' : 'question', { inField, ctrl: e.ctrlKey || e.metaKey })
      if (!action) return
      e.preventDefault()
      if (action.type === 'choose') setChoice(action.choice)
      else if (action.type === 'confidence') setConfidence(action.confidence)
      else if (action.type === 'submit') submit()
      else if (action.type === 'next') load(served?.item_id)
      else if (action.type === 'flag') setFlagOpen(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (error) return <p className="text-red-600">{error}</p>
  if (empty) return <p className="py-16 text-center text-zinc-500">{empty}</p>
  if (!served) return <p className="py-16 text-center text-zinc-500">Loading…</p>

  const label = (side: 'left' | 'right') => (side === 'left' ? 'A' : 'B')
  const goodMark = (side: 'left' | 'right') =>
    reveal && !reveal.item.is_tradeoff && reveal.good_side === side ? ' · better' : ''

  return (
    <div className="space-y-5">
      <p className="text-lg" data-testid="prompt"><Inline text={served.prompt} /></p>
      {served.context_code && (
        <details open className="text-sm">
          <summary className="cursor-pointer text-zinc-500">Context</summary>
          <div className="mt-2">
            <CodePane code={served.context_code} language={served.language} dark={dark} />
          </div>
        </details>
      )}

      {reveal ? (
        <div>
          <div className="mb-1 grid grid-cols-2 gap-4 text-sm font-medium">
            <span>Version A{goodMark('left')}</span>
            <span>Version B{goodMark('right')}</span>
          </div>
          <DiffPane left={served.left} right={served.right} language={served.language} dark={dark} />
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {(['left', 'right'] as const).map((side) => (
            <div key={side}>
              <div className="mb-1 text-sm font-medium">Version {label(side)}</div>
              <CodePane code={served[side]} language={served.language} dark={dark} />
            </div>
          ))}
        </div>
      )}

      {!reveal ? (
        <div className="space-y-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
          <div className="flex flex-wrap gap-2">
            {CHOICES.map(([value, text, key]) => (
              <button key={value} className={`${btn} ${choice === value ? active : idle}`} onClick={() => setChoice(value)}>
                {text}
                <kbd className={kbd}>{key}</kbd>
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-zinc-500">Confidence</span>
            {CONFIDENCES.map(([value, key]) => (
              <button key={value} className={`${btn} ${confidence === value ? active : idle}`} onClick={() => setConfidence(value)}>
                {value}
                <kbd className={kbd}>{key}</kbd>
              </button>
            ))}
          </div>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why? (optional, Ctrl+Enter submits)"
            rows={2}
            className="w-full rounded-md border border-zinc-300 bg-transparent p-2 text-sm dark:border-zinc-600"
          />
          <button className={`${btn} ${active}`} disabled={!choice || !confidence || busy} onClick={submit}>
            Submit
            <kbd className={kbd}>Enter</kbd>
          </button>
        </div>
      ) : (
        <RevealPanel reveal={reveal} />
      )}

      {reveal && (
        <div className="flex flex-wrap items-start gap-2">
          <button className={`${btn} ${active}`} onClick={() => load(served.item_id)}>
            Next
            <kbd className={kbd}>N</kbd>
          </button>
          {flagged ? (
            <span className="py-1.5 text-sm text-zinc-500">Flagged. It is out of rotation.</span>
          ) : flagOpen ? (
            <div className="flex flex-1 gap-2">
              <input
                autoFocus
                value={flagNote}
                onChange={(e) => setFlagNote(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && sendFlag()}
                placeholder="What is wrong with this item?"
                className="flex-1 rounded-md border border-zinc-300 bg-transparent px-2 text-sm dark:border-zinc-600"
              />
              <button className={`${btn} ${idle}`} onClick={sendFlag}>
                Flag
              </button>
            </div>
          ) : (
            <button className={`${btn} ${idle}`} onClick={() => setFlagOpen(true)}>
              Bad item / I disagree
              <kbd className={kbd}>F</kbd>
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function RevealPanel({ reveal }: { reveal: Reveal }) {
  const { item, is_correct } = reveal
  const answer = item.is_tradeoff ? 'It depends: this is a trade-off.' : `Version ${reveal.good_side === 'left' ? 'A' : 'B'} is better.`
  return (
    <div className="space-y-4" data-testid="reveal">
      <div
        className={`rounded-lg px-4 py-3 font-medium ${
          is_correct
            ? 'bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200'
            : 'bg-rose-100 text-rose-900 dark:bg-rose-900/40 dark:text-rose-200'
        }`}
      >
        {is_correct ? 'Correct.' : 'Not this time.'} {answer}
        <span className="ml-2 text-sm font-normal opacity-75">(you said {reveal.confidence} confidence)</span>
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        {[item.category, item.difficulty, item.source_type, item.language].map((tag) => (
          <span key={tag} className="rounded-full bg-zinc-200 px-2 py-0.5 dark:bg-zinc-700">
            {tag}
          </span>
        ))}
      </div>
      <section>
        <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-zinc-500">Why</h3>
        <p className="leading-relaxed whitespace-pre-line"><Inline text={item.explanation} /></p>
      </section>
      <section className="rounded-lg border-l-4 border-amber-500 bg-amber-50 px-4 py-3 dark:bg-amber-900/20">
        <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">The tell</h3>
        <p className="leading-relaxed"><Inline text={item.tell} /></p>
      </section>
      {item.source_type === 'mined' && <Attribution item={item} />}
    </div>
  )
}

function Attribution({ item }: { item: Reveal['item'] }) {
  const link = 'text-indigo-600 underline dark:text-indigo-400'
  return (
    <section className="space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Source</h3>
      <p>
        <a className={link} href={`https://github.com/${item.repo}`} target="_blank" rel="noreferrer">
          {item.repo}
        </a>{' '}
        · {item.original_path} ·{' '}
        <a className={link} href={item.commit_url ?? '#'} target="_blank" rel="noreferrer">
          {item.commit_sha?.slice(0, 10)}
        </a>{' '}
        · {item.license_spdx}
        {item.linked_issue_url && (
          <>
            {' · '}
            <a className={link} href={item.linked_issue_url} target="_blank" rel="noreferrer">
              issue
            </a>
          </>
        )}
      </p>
      {item.commit_message && <p className="font-mono text-xs whitespace-pre-line">{item.commit_message}</p>}
      <p className="text-xs">The later version is better, not necessarily perfect.</p>
    </section>
  )
}
