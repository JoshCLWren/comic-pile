//! CSRF double-submit checks; JWT identity is the canonical, verified auth::identity extractor.
use crate::ApiError;
use axum::{
    extract::Request,
    http::StatusCode,
    middleware::Next,
    response::{IntoResponse, Response},
};

fn cookie_token(headers: &axum::http::HeaderMap) -> Option<String> {
    headers
        .get(axum::http::header::COOKIE)?
        .to_str()
        .ok()?
        .split(';')
        .map(str::trim)
        .find_map(|part| part.strip_prefix("csrf_token=").map(str::to_owned))
        .filter(|token| !token.is_empty())
}
fn constant_time_eq(left: &str, right: &str) -> bool {
    let (left, right) = (left.as_bytes(), right.as_bytes());
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right)
        .fold(0u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

pub async fn csrf_middleware(request: Request, next: Next) -> Response {
    let method = request.method().as_str();
    let path = request.uri().path().trim_end_matches('/');
    let protected =
        matches!(method, "POST" | "PUT" | "PATCH" | "DELETE") && path.starts_with("/api/");
    let exempt = matches!(
        path,
        "/api/v2/auth/login"
            | "/api/v2/auth/register"
            | "/api/v2/auth/refresh"
            | "/api/v1/auth/login"
            | "/api/v1/auth/register"
            | "/api/v1/auth/refresh"
            | "/api/auth/login"
            | "/api/auth/register"
            | "/api/auth/refresh"
    );
    if protected && !exempt {
        let cookie = cookie_token(request.headers());
        let header = request
            .headers()
            .get("x-csrf-token")
            .and_then(|v| v.to_str().ok());
        let valid = cookie
            .as_deref()
            .zip(header)
            .is_some_and(|(cookie, header)| constant_time_eq(cookie, header));
        if !valid {
            return ApiError(
                StatusCode::FORBIDDEN,
                "CSRF token missing or invalid".into(),
            )
            .into_response();
        }
    }
    next.run(request).await
}
