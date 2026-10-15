# Reading List authoring (Option E)

The existing `/api/v1/custom-cbls` POST and PUT accept additive fields:

- `mode`: `strict` or `loose`; omission preserves the existing mode (new lists default to loose).
- `entry_intents`: a map from member Issue ID to `{gate, skipped}`. Gates are `none`, `hold`,
  or `after_previous`. Omitted members retain their intent; new members default to none/unskipped.
  Supplying an intent replaces both values for that member; omitted values use those defaults.
- `confirmed_predecessor_changes`: PUT-only acknowledgement of a rejected preview; POST rejects
  this field, including an empty array.

Any update that changes stored positional requirements (including mode-only and gate-only edits)
returns HTTP 409 with `detail.code = reading_list_predecessor_confirmation_required` and
`detail.predecessor_changes`. Each change names the affected Issue and its before/after source
Issues. Display the changes for reader confirmation, then resubmit the same write with those
Issue-ID relationships as `confirmed_predecessor_changes`. A changed Issue-ID diff requires a new
confirmation. Display names and array ordering do not participate in consent matching. Rejected
previews do not persist metadata, membership, gates, or skips. Successful PUT responses also
include `predecessor_changes` and `warnings` for strict lists that omit unread Issues from a
partially represented Thread. Coverage excludes skipped entries, including when the only placement
for a Thread is skipped. Omitted Issues receive no new constraints. Warnings are bounded to ten
Threads plus a remaining-Thread count; each includes the omitted count and at most five sample
names (each name/title truncated to 80 characters), followed by a remaining-Issue count.

Warnings are write-time diagnostics returned by POST/PUT only. GET returns `warnings: []`; it does
not run global authoring validation. Reopening a list does not imply that coverage was rechecked.

Previews describe **stored authoring constraints**, including globally excluded Issues, consistent
with cycle validation. Eligibility evaluation later ignores globally excluded entries; a constraint
can therefore appear in this preview without currently blocking Roll. Retaining and confirming
those stored relationships protects against latent cycles and silent retargeting when exclusions
are removed. List-local skipped entries are omitted from both stored-order checks and previews.

All list writes for a reader serialize on the reader row. Before commit, validation checks the
complete resulting graph: natural series order, overlapping strict/loose lists and gates, and
currently enforced explicit/historical dependencies. Read Issues participate in cycle validation.
Collection exclusions resolve by owned Issue, Thread, canonical volume, or confirmed external
volume mapping. An excluded prerequisite source fails closed. Cycles return HTTP 422 with
`reading_list_cycle`, a readable path, and edge origins. No historical dependency is classified,
retired, or rewritten by this API; cycle diagnostics explicitly label unknown historical provenance
rather than inferring reader authorship from an absent generated marker. Inert `cbl-order:` rows
are not execution inputs. Each structured cycle-path edge also carries `prerequisite_origin`
(`reader`, `converted`, or null for non-prerequisite edges) and `provenance` (an array). The authoring
adapter marks historical rows as `converted` with `historical classification unknown` provenance;
this is not proof of approved conversion or reader authorship.

Snapshot identity/reference failures indicate persisted-state corruption and intentionally surface
as server errors, rather than a user-edit 422. Ordinary request errors are validated earlier:
ownership/membership and enum validation, database uniqueness/foreign keys, explicit missing-list
404, stranded-prerequisite 422, and cycle 422. The API does not accept client snapshots or IDs for
new entry identities; those internal invariants cannot be authored through this write contract.

Existing checkpoint target metadata remains independent of positional gates and survives unchanged
old-client saves. These authoring fields do not activate Option E in Roll or Queue and do not
compile list adjacency into Dependencies. Production conversion and activation remain separate,
owner-approved operations under #3676.

## Frontend rollout dependency

#3668 owns the 409 preview/confirmation UI, strict-mode warning display, and actionable 422 cycle
feedback in the existing list builder. Gate/mode authoring controls must not be exposed to readers
until that flow is implemented and verified. #3676 production conversion/activation must also wait
for that authoring UX; deploying this API alone does not enable reader-visible gate controls.

CI runs `pnpm --filter frontend run check:api-types` with explicit `ENVIRONMENT=test` to enforce
schema/client freshness, including the environment-gated `/api/v1/debug/log` route. This setting
does not depend on `.env.test` being present or on the runner's inherited environment.
