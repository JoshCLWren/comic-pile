//! Regression coverage for double-submit CSRF on the protected native routes.
//!
//! These are committed replacements for a throwaway probe: a missing cookie, a
//! missing header and a mismatched pair must each be rejected with 403 before
//! authentication or database work, while a matching pair proceeds to bearer
//! authentication. CSRF must never be weakened to make another check pass.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, AppState};
use serde_json::Value;
use std::sync::Arc;
use tower::ServiceExt;

fn state() -> Arc<AppState> {
    Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
                "RUST_ROLL_JWT_SECRET" => Some("synthetic-csrf-test-secret".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    )
}

async fn status_and_body(
    cookie: Option<&str>,
    csrf_header: Option<&str>,
    path: &str,
) -> (StatusCode, Option<Value>) {
    let mut builder = Request::builder()
        .method("POST")
        .uri(path)
        .header(header::CONTENT_TYPE, "application/json");
    if let Some(cookie) = cookie {
        builder = builder.header(header::COOKIE, format!("csrf_token={cookie}"));
    }
    if let Some(csrf_header) = csrf_header {
        builder = builder.header("x-csrf-token", csrf_header);
    }
    let response = router(state())
        .oneshot(builder.body(Body::from("{}")).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let body = to_bytes(response.into_body(), 4096).await.unwrap();
    let body = serde_json::from_slice::<Value>(&body).ok();
    (status, body)
}

#[tokio::test]
async fn protected_native_mutations_require_a_matching_double_submit_pair() {
    let path = "/api/v1/roll/dismiss-pending";

    for (cookie, header_value) in [
        (None, None),
        (Some("token-value"), None),
        (None, Some("token-value")),
        (Some("token-value"), Some("different-value")),
    ] {
        let (status, body) = status_and_body(cookie, header_value, path).await;
        assert_eq!(
            status,
            StatusCode::FORBIDDEN,
            "missing or mismatched CSRF pair must be rejected"
        );
        assert_eq!(
            body,
            Some(serde_json::json!({"detail": "CSRF token missing or invalid"}))
        );
    }

    // A valid pair clears the CSRF gate and reaches bearer authentication, which
    // rejects the unauthenticated request with 401 rather than 403.
    let (status, _) = status_and_body(Some("token-value"), Some("token-value"), path).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn bootstrap_and_recovery_endpoints_stay_csrf_exempt() {
    for path in [
        "/api/v2/auth/login",
        "/api/v2/auth/register",
        "/api/v2/auth/refresh",
        "/api/v2/auth/forgot-password",
        "/api/v2/auth/reset-password",
        "/api/v1/auth/login",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
    ] {
        let (status, _) = status_and_body(None, None, path).await;
        assert_ne!(
            status,
            StatusCode::FORBIDDEN,
            "{path} must remain exempt so a first-time browser can authenticate"
        );
    }
}

#[tokio::test]
async fn logout_requires_a_csrf_pair_on_the_live_alias() {
    let (status, _) = status_and_body(None, None, "/api/v1/auth/logout").await;
    assert_eq!(
        status,
        StatusCode::FORBIDDEN,
        "logout mutates server-side auth state and must stay CSRF-protected"
    );
}
