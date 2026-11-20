#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Handler-level HTTP regressions for the same-path reading-order-group routes
//! (#4841). Exercises the real router against the canonical disposable
//! PostgreSQL schema so int4/int8 decoding and wire shapes are covered end to
//! end. Requires `RUST_ROLL_TEST_DATABASE_URL` and hard-fails without it.

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
    let state = Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
                "RUST_ROLL_JWT_SECRET" => Some("synthetic-reading-order-groups-secret".into()),
                "RUST_ROLL_POOL_SIZE" => Some("2".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    );
    let guard = comicpile_roll_service::test_support::reset_for_test(&state).await;
    let username = format!("{prefix}-{}-{}", std::process::id(), unique_suffix());
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
        .map(str::to_owned);
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    let csrf = csrf.unwrap_or_else(|| panic!("csrf cookie missing: status={status} body={body:?}"));
    let token = body["access_token"]
        .as_str()
        .unwrap_or_else(|| panic!("access token missing: status={status} body={body:?}"))
        .to_owned();
    let user_id: i32 = state
        .pool
        .get()
        .await
        .unwrap()
        .query_one("SELECT id FROM users WHERE username = $1", &[&username])
        .await
        .unwrap()
        .get(0);
    (state, token, csrf, user_id, guard)
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

async fn send(state: &Arc<AppState>, request: Request<Body>) -> (StatusCode, Value) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

#[tokio::test]
async fn reading_order_group_routes_round_trip_over_http() {
    let (state, token, csrf, user_id, _guard) = setup_user("rog-http").await;

    // Seed one owned series with three positioned issues.
    let connection = state.pool.get().await.unwrap();
    let thread_id: i32 = connection
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, status, queue_position) \
             VALUES ($1, 'Series', 'Comic', 3, 'active', 1) RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    for position in 1..=3 {
        connection
            .execute(
                "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
                 VALUES ($1, $2, $3, 'unread', now())",
                &[&thread_id, &position.to_string(), &position],
            )
            .await
            .unwrap();
    }
    drop(connection);

    // Empty list, then create.
    let (status, body) = send(
        &state,
        authed("GET", "/api/v1/reading-order-groups/", &token, &csrf, None),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body, json!([]));

    let (status, body) = send(
        &state,
        authed(
            "POST",
            "/api/v1/reading-order-groups/",
            &token,
            &csrf,
            Some(json!({"name": "Crossover"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    let group_id = body["id"].as_i64().unwrap() as i32;

    // Single-group read before any memberships exist.
    let path = format!("/api/v1/reading-order-groups/{group_id}");
    let (status, body) = send(&state, authed("GET", &path, &token, &csrf, None)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["name"], json!("Crossover"));

    // Thread-level membership, then issue range (set-based insert).
    let path = format!("/api/v1/reading-order-groups/{group_id}/members");
    let (status, body) = send(
        &state,
        authed(
            "POST",
            &path,
            &token,
            &csrf,
            Some(json!({"thread_id": thread_id})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    let member_id = body["id"].as_i64().unwrap() as i32;

    // The group now appears in the thread-scoped listing.
    let path = format!("/api/v1/reading-order-groups/threads/{thread_id}/groups");
    let (status, body) = send(&state, authed("GET", &path, &token, &csrf, None)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body.as_array().unwrap().len(), 1);

    let path = format!("/api/v1/reading-order-groups/{group_id}/issue-ranges");
    let (status, body) = send(
        &state,
        authed(
            "POST",
            &path,
            &token,
            &csrf,
            Some(json!({
                "thread_id": thread_id,
                "start_position": 1,
                "end_position": 2,
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["added_issue_ids"].as_array().unwrap().len(), 2);
    let issue_id = body["added_issue_ids"][0].as_i64().unwrap();

    // Detail enrichment, authoritative ordering and linked plans.
    let path = format!("/api/v1/reading-order-groups/{group_id}/detail");
    let (status, body) = send(&state, authed("GET", &path, &token, &csrf, None)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");

    let path = format!("/api/v1/reading-order-groups/{group_id}/order");
    let (status, body) = send(
        &state,
        authed(
            "PUT",
            &path,
            &token,
            &csrf,
            Some(json!({"items": [{"issue_id": issue_id, "sequence_order": 1}]})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");

    let path = format!("/api/v1/reading-order-groups/{group_id}/plans");
    let (status, body) = send(&state, authed("GET", &path, &token, &csrf, None)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body, json!([]));

    // Rename, then remove the thread-level member and delete the group.
    let (status, body) = send(
        &state,
        authed(
            "PATCH",
            &format!("/api/v1/reading-order-groups/{group_id}"),
            &token,
            &csrf,
            Some(json!({"name": "Renamed"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["name"], json!("Renamed"));

    let (status, _) = send(
        &state,
        authed(
            "DELETE",
            &format!("/api/v1/reading-order-groups/{group_id}/members/{member_id}"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);

    let (status, _) = send(
        &state,
        authed(
            "DELETE",
            &format!("/api/v1/reading-order-groups/{group_id}"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);

    let (status, _) = send(
        &state,
        authed(
            "GET",
            &format!("/api/v1/reading-order-groups/{group_id}"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn reading_order_group_validation_uses_python_422_body() {
    let (state, token, csrf, user_id, _guard) = setup_user("rog-val").await;

    let connection = state.pool.get().await.unwrap();
    let thread_id: i32 = connection
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, status, queue_position) \
             VALUES ($1, 'Series', 'Comic', 1, 'active', 1) RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    let issue_id: i32 = connection
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
             VALUES ($1, '1', 1, 'unread', now()) RETURNING id",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get(0);
    drop(connection);

    let (status, body) = send(
        &state,
        authed(
            "POST",
            "/api/v1/reading-order-groups/",
            &token,
            &csrf,
            Some(json!({"name": "Crossover"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    let group_id = body["id"].as_i64().unwrap() as i32;

    // Invalid path params must map to the production validation body.
    let (status, body) = send(
        &state,
        authed(
            "GET",
            "/api/v1/reading-order-groups/not-an-int",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
    assert_eq!(body, json!({"detail": "Validation failed"}));

    // Malformed JSON bodies must map to the production validation body.
    let request = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/reading-order-groups/{group_id}/members"))
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", &csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"))
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from("{"))
        .unwrap();
    let response = router(state.clone()).oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(body, json!({"detail": "Validation failed"}));

    // Issue-member sequence_order must be >= 1 (Python schema ge=1).
    for sequence_order in [0_i64, -1_i64] {
        let path = format!("/api/v1/reading-order-groups/{group_id}/members");
        let (status, body) = send(
            &state,
            authed(
                "POST",
                &path,
                &token,
                &csrf,
                Some(json!({"issue_id": issue_id, "sequence_order": sequence_order})),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
        assert_eq!(body, json!({"detail": "Validation failed"}));
    }

    // Order items require positive issue_id and sequence_order.
    for payload in [
        json!({"items": [{"issue_id": issue_id, "sequence_order": 0}]}),
        json!({"items": [{"issue_id": issue_id, "sequence_order": -1}]}),
        json!({"items": [{"issue_id": 0, "sequence_order": 1}]}),
        json!({"items": []}),
    ] {
        let path = format!("/api/v1/reading-order-groups/{group_id}/order");
        let (status, body) = send(&state, authed("PUT", &path, &token, &csrf, Some(payload))).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
        assert_eq!(body, json!({"detail": "Validation failed"}));
    }
}

const QUEUE_LOCK_NAMESPACE: i32 = 699001;

static NEXT_TEST_CLIENT: AtomicUsize = AtomicUsize::new(1);

async fn setup_user_pool8(
    prefix: &str,
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
                "RUST_ROLL_JWT_SECRET" => Some("synthetic-reading-order-groups-secret".into()),
                "RUST_ROLL_POOL_SIZE" => Some("8".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    );
    let guard = comicpile_roll_service::test_support::reset_for_test(&state).await;
    let username = format!("{prefix}-{}-{}", std::process::id(), unique_suffix());
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
        .map(str::to_owned);
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    let csrf = csrf.unwrap_or_else(|| panic!("csrf cookie missing: status={status} body={body:?}"));
    let token = body["access_token"]
        .as_str()
        .unwrap_or_else(|| panic!("access token missing: status={status} body={body:?}"))
        .to_owned();
    let user_id: i32 = state
        .pool
        .get()
        .await
        .unwrap()
        .query_one("SELECT id FROM users WHERE username = $1", &[&username])
        .await
        .unwrap()
        .get(0);
    (state, token, csrf, user_id, guard)
}

fn unique_suffix() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos()
}

async fn queue_lock_waiters(conn: &deadpool_postgres::Object, user_id: i32) -> i64 {
    conn.query_one(
        "SELECT count(*) FROM pg_locks \
         WHERE locktype = 'advisory' AND NOT granted \
           AND classid::int = $1 AND objid::int = $2",
        &[&QUEUE_LOCK_NAMESPACE, &user_id],
    )
    .await
    .unwrap()
    .get(0)
}

async fn wait_for_queue_lock_waiters(
    conn: &deadpool_postgres::Object,
    user_id: i32,
    expected: i64,
) {
    for _ in 0..1_000_000 {
        if queue_lock_waiters(conn, user_id).await >= expected {
            return;
        }
        tokio::task::yield_now().await;
    }
    panic!("expected {expected} queue-lock waiters");
}

#[tokio::test]
async fn group_writers_serialize_with_sibling_issue_and_queue_writes() {
    let (state, token, csrf, user_id, _guard) = setup_user_pool8("rog-race").await;
    let mut holder = state.pool.get().await.unwrap();
    let conn = state.pool.get().await.unwrap();

    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, status, queue_position, total_issues, reading_progress) \
             VALUES ($1, 'Series', 'Comic', 3, 'active', 1, 3, 'not_started') RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    let mut issue_ids = Vec::new();
    for position in 1..=3 {
        let issue_id: i32 = conn
            .query_one(
                "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
                 VALUES ($1, $2, $3, 'unread', now()) RETURNING id",
                &[&thread_id, &position.to_string(), &position],
            )
            .await
            .unwrap()
            .get(0);
        issue_ids.push(issue_id);
    }
    let group_id: i32 = conn
        .query_one(
            "INSERT INTO dependency_groups (user_id, name, created_at) VALUES ($1, 'Crossover', now()) RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);

    let hold = holder.transaction().await.unwrap();
    hold.execute(
        "SELECT pg_advisory_xact_lock($1, $2)",
        &[&QUEUE_LOCK_NAMESPACE, &user_id],
    )
    .await
    .unwrap();

    // Sibling issue write: mark an issue read (takes queue lock).
    let sibling_issue = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        let issue_id = issue_ids[0];
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    &format!("/api/v2/issues/{issue_id}/read-markers"),
                    &token,
                    &csrf,
                    None,
                ),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, user_id, 1).await;

    // Group writers that must serialize with sibling issue/queue writers.
    let add_member = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        let path = format!("/api/v1/reading-order-groups/{group_id}/members");
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    &path,
                    &token,
                    &csrf,
                    Some(json!({"thread_id": thread_id})),
                ),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, user_id, 2).await;

    // Sibling queue-affecting write: set current issue takes queue lock.
    let sibling_queue = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    &format!("/api/v1/threads/{thread_id}:setCurrentIssue"),
                    &token,
                    &csrf,
                    Some(json!({"issue_number": "2"})),
                ),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, user_id, 3).await;

    hold.commit().await.unwrap();

    let (s_issue, add, s_queue) = tokio::join!(sibling_issue, add_member, sibling_queue);
    let (s_issue_status, s_issue_body) = s_issue.expect("sibling issue task");
    let (add_status, add_body) = add.expect("add member task");
    let (s_queue_status, s_queue_body) = s_queue.expect("sibling queue task");
    assert!(
        matches!(s_issue_status, StatusCode::NO_CONTENT | StatusCode::OK),
        "sibling issue write deadlocked or errored: {s_issue_status} {s_issue_body:?}"
    );
    assert_eq!(
        add_status,
        StatusCode::CREATED,
        "add member deadlocked or errored: {add_status} {add_body:?}"
    );
    assert_eq!(
        s_queue_status,
        StatusCode::OK,
        "sibling queue write deadlocked or errored: {s_queue_status} {s_queue_body:?}"
    );
}

#[tokio::test]
async fn add_issue_range_serializes_with_sibling_issue_write() {
    let (state, token, csrf, user_id, _guard) = setup_user_pool8("rog-race-range").await;
    let mut holder = state.pool.get().await.unwrap();
    let conn = state.pool.get().await.unwrap();

    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, status, queue_position, total_issues, reading_progress) \
             VALUES ($1, 'Series', 'Comic', 3, 'active', 1, 3, 'not_started') RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    let mut issue_ids = Vec::new();
    for position in 1..=3 {
        let issue_id: i32 = conn
            .query_one(
                "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
                 VALUES ($1, $2, $3, 'unread', now()) RETURNING id",
                &[&thread_id, &position.to_string(), &position],
            )
            .await
            .unwrap()
            .get(0);
        issue_ids.push(issue_id);
    }
    let group_id: i32 = conn
        .query_one(
            "INSERT INTO dependency_groups (user_id, name, created_at) VALUES ($1, 'Crossover', now()) RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);

    let hold = holder.transaction().await.unwrap();
    hold.execute(
        "SELECT pg_advisory_xact_lock($1, $2)",
        &[&QUEUE_LOCK_NAMESPACE, &user_id],
    )
    .await
    .unwrap();

    let sibling_issue = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        let issue_id = issue_ids[0];
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    &format!("/api/v2/issues/{issue_id}/read-markers"),
                    &token,
                    &csrf,
                    None,
                ),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, user_id, 1).await;

    let add_range = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        let path = format!("/api/v1/reading-order-groups/{group_id}/issue-ranges");
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    &path,
                    &token,
                    &csrf,
                    Some(json!({"thread_id": thread_id, "start_position": 1, "end_position": 2})),
                ),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, user_id, 2).await;
    hold.commit().await.unwrap();

    let (s, a) = tokio::join!(sibling_issue, add_range);
    let (s_status, s_body) = s.expect("sibling issue");
    let (a_status, a_body) = a.expect("add range");
    assert!(
        matches!(s_status, StatusCode::NO_CONTENT | StatusCode::OK),
        "{s_status} {s_body:?}"
    );
    assert_eq!(a_status, StatusCode::OK, "{a_status} {a_body:?}");
}

#[tokio::test]
async fn remove_member_serializes_with_sibling_issue_write() {
    let (state, token, csrf, user_id, _guard) = setup_user_pool8("rog-race-remove").await;
    let mut holder = state.pool.get().await.unwrap();
    let conn = state.pool.get().await.unwrap();

    let thread_id: i32 = conn.query_one("INSERT INTO threads (user_id, title, format, issues_remaining, status, queue_position, total_issues, reading_progress) VALUES ($1, 'Series', 'Comic', 1, 'active', 1, 1, 'not_started') RETURNING id", &[&user_id]).await.unwrap().get(0);
    let issue_id: i32 = conn.query_one("INSERT INTO issues (thread_id, issue_number, position, status, created_at) VALUES ($1, '1', 1, 'unread', now()) RETURNING id", &[&thread_id]).await.unwrap().get(0);
    let group_id: i32 = conn.query_one("INSERT INTO dependency_groups (user_id, name, created_at) VALUES ($1, 'Crossover', now()) RETURNING id", &[&user_id]).await.unwrap().get(0);
    let member_id: i32 = conn.query_one("INSERT INTO dependency_group_memberships (group_id, thread_id) VALUES ($1, $2) RETURNING id", &[&group_id, &thread_id]).await.unwrap().get(0);

    let hold = holder.transaction().await.unwrap();
    hold.execute(
        "SELECT pg_advisory_xact_lock($1, $2)",
        &[&QUEUE_LOCK_NAMESPACE, &user_id],
    )
    .await
    .unwrap();

    let sibling_issue = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    &format!("/api/v2/issues/{issue_id}/read-markers"),
                    &token,
                    &csrf,
                    None,
                ),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, user_id, 1).await;

    let remove = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        let path = format!("/api/v1/reading-order-groups/{group_id}/members/{member_id}");
        tokio::spawn(
            async move { send(&state, authed("DELETE", &path, &token, &csrf, None)).await },
        )
    };
    wait_for_queue_lock_waiters(&conn, user_id, 2).await;
    hold.commit().await.unwrap();

    let (s, r) = tokio::join!(sibling_issue, remove);
    let (s_status, s_body) = s.expect("sibling issue");
    let (r_status, r_body) = r.expect("remove member");
    assert!(
        matches!(s_status, StatusCode::NO_CONTENT | StatusCode::OK),
        "{s_status} {s_body:?}"
    );
    assert_eq!(r_status, StatusCode::NO_CONTENT, "{r_status} {r_body:?}");
}

#[tokio::test]
async fn set_group_order_serializes_with_sibling_issue_write() {
    let (state, token, csrf, user_id, _guard) = setup_user_pool8("rog-race-order").await;
    let mut holder = state.pool.get().await.unwrap();
    let conn = state.pool.get().await.unwrap();

    let thread_id: i32 = conn.query_one("INSERT INTO threads (user_id, title, format, issues_remaining, status, queue_position, total_issues, reading_progress) VALUES ($1, 'Series', 'Comic', 2, 'active', 1, 2, 'not_started') RETURNING id", &[&user_id]).await.unwrap().get(0);
    let issue1: i32 = conn.query_one("INSERT INTO issues (thread_id, issue_number, position, status, created_at) VALUES ($1, '1', 1, 'unread', now()) RETURNING id", &[&thread_id]).await.unwrap().get(0);
    let issue2: i32 = conn.query_one("INSERT INTO issues (thread_id, issue_number, position, status, created_at) VALUES ($1, '2', 2, 'unread', now()) RETURNING id", &[&thread_id]).await.unwrap().get(0);
    let group_id: i32 = conn.query_one("INSERT INTO dependency_groups (user_id, name, created_at) VALUES ($1, 'Crossover', now()) RETURNING id", &[&user_id]).await.unwrap().get(0);
    conn.execute("INSERT INTO dependency_group_memberships (group_id, issue_id, sequence_order) VALUES ($1, $2, 1)", &[&group_id, &issue1]).await.unwrap();
    conn.execute("INSERT INTO dependency_group_memberships (group_id, issue_id, sequence_order) VALUES ($1, $2, 2)", &[&group_id, &issue2]).await.unwrap();

    let hold = holder.transaction().await.unwrap();
    hold.execute(
        "SELECT pg_advisory_xact_lock($1, $2)",
        &[&QUEUE_LOCK_NAMESPACE, &user_id],
    )
    .await
    .unwrap();

    let sibling_issue = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    &format!("/api/v2/issues/{issue1}/read-markers"),
                    &token,
                    &csrf,
                    None,
                ),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, user_id, 1).await;

    let reorder = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        let path = format!("/api/v1/reading-order-groups/{group_id}/order");
        tokio::spawn(async move {
            send(&state, authed("PUT", &path, &token, &csrf, Some(json!({"items": [{"issue_id": issue1, "sequence_order": 2}, {"issue_id": issue2, "sequence_order": 1}]})))).await
        })
    };
    wait_for_queue_lock_waiters(&conn, user_id, 2).await;
    hold.commit().await.unwrap();

    let (s, r) = tokio::join!(sibling_issue, reorder);
    let (s_status, s_body) = s.expect("sibling issue");
    let (r_status, r_body) = r.expect("set order");
    assert!(
        matches!(s_status, StatusCode::NO_CONTENT | StatusCode::OK),
        "{s_status} {s_body:?}"
    );
    assert_eq!(r_status, StatusCode::OK, "{r_status} {r_body:?}");
}

#[tokio::test]
async fn delete_group_serializes_with_sibling_issue_write() {
    let (state, token, csrf, user_id, _guard) = setup_user_pool8("rog-race-delete").await;
    let mut holder = state.pool.get().await.unwrap();
    let conn = state.pool.get().await.unwrap();

    let thread_id: i32 = conn.query_one("INSERT INTO threads (user_id, title, format, issues_remaining, status, queue_position, total_issues, reading_progress) VALUES ($1, 'Series', 'Comic', 1, 'active', 1, 1, 'not_started') RETURNING id", &[&user_id]).await.unwrap().get(0);
    let issue_id: i32 = conn.query_one("INSERT INTO issues (thread_id, issue_number, position, status, created_at) VALUES ($1, '1', 1, 'unread', now()) RETURNING id", &[&thread_id]).await.unwrap().get(0);
    let group_id: i32 = conn.query_one("INSERT INTO dependency_groups (user_id, name, created_at) VALUES ($1, 'Crossover', now()) RETURNING id", &[&user_id]).await.unwrap().get(0);
    conn.execute(
        "INSERT INTO dependency_group_memberships (group_id, thread_id) VALUES ($1, $2)",
        &[&group_id, &thread_id],
    )
    .await
    .unwrap();

    let hold = holder.transaction().await.unwrap();
    hold.execute(
        "SELECT pg_advisory_xact_lock($1, $2)",
        &[&QUEUE_LOCK_NAMESPACE, &user_id],
    )
    .await
    .unwrap();

    let sibling_issue = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    &format!("/api/v2/issues/{issue_id}/read-markers"),
                    &token,
                    &csrf,
                    None,
                ),
            )
            .await
        })
    };
    wait_for_queue_lock_waiters(&conn, user_id, 1).await;

    let delete = {
        let state = state.clone();
        let token = token.clone();
        let csrf = csrf.clone();
        let path = format!("/api/v1/reading-order-groups/{group_id}");
        tokio::spawn(
            async move { send(&state, authed("DELETE", &path, &token, &csrf, None)).await },
        )
    };
    wait_for_queue_lock_waiters(&conn, user_id, 2).await;
    hold.commit().await.unwrap();

    let (s, d) = tokio::join!(sibling_issue, delete);
    let (s_status, s_body) = s.expect("sibling issue");
    let (d_status, d_body) = d.expect("delete group");
    assert!(
        matches!(s_status, StatusCode::NO_CONTENT | StatusCode::OK),
        "{s_status} {s_body:?}"
    );
    assert_eq!(d_status, StatusCode::NO_CONTENT, "{d_status} {d_body:?}");
}
