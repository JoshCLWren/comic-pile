# Step 14 production run checklist

1. Deploy/check out the exact audited commit.
2. Run `python scripts/audit_legacy_dependencies.py --user-id 1 --output step-14-dependency-ledger.json` with production DB read credentials.
3. Record the snapshot token and total.
4. Confirm the total matches a same-snapshot direct count of user-1 dependency rows.
5. Review every `needs_review` family and encode stronger evidence rather than guessing.
6. Rerun from a fresh snapshot after classifier changes.
7. Persist final ledger and human summary.
8. Update #2445 and #2366 only when 100% is classified and reconciled.
