#![allow(clippy::unwrap_used, clippy::expect_used)]
//! HTTP regressions for deleting an owned thread through the same-path v1
//! endpoint. The delete must remove the thread together with its dependent rows
//! in one transaction so it cannot fail with a foreign-key violation.

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

async fn send(state: &Arc<AppState>, request: Request<Body>) -> (StatusCode, Value) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

fn delete(path: &str, token: &str, csrf: &str) -> Request<Body> {
    Request::builder()
        .method("DELETE")
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"))
        .body(Body::empty())
        .unwrap()
}

#[tokio::test]
async fn delete_thread_removes_events_and_reading_order_items() {
    let (state, token, csrf, user_id, _guard) = setup_user("thread-delete-fk").await;
    let conn = state.pool.get().await.unwrap();

    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, created_at) \
             VALUES ($1, 'Comic', 1, 1, 'active', $2, NOW()) RETURNING id",
            &[&"Paper Girls QA Edit", &user_id],
        )
        .await
        .unwrap()
        .get(0);

    // Events referencing the thread previously blocked deletion with
    // events_thread_id_fkey; include a pending-roll style event and a rating.
    conn.execute(
        "INSERT INTO events (type, timestamp, user_id, thread_id, selected_thread_id) \
         VALUES ('roll', NOW(), $1, $2, $2)",
        &[&user_id, &thread_id],
    )
    .await
    .unwrap();
    conn.execute(
        "INSERT INTO events (type, timestamp, user_id, thread_id, rating) \
         VALUES ('rate', NOW(), $1, $2, 4.0::float8)",
        &[&user_id, &thread_id],
    )
    .await
    .unwrap();

    // reading_order_items.thread_id has no ON DELETE cascade in the schema, so
    // thread deletion must remove it explicitly.
    let reading_order_id: i32 = conn
        .query_one(
            "INSERT INTO reading_orders (name, user_id) VALUES ($1, $2) RETURNING id",
            &[&"QA list", &user_id],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO reading_order_items (reading_order_id, thread_id, position) \
         VALUES ($1, $2, 1)",
        &[&reading_order_id, &thread_id],
    )
    .await
    .unwrap();

    let (status, body) = send(
        &state,
        delete(&format!("/api/v1/threads/{thread_id}"), &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");

    let thread_count: i64 = conn
        .query_one("SELECT count(*) FROM threads WHERE id = $1", &[&thread_id])
        .await
        .unwrap()
        .get(0);
    assert_eq!(thread_count, 0, "thread row must be deleted");

    let event_count: i64 = conn
        .query_one(
            "SELECT count(*) FROM events WHERE thread_id = $1",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        event_count, 0,
        "events referencing the thread must be removed"
    );

    let item_count: i64 = conn
        .query_one(
            "SELECT count(*) FROM reading_order_items WHERE thread_id = $1",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        item_count, 0,
        "reading order entries for the deleted thread must be removed"
    );

    let delete_audit_count: i64 = conn
        .query_one(
            "SELECT count(*) FROM events WHERE user_id = $1 AND type = 'delete' AND thread_id IS NULL",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        delete_audit_count, 1,
        "a delete audit event should be recorded"
    );
}

#[tokio::test]
async fn delete_thread_not_found_returns_404() {
    let (state, token, csrf, _user_id, _guard) = setup_user("thread-delete-404").await;
    let (status, _body) = send(&state, delete("/api/v1/threads/999999", &token, &csrf)).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}
