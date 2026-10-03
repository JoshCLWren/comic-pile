import { ROLL_WORKSPACE_MAX_WIDTH } from '../workspaceLayout'

/**
 * Rating workspace footer (issue #2712).
 *
 * A thin separator with a dice glyph and reading encouragement on the left and
 * the brand tagline on the right. It sits below the workspace in normal flow and
 * is desktop-only, so it never competes with the rating actions for the initial
 * desktop task view and never appears on a constrained width where it would
 * stack into the actions.
 *
 * The `max-w-4xl` shell is the same bounded workspace width the header and
 * `RatingView` use, so the separator lines up with the composition above it.
 */
export function RollFooter() {
  return (
    <footer
      data-testid="roll-footer"
      className="hidden shrink-0 border-t border-[var(--theme-border)] py-3 lg:block"
    >
      <div
        className={`mx-auto flex w-full items-end justify-between gap-4 px-4 ${ROLL_WORKSPACE_MAX_WIDTH}`}
      >
        <div className="flex min-w-0 items-center gap-2">
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            className="h-4 w-4 shrink-0 text-[var(--theme-text-dim)]"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <rect x="3.75" y="3.75" width="16.5" height="16.5" rx="3.5" />
            <circle cx="8.5" cy="8.5" r="1.25" fill="currentColor" stroke="none" />
            <circle cx="15.5" cy="15.5" r="1.25" fill="currentColor" stroke="none" />
            <circle cx="12" cy="12" r="1.25" fill="currentColor" stroke="none" />
          </svg>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-[var(--theme-text-muted)]">
              Enjoy the next adventure.
            </p>
            <p className="text-xs text-[var(--theme-text-dim)]">Read more comics.</p>
          </div>
        </div>
        <div className="min-w-0 text-right">
          <p className="text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-primary)]">
            Comic Pile
          </p>
          <p className="text-xs text-[var(--theme-text-dim)]">
            Your collection. New discoveries. Greater stories.
          </p>
        </div>
      </div>
    </footer>
  )
}