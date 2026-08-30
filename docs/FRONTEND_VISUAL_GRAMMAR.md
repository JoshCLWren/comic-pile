# Comic Pile frontend visual grammar

This document is the canonical visual contract for Comic Pile frontend work. It describes the product's existing visual language and the constraints that keep new work from inventing a fresh dialect on every page.

It is a decision guide, not a mandate to rewrite every historical class. Existing variation should be migrated only through focused issues backed by rendered or static audit evidence.

## Product character

Comic Pile is a dense personal reading cockpit, not a generic SaaS dashboard. The interface should feel dark, tactile, comic-adjacent, and information-rich without becoming visually noisy. Theme personality comes from semantic accents and surfaces, while layout and interaction behavior should remain consistent across themes.

The three existing themes are `classic`, `ink-gold`, and `command-center`. New feature code should consume semantic theme roles rather than reproduce a theme's literal colors.

## Canonical semantic color and surface roles

`frontend/src/styles.css` owns the canonical theme roles applied by `data-theme`:

| Role | Token | Purpose |
| --- | --- | --- |
| Page | `--theme-bg-page` | Primary application canvas |
| Panel | `--theme-bg-panel` | Cards, grouped controls, inset surfaces |
| Border | `--theme-border` | Ordinary panel/control separation |
| Primary text | `--theme-text-primary` | Main readable text |
| Muted text | `--theme-text-muted` | Secondary labels and context |
| Dim text | `--theme-text-dim` | Tertiary/de-emphasized metadata |
| Comic accent | `--theme-comic-accent` | Comic identity and comic-specific emphasis |
| Continuity accent | `--theme-continuity-accent` | Reading-order, crossover, dependency, continuity information |
| Personal accent | `--theme-personal-accent` | User history, ratings, and personal context |
| Primary action | `--theme-primary-action` | Main affirmative action |
| Primary action hover | `--theme-primary-action-hover` | Interactive state for the main action |
| Danger | `--theme-danger` | Destructive or cancel semantics |
| Danger hover | `--theme-danger-hover` | Interactive destructive state |
| Focus ring | `--theme-focus-ring` | Keyboard/focus visibility |

The older `--bg-*`, `--text-*`, `--accent-*`, and `--glass-*` variables are compatibility aliases. They may remain in existing code, but new work should prefer the `--theme-*` semantic vocabulary when the needed role exists.

`frontend/src/index.css` contains older root-level theme values such as `--theme-primary` and `--theme-bg-card`. Do not treat those as a second design system or add parallel tokens there. A new semantic role belongs with the `data-theme` token sets in `styles.css` and must be defined for every theme.

### Raw colors

Raw Tailwind palette utilities, hex values, RGB/RGBA values, or one-off opacity colors are acceptable only when they express a genuinely local visual effect that has no reusable semantic meaning, for example a WebGL effect or a deliberately translucent overlay. Product meaning such as comic, continuity, personal context, danger, focus, page, panel, border, or text hierarchy must use the semantic roles above.

A repeated raw color is evidence that a semantic role may be missing.

## Spacing and density

Use Tailwind's standard spacing scale. Prefer the small set already dominant in Comic Pile instead of arbitrary bracketed spacing:

- `1` / `1.5` / `2` for tight icon, inline, and metadata relationships;
- `3` / `4` for ordinary control and card padding/gaps;
- `6` for separation between major regions on larger viewports;
- `8` or larger only for deliberate page-section separation.

Responsive pairs such as `p-3 md:p-4`, `gap-4 md:gap-6`, and `px-4 md:px-6` are established patterns. Prefer them when they fit the semantic relationship.

Do not introduce arbitrary values merely to make one screenshot line up. Bracketed values are appropriate for real constraints that the scale cannot express, such as safe-area calculations, viewport containment, or aspect-ratio-driven sizing.

Spacing communicates grouping. Elements that belong together should be closer to each other than to neighboring groups. Avoid large empty tracks manufactured by grid coordinates or `min-height` values.

## Typography

Comic Pile uses Outfit as its application typeface. Preserve the existing compact, high-contrast hierarchy:

| Role | Typical treatment |
| --- | --- |
| Page/title | `text-xl` through `text-2xl`, heavy/bold, compact leading |
| Section/card heading | `text-base` through `text-xl`, bold/black |
| Body | `text-sm` or `text-base`, normal/semibold |
| Metadata | `text-xs` or `text-[11px]`, muted |
| Eyebrow/status label | about `10px`, uppercase, black/bold, wider tracking |
| Primary numeric readout | intentionally large and heavy, e.g. the rating value |

The small uppercase eyebrow is a real Comic Pile motif, not a default treatment for every label. Do not turn ordinary body copy, buttons, or navigation into tracked all-caps simply for visual intensity.

Use line height appropriate to content. Titles may be tight; descriptions and explanatory copy must remain comfortably readable. Avoid arbitrary font sizes when an existing role fits.

## Borders, radii, elevation, and surfaces

Use shape to indicate surface hierarchy, not feature ownership.

- `rounded-lg`: controls, compact dialogs, and smaller contained surfaces.
- `rounded-xl`: ordinary cards, controls, and grouped interactive surfaces.
- `rounded-2xl`: prominent panels or hero/selected-state cards.
- Pill/capsule radii are for chips, badges, compact status controls, and intentionally pill-shaped actions, not generic cards.

`glass-card` is the legacy shared card treatment: semantic panel background, semantic border, `0.75rem` radius. `modal-card` is the established elevated dialog surface with a stronger dark background and shadow. Existing feature-local panels may differ, but new variants require a semantic reason rather than a new radius because it looks better in isolation.

Borders should normally use `--theme-border`. Stronger colored borders communicate state or domain meaning. Shadows/elevation should be sparse. Ordinary cards do not need unique shadows. Reserve strong shadows for overlays, active dice/effects, selected states, or another clear depth/state cue.

## Icons

Icons support recognition; they do not replace labels for unfamiliar or high-consequence actions.

- Keep icons visually subordinate to the action or navigation label.
- Reuse the size of neighboring icons in the same surface rather than inventing a local size.
- Use compact icons for inline metadata/status, medium icons for ordinary controls/navigation, and large decorative icons only for intentional empty/loading/hero states.
- Icon-only interactive controls require an accessible name and a sufficiently large hit target.

Do not mix unrelated icon families or visual weights in the same control group without a product reason.

## Component vocabulary

The repository does not yet have a complete primitive library. That is not permission to invent a new visual treatment at every call site. Think in these semantic primitives even where the current implementation is local markup.

### Actions and buttons

Use one of these roles:

- **Primary:** the next affirmative workflow action. One dominant primary action per local decision area is the default.
- **Secondary:** ordinary supporting action with lower visual emphasis.
- **Destructive/cancel:** uses danger semantics when the consequence warrants it. A benign Back/Close action does not need danger styling merely because it exits something.
- **Icon action:** compact utility action whose icon is recognizable and accessible.

Buttons in the same group should share height, radius, typography, and interaction behavior unless hierarchy intentionally differs. Avoid new one-off button treatments for feature branding.

### Form controls

Inputs, selects, textareas, sliders, and toggles should share the surrounding surface vocabulary and expose visible focus using `--theme-focus-ring`. On mobile, controls must remain inside their container and retain at least the iOS no-zoom text size where editable text is involved.

Validation/error state should add semantic feedback without changing layout unpredictably.

### Cards and panels

A card groups related information. A panel may organize a larger workflow region. Neither should be added merely to put a rounded rectangle around every cluster.

Default properties are semantic panel background, semantic border, an established radius, and content-sized height. Do not stretch cards to equal heights unless the contents genuinely benefit from comparison.

Comic, continuity, and personal-context regions may use their corresponding semantic accent to create domain identity without changing the entire component grammar.

### Badges, chips, and status indicators

Badges and chips are compact state/category markers. Keep them short, content-sized, and visually quieter than primary controls. Color must carry a semantic state or domain role, not merely make a row more colorful.

### Page shell and headers

Pages live inside the shared application shell. Prefer consistent gutters and a bounded readable content region over per-page edge offsets. Headings and nearby actions should wrap/reflow as a unit instead of escaping the viewport.

The fixed navigation and safe-area padding are shell responsibilities. Feature pages should not independently guess navigation heights.

### Modal/dialog surfaces

Use the shared `Modal` behavior for modal interactions unless a distinct interaction model is required. Its current behavior establishes the contract: portal layering, focus trapping/restoration, Escape/backdrop ownership for the topmost dialog, root scroll locking, mobile bottom-sheet presentation, desktop centered presentation, safe-area accommodation, and viewport-bounded scrolling.

Dialogs must fit within the dynamic viewport. Their chrome remains reachable while the dialog body scrolls. Do not solve overflow by allowing buttons or titles to disappear beyond the viewport.

### Loading, empty, and error states

- **Loading:** preserve enough geometry to avoid disruptive jumps, but do not manufacture a full empty card when the eventual region may not exist.
- **Empty:** say what is absent and, when useful, what the user can do next. If a section has no meaningful content and no action, omitting it is often preferable to rendering an empty decorative box.
- **Error:** distinguish a failed load/action from a legitimate empty state and provide a recovery action when one exists.

## Responsive behavior

Responsive rules describe behavior, not screenshots.

### Viewport ranges

Tailwind's existing breakpoints are the default guardrails. Do not add a new breakpoint for a single feature unless the layout has a demonstrated behavioral transition that the existing breakpoints cannot express.

### Mobile and narrow layouts

Narrow layouts may stack vertically and scroll naturally. Maintain readable order, touch targets, safe-area spacing, and horizontal containment. Horizontal scrolling is not an acceptable fallback for ordinary application content.

### Desktop and wide layouts

Desktop should use available width and height as a dashboard canvas when the task benefits from simultaneous context. Pack independent regions rather than reserving blank grid coordinates. For workflows such as Roll, primary information and actions should remain above the fold whenever their actual combined content reasonably fits.

Desktop is not automatically a vertically stretched mobile page. Conversely, do not shrink text or controls below comfortable sizes just to force genuinely dense content into one viewport.

### Grids and cards

Use Grid/Flexbox as layout algorithms. Prefer content-aware packing, `minmax`, `auto-fit`/`auto-fill`, wrapping, and `min-w-0` containment over fixed semantic row/column coordinates that create holes when optional content disappears.

Cards should remain content-sized unless equal sizing has a comparison/product purpose.

### Fixed and sticky chrome

Fixed/sticky elements must not cover reachable content. The shared shell owns ordinary bottom-navigation clearance. Any new fixed element must account for safe areas, keyboard/focus reachability, and content clearance at every viewport where it appears.

### Scrolling

Scrolling is correct when information density genuinely exceeds available space, particularly on mobile. Scrolling is a defect signal when controls are below the fold because of blank grid tracks, oversized decorative media, unnecessary fixed heights, or other manufactured whitespace.

## Motion

Motion should explain state or reinforce an intentional playful interaction, such as the dice. Ordinary navigation and CRUD interactions should not accumulate decorative animation. Respect `prefers-reduced-motion`; new nonessential animations require a reduced-motion behavior.

## Accessibility is part of the visual grammar

Visible focus, sufficient contrast, readable type, semantic control labels, touch target size, and viewport reachability are design requirements, not separate polish. Color should not be the sole carrier of status where the distinction matters.

## Variation rule

**Do not introduce a new font size, spacing value, radius, color role, button treatment, card treatment, breakpoint, shadow, or layout convention merely for local convenience.** Reuse this grammar when an existing semantic role can express the product meaning.

A genuinely new visual role is allowed when all of the following are true:

1. the existing vocabulary cannot express a distinct product meaning or interaction requirement;
2. the variation is expected to recur or is important enough to name explicitly;
3. it works across themes and supported viewport classes;
4. accessibility and interaction behavior are defined with it;
5. the new role is documented here, or a focused architecture issue explicitly owns that update.

A one-off value that cannot meet those conditions should usually be redesigned using an existing role rather than promoted into a token.

## Audit and review workflow

Use the repository audits as evidence, not as an automatic style judge:

```bash
cd frontend && pnpm run audit:style
```

The static audit inventories arbitrary Tailwind values, palette use, raw controls, inline styles, CSS vocabularies, and high-concentration files. A finding is a review prompt, not proof of a bug.

The rendered UI audit owned by #2043/#2070 provides geometry/screenshots across representative states and viewport classes. Rendered evidence outranks class-string aesthetics when the requirement is reachability, overflow, containment, or responsive packing.

When changing frontend visuals, ask in review:

- Does an existing semantic token express this meaning?
- Is this spacing/type/radius treatment already a named role, or am I creating a new local dialect?
- Does optional content disappear cleanly without leaving geometry behind?
- Does the layout reflow rather than overlap or horizontally escape?
- Are important actions reachable at the supported viewport sizes?
- Does the change work in all themes and with keyboard/focus behavior?

## Migration policy

This document does not declare all current variation wrong and does not authorize a mass cleanup. Existing drift should be addressed incrementally through focused issues, preferably when a feature is already being changed or when audit evidence identifies a user-visible/systemic problem.

Do not replace Tailwind, introduce a component framework, or perform repository-wide class rewrites solely to conform old code to this document. Shared primitives should be introduced when repeated behavior and presentation make the abstraction pay for itself.
