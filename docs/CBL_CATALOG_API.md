# Shared CBL catalog API

Authenticated readers browse the same persisted source catalog, including readers
with no comics. These native Rust reads do not reconcile owned Issues, create
Reading Lists or fetch GitHub.

## Endpoints

- `GET /api/v1/issue-identity/cbl-sources/folders?folder=DC` returns immediate
  child folders, breadcrumbs and direct/recursive active-list counts. Omit
  `folder` for the root.
- `GET /api/v1/issue-identity/cbl-sources/browse?folder=DC&page=1&page_size=50`
  returns folders and a page of source lists.
- Add `q` to search names and source-relative paths. `%` and `_` are literal; a
  nonempty query ignores folder scope.
- `GET /api/v1/issue-identity/cbl-sources/{list_id}` returns bounded source-list
  detail and occurrences.

Pages are one-based with at most 100 items. `total`, `total_pages`, `has_next` and
`has_previous` describe the match. Out-of-range pages clamp to the true last page
rather than issuing an unbounded offset. Empty root/search results are successful
empty responses.

Folder paths preserve spaces and forward slashes. Empty/traversal segments,
backslashes and control characters are rejected. Ordering is stable by name,
source path and source-list ID.

## Errors

- Missing folder: 404 with `detail.code = folder_not_found`.
- Malformed folder: 400 with `detail.code = invalid_folder`.
- Invalid pagination: FastAPI-compatible 422 `detail` array.
- Catalog query failure: 503 with `detail.code = cbl_catalog_unavailable`.
- Dependency-acquisition outage: 503 `error.code = database_unavailable` with
  `Retry-After`.

The generated same-path contract carries the exact schemas.

## Data and validation

The baseline schema installs `pg_trgm` and the catalog's current indexes. Catalog
reads never trigger source ingestion; an empty catalog stays empty until an
approved ingestion workflow populates it.

Focused native HTTP coverage lives in
`native/roll-service/tests/cbl_catalog.rs` and uses a disposable PostgreSQL
database. It covers empty accounts, nested folders, literal wildcard search,
inactive sources, validation, route precedence and extreme pagination.
