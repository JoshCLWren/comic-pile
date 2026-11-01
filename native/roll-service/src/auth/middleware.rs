//! Authentication middleware

use axum::{
    extract::{FromRequestParts, Request},
    http::{request::Parts, StatusCode},
    response::{IntoResponse, Response},
    RequestExt,
};
use std::sync::Arc;

use crate::auth::services::AuthService;
use crate::{AppState, ApiError};

/// CSRF token extractor and generator
pub struct CsrfToken {
    token: String,
}

impl CsrfToken {
    pub fn new() -> Self {
        Self {
            token: Self::generate_token(),
        }
    }

    pub fn token(&self) -> &str {
        &self.token
    }

    fn generate_token() -> String {
        use rand::Rng;
        rand::thread_rng()
            .sample_iter(&rand::distributions::Alphanumeric)
            .take(32)
            .map(char::from)
            .collect()
    }
}

/// Extract CSRF token from request
impl<S> FromRequestParts<S> for CsrfToken
where
    S: Send + Sync,
{
    type Rejection = ApiError;

    async fn from_request_parts(parts: &mut Parts, _state: &S) -> Result<Self, Self::Rejection> {
        // Check for CSRF token in header
        let csrf_token = parts.headers
            .get("x-csrf-token")
            .and_then(|v| v.to_str().ok())
            .map(|s| s.to_string())
            .unwrap_or_else(|| Self::generate_token());

        Ok(CsrfToken { token: csrf_token })
    }
}

/// Authentication middleware
pub struct AuthenticatedUser {
    user_id: i32,
}

impl AuthenticatedUser {
    pub fn id(&self) -> i32 {
        self.user_id
    }
}

/// Extract authenticated user from request
impl<S> FromRequestParts<S> for AuthenticatedUser
where
    S: Send + Sync,
{
    type Rejection = ApiError;

    async fn from_request_parts(parts: &mut Parts, state: &S) -> Result<Self, Self::Rejection> {
        let app_state = state.downcast_ref::<Arc<AppState>>()
            .ok_or(ApiError(StatusCode::INTERNAL_SERVER_ERROR, "Invalid app state".to_string()))?;

        // Extract Authorization header
        let auth_header = parts.headers
            .get("authorization")
            .and_then(|v| v.to_str().ok())
            .ok_or_else(|| ApiError(StatusCode::UNAUTHORIZED, "Missing or invalid authorization header".to_string()))?;

        if !auth_header.starts_with("Bearer ") {
            return Err(ApiError(StatusCode::UNAUTHORIZED, "Missing or invalid authorization header".to_string()));
        }

        let token = &auth_header[7..];

        // Verify token using existing auth logic
        let claims = Self::verify_token(app_state.clone(), token)
            .await
            .map_err(|_| ApiError(StatusCode::UNAUTHORIZED, "Invalid or expired token".to_string()))?;

        // Check if token is revoked
        if Self::is_token_revoked(app_state.clone(), &claims.sub, &claims.jti).await
            .map_err(|_| ApiError(StatusCode::INTERNAL_SERVER_ERROR, "Database error".to_string()))? {
            return Err(ApiError(StatusCode::UNAUTHORIZED, "Token has been revoked".to_string()));
        }

        // Get user
        let user = Self::get_user_by_username(app_state.clone(), &claims.sub).await
            .ok_or_else(|| ApiError(StatusCode::UNAUTHORIZED, "User not found".to_string()))?;

        // Check password change
        let user_pc = user.password_epoch();
        if claims.pc < user_pc {
            return Err(ApiError(StatusCode::UNAUTHORIZED, "Password changed; please sign in again".to_string()));
        }

        Ok(AuthenticatedUser { user_id: user.id })
    }
}

impl AuthenticatedUser {
    /// Verify JWT token
    async fn verify_token(state: Arc<AppState>, token: &str) -> Result<crate::auth::dto::Claims, crate::auth::error::AuthError> {
        use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation};
        use serde::Deserialize;

        let key = DecodingKey::from_secret(state.jwt_secret.as_bytes());
        let mut validation = Validation::new(Algorithm::HS256);
        validation.set_required_spec_claims(&["sub", "jti", "exp", "iat", "typ"]);
        validation.validate_exp = true;
        validation.validate_nbf = false;
        validation.validate_aud = false;

        let token_data = decode::<crate::auth::dto::Claims>(token, &key, &validation)
            .map_err(|_| crate::auth::error::AuthError::InvalidToken)?;

        if token_data.claims.typ != "access" {
            return Err(crate::auth::error::AuthError::InvalidToken);
        }

        Ok(token_data.claims)
    }

    /// Check if token is revoked
    async fn is_token_revoked(state: Arc<AppState>, username: &str, jti: &str) -> Result<bool, crate::db::PoolError> {
        let query = r#"
            SELECT 1 FROM revoked_tokens rt
            JOIN users u ON rt.user_id = u.id
            WHERE u.username = $1 AND rt.jti = $2
        "#;

        let conn = state.pool.get().await?;
        let result = conn.query_opt(query, &[&username, &jti]).await?;
        
        Ok(result.is_some())
    }

    /// Get user by username
    async fn get_user_by_username(state: Arc<AppState>, username: &str) -> Option<crate::auth::dto::UserData> {
        let query = r#"
            SELECT id, username, email, password_hash, is_admin, password_changed_at
            FROM users 
            WHERE username = $1 
            LIMIT 1
        "#;

        let conn = match state.pool.get().await {
            Ok(conn) => conn,
            Err(_) => return None,
        };

        match conn.query_opt(query, &[&username]).await {
            Ok(row) => {
                Some(crate::auth::dto::UserData {
                    id: row.get(0),
                    username: row.get(1),
                    email: row.get(2),
                    password_hash: row.get(3),
                    is_admin: row.get(4),
                    password_changed_at: row.get(5),
                })
            }
            Err(_) => None,
        }
    }
}

/// CSRF protection middleware
pub async fn csrf_middleware<S>(
    request: Request,
    next: axum::middleware::Next,
    csrf_token: CsrfToken,
) -> Response {
    // Add CSRF token to response headers
    let mut response = next.run(request).await;
    response.headers_mut()
        .insert("x-csrf-token", csrf_token.token.parse().unwrap());
    
    response
}

/// Rate limiting middleware
pub async fn rate_limit_middleware<S>(
    request: Request,
    next: axum::middleware::Next,
) -> Response {
    // TODO: Implement rate limiting logic
    // For now, just pass through
    next.run(request).await
}