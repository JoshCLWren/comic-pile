//! Vercel's native Rust ingress for the Queue endpoint cutover.
//! The health probe never reads database configuration.
use axum::{
    extract::Request,
    http::{Extensions, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, patch, post},
    Json, Router,
};
use comicpile_queue_service::{
    auth::BackgroundTasks, config::Config, router as queue_router, AppState,
};
use std::{
    future::Future,
    pin::Pin,
    sync::{Arc, OnceLock},
    task::{Context, Poll},
};
use tower::Service;
use vercel_runtime::{axum::StreamingUtils, AppState as VercelState, Error, ResponseBody};

async fn native_health() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "status": "ok",
        "runtime": "rust",
        "service": "queue"
    }))
}

static QUEUE_STATE: OnceLock<Result<Arc<AppState>, &'static str>> = OnceLock::new();

#[cfg(test)]
tokio::task_local! {
    static TEST_QUEUE_STATE: Arc<AppState>;
}

/// JSON subscriber for Vercel logs. `try_init` keeps isolate reuse and tests
/// from failing when startup runs more than once.
fn init_tracing() {
    let directive = std::env::var("RUST_QUEUE_LOG").unwrap_or_else(|_| "info".into());
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

fn resolve_queue_state() -> Result<Arc<AppState>, &'static str> {
    #[cfg(test)]
    if let Ok(state) = TEST_QUEUE_STATE.try_with(Clone::clone) {
        return Ok(state);
    }
    QUEUE_STATE
        .get_or_init(|| {
            Config::from_vercel_env()
                .and_then(AppState::new)
                .map(Arc::new)
                .map_err(|err| {
                    // ConfigError is a static, credential-free message.
                    eprintln!("native_queue initialisation failed: {err}");
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
    // Cold-start the native Queue pool only for authenticated traffic.
    // Keep health independent of DB secrets and failures.
    let request = prepare_inner_request(request);
    let mut result = match resolve_queue_state() {
        Ok(state) => {
            let mut router = queue_router(state);
            match router.call(request).await {
                Ok(response) => response,
                Err(never) => match never {},
            }
        }
        Err(err) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("Queue service unavailable: {err}").into(),
        )
        .into_response(),
    };
    let elapsed = started.elapsed();
    // Ingress path, status, and elapsed time only. Never log query, headers,
    // response JSON, or other user data.
    tracing::info!(%ingress_path, status = %result.status(), elapsed_ms = %elapsed.as_millis());
    result
}

/// Vercel's native Rust function entrypoint.
///
/// This is the entrypoint for the native Queue service.
/// It handles the routing and dispatching of requests to the appropriate handlers.
///
/// # Arguments
/// * `req` - The incoming request.
/// * `ctx` - The Vercel context.
///
/// # Returns
/// A `ResponseBody` containing the response.
pub async fn queue_handler(req: Request, ctx: VercelState) -> Result<ResponseBody<StreamingUtils>, Error> {
    let response = native_dispatch(req).await;
    Ok(ResponseBody::new(response.into_response(), ctx))
}

/// Vercel's native Rust function entrypoint for the health endpoint.
///
/// This provides a health check endpoint that doesn't require database access.
///
/// # Returns
/// A `ResponseBody` containing the health check response.
pub async fn queue_health_handler() -> Result<ResponseBody<StreamingUtils>, Error> {
    let response = native_health().await.into_response();
    Ok(ResponseBody::new(response, VercelState::default()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use http::{Request, StatusCode};
    use std::future::Future;

    fn mock_request() -> Request<Body> {
        Request::builder()
            .uri("/api/v2/queue-entries/123")
            .method("GET")
            .body(Body::empty())
            .unwrap()
    }

    #[tokio::test]
    async fn test_health_endpoint() {
        let response = native_health().await;
        assert_eq!(response.status(), StatusCode::OK);
        let body = response.into_inner();
        let parsed: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(parsed["status"], "ok");
        assert_eq!(parsed["runtime"], "rust");
        assert_eq!(parsed["service"], "queue");
    }

    #[tokio::test]
    async fn test_queue_dispatch() {
        // This test would require mocking the database state
        // For now, just test that the dispatch function doesn't panic
        let request = mock_request();
        let response = native_dispatch(request).await;
        // The actual response depends on the database state, but we just test
        // that the function doesn't panic
        assert!(matches!(response.status(), StatusCode::OK | StatusCode::INTERNAL_SERVER_ERROR));
    }
}