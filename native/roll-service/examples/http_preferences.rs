//! Disposable-schema HTTP regression runner for the native same-path
//! preferences and Taste Bank signal operations (#4834).
//!
//! Environment:
//! * `RUST_ROLL_TEST_TOKEN` — bearer token to present (omit for an
//!   unauthenticated probe, then pass `RUST_ROLL_TEST_TOKEN=`).
//! * `RUST_ROLL_TEST_METHOD` — HTTP method (`GET`, `PATCH`, `PUT`).
//! * `RUST_ROLL_TEST_URI` — request URI (defaults to the preferences GET).
//! * `RUST_ROLL_TEST_BODY` — optional JSON request body.
use axum::{
    body::{to_bytes, Body},
    http::Request,
};
use comicpile_roll_service::{
    config::Config,
    preferences::{PREFERENCES_STATEMENTS_ISSUED, TASTE_STATEMENTS_ISSUED},
    router, AppState,
};
use std::sync::{atomic::Ordering, Arc};
use tower::ServiceExt;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let token = std::env::var("RUST_ROLL_TEST_TOKEN").unwrap_or_default();
    let method = std::env::var("RUST_ROLL_TEST_METHOD").unwrap_or_else(|_| "GET".to_string());
    let uri = std::env::var("RUST_ROLL_TEST_URI")
        .unwrap_or_else(|_| "/api/v1/users/me/preferences".to_string());
    let body = std::env::var("RUST_ROLL_TEST_BODY").unwrap_or_default();
    let config = Config::from_env()?;
    let app = router(Arc::new(AppState::new(config)?));
    let preferences_before = PREFERENCES_STATEMENTS_ISSUED.load(Ordering::Relaxed);
    let taste_before = TASTE_STATEMENTS_ISSUED.load(Ordering::Relaxed);
    let mut builder = Request::builder()
        .method(method.as_str())
        .uri(uri)
        .header("cookie", "csrf_token=synthetic-parity-csrf")
        .header("x-csrf-token", "synthetic-parity-csrf");
    if !token.is_empty() {
        builder = builder.header("authorization", format!("Bearer {token}"));
    }
    if !body.is_empty() {
        builder = builder.header("content-type", "application/json");
    }
    let response = app.oneshot(builder.body(Body::from(body))?).await?;
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 1024 * 1024).await?;
    let payload_bytes = bytes.len();
    // Axum's Json extractor rejects malformed bodies with plain text rather
    // than JSON; surface that text instead of failing the runner so the
    // parity test can still assert the rejection status.
    let data: serde_json::Value = serde_json::from_slice(&bytes).unwrap_or_else(
        |_| serde_json::json!({"raw": String::from_utf8_lossy(&bytes).into_owned()}),
    );
    println!(
        "{}",
        serde_json::json!({
            "status": status,
            "body": data,
            "preferences_statements": PREFERENCES_STATEMENTS_ISSUED.load(Ordering::Relaxed) - preferences_before,
            "taste_statements": TASTE_STATEMENTS_ISSUED.load(Ordering::Relaxed) - taste_before,
            "payload_bytes": payload_bytes
        })
    );
    Ok(())
}
