//! CSRF double-submit checks; JWT identity is the canonical, verified auth::identity extractor.
use crate::ApiError;
use axum::{
    extract::{FromRequestParts, Request},
    http::{request::Parts, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
};

pub struct CsrfToken {
    token: String,
}
impl CsrfToken {
    pub fn token(&self) -> &str {
        &self.token
    }
}

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
impl<S: Send + Sync> FromRequestParts<S> for CsrfToken {
    type Rejection = ApiError;
    async fn from_request_parts(parts: &mut Parts, _state: &S) -> Result<Self, Self::Rejection> {
        Ok(Self {
            token: cookie_token(&parts.headers)
                .unwrap_or_else(crate::auth::utils::generate_csrf_token),
        })
    }
}
pub async fn csrf_middleware(request: Request, next: Next) -> Response {
    let method = request.method().as_str();
    let path = request.uri().path().trim_end_matches('/');
    let protected = matches!(method, "POST" | "PUT" | "PATCH" | "DELETE");
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
        if cookie.as_deref().is_none_or(|token| Some(token) != header) {
            return ApiError(
                StatusCode::FORBIDDEN,
                "CSRF token missing or invalid".into(),
            )
            .into_response();
        }
    }
    next.run(request).await
}
