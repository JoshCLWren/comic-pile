//! Native Queue service with authenticated queue entry resources and owner-scoped PostgreSQL access.
pub mod auth;
pub mod config;
pub mod db;
pub mod queue;

use axum::{
    extract::{Request, State},
    http::StatusCode,
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, patch, post},
    Json, Router,
};
use config::{Config, ConfigError, JwtSecret};
use deadpool_postgres::{Manager, ManagerConfig, Pool, RecyclingMethod, Runtime, Timeouts};
use postgres_native_tls::MakeTlsConnector;
use serde::Serialize;
use std::{
    future::{Future, IntoFuture},
    sync::Arc,
    time::{Duration, Instant},
};

/// Runtime dependencies. Never log this state or its credentials.
pub struct AppState {
    pub pool: Pool,
    pub jwt_secret: JwtSecret,
    pub request_timeout: Duration,
    pub access_token_expire_minutes: i64,
    pub refresh_token_expire_days: i64,
    /// Validate a checked-out socket with a read-only probe before a handler can
    /// use it, replacing one that cannot carry a statement (#4732).
    ///
    /// Production always enables this. The regression suite disables it to prove
    /// the first-statement failure it prevents; no environment variable can.
    pub connection_recovery: bool,
}
impl AppState {
    /// Construct a lazy bounded pool; health/startup never checks out a database connection.
    pub fn new(config: Config) -> Result<Self, ConfigError> {
        let tls = native_tls::TlsConnector::new()
            .map_err(|_| ConfigError("TLS initialization failed"))?;
        let manager = Manager::from_config(
            config.database,
            MakeTlsConnector::new(tls),
            ManagerConfig {
                // `db::checkout` validates the socket with a bounded read-only
                // probe before any handler statement (#4732). Keeping Fast
                // avoids probing twice on every checkout; the centralized probe
                // also classifies and bounds recovery instead of swallowing it.
                recycling_method: RecyclingMethod::Fast,
            },
        );
        let pool = Pool::builder(manager)
            .max_size(config.pool_size)
            .runtime(Runtime::Tokio1)
            .timeouts(Timeouts {
                wait: Some(config.pool_timeout),
                create: Some(config.pool_timeout),
                recycle: Some(config.pool_timeout),
            })
            .build()
            .map_err(|_| ConfigError("database pool construction failed"))?;
        Ok(Self {
            pool,
            jwt_secret: config.jwt_secret,
            request_timeout: config.request_timeout,
            access_token_expire_minutes: config.access_token_expire_minutes,
            refresh_token_expire_days: config.refresh_token_expire_days,
            connection_recovery: config.connection_recovery,
        })
    }
}

/// API error response.
#[derive(Debug, thiserror::Error)]
pub struct ApiError(StatusCode, String);

impl ApiError {
    pub fn new(status: StatusCode, message: String) -> Self {
        Self(status, message)
    }
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.0, self.1)
    }
}

impl axum::response::IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let (status, message) = (self.0, self.1);
        (status, Json(serde_json::json!({ "detail": message }))).into_response()
    }
}

/// Apply CSRF middleware to mutating requests.
///
/// The middleware inspects the request method and path to decide whether to
/// enforce CSRF protection. All mutating requests to the API are protected.
/// Health checks and static assets are not.
pub fn router(state: Arc<AppState>) -> Router {
    use auth::middleware::csrf_middleware;
    Router::new()
        .route(
            "/health",
            get(|| async { Json(serde_json::json!({"status": "ok"})) }),
        )
        .route(
            "/api/v2/health",
            get(|| async { Json(serde_json::json!({"status": "ok"})) }),
        )
        .route("/api/v2/auth/csrf", get(auth::handlers::csrf))
        .route(
            "/api/v2/queue-entries/{thread_id}",
            get(queue::get_queue_entry),
        )
        .route(
            "/api/v2/queue-entries/{thread_id}",
            patch(queue::update_queue_entry),
        )
        .route("/api/v2/queue-orders", post(queue::create_queue_order))
        .layer(middleware::from_fn(csrf_middleware))
}

/// Serve the native Queue service.
///
/// This function sets up the Axum router and starts the HTTP server.
pub async fn serve(
    listener: tokio::net::TcpListener,
    app: Router,
    state: Arc<AppState>,
    shutdown_signal: impl Future<Output = ()> + Send + 'static,
) -> Result<(), &'static str> {
    let graceful = axum::serve::with_graceful_shutdown(listener, app, shutdown_signal)
        .into_make_service_with_connect_info::<std::net::SocketAddr>();
    tracing::info!("native Queue service listening");
    if let Err(error) = axum::serve(graceful, state).await {
        tracing::error!("server error: {error}");
        return Err("server failed");
    }
    Ok(())
}

/// Create a shutdown signal for graceful termination.
///
/// This function returns a future that resolves when the process receives
/// a SIGINT or SIGTERM signal.
pub async fn shutdown_signal() {
    let interrupt = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut signal) => {
                signal.recv().await;
            }
            Err(_) => {
                std::future::pending::<()>().await;
            }
        }
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();
    tokio::select! { _ = interrupt => {}, _ = terminate => {} }
    tracing::info!("draining native Queue requests");
}