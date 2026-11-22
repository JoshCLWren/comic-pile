# Retired shadowed Python handlers

The owner requested removal of the unused Python implementations, their obsolete
tests, and confirmed test-only code in one PR. The public API operations remain
implemented by the existing Rust router; this cleanup does not retire their URLs.

`tests/fixtures/retired-python-handlers.json` records the 78 retired method/path
registrations (65 handler functions, with shared aliases). The Python retirement
guard proves they are absent from FastAPI. The frontend proxy regression checks
that each operation still resolves to native ingress, and the Rust-generated
same-path contract test checks that each operation remains documented.

## Contracts and local requests

`native/contracts/same-path-runtime.openapi.json` supplies the contracts formerly
obtained by importing the retired Python handlers. It is generated from the Rust
DTO documentation, alongside the existing canonical v2 contract, and merged by
`scripts/export_openapi_schema.mjs`. Alias operation IDs are unique; canonical v2
IDs stay stable. See `native/contracts/README.md` for regeneration.

Vite derives its local Rust/Python forwarding from the checked-in Vercel rules,
including method-specific exceptions. It no longer assumes every non-v2 request
belongs to Python. The Python `GET /api/v2/reading-boundaries/{thread_id}` exception
is preserved.

The bot-owned route inventory contains the historical shadowed-handler entries;
those entries do not imply the Python implementations still exist. Use the
retirement manifest and current FastAPI route table to identify removed code.
Bot-owned ingress artifacts remain under the post-merge regeneration workflow.

## Scope of deletion

The cleanup removes superseded router code and exclusive identity-inbox,
preferences, catalog-commit, creator-list, bug-report, and password-reset Python
implementation dependencies. It also removes the unused queue service and
repository, read-frontier service, session response builder, momentum selection
wrapper, and ComicVine scheduling wrapper.

Shared authentication, catalog hydration, session projection, tag, creator and
dependency helpers remain wherever retained Python operations or maintenance
scripts use them. ORM models and migrations for tables still used by Rust remain.

Tests dedicated to deleted Python execution paths are removed. Tests for retained
Python endpoints use direct fixture setup rather than deleted auth/CRUD handlers;
shared service, ownership, middleware, migration, and native-runtime tests remain.
