# Documentation images

## `roll-hero.png`

The README hero: a screenshot of the Comic Pile **Roll** page.

- **Source data:** the deterministic local demo library created by `make setup`
  (`scripts/seed_dev_db.py`): the `testuser` account with the Superman, Batman, Wonder Woman,
  The Flash, and Aquaman series. No production library, personal collection, or real cover art
  was photographed.
- **Capture date:** 2026-10-23.
- **Capture environment:** local checkout, API on `http://127.0.0.1:8000` and Vite on
  `http://127.0.0.1:5173`, Chromium at a 1440×1000 viewport with a device scale factor of 2
  (the committed PNG is 2880×2000), 923,305 bytes.
- **Committed size:** well under the ~2 MiB README budget.

### Reproducing the capture

```bash
make setup          # creates and seeds the local demo library
make dev            # API on :8000, Vite on :5173
cd frontend && pnpm run capture:readme-roll
```

`frontend/scripts/capture-readme-roll-hero.mjs` writes `docs/images/roll-hero.png` and refuses to
capture unless both safety conditions hold:

1. the target host is a loopback address (`127.0.0.1`, `localhost`, or `::1`), so the script can
   never photograph a remote or production account;
2. the Roll pool contains only the seeded demo series, so the script can never publish a real
   library.

Set `CHROMIUM_EXECUTABLE` when Playwright's managed browser is unavailable, and `ROLL_HERO_OUT`,
`ROLL_HERO_BASE_URL`, `ROLL_HERO_USERNAME`, or `ROLL_HERO_PASSWORD` to override the defaults.
The script fails when the resulting PNG exceeds 2 MiB.
