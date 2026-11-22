#![allow(clippy::unwrap_used, clippy::expect_used)]
//! HTTP regressions for deleting an owned thread through the same-path v1
//! endpoint. The delete must remove the thread together with its dependent rows
//! in one transaction so it cannot fail with a foreign-key violation.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, AppState};
use serde_json::{json, Value};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use tower::ServiceExt;

static NEXT_TEST_CLIENT: AtomicUsize = AtomicUsize::new(1);

type Conn = deadpool_postgres::Object;

/// Queue advisory-lock namespace mirrored from `queue::QUEUE_LOCK_NAMESPACE`
/// (pub(crate)); used to hold the queue lock while racing two writers.
const QUEUE_LOCK_NAMESPACE: i32 = 699001;

/// Bounded nanosecond suffix. The auth API caps usernames at 50 characters
/// (`RegisterRequest.username`), and the full username is
/// `{prefix}-{pid}-{suffix}`; a 19-digit suffix made longer prefixes (for
/// example `thread-delete-nocascade`) exceed that limit depending on the PID
/// width. Nine digits keep every username in this file well within the bound
/// while staying unique across sequential calls.
fn unique_suffix() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos()
        % 1_000_000_000
}

async fn setup_user_with_pool(
    prefix: &str,
    pool_size: &str,
) -> (
    Arc<AppState>,
    String,
    String,
    i32,
    tokio::sync::MutexGuard<'static, ()>,
) {
    let url = comicpile_roll_service::test_support::database_url().await;
    let state = Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
                "RUST_ROLL_JWT_SECRET" => Some("synthetic-roll-routes-secret".into()),
                "RUST_ROLL_POOL_SIZE" => Some(pool_size.to_owned()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    );
    let guard = comicpile_roll_service::test_support::reset_for_test(&state).await;
    let username = format!("{prefix}-{}-{}", std::process::id(), unique_suffix());
    let (token, csrf, user_id) = register_user(&state, &username).await;
    (state, token, csrf, user_id, guard)
}

async fn setup_user(
    prefix: &str,
) -> (
    Arc<AppState>,
    String,
    String,
    i32,
    tokio::sync::MutexGuard<'static, ()>,
) {
    setup_user_with_pool(prefix, "2").await
}

/// Admin connection used only to reproduce a production-only schema condition.
/// The DML-only role cannot issue DDL, and deliberately changing the canonical
/// schema is exactly how the #5461 production drift is simulated here.
async fn admin_connection() -> Conn {
    let url = std::env::var("RUST_ROLL_TEST_DATABASE_URL")
        .expect("RUST_ROLL_TEST_DATABASE_URL is required for schema-drift regressions");
    let state = AppState::new(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-roll-routes-secret".into()),
            "RUST_ROLL_POOL_SIZE" => Some("1".into()),
            _ => None,
        })
        .unwrap(),
    )
    .unwrap();
    state.pool.get().await.unwrap()
}

/// Toggle `events_thread_id_fkey` between the canonical `ON DELETE CASCADE` and
/// the non-cascading form that produced the #5461 production FK violation.
async fn set_events_thread_fk_cascade(admin: &Conn, cascade: bool) {
    let action = if cascade { " ON DELETE CASCADE" } else { "" };
    admin
        .batch_execute(&format!(
            "ALTER TABLE events DROP CONSTRAINT IF EXISTS events_thread_id_fkey; \
             ALTER TABLE events ADD CONSTRAINT events_thread_id_fkey \
               FOREIGN KEY (thread_id) REFERENCES threads(id){action}"
        ))
        .await
        .unwrap();
}

async fn queue_lock_waiters(conn: &Conn, user_id: i32) -> i64 {
    conn.query_one(
        "SELECT count(*) FROM pg_locks \
         WHERE locktype = 'advisory' AND NOT granted \
           AND classid::int = $1 AND objid::int = $2",
        &[&QUEUE_LOCK_NAMESPACE, &user_id],
    )
    .await
    .unwrap()
    .get(0)
}

/// Spin (no sleeps) until at least `expected` sessions wait on the queue lock,
/// then return. The wait is recorded synchronously with the lock statement, so
/// the condition is deterministic and contains no elapsed-time window.
async fn wait_for_queue_lock_waiters(conn: &Conn, user_id: i32, expected: i64) {
    for _ in 0..1_000_000 {
        if queue_lock_waiters(conn, user_id).await >= expected {
            return;
        }
        tokio::task::yield_now().await;
    }
    panic!("expected {expected} queue-lock waiters");
}

async fn register_user(state: &Arc<AppState>, username: &str) -> (String, String, i32) {
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/auth/register")
                .header(
                    "x-forwarded-for",
                    format!(
                        "2001:db8::{:x}",
                        NEXT_TEST_CLIENT.fetch_add(1, Ordering::Relaxed)
                    ),
                )
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(
                    json!({
                        "username": username,
                        "email": format!("{username}@example.com"),
                        "password": "correct-horse-battery"
                    })
                    .to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let csrf = response
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .filter_map(|cookie| cookie.to_str().ok())
        .find_map(|cookie| cookie.strip_prefix("csrf_token="))
        .and_then(|cookie| cookie.split(';').next())
        .expect("csrf cookie")
        .to_owned();
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let token = body["access_token"].as_str().unwrap().to_owned();
    let user_id: i32 = state
        .pool
        .get()
        .await
        .unwrap()
        .query_one("SELECT id FROM users WHERE username = $1", &[&username])
        .await
        .unwrap()
        .get(0);
    (token, csrf, user_id)
}

async fn send(state: &Arc<AppState>, request: Request<Body>) -> (StatusCode, Value) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

fn delete(path: &str, token: &str, csrf: &str) -> Request<Body> {
    Request::builder()
        .method("DELETE")
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"))
        .body(Body::empty())
        .unwrap()
}

#[tokio::test]
async fn delete_thread_removes_events_and_reading_order_items() {
    let (state, token, csrf, user_id, _guard) = setup_user("thread-delete-fk").await;
    let conn = state.pool.get().await.unwrap();

    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, created_at) \
             VALUES ($1, 'Comic', 1, 1, 'active', $2, NOW()) RETURNING id",
            &[&"Paper Girls QA Edit", &user_id],
        )
        .await
        .unwrap()
        .get(0);

    // Events referencing the thread previously blocked deletion with
    // events_thread_id_fkey; include a pending-roll style event and a rating.
    conn.execute(
        "INSERT INTO events (type, timestamp, user_id, thread_id, selected_thread_id) \
         VALUES ('roll', NOW(), $1, $2, $2)",
        &[&user_id, &thread_id],
    )
    .await
    .unwrap();
    conn.execute(
        "INSERT INTO events (type, timestamp, user_id, thread_id, rating) \
         VALUES ('rate', NOW(), $1, $2, 4.0::float8)",
        &[&user_id, &thread_id],
    )
    .await
    .unwrap();

    // reading_order_items.thread_id has no ON DELETE cascade in the schema, so
    // thread deletion must remove it explicitly.
    let reading_order_id: i32 = conn
        .query_one(
            "INSERT INTO reading_orders (name, user_id) VALUES ($1, $2) RETURNING id",
            &[&"QA list", &user_id],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO reading_order_items (reading_order_id, thread_id, position) \
         VALUES ($1, $2, 1)",
        &[&reading_order_id, &thread_id],
    )
    .await
    .unwrap();

    let (status, body) = send(
        &state,
        delete(&format!("/api/v1/threads/{thread_id}"), &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");

    let thread_count: i64 = conn
        .query_one("SELECT count(*) FROM threads WHERE id = $1", &[&thread_id])
        .await
        .unwrap()
        .get(0);
    assert_eq!(thread_count, 0, "thread row must be deleted");

    let event_count: i64 = conn
        .query_one(
            "SELECT count(*) FROM events WHERE thread_id = $1",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        event_count, 0,
        "events referencing the thread must be removed"
    );

    let item_count: i64 = conn
        .query_one(
            "SELECT count(*) FROM reading_order_items WHERE thread_id = $1",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        item_count, 0,
        "reading order entries for the deleted thread must be removed"
    );

    let delete_audit_count: i64 = conn
        .query_one(
            "SELECT count(*) FROM events WHERE user_id = $1 AND type = 'delete' AND thread_id IS NULL",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        delete_audit_count, 1,
        "a delete audit event should be recorded"
    );
}

#[tokio::test]
async fn delete_thread_not_found_returns_404() {
    let (state, token, csrf, _user_id, _guard) = setup_user("thread-delete-404").await;
    let (status, _body) = send(&state, delete("/api/v1/threads/999999", &token, &csrf)).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

/// Reproduce the production-only schema drift that caused #5461: the
/// `events.thread_id` FK lacked `ON DELETE CASCADE`, so a plain thread delete
/// failed with `events_thread_id_fkey`. The explicit event cleanup must make the
/// delete succeed even against this non-cascading schema; removing that cleanup
/// makes this test fail with a 400 FK violation.
#[tokio::test]
async fn delete_thread_removes_non_cascading_event_reference() {
    // Acquire the shared-schema test lock first so the DDL below cannot race a
    // sibling test in the same binary.
    let (state, token, csrf, user_id, _guard) = setup_user("thread-delete-nocascade").await;
    let admin = admin_connection().await;
    set_events_thread_fk_cascade(&admin, false).await;

    let conn = state.pool.get().await.unwrap();
    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, created_at) \
             VALUES ('Noncascading events', 'Comic', 0, 1, 'active', $1, NOW()) RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO events (type, timestamp, user_id, thread_id) \
         VALUES ('rate', NOW(), $1, $2)",
        &[&user_id, &thread_id],
    )
    .await
    .unwrap();

    let (status, body) = send(
        &state,
        delete(&format!("/api/v1/threads/{thread_id}"), &token, &csrf),
    )
    .await;
    let event_count: i64 = conn
        .query_one(
            "SELECT count(*) FROM events WHERE thread_id = $1",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get(0);
    let thread_count: i64 = conn
        .query_one("SELECT count(*) FROM threads WHERE id = $1", &[&thread_id])
        .await
        .unwrap()
        .get(0);

    // Restore the canonical constraint before asserting, so a failed assertion
    // never leaves the shared schema in the non-cascading test condition.
    set_events_thread_fk_cascade(&admin, true).await;

    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");
    assert_eq!(
        event_count, 0,
        "explicit cleanup must remove non-cascading event references"
    );
    assert_eq!(thread_count, 0, "thread row must be deleted");
}

/// Delete is a changed writer: it now removes events, reading-order items and
/// continuity checkpoints before the thread row. Force a deterministic
/// interleaving against a sibling writer (update) on the same thread so a lock
/// inversion would deadlock, exactly like the update-vs-exclude regression.
#[tokio::test]
async fn delete_and_update_with_dependent_rows_do_not_deadlock() {
    let (state, token, csrf, user_id, _guard) =
        setup_user_with_pool("thread-delete-race", "8").await;
    let mut holder = state.pool.get().await.unwrap();
    let conn = state.pool.get().await.unwrap();

    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, created_at) \
             VALUES ('Race', 'Comic', 1, 1, 'active', $1, NOW()) RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    let issue_ids: Vec<i32> = conn
        .query(
            "INSERT INTO issues (thread_id, issue_number, status, created_at, position) \
             VALUES ($1, '1', 'unread', NOW(), 0), ($1, '2', 'unread', NOW(), 1) RETURNING id",
            &[&thread_id],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| row.get(0))
        .collect();
    let issue_id = issue_ids[0];
    // All three dependent-row kinds the delete writer now removes.
    conn.execute(
        "INSERT INTO events (type, timestamp, user_id, thread_id) \
         VALUES ('roll', NOW(), $1, $2)",
        &[&user_id, &thread_id],
    )
    .await
    .unwrap();
    let order_id: i32 = conn
        .query_one(
            "INSERT INTO reading_orders (name, user_id) VALUES ('Race list', $1) RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO reading_order_items (reading_order_id, thread_id, position) \
         VALUES ($1, $2, 1)",
        &[&order_id, &thread_id],
    )
    .await
    .unwrap();
    conn.execute(
        "INSERT INTO continuity_rules (user_id, source_type, source_id, target_type, target_id, \
             satisfaction_type, checkpoint_issue_id, created_at, updated_at) \
         VALUES ($1, 'issue', $2, 'issue', $3, 'checkpoint', $2, NOW(), NOW())",
        &[&user_id, &issue_id, &issue_ids[1]],
    )
    .await
    .unwrap();

    // Hold the queue advisory lock first, as every sibling writer does, so the
    // two requests park in a deterministic order instead of racing at random.
    let hold = holder.transaction().await.unwrap();
    hold.execute(
        "SELECT pg_advisory_xact_lock($1, $2)",
        &[&QUEUE_LOCK_NAMESPACE, &user_id],
    )
    .await
    .unwrap();

    let delete = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                delete(&format!("/api/v1/threads/{thread_id}"), &token, &csrf),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, user_id, 1).await;
    let update = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                Request::builder()
                    .method("PUT")
                    .uri(format!("/api/v1/threads/{thread_id}"))
                    .header(header::AUTHORIZATION, format!("Bearer {token}"))
                    .header("x-csrf-token", &csrf)
                    .header(header::COOKIE, format!("csrf_token={csrf}"))
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(json!({"issues_remaining": 2}).to_string()))
                    .unwrap(),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, user_id, 2).await;
    hold.commit().await.unwrap();

    let (d, u) = tokio::join!(delete, update);
    let (d_status, d_body) = d.expect("delete task");
    let (u_status, u_body) = u.expect("update task");
    assert_eq!(
        d_status,
        StatusCode::NO_CONTENT,
        "delete deadlocked or errored: {d_status} {d_body:?}"
    );
    assert_ne!(
        u_status,
        StatusCode::INTERNAL_SERVER_ERROR,
        "update deadlocked or errored: {u_status} {u_body:?}"
    );
    assert!(
        matches!(u_status, StatusCode::OK | StatusCode::NOT_FOUND),
        "unexpected update status: {u_status} {u_body:?}"
    );

    let thread_count: i64 = conn
        .query_one("SELECT count(*) FROM threads WHERE id = $1", &[&thread_id])
        .await
        .unwrap()
        .get(0);
    assert_eq!(thread_count, 0, "thread must be deleted after the race");
    for (label, sql) in [
        ("events", "SELECT count(*) FROM events WHERE thread_id = $1"),
        (
            "reading_order_items",
            "SELECT count(*) FROM reading_order_items WHERE thread_id = $1",
        ),
    ] {
        let count: i64 = conn.query_one(sql, &[&thread_id]).await.unwrap().get(0);
        assert_eq!(count, 0, "{label} must be removed after the race");
    }
}
