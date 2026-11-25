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

async fn persisted_order(state: &Arc<AppState>, thread_id: i32) -> Vec<String> {
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

#[tokio::test]
async fn explicit_numeric_resort_commit_reorders_existing_issues() {
    let (state, token, csrf, user_id, _guard) = setup_user("bprd-4654-resort").await;
    let thread_id = seed_thread(&state, user_id, "Nonmonotonic series").await;
    for (pos, num) in ["129", "140", "142", "130"].iter().enumerate() {
        seed_issue(&state, thread_id, num, pos as i32 + 1).await;
    }

    // Safe default would keep the reader-authored order and append the new
    // numbers, so an explicit resort is the only path that re-seats them.
    let preview = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues/preview"),
            &token,
            &csrf,
            json!({"issue_range": "101", "strategy": "numeric_resort"}),
        ))
        .await
        .unwrap();
    assert_eq!(preview.status(), StatusCode::OK);
    let bytes = to_bytes(preview.into_body(), 256 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(body["requested_strategy"], "numeric_resort");
    assert!(!body["numeric_resort_outcome"].is_null());
    let resort_after: Vec<String> = body["numeric_resort_outcome"]["after"]
        .as_array()
        .unwrap()
        .iter()
        .map(|item| item["issue_number"].as_str().unwrap().to_string())
        .collect();
    assert_eq!(resort_after, vec!["101", "129", "130", "140", "142"]);

    let create = router(state.clone())
        .oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues"),
            &token,
            &csrf,
            json!({"issue_range": "101", "strategy": "numeric_resort"}),
        ))
        .await
        .unwrap();
    assert_eq!(create.status(), StatusCode::CREATED);
    assert_eq!(
        persisted_order(&state, thread_id).await,
        vec!["101", "129", "130", "140", "142"]
    );
}

#[tokio::test]
async fn preview_cancellation_leaves_the_thread_untouched() {
    let (state, token, csrf, user_id, _guard) = setup_user("bprd-4654-cancel").await;
    let thread_id = seed_thread(&state, user_id, "Cancel preview").await;
    for (pos, num) in ["129", "140", "142", "130"].iter().enumerate() {
        seed_issue(&state, thread_id, num, pos as i32 + 1).await;
    }
    let before = persisted_order(&state, thread_id).await;

    // The preview handler must commit nothing: the savepoints are rolled back
    // and the surrounding transaction is rolled back on return.
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
    assert_eq!(persisted_order(&state, thread_id).await, before);
}

#[tokio::test]
async fn concurrent_creates_apply_once_and_retry_is_idempotent() {
    let (state, token, csrf, user_id, _guard) = setup_user("bprd-4654-concurrent").await;
    let thread_id = seed_thread(&state, user_id, "Concurrent writers").await;
    for (pos, num) in ["1", "2"].iter().enumerate() {
        seed_issue(&state, thread_id, num, pos as i32 + 1).await;
    }

    let (first, second) = tokio::join!(
        router(state.clone()).oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues"),
            &token,
            &csrf,
            json!({"issue_range": "3-4"}),
        )),
        router(state.clone()).oneshot(authed(
            "POST",
            &format!("/api/v2/threads/{thread_id}/issues"),
            &token,
            &csrf,
            json!({"issue_range": "3-4"}),
        )),
    );
    let statuses = [first.unwrap().status(), second.unwrap().status()];
    assert_eq!(
        statuses
            .iter()
            .filter(|status| **status == StatusCode::CREATED)
            .count(),
        1
    );
    assert_eq!(
        statuses
            .iter()
            .filter(|status| **status == StatusCode::BAD_REQUEST)
            .count(),
        1,
        "the losing sibling write must be a retryable duplicate, not a 500"
    );
    assert_eq!(
        persisted_order(&state, thread_id).await,
        vec!["1", "2", "3", "4"]
    );
}

#[tokio::test]
async fn unrelated_reader_cannot_preview_or_create_another_readers_thread() {
    let (state, _token, _csrf, user_id, _guard) = setup_user("bprd-4654-owner").await;
    let thread_id = seed_thread(&state, user_id, "Private series").await;
    seed_issue(&state, thread_id, "1", 1).await;
    let (other_token, other_csrf, _) = register_user(
        &state,
        &format!("foreign-{}-{}", std::process::id(), unique_suffix()),
    )
    .await;

    for path in [
        format!("/api/v2/threads/{thread_id}/issues/preview"),
        format!("/api/v2/threads/{thread_id}/issues"),
    ] {
        let response = router(state.clone())
            .oneshot(authed(
                "POST",
                &path,
                &other_token,
                &other_csrf,
                json!({"issue_range": "2"}),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }
    assert_eq!(persisted_order(&state, thread_id).await, vec!["1"]);
}
