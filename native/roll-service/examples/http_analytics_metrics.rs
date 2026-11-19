#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Disposable-schema HTTP regression runner for native v2 analytics metrics.
use axum::{
    body::{to_bytes, Body},
    http::Request,
};
use comicpile_roll_service::{
    analytics::METRICS_STATEMENTS_ISSUED, config::Config, router, AppState,
};
use std::sync::{atomic::Ordering, Arc};
use tower::ServiceExt;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let token = std::env::var("RUST_ROLL_TEST_TOKEN")?;
    let uri = std::env::var("RUST_ROLL_TEST_URI")
        .unwrap_or_else(|_| "/api/v2/analytics/metrics".to_string());
    let config = Config::from_env()?;
    let app = router(Arc::new(AppState::new(config)?));
    let before = METRICS_STATEMENTS_ISSUED.load(Ordering::Relaxed);
    let response = app
        .oneshot(
            Request::builder()
                .method("GET")
                .uri(uri)
                .header("authorization", format!("Bearer {token}"))
                .body(Body::empty())?,
        )
        .await?;
    let statements = METRICS_STATEMENTS_ISSUED.load(Ordering::Relaxed) - before;
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 1024 * 1024).await?;
    let payload_bytes = bytes.len();
    let data: serde_json::Value = serde_json::from_slice(&bytes)?;
    println!(
        "{}",
        serde_json::json!({
            "status": status,
            "body": data,
            "metrics_statements": statements,
            "payload_bytes": payload_bytes
        })
    );
    Ok(())
}
