#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Handler-level HTTP regressions for the same-path native Thread lifecycle
//! routes (#4832 part A).
//!
//! Every test drives the mounted router against the canonical disposable
//! PostgreSQL schema and hard-fails without `RUST_ROLL_TEST_DATABASE_URL`.
//! The frozen Python handlers (`app/api/thread.py`,
//! `app/services/thread_service.py`) are the behavioral oracle.

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

/// Queue advisory-lock namespace mirrored from `queue::QUEUE_LOCK_NAMESPACE`.
const QUEUE_LOCK_NAMESPACE: i32 = 699001;
type Conn = deadpool_postgres::Object;

/// Number of sessions currently waiting on this reader's queue advisory lock.
async fn queue_lock_waiters(conn: &Conn, user_id: i32) -> i64 {
    conn.query_one(
        "SELECT count(*) FROM pg_locks
         WHERE locktype = 'advisory' AND NOT granted
           AND classid::int = $1 AND objid::int = $2",
        &[&QUEUE_LOCK_NAMESPACE, &user_id],
    )
    .await
    .unwrap()
    .get(0)
}

/// Block until at least `expected` sessions wait on the queue lock. This spins
/// on `yield_now` rather than sleeping: PostgreSQL records a lock wait the
/// moment the request issues its lock statement, so the condition is
/// guaranteed to become true and no elapsed-time window is involved. The bound
/// only fails a hung run. Matches the sibling lock-order tests in
/// `thread_issues_v1_http.rs`.
async fn wait_for_queue_lock_waiters(conn: &Conn, user_id: i32, expected: i64) {
    for _ in 0..1_000_000 {
        if queue_lock_waiters(conn, user_id).await >= expected {
            return;
        }
        tokio::task::yield_now().await;
    }
    panic!("expected {expected} queue-lock waiters");
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

/// Same fixture as `setup`, with a larger pool for deterministic multi-writer
/// lock tests (a lock holder plus two in-flight requests need three sockets).
async fn setup_with_pool(prefix: &str, pool_size: &str) -> Ctx {
    let url = comicpile_roll_service::test_support::database_url().await;
    let state = Arc::new(test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-thread-lifecycle-secret".into()),
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

async fn second_user(ctx: &Ctx) -> (String, String, i32) {
    register_user(
        &ctx.state,
        &format!("other-{}-{}", std::process::id(), unique_suffix()),
    )
    .await
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

/// Make a seeded thread an issue-tracked thread with `unread` issues.
async fn track(ctx: &Ctx, thread_id: i32, statuses: &[&str]) -> Vec<i32> {
    let mut ids = Vec::new();
    for (index, status) in statuses.iter().enumerate() {
        ids.push(
            seed_issue(
                ctx,
                thread_id,
                &(index + 1).to_string(),
                index as i32 + 1,
                status,
            )
            .await,
        );
    }
    let unread: Vec<i32> = statuses
        .iter()
        .zip(&ids)
        .filter(|(status, _)| **status == "unread")
        .map(|(_, id)| *id)
        .collect();
    let total = statuses.len() as i32;
    let remaining = unread.len() as i32;
    let next = unread.first().copied();
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE threads SET total_issues = $2, issues_remaining = $3,
                    next_unread_issue_id = $4, reading_progress = 'in_progress'
             WHERE id = $1",
            &[&thread_id, &total, &remaining, &next],
        )
        .await
        .unwrap();
    ids
}

async fn thread_row(ctx: &Ctx, thread_id: i32) -> Option<(String, i32, bool)> {
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .query_opt(
            "SELECT status, queue_position, queue_position_is_manual FROM threads WHERE id = $1",
            &[&thread_id],
        )
        .await
        .unwrap()
        .map(|row| (row.get(0), row.get(1), row.get(2)))
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

fn keys(value: &Value) -> Vec<&str> {
    value
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect()
}

// ---------------------------------------------------------------------------
// auth / CSRF
// ---------------------------------------------------------------------------

#[tokio::test]
async fn every_lifecycle_route_requires_auth() {
    let ctx = setup("lcauth").await;
    let routes = [
        ("POST", "/api/v1/threads/"),
        ("POST", "/api/v1/threads/check-duplicates"),
        ("GET", "/api/v1/threads/excluded/threads"),
        ("POST", "/api/v1/threads/groups:batch"),
        ("POST", "/api/v1/threads/reactivate"),
        ("GET", "/api/v1/threads/stale"),
        ("DELETE", "/api/v1/threads/1"),
        ("PUT", "/api/v1/threads/1"),
        ("POST", "/api/v1/threads/1/exclude"),
        ("POST", "/api/v1/threads/1/restore"),
        ("POST", "/api/v1/threads/1/set-pending"),
        // Same-path Rust replacements must be mounted in the production
        // router: an anonymous request must hit the auth extractor (401),
        // never the inner router's JSON 404 fallback.
        ("PUT", "/api/v1/threads/1/test-backdate"),
        ("GET", "/api/v1/threads/1/issues/creators"),
    ];
    for (method, path) in routes {
        let (status, body) = send(
            &ctx.state,
            Request::builder()
                .method(method)
                .uri(path)
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from("{}"))
                .unwrap(),
        )
        .await;
        assert_eq!(
            status,
            StatusCode::UNAUTHORIZED,
            "{method} {path}: {body:?}"
        );
    }
}

#[tokio::test]
async fn mutations_require_a_csrf_token() {
    // csrf_middleware skips all checks when TEST_ENVIRONMENT=true. Serialize
    // with the backdate tests (which set that process-global flag) and pin it
    // off for this test so a concurrent backdate case cannot flip it mid-flight.
    let _env_guard = TEST_ENV_LOCK.lock().await;
    let _restore = EnvRestore(std::env::var_os("TEST_ENVIRONMENT"));
    std::env::remove_var("TEST_ENVIRONMENT");
    let ctx = setup("lccsrf").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Csrf", "active", 1, 3).await;
    let (status, body) = send(
        &ctx.state,
        Request::builder()
            .method("DELETE")
            .uri(format!("/api/v1/threads/{thread}"))
            .header(header::AUTHORIZATION, format!("Bearer {}", ctx.token))
            .body(Body::empty())
            .unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "{body:?}");
    assert!(thread_row(&ctx, thread).await.is_some());
}

// ---------------------------------------------------------------------------
// create
// ---------------------------------------------------------------------------

#[tokio::test]
async fn create_returns_201_in_python_field_order_at_queue_end() {
    let ctx = setup("lccreate").await;
    let first = seed_thread(&ctx, ctx.user_id, "Existing", "active", 1, 2).await;
    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v1/threads/",
        Some(json!({
            "title": "Saga",
            "format": "comics",
            "issues_remaining": 4,
            "notes": "  keep ",
            "manual_creator_credits": [
                {"name": "  Brian   K. Vaughan ", "roles": ["Writer", "Writer"], "extra": 1},
                {"name": " "}
            ]
        })),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    assert_eq!(
        keys(&body),
        vec![
            "blocking_reasons",
            "created_at",
            "format",
            "id",
            "is_blocked",
            "is_test",
            "issues_remaining",
            "last_activity_at",
            "last_rating",
            "manual_creator_credits",
            "next_unread_issue_id",
            "next_unread_issue_number",
            "notes",
            "queue_position",
            "reading_progress",
            "status",
            "title",
            "total_issues"
        ]
    );
    assert_eq!(body["format"], "Comic");
    assert_eq!(body["status"], "active");
    assert_eq!(body["queue_position"], 2);
    assert_eq!(body["issues_remaining"], 4);
    assert_eq!(body["notes"], "  keep ");
    assert_eq!(body["is_blocked"], false);
    assert_eq!(body["last_rating"], Value::Null);
    assert_eq!(
        body["manual_creator_credits"],
        json!([{"name": "Brian K. Vaughan", "roles": ["Writer"]}])
    );
    assert!(body["created_at"].as_str().unwrap().ends_with('Z'));
    let id = body["id"].as_i64().unwrap() as i32;
    assert_ne!(id, first);
    let (stored_status, position, manual) = thread_row(&ctx, id).await.unwrap();
    assert_eq!(
        (stored_status.as_str(), position, manual),
        ("active", 2, false)
    );
}

#[tokio::test]
async fn create_merges_a_double_submit_into_the_first_thread() {
    let ctx = setup("lcdupe").await;
    let payload = json!({"title": "Double Click", "format": "Comic", "issues_remaining": 3});
    let (first_status, first) = call(&ctx, "POST", "/api/v1/threads/", Some(payload.clone())).await;
    let (second_status, second) = call(
        &ctx,
        "POST",
        "/api/v1/threads/",
        Some(json!({"title": "double click", "format": "comics", "issues_remaining": 3})),
    )
    .await;
    assert_eq!(first_status, StatusCode::CREATED);
    assert_eq!(second_status, StatusCode::CREATED);
    assert_eq!(first["id"], second["id"]);
    let count: i64 = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "SELECT count(*) FROM threads WHERE user_id = $1",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(count, 1);
}

#[tokio::test]
async fn create_with_total_issues_reports_the_unread_issue_count() {
    let ctx = setup("lctracked").await;
    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v1/threads/",
        Some(
            json!({"title": "Tracked", "format": "Digital", "issues_remaining": 5,
                    "total_issues": 5, "is_test": true}),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    // No issue rows exist yet, so the tracked unread count is zero (Python parity).
    assert_eq!(body["issues_remaining"], 0);
    assert_eq!(body["total_issues"], 5);
    assert_eq!(body["is_test"], true);
}

#[tokio::test]
async fn create_validation_matches_the_fastapi_422_envelope() {
    let ctx = setup("lcvalid").await;
    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v1/threads/",
        Some(
            json!({"title": "   ", "format": "", "issues_remaining": -1, "total_issues": 0,
                    "is_test": "perhaps", "manual_creator_credits": ["x"]}),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
    assert_eq!(body["detail"], "Validation failed");
    let errors = body["errors"].as_array().unwrap();
    let fields: Vec<(&str, &str, &str)> = errors
        .iter()
        .map(|error| {
            (
                error["field"].as_str().unwrap(),
                error["type"].as_str().unwrap(),
                error["message"].as_str().unwrap(),
            )
        })
        .collect();
    assert_eq!(
        fields,
        vec![
            (
                "body.title",
                "value_error",
                "Value error, Title cannot be empty or whitespace only"
            ),
            (
                "body.format",
                "string_too_short",
                "String should have at least 1 character"
            ),
            (
                "body.issues_remaining",
                "greater_than_equal",
                "Input should be greater than or equal to 0"
            ),
            (
                "body.total_issues",
                "greater_than_equal",
                "Input should be greater than or equal to 1"
            ),
            (
                "body.manual_creator_credits.0",
                "dict_type",
                "Input should be a valid dictionary"
            ),
            (
                "body.is_test",
                "bool_parsing",
                "Input should be a valid boolean, unable to interpret input"
            ),
        ]
    );
    assert_eq!(body["body"]["title"], "   ");

    let (missing_status, missing) = call(&ctx, "POST", "/api/v1/threads/", None).await;
    assert_eq!(missing_status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(missing["errors"][0]["field"], "body");
    assert_eq!(missing["errors"][0]["type"], "missing");

    let count: i64 = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query_one("SELECT count(*) FROM threads", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(count, 0, "rejected requests must not write");
}

// ---------------------------------------------------------------------------
// update
// ---------------------------------------------------------------------------

#[tokio::test]
async fn update_applies_partial_fields_and_explicit_null_notes() {
    let ctx = setup("lcupdate").await;
    let id = seed_thread(&ctx, ctx.user_id, "Before", "active", 1, 2).await;
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute("UPDATE threads SET notes = 'old' WHERE id = $1", &[&id])
        .await
        .unwrap();
    let path = format!("/api/v1/threads/{id}");
    let (status, body) = call(
        &ctx,
        "PUT",
        &path,
        Some(
            json!({"title": "After", "format": "DIGITAL", "is_test": true,
                    "manual_creator_credits": [{"name": "Ed", "roles": []}]}),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["title"], "After");
    assert_eq!(body["format"], "Digital");
    assert_eq!(body["is_test"], true);
    assert_eq!(body["notes"], "old", "omitted notes stay untouched");
    assert_eq!(
        body["manual_creator_credits"],
        json!([{"name": "Ed", "roles": []}])
    );

    let (_, cleared) = call(&ctx, "PUT", &path, Some(json!({"notes": null}))).await;
    assert_eq!(cleared["notes"], Value::Null, "explicit null clears notes");
    let (_, blank) = call(&ctx, "PUT", &path, Some(json!({"notes": "   "}))).await;
    assert_eq!(
        blank["notes"],
        Value::Null,
        "blank notes are stored as NULL"
    );
}

#[tokio::test]
async fn update_issues_remaining_zero_completes_and_positive_requeues_at_the_end() {
    let ctx = setup("lcflip").await;
    let a = seed_thread(&ctx, ctx.user_id, "A", "active", 1, 3).await;
    let b = seed_thread(&ctx, ctx.user_id, "B", "active", 2, 3).await;
    let c = seed_thread(&ctx, ctx.user_id, "C", "active", 3, 3).await;
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE threads SET queue_position_is_manual = true WHERE id = $1",
            &[&b],
        )
        .await
        .unwrap();

    let (status, body) = call(
        &ctx,
        "PUT",
        &format!("/api/v1/threads/{b}"),
        Some(json!({"issues_remaining": 0})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["status"], "completed");
    assert_eq!(body["queue_position"], 0);
    assert_eq!(body["issues_remaining"], 0);
    assert_eq!(
        thread_row(&ctx, b).await.unwrap(),
        ("completed".into(), 0, false)
    );
    assert_eq!(
        active_positions(&ctx, ctx.user_id).await,
        vec![(a, 1), (c, 2)]
    );

    let (status, body) = call(
        &ctx,
        "PUT",
        &format!("/api/v1/threads/{b}"),
        Some(json!({"issues_remaining": 2})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["status"], "active");
    assert_eq!(body["queue_position"], 3);
    assert_eq!(
        active_positions(&ctx, ctx.user_id).await,
        vec![(a, 1), (c, 2), (b, 3)]
    );
}

#[tokio::test]
async fn update_leaves_excluded_status_and_tracked_counters_alone() {
    let ctx = setup("lcexcl").await;
    let excluded = seed_thread(&ctx, ctx.user_id, "Gone", "excluded", 0, 4).await;
    let (_, body) = call(
        &ctx,
        "PUT",
        &format!("/api/v1/threads/{excluded}"),
        Some(json!({"issues_remaining": 0})),
    )
    .await;
    assert_eq!(
        body["status"], "excluded",
        "derived status never ends an exclusion"
    );
    assert_eq!(body["issues_remaining"], 0);

    let tracked = seed_thread(&ctx, ctx.user_id, "Tracked", "active", 1, 0).await;
    track(&ctx, tracked, &["read", "unread", "unread"]).await;
    let (_, body) = call(
        &ctx,
        "PUT",
        &format!("/api/v1/threads/{tracked}"),
        Some(json!({"issues_remaining": 99})),
    )
    .await;
    assert_eq!(
        body["issues_remaining"], 2,
        "tracked threads ignore manual counters"
    );
    assert_eq!(body["next_unread_issue_number"], "2");
}

#[tokio::test]
async fn update_partial_put_preserves_untouched_fields_under_concurrency() {
    let ctx = setup("lcuppartial").await;
    let id = seed_thread(&ctx, ctx.user_id, "Original", "active", 1, 5).await;
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute("UPDATE threads SET notes = 'keep-me' WHERE id = $1", &[&id])
        .await
        .unwrap();
    let path = format!("/api/v1/threads/{id}");
    let (a, b) = tokio::join!(
        call(&ctx, "PUT", &path, Some(json!({"title": "Renamed"}))),
        call(&ctx, "PUT", &path, Some(json!({"notes": "changed"}))),
    );
    assert_eq!(a.0, StatusCode::OK, "{:?}", a.1);
    assert_eq!(b.0, StatusCode::OK, "{:?}", b.1);
    let (_, body) = call(&ctx, "PUT", &path, Some(json!({}))).await;
    assert_eq!(body["title"], "Renamed");
    assert_eq!(body["notes"], "changed");
    assert_eq!(body["status"], "active");
    assert_eq!(body["queue_position"], 1);
    assert_eq!(body["issues_remaining"], 5);
    assert_eq!(body["format"], "Comic");
}

#[tokio::test]
async fn update_and_exclude_do_not_deadlock() {
    for _ in 0..5 {
        let ctx = setup("lcupexdead").await;
        let id = seed_thread(&ctx, ctx.user_id, "Contended", "active", 1, 5).await;
        let update = {
            let state = ctx.state.clone();
            let token = ctx.token.clone();
            let csrf = ctx.csrf.clone();
            tokio::spawn(async move {
                send(
                    &state,
                    authed(
                        "PUT",
                        &format!("/api/v1/threads/{id}"),
                        &token,
                        &csrf,
                        Some(json!({"issues_remaining": 3})),
                    ),
                )
                .await
            })
        };
        let exclude = {
            let state = ctx.state.clone();
            let token = ctx.token.clone();
            let csrf = ctx.csrf.clone();
            tokio::spawn(async move {
                send(
                    &state,
                    authed(
                        "POST",
                        &format!("/api/v1/threads/{id}/exclude"),
                        &token,
                        &csrf,
                        None,
                    ),
                )
                .await
            })
        };
        let (u, e) = tokio::join!(update, exclude);
        let (u_status, u_body) = u.expect("update task");
        let (e_status, e_body) = e.expect("exclude task");
        assert_ne!(
            u_status,
            StatusCode::INTERNAL_SERVER_ERROR,
            "update deadlocked or errored: {u_status} {u_body:?}"
        );
        assert_ne!(
            e_status,
            StatusCode::INTERNAL_SERVER_ERROR,
            "exclude deadlocked or errored: {e_status} {e_body:?}"
        );
        assert!(
            matches!(u_status, StatusCode::OK | StatusCode::BAD_REQUEST),
            "unexpected update status: {u_status} {u_body:?}"
        );
        assert!(
            matches!(e_status, StatusCode::OK | StatusCode::BAD_REQUEST),
            "unexpected exclude status: {e_status} {e_body:?}"
        );
    }
}

#[tokio::test]
async fn update_validation_and_isolation() {
    let ctx = setup("lcupvalid").await;
    let (other_token, other_csrf, other_id) = second_user(&ctx).await;
    let theirs = seed_thread(&ctx, other_id, "Theirs", "active", 1, 2).await;
    let (status, body) = call(
        &ctx,
        "PUT",
        &format!("/api/v1/threads/{theirs}"),
        Some(json!({"title": "stolen"})),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
    assert_eq!(body["detail"], format!("Thread {theirs} not found"));
    let (_, unchanged) = send(
        &ctx.state,
        authed(
            "PUT",
            &format!("/api/v1/threads/{theirs}"),
            &other_token,
            &other_csrf,
            Some(json!({})),
        ),
    )
    .await;
    assert_eq!(unchanged["title"], "Theirs");

    let mine = seed_thread(&ctx, ctx.user_id, "Mine", "active", 1, 2).await;
    let (status, body) = call(
        &ctx,
        "PUT",
        "/api/v1/threads/not-a-number",
        Some(json!({"title": "x".repeat(201), "issues_remaining": -4})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    let fields: Vec<&str> = body["errors"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| e["field"].as_str().unwrap())
        .collect();
    assert_eq!(
        fields,
        vec!["path.thread_id", "body.title", "body.issues_remaining"]
    );
    let (_, still) = call(
        &ctx,
        "PUT",
        &format!("/api/v1/threads/{mine}"),
        Some(json!({})),
    )
    .await;
    assert_eq!(still["title"], "Mine");
}

// ---------------------------------------------------------------------------
// delete
// ---------------------------------------------------------------------------

#[tokio::test]
async fn delete_prunes_dependent_state_and_renumbers_the_queue() {
    let ctx = setup("lcdelete").await;
    let keep = seed_thread(&ctx, ctx.user_id, "Keep", "active", 1, 2).await;
    let doomed = seed_thread(&ctx, ctx.user_id, "Doomed", "active", 2, 2).await;
    let tail = seed_thread(&ctx, ctx.user_id, "Tail", "active", 3, 2).await;
    let doomed_issues = track(&ctx, doomed, &["unread", "unread"]).await;
    let keep_issues = track(&ctx, keep, &["unread", "unread"]).await;
    let pool = ctx.state.pool.get().await.unwrap();

    // Pending pointer, tags, a plan and plan-owned rules that reference the thread.
    let session: i32 = pool
        .query_one(
            "INSERT INTO sessions (user_id, started_at, start_die, pending_thread_id)
             VALUES ($1, NOW(), 6, $2) RETURNING id",
            &[&ctx.user_id, &doomed],
        )
        .await
        .unwrap()
        .get(0);
    let tag: i32 = pool
        .query_one(
            "INSERT INTO tags (name, normalized_name, scope, owner_user_id, color, created_at, updated_at)
             VALUES ('t', 't', 'user', $1, '#fff', NOW(), NOW()) RETURNING id",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    for (target_type, target_id) in [
        ("Thread", doomed),
        ("Issue", doomed_issues[0]),
        ("Thread", keep),
    ] {
        pool.execute(
            "INSERT INTO tag_assignments (tag_id, target_type, target_id, created_at)
             VALUES ($1, $2, $3, NOW())",
            &[&tag, &target_type, &target_id],
        )
        .await
        .unwrap();
    }
    let nodes = json!([
        {"id": "n1", "node_type": "thread", "ref_id": doomed, "lane_id": "main", "position": 0},
        {"id": "n2", "node_type": "issue", "ref_id": keep_issues[0], "lane_id": "main", "position": 1},
        {"id": "n3", "node_type": "issue", "ref_id": keep_issues[1], "lane_id": "main", "position": 2},
        {"id": "n4", "node_type": "issue", "ref_id": doomed_issues[1], "lane_id": "main", "position": 3}
    ]);
    let plan: i32 = pool
        .query_one(
            "INSERT INTO continuity_plans (user_id, name, ordering_mode, lanes_json, nodes_json,
                                           created_at, updated_at)
             VALUES ($1, 'Plan', 'strict_sequential', '[]'::json, $2, NOW(), NOW()) RETURNING id",
            &[&ctx.user_id, &nodes],
        )
        .await
        .unwrap()
        .get(0);
    let marker = format!("continuity-plan:{plan}");
    for (source, target, note) in [
        (keep_issues[0], doomed_issues[0], Some(marker.clone())),
        (keep_issues[0], keep_issues[1], Some(marker.clone())),
        (doomed_issues[1], keep_issues[1], None),
    ] {
        pool.execute(
            "INSERT INTO continuity_rules (user_id, source_type, source_id, target_type, target_id,
                                            satisfaction_type, note, created_at, updated_at)
             VALUES ($1, 'issue', $2, 'issue', $3, 'item_read', $4, NOW(), NOW())",
            &[&ctx.user_id, &source, &target, &note],
        )
        .await
        .unwrap();
    }
    drop(pool);

    let (status, body) = call(&ctx, "DELETE", &format!("/api/v1/threads/{doomed}"), None).await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");
    assert!(thread_row(&ctx, doomed).await.is_none());
    assert_eq!(
        active_positions(&ctx, ctx.user_id).await,
        vec![(keep, 1), (tail, 2)]
    );

    let pool = ctx.state.pool.get().await.unwrap();
    let pending: Option<i32> = pool
        .query_one(
            "SELECT pending_thread_id FROM sessions WHERE id = $1",
            &[&session],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(pending, None, "pending pointer detached");
    let assignments: i64 = pool
        .query_one("SELECT count(*) FROM tag_assignments", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        assignments, 1,
        "thread and issue assignments purged, keep's retained"
    );
    let tombstones: i64 = pool
        .query_one(
            "SELECT count(*) FROM events WHERE type = 'delete' AND user_id = $1 AND thread_id IS NULL",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(tombstones, 1);
    let stored: Value = pool
        .query_one(
            "SELECT nodes_json FROM continuity_plans WHERE id = $1",
            &[&plan],
        )
        .await
        .unwrap()
        .get(0);
    let node_ids: Vec<&str> = stored
        .as_array()
        .unwrap()
        .iter()
        .map(|n| n["id"].as_str().unwrap())
        .collect();
    assert_eq!(node_ids, vec!["n2", "n3"]);
    assert_eq!(stored[0]["position"], 0);
    assert_eq!(stored[1]["position"], 1);
    let membership: i64 = pool
        .query_one(
            "SELECT count(*) FROM reading_plan_issues WHERE plan_id = $1",
            &[&plan],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(membership, 2, "normalized plan membership rebuilt");
    let rules: Vec<(i32, i32)> = pool
        .query(
            "SELECT source_id, target_id FROM continuity_rules ORDER BY id",
            &[],
        )
        .await
        .unwrap()
        .iter()
        .map(|r| (r.get(0), r.get(1)))
        .collect();
    assert_eq!(rules, vec![(keep_issues[0], keep_issues[1])]);
}

#[tokio::test]
async fn delete_refused_by_the_database_is_a_400_and_changes_nothing() {
    let ctx = setup("lcdelref").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Referenced", "active", 1, 2).await;
    let pool = ctx.state.pool.get().await.unwrap();
    // Force the delete transaction to fail after pruning plan nodes, so the
    // handler reports "Cannot delete thread..." and rolls everything back.
    // Deleting the thread removes its plan node, leaving a malformed surviving
    // node that cannot be rebuilt.
    pool.execute(
        "INSERT INTO continuity_plans (user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at)
         VALUES ($1, 'Refusal', 'strict_sequential', $2::jsonb, $3::jsonb, NOW(), NOW())",
        &[
            &ctx.user_id,
            &json!([{"id": "main", "name": "Main", "order": 0}]),
            &json!([
                {"id": "gone", "node_type": "thread", "ref_id": thread, "lane_id": "main", "position": 0},
                {"id": "bad", "node_type": "issue"}
            ]),
        ],
    )
    .await
    .unwrap();
    drop(pool);
    let (status, body) = call(&ctx, "DELETE", &format!("/api/v1/threads/{thread}"), None).await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body:?}");
    assert!(body["detail"]
        .as_str()
        .unwrap()
        .starts_with("Cannot delete thread: "));
    assert!(thread_row(&ctx, thread).await.is_some());
    let tombstones: i64 = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query_one("SELECT count(*) FROM events WHERE type = 'delete'", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(tombstones, 0, "failed delete rolls back the tombstone");
}

/// A genuine database integrity failure (class 23) during the delete must still
/// map to Python's 400 "Cannot delete thread..." — not a 500. A different
/// user's checkpoint rule has a RESTRICT FK to the thread's issue and lies
/// outside the user-scoped cleanup, so the cascading issue delete is refused by
/// PostgreSQL itself. This keeps the `delete_error` integrity mapping covered.
#[tokio::test]
async fn delete_database_integrity_failure_is_a_400_and_changes_nothing() {
    let ctx = setup("lcdelfkdb").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Referenced", "active", 1, 1).await;
    let pool = ctx.state.pool.get().await.unwrap();
    let issue_ids: Vec<i32> = pool
        .query(
            "INSERT INTO issues (thread_id, issue_number, status, created_at, position) \
             VALUES ($1, '1', 'unread', NOW(), 0), ($1, '2', 'unread', NOW(), 1) RETURNING id",
            &[&thread],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| row.get(0))
        .collect();
    let (_, _, other_id) = second_user(&ctx).await;
    pool.execute(
        "INSERT INTO continuity_rules (user_id, source_type, source_id, target_type, target_id, \
             satisfaction_type, checkpoint_issue_id, created_at, updated_at) \
         VALUES ($1, 'issue', $2, 'issue', $3, 'checkpoint', $2, NOW(), NOW())",
        &[&other_id, &issue_ids[0], &issue_ids[1]],
    )
    .await
    .unwrap();
    drop(pool);

    let (status, body) = call(&ctx, "DELETE", &format!("/api/v1/threads/{thread}"), None).await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body:?}");
    assert!(
        body["detail"]
            .as_str()
            .unwrap()
            .starts_with("Cannot delete thread: "),
        "integrity errors must keep the Python 400 mapping: {body:?}"
    );
    assert!(thread_row(&ctx, thread).await.is_some());
    let tombstones: i64 = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query_one("SELECT count(*) FROM events WHERE type = 'delete'", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(tombstones, 0, "failed delete rolls back the tombstone");
}

#[tokio::test]
async fn delete_is_owner_scoped() {
    let ctx = setup("lcdeliso").await;
    let (_, _, other_id) = second_user(&ctx).await;
    let theirs = seed_thread(&ctx, other_id, "Theirs", "active", 1, 2).await;
    let (status, body) = call(&ctx, "DELETE", &format!("/api/v1/threads/{theirs}"), None).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
    assert_eq!(body["detail"], format!("Thread {theirs} not found"));
    assert!(thread_row(&ctx, theirs).await.is_some());
    let (status, _) = call(&ctx, "DELETE", "/api/v1/threads/999999", None).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, body) = call(&ctx, "DELETE", "/api/v1/threads/abc", None).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["errors"][0]["field"], "path.thread_id");
}

// ---------------------------------------------------------------------------
// exclude / restore / reactivate
// ---------------------------------------------------------------------------

#[tokio::test]
async fn exclude_and_restore_round_trip_with_queue_renumbering() {
    let ctx = setup("lcexres").await;
    let a = seed_thread(&ctx, ctx.user_id, "A", "active", 1, 2).await;
    let b = seed_thread(&ctx, ctx.user_id, "B", "active", 2, 2).await;
    let c = seed_thread(&ctx, ctx.user_id, "C", "active", 3, 2).await;
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE threads SET queue_position_is_manual = true WHERE id = $1",
            &[&b],
        )
        .await
        .unwrap();

    let (status, body) = call(&ctx, "POST", &format!("/api/v1/threads/{b}/exclude"), None).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["status"], "excluded");
    assert_eq!(body["queue_position"], 0);
    assert_eq!(
        thread_row(&ctx, b).await.unwrap(),
        ("excluded".into(), 0, false)
    );
    assert_eq!(
        active_positions(&ctx, ctx.user_id).await,
        vec![(a, 1), (c, 2)]
    );

    // Idempotent.
    let (status, body) = call(&ctx, "POST", &format!("/api/v1/threads/{b}/exclude"), None).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["status"], "excluded");

    let (status, body) = call(&ctx, "POST", &format!("/api/v1/threads/{b}/restore"), None).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["status"], "active");
    assert_eq!(body["queue_position"], 3);
    assert_eq!(
        active_positions(&ctx, ctx.user_id).await,
        vec![(a, 1), (c, 2), (b, 3)]
    );

    let (status, body) = call(&ctx, "POST", &format!("/api/v1/threads/{b}/restore"), None).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["detail"], format!("Thread {b} is not excluded"));
}

#[tokio::test]
async fn exclude_rejects_inactive_threads_and_foreign_threads() {
    let ctx = setup("lcexrej").await;
    let done = seed_thread(&ctx, ctx.user_id, "Done", "completed", 0, 0).await;
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{done}/exclude"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body:?}");
    assert_eq!(
        body["detail"],
        format!("Thread {done} is not active and cannot be excluded")
    );
    let (_, _, other_id) = second_user(&ctx).await;
    let theirs = seed_thread(&ctx, other_id, "Theirs", "active", 1, 2).await;
    for action in ["exclude", "restore"] {
        let (status, body) = call(
            &ctx,
            "POST",
            &format!("/api/v1/threads/{theirs}/{action}"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{action}: {body:?}");
    }
    assert_eq!(thread_row(&ctx, theirs).await.unwrap().0, "active");
}

#[tokio::test]
async fn restore_rederives_tracked_counters_and_shelves_finished_series() {
    let ctx = setup("lcrestore").await;
    let tracked = seed_thread(&ctx, ctx.user_id, "Tracked", "excluded", 0, 99).await;
    let issues = track(&ctx, tracked, &["read", "unread", "unread"]).await;
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE threads SET issues_remaining = 99, next_unread_issue_id = NULL,
                    reading_progress = 'stale' WHERE id = $1",
            &[&tracked],
        )
        .await
        .unwrap();
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{tracked}/restore"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["status"], "active");
    assert_eq!(body["issues_remaining"], 2);
    assert_eq!(body["next_unread_issue_id"], issues[1]);
    assert_eq!(body["reading_progress"], "in_progress");

    let finished = seed_thread(&ctx, ctx.user_id, "Finished", "excluded", 0, 0).await;
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{finished}/restore"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["status"], "completed");
    assert_eq!(body["queue_position"], 0);
}

#[tokio::test]
async fn reactivate_requeues_at_front_and_adds_issues() {
    let ctx = setup("lcreact").await;
    let a = seed_thread(&ctx, ctx.user_id, "A", "active", 1, 2).await;
    let done = seed_thread(&ctx, ctx.user_id, "Done", "completed", 0, 0).await;
    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v1/threads/reactivate",
        Some(json!({"thread_id": done, "issues_to_add": 3})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["status"], "active");
    assert_eq!(body["queue_position"], 1);
    assert_eq!(body["issues_remaining"], 3);
    assert_eq!(
        active_positions(&ctx, ctx.user_id).await,
        vec![(done, 1), (a, 2)]
    );

    let tracked = seed_thread(&ctx, ctx.user_id, "Tracked", "completed", 0, 0).await;
    let issues = track(&ctx, tracked, &["read", "read"]).await;
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE threads SET status = 'completed', queue_position = 0, issues_remaining = 0,
                    next_unread_issue_id = NULL, reading_progress = 'completed' WHERE id = $1",
            &[&tracked],
        )
        .await
        .unwrap();
    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v1/threads/reactivate",
        Some(json!({"thread_id": tracked, "issues_to_add": 2})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["total_issues"], 4);
    assert_eq!(body["issues_remaining"], 2);
    assert_eq!(body["reading_progress"], "in_progress");
    assert_eq!(body["next_unread_issue_number"], "3");
    assert_ne!(body["next_unread_issue_id"], issues[0]);
    let rows: Vec<(String, i32, String)> = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query(
            "SELECT issue_number, position, status FROM issues WHERE thread_id = $1 ORDER BY position",
            &[&tracked],
        )
        .await
        .unwrap()
        .iter()
        .map(|r| (r.get(0), r.get(1), r.get(2)))
        .collect();
    assert_eq!(
        rows,
        vec![
            ("1".into(), 1, "read".into()),
            ("2".into(), 2, "read".into()),
            ("3".into(), 3, "unread".into()),
            ("4".into(), 4, "unread".into()),
        ]
    );
}

#[tokio::test]
async fn reactivate_rejects_bad_requests_and_foreign_threads() {
    let ctx = setup("lcreactbad").await;
    let active = seed_thread(&ctx, ctx.user_id, "Active", "active", 1, 2).await;
    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v1/threads/reactivate",
        Some(json!({"thread_id": active, "issues_to_add": 1})),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body:?}");
    assert_eq!(body["detail"], format!("Thread {active} is not completed"));

    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v1/threads/reactivate",
        Some(json!({"thread_id": active, "issues_to_add": 0})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        body["errors"][0]["message"],
        "Input should be greater than 0"
    );

    let (_, _, other_id) = second_user(&ctx).await;
    let theirs = seed_thread(&ctx, other_id, "Theirs", "completed", 0, 0).await;
    let (status, _) = call(
        &ctx,
        "POST",
        "/api/v1/threads/reactivate",
        Some(json!({"thread_id": theirs, "issues_to_add": 2})),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(thread_row(&ctx, theirs).await.unwrap().0, "completed");
}

/// `generate_series` must produce exactly the requested rows, numbered and
/// positioned from 1 when the tracked thread has no prior issues.
#[tokio::test]
async fn reactivate_generates_exactly_three_numbered_rows_in_sql() {
    let ctx = setup("lcreactseries").await;
    let tracked = seed_thread(&ctx, ctx.user_id, "Tracked", "completed", 0, 0).await;
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE threads SET total_issues = 0, issues_remaining = 0,
                    next_unread_issue_id = NULL, reading_progress = 'completed'
             WHERE id = $1",
            &[&tracked],
        )
        .await
        .unwrap();

    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v1/threads/reactivate",
        Some(json!({"thread_id": tracked, "issues_to_add": 3})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["total_issues"], 3);
    assert_eq!(body["issues_remaining"], 3);
    assert_eq!(body["next_unread_issue_number"], "1");

    let rows: Vec<(String, i32, String)> = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query(
            "SELECT issue_number, position, status FROM issues
             WHERE thread_id = $1 ORDER BY position",
            &[&tracked],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| (row.get(0), row.get(1), row.get(2)))
        .collect();
    assert_eq!(
        rows,
        vec![
            ("1".into(), 1, "unread".into()),
            ("2".into(), 2, "unread".into()),
            ("3".into(), 3, "unread".into()),
        ],
        "generate_series must materialize exactly three correctly numbered rows"
    );
}

/// Counts above the coordinator-approved 10_000 cap are rejected by validation
/// before the handler runs: no issue rows, no queue bump, no thread mutation.
#[tokio::test]
async fn reactivate_rejects_issue_count_above_cap_without_side_effects() {
    let ctx = setup("lcreactcap").await;
    let active = seed_thread(&ctx, ctx.user_id, "Active", "active", 1, 2).await;
    let tracked = seed_thread(&ctx, ctx.user_id, "Tracked", "completed", 0, 0).await;
    track(&ctx, tracked, &["read", "unread"]).await;
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE threads SET status = 'completed', queue_position = 0, issues_remaining = 0,
                    next_unread_issue_id = NULL, reading_progress = 'completed' WHERE id = $1",
            &[&tracked],
        )
        .await
        .unwrap();

    let tracked_before = thread_row(&ctx, tracked).await.unwrap();
    let active_before = thread_row(&ctx, active).await.unwrap();
    let positions_before = active_positions(&ctx, ctx.user_id).await;
    let issues_before: Vec<(String, i32, String)> = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query(
            "SELECT issue_number, position, status FROM issues
             WHERE thread_id = $1 ORDER BY position",
            &[&tracked],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| (row.get(0), row.get(1), row.get(2)))
        .collect();

    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v1/threads/reactivate",
        Some(json!({"thread_id": tracked, "issues_to_add": 10001})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
    assert_eq!(body["detail"], "Validation failed");

    assert_eq!(thread_row(&ctx, tracked).await.unwrap(), tracked_before);
    assert_eq!(thread_row(&ctx, active).await.unwrap(), active_before);
    assert_eq!(active_positions(&ctx, ctx.user_id).await, positions_before);
    let issues_after: Vec<(String, i32, String)> = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query(
            "SELECT issue_number, position, status FROM issues
             WHERE thread_id = $1 ORDER BY position",
            &[&tracked],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| (row.get(0), row.get(1), row.get(2)))
        .collect();
    assert_eq!(
        issues_after, issues_before,
        "capped request must not insert rows"
    );
}

// ---------------------------------------------------------------------------
// set-pending
// ---------------------------------------------------------------------------

#[tokio::test]
async fn set_pending_selects_the_thread_and_records_the_manual_roll() {
    let ctx = setup("lcpend").await;
    let first = seed_thread(&ctx, ctx.user_id, "First", "active", 1, 0).await;
    let issues = track(&ctx, first, &["unread", "unread"]).await;
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{first}/set-pending"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        keys(&body),
        vec![
            "die_size",
            "explanation",
            "format",
            "issue_id",
            "issue_number",
            "issues_remaining",
            "next_issue_id",
            "next_issue_number",
            "offset",
            "queue_position",
            "reading_progress",
            "result",
            "snoozed_count",
            "thread_id",
            "title",
            "total_issues"
        ]
    );
    assert_eq!(body["thread_id"], first);
    assert_eq!(body["issue_id"], issues[0]);
    assert_eq!(body["issue_number"], "1");
    assert_eq!(body["next_issue_id"], issues[0]);
    assert_eq!(body["issues_remaining"], 2);
    assert_eq!(body["queue_position"], 1);
    assert_eq!(body["result"], 0);
    assert_eq!(body["die_size"], 6);
    assert_eq!(body["explanation"], Value::Null);

    let pool = ctx.state.pool.get().await.unwrap();
    let pending: Option<i32> = pool
        .query_one(
            "SELECT pending_thread_id FROM sessions WHERE user_id = $1",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(pending, Some(first));
    let event = pool
        .query_one(
            "SELECT type, selection_method, selected_thread_id, issue_id, issue_number, die, result,
                    user_id, session_id IS NOT NULL
             FROM events WHERE type = 'roll'",
            &[],
        )
        .await
        .unwrap();
    assert_eq!(event.get::<_, String>(0), "roll");
    assert_eq!(event.get::<_, String>(1), "manual");
    assert_eq!(event.get::<_, i32>(2), first);
    assert_eq!(event.get::<_, Option<i32>>(3), Some(issues[0]));
    assert_eq!(event.get::<_, Option<String>>(4).as_deref(), Some("1"));
    assert_eq!(event.get::<_, i32>(5), 6);
    assert_eq!(event.get::<_, i32>(6), 0);
    assert_eq!(event.get::<_, i32>(7), ctx.user_id);
    assert!(event.get::<_, bool>(8));
}

#[tokio::test]
async fn set_pending_accepts_omitted_and_null_body() {
    let ctx = setup("lcpendnull").await;
    let omitted = seed_thread(&ctx, ctx.user_id, "Omitted", "active", 1, 2).await;
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{omitted}/set-pending"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["thread_id"], omitted);

    let null_body = seed_thread(&ctx, ctx.user_id, "Null", "active", 2, 2).await;
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{null_body}/set-pending"),
        Some(Value::Null),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["thread_id"], null_body);
}

#[tokio::test]
async fn set_pending_clears_a_session_snooze_and_records_the_unsnooze() {
    let ctx = setup("lcsnooze").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Snoozed", "active", 1, 3).await;
    let other = seed_thread(&ctx, ctx.user_id, "Other", "active", 2, 3).await;
    // Create the session through the same route, then snooze both threads.
    let (status, _) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{other}/set-pending"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE sessions SET snoozed_thread_ids = $2::text::json WHERE user_id = $1",
            &[&ctx.user_id, &format!("[{thread},{other}]")],
        )
        .await
        .unwrap();
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{thread}/set-pending"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["snoozed_count"], 1);
    assert_eq!(body["offset"], 1);
    let pool = ctx.state.pool.get().await.unwrap();
    let snoozed: String = pool
        .query_one(
            "SELECT snoozed_thread_ids::text FROM sessions WHERE user_id = $1",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        serde_json::from_str::<Vec<i32>>(&snoozed).unwrap(),
        vec![other]
    );
    let unsnoozes: i64 = pool
        .query_one(
            "SELECT count(*) FROM events WHERE type = 'unsnooze' AND thread_id = $1",
            &[&thread],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(unsnoozes, 1);
}

#[tokio::test]
async fn set_pending_rejections_match_python_details() {
    let ctx = setup("lcpendrej").await;
    let done = seed_thread(&ctx, ctx.user_id, "Done", "completed", 0, 0).await;
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{done}/set-pending"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["detail"], format!("Thread {done} is not active"));

    let empty = seed_thread(&ctx, ctx.user_id, "Empty", "active", 1, 0).await;
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{empty}/set-pending"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(
        body["detail"],
        format!("Thread {empty} has no issues remaining")
    );

    // A blocked thread reports its first unread canonical blocker.
    let source = seed_thread(&ctx, ctx.user_id, "Source Series", "active", 2, 0).await;
    let source_issues = track(&ctx, source, &["unread"]).await;
    let target = seed_thread(&ctx, ctx.user_id, "Target", "active", 3, 0).await;
    let target_issues = track(&ctx, target, &["unread"]).await;
    let pool = ctx.state.pool.get().await.unwrap();
    pool.execute(
        "INSERT INTO dependencies (source_issue_id, target_issue_id, created_at)
         VALUES ($1, $2, NOW())",
        &[&source_issues[0], &target_issues[0]],
    )
    .await
    .unwrap();
    pool.execute(
        "UPDATE threads SET is_blocked = true WHERE id = $1",
        &[&target],
    )
    .await
    .unwrap();
    drop(pool);
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{target}/set-pending"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(
        body["detail"],
        format!("Thread {target} is blocked by a dependency: Blocked by Source Series: #1")
    );

    // A stale plan selection conflicts instead of picking the successor.
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{source}/set-pending"),
        Some(json!({"expected_issue_id": source_issues[0] + 1000})),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body:?}");
    assert_eq!(
        body["detail"],
        "This issue is no longer next and available. Refresh the reading plan and try again."
    );
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{source}/set-pending"),
        Some(json!({"expected_issue_id": 0})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["errors"][0]["field"], "body.expected_issue_id");
    let (status, _) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{source}/set-pending"),
        Some(json!({"expected_issue_id": source_issues[0]})),
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    let pool = ctx.state.pool.get().await.unwrap();
    let rolls: i64 = pool
        .query_one("SELECT count(*) FROM events WHERE type = 'roll'", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(rolls, 1, "rejected selections record no roll event");
}

#[tokio::test]
async fn set_pending_rejects_stale_expected_issue_without_creating_checkpoint() {
    let ctx = setup("lcpendckpt").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Series", "active", 1, 0).await;
    let issues = track(&ctx, thread, &["unread", "unread"]).await;
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{thread}/set-pending"),
        Some(json!({"expected_issue_id": issues[0] + 1000})),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body:?}");
    assert_eq!(
        body["detail"],
        "This issue is no longer next and available. Refresh the reading plan and try again."
    );
    let pool = ctx.state.pool.get().await.unwrap();
    let snapshots: i64 = pool
        .query_one(
            "SELECT count(*) FROM snapshots s
             JOIN sessions sess ON sess.id = s.session_id
             WHERE sess.user_id = $1",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        snapshots, 0,
        "rejected set-pending must not create a session-start checkpoint"
    );
    let sessions: i64 = pool
        .query_one(
            "SELECT count(*) FROM sessions WHERE user_id = $1",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        sessions, 0,
        "rejected set-pending must not create a session"
    );
}

#[tokio::test]
async fn set_pending_is_owner_scoped() {
    let ctx = setup("lcpendiso").await;
    let (_, _, other_id) = second_user(&ctx).await;
    let theirs = seed_thread(&ctx, other_id, "Theirs", "active", 1, 2).await;
    let (status, body) = call(
        &ctx,
        "POST",
        &format!("/api/v1/threads/{theirs}/set-pending"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
    let pending: i64 = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "SELECT count(*) FROM sessions WHERE pending_thread_id = $1",
            &[&theirs],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(pending, 0);
}

// ---------------------------------------------------------------------------
// stale
// ---------------------------------------------------------------------------

#[tokio::test]
async fn stale_lists_old_unblocked_unsnoozed_threads_oldest_first() {
    let ctx = setup("lcstale").await;
    let (_, _, other_id) = second_user(&ctx).await;
    let never = seed_thread(&ctx, ctx.user_id, "Never Read", "active", 1, 2).await;
    let old = seed_thread(&ctx, ctx.user_id, "Old", "active", 2, 2).await;
    let older = seed_thread(&ctx, ctx.user_id, "Older", "active", 3, 2).await;
    let fresh = seed_thread(&ctx, ctx.user_id, "Fresh", "active", 4, 2).await;
    let blocked = seed_thread(&ctx, ctx.user_id, "Blocked", "active", 5, 2).await;
    let snoozed = seed_thread(&ctx, ctx.user_id, "Snoozed", "active", 6, 2).await;
    let inactive = seed_thread(&ctx, ctx.user_id, "Done", "completed", 0, 0).await;
    let theirs = seed_thread(&ctx, other_id, "Theirs", "active", 1, 2).await;
    let pool = ctx.state.pool.get().await.unwrap();
    for (id, days) in [
        (old, 40),
        (older, 90),
        (blocked, 90),
        (snoozed, 90),
        (inactive, 90),
        (theirs, 90),
    ] {
        pool.execute(
            "UPDATE threads SET last_activity_at = NOW() - make_interval(days => $2::int) WHERE id = $1",
            &[&id, &days],
        )
        .await
        .unwrap();
    }
    pool.execute(
        "UPDATE threads SET last_activity_at = NOW() - interval '1 day' WHERE id = $1",
        &[&fresh],
    )
    .await
    .unwrap();
    pool.execute(
        "UPDATE threads SET is_blocked = true WHERE id = $1",
        &[&blocked],
    )
    .await
    .unwrap();
    pool.execute(
        "INSERT INTO sessions (user_id, started_at, start_die, snoozed_thread_ids)
         VALUES ($1, NOW(), 6, $2::text::json)",
        &[&ctx.user_id, &format!("[{snoozed}]")],
    )
    .await
    .unwrap();
    drop(pool);

    let (status, body) = call(&ctx, "GET", "/api/v1/threads/stale", None).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let ids: Vec<i64> = body
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["id"].as_i64().unwrap())
        .collect();
    assert_eq!(
        ids,
        vec![never as i64, older as i64, old as i64],
        "NULL activity first, then oldest; blocked/snoozed/fresh/foreign excluded"
    );
    assert_eq!(body[0]["queue_position"], 1);
    assert!(body[1]["last_activity_at"].as_str().unwrap().ends_with('Z'));

    let (_, wider) = call(
        &ctx,
        "GET",
        "/api/v1/threads/stale?days=60&page_size=1",
        None,
    )
    .await;
    assert_eq!(wider.as_array().unwrap().len(), 1);
    assert_eq!(wider[0]["id"], never);
}

#[tokio::test]
async fn stale_rejects_invalid_parameters() {
    let ctx = setup("lcstalebad").await;
    for query in ["days=abc", "page_size=0", "page_size=201"] {
        let (status, body) =
            call(&ctx, "GET", &format!("/api/v1/threads/stale?{query}"), None).await;
        assert_eq!(
            status,
            StatusCode::UNPROCESSABLE_ENTITY,
            "{query}: {body:?}"
        );
        assert_eq!(body["detail"], "Validation failed");
    }
}

// ---------------------------------------------------------------------------
// excluded list
// ---------------------------------------------------------------------------

#[tokio::test]
async fn excluded_list_is_owner_scoped_paginated_and_searchable() {
    let ctx = setup("lcexlist").await;
    let (_, _, other_id) = second_user(&ctx).await;
    seed_thread(&ctx, other_id, "Theirs Excluded", "excluded", 0, 1).await;
    let alpha = seed_thread(&ctx, ctx.user_id, "Alpha", "excluded", 0, 1).await;
    let bravo = seed_thread(&ctx, ctx.user_id, "Bravo Saga", "excluded", 0, 1).await;
    let charlie = seed_thread(&ctx, ctx.user_id, "Charlie", "excluded", 0, 1).await;
    seed_thread(&ctx, ctx.user_id, "Active", "active", 1, 1).await;

    let (status, page) = call(
        &ctx,
        "GET",
        "/api/v1/threads/excluded/threads?sort=title&page_size=2",
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{page:?}");
    assert_eq!(
        keys(&page),
        vec!["active_count", "next_page_token", "threads"]
    );
    assert_eq!(page["active_count"], 0);
    let titles: Vec<&str> = page["threads"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["title"].as_str().unwrap())
        .collect();
    assert_eq!(titles, vec!["Alpha", "Bravo Saga"]);
    assert_eq!(page["threads"][0]["queue_position"], 0);
    assert_eq!(page["threads"][0]["status"], "excluded");
    let token = page["next_page_token"].as_str().unwrap().to_string();
    let (status, second) = call(
        &ctx,
        "GET",
        &format!("/api/v1/threads/excluded/threads?sort=title&page_size=2&page_token={token}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{second:?}");
    assert_eq!(second["threads"][0]["id"], charlie);
    assert_eq!(second["next_page_token"], Value::Null);

    let (_, searched) = call(
        &ctx,
        "GET",
        "/api/v1/threads/excluded/threads?search=saga",
        None,
    )
    .await;
    assert_eq!(searched["threads"].as_array().unwrap().len(), 1);
    assert_eq!(searched["threads"][0]["id"], bravo);

    // `position` is read as `created` (newest first).
    let (_, created) = call(
        &ctx,
        "GET",
        "/api/v1/threads/excluded/threads?sort=position",
        None,
    )
    .await;
    assert_eq!(created["threads"][0]["id"], charlie);
    assert_eq!(created["threads"][2]["id"], alpha);

    // A token minted for one sort is rejected for another.
    let (status, mismatch) = call(
        &ctx,
        "GET",
        &format!("/api/v1/threads/excluded/threads?sort=created&page_token={token}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{mismatch:?}");
}

#[tokio::test]
async fn excluded_list_rejects_invalid_parameters() {
    let ctx = setup("lcexbad").await;
    let (status, body) = call(
        &ctx,
        "GET",
        "/api/v1/threads/excluded/threads?sort=bogus",
        None,
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(
        body["detail"],
        "sort must be one of: position, title, created"
    );
    for query in ["page_size=0", "page_size=201", "search="] {
        let (status, body) = call(
            &ctx,
            "GET",
            &format!("/api/v1/threads/excluded/threads?{query}"),
            None,
        )
        .await;
        assert_eq!(
            status,
            StatusCode::UNPROCESSABLE_ENTITY,
            "{query}: {body:?}"
        );
    }
}

// ---------------------------------------------------------------------------
// check-duplicates
// ---------------------------------------------------------------------------

#[tokio::test]
async fn check_duplicates_reports_volume_and_title_matches_for_the_owner_only() {
    let ctx = setup("lcdup").await;
    let (_, _, other_id) = second_user(&ctx).await;
    let same_volume =
        seed_thread(&ctx, ctx.user_id, "Totally Different Name", "active", 1, 2).await;
    let similar = seed_thread(&ctx, ctx.user_id, "Amazing Spider-Man", "active", 2, 4).await;
    let exact = seed_thread(&ctx, ctx.user_id, "spider man", "completed", 0, 0).await;
    seed_thread(&ctx, ctx.user_id, "Unrelated Title", "active", 3, 1).await;
    seed_thread(&ctx, other_id, "Spider-Man", "active", 1, 9).await;
    let pool = ctx.state.pool.get().await.unwrap();
    let identity: i32 = pool
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json,
                                              created_at, updated_at)
             VALUES ('comicvine', 'series', '4050', $1, NOW(), NOW()) RETURNING id",
            &[&json!({"start_year": "1963"})],
        )
        .await
        .unwrap()
        .get(0);
    pool.execute(
        "INSERT INTO thread_external_series_mappings (thread_id, external_identity_id, status,
                                                      created_at, updated_at)
         VALUES ($1, $2, 'confirmed', NOW(), NOW())",
        &[&same_volume, &identity],
    )
    .await
    .unwrap();
    drop(pool);

    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v1/threads/check-duplicates",
        Some(json!({"title": "Spider-Man", "format": "comics", "comicvine_volume_id": 4050})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let matches = body["matches"].as_array().unwrap();
    let summary: Vec<(i64, &str)> = matches
        .iter()
        .map(|m| {
            (
                m["thread_id"].as_i64().unwrap(),
                m["match_type"].as_str().unwrap(),
            )
        })
        .collect();
    assert_eq!(
        summary,
        vec![
            (same_volume as i64, "same_comicvine_volume"),
            (exact as i64, "similar_title"),
            (similar as i64, "similar_title"),
        ]
    );
    assert_eq!(
        keys(&matches[0]),
        vec![
            "comicvine_volume_id",
            "format",
            "issues_remaining",
            "match_type",
            "start_year",
            "status",
            "thread_id",
            "title",
            "total_issues"
        ]
    );
    assert_eq!(matches[0]["comicvine_volume_id"], 4050);
    assert_eq!(matches[0]["start_year"], 1963);
    assert_eq!(matches[1]["status"], "completed");
    assert_eq!(matches[2]["issues_remaining"], 4);

    let (_, excluded) = call(
        &ctx,
        "POST",
        "/api/v1/threads/check-duplicates",
        Some(json!({"title": "Spider-Man", "format": "Comic", "exclude_thread_id": exact})),
    )
    .await;
    let ids: Vec<i64> = excluded["matches"]
        .as_array()
        .unwrap()
        .iter()
        .map(|m| m["thread_id"].as_i64().unwrap())
        .collect();
    assert_eq!(ids, vec![similar as i64]);

    let (status, invalid) = call(
        &ctx,
        "POST",
        "/api/v1/threads/check-duplicates",
        Some(json!({"title": "", "format": "x".repeat(51), "comicvine_volume_id": 0})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{invalid:?}");
    assert_eq!(invalid["errors"].as_array().unwrap().len(), 3);
}

// ---------------------------------------------------------------------------
// groups:batch
// ---------------------------------------------------------------------------

#[tokio::test]
async fn groups_batch_maps_threads_to_groups_in_request_order() {
    let ctx = setup("lcgroups").await;
    let (_, _, other_id) = second_user(&ctx).await;
    let first = seed_thread(&ctx, ctx.user_id, "First", "active", 1, 2).await;
    let second = seed_thread(&ctx, ctx.user_id, "Second", "active", 2, 2).await;
    let lonely = seed_thread(&ctx, ctx.user_id, "Lonely", "active", 3, 2).await;
    let issue = seed_issue(&ctx, second, "1", 1, "unread").await;
    let theirs = seed_thread(&ctx, other_id, "Theirs", "active", 1, 2).await;
    let pool = ctx.state.pool.get().await.unwrap();
    let zeta: i32 = pool
        .query_one(
            "INSERT INTO dependency_groups (user_id, name, created_at)
             VALUES ($1, 'Zeta Crossover', NOW()) RETURNING id",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    let alpha: i32 = pool
        .query_one(
            "INSERT INTO dependency_groups (user_id, name, created_at)
             VALUES ($1, 'Alpha Crossover', NOW()) RETURNING id",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    let foreign: i32 = pool
        .query_one(
            "INSERT INTO dependency_groups (user_id, name, created_at)
             VALUES ($1, 'Foreign', NOW()) RETURNING id",
            &[&other_id],
        )
        .await
        .unwrap()
        .get(0);
    for (group, thread, issue_id) in [
        (zeta, Some(first), None),
        (alpha, Some(first), None),
        (alpha, None, Some(issue)),
        (foreign, Some(first), None),
    ] {
        pool.execute(
            "INSERT INTO dependency_group_memberships (group_id, thread_id, issue_id)
             VALUES ($1, $2, $3)",
            &[&group, &thread, &issue_id],
        )
        .await
        .unwrap();
    }
    drop(pool);

    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v1/threads/groups:batch",
        Some(json!({"thread_ids": [second, first, first, lonely]})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        serde_json::to_string(&body).unwrap(),
        // `serde_json::Value` objects sort keys; assert content instead of order.
        serde_json::to_string(&json!({
            first.to_string(): [
                {"id": alpha, "name": "Alpha Crossover"},
                {"id": zeta, "name": "Zeta Crossover"}
            ],
            lonely.to_string(): [],
            second.to_string(): [{"id": alpha, "name": "Alpha Crossover"}],
        }))
        .unwrap()
    );

    // Raw wire order is the (deduplicated) request order.
    let response = router(ctx.state.clone())
        .oneshot(authed(
            "POST",
            "/api/v1/threads/groups:batch",
            &ctx.token,
            &ctx.csrf,
            Some(json!({"thread_ids": [second, first, first, lonely]})),
        ))
        .await
        .unwrap();
    let raw = String::from_utf8(
        to_bytes(response.into_body(), 64 * 1024)
            .await
            .unwrap()
            .to_vec(),
    )
    .unwrap();
    let positions: Vec<usize> = [second, first, lonely]
        .iter()
        .map(|id| raw.find(&format!("\"{id}\":")).unwrap())
        .collect();
    assert!(positions.windows(2).all(|pair| pair[0] < pair[1]), "{raw}");

    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v1/threads/groups:batch",
        Some(json!({"thread_ids": [first, theirs]})),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
    assert_eq!(body["detail"], format!("Thread {theirs} not found"));

    let (status, body) = call(
        &ctx,
        "POST",
        "/api/v1/threads/groups:batch",
        Some(json!({"thread_ids": []})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
    assert_eq!(body["errors"][0]["type"], "too_short");
    let (status, _) = call(
        &ctx,
        "POST",
        "/api/v1/threads/groups:batch",
        Some(json!({"thread_ids": (1..=201).collect::<Vec<i32>>()})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
}

// ---------------------------------------------------------------------------
// PUT /api/v1/threads/{thread_id}/test-backdate
// ---------------------------------------------------------------------------

static TEST_ENV_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

struct EnvRestore(Option<std::ffi::OsString>);
impl Drop for EnvRestore {
    fn drop(&mut self) {
        if let Some(value) = self.0.take() {
            std::env::set_var("TEST_ENVIRONMENT", value);
        } else {
            std::env::remove_var("TEST_ENVIRONMENT");
        }
    }
}

#[tokio::test]
async fn test_backdate_thread_for_testing_updates_activity_and_returns_thread() {
    let _env_guard = TEST_ENV_LOCK.lock().await;
    let _restore = EnvRestore(std::env::var_os("TEST_ENVIRONMENT"));
    std::env::set_var("TEST_ENVIRONMENT", "true");
    let ctx = setup("lcbackdate").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Test", "active", 1, 2).await;

    let before = chrono::Utc::now();
    let (status, body) = call(
        &ctx,
        "PUT",
        &format!("/api/v1/threads/{thread}/test-backdate?days_ago=5"),
        None,
    )
    .await;

    assert_eq!(status, StatusCode::OK, "{body:?}");
    // Golden success body measured from the frozen Python route
    // (`app/services/thread_service.py::backdate_thread_for_testing` ->
    // `thread_to_response`, schema `app/schemas/thread.py::ThreadResponse`).
    // Python always emits all 18 fields, including explicit null/[]/false
    // values; a changed response shape must fail here.
    assert_eq!(
        keys(&body),
        vec![
            "blocking_reasons",
            "created_at",
            "format",
            "id",
            "is_blocked",
            "is_test",
            "issues_remaining",
            "last_activity_at",
            "last_rating",
            "manual_creator_credits",
            "next_unread_issue_id",
            "next_unread_issue_number",
            "notes",
            "queue_position",
            "reading_progress",
            "status",
            "title",
            "total_issues"
        ]
    );
    assert_eq!(body["id"], thread);
    assert_eq!(body["title"], "Test");
    assert_eq!(body["format"], "Comic");
    assert_eq!(body["status"], "active");
    assert_eq!(body["queue_position"], 1);
    assert_eq!(body["issues_remaining"], 2);
    assert_eq!(body["is_blocked"], false);
    assert_eq!(body["is_test"], false);
    assert_eq!(body["last_rating"], Value::Null);
    assert_eq!(body["notes"], Value::Null);
    assert_eq!(body["manual_creator_credits"], json!([]));
    assert_eq!(body["blocking_reasons"], json!([]));
    assert!(body["created_at"].as_str().unwrap().ends_with('Z'));
    assert!(body["last_activity_at"].is_string(), "{body:?}");

    let activity: chrono::DateTime<chrono::Utc> = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "SELECT last_activity_at FROM threads WHERE id = $1",
            &[&thread],
        )
        .await
        .unwrap()
        .get(0);
    let expected = before - chrono::Duration::days(5);
    let delta = (activity - expected).num_seconds().abs();
    assert!(
        delta <= 30,
        "expected last_activity_at near {expected}, got {activity}"
    );
}

#[tokio::test]
async fn test_backdate_thread_for_testing_forbidden_without_test_environment() {
    let _env_guard = TEST_ENV_LOCK.lock().await;
    let _restore = EnvRestore(std::env::var_os("TEST_ENVIRONMENT"));
    std::env::remove_var("TEST_ENVIRONMENT");
    let ctx = setup("lcbackdateforbid").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Test", "active", 1, 2).await;

    let (status, body) = call(
        &ctx,
        "PUT",
        &format!("/api/v1/threads/{thread}/test-backdate?days_ago=5"),
        None,
    )
    .await;

    assert_eq!(status, StatusCode::FORBIDDEN, "{body:?}");
    assert_eq!(
        body["detail"],
        "This endpoint is only available in test environment"
    );
}

#[tokio::test]
async fn test_backdate_thread_for_testing_not_found_for_other_user() {
    let _env_guard = TEST_ENV_LOCK.lock().await;
    let _restore = EnvRestore(std::env::var_os("TEST_ENVIRONMENT"));
    std::env::set_var("TEST_ENVIRONMENT", "true");
    let ctx = setup("lcbackdatenotfound").await;
    let (_, _, other_id) = second_user(&ctx).await;
    let thread = seed_thread(&ctx, other_id, "Theirs", "active", 1, 2).await;

    let (status, body) = call(
        &ctx,
        "PUT",
        &format!("/api/v1/threads/{thread}/test-backdate?days_ago=5"),
        None,
    )
    .await;

    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
    assert_eq!(body["detail"], format!("Thread {thread} not found"));
}

#[tokio::test]
async fn test_backdate_thread_for_testing_validates_days_ago() {
    let _env_guard = TEST_ENV_LOCK.lock().await;
    let _restore = EnvRestore(std::env::var_os("TEST_ENVIRONMENT"));
    std::env::set_var("TEST_ENVIRONMENT", "true");
    let ctx = setup("lcbackdatevalidate").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Test", "active", 1, 2).await;

    // Golden 422 responses measured from the frozen Python route. FastAPI
    // raises RequestValidationError for `days_ago: int = Query(..., ge=1,
    // le=3650)` and `app/exception_handlers.py::validation_exception_handler`
    // returns `{"detail": "Validation failed"}` in production (the stable
    // contract), adding `errors`/`body` in dev/test. Assert both so a changed
    // error envelope cannot pass on status code alone.
    let production = std::env::var("ENVIRONMENT").as_deref() == Ok("production");
    let assert_rejection = |status: StatusCode, body: &Value, error: Value| {
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
        assert_eq!(body["detail"], "Validation failed", "{body:?}");
        if !production {
            assert_eq!(
                body["errors"],
                json!([error]),
                "Python-measured validation errors"
            );
            assert_eq!(body["body"], Value::Null, "Python-measured request body");
        }
    };
    let path = format!("/api/v1/threads/{thread}/test-backdate");

    let (status, body) = call(&ctx, "PUT", &path, None).await;
    assert_rejection(
        status,
        &body,
        json!({"field": "query.days_ago", "message": "Field required", "type": "missing"}),
    );

    let (status, body) = call(&ctx, "PUT", &format!("{path}?days_ago=0"), None).await;
    assert_rejection(
        status,
        &body,
        json!({"field": "query.days_ago", "message": "Input should be greater than or equal to 1", "type": "greater_than_equal"}),
    );

    let (status, body) = call(&ctx, "PUT", &format!("{path}?days_ago=3651"), None).await;
    assert_rejection(
        status,
        &body,
        json!({"field": "query.days_ago", "message": "Input should be less than or equal to 3650", "type": "less_than_equal"}),
    );
}

/// A changed writer must serialize on the per-reader queue advisory lock
/// before touching the thread row. Force a deterministic interleaving with the
/// sibling `exclude` writer: a holder keeps the queue lock, both requests park
/// on it, then it is released. Without the queue lock, backdate would grab the
/// thread row first and either deadlock (40P01) or never queue, so this test
/// fails rather than passing on a lucky serial schedule.
#[tokio::test]
async fn test_backdate_and_exclude_do_not_deadlock() {
    let _env_guard = TEST_ENV_LOCK.lock().await;
    let _restore = EnvRestore(std::env::var_os("TEST_ENVIRONMENT"));
    std::env::set_var("TEST_ENVIRONMENT", "true");
    let ctx = setup_with_pool("lcbackdateexdead", "8").await;
    let mut holder = ctx.state.pool.get().await.unwrap();
    let conn = ctx.state.pool.get().await.unwrap();
    let id = seed_thread(&ctx, ctx.user_id, "Contended", "active", 1, 5).await;

    let hold = holder.transaction().await.unwrap();
    hold.execute(
        "SELECT pg_advisory_xact_lock($1, $2)",
        &[&QUEUE_LOCK_NAMESPACE, &ctx.user_id],
    )
    .await
    .unwrap();

    let backdate = {
        let state = ctx.state.clone();
        let token = ctx.token.clone();
        let csrf = ctx.csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "PUT",
                    &format!("/api/v1/threads/{id}/test-backdate?days_ago=5"),
                    &token,
                    &csrf,
                    None,
                ),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, ctx.user_id, 1).await;
    let exclude = {
        let state = ctx.state.clone();
        let token = ctx.token.clone();
        let csrf = ctx.csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    &format!("/api/v1/threads/{id}/exclude"),
                    &token,
                    &csrf,
                    None,
                ),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, ctx.user_id, 2).await;
    hold.commit().await.unwrap();

    let (b, e) = tokio::join!(backdate, exclude);
    let (b_status, b_body) = b.expect("backdate task");
    let (e_status, e_body) = e.expect("exclude task");
    assert_ne!(
        b_status,
        StatusCode::INTERNAL_SERVER_ERROR,
        "backdate deadlocked or errored: {b_status} {b_body:?}"
    );
    assert_eq!(b_status, StatusCode::OK, "backdate: {b_status} {b_body:?}");
    assert_ne!(
        e_status,
        StatusCode::INTERNAL_SERVER_ERROR,
        "exclude deadlocked or errored: {e_status} {e_body:?}"
    );
    assert_eq!(e_status, StatusCode::OK, "exclude: {e_status} {e_body:?}");
}
