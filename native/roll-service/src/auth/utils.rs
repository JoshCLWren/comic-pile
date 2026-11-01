//! Authentication utility functions

use bcrypt::{hash, verify, DEFAULT_COST};

/// Hash password using bcrypt
pub fn hash_password(password: &str) -> Result<String, crate::auth::error::AuthError> {
    // Check password length
    if password.len() < 8 {
        return Err(crate::auth::error::AuthError::PasswordTooShort);
    }

    // Check password length in UTF-8 bytes (bcrypt limit)
    if password.len() > 72 {
        return Err(crate::auth::error::AuthError::PasswordTooLong);
    }

    hash(password, DEFAULT_COST).map_err(|e| {
        eprintln!("Password hashing failed: {}", e);
        crate::auth::error::AuthError::InternalError
    })
}

/// Verify password against hash
pub fn verify_password(password: &str, hash: &str) -> Result<bool, crate::auth::error::AuthError> {
    verify(password, hash).map_err(|e| {
        eprintln!("Password verification failed: {}", e);
        crate::auth::error::AuthError::InternalError
    })
}

/// Generate CSRF token
pub fn generate_csrf_token() -> String {
    use rand::RngExt;
    rand::rng()
        .sample_iter(&rand::distr::Alphanumeric)
        .take(32)
        .map(char::from)
        .collect()
}

/// Extract client IP from request
pub fn get_client_ip(headers: &http::HeaderMap, remote_addr: Option<&str>) -> Option<String> {
    // Check X-Forwarded-For header first
    if let Some(forwarded_for) = headers.get("x-forwarded-for") {
        if let Ok(forwarded_str) = forwarded_for.to_str() {
            let ips: Vec<&str> = forwarded_str.split(',').collect();
            if let Some(ip) = ips.first() {
                return Some(ip.trim().to_string());
            }
        }
    }

    // Check X-Real-IP header
    if let Some(real_ip) = headers.get("x-real-ip") {
        if let Ok(ip_str) = real_ip.to_str() {
            return Some(ip_str.trim().to_string());
        }
    }

    // Use remote address as fallback
    if let Some(remote) = remote_addr {
        return Some(remote.to_string());
    }

    None
}

/// Check if request is secure (HTTPS)
pub fn is_secure_request(headers: &http::HeaderMap) -> bool {
    // Check X-Forwarded-Proto header
    if let Some(proto) = headers.get("x-forwarded-proto") {
        if let Ok(proto_str) = proto.to_str() {
            return proto_str.to_lowercase() == "https";
        }
    }

    // Check if we're behind a load balancer that sets X-Forwarded-Proto
    // For now, assume secure in production
    std::env::var("ENVIRONMENT").map_or(false, |env| env == "production")
}

/// Create secure cookie settings
pub fn cookie_settings() -> http::HeaderValue {
    let mut cookie_settings = String::new();
    cookie_settings.push_str("HttpOnly; Secure; SameSite=Lax");

    http::HeaderValue::from_str(&cookie_settings).expect("Invalid cookie settings")
}

/// Generate random JTI for token revocation
pub fn generate_jti() -> String {
    use rand::RngExt;
    rand::rng()
        .sample_iter(&rand::distr::Alphanumeric)
        .take(32)
        .map(char::from)
        .collect()
}

/// Validate password strength
pub fn validate_password_strength(password: &str) -> Result<(), crate::auth::error::AuthError> {
    // Minimum length
    if password.len() < 8 {
        return Err(crate::auth::error::AuthError::PasswordTooShort);
    }

    // Maximum length in UTF-8 bytes
    if password.len() > 72 {
        return Err(crate::auth::error::AuthError::PasswordTooLong);
    }

    // Check for at least one uppercase letter
    if !password.chars().any(|c| c.is_ascii_uppercase()) {
        return Err(crate::auth::error::AuthError::InternalError); // TODO: Add specific error
    }

    // Check for at least one lowercase letter
    if !password.chars().any(|c| c.is_ascii_lowercase()) {
        return Err(crate::auth::error::AuthError::InternalError); // TODO: Add specific error
    }

    // Check for at least one digit
    if !password.chars().any(|c| c.is_ascii_digit()) {
        return Err(crate::auth::error::AuthError::InternalError); // TODO: Add specific error
    }

    Ok(())
}

/// Sanitize username input
pub fn sanitize_username(username: &str) -> Result<String, crate::auth::error::AuthError> {
    if username.is_empty() {
        return Err(crate::auth::error::AuthError::InvalidCredentials);
    }

    if username.len() > 50 {
        return Err(crate::auth::error::AuthError::InvalidCredentials);
    }

    // Check for invalid characters
    if username
        .chars()
        .any(|c| !c.is_ascii_alphanumeric() && c != '_' && c != '-')
    {
        return Err(crate::auth::error::AuthError::InvalidCredentials);
    }

    Ok(username.to_string())
}

/// Sanitize email input
pub fn sanitize_email(email: &str) -> Result<String, crate::auth::error::AuthError> {
    if email.is_empty() {
        return Err(crate::auth::error::AuthError::InvalidCredentials);
    }

    if email.len() > 255 {
        return Err(crate::auth::error::AuthError::InvalidCredentials);
    }

    // Basic email format validation
    if !email.contains('@') || !email.contains('.') {
        return Err(crate::auth::error::AuthError::InvalidCredentials);
    }

    Ok(email.to_string())
}
