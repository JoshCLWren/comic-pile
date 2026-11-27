#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Handler-level HTTP regressions for the canonical v2 Thread custom methods
//! (issue #5704).
//!
//! Covers the AIP-136 `POST /api/v2/threads/{thread_id}:reactivate` operation:
//! - path-scoped reactivation adds exactly the requested unread issues once
//! - existing issue rows, ratings and the rest of the active queue are preserved
//! - reader ownership, non-completed threads and custom-method dispatch errors
//! - bounded validation runs before any queue or issue write
//! - two concurrent reactivations cannot double-add issues
//!
//! The final test pins the exclusion/restoration boundary: deliberate v2 queue
//! exclusions are durable and reader-owned, and never clear prerequisite
//! blocking (`is_blocked`).
//!
//! Every test drives the mounted router against the canonical disposable
//! PostgreSQL schema and hard-fails without `RUST_ROLL_TEST_DATABASE_URL`.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, test_support, AppState};
use serde_json::{json, Value};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use tower::ServiceExt;

static NEXT_TEST_CLIENT: AtomicUsize = AtomicUsize::new(1);

fn unique_suffix() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos()
}

struct Ctx {
    state: Arc<AppState>,
    token: String,
    csrf: String,
    user_id: i32,
    _guard: tokio::sync::MutexGuard<'static, ()>,
}

async fn setup(prefix: &str) -> Ctx {
    setup_with_pool(prefix, "2").await
}

async fn setup_with_pool(prefix: &str, pool_size: &str) -> Ctx {
    let url = comicpile_roll_service::test_support::database_url().await;
    let state = Arc::new(test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-threads-v2-secret".into()),
            "RUST_ROLL_POOL_SIZE" => Some(pool_size.to_owned()),
            _ => None,
        })
        .unwrap(),
    ));
    let guard = comicpile_roll_service::test_support::reset_for_test(&state).await;
    let username = format!("{prefix}-{}-{}", std::process::id(), unique_suffix());
    let (token, csrf, user_id) = register_user(&state, &username).await;
    Ctx {
        state,
        token,
        csrf,
        user_id,
        _guard: guard,
    }
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
        .unwrap_or_else(|| panic!("csrf cookie missing (status {status})"))
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

async fn second_user(ctx: &Ctx) -> i32 {
    register_user(
        &ctx.state,
        &format!("other-{}-{}", std::process::id(), unique_suffix()),
    )
    .await
    .2
}

async fn send(state: &Arc<AppState>, request: Request<Body>) -> (StatusCode, Value) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 256 * 1024).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

fn authed(method: &str, path: &str, token: &str, csrf: &str, body: Option<Value>) -> Request<Body> {
    let builder = Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"));
    match body {
        Some(body) => builder
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(body.to_string()))
            .unwrap(),
        None => builder.body(Body::empty()).unwrap(),
    }
}

async fn call(ctx: &Ctx, method: &str, path: &str, body: Option<Value>) -> (StatusCode, Value) {
    send(
        &ctx.state,
        authed(method, path, &ctx.token, &ctx.csrf, body),
    )
    .await
}

async fn reactivate(ctx: &Ctx, thread_id: i32, issues_to_add: i32) -> (StatusCode, Value) {
    call(
        ctx,
        "POST",
        &format!("/api/v2/threads/{thread_id}:reactivate"),
        Some(json!({"issues_to_add": issues_to_add})),
    )
    .await
}

async fn seed_thread(
    ctx: &Ctx,
    user_id: i32,
    title: &str,
    status: &str,
    queue_position: i32,
    remaining: i32,
) -> i32 {
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position,
                                  status, manual_creator_credits, is_test, is_blocked,
                                  queue_position_is_manual, created_at)
             VALUES ($1, $2, 'Comic', $3, $4, $5, '[]'::json, false, false, false, NOW())
             RETURNING id",
            &[&user_id, &title, &remaining, &queue_position, &status],
        )
        .await
        .unwrap()
        .get(0)
}

async fn seed_issue(ctx: &Ctx, thread_id: i32, number: &str, position: i32, status: &str) -> i32 {
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, status, position, created_at)
             VALUES ($1, $2, $3, $4, NOW()) RETURNING id",
            &[&thread_id, &number, &status, &position],
        )
        .await
        .unwrap()
        .get(0)
}

/// Give a thread issue rows and mark it completed with no unread issues left.
async fn completed_tracked_thread(ctx: &Ctx, title: &str, statuses: &[&str]) -> (i32, Vec<i32>) {
    let thread = seed_thread(ctx, ctx.user_id, title, "completed", 0, 0).await;
    let mut ids = Vec::new();
    for (index, status) in statuses.iter().enumerate() {
        ids.push(
            seed_issue(
                ctx,
                thread,
                &(index + 1).to_string(),
                index as i32 + 1,
                status,
            )
            .await,
        );
    }
    let total = statuses.len() as i32;
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE threads SET total_issues = $2, issues_remaining = 0,
                    next_unread_issue_id = NULL, reading_progress = 'completed'
             WHERE id = $1",
            &[&thread, &total],
        )
        .await
        .unwrap();
    (thread, ids)
}

async fn active_positions(ctx: &Ctx, user_id: i32) -> Vec<(i32, i32)> {
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .query(
            "SELECT id, queue_position FROM threads
             WHERE user_id = $1 AND status = 'active' AND queue_position >= 1
             ORDER BY queue_position, id",
            &[&user_id],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect()
}

async fn issue_rows(ctx: &Ctx, thread_id: i32) -> Vec<(String, i32, String)> {
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .query(
            "SELECT issue_number, position, status FROM issues
             WHERE thread_id = $1 ORDER BY position, id",
            &[&thread_id],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| (row.get(0), row.get(1), row.get(2)))
        .collect()
}

async fn is_blocked(ctx: &Ctx, thread_id: i32) -> bool {
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "SELECT is_blocked FROM threads WHERE id = $1",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get(0)
}

#[tokio::test]
async fn reactivate_v2_requeues_at_front_and_adds_exactly_the_requested_issues() {
    let ctx = setup("v2reactadd").await;
    let first = seed_thread(&ctx, ctx.user_id, "First", "active", 1, 2).await;
    let second = seed_thread(&ctx, ctx.user_id, "Second", "active", 2, 2).await;
    let (done, existing) = completed_tracked_thread(&ctx, "Done", &["read", "read"]).await;

    // A stored rating on an already-read issue must survive reactivation.
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "INSERT INTO events (type, timestamp, user_id, thread_id, issue_id, rating)
             VALUES ('rate', NOW(), $1, $2, $3, 4.5)",
            &[&ctx.user_id, &done, &existing[0]],
        )
        .await
        .unwrap();

    let (status, body) = reactivate(&ctx, done, 2).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["id"], done);
    assert_eq!(body["status"], "active");
    assert_eq!(body["queue_position"], 1);
    assert_eq!(body["total_issues"], 4);
    assert_eq!(body["issues_remaining"], 2);
    assert_eq!(body["reading_progress"], "in_progress");
    assert_eq!(body["next_unread_issue_number"], "3");
    assert_ne!(body["next_unread_issue_id"], existing[0]);
    assert_eq!(
        active_positions(&ctx, ctx.user_id).await,
        vec![(done, 1), (first, 2), (second, 3)]
    );
    assert_eq!(
        issue_rows(&ctx, done).await,
        vec![
            ("1".into(), 1, "read".into()),
            ("2".into(), 2, "read".into()),
            ("3".into(), 3, "unread".into()),
            ("4".into(), 4, "unread".into()),
        ]
    );
    let rating: f64 = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "SELECT rating FROM events WHERE user_id = $1 AND issue_id = $2",
            &[&ctx.user_id, &existing[0]],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(rating, 4.5, "existing rating/history must be preserved");

    // A second call cannot add the same issues twice: the thread is active now.
    let (status, body) = reactivate(&ctx, done, 2).await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body:?}");
    assert_eq!(body["detail"], format!("Thread {done} is not completed"));
    assert_eq!(issue_rows(&ctx, done).await.len(), 4);
    assert_eq!(
        active_positions(&ctx, ctx.user_id).await,
        vec![(done, 1), (first, 2), (second, 3)]
    );
}

#[tokio::test]
async fn reactivate_v2_requires_tracked_issue_rows_for_the_requested_addition() {
    let ctx = setup("v2reactseries").await;
    let (done, _) = completed_tracked_thread(&ctx, "Tracked", &[]).await;
    let (status, body) = reactivate(&ctx, done, 3).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["total_issues"], 3);
    assert_eq!(body["issues_remaining"], 3);
    assert_eq!(body["next_unread_issue_number"], "1");
    assert_eq!(
        issue_rows(&ctx, done).await,
        vec![
            ("1".into(), 1, "unread".into()),
            ("2".into(), 2, "unread".into()),
            ("3".into(), 3, "unread".into()),
        ],
        "generate_series must materialize exactly the requested rows"
    );
}

#[tokio::test]
async fn reactivate_v2_rejects_foreign_threads_non_completed_threads_and_unknown_actions() {
    let ctx = setup("v2reactreject").await;
    let active = seed_thread(&ctx, ctx.user_id, "Active", "active", 1, 2).await;
    let (status, body) = reactivate(&ctx, active, 1).await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body:?}");
    assert_eq!(body["detail"], format!("Thread {active} is not completed"));

    let foreign = second_user(&ctx).await;
    let theirs = seed_thread(&ctx, foreign, "Theirs", "completed", 0, 0).await;
    let (status, _) = reactivate(&ctx, theirs, 2).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(issue_rows(&ctx, theirs).await, vec![]);

    for path in [
        format!("/api/v2/threads/{active}:unknownAction"),
        format!("/api/v2/threads/{active}"),
    ] {
        let (status, body) = call(&ctx, "POST", &path, Some(json!({"issues_to_add": 1}))).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{path}: {body:?}");
    }
}

#[tokio::test]
async fn reactivate_v2_validation_fails_before_any_write() {
    let ctx = setup("v2reactval").await;
    let active = seed_thread(&ctx, ctx.user_id, "Active", "active", 1, 2).await;
    let (done, _) = completed_tracked_thread(&ctx, "Done", &["read"]).await;
    let positions_before = active_positions(&ctx, ctx.user_id).await;
    let issues_before = issue_rows(&ctx, done).await;

    let (status, body) = reactivate(&ctx, done, 0).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
    assert_eq!(body["detail"], "Validation failed");
    assert_eq!(
        body["errors"][0]["message"],
        "Input should be greater than 0"
    );

    let (status, body) = reactivate(&ctx, done, 10_001).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
    assert_eq!(body["detail"], "Validation failed");

    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v2/threads/{done}:reactivate"),
        Some(json!({})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");

    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v2/threads/not-a-number:reactivate",
        Some(json!({"issues_to_add": 1})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
    assert_eq!(body["detail"], "Validation failed");

    assert_eq!(issue_rows(&ctx, done).await, issues_before);
    assert_eq!(active_positions(&ctx, ctx.user_id).await, positions_before);
    assert_eq!(active_positions(&ctx, ctx.user_id).await, vec![(active, 1)]);
}

/// Both requests serialize on the per-reader queue advisory lock. Exactly one
/// reactivation may win; the loser sees the now-active thread and neither
/// request can insert a duplicate set of issues.
#[tokio::test]
async fn concurrent_reactivate_v2_requests_add_issues_once() {
    let ctx = setup_with_pool("v2reactconcurrent", "4").await;
    let (done, _) = completed_tracked_thread(&ctx, "Done", &["read"]).await;
    let (first, second) = tokio::join!(reactivate(&ctx, done, 3), reactivate(&ctx, done, 3));
    let statuses = [first.0, second.0];
    assert_eq!(
        statuses
            .iter()
            .filter(|status| **status == StatusCode::OK)
            .count(),
        1,
        "one request must win: {first:?} {second:?}"
    );
    assert_eq!(
        statuses
            .iter()
            .filter(|status| **status == StatusCode::BAD_REQUEST)
            .count(),
        1,
        "the loser must see a non-completed thread: {first:?} {second:?}"
    );
    assert_eq!(issue_rows(&ctx, done).await.len(), 4);
}

/// A direct "Remove from Queue" has no container provenance: it excludes the
/// owned thread durably without inventing a group, keeps its issue rows and
/// blocking state, and is reversible through the same v2 resource.
#[tokio::test]
async fn v2_direct_exclusion_needs_no_source_group_and_preserves_issue_rows() {
    let ctx = setup("v2directexcl").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Direct", "active", 1, 2).await;
    let first = seed_issue(&ctx, thread, "1", 1, "unread").await;
    seed_issue(&ctx, thread, "2", 2, "unread").await;
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE threads SET total_issues = 2, issues_remaining = 2,
                    next_unread_issue_id = $2, reading_progress = 'not_started',
                    is_blocked = true WHERE id = $1",
            &[&thread, &first],
        )
        .await
        .unwrap();

    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v2/queue-exclusions",
        Some(json!({"thread_ids": [thread]})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["excluded_thread_ids"], json!([thread]));
    assert!(
        body["group"].is_null(),
        "no source means no provenance group"
    );

    let row: (String, i32) = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "SELECT status, queue_position FROM threads WHERE id = $1",
            &[&thread],
        )
        .await
        .unwrap();
    assert_eq!(row, ("excluded".to_string(), 0));
    assert!(is_blocked(&ctx, thread).await);
    assert_eq!(
        issue_rows(&ctx, thread).await,
        vec![
            ("1".into(), 1, "unread".into()),
            ("2".into(), 2, "unread".into()),
        ]
    );

    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v2/queue-exclusions/restore",
        Some(json!({"thread_ids": [thread]})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["restored_thread_ids"], json!([thread]));
    let status: String = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query_one("SELECT status FROM threads WHERE id = $1", &[&thread])
        .await
        .unwrap()
        .get(0);
    assert_eq!(status, "active");
    assert!(is_blocked(&ctx, thread).await);
    assert_eq!(
        issue_rows(&ctx, thread).await,
        vec![
            ("1".into(), 1, "unread".into()),
            ("2".into(), 2, "unread".into()),
        ]
    );
}

/// Intentional exclusion is a durable queue state, not prerequisite blocking.
/// A blocked thread stays blocked when it is excluded and restored, and a
/// foreign thread id is never touched by the reader's exclusion request.
#[tokio::test]
async fn v2_queue_exclusions_are_reader_owned_and_do_not_clear_blocking() {
    let ctx = setup("v2exclblocking").await;
    let mine = seed_thread(&ctx, ctx.user_id, "Mine", "active", 1, 1).await;
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE threads SET is_blocked = true WHERE id = $1",
            &[&mine],
        )
        .await
        .unwrap();
    let foreign = second_user(&ctx).await;
    let theirs = seed_thread(&ctx, foreign, "Theirs", "active", 1, 1).await;

    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v2/queue-exclusions",
        Some(json!({
            "thread_ids": [mine, theirs],
            "source": {"kind": "reading_list", "id": 1, "name": "Queue"}
        })),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["excluded_thread_ids"], json!([mine]));
    assert!(
        is_blocked(&ctx, mine).await,
        "exclusion must not clear blocking"
    );

    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v2/queue-exclusions/status:check",
        Some(json!({"thread_ids": [mine, theirs]})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["excluded_thread_ids"], json!([mine]));
    assert_eq!(body["active_thread_ids"], json!([]));

    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v2/queue-exclusions/restore",
        Some(json!({"thread_ids": [mine]})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["restored_thread_ids"], json!([mine]));
    assert!(
        is_blocked(&ctx, mine).await,
        "restore must not clear blocking"
    );
    assert!(!is_blocked(&ctx, theirs).await);
}
