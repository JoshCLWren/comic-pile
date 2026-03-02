# TypeScript Strictness Roadmap

## Current State

- Frontend TypeScript migration is complete (`.js/.jsx` migrated to `.ts/.tsx`).
- CI enforces frontend lint + app typecheck (`tsc --noEmit -p frontend/tsconfig.json`).
- `frontend/tsconfig.json` is intentionally still `strict: false`.

## Why Strict Mode Is Deferred

Enabling `strict: true` (or `noImplicitAny` + `strictNullChecks`) currently produces a large volume of errors across legacy modules and test-only code, especially:

- `frontend/src/components/Dice3D.tsx`
- `frontend/src/devtools/*`
- older hook/page utility paths with implicit `unknown`/nullable values

Turning strict mode on immediately would block CI and merge velocity for unrelated work.

## Enforcement Plan

1. Keep CI gate on `npm -C frontend run typecheck` for app code.
2. Burn down strictness blockers in prioritized slices:
   - `Dice3D` and geometry/render config typing
   - hook nullability + API error normalization
   - devtools component prop typing
3. Enable in stages:
   - `strictNullChecks: true`
   - `noImplicitAny: true`
   - then `strict: true`
4. Re-enable and stabilize `typecheck:test` in CI after test utility typing is cleaned up.

## Exit Criteria

- `npm -C frontend run typecheck` passes with `strict: true`.
- `npm -C frontend run typecheck:test` passes and is enforced in CI.
