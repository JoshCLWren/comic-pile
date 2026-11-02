//! Vercel's native Rust ingress for the Roll endpoint cutover.
//! The health probe never reads database configuration.
use axum::{
    extract::Request,
    http::{HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, patch, post},
    Json, Router,
};
use comicpile_roll_service::{
    auth::BackgroundTasks, config::Config, router as roll_router, AppState,
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
        "service": "roll"
    }))
}

static ROLL_STATE: OnceLock<Result<Arc<AppState>, &'static str>> = OnceLock::new();

/// Keep the request's query and authentication intact when the isolated
/// production probe is forwarded through the same authenticated Rust handler.
fn normalize_bootstrap_request(request: &mut Request) {
    if request.uri().path() == "/api/_native_roll/bootstrap" {
        let target = match request.uri().query() {
            Some(query) => format!("/api/v2/roll/bootstrap?{query}"),
            None => "/api/v2/roll/bootstrap".to_owned(),
        };
        *request.uri_mut() = target.parse().expect("valid native bootstrap URI");
    }
}

async fn native_dispatch(request: Request) -> Response {
    // Log only the fixed ingress path, status and elapsed time. Never log query,
    // authorization headers, response JSON or other user data.
    let ingress_path = request.uri().path().to_owned();
    let started = std::time::Instant::now();
    // Cold-start the native Roll pool only for authenticated traffic.
    // Keep health independent of DB secrets and failures.
    let mut result = match ROLL_STATE.get_or_init(|| {
        Config::from_vercel_env()
            .and_then(AppState::new)
            .map(Arc::new)
            .map_err(|err| {
                // ConfigError is a static, credential-free message.
                eprintln!("native_roll initialisation failed: {err}");
                err.0
            })
    }) {
        Ok(state) => {
            let mut router = roll_router(state.clone());
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

async fn native_bootstrap(mut request: Request) -> Response {
    normalize_bootstrap_request(&mut request);
    native_dispatch(request).await
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

fn app() -> Router {
    Router::new()
        .route("/api/_native_roll/health", get(native_health))
        .route("/api/v2/roll/bootstrap", get(native_bootstrap))
        .route("/api/v2/roll/dice-command", post(native_dispatch))
        .route("/api/v2/roll/offer", post(native_dispatch))
        .route("/api/v2/roll/reset", post(native_dispatch))
        .route("/api/v2/reading-boundaries", post(native_dispatch))
        .route("/api/v2/queue-entries/{thread_id}", get(native_dispatch))
        .route("/api/v2/queue-entries/{thread_id}", patch(native_dispatch))
        .route("/api/v2/queue-orders", post(native_dispatch))
        .route("/api/v2/threads", get(native_dispatch))
        .route("/api/_native_roll/bootstrap", get(native_bootstrap))
        .route("/api/v1/roll/dismiss-pending", post(native_dispatch))
        .route("/api/roll/dismiss-pending", post(native_dispatch))
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
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    vercel_runtime::run(NativeVercelService { router: app() }).await
}

#[cfg(test)]
mod tests {
    use super::{app, normalize_bootstrap_request, NativeVercelService};
    use axum::{
        body::{to_bytes, Body},
        http::{header, Request, StatusCode},
        routing::get,
        Router,
    };
    use comicpile_roll_service::auth::BackgroundTasks;
    use tower::Service;
    use vercel_runtime::{AppState as VercelState, LogContext};

    #[tokio::test]
    async fn isolated_bootstrap_preserves_auth_and_query_through_native_ingress() {
        let build_request = || {
            Request::builder()
                .method("GET")
                .uri("/api/_native_roll/bootstrap?timezone=America%2FChicago")
                .header("authorization", "Bearer synthetic-test-token")
                .body(Body::empty())
                .expect("isolated native request")
        };
        let mut normalized = build_request();
        normalize_bootstrap_request(&mut normalized);
        assert_eq!(
            normalized.uri().to_string(),
            "/api/v2/roll/bootstrap?timezone=America%2FChicago"
        );
        assert_eq!(
            normalized.headers().get("authorization"),
            Some(&axum::http::HeaderValue::from_static(
                "Bearer synthetic-test-token"
            ))
        );

        // Exercise the actual production Axum router; the native runtime marker
        // distinguishes this path from an accidental 404 or Python fallback.
        let mut router = app();
        let response = router.call(build_request()).await.expect("native response");
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime"),
            Some(&axum::http::HeaderValue::from_static("rust"))
        );
        assert!(
            response.status() == StatusCode::SERVICE_UNAVAILABLE
                || response.status() == StatusCode::UNAUTHORIZED,
            "isolated path must reach native startup or bearer authentication"
        );
    }

    #[tokio::test]
    async fn native_probe_serves_json_without_config_or_database() {
        let mut router = app();
        let request = Request::builder()
            .method("GET")
            .uri("/api/_native_roll/health")
            .body(Body::empty())
            .expect("valid request");
        let response = router.call(request).await.expect("health response");
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers().get(header::CONTENT_TYPE),
            Some(&axum::http::HeaderValue::from_static("application/json"))
        );
        let body = to_bytes(response.into_body(), 1024)
            .await
            .expect("health JSON");
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&body).expect("valid JSON"),
            serde_json::json!({"status": "ok", "runtime": "rust", "service": "roll"})
        );
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
}
