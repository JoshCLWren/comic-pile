#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Handler-level HTTP regressions for the v2 thread issue collection and
//! thread-scoped creator projection (#5706).
//!
//! Exercises ordering, read/rating/mapping/cover projection, pagination,
//! filtering and owner scoping through the mounted router against the
//! canonical disposable PostgreSQL schema. Requires
//! `RUST_ROLL_TEST_DATABASE_URL` and hard-fails without it.

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

type Conn = deadpool_postgres::Object;

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
    let state = Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
                "RUST_ROLL_JWT_SECRET" => Some("synthetic-v2-thread-issues-secret".into()),
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
    (state, token, csrf, user_id, guard)
}

async fn register_extra_user(state: &Arc<AppState>, prefix: &str) -> (String, String) {
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
                        "password": "correct-horse-battery"
                    })
                    .to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap();
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
    (body["access_token"].as_str().unwrap().to_owned(), csrf)
}

async fn send(state: &Arc<AppState>, path: &str, token: &str, csrf: &str) -> (StatusCode, Value) {
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("GET")
                .uri(path)
                .header(header::AUTHORIZATION, format!("Bearer {token}"))
                .header("x-csrf-token", csrf)
                .header(header::COOKIE, format!("csrf_token={csrf}"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

async fn plain_thread(conn: &Conn, user_id: i32, title: &str) -> i32 {
    conn.query_one(
        "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, is_blocked) \
         VALUES ($1, 'Comic', 3, 1, 'active', $2, true) RETURNING id",
        &[&title, &user_id],
    )
    .await
    .unwrap()
    .get(0)
}

async fn seed_issues(
    conn: &Conn,
    thread_id: i32,
    entries: &[(&str, &str, Option<&str>)],
) -> Vec<i32> {
    let numbers: Vec<&str> = entries.iter().map(|entry| entry.0).collect();
    let statuses: Vec<&str> = entries.iter().map(|entry| entry.1).collect();
    let aliases: Vec<Option<&str>> = entries.iter().map(|entry| entry.2).collect();
    let positions: Vec<i32> = (1..=entries.len() as i32).collect();
    conn.query(
        "INSERT INTO issues (thread_id, issue_number, status, issue_number_alias, created_at, position) \
         SELECT $1, new.number, new.status, new.alias, NOW(), new.position \
         FROM unnest($2::text[], $3::text[], $4::text[], $5::int[]) \
              AS new(number, status, alias, position) \
         ORDER BY new.position RETURNING id",
        &[&thread_id, &numbers, &statuses, &aliases, &positions],
    )
    .await
    .unwrap()
    .iter()
    .map(|row| row.get(0))
    .collect()
}

async fn confirmed_issue_identity(conn: &Conn, issue_id: i32, metadata: Value, confidence: f64) {
    let identity: i32 = conn
        .query_one(
            "INSERT INTO external_identities \
                 (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'issue', $1, $2::text::json, NOW(), NOW()) RETURNING id",
            &[&format!("cv-{issue_id}"), &metadata.to_string()],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO issue_external_identity_mappings \
             (issue_id, external_identity_id, status, evidence_source, confidence, \
              created_at, updated_at, evidence_json) \
         VALUES ($1, $2, 'confirmed', 'test', $3, NOW(), NOW(), '{}'::json)",
        &[&issue_id, &identity, &confidence],
    )
    .await
    .unwrap();
}

async fn candidate_issue_identity(conn: &Conn, issue_id: i32, metadata: Value) {
    let identity: i32 = conn
        .query_one(
            "INSERT INTO external_identities \
                 (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'issue', $1, $2::text::json, NOW(), NOW()) RETURNING id",
            &[&format!("candidate-{issue_id}"), &metadata.to_string()],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO issue_external_identity_mappings \
             (issue_id, external_identity_id, status, evidence_source, confidence, \
              created_at, updated_at, evidence_json) \
         VALUES ($1, $2, 'candidate', 'test', 0.4, NOW(), NOW(), '{}'::json)",
        &[&issue_id, &identity],
    )
    .await
    .unwrap();
}

#[tokio::test]
async fn v2_collection_reads_require_authentication() {
    let (state, _token, _csrf, user_id, _guard) = setup_user("tiss-v2-auth").await;
    let conn = state.pool.get().await.unwrap();
    let thread = plain_thread(&conn, user_id, "V2 Auth").await;
    for path in [
        format!("/api/v2/threads/{thread}/issues"),
        format!("/api/v2/threads/{thread}/creatorCredits"),
    ] {
        let response = router(state.clone())
            .oneshot(
                Request::builder()
                    .method("GET")
                    .uri(&path)
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED, "{path}");
    }
}

#[tokio::test]
async fn v2_issues_are_ordered_enriched_filtered_and_paginated() {
    let (state, token, csrf, user_id, _guard) = setup_user("tiss-v2-issues").await;
    let (other_token, other_csrf) = register_extra_user(&state, "tiss-v2-issues-other").await;
    let conn = state.pool.get().await.unwrap();
    // is_blocked=true: viewing issues must not be vetoed by reading eligibility.
    let thread = plain_thread(&conn, user_id, "V2 Issues").await;
    let ids = seed_issues(
        &conn,
        thread,
        &[
            ("3", "unread", Some("Annual 3")),
            ("1", "unread", None),
            ("2", "read", None),
        ],
    )
    .await;
    conn.execute(
        "INSERT INTO events (type, timestamp, user_id, issue_id, thread_id, rating, context) \
         VALUES ('rate', NOW(), $1, $2, $3, 4.5, '{}'::json)",
        &[&user_id, &ids[0], &thread],
    )
    .await
    .unwrap();
    confirmed_issue_identity(
        &conn,
        ids[0],
        json!({
            "issue_number": "3",
            "image_url": "https://cdn.example.com/3.jpg",
            "person_credits": [{"id": 7, "name": "Writer", "role": "writer"}]
        }),
        1.0,
    )
    .await;
    candidate_issue_identity(
        &conn,
        ids[2],
        json!({"image_url": "https://cdn.example.com/candidate.jpg"}),
    )
    .await;
    let path = format!("/api/v2/threads/{thread}/issues");

    let (status, body) = send(&state, &format!("{path}?page_size=2"), &token, &csrf).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["total_count"], 3);
    assert_eq!(body["page_size"], 2);
    let issues = body["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 2);
    assert_eq!(issues[0]["id"], ids[0]);
    assert_eq!(issues[0]["position"], 1);
    assert_eq!(issues[0]["issue_number"], "3");
    assert_eq!(issues[0]["issue_number_alias"], "Annual 3");
    assert_eq!(issues[0]["status"], "unread");
    assert_eq!(issues[0]["rating"], 4.5);
    assert_eq!(issues[0]["mapping_state"], "confirmed");
    assert!(issues[0]["has_confirmed_identity"].as_bool().unwrap());
    assert_eq!(issues[0]["comicvine_issue_id"], format!("cv-{}", ids[0]));
    assert_eq!(
        issues[0]["cover_image_url"],
        "https://cdn.example.com/3.jpg"
    );
    assert_eq!(issues[1]["id"], ids[1]);
    assert_eq!(issues[1]["mapping_state"], "unmapped");
    assert!(!issues[1]["has_confirmed_identity"].as_bool().unwrap());
    assert!(issues[1]["comicvine_issue_id"].is_null());
    assert!(issues[1]["cover_image_url"].is_null());
    let next = body["next_page_token"].as_str().unwrap().to_owned();

    let (status, body) = send(
        &state,
        &format!("{path}?page_size=2&page_token={next}"),
        &token,
        &csrf,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["issues"].as_array().unwrap().len(), 1);
    assert_eq!(body["issues"][0]["id"], ids[2]);
    assert!(body["next_page_token"].is_null());

    let (status, body) = send(&state, &format!("{path}?status=read"), &token, &csrf).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["total_count"], 1);
    assert_eq!(body["issues"][0]["id"], ids[2]);
    assert_eq!(body["issues"][0]["status"], "read");
    // A candidate mapping is visible as state but never exposes provider
    // identity or the stored cover URL.
    assert_eq!(body["issues"][0]["mapping_state"], "candidate");
    assert!(!body["issues"][0]["has_confirmed_identity"]
        .as_bool()
        .unwrap());
    assert!(body["issues"][0]["comicvine_issue_id"].is_null());
    assert!(body["issues"][0]["cover_image_url"].is_null());

    let (status, body) = send(
        &state,
        &format!("{path}?page_token=not-a-cursor"),
        &token,
        &csrf,
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["detail"], "Invalid page_token format");
    let (status, body) = send(&state, &format!("{path}?status=pending"), &token, &csrf).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["detail"], "Validation failed");

    let (status, body) = send(&state, &path, &other_token, &other_csrf).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"], format!("Thread {thread} not found"));
}

#[tokio::test]
async fn v2_creator_credits_are_bulk_paginated_and_owner_scoped() {
    let (state, token, csrf, user_id, _guard) = setup_user("tiss-v2-credits").await;
    let (other_token, other_csrf) = register_extra_user(&state, "tiss-v2-credits-other").await;
    let conn = state.pool.get().await.unwrap();
    let thread = plain_thread(&conn, user_id, "V2 Credits").await;
    let ids = seed_issues(
        &conn,
        thread,
        &[
            ("1", "unread", None),
            ("2", "read", None),
            ("3", "unread", None),
        ],
    )
    .await;
    confirmed_issue_identity(
        &conn,
        ids[0],
        json!({"person_credits": [
            {"id": 7, "name": "Writer", "role": "writer, cover"},
            {"id": 7, "name": "Writer", "role": "inker"},
            {"name": "Anon", "role": "colorist"}
        ]}),
        1.0,
    )
    .await;
    confirmed_issue_identity(
        &conn,
        ids[2],
        json!({"creator_credits": [{"id": 9, "name": "Penciller", "role": "artist"}]}),
        1.0,
    )
    .await;
    let path = format!("/api/v2/threads/{thread}/creatorCredits");

    let (status, body) = send(&state, &format!("{path}?page_size=1"), &token, &csrf).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["thread_id"], thread);
    assert_eq!(body["total_count"], 3);
    assert_eq!(body["page_size"], 1);
    assert_eq!(body["issues"].as_array().unwrap().len(), 1);
    assert_eq!(body["issues"][0]["issue_id"], ids[0]);
    assert_eq!(
        body["issues"][0]["creators"],
        json!([
            {"creator_id": 7, "name": "Writer", "roles": ["writer", "cover", "inker"]},
            {"creator_id": null, "name": "Anon", "roles": ["colorist"]}
        ])
    );
    let next = body["next_page_token"].as_str().unwrap().to_owned();

    let (status, body) = send(
        &state,
        &format!("{path}?page_size=1&page_token={next}"),
        &token,
        &csrf,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    // The middle issue has no stored credits, so it is omitted from the page.
    assert_eq!(body["issues"].as_array().unwrap().len(), 0);
    let next = body["next_page_token"].as_str().unwrap().to_owned();

    let (status, body) = send(
        &state,
        &format!("{path}?page_size=1&page_token={next}"),
        &token,
        &csrf,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["issues"][0]["issue_id"], ids[2]);
    assert!(body["next_page_token"].is_null());

    let (status, body) = send(&state, &format!("{path}?status=read"), &token, &csrf).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["total_count"], 1);
    assert!(body["issues"].as_array().unwrap().is_empty());

    let (status, body) = send(&state, &format!("{path}?page_size=0"), &token, &csrf).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["detail"], "Validation failed");

    let (status, body) = send(&state, &path, &other_token, &other_csrf).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"], format!("Thread {thread} not found"));
}
