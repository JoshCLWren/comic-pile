#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Database-backed regressions for the native issue-list hot path (#4832).
//!
//! `GET /api/v1/threads/{thread_id}/issues` replaced Python
//! `issue_service.list_issues` at the same method/path. These tests pin the
//! Python wire contract through the real mounted Rust router on the canonical
//! Alembic schema: canonical position order, `{position},{id}` cursor
//! pagination, the unread/read filter, FastAPI-shaped validation errors,
//! owner-scoped 404 detail text, and FastAPI/Pydantic datetime rendering.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, test_support, AppState};
use serde_json::{json, Value};
use std::sync::{
    atomic::{AtomicU16, Ordering},
    Arc,
};
use tower::ServiceExt;

const PASSWORD: &str = "correct-horse-battery";

fn state(url: &str) -> Arc<AppState> {
    Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.into()),
                "RUST_ROLL_JWT_SECRET" => Some(test_support::TEST_JWT_SECRET.into()),
                "RUST_ROLL_POOL_SIZE" => Some("2".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    )
}

async fn database() -> (Arc<AppState>, tokio::sync::MutexGuard<'static, ()>) {
    let url = test_support::database_url().await;
    let state = state(&url);
    let guard = test_support::reset_for_test(&state).await;
    (state, guard)
}

static NEXT_IP: AtomicU16 = AtomicU16::new(1);

async fn register(state: &Arc<AppState>, username: &str) -> String {
    let ip = NEXT_IP.fetch_add(1, Ordering::Relaxed);
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/auth/register")
                .header(header::CONTENT_TYPE, "application/json")
                .header("x-forwarded-for", format!("198.51.100.{ip}"))
                .body(Body::from(
                    json!({
                        "username": username,
                        "email": format!("{username}@example.com"),
                        "password": PASSWORD
                    })
                    .to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let body = to_bytes(response.into_body(), 65536).await.unwrap();
    let value: Value = serde_json::from_slice(&body).unwrap();
    value["access_token"].as_str().unwrap().to_string()
}

async fn get(state: &Arc<AppState>, token: Option<&str>, path: &str) -> (StatusCode, Value) {
    let mut builder = Request::builder().method("GET").uri(path);
    if let Some(token) = token {
        builder = builder.header(header::AUTHORIZATION, format!("Bearer {token}"));
    }
    let response = router(state.clone())
        .oneshot(builder.body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 1 << 20).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

async fn seed_thread(state: &Arc<AppState>, user_id: i32, title: &str) -> i32 {
    state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "INSERT INTO threads
               (title, format, issues_remaining, queue_position, status, user_id, created_at)
             VALUES ($1,'comic',0,1,'active',$2,NOW())
             RETURNING id",
            &[&title, &user_id],
        )
        .await
        .unwrap()
        .get(0)
}

/// Insert one issue and return its id. `read` seeds the read state explicitly
/// so the unread/read filter has data on both sides.
async fn seed_issue(
    state: &Arc<AppState>,
    thread_id: i32,
    number: &str,
    position: i32,
    read: bool,
) -> i32 {
    let connection = state.pool.get().await.unwrap();
    if read {
        connection
            .query_one(
                "INSERT INTO issues (thread_id, issue_number, status, read_at, created_at, position)
                 VALUES ($1,$2,'read','2026-11-01 12:34:56.789012+00'::timestamptz,NOW(),$3)
                 RETURNING id",
                &[&thread_id, &number, &position],
            )
            .await
            .unwrap()
            .get(0)
    } else {
        connection
            .query_one(
                "INSERT INTO issues (thread_id, issue_number, status, created_at, position)
                 VALUES ($1,$2,'unread',NOW(),$3)
                 RETURNING id",
                &[&thread_id, &number, &position],
            )
            .await
            .unwrap()
            .get(0)
    }
}

async fn user_id(state: &Arc<AppState>, username: &str) -> i32 {
    state
        .pool
        .get()
        .await
        .unwrap()
        .query_one("SELECT id FROM users WHERE username=$1", &[&username])
        .await
        .unwrap()
        .get(0)
}

#[test]
fn lists_issues_in_canonical_position_order_with_python_shapes() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    runtime.block_on(async {
        let (state, _guard) = database().await;
        let token = register(&state, "issue-list-owner").await;
        let owner = user_id(&state, "issue-list-owner").await;
        let thread = seed_thread(&state, owner, "Issue list thread").await;
        for (number, position, read) in [("3", 3, false), ("1", 1, true), ("2", 2, false)] {
            seed_issue(&state, thread, number, position, read).await;
        }

        let (status, body) = get(
            &state,
            Some(&token),
            &format!("/api/v1/threads/{thread}/issues"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{body}");
        assert_eq!(body["total_count"], 3);
        assert_eq!(body["page_size"], 50);
        assert!(body["next_page_token"].is_null());
        let issues = body["issues"].as_array().unwrap();
        assert_eq!(issues.len(), 3);
        for (index, expected_number) in ["1", "2", "3"].iter().enumerate() {
            assert_eq!(issues[index]["issue_number"], *expected_number);
            assert_eq!(issues[index]["position"], index as i64 + 1);
            assert_eq!(issues[index]["thread_id"], thread);
        }
        assert_eq!(issues[0]["status"], "read");
        // FastAPI/Pydantic renders aware datetimes with microseconds when
        // present and a Z suffix.
        let read_at = issues[0]["read_at"].as_str().unwrap();
        assert_eq!(read_at, "2026-11-01T12:34:56.789012Z", "{read_at}");
        assert!(issues[1]["read_at"].is_null());
        let created_at = issues[0]["created_at"].as_str().unwrap();
        assert!(
            created_at.starts_with("2026-11-1")
                || created_at.starts_with("2026-11-2")
                || created_at.starts_with("2026-11-3"),
            "{created_at}"
        );
        assert!(created_at.ends_with('Z'), "{created_at}");
    });
}

#[test]
fn paginates_with_the_python_position_id_cursor() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    runtime.block_on(async {
        let (state, _guard) = database().await;
        let token = register(&state, "issue-list-pager").await;
        let owner = user_id(&state, "issue-list-pager").await;
        let thread = seed_thread(&state, owner, "Issue pagination thread").await;
        let mut ids = Vec::new();
        for position in 1..=3 {
            ids.push(seed_issue(&state, thread, &position.to_string(), position, false).await);
        }

        let (status, first) = get(
            &state,
            Some(&token),
            &format!("/api/v1/threads/{thread}/issues?page_size=2"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{first}");
        assert_eq!(first["total_count"], 3);
        assert_eq!(first["page_size"], 2);
        assert_eq!(first["issues"].as_array().unwrap().len(), 2);
        let token_value = first["next_page_token"].as_str().unwrap();
        assert_eq!(token_value, format!("2,{}", ids[1]));

        let (status, second) = get(
            &state,
            Some(&token),
            &format!("/api/v1/threads/{thread}/issues?page_size=2&page_token={token_value}"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{second}");
        assert_eq!(second["total_count"], 3);
        let issues = second["issues"].as_array().unwrap();
        assert_eq!(issues.len(), 1);
        assert_eq!(issues[0]["id"], ids[2]);
        assert!(second["next_page_token"].is_null());
    });
}

#[test]
fn status_filter_and_validation_match_python() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    runtime.block_on(async {
        let (state, _guard) = database().await;
        let token = register(&state, "issue-list-filter").await;
        let owner = user_id(&state, "issue-list-filter").await;
        let thread = seed_thread(&state, owner, "Issue filter thread").await;
        seed_issue(&state, thread, "1", 1, true).await;
        seed_issue(&state, thread, "2", 2, false).await;

        let (status, unread) = get(
            &state,
            Some(&token),
            &format!("/api/v1/threads/{thread}/issues?status=unread"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{unread}");
        assert_eq!(unread["total_count"], 1);
        assert_eq!(unread["issues"][0]["issue_number"], "2");

        let (status, read) = get(
            &state,
            Some(&token),
            &format!("/api/v1/threads/{thread}/issues?status=read"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{read}");
        assert_eq!(read["total_count"], 1);
        assert_eq!(read["issues"][0]["issue_number"], "1");

        for (path, expected_status, expected_detail) in [
            (
                format!("/api/v1/threads/{thread}/issues?status=skipped"),
                StatusCode::UNPROCESSABLE_ENTITY,
                "status must be 'unread' or 'read'",
            ),
            (
                format!("/api/v1/threads/{thread}/issues?page_size=0"),
                StatusCode::UNPROCESSABLE_ENTITY,
                "page_size must be between 1 and 100",
            ),
            (
                format!("/api/v1/threads/{thread}/issues?page_size=101"),
                StatusCode::UNPROCESSABLE_ENTITY,
                "page_size must be between 1 and 100",
            ),
            (
                format!("/api/v1/threads/{thread}/issues?page_token=1,2,3"),
                StatusCode::BAD_REQUEST,
                "Invalid page_token format",
            ),
        ] {
            let (status, body) = get(&state, Some(&token), &path).await;
            assert_eq!(status, expected_status, "{path} -> {body}");
            assert_eq!(body["detail"], expected_detail, "{path}");
        }

        // An empty token is page one (Python's falsy-string check), not an error.
        let (status, body) = get(
            &state,
            Some(&token),
            &format!("/api/v1/threads/{thread}/issues?page_token="),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{body}");
        assert_eq!(body["total_count"], 2);
    });
}

#[test]
fn thread_access_is_owner_scoped() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    runtime.block_on(async {
        let (state, _guard) = database().await;
        let token = register(&state, "issue-list-stranger").await;
        let other = register(&state, "issue-list-owner-2").await;
        let owner_id = user_id(&state, "issue-list-owner-2").await;
        let thread = seed_thread(&state, owner_id, "Foreign thread").await;
        seed_issue(&state, thread, "1", 1, false).await;

        let (status, body) = get(
            &state,
            Some(&token),
            &format!("/api/v1/threads/{thread}/issues"),
        )
        .await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{body}");
        assert_eq!(body["detail"], format!("Thread {thread} not found"));

        let (status, body) = get(&state, None, &format!("/api/v1/threads/{thread}/issues")).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED, "{body}");

        let (status, body) = get(
            &state,
            Some(&other),
            &format!("/api/v1/threads/{thread}/issues"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{body}");
        assert_eq!(body["total_count"], 1);
    });
}
