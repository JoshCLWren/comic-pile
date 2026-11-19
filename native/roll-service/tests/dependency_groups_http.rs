#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Handler-level HTTP regressions for the same-path reading-order-group routes
//! (#4841). Exercises the real router against the canonical disposable
//! PostgreSQL schema so int4/int8 decoding and wire shapes are covered end to
//! end. Requires `RUST_ROLL_TEST_DATABASE_URL` and hard-fails without it.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, AppState};
use serde_json::{json, Value};
use std::sync::Arc;
use tower::ServiceExt;

async fn setup_user(prefix: &str) -> (Arc<AppState>, String, String, i32) {
    let url = comicpile_roll_service::test_support::database_url().await;
    let state = Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
                "RUST_ROLL_JWT_SECRET" => Some("synthetic-reading-order-groups-secret".into()),
                "RUST_ROLL_POOL_SIZE" => Some("2".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    );
    let _guard = comicpile_roll_service::test_support::reset_for_test(&state).await;
    let username = format!("{prefix}-{}", std::process::id());
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/auth/register")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(
                    json!({
                        "username": username,
                        "email": format!("{username}@example.com"),
                        "password": "correct-horse-battery",
                    })
                    .to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap();
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
    let body: Value = serde_json::from_slice(&bytes).unwrap();
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
    (state, token, csrf, user_id)
}

fn authed(method: &str, path: &str, token: &str, csrf: &str, body: Option<Value>) -> Request<Body> {
    let builder = Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"));
    if let Some(body) = body {
        builder
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(body.to_string()))
            .unwrap()
    } else {
        builder.body(Body::empty()).unwrap()
    }
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

#[tokio::test]
async fn reading_order_group_routes_round_trip_over_http() {
    let (state, token, csrf, user_id) = setup_user("rog-http").await;

    // Seed one owned series with three positioned issues.
    let connection = state.pool.get().await.unwrap();
    let thread_id: i32 = connection
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, status, queue_position) \
             VALUES ($1, 'Series', 'Comic', 3, 'active', 1) RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    for position in 1..=3 {
        connection
            .execute(
                "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
                 VALUES ($1, $2, $3, 'unread', now())",
                &[&thread_id, &position.to_string(), &position],
            )
            .await
            .unwrap();
    }
    drop(connection);

    // Empty list, then create.
    let (status, body) = send(
        &state,
        authed("GET", "/api/v1/reading-order-groups/", &token, &csrf, None),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body, json!([]));

    let (status, body) = send(
        &state,
        authed(
            "POST",
            "/api/v1/reading-order-groups/",
            &token,
            &csrf,
            Some(json!({"name": "Crossover"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    let group_id = body["id"].as_i64().unwrap() as i32;

    // Single-group read before any memberships exist.
    let path = format!("/api/v1/reading-order-groups/{group_id}");
    let (status, body) = send(&state, authed("GET", &path, &token, &csrf, None)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["name"], json!("Crossover"));

    // Thread-level membership, then issue range (set-based insert).
    let path = format!("/api/v1/reading-order-groups/{group_id}/members");
    let (status, body) = send(
        &state,
        authed(
            "POST",
            &path,
            &token,
            &csrf,
            Some(json!({"thread_id": thread_id})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    let member_id = body["id"].as_i64().unwrap() as i32;

    // The group now appears in the thread-scoped listing.
    let path = format!("/api/v1/reading-order-groups/threads/{thread_id}/groups");
    let (status, body) = send(&state, authed("GET", &path, &token, &csrf, None)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body.as_array().unwrap().len(), 1);

    let path = format!("/api/v1/reading-order-groups/{group_id}/issue-ranges");
    let (status, body) = send(
        &state,
        authed(
            "POST",
            &path,
            &token,
            &csrf,
            Some(json!({
                "thread_id": thread_id,
                "start_position": 1,
                "end_position": 2,
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["added_issue_ids"].as_array().unwrap().len(), 2);
    let issue_id = body["added_issue_ids"][0].as_i64().unwrap();

    // Detail enrichment, authoritative ordering and linked plans.
    let path = format!("/api/v1/reading-order-groups/{group_id}/detail");
    let (status, body) = send(&state, authed("GET", &path, &token, &csrf, None)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");

    let path = format!("/api/v1/reading-order-groups/{group_id}/order");
    let (status, body) = send(
        &state,
        authed(
            "PUT",
            &path,
            &token,
            &csrf,
            Some(json!({"items": [{"issue_id": issue_id, "sequence_order": 1}]})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");

    let path = format!("/api/v1/reading-order-groups/{group_id}/plans");
    let (status, body) = send(&state, authed("GET", &path, &token, &csrf, None)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body, json!([]));

    // Rename, then remove the thread-level member and delete the group.
    let (status, body) = send(
        &state,
        authed(
            "PATCH",
            &format!("/api/v1/reading-order-groups/{group_id}"),
            &token,
            &csrf,
            Some(json!({"name": "Renamed"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["name"], json!("Renamed"));

    let (status, _) = send(
        &state,
        authed(
            "DELETE",
            &format!("/api/v1/reading-order-groups/{group_id}/members/{member_id}"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);

    let (status, _) = send(
        &state,
        authed(
            "DELETE",
            &format!("/api/v1/reading-order-groups/{group_id}"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);

    let (status, _) = send(
        &state,
        authed(
            "GET",
            &format!("/api/v1/reading-order-groups/{group_id}"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}
