//! Vercel's native Rust ingress for the Issue endpoint cutover.
//! The health probe never reads database configuration.
use axum::{
    extract::Request,
    http::{HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{patch, get},
    Json, Router,
};
use comicpile_roll_service::{config::Config, router as issue_router, AppState};
use std::sync::{Arc, OnceLock};
use tower::{Service, ServiceBuilder};
use vercel_runtime::{axum::VercelLayer, Error};

async fn native_health() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "status": "ok",
        "runtime": "rust",
        "service": "issue"
    }))
}

static ISSUE_STATE: OnceLock<Result<Arc<AppState>, &'static str>> = OnceLock::new();

/// Keep the request's query and authentication intact when the isolated
/// production probe is forwarded through the same authenticated Rust handler.
fn normalize_issue_request(request: &mut Request) {
    if request.uri().path() == "/api/_native_issue/health" {
        let target = match request.uri().query() {
            Some(query) => format!("/api/v2/issues/health?{query}"),
            None => "/api/v2/issues/health".to_owned(),
        };
        *request.uri_mut() = target.parse().expect("valid native issue URI");
    }
}

async fn native_dispatch(request: Request) -> Response {
    // Log only the fixed ingress path, status and elapsed time. Never log query,
    // authorization headers, response JSON or other user data.
    let ingress_path = request.uri().path().to_owned();
    let started = std::time::Instant::now();
    // Cold-start the native Issue service only for authenticated traffic.
    // Keep health independent of DB secrets and failures.
    let mut result = match ISSUE_STATE.get_or_init(|| {
        Config::from_vercel_env()
            .and_then(AppState::new)
            .map(Arc::new)
            .map_err(|err| {
                // ConfigError is a static, credential-free message.
                eprintln!("native_issue initialisation failed: {err}");
                err.0
            })
    }) {
        Ok(state) => {
            let mut router = issue_router(state.clone());
            match router.call(request).await {
                Ok(response) => response,
                Err(never) => match never {},
            }
        }
        Err(_) => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({"detail": "Native Issue unavailable"})),
        )
            .into_response(),
    };
    result
        .headers_mut()
        .insert("x-comicpile-api-runtime", HeaderValue::from_static("rust"));
    eprintln!(
        "native_issue route={} runtime=rust status={} elapsed_ms={}",
        ingress_path,
        result.status().as_u16(),
        started.elapsed().as_millis()
    );
    result
}

async fn native_bootstrap(mut request: Request) -> Response {
    normalize_issue_request(&mut request);
    native_dispatch(request).await
}

fn app() -> Router {
    Router::new()
        .route("/api/_native_issue/health", get(native_health))
        .route("/api/v2/issues/health", get(native_bootstrap))
        .route("/api/v2/issues/:issue_id", patch(native_dispatch))
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    vercel_runtime::run(
        ServiceBuilder::new()
            .layer(VercelLayer::new())
            .service(app()),
    )
    .await
}

#[cfg(test)]
mod tests {
    use super::{app, normalize_issue_request};
    use axum::{
        body::{to_bytes, Body},
        http::{header, Request, StatusCode},
    };
    use tower::Service;

    #[tokio::test]
    async fn isolated_health_serves_json_without_config_or_database() {
        let mut router = app();
        let request = Request::builder()
            .method("GET")
            .uri("/api/_native_issue/health")
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
            serde_json::json!({"status": "ok", "runtime": "rust", "service": "issue"})
        );
    }
}