import { python } from '@codemirror/lang-python'
import { sql } from '@codemirror/lang-sql'
import { MergeView } from '@codemirror/merge'
import { EditorState, type Extension } from '@codemirror/state'
import { EditorView, lineNumbers } from '@codemirror/view'
import { githubDark, githubLight } from '@uiw/codemirror-theme-github'
import { useEffect, useRef } from 'react'

// Add a language here when items in it exist; unknown languages render as plain text.
const LANGUAGES: Record<string, () => Extension> = { python, sql }

function extensions(language: string, dark: boolean): Extension[] {
  return [
    lineNumbers(),
    EditorState.readOnly.of(true),
    EditorView.editable.of(false),
    EditorView.lineWrapping,
    dark ? githubDark : githubLight,
    LANGUAGES[language]?.() ?? [],
    EditorView.theme({ '&': { fontSize: '13px' }, '.cm-scroller': { fontFamily: 'ui-monospace, monospace' } }),
  ]
}

export function CodePane({ code, language, dark }: { code: string; language: string; dark: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const view = new EditorView({
      parent: ref.current!,
      state: EditorState.create({ doc: code.trimEnd(), extensions: extensions(language, dark) }),
    })
    return () => view.destroy()
  }, [code, language, dark])
  return <div ref={ref} className="overflow-hidden rounded-md border border-zinc-200 dark:border-zinc-700" />
}

export function DiffPane(props: { left: string; right: string; language: string; dark: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const { left, right, language, dark } = props
  useEffect(() => {
    const ext = extensions(language, dark)
    const view = new MergeView({
      parent: ref.current!,
      a: { doc: left.trimEnd(), extensions: ext },
      b: { doc: right.trimEnd(), extensions: ext },
      highlightChanges: true,
      gutter: true,
    })
    return () => view.destroy()
  }, [left, right, language, dark])
  return <div ref={ref} className="overflow-hidden rounded-md border border-zinc-200 dark:border-zinc-700" />
}
