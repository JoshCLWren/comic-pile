#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Focused native HTTP regressions for the browser-called continuity-rules v1
//! cutover (issue #4848). Exercises the mounted Rust router so contract shape,
//! auth, ownership scoping, and transactional CRUD are verified at the same-path
//! ingress.
//!
//! Every test is database-backed and fails loudly when the canonical test DSN
//! is missing; there is no implicit skip path (CI provides the DSN).

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{db, router, test_support, AppState};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicU16, Ordering};
use std::sync::Arc;
use tower::ServiceExt;

static NEXT_IP: AtomicU16 = AtomicU16::new(100);

/// Canonical disposable database state. Panics with the standard message when
/// `RUST_ROLL_TEST_DATABASE_URL` is absent, never returns a passing no-op test.
async fn database() -> (Arc<AppState>, tokio::sync::MutexGuard<'static, ()>) {
    let state = test_support::test_state(4)
        .await
        .expect("RUST_ROLL_TEST_DATABASE_URL is required");
    let guard = test_support::reset_for_test(&state).await;
    (state, guard)
}

async fn send(state: &Arc<AppState>, request: Request<Body>) -> (StatusCode, Value, Vec<String>) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    let cookies = response
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .filter_map(|value| value.to_str().ok().map(str::to_owned))
        .collect::<Vec<_>>();
    let body = to_bytes(response.into_body(), 65536).await.unwrap();
    let body = serde_json::from_slice(&body).unwrap_or(Value::Null);
    (status, body, cookies)
}

fn cookie_value(cookies: &[String], name: &str) -> Option<String> {
    cookies.iter().find_map(|cookie| {
        cookie
            .strip_prefix(&format!("{name}="))
            .and_then(|rest| rest.split(';').next())
            .map(str::to_owned)
    })
}

async fn register_and_login(state: &Arc<AppState>, username: &str) -> (String, String) {
    let ip = NEXT_IP.fetch_add(1, Ordering::Relaxed);
    let (status, registered, cookies) = send(
        state,
        Request::builder()
            .method("POST")
            .uri("/api/v1/auth/register")
            .header(header::CONTENT_TYPE, "application/json")
            .header("x-forwarded-for", format!("198.51.100.{ip}"))
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
    .await;
    assert_eq!(status, StatusCode::OK, "{registered}");
    let csrf = cookie_value(&cookies, "csrf_token").expect("csrf cookie");
    let token = registered["access_token"]
        .as_str()
        .expect("access token")
        .to_string();
    (token, csrf)
}

async fn authed_json(
    state: &Arc<AppState>,
    method: &str,
    uri: &str,
    token: &str,
    csrf: &str,
    body: Option<Value>,
) -> (StatusCode, Value) {
    let mut builder = Request::builder()
        .method(method)
        .uri(uri)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"));
    if body.is_some() {
        builder = builder.header(header::CONTENT_TYPE, "application/json");
    }
    let request = builder
        .body(body.map_or_else(Body::empty, |value| Body::from(value.to_string())))
        .unwrap();
    let (status, value, _) = send(state, request).await;
    (status, value)
}

async fn user_id_for(state: &Arc<AppState>, username: &str) -> i32 {
    let conn = db::checkout(state).await.expect("user lookup connection");
    let row = conn
        .query_one("SELECT id FROM users WHERE username = $1", &[&username])
        .await
        .expect("registered user row");
    row.get(0)
}

async fn seed_thread_issue(
    state: &Arc<AppState>,
    user_id: i32,
    thread_id: i32,
    issue_id: i32,
    number: &str,
) {
    let conn = db::checkout(state).await.expect("seed connection");
    conn.batch_execute(&format!(
        "INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status)
         VALUES ({thread_id}, {user_id}, 'Thread {number}', 'Comic', 2, 1, 'active');
         INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
         VALUES ({issue_id}, {thread_id}, '{number}', 'unread', NOW(), 1);"
    ))
    .await
    .expect("seed thread and issue");
}

fn continuity_rule_body() -> Value {
    json!({
        "source_type": "issue",
        "source_id": 3001,
        "target_type": "issue",
        "target_id": 3002,
        "satisfaction_type": "item_read",
        "checkpoint_issue_id": None,
        "convergence_targets": [],
        "selected_member_issue_ids": [],
        "note": None
    })
}

async fn create_rule(
    state: &Arc<AppState>,
    token: &str,
    csrf: &str,
    body: Value,
) -> (StatusCode, Value) {
    authed_json(
        state,
        "POST",
        "/api/v1/continuity-rules/",
        token,
        csrf,
        Some(body),
    )
    .await
}

/// F1: create, list, get, update, delete round trip preserves the wire contract
/// and compiles canonical dependency edges.
#[tokio::test]
async fn continuity_rule_crud_round_trip_is_native_wire_compatible() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cr-wire").await;
    let user_id = user_id_for(&state, "cr-wire").await;
    seed_thread_issue(&state, user_id, 2001, 3001, "1").await;
    seed_thread_issue(&state, user_id, 2001, 3002, "2").await;

    let (status, created) = create_rule(&state, &token, &csrf, continuity_rule_body()).await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    assert_eq!(created["source_id"], 3001, "{created}");
    assert_eq!(created["target_id"], 3002, "{created}");
    assert_eq!(created["satisfaction_type"], "item_read", "{created}");
    assert_eq!(created["user_id"], user_id as i64, "{created}");
    let rule_id = created["id"].as_i64().expect("rule id") as i32;

    // List includes the created rule.
    let (status, listed) = authed_json(
        &state,
        "GET",
        "/api/v1/continuity-rules/",
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{listed}");
    assert!(listed
        .as_array()
        .unwrap()
        .iter()
        .any(|item| item["id"] == rule_id as i64), "{listed}");

    // Get returns the rule shape.
    let (status, fetched) = authed_json(
        &state,
        "GET",
        &format!("/api/v1/continuity-rules/{rule_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{fetched}");
    assert_eq!(fetched["id"], rule_id as i64, "{fetched}");
    assert_eq!(fetched["source_id"], 3001, "{fetched}");
    assert_eq!(fetched["target_id"], 3002, "{fetched}");
    assert!(fetched["convergence_targets"].is_array(), "{fetched}");
    assert!(fetched["selected_member_issue_ids"].is_array(), "{fetched}");

    // Update changes the target and note.
    let mut updated_body = continuity_rule_body();
    updated_body["target_id"] = json!(3001);
    updated_body["source_id"] = json!(3002);
    updated_body["note"] = json!("updated note");
    let (status, updated) = authed_json(
        &state,
        "PUT",
        &format!("/api/v1/continuity-rules/{rule_id}"),
        &token,
        &csrf,
        Some(updated_body),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{updated}");
    assert_eq!(updated["id"], rule_id as i64, "{updated}");
    assert_eq!(updated["source_id"], 3002, "{updated}");
    assert_eq!(updated["target_id"], 3001, "{updated}");
    assert_eq!(updated["note"], "updated note", "{updated}");

    // Delete returns 204 and subsequent get returns 404.
    let (status, _) = authed_json(
        &state,
        "DELETE",
        &format!("/api/v1/continuity-rules/{rule_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);

    let (status, _) = authed_json(
        &state,
        "GET",
        &format!("/api/v1/continuity-rules/{rule_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

/// F2: requests from a user who does not own the referenced issues return 404.
#[tokio::test]
async fn continuity_rule_requires_owned_endpoints() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cr-foreign").await;
    let user_id = user_id_for(&state, "cr-foreign").await;
    seed_thread_issue(&state, user_id, 2002, 3003, "1").await;
    // Issue 3004 is owned by no thread of this user; use a foreign-owned issue.
    register_and_login(&state, "cr-foreign-other").await;

    let mut body = continuity_rule_body();
    body["source_id"] = json!(3003);
    body["target_id"] = json!(999999);

    let (status, _) = create_rule(&state, &token, &csrf, body).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

/// F3: a self-targeting rule (issue to itself) is rejected with 400 before any
/// database write.
#[tokio::test]
async fn continuity_rule_self_target_is_rejected_before_write() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cr-self").await;
    let user_id = user_id_for(&state, "cr-self").await;
    seed_thread_issue(&state, user_id, 2003, 3005, "1").await;

    let mut body = continuity_rule_body();
    body["source_id"] = json!(3005);
    body["target_id"] = json!(3005);

    let (status, _) = create_rule(&state, &token, &csrf, body).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
}

/// F4: unauthenticated requests are rejected with 401.
#[tokio::test]
async fn continuity_rule_requires_authentication() {
    let (state, _db) = database().await;

    let (status, _) = authed_json(
        &state,
        "POST",
        "/api/v1/continuity-rules/",
        "",
        "",
        Some(continuity_rule_body()),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}
