//! Service error types.

use axum::http::StatusCode;

/// Service-level errors.
#[derive(Debug)]
pub enum ServiceError {
    /// Resource not found.
    NotFound(&'static str),
    /// Bad request.
    BadRequest(&'static str),
    /// Unauthorized access.
    Unauthorized(&'static str),
    /// Internal server error.
    InternalError,
    /// Database error.
    DatabaseError,
}

impl std::fmt::Display for ServiceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ServiceError::NotFound(msg) => write!(f, "Not found: {}", msg),
            ServiceError::BadRequest(msg) => write!(f, "Bad request: {}", msg),
            ServiceError::Unauthorized(msg) => write!(f, "Unauthorized: {}", msg),
            ServiceError::InternalError => write!(f, "Internal server error"),
            ServiceError::DatabaseError => write!(f, "Database error"),
        }
    }
}

impl std::error::Error for ServiceError {}

impl From<sqlx::Error> for ServiceError {
    fn from(_error: sqlx::Error) -> Self {
        ServiceError::DatabaseError
    }
}

impl From<serde_json::Error> for ServiceError {
    fn from(_error: serde_json::Error) -> Self {
        ServiceError::BadRequest("Invalid JSON")
    }
}

impl From<uuid::Error> for ServiceError {
    fn from(_error: uuid::Error) -> Self {
        ServiceError::BadRequest("Invalid UUID")
    }
}

impl ServiceError {
    /// Get the HTTP status code for this error.
    pub fn status_code(&self) -> StatusCode {
        match self {
            ServiceError::NotFound(_) => StatusCode::NOT_FOUND,
            ServiceError::BadRequest(_) => StatusCode::BAD_REQUEST,
            ServiceError::Unauthorized(_) => StatusCode::UNAUTHORIZED,
            ServiceError::InternalError => StatusCode::INTERNAL_SERVER_ERROR,
            ServiceError::DatabaseError => StatusCode::INTERNAL_SERVER_ERROR,
        }
    }
}