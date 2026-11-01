//! Data Transfer Objects for authentication

use serde::{Deserialize, Serialize};
use validator::{Validate, ValidationError};

/// Request DTO for user registration
#[derive(Debug, Deserialize, Validate)]
pub struct RegisterRequest {
    #[validate(length(min = 3, max = 50))]
    pub username: String,
    
    #[validate(email)]
    pub email: String,
    
    #[validate(length(min = 8, max = 72))]
    pub password: String,
}

/// Request DTO for user login
#[derive(Debug, Deserialize, Validate)]
pub struct LoginRequest {
    #[validate(length(min = 3, max = 50))]
    pub username: String,
    
    #[validate(length(min = 1))]
    pub password: String,
}

/// Request DTO for token refresh
#[derive(Debug, Deserialize, Validate)]
pub struct RefreshTokenRequest {
    pub refresh_token: String,
}

/// Request DTO for forgot password
#[derive(Debug, Deserialize, Validate)]
pub struct ForgotPasswordRequest {
    #[validate(email)]
    pub email: String,
}

/// Request DTO for password reset
#[derive(Debug, Deserialize, Validate)]
pub struct ResetPasswordRequest {
    pub token: String,
    
    #[validate(length(min = 8, max = 72))]
    pub new_password: String,
}

/// Response DTO for token endpoints
#[derive(Debug, Serialize)]
pub struct TokenResponse {
    pub access_token: String,
    pub refresh_token: String,
    pub token_type: String,
}

/// Response DTO for user information
#[derive(Debug, Serialize)]
pub struct UserResponse {
    pub id: i32,
    pub username: String,
    pub email: Option<String>,
    pub is_admin: bool,
}

/// Response DTO for password reset
#[derive(Debug, Serialize)]
pub struct PasswordResetResponse {
    pub message: String,
}

/// Response DTO for CSRF token
#[derive(Debug, Serialize)]
pub struct CsrfResponse {
    pub csrf_token: String,
}

/// Claims for JWT tokens
#[derive(Debug, Serialize, Deserialize)]
pub struct Claims {
    pub sub: String,          // Subject (username)
    pub jti: String,          // JWT ID for revocation
    pub exp: i64,             // Expiration time
    pub iat: i64,             // Issued at
    pub typ: String,          // Token type ("access" or "refresh")
    pub pc: i64,              // Password change epoch
}

impl Claims {
    /// Create access token claims
    pub fn access_token(username: &str, jti: &str, pc: i64) -> Self {
        let now = chrono::Utc::now().timestamp();
        Self {
            sub: username.to_string(),
            jti: jti.to_string(),
            exp: now + (30 * 60), // 30 minutes
            iat: now,
            typ: "access".to_string(),
            pc,
        }
    }

    /// Create refresh token claims
    pub fn refresh_token(username: &str, jti: &str, pc: i64) -> Self {
        let now = chrono::Utc::now().timestamp();
        Self {
            sub: username.to_string(),
            jti: jti.to_string(),
            exp: now + (7 * 24 * 60 * 60), // 7 days
            iat: now,
            typ: "refresh".to_string(),
            pc,
        }
    }
}

/// User data from database
#[derive(Debug)]
pub struct UserData {
    pub id: i32,
    pub username: String,
    pub email: Option<String>,
    pub password_hash: String,
    pub is_admin: bool,
    pub password_changed_at: Option<chrono::DateTime<chrono::Utc>>,
}

impl UserData {
    /// Get password change epoch (seconds since Unix epoch)
    pub fn password_epoch(&self) -> i64 {
        self.password_changed_at
            .map(|dt| dt.timestamp())
            .unwrap_or(0)
    }
}

/// Database record for checking if token is revoked
#[derive(Debug)]
pub struct RevocationCheck {
    pub is_revoked: bool,
    pub password_epoch: i64,
}

/// Login attempt tracking
#[derive(Debug)]
pub struct LoginAttempt {
    pub id: i32,
    pub username: String,
    pub ip_address: Option<String>,
    pub created_at: chrono::DateTime<chrono::Utc>,
}