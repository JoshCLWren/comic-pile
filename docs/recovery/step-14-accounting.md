# Accounting invariant

Every dependency ID appears exactly once in the row ledger and exactly one classification bucket. `sum(classification_counts.values()) == total == len(rows)` must hold before any result is considered usable.
