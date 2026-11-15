#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Disposable-schema HTTP regression runner for native continuity-plan routes.
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
    let uri = std::env::var("RUST_ROLL_TEST_URI")?;
    let method = std::env::var("RUST_ROLL_TEST_METHOD").unwrap_or_else(|_| "GET".to_string());
    let body = std::env::var("RUST_ROLL_TEST_BODY").unwrap_or_default();
    let config = Config::from_env()?;
    let app = router(Arc::new(AppState::new(config)?));

    let mut builder = Request::builder()
        .method(method.as_str())
        .uri(&uri)
        .header("authorization", format!("Bearer {token}"));
    let request = if method.eq_ignore_ascii_case("GET") || body.is_empty() {
        builder.body(Body::empty())?
    } else {
        builder = builder
            .header("content-type", "application/json")
            .header("cookie", "csrf_token=synthetic-parity-csrf")
            .header("x-csrf-token", "synthetic-parity-csrf");
        builder.body(Body::from(body))?
    };

    let response = app.oneshot(request).await?;
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 4 * 1024 * 1024).await?;
    let data: serde_json::Value = serde_json::from_slice(&bytes)?;
    println!("{}", serde_json::json!({"status": status, "body": data}));
    Ok(())
}
