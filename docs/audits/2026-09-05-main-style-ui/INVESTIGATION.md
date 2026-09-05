# Style / UI audit investigation — main @ a95cba45

Investigation only. No product CSS/UI was changed.

Audited commit: `a95cba45` (`Fix auth session durability and missing-cookie refresh stampede (#2209)`), current `origin/main` as of 2026-09-05.

Canonical contract: `docs/FRONTEND_VISUAL_GRAMMAR.md`.

## Commands and results

| Command | Result |
| --- | --- |
| `git fetch origin main` then branch from `origin/main` | HEAD `a95cba45` |
| `pnpm install --frozen-lockfile` (repo root) | Pass |
| `cd frontend && pnpm install --frozen-lockfile` | Pass |
| `curl -LsSf https://astral.sh/uv/install.sh \| sh` then `uv sync --all-extras` | Pass (uv was not preinstalled) |
| `cd frontend && pnpm run audit:style` | **Pass** (informational). 195 files, 8574 class tokens, 1306 raw palette utilities, 53 one-off arbitrary values, 63 repeated long class groups |
| Isolated Postgres 16 + Redis 7 + `alembic upgrade head` on `127.0.0.1:5432` | Pass. Docker was not available; used local Postgres/Redis instead of `scripts/run_ui_audit.sh` |
| `cd frontend && pnpm exec playwright install chromium --with-deps` | Pass |
| `uv run uvicorn app.main:app --host 127.0.0.1 --port 8002` with `ENVIRONMENT=test` | Health `{"status":"healthy","database":"connected"}` |
| `cd frontend && pnpm run audit:ui` (`BASE_URL=http://127.0.0.1:8002`) | **Pass** (4/4 viewports). 32 scenarios, **55 diagnostic warnings**. Warnings do not fail the harness |

Note: `pnpm run audit:ui` from `frontend/` is the low-level command. The self-contained wrapper is `pnpm run audit:ui` at repo root (`scripts/run_ui_audit.sh`), which requires Docker Compose. This run used the documented frontend command against a locally started API on port 8002.

## Artifact paths

Committed copies (this directory):

- `docs/audits/2026-09-05-main-style-ui/INVESTIGATION.md` (this file)
- `docs/audits/2026-09-05-main-style-ui/style-audit-report.md`
- `docs/audits/2026-09-05-main-style-ui/style-audit-report.json`
- `docs/audits/2026-09-05-main-style-ui/ui-audit-report.md`
- `docs/audits/2026-09-05-main-style-ui/ui-audit-report.json`
- `docs/audits/2026-09-05-main-style-ui/screenshots/` (32 PNGs)

Workspace originals (gitignored):

- `dogfood-output/style-audit/report.md`
- `dogfood-output/style-audit/report.json`
- `frontend/test-results/ui-audit/report.md`
- `frontend/test-results/ui-audit/report.json`
- `frontend/test-results/ui-audit/screenshots/`
- `dogfood-output/ui-audit/` (copy of the Playwright output)

## How to read the ranked list

A finding is listed only when it is **not** already the subject of a closed deslop issue or an open UI issue. Covered items are in the last section so they are not re-filed.

Suggested issue titles are scoped to one surface or one shared primitive.

## Ranked findings (new / residual — file these)

### 1. High — Roll header still clips Ladder and Pick Manually at 820px

- **Files:** `frontend/src/pages/RollPage/components/RollHeader.tsx`, `frontend/src/App.tsx` (`md:grid-cols-[auto_minmax(0,1fr)]`)
- **Signal:** UI audit `unreachable-action` + `clipped-action` + `container-escape` on `roll` at tablet 820x1180. `LADDER` at `left:824` / `PICK MANUALLY` at `left:962` vs viewport 820. Screenshot: `screenshots/roll-tablet-820x1180.png`
- **Why it violates the grammar:** Responsive behavior and page-shell rules require headings and nearby actions to wrap as a unit and stay inside the viewport. Horizontal clipping is not an acceptable fallback. This is also a **regression of closed #2087**, whose acceptance required “820px rendered coverage has no clipped or unreachable Roll actions.”
- **Suggested issue title:** `Regression: Roll header clips Ladder and Pick Manually at 820px`

### 2. High — Queue Add-Thread FAB overlaps the last row on phone

- **Files:** `frontend/src/pages/QueuePage/QueuePage.tsx` (fixed `bottom-24` FAB), `frontend/src/pages/QueuePage/QueueThreadCard.tsx`
- **Signal:** UI audit `chrome-overlap` + `element-collision` on `queue` at phone 390x844 (`overlapRatio` 0.42 between `Add Thread` and `Open Test Thread 3`). Screenshot: `screenshots/queue-phone-390x844.png`
- **Why it violates the grammar:** Fixed/sticky chrome must not cover reachable content. The FAB also uses raw `bg-amber-600` and a one-off `shadow-[0_4px_20px_rgba(212,137,14,0.4)]` instead of `--theme-primary-action` and sparse established elevation.
- **Suggested issue title:** `Queue Add-Thread FAB overlaps the last queue row on phone`

### 3. High — Shared form-control class group still invents a raw-palette input dialect

- **Files:** 15 copies of the same 15-token group, led by `frontend/src/components/DependencyBuilder.tsx`, `frontend/src/pages/QueuePage/FormatSelect.tsx`, plus Login/Register and Queue/Thread textareas. Style-audit “Repeated long class groups” row 1.
- **Signal:** Static audit. Canonical string: `w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors`. A near-twin 16-token login/register group appears 6 times.
- **Why it violates the grammar:** Product text, border, panel, and focus meaning must use `--theme-text-*`, `--theme-border`, `--theme-bg-panel`, and `--theme-focus-ring`. A repeated raw color is evidence a semantic role is missing or unused. This is a local dialect copied across features.
- **Suggested issue title:** `Put the shared form-control class group on --theme-* tokens`

### 4. High — Identity Inbox is a light-theme white-card dialect

- **Files:** `frontend/src/pages/IdentityInboxPage.tsx`
- **Signal:** Static audit concentration (67 decision sites). Authored classes include `bg-white`, `border-stone-200`, `bg-stone-100`, `bg-stone-200`, `text-stone-800`, `text-blue-500`, `bg-green-500`. Not in the rendered audit (route not in the harness).
- **Why it violates the grammar:** Comic Pile is a dark cockpit. Page/panel/text/danger/continuity meaning must come from `data-theme` roles. A white card + raw blue link + traffic-light confidence bar is a second design system. Distinct from open #2207 (nav discoverability only).
- **Suggested issue title:** `Reskin Identity Inbox onto Comic Pile semantic theme tokens`

### 5. High — DependencyCrossoverControls is a gray/blue Bootstrap dialect

- **Files:** `frontend/src/components/DependencyCrossoverControls.tsx`
- **Signal:** Static audit repeated group `mt-1 w-full rounded border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-white` (3 sites). Selected chips use `bg-blue-600 text-white` vs `bg-gray-800`.
- **Why it violates the grammar:** Continuity/crossover membership is `--theme-continuity-accent` / `--theme-primary-action`, not raw blue. `gray-*` and default `rounded` (not `rounded-lg`/`xl`) invent a third control family next to the stone/amber form dialect above.
- **Suggested issue title:** `Retheme DependencyCrossoverControls from gray/blue utilities to semantic tokens`

### 6. Med — Crossover detail is still a raw-palette mini-dashboard

- **Files:** `frontend/src/pages/CrossoverDetailPage.tsx`
- **Signal:** Static audit (97 decision sites / 381 class tokens). Nested `rounded-2xl` + four `rounded-xl` metric tiles using `border-stone-700`, `bg-stone-900/50`, `bg-stone-950/50`, `text-emerald-400`, `bg-red-950/30`, `bg-amber-500`. Screenshot not in the default harness (detail route not audited); index shots show the same raw-stone create chrome: `screenshots/crossovers-desktop-1280x900.png`.
- **Why it violates the grammar:** Cards should not be added merely to wrap every cluster. Comic/continuity/danger meaning must use semantic accents. Nested metric tiles + raw emerald/red readiness chips read as a generic SaaS dashboard. #2091 scoped **index empty/create composition only**, not detail.
- **Suggested issue title:** `UI deslop: Crossover detail metric tiles and raw stone/emerald/red palette`

### 7. Med — Crossovers index create/list still uses raw stone/amber after #2091

- **Files:** `frontend/src/pages/CrossoversPage.tsx`
- **Signal:** Static audit + `screenshots/crossovers-*-*.png`. Eyebrow `text-amber-500`, title `text-stone-100`, input `border-stone-600 bg-stone-950`, primary `bg-amber-500`, errors `text-red-400` / `border-red-800`, populated rows `rounded-2xl border-stone-700 bg-stone-900/60`.
- **Why it violates the grammar:** #2091 removed the oversized empty card. Remaining product color still bypasses `--theme-*`. Focus/primary/danger/text roles exist and are unused here.
- **Suggested issue title:** `Crossovers create form and list rows still use raw Tailwind stone/amber`

### 8. Med — `glass-button` + tracked all-caps is the default action treatment

- **Files:** `frontend/src/styles.css` (`.glass-button` is only `letter-spacing: 0.15em; font-weight: 900; border-radius: 1.5rem`), `frontend/src/pages/QueuePage/QueueModals.tsx`, `frontend/src/pages/RollPage/components/RollModals.tsx`, `frontend/src/pages/ThreadDetailView.tsx`, `frontend/src/components/DependencyBuilder.tsx`, `frontend/src/pages/HistoryPage.tsx`, `frontend/src/pages/QueuePage/QueueControls.tsx`
- **Signal:** Repeated 8-token group `w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60` (5 sites). History/ThreadDetail also add `shadow-xl`.
- **Why it violates the grammar:** Ordinary buttons must not become tracked all-caps for intensity. One primary action per decision area. Pill radii are for chips/status, not generic full-width modal submits. `glass-button` is a leftover name that no longer describes a glass surface.
- **Suggested issue title:** `Stop using glass-button uppercase tracking-widest as the default modal action`

### 9. Med — Auth screens: glass-card + raw amber-600 + hardcoded classic hex

- **Files:** `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/RegisterPage.tsx`
- **Signal:** `glass-card rounded-2xl`, inputs from finding 3, submit `bg-amber-600` / `focus:ring-offset-[#1a1410]`, errors `bg-red-500/10 border-red-500/20 text-red-400`.
- **Why it violates the grammar:** Primary action and danger already have tokens. Hardcoding `#1a1410` freezes classic page color and will be wrong on `ink-gold` / `command-center`. Auth is not in the rendered audit (unauthenticated).
- **Suggested issue title:** `Restyle login/register onto semantic tokens and the shared control grammar`

### 10. Med — Floating Send-feedback button overlaps content at tablet/desktop

- **Files:** `frontend/src/components/BugReportButton.tsx` (`fixed bottom-32 right-4 … backdrop-blur-sm`)
- **Signal:** UI audit `chrome-overlap` on queue/history/crossovers/plans/planner/roll at tablet 820 and desktop 1280 (`overlapWidth/Height` 32). Same 32×32 hit as the floating control.
- **Why it violates the grammar:** New fixed chrome must account for reachability at every viewport. Backdrop-blur on a raw `stone-800/60` pill is glass noise. Distinct from closed #1645 (generic ~900px chrome) because this is one leftover floating control after the shell was made responsive.
- **Suggested issue title:** `Floating Send-feedback button overlaps page content at tablet and desktop`

### 11. Med — Parallel token families still share literals and fight `--theme-*`

- **Files:** `frontend/src/index.css` (`--theme-primary`, `--theme-primary-light`, `--theme-bg-dark`, `--theme-bg-card`), `frontend/src/styles.css` (`--bg-*`, `--text-*`, `--glass-*`, `--accent-*` aliases)
- **Signal:** Style audit “Shared literal custom-property values”: `#d4890e` is simultaneously `--accent-primary`, `--theme-comic-accent`, `--theme-danger-hover`, `--theme-focus-ring`, `--theme-primary-action`. `#110e0a` is `--bg-darker` and `--theme-bg-dark`. Grammar explicitly says not to treat `index.css` as a second design system.
- **Why it violates the grammar:** Collapsed roles make comic accent, focus, and danger-hover the same color. New work cannot tell which token to use. Compatibility aliases are allowed to remain, but shared literals plus a second `--theme-primary` family keep dialects alive.
- **Suggested issue title:** `Collapse leftover index.css --theme-primary tokens into styles.css data-theme roles`

### 12. Med — Feature-local CSS files still paint with hex/rgba and glass aliases

- **Files:** `frontend/src/components/MigrationDialog.css` (143 declarations), `frontend/src/components/DependencyFlowchart.css` (126), plus `frontend/src/components/IssueList.css`
- **Signal:** Highest presentation-decision concentrations after `styles.css`. Literal colors `#d4890e`, `#e8d5b0`, `rgba(255,255,255,0.08)`, plus `--glass-bg` / `--glass-blur` uses.
- **Why it violates the grammar:** Product meaning in CSS must use the same `data-theme` roles. These files are a fourth vocabulary (hand-written CSS + leftover glass tokens) beside Tailwind stone/amber, gray/blue, and `--theme-*`.
- **Suggested issue title:** `Migrate MigrationDialog and DependencyFlowchart CSS onto --theme-* roles`

### 13. Low — Roll recovery/taste cards are rounded-2xl + amber wash + shadow-lg

- **Files:** `frontend/src/pages/RollPage/components/RollRecoveryCard.tsx`, `frontend/src/pages/RollPage/components/TasteDiscoveryCard.tsx`
- **Signal:** Repeated group `mx-auto w-full max-w-xl rounded-2xl border border-amber-500/30 bg-amber-950/20 p-4 shadow-lg` (3 sites).
- **Why it violates the grammar:** Classic AI-card tell: large radius + tinted wash + shadow-lg on an ordinary card. Shadows should be sparse; ordinary cards do not need unique elevation. Raw amber instead of `--theme-comic-accent` / `--theme-bg-panel`.
- **Suggested issue title:** `Retire rounded-2xl+shadow-lg amber recovery cards on Roll`

### 14. Low — 8px/9px labels fall below the metadata role

- **Files:** `frontend/src/pages/RollPage/components/RollHeader.tsx` (`text-[8px]` Ladder / Auto), `frontend/src/pages/QueuePage/CompletedThreadsSection.tsx`, `frontend/src/pages/RollPage/components/ThreadPool.tsx` (`text-[9px]`)
- **Signal:** Style audit text-size inventory. Grammar metadata is `text-xs` or `text-[11px]`; eyebrows are ~10px.
- **Why it violates the grammar:** Variation rule — do not introduce a new font size when an existing role fits. 8px also fails the accessibility-as-grammar requirement.
- **Suggested issue title:** `Replace 8px/9px Roll and Queue labels with grammar metadata sizes`

### 15. Low — Roll eligible-thread tiles still read as glass mini-cards

- **Files:** `frontend/src/pages/RollPage/components/ThreadPool.tsx`
- **Signal:** Rendered shots `screenshots/roll-wide-desktop-1920x1080.png`, `screenshots/roll-tablet-820x1180.png`. Authored groups `flex items-center gap-2 px-4 py-2 bg-white/5 border border-white/5 rounded-lg` and `w-full px-4 py-2 bg-stone-500/5 border border-stone-500/10 rounded-xl`.
- **Why it violates the grammar:** #2087 scoped Roll **header controls** only and explicitly excluded “unrelated Roll cards.” Remaining eligible-thread tiles still use translucent borders and raw stone/white washes instead of one list vocabulary.
- **Suggested issue title:** `UI deslop: Roll eligible-thread tiles still use glass bordered cards`

## Classic AI-visual tells (authored classes)

| Tell | Present? | Where |
| --- | --- | --- |
| Purple/blue gradients | **No** product `bg-gradient` from purple/blue. One amber gradient: `ThreadDetailView.tsx` `bg-gradient-to-r from-amber-500 to-amber-400` | Isolated |
| Inter / system-ui fighting Outfit | **No.** `styles.css` imports Outfit and sets `font-family: 'Outfit', sans-serif` | Good |
| Reflexive glassmorphism | **Yes, residual.** `.glass-card`, `.glass-button`, `--glass-*`, `backdrop-blur` on Modal / RatingActionPanel / ReadingOrderTimeline / BugReportButton / Toast | Prefer `--theme-bg-panel` + `--theme-border` |
| Uniform `rounded-2xl` + `shadow-lg` | **Yes, localized.** Recovery/taste cards; History/QueueControls `shadow-xl` on glass-buttons; Navigation more-menu `rounded-2xl shadow-2xl` | Findings 8, 13 |
| Raw Tailwind palette for product meaning | **Yes, systemic.** 1306 raw palette utilities vs 59 CSS custom-property *uses*. Dominant: `text-stone-*` (500+), `text-amber-*`, `ring-amber-500/30`, `bg-amber-500`, `text-red-*` | Findings 3–7, 9 |
| Light-mode white cards | **Yes.** Identity Inbox | Finding 4 |
| Raw blue as selected/link color | **Yes.** `DependencyCrossoverControls` `bg-blue-600`; Identity Inbox `text-blue-500`; ComicIdentity / ComicVineIssueCard `text-blue-300` | Findings 4–5 |
| Tracked all-caps on ordinary buttons | **Yes.** `glass-button` + `uppercase tracking-widest` | Finding 8 |

`--theme-personal-accent` in classic is `#a855f7` (purple). That is a token definition, not an authored class tell. Do not file a “remove purple” issue against the token unless a theme redesign is intended.

## UI-audit warnings that should not become issues

These fired but are expected harness noise or already-owned work:

- **Mobile nav overlapping `main` (57px).** Shell owns bottom-nav clearance (`pb-20` / `--mobile-nav-height`). High-confidence `chrome-overlap` on phone is the nav sitting in its reserved band.
- **Manual-picker dialog covering the page / overlapping the die.** Expected modal overlay. `element-collision` against `main-die-3d` and die-face buttons is the dialog sitting on top of the roll canvas.
- **`div` overlapping `h1` “PILE ROLLER” (~111–134×28).** Looks like the small header die canvas / fixed fragment, not a user-blocked control. Confirm before filing.
- **Tablet/desktop `Send feedback` 32×32 overlap with `main`.** Same control as finding 10; do not also file a generic “chrome overlaps everything” ticket.

No `horizontal-overflow` or `large-blank-region` findings in this run. History / crossovers / plans empty states at 1920 look compact (closed #2091–#2093 held).

## Already covered — do not duplicate

### Closed deslop / visual-grammar issues

| Issue | Why this audit does not re-file it |
| --- | --- |
| **#2087** Roll control chrome / hierarchy | Header now uses a segmented die group + one solid Pick Manually. **Do re-file the 820px clip as a regression (finding 1).** Do not re-file “every die is a pill.” |
| **#2088** Queue card/action clutter | Rows are a list, not four colored pills. Read is primary; Edit/Snooze muted; Delete quiet. Residual: every row still has a solid Read (acceptable under #2088). |
| **#2089** Continuity Planner hierarchy | Planner uses `--theme-*` for save/cancel/borders. Phone shot no longer shows Add-lane / Save collision. |
| **#2091** Crossovers empty-state card | Empty index is compact copy under the create field. Remaining work is raw palette (finding 7), not the dashed/empty card. |
| **#2092** History sparse dashboard cards | History is a chronological list; Export Summary is a dotted utility link. |
| **#2093** Reading Plans oversized empty card | Empty plans index is compact. |
| **#2043 / #2070** Audit harness | Tooling only. This run used it. |
| **#2044 / #2045** Grammar + static audit | Docs/tooling. |
| **#611** Retire Analytics from nav | `/analytics` redirects to `/`. `AnalyticsPage.tsx` is still a glass-card / raw-amber dialect in source; **do not file a restyle unless the route is revived.** |
| **#1645** Fixed chrome overlap ~900px | Shell work landed. Remaining specific leftover is the floating feedback button (finding 10). |
| **#1943** Roll desktop packing | Wide-desktop roll packs sidebar + die + eligible list; no large-blank-region warning. |

### Open UI issues (already owned)

| Issue | Overlap |
| --- | --- |
| **#2186** Queue danger-red for dependency-blocked threads | Owns `QueueThreadCard.tsx` `bg-red-500/[0.06]`, lock `text-[var(--theme-danger)]`, `text-red-300/80 bg-red-500/10`. Do not file another blocked-row color issue. |
| **#2187** Queue hover overrides row state | Owns `hover:bg-white/[0.04]` vs state backgrounds. |
| **#2184 / #2185** Queue nested scroll / sentinel | Geometry of infinite scroll, not visual slop. |
| **#2207** Identity Inbox unreachable from nav | Discoverability only. Visual reskin is finding 4. |
| **#2104** Remove continuity readiness product surface | Product-surface removal, not CSS cleanup. Crossover detail readiness chips (finding 6) may disappear if #2104 lands first — check before filing finding 6. |

## Suggested filing order

1. Finding 1 (820px Roll regression) — user-visible, closed-issue regression.
2. Finding 2 (Queue FAB overlap) — user-visible, phone.
3. Finding 3 (shared form tokens) — highest-leverage systemic cleanup; unblocks 7 and 9.
4. Findings 4 and 5 — isolated dialects.
5. Findings 6–8 — surface deslop after the shared control exists.
6. Findings 9–12 — auth, floating chrome, token collapse, leftover CSS files.
7. Findings 13–15 — polish.

Do not open a repository-wide “replace all stone/amber” issue. The grammar migration policy forbids mass class rewrites.
