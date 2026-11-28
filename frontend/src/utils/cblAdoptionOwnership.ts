import type {
  CBLAdoptionCommitResult,
  CBLAdoptionPreview,
} from '../services/api-cbl-sources'
import { isBoolean, isNumber, isObject, isString } from './runtimeChecks'
import type { ReadingGraphChoices } from './readingGraphOverlaps'
import { buildCblSeriesGroups } from './cblAdoptionPlan'

/**
 * Client-side pointer from a shared CBL source to the reader's canonical owned
 * Reading List. This is committed state only: it is written after a successful
 * Add/Update commit and never on cancel or while choices are still being edited.
 * The server remains authoritative for the saved choices themselves, which are
 * restored from `GET /api/v2/reading-lists/{list_id}` on reopen (#4022).
 *
 * Display names are deliberately absent: identity is source id + owner, never
 * a name that another list or another reader may share.
 */
export interface OwnedCblListLink {
  sourceId: number
  listId: number
  listVersion: number
  contentHash: string
  revisionSha: string
}

const STORAGE_KEY = 'comicpile.cbl-adoption-owned-lists.v1'

function parseLink(value: unknown): OwnedCblListLink | null {
  if (!isObject(value)) return null
  const { sourceId, listId, listVersion, contentHash, revisionSha } = value
  if (
    !isNumber(sourceId) || !Number.isSafeInteger(sourceId) || sourceId <= 0
    || !isNumber(listId) || !Number.isSafeInteger(listId) || listId <= 0
    || !isNumber(listVersion) || !Number.isSafeInteger(listVersion) || listVersion < 0
    || !isString(contentHash) || !isString(revisionSha)
  ) {
    return null
  }
  return { sourceId, listId, listVersion, contentHash, revisionSha }
}

function readAll() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    if (!isObject(parsed)) return {}
    const links: Record<string, OwnedCblListLink> = {}
    for (const [key, value] of Object.entries(parsed)) {
      const link = parseLink(value)
      if (link && Number(key) === link.sourceId) links[key] = link
    }
    return links
  } catch {
    return {}
  }
}

function writeAll(links: Record<string, OwnedCblListLink>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(links))
  } catch {
    // Storage can be disabled or full; reopen still works within the session
    // through React state, and the server remains the authority for choices.
  }
}

/** Read the committed owned-list pointer for one shared source. */
export function readOwnedCblList(sourceId: number): OwnedCblListLink | null {
  return readAll()[String(sourceId)] ?? null
}

/** Remember the canonical list after a successful, explicitly confirmed commit. */
export function saveOwnedCblList(link: OwnedCblListLink): void {
  writeAll({ ...readAll(), [String(link.sourceId)]: link })
}

/** Drop a pointer whose source has changed or whose list no longer exists. */
export function forgetOwnedCblList(sourceId: number): void {
  const links = readAll()
  delete links[String(sourceId)]
  writeAll(links)
}

/** Resolve the canonical list ID from a commit response, never its plan projection. */
export function canonicalListId(result: CBLAdoptionCommitResult): number | null {
  const value = result.custom_cbl_list_id
  return isNumber(value) && Number.isSafeInteger(value) && value > 0 ? value : null
}

function decisionMap(value: unknown) {
  if (!isObject(value)) return {}
  const decisions: Record<string, boolean> = {}
  for (const [key, raw] of Object.entries(value)) {
    if (isString(raw) && (raw === 'include' || raw === 'exclude')) {
      decisions[key] = raw === 'include'
    } else if (isBoolean(raw)) {
      decisions[key] = raw
    }
  }
  return decisions
}

export interface CblDecisionMap {
  [key: string]: boolean
}

export interface RestoredCblChoices {
  series: CblDecisionMap
  entries: CblDecisionMap
}

/** Committed CBL selection document shape as persisted by the server. */
export interface CommittedCblSelections {
  entry_decisions?: unknown
  series_overrides?: unknown
  series_decisions?: unknown
}

export interface CommittedOverlapDecision {
  overlap_id: string
  choice: string
}

export function parseCommittedSelections(value: unknown): CommittedCblSelections | null {
  if (!isObject(value)) return null
  return {
    entry_decisions: value.entry_decisions,
    series_overrides: value.series_overrides,
    series_decisions: value.series_decisions,
  }
}

export function parseCommittedOverlapDecisions(
  value: unknown,
): ReadonlyArray<CommittedOverlapDecision> | null {
  if (!Array.isArray(value)) return null
  const decisions: CommittedOverlapDecision[] = []
  for (const item of value) {
    if (!isObject(item)) continue
    const { overlap_id: overlapId, choice } = item
    if (isString(overlapId) && isString(choice)) {
      decisions.push({ overlap_id: overlapId, choice })
    }
  }
  return decisions
}

/**
 * Project the server's committed `selections` document back onto the browser's
 * checklist state. Entry overrides win over position/series overrides, exactly
 * as `applyCblAdoptionChoices` applies them while the reader edits.
 */
export function restoreCommittedChoices(
  preview: CBLAdoptionPreview,
  selections: CommittedCblSelections | null | undefined,
): RestoredCblChoices {
  if (!selections) return { series: {}, entries: {} }
  const entryOverrides = decisionMap(selections.entry_decisions)
  const positionOverrides = decisionMap(selections.series_overrides)
  const nameDecisions = decisionMap(selections.series_decisions)

  const series: CblDecisionMap = {}
  const entries: CblDecisionMap = {}
  for (const group of buildCblSeriesGroups(preview)) {
    // A volume-level choice is only real when the server stored one for the
    // whole volume (or the backend's series-name decision). A lone unchecked
    // issue must not silently become "exclude this entire volume" on reopen.
    const groupNameDecision = nameDecisions[group.name]
    const allHavePositionOverride = group.entries.every(
      (entry) => positionOverrides[String(entry.cbl_position)] !== undefined,
    )
    const firstPositionDecision = positionOverrides[String(group.entries[0]?.cbl_position)]
    const uniformPositionDecision =
      allHavePositionOverride
      && group.entries.every(
        (entry) =>
          positionOverrides[String(entry.cbl_position)] === firstPositionDecision,
      )
    const seriesDecision = groupNameDecision
      ?? (uniformPositionDecision ? firstPositionDecision : undefined)

    if (seriesDecision !== undefined) series[group.id] = seriesDecision
    for (const entry of group.entries) {
      const entryId = String(entry.cbl_entry_id)
      const position = String(entry.cbl_position)
      const explicitEntry = entryOverrides[entryId]
      const positionDecision = positionOverrides[position]
      if (explicitEntry !== undefined) {
        entries[entryId] = explicitEntry
      } else if (
        seriesDecision === undefined && positionDecision !== undefined
        || seriesDecision !== undefined
        && positionDecision !== undefined
        && positionDecision !== seriesDecision
      ) {
        entries[entryId] = positionDecision
      }
    }
  }
  return { series, entries }
}

/** Restore reader-approved reading-graph answers from the committed document. */
export function restoreOverlapChoices(
  overlapDecisions: ReadonlyArray<CommittedOverlapDecision> | null | undefined,
): ReadingGraphChoices {
  if (!overlapDecisions) return {}
  const choices: ReadingGraphChoices = {}
  for (const item of overlapDecisions) {
    const overlapId = item.overlap_id
    const choice = item.choice
    if (
      isString(overlapId)
      && isString(choice)
      && (choice === 'protect_order' || choice === 'continue_series')
    ) {
      choices[overlapId] = choice
    }
  }
  return choices
}
