#![allow(clippy::unwrap_used, clippy::expect_used)]
//! DB-backed HTTP regressions for the supported session/History/undo v2 routes
//! delivered under #4839.
//!
//! The four mounted operations are the resource-shaped replacements for the
//! retired v1/unversioned session and undo aliases. This file proves, against
//! the canonical disposable PostgreSQL schema and through the real axum
//! router, that those four paths preserve ownership, the wire shape of their
//! responses and the retirement of the old aliases. It hard-fails without
//! `RUST_ROLL_TEST_DATABASE_URL`; CI supplies that database.

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

struct Ctx {
    state: Arc<AppState>,
    token: String,
    csrf: String,
    user_id: i32,
    _guard: tokio::sync::MutexGuard<'static, ()>,
}

async fn setup(prefix: &str) -> Ctx {
    let url = comicpile_roll_service::test_support::database_url().await;
    let state = Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
                "RUST_ROLL_JWT_SECRET" => Some("synthetic-session-undo-v2-secret".into()),
                "RUST_ROLL_POOL_SIZE" => Some("2".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    );
    let guard = comicpile_roll_service::test_support::reset_for_test(&state).await;
    let username = format!("{prefix}-{}-{}", std::process::id(), unique_suffix());
    let (token, csrf, user_id) = register_user(&state, &username).await;
    seed(&state, user_id).await;
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
                        "password": "correct-horse-battery",
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

/// One owned session with an event and two snapshots, plus a foreign session.
/// IDs are well above the fixtures used by other integration tests so a shared
/// CI database cannot produce accidental collisions.
async fn seed(state: &Arc<AppState>, user_id: i32) {
    let connection = state.pool.get().await.unwrap();
    connection
        .batch_execute(&format!(
            "INSERT INTO users (id, username) VALUES (999999, 'session-v2-foreign-owner');
             INSERT INTO threads (id, user_id, title, format, issues_remaining, total_issues, queue_position, status, is_blocked)
             VALUES (92101, {user_id}, 'Restored Comic', 'comics', 2, 2, 1, 'active', false);
             INSERT INTO sessions (id, user_id, started_at, ended_at, start_die, manual_die, pending_thread_id, reading_mode_suggested, snoozed_thread_ids)
             VALUES (93101, {user_id}, NOW() - interval '1 hour', NULL, 6, NULL, NULL, false, '[92101]'::json),
                    (93102, 999999, NOW() - interval '2 hours', NULL, 6, NULL, NULL, false, '[]'::json);
             INSERT INTO events (id, user_id, session_id, type, timestamp, thread_id, die, die_after)
             VALUES (95101, {user_id}, 93101, 'roll', NOW() - interval '30 minutes', 92101, 6, 20);
             INSERT INTO snapshots (id, session_id, thread_states, session_state, created_at, description)
             VALUES (94101, 93101, '{{}}'::json, '{{}}'::json, NOW() - interval '40 minutes', 'Before roll'),
                    (94102, 93101, '{{}}'::json, '{{}}'::json, NOW() - interval '20 minutes', 'After roll');"
        ))
        .await
        .expect("seed session/undo v2 fixture");
}

fn authed(method: &str, uri: &str, token: &str, csrf: &str) -> Request<Body> {
    Request::builder()
        .method(method)
        .uri(uri)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header(header::COOKIE, format!("csrf_token={csrf}"))
        .header("x-csrf-token", csrf)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::empty())
        .unwrap()
}

async fn send(state: &Arc<AppState>, request: Request<Body>) -> (StatusCode, Value) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 128 * 1024).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

#[tokio::test]
async fn v2_session_details_preserve_owner_scoped_wire_shape() {
    let ctx = setup("session-v2-details").await;
    let (status, body) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v2/reading-sessions/93101/details",
            &ctx.token,
            &ctx.csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["session_id"], 93101);
    let summary = body["narrative_summary"]
        .as_object()
        .expect("summary object");
    for key in ["read", "skipped", "snoozed", "completed"] {
        assert!(
            summary.contains_key(key),
            "narrative_summary must expose {key}"
        );
    }
    let events = body["events"].as_array().expect("events array");
    assert!(events.iter().any(|event| event["type"] == "roll"));

    let (status, body) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v2/reading-sessions/93102/details",
            &ctx.token,
            &ctx.csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
}

#[tokio::test]
async fn v2_snapshot_reads_are_equivalent_and_owner_scoped() {
    let ctx = setup("session-v2-snapshots").await;
    for uri in [
        "/api/v2/reading-sessions/93101/snapshots",
        "/api/v2/undo/93101/snapshots",
    ] {
        let (status, body) = send(&ctx.state, authed("GET", uri, &ctx.token, &ctx.csrf)).await;
        assert_eq!(status, StatusCode::OK, "{uri}: {body:?}");
        assert_eq!(body["session_id"], 93101);
        let snapshots = body["snapshots"].as_array().expect("snapshots array");
        assert_eq!(snapshots.len(), 2);
        assert!(snapshots.iter().all(|item| item["session_id"] == 93101));

        let foreign = uri.replace("93101", "93102");
        let (status, body) = send(&ctx.state, authed("GET", &foreign, &ctx.token, &ctx.csrf)).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{foreign}: {body:?}");
    }
}

#[tokio::test]
async fn v2_undo_restore_preserves_session_and_snoozes() {
    let ctx = setup("session-v2-undo").await;
    let (status, body) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/undo/93101/snapshots/94101/restore",
            &ctx.token,
            &ctx.csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["id"], 93101);
    assert_eq!(body["user_id"], ctx.user_id);
    assert_eq!(body["snoozed_thread_ids"][0], 92101);
    assert_eq!(body["has_restore_point"], true);

    let (status, body) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/undo/93102/snapshots/94101/restore",
            &ctx.token,
            &ctx.csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
}

#[tokio::test]
async fn retired_session_and_undo_aliases_stay_404() {
    let ctx = setup("session-v2-retired").await;
    let paths: &[(&str, &str)] = &[
        ("GET", "/api/v1/sessions/93101/details"),
        ("GET", "/api/v1/sessions/93101/snapshots"),
        ("GET", "/api/v1/sessions/current/"),
        ("GET", "/api/sessions/93101/details"),
        ("GET", "/api/v1/undo/93101/snapshots"),
        ("GET", "/api/undo/93101/snapshots"),
        ("POST", "/api/v1/undo/93101/snapshots/94101/restore"),
        ("POST", "/api/undo/93101/undo/94101"),
    ];
    for (method, path) in paths {
        let (status, body) = send(&ctx.state, authed(method, path, &ctx.token, &ctx.csrf)).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{method} {path}: {body:?}");
    }
}
