//! Password hashing, token digests, CSRF generation and request helpers.

use bcrypt::{hash, verify, DEFAULT_COST};
use rand::distr::{Alphanumeric, SampleString};
use sha2::{Digest, Sha256};

use crate::auth::error::AuthError;

/// Python policy constant: minimum password length in characters.
pub const MIN_PASSWORD_LENGTH: usize = 6;
/// bcrypt silently truncates beyond 72 bytes, so reject longer inputs instead.
pub const MAX_BCRYPT_PASSWORD_BYTES: usize = 72;

#[cfg(test)]
thread_local! {
    /// Bcrypt hashes performed on the current test thread. A thread-local keeps
    /// the probe isolated from unrelated tests running in parallel.
    static BCRYPT_HASH_CALLS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

/// Number of bcrypt hashes performed on this thread (test-only probe).
#[cfg(test)]
pub(crate) fn bcrypt_hash_calls() -> usize {
    BCRYPT_HASH_CALLS.with(std::cell::Cell::get)
}

/// Hash a password with bcrypt using the library's default cost.
pub fn hash_password(password: &str) -> Result<String, AuthError> {
    validate_password_length(password)?;
    #[cfg(test)]
    BCRYPT_HASH_CALLS.with(|calls| calls.set(calls.get() + 1));
    hash(password, DEFAULT_COST).map_err(|error| {
        tracing::error!("password hashing failed: {error}");
        AuthError::InternalError
    })
}

/// Verify a password against a bcrypt hash.
///
/// Inputs beyond bcrypt's 72-byte limit cannot have produced a valid existing
/// hash (Python had the same guard before bcrypt 4), so they fail closed rather
/// than being silently truncated.
pub fn verify_password(password: &str, password_hash: &str) -> Result<bool, AuthError> {
    if password.len() > MAX_BCRYPT_PASSWORD_BYTES {
        return Ok(false);
    }
    verify(password, password_hash).map_err(|error| {
        tracing::error!("password verification failed: {error}");
        AuthError::InternalError
    })
}

/// Enforce the shared password policy before mutating credential state.
pub fn validate_password_length(password: &str) -> Result<(), AuthError> {
    if password.chars().count() < MIN_PASSWORD_LENGTH {
        return Err(AuthError::PasswordTooShort);
    }
    if password.len() > MAX_BCRYPT_PASSWORD_BYTES {
        return Err(AuthError::PasswordTooLong);
    }
    Ok(())
}

/// Generate a cryptographically random opaque token (JTI, CSRF, reset secret).
pub fn generate_token(byte_len: usize) -> String {
    Alphanumeric.sample_string(&mut rand::rng(), byte_len)
}

/// Generate a double-submit CSRF token.
pub fn generate_csrf_token() -> String {
    generate_token(32)
}

/// SHA-256 digest of a reset token, matching the Python storage format.
pub fn token_digest(token: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(token.as_bytes());
    format!("{:x}", hasher.finalize())
}

/// Maximum characters stored in `failed_login_attempts.ip_address`.
/// The production column is `varchar(45)`, so an unbounded forwarded header
/// would otherwise turn a rejected login into a 22001/500.
const MAX_CLIENT_IP_CHARS: usize = 45;

fn bounded_client_ip(candidate: &str) -> Option<String> {
    let trimmed = candidate.trim();
    if trimmed.is_empty() {
        return None;
    }
    Some(trimmed.chars().take(MAX_CLIENT_IP_CHARS).collect())
}

/// Extract the first client IP from proxy headers, mirroring Python.
///
/// Values are truncated to the database column bound so a hostile
/// `X-Forwarded-For` cannot produce a persistence error on the rejected-login
/// path.
pub fn get_client_ip(headers: &http::HeaderMap, remote_addr: Option<&str>) -> String {
    if let Some(forwarded) = headers.get("x-forwarded-for").and_then(|v| v.to_str().ok()) {
        if let Some(first) = bounded_client_ip(forwarded.split(',').next().unwrap_or("")) {
            return first;
        }
    }
    if let Some(real_ip) = headers.get("x-real-ip").and_then(|v| v.to_str().ok()) {
        if let Some(trimmed) = bounded_client_ip(real_ip) {
            return trimmed;
        }
    }
    bounded_client_ip(remote_addr.unwrap_or("")).unwrap_or_else(|| "unknown".to_string())
}

/// Whether the original client request used HTTPS, respecting proxy headers.
pub fn is_secure_request(headers: &http::HeaderMap) -> bool {
    if let Some(proto) = headers
        .get("x-forwarded-proto")
        .and_then(|v| v.to_str().ok())
    {
        return proto
            .split(',')
            .next()
            .unwrap_or("")
            .trim()
            .eq_ignore_ascii_case("https");
    }
    std::env::var("ENVIRONMENT").is_ok_and(|env| env == "production")
}
