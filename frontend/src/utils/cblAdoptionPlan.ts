import type { CBLAdoptionPreview, CBLAdoptionPreviewEntry } from '../services/api-cbl-sources'

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
