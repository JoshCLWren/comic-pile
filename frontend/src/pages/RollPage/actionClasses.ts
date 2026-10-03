/**
 * Roll-screen action hierarchy (issue #3009).
 *
 * `docs/FRONTEND_VISUAL_GRAMMAR.md` reserves the letter-spaced uppercase
 * treatment for eyebrow labels and the primary action, requires action-group
 * peers to share height, radius, typography, and interaction behavior, and
 * requires secondary supporting actions to use ordinary lower-emphasis styling.
 *
 * The rating action group is rendered by two components — `DecisionCard` on the
 * live Roll screen and the separately tested `RatingActionPanel` — and the two
 * drifted apart. That drift is how `Cancel roll` ended up as the only peer with
 * a transparent background and an accent-muted label inside an otherwise
 * uniform row, so it read as a differently colored and visibly squeezed action
 * instead of a peer. Naming each treatment once keeps the peers identical rather
 * than merely similar, and makes the hierarchy reviewable from a single place.
 *
 * These are Tailwind class lists, not a component library: the repository has no
 * button primitive yet, and the grammar only asks that repeated presentation pay
 * for an abstraction. When one arrives it can replace this module wholesale.
 */

/**
 * The dominant affirmative action for a Roll decision area. This is the only
 * element in the rating card allowed to keep uppercase letter-spaced type; the
 * muted gold fill plus the `text-stone-900` label match the die-view Roll CTA's
 * established on-primary treatment so the whole screen has one primary look.
 */
export const rollPrimaryActionClass = [
  'w-full min-h-11 rounded-xl border border-transparent bg-[var(--theme-primary-action)]',
  'px-4 py-2.5 text-xs font-black uppercase tracking-[0.15em] text-stone-900',
  'transition hover:bg-[var(--theme-primary-action-hover)] active:scale-[0.98]',
  'focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-50',
].join(' ')

/**
 * Ordinary supporting action, shared verbatim by every peer button in a rating
 * action group (Snooze, Skip, Cancel roll). `min-w-28` plus `flex-wrap` is what
 * keeps `Cancel roll` off its button edges: the group reflows to two rows on
 * phone widths instead of squeezing three labels into one line, and the label
 * keeps the same `px-4` inline padding at every width.
 *
 * The label uses `--theme-text-primary` rather than `--theme-text-muted` on
 * purpose. `--theme-text-muted` is a pale cyan in the `command-center` theme, so
 * a muted-text secondary read as an unrelated accent inside the navy/gold
 * system; hierarchy here comes from the surface treatment, not from dimming the
 * label into a different hue.
 */
export const rollSecondaryActionClass = [
  'min-h-11 min-w-28 flex-1 rounded-xl border border-[var(--theme-border)]',
  'bg-[var(--theme-bg-panel)] px-4 py-3 text-sm font-semibold',
  'text-[var(--theme-text-primary)]',
  'transition hover:bg-white/10',
  'focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-50',
].join(' ')

/**
 * Compact utility action (icon plus label) such as `Copy title`. Utilities are
 * recovery helpers, not workflow steps, so they stay sentence case, small, and
 * muted, and never compete with the primary action. The caller supplies the hit
 * height so a compact inline utility and a standalone one stay tappable at their
 * own surface's scale.
 *
 * The status variants are resolved here instead of by appending override classes
 * at the call site: two different `text-[…]` utilities in one class list resolve
 * by stylesheet order, not by the order they appear in the attribute, so
 * composing them at the call site would silently pick a winner.
 */
export function rollUtilityActionClass(status: 'idle' | 'copied' | 'failed' = 'idle'): string {
  const base = [
    'inline-flex items-center gap-1.5 rounded-lg border px-3 text-xs font-medium transition',
    'focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-40',
  ].join(' ')

  if (status === 'copied') {
    // Success is carried by the label change plus the polite live region, not
    // by a tint: the design system has no success accent, and reusing the
    // continuity accent here would borrow a reading-order meaning it does not
    // have.
    return `${base} border-[var(--theme-border)] bg-[var(--theme-bg-panel)] text-[var(--theme-text-primary)]`
  }

  if (status === 'failed') {
    return `${base} border-[var(--theme-danger)]/30 bg-[var(--theme-danger)]/10 text-[var(--theme-danger)]`
  }

  return `${base} border-[var(--theme-border)] bg-[var(--theme-bg-panel)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]`
}

/**
 * Neutral confirm-region action. Used where a dialog's quiet choice must read as
 * a peer of the affirmative one rather than as a demoted text link. The caller
 * supplies the hit height.
 */
export const rollDialogSecondaryActionClass = [
  'rounded-lg border border-[var(--theme-border)] px-4 py-2 text-sm font-semibold',
  'text-[var(--theme-text-primary)]',
  'transition-colors hover:bg-white/5 disabled:opacity-50',
].join(' ')

/**
 * Destructive confirm. Skip genuinely discards the rolled comic, so it keeps
 * danger semantics; only its typography is demoted to ordinary sentence case.
 */
export const rollDangerActionClass = [
  'rounded-lg bg-[var(--theme-danger)] px-4 py-2 text-sm font-semibold text-white',
  'transition-colors hover:bg-[var(--theme-danger-hover)] disabled:opacity-50',
].join(' ')

/**
 * Wrapper for the secondary action group. `flex-wrap` is what lets the group
 * reflow instead of squeezing, and the shared `gap-2` keeps wrapped rows evenly
 * spaced.
 */
export const rollSecondaryActionGroupClass = 'flex flex-wrap gap-2'