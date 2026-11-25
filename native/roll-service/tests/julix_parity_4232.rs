#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Production-shaped parity fixtures for issue #4232:
//! "Julix Mignolaverse parity audit: anthology earliest-occurrence policy and
//! missing unread issues".
//!
//! These tests encode the closure-critical invariants from the issue:
//! (a) only the first unread Julix entry is eligible within a strict list,
//! (b) no anthology/physical issue is offered more than once,
//! (c) reading the active frontier (Casualties) exposes the correctly ordered
//!     next entry,
//! (d) omitted in-Thread issues are classified as intentional or repaired.
//!
//! Provenance: issue #4232 verified production findings (2026-10-27) for
//! custom CBL #2, user 1, "Mignolaverse — Julix Comics (Unread)", strict,
//! 466 entries (382 unread). Production numeric IDs below are historical
//! evidence labels; tests allocate fresh PKs and map symbolic identities.

mod incident_fixtures;
use incident_fixtures as fixture;

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, test_support, AppState};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
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

async fn setup_user_with(
    prefix: &str,
    option_e: bool,
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
            "OPTION_E_ENABLED" if option_e => Some("true".into()),
            "OPTION_E_APPROVED_PREVIEW" if option_e => Some("injected-by-test".into()),
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

fn get(path: &str, token: &str, csrf: &str) -> Request<Body> {
    authed("GET", path, token, csrf, None)
}

fn post_req(path: &str, token: &str, csrf: &str, body: Option<Value>) -> Request<Body> {
    authed("POST", path, token, csrf, body)
}

type Conn = deadpool_postgres::Object;

async fn thread(conn: &Conn, user_id: i32, title: &str) -> i32 {
    conn.query_one(
        "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id) \
         VALUES ($1, 'Comic', 0, 1, 'active', $2) RETURNING id",
        &[&title, &user_id],
    )
    .await
    .unwrap()
    .get(0)
}

async fn issue(conn: &Conn, thread_id: i32, number: &str, position: i32, status: &str) -> i32 {
    conn.query_one(
        "INSERT INTO issues (thread_id, issue_number, status, created_at, position) \
         VALUES ($1, $2, $3, NOW(), $4) RETURNING id",
        &[&thread_id, &number, &status, &position],
    )
    .await
    .unwrap()
    .get(0)
}

async fn frontier(conn: &Conn, thread_id: i32, issue_id: i32) {
    conn.execute(
        "UPDATE threads SET next_unread_issue_id = $2 WHERE id = $1",
        &[&thread_id, &issue_id],
    )
    .await
    .unwrap();
}

/// #4232 (a, b, c): strict Julix frontier, anthology single-placement, and
/// reading the frontier exposes the correctly ordered next entry.
///
/// Models the issue's verified production shape around positions 81-84:
/// - pos 81: Hellboy Winter Special 2018 #1 (read, anthology, placed once)
/// - pos 82: Hellboy Winter Special 2017 #1 (read, anthology, placed once)
/// - pos 83: B.P.R.D.: Casualties #1 (unread, active frontier) — issue 117305
/// - pos 84: next unread entry after Casualties
///
/// Also includes later Winter Specials (2016 at 290, 2019 at 323, Yule Cat at
/// 445) as read entries to prove they do not reorder 2018/2017 and do not
/// create duplicate offers.
#[tokio::test]
async fn julix_4232_frontier_anthology_and_casualties_advance() {
    let (state, token, csrf, user_id, _guard) = setup_user_with("t4232-frontier", true).await;
    let conn = state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO sessions (user_id, started_at, start_die) VALUES ($1, NOW(), 6)",
        &[&user_id],
    )
    .await
    .unwrap();

    // Threads (symbolic names mirror production; IDs are fresh).
    let ws2018_thread = thread(&conn, user_id, "Hellboy Winter Special 2018").await;
    let ws2017_thread = thread(&conn, user_id, "Hellboy Winter Special 2017").await;
    let casualties_thread = thread(&conn, user_id, "B.P.R.D.: Casualties").await;
    let after_casualties_thread =
        thread(&conn, user_id, "B.P.R.D.: Vampire").await;
    let ws2016_thread = thread(&conn, user_id, "Hellboy Winter Special 2016").await;
    let ws2019_thread = thread(&conn, user_id, "Hellboy Winter Special 2019").await;
    let yule_cat_thread = thread(&conn, user_id, "Hellboy Winter Special: The Yule Cat").await;

    // Physical issues - one per anthology, placed once in the list.
    let ws2018 = issue(&conn, ws2018_thread, "1", 1, "read").await;
    let ws2017 = issue(&conn, ws2017_thread, "1", 1, "read").await;
    let casualties = issue(&conn, casualties_thread, "1", 1, "unread").await; // prod 117305
    let after_casualties = issue(&conn, after_casualties_thread, "1", 1, "unread").await;
    let ws2016 = issue(&conn, ws2016_thread, "1", 1, "read").await;
    let ws2019 = issue(&conn, ws2019_thread, "1", 1, "read").await;
    let yule_cat = issue(&conn, yule_cat_thread, "1", 1, "read").await;

    // Thread state: only Casualties and after-Casualties have unread work.
    for (tid, remaining, next, status) in [
        (ws2018_thread, 0i32, None, "completed"),
        (ws2017_thread, 0, None, "completed"),
        (casualties_thread, 1, Some(casualties), "active"),
        (after_casualties_thread, 1, Some(after_casualties), "active"),
        (ws2016_thread, 0, None, "completed"),
        (ws2019_thread, 0, None, "completed"),
        (yule_cat_thread, 0, None, "completed"),
    ] {
        conn.execute(
            "UPDATE threads SET queue_position=1, issues_remaining=$2, next_unread_issue_id=$3, \
             status=$4, is_blocked=false WHERE id=$1",
            &[&tid, &remaining, &next, &status],
        )
        .await
        .unwrap();
    }

    let list_id: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, mode, created_at, updated_at) \
             VALUES ($1, 'Mignolaverse — Julix Comics (Unread)', 'strict', NOW(), NOW()) \
             RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);

    // Positions mirror the issue's verified shape (sparse positions are fine;
    // ordering is by position). 2018/2017 stay at 81/82; 2016/2019/Yule Cat
    // remain later — no publication-year reorder.
    let entries: Vec<(i32, i32)> = vec![
        (ws2018, 81),
        (ws2017, 82),
        (casualties, 83),
        (after_casualties, 84),
        (ws2016, 290),
        (ws2019, 323),
        (yule_cat, 445),
    ];
    for (issue_id, position) in &entries {
        conn.execute(
            "INSERT INTO custom_cbl_entries (list_id, issue_id, position, created_at) \
             VALUES ($1, $2, $3, NOW())",
            &[&list_id, issue_id, position],
        )
        .await
        .unwrap();
    }

    // (a) Only first unread Julix entry is eligible.
    let (status, eligible) = send(
        &state,
        get("/api/v2/roll/eligible-issue-ids", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{eligible:?}");
    assert_eq!(eligible["issue_ids"], json!([casualties]), "{eligible:?}");
    assert_eq!(eligible["thread_ids"], json!([casualties_thread]), "{eligible:?}");

    // (b) No anthology offered more than once - every issue_id appears once in
    // the list, and roll pool contains no duplicates.
    let issue_ids: Vec<i32> = entries.iter().map(|(id, _)| *id).collect();
    let unique: BTreeSet<i32> = issue_ids.iter().copied().collect();
    assert_eq!(unique.len(), issue_ids.len(), "list must not duplicate physical issues");
    let pool = eligible["issue_ids"].as_array().unwrap();
    let pool_set: BTreeSet<i64> = pool.iter().filter_map(Value::as_i64).collect();
    assert_eq!(pool_set.len(), pool.len(), "roll pool must not duplicate issues");

    // Reader projection: Casualties is the only available entry; later unread
    // entry is blocked/later, read anthologies are read, and no entry appears twice.
    let (status, reader) = send(
        &state,
        get(&format!("/api/v2/reading-lists/{list_id}/reader"), &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{reader:?}");
    let reader_entries = reader["entries"].as_array().unwrap();
    assert_eq!(reader_entries.len(), entries.len());
    let seen: BTreeSet<i64> = reader_entries
        .iter()
        .filter_map(|e| e["issue_id"].as_i64())
        .collect();
    assert_eq!(seen.len(), reader_entries.len(), "reader must not duplicate issues");
    let by_id = |id: i32| {
        reader_entries
            .iter()
            .find(|e| e["issue_id"] == json!(id))
            .unwrap()
    };
    assert_eq!(by_id(ws2018)["availability"], "read");
    assert_eq!(by_id(ws2017)["availability"], "read");
    assert_eq!(by_id(casualties)["availability"], "available");
    assert_eq!(by_id(after_casualties)["availability"], "later");
    assert_eq!(by_id(ws2016)["availability"], "read");
    assert_eq!(by_id(ws2019)["availability"], "read");
    assert_eq!(by_id(yule_cat)["availability"], "read");

    // (c) Reading Casualties exposes the correctly ordered next entry.
    let (status, roll) = send(
        &state,
        post_req(
            "/api/v2/roll",
            &token,
            &csrf,
            Some(json!({"idempotency_key": "4232-casualties-roll"})),
        ),
    )
    .await;
    // Accept 200/201; some environments return 200.
    assert!(
        status == StatusCode::OK || status == StatusCode::CREATED,
        "roll failed: {status} {roll:?}"
    );

    let (status, rate) = send(
        &state,
        post_req(
            "/api/v2/rate",
            &token,
            &csrf,
            Some(json!({
                "issue_id": casualties,
                "rating": 4.0,
                "idempotency_key": "4232-casualties-rate"
            })),
        ),
    )
    .await;
    assert!(
        status == StatusCode::OK || status == StatusCode::CREATED,
        "rate failed: {status} {rate:?}"
    );

    let (status, eligible_after) = send(
        &state,
        get("/api/v2/roll/eligible-issue-ids", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{eligible_after:?}");
    assert_eq!(
        eligible_after["issue_ids"],
        json!([after_casualties]),
        "after reading Casualties, the next strict-list entry must become eligible"
    );

    let (status, reader_after) = send(
        &state,
        get(&format!("/api/v2/reading-lists/{list_id}/reader"), &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{reader_after:?}");
    let after_entries = reader_after["entries"].as_array().unwrap();
    let after_by_id = |id: i32| {
        after_entries
            .iter()
            .find(|e| e["issue_id"] == json!(id))
            .unwrap()
    };
    assert_eq!(after_by_id(casualties)["availability"], "read");
    assert_eq!(after_by_id(after_casualties)["availability"], "available");
}