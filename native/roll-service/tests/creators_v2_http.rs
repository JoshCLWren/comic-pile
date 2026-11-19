#![allow(clippy::unwrap_used, clippy::expect_used)]
//! PostgreSQL-backed HTTP regressions for the native `/api/v2/creators` reads
//! (#4836). Seeds real `integer` rows (issues, threads, events, external
//! identities, mappings) so the library loader's column decoding, SQL scoping
//! and set-based coverage are exercised against the canonical schema. Requires
//! `RUST_ROLL_TEST_DATABASE_URL` and hard-fails without it.

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

type Conn = deadpool_postgres::Object;

async fn thread(conn: &Conn, user_id: i32, title: &str, manual: Option<Value>) -> i32 {
    let manual = manual.unwrap_or_else(|| json!([]));
    conn.query_one(
        "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, \
         manual_creator_credits) VALUES ($1, 'Comic', 0, 1, 'active', $2, $3) RETURNING id",
        &[&title, &user_id, &manual],
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

async fn credit_identity(conn: &Conn, issue_id: i32, external_id: &str, credits: Value) {
    let identity: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, \
             created_at, updated_at) VALUES ('comicvine', 'issue', $1, $2, NOW(), NOW()) RETURNING id",
            &[&external_id, &json!({"creator_credits": credits})],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, \
         created_at, updated_at, evidence_json) VALUES ($1, $2, 'confirmed', NOW(), NOW(), '{}'::json)",
        &[&issue_id, &identity],
    )
    .await
    .unwrap();
}

async fn rate(conn: &Conn, user_id: i32, thread_id: i32, issue_id: i32, rating: f64) {
    conn.execute(
        "INSERT INTO events (type, timestamp, thread_id, issue_id, rating, user_id) \
         VALUES ('rate', NOW(), $1, $2, $3, $4)",
        &[&thread_id, &issue_id, &rating, &user_id],
    )
    .await
    .unwrap();
}

fn get(path: &str, token: &str, csrf: &str) -> Request<Body> {
    authed("GET", path, token, csrf, None)
}

fn writer(id: i64, name: &str) -> Value {
    json!({"id": id, "name": name, "role": "writer"})
}

fn cover(id: i64, name: &str) -> Value {
    json!({"id": id, "name": name, "role": "cover"})
}

struct Seed {
    thread_a: i32,
}

/// Library: creator 100 writes A#1 (read, 4.5), A#2 (read, unrated), A#3
/// (unread) and only covers A#4 (read, 2.0); creator 200 writes B#1 (read, 3.0)
/// via the thread's manual credits; one issue has no credit metadata at all.
async fn seed(conn: &Conn, user_id: i32) -> Seed {
    let thread_a = thread(conn, user_id, "Series A", None).await;
    let a1 = issue(conn, thread_a, "1", 1, "read").await;
    let a2 = issue(conn, thread_a, "2", 2, "read").await;
    let a3 = issue(conn, thread_a, "3", 3, "unread").await;
    let a4 = issue(conn, thread_a, "4", 4, "read").await;
    credit_identity(conn, a1, "cv-a1", json!([writer(100, "Writer One")])).await;
    credit_identity(conn, a2, "cv-a2", json!([writer(100, "Writer One")])).await;
    credit_identity(conn, a3, "cv-a3", json!([writer(100, "Writer One")])).await;
    credit_identity(conn, a4, "cv-a4", json!([cover(100, "Writer One")])).await;
    rate(conn, user_id, thread_a, a1, 4.5).await;
    rate(conn, user_id, thread_a, a4, 2.0).await;
    let thread_b = thread(
        conn,
        user_id,
        "Series B",
        Some(json!([{"name": "Manual Maker", "roles": ["writer"]}])),
    )
    .await;
    let b1 = issue(conn, thread_b, "1", 1, "read").await;
    rate(conn, user_id, thread_b, b1, 3.0).await;
    let thread_c = thread(conn, user_id, "Series C", None).await;
    issue(conn, thread_c, "1", 1, "read").await;
    Seed { thread_a }
}

#[tokio::test]
async fn every_operation_requires_authentication() {
    let (state, _token, _csrf, _user_id, _guard) = setup_user("crv2-auth").await;
    for path in [
        "/api/v2/creators",
        "/api/v2/creators/summaries?keys=creator:1",
        "/api/v2/creators/compare?keys=creator:1,creator:2",
        "/api/v2/creators/discoveries",
        "/api/v2/creators/team-chemistry",
        "/api/v2/creators/creator:1",
        "/api/v2/creators/creator:1/series/thread:1/issues",
        "/api/v2/creators/creator:1/metrics/average-rating",
    ] {
        let (status, body) = send(
            &state,
            Request::builder()
                .method("GET")
                .uri(path)
                .body(Body::empty())
                .unwrap(),
        )
        .await;
        assert_eq!(status, StatusCode::UNAUTHORIZED, "{path}: {body:?}");
    }
}

#[tokio::test]
async fn loader_reads_integer_columns_and_scoped_reads_match_full_library() {
    let (state, token, csrf, user_id, _guard) = setup_user("crv2-load").await;
    let conn = state.pool.get().await.unwrap();
    let seeded = seed(&conn, user_id).await;

    // Full-library path (Rust-computed coverage, real integer rows).
    let (status, list) = send(&state, get("/api/v2/creators", &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{list:?}");
    let items = list["items"].as_array().unwrap();
    let by_key = |key: &str| items.iter().find(|i| i["canonical_creator_key"] == key);
    let one = by_key("creator:100").expect("creator 100 listed");
    // Cover-only issue 4 is excluded from the headline average: only a1 counts.
    assert_eq!(one["ratings_count"], 1);
    assert_eq!(one["average_rating"], 4.5);
    let manual_key = items
        .iter()
        .map(|i| i["canonical_creator_key"].as_str().unwrap())
        .find(|k| *k != "creator:100")
        .expect("manual creator listed")
        .to_string();

    // Scoped path (SQL-filtered library + SQL coverage totals) must agree.
    let (status, summaries) = send(
        &state,
        get(
            &format!("/api/v2/creators/summaries?keys=creator:100,{manual_key}"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{summaries:?}");
    assert_eq!(summaries["coverage"], list["coverage"]);
    let summary = &summaries["summaries"]["creator:100"];
    assert_eq!(summary["ratings_count"], 1);
    assert_eq!(summary["average_rating"], 4.5);
    assert_eq!(summary["read_unrated_count"], 1);
    assert_eq!(summary["upcoming_count"], 1);
    assert_eq!(summaries["summaries"][&manual_key]["average_rating"], 3.0);
    assert_eq!(list["coverage"]["rated_issues_total"], 3);
    assert_eq!(list["coverage"]["rated_issues_with_creator_metadata"], 3);
    assert_eq!(list["coverage"]["read_unrated_issues_total"], 2);
    assert_eq!(
        list["coverage"]["read_unrated_issues_with_creator_metadata"],
        1
    );

    let (status, detail) = send(&state, get("/api/v2/creators/creator:100", &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{detail:?}");
    assert_eq!(detail["coverage"], list["coverage"]);
    assert_eq!(detail["summary"]["ratings_count"], 1);
    assert_eq!(detail["series_groups_total"], 1);

    let (status, series) = send(
        &state,
        get(
            &format!(
                "/api/v2/creators/creator:100/series/thread:{}/issues",
                seeded.thread_a
            ),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{series:?}");
    assert_eq!(series["thread_id"], seeded.thread_a);

    let (status, drill) = send(
        &state,
        get(
            "/api/v2/creators/creator:100/metrics/read-unrated-count",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{drill:?}");
    assert_eq!(drill["total_count"], 1, "{drill:?}");
    let drilled = drill["included_issues"].as_array().unwrap();
    assert_eq!(drilled.len(), 1);
    assert_eq!(drilled[0]["missing_rating_cause"], "no_source_rating");

    let (status, _) = send(&state, get("/api/v2/creators/creator:999", &token, &csrf)).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, compare) = send(
        &state,
        get(
            &format!("/api/v2/creators/compare?keys=creator:100,{manual_key}"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{compare:?}");
    let (status, _) = send(&state, get("/api/v2/creators/discoveries", &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK);
    let (status, _) = send(
        &state,
        get("/api/v2/creators/team-chemistry", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
}

#[tokio::test]
async fn creators_are_isolated_per_user() {
    let (state, token, csrf, user_id, _guard) = setup_user("crv2-iso").await;
    let (token2, csrf2, user2) = register_extra_user(&state, "crv2-iso2").await;
    let conn = state.pool.get().await.unwrap();
    seed(&conn, user_id).await;
    let (status, body) = send(&state, get("/api/v2/creators/creator:100", &token2, &csrf2)).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
    let (status, body) = send(&state, get("/api/v2/creators", &token2, &csrf2)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["total"], 0);
    let (status, body) = send(&state, get("/api/v2/creators/creator:100", &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let _ = user2;
}

#[tokio::test]
async fn invalid_requests_map_to_validation_and_bad_request() {
    let (state, token, csrf, _user_id, _guard) = setup_user("crv2-422").await;
    let (status, _) = send(&state, get("/api/v2/creators/not-a-key", &token, &csrf)).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    let (status, _) = send(
        &state,
        get("/api/v2/creators/summaries?keys=bad", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    let (status, _) = send(&state, get("/api/v2/creators?limit=0", &token, &csrf)).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
}
