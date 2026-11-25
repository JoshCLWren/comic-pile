#![allow(clippy::unwrap_used, clippy::expect_used)]

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
                "RUST_ROLL_JWT_SECRET" => Some("synthetic-roll-routes-secret".into()),
                "RUST_ROLL_POOL_SIZE" => Some("2".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    );
    let guard = comicpile_roll_service::test_support::reset_for_test(&state).await;
    let username = format!("{prefix}-{}-{}", std::process::id(), unique_suffix());
    let (token, csrf, user_id) = register_user(&state, &username).await;
    (state, token, csrf, user_id, guard)
}

async fn register_user(state: &Arc<AppState>, username: &str) -> (String, String, i32) {
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/auth/register")
                .header("x-forwarded-for", format!("2001:db8::{:x}", NEXT_TEST_CLIENT.fetch_add(1, Ordering::Relaxed)))
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(json!({"username": username, "email": format!("{username}@example.com"), "password": "correct-horse-battery"}).to_string()))
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
    (token, csrf, user_id)
}

fn authed(method: &str, uri: &str, token: &str, csrf: &str, body: Value) -> Request<Body> {
    Request::builder()
        .method(method)
        .uri(uri)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header(header::COOKIE, format!("csrf_token={csrf}"))
        .header("x-csrf-token", csrf)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(body.to_string()))
        .unwrap()
}

async fn seed_thread(state: &Arc<AppState>, user_id: i32, title: &str) -> i32 {
    state.pool.get().await.unwrap()
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, manual_creator_credits, is_test, is_blocked, queue_position_is_manual, created_at)
             VALUES ($1,$2,'Comic',0,1,'active','[]'::json,false,false,false,NOW()) RETURNING id",
            &[&user_id, &title],
        ).await.unwrap().get(0)
}

async fn seed_issue(state: &Arc<AppState>, thread_id: i32, number: &str, position: i32) -> i32 {
    state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, status, position, created_at)
             VALUES ($1,$2,'unread',$3,NOW()) RETURNING id",
            &[&thread_id, &number, &position],
        )
        .await
        .unwrap()
        .get(0)
}

async fn seed_strict_list(
    state: &Arc<AppState>,
    user_id: i32,
    name: &str,
    issue_ids: &[i32],
) -> i32 {
    let list_id: i32 = state.pool.get().await.unwrap()
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, description, created_at, updated_at, mode, overlap_decisions_updated_at)
             VALUES ($1,$2,'',NOW(),NOW(),'strict',NOW()) RETURNING id",
            &[&user_id, &name],
        ).await.unwrap().get(0);
    for (idx, issue_id) in issue_ids.iter().enumerate() {
        state.pool.get().await.unwrap().execute(
            "INSERT INTO custom_cbl_entries (list_id, issue_id, position, created_at, is_checkpoint, checkpoint_target_issue_ids, gate, skipped)
             VALUES ($1,$2,$3,NOW(),false,'[]'::json,'none',false)",
            &[&list_id, &issue_id, &(idx as i32 + 1)],
        ).await.unwrap();
    }
    list_id
}

#[tokio::test]
async fn create_preserves_non_monotonic_order_and_preview_reports_resort_cycle() {
    let (state, token, csrf, user_id, _guard) = setup_user("bprd-4654").await;
    let thread_id = seed_thread(&state, user_id, "B.P.R.D.: Hell on Earth").await;

    // Original Julix-saved order: #129, #140-142, #130-139, #143
    let mut ids = vec![];
    for (pos, num) in [
        "129", "140", "141", "142", "130", "131", "132", "133", "134", "135", "136", "137", "138",
        "139", "143",
    ]
    .iter()
    .enumerate()
    {
        ids.push(seed_issue(&state, thread_id, num, pos as i32 + 1).await);
    }
    // Strict list enforces the Julix order, so numeric resort would cycle.
    seed_strict_list(&state, user_id, "B.P.R.D. Hell on Earth Julix", &ids).await;

    // Preview add 101-102
    let preview_resp = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues/preview"),
            &token,
            &csrf,
            json!({"issue_range":"101-102"}),
        ))
        .await
        .unwrap();
    let status = preview_resp.status();
    let bytes = to_bytes(preview_resp.into_body(), 256 * 1024)
        .await
        .unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    assert_eq!(status, StatusCode::OK, "{body}");

    let default_after: Vec<String> = body["default_outcome"]["after"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v["issue_number"].as_str().unwrap().to_string())
        .collect();
    let original_order = vec![
        "129", "140", "141", "142", "130", "131", "132", "133", "134", "135", "136", "137", "138",
        "139", "143",
    ];
    // Default preserves relative order of existing issues.
    let existing_in_after: Vec<String> = default_after
        .iter()
        .filter(|n| !["101", "102"].contains(&n.as_str()))
        .cloned()
        .collect();
    assert_eq!(existing_in_after, original_order);
    assert!(body["default_outcome"]["preserves_existing_relative_order"]
        .as_bool()
        .unwrap());

    // Numeric resort should report a cycle.
    let resort = &body["numeric_resort_outcome"];
    assert!(!resort.is_null(), "resort outcome should be present");
    assert!(!resort["can_commit"].as_bool().unwrap());
    let cycles = resort["graph"]["cycles"].as_array().unwrap();
    assert!(
        !cycles.is_empty(),
        "expected cycle in numeric resort preview"
    );

    // Create with default safe behavior
    let create_resp = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues"),
            &token,
            &csrf,
            json!({"issue_range":"101-102"}),
        ))
        .await
        .unwrap();
    assert_eq!(create_resp.status(), StatusCode::CREATED);

    // Verify persisted order directly from DB.
    let rows = state
        .pool
        .get()
        .await
        .unwrap()
        .query(
            "SELECT issue_number FROM issues WHERE thread_id=$1 ORDER BY position, id",
            &[&thread_id],
        )
        .await
        .unwrap();
    let got: Vec<String> = rows.iter().map(|r| r.get(0)).collect();
    let mut expected = original_order
        .iter()
        .map(|s| s.to_string())
        .collect::<Vec<_>>();
    expected.push("101".into());
    expected.push("102".into());
    assert_eq!(got, expected);
}

async fn issue_order(state: &Arc<AppState>, thread_id: i32) -> Vec<String> {
    state
        .pool
        .get()
        .await
        .unwrap()
        .query(
            "SELECT issue_number FROM issues WHERE thread_id=$1 ORDER BY position, id",
            &[&thread_id],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| row.get::<_, String>(0))
        .collect()
}

async fn events_count(state: &Arc<AppState>, thread_id: i32) -> i64 {
    state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "SELECT count(*) FROM events WHERE thread_id=$1 AND type='issues_created'",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get::<_, i64>(0)
}

#[tokio::test]
async fn explicit_numeric_resort_commit_reorders_existing_numbers() {
    let (state, token, csrf, user_id, _guard) = setup_user("bprd-4654-resort").await;
    let thread_id = seed_thread(&state, user_id, "Resort series").await;
    for (pos, num) in ["129", "140", "130"].iter().enumerate() {
        seed_issue(&state, thread_id, num, pos as i32 + 1).await;
    }

    let preview = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues/preview"),
            &token,
            &csrf,
            json!({"issue_range": "101"}),
        ))
        .await
        .unwrap();
    assert_eq!(preview.status(), StatusCode::OK);
    let bytes = to_bytes(preview.into_body(), 256 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap();
    assert!(
        body["numeric_resort_outcome"]["can_commit"]
            .as_bool()
            .unwrap(),
        "numeric resort should be committable without a strict-list constraint: {body}"
    );

    let created = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues"),
            &token,
            &csrf,
            json!({"issue_range": "101", "strategy": "numeric_resort"}),
        ))
        .await
        .unwrap();
    assert_eq!(created.status(), StatusCode::CREATED);
    assert_eq!(
        issue_order(&state, thread_id).await,
        vec!["101", "129", "130", "140"]
    );
}

#[tokio::test]
async fn preview_cancel_leaves_thread_unchanged() {
    let (state, token, csrf, user_id, _guard) = setup_user("bprd-4654-cancel").await;
    let thread_id = seed_thread(&state, user_id, "Cancel series").await;
    for (pos, num) in ["129", "140", "130"].iter().enumerate() {
        seed_issue(&state, thread_id, num, pos as i32 + 1).await;
    }
    let before = issue_order(&state, thread_id).await;
    let events_before = events_count(&state, thread_id).await;

    // A preview alone is a cancel: the reader closes without confirming.
    let preview = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues/preview"),
            &token,
            &csrf,
            json!({"issue_range": "101-102"}),
        ))
        .await
        .unwrap();
    assert_eq!(preview.status(), StatusCode::OK);

    assert_eq!(issue_order(&state, thread_id).await, before);
    assert_eq!(events_count(&state, thread_id).await, events_before);
}

#[tokio::test]
async fn foreign_reader_cannot_preview_or_create_thread() {
    let (state, token, csrf, user_id, _guard) = setup_user("bprd-4654-owner").await;
    let thread_id = seed_thread(&state, user_id, "Private series").await;
    seed_issue(&state, thread_id, "1", 1).await;
    let (foreign_token, foreign_csrf, _) = register_user(
        &state,
        &format!("foreign-{}-{}", std::process::id(), unique_suffix()),
    )
    .await;

    let preview = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues/preview"),
            &foreign_token,
            &foreign_csrf,
            json!({"issue_range": "2"}),
        ))
        .await
        .unwrap();
    assert_eq!(preview.status(), StatusCode::NOT_FOUND);

    let create = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues"),
            &foreign_token,
            &foreign_csrf,
            json!({"issue_range": "2"}),
        ))
        .await
        .unwrap();
    assert_eq!(create.status(), StatusCode::NOT_FOUND);
    assert_eq!(issue_order(&state, thread_id).await, vec!["1"]);

    // The owner still sees the unchanged thread.
    let _ = (token, csrf);
}

#[tokio::test]
async fn failed_resort_commit_then_safe_retry_preserves_state() {
    let (state, token, csrf, user_id, _guard) = setup_user("bprd-4654-retry").await;
    let thread_id = seed_thread(&state, user_id, "Retry series").await;
    let ids = vec![
        seed_issue(&state, thread_id, "129", 1).await,
        seed_issue(&state, thread_id, "140", 2).await,
        seed_issue(&state, thread_id, "130", 3).await,
    ];
    seed_strict_list(&state, user_id, "Authored order", &ids).await;
    let before = issue_order(&state, thread_id).await;
    let events_before = events_count(&state, thread_id).await;

    let failed = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues"),
            &token,
            &csrf,
            json!({"issue_range": "101", "strategy": "numeric_resort"}),
        ))
        .await
        .unwrap();
    assert!(
        !failed.status().is_success(),
        "resort against a strict authored order must be rejected atomically"
    );
    assert_eq!(issue_order(&state, thread_id).await, before);
    assert_eq!(events_count(&state, thread_id).await, events_before);

    // Retry with the safe default; order survives and the new issue is appended.
    let retried = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues"),
            &token,
            &csrf,
            json!({"issue_range": "101", "strategy": "safe_default"}),
        ))
        .await
        .unwrap();
    assert_eq!(retried.status(), StatusCode::CREATED);
    assert_eq!(
        issue_order(&state, thread_id).await,
        vec!["129", "140", "130", "101"]
    );
}

#[tokio::test]
async fn concurrent_sibling_previews_do_not_corrupt_thread_state() {
    let (state, token, csrf, user_id, _guard) = setup_user("bprd-4654-concurrent").await;
    let thread_id = seed_thread(&state, user_id, "Concurrent series").await;
    for (pos, num) in ["129", "140", "130"].iter().enumerate() {
        seed_issue(&state, thread_id, num, pos as i32 + 1).await;
    }
    let before = issue_order(&state, thread_id).await;

    let (first, second) = tokio::join!(
        async {
            router(state.clone())
                .oneshot(authed(
                    "POST",
                    &format!("/api/v2/threads/{thread_id}/issues/preview"),
                    &token,
                    &csrf,
                    json!({"issue_range": "101"}),
                ))
                .await
                .unwrap()
        },
        async {
            router(state.clone())
                .oneshot(authed(
                    "POST",
                    &format!("/api/v2/threads/{thread_id}/issues/preview"),
                    &token,
                    &csrf,
                    json!({"issue_range": "102"}),
                ))
                .await
                .unwrap()
        },
    );
    assert_eq!(first.status(), StatusCode::OK);
    assert_eq!(second.status(), StatusCode::OK);
    assert_eq!(issue_order(&state, thread_id).await, before);
}

#[tokio::test]
async fn preview_surfaces_alias_offer_for_mapped_existing_issue() {
    let (state, token, csrf, user_id, _guard) = setup_user("alias-4654").await;
    let thread_id = seed_thread(&state, user_id, "Alias Series").await;
    let issue_id = seed_issue(&state, thread_id, "5", 1).await;
    // Mark the existing issue as mapped so identity evidence supports alias/mapping.
    state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE issues SET catalog_issue_id = 9001 WHERE id = $1",
            &[&issue_id],
        )
        .await
        .unwrap();

    let preview_resp = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues/preview"),
            &token,
            &csrf,
            json!({"issue_range":"5,6"}),
        ))
        .await
        .unwrap();
    let status = preview_resp.status();
    let bytes = to_bytes(preview_resp.into_body(), 256 * 1024)
        .await
        .unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    assert_eq!(status, StatusCode::OK, "{body}");

    let offers = body["alias_offers"].as_array().expect("alias_offers array");
    assert_eq!(offers.len(), 1, "{body}");
    assert_eq!(offers[0]["requested_issue_number"], "5");
    assert_eq!(offers[0]["existing_issue_id"], issue_id);
    assert_eq!(offers[0]["is_mapped"], true);

    // Unaccepted mapped-existing issue blocks commit.
    assert_eq!(body["default_outcome"]["can_commit"], false);
    let msg = body["default_outcome"]["conflict_message"]
        .as_str()
        .unwrap_or("");
    assert!(msg.contains("#5"), "{msg}");

    // Reader explicitly accepts the alias/mapping choice; preview becomes committable.
    let accepted_resp = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues/preview"),
            &token,
            &csrf,
            json!({"issue_range":"5,6", "accepted_alias_issue_numbers":["5"]}),
        ))
        .await
        .unwrap();
    let accepted_status = accepted_resp.status();
    let accepted_bytes = to_bytes(accepted_resp.into_body(), 256 * 1024)
        .await
        .unwrap();
    let accepted: Value = serde_json::from_slice(&accepted_bytes).unwrap_or(Value::Null);
    assert_eq!(accepted_status, StatusCode::OK, "{accepted}");
    assert_eq!(
        accepted["default_outcome"]["can_commit"], true,
        "{accepted}"
    );

    // Create rejects unaccepted mapped-existing alias.
    let reject_resp = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues"),
            &token,
            &csrf,
            json!({"issue_range":"5,6"}),
        ))
        .await
        .unwrap();
    assert_eq!(reject_resp.status(), StatusCode::BAD_REQUEST);

    // Create succeeds when alias is explicitly accepted.
    let create_resp = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues"),
            &token,
            &csrf,
            json!({"issue_range":"5,6", "accepted_alias_issue_numbers":["5"]}),
        ))
        .await
        .unwrap();
    let create_status = create_resp.status();
    let create_bytes = to_bytes(create_resp.into_body(), 256 * 1024).await.unwrap();
    let create_body: Value = serde_json::from_slice(&create_bytes).unwrap_or(Value::Null);
    assert_eq!(create_status, StatusCode::CREATED, "{create_body}");
    assert_eq!(issue_order(&state, thread_id).await, vec!["5", "6"]);
}
