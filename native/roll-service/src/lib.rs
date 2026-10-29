//! Native Roll service with authenticated GET bootstrap and owner-scoped PostgreSQL access.
pub mod auth;
pub mod bootstrap;
pub mod config;
pub mod db;
pub mod option_inputs;
pub mod reading_constraints;
pub mod reading_inputs;
pub mod reading_session;
mod session_bandwidth;

use axum::{
    extract::{Request, State},
    http::StatusCode,
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::get,
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
            .map_err(|_| ConfigError("pool configuration failed"))?;
        Ok(Self {
            pool,
            jwt_secret: config.jwt_secret,
            request_timeout: config.request_timeout,
        })
    }
}

/// Serve until shutdown, drain active requests, and bound even stalled connections.
pub async fn serve(
    listener: tokio::net::TcpListener,
    app: Router,
    state: Arc<AppState>,
    shutdown: impl Future<Output = ()> + Send + 'static,
) -> Result<(), &'static str> {
    let drain_timeout = state.request_timeout + Duration::from_secs(1);
    let (shutdown_send, mut shutdown_receive) = tokio::sync::watch::channel(false);
    let signal_task = tokio::spawn(async move {
        shutdown.await;
        let _ = shutdown_send.send(true);
    });
    let mut graceful_receive = shutdown_receive.clone();
    let server = axum::serve(listener, app)
        .with_graceful_shutdown(async move {
            let _ = graceful_receive.changed().await;
        })
        .into_future();
    tokio::pin!(server);
    let result = tokio::select! {
        result = &mut server => result.map_err(|_| "HTTP server failed"),
        _ = shutdown_receive.changed() => {
            match tokio::time::timeout(drain_timeout, &mut server).await {
                Ok(result) => result.map_err(|_| "HTTP server failed"),
                Err(_) => Err("shutdown drain deadline exceeded"),
            }
        }
    };
    signal_task.abort();
    state.pool.close();
    result
}

/// Python-compatible JSON detail boundary; never serialize a dependency error.
pub struct ApiError(pub StatusCode, pub &'static str);
#[derive(Serialize)]
struct ErrorBody {
    detail: &'static str,
}
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        if self.0 == StatusCode::SERVICE_UNAVAILABLE && self.1 == "Database temporarily unavailable"
        {
            return (
                self.0,
                [("Retry-After", "30")],
                Json(serde_json::json!({"error": {
                    "code": "database_unavailable",
                    "message": "Database temporarily unavailable. Please retry.",
                    "status": "SERVICE_UNAVAILABLE"
                }})),
            )
                .into_response();
        }
        let mut response = (self.0, Json(ErrorBody { detail: self.1 })).into_response();
        if self.0 == StatusCode::UNAUTHORIZED {
            response.headers_mut().insert(
                axum::http::header::WWW_AUTHENTICATE,
                axum::http::HeaderValue::from_static("Bearer"),
            );
        }
        response
    }
}

async fn bound_request(
    State(state): State<Arc<AppState>>,
    request: Request,
    next: Next,
) -> Response {
    let method = request.method().clone();
    let started = Instant::now();
    let response = tokio::time::timeout(state.request_timeout, next.run(request))
        .await
        .unwrap_or_else(|_| {
            ApiError(StatusCode::SERVICE_UNAVAILABLE, "Request timed out").into_response()
        });
    // No URI, query, headers, credentials, SQL or upstream error strings in request logs.
    tracing::info!(method = %method, status = response.status().as_u16(), elapsed_ms = started.elapsed().as_millis() as u64, "request completed");
    response
}

/// Mount health and bootstrap routes; no partial-success fallback.
pub fn router(state: Arc<AppState>) -> Router {
    Router::new()
        .route(
            "/health",
            get(|| async { Json(serde_json::json!({"status": "ok"})) }),
        )
        .route(
            "/api/v2/roll/bootstrap",
            get(bootstrap::bootstrap_v2),
        )
        .fallback(|| async { ApiError(StatusCode::NOT_FOUND, "Not Found") })
        .method_not_allowed_fallback(|| async {
            ApiError(StatusCode::METHOD_NOT_ALLOWED, "Method Not Allowed")
        })
        .layer(middleware::from_fn_with_state(state.clone(), bound_request))
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::{to_bytes, Body};
    use tower::ServiceExt;

    #[tokio::test]
    async fn timeout_cancels_work_and_returns_json() {
        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            "RUST_ROLL_REQUEST_TIMEOUT_MS" => Some("10".into()),
            _ => None,
        })
        .unwrap();
        let state = Arc::new(AppState::new(config).unwrap());
        let app = Router::new()
            .route(
                "/slow",
                get(|| async {
                    tokio::time::sleep(Duration::from_secs(10)).await;
                    "unexpected success"
                }),
            )
            .layer(middleware::from_fn_with_state(state, bound_request));
        let response = app
            .oneshot(Request::builder().uri("/slow").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(
            to_bytes(response.into_body(), 4096).await.unwrap(),
            r#"{"detail":"Request timed out"}"#
        );
    }
}
