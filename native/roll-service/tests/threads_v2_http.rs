#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Handler-level HTTP regressions for the canonical Thread write resources
//! (#5703): `PATCH /api/v2/threads/{thread_id}` and
//! `DELETE /api/v2/threads/{thread_id}`.

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

static NEXT_TEST_CLIENT: AtomicUsize = AtomicUsize::new(1);

fn unique_suffix() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos()
}

struct Ctx {
    state: Arc<AppState>,
    token: String,
    csrf: String,
    user_id: i32,
    _guard: tokio::sync::MutexGuard<'static, ()>,
}

async fn setup(prefix: &str) -> Ctx {
    let url = test_support::database_url().await;
    let state = Arc::new(test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-thread-v2-secret".into()),
            _ => None,
        })
        .unwrap(),
    ));
    let guard = test_support::reset_for_test(&state).await;
    let username = format!("{prefix}-{}-{}", std::process::id(), unique_suffix());
    let (token, csrf, user_id) = register_user(&state, &username).await;
    Ctx {
        state,
        token,
        csrf,
        user_id,
        _guard: guard,
    }
}

async fn register_user(state: &Arc<AppState>, username: &str) -> (String, String, i32) {
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v2/auth/register")
                .header(
                    "x-forwarded-for",
                    format!(
                        "2001:db8::{:x}",
                        NEXT_TEST_CLIENT.fetch_add(1, Ordering::Relaxed)
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
        .unwrap_or_else(|| panic!("csrf cookie missing (status {status})"))
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

async fn send(state: &Arc<AppState>, request: Request<Body>) -> (StatusCode, Value) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 256 * 1024).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

fn authed(method: &str, uri: &str, token: &str, csrf: &str, body: Option<Value>) -> Request<Body> {
    let builder = Request::builder()
        .method(method)
        .uri(uri)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"));
    match body {
        Some(body) => builder
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(body.to_string()))
            .unwrap(),
        None => builder.body(Body::empty()).unwrap(),
    }
}

async fn call(ctx: &Ctx, method: &str, uri: &str, body: Option<Value>) -> (StatusCode, Value) {
    send(&ctx.state, authed(method, uri, &ctx.token, &ctx.csrf, body)).await
}

async fn seed_thread(ctx: &Ctx, user_id: i32, title: &str) -> i32 {
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position,
                                  status, notes, manual_creator_credits, is_test, is_blocked,
                                  queue_position_is_manual, created_at)
             VALUES ($1, $2, 'Comic', 3, $3, 'active', 'saved notes',
                     '[{\"name\":\"Jane Doe\",\"roles\":[\"Writer\"]}]'::json,
                     false, false, false, NOW())
             RETURNING id",
            &[&user_id, &title, &user_id],
        )
        .await
        .unwrap()
        .get(0)
}

async fn stored(ctx: &Ctx, thread_id: i32) -> Option<(String, String, Option<String>, Value)> {
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .query_opt(
            "SELECT title, format, notes, manual_creator_credits FROM threads WHERE id = $1",
            &[&thread_id],
        )
        .await
        .unwrap()
        .map(|row| (row.get(0), row.get(1), row.get(2), row.get(3)))
}

#[tokio::test]
async fn patch_preserves_omitted_fields_and_clears_explicit_null_notes() {
    let ctx = setup("v2patch").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Original").await;
    let uri = format!("/api/v2/threads/{thread}");

    let (status, body) = call(&ctx, "PATCH", &uri, Some(json!({"title": "Renamed"}))).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["title"], "Renamed");
    let (title, format, notes, credits) = stored(&ctx, thread).await.unwrap();
    assert_eq!(title, "Renamed");
    assert_eq!(format, "Comic");
    assert_eq!(notes.as_deref(), Some("saved notes"));
    assert_eq!(credits, json!([{"name": "Jane Doe", "roles": ["Writer"]}]));

    let (status, body) = call(&ctx, "PATCH", &uri, Some(json!({"notes": null}))).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let (title, _format, notes, credits) = stored(&ctx, thread).await.unwrap();
    assert_eq!(title, "Renamed");
    assert_eq!(notes, None);
    assert_eq!(credits, json!([{"name": "Jane Doe", "roles": ["Writer"]}]));
}

#[tokio::test]
async fn patch_owner_can_edit_creator_credits_and_mask_clears_them() {
    let ctx = setup("v2credits").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Credits").await;
    let uri = format!("/api/v2/threads/{thread}");

    let (status, body) = call(
        &ctx,
        "PATCH",
        &uri,
        Some(json!({
            "manual_creator_credits": [
                {"name": "  Alan   Moore ", "roles": ["Writer", "Writer"]}
            ]
        })),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body["manual_creator_credits"],
        json!([{"name": "Alan Moore", "roles": ["Writer"]}])
    );

    let (status, _body) = call(
        &ctx,
        "PATCH",
        &uri,
        Some(json!({"update_mask": ["manual_creator_credits"]})),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(stored(&ctx, thread).await.unwrap().3, json!([]));
}

#[tokio::test]
async fn patch_stale_expected_precondition_returns_409_and_writes_nothing() {
    let ctx = setup("v2stale").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Committed").await;
    let uri = format!("/api/v2/threads/{thread}");

    let (status, body) = call(
        &ctx,
        "PATCH",
        &uri,
        Some(json!({
            "title": "Should not land",
            "expected": {"title": "Stale title", "notes": "saved notes"}
        })),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body:?}");
    assert_eq!(body["detail"]["code"], "thread_edit_conflict");
    assert_eq!(body["detail"]["current"]["title"], "Committed");
    let (title, _, notes, _) = stored(&ctx, thread).await.unwrap();
    assert_eq!(title, "Committed");
    assert_eq!(notes.as_deref(), Some("saved notes"));
}

#[tokio::test]
async fn patch_and_delete_reject_cross_account_writes_with_404() {
    let ctx = setup("v2owner").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Owned").await;
    let (other_token, other_csrf, _other_user) = register_user(
        &ctx.state,
        &format!("v2other-{}-{}", std::process::id(), unique_suffix()),
    )
    .await;
    let uri = format!("/api/v2/threads/{thread}");

    let (status, body) = send(
        &ctx.state,
        authed(
            "PATCH",
            &uri,
            &other_token,
            &other_csrf,
            Some(json!({"title": "Nope"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
    let (status, body) = send(
        &ctx.state,
        authed("DELETE", &uri, &other_token, &other_csrf, None),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
    assert_eq!(body["detail"], format!("Thread {thread} not found"));
    assert!(stored(&ctx, thread).await.is_some());
}

#[tokio::test]
async fn delete_v2_removes_thread_and_subsequent_operations_return_404() {
    let ctx = setup("v2delete").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Delete me").await;
    let uri = format!("/api/v2/threads/{thread}");
    let conn = ctx.state.pool.get().await.unwrap();
    let event_id: i32 = conn
        .query_one(
            "INSERT INTO events (type, timestamp, user_id, thread_id)
             VALUES ('rate', NOW(), $1, $2) RETURNING id",
            &[&ctx.user_id, &thread],
        )
        .await
        .unwrap()
        .get(0);
    let session_id: i32 = conn
        .query_one(
            "INSERT INTO sessions (start_die, user_id) VALUES (6, $1) RETURNING id",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    let snapshot_id: i32 = conn
        .query_one(
            "INSERT INTO snapshots (session_id, event_id, thread_states, created_at)
             VALUES ($1, $2, '{}'::json, NOW()) RETURNING id",
            &[&session_id, &event_id],
        )
        .await
        .unwrap()
        .get(0);
    let order_id: i32 = conn
        .query_one(
            "INSERT INTO reading_orders (name, user_id) VALUES ('Delete fixture', $1) RETURNING id",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO reading_order_items (reading_order_id, thread_id, position)
         VALUES ($1, $2, 1)",
        &[&order_id, &thread],
    )
    .await
    .unwrap();
    let issue_id: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, status, created_at, position)
             VALUES ($1, '1', 'unread', NOW(), 1) RETURNING id",
            &[&thread],
        )
        .await
        .unwrap()
        .get(0);
    let reading_list_id: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, description, mode, created_at, updated_at, overlap_decisions_updated_at)
             VALUES ($1, 'Delete fixture list', NULL, 'loose', NOW(), NOW(), NOW()) RETURNING id",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    let reading_list_entry_id: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_entries (list_id, issue_id, position, created_at, is_checkpoint, checkpoint_target_issue_ids, gate, skipped)
             VALUES ($1, $2, 0, NOW(), false, '[]'::json, 'none', false) RETURNING id",
            &[&reading_list_id, &issue_id],
        )
        .await
        .unwrap()
        .get(0);
    drop(conn);

    let (status, body) = call(&ctx, "DELETE", &uri, None).await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");
    assert!(stored(&ctx, thread).await.is_none());

    let conn = ctx.state.pool.get().await.unwrap();
    let remaining = conn
        .query_one(
            "SELECT (SELECT count(*) FROM events WHERE id = $1),
                    (SELECT count(*) FROM snapshots WHERE id = $2),
                    (SELECT count(*) FROM reading_order_items WHERE thread_id = $3),
                    (SELECT count(*) FROM custom_cbl_entries WHERE id = $4)",
            &[&event_id, &snapshot_id, &thread, &reading_list_entry_id],
        )
        .await
        .unwrap();
    assert_eq!(remaining.get::<_, i64>(0), 0, "thread event removed");
    assert_eq!(remaining.get::<_, i64>(1), 0, "dependent snapshot removed");
    assert_eq!(remaining.get::<_, i64>(2), 0, "reading-order item removed");
    assert_eq!(
        remaining.get::<_, i64>(3),
        0,
        "reading-list membership removed"
    );
    drop(conn);

    let (status, body) = call(&ctx, "DELETE", &uri, None).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
    assert_eq!(body["detail"], format!("Thread {thread} not found"));
    let (status, body) = call(&ctx, "PATCH", &uri, Some(json!({"title": "No"}))).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
}

#[tokio::test]
async fn delete_v2_removes_thread_with_reading_list_membership_dependencies() {
    // #5950: a confirmed delete must also succeed when the thread's issues are
    // referenced by Reading List membership rows. Those entries carry an
    // `issue_id` FK (not a `thread_id` FK), so they are cleaned up only by the
    // cascading issue delete. Prove the whole chain resolves to 204 and leaves
    // no orphaned membership or removed list behind.
    let ctx = setup("v2deletelist").await;
    let thread = seed_thread(&ctx, ctx.user_id, "Listed series").await;
    let conn = ctx.state.pool.get().await.unwrap();
    let issue_id: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, status, position, created_at)
             VALUES ($1, '1', 'unread', 1, NOW()) RETURNING id",
            &[&thread],
        )
        .await
        .unwrap()
        .get(0);
    let list_id: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, created_at, updated_at)
             VALUES ($1, 'Delete fixture list', NOW(), NOW()) RETURNING id",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO custom_cbl_entries (list_id, issue_id, position, created_at)
         VALUES ($1, $2, 1, NOW())",
        &[&list_id, &issue_id],
    )
    .await
    .unwrap();
    drop(conn);

    let uri = format!("/api/v2/threads/{thread}");
    let (status, body) = call(&ctx, "DELETE", &uri, None).await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");

    let conn = ctx.state.pool.get().await.unwrap();
    let counts = conn
        .query_one(
            "SELECT (SELECT count(*) FROM threads WHERE id = $1),
                    (SELECT count(*) FROM issues WHERE thread_id = $1),
                    (SELECT count(*) FROM custom_cbl_entries WHERE issue_id = $2),
                    (SELECT count(*) FROM custom_cbl_lists WHERE id = $3)",
            &[&thread, &issue_id, &list_id],
        )
        .await
        .unwrap();
    assert_eq!(counts.get::<_, i64>(0), 0, "thread removed");
    assert_eq!(counts.get::<_, i64>(1), 0, "thread issues removed");
    assert_eq!(
        counts.get::<_, i64>(2),
        0,
        "reading-list membership removed"
    );
    assert_eq!(counts.get::<_, i64>(3), 1, "reading list itself retained");
    drop(conn);
}

/// Read-only Queue revisits must return the same ids, order and totals, and
/// every rendered row must be a member of the set the totals count (#3604).
///
/// Ties in `queue_position` are intentional here: the deterministic `id`
/// tie-breaker is what keeps repeated reads stable. The second half seeds an
/// invalid active row at position 0 to prove rows and totals cannot diverge.
#[tokio::test]
async fn repeated_queue_reads_are_stable_and_share_membership_with_totals() {
    let ctx = setup("v2queue-stability").await;
    let first = seed_thread(&ctx, ctx.user_id, "First").await;
    let second = seed_thread(&ctx, ctx.user_id, "Second").await;
    let uri = "/api/v2/threads?sort=position&page_size=50";

    let mut baseline: Option<(Vec<i64>, i64, i64)> = None;
    for _ in 0..3 {
        let (status, body) = call(&ctx, "GET", uri, None).await;
        assert_eq!(status, StatusCode::OK, "{body:?}");
        let ids = body["threads"]
            .as_array()
            .expect("threads array")
            .iter()
            .map(|row| row["id"].as_i64().expect("thread id"))
            .collect::<Vec<_>>();
        let snapshot = (
            ids,
            body["active_count"].as_i64().expect("active_count"),
            body["filtered_count"].as_i64().expect("filtered_count"),
        );
        match &baseline {
            None => baseline = Some(snapshot),
            Some(expected) => assert_eq!(
                &snapshot, expected,
                "read-only revisit changed Queue membership, order or totals"
            ),
        }
    }
    let baseline = baseline.expect("at least one read");
    assert_eq!(baseline.0, vec![first as i64, second as i64]);
    assert_eq!(baseline.1, 2);
    assert_eq!(baseline.2, 2);

    // Leave the row active but outside the queue: the list and both totals
    // must agree that it is not a member.
    let conn = ctx.state.pool.get().await.unwrap();
    let updated = conn
        .execute(
            "UPDATE threads SET queue_position = 0 WHERE id = $1",
            &[&second],
        )
        .await
        .unwrap();
    assert_eq!(updated, 1);
    drop(conn);

    let (status, body) = call(&ctx, "GET", uri, None).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let ids = body["threads"]
        .as_array()
        .expect("threads array")
        .iter()
        .map(|row| row["id"].as_i64().expect("thread id"))
        .collect::<Vec<_>>();
    assert_eq!(
        ids,
        vec![first as i64],
        "non-queued active row must not render"
    );
    assert_eq!(body["active_count"].as_i64(), Some(1));
    assert_eq!(body["filtered_count"].as_i64(), Some(1));
}
>>>>>>> origin/main
