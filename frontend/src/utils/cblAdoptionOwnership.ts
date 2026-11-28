import type {
  CBLAdoptionCommitResult,
  CBLAdoptionPreview,
} from '../services/api-cbl-sources'
import { isBoolean, isNumber, isObject, isString } from './runtimeChecks'
import type { ReadingGraphChoices } from './readingGraphOverlaps'

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

function readAll(): Record<string, OwnedCblListLink> {
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

function decisionMap(value: unknown): Record<string, boolean> {
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

export interface RestoredCblChoices {
  series: Record<string, boolean>
  entries: Record<string, boolean>
}

/**
 * Project the server's committed `selections` document back onto the browser's
 * checklist state. Entry overrides win over position/series overrides, exactly
 * as `applyCblAdoptionChoices` applies them while the reader edits.
 */
export function restoreCommittedChoices(
  preview: CBLAdoptionPreview,
  selections: unknown,
): RestoredCblChoices {
  if (!isObject(selections)) return { series: {}, entries: {} }
  const entryOverrides = decisionMap(selections.entry_decisions)
  const positionOverrides = decisionMap(selections.series_overrides)

  const byGroup = new Map<string, Array<{ entryId: string; position: string; include: boolean }>>()
  for (const entry of preview.entries) {
    const entryId = String(entry.cbl_entry_id)
    const position = String(entry.cbl_position)
    const include = entryOverrides[entryId] ?? positionOverrides[position]
    if (include === undefined) continue
    const group = byGroup.get(entry.series_group_id) ?? []
    group.push({ entryId, position, include })
    byGroup.set(entry.series_group_id, group)
  }

  const series: Record<string, boolean> = {}
  const entries: Record<string, boolean> = {}
  for (const [groupId, decisions] of byGroup) {
    const allSame =
      decisions.length > 0 && decisions.every((decision) => decision.include === decisions[0].include)
    if (allSame) {
      series[groupId] = decisions[0].include
    }
    // An entry that disagrees with its volume (or whose volume has no uniform
    // decision) is an explicit per-issue choice and must be restored as such.
    for (const decision of decisions) {
      if (!allSame || decision.include !== decisions[0].include || decision.entryId in entryOverrides) {
        entries[decision.entryId] = decision.include
      }
    }
  }
  return { series, entries }
}

/** Restore reader-approved reading-graph answers from the committed document. */
export function restoreOverlapChoices(overlapDecisions: unknown): ReadingGraphChoices {
  if (!Array.isArray(overlapDecisions)) return {}
  const choices: ReadingGraphChoices = {}
  for (const item of overlapDecisions) {
    if (!isObject(item)) continue
    const { overlap_id: overlapId, choice } = item
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
