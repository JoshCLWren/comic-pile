//! Vercel's native Rust ingress for the Roll endpoint cutover.
//! The health probe never reads database configuration.
#![cfg_attr(test, allow(clippy::unwrap_used, clippy::expect_used))]
use axum::{
    extract::{OriginalUri, Request},
    http::{Extensions, HeaderValue, Method, StatusCode},
    response::{IntoResponse, Response},
    routing::{delete, get, patch, post, put},
    Json, Router,
};
use comicpile_roll_service::{
    auth::BackgroundTasks, config::Config, demo, router as roll_router, AppState,
};
use std::{
    future::Future,
    pin::Pin,
    sync::{Arc, OnceLock},
    task::{Context, Poll},
};
use tower::Service;
use vercel_runtime::{axum::StreamingUtils, AppState as VercelState, Error, ResponseBody};

async fn native_health() -> Response {
    let mut response = Json(serde_json::json!({
        "status": "ok",
        "runtime": "rust",
        "service": "roll",
        "build": {
            "revision": env!("COMICPILE_SOURCE_REVISION"),
            "compiler": env!("COMICPILE_COMPILER"),
            "lock_sha256": env!("COMICPILE_LOCK_SHA256"),
            "package": env!("CARGO_PKG_NAME"),
            "version": env!("CARGO_PKG_VERSION")
        },
        "process": {
            "executable": std::env::current_exe().ok()
                .and_then(|path| path.file_name().map(|name| name.to_string_lossy().into_owned())),
            "os": std::env::consts::OS,
            "arch": std::env::consts::ARCH
        }
    }))
    .into_response();
    response
        .headers_mut()
        .insert("x-comicpile-api-runtime", HeaderValue::from_static("rust"));
    response
}

/// Serve the guest fixture without constructing database or auth state.
async fn native_demo() -> Response {
    let mut response = demo::read_demo_roll().await.into_response();
    response
        .headers_mut()
        .insert("x-comicpile-api-runtime", HeaderValue::from_static("rust"));
    eprintln!("native_roll route=/api/v2/demo-roll runtime=rust status=200");
    response
}

/// Serve simple startup metrics without requiring database or auth state.
async fn native_metrics(method: Method, OriginalUri(uri): OriginalUri) -> Response {
    let path = uri.path().to_owned();
    let mut response = comicpile_roll_service::metrics::get_metrics()
        .await
        .into_response();
    response
        .headers_mut()
        .insert("x-comicpile-api-runtime", HeaderValue::from_static("rust"));
    if method == Method::GET {
        eprintln!("native_roll route={} runtime=rust status=200", path);
    }
    response
}

static ROLL_STATE: OnceLock<Result<Arc<AppState>, &'static str>> = OnceLock::new();

#[cfg(test)]
tokio::task_local! {
    static TEST_ROLL_STATE: Arc<AppState>;
}

/// JSON subscriber for Vercel logs. `try_init` keeps isolate reuse and tests
/// from failing when startup runs more than once.
fn init_tracing() {
    // Production panic hooks otherwise print sensitive payloads before catch_unwind.
    #[cfg(not(test))]
    comicpile_roll_service::install_sanitized_panic_hook();
    comicpile_roll_service::metrics::record_startup_start();
    let directive = std::env::var("RUST_ROLL_LOG").unwrap_or_else(|_| "info".into());
    let filter = tracing_subscriber::EnvFilter::try_new(directive)
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"));
    let _ = tracing_subscriber::fmt()
        .json()
        .with_env_filter(filter)
        .try_init();
}

/// Drop outer-router `UrlParams` before the inner service router matches the
/// same `{thread_id}` pattern. axum 0.8 extends nested path params, so leaving
/// the ingress params in place makes `Path<i32>` see two arguments and return
/// its built-in 500. Keep only `BackgroundTasks`, which the Vercel service
/// inserts for post-response auth work; every other inner extractor reads
/// router state, headers, or the inner match.
fn prepare_inner_request(request: Request) -> Request {
    let (mut parts, body) = request.into_parts();
    let background = parts.extensions.remove::<BackgroundTasks>();
    parts.extensions = Extensions::new();
    if let Some(background) = background {
        parts.extensions.insert(background);
    }
    Request::from_parts(parts, body)
}

fn resolve_roll_state() -> Result<Arc<AppState>, &'static str> {
    #[cfg(test)]
    if let Ok(state) = TEST_ROLL_STATE.try_with(Clone::clone) {
        return Ok(state);
    }
    ROLL_STATE
        .get_or_init(|| {
            Config::from_vercel_env()
                .and_then(AppState::new)
                .map(Arc::new)
                .map_err(|err| {
                    // ConfigError is a static, credential-free message.
                    eprintln!("native_roll initialisation failed: {err}");
                    err.0
                })
        })
        .clone()
}

async fn native_dispatch(request: Request) -> Response {
    init_tracing();
    // Log only the fixed ingress path, status and elapsed time. Never log query,
    // authorization headers, response JSON or other user data.
    let ingress_path = request.uri().path().to_owned();
    let started = std::time::Instant::now();
    // Cold-start the native Roll pool only for authenticated traffic.
    // Keep health independent of DB secrets and failures.
    let request = prepare_inner_request(request);
    let mut result = match resolve_roll_state() {
        Ok(state) => {
            let mut router = roll_router(state);
            match router.call(request).await {
                Ok(response) => response,
                Err(never) => match never {},
            }
        }
        Err(_) => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({"detail": "Native Roll unavailable"})),
        )
            .into_response(),
    };
    result
        .headers_mut()
        .insert("x-comicpile-api-runtime", HeaderValue::from_static("rust"));
    eprintln!(
        "native_roll route={} runtime=rust status={} elapsed_ms={}",
        ingress_path,
        result.status().as_u16(),
        started.elapsed().as_millis()
    );
    result
}

/// Vercel's stock layer drops the per-invocation runtime state, which owns the
/// `wait_until` tracker. Background auth work (password-recovery email) is only
/// guaranteed to finish when it is registered there, so this service forwards
/// that state into every request as a [`BackgroundTasks`] extension before
/// dispatching to the router.
#[derive(Clone)]
struct NativeVercelService {
    router: Router,
}

impl<B> Service<(VercelState, axum::http::Request<B>)> for NativeVercelService
where
    B: http_body::Body<Data = axum::body::Bytes> + Send + 'static,
    B::Error: Into<Error>,
{
    type Response = vercel_runtime::Response<ResponseBody>;
    type Error = Error;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, (state, request): (VercelState, axum::http::Request<B>)) -> Self::Future {
        let mut router = self.router.clone();
        Box::pin(async move {
            let (parts, body) = request.into_parts();
            let mut request = axum::http::Request::from_parts(parts, axum::body::Body::new(body));
            request
                .extensions_mut()
                .insert(BackgroundTasks::new(move |future| {
                    state.wait_until(future);
                }));
            let response = match router.call(request).await {
                Ok(response) => response,
                Err(never) => match never {},
            };
            StreamingUtils::process_response(response).await
        })
    }
}

/// Unknown API paths must terminate in Rust without initializing Python or Neon.
async fn native_not_found() -> Response {
    let mut response = (
        StatusCode::NOT_FOUND,
        Json(serde_json::json!({"detail": "Not Found"})),
    )
        .into_response();
    response
        .headers_mut()
        .insert("x-comicpile-api-runtime", HeaderValue::from_static("rust"));
    response
}

fn app() -> Router {
    Router::new()
        .route("/api/v2/health", get(native_health))
        .route("/api/metrics", get(native_metrics))
        .route("/api/v1/metrics", get(native_metrics))
        .route("/api/v2/identity-inbox", get(native_dispatch))
        .route("/api/v2/identity-inbox/issue-matches", get(native_dispatch))
        .route("/api/v2/identity-inbox/{mapping_id}", get(native_dispatch))
        .route(
            "/api/v2/identity-inbox/{mapping_id}/confirmations",
            post(native_dispatch),
        )
        .route(
            "/api/v2/identity-inbox/{mapping_id}/deferrals",
            post(native_dispatch),
        )
        .route(
            "/api/v2/identity-inbox/{mapping_id}/rejections",
            post(native_dispatch),
        )
        .route(
            "/api/v2/identity-inbox/{mapping_id}/skips",
            post(native_dispatch),
        )
        .route(
            "/api/v2/maintenance/comicvine-metadata-repairs",
            get(native_dispatch),
        )
        .route("/api/v2/activity", get(native_dispatch))
        .route("/api/v2/roll/bootstrap", get(native_dispatch))
        .route("/api/v2/reading-sessions", post(native_dispatch))
        .route(
            "/api/v2/reading-sessions/{session_id}/snapshots",
            get(native_dispatch),
        )
        .route(
            "/api/v2/reading-sessions/{session_id}/details",
            get(native_dispatch),
        )
        .route("/api/v2/undo/{session_id}/snapshots", get(native_dispatch))
        .route(
            "/api/v2/undo/{session_id}/snapshots/{snapshot_id}/restore",
            post(native_dispatch),
        )
        .route("/api/v2/roll/dice-command", post(native_dispatch))
        .route("/api/v2/series-mapping-commits", post(native_dispatch))
        .route(
            "/api/v1/catalog/series-mappings/commit",
            post(native_dispatch),
        )
        .route(
            "/api/v1/catalog/series-mappings/preview",
            post(native_dispatch),
        )
        .route(
            "/api/v1/continuity-plans/{plan_id}/reading-orders/project-preview",
            post(native_dispatch),
        )
        .route(
            "/api/v1/issue-identity/cbl/{list_id}/adoption-preview",
            get(native_dispatch),
        )
        .route(
            "/api/v1/issue-identity/cbl/{list_id}/reading-graph-preview",
            post(native_dispatch),
        )
        .route("/api/v2/roll/offer", post(native_dispatch))
        .route("/api/v2/roll/unsnooze", post(native_dispatch))
        .route("/api/v2/roll/reset", post(native_dispatch))
        .route("/api/v2/roll/die-state", get(native_dispatch))
        .route("/api/v2/roll/eligible-issue-ids", get(native_dispatch))
        .route("/api/v2/demo-roll", get(native_demo))
        .route("/api/v2/reading-boundaries", post(native_dispatch))
        .route("/api/v2/reading-orders/", get(native_dispatch))
        .route(
            "/api/v2/reading-orders/{reading_order_id}/items",
            post(native_dispatch),
        )
        .route("/api/v1/cron/release-sync", get(native_dispatch))
        .route("/api/v2/reading-plan-sync/status", get(native_dispatch))
        .route("/api/v2/reading-plan-sync/runs", post(native_dispatch))
        .route("/api/v2/queue-entries/{thread_id}", get(native_dispatch))
        .route("/api/v2/queue-entries/{thread_id}", patch(native_dispatch))
        .route("/api/v2/queue-orders", post(native_dispatch))
        .route("/api/v2/queue-exclusions", post(native_dispatch))
        .route(
            "/api/v2/queue-exclusions/status:check",
            post(native_dispatch),
        )
        .route("/api/v2/queue-exclusions/restore", post(native_dispatch))
        .route(
            "/api/v2/queue-exclusion-groups/{group_id}/restore",
            post(native_dispatch),
        )
        .route("/api/v2/threads", get(native_dispatch))
        .route("/api/v1/threads/{thread_id}", get(native_dispatch))
        .route("/api/v1/threads/{thread_id}", post(native_dispatch))
        .route("/api/v1/threads:getBlockingInfo", post(native_dispatch))
        .route(
            "/api/v1/threads/{thread_id}/connected",
            get(native_dispatch),
        )
        .route(
            "/api/v1/threads/{thread_id}/dependency-order-check",
            get(native_dispatch),
        )
        .route(
            "/api/v1/threads/{thread_id}/issues:validateOrder",
            get(native_dispatch),
        )
        .route(
            "/api/v1/threads/{thread_id}/reading-orders",
            get(native_dispatch),
        )
        .route("/api/v1/threads/{thread_id}/issues", get(native_dispatch))
        .route("/api/v1/threads/{thread_id}/issues", post(native_dispatch))
        .route(
            "/api/v1/threads/{thread_id}/issues/creators",
            get(native_dispatch),
        )
        .route(
            "/api/v1/threads/{thread_id}/issues:reorder",
            post(native_dispatch),
        )
        .route("/api/threads/{thread_id}", get(native_dispatch))
        .route("/api/v1/threads/completed/threads", get(native_dispatch))
        .route("/api/v1/threads/", post(native_dispatch))
        .route("/api/v1/threads/check-duplicates", post(native_dispatch))
        .route("/api/v1/threads/excluded/threads", get(native_dispatch))
        .route("/api/v1/threads/groups:batch", post(native_dispatch))
        .route("/api/v1/threads/reactivate", post(native_dispatch))
        .route("/api/v1/threads/stale", get(native_dispatch))
        .route("/api/v1/threads/{thread_id}", put(native_dispatch))
        .route("/api/v1/threads/{thread_id}", delete(native_dispatch))
        .route("/api/v1/threads/{thread_id}/exclude", post(native_dispatch))
        .route("/api/v1/threads/{thread_id}/restore", post(native_dispatch))
        .route(
            "/api/v1/threads/{thread_id}/set-pending",
            post(native_dispatch),
        )
        .route(
            "/api/v1/threads/{thread_id}/test-backdate",
            put(native_dispatch),
        )
        .route("/api/v2/reading-graph", get(native_dispatch))
        .route("/api/v2/reading-graph/repairs", post(native_dispatch))
        .route("/api/v2/dependencies/", post(native_dispatch))
        .route("/api/v2/dependencies/blocked", get(native_dispatch))
        .route(
            "/api/v2/dependencies/{dependency_id}",
            get(native_dispatch)
                .patch(native_dispatch)
                .delete(native_dispatch),
        )
        .route("/api/v2/threads/{thread_id}/issues", post(native_dispatch))
        .route(
            "/api/v2/threads/{thread_id}/issue-order",
            put(native_dispatch),
        )
        .route("/api/v2/issues/{issue_id}", delete(native_dispatch))
        .route(
            "/api/v2/continuity-plans/{plan_id}/reader",
            get(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/{plan_id}/recovery",
            get(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/{plan_id}/recovery",
            post(native_dispatch),
        )
        .route("/api/v2/reading-lists", get(native_dispatch))
        .route("/api/v2/reading-lists", post(native_dispatch))
        .route(
            "/api/v2/reading-lists/memberships:check",
            post(native_dispatch),
        )
        .route("/api/v2/reading-lists/{list_id}", get(native_dispatch))
        .route("/api/v2/reading-lists/{list_id}", delete(native_dispatch))
        .route("/api/v2/reading-lists/{list_id}", put(native_dispatch))
        .route(
            "/api/v2/reading-lists/{list_id}/reader",
            get(native_dispatch),
        )
        .route(
            "/api/v2/reading-lists/issue-candidates",
            get(native_dispatch),
        )
        .route(
            "/api/v2/reading-lists/{list_id}/export",
            get(native_dispatch),
        )
        .route(
            "/api/v2/reading-lists/{list_id}/reading-plans/{plan_id}/applications",
            post(native_dispatch),
        )
        .route(
            "/api/v2/reading-lists/{list_id}/overlap-decisions",
            get(native_dispatch),
        )
        .route(
            "/api/v2/reading-lists/{list_id}/overlap-decisions",
            put(native_dispatch),
        )
        .route(
            "/api/v2/reading-lists/{list_id}/overlap-decisions/{decision_id}",
            delete(native_dispatch),
        )
        .route(
            "/api/v2/reading-lists/{list_id}/adoption-commits",
            post(native_dispatch),
        )
        .route(
            "/api/v2/reading-lists/{list_id}/reading-plans/{plan_id}/adoption-commits",
            post(native_dispatch),
        )
        .route("/api/v2/analytics/metrics", get(native_dispatch))
        .route("/api/v2/issues/{issue_id}/comicvine", get(native_dispatch))
        .route("/api/v2/issues/{issue_id}", get(native_dispatch))
        .route(
            "/api/v2/issues/{issue_id}/read-markers",
            post(native_dispatch).delete(native_dispatch),
        )
        .route("/api/v2/issues/{issue_id}/position", put(native_dispatch))
        .route("/api/v2/issue-read-markers", post(native_dispatch))
        .route("/api/v2/issue-read-marker-removals", post(native_dispatch))
        .route(
            "/api/v2/issues/{issue_id}/reader-context",
            get(native_dispatch),
        )
        .route("/api/v1/issues/{issue_id}/comicvine", get(native_dispatch))
        .route("/api/v1/issue-identity/cbl-sources", get(native_dispatch))
        .route(
            "/api/v1/issue-identity/cbl-sources/browse",
            get(native_dispatch),
        )
        .route(
            "/api/v1/issue-identity/cbl-sources/folders",
            get(native_dispatch),
        )
        // Issue Identity / CBL Adoption ingress (#5484). PR #5451 cut these
        // paths over to native-rust and removed the Python handlers, but only
        // registered the discover/browse/folders/adoption-preview siblings in
        // this Vercel entry. Unregistered paths fell through to
        // native_not_found, so production source detail, list candidates and
        // adoption commit returned 404 "Not Found". Keep this table in sync
        // with the inner comicpile_roll_service::router() route table.
        .route(
            "/api/v1/issue-identity/cbl-sources/{list_id}",
            get(native_dispatch),
        )
        .route(
            "/api/v1/issue-identity/cbl-sources/by-comicvine-issue/{comicvine_issue_id}",
            get(native_dispatch),
        )
        .route(
            "/api/v1/issue-identity/cbl-sources/compare",
            post(native_dispatch),
        )
        .route(
            "/api/v1/issue-identity/reading-lists/{list_id}/cbl-candidates",
            get(native_dispatch),
        )
        .route(
            "/api/v1/issue-identity/cbl/{list_id}/adoption-plan",
            post(native_dispatch),
        )
        .route(
            "/api/v1/comicvine/series/{comicvine_volume_id}/import-status",
            get(native_dispatch),
        )
        // Canonical native v2 ComicVine read routes (#4835, split chunk A).
        .route("/api/v2/comicvine/search/series", get(native_dispatch))
        .route("/api/v2/comicvine/resolve", get(native_dispatch))
        .route(
            "/api/v2/comicvine/series/{comicvine_volume_id}/issues",
            get(native_dispatch),
        )
        // Native v2 ComicVine routes (#4835, split chunk B).
        .route(
            "/api/v2/comicvine/issues/{issue_id}/identity",
            get(native_dispatch),
        )
        .route(
            "/api/v2/comicvine/issues/{issue_id}/metadata:corrections",
            get(native_dispatch),
        )
        .route(
            "/api/v2/issues/{issue_id}/dependencies",
            get(native_dispatch),
        )
        .route(
            "/api/v1/threads/{thread_id}/dependencies",
            get(native_dispatch),
        )
        .route("/api/v1/continuity-rules/", get(native_dispatch))
        .route("/api/v1/continuity-rules/", post(native_dispatch))
        .route("/api/v1/continuity-rules/{rule_id}", get(native_dispatch))
        .route("/api/v1/continuity-rules/{rule_id}", put(native_dispatch))
        .route(
            "/api/v1/continuity-rules/{rule_id}",
            delete(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/",
            get(native_dispatch).post(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/from-reading-order",
            post(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/release-sources/",
            post(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/release-sources/{source_id}",
            patch(native_dispatch).delete(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/{plan_id}",
            get(native_dispatch)
                .put(native_dispatch)
                .delete(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/{plan_id}/membership",
            get(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id}",
            post(native_dispatch).delete(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/{plan_id}/reading-orders/project",
            post(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/{plan_id}/release-sources/",
            get(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/{plan_id}/release-sources/reader",
            get(native_dispatch),
        )
        .route("/api/v2/releases", get(native_dispatch))
        .route("/api/v1/releases/", put(native_dispatch))
        .route("/api/v1/releases/source", get(native_dispatch))
        .route("/api/v1/releases/{release_id}", get(native_dispatch))
        .route(
            "/api/v1/releases/{release_id}/retract",
            post(native_dispatch),
        )
        .route(
            "/api/v1/threads/{thread_id}/issue-dependencies",
            get(native_dispatch),
        )
        .route("/api/v2/tags", get(native_dispatch))
        .route("/api/v2/tags", post(native_dispatch))
        .route(
            "/api/v2/tags/effective/issues/{issue_id}",
            get(native_dispatch),
        )
        .route(
            "/api/v2/tags/effective/plans/{plan_id}",
            get(native_dispatch),
        )
        .route(
            "/api/v2/tags/effective/threads/{thread_id}",
            get(native_dispatch),
        )
        .route(
            "/api/v2/tags/effective/threads/{thread_id}/issues",
            get(native_dispatch),
        )
        .route("/api/v2/tags/{tag_id}", get(native_dispatch))
        .route("/api/v2/tags/{tag_id}", patch(native_dispatch))
        .route("/api/v2/tags/{tag_id}", delete(native_dispatch))
        .route("/api/v2/tags/{tag_id}/usage", get(native_dispatch))
        .route("/api/v2/tags/{tag_id}/assignments", post(native_dispatch))
        .route(
            "/api/v2/tags/{tag_id}/assignments/{target_type}/{target_id}",
            delete(native_dispatch),
        )
        .route(
            "/api/v2/tags/{tag_id}/assignment-batches",
            post(native_dispatch),
        )
        .route(
            "/api/v2/tags/{tag_id}/unassignment-batches",
            post(native_dispatch),
        )
        .route("/api/v2/roll/dismiss-pending", post(native_dispatch))
        .route("/api/v2/roll/override", post(native_dispatch))
        .route(
            "/api/v1/roll/events/{event_id}/recommendation-explanation",
            get(native_dispatch),
        )
        .route(
            "/api/roll/events/{event_id}/recommendation-explanation",
            get(native_dispatch),
        )
        .route("/api/v2/roll/switch-prerequisite", post(native_dispatch))
        .route("/api/v2/users/me/preferences", get(native_dispatch))
        .route("/api/v2/users/me/preferences", patch(native_dispatch))
        .route("/api/v1/users/me/taste-signals", get(native_dispatch))
        .route(
            "/api/v1/users/me/taste-signals/{signal_type}/{external_key}/verdict",
            put(native_dispatch),
        )
        .route("/api/v2/reading-mode", get(native_dispatch))
        .route("/api/v2/reading-mode", put(native_dispatch))
        .route(
            "/api/v2/reading-mode/suggestion-dismissals",
            post(native_dispatch),
        )
        .route("/api/v2/reading-mode/suggestions", post(native_dispatch))
        .route("/api/v2/auth/register", post(native_dispatch))
        .route("/api/v2/auth/login", post(native_dispatch))
        .route("/api/v2/auth/refresh", post(native_dispatch))
        .route("/api/v2/auth/logout", post(native_dispatch))
        .route("/api/v2/auth/csrf", get(native_dispatch))
        .route("/api/v2/auth/me", get(native_dispatch))
        .route("/api/v2/auth/forgot-password", post(native_dispatch))
        .route("/api/v2/auth/reset-password", post(native_dispatch))
        .route("/api/v1/auth/me", get(native_dispatch))
        .route("/api/auth/me", get(native_dispatch))
        .route("/api/v1/auth/login", post(native_dispatch))
        .route("/api/v1/auth/register", post(native_dispatch))
        .route("/api/v1/auth/refresh", post(native_dispatch))
        .route("/api/v1/auth/logout", post(native_dispatch))
        .route("/api/v1/auth/csrf", get(native_dispatch))
        .route("/api/v1/auth/forgot-password", post(native_dispatch))
        .route("/api/v1/auth/reset-password", post(native_dispatch))
        .route("/api/auth/login", post(native_dispatch))
        .route("/api/auth/register", post(native_dispatch))
        .route("/api/auth/refresh", post(native_dispatch))
        .route("/api/auth/logout", post(native_dispatch))
        .route("/api/auth/csrf", get(native_dispatch))
        .route("/api/auth/forgot-password", post(native_dispatch))
        .route("/api/auth/reset-password", post(native_dispatch))
        .route("/api/v2/creators", get(native_dispatch))
        .route("/api/v2/creators/summaries", get(native_dispatch))
        .route("/api/v2/creators/compare", get(native_dispatch))
        .route("/api/v2/creators/discoveries", get(native_dispatch))
        .route("/api/v2/creators/team-chemistry", get(native_dispatch))
        .route("/api/v2/creators/{creator_key}", get(native_dispatch))
        .route(
            "/api/v2/creators/{creator_key}/series/{series_key}/issues",
            get(native_dispatch),
        )
        .route(
            "/api/v2/creators/{creator_key}/metrics/{metric_type}",
            get(native_dispatch),
        )
        .route(
            "/api/v2/creators/{creator_key}/metrics/rating-distribution/{rating_value}",
            get(native_dispatch),
        )
        .route(
            "/api/v2/creators/{creator_key}/metrics/role-stats/{role}",
            get(native_dispatch),
        )
        .route(
            "/api/v2/creators/{creator_key}/metrics/series-stats/{series_key}",
            get(native_dispatch),
        )
        .route("/api/v1/taste/discoveries", get(native_dispatch))
        .route(
            "/api/v1/taste/discoveries/{signal_id}/dismiss",
            post(native_dispatch),
        )
        .route("/api/bug-reports/", post(native_dispatch))
        .route("/api/v1/bug-reports/", post(native_dispatch))
        .route("/api/v1/reading-order-groups/", get(native_dispatch))
        .route("/api/v1/reading-order-groups/", post(native_dispatch))
        .route(
            "/api/v1/reading-order-groups/threads/{thread_id}/groups",
            get(native_dispatch),
        )
        .route(
            "/api/v1/reading-order-groups/{group_id}",
            get(native_dispatch),
        )
        .route(
            "/api/v1/reading-order-groups/{group_id}",
            patch(native_dispatch),
        )
        .route(
            "/api/v1/reading-order-groups/{group_id}",
            delete(native_dispatch),
        )
        .route(
            "/api/v1/reading-order-groups/{group_id}/detail",
            get(native_dispatch),
        )
        .route(
            "/api/v1/reading-order-groups/{group_id}/issue-ranges",
            post(native_dispatch),
        )
        .route(
            "/api/v1/reading-order-groups/{group_id}/members",
            post(native_dispatch),
        )
        .route(
            "/api/v1/reading-order-groups/{group_id}/members/{member_id}",
            delete(native_dispatch),
        )
        .route(
            "/api/v1/reading-order-groups/{group_id}/order",
            put(native_dispatch),
        )
        .route(
            "/api/v1/reading-order-groups/{group_id}/plans",
            get(native_dispatch),
        )
        .fallback(native_not_found)
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    init_tracing();
    let router = app();
    comicpile_roll_service::metrics::mark_startup_complete();
    vercel_runtime::run(NativeVercelService { router }).await
}

#[cfg(test)]
mod tests {
    use super::{app, NativeVercelService, TEST_ROLL_STATE};
    use axum::{
        body::{to_bytes, Body},
        http::{header, Request, StatusCode},
        routing::get,
        Router,
    };
    use comicpile_roll_service::{auth::BackgroundTasks, config::Config, AppState};
    use serde_json::Value;
    use std::sync::Arc;
    use tower::Service;
    use vercel_runtime::{AppState as VercelState, LogContext};

    const JWT_SECRET: &str = "synthetic-ingress-queue-secret";

    #[tokio::test]
    async fn metrics_aliases_are_unauthenticated_and_database_free() {
        comicpile_roll_service::metrics::record_startup_start();
        comicpile_roll_service::metrics::mark_startup_complete();
        let mut first = None;
        for path in ["/api/metrics"] {
            let response = app()
                .call(Request::builder().uri(path).body(Body::empty()).unwrap())
                .await
                .expect("metrics response");
            assert_eq!(response.status(), StatusCode::OK);
            assert_eq!(response.headers()["x-comicpile-api-runtime"], "rust");
            let body: Value =
                serde_json::from_slice(&to_bytes(response.into_body(), 4096).await.unwrap())
                    .unwrap();
            assert_eq!(body.as_object().unwrap().len(), 2);
            assert!(body["startup_time"].is_number());
            assert!(body["startup_duration"].is_number());
            if let Some(previous) = &first {
                assert_eq!(&body, previous);
            }
            first = Some(body);
        }
    }

    #[tokio::test]
    async fn guest_demo_ingress_needs_no_auth_or_database_state() {
        let mut router = app();
        let response = router
            .call(
                Request::builder()
                    .uri("/api/v2/demo-roll")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .expect("guest demo response");
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime").unwrap(),
            "rust"
        );
        let body: Value =
            serde_json::from_slice(&to_bytes(response.into_body(), 1024 * 1024).await.unwrap())
                .unwrap();
        assert_eq!(body["title"], "Sample: The Dark Knight Returns (Demo)");
        assert_eq!(body["result"], 4);
        assert!(body.get("user_id").is_none());
    }

    #[tokio::test]
    async fn v2_issue_read_ingress_reaches_rust_and_requires_auth() {
        for uri in [
            "/api/v2/issues/7",
            "/api/v1/issues/7/comicvine",
            "/api/v2/issues/7/dependencies",
        ] {
            let mut router = app();
            let response = router
                .call(
                    Request::builder()
                        .method("GET")
                        .uri(uri)
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .expect("router response");
            assert!(
                response.status() == StatusCode::UNAUTHORIZED
                    || response.status() == StatusCode::SERVICE_UNAVAILABLE,
                "{uri} must require auth and reach Rust, got {}",
                response.status()
            );
            assert_eq!(
                response.headers().get("x-comicpile-api-runtime").unwrap(),
                "rust"
            );
            let bytes = to_bytes(response.into_body(), 8192)
                .await
                .expect("body bytes");
            let text = String::from_utf8_lossy(&bytes);
            assert!(
                !text.contains("Wrong number of path arguments"),
                "numeric issue ids must not fail Path extraction for {uri}: {text}"
            );
        }
    }

    #[tokio::test]
    async fn v2_issue_read_state_ingress_reaches_rust_and_requires_auth() {
        for (method, uri) in [
            ("GET", "/api/v2/issues/7/reader-context"),
            ("POST", "/api/v2/issues/7/read-markers"),
            ("DELETE", "/api/v2/issues/7/read-markers"),
            ("PUT", "/api/v2/issues/7/position"),
            ("POST", "/api/v2/issue-read-markers"),
            ("POST", "/api/v2/issue-read-marker-removals"),
        ] {
            let mut router = app();
            let response = router
                .call(
                    Request::builder()
                        .method(method)
                        .uri(uri)
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .expect("router response");
            assert!(
                response.status() == StatusCode::UNAUTHORIZED
                    || response.status() == StatusCode::SERVICE_UNAVAILABLE
                    || response.status() == StatusCode::FORBIDDEN,
                "{method} {uri} must require auth and reach Rust, got {}",
                response.status()
            );
            assert_eq!(
                response.headers().get("x-comicpile-api-runtime").unwrap(),
                "rust"
            );
        }
    }

    #[tokio::test]
    async fn v1_taste_discovery_list_ingress_preserves_same_path_and_requires_auth() {
        let mut router = app();
        let response = router
            .call(
                Request::builder()
                    .method("GET")
                    .uri("/api/v1/taste/discoveries")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .expect("router response");
        assert!(
            response.status() == StatusCode::UNAUTHORIZED
                || response.status() == StatusCode::SERVICE_UNAVAILABLE,
            "taste discovery list must require auth and reach Rust, got {}",
            response.status()
        );
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime").unwrap(),
            "rust"
        );
    }

    #[tokio::test]
    async fn v1_taste_dismiss_ingress_preserves_same_path_and_requires_auth() {
        let mut router = app();
        let response = router
            .call(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/taste/discoveries/7/dismiss")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .expect("router response");
        assert!(
            response.status() == StatusCode::UNAUTHORIZED
                || response.status() == StatusCode::SERVICE_UNAVAILABLE
                || response.status() == StatusCode::FORBIDDEN,
            "taste dismiss must require auth and reach Rust, got {}",
            response.status()
        );
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime").unwrap(),
            "rust"
        );
        let bytes = to_bytes(response.into_body(), 8192)
            .await
            .expect("body bytes");
        let text = String::from_utf8_lossy(&bytes);
        assert!(
            !text.contains("Wrong number of path arguments"),
            "numeric signal ids must not fail Path extraction: {text}"
        );
    }

    #[tokio::test]
    async fn v1_cbl_adoption_preview_ingress_reaches_rust_and_requires_auth() {
        let mut router = app();
        let response = router
            .call(
                Request::builder()
                    .method("GET")
                    .uri("/api/v1/issue-identity/cbl/1/adoption-preview")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .expect("router response");
        assert!(
            response.status() == StatusCode::UNAUTHORIZED
                || response.status() == StatusCode::SERVICE_UNAVAILABLE,
            "adoption-preview must reach Rust ingress, got {}",
            response.status()
        );
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime").unwrap(),
            "rust"
        );
    }

    #[tokio::test]
    async fn cbl_adoption_paths_reach_rust_ingress_and_never_hit_json_404() {
        // Regression for #5484: PR #5451 cut these adoption-path operations to
        // native-rust and removed their Python handlers, but this Vercel entry
        // only registered the discover/browse/folders/adoption-preview paths.
        // Every unregistered path fell through to native_not_found, which is
        // the production "Unable to load this CBL source" / 404 seen on source
        // detail, list candidates and adoption commit. An authenticated-rust
        // path must reach the dispatched handler's 401/503 (no DB state here),
        // never the Rust JSON 404 fallback.
        let cases = [
            ("GET", "/api/v1/issue-identity/cbl-sources/26"),
            (
                "GET",
                "/api/v1/issue-identity/cbl-sources/by-comicvine-issue/4000-1",
            ),
            ("POST", "/api/v1/issue-identity/cbl-sources/compare"),
            (
                "GET",
                "/api/v1/issue-identity/reading-lists/26/cbl-candidates",
            ),
            ("POST", "/api/v1/issue-identity/cbl/26/adoption-plan"),
            ("POST", "/api/v2/reading-lists/26/adoption-commits"),
            (
                "POST",
                "/api/v2/reading-lists/26/reading-plans/7/adoption-commits",
            ),
        ];
        for (method, uri) in cases {
            let mut router = app();
            let response = router
                .call(
                    Request::builder()
                        .method(method)
                        .uri(uri)
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .expect("router response");
            assert!(
                response.status() == StatusCode::UNAUTHORIZED
                    || response.status() == StatusCode::SERVICE_UNAVAILABLE,
                "{method} {uri} must reach Rust dispatch, not the 404 fallback, got {}",
                response.status()
            );
            assert_eq!(
                response.headers().get("x-comicpile-api-runtime").unwrap(),
                "rust",
                "{method} {uri} runtime header"
            );
            let bytes = to_bytes(response.into_body(), 8192)
                .await
                .expect("body bytes");
            let text = String::from_utf8_lossy(&bytes);
            assert_ne!(
                text, r#"{"detail":"Not Found"}"#,
                "{method} {uri} must not hit native_not_found: {text}"
            );
        }
    }

    #[tokio::test]
    async fn cbl_sources_discover_ingress_reaches_rust_and_requires_auth() {
        // The bare discover path must be registered in this Vercel entry like
        // its /browse and /folders siblings; an unregistered path falls through
        // to the Rust JSON 404 that production CBL source search hit (#5449).
        let mut router = app();
        let response = router
            .call(
                Request::builder()
                    .method("GET")
                    .uri("/api/v1/issue-identity/cbl-sources?q=batman&limit=25")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .expect("router response");
        assert!(
            response.status() == StatusCode::UNAUTHORIZED
                || response.status() == StatusCode::SERVICE_UNAVAILABLE,
            "cbl-sources discover must reach Rust ingress, not the 404 fallback, got {}",
            response.status()
        );
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime").unwrap(),
            "rust"
        );
        let bytes = to_bytes(response.into_body(), 8192)
            .await
            .expect("body bytes");
        let text = String::from_utf8_lossy(&bytes);
        assert!(
            text != r#"{"detail":"Not Found"}"#,
            "cbl-sources discover must not hit the native 404 fallback: {text}"
        );
    }

    #[tokio::test]
    async fn test_backdate_ingress_reaches_rust_and_never_hits_json_404() {
        // The threads route fragment points this method/path at this Vercel
        // entry. Without a matching outer route the regenerated ingress falls
        // through to native_not_found before the inner router ever sees the
        // handler (same failure class as #5484). No DB state is needed here:
        // an anonymous mutation must reach the dispatched handler's 401 (or
        // the 503 cold-start response), never the Rust JSON 404.
        let mut router = app();
        let response = router
            .call(
                Request::builder()
                    .method("PUT")
                    .uri("/api/v1/threads/21/test-backdate?days_ago=5")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .expect("router response");
        assert!(
            response.status() == StatusCode::UNAUTHORIZED
                || response.status() == StatusCode::SERVICE_UNAVAILABLE,
            "test-backdate must reach Rust dispatch, not the 404 fallback, got {}",
            response.status()
        );
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime").unwrap(),
            "rust"
        );
        let bytes = to_bytes(response.into_body(), 8192)
            .await
            .expect("body bytes");
        let text = String::from_utf8_lossy(&bytes);
        assert_ne!(
            text, r#"{"detail":"Not Found"}"#,
            "test-backdate must not hit native_not_found: {text}"
        );
    }

    #[tokio::test]
    async fn comicvine_import_status_ingress_preserves_same_path_and_requires_auth() {
        let mut router = app();
        let response = router
            .call(
                Request::builder()
                    .method("GET")
                    .uri("/api/v1/comicvine/series/42/import-status")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .expect("router response");
        assert!(
            response.status() == StatusCode::UNAUTHORIZED
                || response.status() == StatusCode::SERVICE_UNAVAILABLE,
            "ComicVine import status must require auth and reach Rust, got {}",
            response.status()
        );
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime").unwrap(),
            "rust"
        );
    }

    #[tokio::test]
    async fn comicvine_v2_ingress_preserves_canonical_paths_and_requires_auth() {
        for (method, uri) in [
            ("GET", "/api/v2/comicvine/search/series?q=batman"),
            ("GET", "/api/v2/comicvine/resolve?input=batman"),
            ("GET", "/api/v2/comicvine/series/42/issues"),
            ("GET", "/api/v2/comicvine/issues/7/identity"),
            ("GET", "/api/v2/comicvine/issues/7/metadata:corrections"),
            // Ingress samples for every native v2 ComicVine operation.
        ] {
            let mut router = app();
            let response = router
                .call(
                    Request::builder()
                        .method(method)
                        .uri(uri)
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .expect("router response");
            assert!(
                response.status() == StatusCode::UNAUTHORIZED
                    || response.status() == StatusCode::SERVICE_UNAVAILABLE,
                "{method} {uri} must require auth and reach Rust, got {}",
                response.status()
            );
            assert_eq!(
                response.headers().get("x-comicpile-api-runtime").unwrap(),
                "rust",
                "{method} {uri} must be served by the native ingress"
            );
        }
    }

    #[tokio::test]
    async fn bug_report_ingress_preserves_same_paths_and_requires_auth() {
        for uri in ["/api/bug-reports/", "/api/v1/bug-reports/"] {
            let mut router = app();
            let response = router
                .call(
                    Request::builder()
                        .method("POST")
                        .uri(uri)
                        .header("content-type", "application/json")
                        .body(Body::from(r#"{"title":"Bug","description":"Details"}"#))
                        .unwrap(),
                )
                .await
                .expect("router response");
            assert!(
                response.status() == StatusCode::UNAUTHORIZED
                    || response.status() == StatusCode::SERVICE_UNAVAILABLE,
                "{uri} must require auth and reach Rust, got {}",
                response.status()
            );
            assert_eq!(
                response.headers().get("x-comicpile-api-runtime").unwrap(),
                "rust"
            );
        }
    }

    #[tokio::test]
    async fn activity_ingress_reaches_authenticated_native_dispatch() {
        for uri in ["/api/v2/activity"] {
            let response = app()
                .call(Request::builder().uri(uri).body(Body::empty()).unwrap())
                .await
                .expect("router response");
            assert!(
                response.status() == StatusCode::UNAUTHORIZED
                    || response.status() == StatusCode::SERVICE_UNAVAILABLE,
                "{uri} must reach authenticated native dispatch, got {}",
                response.status()
            );
            assert_eq!(
                response.headers().get("x-comicpile-api-runtime").unwrap(),
                "rust"
            );
        }
    }

    #[tokio::test]
    async fn v2_reading_session_ingress_reaches_rust_and_requires_auth() {
        for uri in [
            "/api/v2/reading-sessions/7/details",
            "/api/v2/reading-sessions/7/snapshots",
        ] {
            let mut router = app();
            let response = router
                .call(
                    Request::builder()
                        .method("GET")
                        .uri(uri)
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .expect("router response");
            assert!(
                response.status() == StatusCode::UNAUTHORIZED
                    || response.status() == StatusCode::SERVICE_UNAVAILABLE,
                "{uri} must require auth and reach Rust, got {}",
                response.status()
            );
            assert_eq!(
                response.headers().get("x-comicpile-api-runtime").unwrap(),
                "rust"
            );
            let bytes = to_bytes(response.into_body(), 8192)
                .await
                .expect("body bytes");
            let text = String::from_utf8_lossy(&bytes);
            assert!(
                !text.contains("Wrong number of path arguments"),
                "numeric session ids must not fail Path extraction for {uri}: {text}"
            );
        }
    }

    #[tokio::test]
    async fn migrated_v2_roll_and_release_ingress_never_hits_json_404() {
        // The Vercel ingress owns a route table separate from the library
        // router. Every browser-facing path moved in this cutover must be
        // registered here too, otherwise it falls through to native_not_found.
        for (method, uri) in [
            ("POST", "/api/v2/roll/override"),
            ("POST", "/api/v2/roll/dismiss-pending"),
            ("POST", "/api/v2/roll/switch-prerequisite"),
            ("GET", "/api/v2/releases"),
        ] {
            let mut router = app();
            let response = router
                .call(
                    Request::builder()
                        .method(method)
                        .uri(uri)
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .expect("router response");
            assert_eq!(
                response.headers().get("x-comicpile-api-runtime").unwrap(),
                "rust",
                "{method} {uri} runtime header"
            );
            assert_ne!(
                response.status(),
                StatusCode::NOT_FOUND,
                "{method} {uri} must reach Rust dispatch, not the 404 fallback"
            );
        }
    }

    #[tokio::test]
    async fn unknown_api_route_returns_rust_json_404_without_database() {
        let mut router = app();
        let response = router
            .call(
                Request::builder()
                    .uri("/api/v2/definitely-not-registered")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .expect("router response");
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime").unwrap(),
            "rust"
        );
        let bytes = to_bytes(response.into_body(), 1024)
            .await
            .expect("body bytes");
        assert_eq!(
            serde_json::from_slice::<Value>(&bytes).expect("JSON"),
            serde_json::json!({"detail": "Not Found"})
        );
    }

    static SCHEMA_COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

    async fn disposable_schema_url() -> String {
        let base = std::env::var("RUST_ROLL_TEST_DATABASE_URL")
            .expect("disposable RUST_ROLL_TEST_DATABASE_URL required; tests never silently skip");
        let (admin, connection) = tokio_postgres::connect(&base, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let seq = SCHEMA_COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let schema = format!("ingress_queue_{}_{}_{}", std::process::id(), nanos, seq);
        admin
            .batch_execute(&format!(
                "CREATE SCHEMA {schema};
                 CREATE TABLE {schema}.users (
                     id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                     username text UNIQUE NOT NULL,
                     email text,
                     password_hash text,
                     is_admin boolean NOT NULL DEFAULT false,
                     password_changed_at timestamptz,
                     created_at timestamptz NOT NULL
                 );
                 CREATE TABLE {schema}.failed_login_attempts (
                     id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                     username text NOT NULL,
                     ip_address text NOT NULL,
                     attempted_at timestamptz NOT NULL DEFAULT NOW()
                 );
                 CREATE TABLE {schema}.revoked_tokens (
                     id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                     user_id integer NOT NULL,
                     jti text NOT NULL UNIQUE,
                     revoked_at timestamptz NOT NULL DEFAULT NOW(),
                     expires_at timestamptz NOT NULL
                 );
                 CREATE TABLE {schema}.password_reset_tokens (
                     id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                     user_id integer NOT NULL,
                     token_digest text NOT NULL UNIQUE,
                     expires_at timestamptz NOT NULL,
                     used_at timestamptz,
                     created_at timestamptz NOT NULL
                 );
                 CREATE TABLE {schema}.threads (
                     id integer PRIMARY KEY,
                     user_id integer NOT NULL,
                     title text NOT NULL DEFAULT '',
                     status text NOT NULL DEFAULT 'active',
                     queue_position integer NOT NULL,
                     queue_position_is_manual boolean NOT NULL DEFAULT false,
                     is_blocked boolean NOT NULL DEFAULT false
                 );
                 CREATE TABLE {schema}.issues (
                     id integer PRIMARY KEY,
                     thread_id integer NOT NULL,
                     issue_number varchar NOT NULL,
                     position integer NOT NULL,
                     status varchar NOT NULL,
                     read_at timestamptz,
                     created_at timestamptz NOT NULL DEFAULT now()
                 );
                 CREATE TABLE {schema}.events (
                     id serial PRIMARY KEY,
                     type text NOT NULL,
                     timestamp timestamptz NOT NULL DEFAULT now(),
                     user_id integer,
                     thread_id integer
                 );
                 CREATE TABLE {schema}.cbl_sources (
                     id integer PRIMARY KEY,
                     repository varchar(255) NOT NULL,
                     revision_sha varchar(64) NOT NULL,
                     synced_at timestamptz NOT NULL DEFAULT now(),
                     created_at timestamptz NOT NULL DEFAULT now(),
                     updated_at timestamptz NOT NULL DEFAULT now()
                 );
                 CREATE TABLE {schema}.cbl_source_lists (
                     id integer PRIMARY KEY,
                     source_id integer NOT NULL,
                     source_path varchar(1000) NOT NULL,
                     name varchar(500) NOT NULL,
                     declared_issue_count integer,
                     content_hash varchar(64) NOT NULL,
                     revision_sha varchar(64) NOT NULL,
                     active boolean NOT NULL,
                     created_at timestamptz NOT NULL DEFAULT now(),
                     updated_at timestamptz NOT NULL DEFAULT now()
                 );
                 CREATE TABLE {schema}.external_identities (
                     id integer PRIMARY KEY,
                     provider varchar(50) NOT NULL,
                     entity_type varchar(20) NOT NULL,
                     external_id varchar(100) NOT NULL,
                     metadata_json jsonb NOT NULL DEFAULT '{{}}',
                     created_at timestamptz NOT NULL DEFAULT now(),
                     updated_at timestamptz NOT NULL DEFAULT now()
                 );
                 CREATE TABLE {schema}.cbl_source_entries (
                     id integer PRIMARY KEY,
                     list_id integer NOT NULL,
                     position integer NOT NULL,
                     series_name varchar(500) NOT NULL,
                     issue_number varchar(100) NOT NULL,
                     volume_year integer,
                     publication_year integer,
                     external_series_identity_id integer,
                     external_issue_identity_id integer,
                     created_at timestamptz NOT NULL DEFAULT now()
                 );"
            ))
            .await
            .expect("ingress queue schema");
        let separator = if base.contains('?') { '&' } else { '?' };
        format!("{base}{separator}sslmode=disable&options=-c%20search_path%3D{schema}")
    }

    fn test_state(url: &str) -> Arc<AppState> {
        Arc::new(
            AppState::new(
                Config::from_lookup(|key| match key {
                    "RUST_ROLL_DATABASE_URL" => Some(url.into()),
                    "RUST_ROLL_JWT_SECRET" => Some(JWT_SECRET.into()),
                    "RUST_ROLL_POOL_SIZE" => Some("2".into()),
                    _ => None,
                })
                .expect("ingress test config"),
            )
            .expect("ingress test state"),
        )
    }

    async fn call_app(request: Request<Body>) -> (StatusCode, Value, Vec<String>, String) {
        let mut router = app();
        let response = router.call(request).await.expect("native response");
        let status = response.status();
        let cookies = response
            .headers()
            .get_all(header::SET_COOKIE)
            .iter()
            .filter_map(|value| value.to_str().ok().map(str::to_owned))
            .collect::<Vec<_>>();
        let body = to_bytes(response.into_body(), 1024 * 1024)
            .await
            .expect("response body");
        let text = String::from_utf8_lossy(&body).into_owned();
        let json = serde_json::from_slice(&body).unwrap_or(Value::Null);
        (status, json, cookies, text)
    }

    fn csrf_from(cookies: &[String]) -> String {
        cookies
            .iter()
            .find_map(|cookie| {
                cookie
                    .split(';')
                    .next()
                    .and_then(|part| part.strip_prefix("csrf_token="))
                    .map(str::to_owned)
            })
            .expect("csrf cookie")
    }

    fn assert_not_path_extraction_500(status: StatusCode, body: &str) {
        assert!(
            !(status == StatusCode::INTERNAL_SERVER_ERROR
                && body.contains("Wrong number of path arguments")),
            "numeric queue-entry ids must not fail Path extraction: {body}"
        );
    }

    /// Each DB-backed test registers its own user. The auth register limiter is
    /// a process-global 5-per-minute bucket keyed by client IP, so a fixed IP
    /// makes parallel tests race into 429 "Too many requests" flakes. Give every
    /// registration a unique client IP so each test owns its own bucket.
    static REGISTER_CLIENT_COUNTER: std::sync::atomic::AtomicU32 =
        std::sync::atomic::AtomicU32::new(0);

    async fn register_session(username: &str) -> (String, String, i32) {
        let client_ip = format!(
            "198.51.100.{}",
            REGISTER_CLIENT_COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1
        );
        let (status, body, cookies, text) = call_app(
            Request::builder()
                .method("POST")
                .uri("/api/v2/auth/register")
                .header(header::CONTENT_TYPE, "application/json")
                .header("x-forwarded-for", client_ip)
                .body(Body::from(
                    serde_json::json!({
                        "username": username,
                        "email": format!("{username}@example.com"),
                        "password": "correct-horse-battery"
                    })
                    .to_string(),
                ))
                .expect("register request"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{text}");
        let access = body["access_token"]
            .as_str()
            .expect("access token")
            .to_owned();
        let connection = TEST_ROLL_STATE
            .try_with(Clone::clone)
            .expect("test state")
            .pool
            .get()
            .await
            .expect("user lookup");
        let user_id: i32 = connection
            .query_one("SELECT id FROM users WHERE username = $1", &[&username])
            .await
            .expect("registered user")
            .get(0);
        (access, csrf_from(&cookies), user_id)
    }

    async fn seed_threads(user_id: i32, rows: &[(i32, i32)]) {
        let connection = TEST_ROLL_STATE
            .try_with(Clone::clone)
            .expect("test state")
            .pool
            .get()
            .await
            .expect("seed connection");
        for (id, position) in rows {
            connection
                .execute(
                    "INSERT INTO threads (id, user_id, status, queue_position) \
                     VALUES ($1, $2, 'active', $3)",
                    &[id, &user_id, position],
                )
                .await
                .expect("seed thread");
        }
    }

    async fn stored_order(user_id: i32) -> Vec<i32> {
        let connection = TEST_ROLL_STATE
            .try_with(Clone::clone)
            .expect("test state")
            .pool
            .get()
            .await
            .expect("order connection");
        connection
            .query(
                "SELECT id FROM threads WHERE user_id = $1 AND status = 'active' \
                 AND queue_position >= 1 ORDER BY queue_position, id",
                &[&user_id],
            )
            .await
            .expect("read order")
            .iter()
            .map(|row| row.get(0))
            .collect()
    }

    async fn queue_request(
        method: &str,
        thread_id: i32,
        access: &str,
        csrf: &str,
        body: Option<Value>,
    ) -> (StatusCode, Value, String) {
        let mut builder = Request::builder()
            .method(method)
            .uri(format!("/api/v2/queue-entries/{thread_id}"))
            .header(header::AUTHORIZATION, format!("Bearer {access}"))
            .header(header::COOKIE, format!("csrf_token={csrf}"))
            .header("x-csrf-token", csrf);
        if body.is_some() {
            builder = builder.header(header::CONTENT_TYPE, "application/json");
        }
        let (status, json, _, text) = call_app(
            builder
                .body(match body {
                    Some(payload) => Body::from(payload.to_string()),
                    None => Body::empty(),
                })
                .expect("queue request"),
        )
        .await;
        assert_not_path_extraction_500(status, &text);
        (status, json, text)
    }

    #[tokio::test]
    async fn canonical_bootstrap_preserves_auth_and_query_through_rust_ingress() {
        let request = Request::builder()
            .method("GET")
            .uri("/api/v2/roll/bootstrap?timezone=America%2FChicago")
            .header("authorization", "Bearer synthetic-test-token")
            .body(Body::empty())
            .expect("canonical request");
        assert_eq!(
            request.uri().to_string(),
            "/api/v2/roll/bootstrap?timezone=America%2FChicago"
        );
        assert_eq!(
            request.headers().get("authorization"),
            Some(&axum::http::HeaderValue::from_static(
                "Bearer synthetic-test-token"
            ))
        );

        // Exercise the actual production Axum router with no special-case URL rewrite.
        let mut router = app();
        let response = router.call(request).await.expect("Rust response");
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime"),
            Some(&axum::http::HeaderValue::from_static("rust"))
        );
        assert!(
            response.status() == StatusCode::SERVICE_UNAVAILABLE
                || response.status() == StatusCode::UNAUTHORIZED,
            "canonical path must reach Rust startup or bearer authentication"
        );
    }

    #[tokio::test]
    async fn native_probe_serves_json_without_config_or_database() {
        let mut router = app();
        let request = Request::builder()
            .method("GET")
            .uri("/api/v2/health")
            .body(Body::empty())
            .expect("valid request");
        let response = router.call(request).await.expect("health response");
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime"),
            Some(&axum::http::HeaderValue::from_static("rust"))
        );
        assert_eq!(
            response.headers().get(header::CONTENT_TYPE),
            Some(&axum::http::HeaderValue::from_static("application/json"))
        );
        let body = to_bytes(response.into_body(), 1024)
            .await
            .expect("health JSON");
        let health: serde_json::Value = serde_json::from_slice(&body).expect("valid JSON");
        assert_eq!(health["status"], "ok");
        assert_eq!(health["runtime"], "rust");
        assert_eq!(health["service"], "roll");
        assert_eq!(
            health["build"]["revision"],
            env!("COMICPILE_SOURCE_REVISION")
        );
        assert!(health["build"]["compiler"]
            .as_str()
            .unwrap()
            .starts_with("rustc "));
        assert_eq!(
            health["build"]["lock_sha256"],
            env!("COMICPILE_LOCK_SHA256")
        );
        assert_eq!(health["build"]["lock_sha256"].as_str().unwrap().len(), 64);
        assert_eq!(health["build"]["package"], env!("CARGO_PKG_NAME"));
        let executable = std::env::current_exe().expect("current executable");
        assert_eq!(
            health["process"]["executable"],
            executable.file_name().unwrap().to_string_lossy().as_ref()
        );
        assert_eq!(health["process"]["os"], std::env::consts::OS);
        assert_eq!(health["process"]["arch"], std::env::consts::ARCH);
    }

    #[tokio::test]
    async fn vercel_service_propagates_the_wait_until_tracker_to_handlers() {
        async fn probe(parts: axum::http::request::Parts) -> StatusCode {
            if parts.extensions.get::<BackgroundTasks>().is_some() {
                StatusCode::OK
            } else {
                StatusCode::INTERNAL_SERVER_ERROR
            }
        }

        #[cfg(unix)]
        let log_context = LogContext::new(None, None, None);
        #[cfg(not(unix))]
        let log_context = LogContext::new();

        let mut service = NativeVercelService {
            router: Router::new().route("/probe", get(probe)),
        };
        let request = Request::builder()
            .method("GET")
            .uri("/probe")
            .body(Body::empty())
            .expect("valid probe request");
        let response = Service::call(&mut service, (VercelState::new(log_context), request))
            .await
            .expect("vercel service response");
        assert_eq!(
            response.status(),
            StatusCode::OK,
            "handlers must receive the invocation's tracked background registrar"
        );
    }

    #[tokio::test]
    async fn two_router_thread_issue_list_loads_authenticated_pages_from_rust() {
        let url = disposable_schema_url().await;
        let state = test_state(&url);
        TEST_ROLL_STATE
            .scope(state, async {
                let username = format!("thread-issues-ingress-{}", std::process::id());
                let (access, _, user_id) = register_session(&username).await;
                seed_threads(user_id, &[(21, 1)]).await;

                let connection = TEST_ROLL_STATE
                    .try_with(Clone::clone)
                    .expect("test state")
                    .pool
                    .get()
                    .await
                    .expect("seed issues");
                for (id, position, status) in [
                    (101_i32, 1_i32, "unread"),
                    (102_i32, 2_i32, "read"),
                    (103_i32, 3_i32, "unread"),
                ] {
                    let thread_id = 21_i32;
                    let issue_number = position.to_string();
                    connection
                        .execute(
                            "INSERT INTO issues (id, thread_id, issue_number, position, status) \
                             VALUES ($1, $2, $3, $4, $5)",
                            &[&id, &thread_id, &issue_number, &position, &status],
                        )
                        .await
                        .expect("seed issue");
                }
                drop(connection);

                let request = |uri: String, token: &str| {
                    Request::builder()
                        .method("GET")
                        .uri(uri)
                        .header(header::AUTHORIZATION, format!("Bearer {token}"))
                        .body(Body::empty())
                        .expect("thread issues request")
                };
                let (status, first, _, text) = call_app(request(
                    "/api/v1/threads/21/issues?page_size=2".into(),
                    &access,
                ))
                .await;
                assert_eq!(status, StatusCode::OK, "{text}");
                assert_eq!(first["total_count"], 3);
                assert_eq!(first["page_size"], 2);
                assert_eq!(first["issues"].as_array().expect("issue rows").len(), 2);
                assert_eq!(first["issues"][0]["issue_number"], "1");
                assert_eq!(first["issues"][1]["issue_number"], "2");
                let cursor = first["next_page_token"]
                    .as_str()
                    .expect("pagination cursor");
                assert_eq!(cursor, "2,102");

                let (status, next, _, text) = call_app(request(
                    format!("/api/v1/threads/21/issues?page_size=2&page_token={cursor}"),
                    &access,
                ))
                .await;
                assert_eq!(status, StatusCode::OK, "{text}");
                assert_eq!(next["total_count"], 3);
                assert_eq!(next["issues"].as_array().expect("last page").len(), 1);
                assert_eq!(next["issues"][0]["issue_number"], "3");
                assert!(next["next_page_token"].is_null());

                let (status, unread, _, text) = call_app(request(
                    "/api/v1/threads/21/issues?status=unread&page_size=100".into(),
                    &access,
                ))
                .await;
                assert_eq!(status, StatusCode::OK, "{text}");
                assert_eq!(unread["total_count"], 2);
                assert_eq!(unread["issues"].as_array().expect("filtered").len(), 2);

                let (status, missing, _, _) =
                    call_app(request("/api/v1/threads/999/issues".into(), &access)).await;
                assert_eq!(status, StatusCode::NOT_FOUND);
                assert_eq!(missing["detail"], "Thread 999 not found");

                let other_name = format!("thread-issues-foreign-{}", std::process::id());
                let (other_access, _, _) = register_session(&other_name).await;
                let (status, _, _, _) =
                    call_app(request("/api/v1/threads/21/issues".into(), &other_access)).await;
                assert_eq!(status, StatusCode::NOT_FOUND);
            })
            .await;
    }

    #[tokio::test]
    async fn two_router_thread_issue_list_validation_matches_python_contract() {
        let url = disposable_schema_url().await;
        let state = test_state(&url);
        TEST_ROLL_STATE
            .scope(state, async {
                let username = format!("thread-issues-validation-{}", std::process::id());
                let (access, _, user_id) = register_session(&username).await;
                seed_threads(user_id, &[(21, 1)]).await;

                let assert_validation_422 =
                    |status: StatusCode,
                     headers: &axum::http::HeaderMap,
                     body: Value,
                     text: &str,
                     uri: &str| {
                        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{uri}: {text}");
                        assert_eq!(
                            headers
                                .get(header::CONTENT_TYPE)
                                .and_then(|v| v.to_str().ok()),
                            Some("application/json"),
                            "{uri}: {text}"
                        );
                        assert_eq!(body["detail"], "Validation failed", "{uri}: {text}");
                    };

                let mut router = app();
                for uri in [
                    "/api/v1/threads/not-an-int/issues",
                    "/api/v1/threads/21/issues?page_size=abc",
                    "/api/v1/threads/21/issues?page_size=99999999999999999999",
                    "/api/v1/threads/21/issues?page_size=0",
                    "/api/v1/threads/21/issues?page_size=101",
                    "/api/v1/threads/21/issues?status=invalid",
                    // Invalid-UTF-8 path extraction must also use the 422 envelope.
                    "/api/v1/threads/%FF/issues",
                ] {
                    let request = Request::builder()
                        .method("GET")
                        .uri(uri)
                        .header(header::AUTHORIZATION, format!("Bearer {access}"))
                        .body(Body::empty())
                        .expect("validation request");
                    let response = router.call(request).await.expect("response");
                    let status = response.status();
                    let headers = response.headers().clone();
                    let body = to_bytes(response.into_body(), 8192).await.expect("body");
                    let text = String::from_utf8_lossy(&body).into_owned();
                    let json: Value = serde_json::from_slice(&body).unwrap_or(Value::Null);
                    assert_validation_422(status, &headers, json, &text, uri);
                    router = app();
                }

                let (status, body, _, text) = call_app(
                    Request::builder()
                        .method("GET")
                        .uri("/api/v1/threads/21/issues?page_token=bad")
                        .header(header::AUTHORIZATION, format!("Bearer {access}"))
                        .body(Body::empty())
                        .expect("bad token request"),
                )
                .await;
                assert_eq!(status, StatusCode::BAD_REQUEST, "{text}");
                assert_eq!(body["detail"], "Invalid page_token format", "{text}");

                // Encoded-but-valid query values are form-decoded before
                // validation: `2%2C102` is the cursor `2,102` and `%72ead`
                // is `read`. Neither may fall into the 400/422 paths (#5318).
                for uri in [
                    "/api/v1/threads/21/issues?page_token=2%2C102",
                    "/api/v1/threads/21/issues?status=%72ead",
                ] {
                    let (status, body, _, text) = call_app(
                        Request::builder()
                            .method("GET")
                            .uri(uri)
                            .header(header::AUTHORIZATION, format!("Bearer {access}"))
                            .body(Body::empty())
                            .expect("encoded query request"),
                    )
                    .await;
                    assert_eq!(status, StatusCode::OK, "{uri}: {text}");
                    assert_eq!(body["total_count"], 0, "{uri}: {text}");
                }
            })
            .await;
    }

    #[tokio::test]
    async fn two_router_queue_entry_stack_repositions_without_path_extraction_500() {
        let url = disposable_schema_url().await;
        let state = test_state(&url);
        TEST_ROLL_STATE
            .scope(state, async {
                let username = format!("queue-ingress-{}", std::process::id());
                let (access, csrf, user_id) = register_session(&username).await;
                seed_threads(user_id, &[(11, 1), (12, 2), (13, 3)]).await;

                let (status, body, text) = queue_request("GET", 13, &access, &csrf, None).await;
                assert_eq!(status, StatusCode::OK, "{text}");
                assert_eq!(body["thread_id"], 13);
                assert_eq!(body["position"], 3);

                let (status, body, text) = queue_request(
                    "PATCH",
                    13,
                    &access,
                    &csrf,
                    Some(serde_json::json!({"position": 1})),
                )
                .await;
                assert_eq!(status, StatusCode::OK, "{text}");
                assert_eq!(body["thread_id"], 13);
                assert_eq!(body["position"], 1);
                assert_eq!(stored_order(user_id).await, vec![13, 11, 12]);

                let (status, body, text) = queue_request(
                    "PATCH",
                    13,
                    &access,
                    &csrf,
                    Some(serde_json::json!({"position": 2_147_483_647})),
                )
                .await;
                assert_eq!(status, StatusCode::OK, "{text}");
                assert_eq!(body["thread_id"], 13);
                assert_eq!(body["position"], 3);
                assert_eq!(stored_order(user_id).await, vec![11, 12, 13]);
            })
            .await;
    }

    #[tokio::test]
    async fn roll_unsnooze_is_served_from_rust_ingress_against_postgres() {
        // Regression for #4589 review: the inner router had the route but this
        // Vercel entry did not, so browsers got the ingress 404 fallback.
        let url = disposable_schema_url().await;
        let state = test_state(&url);
        TEST_ROLL_STATE
            .scope(state, async {
                let username = format!("unsnooze-ingress-{}", std::process::id());
                let (access, csrf, user_id) = register_session(&username).await;
                seed_threads(user_id, &[(21, 1)]).await;
                let request = |token: Option<&str>| {
                    let mut builder = Request::builder()
                        .method("POST")
                        .uri("/api/v2/roll/unsnooze")
                        .header(header::CONTENT_TYPE, "application/json")
                        .header(header::COOKIE, format!("csrf_token={csrf}"))
                        .header("x-csrf-token", csrf.as_str());
                    if let Some(token) = token {
                        builder = builder.header(header::AUTHORIZATION, format!("Bearer {token}"));
                    }
                    builder
                        .body(Body::from(serde_json::json!({"thread_id": 21}).to_string()))
                        .expect("unsnooze request")
                };
                // Unauthenticated reaches the dispatched handler's 401.
                let (status, _, _, text) = call_app(request(None)).await;
                assert_eq!(status, StatusCode::UNAUTHORIZED, "{text}");
                // Authenticated requests must reach the handler, never the
                // ingress 404 fallback. This ingress schema is deliberately
                // partial, so the handler may 5xx here; the full behavior is
                // covered against the canonical schema in the inner-router
                // tests (thread_ordering_v1_http).
                let (status, _, _, text) = call_app(request(Some(&access))).await;
                assert_ne!(status, StatusCode::NOT_FOUND, "{text}");
            })
            .await;
    }

    #[tokio::test]
    async fn cbl_sources_discover_is_served_from_rust_ingress_against_postgres() {
        // Regression for #5449: the bare `GET /api/v1/issue-identity/cbl-sources`
        // discover path must be registered in this Vercel entry and dispatched
        // to the Rust service, not fall through to the Rust JSON 404.
        let url = disposable_schema_url().await;
        let state = test_state(&url);
        TEST_ROLL_STATE
            .scope(state, async {
                let username = format!("cbl-discover-ingress-{}", std::process::id());
                let (access, _csrf, _user_id) = register_session(&username).await;

                let connection = TEST_ROLL_STATE
                    .try_with(Clone::clone)
                    .expect("test state")
                    .pool
                    .get()
                    .await
                    .expect("seed connection");
                connection
                    .batch_execute(
                        "INSERT INTO cbl_sources (id, repository, revision_sha) \
                         VALUES (1, '/mnt/bigdata/CBL-ReadingLists', 'abc123'); \
                         INSERT INTO cbl_source_lists \
                           (id, source_id, source_path, name, declared_issue_count, \
                            content_hash, revision_sha, active) \
                         VALUES \
                           (1, 1, 'DC/Batman (1940)/Batman.cbl', 'Batman 1940', 12, \
                            'h-bat', 'abc123', TRUE), \
                           (2, 1, 'DC/Batman (1940)/Batman Adventures.cbl', \
                            'Batman Adventures', 6, 'h-adv', 'abc123', TRUE), \
                           (3, 1, 'Marvel/X-Men.cbl', 'X-Men', 30, 'h-x', 'abc123', TRUE), \
                           (4, 1, 'DC/Archived.cbl', 'Archived Batman', 1, \
                            'h-arch', 'abc123', FALSE), \
                           (5, 1, 'DC/Special/100% Complete.cbl', '100% Complete', 2, \
                            'h-pct', 'abc123', TRUE), \
                           (6, 1, 'DC/Special/100X Complete.cbl', '100X Complete', 2, \
                            'h-pctx', 'abc123', TRUE), \
                           (7, 1, 'DC/Special/Under_score.cbl', 'Under_score', 3, \
                            'h-us', 'abc123', TRUE), \
                           (8, 1, 'DC/Special/UnderXscore.cbl', 'UnderXscore', 3, \
                            'h-usx', 'abc123', TRUE), \
                           (9, 1, 'DC/Special/Back\\Slash.cbl', 'Back\\Slash', 4, \
                            'h-bs', 'abc123', TRUE), \
                           (10, 1, 'DC/Special/BackSlash.cbl', 'BackSlash', 4, \
                            'h-bsx', 'abc123', TRUE);",
                    )
                    .await
                    .expect("seed cbl catalog");
                drop(connection);

                // Without credentials the registered path must reach the
                // dispatched handler's 401, not the ingress 404 fallback.
                let (status, _, _, text) = call_app(
                    Request::builder()
                        .method("GET")
                        .uri("/api/v1/issue-identity/cbl-sources?q=batman")
                        .body(Body::empty())
                        .expect("unauthenticated cbl discover request"),
                )
                .await;
                assert_eq!(status, StatusCode::UNAUTHORIZED, "{text}");

                let request = |uri: String| {
                    Request::builder()
                        .method("GET")
                        .uri(uri)
                        .header(header::AUTHORIZATION, format!("Bearer {access}"))
                        .body(Body::empty())
                        .expect("cbl discover request")
                };

                let (status, body, _, text) =
                    call_app(request("/api/v1/issue-identity/cbl-sources".into())).await;
                assert_eq!(status, StatusCode::OK, "{text}");
                let items = body.as_array().expect("discovery list");
                assert_eq!(items.len(), 9, "inactive lists must be excluded: {text}");
                assert!(
                    items
                        .iter()
                        .all(|item| item["source_repository"] == "JoshCLWren/CBL-ReadingLists"),
                    "mirror repositories must project to the public name: {text}"
                );

                // Regression for #5485: "Batman" (and case/substring variants) must
                // match active CBL source lists by name or source path, while other
                // terms continue to work. The inactive "Archived Batman" row must
                // remain excluded so results come from active catalog entries only.
                for query in ["batman", "Batman", "BATMAN", "Bat"] {
                    let (status, body, _, text) = call_app(request(format!(
                        "/api/v1/issue-identity/cbl-sources?q={query}"
                    )))
                    .await;
                    assert_eq!(status, StatusCode::OK, "{query}: {text}");
                    let items = body.as_array().expect("filtered discovery list");
                    assert!(
                        !items.is_empty(),
                        "search for {query:?} must return Batman results (#5485): {text}"
                    );
                    assert!(
                        items.iter().all(|item| {
                            item["name"]
                                .as_str()
                                .unwrap_or_default()
                                .to_ascii_lowercase()
                                .contains("bat")
                                || item["source_path"]
                                    .as_str()
                                    .unwrap_or_default()
                                    .to_ascii_lowercase()
                                    .contains("bat")
                        }),
                        "all results for {query:?} must match the Batman term: {text}"
                    );
                    assert!(
                        items.iter().all(|item| item["name"] != "Archived Batman"),
                        "inactive lists must stay excluded for {query:?}: {text}"
                    );
                }

                // Literal LIKE metacharacters must be escaped so user terms match
                // %, _, and \ characters exactly (not as SQL wildcards/escapes).
                for (query, expected_name, excluded_name) in [
                    ("100%25", "100% Complete", "100X Complete"),
                    ("Under_score", "Under_score", "UnderXscore"),
                    ("Back%5CSlash", "Back\\Slash", "BackSlash"),
                ] {
                    let (status, body, _, text) = call_app(request(format!(
                        "/api/v1/issue-identity/cbl-sources?q={query}"
                    )))
                    .await;
                    assert_eq!(status, StatusCode::OK, "{query}: {text}");
                    let items = body.as_array().expect("filtered discovery list");
                    assert!(
                        items.iter().any(|item| item["name"] == expected_name),
                        "literal search {query:?} must match {expected_name:?}: {text}"
                    );
                    assert!(
                        items.iter().all(|item| item["name"] != excluded_name),
                        "literal search {query:?} must not wildcard-match {excluded_name:?}: {text}"
                    );
                }

                let (status, body, _, text) = call_app(request(
                    "/api/v1/issue-identity/cbl-sources?q=batman&limit=1".into(),
                ))
                .await;
                assert_eq!(status, StatusCode::OK, "{text}");
                let items = body.as_array().expect("filtered discovery list");
                assert_eq!(items.len(), 1, "limit must bound the search: {text}");
                assert_eq!(items[0]["name"], "Batman 1940", "{text}");
                assert_eq!(
                    items[0]["source_path"], "DC/Batman (1940)/Batman.cbl",
                    "discovery keeps the raw stored path: {text}"
                );
                assert_eq!(items[0]["declared_issue_count"], 12, "{text}");
            })
            .await;
    }

    #[tokio::test]
    async fn cbl_sources_discover_high_volume_batman_catalog_returns_bounded_active_results() {
        // Regression for #5485: a realistic catalog has hundreds of Batman
        // sources, many inactive or with NULL entry counts. Searches for
        // "Batman"/"batman"/"Bat" must still return a full page of ACTIVE
        // matches while narrow terms ("Teen Titans", "X-Men") keep working.
        let url = disposable_schema_url().await;
        let state = test_state(&url);
        TEST_ROLL_STATE
            .scope(state, async {
                let username = format!("cbl-discover-volume-{}", std::process::id());
                let (access, _csrf, _user_id) = register_session(&username).await;
                let connection = TEST_ROLL_STATE
                    .try_with(Clone::clone)
                    .expect("test state")
                    .pool
                    .get()
                    .await
                    .expect("seed connection");
                connection
                    .batch_execute(
                        "INSERT INTO cbl_sources (id, repository, revision_sha) \
                         VALUES (1, '/mnt/bigdata/CBL-ReadingLists', 'abc123'); \
                         INSERT INTO cbl_source_lists \
                           (id, source_id, source_path, name, declared_issue_count, \
                            content_hash, revision_sha, active) \
                         SELECT n, 1, 'DC/Batman/Batman Run ' || lpad(n::text, 3, '0') || '.cbl', \
                                'Batman Run ' || lpad(n::text, 3, '0'), \
                                CASE WHEN n % 7 = 0 THEN NULL ELSE n END, \
                                'h' || n, 'abc123', TRUE \
                         FROM generate_series(1, 120) AS n; \
                         INSERT INTO cbl_source_lists \
                           (id, source_id, source_path, name, declared_issue_count, \
                            content_hash, revision_sha, active) \
                         SELECT 200 + n, 1, 'DC/Old/Batman Old ' || n || '.cbl', \
                                'AAA Batman Archived ' || n, 3, 'ha' || n, 'abc123', FALSE \
                         FROM generate_series(1, 60) AS n; \
                         INSERT INTO cbl_source_lists \
                           (id, source_id, source_path, name, declared_issue_count, \
                            content_hash, revision_sha, active) \
                         SELECT 300 + n, 1, 'DC/Batman/Crossovers/Event ' || n || '.cbl', \
                                'Event ' || n, 5, 'hp' || n, 'abc123', TRUE \
                         FROM generate_series(1, 40) AS n; \
                         INSERT INTO cbl_source_lists \
                           (id, source_id, source_path, name, declared_issue_count, \
                            content_hash, revision_sha, active) \
                         VALUES \
                           (400, 1, 'DC/Teen Titans/Teen Titans.cbl', 'Teen Titans', 9, 'ht', 'abc123', TRUE), \
                           (401, 1, 'Marvel/X-Men/X-Men 1963.cbl', 'X-Men 1963', 9, 'hx1', 'abc123', TRUE), \
                           (402, 1, 'Marvel/X-Men/X-Men 1991.cbl', 'X-Men 1991', NULL, 'hx2', 'abc123', TRUE);",
                    )
                    .await
                    .expect("seed high-volume cbl catalog");
                drop(connection);

                let request = |uri: String| {
                    Request::builder()
                        .method("GET")
                        .uri(uri)
                        .header(header::AUTHORIZATION, format!("Bearer {access}"))
                        .body(Body::empty())
                        .expect("cbl discover request")
                };

                for (query, limit, expected) in [
                    ("Batman", 25, 25),
                    ("batman", 25, 25),
                    ("Bat", 25, 25),
                    ("Batman", 100, 100),
                    ("Teen%20Titans", 25, 1),
                    ("X-Men", 25, 2),
                ] {
                    let (status, body, _, text) = call_app(request(format!(
                        "/api/v1/issue-identity/cbl-sources?q={query}&limit={limit}"
                    )))
                    .await;
                    assert_eq!(status, StatusCode::OK, "{query}/{limit}: {text}");
                    let items = body.as_array().expect("discovery list");
                    assert_eq!(items.len(), expected, "{query}/{limit}: {text}");
                    assert!(
                        items.iter().all(|item| !item["name"]
                            .as_str()
                            .unwrap_or_default()
                            .contains("Archived")),
                        "inactive rows must be excluded for {query}: {text}"
                    );
                }
            })
            .await;
    }

    #[tokio::test]
    async fn cbl_source_detail_is_served_from_rust_ingress_against_postgres() {
        // Deterministic DB-backed regression for #5484: the source-detail path
        // must be registered in this Vercel entry and dispatched to the Rust
        // get_cbl_source_list handler (not fall through to native_not_found).
        // Drive the real handler against a disposable schema and assert the
        // projected detail plus ordered entries, including Comic Vine IDs.
        let url = disposable_schema_url().await;
        let state = test_state(&url);
        TEST_ROLL_STATE
            .scope(state, async {
                let username = format!("cbl-detail-ingress-{}", std::process::id());
                let (access, _csrf, _user_id) = register_session(&username).await;

                let connection = TEST_ROLL_STATE
                    .try_with(Clone::clone)
                    .expect("test state")
                    .pool
                    .get()
                    .await
                    .expect("seed connection");
                connection
                    .batch_execute(
                        "INSERT INTO cbl_sources (id, repository, revision_sha) \
                         VALUES (1, '/mnt/bigdata/CBL-ReadingLists', 'abc123'); \
                         INSERT INTO cbl_source_lists \
                           (id, source_id, source_path, name, declared_issue_count, \
                            content_hash, revision_sha, active) \
                         VALUES \
                           (26, 1, 'BPRD/Plague of Frogs/Omnibus Vol 3.cbl', \
                            'B.P.R.D. Plague of Frogs Omnibus Vol. 3', 2, \
                            'h-bprd', 'abc123', TRUE); \
                         INSERT INTO external_identities \
                           (id, provider, entity_type, external_id) \
                         VALUES \
                           (10, 'comicvine', 'issue', '4000-1'), \
                           (11, 'comicvine', 'series', '4050-1'); \
                         INSERT INTO cbl_source_entries \
                           (id, list_id, position, series_name, issue_number, \
                            volume_year, publication_year, \
                            external_issue_identity_id, external_series_identity_id) \
                         VALUES \
                           (1, 26, 1, 'B.P.R.D.', '1', 2002, 2003, 10, 11), \
                           (2, 26, 2, 'B.P.R.D.', '2', NULL, 2004, NULL, 11);",
                    )
                    .await
                    .expect("seed cbl source detail");
                drop(connection);

                // Without credentials the registered path reaches the handler's
                // 401, not the ingress 404 fallback.
                let (status, _, _, text) = call_app(
                    Request::builder()
                        .method("GET")
                        .uri("/api/v1/issue-identity/cbl-sources/26")
                        .body(Body::empty())
                        .expect("unauthenticated cbl detail request"),
                )
                .await;
                assert_eq!(status, StatusCode::UNAUTHORIZED, "{text}");

                let (status, body, _, text) = call_app(
                    Request::builder()
                        .method("GET")
                        .uri("/api/v1/issue-identity/cbl-sources/26?limit=10")
                        .header(header::AUTHORIZATION, format!("Bearer {access}"))
                        .body(Body::empty())
                        .expect("authenticated cbl detail request"),
                )
                .await;
                assert_eq!(status, StatusCode::OK, "{text}");
                assert_eq!(body["id"], 26, "{text}");
                assert_eq!(
                    body["name"], "B.P.R.D. Plague of Frogs Omnibus Vol. 3",
                    "{text}"
                );
                assert_eq!(
                    body["source_repository"], "JoshCLWren/CBL-ReadingLists",
                    "mirror repository must project to public name: {text}"
                );
                assert_eq!(
                    body["source_path"], "BPRD/Plague of Frogs/Omnibus Vol 3.cbl",
                    "detail keeps the raw source path: {text}"
                );
                assert_eq!(body["entries_total"], 2, "{text}");
                let entries = body["entries"].as_array().expect("ordered entries");
                assert_eq!(entries.len(), 2, "{text}");
                assert_eq!(entries[0]["position"], 1, "{text}");
                assert_eq!(entries[0]["comicvine_issue_id"], "4000-1", "{text}");
                assert_eq!(entries[0]["comicvine_volume_id"], "4050-1", "{text}");
                assert_eq!(entries[1]["position"], 2, "{text}");
                assert!(
                    entries[1]["comicvine_issue_id"].is_null(),
                    "unmapped entry must have no comicvine issue id: {text}"
                );
            })
            .await;
    }

    #[tokio::test]
    async fn custom_cbl_overlap_decisions_ingress_reaches_rust_dispatch() {
        // Both overlap-decision path shapes must be registered in the Vercel
        // native_roll ingress (not just the inner service) so production
        // requests do not fall through to the Rust JSON 404 fallback.
        let cases = [
            ("GET", "/api/v2/reading-lists/26/overlap-decisions"),
            ("PUT", "/api/v2/reading-lists/26/overlap-decisions"),
            ("DELETE", "/api/v2/reading-lists/26/overlap-decisions/7"),
        ];
        for (method, uri) in cases {
            let mut router = app();
            let response = router
                .call(
                    Request::builder()
                        .method(method)
                        .uri(uri)
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .expect("router response");
            assert!(
                response.status() == StatusCode::UNAUTHORIZED
                    || response.status() == StatusCode::SERVICE_UNAVAILABLE
                    || response.status() == StatusCode::FORBIDDEN,
                "{method} {uri} must reach Rust dispatch, not the 404 fallback, got {}",
                response.status()
            );
            assert_eq!(
                response.headers().get("x-comicpile-api-runtime").unwrap(),
                "rust",
                "{method} {uri} runtime header"
            );
            let bytes = to_bytes(response.into_body(), 8192)
                .await
                .expect("body bytes");
            let text = String::from_utf8_lossy(&bytes);
            assert_ne!(
                text, r#"{"detail":"Not Found"}"#,
                "{method} {uri} must not hit native_not_found: {text}"
            );
        }
    }
}
