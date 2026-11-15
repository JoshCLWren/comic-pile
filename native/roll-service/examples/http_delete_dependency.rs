#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Disposable-schema HTTP regression runner for the native delete-dependency endpoint.
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
    let dependency_id = std::env::var("RUST_ROLL_TEST_DEPENDENCY_ID")?;
    let config = Config::from_env()?;
    let app = router(Arc::new(AppState::new(config)?));
    let response = app
        .oneshot(
            Request::builder()
                .method("DELETE")
                .uri(format!("/api/v2/dependencies/{dependency_id}"))
                .header("authorization", format!("Bearer {token}"))
                .header("cookie", "csrf_token=synthetic-parity-csrf")
                .header("x-csrf-token", "synthetic-parity-csrf")
                .body(Body::empty())?,
        )
        .await?;
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 2 * 1024 * 1024).await?;
    let data: serde_json::Value = serde_json::from_slice(&bytes)?;
    println!("{}", serde_json::json!({"status": status, "body": data}));
    Ok(())
}