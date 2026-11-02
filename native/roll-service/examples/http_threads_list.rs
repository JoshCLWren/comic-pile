//! Disposable-schema HTTP regression runner for the native v2 threads collection.
use axum::{
    body::{to_bytes, Body},
    http::Request,
};
use comicpile_roll_service::{config::Config, router, threads::PAGE_STATEMENTS_ISSUED, AppState};
use std::sync::{atomic::Ordering, Arc};
use tower::ServiceExt;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let token = std::env::var("RUST_ROLL_TEST_TOKEN")?;
    let uri = std::env::var("RUST_ROLL_TEST_URI").unwrap_or_else(|_| "/api/v2/threads".to_string());
    let config = Config::from_env()?;
    let app = router(Arc::new(AppState::new(config)?));
    let before = PAGE_STATEMENTS_ISSUED.load(Ordering::Relaxed);
    let response = app
        .oneshot(
            Request::builder()
                .method("GET")
                .uri(uri)
                .header("authorization", format!("Bearer {token}"))
                .body(Body::empty())?,
        )
        .await?;
    let statements = PAGE_STATEMENTS_ISSUED.load(Ordering::Relaxed) - before;
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 4 * 1024 * 1024).await?;
    let data: serde_json::Value = serde_json::from_slice(&bytes)?;
    println!(
        "{}",
        serde_json::json!({"status": status, "body": data, "page_statements": statements})
    );
    Ok(())
}
