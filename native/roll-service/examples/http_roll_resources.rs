//! Disposable-schema HTTP regression runner for the scoped native v2 Roll
//! resources: the die state and the ordered eligible issue identifiers.
use axum::{
    body::{to_bytes, Body},
    http::Request,
};
use comicpile_roll_service::{
    config::Config,
    roll_resources::{DIE_STATEMENTS_ISSUED, ELIGIBLE_STATEMENTS_ISSUED},
    router, AppState,
};
use std::sync::{atomic::Ordering, Arc};
use tower::ServiceExt;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let token = std::env::var("RUST_ROLL_TEST_TOKEN")?;
    let uri = std::env::var("RUST_ROLL_TEST_URI")
        .unwrap_or_else(|_| "/api/v2/roll/eligible-issue-ids".to_string());
    let config = Config::from_env()?;
    let app = router(Arc::new(AppState::new(config)?));
    let die_before = DIE_STATEMENTS_ISSUED.load(Ordering::Relaxed);
    let eligible_before = ELIGIBLE_STATEMENTS_ISSUED.load(Ordering::Relaxed);
    let response = app
        .oneshot(
            Request::builder()
                .method("GET")
                .uri(&uri)
                .header("authorization", format!("Bearer {token}"))
                .body(Body::empty())?,
        )
        .await?;
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 4 * 1024 * 1024).await?;
    let data: serde_json::Value = serde_json::from_slice(&bytes)?;
    println!(
        "{}",
        serde_json::json!({
            "status": status,
            "body": data,
            "die_statements": DIE_STATEMENTS_ISSUED.load(Ordering::Relaxed) - die_before,
            "eligible_statements": ELIGIBLE_STATEMENTS_ISSUED.load(Ordering::Relaxed)
                - eligible_before
        })
    );
    Ok(())
}
