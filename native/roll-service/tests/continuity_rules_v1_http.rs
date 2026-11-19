#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Focused native HTTP regressions for the browser-called continuity-rules v1
//! cutover (issue #4848). Exercises the mounted Rust router so auth, ownership,
//! validation, cycle detection, canonical edge compilation and the wire shape
//! are verified at the same-path ingress (`/api/v1/continuity-rules/`).
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

async fn send(
    state: &Arc<AppState>,
    request: Request<Body>,
) -> (StatusCode, Value, Vec<String>, Option<String>) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    let runtime = response
        .headers()
        .get("x-comicpile-api-runtime")
        .and_then(|value| value.to_str().ok())
        .map(str::to_owned);
    let cookies = response
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .filter_map(|value| value.to_str().ok().map(str::to_owned))
        .collect::<Vec<_>>();
    let body = to_bytes(response.into_body(), 65536).await.unwrap();
    let body = serde_json::from_slice(&body).unwrap_or(Value::Null);
    (status, body, cookies, runtime)
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
    let (status, registered, cookies, _) = send(
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
    let (status, value, _, _) = send(state, request).await;
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

async fn seed_thread(state: &Arc<AppState>, user_id: i32, thread_id: i32) {
    let conn = db::checkout(state).await.expect("seed connection");
    conn.execute(
        "INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status)
          VALUES ($1, $2, 'Continuity Rules Test', 'Comic', 3, 1, 'active')",
        &[&thread_id, &user_id],
    )
    .await
    .expect("seed thread");
}

async fn seed_issue(state: &Arc<AppState>, thread_id: i32, issue_id: i32, number: &str) {
    let conn = db::checkout(state).await.expect("seed connection");
    conn.execute(
        "INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
          VALUES ($1, $2, $3, 'unread', NOW(), $4)",
        &[&issue_id, &thread_id, &number, &(issue_id % 1000)],
    )
    .await
    .expect("seed issue");
}

async fn seed_thread_issues(state: &Arc<AppState>, user_id: i32, thread_id: i32, issue_ids: &[i32]) {
    seed_thread(state, user_id, thread_id).await;
    for (index, issue_id) in issue_ids.iter().enumerate() {
        seed_issue(state, thread_id, *issue_id, &format!("{}", index + 1)).await;
    }
}

fn item_read_rule(source_id: i64, target_id: i64) -> Value {
    json!({
        "source_type": "issue",
        "source_id": source_id,
        "target_type": "issue",
        "target_id": target_id,
        "satisfaction_type": "item_read",
        "checkpoint_issue_id": null,
        "convergence_targets": [],
        "selected_member_issue_ids": [],
        "note": null
    })
}

async fn dependency_count(state: &Arc<AppState>, source: i32, target: i32) -> i64 {
    let conn = db::checkout(state).await.expect("edge verify connection");
    conn.query_one(
        "SELECT count(*) FROM dependencies WHERE source_issue_id=$1 AND target_issue_id=$2",
        &[&source, &target],
    )
    .await
    .expect("edge count")
    .get(0)
}

/// All five operations require authentication, and every response (including
/// the 401) carries the native runtime identity header.
#[tokio::test]
async fn continuity_rules_operations_require_auth_and_emit_rust_runtime_header() {
    let (state, _db) = database().await;
    for (method, uri) in [
        ("GET", "/api/v1/continuity-rules/".to_string()),
        ("POST", "/api/v1/continuity-rules/".to_string()),
        ("GET", "/api/v1/continuity-rules/1".to_string()),
        ("PUT", "/api/v1/continuity-rules/1".to_string()),
        ("DELETE", "/api/v1/continuity-rules/1".to_string()),
    ] {
        let request = Request::builder()
            .method(method)
            .uri(&uri)
            .body(Body::from("{}"))
            .unwrap();
        let (status, _body, _, runtime) = send(&state, request).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED, "{method} {uri}");
        assert_eq!(
            runtime.as_deref(),
            Some("rust"),
            "{method} {uri} must be served by the native binary"
        );
    }
}

/// Full same-path CRUD wire contract: create 201 shape, list, get, update,
/// delete 204, then 404s — plus canonical edge compilation and retirement.
#[tokio::test]
async fn continuity_rule_crud_wire_contract_and_canonical_edges() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cr-crud").await;
    let user_id = user_id_for(&state, "cr-crud").await;
    seed_thread_issues(&state, user_id, 810001, &[810011, 810012, 810013]).await;

    // Create: 201 with the full response shape.
    let (status, created) = authed_json(
        &state,
        "POST",
        "/api/v1/continuity-rules/",
        &token,
        &csrf,
        Some(item_read_rule(810011, 810012)),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let rule_id = created["id"].as_i64().expect("rule id");
    assert_eq!(created["user_id"], user_id);
    assert_eq!(created["source_type"], "issue");
    assert_eq!(created["source_id"], 810011);
    assert_eq!(created["target_type"], "issue");
    assert_eq!(created["target_id"], 810012);
    assert_eq!(created["satisfaction_type"], "item_read");
    assert!(created["checkpoint_issue_id"].is_null(), "{created}");
    assert_eq!(created["convergence_targets"], json!([]), "{created}");
    assert_eq!(created["selected_member_issue_ids"], json!([]), "{created}");
    assert!(created["note"].is_null(), "{created}");
    assert!(
        created["created_at"].as_str().is_some_and(|value| !value.is_empty()),
        "{created}"
    );
    assert!(
        created["updated_at"].as_str().is_some_and(|value| !value.is_empty()),
        "{created}"
    );
    // item_read issue->issue compiles to the canonical source->target edge.
    assert_eq!(
        dependency_count(&state, 810011, 810012).await,
        1,
        "create must compile the canonical dependency edge"
    );

    // List: 200 array containing the created rule.
    let (status, listed) = authed_json(
        &state,
        "GET",
        "/api/v1/continuity-rules/",
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{listed}");
    assert!(
        listed
            .as_array()
            .unwrap()
            .iter()
            .any(|item| item["id"] == rule_id),
        "{listed}"
    );

    // Get: 200 with the same id.
    let (status, fetched) = authed_json(
        &state,
        "GET",
        &format!("/api/v1/continuity-rules/{rule_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{fetched}");
    assert_eq!(fetched["id"], rule_id);
    assert_eq!(fetched["target_id"], 810012);

    // Update: 200, note changed, edge retargeted to the new pair.
    let mut update = item_read_rule(810011, 810013);
    update["note"] = json!("retargeted");
    let (status, updated) = authed_json(
        &state,
        "PUT",
        &format!("/api/v1/continuity-rules/{rule_id}"),
        &token,
        &csrf,
        Some(update),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{updated}");
    assert_eq!(updated["id"], rule_id);
    assert_eq!(updated["target_id"], 810013);
    assert_eq!(updated["note"], "retargeted");
    assert_eq!(dependency_count(&state, 810011, 810012).await, 0);
    assert_eq!(dependency_count(&state, 810011, 810013).await, 1);

    // Delete: 204, then get/delete are 404 and the canonical edge is retired.
    let (status, _) = authed_json(
        &state,
        "DELETE",
        &format!("/api/v1/continuity-rules/{rule_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    let (status, gone) = authed_json(
        &state,
        "GET",
        &format!("/api/v1/continuity-rules/{rule_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{gone}");
    assert_eq!(
        format!("{gone}"),
        format!("{{\"detail\":\"Continuity rule {rule_id} not found\"}}")
    );
    let (status, _) = authed_json(
        &state,
        "DELETE",
        &format!("/api/v1/continuity-rules/{rule_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(dependency_count(&state, 810011, 810013).await, 0);
}

/// Validation, ownership, duplicate and cycle error contract at the same-path
/// ingress: 400 for invalid shapes, 404 for unowned/foreign nodes and rules,
/// 409 for the duplicate edge and for cycles.
#[tokio::test]
async fn continuity_rule_validation_ownership_duplicate_and_cycle_errors() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cr-errors").await;
    let user_id = user_id_for(&state, "cr-errors").await;
    seed_thread_issues(&state, user_id, 820001, &[820011, 820012, 820013]).await;

    // A second user owns foreign issues and a foreign rule.
    let (foreign_token, foreign_csrf) = register_and_login(&state, "cr-foreign").await;
    let foreign_user_id = user_id_for(&state, "cr-foreign").await;
    seed_thread_issues(&state, foreign_user_id, 820002, &[820021, 820022]).await;
    let (status, foreign_rule) = authed_json(
        &state,
        "POST",
        "/api/v1/continuity-rules/",
        &foreign_token,
        &foreign_csrf,
        Some(item_read_rule(820021, 820022)),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{foreign_rule}");
    let foreign_rule_id = foreign_rule["id"].as_i64().expect("foreign rule id");

    let uri = "/api/v1/continuity-rules/";

    // Invalid satisfaction_type -> 400.
    let mut bad_type = item_read_rule(820011, 820012);
    bad_type["satisfaction_type"] = json!("bogus");
    let (status, body) = authed_json(&state, "POST", uri, &token, &csrf, Some(bad_type)).await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body}");
    assert_eq!(body["detail"], "Invalid satisfaction_type");

    // Self-target -> 400.
    let mut self_target = item_read_rule(820011, 820011);
    let (status, body) = authed_json(&state, "POST", uri, &token, &csrf, Some(self_target)).await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body}");
    assert_eq!(body["detail"], "A continuity rule cannot target its own source node");

    // Checkpoint rule without checkpoint_issue_id -> 400.
    let mut checkpoint = item_read_rule(820011, 820012);
    checkpoint["satisfaction_type"] = json!("checkpoint");
    let (status, body) = authed_json(&state, "POST", uri, &token, &csrf, Some(checkpoint)).await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body}");
    assert_eq!(
        body["detail"],
        "checkpoint_issue_id is required for checkpoint rules"
    );

    // Non-compilable shape (item_read onto a crossover target) -> 400.
    let mut crossover = item_read_rule(820011, 820012);
    crossover["target_type"] = json!("crossover");
    let (status, body) = authed_json(&state, "POST", uri, &token, &csrf, Some(crossover)).await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body}");
    assert!(
        format!("{body}").contains("does not compile to canonical edges"),
        "{body}"
    );

    // Rule referencing another user's issue -> 404.
    let mut unowned = item_read_rule(820011, 820021);
    let (status, body) = authed_json(&state, "POST", uri, &token, &csrf, Some(unowned)).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body}");
    assert_eq!(body["detail"], "Issue 820021 not found");

    // Valid create, then duplicate edge -> 409 continuity_rule_exists.
    let (status, created) = authed_json(
        &state,
        "POST",
        uri,
        &token,
        &csrf,
        Some(item_read_rule(820011, 820012)),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let rule_id = created["id"].as_i64().expect("rule id");
    let (status, body) = authed_json(
        &state,
        "POST",
        uri,
        &token,
        &csrf,
        Some(item_read_rule(820011, 820012)),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(body["detail"], "continuity_rule_exists");

    // Reverse edge closes a cycle -> 409 continuity_cycle.
    let (status, body) = authed_json(
        &state,
        "POST",
        uri,
        &token,
        &csrf,
        Some(item_read_rule(820012, 820011)),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(body["detail"], "continuity_cycle");

    // A second rule extends the graph: 820012 -> 820013.
    let (status, second) = authed_json(
        &state,
        "POST",
        uri,
        &token,
        &csrf,
        Some(item_read_rule(820012, 820013)),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{second}");

    // Foreign rule is invisible: get/put/delete -> 404.
    let foreign_uri = format!("/api/v1/continuity-rules/{foreign_rule_id}");
    for (method, body) in [
        ("GET", None),
        ("PUT", Some(item_read_rule(820011, 820012))),
        ("DELETE", None),
    ] {
        let (status, detail) = authed_json(&state, method, &foreign_uri, &token, &csrf, body).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{method}: {detail}");
        assert_eq!(
            detail["detail"],
            format!("Continuity rule {foreign_rule_id} not found")
        );
    }

    // Updating the first rule to 820013 -> 820012 would close the loop
    // 820012 -> 820013 -> 820012 through the surviving second rule -> 409.
    let (status, body) = authed_json(
        &state,
        "PUT",
        &format!("/api/v1/continuity-rules/{rule_id}"),
        &token,
        &csrf,
        Some(item_read_rule(820013, 820012)),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(body["detail"], "continuity_cycle");
}

/// Converged rules persist their convergence targets and compile one canonical
/// edge per issue convergence target; a checkpoint rule compiles from the
/// checkpoint issue instead of the source.
#[tokio::test]
async fn converged_and_checkpoint_rules_compile_canonical_edges() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cr-converged").await;
    let user_id = user_id_for(&state, "cr-converged").await;
    seed_thread_issues(&state, user_id, 830001, &[830011, 830012, 830013, 830014]).await;

    let uri = "/api/v1/continuity-rules/";

    // Converged rule: targets 830012 and 830013 wait for 830011.
    let converged = json!({
        "source_type": "issue",
        "source_id": 830011,
        "target_type": "issue",
        "target_id": 830012,
        "satisfaction_type": "converged",
        "checkpoint_issue_id": null,
        "convergence_targets": [{"type": "issue", "id": 830011}, {"type": "issue", "id": 830013}],
        "selected_member_issue_ids": [],
        "note": "converge here"
    });
    let (status, created) = authed_json(&state, "POST", uri, &token, &csrf, Some(converged)).await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let converged_id = created["id"].as_i64().expect("rule id");
    assert_eq!(
        created["convergence_targets"],
        json!([{"type": "issue", "id": 830011}, {"type": "issue", "id": 830013}]),
        "{created}"
    );
    assert_eq!(created["note"], "converge here");
    // The target itself is excluded from its own prerequisite edges.
    assert_eq!(dependency_count(&state, 830011, 830012).await, 1);
    assert_eq!(dependency_count(&state, 830013, 830012).await, 1);

    // Checkpoint rule on a disjoint pair: the canonical edge runs from the
    // checkpoint issue, not the source.
    let checkpoint = json!({
        "source_type": "issue",
        "source_id": 830013,
        "target_type": "issue",
        "target_id": 830014,
        "satisfaction_type": "checkpoint",
        "checkpoint_issue_id": 830011,
        "convergence_targets": [],
        "selected_member_issue_ids": [],
        "note": null
    });
    let (status, created) = authed_json(&state, "POST", uri, &token, &csrf, Some(checkpoint)).await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    assert_eq!(created["checkpoint_issue_id"], 830011);
    assert_eq!(dependency_count(&state, 830011, 830014).await, 1);
    assert_eq!(dependency_count(&state, 830013, 830014).await, 0);

    // Deleting the converged rule retires only its own canonical edges.
    let (status, _) = authed_json(
        &state,
        "DELETE",
        &format!("/api/v1/continuity-rules/{converged_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    assert_eq!(dependency_count(&state, 830011, 830012).await, 0);
    assert_eq!(dependency_count(&state, 830013, 830012).await, 0);
    // The checkpoint edge belongs to the other rule and must survive.
    assert_eq!(dependency_count(&state, 830011, 830014).await, 1);
}
