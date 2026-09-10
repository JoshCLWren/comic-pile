# Step 14 dependency classification audit

This is the read-only evidence procedure for #2445 under recovery epic #2366 and architecture hold #2363.

Run against one production snapshot:

```bash
python scripts/audit_legacy_dependencies.py --user-id 1 --output step-14-dependency-ledger.json
```

The output enumerates every selected dependency ID, produces a stable snapshot token, and reconciles classification totals to the ledger total.

Classification is intentionally conservative. Exact `cbl-order:source:*` compatibility rows are classified as `reading_plan_order`. Linked legacy rows are not automatically considered safe because canonical-rule linkage does not prove whether the legacy row should survive. All other rows remain `needs_review` until stronger family or row-level evidence is encoded and reviewed.

## Completion gate

Do not close #2445 from the existence of this script. Step 14 is complete only after a fresh production run accounts for 100% of user-1 dependencies and the remaining `needs_review` rows have explicit evidence and human decisions. Persist the resulting ledger/summary as recovery evidence and update #2366.

This procedure performs no writes, commits, blocked-state refreshes, plan changes, dependency changes, or continuity-rule changes.
