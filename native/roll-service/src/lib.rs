//! Native Roll service with authenticated GET bootstrap and owner-scoped PostgreSQL access.
#![cfg_attr(test, allow(clippy::unwrap_used, clippy::expect_used))]

pub mod analytics;
pub mod auth;
pub mod bootstrap;
pub mod bug_reports;
pub mod comicvine_issue;
pub mod comicvine_repair;
pub mod comicvine_resolution;
pub mod config;
pub mod continuity_rules;
pub mod creators;
pub mod db;
pub mod demo;
pub mod dependencies;
pub mod dice_api;
pub mod dice_mutation;
pub mod dice_state;
pub mod dismiss_pending;
pub mod identity_inbox;
pub mod issue_handler;
pub mod issue_mutation;
pub mod issue_read;
pub mod issue_service;
pub mod legacy_dependencies;
pub mod openapi;
pub mod option_inputs;
pub mod preferences;
pub mod queue;
pub mod reading_blocker_projection;
pub mod reading_boundary;
pub mod reading_constraints;
pub mod reading_eligibility;
pub mod reading_graph;
pub mod reading_inputs;
pub mod reading_list;
pub mod reading_mode;
pub mod reading_plan_reader;
pub mod reading_plan_recovery;
pub mod reading_session;
pub mod releases;
pub mod roll_exclusions;
pub mod roll_offer;
pub mod roll_pool;
pub mod roll_reset;
pub mod roll_resources;
mod session_bandwidth;
pub mod session_detail;
pub mod session_history;
pub mod tags;
pub mod taste_discoveries;
pub mod threads;

/// Test scaffolding shared by unit and integration tests.
///
/// Not `#[cfg(test)]` because integration tests link the library without that
/// cfg. Nothing here runs unless a test calls it.
pub mod test_support;

use axum::{
    extract::{Request, State},
    http::StatusCode,
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{delete, get, patch, post, put},
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
    ///
    /// Production uses [`RecyclingMethod::Fast`] and relies on [`db::checkout`]'s bounded
    /// read-only probe for validation so reused connections are checked exactly once (#4732).
    pub fn new(config: Config) -> Result<Self, ConfigError> {
        Self::with_recycling(config, RecyclingMethod::Fast)
    }

    /// Test and operator override for the pool recycling method.
    ///
    /// Production callers should use [`Self::new`]. Negative-control fixtures may select
    /// `RecyclingMethod::Fast` with `connection_recovery` disabled so a fault fires on the
    /// handler's first statement rather than during pool recycling.
    pub fn with_recycling(
        config: Config,
        recycling_method: RecyclingMethod,
    ) -> Result<Self, ConfigError> {
        let tls = native_tls::TlsConnector::new().map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            ConfigError("TLS initialization failed")
        })?;
        let manager = Manager::from_config(
            config.database,
            MakeTlsConnector::new(tls),
            ManagerConfig { recycling_method },
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
            .map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                ConfigError("pool configuration failed")
            })?;
        Ok(Self {
            pool,
            jwt_secret: config.jwt_secret,
            request_timeout: config.request_timeout,
            access_token_expire_minutes: config.access_token_expire_minutes,
            refresh_token_expire_days: config.refresh_token_expire_days,
            connection_recovery: true,
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
        result = &mut server => result.map_err(|e| { tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            ); "HTTP server failed" }),
        _ = shutdown_receive.changed() => {
            match tokio::time::timeout(drain_timeout, &mut server).await {
                Ok(result) => result.map_err(|e| { tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            ); "HTTP server failed" }),
                Err(_) => Err("shutdown drain deadline exceeded"),
            }
        }
    };
    signal_task.abort();
    state.pool.close();
    result
}

/// Python-compatible JSON detail boundary; never serialize a dependency error.
///
/// Typed error taxonomy: behavior branches (Retry-After, deadlock retry) must
/// match on variants, never on message text (#4766). Construct with the
/// most specific variant; `Detail` is the explicit escape hatch for statuses
/// without a dedicated variant. The detail is owned so per-request validation
/// and lookup messages never leak memory through `'static` borrows. Static
/// messages still allocate on the error path, which is bounded by request
/// volume and always freed when the response is sent; it is cheaper than
/// leaking every dynamic message for the life of the process.
#[derive(Debug)]
pub enum ApiError {
    /// 503 with `Retry-After: 30` and the `database_unavailable` envelope.
    DatabaseUnavailable,
    /// A PostgreSQL deadlock victim (`40P01`). Retryable by variant.
    DeadlockDetected,
    /// 503 request deadline was exceeded by the outer middleware.
    RequestTimeout,
    /// Generic 500 (internal/corrupt/projection failure).
    Internal(String),
    /// A PostgreSQL unique violation (`23505`). Retryable by variant.
    UniqueViolation,
    /// Generic 503 for statuses without a dedicated availability variant.
    ServiceUnavailable(String),
    /// 404.
    NotFound(String),
    /// 400.
    BadRequest(String),
    /// 401 (also emits `WWW-Authenticate: Bearer`).
    Unauthorized(String),
    /// 403.
    Forbidden(String),
    /// 409.
    Conflict(String),
    /// 422.
    Unprocessable(String),
    /// 405.
    MethodNotAllowed(String),
    /// Fallback: explicit status + detail for statuses without a variant.
    Detail {
        /// HTTP status to emit.
        status: StatusCode,
        /// Wire detail message.
        detail: String,
    },
}

impl ApiError {
    /// Retryable database-availability error. Always the same variant so the
    /// `Retry-After` header survives message rewording.
    pub fn database_unavailable() -> Self {
        Self::DatabaseUnavailable
    }

    /// Explicit status + detail for statuses without a dedicated variant.
    pub fn with_status(status: StatusCode, detail: impl Into<String>) -> Self {
        Self::Detail {
            status,
            detail: detail.into(),
        }
    }

    /// HTTP status for this error. Branches on the variant, never the message.
    pub fn status(&self) -> StatusCode {
        match self {
            ApiError::DatabaseUnavailable => StatusCode::SERVICE_UNAVAILABLE,
            ApiError::DeadlockDetected => StatusCode::INTERNAL_SERVER_ERROR,
            ApiError::RequestTimeout => StatusCode::SERVICE_UNAVAILABLE,
            ApiError::Internal(_) => StatusCode::INTERNAL_SERVER_ERROR,
            ApiError::UniqueViolation => StatusCode::INTERNAL_SERVER_ERROR,
            ApiError::ServiceUnavailable(_) => StatusCode::SERVICE_UNAVAILABLE,
            ApiError::NotFound(_) => StatusCode::NOT_FOUND,
            ApiError::BadRequest(_) => StatusCode::BAD_REQUEST,
            ApiError::Unauthorized(_) => StatusCode::UNAUTHORIZED,
            ApiError::Forbidden(_) => StatusCode::FORBIDDEN,
            ApiError::Conflict(_) => StatusCode::CONFLICT,
            ApiError::Unprocessable(_) => StatusCode::UNPROCESSABLE_ENTITY,
            ApiError::MethodNotAllowed(_) => StatusCode::METHOD_NOT_ALLOWED,
            ApiError::Detail { status, .. } => *status,
        }
    }

    /// Wire detail for this error. Stable strings are returned as `&'static`
    /// where the variant carries no payload; owned details borrow the payload.
    pub fn detail(&self) -> &str {
        match self {
            ApiError::DatabaseUnavailable => "Database temporarily unavailable",
            ApiError::DeadlockDetected => "Reading session deadlock",
            ApiError::RequestTimeout => "Request timed out",
            ApiError::UniqueViolation => "Internal Server Error",
            ApiError::Internal(detail)
            | ApiError::ServiceUnavailable(detail)
            | ApiError::NotFound(detail)
            | ApiError::BadRequest(detail)
            | ApiError::Unauthorized(detail)
            | ApiError::Forbidden(detail)
            | ApiError::Conflict(detail)
            | ApiError::Unprocessable(detail)
            | ApiError::MethodNotAllowed(detail) => detail.as_str(),
            ApiError::Detail { detail, .. } => detail.as_str(),
        }
    }

    /// True only for the `DatabaseUnavailable` variant (not message text).
    pub fn is_database_unavailable(&self) -> bool {
        matches!(self, ApiError::DatabaseUnavailable)
    }

    /// True only for the `DeadlockDetected` variant (not message text).
    pub fn is_deadlock(&self) -> bool {
        matches!(self, ApiError::DeadlockDetected)
    }

    /// True only for the `UniqueViolation` variant (not message text).
    pub fn is_unique_violation(&self) -> bool {
        matches!(self, ApiError::UniqueViolation)
    }
}

/// Secret-free classification of an error being replaced by a mapped error.
///
/// Logging the `Debug` of a replaced error can carry credential-bearing input
/// (validated password and token values, provider URIs with `api_key`, database
/// URLs, SQL). Log only the error's type name, never its message or payload.
pub fn error_kind<T: ?Sized>(_: &T) -> &'static str {
    std::any::type_name::<T>()
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.detail())
    }
}

impl std::error::Error for ApiError {}

#[derive(Serialize)]
struct ErrorBody<'a> {
    detail: &'a str,
}
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        if self.is_database_unavailable() {
            return (
                self.status(),
                [("Retry-After", "30")],
                Json(serde_json::json!({"error": {
                    "code": "database_unavailable",
                    "message": "Database temporarily unavailable. Please retry.",
                    "status": "SERVICE_UNAVAILABLE"
                }})),
            )
                .into_response();
        }
        let status = self.status();
        let detail_owned = self.detail().to_string();
        let mut response = (
            status,
            Json(ErrorBody {
                detail: &detail_owned,
            }),
        )
            .into_response();
        if status == StatusCode::UNAUTHORIZED {
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
    // Cron drains are explicitly awaited, and bounded by the Vercel invocation.
    let timeout = if request.uri().path() == "/api/v2/maintenance/comicvine-metadata-repairs" {
        Duration::from_secs(50)
    } else {
        state.request_timeout
    };
    let response = tokio::time::timeout(timeout, next.run(request))
        .await
        .unwrap_or_else(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            ApiError::RequestTimeout.into_response()
        });
    // No URI, query, headers, credentials, SQL or upstream error strings in request logs.
    tracing::info!(method = %method, status = response.status().as_u16(), elapsed_ms = started.elapsed().as_millis() as u64, "request completed");
    response
}

/// Replace Rust's default panic hook in production with a payload-free signal.
///
/// `catch_unwind` invokes the hook *before* returning an error. Without this,
/// a handler panic can return sanitized JSON yet still leak its message, source
/// location, or user content through Vercel's stderr logs. This is process-wide
/// by design and is installed once at the native Rust executable entrypoints.
pub fn install_sanitized_panic_hook() {
    static INSTALL: std::sync::Once = std::sync::Once::new();
    INSTALL.call_once(|| {
        std::panic::set_hook(Box::new(|_| {
            eprintln!("native Rust panic: payload and location redacted");
        }));
    });
}

/// Map a handler panic to the standard 500 JSON body without leaking details.
///
/// The panic payload and location are deliberately never logged: payloads can
/// carry user data or secrets. Only a fixed message is emitted so the failure
/// stays attributable without exposing request content (#4742).
async fn catch_panic(request: Request, next: Next) -> Response {
    let future = next.run(request);
    let mut future = Box::pin(future);
    std::future::poll_fn(|context| {
        match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            future.as_mut().poll(context)
        })) {
            Ok(poll) => poll,
            Err(_) => {
                tracing::error!("request handler panicked");
                std::task::Poll::Ready(
                    ApiError::with_status(
                        StatusCode::INTERNAL_SERVER_ERROR,
                        "Internal Server Error".to_string(),
                    )
                    .into_response(),
                )
            }
        }
    })
    .await
}

/// Mount health and bootstrap routes; no partial-success fallback.
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
        .route("/api/v2/auth/register", post(auth::handlers::register))
        .route("/api/v2/auth/login", post(auth::handlers::login))
        .route("/api/v2/auth/refresh", post(auth::handlers::refresh))
        .route("/api/v2/auth/logout", post(auth::handlers::logout))
        .route("/api/v2/auth/csrf", get(auth::handlers::csrf))
        .route("/api/v2/auth/me", get(auth::handlers::me))
        .route(
            "/api/v2/auth/forgot-password",
            post(auth::handlers::forgot_password),
        )
        .route(
            "/api/v2/auth/reset-password",
            post(auth::handlers::reset_password),
        )
        .route("/api/v1/auth/register", post(auth::handlers::register))
        .route("/api/v1/auth/login", post(auth::handlers::login))
        .route("/api/v1/auth/refresh", post(auth::handlers::refresh))
        .route("/api/v1/auth/logout", post(auth::handlers::logout))
        .route("/api/v1/auth/csrf", get(auth::handlers::csrf))
        .route("/api/v1/auth/me", get(auth::handlers::me))
        .route(
            "/api/v1/auth/forgot-password",
            post(auth::handlers::forgot_password),
        )
        .route(
            "/api/v1/auth/reset-password",
            post(auth::handlers::reset_password),
        )
        .route("/api/auth/register", post(auth::handlers::register))
        .route("/api/auth/login", post(auth::handlers::login))
        .route("/api/auth/refresh", post(auth::handlers::refresh))
        .route("/api/auth/logout", post(auth::handlers::logout))
        .route("/api/auth/csrf", get(auth::handlers::csrf))
        .route("/api/auth/me", get(auth::handlers::me))
        .route(
            "/api/auth/forgot-password",
            post(auth::handlers::forgot_password),
        )
        .route(
            "/api/auth/reset-password",
            post(auth::handlers::reset_password),
        )
        .route(
            "/api/v2/maintenance/comicvine-metadata-repairs",
            get(comicvine_repair::drain),
        )
        .route("/api/v2/roll/bootstrap", get(bootstrap::bootstrap_v2))
        .route("/api/v2/demo-roll", get(demo::read_demo_roll))
        .route("/api/v2/roll/die-state", get(roll_resources::die_state))
        .route(
            "/api/v2/roll/eligible-issue-ids",
            get(roll_resources::eligible_issue_ids),
        )
        .route(
            "/api/v2/reading-sessions",
            post(bootstrap::initialize_session),
        )
        .route(
            "/api/sessions/{session_id}",
            get(session_detail::get_session),
        )
        .route(
            "/api/v1/sessions/{session_id}",
            get(session_detail::get_session),
        )
        .route(
            "/api/sessions/{session_id}/snapshots",
            get(session_history::list_session_snapshots),
        )
        .route(
            "/api/v1/sessions/{session_id}/snapshots",
            get(session_history::list_session_snapshots),
        )
        .route("/api/v2/roll/dice-command", post(dice_api::manual_die))
        .route("/api/v2/roll/offer", post(roll_offer::offer))
        .route("/api/v2/roll/reset", post(roll_reset::reset))
        .route(
            "/api/v2/reading-boundaries",
            post(reading_boundary::reading_boundary_batch_v2),
        )
        .route(
            "/api/v2/queue-entries/{thread_id}",
            get(queue::get_queue_entry),
        )
        .route(
            "/api/v2/queue-entries/{thread_id}",
            patch(queue::update_queue_entry),
        )
        .route("/api/v2/queue-orders", post(queue::create_queue_order))
        .route("/api/v2/threads", get(threads::list_threads))
        .route(
            "/api/v1/threads/{thread_id}",
            get(threads::get_thread_detail),
        )
        .route("/api/threads/{thread_id}", get(threads::get_thread_detail))
        .route(
            "/api/v1/threads/completed/threads",
            get(threads::list_completed_threads),
        )
        .route(
            "/api/v2/reading-lists",
            get(reading_list::list_reading_lists),
        )
        .route(
            "/api/v2/reading-lists",
            post(reading_list::create_reading_list),
        )
        .route(
            "/api/v2/reading-lists/{list_id}",
            get(reading_list::get_reading_list),
        )
        .route(
            "/api/v2/reading-lists/{list_id}",
            put(reading_list::update_reading_list),
        )
        .route(
            "/api/v2/reading-lists/{list_id}",
            delete(reading_list::delete_reading_list),
        )
        .route(
            "/api/v2/reading-lists/{list_id}/reader",
            get(reading_list::read_reading_list),
        )
        .route(
            "/api/v2/continuity-plans/{plan_id}/reader",
            get(reading_plan_reader::read),
        )
        .route(
            "/api/v2/continuity-plans/{plan_id}/recovery",
            get(reading_plan_recovery::preview),
        )
        .route(
            "/api/v2/continuity-plans/{plan_id}/recovery",
            post(reading_plan_recovery::relink),
        )
        .route("/api/v2/reading-graph", get(reading_graph::reading_graph))
        .route("/api/v2/reading-graph/repairs", post(reading_graph::repair))
        .route(
            "/api/v2/dependencies/",
            post(dependencies::create_dependency),
        )
        .route(
            "/api/v2/dependencies/{dependency_id}",
            delete(dependencies::delete_dependency),
        )
        .route(
            "/api/v1/dependencies/blocked",
            get(legacy_dependencies::blocked),
        )
        .route("/api/v1/dependencies/", post(legacy_dependencies::create))
        .route(
            "/api/v1/dependencies/{dependency_id}",
            get(legacy_dependencies::get),
        )
        .route(
            "/api/v1/dependencies/{dependency_id}",
            patch(legacy_dependencies::update),
        )
        .route(
            "/api/v1/dependencies/{dependency_id}",
            delete(legacy_dependencies::delete),
        )
        .route("/api/v2/analytics/metrics", get(analytics::metrics))
        .route("/api/v1/identity-inbox", get(identity_inbox::list_inbox))
        .route(
            "/api/v1/identity-inbox/search/issues",
            get(identity_inbox::search_issues),
        )
        .route(
            "/api/v1/identity-inbox/{mapping_id}",
            get(identity_inbox::get_inbox_item),
        )
        .route(
            "/api/v1/identity-inbox/{mapping_id}/confirm",
            post(identity_inbox::confirm),
        )
        .route(
            "/api/v1/identity-inbox/{mapping_id}/defer",
            post(identity_inbox::defer),
        )
        .route(
            "/api/v1/identity-inbox/{mapping_id}/reject",
            post(identity_inbox::reject),
        )
        .route(
            "/api/v1/identity-inbox/{mapping_id}/skip",
            post(identity_inbox::skip),
        )
        .route(
            "/api/v2/issues/{issue_id}/comicvine",
            get(comicvine_issue::issue_intelligence),
        )
        .route("/api/v1/issues/{issue_id}", get(issue_read::get_issue))
        .route(
            "/api/v1/issues/{issue_id}/comicvine",
            get(comicvine_issue::issue_intelligence),
        )
        .route(
            "/api/v1/comicvine/series/{comicvine_volume_id}/import-status",
            get(comicvine_resolution::series_import_status),
        )
        .route(
            "/api/v1/issues/{issue_id}/dependencies",
            get(issue_read::get_issue_dependencies),
        )
        .route(
            "/api/v1/threads/{thread_id}/issue-dependencies",
            get(issue_read::get_thread_issue_dependencies),
        )
        .route(
            "/api/v1/threads/{thread_id}/dependencies",
            get(dependencies::get_thread_dependencies),
        )
        .route(
            "/api/v1/roll/dismiss-pending",
            post(dismiss_pending::dismiss_pending),
        )
        .route(
            "/api/roll/dismiss-pending",
            post(dismiss_pending::dismiss_pending),
        )
        .route(
            "/api/v1/users/me/preferences",
            get(preferences::get_user_preferences),
        )
        .route(
            "/api/v1/users/me/preferences",
            patch(preferences::patch_user_preferences),
        )
        .route(
            "/api/v1/users/me/taste-signals",
            get(preferences::list_taste_signals),
        )
        .route(
            "/api/v1/users/me/taste-signals/{signal_type}/{external_key}/verdict",
            put(preferences::set_taste_signal_verdict),
        )
        .route(
            "/api/v2/issues/{issue_id}",
            patch(issue_handler::read_rate_issue),
        )
        .route(
            "/api/v2/issues/{issue_id}",
            delete(issue_mutation::delete_issue),
        )
        .route("/api/v2/issues/cards", post(issue_handler::issue_cards))
        .route(
            "/api/v2/threads/{thread_id}/issues",
            post(issue_mutation::create_issues),
        )
        .route(
            "/api/v2/threads/{thread_id}/issue-order",
            put(issue_mutation::reorder_issues),
        )
        .route("/api/v1/creators", get(creators::list_creators))
        .route("/api/v1/creators/", get(creators::list_creators))
        .route("/api/v1/creators/summaries", get(creators::get_summaries))
        .route(
            "/api/v1/continuity-rules/",
            get(continuity_rules::list).post(continuity_rules::create),
        )
        .route(
            "/api/v1/continuity-rules/{rule_id}",
            get(continuity_rules::get)
                .put(continuity_rules::update)
                .delete(continuity_rules::delete),
        )
        .route(
            "/api/v1/taste/discoveries/{signal_id}/dismiss",
            post(taste_discoveries::dismiss_taste_discovery),
        )
        .route("/api/bug-reports/", post(bug_reports::create))
        .route("/api/v1/bug-reports/", post(bug_reports::create))
        .route(
            "/api/v1/releases/",
            get(releases::list).put(releases::publish),
        )
        .route("/api/v1/releases/source", get(releases::reconcile))
        .route("/api/v1/releases/{release_id}", get(releases::get))
        .route(
            "/api/v1/releases/{release_id}/retract",
            post(releases::retract),
        )
        .route("/api/v1/tags/", get(tags::list_tags))
        .route("/api/v1/tags/", post(tags::create_tag))
        .route(
            "/api/v1/tags/effective/issue/{issue_id}/",
            get(tags::effective_for_issue),
        )
        .route(
            "/api/v1/tags/effective/plan/{plan_id}/",
            get(tags::effective_for_plan),
        )
        .route(
            "/api/v1/tags/effective/thread/{thread_id}/",
            get(tags::effective_for_thread),
        )
        .route(
            "/api/v1/tags/effective/thread/{thread_id}/issues/",
            get(tags::thread_issues_effective),
        )
        .route("/api/v1/tags/{tag_id}/", get(tags::get_tag))
        .route("/api/v1/tags/{tag_id}/", put(tags::update_tag))
        .route("/api/v1/tags/{tag_id}/", delete(tags::delete_tag))
        .route("/api/v1/tags/{tag_id}/assign/", post(tags::assign_tag))
        .route(
            "/api/v1/tags/{tag_id}/bulk-assign/",
            post(tags::bulk_assign_tag),
        )
        .route(
            "/api/v1/tags/{tag_id}/bulk-unassign/",
            post(tags::bulk_unassign_tag),
        )
        .route(
            "/api/v1/tags/{tag_id}/unassign/",
            delete(tags::unassign_tag),
        )
        .route("/api/v1/tags/{tag_id}/usage/", get(tags::get_tag_usage))
        .route("/api/v1/reading-mode", get(reading_mode::get_reading_mode))
        .route("/api/v1/reading-mode", post(reading_mode::set_reading_mode))
        .route(
            "/api/v1/reading-mode/dismiss-suggestion",
            post(reading_mode::dismiss_reading_mode_suggestion),
        )
        .route(
            "/api/v1/reading-mode/suggest",
            post(reading_mode::suggest_reading_mode),
        )
        .fallback(|| async { ApiError::NotFound("Not Found".to_string()) })
        .method_not_allowed_fallback(|| async {
            ApiError::MethodNotAllowed("Method Not Allowed".to_string())
        })
        .layer(middleware::from_fn_with_state(state.clone(), bound_request))
        .layer(axum::middleware::from_fn(csrf_middleware))
        .layer(axum::middleware::from_fn(catch_panic))
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

    #[test]
    fn api_error_variants_carry_typed_status_and_detail() {
        let cases = [
            (
                ApiError::DatabaseUnavailable,
                StatusCode::SERVICE_UNAVAILABLE,
                "Database temporarily unavailable",
            ),
            (
                ApiError::DeadlockDetected,
                StatusCode::INTERNAL_SERVER_ERROR,
                "Reading session deadlock",
            ),
            (
                ApiError::RequestTimeout,
                StatusCode::SERVICE_UNAVAILABLE,
                "Request timed out",
            ),
            (
                ApiError::Internal("boom".to_string()),
                StatusCode::INTERNAL_SERVER_ERROR,
                "boom",
            ),
            (
                ApiError::NotFound("gone".to_string()),
                StatusCode::NOT_FOUND,
                "gone",
            ),
            (
                ApiError::BadRequest("bad".to_string()),
                StatusCode::BAD_REQUEST,
                "bad",
            ),
            (
                ApiError::Unauthorized("no".to_string()),
                StatusCode::UNAUTHORIZED,
                "no",
            ),
            (
                ApiError::Forbidden("stop".to_string()),
                StatusCode::FORBIDDEN,
                "stop",
            ),
            (
                ApiError::Conflict("clash".to_string()),
                StatusCode::CONFLICT,
                "clash",
            ),
            (
                ApiError::Unprocessable("bad shape".to_string()),
                StatusCode::UNPROCESSABLE_ENTITY,
                "bad shape",
            ),
            (
                ApiError::MethodNotAllowed("nope".to_string()),
                StatusCode::METHOD_NOT_ALLOWED,
                "nope",
            ),
            (
                ApiError::ServiceUnavailable("down".to_string()),
                StatusCode::SERVICE_UNAVAILABLE,
                "down",
            ),
            (
                ApiError::Detail {
                    status: StatusCode::TOO_MANY_REQUESTS,
                    detail: "slow down".to_string(),
                },
                StatusCode::TOO_MANY_REQUESTS,
                "slow down",
            ),
        ];
        for (error, status, detail) in cases {
            assert_eq!(error.status(), status);
            assert_eq!(error.detail(), detail);
        }
    }

    #[test]
    fn api_error_behavior_branches_on_variant_not_message_text() {
        // Rewording a message must not change behavior. Only the dedicated
        // variants are database-unavailable or deadlock; other variants that
        // happen to carry the same text (or 503/500 statuses) are neither.
        assert!(ApiError::DatabaseUnavailable.is_database_unavailable());
        assert!(
            !ApiError::Internal("Database temporarily unavailable".to_string())
                .is_database_unavailable()
        );
        assert!(
            !ApiError::ServiceUnavailable("Database temporarily unavailable".to_string())
                .is_database_unavailable()
        );
        assert!(
            !ApiError::NotFound("Database temporarily unavailable".to_string())
                .is_database_unavailable()
        );

        assert!(ApiError::DeadlockDetected.is_deadlock());
        assert!(!ApiError::Internal("Reading session deadlock".to_string()).is_deadlock());
        assert!(
            !ApiError::Internal("Reading session deadlock".to_string()).is_database_unavailable()
        );

        // RequestTimeout is not conflated with DatabaseUnavailable.
        assert!(!ApiError::RequestTimeout.is_database_unavailable());
        assert_eq!(
            ApiError::RequestTimeout.status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
    }

    #[tokio::test]
    async fn database_unavailable_response_keeps_retry_after_and_wire_body() {
        let response = ApiError::DatabaseUnavailable.into_response();
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        let retry_after = response
            .headers()
            .get("Retry-After")
            .and_then(|value| value.to_str().ok());
        assert_eq!(retry_after, Some("30"));
        let body = to_bytes(response.into_body(), 4096).await.unwrap();
        let text = std::str::from_utf8(&body).unwrap();
        assert!(text.contains("\"code\":\"database_unavailable\""));
        assert!(text.contains("Database temporarily unavailable. Please retry."));
    }

    #[tokio::test]
    async fn non_database_503_does_not_get_retry_after() {
        let response = ApiError::RequestTimeout.into_response();
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        assert!(response.headers().get("Retry-After").is_none());
        let body = to_bytes(response.into_body(), 4096).await.unwrap();
        assert_eq!(&body[..], b"{\"detail\":\"Request timed out\"}");
    }

    #[tokio::test]
    async fn unauthorized_keeps_wire_body_and_bearer_challenge() {
        let response = ApiError::Unauthorized("User not found".to_string()).into_response();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
        let challenge = response
            .headers()
            .get(axum::http::header::WWW_AUTHENTICATE)
            .and_then(|value| value.to_str().ok());
        assert_eq!(challenge, Some("Bearer"));
        let body = to_bytes(response.into_body(), 4096).await.unwrap();
        assert_eq!(&body[..], b"{\"detail\":\"User not found\"}");
    }

    #[tokio::test]
    async fn panic_maps_to_standard_500_json_without_leaking_payload() {
        async fn panicking() -> Response {
            panic!("secret canary in panic payload");
        }
        let app = Router::new()
            .route("/panic", get(panicking))
            .route(
                "/ok",
                get(|| async { Json(serde_json::json!({"ok": true})) }),
            )
            .layer(middleware::from_fn(catch_panic));
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/panic")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::INTERNAL_SERVER_ERROR);
        let body = to_bytes(response.into_body(), 4096).await.unwrap();
        assert_eq!(body, r#"{"detail":"Internal Server Error"}"#);
        assert!(
            !String::from_utf8_lossy(&body).contains("canary"),
            "panic payload must never reach the response body"
        );
        let response = app
            .oneshot(Request::builder().uri("/ok").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn production_router_keeps_normal_statuses_unchanged() {
        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        })
        .unwrap();
        let app = router(Arc::new(AppState::new(config).unwrap()));
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/health")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let response = app
            .oneshot(
                Request::builder()
                    .uri("/no-such-route")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
        assert_eq!(
            to_bytes(response.into_body(), 4096).await.unwrap(),
            r#"{"detail":"Not Found"}"#
        );
    }

    #[test]
    fn panic_hook_child_never_logs_sensitive_payload() {
        if std::env::var_os("COMICPILE_PANIC_HOOK_CHILD").is_none() {
            return;
        }
        install_sanitized_panic_hook();
        panic!("secret-canary-panic-message");
    }

    #[test]
    fn panic_hook_redacts_payload_in_real_subprocess() {
        // Never replace the hook of this shared test process: the child is
        // isolated so parallel Rust tests retain their normal failure output.
        let output = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "tests::panic_hook_child_never_logs_sensitive_payload",
                "--nocapture",
            ])
            .env("COMICPILE_PANIC_HOOK_CHILD", "1")
            .output()
            .unwrap();
        assert!(!output.status.success(), "child must panic and fail");
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(stderr.contains("native Rust panic: payload and location redacted"));
        assert!(
            !stderr.contains("secret-canary-panic-message")
                && !stdout.contains("secret-canary-panic-message"),
            "panic payload must not escape to stdout/stderr"
        );
    }

    #[test]
    fn lints_forbid_unwrap_in_production_code() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("Cargo.toml");
        let manifest = std::fs::read_to_string(&path).expect("read service manifest");
        assert!(
            manifest.contains("unwrap_used") && manifest.contains("expect_used"),
            "manifest must deny unwrap/expect so a new production panic fails CI (see #4742)"
        );
    }
}
