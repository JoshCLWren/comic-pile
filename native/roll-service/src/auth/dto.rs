//! Data transfer objects for the Rust v2 first-party authentication surface.

use serde::{Deserialize, Serialize};
use validator::Validate;

/// Request body for account registration.
#[derive(Debug, Deserialize, Validate, utoipa::ToSchema)]
pub struct RegisterRequest {
    // Python imposed no minimum username length; keep the DB's 50-character
    // bound so existing short accounts remain registrable/loggable-in.
    #[validate(length(max = 50))]
    pub username: String,

    #[validate(email)]
    pub email: String,

    #[validate(length(min = 6))]
    pub password: String,
}

/// Request body for username/password login.
///
/// Login deliberately does not impose the registration minimum length: accounts
/// created before the current policy must still be able to sign in. An empty
/// password is rejected by bcrypt verification with the same non-enumerating
/// 401 as any other incorrect credential, matching Python.
#[derive(Debug, Deserialize, Validate, utoipa::ToSchema)]
pub struct LoginRequest {
    #[validate(length(max = 50))]
    pub username: String,

    pub password: String,
}

/// Optional request body for token refresh; the refresh cookie is also accepted.
#[derive(Debug, Deserialize, Validate, utoipa::ToSchema)]
pub struct RefreshTokenRequest {
    pub refresh_token: String,
}

/// Response body for token endpoints, matching the Python wire contract.
#[derive(Debug, Serialize, utoipa::ToSchema)]
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
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct UserResponse {
    pub id: i32,
    pub username: String,
    pub email: Option<String>,
    pub is_admin: bool,
}

/// Request body for an enumeration-safe password-recovery email.
#[derive(Debug, Deserialize, Validate, utoipa::ToSchema)]
pub struct ForgotPasswordRequest {
    #[validate(email)]
    pub email: String,
}

/// Request body for completing a password reset with a single-use token.
#[derive(Debug, Deserialize, Validate, utoipa::ToSchema)]
pub struct ResetPasswordRequest {
    #[validate(length(min = 1))]
    pub token: String,

    #[validate(length(min = 1))]
    pub new_password: String,
}

/// Safe acknowledgement returned whether or not an account exists.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct PasswordResetResponse {
    #[schema(value_type = String)]
    pub message: &'static str,
}

/// Response body carrying a double-submit CSRF token.
#[derive(Debug, Serialize, utoipa::ToSchema)]
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
    /// Create access-token claims using the configured lifetime.
    pub fn access(username: &str, jti: &str, password_epoch: i64, expire_minutes: i64) -> Self {
        Self::new(username, jti, password_epoch, "access", expire_minutes * 60)
    }

    /// Create refresh-token claims using the configured lifetime.
    pub fn refresh(username: &str, jti: &str, password_epoch: i64, expire_days: i64) -> Self {
        Self::new(
            username,
            jti,
            password_epoch,
            "refresh",
            expire_days * 24 * 60 * 60,
        )
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

// Documentation-only operations below emit the published v2 auth contract.
// They intentionally have no bodies: the mounted handlers in `handlers.rs` are
// the runtime authority, and these declarations exist only so the canonical
// `NativeV2Api` aggregate can publish each deployed method/path.

/// Documentation-only operation for the mounted v2 registration handler.
#[utoipa::path(
    post,
    path = "/api/v2/auth/register",
    tag = "auth",
    request_body = RegisterRequest,
    responses(
        (status = 200, description = "Account created and bearer tokens issued", body = TokenResponse),
        (status = 400, description = "Username or email is already registered"),
        (status = 422, description = "Request payload failed validation"),
        (status = 429, description = "Registration rate limit exceeded"),
        (status = 503, description = "Database temporarily unavailable")
    )
)]
#[allow(dead_code)]
pub fn register_documentation() {}

/// Documentation-only operation for the mounted v2 login handler.
#[utoipa::path(
    post,
    path = "/api/v2/auth/login",
    tag = "auth",
    request_body = LoginRequest,
    responses(
        (status = 200, description = "Credentials accepted and bearer tokens issued", body = TokenResponse),
        (status = 400, description = "Username field contained an email address"),
        (status = 401, description = "Incorrect username or password"),
        (status = 422, description = "Request payload failed validation"),
        (status = 429, description = "Login rate limit exceeded"),
        (status = 503, description = "Database temporarily unavailable")
    )
)]
#[allow(dead_code)]
pub fn login_documentation() {}

/// Documentation-only operation for the mounted v2 refresh handler.
///
/// The refresh cookie is an alternative to the optional JSON body token.
#[utoipa::path(
    post,
    path = "/api/v2/auth/refresh",
    tag = "auth",
    request_body = Option<RefreshTokenRequest>,
    responses(
        (status = 200, description = "Refreshed bearer tokens issued", body = TokenResponse),
        (status = 401, description = "Missing, invalid, revoked or stale refresh token"),
        (status = 429, description = "Refresh rate limit exceeded"),
        (status = 503, description = "Database temporarily unavailable")
    )
)]
#[allow(dead_code)]
pub fn refresh_documentation() {}

/// Documentation-only operation for the mounted v2 logout handler.
#[utoipa::path(
    post,
    path = "/api/v2/auth/logout",
    tag = "auth",
    responses(
        (status = 200, description = "Bearer token revoked and refresh cookie cleared", body = serde_json::Value),
        (status = 503, description = "Database temporarily unavailable")
    )
)]
#[allow(dead_code)]
pub fn logout_documentation() {}

/// Documentation-only operation for the mounted v2 CSRF handler.
#[utoipa::path(
    get,
    path = "/api/v2/auth/csrf",
    tag = "auth",
    responses(
        (status = 200, description = "Double-submit CSRF token", body = CsrfResponse)
    )
)]
#[allow(dead_code)]
pub fn csrf_documentation() {}

/// Documentation-only operation for the mounted v2 current-user handler.
#[utoipa::path(
    get,
    path = "/api/v2/auth/me",
    tag = "auth",
    responses(
        (status = 200, description = "Authenticated account profile", body = UserResponse),
        (status = 401, description = "Not authenticated or token invalid"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn me_documentation() {}

/// Documentation-only operation for the mounted v2 forgot-password handler.
#[utoipa::path(
    post,
    path = "/api/v2/auth/forgot-password",
    tag = "auth",
    request_body = ForgotPasswordRequest,
    responses(
        (status = 200, description = "Enumeration-safe acknowledgement", body = PasswordResetResponse),
        (status = 422, description = "Request payload failed validation"),
        (status = 429, description = "Password-recovery rate limit exceeded"),
        (status = 503, description = "Database temporarily unavailable")
    )
)]
#[allow(dead_code)]
pub fn forgot_password_documentation() {}

/// Documentation-only operation for the mounted v2 reset-password handler.
#[utoipa::path(
    post,
    path = "/api/v2/auth/reset-password",
    tag = "auth",
    request_body = ResetPasswordRequest,
    responses(
        (status = 200, description = "Password reset completed", body = PasswordResetResponse),
        (status = 400, description = "Invalid or expired reset request"),
        (status = 422, description = "Request payload failed validation"),
        (status = 429, description = "Password-recovery rate limit exceeded"),
        (status = 503, description = "Database temporarily unavailable")
    )
)]
#[allow(dead_code)]
pub fn reset_password_documentation() {}
