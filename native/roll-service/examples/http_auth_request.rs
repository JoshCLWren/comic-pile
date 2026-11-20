#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Disposable-schema HTTP regression runner for the native v2 first-party
//! authentication endpoints (#5147).
//!
//! One process performs exactly one authenticated HTTP request so the
//! `pg_stat_statements` delta around it is the route's own statement budget.
//! The request shape comes from the environment, so registration, token
//! refresh, logout, current-user, password recovery and password completion
//! share this runner without any of them borrowing another route's session.
use axum::{
    body::{to_bytes, Body},
    http::{header, Request},
};
use comicpile_roll_service::{config::Config, router, AppState};
use std::sync::Arc;
use tower::ServiceExt;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let method = std::env::var("RUST_ROLL_TEST_METHOD").unwrap_or_else(|_| "GET".to_string());
    let uri = std::env::var("RUST_ROLL_TEST_URI")?;
    let body = std::env::var("RUST_ROLL_TEST_BODY").unwrap_or_default();
    let config = Config::from_env()?;
    let app = router(Arc::new(AppState::new(config)?));
    let mut builder = Request::builder().method(method.as_str()).uri(&uri);
    if let Ok(token) = std::env::var("RUST_ROLL_TEST_TOKEN") {
        builder = builder.header(header::AUTHORIZATION, format!("Bearer {token}"));
    }
    if let Ok(csrf) = std::env::var("RUST_ROLL_TEST_CSRF") {
        // Double-submit pair for the cookie-authenticated logout request.
        builder = builder.header(header::COOKIE, format!("csrf_token={csrf}"));
        builder = builder.header("x-csrf-token", csrf);
    }
    let request = if body.is_empty() {
        builder.body(Body::empty())?
    } else {
        builder
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(body))?
    };
    let response = app.oneshot(request).await?;
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 4 * 1024 * 1024).await?;
    let data: serde_json::Value = serde_json::from_slice(&bytes)?;
    println!("{}", serde_json::json!({"status": status, "body": data}));
    Ok(())
}
