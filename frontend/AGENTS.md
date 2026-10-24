# Frontend agent guidance

The repository-level `../AGENTS.md` rules apply to all frontend work.

For any change that affects layout, styling, component presentation, responsive behavior, dialogs, fixed/sticky chrome, icons, or theme usage, also follow the canonical visual contract in [`../docs/FRONTEND_VISUAL_GRAMMAR.md`](../docs/FRONTEND_VISUAL_GRAMMAR.md).

Do not introduce a new visual value or treatment merely for local convenience when the existing semantic grammar can express the product meaning. Use the static and rendered audits as evidence when deciding whether existing variation is intentional or drift.

## Overlay Architecture Ownership

**One primitive rule:** Dialogs use `Modal`; menus/popovers use `OverlayPortal` `layer="menu"` (or a thin shared Menu primitive built on it).

**Approved components:**
- `Modal` — full-dialog primitives with focus trap, Escape handling, backdrop ownership, focus lock, and stacking counter
- `OverlayPortal` `layer="menu"` — position menus, popovers, and selectors
- `OverlayPortal` `layer="dialog"` — portaled dialogs that delegate focus/Escape/stacking to `Modal`

**Not allowed:** Ad-hoc `fixed inset-0` / `role="dialog"` / `aria-modal` overlays outside the approved components above. New dialogs must go through `Modal`; new menus must go through `OverlayPortal` `layer="menu"`.

**Known debt (allowlisted until migration):** `MigrationDialog`, `SimpleMigrationDialog`, `ContinuityPlansIndexPage`, `Navigation` "More" menu — these will be migrated in a follow-up ticket.

## Focused checks for shared boundaries

When adding an `App.tsx` route, classify it in `src/seo/routeSeo.ts`, update
`public/robots.txt`, and run `seoRouteTable.test.ts` plus
`seoIndexabilityPolicy.test.ts` before pushing. Unknown-route fallback does not
replace explicit classification.

When changing optional Roll data ownership, run both request-scope suites
(`useRollRating.request-scopes.test.tsx` and `useRatingView.request-scopes.test.tsx`)
and `RatingView.optional-cards.test.tsx`. Mock the API actually consumed by the
surface and preserve its independent loading, failure, and retry coverage.
