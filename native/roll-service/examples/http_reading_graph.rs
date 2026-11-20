#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Disposable-schema HTTP regression runner for native v2 reading-graph operations.
use axum::{
    body::{to_bytes, Body},
    http::Request,
};
use comicpile_roll_service::{config::Config, router, AppState};
use std::sync::Arc;
use tower::ServiceExt;

/// Deliberately extend the measured request with controlled regression SQL.
/// This exists only in the disposable HTTP example, never in the service router.
async fn inject_controlled_queries() -> Result<(), Box<dyn std::error::Error>> {
    let mode = std::env::var("RUST_ROLL_TEST_QUERY_INJECTION").unwrap_or_default();
    if mode.is_empty() {
        return Ok(());
    }
    let database_url = std::env::var("RUST_ROLL_DATABASE_URL")?;
    let (client, connection) =
        tokio_postgres::connect(&database_url, tokio_postgres::NoTls).await?;
    let connection_task = tokio::spawn(connection);
    match mode.as_str() {
        "extra" => {
            client.simple_query("SELECT 1").await?;
        }
        "per-row" => {
            let rows = client.query("SELECT id FROM issues ORDER BY id", &[]).await?;
            for row in rows {
                let issue_id: i32 = row.get(0);
                client
                    .execute("SELECT id FROM issues WHERE id=$1", &[&issue_id])
                    .await?;
            }
        }
        _ => return Err(format!("unknown query injection mode: {mode}").into()),
    }
    drop(client);
    connection_task.await??;
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let token = std::env::var("RUST_ROLL_TEST_TOKEN")?;
    let method = std::env::var("RUST_ROLL_TEST_METHOD").unwrap_or_else(|_| "GET".to_string());
    let uri =
        std::env::var("RUST_ROLL_TEST_URI").unwrap_or_else(|_| "/api/v2/reading-graph".to_string());
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
    }
    let response = app.oneshot(builder.body(Body::from(body))?).await?;
    let status = response.status().as_u16();
    let bytes = to_bytes(response.into_body(), 4 * 1024 * 1024).await?;
    let data: serde_json::Value = serde_json::from_slice(&bytes)?;
    inject_controlled_queries().await?;
    println!("{}", serde_json::json!({"status": status, "body": data}));
    Ok(())
}
