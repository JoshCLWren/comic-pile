import type { InheritanceSource } from '../../services/api-tags'

/**
 * Query parameter that asks a detail page to open its tag editor.
 *
 * Inherited-source entries are navigation affordances: following one must land
 * the reader on the object that owns the assignment with its editor already
 * open, so the tag can actually be edited there (issue #4332). The parameter is
 * intentionally explicit rather than a fragment scroll, because it gives every
 * source link a real effect even when the source is the page already on screen.
 */
export const TAG_EDITOR_QUERY_PARAM = 'tagEditor'

/** `tagEditor` value for a Thread source. */
export const TAG_EDITOR_THREAD = 'thread'

/** `tagEditor` value for a Reading Plan (ContinuityPlan) source. */
export const TAG_EDITOR_PLAN = 'plan'

/** Supported tag-editor deep-link targets. */
export type TagEditorTarget = typeof TAG_EDITOR_THREAD | typeof TAG_EDITOR_PLAN

/**
 * Destination route for an inheritance source without editor state.
 *
 * Threads and Reading Plans have stable detail routes. Issue-typed sources in
 * v1 are always the queried object itself (issues inherit from threads and
 * plans, never from other issues), so they have no navigable destination.
 */
export function sourceRoute(source: InheritanceSource): string | null {
  if (source.target_type === 'Thread') return `/thread/${source.target_id}`
  if (source.target_type === 'ContinuityPlan')
    return `/continuity-plans/${source.target_id}`
  return null
}

/** Editor deep-link target for a source type, if its page hosts a tag editor. */
export function sourceTagEditorTarget(
  source: InheritanceSource,
): TagEditorTarget | null {
  if (source.target_type === 'Thread') return TAG_EDITOR_THREAD
  if (source.target_type === 'ContinuityPlan') return TAG_EDITOR_PLAN
  return null
}

/**
 * Destination route for a source with its tag editor open.
 *
 * Returns `null` for sources that cannot be edited in place (Issue-typed
 * sources, which v1 never produces as an inheritance parent).
 */
export function sourceTagEditorPath(source: InheritanceSource): string | null {
  const route = sourceRoute(source)
  const target = sourceTagEditorTarget(source)
  if (!route || !target) return null
  return `${route}?${TAG_EDITOR_QUERY_PARAM}=${target}`
}

/**
 * Rewrite a location search string so it opens or closes a tag editor.
 *
 * Other query parameters are preserved, so opening an editor from a deep link
 * (for example `?issue=12`) never discards the reader's current target.
 */
export function tagEditorSearch(
  search: string,
  target: TagEditorTarget | null,
): string {
  const params = new URLSearchParams(search)
  if (target) params.set(TAG_EDITOR_QUERY_PARAM, target)
  else params.delete(TAG_EDITOR_QUERY_PARAM)
  const next = params.toString()
  return next ? `?${next}` : ''
}
