#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Handler-level HTTP regressions for bulk queue exclusions (#5435).
//!
//! Covers one-action bulk remove/restore for a reading container's series:
//! - bulk exclude creates grouped provenance and removes active threads
//! - excluded threads listing exposes `queue_exclusion_group`
//! - bulk restore and group restore return threads to the active queue
//! - roll eligibility follows queue membership (active count/list)
//!
//! Exercises the mounted router against the canonical disposable PostgreSQL
//! schema and hard-fails without `RUST_ROLL_TEST_DATABASE_URL`.

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
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-queue-exclusions-secret".into()),
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

async fn send(state: &Arc<AppState>, request: Request<Body>) -> (StatusCode, Value) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 128 * 1024).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

fn authed(method: &str, path: &str, token: &str, csrf: &str, body: Option<Value>) -> Request<Body> {
    let builder = Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"));
    if let Some(payload) = body {
        builder
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(payload.to_string()))
            .unwrap()
    } else {
        builder.body(Body::empty()).unwrap()
    }
}

async fn insert_thread(ctx: &Ctx, title: &str, position: i32, status: &str) -> i32 {
    let client = ctx.state.pool.get().await.unwrap();
    client
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at) \
             VALUES ($1, $2, 'comic', 3, $3, $4, NOW()) RETURNING id",
            &[&ctx.user_id, &title, &position, &status],
        )
        .await
        .unwrap()
        .get(0)
}

#[tokio::test(flavor = "multi_thread")]
async fn bulk_exclude_and_restore_manage_grouped_queue_membership() {
    let ctx = setup("qex").await;
    let t1 = insert_thread(&ctx, "Alpha", 1, "active").await;
    let t2 = insert_thread(&ctx, "Beta", 2, "active").await;
    let t3 = insert_thread(&ctx, "Gamma", 3, "active").await;

    let (status, body) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/queue-exclusions",
            &ctx.token,
            &ctx.csrf,
            Some(json!({
                "thread_ids": [t1, t2],
                "source": { "kind": "reading_list", "id": 42, "name": "My List" }
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let group_id = body["group"]["id"].as_i64().expect("group id") as i32;
    assert_eq!(body["group"]["source_kind"], "reading_list");
    assert_eq!(body["group"]["source_name"], "My List");
    let mut excluded_ids = body["excluded_thread_ids"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_i64().unwrap() as i32)
        .collect::<Vec<_>>();
    excluded_ids.sort_unstable();
    assert_eq!(excluded_ids, vec![t1, t2]);

    // Excluded listing exposes provenance and groups the removed threads.
    let (status, body) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v1/threads/excluded/threads",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let threads = body["threads"].as_array().unwrap();
    assert_eq!(threads.len(), 2, "{body:?}");
    for thread in threads {
        assert_eq!(
            thread["queue_exclusion_group"]["id"].as_i64().unwrap() as i32,
            group_id
        );
        assert_eq!(
            thread["queue_exclusion_group"]["source_kind"],
            "reading_list"
        );
        assert_eq!(thread["queue_exclusion_group"]["source_name"], "My List");
    }

    // Roll eligibility / active queue membership: only the untouched thread remains.
    let (status, body) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v2/threads?page_size=50",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["active_count"].as_i64(), Some(1), "{body:?}");
    let active_ids = body["threads"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["id"].as_i64().unwrap() as i32)
        .collect::<Vec<_>>();
    assert_eq!(active_ids, vec![t3], "{body:?}");

    // Restore the whole group in one action.
    let (status, body) = send(
        &ctx.state,
        authed(
            "POST",
            &format!("/api/v2/queue-exclusion-groups/{group_id}/restore"),
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let mut restored = body["restored_thread_ids"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_i64().unwrap() as i32)
        .collect::<Vec<_>>();
    restored.sort_unstable();
    assert_eq!(restored, vec![t1, t2]);

    let (status, body) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v1/threads/excluded/threads",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["threads"].as_array().unwrap().len(), 0, "{body:?}");

    let (status, body) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v2/threads?page_size=50",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["active_count"].as_i64(), Some(3), "{body:?}");

    // Bulk restore by explicit ids (re-exclude then restore by ids).
    let (status, _body) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/queue-exclusions",
            &ctx.token,
            &ctx.csrf,
            Some(json!({
                "thread_ids": [t1, t3],
                "source": { "kind": "reading_plan", "id": 7, "name": "Plan P" }
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let (status, body) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/queue-exclusions/restore",
            &ctx.token,
            &ctx.csrf,
            Some(json!({ "thread_ids": [t1, t3] })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let mut restored = body["restored_thread_ids"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_i64().unwrap() as i32)
        .collect::<Vec<_>>();
    restored.sort_unstable();
    assert_eq!(restored, vec![t1, t3]);

    let (status, body) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v2/threads?page_size=50",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["active_count"].as_i64(), Some(3), "{body:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn bulk_requests_enforce_thread_id_count_limits() {
    let ctx = setup("qexlim").await;
    let too_many: Vec<i32> = (1..=1001).collect();

    let (status, body) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/queue-exclusions",
            &ctx.token,
            &ctx.csrf,
            Some(json!({
                "thread_ids": too_many,
                "source": { "kind": "reading_list", "id": 1, "name": "Big" }
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body:?}");
    assert!(
        body["detail"].as_str().unwrap_or("").contains("at most"),
        "{body:?}"
    );

    let too_many_restore: Vec<i32> = (1..=1001).collect();
    let (status, body) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/queue-exclusions/restore",
            &ctx.token,
            &ctx.csrf,
            Some(json!({ "thread_ids": too_many_restore })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body:?}");
    assert!(
        body["detail"].as_str().unwrap_or("").contains("at most"),
        "{body:?}"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn concurrent_bulk_exclude_and_single_exclude_serialize_consistently() {
    let ctx = setup("qexc").await;
    let t1 = insert_thread(&ctx, "A", 1, "active").await;
    let t2 = insert_thread(&ctx, "B", 2, "active").await;
    let t3 = insert_thread(&ctx, "C", 3, "active").await;

    let bulk = {
        let state = ctx.state.clone();
        let token = ctx.token.clone();
        let csrf = ctx.csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    "/api/v2/queue-exclusions",
                    &token,
                    &csrf,
                    Some(json!({
                        "thread_ids": [t1, t2],
                        "source": { "kind": "reading_list", "id": 10, "name": "L1" }
                    })),
                ),
            )
            .await
        })
    };
    let single = {
        let state = ctx.state.clone();
        let token = ctx.token.clone();
        let csrf = ctx.csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    &format!("/api/v1/threads/{t3}/exclude"),
                    &token,
                    &csrf,
                    None,
                ),
            )
            .await
        })
    };

    let (r1, r2) = tokio::join!(bulk, single);
    let (s1, b1) = r1.unwrap();
    let (s2, b2) = r2.unwrap();
    assert_eq!(s1, StatusCode::OK, "{b1:?}");
    assert!(s2.is_success(), "{s2:?} {b2:?}");

    let (status, body) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v2/threads?page_size=50",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["active_count"].as_i64(), Some(0), "{body:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn concurrent_group_restore_and_bulk_exclude_do_not_cross_groups() {
    let ctx = setup("qexr").await;
    let t1 = insert_thread(&ctx, "A", 1, "active").await;
    let t2 = insert_thread(&ctx, "B", 2, "active").await;

    // Create initial exclusion group containing both threads.
    let (status, body) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/queue-exclusions",
            &ctx.token,
            &ctx.csrf,
            Some(json!({
                "thread_ids": [t1, t2],
                "source": { "kind": "reading_list", "id": 1, "name": "Old" }
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let group_id = body["group"]["id"].as_i64().unwrap() as i32;

    // Race: restore old group vs exclude the same threads into a new group.
    let restore = {
        let state = ctx.state.clone();
        let token = ctx.token.clone();
        let csrf = ctx.csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    &format!("/api/v2/queue-exclusion-groups/{group_id}/restore"),
                    &token,
                    &csrf,
                    None,
                ),
            )
            .await
        })
    };
    let exclude_new = {
        let state = ctx.state.clone();
        let token = ctx.token.clone();
        let csrf = ctx.csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    "/api/v2/queue-exclusions",
                    &token,
                    &csrf,
                    Some(json!({
                        "thread_ids": [t1, t2],
                        "source": { "kind": "reading_list", "id": 2, "name": "New" }
                    })),
                ),
            )
            .await
        })
    };

    let (r1, r2) = tokio::join!(restore, exclude_new);
    let (s1, b1) = r1.unwrap();
    let (s2, b2) = r2.unwrap();
    assert_eq!(s1, StatusCode::OK, "{b1:?}");
    assert_eq!(s2, StatusCode::OK, "{b2:?}");

    // Invariant: no thread remains excluded under the old group after a
    // concurrent restore/exclude-new race. Depending on serialization order,
    // threads are either active or excluded under the new group.
    let (status, body) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v1/threads/excluded/threads",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    for thread in body["threads"].as_array().unwrap() {
        let gid = thread["queue_exclusion_group"]["id"].as_i64().unwrap() as i32;
        assert_ne!(
            gid, group_id,
            "thread must not remain in old group: {thread:?}"
        );
        assert_eq!(
            thread["queue_exclusion_group"]["source_name"], "New",
            "excluded threads must belong to the newer group: {thread:?}"
        );
    }

    let (status, body) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v2/threads?page_size=50",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let active_count = body["active_count"].as_i64().unwrap();
    assert!(active_count == 0 || active_count == 2, "{body:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn concurrent_bulk_restore_and_single_restore_serialize_consistently() {
    let ctx = setup("qexs").await;
    let t1 = insert_thread(&ctx, "A", 1, "active").await;
    let t2 = insert_thread(&ctx, "B", 2, "active").await;

    let (status, _body) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/queue-exclusions",
            &ctx.token,
            &ctx.csrf,
            Some(json!({
                "thread_ids": [t1, t2],
                "source": { "kind": "crossover", "id": 3, "name": "X" }
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    let bulk_restore = {
        let state = ctx.state.clone();
        let token = ctx.token.clone();
        let csrf = ctx.csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    "/api/v2/queue-exclusions/restore",
                    &token,
                    &csrf,
                    Some(json!({ "thread_ids": [t1, t2] })),
                ),
            )
            .await
        })
    };
    let single_restore = {
        let state = ctx.state.clone();
        let token = ctx.token.clone();
        let csrf = ctx.csrf.clone();
        tokio::spawn(async move {
            send(
                &state,
                authed(
                    "POST",
                    &format!("/api/v1/threads/{t1}/restore"),
                    &token,
                    &csrf,
                    None,
                ),
            )
            .await
        })
    };

    let (r1, r2) = tokio::join!(bulk_restore, single_restore);
    let (s1, b1) = r1.unwrap();
    let (s2, b2) = r2.unwrap();
    assert_eq!(s1, StatusCode::OK, "{b1:?}");
    // Single restore may see thread already restored by bulk op.
    assert!(
        s2.is_success() || s2 == StatusCode::CONFLICT || s2 == StatusCode::BAD_REQUEST,
        "{s2:?} {b2:?}"
    );

    let (status, body) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v2/threads?page_size=50",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["active_count"].as_i64(), Some(2), "{body:?}");

    let (status, body) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v1/threads/excluded/threads",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["threads"].as_array().unwrap().len(), 0, "{body:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn check_excluded_status_reports_excluded_and_active_threads() {
    let ctx = setup("qex-status").await;
    let excluded = insert_thread(&ctx, "Excluded", 1, "excluded").await;
    let active = insert_thread(&ctx, "Active", 2, "active").await;

    let (status, body) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/queue-exclusions/status:check",
            &ctx.token,
            &ctx.csrf,
            Some(json!({ "thread_ids": [excluded, active, 999999] })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["excluded_thread_ids"], json!([excluded]), "{body:?}");
    assert_eq!(body["active_thread_ids"], json!([active]), "{body:?}");
}
