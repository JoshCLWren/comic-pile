#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Focused native HTTP regressions for the browser-called continuity-plans v1
//! cutover (issue #4838). Exercises the mounted Rust router so contract shape
//! and transactional CRUD are verified at the same-path ingress.
//!
//! Every test is database-backed and fails loudly when the canonical test DSN
//! is missing; there is no implicit skip path (CI provides the DSN).

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{db, router, test_support, AppState};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicU16, Ordering};
use std::sync::Arc;
use tower::ServiceExt;

static NEXT_IP: AtomicU16 = AtomicU16::new(10);

/// Canonical disposable database state. Panics with the standard message when
/// `RUST_ROLL_TEST_DATABASE_URL` is absent, never returns a passing no-op test.
async fn database() -> (Arc<AppState>, tokio::sync::MutexGuard<'static, ()>) {
    let state = test_support::test_state(4)
        .await
        .expect("RUST_ROLL_TEST_DATABASE_URL is required");
    let guard = test_support::reset_for_test(&state).await;
    (state, guard)
}

async fn send(state: &Arc<AppState>, request: Request<Body>) -> (StatusCode, Value, Vec<String>) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    let cookies = response
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .filter_map(|value| value.to_str().ok().map(str::to_owned))
        .collect::<Vec<_>>();
    let body = to_bytes(response.into_body(), 65536).await.unwrap();
    let body = serde_json::from_slice(&body).unwrap_or(Value::Null);
    (status, body, cookies)
}

fn cookie_value(cookies: &[String], name: &str) -> Option<String> {
    cookies.iter().find_map(|cookie| {
        cookie
            .strip_prefix(&format!("{name}="))
            .and_then(|rest| rest.split(';').next())
            .map(str::to_owned)
    })
}

async fn register_and_login(state: &Arc<AppState>, username: &str) -> (String, String) {
    let ip = NEXT_IP.fetch_add(1, Ordering::Relaxed);
    let (status, registered, cookies) = send(
        state,
        Request::builder()
            .method("POST")
            .uri("/api/v1/auth/register")
            .header(header::CONTENT_TYPE, "application/json")
            .header("x-forwarded-for", format!("198.51.100.{ip}"))
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
    assert_eq!(status, StatusCode::OK, "{registered}");
    let csrf = cookie_value(&cookies, "csrf_token").expect("csrf cookie");
    let token = registered["access_token"]
        .as_str()
        .expect("access token")
        .to_string();
    (token, csrf)
}

async fn authed_json(
    state: &Arc<AppState>,
    method: &str,
    uri: &str,
    token: &str,
    csrf: &str,
    body: Option<Value>,
) -> (StatusCode, Value) {
    let mut builder = Request::builder()
        .method(method)
        .uri(uri)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"));
    if body.is_some() {
        builder = builder.header(header::CONTENT_TYPE, "application/json");
    }
    let request = builder
        .body(body.map_or_else(Body::empty, |value| Body::from(value.to_string())))
        .unwrap();
    let (status, value, _) = send(state, request).await;
    (status, value)
}

async fn user_id_for(state: &Arc<AppState>, username: &str) -> i32 {
    let conn = db::checkout(state).await.expect("user lookup connection");
    let row = conn
        .query_one("SELECT id FROM users WHERE username = $1", &[&username])
        .await
        .expect("registered user row");
    row.get(0)
}

async fn seed_thread_issue(
    state: &Arc<AppState>,
    user_id: i32,
    thread_id: i32,
    issue_id: i32,
    title: &str,
    number: &str,
) {
    let conn = db::checkout(state).await.expect("seed connection");
    conn.batch_execute(&format!(
        "INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status)
         VALUES ({thread_id}, {user_id}, '{title}', 'Comic', 2, 1, 'active');
         INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
         VALUES ({issue_id}, {thread_id}, '{number}', 'unread', NOW(), 1);"
    ))
    .await
    .expect("seed thread and issue");
}

async fn create_plan(
    state: &Arc<AppState>,
    token: &str,
    csrf: &str,
    body: Value,
) -> (StatusCode, Value) {
    authed_json(
        state,
        "POST",
        "/api/v2/continuity-plans/",
        token,
        csrf,
        Some(body),
    )
    .await
}

fn simple_plan(nodes: Value) -> Value {
    json!({
        "name": "HTTP Plan",
        "ordering_mode": "informational",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": nodes
    })
}

#[tokio::test]
async fn continuity_plan_crud_and_membership_shape_are_native_wire_compatible() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cp-wire").await;

    let (status, created) = create_plan(&state, &token, &csrf, simple_plan(json!([]))).await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id");
    assert_eq!(created["name"], "HTTP Plan");
    assert_eq!(created["ordering_mode"], "informational");

    let (status, listed) = authed_json(
        &state,
        "GET",
        "/api/v2/continuity-plans/",
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{listed}");
    assert!(listed
        .as_array()
        .unwrap()
        .iter()
        .any(|item| item["id"] == plan_id));

    let (status, fetched) = authed_json(
        &state,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{fetched}");
    assert_eq!(fetched["id"], plan_id);

    let (status, membership) = authed_json(
        &state,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}/membership"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{membership}");
    assert_eq!(membership["plan_id"], plan_id);
    assert!(membership["issues"].is_array(), "{membership}");
    assert!(membership["dependencies"].is_array(), "{membership}");
    assert!(membership["sources"].is_array(), "{membership}");
    assert!(membership["placements"].is_array(), "{membership}");
    assert_eq!(membership["progress"]["total_issues"], 0, "{membership}");

    let mut update = simple_plan(json!([]));
    update["name"] = json!("HTTP Plan Updated");
    update["expected_updated_at"] = created["updated_at"].clone();
    let (status, updated) = authed_json(
        &state,
        "PUT",
        &format!("/api/v2/continuity-plans/{plan_id}"),
        &token,
        &csrf,
        Some(update),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{updated}");
    assert_eq!(updated["name"], "HTTP Plan Updated");

    let (status, _) = authed_json(
        &state,
        "DELETE",
        &format!("/api/v2/continuity-plans/{plan_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    let (status, _) = authed_json(
        &state,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

/// F2: link dependency must not `RETURNING id` from the composite-PK table,
/// must be idempotent 201 with the canonical dependency id, 422 for unowned
/// endpoints, 404 for a missing edge, and unlink must be 204/404.
#[tokio::test]
async fn link_dependency_is_idempotent_and_uses_composite_pk_contract() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cp-link").await;
    let user_id = user_id_for(&state, "cp-link").await;
    seed_thread_issue(&state, user_id, 710001, 710011, "Link One", "1").await;
    seed_thread_issue(&state, user_id, 710002, 710012, "Link Two", "2").await;
    // A foreign dependency whose endpoints this user does not own.
    register_and_login(&state, "cp-link-foreign").await;
    let foreign_user_id = user_id_for(&state, "cp-link-foreign").await;
    seed_thread_issue(&state, foreign_user_id, 710003, 710013, "Foreign", "1").await;
    seed_thread_issue(&state, foreign_user_id, 710004, 710014, "Foreign", "2").await;

    let conn = db::checkout(&state)
        .await
        .expect("dependency seed connection");
    conn.batch_execute(
        "INSERT INTO dependencies (id, created_at, source_issue_id, target_issue_id)
         VALUES (710021, NOW(), 710011, 710012),
                (710022, NOW(), 710013, 710014);",
    )
    .await
    .expect("seed dependencies");

    let (status, created) = create_plan(&state, &token, &csrf, simple_plan(json!([]))).await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id");

    let link_uri = format!("/api/v2/continuity-plans/{plan_id}/dependencies/710021");
    let (status, linked) = authed_json(
        &state,
        "POST",
        &link_uri,
        &token,
        &csrf,
        Some(json!({"explanation": "first"})),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{linked}");
    assert_eq!(linked["dependency_id"], 710021, "{linked}");
    assert_eq!(linked["source_issue_id"], 710011, "{linked}");
    assert_eq!(linked["target_issue_id"], 710012, "{linked}");
    assert_eq!(linked["explanation"], "first", "{linked}");

    // Idempotent re-link: 201, canonical id, original explanation unchanged.
    let (status, relinked) = authed_json(
        &state,
        "POST",
        &link_uri,
        &token,
        &csrf,
        Some(json!({"explanation": "second"})),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{relinked}");
    assert_eq!(relinked["dependency_id"], 710021, "{relinked}");
    assert_eq!(relinked["explanation"], "first", "{relinked}");

    let conn = db::checkout(&state).await.expect("verify link connection");
    let rows: i64 = conn
        .query_one(
            "SELECT COUNT(*) FROM reading_plan_dependencies WHERE plan_id = $1 AND dependency_id = 710021",
            &[&(plan_id as i32)],
        )
        .await
        .expect("link count")
        .get(0);
    assert_eq!(rows, 1, "linking must be idempotent");
    drop(conn);

    let (status, missing) = authed_json(
        &state,
        "POST",
        &format!("/api/v2/continuity-plans/{plan_id}/dependencies/999999"),
        &token,
        &csrf,
        Some(json!({})),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{missing}");
    assert!(format!("{missing}").contains("Dependency 999999 not found"));

    let (status, unowned) = authed_json(
        &state,
        "POST",
        &format!("/api/v2/continuity-plans/{plan_id}/dependencies/710022"),
        &token,
        &csrf,
        Some(json!({})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{unowned}");
    assert!(
        format!("{unowned}").contains("dangling_plan_reference"),
        "{unowned}"
    );

    let (status, _) = authed_json(&state, "DELETE", &link_uri, &token, &csrf, None).await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    let (status, gone) = authed_json(&state, "DELETE", &link_uri, &token, &csrf, None).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{gone}");
}

/// F4: plan detail must apply the normalized-membership overlay and fill blank
/// issue labels from the owned issue/thread pair, like Python's
/// `editor_plan_response`.
#[tokio::test]
async fn plan_detail_overlays_membership_and_fills_labels() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cp-labels").await;
    let user_id = user_id_for(&state, "cp-labels").await;
    seed_thread_issue(&state, user_id, 720001, 720011, "Series Alpha", "5").await;
    seed_thread_issue(&state, user_id, 720002, 720012, "Series Beta", "12").await;

    let node = json!({
        "id": "issue-1", "node_type": "issue", "ref_id": 720011,
        "lane_id": "main", "position": 0
    });
    let (status, created) = create_plan(&state, &token, &csrf, simple_plan(json!([node]))).await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id") as i32;
    assert_eq!(created["nodes"][0]["label"], "Series Alpha #5", "{created}");

    // Insert a second membership occurrence that is absent from nodes_json.
    // The authoritative overlay must surface it on GET.
    let conn = db::checkout(&state).await.expect("overlay seed connection");
    conn.execute(
        "INSERT INTO reading_plan_issues
         (plan_id, occurrence_id, issue_id, lane_id, display_position, is_checkpoint)
         VALUES ($1, 'issue-2', 720012, 'main', 1, false)",
        &[&plan_id],
    )
    .await
    .expect("seed extra membership");
    drop(conn);

    let (status, fetched) = authed_json(
        &state,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{fetched}");
    let nodes = fetched["nodes"].as_array().expect("nodes array");
    assert_eq!(
        nodes.len(),
        2,
        "membership must override stored JSON: {fetched}"
    );
    let labels: Vec<&str> = nodes
        .iter()
        .map(|node| node["label"].as_str().unwrap_or_default())
        .collect();
    assert!(labels.contains(&"Series Alpha #5"), "{fetched}");
    assert!(labels.contains(&"Series Beta #12"), "{fetched}");
}

/// F5: list must expose CBL placement source paths and owner-scoped source
/// names, matching Python `plan_source_paths` + `load_reading_plan_source_names`.
#[tokio::test]
async fn plan_list_includes_cbl_placement_paths_and_source_names() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cp-sources").await;
    let user_id = user_id_for(&state, "cp-sources").await;
    seed_thread_issue(&state, user_id, 730001, 730011, "Source Series", "1").await;

    let conn = db::checkout(&state).await.expect("list seed connection");
    conn.execute(
        "INSERT INTO custom_cbl_lists
         (id, user_id, name, created_at, updated_at, mode)
         VALUES (730101, $1, 'My Reading List', NOW(), NOW(), 'loose')",
        &[&user_id],
    )
    .await
    .expect("seed custom cbl list");
    drop(conn);

    let node = json!({
        "id": "issue-1", "node_type": "issue", "ref_id": 730011,
        "lane_id": "main", "position": 0,
        "source_cbl_placements": [{"source_path": "custom-cbl:730101", "position": 1}],
        "source_paths": ["manual/path", "custom-cbl:730101"]
    });
    let (status, created) = create_plan(&state, &token, &csrf, simple_plan(json!([node]))).await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id");

    let (status, listed) = authed_json(
        &state,
        "GET",
        "/api/v2/continuity-plans/",
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{listed}");
    let item = listed
        .as_array()
        .unwrap()
        .iter()
        .find(|item| item["id"] == plan_id)
        .expect("created plan in list");
    let paths = item["source_paths"].as_array().expect("source_paths");
    let values: Vec<&str> = paths
        .iter()
        .map(|p| p.as_str().unwrap_or_default())
        .collect();
    assert_eq!(values, vec!["custom-cbl:730101", "manual/path"], "{item}");
    assert_eq!(
        item["source_names"]["custom-cbl:730101"], "My Reading List",
        "{item}"
    );
}

/// F6: ISO `updated_at` on the wire and timezone-aware optimistic concurrency.
#[tokio::test]
async fn plan_updated_at_is_iso_and_version_check_is_timezone_aware() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cp-version").await;

    let (status, created) = create_plan(&state, &token, &csrf, simple_plan(json!([]))).await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id");
    let updated_at = created["updated_at"].as_str().expect("ISO updated_at");
    assert!(updated_at.contains('T'), "non-ISO updated_at: {updated_at}");
    assert!(
        updated_at.ends_with('Z') || updated_at.contains("+00:00"),
        "updated_at must carry a timezone: {updated_at}"
    );

    let uri = format!("/api/v2/continuity-plans/{plan_id}");

    // The exact ISO token returned by GET must be accepted (GET-then-PUT).
    let mut matching = simple_plan(json!([]));
    matching["expected_updated_at"] = json!(updated_at);
    let (status, body) = authed_json(&state, "PUT", &uri, &token, &csrf, Some(matching)).await;
    assert_eq!(status, StatusCode::OK, "{body}");

    // The same instant in a different ISO representation (+00:00) must match.
    let offset_token = updated_at.replace('Z', "+00:00");
    let (status, fetched) = authed_json(&state, "GET", &uri, &token, &csrf, None).await;
    assert_eq!(status, StatusCode::OK, "{fetched}");
    let newest = fetched["updated_at"].as_str().expect("ISO updated_at");
    let mut offset = simple_plan(json!([]));
    offset["expected_updated_at"] = json!(newest.replace('Z', "+00:00"));
    let (status, body) = authed_json(&state, "PUT", &uri, &token, &csrf, Some(offset)).await;
    assert_eq!(
        status,
        StatusCode::OK,
        "offset token {offset_token} should match: {body}"
    );

    // A genuinely stale ISO token must 409 with an ISO expected_updated_at.
    let mut stale = simple_plan(json!([]));
    stale["expected_updated_at"] = json!("2000-01-01T00:00:00Z");
    let (status, conflict) = authed_json(&state, "PUT", &uri, &token, &csrf, Some(stale)).await;
    assert_eq!(status, StatusCode::CONFLICT, "{conflict}");
    assert_eq!(
        conflict["detail"]["code"], "plan_version_conflict",
        "{conflict}"
    );
    let detail_token = conflict["detail"]["expected_updated_at"]
        .as_str()
        .expect("ISO conflict token");
    assert!(
        detail_token.contains('T'),
        "non-ISO conflict token: {conflict}"
    );
}

/// Issue #5462: an empty authored plan (0 lanes, 0 nodes) saves but must open
/// and be editable. A plan that never recorded an owned Reading List stays
/// editable after its first issue is saved too (Greptile finding on #5467).
#[tokio::test]
async fn empty_plan_reader_opens_as_editable_without_recovery_409() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cp-empty-reader").await;

    let (status, created) = create_plan(
        &state,
        &token,
        &csrf,
        json!({
            "name": "QA empty plan",
            "ordering_mode": "informational",
            "lanes": [],
            "nodes": []
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id");

    let (status, reader) = authed_json(
        &state,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}/reader"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{reader}");
    assert_eq!(reader["plan_id"], plan_id, "{reader}");
    assert_eq!(reader["name"], "QA empty plan", "{reader}");
    assert_eq!(reader["execution_mode"], "legacy", "{reader}");
    assert_eq!(reader["ordering_mode"], "informational", "{reader}");
    assert_eq!(reader["progress"]["total_issues"], 0, "{reader}");
    assert_eq!(reader["progress"]["read_issues"], 0, "{reader}");
    assert_eq!(reader["available_now"], json!([]), "{reader}");
    assert_eq!(reader["blocked_next"], json!([]), "{reader}");
    assert_eq!(reader["lanes"], json!([]), "{reader}");
    assert_eq!(reader["sources"], json!([]), "{reader}");

    // Save an issue through the same authoring path the legacy editor uses.
    // It creates retained membership but no Reading List link; reopening must
    // still yield the editable legacy plan, never a 409 recovery conflict.
    let user_id = user_id_for(&state, "cp-empty-reader").await;
    seed_thread_issue(&state, user_id, 546201, 546211, "QA Series", "1").await;
    let (status, saved) = authed_json(
        &state,
        "PUT",
        &format!("/api/v2/continuity-plans/{plan_id}"),
        &token,
        &csrf,
        Some(json!({
            "name": "QA empty plan",
            "ordering_mode": "informational",
            "lanes": [{"id": "main", "name": "Main", "order": 0}],
            "nodes": [{
                "id": "issue-546211",
                "node_type": "issue",
                "ref_id": 546211,
                "lane_id": "main",
                "position": 0,
                "label": "QA Series #1"
            }],
            "expected_updated_at": created["updated_at"]
        })),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{saved}");

    let (status, reopened) = authed_json(
        &state,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}/reader"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{reopened}");
    assert_eq!(reopened["execution_mode"], "legacy", "{reopened}");
    assert_eq!(reopened["progress"]["total_issues"], 1, "{reopened}");
    assert_eq!(
        reopened["lanes"].as_array().map(Vec::len),
        Some(1),
        "{reopened}"
    );
    assert_eq!(reopened["lanes"][0]["id"], "main", "{reopened}");
    assert_eq!(
        reopened["lanes"][0]["issues"][0]["issue_id"], 546211,
        "{reopened}"
    );
    assert_eq!(
        reopened["lanes"][0]["issues"][0]["issue_number"], "1",
        "{reopened}"
    );
}

/// #5614: creating a Strict plan with 0 lanes and 0 steps must save as an
/// empty plan and open editable. The zero-lane creation previously failed
/// with a bare 422 ("strict sequential plans must use exactly one lane").
#[tokio::test]
async fn strict_empty_plan_creates_opens_and_adds_issue() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cp-strict-empty").await;

    let (status, created) = create_plan(
        &state,
        &token,
        &csrf,
        json!({
            "name": "QA strict empty plan",
            "ordering_mode": "strict_sequential",
            "lanes": [],
            "nodes": []
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id");
    assert_eq!(created["ordering_mode"], "strict_sequential", "{created}");

    // The saved plan opens as an empty plan, not a 409 recovery screen.
    let (status, reader) = authed_json(
        &state,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}/reader"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{reader}");
    assert_eq!(reader["ordering_mode"], "strict_sequential", "{reader}");
    assert_eq!(reader["progress"]["total_issues"], 0, "{reader}");
    assert_eq!(reader["progress"]["read_issues"], 0, "{reader}");
    assert_eq!(reader["available_now"], json!([]), "{reader}");
    assert_eq!(reader["lanes"], json!([]), "{reader}");

    // Save an issue through the same authoring path the legacy editor uses.
    // The editor hydrates the empty plan with a default lane, so saving
    // writes one lane and the issue.
    let user_id = user_id_for(&state, "cp-strict-empty").await;
    seed_thread_issue(&state, user_id, 546241, 546251, "QA Strict Series", "1").await;
    let (status, saved) = authed_json(
        &state,
        "PUT",
        &format!("/api/v2/continuity-plans/{plan_id}"),
        &token,
        &csrf,
        Some(json!({
            "name": "QA strict empty plan",
            "ordering_mode": "strict_sequential",
            "lanes": [{"id": "main", "name": "Main", "order": 0}],
            "nodes": [{
                "id": "issue-546251",
                "node_type": "issue",
                "ref_id": 546251,
                "lane_id": "main",
                "position": 0,
                "label": "QA Strict Series #1"
            }],
            "expected_updated_at": created["updated_at"]
        })),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{saved}");

    let (status, reopened) = authed_json(
        &state,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}/reader"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{reopened}");
    assert_eq!(
        reopened["lanes"].as_array().map(Vec::len),
        Some(1),
        "{reopened}"
    );
    assert_eq!(reopened["lanes"][0]["id"], "main", "{reopened}");
    assert_eq!(
        reopened["lanes"][0]["issues"][0]["issue_id"], 546251,
        "{reopened}"
    );
    assert_eq!(
        reopened["lanes"][0]["issues"][0]["issue_number"], "1",
        "{reopened}"
    );
}

/// Issue #4724: a saved Strict plan linked to a loose (or stale) Reading List
/// must keep displaying Strict. The List stays the sole authority for
/// *execution*, but `ordering_mode` is the plan's explicit saved display intent
/// and must agree with the plans index and the planner editor after refresh.
#[tokio::test]
async fn strict_plan_linked_to_loose_list_keeps_explicit_ordering_mode() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cp-mode-strict-loose").await;
    let user_id = user_id_for(&state, "cp-mode-strict-loose").await;

    let (status, created) = create_plan(
        &state,
        &token,
        &csrf,
        json!({
            "name": "Plan A mode regression",
            "ordering_mode": "strict_sequential",
            "lanes": [{"id": "main", "name": "Main", "order": 0}],
            "nodes": []
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id");
    let plan_id_i32 = i32::try_from(plan_id).expect("int4 plan id");

    seed_thread_issue(&state, user_id, 547301, 547311, "Mode Series A", "1").await;
    seed_thread_issue(&state, user_id, 547302, 547312, "Mode Series B", "1").await;

    let conn = db::checkout(&state).await.expect("seed connection");
    let list_id: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, mode, created_at, updated_at)
             VALUES ($1, 'QA loose authority', 'loose', NOW(), NOW()) RETURNING id",
            &[&user_id],
        )
        .await
        .expect("create owned loose list")
        .get(0);
    conn.execute(
        "INSERT INTO custom_cbl_entries (list_id, issue_id, position, created_at)
         VALUES ($1, 547311, 0, NOW()), ($1, 547312, 1, NOW())",
        &[&list_id],
    )
    .await
    .expect("seed owned list entries");
    conn.execute(
        "INSERT INTO reading_plan_sources
            (plan_id, raw_source_path, custom_cbl_list_id, recorded_at)
         VALUES ($1, $2, $3, NOW())",
        &[&plan_id_i32, &format!("custom-cbl:{list_id}"), &list_id],
    )
    .await
    .expect("link plan to authoritative list");
    drop(conn);

    let (status, reader) = authed_json(
        &state,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}/reader"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{reader}");
    assert_eq!(reader["execution_mode"], "option_e", "{reader}");
    assert_eq!(reader["ordering_mode"], "strict_sequential", "{reader}");
    // Availability is still projected by the linked loose List, not the mode
    // we display for the plan.
    assert_eq!(
        reader["lanes"][0]["issues"].as_array().map(Vec::len),
        Some(2),
        "{reader}"
    );
    assert_eq!(
        reader["available_now"].as_array().map(Vec::len),
        Some(2),
        "{reader}"
    );

    let (status, listed) = authed_json(
        &state,
        "GET",
        "/api/v2/continuity-plans/",
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{listed}");
    let item = listed
        .as_array()
        .and_then(|items| items.iter().find(|item| item["id"] == plan_id))
        .expect("created plan in index");
    assert_eq!(item["ordering_mode"], "strict_sequential", "{listed}");
}

/// Issue #4724 legacy fallback: a plan that never had an authoritative List
/// keeps its explicit saved mode too, so a refresh cannot silently downgrade
/// it when the source link is absent.
#[tokio::test]
async fn strict_legacy_plan_keeps_explicit_ordering_mode_without_list() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cp-mode-strict-legacy").await;

    let (status, created) = create_plan(
        &state,
        &token,
        &csrf,
        json!({
            "name": "Plan A legacy mode regression",
            "ordering_mode": "strict_sequential",
            "lanes": [{"id": "main", "name": "Main", "order": 0}],
            "nodes": []
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id");

    let (status, reader) = authed_json(
        &state,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}/reader"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{reader}");
    assert_eq!(reader["execution_mode"], "legacy", "{reader}");
    assert_eq!(reader["ordering_mode"], "strict_sequential", "{reader}");
    assert_eq!(reader["available_now"], json!([]), "{reader}");
    assert_eq!(reader["blocked_next"], json!([]), "{reader}");
}

/// A plan whose owned Reading List link was removed must still require the
/// explicit recovery flow. The FK sets custom_cbl_list_id to NULL on list
/// deletion while the immutable `custom-cbl:<id>` provenance survives.
#[tokio::test]
async fn plan_with_removed_list_authority_still_requires_recovery() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cp-orphaned-reader").await;

    let (status, created) = create_plan(
        &state,
        &token,
        &csrf,
        json!({
            "name": "QA orphaned plan",
            "ordering_mode": "informational",
            "lanes": [],
            "nodes": []
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id");

    let plan_id_i32 = i32::try_from(plan_id).expect("int4 plan id");
    let conn = db::checkout(&state).await.expect("seed connection");
    conn.execute(
        "INSERT INTO reading_plan_sources (plan_id, raw_source_path, recorded_at)
         VALUES ($1, 'custom-cbl:999999', NOW())",
        &[&plan_id_i32],
    )
    .await
    .expect("seed removed-list provenance");
    drop(conn);

    let (status, reader) = authed_json(
        &state,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}/reader"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{reader}");
    assert!(
        reader.to_string().contains("Open recovery to relink"),
        "{reader}"
    );
}

/// Recovery relink records Reading List authority independently of plan nodes.
/// Saving through the authoring editor must not erase that provenance, or an
/// orphaned plan could silently become a never-linked legacy plan.
#[tokio::test]
async fn authoring_save_preserves_removed_list_authority() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cp-preserve-authority").await;

    let (status, created) = create_plan(
        &state,
        &token,
        &csrf,
        json!({
            "name": "QA relinked plan",
            "ordering_mode": "informational",
            "lanes": [],
            "nodes": []
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id");
    let plan_id_i32 = i32::try_from(plan_id).expect("int4 plan id");
    let user_id = user_id_for(&state, "cp-preserve-authority").await;

    let conn = db::checkout(&state).await.expect("seed connection");
    let list_id: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, mode, created_at, updated_at)
             VALUES ($1, 'QA authority', 'loose', NOW(), NOW()) RETURNING id",
            &[&user_id],
        )
        .await
        .expect("create owned list")
        .get(0);
    let raw_source_path = format!("custom-cbl:{list_id}");
    conn.execute(
        "INSERT INTO reading_plan_sources
            (plan_id, raw_source_path, custom_cbl_list_id, recorded_at)
         VALUES ($1, $2, $3, NOW())",
        &[&plan_id_i32, &raw_source_path, &list_id],
    )
    .await
    .expect("relink plan to list");
    conn.execute("DELETE FROM custom_cbl_lists WHERE id=$1", &[&list_id])
        .await
        .expect("delete the list; FK sets custom_cbl_list_id to NULL");
    drop(conn);

    let (status, reader) = authed_json(
        &state,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}/reader"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{reader}");

    let (status, saved) = authed_json(
        &state,
        "PUT",
        &format!("/api/v2/continuity-plans/{plan_id}"),
        &token,
        &csrf,
        Some(json!({
            "name": "QA relinked plan",
            "ordering_mode": "informational",
            "lanes": [{"id": "main", "name": "Main", "order": 0}],
            "nodes": [],
            "expected_updated_at": created["updated_at"]
        })),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{saved}");

    let (status, reopened) = authed_json(
        &state,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}/reader"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{reopened}");
    assert!(
        reopened.to_string().contains("Open recovery to relink"),
        "{reopened}"
    );

    let conn = db::checkout(&state).await.expect("verify connection");
    let preserved: i64 = conn
        .query_one(
            "SELECT count(*) FROM reading_plan_sources
              WHERE plan_id=$1 AND raw_source_path LIKE 'custom-cbl:%'",
            &[&plan_id_i32],
        )
        .await
        .expect("verify preserved provenance")
        .get(0);
    drop(conn);
    assert_eq!(preserved, 1, "authoring save erased list provenance");
}

/// Concurrency guard for the changed membership writer: two overlapping saves
/// of the same plan must both settle (one wins, one version-conflicts) without
/// deadlocking or losing preserved Reading List provenance.
#[tokio::test]
async fn concurrent_authoring_saves_keep_source_history() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cp-save-race").await;

    let (status, created) = create_plan(
        &state,
        &token,
        &csrf,
        json!({
            "name": "QA race plan",
            "ordering_mode": "informational",
            "lanes": [],
            "nodes": []
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id");
    let plan_id_i32 = i32::try_from(plan_id).expect("int4 plan id");
    let user_id = user_id_for(&state, "cp-save-race").await;

    let conn = db::checkout(&state).await.expect("seed connection");
    let list_id: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, mode, created_at, updated_at)
             VALUES ($1, 'QA race authority', 'loose', NOW(), NOW()) RETURNING id",
            &[&user_id],
        )
        .await
        .expect("create owned list")
        .get(0);
    let raw_source_path = format!("custom-cbl:{list_id}");
    conn.execute(
        "INSERT INTO reading_plan_sources
            (plan_id, raw_source_path, custom_cbl_list_id, recorded_at)
         VALUES ($1, $2, $3, NOW())",
        &[&plan_id_i32, &raw_source_path, &list_id],
    )
    .await
    .expect("relink plan to list");
    drop(conn);

    let payload = |name: &str| {
        json!({
            "name": name,
            "ordering_mode": "informational",
            "lanes": [{"id": "main", "name": "Main", "order": 0}],
            "nodes": [],
            "expected_updated_at": created["updated_at"]
        })
    };
    let uri = format!("/api/v2/continuity-plans/{plan_id}");
    let (first, second) = tokio::join!(
        authed_json(&state, "PUT", &uri, &token, &csrf, Some(payload("race A"))),
        authed_json(&state, "PUT", &uri, &token, &csrf, Some(payload("race B"))),
    );
    let statuses = [first.0, second.0];
    assert_eq!(
        statuses
            .iter()
            .filter(|status| **status == StatusCode::OK)
            .count(),
        1,
        "expected exactly one winning save: {first:?} {second:?}"
    );
    assert_eq!(
        statuses
            .iter()
            .filter(|status| **status == StatusCode::CONFLICT)
            .count(),
        1,
        "expected one optimistic-lock conflict: {first:?} {second:?}"
    );

    let conn = db::checkout(&state).await.expect("verify connection");
    let preserved: i64 = conn
        .query_one(
            "SELECT count(*) FROM reading_plan_sources
              WHERE plan_id=$1 AND raw_source_path=$2",
            &[&plan_id_i32, &raw_source_path],
        )
        .await
        .expect("verify preserved provenance")
        .get(0);
    drop(conn);
    assert_eq!(preserved, 1, "concurrent saves lost list provenance");
}

/// Repeated authoring saves of a preserved `custom-cbl:` placement must rebuild
/// its placement row rather than duplicating or stranding it.
#[tokio::test]
async fn repeated_authoring_saves_do_not_duplicate_preserved_placements() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cp-repeat-save").await;

    let (status, created) = create_plan(
        &state,
        &token,
        &csrf,
        json!({
            "name": "QA repeat plan",
            "ordering_mode": "informational",
            "lanes": [],
            "nodes": []
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id");
    let plan_id_i32 = i32::try_from(plan_id).expect("int4 plan id");
    let user_id = user_id_for(&state, "cp-repeat-save").await;
    seed_thread_issue(&state, user_id, 546301, 546311, "Repeat Series", "1").await;

    let conn = db::checkout(&state).await.expect("seed connection");
    let list_id: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, mode, created_at, updated_at)
             VALUES ($1, 'QA repeat authority', 'loose', NOW(), NOW()) RETURNING id",
            &[&user_id],
        )
        .await
        .expect("create owned list")
        .get(0);
    let raw_source_path = format!("custom-cbl:{list_id}");
    conn.execute(
        "INSERT INTO reading_plan_sources
            (plan_id, raw_source_path, custom_cbl_list_id, recorded_at)
         VALUES ($1, $2, $3, NOW())",
        &[&plan_id_i32, &raw_source_path, &list_id],
    )
    .await
    .expect("relink plan to list");
    drop(conn);

    let build_payload = |version: &serde_json::Value| {
        json!({
            "name": "QA repeat plan",
            "ordering_mode": "informational",
            "lanes": [{"id": "main", "name": "Main", "order": 0}],
            "nodes": [{
                "id": "issue-546311",
                "node_type": "issue",
                "ref_id": 546311,
                "lane_id": "main",
                "position": 0,
                "source_paths": [raw_source_path]
            }],
            "expected_updated_at": version
        })
    };

    let uri = format!("/api/v2/continuity-plans/{plan_id}");
    let (status, first) = authed_json(
        &state,
        "PUT",
        &uri,
        &token,
        &csrf,
        Some(build_payload(&created["updated_at"])),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{first}");

    let (status, plan) = authed_json(&state, "GET", &uri, &token, &csrf, None).await;
    assert_eq!(status, StatusCode::OK, "{plan}");
    let (status, second) = authed_json(
        &state,
        "PUT",
        &uri,
        &token,
        &csrf,
        Some(build_payload(&plan["updated_at"])),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{second}");

    let conn = db::checkout(&state).await.expect("verify connection");
    let placements: i64 = conn
        .query_one(
            "SELECT count(*) FROM reading_plan_source_placements
              WHERE plan_id=$1",
            &[&plan_id_i32],
        )
        .await
        .expect("verify placements")
        .get(0);
    drop(conn);
    assert_eq!(placements, 1, "repeated save duplicated a placement row");
}
