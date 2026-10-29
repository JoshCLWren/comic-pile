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
    vercel_runtime::run(ServiceBuilder::new().layer(VercelLayer::new()).service(app())).await
}

#[cfg(test)]
mod tests {
    use super::{app, native_health};

    #[test]
    fn native_health_router_does_not_require_application_state() {
        let _router = app();
    }

    #[tokio::test]
    async fn native_probe_reports_rust_without_config_or_database() {
        assert_eq!(
            native_health().await.0,
            serde_json::json!({"status": "ok", "runtime": "rust", "service": "roll"})
        );
    }
}
