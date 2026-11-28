#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Database-backed regression for issue #5265 (MQA-TAG-005): a Reading Plan's
//! tags must be inherited by every member issue, including the plan's sole
//! unread / next-unread issue. The plan page renders issue chips from the bulk
//! `GET /api/v2/tags/effective/threads/{thread_id}/issues` read, so both the
//! bulk and single-issue effective reads are asserted for read and unread
//! members alike.
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

static NEXT_IP: AtomicU16 = AtomicU16::new(60);

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

async fn authed(
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

/// Seed one owned thread whose issue #2 is the sole unread (next-unread)
/// issue, plus one owned plan containing all three issues.
async fn seed_plan_scenario(state: &Arc<AppState>, username: &str) -> (i32, String, String) {
    let (token, csrf) = register_and_login(state, username).await;
    let conn = db::checkout(state).await.expect("seed connection");
    let user_id: i32 = conn
        .query_one("SELECT id FROM users WHERE username = $1", &[&username])
        .await
        .expect("user row")
        .get(0);
    conn.execute(
        "INSERT INTO threads (id, title, format, issues_remaining, queue_position, status, user_id)
         VALUES (1, 'Superman', 'single', 1, 1, 'active', $1)",
        &[&user_id],
    )
    .await
    .expect("seed thread");
    for (id, number, status) in [("1", "1", "read"), ("2", "2", "unread"), ("3", "3", "read")] {
        conn.execute(
            "INSERT INTO issues (id, thread_id, issue_number, status, read_at, created_at, position)
             VALUES ($1, 1, $2, $3::varchar, CASE WHEN $3 = 'read' THEN NOW() ELSE NULL END, NOW(), $1)",
            &[&id.parse::<i32>().unwrap(), &number, &status],
        )
        .await
        .expect("seed issue");
    }
    conn.execute(
        "UPDATE threads SET next_unread_issue_id = 2 WHERE id = 1",
        &[],
    )
    .await
    .expect("point thread at its next unread issue");
    conn.execute(
        "INSERT INTO continuity_plans (id, user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
         VALUES (1, $1, 'QA Destructive A', 'informational', '[]'::json, '[]'::json, NOW(), NOW())",
        &[&user_id],
    )
    .await
    .expect("seed plan");
    for (occ, issue_id, position) in [("occ-1", 1, 0), ("occ-2", 2, 1), ("occ-3", 3, 2)] {
        conn.execute(
            "INSERT INTO reading_plan_issues (plan_id, occurrence_id, issue_id, lane_id, display_position, is_checkpoint)
             VALUES (1, $1, $2, 'main', $3, false)",
            &[&occ, &issue_id, &position],
        )
        .await
        .expect("seed plan membership");
    }
    drop(conn);
    (user_id, token, csrf)
}

async fn create_and_assign_plan_tag(
    state: &Arc<AppState>,
    token: &str,
    csrf: &str,
    name: &str,
) -> i32 {
    let (status, created) = authed(
        state,
        "POST",
        "/api/v2/tags",
        token,
        csrf,
        Some(json!({"name": name, "color": "red"})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{created}");
    let tag_id = created["tag"]["id"].as_i64().expect("tag id") as i32;
    for (target_type, target_id) in [("ContinuityPlan", 1), ("Thread", 1)] {
        let (status, assigned) = authed(
            state,
            "POST",
            &format!("/api/v2/tags/{tag_id}/assignments"),
            token,
            csrf,
            Some(json!({"target_type": target_type, "target_id": target_id})),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{assigned}");
    }
    tag_id
}

fn plan_source_present(issue_entry: &Value, tag_name: &str) -> bool {
    issue_entry["effective_tags"]
        .as_array()
        .map(|tags| {
            tags.iter().any(|entry| {
                entry["tag"]["name"] == tag_name
                    && entry["sources"]
                        .as_array()
                        .map(|sources| {
                            sources.iter().any(|source| {
                                source["target_type"] == "ContinuityPlan"
                                    && source["target_id"] == 1
                            })
                        })
                        .unwrap_or(false)
            })
        })
        .unwrap_or(false)
}

/// Seed the production shape for a list-linked plan (issue #5265): the v2
/// plan reader renders steps from the plan's linked authoritative Reading
/// List, while `reading_plan_issues` is only a retained snapshot that relink
/// never rewrites. Issue #2 (the sole unread / next-unread issue) is present
/// in the authoritative list but absent from the stale membership snapshot.
async fn seed_list_linked_plan_scenario(
    state: &Arc<AppState>,
    username: &str,
) -> (i32, String, String) {
    let (user_id, token, csrf) = seed_plan_scenario(state, username).await;
    let conn = db::checkout(state).await.expect("seed list connection");
    // The stale retained membership keeps only the read issues.
    conn.execute(
        "DELETE FROM reading_plan_issues WHERE plan_id = 1 AND issue_id = 2",
        &[],
    )
    .await
    .expect("stale membership snapshot");
    conn.execute(
        "INSERT INTO custom_cbl_lists (id, user_id, name, mode, created_at, updated_at)
         VALUES (1, $1, 'QA Destructive A list', 'strict', NOW(), NOW())",
        &[&user_id],
    )
    .await
    .expect("seed linked list");
    for (entry_id, issue_id, position) in [(1, 1, 0), (2, 2, 1), (3, 3, 2)] {
        conn.execute(
            "INSERT INTO custom_cbl_entries (id, list_id, issue_id, position, created_at, is_checkpoint)
             VALUES ($1, 1, $2, $3, NOW(), false)",
            &[&entry_id, &issue_id, &position],
        )
        .await
        .expect("seed list entry");
    }
    conn.execute(
        "INSERT INTO reading_plan_sources (plan_id, raw_source_path, custom_cbl_list_id, recorded_at)
         VALUES (1, 'custom-cbl:1', 1, NOW())",
        &[],
    )
    .await
    .expect("link authoritative list to plan");
    drop(conn);
    (user_id, token, csrf)
}

#[tokio::test]
async fn bulk_thread_issues_read_inherits_plan_tags_for_unread_next_issue() {
    let (state, _guard) = database().await;
    let (_user_id, token, csrf) = seed_plan_scenario(&state, "tag-plan-bulk").await;
    create_and_assign_plan_tag(&state, &token, &csrf, "QA B5 PlanTag").await;

    let (status, body) = authed(
        &state,
        "GET",
        "/api/v2/tags/effective/threads/1/issues",
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let issues = body["issues"].as_array().expect("issues array");
    assert_eq!(issues.len(), 3, "{body}");
    for entry in issues {
        let target_id = entry["target_id"].as_i64().expect("target id");
        assert!(
            plan_source_present(entry, "QA B5 PlanTag"),
            "issue {target_id} (status read/unread) must inherit the plan tag with the plan source: {entry}"
        );
    }
}

#[tokio::test]
async fn single_issue_read_inherits_plan_tags_for_unread_next_issue() {
    let (state, _guard) = database().await;
    let (_user_id, token, csrf) = seed_plan_scenario(&state, "tag-plan-single").await;
    create_and_assign_plan_tag(&state, &token, &csrf, "QA Rust Watch").await;

    // Issue 2 is the thread's sole unread / next-unread issue.
    let (status, body) = authed(
        &state,
        "GET",
        "/api/v2/tags/effective/issues/2",
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert!(
        plan_source_present(&body, "QA Rust Watch"),
        "the plan's next-unread issue must inherit the plan tag with the plan source: {body}"
    );
}

#[tokio::test]
async fn bulk_read_inherits_plan_tags_from_linked_authoritative_list_for_unread_issue() {
    let (state, _guard) = database().await;
    let (_user_id, token, csrf) = seed_list_linked_plan_scenario(&state, "tag-list-bulk").await;
    create_and_assign_plan_tag(&state, &token, &csrf, "QA B5 PlanTag").await;

    let (status, body) = authed(
        &state,
        "GET",
        "/api/v2/tags/effective/threads/1/issues",
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let issues = body["issues"].as_array().expect("issues array");
    assert_eq!(issues.len(), 3, "{body}");
    for entry in issues {
        let target_id = entry["target_id"].as_i64().expect("target id");
        assert!(
            plan_source_present(entry, "QA B5 PlanTag"),
            "issue {target_id} shown in the plan via the authoritative Reading List must inherit the plan tag: {entry}"
        );
    }
}

#[tokio::test]
async fn single_read_inherits_plan_tags_from_linked_authoritative_list_for_unread_issue() {
    let (state, _guard) = database().await;
    let (_user_id, token, csrf) = seed_list_linked_plan_scenario(&state, "tag-list-single").await;
    create_and_assign_plan_tag(&state, &token, &csrf, "QA Rust Watch").await;

    // Issue 2 is the thread's sole unread / next-unread issue and is a member
    // of the plan's authoritative Reading List even though the retained
    // reading_plan_issues snapshot lacks it.
    let (status, body) = authed(
        &state,
        "GET",
        "/api/v2/tags/effective/issues/2",
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert!(
        plan_source_present(&body, "QA Rust Watch"),
        "the plan's next-unread issue must inherit the plan tag via the linked authoritative list: {body}"
    );
}

#[tokio::test]
async fn foreign_plan_and_linked_list_never_leak_as_inheritance_source() {
    let (state, _guard) = database().await;
    let (_user_id, token, csrf) = seed_list_linked_plan_scenario(&state, "tag-list-owner").await;
    let tag_id = create_and_assign_plan_tag(&state, &token, &csrf, "QA B5 PlanTag").await;

    // Case A (plan-ownership filter): a foreign plan linked to a foreign list
    // whose entries reference the *requested* issues (1, 2, 3), carrying a
    // viewer-visible private tag. Without `cp.user_id = viewer` these would
    // surface as ContinuityPlan sources.
    register_and_login(&state, "tag-list-foreign").await;
    let conn = db::checkout(&state).await.expect("foreign seed connection");
    let foreign_user_id: i32 = conn
        .query_one(
            "SELECT id FROM users WHERE username = 'tag-list-foreign'",
            &[],
        )
        .await
        .expect("foreign user row")
        .get(0);
    let viewer_id: i32 = conn
        .query_one(
            "SELECT id FROM users WHERE username = 'tag-list-owner'",
            &[],
        )
        .await
        .expect("viewer user row")
        .get(0);
    conn.execute(
        "INSERT INTO continuity_plans (id, user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
         VALUES (2, $1, 'Foreign plan', 'informational', '[]'::json, '[]'::json, NOW(), NOW())",
        &[&foreign_user_id],
    )
    .await
    .expect("foreign plan");
    conn.execute(
        "INSERT INTO custom_cbl_lists (id, user_id, name, mode, created_at, updated_at)
         VALUES (2, $1, 'Foreign list', 'loose', NOW(), NOW())",
        &[&foreign_user_id],
    )
    .await
    .expect("foreign list");
    for (entry_id, issue_id) in [(21, 1), (22, 2), (23, 3)] {
        conn.execute(
            "INSERT INTO custom_cbl_entries (id, list_id, issue_id, position, created_at, is_checkpoint)
             VALUES ($1, 2, $2, $1, NOW(), false)",
            &[&entry_id, &issue_id],
        )
        .await
        .expect("foreign list entry referencing a requested issue");
    }
    conn.execute(
        "INSERT INTO reading_plan_sources (plan_id, raw_source_path, custom_cbl_list_id, recorded_at)
         VALUES (2, 'custom-cbl:2', 2, NOW())",
        &[],
    )
    .await
    .expect("foreign link");
    // Viewer-visible private tag sitting on the foreign plan (seeded directly;
    // the API would refuse it, the SQL ownership filter is what must hold).
    conn.execute(
        "INSERT INTO tags (id, name, normalized_name, scope, owner_user_id, color, created_at, updated_at)
         VALUES (90, 'Viewer Visible', 'viewer visible', 'private', $1, '#123456', NOW(), NOW())",
        &[&viewer_id],
    )
    .await
    .expect("viewer-visible tag on foreign plan");
    conn.execute(
        "INSERT INTO tag_assignments (tag_id, target_type, target_id, created_at)
         VALUES (90, 'ContinuityPlan', 2, NOW())",
        &[],
    )
    .await
    .expect("assignment on foreign plan");
    // Case B (list-ownership filter): the viewer's own plan 3 has no
    // reading_plan_issues rows at all and is linked to the *foreign* list 2,
    // which references issue 2. Without `l.user_id = cp.user_id` issue 2 would
    // inherit plan 3's tag through the foreign list.
    conn.execute(
        "INSERT INTO continuity_plans (id, user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
         VALUES (3, $1, 'Viewer plan linked to a foreign list', 'informational', '[]'::json, '[]'::json, NOW(), NOW())",
        &[&viewer_id],
    )
    .await
    .expect("viewer plan 3");
    conn.execute(
        "INSERT INTO reading_plan_sources (plan_id, raw_source_path, custom_cbl_list_id, recorded_at)
         VALUES (3, 'custom-cbl:2', 2, NOW())",
        &[],
    )
    .await
    .expect("viewer plan linked to foreign list");
    drop(conn);
    let (status, assigned) = authed(
        &state,
        "POST",
        &format!("/api/v2/tags/{tag_id}/assignments"),
        &token,
        &csrf,
        Some(json!({"target_type": "ContinuityPlan", "target_id": 3})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{assigned}");

    let (status, body) = authed(
        &state,
        "GET",
        "/api/v2/tags/effective/threads/1/issues",
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    for entry in body["issues"].as_array().expect("issues array") {
        let names: Vec<&str> = entry["effective_tags"]
            .as_array()
            .map(|tags| {
                tags.iter()
                    .filter_map(|t| t["tag"]["name"].as_str())
                    .collect()
            })
            .unwrap_or_default();
        assert!(
            !names.contains(&"Viewer Visible"),
            "viewer-visible tag on a foreign plan leaked into effective tags: {entry}"
        );
        for tag in entry["effective_tags"].as_array().expect("effective tags") {
            for source in tag["sources"].as_array().expect("sources") {
                assert!(
                    !(source["target_type"] == "ContinuityPlan"
                        && (source["target_id"] == 2 || source["target_id"] == 3)),
                    "plan membership leaked through a foreign plan or foreign list: {entry}"
                );
            }
        }
    }
    // The viewer's own plan 1 must still contribute via its owned linked list.
    let issue_two = body["issues"]
        .as_array()
        .expect("issues array")
        .iter()
        .find(|entry| entry["target_id"] == 2)
        .expect("issue 2 entry");
    assert!(
        plan_source_present(issue_two, "QA B5 PlanTag"),
        "owned plan 1 must still be a source for issue 2: {issue_two}"
    );
}

#[tokio::test]
async fn bulk_unassign_keeps_list_member_in_still_inherited_ids() {
    let (state, _guard) = database().await;
    let (_user_id, token, csrf) = seed_list_linked_plan_scenario(&state, "tag-unassign-list").await;
    let tag_id = create_and_assign_plan_tag(&state, &token, &csrf, "QA B5 PlanTag").await;
    // Direct assignment on the unread issue only; no Thread assignment, so no
    // thread source can mask a missing plan source.
    let (status, assigned) = authed(
        &state,
        "POST",
        &format!("/api/v2/tags/{tag_id}/assignments"),
        &token,
        &csrf,
        Some(json!({"target_type": "Issue", "target_id": 2})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{assigned}");

    let (status, body) = authed(
        &state,
        "POST",
        &format!("/api/v2/tags/{tag_id}/unassignment-batches"),
        &token,
        &csrf,
        Some(json!({"target_type": "Issue", "target_ids": [2]})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(
        body["affected_ids"],
        json!([2]),
        "direct assignment removed: {body}"
    );
    assert!(
        body["still_inherited_ids"]
            .as_array()
            .map(|ids| ids.contains(&json!(2)))
            .unwrap_or(false),
        "issue 2 belongs to the plan via the linked authoritative list, so it must stay in still_inherited_ids: {body}"
    );
    let remaining: i64 = state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "SELECT COUNT(*)::bigint FROM tag_assignments WHERE tag_id = $1 AND target_type = 'Issue' AND target_id = 2",
            &[&tag_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(remaining, 0, "the direct Issue assignment must be deleted");
}
