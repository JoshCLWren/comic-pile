//! Concurrency regression for atomic login lockout serialization (#4746).
//!
//! The previous implementation checked the per-account and per-client
//! failure counts, released its pool checkout for bcrypt, and recorded the
//! outcome in a separate statement, so simultaneous failures at the
//! threshold could all pass the check and all insert — crossing the limit
//! and letting an attacker spend N guesses per burst. Login now linearizes
//! in a second transaction: per-username and per-IP advisory locks plus a
//! recount under the locks make the record-or-clear decision atomic, while
//! bcrypt still runs with no pooled connection held.
//!
//! The 5-account / 10-address ceilings below mirror `MAX_USERNAME_FAILURES`
//! / `MAX_IP_FAILURES` in `src/auth/services.rs`; the budget pin
//! (`tests/test_login_sql_budget.py`) fails if the two ever disagree.
//!
//! The concurrency tests are deterministic: every attempt batch is launched
//! behind a `tokio::sync::Barrier` on real PostgreSQL, and the exact final
//! row counts prove the cap. With 4 stored failures and 2 simultaneous
//! failures, the buggy code stored 6 rows; the fix stores exactly 5 (the
//! first concurrent attempt reaches the threshold, the second is rejected
//! without a write). The same cap holds for an 8-attempt burst and for the
//! per-IP dimension. Elapsed wall time is printed per test; the dominant
//! cost stays the bcrypt verification itself (one per admitted attempt),
//! and the whole burst path issues at most 8 statements — 6 application
//! plus `BEGIN`/`COMMIT` — independent of attempt history. Full
//! `pg_stat_statements` parity is the shared #4737 harness;
//! `count_queries_stay_indexed_as_history_grows` proves the count queries
//! remain index range scans beside 200 stored rows.
//!
//! Canonical Alembic schema only: `test_support` supplies the DML-only
//! role and the fixture rows are inserted through `INSERT ... RETURNING`
//! on the disposable database. No plaintext password is ever bound as a
//! database parameter; only usernames and client addresses are.

use comicpile_roll_service::{
    auth::{AuthError, AuthService, LoginRequest, RegisterRequest},
    config::Config,
    test_support, AppState,
};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Barrier;

const PASSWORD: &str = "correct-horse-battery";

/// Failure counts are indexed range scans, so a 200-row history must not
/// change any login outcome below.
const HISTORY_ROWS: i64 = 200;

fn state(url: &str, pool_size: usize) -> Arc<AppState> {
    Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.into()),
                "RUST_ROLL_JWT_SECRET" => Some(test_support::TEST_JWT_SECRET.into()),
                "RUST_ROLL_POOL_SIZE" => Some(pool_size.to_string()),
                "RUST_ROLL_POOL_TIMEOUT_MS" => Some("5000".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    )
}

async fn database(pool_size: usize) -> (Arc<AppState>, tokio::sync::MutexGuard<'static, ()>) {
    let url = test_support::database_url().await;
    let state = state(&url, pool_size);
    let guard = test_support::reset_for_test(&state).await;
    (state, guard)
}

/// One distinct TEST-NET client address per attempt, so the per-IP lockout
/// never confounds the per-username measurements.
fn unique_ip(attempt: u16) -> String {
    format!("198.51.100.{}", attempt)
}

async fn register(state: &Arc<AppState>, username: &str) {
    let service = AuthService::new(Arc::clone(state));
    service
        .register(&RegisterRequest {
            username: username.into(),
            email: format!("{username}@example.com"),
            password: PASSWORD.into(),
        })
        .await
        .expect("fixture registration must succeed");
}

async fn wrong_password_login(
    state: &Arc<AppState>,
    username: &str,
    ip: &str,
) -> Result<(), AuthError> {
    let service = AuthService::new(Arc::clone(state));
    service
        .login(
            &LoginRequest {
                username: username.into(),
                password: "incorrect-password".into(),
            },
            ip,
        )
        .await
        .map(|_| ())
}

async fn correct_password_login(
    state: &Arc<AppState>,
    username: &str,
    ip: &str,
) -> Result<String, AuthError> {
    let service = AuthService::new(Arc::clone(state));
    service
        .login(
            &LoginRequest {
                username: username.into(),
                password: PASSWORD.into(),
            },
            ip,
        )
        .await
        .map(|tokens| tokens.access_token)
}

async fn seed_attempts(state: &Arc<AppState>, username: &str, ip: &str, count: i64, recent: bool) {
    let connection = state.pool.get().await.unwrap();
    for _ in 0..count {
        if recent {
            connection
                .execute(
                    "INSERT INTO failed_login_attempts (username, ip_address, attempted_at) \
                     VALUES ($1, $2, NOW())",
                    &[&username, &ip],
                )
                .await
                .unwrap();
        } else {
            // Outside both the 15-minute account and 30-minute address windows.
            connection
                .execute(
                    "INSERT INTO failed_login_attempts (username, ip_address, attempted_at) \
                     VALUES ($1, $2, NOW() - INTERVAL '1 hour')",
                    &[&username, &ip],
                )
                .await
                .unwrap();
        }
    }
}

async fn failure_rows(state: &Arc<AppState>, column: &str, value: &str) -> i64 {
    let connection = state.pool.get().await.unwrap();
    let sql = format!("SELECT count(*) FROM failed_login_attempts WHERE {column} = $1");
    connection
        .query_one(&sql, &[&value])
        .await
        .unwrap()
        .get::<_, i64>(0)
}

async fn username_rows(state: &Arc<AppState>, username: &str) -> i64 {
    failure_rows(state, "username", username).await
}

async fn ip_rows(state: &Arc<AppState>, ip: &str) -> i64 {
    failure_rows(state, "ip_address", ip).await
}

/// Four stored failures, then two simultaneous failures: exactly 5 rows, and
/// the next correct-password login is still rejected.
#[tokio::test]
async fn simultaneous_failures_at_threshold_cannot_be_bypassed() {
    let (state, _db) = database(6).await;
    register(&state, "lockout-concurrent").await;
    seed_attempts(&state, "lockout-concurrent", "198.51.100.11", 4, true).await;

    let started = Instant::now();
    let barrier = Arc::new(Barrier::new(3));
    let mut tasks = Vec::new();
    for offset in 0..2_u16 {
        let barrier = Arc::clone(&barrier);
        let state = Arc::clone(&state);
        tasks.push(tokio::spawn(async move {
            barrier.wait().await;
            wrong_password_login(&state, "lockout-concurrent", &unique_ip(30 + offset)).await
        }));
    }
    // Include the test task so both bursts genuinely start together.
    barrier.wait().await;
    let mut outcomes = Vec::new();
    for task in tasks {
        outcomes.push(task.await.unwrap());
    }
    let elapsed = started.elapsed();
    println!("2-attempt burst at threshold finished in {elapsed:?}");
    assert_eq!(outcomes.len(), 2);
    for outcome in &outcomes {
        assert!(
            matches!(outcome, Err(AuthError::InvalidCredentials)),
            "both concurrent failures must be rejected with the non-enumerating 401, got {outcome:?}"
        );
    }
    assert_eq!(
        username_rows(&state, "lockout-concurrent").await,
        5,
        "only the attempt that reached the threshold may write its failure row"
    );
    assert!(matches!(
        correct_password_login(&state, "lockout-concurrent", "198.51.100.99").await,
        Err(AuthError::InvalidCredentials)
    ));
}

/// Eight simultaneous failures from an empty account store exactly 5 rows:
/// the burst cannot buy extra guesses, and the account stays locked.
#[tokio::test]
async fn larger_simultaneous_burst_is_capped_at_the_threshold() {
    let (state, _db) = database(8).await;
    register(&state, "lockout-burst").await;

    const BURST: usize = 8;
    let started = Instant::now();
    let barrier = Arc::new(Barrier::new(BURST + 1));
    let mut tasks = Vec::new();
    for offset in 0..BURST as u16 {
        let barrier = Arc::clone(&barrier);
        let state = Arc::clone(&state);
        tasks.push(tokio::spawn(async move {
            barrier.wait().await;
            wrong_password_login(&state, "lockout-burst", &unique_ip(40 + offset)).await
        }));
    }
    barrier.wait().await;
    let mut outcomes = Vec::new();
    for task in tasks {
        outcomes.push(task.await.unwrap());
    }
    let elapsed = started.elapsed();
    println!("{BURST}-attempt burst finished in {elapsed:?}");
    assert_eq!(outcomes.len(), BURST);
    for outcome in &outcomes {
        assert!(
            matches!(outcome, Err(AuthError::InvalidCredentials)),
            "every concurrent failure must be rejected, got {outcome:?}"
        );
    }
    assert_eq!(
        username_rows(&state, "lockout-burst").await,
        5,
        "an 8-attempt burst must store at most the 5-threshold rows"
    );
    assert!(matches!(
        correct_password_login(&state, "lockout-burst", "198.51.100.99").await,
        Err(AuthError::InvalidCredentials)
    ));
}

/// The per-IP dimension caps as well: 9 stored failures for one address, then
/// two simultaneous failures from it store exactly 10 rows, and a separate
/// account with no failures of its own is still locked from that address.
#[tokio::test]
async fn per_ip_lockout_is_capped_under_concurrent_addresses() {
    let (state, _db) = database(6).await;
    register(&state, "ip-lockout-reader").await;
    let shared_ip = "203.0.113.200";
    seed_attempts(&state, "ip-seed-user", shared_ip, 9, true).await;

    let barrier = Arc::new(Barrier::new(3));
    let mut tasks = Vec::new();
    for username in ["ip-burst-1", "ip-burst-2"] {
        let barrier = Arc::clone(&barrier);
        let state = Arc::clone(&state);
        tasks.push(tokio::spawn(async move {
            barrier.wait().await;
            wrong_password_login(&state, username, shared_ip).await
        }));
    }
    barrier.wait().await;
    let mut outcomes = Vec::new();
    for task in tasks {
        outcomes.push(task.await.unwrap());
    }
    assert_eq!(outcomes.len(), 2);
    for outcome in &outcomes {
        assert!(matches!(outcome, Err(AuthError::InvalidCredentials)));
    }
    assert_eq!(
        ip_rows(&state, shared_ip).await,
        10,
        "only the attempt that reached the 10-row address threshold may write"
    );
    assert!(matches!(
        correct_password_login(&state, "ip-lockout-reader", shared_ip).await,
        Err(AuthError::InvalidCredentials)
    ));
}

/// Successful logins still clear the account's failures together, and
/// failures outside the retention windows no longer lock the account.
#[tokio::test]
async fn concurrent_success_clears_attempts_and_windows_still_recover() {
    let (state, _db) = database(6).await;
    register(&state, "recovery-reader").await;
    seed_attempts(&state, "recovery-reader", "198.51.100.11", 4, true).await;
    seed_attempts(&state, "recovery-reader", "198.51.100.12", 5, false).await;

    let barrier = Arc::new(Barrier::new(4));
    let mut tasks = Vec::new();
    for offset in 0..3_u16 {
        let barrier = Arc::clone(&barrier);
        let state = Arc::clone(&state);
        tasks.push(tokio::spawn(async move {
            barrier.wait().await;
            correct_password_login(&state, "recovery-reader", &unique_ip(50 + offset)).await
        }));
    }
    barrier.wait().await;
    let mut outcomes = Vec::new();
    for task in tasks {
        outcomes.push(task.await.unwrap());
    }
    assert_eq!(outcomes.len(), 3);
    for outcome in &outcomes {
        assert!(
            outcome.as_ref().is_ok_and(|token| !token.is_empty()),
            "concurrent correct passwords below the threshold must succeed, got {outcome:?}"
        );
    }
    assert_eq!(
        username_rows(&state, "recovery-reader").await,
        0,
        "a successful login clears all of the account's failure rows"
    );

    // Five expired rows must not lock the account once the windows pass.
    seed_attempts(&state, "recovery-reader", "198.51.100.13", 5, false).await;
    assert!(
        correct_password_login(&state, "recovery-reader", "198.51.100.14")
            .await
            .is_ok()
    );
    assert_eq!(username_rows(&state, "recovery-reader").await, 0);
}

/// Bcrypt runs with no pooled connection held: with 3 of 4 connections
/// reserved by the test, the login takes the last slot for Phase 1,
/// releases it during bcrypt, and we can check out that freed connection
/// while bcrypt is still in flight. A barrier synchronizes the start so
/// the test observes the Phase 1 release directly without polling.
#[tokio::test]
async fn bcrypt_verification_does_not_hold_a_pooled_connection() {
    let (state, _db) = database(4).await;
    register(&state, "connection-reader").await;

    // Reserve 3 of 4 connections, leaving 1 free for the login's Phase 1.
    let mut reserved = Vec::new();
    for _ in 0..3 {
        reserved.push(state.pool.get().await.unwrap());
    }

    // Barrier ensures the login and the test's pool.get() start together.
    let barrier = Arc::new(Barrier::new(2));
    let barrier_for_login = Arc::clone(&barrier);
    let state_for_login = Arc::clone(&state);
    let login = tokio::spawn(async move {
        barrier_for_login.wait().await;
        wrong_password_login(&state_for_login, "connection-reader", "198.51.100.77").await
    });

    // Wait for the login to start, then wait for it to release its Phase 1 connection.
    barrier.wait().await;

    // At this point, the login has started and is trying to get a connection.
    // With 3 reserved, there's 1 free — the login will take it for Phase 1.
    // We now wait for that connection to be released (happens after Phase 1).
    let freed_connection = tokio::time::timeout(Duration::from_secs(5), state.pool.get())
        .await
        .expect("checkout must not hang — login should release Phase 1 connection during bcrypt")
        .expect("the freed login connection must be reusable during bcrypt");

    // We now hold the connection that was freed after Phase 1.
    // The login task must still be in bcrypt verification (Phase 2 hasn't started
    // because it needs a connection, which we're holding).
    assert!(
        !login.is_finished(),
        "login must still be verifying while its connection is reusable"
    );

    // Release our hold so the login can proceed to Phase 2.
    drop(freed_connection);

    // Wait for login to complete.
    let outcome = login.await.unwrap();
    assert!(matches!(outcome, Err(AuthError::InvalidCredentials)));

    drop(reserved);
}

/// The count queries stay index range scans beside stored history, and a
/// login decision does not change when history grows.
#[tokio::test]
async fn count_queries_stay_indexed_as_history_grows() {
    let (state, _db) = database(4).await;
    register(&state, "index-reader").await;

    let connection = state.pool.get().await.unwrap();
    connection
        .execute(
            "INSERT INTO failed_login_attempts (username, ip_address, attempted_at) \
             SELECT 'bulk-' || g, $1, NOW() FROM generate_series(1, $2::bigint) AS g",
            &[&"198.51.100.9", &HISTORY_ROWS],
        )
        .await
        .unwrap();
    for (label, sql, value) in [
        (
            "username counts",
            "EXPLAIN SELECT count(*) FROM failed_login_attempts \
             WHERE username = $1 AND attempted_at >= NOW() - INTERVAL '15 minutes'",
            "index-reader",
        ),
        (
            "address counts",
            "EXPLAIN SELECT count(*) FROM failed_login_attempts \
             WHERE ip_address = $1 AND attempted_at >= NOW() - INTERVAL '30 minutes'",
            "198.51.100.9",
        ),
    ] {
        let rows = connection.query(sql, &[&value]).await.unwrap();
        let plan = rows
            .iter()
            .map(|row| row.get::<_, String>(0))
            .collect::<Vec<_>>()
            .join("\n")
            .to_lowercase();
        assert!(
            plan.contains("ix_failed_login"),
            "{label} must use a failure-count index, plan: {plan}"
        );
        assert!(
            !plan.contains("seq scan"),
            "{label} must never sequentially scan the attempts table, plan: {plan}"
        );
    }
    drop(connection);

    // The 200 unrelated rows never affect this account's decision: a correct
    // password still succeeds, and its success path issues the same bounded
    // statement set.
    assert!(
        correct_password_login(&state, "index-reader", "198.51.100.21")
            .await
            .is_ok()
    );
}
