# CBL Reverse Lookup by Exact Comic Vine Issue Identity

Issue #4011 implements the read-only half of the exact-Comic-Vine reverse search described in
[#1615](https://github.com/JoshCLWren/comic-pile/issues/1615). The endpoint answers one question
about the **shared** CBL catalog:

> Which CBLs in the fork contain this exact Comic Vine issue ID, and at which source positions?

The answer is catalog data. It is identical for every reader, including readers who own no comics
at all, and it never changes reader-owned rows.

## Endpoint

```http
GET /api/v1/issue-identity/cbl-sources/by-comicvine-issue/{comicvine_issue_id}?offset=0&limit=50
```

The route is authenticated (any signed-in reader) and read-only. `offset` is a zero-based index and
`limit` is capped at 200.

```json
{
  "comicvine_issue_id": "4000-issue-1",
  "occurrences_total": 3,
  "lists_total": 2,
  "occurrences_offset": 0,
  "occurrences_limit": 50,
  "occurrences": [
    {
      "list_id": 12,
      "list_name": "Alpha Reading",
      "source_path": "Marvel/Alpha.cbl",
      "source_repository": "JoshCLWren/CBL-ReadingLists",
      "source_ref": "JoshCLWren/CBL-ReadingLists:Marvel/Alpha.cbl",
      "revision_sha": "abc123",
      "position": 1,
      "series_name": "Mister Miracle",
      "issue_number": "1",
      "volume_year": 1985,
      "publication_year": 1985,
      "comicvine_issue_id": "4000-issue-1",
      "comicvine_volume_id": "2000-volume-1"
    }
  ]
}
```

- `occurrences_total` counts every matching source position in the catalog.
- `lists_total` counts the **distinct** source lists that contain the identity, so a source that
  holds the same issue twice does not inflate the list count.
- `occurrences_offset` / `occurrences_limit` echo the requested page. Totals always describe the
  whole match, not the page.

## Match rules

The match is exact on the provider identity, and only on the provider identity:

- the query joins `cbl_source_entries.external_issue_identity_id` to `external_identities` with
  `provider = 'comicvine'`, `entity_type = 'issue'`, and the requested `external_id`;
- a shared series title, a shared volume, or the same issue number in another volume never
  produces a false positive;
- the entry's series/volume identity is reported as `comicvine_volume_id` context so a reader can
  tell same-titled volumes apart. It is `null` when the source carries no Comic Vine volume
  identity.

The endpoint never constrains to user-owned `issues` or `issue_external_identity_mappings`. A Comic
Vine ID that no reader owns still returns every CBL that contains it, and a reader who owns the
matching comic gets the same answer as a reader who does not.

## Catalog rules

- Only **active** source lists participate. A list that the current mirror revision no longer
  contains is retained in the database as inactive and is not part of the browsable catalog.
- Repeated occurrences inside one source list stay separate rows with their own source positions.
- The same identity in several source lists is reported once per list.
- Source repository and path are returned in reader-safe form: a local mirror path such as
  `/mnt/bigdata/CBL-ReadingLists` is never exposed.

## Layers

| Layer | Module | Responsibility |
|---|---|---|
| Router | `app/api/cbl_comicvine_lookup.py` | Validates the request and maps the service result to the response schema |
| Service | `app/services/cbl_comicvine_lookup_service.py` | Builds the reader-safe occurrence page |
| Repository | `app/repositories/cbl_comicvine_lookup_repository.py` | Owns the identity join, the occurrence query, and the totals |

The reverse lookup is a read path. It performs no writes, triggers no GitHub fetch, and does not
depend on the reading-plan sync, so a lookup never causes per-CBL network work.
