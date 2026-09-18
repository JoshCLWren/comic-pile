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
