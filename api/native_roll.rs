//! Vercel's official Rust Function bridge for the Roll cutover.
//! The native ingress diagnostic must not initialize the Roll database or auth state.
//! GET /api/v2/roll/bootstrap remains routed to Python until its own cutover.
use axum::{routing::get, Json, Router};
use tower::ServiceBuilder;
use vercel_runtime::{axum::VercelLayer, Error};

async fn native_health() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "status": "ok",
        "runtime": "rust",
        "service": "roll"
    }))
}

fn app() -> Router {
    Router::new().route("/api/_native_roll/health", get(native_health))
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    // Only the isolated health route is wired here. Native Roll handlers and
    // their database pools belong in the subsequent production cutover PR.
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
