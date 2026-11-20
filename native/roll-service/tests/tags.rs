#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Database-backed regressions for every tag mutation through the mounted router.

use axum::{
    body::Body,
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, AppState};
use serde_json::Value;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

// Distinct proxied clients for registration: the production limiter is
// intentionally process-global even when each test resets PostgreSQL.
static NEXT_TEST_CLIENT: AtomicUsize = AtomicUsize::new(1);
use tower::ServiceExt;

async fn setup() -> (
    Arc<AppState>,
    String,
    i32,
    tokio::sync::MutexGuard<'static, ()>,
) {
    let url = comicpile_roll_service::test_support::database_url().await;
    let state = Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
                "RUST_ROLL_JWT_SECRET" => Some("synthetic-tags-secret".into()),
                "RUST_ROLL_POOL_SIZE" => Some("2".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    );
    let _guard = comicpile_roll_service::test_support::reset_for_test(&state).await;
    let username = format!("tag-user-{}-{}", std::process::id(), unique_suffix());
    let registered = send(
        &state,
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
                serde_json::json!({
                    "username": username,
                    "email": "tag-user@example.com",
                    "password": "correct-horse-battery"
                })
                .to_string(),
            ))
            .unwrap(),
    )
    .await;
    assert_eq!(registered.0, StatusCode::OK, "{registered:?}");
    let token = registered.1["access_token"].as_str().unwrap().to_owned();
    let user_id: i32 = state
        .pool
        .get()
        .await
        .unwrap()
        .query_one("SELECT id FROM users ORDER BY id DESC LIMIT 1", &[])
        .await
        .unwrap()
        .get(0);
    state.pool.get().await.unwrap().execute(
        "INSERT INTO threads (id, title, format, issues_remaining, queue_position, status, user_id) VALUES (1, 'Tag thread', 'single', 1, 1, 'active', $1)", &[&user_id],
    ).await.unwrap();
    let created = mutation(
        &state,
        &token,
        "POST",
        "/api/v1/tags/",
        serde_json::json!({"name":"Original","color":"red"}),
    )
    .await;
    assert_eq!(created.0, StatusCode::OK, "{created:?}");
    (
        state,
        token,
        created.1["tag"]["id"].as_i64().unwrap() as i32,
        _guard,
    )
}

fn unique_suffix() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos()
}

async fn send(state: &Arc<AppState>, request: Request<Body>) -> (StatusCode, Value) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), 16 * 1024)
        .await
        .unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

async fn mutation(
    state: &Arc<AppState>,
    token: &str,
    method: &str,
    path: &str,
    body: Value,
) -> (StatusCode, Value) {
    send(
        state,
        Request::builder()
            .method(method)
            .uri(path)
            .header(header::CONTENT_TYPE, "application/json")
            .header(header::AUTHORIZATION, format!("Bearer {token}"))
            .header("cookie", "csrf_token=synthetic-tags-csrf")
            .header("x-csrf-token", "synthetic-tags-csrf")
            .body(Body::from(body.to_string()))
            .unwrap(),
    )
    .await
}

async fn assignment_count(state: &Arc<AppState>, tag_id: i32) -> i64 {
    state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "SELECT COUNT(*)::bigint FROM tag_assignments WHERE tag_id = $1",
            &[&tag_id],
        )
        .await
        .unwrap()
        .get(0)
}

#[tokio::test]
async fn create_tag_writes_database_row() {
    let (state, token, _tag_id, _guard) = setup().await;
    let result = mutation(
        &state,
        &token,
        "POST",
        "/api/v1/tags/",
        serde_json::json!({"name":"Additional","color":"red"}),
    )
    .await;
    assert_eq!(result.0, StatusCode::OK, "{result:?}");
    let tag_id = result.1["tag"]["id"].as_i64().unwrap() as i32;
    let name: String = state
        .pool
        .get()
        .await
        .unwrap()
        .query_one("SELECT name FROM tags WHERE id = $1", &[&tag_id])
        .await
        .unwrap()
        .get(0);
    assert_eq!(name, "Additional");
}

#[tokio::test]
async fn update_tag_persists_name_and_color() {
    let (state, token, tag_id, _guard) = setup().await;
    let result = mutation(
        &state,
        &token,
        "PUT",
        &format!("/api/v1/tags/{tag_id}/"),
        serde_json::json!({"name":"Renamed","color":"blue"}),
    )
    .await;
    assert_eq!(result.0, StatusCode::OK, "{result:?}");
    assert_eq!(result.1["name"], "Renamed");
    let name: String = state
        .pool
        .get()
        .await
        .unwrap()
        .query_one("SELECT name FROM tags WHERE id = $1", &[&tag_id])
        .await
        .unwrap()
        .get(0);
    assert_eq!(name, "Renamed");
}

#[tokio::test]
async fn assign_tag_inserts_assignment() {
    let (state, token, tag_id, _guard) = setup().await;
    let result = mutation(
        &state,
        &token,
        "POST",
        &format!("/api/v1/tags/{tag_id}/assign/"),
        serde_json::json!({"target_type":"Thread","target_id":1}),
    )
    .await;
    assert_eq!(result.0, StatusCode::OK, "{result:?}");
    assert_eq!(assignment_count(&state, tag_id).await, 1);
}

#[tokio::test]
async fn unassign_tag_removes_assignment() {
    let (state, token, tag_id, _guard) = setup().await;
    assert_eq!(
        mutation(
            &state,
            &token,
            "POST",
            &format!("/api/v1/tags/{tag_id}/assign/"),
            serde_json::json!({"target_type":"Thread","target_id":1})
        )
        .await
        .0,
        StatusCode::OK
    );
    let result = mutation(
        &state,
        &token,
        "DELETE",
        &format!("/api/v1/tags/{tag_id}/unassign/"),
        serde_json::json!({"target_type":"Thread","target_id":1}),
    )
    .await;
    assert_eq!(result.0, StatusCode::OK, "{result:?}");
    assert_eq!(assignment_count(&state, tag_id).await, 0);
}

#[tokio::test]
async fn bulk_assign_tag_writes_unique_assignments() {
    let (state, token, tag_id, _guard) = setup().await;
    let result = mutation(
        &state,
        &token,
        "POST",
        &format!("/api/v1/tags/{tag_id}/bulk-assign/"),
        serde_json::json!({"target_type":"Thread","target_ids":[1,1]}),
    )
    .await;
    assert_eq!(result.0, StatusCode::OK, "{result:?}");
    assert_eq!(result.1["affected_ids"], serde_json::json!([1]));
    assert_eq!(assignment_count(&state, tag_id).await, 1);
}

#[tokio::test]
async fn bulk_unassign_tag_removes_assignments() {
    let (state, token, tag_id, _guard) = setup().await;
    assert_eq!(
        mutation(
            &state,
            &token,
            "POST",
            &format!("/api/v1/tags/{tag_id}/assign/"),
            serde_json::json!({"target_type":"Thread","target_id":1})
        )
        .await
        .0,
        StatusCode::OK
    );
    let result = mutation(
        &state,
        &token,
        "POST",
        &format!("/api/v1/tags/{tag_id}/bulk-unassign/"),
        serde_json::json!({"target_type":"Thread","target_ids":[1]}),
    )
    .await;
    assert_eq!(result.0, StatusCode::OK, "{result:?}");
    assert_eq!(assignment_count(&state, tag_id).await, 0);
}

#[tokio::test]
async fn delete_tag_cascades_assignments() {
    let (state, token, tag_id, _guard) = setup().await;
    let assigned = mutation(
        &state,
        &token,
        "POST",
        &format!("/api/v1/tags/{tag_id}/assign/"),
        serde_json::json!({"target_type":"Thread","target_id":1}),
    )
    .await;
    assert_eq!(assigned.0, StatusCode::OK, "{assigned:?}");
    assert_eq!(assignment_count(&state, tag_id).await, 1);
    let result = mutation(
        &state,
        &token,
        "DELETE",
        &format!("/api/v1/tags/{tag_id}/"),
        serde_json::json!({}),
    )
    .await;
    assert_eq!(result.0, StatusCode::OK, "{result:?}");
    let remaining: i64 = state
        .pool
        .get()
        .await
        .unwrap()
        .query_one(
            "SELECT COUNT(*)::bigint FROM tags WHERE id = $1",
            &[&tag_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(remaining, 0);
    assert_eq!(assignment_count(&state, tag_id).await, 0);
}
