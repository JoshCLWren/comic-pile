#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Focused native HTTP regressions for the browser-called continuity-rules v1
//! cutover (issue #4848).
//!
//! The retired Python handler `app/api/continuity_rule.py` is the wire oracle.
//! These tests exercise the mounted Rust router at the identical same-path
//! ingress, so the frozen status codes, FastAPI `detail` envelopes, structured
//! domain errors, ISO-8601 timestamps and canonical dependency lifecycle are
//! all verified against a real PostgreSQL schema.
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

static NEXT_IP: AtomicU16 = AtomicU16::new(40);

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

async fn create_rule(
    state: &Arc<AppState>,
    token: &str,
    csrf: &str,
    body: Value,
) -> (StatusCode, Value) {
    authed_json(
        state,
        "POST",
        "/api/v1/continuity-rules/",
        token,
        csrf,
        Some(body),
    )
    .await
}

fn item_rule(source_id: i32, target_id: i32) -> Value {
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

#[tokio::test]
async fn continuity_rule_crud_is_native_wire_compatible() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cr-wire").await;
    let user_id = user_id_for(&state, "cr-wire").await;
    seed_thread_issue(&state, user_id, 810001, 810011, "Rules", "1").await;
    seed_thread_issue(&state, user_id, 810002, 810012, "Rules", "2").await;

    let (status, created) = create_rule(&state, &token, &csrf, item_rule(810011, 810012)).await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let rule_id = created["id"].as_i64().expect("rule id");
    assert_eq!(created["user_id"], user_id);
    assert_eq!(created["source_type"], "issue");
    assert_eq!(created["source_id"], 810011);
    assert_eq!(created["target_type"], "issue");
    assert_eq!(created["target_id"], 810012);
    assert_eq!(created["satisfaction_type"], "item_read");
    assert!(created["checkpoint_issue_id"].is_null(), "{created}");
    assert_eq!(created["convergence_targets"], json!([]));
    assert_eq!(created["selected_member_issue_ids"], json!([]));
    assert!(created["note"].is_null(), "{created}");
    // Python `datetime.isoformat()` shape: RFC-3339 with a `T` and `Z`.
    let created_at = created["created_at"].as_str().expect("created_at");
    let updated_at = created["updated_at"].as_str().expect("updated_at");
    assert!(created_at.contains('T'), "{created_at}");
    assert!(created_at.ends_with('Z'), "{created_at}");
    assert!(updated_at.ends_with('Z'), "{updated_at}");

    // The authored hard constraint compiles to one canonical dependency edge.
    let conn = db::checkout(&state).await.expect("edge lookup connection");
    let edges: i64 = conn
        .query_one(
            "SELECT count(*) FROM dependencies
             WHERE source_issue_id = 810011 AND target_issue_id = 810012
               AND note = $1",
            &[&format!("canonical:rule:{rule_id}")],
        )
        .await
        .expect("compiled edge lookup")
        .get(0);
    assert_eq!(edges, 1);
    drop(conn);

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
    assert!(listed
        .as_array()
        .expect("rule list")
        .iter()
        .any(|item| item["id"] == rule_id));

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
    assert_eq!(fetched["id"], created["id"]);

    let mut update = item_rule(810011, 810012);
    update["note"] = json!("updated");
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
    assert_eq!(updated["note"], "updated");
    assert!(updated["updated_at"]
        .as_str()
        .is_some_and(|value| value.ends_with('Z')));

    let (status, body) = authed_json(
        &state,
        "DELETE",
        &format!("/api/v1/continuity-rules/{rule_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{body}");

    let (status, missing) = authed_json(
        &state,
        "GET",
        &format!("/api/v1/continuity-rules/{rule_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{missing}");
    assert_eq!(
        missing["detail"],
        format!("Continuity rule {rule_id} not found")
    );

    // Deleting the rule retires its compiled canonical edge.
    let conn = db::checkout(&state).await.expect("edge retirement connection");
    let remaining: i64 = conn
        .query_one(
            "SELECT count(*) FROM dependencies
             WHERE source_issue_id = 810011 AND target_issue_id = 810012
               AND note LIKE 'canonical:rule:%'",
            &[],
        )
        .await
        .expect("retired edge lookup")
        .get(0);
    assert_eq!(remaining, 0);
}

#[tokio::test]
async fn continuity_rule_domain_errors_keep_python_structured_details() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cr-errors").await;
    let user_id = user_id_for(&state, "cr-errors").await;
    seed_thread_issue(&state, user_id, 820001, 820011, "Errors", "1").await;
    seed_thread_issue(&state, user_id, 820002, 820012, "Errors", "2").await;

    let (status, created) = create_rule(&state, &token, &csrf, item_rule(820011, 820012)).await;
    assert_eq!(status, StatusCode::CREATED, "{created}");

    // Unique edge constraint -> structured 409 (Python IntegrityError mapping).
    let (status, duplicate) = create_rule(&state, &token, &csrf, item_rule(820011, 820012)).await;
    assert_eq!(status, StatusCode::CONFLICT, "{duplicate}");
    assert_eq!(duplicate["detail"]["code"], "continuity_rule_exists");

    // Reverse edge completes a cycle -> structured 409 with the edge named.
    let (status, cycle) = create_rule(&state, &token, &csrf, item_rule(820012, 820011)).await;
    assert_eq!(status, StatusCode::CONFLICT, "{cycle}");
    assert_eq!(cycle["detail"]["code"], "continuity_cycle");
    assert_eq!(
        cycle["detail"]["source"],
        json!({"type": "issue", "id": 820012})
    );
    assert_eq!(
        cycle["detail"]["target"],
        json!({"type": "issue", "id": 820011})
    );

    // A member-list rule is schema-valid but never compiles to canonical edges.
    let mut member_rule = item_rule(820011, 820012);
    member_rule["satisfaction_type"] = json!("selected_members_read");
    member_rule["selected_member_issue_ids"] = json!([820011]);
    let (status, non_compilable) = create_rule(&state, &token, &csrf, member_rule).await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{non_compilable}");
    assert_eq!(
        non_compilable["detail"]["code"],
        "continuity_rule_not_compilable"
    );
    assert!(
        non_compilable["detail"]["message"]
            .as_str()
            .is_some_and(|message| message.contains("does not compile to canonical edges")),
        "{non_compilable}"
    );

    // A historical inert cbl-order row must not be silently shadowed.
    seed_thread_issue(&state, user_id, 820003, 820021, "Collision", "1").await;
    seed_thread_issue(&state, user_id, 820004, 820022, "Collision", "2").await;
    let conn = db::checkout(&state).await.expect("collision seed connection");
    conn.batch_execute(
        "INSERT INTO dependencies (created_at, source_issue_id, target_issue_id, note)
         VALUES (NOW(), 820021, 820022, 'cbl-order:legacy-materialization');",
    )
    .await
    .expect("seed inert cbl-order row");
    drop(conn);
    let (status, collision) = create_rule(&state, &token, &csrf, item_rule(820021, 820022)).await;
    assert_eq!(status, StatusCode::CONFLICT, "{collision}");
    assert_eq!(collision["detail"]["code"], "continuity_cbl_collision");
    assert!(
        collision["detail"]["message"]
            .as_str()
            .is_some_and(|message| message.contains("collides with historical cbl-order rows")),
        "{collision}"
    );
}

#[tokio::test]
async fn continuity_rule_validation_uses_the_house_422_envelope() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cr-validation").await;
    let user_id = user_id_for(&state, "cr-validation").await;
    seed_thread_issue(&state, user_id, 830001, 830011, "Validation", "1").await;
    seed_thread_issue(&state, user_id, 830002, 830012, "Validation", "2").await;

    let mut invalid_type = item_rule(830011, 830012);
    invalid_type["satisfaction_type"] = json!("not-a-satisfaction");
    let (status, body) = create_rule(&state, &token, &csrf, invalid_type).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"], "Validation failed");

    let mut invalid_id = item_rule(830011, 830012);
    invalid_id["source_id"] = json!(0);
    let (status, body) = create_rule(&state, &token, &csrf, invalid_id).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"], "Validation failed");

    let mut oversized_note = item_rule(830011, 830012);
    oversized_note["note"] = json!("x".repeat(501));
    let (status, body) = create_rule(&state, &token, &csrf, oversized_note).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"], "Validation failed");
}

#[tokio::test]
async fn continuity_rule_unowned_references_return_python_404_detail() {
    let (state, _db) = database().await;
    let (token, csrf) = register_and_login(&state, "cr-owner").await;
    register_and_login(&state, "cr-foreign").await;
    let foreign_user_id = user_id_for(&state, "cr-foreign").await;
    seed_thread_issue(
        &state,
        foreign_user_id,
        840001,
        840011,
        "Foreign",
        "1",
    )
    .await;
    seed_thread_issue(
        &state,
        foreign_user_id,
        840002,
        840012,
        "Foreign",
        "2",
    )
    .await;

    let (status, body) = create_rule(&state, &token, &csrf, item_rule(840011, 840012)).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body}");
    assert_eq!(body["detail"], "Issue 840011 not found");
}
