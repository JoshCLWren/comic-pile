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
    csrf: String,
    user_id: i32,
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
    let register_request = Request::builder()
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
        .unwrap();
    let response = router(state.clone())
        .oneshot(register_request)
        .await
        .unwrap();
    let status = response.status();
    let csrf = response
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .filter_map(|value| value.to_str().ok())
        .find_map(|value| value.strip_prefix("csrf_token="))
        .and_then(|value| value.split(';').next())
        .unwrap()
        .to_owned();
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
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
        csrf,
        user_id,
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

async fn post(
    state: &Arc<AppState>,
    token: &str,
    csrf: &str,
    uri: &str,
    body: Value,
) -> (StatusCode, Value) {
    send(
        state,
        Request::builder()
            .method("POST")
            .uri(uri)
            .header(header::AUTHORIZATION, format!("Bearer {token}"))
            .header("x-csrf-token", csrf)
            .header(header::COOKIE, format!("csrf_token={csrf}"))
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(body.to_string()))
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

#[tokio::test]
async fn structured_error_details_are_json_objects_not_strings() {
    let fixture = setup().await;

    // A foreign issue must emit Python's structured 422, not a stringified
    // JSON blob under `detail`.
    let (status, body) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        "/api/v1/custom-cbls",
        json!({"name": "Foreign", "issue_ids": [910202]}),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"]["code"], "custom_cbl_issue_not_owned");
    assert_eq!(body["detail"]["issue_ids"], json!([910202]));

    // An out-of-membership checkpoint target is the same structured shape.
    let (status, body) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        "/api/v1/custom-cbls",
        json!({
            "name": "Bad checkpoint",
            "issue_ids": [910201],
            "checkpoint_issue_ids": [910201],
            "checkpoint_targets": {"910201": [999999]}
        }),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(
        body["detail"]["code"],
        "custom_cbl_invalid_checkpoint_targets"
    );
}

#[tokio::test]
async fn strict_list_reports_partial_coverage_warnings() {
    let fixture = setup().await;
    let conn = fixture.state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
         VALUES (910203, 910101, '8', 'unread', NOW(), 2)",
        &[],
    )
    .await
    .expect("seed second unread issue in owned thread");
    drop(conn);

    let (status, body) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        "/api/v1/custom-cbls",
        json!({
            "name": "Strict partial",
            "mode": "strict",
            "issue_ids": [910201]
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body}");
    let warnings = body["warnings"].as_array().expect("warnings array");
    assert!(
        warnings.iter().any(|value| {
            value.as_str().is_some_and(|text| {
                text.contains("Strict list omits 1 unread Issues from Saga")
                    && text.contains("Saga #8")
            })
        }),
        "expected strict partial-coverage warning: {body}"
    );
}

#[tokio::test]
async fn apply_rebuilds_membership_and_compiled_rules() {
    let fixture = setup().await;
    let conn = fixture.state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
         VALUES (910203, 910101, '8', 'unread', NOW(), 2)",
        &[],
    )
    .await
    .expect("seed second issue in owned thread");
    conn.execute(
        "INSERT INTO continuity_plans
           (id, user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
         VALUES (920001, $1, 'Apply target', 'strict_sequential', '[]'::json, '[]'::json, NOW(), NOW())",
        &[&fixture.user_id],
    )
    .await
    .expect("seed owned continuity plan");
    drop(conn);

    let (status, list) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        "/api/v1/custom-cbls",
        json!({
            "name": "Apply source",
            "mode": "strict",
            "issue_ids": [910201, 910203],
            "checkpoint_issue_ids": [910201]
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{list}");
    let list_id = list["id"].as_i64().unwrap();

    let (status, body) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        &format!("/api/v1/custom-cbls/{list_id}/reading-plans/920001:apply"),
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["added_issue_ids"], json!([910201, 910203]));

    let conn = fixture.state.pool.get().await.unwrap();
    let members: i64 = conn
        .query_one(
            "SELECT count(*) FROM reading_plan_issues WHERE plan_id=920001",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        members, 2,
        "membership overlay must mirror merged plan nodes"
    );

    let rule = conn
        .query_one(
            "SELECT source_id, target_id, checkpoint_issue_id FROM continuity_rules
             WHERE user_id=$1 AND note='continuity-plan:920001' AND satisfaction_type='checkpoint'",
            &[&fixture.user_id],
        )
        .await
        .expect("compiled checkpoint rule");
    assert_eq!(rule.get::<_, i32>(0), 910201);
    assert_eq!(rule.get::<_, i32>(1), 910203);
    assert_eq!(rule.get::<_, Option<i32>>(2), Some(910201));

    let dependencies: i64 = conn
        .query_one(
            "SELECT count(*) FROM dependencies
             WHERE source_issue_id=910201 AND target_issue_id=910203
               AND note LIKE 'canonical:rule:%'",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        dependencies, 1,
        "compiled rule must create a canonical edge"
    );
    drop(conn);
}

#[tokio::test]
async fn apply_preserves_authoritative_plan_membership() {
    let fixture = setup().await;
    let conn = fixture.state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
        VALUES (910203, 910101, '8', 'unread', NOW(), 2),
               (910204, 910101, '9', 'unread', NOW(), 3);

        INSERT INTO continuity_plans
           (id, user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
        VALUES (920002, {}, 'Apply membership target', 'strict_sequential',
                '[]'::json, '[{{"id":"custom-cbl","name":"Custom CBL","order":0}}]'::json,
                NOW(), NOW());

        INSERT INTO reading_plan_issues
           (plan_id, occurrence_id, issue_id, lane_id, display_position, label, is_checkpoint)
        VALUES (920002, 'authoritative-910204', 910204, 'custom-cbl', 0, 'Authoritative', false);
        "#,
        fixture.user_id
    ))
    .await
    .expect("seed plan whose authoritative membership is absent from nodes_json");
    drop(conn);

    let (status, list) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        "/api/v1/custom-cbls",
        json!({
            "name": "Apply membership source",
            "mode": "strict",
            "issue_ids": [910201, 910203],
            "checkpoint_issue_ids": [910201]
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{list}");
    let list_id = list["id"].as_i64().unwrap();

    let (status, body) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        &format!("/api/v1/custom-cbls/{list_id}/reading-plans/920002:apply"),
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["added_issue_ids"], json!([910201, 910203]));
    assert!(
        body["nodes"]
            .as_array()
            .is_some_and(|nodes| nodes.iter().any(|node| node["ref_id"] == json!(910204))),
        "authoritative member must survive into the merged plan: {body}"
    );

    let conn = fixture.state.pool.get().await.unwrap();
    let members: Vec<i32> = conn
        .query(
            "SELECT issue_id FROM reading_plan_issues
             WHERE plan_id=920002 ORDER BY display_position",
            &[],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| row.get(0))
        .collect();
    assert_eq!(
        members,
        vec![910204, 910201, 910203],
        "membership overlay must be derived from authoritative rows, not stale nodes_json"
    );
    drop(conn);
}
