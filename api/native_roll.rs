//! Vercel's native Rust ingress for the Roll endpoint cutover.
//! The health probe never reads database configuration.
use axum::{
    extract::Request,
    http::{HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
    Json, Router,
};
use comicpile_roll_service::{config::Config, router as roll_router, AppState};
use std::sync::{Arc, OnceLock};
use tower::{Service, ServiceBuilder};
use vercel_runtime::{axum::VercelLayer, Error};

async fn native_health() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "status": "ok",
        "runtime": "rust",
        "service": "roll"
    }))
}

static ROLL_STATE: OnceLock<Result<Arc<AppState>, &'static str>> = OnceLock::new();

async fn native_bootstrap(mut request: Request) -> Response {
    // The isolated native path keeps Python serving the user-facing endpoint
    // until the Rust runtime passes the real production startup check.
    if request.uri().path() == "/api/_native_roll/bootstrap" {
        let target = match request.uri().query() {
            Some(query) => format!("/api/v2/roll/bootstrap?{query}"),
            None => "/api/v2/roll/bootstrap".to_owned(),
        };
        *request.uri_mut() = target.parse().expect("valid native bootstrap URI");
    }
    // Cold-start the native Roll pool only for authenticated bootstrap traffic.
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
    result
}

fn app() -> Router {
    Router::new()
        .route("/api/_native_roll/health", get(native_health))
        .route("/api/v2/roll/bootstrap", get(native_bootstrap))
        .route("/api/_native_roll/bootstrap", get(native_bootstrap))
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
    use super::app;
    use axum::{
        body::{to_bytes, Body},
        http::{header, Request, StatusCode},
    };
    use tower::Service;

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
}
