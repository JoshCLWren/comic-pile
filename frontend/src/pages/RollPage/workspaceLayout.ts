/**
 * Roll rating workspace geometry (issue #2712).
 *
 * The page chrome and the rating workspace must resolve to the same outer edges
 * and the same Comic/Decision division. Otherwise the header accent rule stops
 * somewhere other than the boundary it exists to mark, and the header no longer
 * reads as one workspace with the composition beneath it. Tailwind resolves
 * utility strings literally, so the recipe is owned here once and composed at
 * each call site rather than copied into the header and the workspace.
 *
 * The bounded `max-w-4xl` shell and the bounded Decision track are the shipped
 * #2990 density fix: they keep comic content clustered with the decision card
 * instead of stranding it across a wide empty track. #2992 asserts that
 * clustering in rendered geometry at 1280-2560px. Growing these tracks so the
 * shell can span the full authenticated width additionally requires growing
 * `ComicPillar`/`ComicIdentity` internals, which #2712 explicitly fences out
 * (`#2762`/`#2768` own those components).
 */

/** Bounded, centered workspace shell. Not stretched indefinitely on ultrawide. */
export const ROLL_WORKSPACE_MAX_WIDTH = 'lg:mx-auto lg:max-w-4xl'

/**
 * Asymmetric two-region split: a slightly wider Comic region beside a bounded
 * Decision region. Underscore separators only; a top-level comma in an
 * arbitrary `grid-cols-[...]` value emits invalid CSS and silently collapses
 * the grid to one column (#2952, guarded by #2992).
 */
export const ROLL_WORKSPACE_TRACKS =
  'lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)] xl:grid-cols-[minmax(0,32rem)_minmax(18rem,24rem)]'

/** Compact intentional gutter between the two regions. */
export const ROLL_WORKSPACE_GUTTER = 'gap-4 lg:gap-6'