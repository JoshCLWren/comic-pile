#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Focused native HTTP regressions for the browser-called continuity-rules v1
//! cutover (issue #4848). Exercises the mounted Rust router so contract shape
//! and transactional CRUD are verified at the same-path ingress.
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

static NEXT_IP: AtomicU16 = AtomicU16::new(10);

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

async fn seed_issues(state: &Arc<AppState>, user_id: i32) -> (i32, i32, i32) {
    let conn = db::checkout(state).await.expect("seed connection");
    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id) \
             VALUES ('CR Thread', 'Comic', 2, 1, 'active', $1) RETURNING id",
            &[&user_id],
        )
        .await
        .expect("seed thread")
        .get(0);
    let source_issue: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, status, created_at, position) \
             VALUES ($1, '1', 'unread', NOW(), 1) RETURNING id",
            &[&thread_id],
        )
        .await
        .expect("seed source issue")
        .get(0);
    let target_issue: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, status, created_at, position) \
             VALUES ($1, '2', 'unread', NOW(), 2) RETURNING id",
            &[&thread_id],
        )
        .await
        .expect("seed target issue")
        .get(0);
    (thread_id, source_issue, target_issue)
}

#[tokio::test]
async fn continuity_rules_requires_authentication() {
    let (state, _db) = database().await;
    for (method, path) in [
        ("GET", "/api/v1/continuity-rules/"),
        ("POST", "/api/v1/continuity-rules/"),
        ("GET", "/api/v1/continuity-rules/1"),
        ("PUT", "/api/v1/continuity-rules/1"),
        ("DELETE", "/api/v1/continuity-rules/1"),
    ] {
        let (status, _, _) = send(
            &state,
            Request::builder()
                .method(method)
                .uri(path)
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from("{}"))
                .unwrap(),
        )
        .await;
        assert!(
            status == StatusCode::UNAUTHORIZED || status == StatusCode::FORBIDDEN,
            "{method} {path} -> {status}"
        );
    }
}

#[tokio::test]
async fn continuity_rules_crud_is_native_wire_compatible() {
    let (state, _db) = database().await;
    let username = format!("cr{}", NEXT_IP.fetch_add(1, Ordering::Relaxed));
    let (token, csrf) = register_and_login(&state, &username).await;
    let user_id = user_id_for(&state, &username).await;
    let (_thread, source_issue, target_issue) = seed_issues(&state, user_id).await;

    let (status, created) = authed_json(
        &state,
        "POST",
        "/api/v1/continuity-rules/",
        &token,
        &csrf,
        Some(json!({
            "source_type": "issue",
            "source_id": source_issue,
            "target_type": "issue",
            "target_id": target_issue,
            "satisfaction_type": "item_read",
        })),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let rule_id = created["id"].as_i64().expect("rule id");
    assert_eq!(created["source_id"], source_issue);
    assert_eq!(created["target_id"], target_issue);
    assert_eq!(created["satisfaction_type"], "item_read");

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
        .any(|item| item["id"] == rule_id));

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
    assert_eq!(fetched["id"], rule_id);

    let (status, updated) = authed_json(
        &state,
        "PUT",
        &format!("/api/v1/continuity-rules/{rule_id}"),
        &token,
        &csrf,
        Some(json!({
            "source_type": "issue",
            "source_id": target_issue,
            "target_type": "issue",
            "target_id": source_issue,
            "satisfaction_type": "item_read",
            "note": "updated",
        })),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{updated}");
    assert_eq!(updated["note"], "updated");

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
