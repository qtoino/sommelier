/** Render `backticked` spans as inline code; everything else is plain text. */
export function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split(/(`[^`]+`)/).map((part, i) =>
        part.startsWith('`') && part.endsWith('`') && part.length > 1 ? (
          <code key={i} className="rounded bg-zinc-200 px-1 font-mono text-[0.9em] dark:bg-zinc-800">
            {part.slice(1, -1)}
          </code>
        ) : (
          part
        ),
      )}
    </>
  )
}
