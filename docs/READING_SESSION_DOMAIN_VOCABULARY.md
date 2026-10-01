# Reading session domain vocabulary

ComicPile uses the word **session** for two unrelated things:

1. **Reading history** — the durable `ReadingSession` record (the `sessions` table) plus its
   `Event` and `Snapshot` children. This is product reading state.
2. **Authentication state** — password credentials, `password_changed_at`, and `revoked_token`.

The collision is not cosmetic. The password-reset incident fixed in #2996 happened because auth
recovery called a helper whose name read like "revoke this user's logins" while it actually
deleted reading history. Issue #2998 removes the foot gun by making the reading domain explicit
in code.

## Current domain vocabulary

| Concept | Canonical name | Location |
|---|---|---|
| Durable reading record | `ReadingSession` | `app/models/reading_session.py` |
| Reading persistence | reading-session repository helpers | `app/repositories/reading_session_repository.py` |
| Reading API router | `reading_session.router` | `app/api/reading_session.py` |
| Reading Pydantic schemas | `app/schemas/reading_session.py` | `app/schemas/reading_session.py` |
| Reading services | `app/services/reading_session_*.py` | services |
| Reading domain logic | `comic_pile/reading_session.py` | `comic_pile/__init__.py` re-exports |

`app.models` exports `ReadingSession`. It deliberately does **not** export a bare `Session`, and
`app/repositories/reading_session_repository.py` deliberately exposes **no** bulk-delete helper.
`tests/test_reading_session_auth_boundary.py` enforces both as static guards.

## Intentionally retained ambiguous-looking uses

These are the storage, deployment, and public-API edges. Each is deliberate: renaming it would
break durable data, deployed configuration, or published clients without reducing any ambiguity
inside application code.

### Storage edge (durable data)

- **Table name `sessions`** — `ReadingSession.__tablename__` stays `sessions`. Renaming the table
  would require a data migration with no safety benefit; the class name carries the domain.
- **`Event.session_id` and `Snapshot.session_id`** — foreign-key column names stay as-is for the
  same reason.
- **`Snapshot.description == "Session start"`** — persisted string data. It is referenced through
  `app.constants.READING_SESSION_START_SNAPSHOT_DESCRIPTION` so writer and reader cannot drift.
  Never rename this value alongside code symbols.

### Public API edge (published contract)

- **HTTP paths `/api/sessions/*` and `/api/v1/sessions/*`** — unchanged. Renaming the paths would
  break every deployed client for a purely internal clarity gain.
- **OpenAPI component names** (`SessionResponse`, `SessionListItem`, `SessionDetailsResponse`,
  `SessionHistoryListResponse`, `SessionMode*`) — these are generated into
  `frontend/src/generated/openapi.ts` and consumed by `frontend/src/services/apiTypes.ts`.
  Renaming them requires a coordinated schema regeneration and frontend type migration.

### Deployment configuration edge

- **`SESSION_GAP_HOURS` env var and `app.config.SessionSettings`** — the class docstring already
  states it is reading-session configuration. Environment variable names are an operator-facing
  contract and are not renamed for internal clarity.

### Test naming

- **`tests/test_session_*.py` file names** — retained. Test module names describe the API surface
  under test, and the production modules they cover are already unambiguously named. Their
  assertions and helpers use `ReadingSession`.

## Rules for future work

- New reading-domain symbols must carry the `reading_session` / `ReadingSession` qualifier.
- Auth code must not import anything from `app/repositories/reading_session_repository.py` unless
  the interaction is documented in the PR that introduces it.
- Never reintroduce a bulk-delete helper on the reading-session repository. Individual row
  mutations belong to the service that owns the business rule.
- When a new domain noun collides with a common English or infrastructure word, qualify it at the
  boundary (model, repository, and helper names) rather than relying on reviewer vigilance.