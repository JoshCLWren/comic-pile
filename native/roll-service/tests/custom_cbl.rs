#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Native HTTP regressions for GET /api/v1/custom-cbls/issue-search.
//!
//! Exercises the mounted router against canonical disposable PostgreSQL rows:
//! FastAPI-compatible 422 validation envelopes (limit bounds, malformed limit,
//! overlong `q`), a valid bounded search, and foreign-owner exclusion.

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

static NEXT_CLIENT: AtomicUsize = AtomicUsize::new(1);

struct Fixture {
    state: Arc<AppState>,
    token: String,
    _guard: tokio::sync::MutexGuard<'static, ()>,
}

async fn setup() -> Fixture {
    let url = comicpile_roll_service::test_support::database_url().await;
    let state = Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
                "RUST_ROLL_JWT_SECRET" => {
                    Some(comicpile_roll_service::test_support::TEST_JWT_SECRET.into())
                }
                "RUST_ROLL_POOL_SIZE" => Some("2".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    );
    let guard = comicpile_roll_service::test_support::reset_for_test(&state).await;

    let suffix = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let username = format!("issue-search-{suffix}");
    let (status, body) = send(
        &state,
        Request::builder()
            .method("POST")
            .uri("/api/v1/auth/register")
            .header(
                "x-forwarded-for",
                format!(
                    "2001:db8::{:x}",
                    NEXT_CLIENT.fetch_add(1, Ordering::Relaxed)
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
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let token = body["access_token"].as_str().unwrap().to_owned();

    let conn = state.pool.get().await.unwrap();
    let row = conn
        .query_one("SELECT id FROM users WHERE username = $1", &[&username])
        .await
        .expect("registered user row");
    let user_id: i32 = row.get(0);

    const OTHER_USER_ID: i32 = 910001;
    let own_thread_id: i32 = 910101;
    let other_thread_id: i32 = 910102;
    let own_issue_id: i32 = 910201;
    let other_issue_id: i32 = 910202;
    conn.batch_execute(&format!(
        "INSERT INTO users (id, username) VALUES ({OTHER_USER_ID}, 'issue-search-other');
         INSERT INTO threads
           (id, user_id, title, format, issues_remaining, queue_position, status)
         VALUES ({own_thread_id}, {user_id}, 'Saga', 'Comic', 1, 1, 'active'),
                ({other_thread_id}, {OTHER_USER_ID}, 'Saga', 'Comic', 1, 1, 'active');
         INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
         VALUES ({own_issue_id}, {own_thread_id}, '7', 'unread', NOW(), 1),
                ({other_issue_id}, {other_thread_id}, '7', 'unread', NOW(), 1);"
    ))
    .await
    .expect("seed issue-search fixture");
    drop(conn);

    Fixture {
        state,
        token,
        _guard: guard,
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

async fn get(state: &Arc<AppState>, token: &str, uri: &str) -> (StatusCode, Value) {
    send(
        state,
        Request::builder()
            .method("GET")
            .uri(uri)
            .header(header::AUTHORIZATION, format!("Bearer {token}"))
            .body(Body::empty())
            .unwrap(),
    )
    .await
}

fn two_hundred_char_q() -> String {
    "a".repeat(200)
}

fn two_hundred_and_one_char_q() -> String {
    "a".repeat(201)
}

#[tokio::test]
async fn valid_bounded_search_returns_only_owned_issues() {
    let fixture = setup().await;

    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        "/api/v1/custom-cbls/issue-search?q=saga&limit=10",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let issue_ids: Vec<i64> = body
        .as_array()
        .expect("array body")
        .iter()
        .map(|item| item["issue_id"].as_i64().expect("issue_id"))
        .collect();
    assert_eq!(
        issue_ids.len(),
        1,
        "only the caller's issue may surface: {body}"
    );

    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        "/api/v1/custom-cbls/issue-search?limit=1",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");

    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        "/api/v1/custom-cbls/issue-search?limit=100",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");

    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        "/api/v1/custom-cbls/issue-search",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
}

#[tokio::test]
async fn limit_zero_and_negative_return_fastapi_422_envelope() {
    let fixture = setup().await;

    for raw in ["0", "-1"] {
        let (status, body) = get(
            &fixture.state,
            &fixture.token,
            &format!("/api/v1/custom-cbls/issue-search?limit={raw}"),
        )
        .await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
        assert_eq!(body["detail"][0]["type"], "greater_than_equal");
        assert_eq!(body["detail"][0]["loc"], json!(["query", "limit"]));
        assert_eq!(body["detail"][0]["ctx"], json!({"ge": 1}));
    }
}

#[tokio::test]
async fn limit_above_maximum_returns_fastapi_422_envelope() {
    let fixture = setup().await;

    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        "/api/v1/custom-cbls/issue-search?limit=101",
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"][0]["type"], "less_than_equal");
    assert_eq!(body["detail"][0]["loc"], json!(["query", "limit"]));
    assert_eq!(body["detail"][0]["ctx"], json!({"le": 100}));
}

#[tokio::test]
async fn malformed_limit_returns_fastapi_422_envelope() {
    let fixture = setup().await;

    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        "/api/v1/custom-cbls/issue-search?limit=abc",
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"][0]["type"], "int_parsing");
    assert_eq!(body["detail"][0]["loc"], json!(["query", "limit"]));

    // Unparsable-but-digit strings overflow i64; Python reports Query(le=100) failures.
    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        "/api/v1/custom-cbls/issue-search?limit=99999999999999999999999999999",
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"][0]["type"], "less_than_equal");
    assert_eq!(body["detail"][0]["loc"], json!(["query", "limit"]));
}

#[tokio::test]
async fn overlong_q_returns_fastapi_422_envelope() {
    let fixture = setup().await;

    let q = two_hundred_and_one_char_q();
    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        &format!("/api/v1/custom-cbls/issue-search?q={q}"),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"][0]["type"], "string_too_long");
    assert_eq!(body["detail"][0]["loc"], json!(["query", "q"]));
    assert_eq!(body["detail"][0]["ctx"], json!({"max_length": 200}));

    let q = two_hundred_char_q();
    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        &format!("/api/v1/custom-cbls/issue-search?q={q}"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
}

#[tokio::test]
async fn combined_failures_report_all_query_errors() {
    let fixture = setup().await;

    let q = two_hundred_and_one_char_q();
    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        &format!("/api/v1/custom-cbls/issue-search?q={q}&limit=0"),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    let types: Vec<&str> = body["detail"]
        .as_array()
        .expect("detail array")
        .iter()
        .map(|item| item["type"].as_str().expect("error type"))
        .collect();
    assert_eq!(types, vec!["string_too_long", "greater_than_equal"]);
}
