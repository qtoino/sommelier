import { useEffect, useState } from 'react'
import { type Bucket, type Stats as StatsData, getStats } from './api'
import { calibrationNote, pct, ratio } from './logic'

function Table({ title, rows }: { title: string; rows: [string, Bucket][] }) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-zinc-500">{title}</h3>
      {rows.length === 0 && <p className="text-sm text-zinc-500">No answers yet.</p>}
      <div className="space-y-1">
        {rows.map(([name, b]) => (
          <div key={name} className="grid grid-cols-[9rem_1fr_5rem] items-center gap-3 text-sm">
            <span className="truncate">{name}</span>
            <div className="h-2 rounded bg-zinc-200 dark:bg-zinc-700">
              <div className="h-2 rounded bg-indigo-500" style={{ width: `${ratio(b) * 100}%` }} />
            </div>
            <span className="text-right tabular-nums">
              {pct(b)} <span className="text-zinc-500">/{b.n}</span>
            </span>
          </div>
        ))}
      </div>
    </section>
  )
}

const ORDER = ['low', 'medium', 'high', 'easy', 'hard']
const sorted = (rec: Record<string, Bucket>): [string, Bucket][] =>
  Object.entries(rec).sort(([a], [b]) => (ORDER.indexOf(a) - ORDER.indexOf(b)) || a.localeCompare(b))

function Big({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
      <div className="text-sm text-zinc-500">{label}</div>
      <div className="text-3xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-zinc-500">{hint}</div>}
    </div>
  )
}

export function Stats() {
  const [stats, setStats] = useState<StatsData | null>(null)
  useEffect(() => {
    getStats().then(setStats)
  }, [])
  if (!stats) return <p className="text-zinc-500">Loading…</p>
  const total = Object.values(stats.inventory).reduce((a, b) => a + b, 0)
  const asPct = (x: number) => (stats.overall.n ? `${Math.round(x * 100)}%` : '–')

  return (
    <div className="space-y-8">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Big label="Accuracy" value={pct(stats.overall)} hint={`${stats.overall.n} answered of ${total} active items`} />
        <Big label="'Always pick the longer one'" value={asPct(stats.longer_baseline)} hint="Baseline you should beat" />
        <Big label="Said 'It depends'" value={asPct(stats.hedge_rate)} hint="Hedge rate" />
        <Big label="To review" value={String(stats.review_count)} hint="Items you got wrong last time" />
      </div>
      <div className="grid gap-8 lg:grid-cols-2">
        <div className="space-y-8">
          <Table title="By category" rows={sorted(stats.by_category)} />
          <div>
            <Table title="By confidence (calibration)" rows={sorted(stats.by_confidence)} />
            <p className="mt-2 text-sm text-zinc-500">{calibrationNote(stats.by_confidence)}</p>
          </div>
        </div>
        <div className="space-y-8">
          <Table title="By source" rows={sorted(stats.by_source)} />
          <Table title="By difficulty" rows={sorted(stats.by_difficulty)} />
        </div>
      </div>
      <section>
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-zinc-500">Recent</h3>
        <ul className="divide-y divide-zinc-200 text-sm dark:divide-zinc-700">
          {stats.recent.map((r, i) => (
            <li key={i} className="flex gap-3 py-2">
              <span className={r.is_correct ? 'text-emerald-600' : 'text-rose-600'}>{r.is_correct ? '✓' : '✗'}</span>
              <span className="w-28 shrink-0 text-zinc-500">{r.category}</span>
              <span className="flex-1 truncate">{r.prompt}</span>
              <span className="text-zinc-500">{r.confidence}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
