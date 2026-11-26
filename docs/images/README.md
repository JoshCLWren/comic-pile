# Documentation images

## `roll-hero.png`

The README hero is a historical capture of the Comic Pile Roll page from
2026-10-23. Its source was a deterministic pre-cutover demo library containing
Superman, Batman, Wonder Woman, The Flash, and Aquaman; no production library,
personal collection, or real cover art was photographed. The committed PNG is
2880×2000 and remains under the README image budget.

## Current capture boundary

The former demo-seed workflow (`make seed-dev` and its Python seed script) was
retired with the Python application. The current native service runs on `:8010`,
not `:8000`, and a clean checkout has no seed command. Do not follow the historical capture instructions below as current
setup guidance.

`frontend/scripts/capture-readme-roll-hero.mjs` remains as a local helper, but its
seeded-demo login and five-title safety preconditions are not provisioned by the
current setup. Replacing the hero therefore requires an explicitly prepared
loopback-only demo fixture and updated provenance. Never point capture tooling
at production or a shared reader account.

## `social-preview.png`

The 1280×640 repository social preview delivered for #3887 is rendered from
`social-preview.html` in this directory. It uses the actual Comic Pile logo mark
copied verbatim from `static/favicon.svg` (teal rounded die with five white pips)
and the committed `roll-hero.png` capture on the right. That capture comes only
from the seeded/demo library (Superman, Batman, The Flash and Aquaman in play);
no personal reading library, QA account, or invented logo is depicted.

Regenerate the PNG deterministically from the checked-out sources:

```bash
chromium --headless --no-sandbox --disable-gpu --hide-scrollbars \
  --allow-file-access-from-files --force-device-scale-factor=1 \
  --window-size=1280,640 \
  --screenshot=docs/images/social-preview.png \
  file://$PWD/docs/images/social-preview.html
```

The committed PNG must stay exactly 1280×640 and under 2 MiB;
`tests/test_social_preview_asset.py` guards those properties and the use of only
the verified repository assets.

**Owner action still required.** This is a repository-admin setting, so a factory
worker cannot apply it. The repository owner must upload `social-preview.png`
under **Settings → General → Social preview**, then verify that GitHub renders
it at 1280×640. Do not change repository topics or the description as part of
this work.

**Live state observed 2026-11-26 (read-only).** The repository API reported
`has_discussions: true`, so Discussions appears enabled. The repository page's
`og:image` still resolved to a 1920×1080 *Creator Comparison* capture signed in
as "Josh", with personal-library counts and unread-issue lists. That image
neither has the approved 1280×640 dimensions nor satisfies the demo-data-only
rule, so the upload and GitHub display verification remain owner actions. The
repository description and topics were not modified by this work.
