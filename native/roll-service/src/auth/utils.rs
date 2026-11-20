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
    /// Bcrypt hash invocations on the current thread. A thread-local keeps
    /// the probe isolated from unrelated tests running in parallel. The
    /// sync helper probes where it hashes; [`hash_password_blocking`] probes
    /// on the calling task's thread so tests observe the count regardless of
    /// which blocking-pool thread performs the hash (the closure's own
    /// increment lands on that pool thread and is never read).
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

/// Hash a password with bcrypt off the async runtime workers.
///
/// Bcrypt costs roughly 100 ms of CPU per call at the default cost, so the
/// async credential paths move an owned copy of the input onto tokio's
/// blocking pool instead of stalling a runtime worker. The synchronous
/// [`hash_password`] stays available for direct and test callers.
///
/// Returns [`AuthError::PasswordTooShort`]/[`AuthError::PasswordTooLong`]
/// without spawning a task when the input violates the shared policy; the
/// spawned closure re-uses [`hash_password`], which re-checks the policy
/// before hashing. Joins map a panicking worker to
/// [`AuthError::InternalError`]; error messages never include the password.
///
/// # Errors
/// Returns policy or [`AuthError::InternalError`] failures as described above.
pub async fn hash_password_blocking(password: String) -> Result<String, AuthError> {
    validate_password_length(&password)?;
    #[cfg(test)]
    BCRYPT_HASH_CALLS.with(|calls| calls.set(calls.get() + 1));
    tokio::task::spawn_blocking(move || hash_password(&password))
        .await
        .map_err(|error| {
            tracing::error!("password hashing task failed: {error}");
            AuthError::InternalError
        })?
}

/// Verify a password against a bcrypt hash on tokio's blocking pool.
///
/// See [`hash_password_blocking`] for why bcrypt never runs inline on the
/// async workers. Inputs beyond bcrypt's 72-byte limit still short-circuit to
/// `false` inside [`verify_password`], so the fail-closed contract is
/// preserved on whichever thread performs the check.
///
/// # Errors
/// Returns [`AuthError::InternalError`] when the blocking task panics or
/// bcrypt verification fails; error messages never include the inputs.
pub async fn verify_password_blocking(
    password: String,
    password_hash: String,
) -> Result<bool, AuthError> {
    tokio::task::spawn_blocking(move || verify_password(&password, &password_hash))
        .await
        .map_err(|error| {
            tracing::error!("password verification task failed: {error}");
            AuthError::InternalError
        })?
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::services::UNKNOWN_ACCOUNT_BCRYPT_HASH;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

    /// A current-thread tokio runtime goes unresponsive while bcrypt runs
    /// inline on its only worker. With the blocking-pool wrappers, a spawned
    /// ticker task must keep advancing while a verify is in flight, which
    /// would be impossible if the bcrypt work stalled the worker (#4767).
    #[tokio::test]
    async fn password_verification_keeps_the_tokio_worker_responsive() {
        let ticks = std::sync::Arc::new(AtomicUsize::new(0));
        let stop = std::sync::Arc::new(AtomicBool::new(false));
        let ticker = {
            let ticks = std::sync::Arc::clone(&ticks);
            let stop = std::sync::Arc::clone(&stop);
            tokio::spawn(async move {
                while !stop.load(Ordering::Relaxed) {
                    ticks.fetch_add(1, Ordering::Relaxed);
                    tokio::task::yield_now().await;
                }
            })
        };

        let hash = hash_password("responsive-password").unwrap();
        let verified =
            verify_password_blocking("responsive-password".to_string(), hash.to_string())
                .await
                .unwrap();
        stop.store(true, Ordering::Relaxed);
        ticker.await.unwrap();

        assert!(verified);
        assert!(
            ticks.load(Ordering::Relaxed) >= 2,
            "the tokio worker must keep polling other tasks while bcrypt runs \
             on the blocking pool (observed {} ticks)",
            ticks.load(Ordering::Relaxed)
        );
    }

    /// The blocking wrapper produces the same kind of hash the sync helper
    /// does, and mismatches are false rather than errors.
    #[tokio::test]
    async fn blocking_verify_agrees_with_the_sync_helper() {
        let hash = hash_password("policy-password").unwrap();
        assert!(
            verify_password_blocking("policy-password".to_string(), hash.to_string())
                .await
                .unwrap()
        );
        assert!(
            !verify_password_blocking("another-password".to_string(), hash)
                .await
                .unwrap()
        );
    }

    /// Over-limit inputs stay fail-closed inside the blocking wrapper.
    #[tokio::test]
    async fn blocking_verify_fails_closed_for_overlong_passwords() {
        let over_limit = "a".repeat(MAX_BCRYPT_PASSWORD_BYTES + 1);
        assert!(
            !verify_password_blocking(over_limit, UNKNOWN_ACCOUNT_BCRYPT_HASH.to_string())
                .await
                .unwrap()
        );
    }

    /// Policy violations are reported by the blocking wrapper without paying
    /// (or even spawning) a bcrypt hash.
    #[tokio::test]
    async fn blocking_hash_enforces_the_password_policy_before_bcrypt() {
        let before = bcrypt_hash_calls();
        assert!(matches!(
            hash_password_blocking("tiny".to_string()).await,
            Err(AuthError::PasswordTooShort)
        ));
        assert_eq!(
            bcrypt_hash_calls(),
            before,
            "a password violating policy must be rejected without hashing"
        );
    }

    /// A valid blocking hash is paid exactly once and verifies via both paths.
    #[tokio::test]
    async fn blocking_hash_records_one_probed_call() {
        let before = bcrypt_hash_calls();
        let hash = hash_password_blocking("policy-password".to_string())
            .await
            .unwrap();
        assert_eq!(bcrypt_hash_calls(), before + 1);
        assert!(verify_password("policy-password", &hash).unwrap());
    }
}
