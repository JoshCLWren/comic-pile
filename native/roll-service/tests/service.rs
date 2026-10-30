//! Real router and configuration regressions, with no live database required.
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use comicpile_roll_service::{
    config::{Config, Environment},
    router, AppState,
};
use std::{collections::HashMap, sync::Arc, time::Duration};
use tower::ServiceExt;

fn values() -> HashMap<&'static str, String> {
    HashMap::from([
        (
            "RUST_ROLL_DATABASE_URL",
            "postgresql://synthetic:private-password@127.0.0.1:1/unused?sslmode=disable".into(),
        ),
        (
            "RUST_ROLL_JWT_SECRET",
            "synthetic-private-jwt-secret".into(),
        ),
    ])
}
fn config() -> Config {
    let values = values();
    Config::from_lookup(|key| values.get(key).cloned()).unwrap()
}

#[test]
fn local_defaults_are_bounded_and_credentials_are_required() {
    let config = config();
    assert_eq!(config.environment, Environment::Development);
    assert!(config.bind.ip().is_loopback());
    assert_eq!(config.pool_size, 4);
    assert_eq!(config.pool_timeout, Duration::from_secs(2));
    assert_eq!(config.request_timeout, Duration::from_secs(10));
    assert!(!config.jwt_secret.as_bytes().is_empty());
    for key in ["RUST_ROLL_DATABASE_URL", "RUST_ROLL_JWT_SECRET"] {
        let mut values = values();
        values.remove(key);
        assert!(Config::from_lookup(|key| values.get(key).cloned()).is_err());
    }
}

#[test]
fn configuration_errors_never_echo_secret_values() {
    for (key, invalid) in [
        ("RUST_ROLL_DATABASE_URL", "private-password-invalid-url"),
        ("RUST_ROLL_BIND", "private-bind-secret"),
        ("RUST_ROLL_LOG", "[private-log-secret"),
        ("RUST_ROLL_POOL_SIZE", "private-size-secret"),
    ] {
        let mut values = values();
        values.insert(key, invalid.into());
        let error = Config::from_lookup(|key| values.get(key).cloned())
            .err()
            .unwrap();
        assert!(!format!("{error:?} {error}").contains(invalid));
    }
}

#[test]
fn reject_unbounded_settings_and_public_development_binding() {
    for (key, invalid) in [
        ("RUST_ROLL_POOL_SIZE", "0"),
        ("RUST_ROLL_POOL_SIZE", "33"),
        ("RUST_ROLL_POOL_TIMEOUT_MS", "30001"),
        ("RUST_ROLL_REQUEST_TIMEOUT_MS", "60001"),
        ("RUST_ROLL_REQUEST_TIMEOUT_MS", "0"),
        ("RUST_ROLL_BIND", "0.0.0.0:8010"),
        ("RUST_ROLL_ENV", "prodution"),
    ] {
        let mut values = values();
        values.insert(key, invalid.into());
        assert!(
            Config::from_lookup(|key| values.get(key).cloned()).is_err(),
            "{key}"
        );
    }
}

#[test]
fn public_production_binding_requires_verified_tls_transport() {
    let mut values = values();
    values.insert("RUST_ROLL_ENV", "production".into());
    values.insert("RUST_ROLL_BIND", "0.0.0.0:8010".into());
    assert!(Config::from_lookup(|key| values.get(key).cloned()).is_err());
    values.insert(
        "RUST_ROLL_DATABASE_URL",
        "postgresql://synthetic:secret@localhost/unused?sslmode=require".into(),
    );
    assert!(Config::from_lookup(|key| values.get(key).cloned()).is_ok());
}

#[tokio::test]
async fn health_and_error_envelopes_work_without_database_checkout() {
    let state = Arc::new(AppState::new(config()).unwrap());
    let app = router(state.clone());
    for (method, path, status, expected) in [
        (
            "GET",
            "/health",
            StatusCode::OK,
            serde_json::json!({"status": "ok"}),
        ),
        (
            "GET",
            "/unknown?token=private",
            StatusCode::NOT_FOUND,
            serde_json::json!({"detail": "Not Found"}),
        ),
        (
            "GET",
            "/api/v2/roll/bootstrap",
            StatusCode::UNAUTHORIZED,
            serde_json::json!({"detail": "Not authenticated"}),
        ),
        (
            "POST",
            "/health",
            StatusCode::METHOD_NOT_ALLOWED,
            serde_json::json!({"detail": "Method Not Allowed"}),
        ),
    ] {
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .method(method)
                    .uri(path)
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), status);
        assert_eq!(response.headers()["content-type"], "application/json");
        let body = to_bytes(response.into_body(), 4096).await.unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&body).unwrap(),
            expected
        );
    }
    assert_eq!(state.pool.status().size, 0);
    state.pool.close();
    assert!(state.pool.get().await.is_err());
}

#[tokio::test]
async fn stalled_database_handshake_hits_configured_create_timeout() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let handshake = tokio::spawn(async move {
        let (_connection, _) = listener.accept().await.unwrap();
        std::future::pending::<()>().await;
    });
    let mut config = config();
    config.database = format!("postgresql://synthetic:secret@{address}/unused?sslmode=disable")
        .parse()
        .unwrap();
    config.pool_timeout = Duration::from_millis(50);
    let state = AppState::new(config).unwrap();
    let started = std::time::Instant::now();
    let result = tokio::time::timeout(Duration::from_secs(1), state.pool.get())
        .await
        .unwrap();
    assert!(matches!(
        result,
        Err(deadpool_postgres::PoolError::Timeout(
            deadpool_postgres::TimeoutType::Create
        ))
    ));
    assert!(started.elapsed() >= Duration::from_millis(40));
    assert!(started.elapsed() < Duration::from_secs(1));
    assert_eq!(state.pool.status().size, 0);
    handshake.abort();
}
