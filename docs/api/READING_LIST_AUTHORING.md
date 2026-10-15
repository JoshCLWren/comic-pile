# Reading List authoring (Option E)

The existing `/api/v1/custom-cbls` POST and PUT accept additive fields:

- `mode`: `strict` or `loose`; omission preserves the existing mode (new lists default to loose).
- `entry_intents`: a map from member Issue ID to `{gate, skipped}`. Gates are `none`, `hold`,
  or `after_previous`. Omitted members retain their intent; new members default to none/unskipped.
  Supplying an intent replaces both values for that member; omitted values use those defaults.
- `confirmed_predecessor_changes`: the exact semantic diff from a rejected reorder preview.

A placement, membership, or skip change that changes positional requirements returns HTTP 409
with `detail.code = reading_list_predecessor_confirmation_required` and
`detail.predecessor_changes`. Each change names the affected Issue and its before/after source
Issues. Display the changes for reader confirmation, then resubmit the same write with that exact
array as `confirmed_predecessor_changes`. A changed diff requires a new confirmation. Rejected
previews do not persist metadata, membership, gates, or skips. Successful PUT responses also
include `predecessor_changes`; a mode/gate-only edit returns its effective changes directly.

All list writes for a reader serialize on the reader row. Before commit, validation checks the
complete resulting graph: natural series order, overlapping strict/loose lists and gates, and
currently enforced explicit/historical dependencies. Read Issues participate in cycle validation.
Collection exclusions resolve by owned Issue, Thread, canonical volume, or confirmed external
volume mapping. An excluded prerequisite source fails closed. Cycles return HTTP 422 with
`reading_list_cycle`, a readable path, and edge origins. No historical dependency is classified,
retired, or rewritten by this API; inert `cbl-order:` rows are not execution inputs.

Existing checkpoint target metadata remains independent of positional gates and survives unchanged
old-client saves. These authoring fields do not activate Option E in Roll or Queue and do not
compile list adjacency into Dependencies. Production conversion and activation remain separate,
owner-approved operations under #3676.
