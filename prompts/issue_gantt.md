# Issue Implementation Gantt Chart

## Overview
This Gantt chart visualizes the implementation timeline for issues #483-#494 on JoshCLWren/comic-pile. Issues are grouped into waves based on complexity and dependencies.

## Wave Definitions

- **Wave 1 (1-2 days each)**: Quick CSS/config changes, fully independent
- **Wave 2 (2-3 days each)**: Moderate complexity, some UI/UX work
- **Wave 3 (3-5 days each)**: Complex UI with multiple features
- **Wave 4 (5+ days)**: Requires backend data model changes

```mermaid
gantt
    title Comic Pile Issue Implementation Timeline
    dateFormat  YYYY-MM-DD
    
    section Wave 1 (CSS/Config)
    #494 Text Input Borders     :w1a, 2026-04-21, 1d
    #484 Modal Transparency      :w1b, 2026-04-21, 1d
    #485 Bug Button Mobile       :w1c, 2026-04-22, 1d
    #488 Feature-Flag Reviews    :w1d, 2026-04-22, 1d
    #486 Feature-Flag Collections:w1e, 2026-04-23, 1d
    
    section Wave 2 (UI/UX Fixes)
    #493 Bug Button Navigation   :w2a, 2026-04-21, 2d
    #491 Shuffle Queue           :w2b, 2026-04-23, 2d
    #483 Issue Correction Dialog :w2c, 2026-04-25, 3d
    
    section Wave 3 (Complex Features)
    #487 Theme Selector          :w3a, 2026-04-24, 3d
    #490 Queue Page UX           :w3b, 2026-04-25, 4d
    #492 Larger Dice Support     :w3c, 2026-04-27, 5d
    
    section Wave 4 (Backend Required)
    #489 Reading Orders          :w4a, 2026-04-28, 7d
```

## Wave Details

### Wave 1: Quick Wins (April 21-23)
| Issue | Title | Est. Time | Dependencies |
|-------|-------|-----------|--------------|
| #494 | Text Input Borders | 1 day | None |
| #484 | Modal Transparency | 1 day | None |
| #485 | Bug Button Mobile | 1 day | None |
| #488 | Feature-Flag Reviews | 1 day | None |
| #486 | Feature-Flag Collections | 1 day | None |

### Wave 2: UI/UX Fixes (April 21-27)
| Issue | Title | Est. Time | Dependencies |
|-------|-------|-----------|--------------|
| #493 | Bug Button Navigation | 2 days | None |
| #491 | Shuffle Queue | 2 days | Backend endpoint needed |
| #483 | Issue Correction Dialog | 3 days | None |

### Wave 3: Complex Features (April 24-May 1)
| Issue | Title | Est. Time | Dependencies |
|-------|-------|-----------|--------------|
| #487 | Theme Selector | 3 days | None |
| #490 | Queue Page UX | 4 days | None |
| #492 | Larger Dice | 5 days | 3D geometry for new dice |

### Wave 4: Backend Required (April 28-May 5)
| Issue | Title | Est. Time | Dependencies |
|-------|-------|-----------|--------------|
| #489 | Reading Orders | 7 days | New DB tables, API endpoints |

## Notes

- Wave 1 can run entirely in parallel - no shared files
- Wave 2 issues can overlap; #491 requires backend work first
- Wave 3 should start after Wave 1 to avoid CSS conflicts
- Wave 4 is the largest effort; consider starting backend early
- Total estimated timeline: ~10-12 working days with parallelization
