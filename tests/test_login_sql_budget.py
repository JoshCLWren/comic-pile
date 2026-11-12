"""SQL budget guard for ``POST /api/v2/auth/login`` (#4746).

The 2026-11-07 #4335 update requires a reviewed ``sql_budget`` beside each
DB-backed Rust operation in ``docs/api/v2-route-inventory.json``. This test
pins the login budget against the Rust call sites in
``native/roll-service/src/auth/services.rs``: the optimistic gate reads the
combined failure counts and the user row, then the serialized decision
transaction takes two advisory locks, recounts, and performs exactly one
conditional insert or delete. Bcrypt stays in Rust on tokio's blocking
pool, and no statement binds the plaintext password.

A new or moved statement will not fail this test by magic: adding one
requires deleting a slot the same size, or a deliberate pin + inventory
update. All statements are set-based and independent of attempt history:
the attempt table is read only through its two window indexes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "api" / "v2-route-inventory.json"
SERVICES = ROOT / "native" / "roll-service" / "src" / "auth" / "services.rs"

QUERY_CALL = re.compile(r"\.(query|query_opt|query_one|execute)\(")
STRING_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')

# Production ceilings mirrored by the Rust concurrency tests. The same
# values must hold in services.rs; see also MAX_USERNAME_FAILURES /
# MAX_IP_FAILURES below.
PINNED_MAX_USERNAME_FAILURES = 5
PINNED_MAX_IP_FAILURES = 10


def _login_entry() -> dict[str, object]:
    """Return the inventory entry for the login operation."""
    document = json.loads(INVENTORY.read_text(encoding="utf-8"))
    operations = document["operations"]
    assert isinstance(operations, list)
    for operation in operations:
        if not isinstance(operation, dict):
            raise AssertionError("inventory operations must be objects")
        if (
            operation.get("method") == "POST"
            and operation.get("path") == "/api/v2/auth/login"
        ):
            return operation
    raise AssertionError("login missing from v2 route inventory")


def _login_body(source: str) -> str:
    """Return the login handler body, excluding its doc comment."""
    start = source.index("pub async fn login(")
    end = source.index("pub async fn refresh(")
    return source[start:end]


def test_login_sql_budget_matches_handler_call_sites() -> None:
    """The declared budget equals the statically pinned Rust call sites."""
    entry = _login_entry()
    budget = entry.get("sql_budget")
    assert isinstance(budget, dict), "login entry must declare a sql_budget"

    source = SERVICES.read_text(encoding="utf-8")
    login = _login_body(source)

    # Optimistic gate: combined counts (one statement) plus the user fetch
    # inside the user-by-username helper (presence-checked, not counted).
    assert login.count("FAILURE_COUNTS_SQL") == 2, "gate and recount must share one SQL constant"
    assert login.count(".query_one(") == 2, "gate counts + serialized recount"
    assert "query_opt" in source.split("async fn user_by_username(", 1)[1], (
        "user fetch must stay a single helper statement"
    )

    # Serialized decision: two advisory locks, then one conditional write.
    # DELETE xor INSERT: both call sites exist, one runs per outcome.
    lock_statements = len(re.findall(r"pg_advisory_xact_lock", login))
    assert lock_statements == 2, "username and client-address locks, in this order"
    assert "DELETE FROM failed_login_attempts" in login
    assert "INSERT INTO failed_login_attempts" in login
    assert login.count("transaction()") == 1 and login.count("commit()") == 2, (
        "one transaction per login: BEGIN once, COMMIT once per outcome branch"
    )

    counts_statements = 1
    user_fetch_statements = 1
    recount_statements = 1
    write_statements = 1
    expected = (
        counts_statements
        + user_fetch_statements
        + lock_statements
        + recount_statements
        + write_statements
    )
    assert expected == 6
    assert budget.get("application_statements") == expected
    assert budget.get("transaction_control_statements") == 2
    assert budget.get("total_statements") == expected + 2
    assert budget.get("runtime_overhead_statements") == 2
    assert budget.get("max_statements") == expected + 4
    assert budget.get("basis") == (
        "optimistic gate 2 (counts + user fetch) + serialized decision 4 "
        "(2 advisory locks + recount + conditional insert/delete) (+2 tx control); "
        "set-based, index-backed, independent of attempt history; "
        "bcrypt in Rust, no plaintext secret in SQL; measured cold-pool path "
        "adds two SELECT 1 checkout probes"
    )


def test_login_lockout_limits_and_windows_match_the_pinned_ceilings() -> None:
    """Production ceilings, windows and bcrypt placement stay as pinned."""
    source = SERVICES.read_text(encoding="utf-8")
    assert f"MAX_USERNAME_FAILURES: i64 = {PINNED_MAX_USERNAME_FAILURES};" in source
    assert f"MAX_IP_FAILURES: i64 = {PINNED_MAX_IP_FAILURES};" in source
    start = source.index("FAILURE_COUNTS_SQL")
    windows = source[start : source.index(";", start)]
    assert "INTERVAL '15 minutes'" in windows
    assert "INTERVAL '30 minutes'" in windows

    login = _login_body(source)
    # Bcrypt stays in Rust on both the known- and unknown-account paths,
    # after the pool checkout has ended (no connection held across CPU work).
    assert "verify_password_blocking(request.password" in login
    assert "verify_unknown_account_password(&request.password)" in login

    # No statement text may reference a password: only the username and the
    # client address are bound; the secret never reaches PostgreSQL.
    for sql in STRING_LITERAL.findall(login):
        assert "password" not in sql.lower(), f"plaintext secret reached SQL text: {sql!r}"
    for sql in STRING_LITERAL.findall(windows):
        assert "password" not in sql.lower(), f"plaintext secret reached SQL text: {sql!r}"


def test_login_has_no_query_inside_a_loop() -> None:
    """The serialized decision adds no per-row (N+1) statements."""
    source = SERVICES.read_text(encoding="utf-8")
    login = _login_body(source)
    assert not re.search(r"(?m)^\s*(for|while)\s", login), (
        "login must not loop over statements; counts are set-based"
    )
    assert len(QUERY_CALL.findall(login)) == 6, (
        "login body must hold exactly the 6 gated statement sites "
        "(gate counts, recount, 2 advisory locks, conditional insert/delete)"
    )
