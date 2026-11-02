//! Native HTTP auth contract against the canonical application PostgreSQL schema.
use axum::{
    body::{to_bytes, Body},
    http::Request,
    Router,
};
use comicpile_roll_service::{config::Config, router, AppState};
use serde_json::{json, Value};
use std::sync::Arc;
use tower::ServiceExt;

async fn login(
    app: &Router,
    username: &str,
    password: &str,
) -> Result<Value, Box<dyn std::error::Error>> {
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/auth/login")
                .header("content-type", "application/json")
                .header("x-forwarded-for", "198.51.100.51")
                .body(Body::from(
                    json!({"username": username, "password": password}).to_string(),
                ))?,
        )
        .await?;
    let status = response.status().as_u16();
    let body: Value = serde_json::from_slice(&to_bytes(response.into_body(), 8192).await?)?;
    Ok(json!({
        "status": status,
        "detail": body.get("detail"),
        "token_issued": body.get("access_token").and_then(Value::as_str).is_some(),
    }))
}

async fn register(
    app: &Router,
    username: &str,
    email: &str,
    password: &str,
) -> Result<Value, Box<dyn std::error::Error>> {
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/auth/register")
                .header("content-type", "application/json")
                .header("x-forwarded-for", "198.51.100.52")
                .body(Body::from(
                    json!({"username": username, "email": email, "password": password}).to_string(),
                ))?,
        )
        .await?;
    let status = response.status().as_u16();
    let body: Value = serde_json::from_slice(&to_bytes(response.into_body(), 8192).await?)?;
    Ok(json!({
        "status": status,
        "detail": body.get("detail"),
        "token_issued": body.get("access_token").and_then(Value::as_str).is_some(),
    }))
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let username = std::env::var("RUST_ROLL_TEST_USERNAME")?;
    let password = std::env::var("RUST_ROLL_TEST_PASSWORD")?;
    let register_username = std::env::var("RUST_ROLL_TEST_REGISTER_USERNAME")?;
    let register_email = std::env::var("RUST_ROLL_TEST_REGISTER_EMAIL")?;
    let register_password = std::env::var("RUST_ROLL_TEST_REGISTER_PASSWORD")?;
    let app = router(Arc::new(AppState::new(Config::from_env()?)?));

    // The canonical application schema has users.created_at NOT NULL with no
    // server default. Registration must write it explicitly; a handcrafted test
    // table with DEFAULT NOW() previously masked the production 500.
    let registration = register(
        &app,
        &register_username,
        &register_email,
        &register_password,
    )
    .await?;
    let registered_valid = login(&app, &register_username, &register_password).await?;

    // Exercise successful auth and BOTH rejected paths in one process.
    let valid = login(&app, &username, &password).await?;
    let wrong_password = login(&app, &username, "wrong-password-for-test").await?;
    let unknown_user = login(
        &app,
        "does-not-exist-auth-parity",
        "wrong-password-for-test",
    )
    .await?;
    println!(
        "{}",
        json!({
            "register": registration,
            "registered_valid": registered_valid,
            "valid": valid,
            "wrong_password": wrong_password,
            "unknown_user": unknown_user,
        })
    );
    Ok(())
}
