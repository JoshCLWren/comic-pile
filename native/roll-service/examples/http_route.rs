#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Generic single-request HTTP regression runner for SQL budget parity.
//!
//! One binary covers every mounted native v2 operation so the parity suite can
//! exercise an exact method/path without one Cargo example per route.
//!
//! Environment:
//! * `RUST_ROLL_TEST_METHOD` — HTTP method (defaults to `GET`).
//! * `RUST_ROLL_TEST_URI` — exact request URI, including any query string.
//! * `RUST_ROLL_TEST_TOKEN` — optional bearer access token.
//! * `RUST_ROLL_TEST_BODY` — optional JSON request body.
//! * `RUST_ROLL_TEST_COOKIE` — optional Cookie header (defaults to a synthetic
//!   double-submit CSRF cookie).
//! * `RUST_ROLL_TEST_CSRF` — optional `x-csrf-token` header (defaults to the
//!   synthetic CSRF value).
//! * `RUST_ROLL_TEST_REPEAT` — optional number of extra copies of the same
//!   request issued sequentially after the first. The parity negative controls
//!   use this to demonstrate that data-dependent N+1 work fails the declared
//!   budget; ordinary measurements leave it at `1`.
use axum::{
    body::{to_bytes, Body},
    http::Request,
};
use comicpile_roll_service::{config::Config, router, AppState};
use std::sync::Arc;
use tower::ServiceExt;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let method = std::env::var("RUST_ROLL_TEST_METHOD").unwrap_or_else(|_| "GET".to_string());
    let uri = std::env::var("RUST_ROLL_TEST_URI")?;
    let token = std::env::var("RUST_ROLL_TEST_TOKEN").unwrap_or_default();
    let body = std::env::var("RUST_ROLL_TEST_BODY").unwrap_or_default();
    let cookie = std::env::var("RUST_ROLL_TEST_COOKIE")
        .unwrap_or_else(|_| "csrf_token=synthetic-parity-csrf".to_string());
    let csrf = std::env::var("RUST_ROLL_TEST_CSRF")
        .unwrap_or_else(|_| "synthetic-parity-csrf".to_string());
    let repeat = std::env::var("RUST_ROLL_TEST_REPEAT")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(1)
        .max(1);
    let config = Config::from_env()?;
    let app = router(Arc::new(AppState::new(config)?));
    let mut statuses = Vec::with_capacity(repeat);
    let mut last_body = serde_json::Value::Null;
    let mut last_bytes = 0;
    for _ in 0..repeat {
        let mut builder = Request::builder()
            .method(method.as_str())
            .uri(&uri)
            .header("cookie", &cookie)
            .header("x-csrf-token", &csrf);
        if !token.is_empty() {
            builder = builder.header("authorization", format!("Bearer {token}"));
        }
        if !body.is_empty() {
            builder = builder.header("content-type", "application/json");
        }
        let response = app
            .clone()
            .oneshot(builder.body(Body::from(body.clone()))?)
            .await?;
        let status = response.status().as_u16();
        let bytes = to_bytes(response.into_body(), 8 * 1024 * 1024).await?;
        last_bytes = bytes.len();
        last_body = serde_json::from_slice(&bytes).unwrap_or_else(
            |_| serde_json::json!({"raw": String::from_utf8_lossy(&bytes).into_owned()}),
        );
        statuses.push(status);
    }
    println!(
        "{}",
        serde_json::json!({
            "status": statuses.first().copied().unwrap_or(0),
            "statuses": statuses,
            "body": last_body,
            "response_bytes": last_bytes
        })
    );
    Ok(())
}
