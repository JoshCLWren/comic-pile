# Deprecated Issue Kanban Snapshot

> This file is no longer a live board. GitHub Issues, labels, issue links, and
> `make next-task` are now authoritative. Do not update this file for status
> changes. It remains temporarily as historical context while issue workflow
> migration is completed in [#644](https://github.com/JoshCLWren/comic-pile/issues/644).

This board is the repo-level view of the active GitHub backlog. GitHub issues remain the source of truth for discussion, implementation plans, and completion. Update this file when an issue changes column, priority, or dependency. Agents must follow [ISSUE_EXECUTION_PROTOCOL.md](ISSUE_EXECUTION_PROTOCOL.md).

Last reviewed: 2026-07-17 (planning complete for #603, #609, and #613)

## Priority

| Priority | Meaning |
| --- | --- |
| Critical | Blocks a primary workflow or combines multiple reports. Do next. |
| High | Significant user-facing breakage or performance problem. Do before enhancements. |
| Medium | Important polish or clarity issue with a contained scope. |
| Low | Product decision or enhancement that should wait for foundational work. |

## Board

### Planning required

These issues require a concrete local implementation plan before DeepSeek starts coding. The plan files below are authoritative; GitHub comments contain only compact pointers for discoverability.

| Issue | Planner deliverable | Planning exit criteria | Next column |
| --- | --- | --- | --- |

### Ready / next up

| Issue | Priority | Work | Depends on | Done when |
| --- | --- | --- | --- | --- |
| [#602](https://github.com/JoshCLWren/comic-pile/issues/602) | High | Prevent mobile viewport overflow and input zoom. | None | Forms remain usable at 320px, 375px, and 414px widths. |

### Planned

| Issue | Priority | Work | Depends on | Done when |
| --- | --- | --- | --- | --- |
| [#599](https://github.com/JoshCLWren/comic-pile/issues/599) | High | Keep Save and Continue clear of rating and bug-report controls. | None | Rating controls and actions remain visible and tappable on mobile. |
| [#608](https://github.com/JoshCLWren/comic-pile/issues/608) | High | Load session history incrementally. | Existing backend cursor pagination | Initial load fetches one page; users can reach older sessions without duplicates. |
| [#614](https://github.com/JoshCLWren/comic-pile/issues/614) | Medium | Fit the bug-report modal on narrow iOS viewports. | #602 modal/viewport work may provide shared fixes | Modal fits a 320px viewport with no horizontal overflow. |
| [#609](https://github.com/JoshCLWren/comic-pile/issues/609) · [plan](issue-plans/609.md) | Medium | Make session events complete, coherent, and labeled. | #608 is related but not strictly blocking | Events show thread, issue/read count, die/roll, rating, timestamp, status, and snapshot context. |

### Queued enhancements / decisions

| Issue | Priority | Work | Depends on | Done when |
| --- | --- | --- | --- | --- |
| [#613](https://github.com/JoshCLWren/comic-pile/issues/613) · [plan](issue-plans/613.md) | Low | Add named groups for connected reading-order dependencies. | #603 | Users can create and assign named groups; roll view displays group names. |
| [#611](https://github.com/JoshCLWren/comic-pile/issues/611) | Low | Decide whether to redesign or retire Analytics. | Product decision | Decision is documented and navigation/page behavior matches it. |

### In progress

_None recorded._

### Validation

| Issue | Priority | Work | Depends on | Done when |
| --- | --- | --- | --- | --- |
| [#603](https://github.com/JoshCLWren/comic-pile/issues/603) · [plan](issue-plans/603.md) | Critical | Make dependency management discoverable and usable on mobile and desktop. | None | Users can view, add, edit, and delete dependencies at 375px without clipped or overlapping controls. |
| [#615](https://github.com/JoshCLWren/comic-pile/issues/615) | High | Fix authenticated reading-orders requests returning 401. | None | Roll view loads reading-order data without 401 console errors; auth and refresh tests pass. |

### Done

_None recorded._

### Recently consolidated

| Issue | Result |
| --- | --- |
| #607 | Closed as duplicate of #603. |
| #612 | Closed as duplicate of #603. |
| #610 | Closed as duplicate of #609. |

## Dependency map

```text
#615 Reading-order authentication fix
  └── independent; removes noisy diagnostics from roll-view work

#603 Mobile dependency management
  └── #613 Named connected reading-order groups

#602 Mobile viewport and input behavior
  ├── informs #599 Rating action layout
  └── informs #614 Bug-report modal width

#608 History pagination
  └── related to, but does not block, #609 Session detail presentation

#609 Session details and snapshots
  └── combines former #610 snapshot-label work
```

## Working rules

- Keep one canonical issue for duplicate reports; link and close duplicates.
- Follow the sequence: Planning required → Ready/Planned/Queued → In progress → Validation → Done.
- A planning issue cannot move to implementation until its local plan file exists and is linked from this board. The GitHub issue receives a compact pointer to the local plan.
- A planning pass is required for #603, #609, and #613 only. Plans for all three have been posted to their GitHub issues; they may proceed through their execution columns when dependencies permit. The other active issues may go directly to DeepSeek execution.
- Do not move an issue to Validation until the required local tests pass.
- Frontend issues require lint, typecheck, build, unit tests, and relevant Playwright coverage.
- Backend changes require the relevant pytest coverage and the repository's async PostgreSQL rules.
- If implementation discovers a new dependency, add it to this board and the GitHub issue before continuing.
