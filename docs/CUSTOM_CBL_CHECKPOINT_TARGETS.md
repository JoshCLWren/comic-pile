# Durable custom CBL checkpoint targets

Custom CBL membership is intended display order. A checkpoint carries specific
source and target issue IDs. List adjacency never becomes an implicit additional
prerequisite. This extends the existing CBL and plan compiler; Roll still consumes
the existing canonical Dependencies.

## Authoring contract

`CustomCBLWrite.checkpoint_targets` maps a source issue ID to its target issue IDs:

```json
{
  "name": "Selected checkpoints",
  "issue_ids": [1, 2, 3, 4],
  "checkpoint_targets": {"1": [3, 4]}
}
```

The compiler emits 1→3 and 1→4, never 1→2 or 3→4. Both endpoints must be owned
issues in the custom list. Self-targets, duplicates, and non-member targets are
rejected. Adding an existing owned source to a list does not import a comic.

Entries return `checkpoint_target_issue_ids`; applied plan nodes carry
`checkpoint_target_ref_ids`. The existing singular plan target remains supported.
The planner serializer preserves both forms on save and clears them when a reader
disables the checkpoint.

Omitting `checkpoint_targets` preserves existing targets across reorder. Omitting
`checkpoint_issue_ids` preserves existing source selections. Explicitly supplying
that source selection removes checkpoints for unchecked sources, supporting the
existing builder. Legacy flags bind to the successor in the custom source list,
and a terminal flag is cleared. Removing a target drops that target rather than
redirecting the checkpoint to a neighbor in either the list or destination plan.

## Production recovery boundary

The additive migration stores target metadata and freezes existing source-list
flags. It does not compile any Dependencies or change Roll blocked flags.
Existing canonical prerequisites continue to govern Roll until a separately
reviewed reconciliation is applied.

On October 13, fifteen custom lists were preserved from user 1's existing plans:
477 existing owned issue references in their saved order. Absolute Flash and
Absolute Green Lantern are excluded. Before/after fingerprints matched for
issues, threads, reading history, plans, memberships, rules and Dependencies.
The three previously existing lists were retained. JSA has the same 57 ordered
issues as its plan, apart from the plan's additional Starman #55 prerequisite.
Julix has the same 464 ordered plan issues plus two already-read stories,
Box Full of Evil #1 and Amazing Screw-On Head #1. Fourth World matches exactly.

This preservation does not approve retiring any blocker. The previous cleanup
forecast and replica test results are insufficient evidence of intended reading
behavior. Generated provenance alone cannot distinguish an unwanted adjacency
from a genuine sequel or crossover prerequisite. Every proposed unlock still
needs an evidence-backed disposition before production retirement.
