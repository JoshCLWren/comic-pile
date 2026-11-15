#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Disposable-schema HTTP regression runner for the native v2 continuity-plan
//! operations: the Option E reader, the recovery preview and the recovery
//! relink write.
//!
//! The method and URI are taken from the environment so one binary exercises
//! every continuity-plan route:
//!
//! * `GET /api/v2/continuity-plans/{plan_id}/reader`
//! * `GET /api/v2/continuity-plans/{plan_id}/recovery`
//! * `POST /api/v2/continuity-plans/{plan_id}/recovery` (JSON body)
//!
//! The process prints one JSON object (`{"status": ..., "body": ...}`) so the
//! Python parity tests can assert the real HTTP response and its data shape.
use axum::{
    body::{to_bytes, Body},
    http::Request,
};
use comicpile_roll_service::{config::Config, router, AppState};
use std::sync::Arc;
use tower::ServiceExt;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let token = std::env::var("RUST_ROLL_TEST_TOKEN")?;
    let method = std::env::var("RUST_ROLL_TEST_METHOD").unwrap_or_else(|_| "GET".to_string());
    let uri = std::env::var("RUST_ROLL_TEST_URI")?;
    let body = std::env::var("RUST_ROLL_TEST_BODY")
        .ok()
        .filter(|body| !body.is_empty());
    let config = Config::from_env()?;
    let app = router(Arc::new(AppState::new(config)?));

    let mut builder = Request::builder()
        .method(method.as_str())
        .uri(&uri)
        .header("authorization", format!("Bearer {token}"));
    let request_body = match body {
        Some(body) => {
            builder = builder
                .header("content-type", "application/json")
                .header("cookie", "csrf_token=synthetic-parity-csrf")
                .header("x-csrf-token", "synthetic-parity-csrf");
            Body::from(body)
        }
        None => Body::empty(),
    };

    let response = app.oneshot(builder.body(request_body)?).await?;
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 4 * 1024 * 1024).await?;
    let data: serde_json::Value = serde_json::from_slice(&bytes)?;
    println!("{}", serde_json::json!({"status": status, "body": data}));
    Ok(())
}