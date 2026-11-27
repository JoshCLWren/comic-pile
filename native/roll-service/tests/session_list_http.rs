#![allow(clippy::unwrap_used, clippy::expect_used)]
//! DB-backed HTTP regressions for the canonical reading-session collection
//! (#5708). These hit the real mounted router against the disposable canonical
//! schema: owner scope, keyset pagination, stable resource names and the
//! event-derived aggregates are all proven on real PostgreSQL rows.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use chrono::{DateTime, Utc};
use comicpile_roll_service::{config::Config, router, test_support, AppState};
use serde_json::{json, Value};
use std::sync::Arc;
use tower::ServiceExt;

const PASSWORD: &str = "correct-horse-battery";

fn state(url: &str) -> Arc<AppState> {
    Arc::new(test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.into()),
            "RUST_ROLL_JWT_SECRET" => Some(test_support::TEST_JWT_SECRET.into()),
            "RUST_ROLL_POOL_SIZE" => Some("4".into()),
            _ => None,
        })
        .unwrap(),
    ))
}

async fn database() -> (Arc<AppState>, tokio::sync::MutexGuard<'static, ()>) {
    let url = test_support::database_url().await;
    let state = state(&url);
    let guard = test_support::reset_for_test(&state).await;
    (state, guard)
}

async fn register(state: &Arc<AppState>, username: &str) -> (String, String, i32) {
    use std::sync::atomic::{AtomicU16, Ordering};
    static NEXT_IP: AtomicU16 = AtomicU16::new(1);
    let ip = NEXT_IP.fetch_add(1, Ordering::Relaxed);
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v2/auth/register")
                .header(header::CONTENT_TYPE, "application/json")
                .header("x-forwarded-for", format!("198.51.100.{ip}"))
                .body(Body::from(
                    json!({
                        "username": username,
                        "email": format!("{username}@example.com"),
                        "password": PASSWORD,
                    })
                    .to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let csrf = response
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .filter_map(|value| value.to_str().ok())
        .find_map(|cookie| cookie.strip_prefix("csrf_token="))
        .and_then(|rest| rest.split(';').next())
        .expect("register sets a CSRF cookie")
        .to_string();
    let bytes = to_bytes(response.into_body(), 1 << 20).await.unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap();
    let token = body["access_token"].as_str().unwrap().to_string();
    let conn = state.pool.get().await.unwrap();
    let id = conn
        .query_one("SELECT id FROM users WHERE username=$1", &[&username])
        .await
        .unwrap()
        .get::<_, i32>(0);
    (token, csrf, id)
}

async fn send(
    state: &Arc<AppState>,
    auth: (&str, &str),
    path: &str,
) -> (StatusCode, Value) {
    let (token, csrf) = auth;
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("GET")
                .uri(path)
                .header(header::AUTHORIZATION, format!("Bearer {token}"))
                .header(header::COOKIE, format!("csrf_token={csrf}"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 1 << 20).await.unwrap();
    let value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, value)
}

async fn insert_session(state: &Arc<AppState>, user_id: i32, started: &str, die: i32) -> i32 {
    let started_at: DateTime<Utc> = DateTime::parse_from_rfc3339(started)
        .expect("fixture timestamp")
        .with_timezone(&Utc);
    let conn = state.pool.get().await.unwrap();
    conn.query_one(
        "INSERT INTO sessions (user_id, started_at, start_die)
         VALUES ($1, $2, $3) RETURNING id",
        &[&user_id, &started_at, &die],
    )
    .await
    .unwrap()
    .get::<_, i32>(0)
}

#[tokio::test]
async fn canonical_session_list_and_get_are_owner_scoped_and_paginated() {
    let (state, _guard) = database().await;
    let (owner_token, owner_csrf, owner_id) = register(&state, "sessions_list_owner").await;
    let (other_token, other_csrf, other_id) = register(&state, "sessions_list_other").await;
    let owner = (owner_token.as_str(), owner_csrf.as_str());
    let other = (other_token.as_str(), other_csrf.as_str());

    let first = insert_session(&state, owner_id, "2026-11-25T01:00:00Z", 6).await;
    let second = insert_session(&state, owner_id, "2026-11-26T01:00:00Z", 8).await;
    let third = insert_session(&state, owner_id, "2026-11-27T01:00:00Z", 10).await;
    let foreign = insert_session(&state, other_id, "2026-11-28T01:00:00Z", 12).await;

    let conn = state.pool.get().await.unwrap();
    let event_at: DateTime<Utc> = "2026-11-27T01:05:00Z".parse().unwrap();
    conn.execute(
        "INSERT INTO events (type, timestamp, session_id, user_id, die_after, context)
         VALUES ('rate', $1, $2, $3, 12, '{}'::json)",
        &[&event_at, &third, &owner_id],
    )
    .await
    .unwrap();
    let snapshot_at: DateTime<Utc> = "2026-11-27T01:06:00Z".parse().unwrap();
    conn.execute(
        "INSERT INTO snapshots (session_id, event_id, thread_states, created_at)
         VALUES ($1, NULL, '{}'::json, $2)",
        &[&third, &snapshot_at],
    )
    .await
    .unwrap();
    drop(conn);

    let (status, page_one) = send(&state, owner, "/api/v2/readingSessions?page_size=2").await;
    assert_eq!(status, StatusCode::OK, "list must be mounted and authenticated");
    let items = page_one["reading_sessions"].as_array().expect("session array");
    assert_eq!(items.len(), 2);
    assert_eq!(items[0]["name"].as_str(), Some(format!("readingSessions/{third}").as_str()));
    assert_eq!(items[0]["session_id"].as_i64(), Some(i64::from(third)));
    assert_eq!(items[0]["current_die"].as_i64(), Some(12));
    assert_eq!(items[0]["event_count"].as_i64(), Some(1));
    assert_eq!(items[0]["snapshot_count"].as_i64(), Some(1));
    assert_eq!(items[1]["name"].as_str(), Some(format!("readingSessions/{second}").as_str()));
    let token = page_one["next_page_token"].as_str().expect("continuation token");

    let (status, page_two) = send(
        &state,
        owner,
        &format!("/api/v2/readingSessions?page_size=2&page_token={token}"),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let items = page_two["reading_sessions"].as_array().expect("session array");
    assert_eq!(items.len(), 1);
    assert_eq!(items[0]["name"].as_str(), Some(format!("readingSessions/{first}").as_str()));
    assert!(page_two["next_page_token"].is_null(), "last page has no cursor");

    let (status, detail) = send(
        &state,
        owner,
        &format!("/api/v2/readingSessions/{third}"),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(detail["name"].as_str(), Some(format!("readingSessions/{third}").as_str()));
    assert_eq!(detail["start_die"].as_i64(), Some(10));
    assert_eq!(detail["ladder_path"].as_str(), Some("10 → 12"));

    let (status, _) = send(&state, owner, &format!("/api/v2/readingSessions/{foreign}")).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "foreign session is indistinguishable");
    let (status, _) = send(&state, other, &format!("/api/v2/readingSessions/{third}")).await;
    assert_eq!(status, StatusCode::NOT_FOUND);

    let (status, _) = send(&state, owner, "/api/v2/readingSessions?page_size=0").await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    let (status, _) = send(&state, owner, "/api/v2/readingSessions?page_token=forged").await;
    assert_eq!(status, StatusCode::BAD_REQUEST);

    let unauthenticated = router(state.clone())
        .oneshot(
            Request::builder()
                .method("GET")
                .uri("/api/v2/readingSessions")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(unauthenticated.status(), StatusCode::UNAUTHORIZED);
    let bytes = to_bytes(unauthenticated.into_body(), 8192).await.unwrap();
    assert!(String::from_utf8_lossy(&bytes).contains("detail"));
}
