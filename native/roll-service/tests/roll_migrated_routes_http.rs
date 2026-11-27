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
                .uri("/api/v2/auth/register")
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

/// Seed the owned/foreign session drill-down rows used by the #5885 HTTP
/// regressions. High, fixed IDs avoid the sequence values allocated by the
/// register calls in `setup_user` / `register_extra_user`.
async fn seed_session_drilldown_fixture(state: &Arc<AppState>, owner_id: i32, foreign_id: i32) {
    let connection = state.pool.get().await.unwrap();
    connection
        .batch_execute(&format!(
            "INSERT INTO threads (id, user_id, title, format, issues_remaining, total_issues, reading_progress, queue_position, status, is_blocked)
             VALUES (9711, {owner_id}, 'Owned Comic', 'Comic', 2, 2, NULL, 1, 'active', false);
             INSERT INTO sessions (id, user_id, started_at, ended_at, start_die, manual_die, reading_mode_suggested, snoozed_thread_ids)
             VALUES (9701, {owner_id}, NOW(), NULL, 6, NULL, false, '[]'::json),
                    (9702, {foreign_id}, NOW(), NULL, 6, NULL, false, '[]'::json);
             INSERT INTO events (session_id, type, timestamp, thread_id, selected_thread_id, die, result, die_after, rating)
             VALUES (9701, 'roll', NOW(), 9711, 9711, 6, 4, NULL, NULL),
                    (9701, 'rate', NOW() + interval '1 second', 9711, NULL, 6, NULL, 8, 4.0);
             INSERT INTO snapshots (id, session_id, thread_states, session_state, created_at, description)
             VALUES (9721, 9701, '{{}}'::json, '{{}}'::json, NOW(), 'Session start'),
                    (9722, 9701, '{{}}'::json, '{{}}'::json, NOW() + interval '1 minute', 'After rating'),
                    (9723, 9702, '{{}}'::json, '{{}}'::json, NOW(), 'Foreign snapshot');"
        ))
        .await
        .unwrap();
    drop(connection);
}

#[tokio::test]
async fn session_details_http_preserves_wire_contract_and_owner_scope() {
    let (state, token, csrf, owner, _guard) = setup_user("sessdet").await;
    let (_token2, _csrf2, foreign) = register_extra_user(&state, "sessdetf").await;
    seed_session_drilldown_fixture(&state, owner, foreign).await;

    let (status, body) = send(
        &state,
        authed(
            "GET",
            "/api/v2/readingSessions/9701/details",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    for key in [
        "session_id",
        "started_at",
        "start_die",
        "ladder_path",
        "narrative_summary",
        "current_die",
        "events",
    ] {
        assert!(body.get(key).is_some(), "missing Python wire key `{key}`");
    }
    assert_eq!(body["session_id"].as_i64(), Some(9701));
    assert!(
        body["started_at"]
            .as_str()
            .is_some_and(|value| value.ends_with('Z')),
        "timestamps must stay UTC like the Python contract: {body:?}"
    );
    let summary = body["narrative_summary"].as_object().expect("summary");
    for key in ["read", "skipped", "snoozed", "completed"] {
        assert!(summary[key].is_array(), "`{key}` must always be a list");
    }
    let events = body["events"].as_array().expect("events");
    assert!(!events.is_empty());
    for event in events {
        assert!(
            event["type"].as_str().is_some(),
            "event must expose the Python `type` key: {event:?}"
        );
        assert!(
            event.get("type_").is_none(),
            "Rust field name must not leak onto the wire: {event:?}"
        );
    }

    for path in [
        "/api/v2/readingSessions/9702/details",
        "/api/v2/readingSessions/9999/details",
    ] {
        let (status, body) = send(&state, authed("GET", path, &token, &csrf, None)).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{path}: {body:?}");
        assert_eq!(body["detail"].as_str(), Some("Session not found"));
    }
}

#[tokio::test]
async fn session_and_undo_snapshot_http_reads_are_owner_scoped() {
    let (state, token, csrf, owner, _guard) = setup_user("snapshot").await;
    let (_token2, _csrf2, foreign) = register_extra_user(&state, "snapshotf").await;
    seed_session_drilldown_fixture(&state, owner, foreign).await;

    for path in [
        "/api/v2/readingSessions/9701/snapshots",
        "/api/v2/undo/9701/snapshots",
    ] {
        let (status, body) = send(&state, authed("GET", path, &token, &csrf, None)).await;
        assert_eq!(status, StatusCode::OK, "{path}: {body:?}");
        assert_eq!(body["session_id"].as_i64(), Some(9701));
        let snapshots = body["snapshots"].as_array().expect("snapshots array");
        assert_eq!(snapshots.len(), 2, "{path}");
        for snapshot in snapshots {
            for key in ["id", "session_id", "created_at", "description", "event_id"] {
                assert!(snapshot.get(key).is_some(), "{path} missing `{key}`");
            }
            assert_eq!(snapshot["session_id"].as_i64(), Some(9701));
            assert!(
                snapshot["created_at"]
                    .as_str()
                    .is_some_and(|value| value.ends_with('Z')),
                "{path} must emit UTC timestamps: {snapshot:?}"
            );
        }
        assert!(
            snapshots[0]["created_at"].as_str() >= snapshots[1]["created_at"].as_str(),
            "{path} must return newest snapshots first"
        );

        for (id, detail) in [(9702, "Session not found"), (9999, "Session not found")] {
            let foreign_path = path.replace("/9701/", &format!("/{id}/"));
            let (status, body) =
                send(&state, authed("GET", &foreign_path, &token, &csrf, None)).await;
            assert_eq!(status, StatusCode::NOT_FOUND, "{foreign_path}: {body:?}");
            assert_eq!(body["detail"].as_str(), Some(detail));
        }
    }
}

#[tokio::test]
async fn undo_restore_http_preserves_wire_contract_and_owner_scope() {
    let (state, token, csrf, owner, _guard) = setup_user("undorest").await;
    let (_token2, _csrf2, foreign) = register_extra_user(&state, "undorestf").await;
    seed_session_drilldown_fixture(&state, owner, foreign).await;

    let (status, body) = send(
        &state,
        authed(
            "POST",
            "/api/v2/undo/9701/snapshots/9721/restore",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["id"].as_i64(), Some(9701));
    for key in [
        "started_at",
        "start_die",
        "user_id",
        "ladder_path",
        "current_die",
        "has_restore_point",
        "snapshot_count",
        "snoozed_thread_ids",
        "snoozed_threads",
        "skipped_thread_ids",
        "skipped_threads",
        "reading_mode_suggested",
    ] {
        assert!(body.get(key).is_some(), "missing Python wire key `{key}`");
    }
    for key in ["snoozed_threads", "skipped_threads"] {
        assert!(body[key].is_array(), "`{key}` must always be a list");
    }

    // A foreign session and a snapshot outside the owned session are both
    // indistinguishable from a missing resource.
    for (path, detail) in [
        (
            "/api/v2/undo/9702/snapshots/9723/restore",
            "Session not found",
        ),
        (
            "/api/v2/undo/9701/snapshots/9723/restore",
            "Snapshot not found",
        ),
    ] {
        let (status, body) = send(&state, authed("POST", path, &token, &csrf, None)).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{path}: {body:?}");
        assert_eq!(body["detail"].as_str(), Some(detail));
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
