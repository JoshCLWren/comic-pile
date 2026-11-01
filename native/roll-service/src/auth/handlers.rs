//! HTTP handlers for authentication endpoints

use axum::{
    extract::{Query, State},
    http::{HeaderMap, Request},
    response::{IntoResponse, Response},
    Json,
};
use serde::Deserialize;
use std::sync::Arc;
use tokio::time::{Duration, Instant};
use tower::ServiceExt;
use tower_http::timeout::TimeoutLayer;
use tracing::{info, warn};

use crate::auth::{
    dto::*,
    error::{AuthError, AuthResult},
    middleware::CsrfToken,
    services::{AuthService, PasswordResetService},
    utils::get_client_ip,
};
use crate::{AppState, ApiError};

/// Rate limiting configuration
const RATE_LIMIT_LOGIN: (u32, Duration) = (5, Duration::from_secs(60));
const RATE_LIMIT_REFRESH: (u32, Duration) = (20, Duration::from_secs(60));
const RATE_LIMIT_FORGOT_PASSWORD: (u32, Duration) = (3, Duration::from_secs(60));

/// State for rate limiting
#[derive(Clone)]
struct RateLimitState {
    attempts: Arc<std::sync::RwLock<std::collections::HashMap<String, Vec<Instant>>>>,
}

impl RateLimitState {
    fn new() -> Self {
        Self {
            attempts: Arc::new(std::sync::RwLock::new(std::collections::HashMap::new())),
        }
    }

    async fn check_rate_limit(&self, identifier: &str, limit: (u32, Duration)) -> Result<(), AuthError> {
        let now = Instant::now();
        let mut attempts = self.attempts.write().unwrap();
        let user_attempts = attempts.entry(identifier.to_string()).or_insert_with(Vec::new);

        // Remove old attempts
        user_attempts.retain(|&attempt| now.duration_since(attempt) < limit.1);

        if user_attempts.len() >= limit.0 as usize {
            return Err(AuthError::AccountLocked);
        }

        user_attempts.push(now);
        Ok(())
    }
}

/// Register a new user
pub async fn register(
    State(state): State<Arc<AppState>>,
    State(rate_limit): State<Arc<RateLimitState>>,
    Json(request): Json<RegisterRequest>,
) -> AuthResponse<TokenResponse> {
    // Validate request
    if let Err(errors) = request.validate() {
        return Err(AuthError::InternalError); // Simplified error handling
    }

    // Check rate limit (by IP for registration)
    let ip = get_client_ip(&HeaderMap::new(), None);
    rate_limit.check_rate_limit(&ip, RATE_LIMIT_LOGIN).await?;

    let auth_service = AuthService::new(state.clone());
    let result = auth_service.register(&request).await?;

    info!("User registered: {}", request.username);
    Ok(Json(result))
}

/// Login user and return tokens
pub async fn login(
    State(state): State<Arc<AppState>>,
    State(rate_limit): State<Arc<RateLimitState>>,
    Json(request): Json<LoginRequest>,
) -> AuthResponse<TokenResponse> {
    // Validate request
    if let Err(errors) = request.validate() {
        return Err(AuthError::InternalError); // Simplified error handling
    }

    // Check rate limit (by username for login)
    rate_limit.check_rate_limit(&request.username, RATE_LIMIT_LOGIN).await?;

    let auth_service = AuthService::new(state.clone());
    let result = auth_service.login(&request).await?;

    info!("User logged in: {}", request.username);
    Ok(Json(result))
}

/// Refresh access token
pub async fn refresh(
    State(state): State<Arc<AppState>>,
    State(rate_limit): State<Arc<RateLimitState>>,
    Json(request): Json<RefreshTokenRequest>,
) -> AuthResponse<TokenResponse> {
    // Validate request
    if let Err(errors) = request.validate() {
        return Err(AuthError::InternalError); // Simplified error handling
    }

    // Check rate limit (by refresh token for refresh)
    let token_hash = Self::hash_token(&request.refresh_token);
    rate_limit.check_rate_limit(&token_hash, RATE_LIMIT_REFRESH).await?;

    let auth_service = AuthService::new(state.clone());
    let result = auth_service.refresh_token(&request.refresh_token).await?;

    info!("Token refreshed");
    Ok(Json(result))
}

/// Logout user by revoking token
pub async fn logout(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> AuthResponse<Json<serde_json::Value>> {
    let auth_header = headers.get("authorization")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    if auth_header.starts_with("Bearer ") {
        let token = &auth_header[7..];
        let auth_service = AuthService::new(state.clone());
        auth_service.logout(token).await?;
    }

    // Clear refresh cookie
    let response = Response::builder()
        .status(axum::http::StatusCode::OK)
        .header("set-cookie", "refresh_token=; Path=/api; HttpOnly; Secure; SameSite=Lax; Max-Age=0")
        .body(axum::body::boxed(axum::body::Full::from(
            r#"{"message":"Successfully logged out"}"#,
        )))
        .unwrap();

    Ok(response)
}

/// Get CSRF token
pub async fn csrf(
    State(_state): State<Arc<AppState>>,
    csrf_token: CsrfToken,
) -> AuthResponse<Json<CsrfResponse>> {
    Ok(Json(CsrfResponse {
        csrf_token: csrf_token.token(),
    }))
}

/// Get current user information
pub async fn me(
    State(state): State<Arc<AppState>>,
    user: crate::auth::middleware::AuthenticatedUser,
) -> AuthResponse<Json<UserResponse>> {
    let auth_service = AuthService::new(state.clone());
    let user_info = auth_service.get_user_info(user.id()).await?;

    Ok(Json(user_info))
}

/// Initiate password reset
pub async fn forgot_password(
    State(state): State<Arc<AppState>>,
    State(rate_limit): State<Arc<RateLimitState>>,
    Json(request): Json<ForgotPasswordRequest>,
) -> AuthResponse<Json<PasswordResetResponse>> {
    // Validate request
    if let Err(errors) = request.validate() {
        return Err(AuthError::InternalError); // Simplified error handling
    }

    // Check rate limit (by email for forgot password)
    rate_limit.check_rate_limit(&request.email, RATE_LIMIT_FORGOT_PASSWORD).await?;

    let password_reset_service = PasswordResetService::new(state.clone());
    password_reset_service.initiate_forgot_password(&request.email).await?;

    Ok(Json(PasswordResetResponse {
        message: "If an account exists, a reset link has been sent.".to_string(),
    }))
}

/// Complete password reset
pub async fn reset_password(
    State(state): State<Arc<AppState>>,
    Json(request): Json<ResetPasswordRequest>,
) -> AuthResponse<Json<PasswordResetResponse>> {
    // Validate request
    if let Err(errors) = request.validate() {
        return Err(AuthError::InternalError); // Simplified error handling
    }

    let password_reset_service = PasswordResetService::new(state.clone());
    password_reset_service.complete_reset(&request.token, &request.new_password).await?;

    Ok(Json(PasswordResetResponse {
        message: "Password reset successfully.".to_string(),
    }))
}

/// Helper function to hash token for rate limiting
fn hash_token(token: &str) -> String {
    use sha2::{Sha256, Digest};
    let mut hasher = Sha256::new();
    hasher.update(token.as_bytes());
    format!("{:x}", hasher.finalize())
}

/// Type alias for auth responses
type AuthResponse<T> = Result<T, ApiError>;

/// Apply timeout layer to handlers
pub fn apply_timeout_layer() -> TimeoutLayer {
    TimeoutLayer::new(Duration::from_secs(30))
}