import type { CorrectionChoiceId } from '../components/CorrectionSheet'

/** One user-rated comic used as example evidence (e.g. analytics top-rated threads). */
export interface RatedComicOption {
  title: string
  rating: number | null
  format: string | null
}

/** One comic from the user's own read/queue history (e.g. Roll bootstrap pool). */
export interface HistoryComicOption {
  title: string
  format: string | null
}

export interface CorrectionExampleInput {
  /** Comics the user has rated, carrying the rating signal. */
  rated: RatedComicOption[]
  /** Comics from the user's own queue/read history, carrying format context. */
  history: HistoryComicOption[]
  /** Current roll target: never illustrate an option with the comic being rejected. */
  activeTitle?: string | null
  /** Format of the current roll target, used for the same-effort peer example. */
  activeFormat?: string | null
}

/** Example display title per choice. Absent key = no honest example exists. */
export type CorrectionExampleTitles = Partial<Record<CorrectionChoiceId, string>>

/**
 * Ratings use the 0.5-5.0 scale (app/schemas/rate.py). Only comics at or above
 * this threshold illustrate "what I've liked" so a lukewarm top rating never
 * poses as a favorite.
 */
const LIKED_RATING_THRESHOLD = 3.5

/**
 * Normalized format hints for the lightest-commitment reads in a user's
 * history. This is an illustrative UI heuristic only: it never feeds
 * selection, which stays on the canonical bandwidth behavior behind the
 * `even_easier` patch.
 */
const LIGHT_FORMAT_HINTS = ['issue', 'single', 'one-shot', 'oneshot', 'annual']

function normalizedTitle(title: string): string {
  return title.trim()
}

function normalizedFormat(format: string | null | undefined): string {
  return (format ?? '').trim().toLowerCase()
}

function isUsableTitle(title: string, activeTitle: string): boolean {
  const clean = normalizedTitle(title)
  if (!clean) return false
  return clean.toLowerCase() !== activeTitle
}

function isLightFormat(format: string | null | undefined): boolean {
  const normalized = normalizedFormat(format)
  if (!normalized) return false
  return LIGHT_FORMAT_HINTS.some((hint) => normalized.includes(hint))
}

/**
 * Derive per-choice example titles for the correction sheet from the signed-in
 * user's own rated/read history.
 *
 * Every returned title comes verbatim from the input: examples are never
 * invented and never drawn from global popularity data. Selecting a choice
 * still uses the canonical session-mode patch; examples are explanatory only.
 * When no honest example exists for an option, its key is omitted so the
 * sheet degrades to descriptive copy. `pure_random` never receives an
 * example because it explicitly ignores steering preferences.
 */
export function selectCorrectionExamples(input: CorrectionExampleInput): CorrectionExampleTitles {
  const activeTitle = normalizedTitle(input.activeTitle ?? '').toLowerCase()
  const liked = input.rated
    .filter(
      (entry) =>
        entry.rating != null &&
        entry.rating >= LIKED_RATING_THRESHOLD &&
        isUsableTitle(entry.title, activeTitle),
    )
    .sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0))

  const result: CorrectionExampleTitles = {}
  const used = new Set<string>()

  const claim = (title: string): string => {
    used.add(normalizedTitle(title).toLowerCase())
    return normalizedTitle(title)
  }
  const isClaimed = (title: string): boolean =>
    used.has(normalizedTitle(title).toLowerCase())

  // Familiar: the user's top-rated comics illustrate "what I've liked".
  // Up to two titles keep the line compact ("A / B territory").
  const familiarPicks = liked.filter((entry) => !isClaimed(entry.title)).slice(0, 2)
  let familiarFormat = ''
  if (familiarPicks.length > 0) {
    result.something_familiar = familiarPicks.map(entry => claim(entry.title)).join(' / ')
    familiarFormat = normalizedFormat(familiarPicks[0].format)
  }

  // Change of pace: a liked comic in a different format lane than the familiar
  // pick illustrates meaningful contrast without claiming genre knowledge the
  // client does not have. Falls back to no example when the liked history is
  // single-format.
  const contrast = liked.find(
    (entry) =>
      !isClaimed(entry.title) &&
      familiarFormat !== '' &&
      normalizedFormat(entry.format) !== '' &&
      normalizedFormat(entry.format) !== familiarFormat,
  )
  if (contrast) {
    result.something_different = claim(contrast.title)
  }

  const historyPool = [...input.rated, ...input.history]

  // Lighter: a single-issue-style read from the user's own history illustrates
  // lower commitment. Format is illustration only, never a second effort
  // definition: selection still uses the canonical bandwidth patch.
  const lighter = historyPool.find(
    (entry) =>
      isUsableTitle(entry.title, activeTitle) &&
      !isClaimed(entry.title) &&
      isLightFormat(entry.format),
  )
  if (lighter) {
    result.even_easier = claim(lighter.title)
  }

  // Same effort: another comic in the same format lane as the current roll
  // illustrates "same commitment, different comic". Without a known active
  // format there is no honest peer, so the key stays omitted.
  const activeFormat = normalizedFormat(input.activeFormat)
  if (activeFormat !== '') {
    const peer = historyPool.find(
      (entry) =>
        isUsableTitle(entry.title, activeTitle) &&
        !isClaimed(entry.title) &&
        normalizedFormat(entry.format) === activeFormat,
    )
    if (peer) {
      result.keep_level_different = claim(peer.title)
    }
  }

  return result
}
