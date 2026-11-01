import { useEffect, useMemo, useState } from 'react'
import type { Filters } from './api'
import { Play } from './Play'
import { Stats } from './Stats'

const CATEGORIES = ['correctness', 'edge-case', 'security', 'performance', 'readability', 'api-design', 'sql-and-schema']
type View = 'practice' | 'review' | 'stats'

function initialDark(): boolean {
  try {
    const saved = localStorage.getItem('theme')
    if (saved) return saved === 'dark'
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

function Select(props: { value: string; onChange: (v: string) => void; label: string; options: string[] }) {
  return (
    <select
      aria-label={props.label}
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
      className="rounded-md border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-600 dark:bg-zinc-900"
    >
      <option value="">{props.label}: all</option>
      {props.options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  )
}

export default function App() {
  const [dark, setDark] = useState(initialDark)
  const [view, setView] = useState<View>('practice')
  const [category, setCategory] = useState('')
  const [source, setSource] = useState('')
  const [difficulty, setDifficulty] = useState('')

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    try {
      localStorage.setItem('theme', dark ? 'dark' : 'light')
    } catch {
      /* storage unavailable */
    }
  }, [dark])

  const filters: Filters = useMemo(
    () => ({ category, source_type: source, difficulty, review: view === 'review' }),
    [category, source, difficulty, view],
  )

  const tab = (v: View, text: string) => (
    <button
      onClick={() => setView(v)}
      className={`rounded-md px-3 py-1 text-sm ${view === v ? 'bg-zinc-200 font-medium dark:bg-zinc-800' : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100'}`}
    >
      {text}
    </button>
  )

  return (
    <div className="min-h-screen bg-white text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <header className="border-b border-zinc-200 dark:border-zinc-800">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3">
          <h1 className="mr-4 text-lg font-semibold">Sommelier</h1>
          <nav className="flex gap-1">
            {tab('practice', 'Practice')}
            {tab('review', 'Review mistakes')}
            {tab('stats', 'Stats')}
          </nav>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {view !== 'stats' && (
              <>
                <Select label="Category" value={category} onChange={setCategory} options={CATEGORIES} />
                <Select label="Source" value={source} onChange={setSource} options={['mined', 'synthetic']} />
                <Select label="Difficulty" value={difficulty} onChange={setDifficulty} options={['easy', 'medium', 'hard']} />
              </>
            )}
            <button
              onClick={() => setDark(!dark)}
              className="rounded-md border border-zinc-300 px-2 py-1 text-sm dark:border-zinc-600"
              aria-label="Toggle dark mode"
            >
              {dark ? 'Light' : 'Dark'}
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        {view === 'stats' ? <Stats /> : <Play key={view} filters={filters} dark={dark} />}
      </main>
    </div>
  )
}
