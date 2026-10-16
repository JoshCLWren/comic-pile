# Collection exclusions during CBL import

CBL reconciliation and adoption now check the reader's durable collection
exclusions independently of per-list Include/Exclude choices. A source Include
choice cannot clear or bypass a collection exclusion. List-local skips remain
local and do not create exclusions.

Preview preserves every source position and adds these fields:

- `collection_excluded`: this entry cannot be included from the current preview.
- `collection_exclusion_reason`: `collection_volume_excluded`,
  `collection_thread_excluded`, `collection_issue_excluded`, or
  `collection_identity_requires_review`.
- `collection_exclusion_ids`: matching owner-scoped decision IDs, empty when
  uncertain identity prevents a safe exclusion check.

Confirmed exclusions are counted as excluded and never selected by default.
Missing/conflicting identity is unresolved and cannot be forced in by Include;
readers can explicitly exclude that source entry/series to import other material.
The existing preview checkbox is disabled for collection-blocked entries, with
an explanation alongside the source series/issue label. Local series Include
controls retain the same exclusion result.

Checks use stable provider identities, confirmed Issue/Thread mappings and
canonical catalog series identities. ComicVine `4050-123` and `123` identify the
same volume. Series spelling, punctuation, absence from a list and annual labels
never infer an exclusion or bypass one. Missing/conflicting volume evidence fails
closed when external volume exclusions cannot otherwise be checked.

Preview is observational. Commit acquires the same reader row lock as exclusion
creation/deletion, reads current exclusions, and repeats the check after resolving
an actual target Thread or reusable Issue. Exclusions added after preview take
effect at commit, even when source fingerprint and Include choices are unchanged.
Changed collection constraints invalidate an older adoption receipt, so a retry
cannot replay obsolete Include results. New and targeted adoption paths share this boundary. Reconciliation's separate
identity report also leaves excluded entries unchosen with an explanation.

No production backfill, automatic exclusion creation, Roll authority change or
release-sync behavior is part of #3670. Release sync enforcement is tracked by
#3671. These import guards protect explicit reader intent while the separately
approved Option E conversion and activation remain pending.
