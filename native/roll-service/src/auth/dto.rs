//! Data transfer objects for the Rust v2 first-party authentication surface.

use serde::{Deserialize, Serialize};
use validator::Validate;

/// Request body for account registration.
#[derive(Debug, Deserialize, Validate)]
pub struct RegisterRequest {
    #[validate(length(min = 3, max = 50))]
    pub username: String,

    #[validate(email)]
    pub email: String,

    #[validate(length(min = 6))]
    pub password: String,
}

/// Request body for username/password login.
///
/// Login deliberately does not impose the registration minimum length: accounts
/// created before the current policy must still be able to sign in.
#[derive(Debug, Deserialize, Validate)]
pub struct LoginRequest {
    #[validate(length(max = 50))]
    pub username: String,

    #[validate(length(min = 1))]
    pub password: String,
}

/// Optional request body for token refresh; the refresh cookie is also accepted.
#[derive(Debug, Deserialize, Validate)]
pub struct RefreshTokenRequest {
    pub refresh_token: String,
}

/// Response body for token endpoints, matching the Python wire contract.
#[derive(Debug, Serialize)]
pub struct TokenResponse {
    pub access_token: String,
    pub refresh_token: String,
    pub token_type: String,
}

impl TokenResponse {
    /// Build the canonical bearer token response.
    pub fn bearer(access_token: String, refresh_token: String) -> Self {
        Self {
            access_token,
            refresh_token,
            token_type: "bearer".to_string(),
        }
    }
}

/// Response body for the current-user endpoint.
#[derive(Debug, Serialize)]
pub struct UserResponse {
    pub id: i32,
    pub username: String,
    pub email: Option<String>,
    pub is_admin: bool,
}

/// Request body for an enumeration-safe password-recovery email.
#[derive(Debug, Deserialize, Validate)]
pub struct ForgotPasswordRequest {
    #[validate(email)]
    pub email: String,
}

/// Request body for completing a password reset with a single-use token.
#[derive(Debug, Deserialize, Validate)]
pub struct ResetPasswordRequest {
    #[validate(length(min = 1))]
    pub token: String,

    #[validate(length(min = 1))]
    pub new_password: String,
}

/// Safe acknowledgement returned whether or not an account exists.
#[derive(Debug, Serialize)]
pub struct PasswordResetResponse {
    pub message: &'static str,
}

/// Response body carrying a double-submit CSRF token.
#[derive(Debug, Serialize)]
pub struct CsrfResponse {
    pub csrf_token: String,
}

/// JWT claims shared with the Python issuer and verifier.
///
/// Python emits ``type`` (not ``typ``), a ``pc`` password-change epoch, ``sub``
/// as the username and ``jti`` for revocation. Keep every field optional-safe so
/// tokens issued by either runtime remain valid.
#[derive(Debug, Serialize, Deserialize)]
pub struct Claims {
    pub sub: String,
    pub jti: String,
    pub exp: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub iat: Option<i64>,
    #[serde(rename = "type")]
    pub token_type: String,
    #[serde(default)]
    pub pc: i64,
}

impl Claims {
    /// Create access-token claims valid for 30 minutes.
    pub fn access(username: &str, jti: &str, password_epoch: i64) -> Self {
        Self::new(username, jti, password_epoch, "access", 30 * 60)
    }

    /// Create refresh-token claims valid for seven days.
    pub fn refresh(username: &str, jti: &str, password_epoch: i64) -> Self {
        Self::new(username, jti, password_epoch, "refresh", 7 * 24 * 60 * 60)
    }

    fn new(username: &str, jti: &str, password_epoch: i64, token_type: &str, ttl: i64) -> Self {
        let now = chrono::Utc::now().timestamp();
        Self {
            sub: username.to_string(),
            jti: jti.to_string(),
            exp: now + ttl,
            iat: Some(now),
            token_type: token_type.to_string(),
            pc: password_epoch,
        }
    }
}

/// User row needed by the authentication service. The password-change epoch is
/// read as Unix seconds in SQL so the driver never needs a chrono SQL mapping.
#[derive(Debug)]
pub struct UserData {
    pub id: i32,
    pub username: String,
    pub email: Option<String>,
    pub password_hash: Option<String>,
    pub is_admin: bool,
    pub password_epoch: i64,
}
