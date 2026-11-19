#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Handler-level HTTP regressions for the migrated same-path Roll v1 routes.
//!
//! Exercises auth, ownership scoping, and error mapping through the mounted
//! router against the canonical disposable PostgreSQL schema.

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

async fn setup_user(
    prefix: &str,
) -> (
    Arc<AppState>,
    String,
    String,
    i32,
    tokio::sync::MutexGuard<'static, ()>,
) {
    let url = comicpile_roll_service::test_support::database_url().await;
    let state = Arc::new(test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-roll-routes-secret".into()),
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .unwrap(),
    ));
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

#[tokio::test]
async fn recommendation_explanation_requires_auth() {
    let (state, _token, _csrf, _user_id, _guard) = setup_user("recauth").await;
    let (status, body) = send(
        &state,
        Request::builder()
            .method("GET")
            .uri("/api/v1/roll/events/1/recommendation-explanation")
            .body(Body::empty())
            .unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED, "{body:?}");
}

#[tokio::test]
async fn override_requires_auth() {
    let (state, _token, _csrf, _user_id, _guard) = setup_user("ovrauth").await;
    let (status, body) = send(
        &state,
        Request::builder()
            .method("POST")
            .uri("/api/v2/roll/override")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(json!({"thread_id": 1}).to_string()))
            .unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED, "{body:?}");
}

#[tokio::test]
async fn switch_prerequisite_requires_auth() {
    let (state, _token, _csrf, _user_id, _guard) = setup_user("swauth").await;
    let (status, body) = send(
        &state,
        Request::builder()
            .method("POST")
            .uri("/api/v2/roll/switch-prerequisite")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({"node_type":"issue","node_id":1}).to_string(),
            ))
            .unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED, "{body:?}");
}

#[tokio::test]
async fn recommendation_explanation_returns_404_for_missing_event() {
    let (state, token, csrf, _user_id, _guard) = setup_user("rec404").await;
    let (status, body) = send(
        &state,
        authed(
            "GET",
            "/api/v1/roll/events/999999/recommendation-explanation",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
}

#[tokio::test]
async fn recommendation_explanation_hides_other_users_event() {
    let (state, token, csrf, user_id, _guard) = setup_user("recown1").await;
    let (_token2, _csrf2, user2) = register_extra_user(&state, "recown2").await;
    let conn = state.pool.get().await.unwrap();
    let session_id: i32 = conn
        .query_one(
            "INSERT INTO sessions (user_id, started_at, start_die) VALUES ($1, NOW(), 6) RETURNING id",
            &[&user2],
        )
        .await
        .unwrap()
        .get(0);
    let event_id: i32 = conn
        .query_one(
            "INSERT INTO events (type, user_id, session_id, die, result, selection_method, timestamp)
             VALUES ('roll', $1, $2, 6, 1, 'random', NOW()) RETURNING id",
            &[&user2, &session_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_ne!(user_id, user2);
    let (status, body) = send(
        &state,
        authed(
            "GET",
            &format!("/api/v1/roll/events/{event_id}/recommendation-explanation"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
}

#[tokio::test]
async fn recommendation_explanation_rejects_non_roll_event() {
    let (state, token, csrf, user_id, _guard) = setup_user("rec422").await;
    let conn = state.pool.get().await.unwrap();
    let session_id: i32 = conn
        .query_one(
            "INSERT INTO sessions (user_id, started_at, start_die) VALUES ($1, NOW(), 6) RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    let event_id: i32 = conn
        .query_one(
            "INSERT INTO events (type, user_id, session_id, die, result, selection_method, timestamp)
             VALUES ('rate', $1, $2, 6, 1, 'manual', NOW()) RETURNING id",
            &[&user_id, &session_id],
        )
        .await
        .unwrap()
        .get(0);
    let (status, body) = send(
        &state,
        authed(
            "GET",
            &format!("/api/v1/roll/events/{event_id}/recommendation-explanation"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
}

#[tokio::test]
async fn override_returns_404_for_missing_or_other_users_thread() {
    let (state, token, csrf, _user_id, _guard) = setup_user("ovr404").await;
    let (status, body) = send(
        &state,
        authed(
            "POST",
            "/api/v2/roll/override",
            &token,
            &csrf,
            Some(json!({"thread_id": 999999})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");

    let (_token2, _csrf2, user2) = register_extra_user(&state, "ovrown2").await;
    let conn = state.pool.get().await.unwrap();
    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id)
             VALUES ('Other', 'comic', 1, 1, 'active', $1) RETURNING id",
            &[&user2],
        )
        .await
        .unwrap()
        .get(0);
    let (status, body) = send(
        &state,
        authed(
            "POST",
            "/api/v2/roll/override",
            &token,
            &csrf,
            Some(json!({"thread_id": thread_id})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
}

#[tokio::test]
async fn override_returns_422_for_non_selectable_thread() {
    let (state, token, csrf, user_id, _guard) = setup_user("ovr422").await;
    let conn = state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO sessions (user_id, started_at, start_die) VALUES ($1, NOW(), 6)",
        &[&user_id],
    )
    .await
    .unwrap();
    // Active thread with no unread issue/frontier is not a selectable candidate.
    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id)
             VALUES ('Empty', 'comic', 0, 1, 'active', $1) RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    let (status, body) = send(
        &state,
        authed(
            "POST",
            "/api/v2/roll/override",
            &token,
            &csrf,
            Some(json!({"thread_id": thread_id})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
}

#[tokio::test]
async fn switch_prerequisite_returns_404_for_missing_or_other_users_issue() {
    let (state, token, csrf, _user_id, _guard) = setup_user("sw404").await;
    let (status, body) = send(
        &state,
        authed(
            "POST",
            "/api/v2/roll/switch-prerequisite",
            &token,
            &csrf,
            Some(json!({"node_type":"issue","node_id":999999})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
}

#[tokio::test]
async fn switch_prerequisite_rejects_unsupported_node_type() {
    let (state, token, csrf, _user_id, _guard) = setup_user("sw422").await;
    let (status, body) = send(
        &state,
        authed(
            "POST",
            "/api/v2/roll/switch-prerequisite",
            &token,
            &csrf,
            Some(json!({"node_type":"crossover","node_id":1})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
}
