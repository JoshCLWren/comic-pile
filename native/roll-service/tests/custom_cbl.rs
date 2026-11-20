#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Native HTTP regressions for GET /api/v2/reading-lists/issue-candidates.
//!
//! Exercises the mounted router against canonical disposable PostgreSQL rows:
//! FastAPI-compatible 422 validation envelopes (limit bounds, malformed limit,
//! overlong `q`), a valid bounded search, and foreign-owner exclusion.

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
    let state = Arc::new(test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => {
                Some(comicpile_roll_service::test_support::TEST_JWT_SECRET.into())
            }
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .unwrap(),
    ));
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
        "INSERT INTO users (id, username, is_admin, created_at)
         VALUES ({OTHER_USER_ID}, 'issue-search-other', false, NOW());
         INSERT INTO threads
           (id, user_id, title, format, issues_remaining, queue_position, status,
            manual_creator_credits, is_test, is_blocked, queue_position_is_manual, created_at)
         VALUES ({own_thread_id}, {user_id}, 'Saga', 'Comic', 1, 1, 'active',
                 '[]'::json, false, false, false, NOW()),
                ({other_thread_id}, {OTHER_USER_ID}, 'Saga', 'Comic', 1, 1, 'active',
                 '[]'::json, false, false, false, NOW());
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
        "/api/v2/reading-lists/issue-candidates?q=saga&limit=10",
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
        "/api/v2/reading-lists/issue-candidates?limit=1",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");

    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        "/api/v2/reading-lists/issue-candidates?limit=100",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");

    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        "/api/v2/reading-lists/issue-candidates",
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
            &format!("/api/v2/reading-lists/issue-candidates?limit={raw}"),
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
        "/api/v2/reading-lists/issue-candidates?limit=101",
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
        "/api/v2/reading-lists/issue-candidates?limit=abc",
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"][0]["type"], "int_parsing");
    assert_eq!(body["detail"][0]["loc"], json!(["query", "limit"]));

    // Unparsable-but-digit strings overflow i64; Python reports Query(le=100) failures.
    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        "/api/v2/reading-lists/issue-candidates?limit=99999999999999999999999999999",
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
        &format!("/api/v2/reading-lists/issue-candidates?q={q}"),
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
        &format!("/api/v2/reading-lists/issue-candidates?q={q}"),
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
        &format!("/api/v2/reading-lists/issue-candidates?q={q}&limit=0"),
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

async fn put(
    state: &Arc<AppState>,
    token: &str,
    csrf: &str,
    uri: &str,
    body: Value,
) -> (StatusCode, Value) {
    send(
        state,
        Request::builder()
            .method("PUT")
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

#[tokio::test]
async fn structured_error_details_are_json_objects_not_strings() {
    let fixture = setup().await;

    // A foreign/unowned issue is rejected on v2 create.
    let (status, body) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        "/api/v2/reading-lists",
        json!({"name": "Foreign", "issue_ids": [910202]}),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body}");
    assert_eq!(body["detail"], "Issue not found");

    // An out-of-membership checkpoint target is rejected on update with a
    // structured v2 error.
    let (status, body) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        "/api/v2/reading-lists",
        json!({
            "name": "Base",
            "issue_ids": [910201]
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body}");
    let list_id = body["id"].as_i64().expect("list id");
    let (status, body) = put(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        &format!("/api/v2/reading-lists/{list_id}"),
        json!({
            "name": "Bad checkpoint",
            "issue_ids": [910201],
            "checkpoint_issue_ids": [910201],
            "checkpoint_targets": {"910201": [999999]}
        }),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"], "custom_cbl_invalid_checkpoint_targets");
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
        "/api/v2/reading-lists",
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
        "/api/v2/reading-lists",
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
        &format!("/api/v2/reading-lists/{list_id}/reading-plans/920001/applications"),
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
        "/api/v2/reading-lists",
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
        &format!("/api/v2/reading-lists/{list_id}/reading-plans/920002/applications"),
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

#[tokio::test]
async fn apply_does_not_duplicate_cross_lane_source_issues() {
    let fixture = setup().await;
    let conn = fixture.state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
         VALUES (910203, 910101, '8', 'unread', NOW(), 2)",
        &[],
    )
    .await
    .expect("seed second issue in owned thread");
    drop(conn);

    let (status, list) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        "/api/v2/reading-lists",
        json!({
            "name": "Cross-lane source",
            "mode": "strict",
            "issue_ids": [910201, 910203]
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{list}");
    let list_id = list["id"].as_i64().unwrap();
    let source_path = format!("custom-cbl:{list_id}");

    // Plan 920003 already holds issue 910201 in another lane, carrying
    // provenance from this same CBL.
    let conn = fixture.state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO continuity_plans
           (id, user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
         VALUES (920003, {user_id}, 'Cross-lane target', 'strict_sequential',
                 '[{{"id":"occ-910201","node_type":"issue","ref_id":910201,"lane_id":"other","position":0,"label":"Saga #7","is_checkpoint":false,"checkpoint_target_ref_id":null,"checkpoint_target_ref_ids":[],"convergence_gate":[],"source_paths":["{source_path}","reading-list:55"],"source_cbl_placements":[{{"source_path":"{source_path}","position":0}}],"source_explanation":"Added from custom CBL ''Cross-lane source''."}}]'::json,
                 '[{{"id":"custom-cbl","name":"Custom CBL","order":0}},
                   {{"id":"other","name":"Other","order":1}}]'::json,
                 NOW(), NOW());
        INSERT INTO reading_plan_issues
           (plan_id, occurrence_id, issue_id, lane_id, display_position, label, is_checkpoint)
         VALUES (920003, 'occ-910201', 910201, 'other', 0, 'Saga #7', false);
        "#,
        user_id = fixture.user_id,
    ))
    .await
    .expect("seed plan with a cross-lane source issue");
    drop(conn);

    let (status, body) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        &format!("/api/v2/reading-lists/{list_id}/reading-plans/920003/applications"),
        json!({"lane_id": "custom-cbl"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["added_issue_ids"], json!([910203]));
    assert_eq!(body["skipped_existing_issue_ids"], json!([910201]));

    let nodes = body["nodes"].as_array().expect("nodes array");
    let cross_lane: Vec<&Value> = nodes
        .iter()
        .filter(|node| node["ref_id"] == json!(910201))
        .collect();
    assert_eq!(
        cross_lane.len(),
        1,
        "cross-lane source issue must not be duplicated into the target lane: {body}"
    );
    assert_eq!(cross_lane[0]["lane_id"], json!("other"));
    assert!(
        cross_lane[0]["source_paths"]
            .as_array()
            .is_some_and(|paths| paths
                .iter()
                .any(|p| p.as_str() == Some(source_path.as_str()))),
        "cross-lane node provenance must stay untouched: {body}"
    );
    assert_eq!(
        cross_lane[0]["source_explanation"],
        json!("Added from custom CBL 'Cross-lane source'.")
    );
    assert!(
        nodes
            .iter()
            .any(|node| node["ref_id"] == json!(910203) && node["lane_id"] == json!("custom-cbl")),
        "the new source issue lands in the target lane: {body}"
    );

    let conn = fixture.state.pool.get().await.unwrap();
    let rows = conn
        .query(
            "SELECT lane_id FROM reading_plan_issues WHERE plan_id=920003 AND issue_id=910201",
            &[],
        )
        .await
        .unwrap();
    assert_eq!(rows.len(), 1, "membership keeps exactly one row: {body}");
    assert_eq!(rows[0].get::<_, String>(0), "other");
    let target_members: i64 = conn
        .query_one(
            "SELECT count(*) FROM reading_plan_issues WHERE plan_id=920003 AND lane_id='custom-cbl'",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(target_members, 1);
    drop(conn);
}

#[tokio::test]
async fn apply_reuse_clears_stale_checkpoint_target_ref_id() {
    let fixture = setup().await;
    let conn = fixture.state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
         VALUES (910203, 910101, '8', 'unread', NOW(), 2),
                (910204, 910101, '9', 'unread', NOW(), 3)",
        &[],
    )
    .await
    .expect("seed issues in owned thread");
    drop(conn);

    let (status, list) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        "/api/v2/reading-lists",
        json!({
            "name": "Checkpoint reuse",
            "mode": "strict",
            "issue_ids": [910201, 910203],
            "checkpoint_issue_ids": [910201],
            "checkpoint_targets": {"910201": [910203]}
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{list}");
    let list_id = list["id"].as_i64().unwrap();
    let source_path = format!("custom-cbl:{list_id}");

    // Plan 920004 already holds 910201 in the target lane with a stale legacy
    // singular checkpoint target pointing at 910204.
    let conn = fixture.state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO continuity_plans
           (id, user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
         VALUES (920004, {user_id}, 'Checkpoint reuse target', 'strict_sequential',
                 '[{{"id":"occ-910201","node_type":"issue","ref_id":910201,"lane_id":"custom-cbl","position":0,"label":"Saga #7","is_checkpoint":false,"checkpoint_target_ref_id":910204,"checkpoint_target_ref_ids":[],"convergence_gate":[],"source_paths":["{source_path}"]}}]'::json,
                 '[{{"id":"custom-cbl","name":"Custom CBL","order":0}}]'::json,
                 NOW(), NOW());
        INSERT INTO reading_plan_issues
           (plan_id, occurrence_id, issue_id, lane_id, display_position, label, is_checkpoint)
         VALUES (920004, 'occ-910201', 910201, 'custom-cbl', 0, 'Saga #7', false);
        "#,
        user_id = fixture.user_id,
    ))
    .await
    .expect("seed plan with a stale checkpoint target");
    drop(conn);

    let (status, body) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        &format!("/api/v2/reading-lists/{list_id}/reading-plans/920004/applications"),
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["skipped_existing_issue_ids"], json!([910201]));
    assert_eq!(body["added_issue_ids"], json!([910203]));

    let nodes = body["nodes"].as_array().expect("nodes array");
    let reused = nodes
        .iter()
        .find(|node| node["ref_id"] == json!(910201))
        .expect("reused node present");
    assert_eq!(
        reused["checkpoint_target_ref_id"],
        Value::Null,
        "stale singular checkpoint target must be cleared on reuse: {body}"
    );
    assert_eq!(reused["checkpoint_target_ref_ids"], json!([910203]));
    assert_eq!(reused["is_checkpoint"], json!(true));
    assert_eq!(reused["lane_id"], json!("custom-cbl"));
    assert!(
        reused["source_paths"].as_array().is_some_and(|paths| paths
            .iter()
            .any(|p| p.as_str() == Some(source_path.as_str()))),
        "reused node keeps fresh CBL provenance: {body}"
    );

    let conn = fixture.state.pool.get().await.unwrap();
    let nodes_json: Value = conn
        .query_one(
            "SELECT nodes_json FROM continuity_plans WHERE id=920004",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    let persisted = nodes_json
        .as_array()
        .expect("persisted nodes array")
        .iter()
        .find(|node| node["ref_id"] == json!(910201))
        .expect("persisted reused node");
    assert_eq!(
        persisted["checkpoint_target_ref_id"],
        Value::Null,
        "persisted document must carry the cleared field"
    );

    let stale_edges: i64 = conn
        .query_one(
            "SELECT count(*) FROM dependencies
             WHERE source_issue_id=910201 AND target_issue_id=910204",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        stale_edges, 0,
        "stale singular checkpoint target must not compile into an edge"
    );
    let rule = conn
        .query_one(
            "SELECT target_id FROM continuity_rules
             WHERE user_id=$1 AND note='continuity-plan:920004' AND satisfaction_type='checkpoint'",
            &[&fixture.user_id],
        )
        .await
        .expect("compiled checkpoint rule");
    assert_eq!(rule.get::<_, i32>(0), 910203);
    drop(conn);
}

#[tokio::test]
async fn membership_checks_are_owner_scoped_and_honor_excluded_list() {
    let fixture = setup().await;
    let (status, body) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        "/api/v2/reading-lists",
        json!({"name": "Membership List", "issue_ids": [910201]}),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body}");
    let list_id = body["id"].as_i64().expect("list id");

    let (status, body) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        "/api/v2/reading-lists/memberships:check",
        json!({"thread_ids": [910102, 910101, 910101]}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["thread_ids"], json!([910101]));

    let (status, body) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        "/api/v2/reading-lists/memberships:check",
        json!({"thread_ids": [910101], "exclude_list_id": list_id}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["thread_ids"], json!([]));
}

#[tokio::test]
async fn overlap_decisions_accept_non_numeric_comicvine_volume_keys() {
    let fixture = setup().await;

    let (status, body) = post(
        &fixture.state,
        &fixture.token,
        &fixture.csrf,
        "/api/v2/reading-lists",
        json!({"name": "Overlap List", "mode": "loose", "issue_ids": []}),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body}");
    let list_id = body["id"].as_i64().expect("list id") as i32;

    let conn = fixture.state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        "INSERT INTO threads
           (id, user_id, title, format, issues_remaining, queue_position, status,
            manual_creator_credits, is_test, is_blocked, queue_position_is_manual, created_at)
         VALUES (930101, {}, 'Alpha Series', 'Comic', 0, 930101, 'active',
                 '[]'::json, false, false, false, NOW()),
                (930102, {}, 'Beta Series', 'Comic', 0, 930102, 'active',
                 '[]'::json, false, false, false, NOW());
         INSERT INTO external_identities
           (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
         VALUES (930201, 'comicvine', 'series', 'alpha-vol', '{{}}'::json, NOW(), NOW()),
                (930202, 'comicvine', 'series', 'beta.vol', '{{}}'::json, NOW(), NOW());
         INSERT INTO thread_external_series_mappings
           (id, thread_id, external_identity_id, status, created_at, updated_at)
         VALUES (930301, 930101, 930201, 'confirmed', NOW(), NOW()),
                (930302, 930102, 930202, 'confirmed', NOW(), NOW());",
        fixture.user_id, fixture.user_id
    ))
    .await
    .expect("seed non-numeric volume candidates");
    drop(conn);

    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        &format!("/api/v2/reading-lists/{list_id}/overlap-decisions"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let candidates = body["candidate_volumes"]
        .as_array()
        .expect("candidate_volumes array");
    let volume_ids: Vec<_> = candidates
        .iter()
        .filter_map(|candidate| candidate["volume_id"].as_str())
        .collect();
    assert!(
        volume_ids.contains(&"comicvine:alpha-vol"),
        "non-numeric candidate missing: {body}"
    );
    assert!(
        volume_ids.contains(&"comicvine:beta.vol"),
        "dotted non-numeric candidate missing: {body}"
    );

    let expected_updated_at = body["updated_at"].as_str().expect("updated_at").to_owned();
    let (status, body) = send(
        &fixture.state,
        Request::builder()
            .method("PUT")
            .uri(format!("/api/v2/reading-lists/{list_id}/overlap-decisions"))
            .header(header::AUTHORIZATION, format!("Bearer {}", fixture.token))
            .header("x-csrf-token", &fixture.csrf)
            .header(header::COOKIE, format!("csrf_token={}", fixture.csrf))
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "continuing_volume_id": "comicvine:alpha-vol",
                    "waiting_volume_id": "comicvine:beta.vol",
                    "expected_updated_at": expected_updated_at
                })
                .to_string(),
            ))
            .unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let decisions = body["decisions"].as_array().expect("decisions array");
    assert!(
        decisions.iter().any(|decision| {
            decision["continuing_volume_id"] == json!("comicvine:alpha-vol")
                && decision["waiting_volume_id"] == json!("comicvine:beta.vol")
        }),
        "saved non-numeric overlap decision missing: {body}"
    );

    let decision_id = decisions[0]["id"].as_i64().expect("decision id");
    let (status, body) = send(
        &fixture.state,
        Request::builder()
            .method("DELETE")
            .uri(format!(
                "/api/v2/reading-lists/{list_id}/overlap-decisions/{decision_id}"
            ))
            .header(header::AUTHORIZATION, format!("Bearer {}", fixture.token))
            .header("x-csrf-token", &fixture.csrf)
            .header(header::COOKIE, format!("csrf_token={}", fixture.csrf))
            .body(Body::empty())
            .unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["decisions"], json!([]));
    let remaining: i64 = fixture
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "SELECT count(*) FROM custom_cbl_overlap_decisions WHERE id = $1",
            &[&(decision_id as i32)],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(remaining, 0);
}

#[tokio::test]
async fn issue_search_returns_each_issue_once_and_keeps_same_titled_series_distinct() {
    let fixture = setup().await;
    let user_id = fixture.user_id;
    let conn = fixture.state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        "INSERT INTO threads
           (id, user_id, title, format, issues_remaining, queue_position, status,
            manual_creator_credits, is_test, is_blocked, queue_position_is_manual, created_at)
         VALUES (910301, {user_id}, 'Mutant X', 'Comic', 2, 2, 'active',
                 '[]'::json, false, false, false, NOW()),
                (910302, {user_id}, 'Mutant X', 'Comic', 1, 3, 'active',
                 '[]'::json, false, false, false, NOW());
         INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
         VALUES (910311, 910301, '1', 'unread', NOW(), 1),
                (910313, 910301, '2', 'unread', NOW(), 3),
                (910321, 910302, '1', 'unread', NOW(), 1);"
    ))
    .await
    .expect("seed duplicate fixture");
    drop(conn);

    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        "/api/v2/reading-lists/issue-candidates?q=Mutant%20X%20%231&limit=10",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let pairs: Vec<(i64, i64)> = body
        .as_array()
        .expect("array body")
        .iter()
        .map(|i| {
            (
                i["thread_id"].as_i64().unwrap(),
                i["issue_id"].as_i64().unwrap(),
            )
        })
        .collect();
    assert_eq!(
        pairs,
        vec![(910301, 910311), (910302, 910321)],
        "each canonical issue once; same-titled series stay distinct: {body}"
    );

    // A bounded result must still reach every same-titled series even when the
    // first series has more matching issues than the limit.
    let (status, body) = get(
        &fixture.state,
        &fixture.token,
        "/api/v2/reading-lists/issue-candidates?q=Mutant%20X&limit=2",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let mut threads: Vec<i64> = body
        .as_array()
        .expect("array body")
        .iter()
        .map(|i| i["thread_id"].as_i64().unwrap())
        .collect();
    threads.sort();
    assert_eq!(threads, vec![910301, 910302], "{body}");
}
