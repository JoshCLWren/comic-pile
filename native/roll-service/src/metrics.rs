//! Simple unauthenticated performance metrics for the native runtime.
//!
//! This preserves the legacy wire contract of `GET /api/metrics` and
//! `GET /api/v1/metrics` while serving it from the Rust binary.

use axum::Json;
use serde::Serialize;
use std::sync::OnceLock;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

static STARTUP: OnceLock<StartupMetrics> = OnceLock::new();

struct StartupMetrics {
    startup_time: f64,
    startup_instant: Instant,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct StartupMetricsResponse {
    pub startup_time: Option<f64>,
    pub startup_duration: Option<f64>,
}

fn startup() -> &'static StartupMetrics {
    STARTUP.get_or_init(|| {
        let now = SystemTime::now();
        let startup_time = now
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        StartupMetrics {
            startup_time,
            startup_instant: Instant::now(),
        }
    })
}

/// Return startup metrics for the current native process.
///
/// `startup_duration` is measured from first metrics initialization in this
/// process to the time of the request, preserving the legacy keys and types.
pub async fn get_metrics() -> Json<StartupMetricsResponse> {
    let started = startup();
    let startup_duration = started.startup_instant.elapsed().as_secs_f64();
    Json(StartupMetricsResponse {
        startup_time: Some(started.startup_time),
        startup_duration: Some(startup_duration),
    })
}

/// OpenAPI documentation for the legacy metrics endpoints.
#[utoipa::path(
    get,
    path = "/api/metrics",
    tag = "metrics",
    responses((status = 200, description = "Simple application startup metrics", body = StartupMetricsResponse))
)]
pub fn get_metrics_documentation() {}

#[cfg(test)]
mod tests {
    use super::get_metrics;

    #[tokio::test]
    async fn metrics_preserve_legacy_shape() {
        let payload = serde_json::to_value(get_metrics().await.0).expect("serialize metrics");
        assert!(payload.get("startup_time").is_some());
        assert!(payload.get("startup_duration").is_some());
        assert!(payload["startup_time"].is_number() || payload["startup_time"].is_null());
        assert!(payload["startup_duration"].is_number() || payload["startup_duration"].is_null());
    }
}
