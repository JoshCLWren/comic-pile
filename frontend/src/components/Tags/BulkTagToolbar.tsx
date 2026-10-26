import { useState } from 'react'
import { useDebounce } from '../../hooks/useDebounce'
import { useBulkAssignTag, useBulkUnassignTag, useTags } from '../../hooks/useTags'
import { TAG_COLOR_HEX, type Tag } from '../../services/api-tags'
import { tagErrorMessage } from './tagErrors'

export interface BulkTagToolbarProps {
  /** Selected issue ids the bulk operation applies to. */
  selectedIds: number[]
  onClearSelection: () => void
  onDone?: (summary: string) => void
}

/**
 * Bulk tag add/remove for arbitrary multi-selected issues (issue #3032).
 *
 * Bulk operations change only the selected tag assignment and never replace
 * unrelated tags on those issues. The toolbar reports how many issues were
 * newly changed versus already in the desired state.
 */
export function BulkTagToolbar({ selectedIds, onClearSelection, onDone }: BulkTagToolbarProps) {
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebounce(search, 250)
  const usable = useTags(debouncedSearch)
  const [picked, setPicked] = useState<Tag | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  const bulkAssign = useBulkAssignTag()
  const bulkUnassign = useBulkUnassignTag()
  const busy = bulkAssign.isPending || bulkUnassign.isPending

  if (selectedIds.length === 0) return null

  async function run(mode: 'add' | 'remove') {
    if (!picked) {
      setFailure('Pick a tag first.')
      return
    }
    setFailure(null)
    const data = { target_type: 'Issue' as const, target_ids: selectedIds }
    try {
      const result =
        mode === 'add'
          ? await bulkAssign.mutateAsync({ id: picked.id, data })
          : await bulkUnassign.mutateAsync({ id: picked.id, data })
      const stillInheritedIds = new Set(result.still_inherited_ids ?? [])
      const alreadyUntaggedCount = result.already_ids.filter(
        (issueId) => !stillInheritedIds.has(issueId),
      ).length
      const selectedCount = result.requested_ids.length
      const selectedNoun = selectedCount === 1 ? 'issue' : 'issues'
      const stillInheritedCount = stillInheritedIds.size
      const summary =
        mode === 'add'
          ? `Tagged “${picked.name}” on ${result.affected_ids.length} of ` +
            `${selectedCount} selected ${selectedNoun}` +
            (result.already_ids.length > 0
              ? ` (${result.already_ids.length} already tagged)`
              : '') +
            '.'
          : `Removed direct “${picked.name}” tag from ${result.affected_ids.length} of ` +
            `${selectedCount} selected ${selectedNoun}` +
            (stillInheritedCount > 0
              ? ` (${stillInheritedCount} ${stillInheritedCount === 1 ? 'issue still inherits' : 'issues still inherit'} it)`
              : '') +
            (alreadyUntaggedCount > 0 ? ` (${alreadyUntaggedCount} already untagged)` : '') +
            '.'
      onDone?.(summary)
      onClearSelection()
    } catch (error) {
      setFailure(tagErrorMessage(error, `Bulk ${mode} failed.`))
    }
  }

  return (
    <div
      role="toolbar"
      aria-label={`Bulk tag editing for ${selectedIds.length} selected ${selectedIds.length === 1 ? 'issue' : 'issues'}`}
      className="flex min-w-0 flex-col gap-2 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-bold text-[var(--theme-text-primary)]">
          {selectedIds.length} selected
        </p>
        {picked && (
          <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--theme-border)] px-2.5 py-1 text-xs font-semibold text-[var(--theme-text-primary)]">
            <span
              aria-hidden="true"
              className="inline-block h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: picked.color }}
            />
            <span className="min-w-0 truncate" title={picked.name}>
              {picked.name}
            </span>
            <button
              type="button"
              onClick={() => setPicked(null)}
              aria-label="Clear picked tag"
              className="shrink-0 rounded-full px-1 text-[var(--theme-text-muted)] hover:text-[var(--theme-danger)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            >
              ×
            </button>
          </span>
        )}
        <button
          type="button"
          onClick={onClearSelection}
          className="ml-auto text-xs font-semibold text-[var(--theme-text-muted)] underline decoration-dotted underline-offset-2 hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
        >
          Clear selection
        </button>
      </div>

      {!picked && (
        <>
          <input
            type="text"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search tags to bulk-apply…"
            aria-label="Search tags to bulk-apply"
            className="w-full rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2 text-sm text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
          />
          {usable.isPending ? (
            <p className="text-xs text-[var(--theme-text-dim)]">Searching…</p>
          ) : (usable.data?.tags ?? []).length === 0 ? (
            <p className="text-xs text-[var(--theme-text-dim)]">No matching tags.</p>
          ) : (
            <ul className="flex max-w-full flex-wrap gap-1.5" aria-label="Matching tags">
              {(usable.data?.tags ?? []).slice(0, 12).map((tag) => (
                <li key={tag.id} className="min-w-0 max-w-full">
                  <button
                    type="button"
                    onClick={() => {
                      setPicked(tag)
                      setFailure(null)
                    }}
                    className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--theme-border)] px-2.5 py-1 text-xs font-semibold text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                  >
                    <span
                      aria-hidden="true"
                      className="inline-block h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: tag.color || TAG_COLOR_HEX.red }}
                    />
                    <span className="min-w-0 truncate" title={tag.name}>
                      {tag.name}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {failure && (
        <p role="alert" className="text-sm font-semibold text-[var(--theme-danger)]">
          {failure}
        </p>
      )}

      {picked && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void run('add')}
            disabled={busy}
            className="rounded-lg bg-[var(--theme-primary-action)] px-3 py-1.5 text-sm font-bold text-white transition hover:bg-[var(--theme-primary-action-hover)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-50"
          >
            {bulkAssign.isPending ? 'Adding…' : `Add tag to ${selectedIds.length}`}
          </button>
          <button
            type="button"
            onClick={() => void run('remove')}
            disabled={busy}
            className="rounded-lg border border-[var(--theme-border)] px-3 py-1.5 text-sm font-semibold text-[var(--theme-text-primary)] transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-50"
          >
            {bulkUnassign.isPending ? 'Removing…' : `Remove tag from ${selectedIds.length}`}
          </button>
        </div>
      )}
    </div>
  )
}
