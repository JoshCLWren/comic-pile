//! Disposable-schema HTTP regression runner for the real native Roll router.
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
    let config = Config::from_env()?;
    let app = router(Arc::new(AppState::new(config)?));
    let initialization = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v2/reading-sessions")
                .header("authorization", format!("Bearer {token}"))
                .header("content-type", "application/json")
                .header("cookie", "csrf_token=synthetic-parity-csrf")
                .header("x-csrf-token", "synthetic-parity-csrf")
                .body(Body::from(r#"{"timezone":"America/Chicago"}"#))?,
        )
        .await?;
    if !initialization.status().is_success() {
        let status = initialization.status().as_u16();
        let bytes = to_bytes(initialization.into_body(), 2 * 1024 * 1024).await?;
        let data: serde_json::Value = serde_json::from_slice(&bytes)?;
        println!("{}", serde_json::json!({"status":status,"body":data}));
        return Ok(());
    }
    let response = app
        .oneshot(
            Request::builder()
                .uri("/api/v2/roll/bootstrap?timezone=America%2FChicago")
                .header("authorization", format!("Bearer {token}"))
                .body(Body::empty())?,
        )
        .await?;
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 2 * 1024 * 1024).await?;
    let data: serde_json::Value = serde_json::from_slice(&bytes)?;
    println!("{}", serde_json::json!({"status":status,"body":data}));
    Ok(())
}
