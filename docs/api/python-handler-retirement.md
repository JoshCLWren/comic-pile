# Retired shadowed Python handlers

> **Status: completed historical deletion record.** No Python application handlers
> remain. Current runtime/route authority is the native router, generated contracts,
> and [route inventory](../api/v2-route-inventory.json).
<!-- docs-path-check: historical -->

The owner requested removal of the unused Python implementations, their obsolete
tests, and confirmed test-only code in one PR. The public API operations remain
implemented by the existing Rust router; this cleanup does not retire their URLs.

`tests/fixtures/retired-python-handlers.json` records the 78 retired method/path
registrations (65 handler functions, with shared aliases). The retirement guard
proved those handlers absent when the Python application was deleted. The
frontend proxy regression resolves every manifest operation to native ingress
against the route fragments, and the Rust-generated same-path contract test
checks that each retained operation remains documented.

## Contracts and local requests

`native/contracts/same-path-runtime.openapi.json` supplies the contracts formerly
obtained by importing the retired Python handlers. It is generated from the Rust
DTO documentation, alongside the existing canonical v2 contract, and merged by
`scripts/export_openapi_schema.mjs`. Alias operation IDs are unique; canonical v2
IDs stay stable. See `native/contracts/README.md` for regeneration.

Vite derives local native forwarding from the checked-in Vercel rules and route
fragments, including method-specific compatibility operations. There is no
Python forwarding target; `GET /api/v2/reading-boundaries/{thread_id}` resolves to
native Rust like the other retired registrations.

The bot-owned route inventory contains historical shadowed-handler entries;
those entries do not imply Python implementations still exist. Use the
retirement manifest, native router, generated contracts, and route inventory to
identify the retained operations. Bot-owned ingress artifacts remain under the
post-merge regeneration workflow.

## Scope of deletion

The cleanup removed superseded router code and exclusive identity-inbox,
preferences, catalog-commit, creator-list, bug-report, and password-reset Python
implementation dependencies. It also removed the unused queue service and
repository, read-frontier service, session response builder, momentum selection
wrapper, and ComicVine scheduling wrapper.

At deletion time, shared authentication, catalog hydration, session projection,
tag, creator and dependency helpers were retained only where still-needed code
used them. No Python endpoint or application runtime remains; current behavior
lives in native Rust and the generated same-path contract.

Tests dedicated to deleted Python execution paths were removed. Native runtime,
contract, migration, ownership, and repository-tooling tests remain.
