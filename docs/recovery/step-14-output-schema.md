# Step 14 audit output

Top-level fields: `user_id`, `snapshot_token`, `total`, `classification_counts`, `rows`.

Each row includes the dependency identity/endpoints/note, linked canonical rule IDs, overlapping legacy Reading Order IDs, overlapping canonical Reading Plan IDs, classification, reason, and human-review flag.

The ledger is the accounting spine. Additional evidence fields required by #2445 must be added before final production sign-off where the current schema does not yet capture them.
