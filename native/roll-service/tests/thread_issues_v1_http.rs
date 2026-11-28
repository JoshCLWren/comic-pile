#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Handler-level HTTP regressions for the same-path thread issue-management
//! operations (#4832 part D).
//!
//! Exercises auth, ownership scoping, ordering and error mapping through the
//! mounted router against the canonical disposable PostgreSQL schema. Requires
//! `RUST_ROLL_TEST_DATABASE_URL` and hard-fails without it.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
    routing::get as route_get,
    Router,
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
    setup_user_with(prefix, false).await
}

/// `option_e` is injected into the state's config; nothing touches the process env.
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
    let state = Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
                "RUST_ROLL_JWT_SECRET" => Some("synthetic-roll-routes-secret".into()),
                "RUST_ROLL_POOL_SIZE" => Some("2".into()),
                "OPTION_E_ENABLED" if option_e => Some("true".into()),
                "OPTION_E_APPROVED_PREVIEW" if option_e => Some("injected-by-test".into()),
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

type Conn = deadpool_postgres::Object;

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

/// Seed several issues in one set-based insert (no SQL inside loops),
/// returning their ids ordered by position.
async fn seed_issues(conn: &Conn, thread_id: i32, numbers: &[&str], status: &str) -> Vec<i32> {
    let positions: Vec<i32> = (1..=numbers.len() as i32).collect();
    let mut rows: Vec<(i32, i32)> = conn
        .query(
            "INSERT INTO issues (thread_id, issue_number, status, created_at, position) \
             SELECT $1, new.number, $2, NOW(), new.position \
             FROM unnest($3::text[], $4::int[]) AS new(number, position) \
             RETURNING id, position",
            &[&thread_id, &status, &numbers, &positions],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();
    rows.sort_by_key(|(_, position)| *position);
    rows.into_iter().map(|(id, _)| id).collect()
}

async fn frontier(conn: &Conn, thread_id: i32, issue_id: i32) {
    conn.execute(
        "UPDATE threads SET next_unread_issue_id = $2 WHERE id = $1",
        &[&thread_id, &issue_id],
    )
    .await
    .unwrap();
}

fn post(path: &str, token: &str, csrf: &str, body: Option<Value>) -> Request<Body> {
    authed("POST", path, token, csrf, body)
}

fn get(path: &str, token: &str, csrf: &str) -> Request<Body> {
    authed("GET", path, token, csrf, None)
}

async fn send_router(router: Router, request: Request<Body>) -> (StatusCode, Value) {
    let response = router.oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

fn creators_test_router(state: &Arc<AppState>) -> Router {
    Router::new()
        .route(
            "/api/v1/threads/{thread_id}/issues/creators",
            route_get(comicpile_roll_service::thread_issues::list_thread_issue_creators),
        )
        .with_state(state.clone())
}

async fn plain_thread(
    conn: &Conn,
    user_id: i32,
    title: &str,
    remaining: i32,
    position: i32,
) -> i32 {
    conn.query_one(
        "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id) \
         VALUES ($1, 'Comic', $2, $3, 'active', $4) RETURNING id",
        &[&title, &remaining, &position, &user_id],
    )
    .await
    .unwrap()
    .get(0)
}

async fn positions(conn: &Conn, thread_id: i32) -> Vec<(String, i32, String)> {
    conn.query(
        "SELECT issue_number, position, status FROM issues WHERE thread_id = $1 ORDER BY position",
        &[&thread_id],
    )
    .await
    .unwrap()
    .iter()
    .map(|r| (r.get(0), r.get(1), r.get(2)))
    .collect()
}

#[tokio::test]
async fn every_operation_requires_authentication() {
    let (state, _token, _csrf, _user_id, _guard) = setup_user("tiss-auth").await;
    for (method, path) in [
        ("POST", "/api/v1/threads/1/issues"),
        ("POST", "/api/v1/threads/1/issues:reorder"),
    ] {
        let (status, _) = send(
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

    // Creators endpoint is not mounted on the public Rust router (vercel routes to
    // Python), but the retained handler must still require authentication.
    let (status, _) = send_router(
        creators_test_router(&state),
        Request::builder()
            .method("GET")
            .uri("/api/v1/threads/1/issues/creators")
            .body(Body::empty())
            .unwrap(),
    )
    .await;
    assert!(
        status == StatusCode::UNAUTHORIZED || status == StatusCode::FORBIDDEN,
        "GET /api/v1/threads/1/issues/creators -> {status}"
    );
}

#[tokio::test]
async fn create_issues_places_naturally_appends_and_anchors() {
    let (state, token, csrf, user_id, _guard) = setup_user("tiss-create").await;
    let conn = state.pool.get().await.unwrap();
    let other = plain_thread(&conn, user_id, "Other", 0, 1).await;
    let thread = plain_thread(&conn, user_id, "Series", 0, 2).await;

    // Unmigrated empty thread: natural order, becomes tracked and active.
    let (status, body) = send(
        &state,
        post(
            &format!("/api/v1/threads/{thread}/issues"),
            &token,
            &csrf,
            Some(json!({"issue_range": "33-35"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body}");
    assert_eq!(body["total_count"], 3);
    assert_eq!(body["page_size"], 3);
    assert!(body["next_page_token"].is_null());
    assert_eq!(body["issues"][0]["issue_number"], "33");
    assert_eq!(body["issues"][0]["status"], "unread");
    assert!(body["issues"][0]["read_at"].is_null());
    assert!(body["issues"][0]["created_at"]
        .as_str()
        .unwrap()
        .ends_with('Z'));

    // Natural placement seats #2 ahead of #33 and shifts the rest.
    let (status, body) = send(
        &state,
        post(
            &format!("/api/v1/threads/{thread}/issues"),
            &token,
            &csrf,
            Some(json!({"issue_range": "2"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body}");
    assert_eq!(body["total_count"], 4);
    assert_eq!(body["issues"].as_array().unwrap().len(), 1);
    assert_eq!(body["issues"][0]["position"], 1);
    let rows = positions(&conn, thread).await;
    assert_eq!(
        rows.iter().map(|r| r.0.as_str()).collect::<Vec<_>>(),
        vec!["2", "33", "34", "35"]
    );
    let next: i32 = conn
        .query_one(
            "SELECT next_unread_issue_id FROM threads WHERE id = $1",
            &[&thread],
        )
        .await
        .unwrap()
        .get(0);
    let first: i32 = conn
        .query_one(
            "SELECT id FROM issues WHERE thread_id = $1 AND position = 1",
            &[&thread],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(next, first);
    let events: i64 = conn
        .query_one(
            "SELECT count(*) FROM events WHERE type = 'issues_created' AND thread_id = $1",
            &[&thread],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(events, 2);

    // Explicit null appends; irregular labels append too.
    let (status, _) = send(
        &state,
        post(
            &format!("/api/v1/threads/{thread}/issues"),
            &token,
            &csrf,
            Some(json!({"issue_range": "3", "insert_after_issue_id": null})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED);
    assert_eq!(positions(&conn, thread).await.last().unwrap().0, "3");

    // A concrete anchor inserts directly after it and shifts later issues.
    let (status, body) = send(
        &state,
        post(
            &format!("/api/v1/threads/{thread}/issues"),
            &token,
            &csrf,
            Some(json!({"issue_range": "Annual 1", "insert_after_issue_id": first})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body}");
    assert_eq!(body["issues"][0]["position"], 2);
    let numbers: Vec<String> = positions(&conn, thread)
        .await
        .into_iter()
        .map(|r| r.0)
        .collect();
    assert_eq!(numbers, vec!["2", "Annual 1", "33", "34", "35", "3"]);

    // Duplicate range, bad range, unknown anchor, foreign anchor.
    let (status, body) = send(
        &state,
        post(
            &format!("/api/v1/threads/{thread}/issues"),
            &token,
            &csrf,
            Some(json!({"issue_range": "33-34"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["detail"], "All issues in range already exist");
    let (status, body) = send(
        &state,
        post(
            &format!("/api/v1/threads/{thread}/issues"),
            &token,
            &csrf,
            Some(json!({"issue_range": "5-3"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["detail"], "Range start (5) cannot exceed end (3)");
    let (status, body) = send(
        &state,
        post(
            &format!("/api/v1/threads/{thread}/issues"),
            &token,
            &csrf,
            Some(json!({"issue_range": "9", "insert_after_issue_id": 99999999})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"], "Issue 99999999 not found");

    // The queue stays dense: the completed-then-reactivated flow is covered by
    // the `other` thread keeping a valid position.
    let positions_after: Vec<i32> = conn
        .query(
            "SELECT queue_position FROM threads WHERE user_id = $1 AND status = 'active' ORDER BY queue_position",
            &[&user_id],
        )
        .await
        .unwrap()
        .iter()
        .map(|r| r.get(0))
        .collect();
    assert_eq!(positions_after, vec![1, 2]);
    let _ = other;
}

#[tokio::test]
async fn create_issues_validation_isolation_and_not_found() {
    let (state, token, csrf, user_id, _guard) = setup_user("tiss-create-guard").await;
    let (other_token, other_csrf, _other_user) =
        register_extra_user(&state, "tiss-create-other").await;
    let conn = state.pool.get().await.unwrap();
    let thread = plain_thread(&conn, user_id, "Mine", 0, 1).await;
    for body in [
        json!({}),
        json!({"issue_range": ""}),
        json!({"issue_range": 5}),
        json!({"issue_range": "1", "insert_after_issue_id": 0}),
        json!({"issue_range": "1", "insert_after_issue_id": "x"}),
    ] {
        let (status, payload) = send(
            &state,
            post(
                &format!("/api/v1/threads/{thread}/issues"),
                &token,
                &csrf,
                Some(body),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(payload["detail"], "Validation failed");
    }
    let (status, _) = send(
        &state,
        post(
            "/api/v1/threads/not-an-int/issues",
            &token,
            &csrf,
            Some(json!({"issue_range": "1"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    let (status, body) = send(
        &state,
        post(
            "/api/v1/threads/987654/issues",
            &token,
            &csrf,
            Some(json!({"issue_range": "1"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"], "Thread 987654 not found");
    // Cross-user: same 404 as a missing thread, and nothing is written.
    let (status, body) = send(
        &state,
        post(
            &format!("/api/v1/threads/{thread}/issues"),
            &other_token,
            &other_csrf,
            Some(json!({"issue_range": "1"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"], format!("Thread {thread} not found"));
    assert!(positions(&conn, thread).await.is_empty());
}

#[tokio::test]
async fn reorder_rewrites_positions_and_validates() {
    let (state, token, csrf, user_id, _guard) = setup_user("tiss-reorder").await;
    let (other_token, other_csrf, _other_user) =
        register_extra_user(&state, "tiss-reorder-other").await;
    let conn = state.pool.get().await.unwrap();
    let thread = plain_thread(&conn, user_id, "Reorder", 3, 1).await;
    let ids = seed_issues(&conn, thread, &["1", "2", "3"], "unread").await;
    frontier(&conn, thread, ids[0]).await;
    let path = format!("/api/v1/threads/{thread}/issues:reorder");

    let (status, _) = send(
        &state,
        post(
            &path,
            &token,
            &csrf,
            Some(json!({"issue_ids": [ids[2], ids[0], ids[1]]})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    let order: Vec<String> = positions(&conn, thread)
        .await
        .into_iter()
        .map(|r| r.0)
        .collect();
    assert_eq!(order, vec!["3", "1", "2"]);
    let row = conn
        .query_one(
            "SELECT next_unread_issue_id, total_issues, issues_remaining, reading_progress FROM threads WHERE id = $1",
            &[&thread],
        )
        .await
        .unwrap();
    assert_eq!(row.get::<_, Option<i32>>(0), Some(ids[2]));
    assert_eq!(row.get::<_, Option<i32>>(1), Some(3));
    assert_eq!(row.get::<_, i32>(2), 3);
    assert_eq!(
        row.get::<_, Option<String>>(3).as_deref(),
        Some("not_started")
    );

    for bad in [
        json!({"issue_ids": [ids[0], ids[1]]}),
        json!({"issue_ids": [ids[0], ids[0], ids[1]]}),
        json!({"issue_ids": [ids[0], ids[1], 424242]}),
    ] {
        let (status, body) = send(&state, post(&path, &token, &csrf, Some(bad))).await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
        assert_eq!(
            body["detail"],
            "issue_ids must contain every issue in the thread exactly once"
        );
    }
    for bad in [
        json!({"issue_ids": []}),
        json!({}),
        json!({"issue_ids": ["x"]}),
    ] {
        let (status, body) = send(&state, post(&path, &token, &csrf, Some(bad))).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(body["detail"], "Validation failed");
    }
    let (status, _) = send(
        &state,
        post(
            "/api/v1/threads/987654/issues:reorder",
            &token,
            &csrf,
            Some(json!({"issue_ids": [1]})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, _) = send(
        &state,
        post(
            &path,
            &other_token,
            &other_csrf,
            Some(json!({"issue_ids": ids})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let order: Vec<String> = positions(&conn, thread)
        .await
        .into_iter()
        .map(|r| r.0)
        .collect();
    assert_eq!(order, vec!["3", "1", "2"]);
}

#[tokio::test]
async fn creators_are_bulk_read_merged_and_owner_scoped() {
    let (state, token, csrf, user_id, _guard) = setup_user("tiss-creators").await;
    let (other_token, other_csrf, _other_user) =
        register_extra_user(&state, "tiss-creators-other").await;
    let conn = state.pool.get().await.unwrap();
    let thread = plain_thread(&conn, user_id, "Credits", 2, 1).await;
    let mapped = issue(&conn, thread, "1", 1, "unread").await;
    let _unmapped = issue(&conn, thread, "2", 2, "unread").await;
    let identity: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'issue', 'cv-1', $1::text::json, NOW(), NOW()) RETURNING id",
            &[&json!({"person_credits": [
                {"id": 7, "name": "Writer", "role": "writer, cover"},
                {"id": 7, "name": "Writer", "role": "inker"},
                {"name": "Anon", "role": "colorist"}
            ]}).to_string()],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, evidence_source, confidence, created_at, updated_at, evidence_json) \
         VALUES ($1, $2, 'confirmed', 'test', 1.0, NOW(), NOW(), '{}'::json)",
        &[&mapped, &identity],
    )
    .await
    .unwrap();
    let path = format!("/api/v1/threads/{thread}/issues/creators");
    let router = creators_test_router(&state);
    let (status, body) = send_router(router.clone(), get(&path, &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["thread_id"], thread);
    assert_eq!(body["issues"].as_array().unwrap().len(), 1);
    assert_eq!(body["issues"][0]["issue_id"], mapped);
    assert_eq!(
        body["issues"][0]["creators"],
        json!([
            {"creator_id": 7, "name": "Writer", "roles": ["writer", "cover", "inker"]},
            {"creator_id": null, "name": "Anon", "roles": ["colorist"]}
        ])
    );
    let (status, body) = send_router(router.clone(), get(&path, &other_token, &other_csrf)).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"], format!("Thread {thread} not found"));
    let (status, _) = send_router(
        router.clone(),
        get("/api/v1/threads/987654/issues/creators", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, body) = send_router(
        router,
        get("/api/v1/threads/abc/issues/creators", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["detail"], "Validation failed");
}

#[tokio::test]
async fn v2_thread_issue_list_is_owner_scoped_and_paginated() {
    let (state, token, csrf, user_id, _guard) = setup_user("tiss-v2-list").await;
    let (other_token, other_csrf, _) = register_extra_user(&state, "tiss-v2-list-other").await;
    let conn = state.pool.get().await.unwrap();
    let thread = plain_thread(&conn, user_id, "V2 List", 3, 1).await;
    let ids = seed_issues(&conn, thread, &["1", "2", "3"], "unread").await;

    let (status, body) = send(
        &state,
        get(
            &format!("/api/v2/threads/{thread}/issues?page_size=2"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["total_count"], 3);
    assert_eq!(body["page_size"], 2);
    assert_eq!(body["issues"].as_array().unwrap().len(), 2);
    assert_eq!(body["issues"][0]["id"], ids[0]);
    assert_eq!(body["issues"][1]["id"], ids[1]);
    let cursor = body["next_page_token"].as_str().unwrap().to_owned();

    let (status, body) = send(
        &state,
        get(
            &format!("/api/v2/threads/{thread}/issues?page_size=2&page_token={cursor}"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["issues"].as_array().unwrap().len(), 1);
    assert_eq!(body["issues"][0]["id"], ids[2]);
    assert!(body["next_page_token"].is_null());

    let (status, body) = send(
        &state,
        get(
            &format!("/api/v2/threads/{thread}/issues?status=read"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["total_count"], 0);
    assert_eq!(body["issues"].as_array().unwrap().len(), 0);

    let (status, _) = send(
        &state,
        get(
            &format!("/api/v2/threads/{thread}/issues"),
            &other_token,
            &other_csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, body) = send(
        &state,
        get(
            &format!("/api/v2/threads/{thread}/issues?page_size=0"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["detail"], "Validation failed");
}

#[tokio::test]
async fn v2_creator_credits_are_bounded_paginated_and_owner_scoped() {
    let (state, token, csrf, user_id, _guard) = setup_user("tiss-v2-credits").await;
    let (other_token, other_csrf, _) = register_extra_user(&state, "tiss-v2-credits-other").await;
    let conn = state.pool.get().await.unwrap();
    let thread = plain_thread(&conn, user_id, "V2 Credits", 0, 1).await;
    let ids = seed_issues(&conn, thread, &["1", "2"], "unread").await;
    let _unmapped = issue(&conn, thread, "3", 3, "unread").await;
    let identity: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'issue', 'cv-v2-credits', $1::text::json, NOW(), NOW()) RETURNING id",
            &[&json!({"person_credits": [
                {"id": 7, "name": "Writer", "role": "writer"},
                {"name": "Anon", "role": "colorist"}
            ]}).to_string()],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO issue_external_identity_mappings \
         (issue_id, external_identity_id, status, evidence_source, confidence, created_at, updated_at, evidence_json) \
         SELECT unnest($1::int[]), $2, 'confirmed', 'test', 1.0, NOW(), NOW(), '{}'::json",
        &[&ids, &identity],
    )
    .await
    .unwrap();

    let (status, body) = send(
        &state,
        get(
            &format!("/api/v2/threads/{thread}/creatorCredits?page_size=1"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["thread_id"], thread);
    assert_eq!(body["total_count"], 2);
    assert_eq!(body["page_size"], 1);
    assert_eq!(body["issues"].as_array().unwrap().len(), 1);
    assert_eq!(body["issues"][0]["issue_id"], ids[0]);
    assert_eq!(
        body["issues"][0]["creators"],
        json!([
            {"creator_id": 7, "name": "Writer", "roles": ["writer"]},
            {"creator_id": null, "name": "Anon", "roles": ["colorist"]}
        ])
    );
    let cursor = body["next_page_token"].as_str().unwrap().to_owned();

    let (status, body) = send(
        &state,
        get(
            &format!("/api/v2/threads/{thread}/creatorCredits?page_size=1&page_token={cursor}"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["issues"].as_array().unwrap().len(), 1);
    assert_eq!(body["issues"][0]["issue_id"], ids[1]);
    assert!(body["next_page_token"].is_null());
    for entry in body["issues"].as_array().unwrap() {
        assert_ne!(entry["issue_id"], _unmapped);
    }

    let (status, _) = send(
        &state,
        get(
            &format!("/api/v2/threads/{thread}/creatorCredits"),
            &other_token,
            &other_csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, body) = send(
        &state,
        get(
            &format!("/api/v2/threads/{thread}/creatorCredits?page_size=101"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["detail"], "Validation failed");
    let (status, body) = send(
        &state,
        get(
            &format!("/api/v2/threads/{thread}/creatorCredits?page_token=bad"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["detail"], "Invalid page_token format");
}

#[tokio::test]
async fn unknown_thread_actions_stay_not_found() {
    let (state, token, csrf, _user_id, _guard) = setup_user("tiss-unknown").await;
    let (status, _) = send(
        &state,
        post("/api/v1/threads/1:nope", &token, &csrf, Some(json!({}))),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}
