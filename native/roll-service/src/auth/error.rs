//! Authentication error types

use axum::{http::StatusCode, response::IntoResponse};
use serde::Serialize;

/// Authentication error types with appropriate HTTP status codes
#[derive(Debug, thiserror::Error)]
pub enum AuthError {
    #[error("Invalid credentials")]
    InvalidCredentials,

    #[error("User not found")]
    UserNotFound,

    #[error("Username already exists")]
    UsernameExists,

    #[error("Email already exists")]
    EmailExists,

    #[error("Token has been revoked")]
    TokenRevoked,

    #[error("Invalid or expired token")]
    InvalidToken,

    #[error("Invalid token format")]
    InvalidTokenFormat,

    #[error("Password changed; please sign in again")]
    PasswordChanged,

    #[error("Missing or invalid authorization header")]
    MissingAuthHeader,

    #[error("Missing refresh token")]
    MissingRefreshToken,

    #[error("Invalid refresh token")]
    InvalidRefreshToken,

    #[error("Password too short")]
    PasswordTooShort,

    #[error("Password too long (UTF-8 bytes)")]
    PasswordTooLong,

    #[error("Username cannot contain '@'")]
    InvalidUsername,

    #[error("Account temporarily locked")]
    AccountLocked,

    #[error("Internal server error")]
    InternalError,

    #[error("Database error")]
    DatabasePool(#[from] deadpool_postgres::PoolError),
    #[error("Database query error")]
    DatabaseQuery(#[from] tokio_postgres::Error),
}

impl IntoResponse for AuthError {
    fn into_response(self) -> axum::response::Response {
        let (status, error_message) = match self {
            AuthError::InvalidCredentials => {
                (StatusCode::UNAUTHORIZED, "Incorrect username or password")
            }
            AuthError::UserNotFound => (StatusCode::UNAUTHORIZED, "Incorrect username or password"),
            AuthError::UsernameExists => (StatusCode::BAD_REQUEST, "Username already registered"),
            AuthError::EmailExists => (StatusCode::BAD_REQUEST, "Email already registered"),
            AuthError::TokenRevoked => (StatusCode::UNAUTHORIZED, "Token has been revoked"),
            AuthError::InvalidToken => (StatusCode::UNAUTHORIZED, "Invalid or expired token"),
            AuthError::InvalidTokenFormat => (StatusCode::UNAUTHORIZED, "Invalid token format"),
            AuthError::PasswordChanged => (
                StatusCode::UNAUTHORIZED,
                "Password changed; please sign in again",
            ),
            AuthError::MissingAuthHeader => (
                StatusCode::UNAUTHORIZED,
                "Missing or invalid authorization header",
            ),
            AuthError::MissingRefreshToken => (StatusCode::UNAUTHORIZED, "Missing refresh token"),
            AuthError::InvalidRefreshToken => (StatusCode::UNAUTHORIZED, "Invalid refresh token"),
            AuthError::PasswordTooShort => (
                StatusCode::UNPROCESSABLE_ENTITY,
                "Password must be at least 8 characters",
            ),
            AuthError::PasswordTooLong => (
                StatusCode::UNPROCESSABLE_ENTITY,
                "Password must be at most 72 UTF-8 bytes",
            ),
            AuthError::InvalidUsername => (StatusCode::BAD_REQUEST, "Username cannot contain '@'"),
            AuthError::AccountLocked => {
                (StatusCode::TOO_MANY_REQUESTS, "Account temporarily locked")
            }
            AuthError::InternalError => {
                (StatusCode::INTERNAL_SERVER_ERROR, "Internal server error")
            }
            AuthError::DatabasePool(_) | AuthError::DatabaseQuery(_) => {
                (StatusCode::INTERNAL_SERVER_ERROR, "Internal server error")
            }
        };

        let body = ErrorResponse {
            error: error_message.to_string(),
        };

        (status, axum::Json(body)).into_response()
    }
}

/// Standard error response format
#[derive(Serialize)]
pub struct ErrorResponse {
    pub error: String,
}

/// Type alias for Result<T, AuthError>
pub type AuthResult<T> = Result<T, AuthError>;
