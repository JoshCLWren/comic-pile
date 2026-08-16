# Queue card clipping regression harness (#1295 / #625)

This directory backs the TestDriver regression test
[`../testdriver/queue-card-clipping.test.mjs`](../testdriver/queue-card-clipping.test.mjs).

## What it covers

Issue **#1295** ("E2E: keeps mobile cards clipped while exposing actions through
the shared overlay") reported this Playwright failure in
`frontend/src/test/queue-interaction-containment.spec.ts`:

```
Expected: "hidden"
Received: "visible"
Timeout 10000ms exceeded while waiting on the predicate
```

That assertion checks the queue thread card clips its own content:

```ts
await expect
  .poll(() => firstCard.evaluate((el) => getComputedStyle(el).overflow))
  .toBe('hidden');
```

### Root cause (product bug)

The card element in `frontend/src/pages/QueuePage/QueueThreadCard.tsx` carries
the classes `queue-thread-card glass-card …`, but **no CSS rule sets `overflow`
on it**:

- `.glass-card` in `frontend/src/styles.css` sets background/border/radius only.
- There is no `.queue-thread-card` rule at all, and the card's `className` has no
  `overflow-hidden` Tailwind utility.

So the card computes `overflow: visible` and the E2E assertion times out. (The
shared overlay portal that lets the actions menu escape the card already works —
that part of the spec passes.)

### Fix (product code — belongs to the app, applied by a maintainer)

Give the card `overflow: hidden`, e.g. add to `frontend/src/styles.css`:

```css
.queue-thread-card { overflow: hidden; }
```

…or add the `overflow-hidden` utility to the card element's `className` in
`QueueThreadCard.tsx`.

## The harness

`queue-card-clipping.inline.html` is a single, dependency-free page that renders
the exact card DOM from `QueueThreadCard.tsx` with the subset of real app styles
that apply to the card (`.glass-card` + the Tailwind utilities it uses) — none of
which set `overflow`, exactly like the shipped app. An oversized striped
"OVERFLOW PROBE" banner makes clipping visible to the eye, and a readout prints
`getComputedStyle(card).overflow`. A button toggles the fix
(`.queue-thread-card { overflow: hidden }`).

The TestDriver test ships this file into the sandbox, serves it on localhost, and
drives a real Chrome to assert the card goes from `overflow: visible` (probe
spilling out — the bug) to `overflow: hidden` (probe clipped — the corrected
behavior). It needs no backend, auth, or public tunnel.

Run it:

```bash
npx vitest run testdriver/queue-card-clipping.test.mjs
```
