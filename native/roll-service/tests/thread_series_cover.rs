#![allow(clippy::unwrap_used, clippy::expect_used)]
//! DB-backed regression for the derived series cover on `GET /api/v2/threads`.
//!
//! The series cover is the exact provider CDN URL of the thread's next unread
//! confirmed issue, falling back to the first confirmed issue that carries a
//! cover. Computed set‑based in one statement (no per‑row application query).
//! Every test drives the mounted router against the canonical disposable
//! PostgreSQL schema and hard-fails without `RUST_ROLL_TEST_DATABASE_URL`.

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
    let url = comicpile_roll_service::test_support::database_url().await;
    let state = Arc::new(test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-thread-series-cover-secret".into()),
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .unwrap(),
    ));
    let guard = comicpile_roll_service::test_support::reset_for_test(&state).await;
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
                .uri("/api/v1/auth/register")
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

fn authed(method: &str, path: &str, token: &str, csrf: &str) -> Request<Body> {
    Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"))
        .body(Body::empty())
        .unwrap()
}

async fn call(ctx: &Ctx, method: &str, path: &str) -> (StatusCode, Value) {
    let response = router(ctx.state.clone())
        .oneshot(authed(method, path, &ctx.token, &ctx.csrf))
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 256 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, body)
}

async fn call_json(ctx: &Ctx, method: &str, path: &str, json_body: Value) -> (StatusCode, Value) {
    let mut request = authed(method, path, &ctx.token, &ctx.csrf);
    request
        .headers_mut()
        .insert(header::CONTENT_TYPE, "application/json".parse().unwrap());
    *request.body_mut() = Body::from(json_body.to_string());
    let response = router(ctx.state.clone())
        .oneshot(request)
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 256 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, body)
}

async fn seed_thread(
    ctx: &Ctx,
    user_id: i32,
    title: &str,
    status: &str,
    queue_position: i32,
) -> i32 {
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position,
                                  status, manual_creator_credits, is_test, is_blocked,
                                  queue_position_is_manual, created_at)
             VALUES ($1, $2, 'Comic', 0, $3, $4, '[]'::json, false, false, false, NOW())
             RETURNING id",
            &[&user_id, &title, &queue_position, &status],
        )
        .await
        .unwrap()
        .get(0)
}

async fn seed_issue(ctx: &Ctx, thread_id: i32, number: &str, position: i32, status: &str) -> i32 {
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, status, position, created_at)
             VALUES ($1, $2, $3, $4, NOW()) RETURNING id",
            &[&thread_id, &number, &status, &position],
        )
        .await
        .unwrap()
        .get(0)
}

async fn set_frontier(ctx: &Ctx, thread_id: i32, next_unread_issue_id: Option<i32>) {
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE threads SET next_unread_issue_id = $2, reading_progress = 'in_progress'
             WHERE id = $1",
            &[&thread_id, &next_unread_issue_id],
        )
        .await
        .unwrap();
}

async fn seed_confirmed_cover(
    ctx: &Ctx,
    issue_id: i32,
    external_id: &str,
    cover_url: Option<&str>,
) {
    let metadata = match cover_url {
        Some(url) => json!({"image": {"original_url": url}}),
        None => json!({"issue_number": "1"}),
    };
    let identity: i32 = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, \
             created_at, updated_at) VALUES ('comicvine', 'issue', $1, $2, NOW(), NOW()) RETURNING id",
            &[&external_id, &metadata],
        )
        .await
        .unwrap()
        .get(0);
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, \
             created_at, updated_at, evidence_json) VALUES ($1, $2, 'confirmed', NOW(), NOW(), '{}'::json)",
            &[&issue_id, &identity],
        )
        .await
        .unwrap();
}

fn thread_cover(body: &Value, title: &str) -> Option<String> {
    let threads = body["threads"].as_array()?;
    threads
        .iter()
        .find(|thread| thread["title"] == title)
        .and_then(|thread| thread["series_cover_image_url"].as_str())
        .map(|s| s.to_owned())
}

/// Seed a confirmed ComicVine mapping with an arbitrary provider metadata
/// payload. Used by the thumb-only regression below (#5624).
async fn seed_confirmed_metadata(ctx: &Ctx, issue_id: i32, external_id: &str, metadata: Value) {
    let identity: i32 = ctx
        .state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, \
             created_at, updated_at) VALUES ('comicvine', 'issue', $1, $2, NOW(), NOW()) RETURNING id",
            &[&external_id, &metadata],
        )
        .await
        .unwrap()
        .get(0);
    ctx.state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, \
             created_at, updated_at, evidence_json) VALUES ($1, $2, 'confirmed', NOW(), NOW(), '{}'::json)",
            &[&issue_id, &identity],
        )
        .await
        .unwrap();
}

#[tokio::test]
async fn series_cover_uses_thumb_url_when_no_larger_image_exists() {
    // MQA-THREAD-004 / #5624: a mapped ComicVine issue whose provider entry
    // carries its only cover in `image.thumb_url` must show that cover on the
    // thread instead of "No cover".
    let ctx = setup("sc-thumb").await;
    let thread_id = seed_thread(&ctx, ctx.user_id, "Thumb Only", "active", 1).await;
    let issue = seed_issue(&ctx, thread_id, "5", 1, "unread").await;
    set_frontier(&ctx, thread_id, Some(issue)).await;
    seed_confirmed_metadata(
        &ctx,
        issue,
        "detective-comics-5",
        json!({"image": {"thumb_url": "https://cv.example/detective5-thumb.jpg"}}),
    )
    .await;

    let (status, body) = call(&ctx, "GET", "/api/v2/threads").await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        thread_cover(&body, "Thumb Only"),
        Some("https://cv.example/detective5-thumb.jpg".to_owned())
    );

    // The thread detail page renders per-issue covers from the issue-card
    // projection, which must expose the same thumb URL for the mapped issue.
    let (card_status, card_body) = call_json(
        &ctx,
        "POST",
        "/api/v2/issues/cards",
        json!({"issue_ids": [issue]}),
    )
    .await;
    assert_eq!(card_status, StatusCode::OK, "{card_body:?}");
    assert_eq!(
        card_body["items"][0]["cover_image_url"].as_str(),
        Some("https://cv.example/detective5-thumb.jpg"),
        "{card_body:?}"
    );
    assert_eq!(
        card_body["items"][0]["mapping_state"].as_str(),
        Some("confirmed"),
        "{card_body:?}"
    );
}

#[tokio::test]
async fn series_cover_prefers_next_unread_confirmed_issue() {
    let ctx = setup("sc-next").await;
    let thread_id = seed_thread(&ctx, ctx.user_id, "Next Wins", "active", 1).await;
    // An earlier-positioned covered issue that is already read must lose to the
    // later-positioned next unread issue, so the next-unread priority is what
    // the assertion exercises.
    let read_covered = seed_issue(&ctx, thread_id, "1", 1, "read").await;
    let next_issue = seed_issue(&ctx, thread_id, "2", 2, "unread").await;
    set_frontier(&ctx, thread_id, Some(next_issue)).await;
    seed_confirmed_cover(
        &ctx,
        read_covered,
        "read-cover-id",
        Some("https://cv.example/read.jpg"),
    )
    .await;
    seed_confirmed_cover(
        &ctx,
        next_issue,
        "next-cover-id",
        Some("https://cv.example/next.jpg"),
    )
    .await;

    let (status, body) = call(&ctx, "GET", "/api/v2/threads").await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        thread_cover(&body, "Next Wins"),
        Some("https://cv.example/next.jpg".to_owned())
    );
}

#[tokio::test]
async fn series_cover_falls_back_to_first_confirmed_issue() {
    let ctx = setup("sc-fallback").await;
    let thread_id = seed_thread(&ctx, ctx.user_id, "Fallback Wins", "active", 1).await;
    let next_issue = seed_issue(&ctx, thread_id, "1", 1, "unread").await;
    let first_issue = seed_issue(&ctx, thread_id, "2", 2, "unread").await;
    let later_issue = seed_issue(&ctx, thread_id, "3", 3, "unread").await;
    set_frontier(&ctx, thread_id, Some(next_issue)).await;
    // Next unread has no cover image. Two covered issues are inserted out of
    // position order, so only the position ordering can pick the second one.
    seed_confirmed_cover(&ctx, next_issue, "next-no-cover-id", None).await;
    seed_confirmed_cover(
        &ctx,
        later_issue,
        "later-cover-id",
        Some("https://cv.example/later.jpg"),
    )
    .await;
    seed_confirmed_cover(
        &ctx,
        first_issue,
        "first-cover-id",
        Some("https://cv.example/first.jpg"),
    )
    .await;

    let (status, body) = call(&ctx, "GET", "/api/v2/threads").await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        thread_cover(&body, "Fallback Wins"),
        Some("https://cv.example/first.jpg".to_owned())
    );
}

#[tokio::test]
async fn series_cover_uses_the_issue_card_mapping_preference() {
    // Two confirmed ComicVine mappings on one issue, both carrying covers. The
    // issue card picks the higher-confidence mapping, so the series cover must
    // pick the same one even though it was inserted second.
    let ctx = setup("sc-confidence").await;
    let thread_id = seed_thread(&ctx, ctx.user_id, "Confidence Wins", "active", 1).await;
    let issue = seed_issue(&ctx, thread_id, "1", 1, "unread").await;
    set_frontier(&ctx, thread_id, Some(issue)).await;
    let client = ctx.state.pool.get().await.unwrap();
    // Two identities and two mappings land in one set-based statement each, so
    // the fixture does not issue SQL per row.
    let external_ids = vec![
        "low-confidence-id".to_owned(),
        "high-confidence-id".to_owned(),
    ];
    let metadata: Vec<String> = ["https://cv.example/low.jpg", "https://cv.example/high.jpg"]
        .iter()
        .map(|cover| json!({"image": {"original_url": cover}}).to_string())
        .collect();
    let identity_rows = client
        .query(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, \
             created_at, updated_at) \
             SELECT 'comicvine', 'issue', ext, meta::json, NOW(), NOW() \
             FROM unnest($1::text[], $2::text[]) AS t(ext, meta) \
             ORDER BY ext \
             RETURNING id, external_id",
            &[&external_ids, &metadata],
        )
        .await
        .unwrap();
    let identity_by_external: std::collections::HashMap<String, i32> = identity_rows
        .iter()
        .map(|row| (row.get::<_, String>(1), row.get::<_, i32>(0)))
        .collect();
    let identity_ids: Vec<i32> = external_ids
        .iter()
        .map(|id| identity_by_external[id])
        .collect();
    let confidences = vec![0.4_f64, 0.9_f64];
    client
        .execute(
            "INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, \
             confidence, created_at, updated_at, evidence_json) \
             SELECT $1, ident, 'confirmed', conf, NOW(), NOW(), '{}'::json \
             FROM unnest($2::int4[], $3::float8[]) AS m(ident, conf)",
            &[&issue, &identity_ids, &confidences],
        )
        .await
        .unwrap();
    drop(client);

    let (status, body) = call(&ctx, "GET", "/api/v2/threads").await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        thread_cover(&body, "Confidence Wins"),
        Some("https://cv.example/high.jpg".to_owned())
    );
}

#[tokio::test]
async fn series_cover_null_when_no_confirmed_cover() {
    let ctx = setup("series-cover-null").await;
    let thread_id = seed_thread(&ctx, ctx.user_id, "No Cover", "active", 1).await;
    let issue = seed_issue(&ctx, thread_id, "1", 1, "unread").await;
    set_frontier(&ctx, thread_id, Some(issue)).await;
    seed_confirmed_cover(&ctx, issue, "no-cover-id", None).await;

    let (status, body) = call(&ctx, "GET", "/api/v2/threads").await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(thread_cover(&body, "No Cover"), None);
}

#[tokio::test]
async fn series_cover_null_when_thread_has_no_issues() {
    let ctx = setup("series-cover-empty").await;
    let _thread_id = seed_thread(&ctx, ctx.user_id, "Empty Series", "active", 1).await;

    let (status, body) = call(&ctx, "GET", "/api/v2/threads").await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(thread_cover(&body, "Empty Series"), None);
}

#[tokio::test]
async fn series_cover_is_owner_scoped() {
    let ctx = setup("series-cover-scoped").await;
    let thread_id = seed_thread(&ctx, ctx.user_id, "Owner Series", "active", 1).await;
    let issue = seed_issue(&ctx, thread_id, "1", 1, "unread").await;
    set_frontier(&ctx, thread_id, Some(issue)).await;
    seed_confirmed_cover(
        &ctx,
        issue,
        "scoped-cover-id",
        Some("https://cv.example/scoped.jpg"),
    )
    .await;

    // A second user's confirmed-cover thread must not appear.
    let (other_token, other_csrf, other_user_id) = register_user(
        &ctx.state,
        &format!("other-{}-{}", std::process::id(), unique_suffix()),
    )
    .await;
    let other_thread =
        seed_thread_raw(&ctx.state, other_user_id, "Other Series", "active", 1).await;
    let other_issue = seed_issue_raw(&ctx.state, other_thread, "1", 1, "unread").await;
    set_frontier_raw(&ctx.state, other_thread, Some(other_issue)).await;
    seed_confirmed_cover_raw(
        &ctx.state,
        other_issue,
        "other-scoped-id",
        Some("https://cv.example/other.jpg"),
    )
    .await;

    let (status, body) = call(&ctx, "GET", "/api/v2/threads").await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        thread_cover(&body, "Owner Series"),
        Some("https://cv.example/scoped.jpg".to_owned())
    );
    // The other user's series is not visible to this caller.
    assert!(!body["threads"]
        .as_array()
        .unwrap()
        .iter()
        .any(|t| t["title"] == "Other Series"));

    // The other user can see their own series cover.
    let response = router(ctx.state.clone())
        .oneshot(authed("GET", "/api/v2/threads", &other_token, &other_csrf))
        .await
        .unwrap();
    let bytes = to_bytes(response.into_body(), 256 * 1024).await.unwrap();
    let other_body: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    assert_eq!(
        thread_cover(&other_body, "Other Series"),
        Some("https://cv.example/other.jpg".to_owned())
    );
}

// Raw seeders reuse the test state without the per-test reset guard (called
// after the owning test's guard is still held, so the schema stays intact).
async fn seed_thread_raw(
    state: &Arc<AppState>,
    user_id: i32,
    title: &str,
    status: &str,
    queue_position: i32,
) -> i32 {
    state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position,
                                  status, manual_creator_credits, is_test, is_blocked,
                                  queue_position_is_manual, created_at)
             VALUES ($1, $2, 'Comic', 0, $3, $4, '[]'::json, false, false, false, NOW())
             RETURNING id",
            &[&user_id, &title, &queue_position, &status],
        )
        .await
        .unwrap()
        .get(0)
}

async fn seed_issue_raw(
    state: &Arc<AppState>,
    thread_id: i32,
    number: &str,
    position: i32,
    status: &str,
) -> i32 {
    state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, status, position, created_at)
             VALUES ($1, $2, $3, $4, NOW()) RETURNING id",
            &[&thread_id, &number, &status, &position],
        )
        .await
        .unwrap()
        .get(0)
}

async fn set_frontier_raw(
    state: &Arc<AppState>,
    thread_id: i32,
    next_unread_issue_id: Option<i32>,
) {
    state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE threads SET next_unread_issue_id = $2, reading_progress = 'in_progress'
             WHERE id = $1",
            &[&thread_id, &next_unread_issue_id],
        )
        .await
        .unwrap();
}

async fn seed_confirmed_cover_raw(
    state: &Arc<AppState>,
    issue_id: i32,
    external_id: &str,
    cover_url: Option<&str>,
) {
    let metadata = match cover_url {
        Some(url) => json!({"image": {"original_url": url}}),
        None => json!({"issue_number": "1"}),
    };
    let identity: i32 = state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, \
             created_at, updated_at) VALUES ('comicvine', 'issue', $1, $2, NOW(), NOW()) RETURNING id",
            &[&external_id, &metadata],
        )
        .await
        .unwrap()
        .get(0);
    state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, \
             created_at, updated_at, evidence_json) VALUES ($1, $2, 'confirmed', NOW(), NOW(), '{}'::json)",
            &[&issue_id, &identity],
        )
        .await
        .unwrap();
}
