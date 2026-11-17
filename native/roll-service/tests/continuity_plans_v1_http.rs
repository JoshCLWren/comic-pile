#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Focused native HTTP regressions for the browser-called continuity-plans v1
//! cutover (issue #4838). Exercises the mounted Rust router so contract shape
//! and basic transactional CRUD are verified at the same-path ingress.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, test_support, AppState};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicU16, Ordering};
use std::sync::Arc;
use tower::ServiceExt;

static NEXT_IP: AtomicU16 = AtomicU16::new(10);

async fn database() -> Option<(Arc<AppState>, tokio::sync::MutexGuard<'static, ()>)> {
    let url = match std::env::var("RUST_ROLL_TEST_DATABASE_URL") {
        Ok(value) if !value.trim().is_empty() => value,
        _ => return None,
    };
    // Reuse the suite's canonical disposable-database helper when available.
    let _ = test_support::database_url().await;
    let state = Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
                "RUST_ROLL_JWT_SECRET" => Some(test_support::TEST_JWT_SECRET.into()),
                "RUST_ROLL_POOL_SIZE" => Some("4".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    );
    let guard = test_support::reset_for_test(&state).await;
    Some((state, guard))
}

async fn send(
    state: &Arc<AppState>,
    request: Request<Body>,
) -> (StatusCode, Value, Vec<String>) {
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
        cookie.strip_prefix(&format!("{name}=")).and_then(|rest| rest.split(';').next()).map(str::to_owned)
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
    let token = registered["access_token"].as_str().expect("access token").to_string();
    let _ = csrf;
    (token, cookie_value(&cookies, "csrf_token").unwrap_or_default())
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

#[tokio::test]
async fn continuity_plan_crud_and_membership_shape_are_native_wire_compatible() {
    let Some((state, _db)) = database().await else {
        eprintln!(
            "skipping continuity_plans_v1_http: RUST_ROLL_TEST_DATABASE_URL not configured"
        );
        return;
    };
    let (token, csrf) = register_and_login(&state, "cp-wire").await;

    let create_body = json!({
        "name": "Wire Plan",
        "ordering_mode": "informational",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": []
    });
    let (status, created, _) = send(
        &state,
        Request::builder()
            .method("POST")
            .uri("/api/v1/continuity-plans/")
            .header(header::AUTHORIZATION, format!("Bearer {token}"))
            .header("x-csrf-token", &csrf)
            .header(header::COOKIE, format!("csrf_token={csrf}"))
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(create_body.to_string()))
            .unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let plan_id = created["id"].as_i64().expect("plan id");
    assert_eq!(created["name"], "Wire Plan");
    assert_eq!(created["ordering_mode"], "informational");

    let (status, listed) = authed_json(&state, "GET", "/api/v1/continuity-plans/", &token, &csrf, None).await;
    assert_eq!(status, StatusCode::OK, "{listed}");
    assert!(listed.as_array().unwrap().iter().any(|item| item["id"] == plan_id));

    let (status, fetched) = authed_json(
        &state,
        "GET",
        &format!("/api/v1/continuity-plans/{plan_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{fetched}");
    assert_eq!(fetched["id"], plan_id);

    // P1 #2 contract: membership response must match Python schema
    // {plan_id, issues[], dependencies[], sources[], placements[], progress{total_issues, read_issues}}.
    let (status, membership) = authed_json(
        &state,
        "GET",
        &format!("/api/v1/continuity-plans/{plan_id}/membership"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{membership}");
    assert_eq!(membership["plan_id"], plan_id);
    assert!(membership["issues"].is_array(), "{membership}");
    assert!(membership["dependencies"].is_array(), "{membership}");
    assert!(membership["sources"].is_array(), "{membership}");
    assert!(membership["placements"].is_array(), "{membership}");
    assert_eq!(membership["progress"]["total_issues"], 0, "{membership}");
    assert_eq!(membership["progress"]["read_issues"], 0, "{membership}");

    let update_body = json!({
        "name": "Wire Plan Updated",
        "ordering_mode": "informational",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [],
        "expected_updated_at": created["updated_at"]
    });
    let (status, updated) = authed_json(
        &state,
        "PUT",
        &format!("/api/v1/continuity-plans/{plan_id}"),
        &token,
        &csrf,
        Some(update_body),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{updated}");
    assert_eq!(updated["name"], "Wire Plan Updated");

    let (status, deleted) = authed_json(
        &state,
        "DELETE",
        &format!("/api/v1/continuity-plans/{plan_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT, "{deleted}");

    let (status, missing) = authed_json(
        &state,
        "GET",
        &format!("/api/v1/continuity-plans/{plan_id}"),
        &token,
        &csrf,
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{missing}");
}
