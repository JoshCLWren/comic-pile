#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Focused native HTTP regressions for the browser-called reading-order-groups
//! v1 cutover (issue #4841, parent #4335). Exercises the mounted Rust router so
//! auth, ownership, wire shape and transactional CRUD are verified at the
//! same-path ingress `/api/v1/reading-order-groups/*`.
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

async fn register_and_login(state: &Arc<AppState>, username: &str) -> (String, String, i32) {
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
    let conn = db::checkout(state).await.expect("user lookup connection");
    let row = conn
        .query_one("SELECT id FROM users WHERE username = $1", &[&username])
        .await
        .expect("registered user row");
    (token, csrf, row.get(0))
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

async fn seed_thread_with_issues(
    state: &Arc<AppState>,
    user_id: i32,
    title: &str,
    numbers: &[&str],
) -> (i32, Vec<i32>) {
    let conn = db::checkout(state).await.expect("seed connection");
    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, total_issues) \
             VALUES ($1, 'Comic', $2, 1, 'active', $3, $2) RETURNING id",
            &[&title, &(numbers.len() as i32), &user_id],
        )
        .await
        .expect("seed thread")
        .get(0);
    let positions: Vec<i32> = (1..=numbers.len() as i32).collect();
    let issue_ids: Vec<i32> = conn
        .query(
            "INSERT INTO issues (thread_id, issue_number, status, created_at, position) \
             SELECT $1, new.number, 'unread', NOW(), new.position \
             FROM unnest($2::text[], $3::int[]) AS new(number, position) \
             RETURNING id",
            &[&thread_id, &numbers, &positions],
        )
        .await
        .expect("seed issues")
        .iter()
        .map(|row| row.get(0))
        .collect();
    (thread_id, issue_ids)
}

/// Full same-path CRUD over the mounted router, including the Python error
/// shapes (401 unauthenticated, 409 duplicate name, 422 blank name, 404
/// foreign/missing group) and the list/detail/member wire fields.
#[tokio::test]
async fn reading_order_groups_http_crud_matches_python_wire_contract() {
    let (state, _db) = database().await;
    let (token, csrf, user_id) = register_and_login(&state, "rog-crud").await;

    // Auth is enforced at the same-path ingress.
    let (status, _, _) = send(
        &state,
        Request::builder()
            .method("GET")
            .uri("/api/v1/reading-order-groups/")
            .body(Body::empty())
            .unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);

    // Empty list is `[]`, never an omitted field.
    let (status, listed) = authed_json(
        &state,
        "GET",
        "/api/v1/reading-order-groups/",
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{listed}");
    assert_eq!(listed, json!([]), "{listed}");

    // Create trims the name and returns the full group projection.
    let (status, created) = authed_json(
        &state,
        "POST",
        "/api/v1/reading-order-groups/",
        &token,
        &csrf,
        Some(json!({"name": "  Alpha crossover  "})),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let group_id = created["id"].as_i64().expect("group id");
    assert_eq!(created["name"], "Alpha crossover");
    assert!(created["created_at"].as_str().is_some(), "{created}");
    assert_eq!(created["memberships"], json!([]), "{created}");
    assert_eq!(created["read_issues"], 0, "{created}");
    assert_eq!(created["total_issues"], 0, "{created}");
    assert_eq!(created["reading_progress"], "0%", "{created}");

    // Python parity: duplicate name -> 409, blank name -> 422.
    let (status, dup) = authed_json(
        &state,
        "POST",
        "/api/v1/reading-order-groups/",
        &token,
        &csrf,
        Some(json!({"name": "Alpha crossover"})),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{dup}");
    assert_eq!(dup["detail"], "A group with this name already exists");
    let (status, blank) = authed_json(
        &state,
        "POST",
        "/api/v1/reading-order-groups/",
        &token,
        &csrf,
        Some(json!({"name": "   "})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{blank}");
    assert_eq!(blank["detail"], "Group name must not be blank");

    // Seed a thread with two unread issues and add the thread as a member.
    let (thread_id, issue_ids) =
        seed_thread_with_issues(&state, user_id, "Rog Series", &["1", "2"]).await;
    let (status, member) = authed_json(
        &state,
        "POST",
        &format!("/api/v1/reading-order-groups/{group_id}/members"),
        &token,
        &csrf,
        Some(json!({"thread_id": thread_id})),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{member}");
    assert_eq!(member["thread_id"], thread_id);
    assert_eq!(member["series_title"], "Rog Series");
    let member_id = member["id"].as_i64().expect("member id");

    // Exactly one of thread_id / issue_id is required.
    let (status, both) = authed_json(
        &state,
        "POST",
        &format!("/api/v1/reading-order-groups/{group_id}/members"),
        &token,
        &csrf,
        Some(json!({"thread_id": thread_id, "issue_id": issue_ids[0]})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{both}");

    // List and get both carry the membership and progress projection.
    let (status, listed) = authed_json(
        &state,
        "GET",
        "/api/v1/reading-order-groups/",
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{listed}");
    let group = listed
        .as_array()
        .expect("list array")
        .iter()
        .find(|item| item["id"] == group_id)
        .expect("created group present")
        .clone();
    assert_eq!(group["memberships"].as_array().expect("members").len(), 1);
    assert_eq!(group["total_issues"], 2, "{group}");
    assert_eq!(group["read_issues"], 0, "{group}");
    assert_eq!(group["reading_progress"], "0%", "{group}");

    let (status, fetched) = authed_json(
        &state,
        "GET",
        &format!("/api/v1/reading-order-groups/{group_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{fetched}");
    assert_eq!(fetched["id"], group_id);
    assert_eq!(fetched["name"], "Alpha crossover");

    // Thread-scoped group summaries.
    let (status, summaries) = authed_json(
        &state,
        "GET",
        &format!("/api/v1/reading-order-groups/threads/{thread_id}/groups"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{summaries}");
    assert!(summaries
        .as_array()
        .expect("summaries array")
        .iter()
        .any(|item| item["id"] == group_id && item["name"] == "Alpha crossover"));

    // Detail nests the membership with its thread projection.
    let (status, detail) = authed_json(
        &state,
        "GET",
        &format!("/api/v1/reading-order-groups/{group_id}/detail"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{detail}");
    let detail_members = detail["memberships"]
        .as_array()
        .expect("detail memberships");
    assert_eq!(detail_members.len(), 1, "{detail}");
    assert_eq!(detail_members[0]["membership"]["id"], member_id);
    assert_eq!(
        detail_members[0]["thread"]["title"],
        json!("Rog Series"),
        "{detail}"
    );
    assert!(detail["linked_plans"].is_array(), "{detail}");

    // Rename via PATCH.
    let (status, renamed) = authed_json(
        &state,
        "PATCH",
        &format!("/api/v1/reading-order-groups/{group_id}"),
        &token,
        &csrf,
        Some(json!({"name": "Beta crossover"})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{renamed}");
    assert_eq!(renamed["name"], "Beta crossover");

    // Remove the member, then delete the group; both are 204 and the group
    // afterwards 404s.
    let (status, removed) = authed_json(
        &state,
        "DELETE",
        &format!("/api/v1/reading-order-groups/{group_id}/members/{member_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{removed}");
    let (status, deleted) = authed_json(
        &state,
        "DELETE",
        &format!("/api/v1/reading-order-groups/{group_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{deleted}");
    let (status, gone) = authed_json(
        &state,
        "GET",
        &format!("/api/v1/reading-order-groups/{group_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{gone}");
    assert_eq!(gone["detail"], format!("Group {group_id} not found"));
}

/// Ownership isolation: a second user can neither see nor mutate another
/// user's group, and unknown thread ids 404 like the Python handler.
#[tokio::test]
async fn reading_order_groups_are_owner_scoped_over_http() {
    let (state, _db) = database().await;
    let (token_a, csrf_a, _user_a) = register_and_login(&state, "rog-owner-a").await;
    let (token_b, csrf_b, _user_b) = register_and_login(&state, "rog-owner-b").await;

    let (status, created) = authed_json(
        &state,
        "POST",
        "/api/v1/reading-order-groups/",
        &token_a,
        &csrf_a,
        Some(json!({"name": "Owner A group"})),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let group_id = created["id"].as_i64().expect("group id");

    for method in ["GET", "PATCH", "DELETE"] {
        let body = if method == "PATCH" {
            Some(json!({"name": "stolen"}))
        } else {
            None
        };
        let (status, body_out) = authed_json(
            &state,
            method,
            &format!("/api/v1/reading-order-groups/{group_id}"),
            &token_b,
            &csrf_b,
            body,
        )
        .await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{method}: {body_out}");
    }

    // User B's list stays empty; user A still sees the group.
    let (status, listed_b) = authed_json(
        &state,
        "GET",
        "/api/v1/reading-order-groups/",
        &token_b,
        &csrf_b,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{listed_b}");
    assert_eq!(listed_b, json!([]), "{listed_b}");

    // Unknown thread id -> 404 `Thread {id} not found` (Python parity).
    let (status, missing) = authed_json(
        &state,
        "GET",
        "/api/v1/reading-order-groups/threads/424242/groups",
        &token_a,
        &csrf_a,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{missing}");
    assert_eq!(missing["detail"], "Thread 424242 not found");
}

/// Issue-range and crossover-order writes stay bounded and owner-checked over
/// HTTP, matching the Python service validation.
#[tokio::test]
async fn reading_order_groups_issue_range_and_order_validation_over_http() {
    let (state, _db) = database().await;
    let (token, csrf, user_id) = register_and_login(&state, "rog-range").await;

    let (status, created) = authed_json(
        &state,
        "POST",
        "/api/v1/reading-order-groups/",
        &token,
        &csrf,
        Some(json!({"name": "Range group"})),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let group_id = created["id"].as_i64().expect("group id");
    let (thread_id, issue_ids) =
        seed_thread_with_issues(&state, user_id, "Range Series", &["1", "2", "3"]).await;

    // Adding an issue range reports added vs already-present ids.
    let (status, range) = authed_json(
        &state,
        "POST",
        &format!("/api/v1/reading-order-groups/{group_id}/issue-ranges"),
        &token,
        &csrf,
        Some(json!({"thread_id": thread_id, "start_position": 1, "end_position": 2})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{range}");
    assert_eq!(range["added_issue_ids"].as_array().expect("added").len(), 2);
    let (status, again) = authed_json(
        &state,
        "POST",
        &format!("/api/v1/reading-order-groups/{group_id}/issue-ranges"),
        &token,
        &csrf,
        Some(json!({"thread_id": thread_id, "start_position": 1, "end_position": 2})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{again}");
    assert_eq!(again["added_issue_ids"], json!([]), "{again}");
    assert_eq!(
        again["already_present_issue_ids"]
            .as_array()
            .expect("present")
            .len(),
        2
    );

    // Inverted range -> 422 like the Python service.
    let (status, inverted) = authed_json(
        &state,
        "POST",
        &format!("/api/v1/reading-order-groups/{group_id}/issue-ranges"),
        &token,
        &csrf,
        Some(json!({"thread_id": thread_id, "start_position": 3, "end_position": 1})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{inverted}");

    // Order update assigns sequence positions to the range members.
    let items: Vec<Value> = issue_ids
        .iter()
        .take(2)
        .enumerate()
        .map(|(index, id)| json!({"issue_id": id, "sequence_order": index as i32 + 1}))
        .collect();
    let (status, ordered) = authed_json(
        &state,
        "PUT",
        &format!("/api/v1/reading-order-groups/{group_id}/order"),
        &token,
        &csrf,
        Some(json!({"items": items})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{ordered}");
    let sequences: Vec<i64> = ordered["memberships"]
        .as_array()
        .expect("memberships")
        .iter()
        .filter_map(|m| m["sequence_order"].as_i64())
        .collect();
    assert_eq!(sequences, vec![1, 2], "{ordered}");

    // Empty order is rejected.
    let (status, empty) = authed_json(
        &state,
        "PUT",
        &format!("/api/v1/reading-order-groups/{group_id}/order"),
        &token,
        &csrf,
        Some(json!({"items": []})),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{empty}");

    // Crossover plans endpoint is owner-scoped and returns a list.
    let (status, plans) = authed_json(
        &state,
        "GET",
        &format!("/api/v1/reading-order-groups/{group_id}/plans"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{plans}");
    assert!(plans.is_array(), "{plans}");
}
