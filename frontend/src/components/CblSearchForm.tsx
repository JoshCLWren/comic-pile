import type { FormEvent } from 'react'

interface CblSearchFormProps {
  queryDraft: string
  isCommitting: boolean
  onQueryDraftChange: (value: string) => void
  onSearch: (event: FormEvent) => void
}

/** Explicit-submit search controls for the shared CBL catalog. */
export function CblSearchForm({
  queryDraft,
  isCommitting,
  onQueryDraftChange,
  onSearch,
}: CblSearchFormProps) {
  return (
    <form onSubmit={onSearch} className="flex flex-col gap-2 sm:flex-row">
      <label className="sr-only" htmlFor="cbl-browser-search">
        Search source lists
      </label>
      <input
        id="cbl-browser-search"
        value={queryDraft}
        onChange={(event) => onQueryDraftChange(event.target.value)}
        placeholder="Search source lists"
        maxLength={200}
        disabled={isCommitting}
        className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-[var(--theme-text-primary)] disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={isCommitting}
        className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50"
      >
        Search
      </button>
    </form>
  )
}
