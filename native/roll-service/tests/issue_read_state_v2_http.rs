#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Handler-level HTTP regressions for the native v2 issue read-state, position
//! and reader-context resources (moved from the retired v1 action URLs).
//!
//! Exercises auth, ownership scoping, ordering and error mapping through the
//! mounted router against the canonical disposable PostgreSQL schema. Requires
//! `RUST_ROLL_TEST_DATABASE_URL` and hard-fails without it.

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

fn unique_suffix() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos()
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
    setup_user_with_pool(prefix, 2).await
}

async fn setup_user_with_pool(
    prefix: &str,
    pool_size: usize,
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
                "RUST_ROLL_POOL_SIZE" => Some(pool_size.to_string()),
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

async fn register_extra_user(state: &Arc<AppState>, prefix: &str) -> (String, String, i32) {
    let username = format!("{prefix}-{}-{}", std::process::id(), unique_suffix());
    register_user(state, &username).await
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

fn authed(method: &str, path: &str, token: &str, csrf: &str, body: Option<Value>) -> Request<Body> {
    let builder = Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"));
    if let Some(body) = body {
        builder
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(body.to_string()))
            .unwrap()
    } else {
        builder.body(Body::empty()).unwrap()
    }
}

type Conn = deadpool_postgres::Object;

/// One seeded series: `(thread_id, issue_ids)` with consistent tracking counters.
async fn series(
    conn: &Conn,
    user_id: i32,
    title: &str,
    queue_position: i32,
    status: &str,
    issues: &[(&str, &str)],
) -> (i32, Vec<i32>) {
    let unread = issues.iter().filter(|(_, st)| *st == "unread").count() as i32;
    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id,
                                  total_issues, reading_progress)
             VALUES ($1, 'Comic', $2, $3, $4, $5, $6, $7) RETURNING id",
            &[
                &title,
                &unread,
                &queue_position,
                &status,
                &user_id,
                &(issues.len() as i32),
                &if unread == 0 {
                    "completed"
                } else {
                    "in_progress"
                },
            ],
        )
        .await
        .unwrap()
        .get(0);
    let mut ids = vec![];
    for (index, (number, state)) in issues.iter().enumerate() {
        let id: i32 = conn
            .query_one(
                "INSERT INTO issues (thread_id, issue_number, status, created_at, position)
                 VALUES ($1, $2, $3, NOW(), $4) RETURNING id",
                &[&thread_id, number, state, &(index as i32 + 1)],
            )
            .await
            .unwrap()
            .get(0);
        ids.push(id);
    }
    let next: Option<i32> = issues
        .iter()
        .zip(&ids)
        .find(|((_, st), _)| *st == "unread")
        .map(|(_, id)| *id);
    conn.execute(
        "UPDATE threads SET next_unread_issue_id = $2 WHERE id = $1",
        &[&thread_id, &next],
    )
    .await
    .unwrap();
    (thread_id, ids)
}

#[derive(Debug, PartialEq)]
struct ThreadRow {
    status: String,
    queue_position: i32,
    manual: bool,
    next: Option<i32>,
    remaining: i32,
    total: Option<i32>,
    progress: Option<String>,
    blocked: bool,
}

async fn thread_row(conn: &Conn, thread_id: i32) -> ThreadRow {
    let row = conn
        .query_one(
            "SELECT status, queue_position, queue_position_is_manual, next_unread_issue_id,
                    issues_remaining, total_issues, reading_progress, is_blocked
             FROM threads WHERE id = $1",
            &[&thread_id],
        )
        .await
        .unwrap();
    ThreadRow {
        status: row.get(0),
        queue_position: row.get(1),
        manual: row.get(2),
        next: row.get(3),
        remaining: row.get(4),
        total: row.get(5),
        progress: row.get(6),
        blocked: row.get(7),
    }
}

async fn issue_state(conn: &Conn, issue_id: i32) -> (String, bool) {
    let row = conn
        .query_one(
            "SELECT status, read_at IS NOT NULL FROM issues WHERE id = $1",
            &[&issue_id],
        )
        .await
        .unwrap();
    (row.get(0), row.get(1))
}

async fn positions(conn: &Conn, thread_id: i32) -> Vec<i32> {
    conn.query(
        "SELECT id FROM issues WHERE thread_id = $1 ORDER BY position",
        &[&thread_id],
    )
    .await
    .unwrap()
    .iter()
    .map(|row| row.get(0))
    .collect()
}

/// `(type, user_id, thread_id, issue_id, issue_number)` history rows, oldest first.
async fn events(
    conn: &Conn,
    user_id: i32,
) -> Vec<(
    String,
    Option<i32>,
    Option<i32>,
    Option<i32>,
    Option<String>,
)> {
    conn.query(
        "SELECT type, user_id, thread_id, issue_id, issue_number FROM events
         WHERE user_id = $1 ORDER BY id",
        &[&user_id],
    )
    .await
    .unwrap()
    .iter()
    .map(|row| (row.get(0), row.get(1), row.get(2), row.get(3), row.get(4)))
    .collect()
}

async fn dependency(conn: &Conn, source: i32, target: i32, note: Option<&str>) -> i32 {
    conn.query_one(
        "INSERT INTO dependencies (created_at, source_issue_id, target_issue_id, note, origin) \
         VALUES (NOW(), $1, $2, $3, 'reader') RETURNING id",
        &[&source, &target, &note],
    )
    .await
    .unwrap()
    .get(0)
}

fn get(path: &str, token: &str, csrf: &str) -> Request<Body> {
    authed("GET", path, token, csrf, None)
}

fn post(path: &str, token: &str, csrf: &str, body: Option<Value>) -> Request<Body> {
    authed("POST", path, token, csrf, body)
}

fn mark(path: &str, token: &str, csrf: &str) -> Request<Body> {
    post(path, token, csrf, None)
}

fn unmark(path: &str, token: &str, csrf: &str) -> Request<Body> {
    authed("DELETE", path, token, csrf, None)
}

fn move_req(path: &str, token: &str, csrf: &str, body: Option<Value>) -> Request<Body> {
    authed("PUT", path, token, csrf, body)
}

fn row(
    status: &str,
    queue_position: i32,
    next: Option<i32>,
    remaining: i32,
    total: i32,
    progress: &str,
) -> ThreadRow {
    ThreadRow {
        status: status.into(),
        queue_position,
        manual: false,
        next,
        remaining,
        total: Some(total),
        progress: Some(progress.into()),
        blocked: false,
    }
}

#[tokio::test]
async fn every_operation_requires_authentication() {
    let (state, _token, _csrf, _user_id, _guard) = setup_user("irs-auth").await;
    for (method, path) in [
        ("GET", "/api/v2/issues/1/reader-context"),
        ("POST", "/api/v2/issues/1/read-markers"),
        ("DELETE", "/api/v2/issues/1/read-markers"),
        ("PUT", "/api/v2/issues/1/position"),
        ("POST", "/api/v2/issue-read-markers"),
        ("POST", "/api/v2/issue-read-marker-removals"),
    ] {
        let (status, body) = send(
            &state,
            Request::builder()
                .method(method)
                .uri(path)
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(
                    json!({"issue_ids": [1], "after_issue_id": null}).to_string(),
                ))
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
async fn mark_read_walks_a_series_to_completion_and_renumbers_the_queue() {
    let (state, token, csrf, user_id, _guard) = setup_user("irs-read").await;
    let conn = state.pool.get().await.unwrap();
    let (alpha, a) = series(
        &conn,
        user_id,
        "Alpha",
        1,
        "active",
        &[("1", "unread"), ("2", "unread")],
    )
    .await;
    let (beta, _) = series(&conn, user_id, "Beta", 2, "active", &[("1", "unread")]).await;
    let (gamma, _) = series(&conn, user_id, "Gamma", 3, "active", &[("1", "unread")]).await;
    conn.execute(
        "UPDATE threads SET queue_position_is_manual = TRUE WHERE id = $1",
        &[&alpha],
    )
    .await
    .unwrap();

    let (status, body) = send(
        &state,
        mark(
            &format!("/api/v2/issues/{}/read-markers", a[0]),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");
    assert_eq!(issue_state(&conn, a[0]).await, ("read".into(), true));
    let mut expected = row("active", 1, Some(a[1]), 1, 2, "in_progress");
    expected.manual = true;
    assert_eq!(thread_row(&conn, alpha).await, expected);

    let (status, body) = send(
        &state,
        mark(
            &format!("/api/v2/issues/{}/read-markers", a[0]),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(
        body,
        json!({"detail": format!("Issue {} is already marked as read", a[0])})
    );

    let (status, _) = send(
        &state,
        mark(
            &format!("/api/v2/issues/{}/read-markers", a[1]),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    // Completed: no pointer, manual claim cleared, the active queue is dense again.
    assert_eq!(
        thread_row(&conn, alpha).await,
        row("completed", 1, None, 0, 2, "completed")
    );
    assert_eq!(thread_row(&conn, beta).await.queue_position, 1);
    assert_eq!(thread_row(&conn, gamma).await.queue_position, 2);

    let history = events(&conn, user_id).await;
    assert_eq!(
        history,
        vec![
            (
                "issue_read".to_string(),
                Some(user_id),
                Some(alpha),
                Some(a[0]),
                Some("1".to_string())
            ),
            (
                "issue_read".to_string(),
                Some(user_id),
                Some(alpha),
                Some(a[1]),
                Some("2".to_string())
            ),
        ]
    );
}

#[tokio::test]
async fn completing_an_excluded_series_keeps_it_excluded_without_renumbering() {
    let (state, token, csrf, user_id, _guard) = setup_user("irs-excl").await;
    let conn = state.pool.get().await.unwrap();
    let (excluded, e) = series(
        &conn,
        user_id,
        "Excluded",
        5,
        "excluded",
        &[("1", "unread")],
    )
    .await;
    let (active, _) = series(&conn, user_id, "Active", 3, "active", &[("1", "unread")]).await;
    let (status, _) = send(
        &state,
        mark(
            &format!("/api/v2/issues/{}/read-markers", e[0]),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    let after = thread_row(&conn, excluded).await;
    assert_eq!(after.status, "excluded");
    assert_eq!(after.queue_position, 5);
    assert_eq!(after.progress.as_deref(), Some("completed"));
    assert_eq!(after.remaining, 0);
    // No renumbering happened because the status was not written.
    assert_eq!(thread_row(&conn, active).await.queue_position, 3);
}

#[tokio::test]
async fn mark_unread_reactivates_a_completed_series_and_moves_the_pointer_back() {
    let (state, token, csrf, user_id, _guard) = setup_user("irs-unread").await;
    let conn = state.pool.get().await.unwrap();
    let (first, _) = series(&conn, user_id, "First", 1, "active", &[("1", "unread")]).await;
    let (done, d) = series(
        &conn,
        user_id,
        "Done",
        0,
        "completed",
        &[("1", "read"), ("2", "read")],
    )
    .await;
    let (second, _) = series(&conn, user_id, "Second", 2, "active", &[("1", "unread")]).await;

    let (status, body) = send(
        &state,
        unmark(
            &format!("/api/v2/issues/{}/read-markers", d[1]),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");
    assert_eq!(issue_state(&conn, d[1]).await, ("unread".into(), false));
    // Seated at the end of the active queue, then the queue is renumbered.
    assert_eq!(
        thread_row(&conn, done).await,
        row("active", 3, Some(d[1]), 1, 2, "in_progress")
    );
    assert_eq!(thread_row(&conn, first).await.queue_position, 1);
    assert_eq!(thread_row(&conn, second).await.queue_position, 2);

    // An earlier issue becomes the new frontier.
    let (status, _) = send(
        &state,
        unmark(
            &format!("/api/v2/issues/{}/read-markers", d[0]),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    assert_eq!(
        thread_row(&conn, done).await,
        row("active", 3, Some(d[0]), 2, 2, "in_progress")
    );

    let (status, body) = send(
        &state,
        unmark(
            &format!("/api/v2/issues/{}/read-markers", d[0]),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(
        body,
        json!({"detail": format!("Issue {} is already marked as unread", d[0])})
    );
    let history = events(&conn, user_id).await;
    assert_eq!(history.len(), 2);
    assert!(history.iter().all(|(kind, ..)| kind == "issue_unread"));
}

#[tokio::test]
async fn read_state_changes_refresh_the_blocked_flag_in_the_same_transaction() {
    let (state, token, csrf, user_id, _guard) = setup_user("irs-blocked").await;
    let conn = state.pool.get().await.unwrap();
    let (blocked, b) = series(&conn, user_id, "Blocked", 1, "active", &[("1", "unread")]).await;
    let (blocker, k) = series(&conn, user_id, "Blocker", 2, "active", &[("1", "unread")]).await;
    dependency(&conn, k[0], b[0], None).await;
    conn.execute(
        "UPDATE threads SET is_blocked = TRUE WHERE id = $1",
        &[&blocked],
    )
    .await
    .unwrap();

    let (status, _) = send(
        &state,
        mark(
            &format!("/api/v2/issues/{}/read-markers", k[0]),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    assert!(!thread_row(&conn, blocked).await.blocked);

    let (status, _) = send(
        &state,
        unmark(
            &format!("/api/v2/issues/{}/read-markers", k[0]),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    assert!(thread_row(&conn, blocked).await.blocked);
    let _ = blocker;
}

#[tokio::test]
async fn single_mark_and_move_hide_foreign_issues_behind_the_same_404() {
    let (state, token, csrf, user_id, _guard) = setup_user("irs-own").await;
    let (_token2, _csrf2, user2) = register_extra_user(&state, "irs-own2").await;
    let conn = state.pool.get().await.unwrap();
    let (foreign, f) = series(
        &conn,
        user2,
        "Foreign",
        1,
        "active",
        &[("1", "unread"), ("2", "read")],
    )
    .await;
    let (_mine, m) = series(&conn, user_id, "Mine", 1, "active", &[("1", "unread")]).await;
    let before = thread_row(&conn, foreign).await;

    for (method, path, body) in [
        (
            "POST",
            format!("/api/v2/issues/{}/read-markers", f[0]),
            None,
        ),
        (
            "DELETE",
            format!("/api/v2/issues/{}/read-markers", f[1]),
            None,
        ),
        (
            "PUT",
            format!("/api/v2/issues/{}/position", f[0]),
            Some(json!({"after_issue_id": null})),
        ),
        (
            "PUT",
            format!("/api/v2/issues/{}/position", m[0]),
            Some(json!({"after_issue_id": f[0]})),
        ),
        (
            "POST",
            "/api/v2/issues/999999/read-markers".to_string(),
            None,
        ),
    ] {
        let (status, response) = send(&state, authed(method, &path, &token, &csrf, body)).await;
        assert_eq!(
            status,
            StatusCode::NOT_FOUND,
            "{method} {path}: {response:?}"
        );
    }
    let (status, body) = send(
        &state,
        mark(
            &format!("/api/v2/issues/{}/read-markers", f[0]),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(
        (status, body),
        (
            StatusCode::NOT_FOUND,
            json!({"detail": format!("Issue {} not found", f[0])})
        )
    );
    let (status, body) = send(
        &state,
        get(
            &format!("/api/v2/issues/{}/reader-context", f[0]),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(
        (status, body),
        (
            StatusCode::NOT_FOUND,
            json!({"detail": format!("Issue {} not found", f[0])})
        )
    );
    assert_eq!(thread_row(&conn, foreign).await, before);
    assert_eq!(issue_state(&conn, f[0]).await, ("unread".into(), false));
    assert!(events(&conn, user2).await.is_empty());
    assert!(events(&conn, user_id).await.is_empty());
}

#[tokio::test]
async fn bulk_mark_read_is_atomic_and_records_one_event_per_entry() {
    let (state, token, csrf, user_id, _guard) = setup_user("irs-bulk").await;
    let (_t2, _c2, user2) = register_extra_user(&state, "irs-bulk2").await;
    let conn = state.pool.get().await.unwrap();
    let (alpha, a) = series(
        &conn,
        user_id,
        "Alpha",
        1,
        "active",
        &[("1", "unread"), ("2", "unread")],
    )
    .await;
    let (beta, b) = series(
        &conn,
        user_id,
        "Beta",
        2,
        "active",
        &[("1", "unread"), ("2", "unread")],
    )
    .await;
    let (gamma, g) = series(&conn, user_id, "Gamma", 3, "active", &[("1", "unread")]).await;
    let (_foreign, f) = series(&conn, user2, "Foreign", 1, "active", &[("1", "unread")]).await;
    let (_done, d) = series(
        &conn,
        user_id,
        "Done",
        4,
        "active",
        &[("1", "read"), ("2", "unread")],
    )
    .await;

    // First invalid id in request order wins; nothing changes.
    for (ids, status_code, detail) in [
        (
            json!([a[0], f[0]]),
            StatusCode::NOT_FOUND,
            format!("Issue {} not found", f[0]),
        ),
        (
            json!([a[0], d[0]]),
            StatusCode::BAD_REQUEST,
            format!("Issue {} is already marked as read", d[0]),
        ),
        (
            json!([f[0], d[0]]),
            StatusCode::NOT_FOUND,
            format!("Issue {} not found", f[0]),
        ),
    ] {
        let (status, body) = send(
            &state,
            post(
                "/api/v2/issue-read-markers",
                &token,
                &csrf,
                Some(json!({"issue_ids": ids})),
            ),
        )
        .await;
        assert_eq!((status, body), (status_code, json!({"detail": detail})));
    }
    assert_eq!(issue_state(&conn, a[0]).await, ("unread".into(), false));
    assert!(events(&conn, user_id).await.is_empty());

    let (status, body) = send(
        &state,
        post(
            "/api/v2/issue-read-markers",
            &token,
            &csrf,
            Some(json!({"issue_ids": [g[0], a[0], b[0], b[1], a[0]]})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");
    assert_eq!(
        thread_row(&conn, alpha).await,
        row("active", 1, Some(a[1]), 1, 2, "in_progress")
    );
    assert_eq!(
        thread_row(&conn, beta).await,
        row("completed", 2, None, 0, 2, "completed")
    );
    assert_eq!(
        thread_row(&conn, gamma).await,
        row("completed", 3, None, 0, 1, "completed")
    );
    // Alpha is the only active series left in the original queue, so it renumbers to 1;
    // "Done" keeps the only remaining slot after it.
    let queue: Vec<(i32, i32)> = conn
        .query(
            "SELECT id, queue_position FROM threads WHERE user_id = $1 AND status = 'active' ORDER BY queue_position",
            &[&user_id],
        )
        .await
        .unwrap()
        .iter()
        .map(|r| (r.get(0), r.get(1)))
        .collect();
    assert_eq!(
        queue.iter().map(|(_, p)| *p).collect::<Vec<_>>(),
        vec![1, 2]
    );
    // Duplicated list entries record one event each, in request order.
    let history = events(&conn, user_id).await;
    let issue_ids: Vec<i32> = history.iter().map(|e| e.3.unwrap()).collect();
    assert_eq!(issue_ids, vec![g[0], a[0], b[0], b[1], a[0]]);
    assert!(history
        .iter()
        .all(|e| e.0 == "issue_read" && e.1 == Some(user_id)));
}

#[tokio::test]
async fn bulk_mark_unread_reactivates_completed_series_with_not_started_progress() {
    let (state, token, csrf, user_id, _guard) = setup_user("irs-bulku").await;
    let conn = state.pool.get().await.unwrap();
    let (live, _) = series(&conn, user_id, "Live", 1, "active", &[("1", "unread")]).await;
    let (done, d) = series(
        &conn,
        user_id,
        "Done",
        0,
        "completed",
        &[("1", "read"), ("2", "read")],
    )
    .await;
    let (_unread, u) = series(&conn, user_id, "Unread", 2, "active", &[("1", "unread")]).await;

    let (status, body) = send(
        &state,
        post(
            "/api/v2/issue-read-marker-removals",
            &token,
            &csrf,
            Some(json!({"issue_ids": [u[0]]})),
        ),
    )
    .await;
    assert_eq!(
        (status, body),
        (
            StatusCode::BAD_REQUEST,
            json!({"detail": format!("Issue {} is already marked as unread", u[0])})
        )
    );

    let (status, body) = send(
        &state,
        post(
            "/api/v2/issue-read-marker-removals",
            &token,
            &csrf,
            Some(json!({"issue_ids": [d[1], d[0]]})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");
    assert_eq!(
        thread_row(&conn, done).await,
        row("active", 3, Some(d[0]), 2, 2, "not_started")
    );
    assert_eq!(thread_row(&conn, live).await.queue_position, 1);
    let history = events(&conn, user_id).await;
    assert_eq!(
        history.iter().map(|e| e.3.unwrap()).collect::<Vec<_>>(),
        vec![d[1], d[0]]
    );
    assert!(history.iter().all(|e| e.0 == "issue_unread"));
}

#[tokio::test]
async fn bulk_mark_unread_seats_reactivated_series_after_retained_queue_positions() {
    let (state, token, csrf, user_id, _guard) = setup_user("irs-bulkq").await;
    let conn = state.pool.get().await.unwrap();
    let (first, _) = series(&conn, user_id, "Live", 1, "active", &[("1", "unread")]).await;
    let (kept, k) = series(&conn, user_id, "Kept", 5, "completed", &[("1", "read")]).await;
    let (later, l) = series(&conn, user_id, "Later", 0, "completed", &[("1", "read")]).await;

    let (status, body) = send(
        &state,
        post(
            "/api/v2/issue-read-marker-removals",
            &token,
            &csrf,
            Some(json!({"issue_ids": [l[0], k[0]]})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");
    // The retained position 5 counts toward the end of the queue, so the series
    // without a seat is appended after it (Python `max_queue_position + 1`).
    assert_eq!(thread_row(&conn, first).await.queue_position, 1);
    assert_eq!(thread_row(&conn, kept).await.queue_position, 2);
    assert_eq!(thread_row(&conn, later).await.queue_position, 3);
}

#[tokio::test]
async fn bulk_errors_follow_request_order() {
    let (state, token, csrf, user_id, _guard) = setup_user("irs-bulko").await;
    let conn = state.pool.get().await.unwrap();
    let (_t, ids) = series(
        &conn,
        user_id,
        "Order",
        1,
        "active",
        &[("1", "read"), ("2", "unread")],
    )
    .await;
    let (read_id, unread_id) = (ids[0], ids[1]);
    let cases = [
        (
            "issue-read-markers",
            json!([read_id, 2147483648_i64]),
            StatusCode::BAD_REQUEST,
            format!("Issue {read_id} is already marked as read"),
        ),
        (
            "issue-read-markers",
            json!([2147483648_i64, read_id]),
            StatusCode::NOT_FOUND,
            "Issue 2147483648 not found".to_string(),
        ),
        (
            "issue-read-markers",
            json!([unread_id, 999_999, read_id]),
            StatusCode::NOT_FOUND,
            "Issue 999999 not found".to_string(),
        ),
        (
            "issue-read-marker-removals",
            json!([unread_id, 2147483648_i64]),
            StatusCode::BAD_REQUEST,
            format!("Issue {unread_id} is already marked as unread"),
        ),
        (
            "issue-read-marker-removals",
            json!([read_id, 999_999, unread_id]),
            StatusCode::NOT_FOUND,
            "Issue 999999 not found".to_string(),
        ),
    ];
    for (op, issue_ids, expected_status, detail) in cases {
        let (status, body) = send(
            &state,
            post(
                &format!("/api/v2/{op}"),
                &token,
                &csrf,
                Some(json!({"issue_ids": issue_ids})),
            ),
        )
        .await;
        assert_eq!(
            (status, body),
            (expected_status, json!({"detail": detail})),
            "{op} {issue_ids}"
        );
    }
    // Nothing changed: every case failed before the write.
    assert_eq!(issue_state(&conn, read_id).await.0, "read");
    assert_eq!(issue_state(&conn, unread_id).await.0, "unread");
}

#[tokio::test]
async fn move_reorders_and_refreshes_the_thread_counters() {
    let (state, token, csrf, user_id, _guard) = setup_user("irs-move").await;
    let (_t2, _c2, user2) = register_extra_user(&state, "irs-move2").await;
    let conn = state.pool.get().await.unwrap();
    let (alpha, a) = series(
        &conn,
        user_id,
        "Alpha",
        1,
        "active",
        &[
            ("1", "read"),
            ("2", "unread"),
            ("3", "unread"),
            ("4", "unread"),
        ],
    )
    .await;
    let (_other, o) = series(&conn, user_id, "Other", 2, "active", &[("1", "unread")]).await;
    let (_foreign, f) = series(&conn, user2, "Foreign", 1, "active", &[("1", "unread")]).await;

    // Move issue 4 to the top: becomes the first unread issue.
    let (status, body) = send(
        &state,
        move_req(
            &format!("/api/v2/issues/{}/position", a[3]),
            &token,
            &csrf,
            Some(json!({"after_issue_id": null})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");
    assert_eq!(positions(&conn, alpha).await, vec![a[3], a[0], a[1], a[2]]);
    assert_eq!(
        thread_row(&conn, alpha).await,
        row("active", 1, Some(a[3]), 3, 4, "in_progress")
    );

    // Move after another issue.
    let (status, _) = send(
        &state,
        move_req(
            &format!("/api/v2/issues/{}/position", a[3]),
            &token,
            &csrf,
            Some(json!({"after_issue_id": a[1]})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    assert_eq!(positions(&conn, alpha).await, vec![a[0], a[1], a[3], a[2]]);
    assert_eq!(thread_row(&conn, alpha).await.next, Some(a[1]));

    // Anchoring on itself changes nothing but still succeeds.
    let (status, _) = send(
        &state,
        move_req(
            &format!("/api/v2/issues/{}/position", a[2]),
            &token,
            &csrf,
            Some(json!({"after_issue_id": a[2]})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    assert_eq!(positions(&conn, alpha).await, vec![a[0], a[1], a[3], a[2]]);

    // Anchors must live in the same owned thread.
    for anchor in [o[0], f[0], 999_999] {
        let (status, body) = send(
            &state,
            move_req(
                &format!("/api/v2/issues/{}/position", a[2]),
                &token,
                &csrf,
                Some(json!({"after_issue_id": anchor})),
            ),
        )
        .await;
        assert_eq!(
            (status, body),
            (
                StatusCode::NOT_FOUND,
                json!({"detail": format!("Issue {anchor} not found")})
            )
        );
    }
    assert_eq!(positions(&conn, alpha).await, vec![a[0], a[1], a[3], a[2]]);
}

#[tokio::test]
async fn validation_errors_use_the_production_detail_after_authentication() {
    let (state, token, csrf, user_id, _guard) = setup_user("irs-422").await;
    let conn = state.pool.get().await.unwrap();
    let (_alpha, a) = series(&conn, user_id, "Alpha", 1, "active", &[("1", "unread")]).await;

    let expected = json!({"detail": "Validation failed"});

    let (status, body) = send(
        &state,
        mark("/api/v2/issues/abc/read-markers", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body, expected);
    let (status, body) = send(
        &state,
        get("/api/v2/issues/abc/reader-context", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body, expected);

    let (status, body) = send(
        &state,
        move_req(
            &format!("/api/v2/issues/{}/position", a[0]),
            &token,
            &csrf,
            Some(json!({})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body, expected);
    let (status, body) = send(
        &state,
        move_req(
            "/api/v2/issues/x/position",
            &token,
            &csrf,
            Some(json!({"after_issue_id": 0})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body, expected);

    for (path, payload) in [
        ("/api/v2/issue-read-markers", json!({"issue_ids": []})),
        (
            "/api/v2/issue-read-marker-removals",
            json!({"issue_ids": (1..=101).collect::<Vec<i32>>()}),
        ),
        ("/api/v2/issue-read-markers", json!({})),
        ("/api/v2/issue-read-markers", json!({"issue_ids": "1"})),
        (
            "/api/v2/issue-read-markers",
            json!({"issue_ids": [1, "x", null]}),
        ),
    ] {
        let (status, body) = send(&state, post(path, &token, &csrf, Some(payload))).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{path}");
        assert_eq!(body, expected, "{path}");
    }
    // Wrong methods on v2 resource paths are a 405 with the Starlette-style detail body.
    for (method, path) in [
        ("GET", format!("/api/v2/issues/{}/read-markers", a[0])),
        ("POST", format!("/api/v2/issues/{}/position", a[0])),
    ] {
        let (status, body) = send(&state, authed(method, &path, &token, &csrf, None)).await;
        assert_eq!(
            (status, body),
            (
                StatusCode::METHOD_NOT_ALLOWED,
                json!({"detail": "Method Not Allowed"})
            ),
            "{method} {path}"
        );
    }
    assert_eq!(issue_state(&conn, a[0]).await, ("unread".into(), false));
}

#[tokio::test]
async fn reader_context_reports_series_crossovers_local_chain_and_edges() {
    let (state, token, csrf, user_id, _guard) = setup_user("irs-ctx").await;
    let (_t2, _c2, user2) = register_extra_user(&state, "irs-ctx2").await;
    let conn = state.pool.get().await.unwrap();
    let (main, m) = series(
        &conn,
        user_id,
        "Saga",
        1,
        "active",
        &[
            ("1", "read"),
            ("2", "read"),
            ("3", "unread"),
            ("4", "unread"),
            ("5", "unread"),
            ("6", "unread"),
        ],
    )
    .await;
    let (side, s) = series(
        &conn,
        user_id,
        "Side Story",
        2,
        "active",
        &[("1", "read"), ("2", "unread")],
    )
    .await;
    let (foreign, fo) = series(&conn, user2, "Foreign Saga", 1, "active", &[("1", "read")]).await;

    // Confirmed ComicVine volume 4050 on the current issue; two read siblings share it.
    for (issue_id, confirmed, metadata) in [
        (
            m[2],
            "confirmed",
            json!({"volume": {"id": "4050", "name": " Saga "}}),
        ),
        (m[0], "confirmed", json!({"volume_id": 4050})),
        (s[0], "confirmed", json!({"volume": {"id": 4050}})),
        (m[1], "candidate", json!({"volume": {"id": 4050}})),
        (fo[0], "confirmed", json!({"volume": {"id": 4050}})),
    ] {
        let ext_id = format!("cv-{issue_id}");
        let identity: i32 = conn
            .query_one(
                "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at)
                 VALUES ('comicvine', 'issue', $1, $2::text::json, NOW(), NOW()) RETURNING id",
                &[&ext_id, &metadata.to_string()],
            )
            .await
            .unwrap()
            .get(0);
        conn.execute(
            "INSERT INTO issue_external_identity_mappings
                 (issue_id, external_identity_id, status, evidence_json, created_at, updated_at)
             VALUES ($1, $2, $3, '{}'::json, NOW(), NOW())",
            &[&issue_id, &identity, &confirmed],
        )
        .await
        .unwrap();
    }
    // Latest rate event wins per issue; ties on timestamp resolve by id.
    for (issue_id, thread_id, rating, minutes_ago) in [
        (m[0], main, 2.0_f64, 30),
        (m[0], main, 4.5, 20),
        (s[0], side, 3.0, 10),
        (m[1], main, 5.0, 5),
        (m[3], main, 1.5, 1),
        (fo[0], foreign, 1.0, 1),
    ] {
        let owner = if thread_id == foreign { user2 } else { user_id };
        conn.execute(
            "INSERT INTO events (type, timestamp, user_id, thread_id, issue_id, rating)
             VALUES ('rate', NOW() - ($5::int * INTERVAL '1 minute'), $1, $2, $3, $4)",
            &[&owner, &thread_id, &issue_id, &rating, &minutes_ago],
        )
        .await
        .unwrap();
    }
    // Crossovers: exact members and a thread-level group.
    let exact: i32 = conn
        .query_one("INSERT INTO dependency_groups (user_id, name, created_at) VALUES ($1, 'Event A', NOW()) RETURNING id", &[&user_id])
        .await
        .unwrap()
        .get(0);
    for issue_id in [m[2], m[4], s[0]] {
        conn.execute(
            "INSERT INTO dependency_group_memberships (group_id, issue_id) VALUES ($1, $2)",
            &[&exact, &issue_id],
        )
        .await
        .unwrap();
    }
    let whole: i32 = conn
        .query_one("INSERT INTO dependency_groups (user_id, name, created_at) VALUES ($1, 'Annual Run', NOW()) RETURNING id", &[&user_id])
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO dependency_group_memberships (group_id, thread_id) VALUES ($1, $2)",
        &[&whole, &main],
    )
    .await
    .unwrap();
    // Edges: a dependency into the current issue, a continuity rule out of it.
    let dep = dependency(&conn, s[0], m[2], Some("read first")).await;
    let rule: i32 = conn
        .query_one(
            "INSERT INTO continuity_rules (user_id, source_type, source_id, target_type, target_id, satisfaction_type, created_at, updated_at)
             VALUES ($1, 'issue', $2, 'issue', $3, 'item_read', NOW(), NOW()) RETURNING id",
            &[&user_id, &m[2], &s[1]],
        )
        .await
        .unwrap()
        .get(0);

    let (status, body) = send(
        &state,
        get(
            &format!("/api/v2/issues/{}/reader-context", m[2]),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    // Series: m[0] (4.5 after correction), m[1] is only a candidate so excluded; s[0] 3.0.
    assert_eq!(body["issue_id"], m[2]);
    assert_eq!(
        body["series"],
        json!({
            "identity_source": "comicvine",
            "canonical_series_id": "4050",
            "series_name": "Saga",
            "average_rating": 3.75,
            "ratings_count": 2,
            "previous_issue": {"issue_id": m[1], "issue_number": "2", "rating": 5.0},
            "recent_ratings": [
                {"issue_id": s[0], "issue_number": "1", "rating": 3.0},
                {"issue_id": m[0], "issue_number": "1", "rating": 4.5}
            ],
            "highest_rating": 4.5,
            "lowest_rating": 3.0
        })
    );
    assert_eq!(
        body["crossovers"],
        json!([
            {
                "id": whole, "name": "Annual Run", "applies_to_current_issue": true,
                "membership_kind": "thread",
                "next_member": {"issue_id": m[3], "issue_number": "4"},
                "average_rating": null, "ratings_count": 0, "read_count": 0
            },
            {
                "id": exact, "name": "Event A", "applies_to_current_issue": true,
                "membership_kind": "issue",
                "next_member": {"issue_id": m[4], "issue_number": "5"},
                "average_rating": 3.0, "ratings_count": 1, "read_count": 1
            }
        ])
    );
    let local = body["local_chain"]["issues"].as_array().unwrap();
    assert_eq!(
        local
            .iter()
            .map(|i| i["issue_number"].as_str().unwrap())
            .collect::<Vec<_>>(),
        vec!["1", "2", "3", "4", "5"]
    );
    assert_eq!(
        local
            .iter()
            .map(|i| i["relation"].as_str().unwrap())
            .collect::<Vec<_>>(),
        vec!["previous", "previous", "current", "next", "future"]
    );
    assert_eq!(local[3]["rating"], 1.5);
    assert_eq!(
        local[2]["crossover_memberships"],
        json!([{"id": whole, "name": "Annual Run"}, {"id": exact, "name": "Event A"}])
    );
    assert_eq!(
        local[3]["crossover_memberships"],
        json!([{"id": whole, "name": "Annual Run"}])
    );

    let edges = body["local_chain"]["edges"].as_array().unwrap();
    assert_eq!(edges.len(), 2);
    // "continuity" sorts before "dependency".
    assert_eq!(
        edges[0],
        json!({
            "id": rule, "kind": "continuity",
            "source_issue_id": m[2], "target_issue_id": s[1],
            "source_thread_id": main, "target_thread_id": side,
            "source_label": "Saga #3", "target_label": "Side Story #2",
            "source_issue_number": "3", "target_issue_number": "2",
            "source_thread_title": "Saga", "target_thread_title": "Side Story",
            "source_status": "unread", "target_status": "unread",
            "note": null,
            "explanation": "Saga #3 must be read before Side Story #2"
        })
    );
    assert_eq!(edges[1]["id"], dep);
    assert_eq!(edges[1]["kind"], "dependency");
    assert_eq!(edges[1]["note"], "read first");
    assert_eq!(edges[1]["explanation"], "You must read Side Story #1 first");

    // An issue with no confirmed identity reports `unavailable` and an empty series.
    let (status, body) = send(
        &state,
        get(
            &format!("/api/v2/issues/{}/reader-context", m[5]),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body["series"],
        json!({
            "identity_source": "unavailable", "canonical_series_id": null, "series_name": null,
            "average_rating": null, "ratings_count": 0,
            "previous_issue": {"issue_id": m[4], "issue_number": "5", "rating": null},
            "recent_ratings": [], "highest_rating": null, "lowest_rating": null
        })
    );
    assert_eq!(body["crossovers"][0]["next_member"], Value::Null);
    assert_eq!(body["local_chain"]["issues"].as_array().unwrap().len(), 3);
}

/// Number of sessions currently waiting on this reader's queue advisory lock.
async fn queue_lock_waiters(conn: &Conn, user_id: i32) -> i64 {
    conn.query_one(
        "SELECT count(*) FROM pg_locks
         WHERE locktype = 'advisory' AND NOT granted
           AND classid::int = 699001 AND objid::int = $1",
        &[&user_id],
    )
    .await
    .unwrap()
    .get(0)
}

/// Block until exactly `expected` sessions wait on the queue lock. This observes
/// database state (no sleeps-as-synchronization, no retries): the loop only
/// yields between observations and the bound exists solely to fail a hung run.
async fn wait_for_queue_lock_waiters(conn: &Conn, user_id: i32, expected: i64) {
    for _ in 0..3000 {
        if queue_lock_waiters(conn, user_id).await == expected {
            return;
        }
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    panic!("expected {expected} queue-lock waiters");
}

/// Mark-unread (reactivating a completed series) and a roll_offer PATCH on the
/// same thread must not deadlock. The interleaving is forced: a holder keeps the
/// queue lock while the PATCH arrives first and queues on it, then markUnread
/// arrives and queues behind it. Under the old order (thread row lock before
/// the queue lock) markUnread would already own the row the PATCH needs once the
/// holder releases, giving a lock cycle (40P01). Taking the queue lock first
/// means markUnread waits before touching the row, so the writers serialize.
#[tokio::test]
async fn mark_unread_and_roll_offer_patch_on_same_thread_do_not_deadlock() {
    let (state, token, csrf, user_id, _guard) = setup_user_with_pool("isdld", 8).await;
    let mut holder = state.pool.get().await.unwrap();
    let conn = state.pool.get().await.unwrap();

    // A completed, unseated series so :markUnread reactivates it (queue lock
    // required), and a conflicting stored receipt so the roll_offer PATCH
    // acquires its locks and returns 409 without needing full roll context.
    let (thread_id, issue_ids) = series(
        &conn,
        user_id,
        "Deadlock race",
        0,
        "completed",
        &[("1", "read")],
    )
    .await;
    let issue_id = issue_ids[0];
    conn.execute(
        "INSERT INTO events (type, timestamp, user_id, thread_id, issue_id, context)
         VALUES ('rate', NOW(), $1, $2, $3, $4::text::json)",
        &[
            &user_id,
            &thread_id,
            &issue_id,
            &serde_json::json!({
                "issue_command_key": "race-key-deadlock-01",
                "issue_command_payload": {
                    "issue_id": issue_id,
                    "status": "read",
                    "rating": 1.0,
                    "source": "roll_offer"
                }
            })
            .to_string(),
        ],
    )
    .await
    .unwrap();

    let hold = holder.transaction().await.unwrap();
    hold.execute("SELECT pg_advisory_xact_lock(699001, $1)", &[&user_id])
        .await
        .unwrap();

    let patch = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "PATCH",
                    &format!("/api/v2/issues/{issue_id}"),
                    &token,
                    &csrf,
                    Some(json!({
                        "status": "read",
                        "rating": 4.0,
                        "idempotency_key": "race-key-deadlock-01",
                        "source": "roll_offer"
                    })),
                ),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, user_id, 1).await;
    let unread = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "DELETE",
                    &format!("/api/v2/issues/{issue_id}/read-markers"),
                    &token,
                    &csrf,
                    None,
                ),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, user_id, 2).await;
    hold.commit().await.unwrap();

    let (u, p) = tokio::join!(unread, patch);
    let (u_status, u_body) = u.expect("markUnread task");
    let (p_status, p_body) = p.expect("roll_offer patch task");
    assert_eq!(
        p_status,
        StatusCode::CONFLICT,
        "roll_offer patch: {p_status} {p_body:?}"
    );
    assert_eq!(
        u_status,
        StatusCode::NO_CONTENT,
        "markUnread deadlocked or errored: {u_status} {u_body:?}"
    );
    let reactivated = thread_row(&conn, thread_id).await;
    assert_eq!(reactivated.queue_position, 1);
}
