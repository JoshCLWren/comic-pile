import { useId, useState } from 'react'

interface WhyThisRollProps {
  /** Reader-facing explanation for the roll selection, or null when none. */
  explanation: string | null | undefined
}

/**
 * Subtle, collapsed-by-default disclosure that explains why ComicPile selected
 * the current recommendation. It never pushes the primary rating actions out of
 * view and is fully keyboard/screen-reader accessible.
 */
export function WhyThisRoll({ explanation }: WhyThisRollProps) {
  const [open, setOpen] = useState(false)
  const regionId = useId()

  if (!explanation) {
    return null
  }

  return (
    <div className="mt-2">
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm font-medium text-sky-600 hover:bg-sky-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:text-sky-400 dark:hover:bg-sky-950"
        aria-expanded={open}
        aria-controls={regionId}
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden="true">{open ? '▾' : '▸'}</span>
        Why this?
      </button>
      {open && (
        <p
          id={regionId}
          role="region"
          aria-label="Why this roll"
          className="mt-1 max-w-prose rounded-md bg-slate-50 p-2 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200"
        >
          {explanation}
        </p>
      )}
    </div>
  )
}

export default WhyThisRoll
