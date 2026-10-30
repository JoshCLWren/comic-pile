import { useMemo, useState } from 'react'
import { computeEntryRequirements } from '../utils/readingListAuthoring'
import { cblSeriesGroupLabel } from '../utils/cblAdoptionPlan'
import type { ReadingListGate, ReadingListMode } from '../services/api-custom-cbl'
import TriStateCheckbox from './TriStateCheckbox'

/**
 * One entry shown in the before/after replacement review.
 *
 * `comicId` is always the canonical Issue ID (the exact ID the Reading List
 * stores), never a display title or a CBL position.
 * `position` is the one-based reading order position in the original list or
 * source, used to show the expected order outcome in the preview.
 */
export interface ReplaceEntry {
  /** Canonical Issue ID; this is the identity the list write uses. */
  comicId: number
  /** Reader-facing `Series #Number` label. */
  title: string
  /** Whether this entry is currently selected for the replacement. */
  included: boolean
  /** Comic Vine volume group the entry belongs to, when it comes from a CBL source. */
  series_group_id?: string
  /** Series name as the source declares it. */
  series_name?: string
  /** Volume or publication year used to tell same-named runs apart. */
  volume_year?: number | null
  /** Entry already in the owned Reading List but absent from the chosen CBL. */
  manual?: boolean
  /** Entry is part of the CBL source's default selection. */
  defaultIncluded?: boolean
  /** Entry is already saved in the owned Reading List. */
  saved?: boolean
  /** Positional gate to keep when the entry survives the replacement. */
  gate?: ReadingListGate
  /** List-local skip state to keep when the entry survives the replacement. */
  skipped?: boolean
  /** One-based reading order position in the original list or source. */
  position?: number
}

interface SeriesGroup {
  /** Stable series-group identity from the CBL source. */
  id: string
  /** Reader-facing series label, disambiguated by year when known. */
  label: string
  /** Every after-entry that belongs to this series. */
  entries: ReplaceEntry[]
  /** How many entries in this group are currently selected. */
  selectedCount: number
  /** Tri-state of the series checkbox. */
  state: 'checked' | 'unchecked' | 'indeterminate'
}

interface ReplaceGraphImpact {
  /** Dependencies (`waits on` edges) in the saved list. */
  beforeEdges: number
  /** Dependencies in the reviewed selection. */
  afterEdges: number
  /** Entries that gain at least one wait. */
  newlyBlocked: number
  /** Entries that lose every wait. */
  newlyFreed: number
}

interface Props {
  listName: string
  /** Immutable owned Reading List ID the confirmation targets. */
  listId: number
  mode: ReadingListMode
  before: ReplaceEntry[]
  after: ReplaceEntry[]
  onConfirm: (selected: number[]) => void
  onCancel: () => void
  onUndo?: () => void
}

/** Count dependency edges in one positional requirement map. */
function countEdges(requirements: Map<number, number[]>): number {
  let edges = 0
  for (const waitsOn of requirements.values()) edges += waitsOn.length
  return edges
}

/** Collect the Issue IDs that wait on at least one earlier entry. */
function waitingIssueIds(requirements: Map<number, number[]>): Set<number> {
  const waiting = new Set<number>()
  for (const [issueId, waitsOn] of requirements.entries()) {
    if (waitsOn.length > 0) waiting.add(issueId)
  }
  return waiting
}

/**
 * Compute the before/after reading-graph impact of the current selection.
 *
 * The graph is the same positional requirement model the Reading List editor
 * and the Roll evaluator share, so the preview cannot disagree with execution.
 */
function graphImpact(
  mode: ReadingListMode,
  before: ReplaceEntry[],
  selected: Set<number>,
  after: ReplaceEntry[],
): ReplaceGraphImpact {
  const beforeRequirements = computeEntryRequirements(
    mode,
    before.map((entry) => ({
      issue_id: entry.comicId,
      gate: entry.gate ?? 'none',
      skipped: Boolean(entry.skipped),
    })),
  )
  const afterRequirements = computeEntryRequirements(
    mode,
    after.flatMap((entry) =>
      selected.has(entry.comicId)
        ? [
            {
              issue_id: entry.comicId,
              gate: entry.gate ?? 'none',
              skipped: Boolean(entry.skipped),
            },
          ]
        : [],
    ),
  )
  const beforeWaiting = waitingIssueIds(beforeRequirements)
  const afterWaiting = waitingIssueIds(afterRequirements)
  let newlyBlocked = 0
  for (const issueId of afterWaiting) {
    if (!beforeWaiting.has(issueId)) newlyBlocked += 1
  }
  let newlyFreed = 0
  for (const issueId of beforeWaiting) {
    if (!afterWaiting.has(issueId)) newlyFreed += 1
  }
  return {
    beforeEdges: countEdges(beforeRequirements),
    afterEdges: countEdges(afterRequirements),
    newlyBlocked,
    newlyFreed,
  }
}

/**
 * Split the after-selection into CBL series groups and manual additions.
 *
 * Manual entries (saved list entries not in the chosen CBL) have no series
 * group and are returned separately so they stay as individual checkboxes.
 */
function splitSeriesGroups(
  after: ReplaceEntry[],
  selected: Set<number>,
): { groups: SeriesGroup[]; manual: ReplaceEntry[] } {
  const groups = new Map<string, ReplaceEntry[]>()
  const manual: ReplaceEntry[] = []

  for (const entry of after) {
    if (entry.series_group_id) {
      const existing = groups.get(entry.series_group_id)
      if (existing) existing.push(entry)
      else groups.set(entry.series_group_id, [entry])
    } else {
      manual.push(entry)
    }
  }

  return {
    groups: Array.from(groups.entries()).map(([id, entries]) => {
      const first = entries[0]!
      const label = first.series_name
        ? cblSeriesGroupLabel(first.series_name, first.volume_year ?? null)
        : id
      const selectedCount = entries.filter((e) => selected.has(e.comicId)).length
      let state: SeriesGroup['state']
      if (selectedCount === 0) state = 'unchecked'
      else if (selectedCount === entries.length) state = 'checked'
      else state = 'indeterminate'
      return { id, label, entries, selectedCount, state }
    }),
    manual,
  }
}

/**
 * Review an existing Reading List replacement against one chosen CBL source.
 *
 * The panel shows exact Issue IDs on both sides, distinguishes source-default
 * from already-saved selections, keeps manual extras visible, and previews the
 * reading-graph impact before the reader confirms the replacement of the named
 * owned list. Undo restores only the list; it never touches read history.
 *
 * CBL source entries are grouped by Comic Vine volume so the reader can
 * include or exclude a whole series at once with a series-level tri-state
 * checkbox. Unchecking one issue flips its series to mixed; checking the mixed
 * series restores all of its issues.
 */
export function CblReplaceReviewPanel({
  listName,
  listId,
  mode,
  before,
  after,
  onConfirm,
  onCancel,
  onUndo,
}: Props) {
  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(after.filter((entry) => entry.included).map((entry) => entry.comicId)),
  )

  const { groups: seriesGroups, manual: manualEntries } = useMemo(
    () => splitSeriesGroups(after, selected),
    [after, selected],
  )

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSeries = (groupId: string, include: boolean) => {
    const group = seriesGroups.find((g) => g.id === groupId)
    if (!group) return
    setSelected((prev) => {
      const next = new Set(prev)
      for (const entry of group.entries) {
        if (include) next.add(entry.comicId)
        else next.delete(entry.comicId)
      }
      return next
    })
  }

  const impact = useMemo(
    () => graphImpact(mode, before, selected, after),
    [mode, before, selected, after],
  )
  const selectedCount = selected.size
  const manualCount = after.filter((entry) => entry.manual).length

  return (
    <section
      data-testid="cbl-replace-review"
      aria-labelledby="cbl-replace-heading"
      className="space-y-3 rounded-xl border border-[var(--theme-border)] p-3"
    >
      <header className="space-y-1">
        <h3 id="cbl-replace-heading" className="text-sm font-bold text-[var(--theme-text-primary)]">
          Replace “{listName}” using this CBL
        </h3>
        <p className="text-xs text-[var(--theme-text-muted)]">
          Confirmation targets Reading List #{listId}. Read history, ratings, collection
          exclusions, and other lists are not changed.
        </p>
      </header>

      <div className="grid gap-2 sm:grid-cols-2">
        <div>
          <h4 className="text-xs font-semibold text-[var(--theme-text-primary)]">
            Before · {before.length} saved
          </h4>
          <ul className="space-y-1 text-xs" aria-label="Before replacement">
            {before.map((entry) => (
              <li key={entry.comicId} data-testid={`before-${entry.comicId}`}>
                <span className="font-mono text-[var(--theme-text-dim)]">{entry.comicId}</span>{' '}
                {entry.title}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-xs font-semibold text-[var(--theme-text-primary)]">
            After · {selectedCount} selected
          </h4>
          <ul className="space-y-1 text-xs" aria-label="After replacement">
            {seriesGroups.map((group) => (
              <li key={group.id} className="rounded-lg border border-[var(--theme-border)] p-2">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2">
                    <TriStateCheckbox
                      checked={group.state === 'checked'}
                      indeterminate={group.state === 'indeterminate'}
                      label={`Include ${group.label} series`}
                      onChange={(include) => toggleSeries(group.id, include)}
                    />
                    <span className="min-w-0 flex-1 truncate text-sm font-bold text-[var(--theme-text-primary)]">
                      {group.label}
                    </span>
                    <span className="shrink-0 text-xs text-[var(--theme-text-muted)]">
                      {group.selectedCount} of {group.entries.length} selected
                    </span>
                  </div>
                </div>
                <ul className="space-y-1 mt-2 pl-4 border-l border-[var(--theme-border)]">
                  {group.entries.map((entry) => (
                    <li key={entry.comicId} data-testid={`after-${entry.comicId}`}>
                      <label className="flex items-start gap-2">
                        <input
                          type="checkbox"
                          checked={selected.has(entry.comicId)}
                          onChange={() => toggle(entry.comicId)}
                          aria-label={`Include ${entry.title} (Issue ${entry.comicId})`}
                          data-testid={`toggle-${entry.comicId}`}
                          className="mt-0.5 h-4 w-4"
                        />
                        <span>
                          <span className="font-mono text-[var(--theme-text-dim)]">{entry.comicId}</span>{' '}
                          {entry.title}
                          {entry.position != null ? (
                            <span
                              data-testid={`position-${entry.comicId}`}
                              className="ml-2 font-mono text-[10px] text-[var(--theme-text-muted)]"
                            >
                              pos {entry.position + 1}
                            </span>
                          ) : null}
                          {entry.defaultIncluded ? (
                            <span
                              data-testid={`default-${entry.comicId}`}
                              className="ml-2 rounded-full border border-[var(--theme-border)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[var(--theme-text-dim)]"
                            >
                              default
                            </span>
                          ) : null}
                          {entry.saved ? (
                            <span
                              data-testid={`saved-${entry.comicId}`}
                              className="ml-2 rounded-full border border-[var(--theme-border)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[var(--theme-text-dim)]"
                            >
                              saved
                            </span>
                          ) : null}
                          {entry.manual ? (
                            <span data-testid={`manual-${entry.comicId}`}> (manual)</span>
                          ) : null}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
            {manualEntries.length > 0 && (
              <li className="rounded-lg border border-[var(--theme-border)] p-2">
                <div className="flex items-center gap-2 mb-2">
                  <span
                    className="text-xs font-semibold uppercase tracking-wider text-[var(--theme-text-muted)]"
                  >
                    Manual additions
                  </span>
                </div>
                <ul className="space-y-1">
                  {manualEntries.map((entry) => (
                    <li key={entry.comicId} data-testid={`after-${entry.comicId}`}>
                      <label className="flex items-start gap-2">
                        <input
                          type="checkbox"
                          checked={selected.has(entry.comicId)}
                          onChange={() => toggle(entry.comicId)}
                          aria-label={`Include ${entry.title} (Issue ${entry.comicId})`}
                          data-testid={`toggle-${entry.comicId}`}
                          className="mt-0.5 h-4 w-4"
                        />
                        <span>
                          <span className="font-mono text-[var(--theme-text-dim)]">{entry.comicId}</span>{' '}
                          {entry.title}
                          {entry.position != null ? (
                            <span
                              data-testid={`position-${entry.comicId}`}
                              className="ml-2 font-mono text-[10px] text-[var(--theme-text-muted)]"
                            >
                              pos {entry.position + 1}
                            </span>
                          ) : null}
                          {entry.saved ? (
                            <span
                              data-testid={`saved-${entry.comicId}`}
                              className="ml-2 rounded-full border border-[var(--theme-border)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[var(--theme-text-dim)]"
                            >
                              saved
                            </span>
                          ) : null}
                          {entry.manual ? (
                            <span data-testid={`manual-${entry.comicId}`}> (manual)</span>
                          ) : null}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </li>
            )}
          </ul>
        </div>
      </div>

      {manualCount > 0 ? (
        <p className="text-xs text-[var(--theme-text-muted)]">
          {manualCount} saved {manualCount === 1 ? 'entry is' : 'entries are'} not in this CBL.
          Kept checked so the replacement never silently drops your own additions.
        </p>
      ) : null}

      <div
        data-testid="cbl-replace-graph-impact"
        className="rounded-lg border border-[var(--theme-border)] p-2 text-xs text-[var(--theme-text-muted)]"
      >
        <p className="font-semibold text-[var(--theme-text-primary)]">Reading graph impact</p>
        <p>
          Waits-on links: {impact.beforeEdges} → {impact.afterEdges}
          {impact.newlyBlocked > 0 ? ` · ${impact.newlyBlocked} gain a wait` : ''}
          {impact.newlyFreed > 0 ? ` · ${impact.newlyFreed} lose every wait` : ''}
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          data-testid="confirm-replace"
          onClick={() => onConfirm(after.filter((entry) => selected.has(entry.comicId)).map((entry) => entry.comicId))}
          disabled={selectedCount === 0}
          className="min-h-10 rounded-lg bg-[var(--theme-continuity-accent)] px-3 text-sm font-black text-black disabled:opacity-50"
        >
          Confirm replacement of this list
        </button>
        <button
          type="button"
          data-testid="cancel-replace"
          onClick={onCancel}
          className="min-h-10 rounded-lg border border-[var(--theme-border)] px-3 text-sm font-bold text-[var(--theme-text-primary)]"
        >
          Cancel
        </button>
        {onUndo ? (
          <button
            type="button"
            data-testid="undo-replace"
            onClick={onUndo}
            className="min-h-10 rounded-lg border border-[var(--theme-border)] px-3 text-sm font-bold text-[var(--theme-text-primary)]"
          >
            Undo replacement
          </button>
        ) : null}
      </div>
    </section>
  )
}

export default CblReplaceReviewPanel
