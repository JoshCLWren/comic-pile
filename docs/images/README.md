# Documentation images

## `roll-hero.png`

The README hero is a historical capture of the Comic Pile Roll page from
2026-10-23. Its source was a deterministic pre-cutover demo library containing
Superman, Batman, Wonder Woman, The Flash, and Aquaman; no production library,
personal collection, or real cover art was photographed. The committed PNG is
2880×2000 and remains under the README image budget.

## Current capture boundary

The old `make setup` / `make seed-dev` demo-data workflow and
`scripts/seed_dev_db.py` were retired with the Python application. The current
native service runs on `:8010`, not `:8000`, and a clean checkout has no seed
command. Do not follow the historical capture instructions below as current
setup guidance.

`frontend/scripts/capture-readme-roll-hero.mjs` remains as a local helper, but its
seeded-demo login and five-title safety preconditions are not provisioned by the
current setup. Replacing the hero therefore requires an explicitly prepared
loopback-only demo fixture and updated provenance. Never point capture tooling
at production or a shared reader account.
