# Roll command-center visual reference (HISTORICAL)

> **This document describes the superseded three-pillar design.** The authoritative
> desktop visual reference is now the **2026-09-20 two-region Roll redesign** implemented
> across issues `#2762`, `#2768`, `#2763`, `#2764`, `#2712`, and `#2767`, with final
> integration in `#2765`.

The image below shows the **retired three-pillar cockpit** that was the approved
north star before the 2026-09-20 redesign. It is retained only for historical
provenance and must not be used as an implementation reference.

<img src="./roll-command-center-reference.jpg" alt="ComicPile Roll command-center desktop reference showing the retired three-pillar design: The Comic, Reading Context, and Your Context" width="1200" />

## What this historical reference locked (superseded)

- Three top-aligned console pillars: **01 The Comic**, **02 Reading Context**, **03 Your Context**.
- The Comic was cover-led and editorial.
- Reading Context was the widest pillar and made the local reading chain a major visual element.
- Your Context made the current rating, die consequence, personal analytics, and completion actions dominant.
- The visual language used near-black/ink with semantic amber, cyan/teal, and violet accents.
- `Mark Read & Save` was the decisive action; Snooze and Cancel were intentionally paired secondary actions.
- The desktop composition was a cockpit, not a loose generic card grid.

## Current authoritative design (2026-09-20 two-region redesign)

The integrated Roll screen now uses a **two-region composition** (Comic / Decision)
with optional Reading Context and Reading Boundaries cards collapsed beneath the
Decision region. The legacy three-pillar layout has been removed.

### Desktop hierarchy (1920×926 reference)

```
ROLL                                      BACK TO QUEUE
A RANDOM COMIC FROM YOUR LIBRARY
──────────── gold rule across comic side only ───────────

┌──────────────────── comic region, ~55% ────────────────────┐  ┌─ decision, ~45% ─┐
│ cover rail │ ComicVine eyebrow / title / progress          │  │ rating            │
│            │ compact identity + correction controls        │  │ slider            │
│            │ story title / date                            │  │ save/actions      │
│            │ summary                                       │  └───────────────────┘
│            │ creators                                      │  ┌─ context ─────────┐
│ cover utils│ secondary metadata below as needed            │  └───────────────────┘
└─────────────────────────────────────────────────────────────┘  ┌─ boundaries ──────┐
                                                                 └───────────────────┘
```

### Key differences from the retired design

| Retired three-pillar | Current two-region |
|---------------------|-------------------|
| Three equal peer columns | Asymmetric ~55/45 Comic/Decision split |
| Reading Context as widest middle pillar | Reading Context / Boundaries as compact optional cards under Decision |
| `Why this?` disclosure in middle | No `Why this?` surface; optional cards are user-invoked |
| The Comic heading visible | No visible `The Comic` heading |
| Selected issue boxed card | No `Selected issue` card; identity lives in Comic region header |
| Series/issue identity duplicated | Identity rendered once in Comic region |

### Component/Issue mapping

- **Comic region structure**: `#2762` (cover/details shell), `#2768` (rich metadata: summary, creators, story arcs, cover utilities)
- **Decision region**: `#2763` (DecisionCard visual conformance)
- **Optional cards (Context/Boundaries)**: `#2764` (collapsed cards + lazy loading), `#2767` (request plumbing)
- **Outer workspace geometry & page chrome**: `#2712` (header, 55/45 split, footer, responsive reflow)
- **Final integration & acceptance**: `#2765`

### Responsive behavior (authoritative)

- **390×844 phone**: One continuous column. Task order: Comic → Decision → Reading Context → Reading Boundaries. Sticky completion slab.
- **800×1094 tablet portrait**: Intentional stack/reflow after navigation width. No forced two-column crush.
- **1280×800 small desktop/landscape**: Two columns when post-navigation width supports both. Decision remains scannable.
- **1440×900 normal desktop**: Intentional asymmetric two-column. Cover/details split useful.
- **1920×926 reference desktop**: Near-55/45 balance. No empty center canyon. No giant parent glass-card frame.

### Cover modal and ComicVine link

- `View larger` uses the already-loaded cover via the shared `Modal` primitive (no provider request).
- `Open in ComicVine` uses the existing `comicvine_url` field from ComicVine intelligence.

### Legacy elements removed

- Visible `THE COMIC` pillar heading
- Boxed `Selected issue` card
- Series/issue identity duplication between legacy card and ComicVine metadata
- `Why this?` disclosure
- Three-pillar grid reservation (no middle-column blank canyon)

### References

- Final integration acceptance: issue `#2765`
- Visual grammar: `docs/FRONTEND_VISUAL_GRAMMAR.md`
- Workspace layout constants: `frontend/src/pages/RollPage/workspaceLayout.ts`
- Component boundaries: `RatingView`, `ComicPillar`, `ComicIdentity`, `DecisionCard`, `OptionalReadingCards`

---

*The retired three-pillar image remains in this directory for audit trail purposes only.*