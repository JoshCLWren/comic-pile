//! Vercel's official Rust Function bridge for the Roll cutover.
//! The diagnostic route proves native ingress before the bootstrap response is switched.
//! Other /api routes must continue to use Python until their individual cutovers.
use axum::{routing::get, Json};
use comicpile_roll_service::{config::Config, router, AppState};
use std::sync::Arc;
use tower::ServiceBuilder;
use vercel_runtime::{axum::VercelLayer, Error};

fn production_postgres_url(url: String) -> String {
    // Python supports both SQLAlchemy PostgreSQL dialects; tokio-postgres does not.
    let url = if let Some(rest) = url.strip_prefix("postgresql+asyncpg://") {
        format!("postgresql://{rest}")
    } else if let Some(rest) = url.strip_prefix("postgresql+psycopg://") {
        format!("postgresql://{rest}")
    } else {
        url
    };
    // The native production pool must not silently drop TLS.
    if url
        .split_once('?')
        .is_some_and(|(_, query)| query.split('&').any(|part| part.starts_with("sslmode=")))
    {
        url
    } else if url.contains('?') {
        format!("{url}&sslmode=require")
    } else {
        format!("{url}?sslmode=require")
    }
}

fn config() -> Result<Config, comicpile_roll_service::config::ConfigError> {
    Config::from_lookup(|name| match name {
        "RUST_ROLL_ENV" => std::env::var(name)
            .ok()
            .or_else(|| Some("production".into())),
        "RUST_ROLL_DATABASE_URL" => std::env::var(name)
            .ok()
            .or_else(|| std::env::var("DATABASE_URL").ok())
            .map(production_postgres_url),
        // Python's signed access tokens use SECRET_KEY, not JWT_SECRET.
        "RUST_ROLL_JWT_SECRET" => std::env::var(name)
            .ok()
            .or_else(|| std::env::var("SECRET_KEY").ok()),
        _ => std::env::var(name).ok(),
    })
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    let state = Arc::new(AppState::new(config()?)?);
    // This route is a native runtime probe, NOT the migrated Roll bootstrap.
    // Do not route GET /api/v2/roll/bootstrap here until its full handler exists.
    let app = router(state).route(
        "/api/_native_roll/health",
        get(|| async {
            Json(serde_json::json!({
                "status": "ok",
                "runtime": "rust",
                "service": "roll"
            }))
        }),
    );
    vercel_runtime::run(ServiceBuilder::new().layer(VercelLayer::new()).service(app)).await
}

#[cfg(test)]
mod tests {
    use super::production_postgres_url;

    #[test]
    fn native_postgres_url_enforces_tls_and_normalizes_sqlalchemy_dialect() {
        assert_eq!(
            production_postgres_url("postgresql+asyncpg://localhost/db".into()),
            "postgresql://localhost/db?sslmode=require"
        );
        assert_eq!(
            production_postgres_url("postgresql+psycopg://localhost/db".into()),
            "postgresql://localhost/db?sslmode=require"
        );
        assert_eq!(
            production_postgres_url("postgresql://localhost/db?application_name=roll".into()),
            "postgresql://localhost/db?application_name=roll&sslmode=require"
        );
        assert_eq!(
            production_postgres_url("postgresql://localhost/db?sslmode=require".into()),
            "postgresql://localhost/db?sslmode=require"
        );
    }
}
