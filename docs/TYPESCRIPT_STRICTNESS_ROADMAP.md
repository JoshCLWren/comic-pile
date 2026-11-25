# TypeScript Strictness Status

The frontend TypeScript migration is complete. `frontend/tsconfig.json` enables strict mode, and `pnpm --filter frontend run typecheck` checks both the app and test TypeScript configurations. CI enforces that command.

The earlier staged plan to defer `strictNullChecks`, `noImplicitAny`, and test typechecking is superseded. Remaining work is ordinary maintenance under the current strict gate, not a future activation phase.

See `frontend/package.json`, `frontend/tsconfig.json`, and `frontend/tsconfig.test.json` for the executable contract.
