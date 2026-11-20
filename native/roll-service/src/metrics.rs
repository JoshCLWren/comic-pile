//! Simple unauthenticated performance metrics for the native runtime.
//!
//! This preserves the legacy wire contract of `GET /api/metrics` and
//! `GET /api/v1/metrics` while serving it from the Rust binary.

use axum::Json;
use serde::Serialize;
use std::sync::OnceLock;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

static START_INSTANT: OnceLock<Instant> = OnceLock::new();
static STARTUP_TIME_SECS: OnceLock<f64> = OnceLock::new();
static STARTUP_DURATION_SECS: OnceLock<f64> = OnceLock::new();

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct StartupMetricsResponse {
    pub startup_time: Option<f64>,
    pub startup_duration: Option<f64>,
}

fn now_epoch_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

/// Capture the startup start instant during native initialization.
pub fn record_startup_start() {
    let _ = START_INSTANT.get_or_init(Instant::now);
    let _ = STARTUP_TIME_SECS.get_or_init(now_epoch_secs);
}

/// Mark startup as complete and store the finished startup duration.
///
/// Repeated calls keep the first completed measurement.
pub fn mark_startup_complete() {
    record_startup_start();
    let duration = START_INSTANT
        .get()
        .map(Instant::elapsed)
        .unwrap_or_default()
        .as_secs_f64();
    let _ = STARTUP_DURATION_SECS.set(duration);
}

/// Return startup metrics for the current native process.
///
/// Returns the stored startup timestamp and stored completed startup duration.
/// If startup completion was not explicitly marked, the duration is finalized on
/// first metrics access and then reused for subsequent requests.
pub async fn get_metrics() -> Json<StartupMetricsResponse> {
    record_startup_start();
    let startup_duration = *STARTUP_DURATION_SECS.get_or_init(|| {
        START_INSTANT
            .get()
            .map(Instant::elapsed)
            .unwrap_or_default()
            .as_secs_f64()
    });
    Json(StartupMetricsResponse {
        startup_time: STARTUP_TIME_SECS.get().copied(),
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

/// OpenAPI documentation for the versioned metrics alias.
#[utoipa::path(
    get,
    path = "/api/v1/metrics",
    tag = "metrics",
    responses((status = 200, description = "Simple application startup metrics", body = StartupMetricsResponse))
)]
pub fn get_v1_metrics_documentation() {}

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

    #[tokio::test]
    async fn startup_duration_is_stable_across_requests() {
        let first = get_metrics().await.0.startup_duration;
        let second = get_metrics().await.0.startup_duration;
        assert_eq!(first, second);
    }
}
