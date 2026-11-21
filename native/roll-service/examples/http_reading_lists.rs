#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Disposable-schema HTTP regression runner for native v2 reading-list operations.
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
    let uri =
        std::env::var("RUST_ROLL_TEST_URI").unwrap_or_else(|_| "/api/v2/reading-lists".to_string());
    let body = std::env::var("RUST_ROLL_TEST_BODY").unwrap_or_default();
    let config = Config::from_env()?;
    let app = router(Arc::new(AppState::new(config)?));
    let mut builder = Request::builder()
        .method(method.as_str())
        .uri(uri)
        .header("authorization", format!("Bearer {token}"));
    if method != "GET" && !body.is_empty() {
        builder = builder
            .header("content-type", "application/json")
            .header("cookie", "csrf_token=synthetic-parity-csrf")
            .header("x-csrf-token", "synthetic-parity-csrf");
    } else if method != "GET" {
        builder = builder
            .header("cookie", "csrf_token=synthetic-parity-csrf")
            .header("x-csrf-token", "synthetic-parity-csrf");
    }
    let response = app.oneshot(builder.body(Body::from(body))?).await?;
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 4 * 1024 * 1024).await?;
    let data: serde_json::Value =
        serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null);
    println!("{}", serde_json::json!({"status": status, "body": data}));
    Ok(())
}
