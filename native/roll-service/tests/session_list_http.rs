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

async fn send(state: &Arc<AppState>, auth: (&str, &str), path: &str) -> (StatusCode, Value) {
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
    assert_eq!(
        status,
        StatusCode::OK,
        "list must be mounted and authenticated"
    );
    let items = page_one["reading_sessions"]
        .as_array()
        .expect("session array");
    assert_eq!(items.len(), 2);
    assert_eq!(
        items[0]["name"].as_str(),
        Some(format!("readingSessions/{third}").as_str())
    );
    assert_eq!(items[0]["session_id"].as_i64(), Some(i64::from(third)));
    assert_eq!(items[0]["current_die"].as_i64(), Some(12));
    assert_eq!(items[0]["event_count"].as_i64(), Some(1));
    assert_eq!(items[0]["snapshot_count"].as_i64(), Some(1));
    assert_eq!(
        items[1]["name"].as_str(),
        Some(format!("readingSessions/{second}").as_str())
    );
    let token = page_one["next_page_token"]
        .as_str()
        .expect("continuation token");

    let (status, page_two) = send(
        &state,
        owner,
        &format!("/api/v2/readingSessions?page_size=2&page_token={token}"),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let items = page_two["reading_sessions"]
        .as_array()
        .expect("session array");
    assert_eq!(items.len(), 1);
    assert_eq!(
        items[0]["name"].as_str(),
        Some(format!("readingSessions/{first}").as_str())
    );
    assert!(
        page_two["next_page_token"].is_null(),
        "last page has no cursor"
    );

    let (status, detail) = send(&state, owner, &format!("/api/v2/readingSessions/{third}")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        detail["name"].as_str(),
        Some(format!("readingSessions/{third}").as_str())
    );
    assert_eq!(detail["start_die"].as_i64(), Some(10));
    assert_eq!(detail["ladder_path"].as_str(), Some("10 → 12"));

    let (status, _) = send(&state, owner, &format!("/api/v2/readingSessions/{foreign}")).await;
    assert_eq!(
        status,
        StatusCode::NOT_FOUND,
        "foreign session is indistinguishable"
    );
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

#[tokio::test]
async fn canonical_session_resources_claim_sessionless_rate_events_in_window() {
    let (state, _guard) = database().await;
    let (owner_token, owner_csrf, owner_id) =
        register(&state, "sessions_list_sessionless_owner").await;
    let (_other_token, _other_csrf, other_id) =
        register(&state, "sessions_list_sessionless_other").await;
    let owner = (owner_token.as_str(), owner_csrf.as_str());

    let older = insert_session(&state, owner_id, "2026-11-25T01:00:00Z", 6).await;
    let current = insert_session(&state, owner_id, "2026-11-26T01:00:00Z", 10).await;

    let conn = state.pool.get().await.unwrap();
    let sql = "INSERT INTO events (user_id, session_id, type, timestamp, die_after, context)
               VALUES ($1, NULL, 'rate', $2, $3, '{}'::json)";
    // Dice/read writes carry user_id but no session_id; each belongs only to
    // the window that contains it.
    for (at, user, die) in [
        ("2026-11-26T01:05:00Z", owner_id, 14), // inside the current window
        ("2026-11-25T01:05:00Z", owner_id, 9),  // inside the older window
        ("2026-11-24T01:00:00Z", owner_id, 3),  // before both windows
        ("2026-11-26T01:06:00Z", other_id, 99), // other reader's action
    ] {
        let timestamp: DateTime<Utc> = at.parse().unwrap();
        conn.execute(sql, &[&user, &timestamp, &die]).await.unwrap();
    }
    drop(conn);

    let (status, active) = send(&state, owner, &format!("/api/v2/readingSessions/{current}")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(active["event_count"].as_i64(), Some(1));
    assert_eq!(active["current_die"].as_i64(), Some(14));
    assert_eq!(active["ladder_path"].as_str(), Some("10 → 14"));

    let (status, previous) = send(&state, owner, &format!("/api/v2/readingSessions/{older}")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(previous["event_count"].as_i64(), Some(1));
    assert_eq!(previous["ladder_path"].as_str(), Some("6 → 9"));

    let (status, list) = send(&state, owner, "/api/v2/readingSessions?page_size=10").await;
    assert_eq!(status, StatusCode::OK);
    let items = list["reading_sessions"].as_array().unwrap();
    assert_eq!(items.len(), 2);
    assert_eq!(items[0]["event_count"].as_i64(), Some(1));
    assert_eq!(items[0]["current_die"].as_i64(), Some(14));

    // The canonical List/Get projection must agree with the /details endpoint
    // for the same session instead of losing the modern dice/read history.
    let (status, details) = send(
        &state,
        owner,
        &format!("/api/v2/readingSessions/{current}/details"),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(details["current_die"].as_i64(), Some(14));
    assert_eq!(details["ladder_path"].as_str(), Some("10 → 14"));
    assert_eq!(details["events"].as_array().unwrap().len(), 1);
}

#[tokio::test]
async fn canonical_session_resources_ignore_roll_rating_companion_events() {
    let (state, _guard) = database().await;
    let (owner_token, owner_csrf, owner_id) =
        register(&state, "sessions_list_companion_owner").await;
    let owner = (owner_token.as_str(), owner_csrf.as_str());
    let session = insert_session(&state, owner_id, "2026-11-26T01:00:00Z", 6).await;

    let conn = state.pool.get().await.unwrap();
    let companion_at: DateTime<Utc> = "2026-11-26T01:05:00Z".parse().unwrap();
    conn.execute(
        "INSERT INTO events (user_id, session_id, type, timestamp, die_after, context)
         VALUES ($1, NULL, 'rate', $2, 8, '{\"dice_command\":{\"kind\":\"roll_rating\"}}'::json)",
        &[&owner_id, &companion_at],
    )
    .await
    .unwrap();
    let reader_at: DateTime<Utc> = "2026-11-26T01:05:01Z".parse().unwrap();
    conn.execute(
        "INSERT INTO events (user_id, session_id, type, timestamp, die_after, context)
         VALUES ($1, NULL, 'rate', $2, 8, '{\"source\":\"roll_offer\"}'::json)",
        &[&owner_id, &reader_at],
    )
    .await
    .unwrap();
    drop(conn);

    let (status, resource) =
        send(&state, owner, &format!("/api/v2/readingSessions/{session}")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(resource["event_count"].as_i64(), Some(1));
    assert_eq!(resource["ladder_path"].as_str(), Some("6 → 8"));
    assert_eq!(resource["current_die"].as_i64(), Some(8));
}

#[tokio::test]
async fn canonical_session_resources_include_sessionless_manual_die_selection() {
    let (state, _guard) = database().await;
    let (owner_token, owner_csrf, owner_id) = register(&state, "sessions_list_manual_owner").await;
    let (_other_token, _other_csrf, other_id) =
        register(&state, "sessions_list_manual_other").await;
    let owner = (owner_token.as_str(), owner_csrf.as_str());
    let session = insert_session(&state, owner_id, "2026-11-26T01:00:00Z", 6).await;

    let conn = state.pool.get().await.unwrap();
    let manual_at: DateTime<Utc> = "2026-11-26T01:05:00Z".parse().unwrap();
    conn.execute(
        "INSERT INTO events (user_id, session_id, type, timestamp, die, die_after, context)
         VALUES ($1, NULL, 'manual_die', $2, 10, 12,
                 '{\"dice_command\":{\"kind\":\"manual_select\",\"die\":12}}'::json)",
        &[&owner_id, &manual_at],
    )
    .await
    .unwrap();
    // A foreign reader's manual selection in the same window must not leak in.
    let foreign_at: DateTime<Utc> = "2026-11-26T01:06:00Z".parse().unwrap();
    conn.execute(
        "INSERT INTO events (user_id, session_id, type, timestamp, die, die_after)
         VALUES ($1, NULL, 'manual_die', $2, 10, 20)",
        &[&other_id, &foreign_at],
    )
    .await
    .unwrap();
    drop(conn);

    let (status, get) = send(&state, owner, &format!("/api/v2/readingSessions/{session}")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(get["event_count"].as_i64(), Some(1));
    assert_eq!(get["current_die"].as_i64(), Some(12));
    assert_eq!(get["ladder_path"].as_str(), Some("6 → 12"));

    let (status, list) = send(&state, owner, "/api/v2/readingSessions?page_size=10").await;
    assert_eq!(status, StatusCode::OK);
    let items = list["reading_sessions"].as_array().unwrap();
    assert_eq!(items.len(), 1);
    assert_eq!(items[0]["event_count"].as_i64(), Some(1));
    assert_eq!(items[0]["current_die"].as_i64(), Some(12));
    assert_eq!(items[0]["ladder_path"].as_str(), Some("6 → 12"));

    let (status, details) = send(
        &state,
        owner,
        &format!("/api/v2/readingSessions/{session}/details"),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(details["current_die"].as_i64(), Some(12));
    assert_eq!(details["ladder_path"].as_str(), Some("6 → 12"));
    let events = details["events"].as_array().unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0]["type"].as_str(), Some("manual_die"));
}

#[tokio::test]
async fn canonical_session_resources_record_sessionless_reset_after_rate() {
    let (state, _guard) = database().await;
    let (owner_token, owner_csrf, owner_id) = register(&state, "sessions_list_reset_owner").await;
    let owner = (owner_token.as_str(), owner_csrf.as_str());
    let session = insert_session(&state, owner_id, "2026-11-26T01:00:00Z", 6).await;

    let conn = state.pool.get().await.unwrap();
    let rate_at: DateTime<Utc> = "2026-11-26T01:05:00Z".parse().unwrap();
    conn.execute(
        "INSERT INTO events (user_id, session_id, type, timestamp, die, die_after, context)
         VALUES ($1, NULL, 'rate', $2, 20, 20, '{}'::json)",
        &[&owner_id, &rate_at],
    )
    .await
    .unwrap();
    let reset_at: DateTime<Utc> = "2026-11-26T01:10:00Z".parse().unwrap();
    conn.execute(
        "INSERT INTO events (user_id, session_id, type, timestamp, die, die_after, context)
         VALUES ($1, NULL, 'reset_dice', $2, 20, 6,
                 '{\"dice_command\":{\"kind\":\"reset\"}}'::json)",
        &[&owner_id, &reset_at],
    )
    .await
    .unwrap();
    drop(conn);

    let (status, get) = send(&state, owner, &format!("/api/v2/readingSessions/{session}")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(get["event_count"].as_i64(), Some(2));
    assert_eq!(get["current_die"].as_i64(), Some(6));
    assert_eq!(get["ladder_path"].as_str(), Some("6 → 20 → 6"));

    let (status, list) = send(&state, owner, "/api/v2/readingSessions?page_size=10").await;
    assert_eq!(status, StatusCode::OK);
    let items = list["reading_sessions"].as_array().unwrap();
    assert_eq!(items.len(), 1);
    assert_eq!(items[0]["event_count"].as_i64(), Some(2));
    assert_eq!(items[0]["current_die"].as_i64(), Some(6));
    assert_eq!(items[0]["ladder_path"].as_str(), Some("6 → 20 → 6"));

    let (status, details) = send(
        &state,
        owner,
        &format!("/api/v2/readingSessions/{session}/details"),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(details["current_die"].as_i64(), Some(6));
    assert_eq!(details["ladder_path"].as_str(), Some("6 → 20 → 6"));
    let types: Vec<&str> = details["events"]
        .as_array()
        .unwrap()
        .iter()
        .map(|event| event["type"].as_str().unwrap())
        .collect();
    assert_eq!(types, ["reset_dice", "rate"]);
}
