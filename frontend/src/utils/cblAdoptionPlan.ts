import type { CBLAdoptionPreview, CBLAdoptionPreviewEntry } from '../services/api-cbl-sources'

/**
 * Include state of one Comic Vine volume group inside the CBL checklist.
 *
 * `indeterminate` is the native tri-state a partially selected volume shows.
 */
export type CblSeriesGroupState = 'checked' | 'unchecked' | 'indeterminate'

/**
 * One Comic Vine volume group of the CBL source with its checklist state.
 */
export interface CblSeriesGroup {
  /** Stable group identity: the Comic Vine volume, or the name/year fallback. */
  id: string
  /** Series name as the source declares it. */
  name: string
  /** Volume or publication year used to tell same-named runs apart. */
  year: number | null
  /** Reader-facing group label, disambiguated by year when one is known. */
  label: string
  /** Every source entry that belongs to this group, in source order. */
  entries: CBLAdoptionPreviewEntry[]
  /** Entries that can actually be adopted (resolved or safely importable). */
  selectableEntries: CBLAdoptionPreviewEntry[]
  /** How many selectable entries are currently included. */
  selectedCount: number
  /** Tri-state of the group checkbox. */
  state: CblSeriesGroupState
}

/**
 * Apply include/exclude choices to an already-reconciled CBL preview locally.
 *
 * Mirrors `calculate_cbl_adoption_plan` so Customize toggles stay instant and
 * never re-reconcile the source on every click.
 *
 * @param preview - Fingerprinted preview from the server.
 * @param seriesDecisions - Per series-group include map.
 * @param entryDecisions - Per `cbl_entry_id` include map.
 * @returns A new preview with decisions and summary updated.
 */
export function applyCblAdoptionChoices(
  preview: CBLAdoptionPreview,
  seriesDecisions: Record<string, boolean>,
  entryDecisions: Record<string, boolean>,
): CBLAdoptionPreview {
  const includedExisting: number[] = []
  const missingWouldCreate: number[] = []
  const excluded: number[] = []
  const unresolved: number[] = []
  const awaitingOptIn: number[] = []

  const entries = preview.entries.map((sourceEntry) => {
    const entry = { ...sourceEntry }
    const entryKey = String(entry.cbl_entry_id)
    const resolved = entry.resolved_issue_id !== null && entry.adoption_class === 'existing'
    const importable = entry.adoption_class === 'missing_importable'
    const selectable = resolved || importable

    let decision: CBLAdoptionPreviewEntry['adoption_decision']
    if (entry.collection_excluded) {
      if (entry.collection_exclusion_reason === 'collection_identity_requires_review'
        && (entryDecisions[entryKey] ?? seriesDecisions[entry.series_group_id] ?? true)) {
        decision = 'unresolved'
        unresolved.push(entry.cbl_position)
      } else {
        decision = 'excluded'
        excluded.push(entry.cbl_position)
      }
    } else if (!selectable) {
      // #3542: excluding the whole series defers its unresolved entries the
      // same way an explicit per-entry Skip does, so the reader never needs a
      // separate Skip before Add can proceed. An explicit entry choice still
      // wins over the series choice, mirroring the collection-exclusion branch.
      const skipRequested =
        (entryDecisions[entryKey] ?? seriesDecisions[entry.series_group_id] ?? true) === false
      if (skipRequested) {
        decision = 'excluded'
        excluded.push(entry.cbl_position)
      } else {
        decision = 'unresolved'
        unresolved.push(entry.cbl_position)
      }
    } else {
      const defaultSelected = resolved || importable
      const selected =
        entryKey in entryDecisions
          ? entryDecisions[entryKey]
          : entry.series_group_id in seriesDecisions
            ? seriesDecisions[entry.series_group_id]
            : defaultSelected
      if (selected) {
        decision = resolved ? 'included_existing' : 'would_create_missing'
        if (resolved) includedExisting.push(entry.cbl_position)
        else missingWouldCreate.push(entry.cbl_position)
      } else {
        const explicit = entryKey in entryDecisions || entry.series_group_id in seriesDecisions
        decision = explicit ? 'excluded' : 'awaiting_opt_in'
        if (decision === 'excluded') excluded.push(entry.cbl_position)
        else awaitingOptIn.push(entry.cbl_position)
      }
    }

    entry.adoption_decision = decision
    entry.adopted = decision === 'included_existing' || decision === 'would_create_missing'
    return entry
  })

  return {
    ...preview,
    entries,
    summary: {
      reused_existing_count: includedExisting.length,
      missing_would_create_count: missingWouldCreate.length,
      excluded_count: excluded.length,
      unresolved_count: unresolved.length,
      awaiting_opt_in_count: awaitingOptIn.length,
      final_adopted_count: includedExisting.length + missingWouldCreate.length,
      final_adopted_order: [...includedExisting, ...missingWouldCreate].sort((left, right) => left - right),
      reused_existing_positions: includedExisting,
      missing_would_create_positions: missingWouldCreate,
      excluded_positions: excluded,
      unresolved_positions: unresolved,
      awaiting_opt_in_positions: awaitingOptIn,
    },
  }
}

/**
 * Label one Comic Vine volume group for the reader.
 *
 * Two volumes can share a series name, so the year disambiguates them instead
 * of collapsing them into one indistinguishable group.
 *
 * @param name - Series name as the source declares it.
 * @param year - Volume or publication year, when the source declares one.
 * @returns The reader-facing group label.
 */
export function cblSeriesGroupLabel(name: string, year: number | null): string {
  return year === null ? name : `${name} (${year})`
}

/**
 * Group the reconciled source entries into Comic Vine volume groups.
 *
 * Groups keep the source order of their first occurrence. A group is
 * `checked` when every adoptable entry in it is included, `unchecked` when
 * the reader excluded all of them, and `indeterminate` when only some of
 * them are included.
 *
 * @param preview - Reconciled preview, with any local choices already applied.
 * @returns The volume groups of the source in source order.
 */
export function buildCblSeriesGroups(preview: CBLAdoptionPreview): CblSeriesGroup[] {
  const groups = new Map<string, CblSeriesGroup>()

  for (const entry of preview.entries) {
    const existing = groups.get(entry.series_group_id)
    if (existing) {
      existing.entries.push(entry)
      continue
    }
    const year = entry.volume_year ?? entry.publication_year ?? null
    groups.set(entry.series_group_id, {
      id: entry.series_group_id,
      name: entry.series_name,
      year,
      label: cblSeriesGroupLabel(entry.series_name, year),
      entries: [entry],
      selectableEntries: [],
      selectedCount: 0,
      state: 'unchecked',
    })
  }

  return Array.from(groups.values()).map((group) => {
    const selectableEntries = group.entries.filter(
      (entry) => entry.adoption_class === 'existing' || entry.adoption_class === 'missing_importable',
    )
    const selectedCount = selectableEntries.filter((entry) => entry.adopted).length
    const excludedCount = group.entries.filter(
      (entry) => entry.adoption_decision === 'excluded',
    ).length
    let state: CblSeriesGroupState
    if (excludedCount === group.entries.length && group.entries.length > 0) {
      state = 'unchecked'
    } else if (selectedCount === selectableEntries.length) {
      state = 'checked'
    } else {
      state = 'indeterminate'
    }
    return { ...group, selectableEntries, selectedCount, state }
  })
}

/**
 * Accessible label for one issue checkbox inside a volume group.
 *
 * The group label carries the volume year, so two volumes that share a series
 * name still produce distinct checkbox names.
 *
 * @param group - The volume group the entry belongs to.
 * @param entry - The source entry the checkbox controls.
 * @returns The checkbox accessible name.
 */
export function cblEntryCheckboxLabel(
  group: CblSeriesGroup,
  entry: CBLAdoptionPreviewEntry,
): string {
  return `Include ${group.label} #${entry.issue_number}`
}
