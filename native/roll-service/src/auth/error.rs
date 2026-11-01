//! Authentication error types with Python-compatible HTTP statuses and details.

use axum::{http::StatusCode, response::IntoResponse};
use serde::Serialize;

/// Authentication failures. Messages are stable and contain no secrets.
#[derive(Debug, thiserror::Error)]
pub enum AuthError {
    #[error("Incorrect username or password")]
    InvalidCredentials,

    #[error("User not found")]
    UserNotFound,

    #[error("Username already registered")]
    UsernameExists,

    #[error("Email already registered")]
    EmailExists,

    #[error("Username or email already registered")]
    UserExists,

    #[error("Username cannot contain an '@' character.")]
    InvalidUsername,

    #[error("Sign in with your username, not your email.")]
    EmailLogin,

    #[error("Token has been revoked")]
    TokenRevoked,

    #[error("Invalid or expired token")]
    InvalidToken,

    #[error("Missing refresh token")]
    MissingRefreshToken,

    #[error("Invalid refresh token")]
    InvalidRefreshToken,

    #[error("Refresh token has been revoked")]
    RefreshTokenRevoked,

    #[error("User not found")]
    RefreshUserNotFound,

    #[error("Password changed; please sign in again.")]
    PasswordChanged,

    #[error("Password must be at least 6 characters.")]
    PasswordTooShort,

    #[error("Password must be at most 72 UTF-8 bytes.")]
    PasswordTooLong,

    #[error("Request validation failed")]
    Validation,

    #[error("Too many requests")]
    RateLimited,

    #[error("Internal server error")]
    InternalError,

    #[error("Database temporarily unavailable. Please retry.")]
    Unavailable,

    #[error("Database error")]
    DatabasePool(#[from] deadpool_postgres::PoolError),
    #[error("Database error")]
    DatabaseQuery(#[from] tokio_postgres::Error),
}

impl From<crate::ApiError> for AuthError {
    fn from(error: crate::ApiError) -> Self {
        if error.0 == StatusCode::SERVICE_UNAVAILABLE {
            AuthError::Unavailable
        } else {
            AuthError::InternalError
        }
    }
}

impl AuthError {
    /// The HTTP status and stable detail for this failure.
    pub fn status_and_detail(&self) -> (StatusCode, &'static str) {
        match self {
            AuthError::InvalidCredentials | AuthError::UserNotFound => {
                (StatusCode::UNAUTHORIZED, "Incorrect username or password")
            }
            AuthError::UsernameExists => (StatusCode::BAD_REQUEST, "Username already registered"),
            AuthError::EmailExists => (StatusCode::BAD_REQUEST, "Email already registered"),
            AuthError::UserExists => (
                StatusCode::BAD_REQUEST,
                "Username or email already registered",
            ),
            AuthError::InvalidUsername => (
                StatusCode::BAD_REQUEST,
                "Username cannot contain an '@' character.",
            ),
            AuthError::EmailLogin => (
                StatusCode::BAD_REQUEST,
                "Sign in with your username, not your email.",
            ),
            AuthError::TokenRevoked => (StatusCode::UNAUTHORIZED, "Token has been revoked"),
            AuthError::InvalidToken => (StatusCode::UNAUTHORIZED, "Invalid or expired token"),
            AuthError::MissingRefreshToken => (StatusCode::UNAUTHORIZED, "Missing refresh token"),
            AuthError::InvalidRefreshToken => (StatusCode::UNAUTHORIZED, "Invalid refresh token"),
            AuthError::RefreshTokenRevoked => {
                (StatusCode::UNAUTHORIZED, "Refresh token has been revoked")
            }
            AuthError::RefreshUserNotFound => (StatusCode::UNAUTHORIZED, "User not found"),
            AuthError::PasswordChanged => (
                StatusCode::UNAUTHORIZED,
                "Password changed; please sign in again.",
            ),
            AuthError::PasswordTooShort => (
                StatusCode::UNPROCESSABLE_ENTITY,
                "Password must be at least 6 characters.",
            ),
            AuthError::PasswordTooLong => (
                StatusCode::UNPROCESSABLE_ENTITY,
                "Password must be at most 72 UTF-8 bytes.",
            ),
            AuthError::Validation => (
                StatusCode::UNPROCESSABLE_ENTITY,
                "Request validation failed",
            ),
            AuthError::RateLimited => (StatusCode::TOO_MANY_REQUESTS, "Too many requests"),
            AuthError::InternalError => {
                (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error")
            }
            AuthError::Unavailable => (
                StatusCode::SERVICE_UNAVAILABLE,
                "Database temporarily unavailable. Please retry.",
            ),
            AuthError::DatabasePool(_) | AuthError::DatabaseQuery(_) => (
                StatusCode::SERVICE_UNAVAILABLE,
                "Database temporarily unavailable. Please retry.",
            ),
        }
    }
}

impl IntoResponse for AuthError {
    fn into_response(self) -> axum::response::Response {
        let (status, detail) = self.status_and_detail();
        let mut response = (status, axum::Json(ErrorResponse { detail })).into_response();
        if status == StatusCode::UNAUTHORIZED {
            response.headers_mut().insert(
                axum::http::header::WWW_AUTHENTICATE,
                axum::http::HeaderValue::from_static("Bearer"),
            );
        }
        if status == StatusCode::SERVICE_UNAVAILABLE {
            response.headers_mut().insert(
                axum::http::header::RETRY_AFTER,
                axum::http::HeaderValue::from_static("30"),
            );
        }
        response
    }
}

/// Python-compatible error envelope.
#[derive(Serialize)]
pub struct ErrorResponse {
    pub detail: &'static str,
}

/// Result alias used by the authentication service.
pub type AuthResult<T> = Result<T, AuthError>;
