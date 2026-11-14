//! HTTP handlers for the Rust v2 first-party authentication endpoints.

use std::collections::HashMap;
use std::sync::{Arc, OnceLock, RwLock};

use axum::{
    extract::State,
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use tokio::time::{Duration, Instant};
use validator::Validate;

use crate::auth::{
    dto::{
        CsrfResponse, ForgotPasswordRequest, LoginRequest, PasswordResetResponse,
        RefreshTokenRequest, RegisterRequest, ResetPasswordRequest, TokenResponse, UserResponse,
    },
    error::{AuthError, AuthResult},
    identity::AuthenticatedUser,
    mailer,
    services::{AuthService, PasswordResetService},
    utils::{generate_csrf_token, get_client_ip, is_secure_request, token_digest},
    BackgroundTasks,
};
use crate::AppState;

const REFRESH_COOKIE: &str = "refresh_token";
const CSRF_COOKIE: &str = "csrf_token";
// The refresh cookie is scoped to /api so it is never attached to static
// assets, and set/clear must use the identical path or logout cannot remove it.
const REFRESH_COOKIE_PATH: &str = "/api";
const CSRF_COOKIE_PATH: &str = "/";
const CSRF_COOKIE_MAX_AGE_SECONDS: i64 = 24 * 60 * 60;
const FORGOT_PASSWORD_MESSAGE: &str = "If an account exists, a reset link has been sent.";
const RESET_PASSWORD_MESSAGE: &str = "Password reset successfully.";
const RESET_PASSWORD_LIMIT_PER_MINUTE: usize = 5;
/// Hard cap on distinct limiter keys, so rotating an attacker-controlled
/// token/IP cannot grow this process-local map without bound.
const MAX_RATE_LIMIT_KEYS: usize = 4096;
/// Keys with no attempt inside this retention window are discarded during
/// pressure eviction.
const RATE_LIMIT_RETENTION: Duration = Duration::from_secs(60 * 60);

/// In-process request limiter. Keys are endpoint-scoped client IPs (or token
/// digests for refresh), never usernames, passwords or secrets.
#[derive(Default)]
struct RateLimiter {
    attempts: RwLock<HashMap<String, Vec<Instant>>>,
}

impl RateLimiter {
    fn check(&self, key: &str, limit: usize, window: Duration) -> Result<(), AuthError> {
        let now = Instant::now();
        let mut attempts = self.attempts.write().unwrap_or_else(|e| e.into_inner());
        if attempts.len() >= MAX_RATE_LIMIT_KEYS {
            attempts.retain(|_, entries| {
                entries.retain(|seen| now.duration_since(*seen) < RATE_LIMIT_RETENTION);
                !entries.is_empty()
            });
            // A sustained flood can still fill every key with fresh timestamps.
            // Resetting the counters is preferable to unbounded memory growth;
            // the database-backed username/IP lockout remains authoritative.
            if attempts.len() >= MAX_RATE_LIMIT_KEYS {
                attempts.clear();
            }
        }
        let entries = attempts.entry(key.to_string()).or_default();
        entries.retain(|seen| now.duration_since(*seen) < window);
        if entries.len() >= limit {
            return Err(AuthError::RateLimited);
        }
        entries.push(now);
        Ok(())
    }
}

fn limiter() -> &'static RateLimiter {
    static LIMITER: OnceLock<RateLimiter> = OnceLock::new();
    LIMITER.get_or_init(RateLimiter::default)
}

/// Decide whether in-process auth throttling is active.
///
/// Mirrors Python's `app/middleware/rate_limit.py::_should_enable_rate_limiting`
/// contract exactly: throttling is exempt only when the process is explicitly a
/// test environment (`TEST_ENVIRONMENT == "true"`) and the test run did not opt
/// back in with `ENABLE_RATE_LIMITING_IN_TESTS == "true"`. Production never sets
/// `TEST_ENVIRONMENT`, so this always returns `true` there and production
/// behavior is unchanged.
fn rate_limiting_enabled_for(
    test_environment: Option<&str>,
    enable_rate_limiting_in_tests: Option<&str>,
) -> bool {
    if test_environment != Some("true") {
        return true;
    }
    enable_rate_limiting_in_tests == Some("true")
}

fn rate_limiting_enabled() -> bool {
    let test_environment = std::env::var("TEST_ENVIRONMENT").ok();
    let enable_rate_limiting_in_tests = std::env::var("ENABLE_RATE_LIMITING_IN_TESTS").ok();
    rate_limiting_enabled_for(
        test_environment.as_deref(),
        enable_rate_limiting_in_tests.as_deref(),
    )
}

/// Apply the per-key request throttle unless the current process is a test
/// environment that did not explicitly opt in to rate limiting.
fn enforce_rate_limit(key: &str, limit: usize, window: Duration) -> Result<(), AuthError> {
    if !rate_limiting_enabled() {
        return Ok(());
    }
    limiter().check(key, limit, window)
}

fn client_ip(headers: &HeaderMap) -> String {
    get_client_ip(headers, None)
}

fn cookie_value<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers
        .get(header::COOKIE)?
        .to_str()
        .ok()?
        .split(';')
        .map(str::trim)
        .find_map(|part| {
            part.strip_prefix(name)
                .and_then(|rest| rest.strip_prefix('='))
        })
        .filter(|value| !value.is_empty())
}

fn cookie(
    name: &str,
    value: &str,
    path: &str,
    max_age: i64,
    http_only: bool,
    secure: bool,
) -> HeaderValue {
    let mut settings = format!("{name}={value}; Path={path}; Max-Age={max_age}; SameSite=Lax");
    if http_only {
        settings.push_str("; HttpOnly");
    }
    if secure {
        settings.push_str("; Secure");
    }
    #[allow(clippy::expect_used)]
    HeaderValue::from_str(&settings).expect("generated cookie value is header-safe")
}

fn cleared_refresh_cookie(secure: bool) -> HeaderValue {
    let mut settings =
        format!("{REFRESH_COOKIE}=; Path={REFRESH_COOKIE_PATH}; Max-Age=0; SameSite=Lax; HttpOnly");
    if secure {
        settings.push_str("; Secure");
    }
    #[allow(clippy::expect_used)]
    HeaderValue::from_str(&settings).expect("static cookie value is header-safe")
}

/// Append the refresh and double-submit CSRF cookies for a successful sign-in.
fn authentication_headers(
    headers: &HeaderMap,
    refresh_token: &str,
    refresh_max_age_seconds: i64,
) -> HeaderMap {
    let secure = is_secure_request(headers);
    let csrf_token = cookie_value(headers, CSRF_COOKIE)
        .map(str::to_owned)
        .unwrap_or_else(generate_csrf_token);
    let mut response_headers = HeaderMap::new();
    response_headers.append(
        header::SET_COOKIE,
        cookie(
            REFRESH_COOKIE,
            refresh_token,
            REFRESH_COOKIE_PATH,
            refresh_max_age_seconds,
            true,
            secure,
        ),
    );
    response_headers.append(
        header::SET_COOKIE,
        cookie(
            CSRF_COOKIE,
            &csrf_token,
            CSRF_COOKIE_PATH,
            CSRF_COOKIE_MAX_AGE_SECONDS,
            false,
            secure,
        ),
    );
    response_headers
}

fn refresh_cookie_max_age_seconds(state: &AppState) -> i64 {
    state.refresh_token_expire_days * 24 * 60 * 60
}

/// Register a new first-party account.
pub async fn register(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(request): Json<RegisterRequest>,
) -> AuthResult<(HeaderMap, Json<TokenResponse>)> {
    request.validate().map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        AuthError::Validation
    })?;
    let ip = client_ip(&headers);
    enforce_rate_limit(&format!("register:{ip}"), 5, Duration::from_secs(60))?;
    let refresh_max_age = refresh_cookie_max_age_seconds(&state);
    let tokens = AuthService::new(state).register(&request).await?;
    let response_headers = authentication_headers(&headers, &tokens.refresh_token, refresh_max_age);
    Ok((response_headers, Json(tokens)))
}

/// Authenticate an existing account.
pub async fn login(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(request): Json<LoginRequest>,
) -> AuthResult<(HeaderMap, Json<TokenResponse>)> {
    request.validate().map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        AuthError::Validation
    })?;
    let ip = client_ip(&headers);
    enforce_rate_limit(&format!("login:{ip}"), 5, Duration::from_secs(60))?;
    let refresh_max_age = refresh_cookie_max_age_seconds(&state);
    let tokens = AuthService::new(state).login(&request, &ip).await?;
    let response_headers = authentication_headers(&headers, &tokens.refresh_token, refresh_max_age);
    Ok((response_headers, Json(tokens)))
}

/// Rotate the refresh credential from the body or the HttpOnly cookie.
pub async fn refresh(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    body: axum::body::Bytes,
) -> AuthResult<(HeaderMap, Json<TokenResponse>)> {
    let body_token = if body.is_empty() {
        None
    } else {
        serde_json::from_slice::<RefreshTokenRequest>(&body)
            .ok()
            .map(|request| request.refresh_token)
    };
    let refresh_token = body_token
        .or_else(|| cookie_value(&headers, REFRESH_COOKIE).map(str::to_owned))
        .ok_or(AuthError::MissingRefreshToken)?;
    enforce_rate_limit(
        &format!("refresh:{}", token_digest(&refresh_token)),
        20,
        Duration::from_secs(60),
    )?;
    let refresh_max_age = refresh_cookie_max_age_seconds(&state);
    let tokens = AuthService::new(state).refresh(&refresh_token).await?;
    let response_headers = authentication_headers(&headers, &tokens.refresh_token, refresh_max_age);
    Ok((response_headers, Json(tokens)))
}

/// Revoke the presented access token and clear the refresh cookie.
pub async fn logout(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> AuthResult<Response> {
    let access_token = headers
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.split_once(' '))
        .filter(|(scheme, token)| scheme.eq_ignore_ascii_case("bearer") && !token.is_empty())
        .map(|(_, token)| token);
    if let Some(token) = access_token {
        AuthService::new(state).logout(token).await?;
    }
    let mut response_headers = HeaderMap::new();
    response_headers.append(
        header::SET_COOKIE,
        cleared_refresh_cookie(is_secure_request(&headers)),
    );
    Ok((
        StatusCode::OK,
        response_headers,
        Json(serde_json::json!({"message": "Successfully logged out"})),
    )
        .into_response())
}

/// Issue or return a double-submit CSRF token.
pub async fn csrf(headers: HeaderMap) -> Response {
    let token = cookie_value(&headers, CSRF_COOKIE)
        .map(str::to_owned)
        .unwrap_or_else(generate_csrf_token);
    let mut response_headers = HeaderMap::new();
    response_headers.append(
        header::SET_COOKIE,
        cookie(
            CSRF_COOKIE,
            &token,
            CSRF_COOKIE_PATH,
            CSRF_COOKIE_MAX_AGE_SECONDS,
            false,
            is_secure_request(&headers),
        ),
    );
    (response_headers, Json(CsrfResponse { csrf_token: token })).into_response()
}

/// Begin an enumeration-safe password-recovery request and deliver the reset
/// link off the response path.
pub async fn forgot_password(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    tasks: BackgroundTasks,
    Json(request): Json<ForgotPasswordRequest>,
) -> AuthResult<Json<PasswordResetResponse>> {
    request.validate().map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        AuthError::Validation
    })?;
    let ip = client_ip(&headers);
    enforce_rate_limit(&format!("forgot:{ip}"), 3, Duration::from_secs(60))?;
    if let Some(delivery) = PasswordResetService::new(state)
        .begin_reset(&request.email)
        .await?
    {
        // Delivery never blocks the acknowledgement, so provider latency cannot
        // distinguish a known address from an unknown one. It is still
        // registered as tracked background work: a bare `tokio::spawn` would let
        // a serverless isolate freeze before SMTP completes.
        tasks.spawn(async move { mailer::deliver(delivery).await });
    }
    Ok(Json(PasswordResetResponse {
        message: FORGOT_PASSWORD_MESSAGE,
    }))
}

/// Complete a password reset and bump the credential epoch.
pub async fn reset_password(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(request): Json<ResetPasswordRequest>,
) -> AuthResult<Json<PasswordResetResponse>> {
    request.validate().map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        AuthError::Validation
    })?;
    let ip = client_ip(&headers);
    enforce_rate_limit(
        &format!("reset:{ip}"),
        RESET_PASSWORD_LIMIT_PER_MINUTE,
        Duration::from_secs(60),
    )?;
    PasswordResetService::new(state)
        .complete_reset(&request.token, &request.new_password)
        .await?;
    Ok(Json(PasswordResetResponse {
        message: RESET_PASSWORD_MESSAGE,
    }))
}

/// Return the current authenticated account profile.
pub async fn me(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> AuthResult<Json<UserResponse>> {
    let user_info = AuthService::new(state).get_user_info(user.id()).await?;
    Ok(Json(user_info))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::services::decode_claims;
    use crate::auth::utils::{bcrypt_hash_calls, token_digest, verify_password};
    use crate::config::Config;
    use axum::body::Bytes;

    #[test]
    fn throttling_is_enabled_without_a_test_environment() {
        assert!(
            rate_limiting_enabled_for(None, None),
            "production (no TEST_ENVIRONMENT) must always throttle"
        );
        assert!(
            rate_limiting_enabled_for(None, Some("true")),
            "opting in only matters inside a test environment"
        );
    }

    #[test]
    fn throttling_is_disabled_in_a_test_environment_by_default() {
        assert!(!rate_limiting_enabled_for(Some("true"), None));
        assert!(!rate_limiting_enabled_for(Some("true"), Some("false")));
    }

    #[test]
    fn throttling_respects_explicit_opt_in_in_tests() {
        assert!(rate_limiting_enabled_for(Some("true"), Some("true")));
    }

    #[test]
    fn throttling_is_enabled_when_the_test_environment_flag_is_false() {
        assert!(rate_limiting_enabled_for(Some("false"), None));
        assert!(rate_limiting_enabled_for(Some("false"), Some("true")));
    }

    #[test]
    fn rate_limiter_caps_distinct_attacker_controlled_keys() {
        let limiter = RateLimiter::default();
        let over_cap = MAX_RATE_LIMIT_KEYS + 32;
        for index in 0..over_cap {
            limiter
                .check(&format!("refresh:{index}"), 20, Duration::from_secs(60))
                .unwrap();
        }
        let keys = limiter.attempts.read().unwrap().len();
        assert!(
            keys <= MAX_RATE_LIMIT_KEYS,
            "limiter must evict keys instead of growing without bound: {keys}"
        );
    }

    fn state(url: &str) -> Arc<AppState> {
        Arc::new(
            AppState::new(
                Config::from_lookup(|key| match key {
                    "RUST_ROLL_DATABASE_URL" => Some(url.into()),
                    "RUST_ROLL_JWT_SECRET" => Some("synthetic-auth-test-secret".into()),
                    "RUST_ROLL_POOL_SIZE" => Some("1".into()),
                    _ => None,
                })
                .unwrap(),
            )
            .unwrap(),
        )
    }

    /// Lock and reset the canonical Alembic schema for one serialized auth test.
    ///
    /// Auth tests never silently skip: a missing disposable database is a hard
    /// failure. The schema comes from the Alembic fixture, not from DDL here.
    async fn canonical_auth_state() -> (Arc<AppState>, tokio::sync::MutexGuard<'static, ()>) {
        let url = crate::test_support::database_url().await;
        let state = state(&url);
        let guard = crate::test_support::reset_for_test(&state).await;
        (state, guard)
    }

    fn json_headers(ip: &str) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("application/json"),
        );
        headers.insert("x-forwarded-for", HeaderValue::from_str(ip).unwrap());
        headers
    }

    #[tokio::test]
    async fn register_login_refresh_logout_round_trip() {
        let (state, _db) = canonical_auth_state().await;
        let headers = json_headers("198.51.100.10");
        let register_request = RegisterRequest {
            username: "round-trip-reader".into(),
            email: "round-trip@example.com".into(),
            password: "correct-horse-battery".into(),
        };
        let (_, Json(created)) = register(
            State(state.clone()),
            headers.clone(),
            Json(register_request),
        )
        .await
        .unwrap();
        let claims = decode_claims(
            &created.access_token,
            b"synthetic-auth-test-secret",
            Some("access"),
        )
        .unwrap();
        assert_eq!(claims.sub, "round-trip-reader");
        assert_eq!(claims.token_type, "access");

        let connection = state.pool.get().await.unwrap();
        let hash: String = connection
            .query_one(
                "SELECT password_hash FROM users WHERE username = $1",
                &[&"round-trip-reader"],
            )
            .await
            .unwrap()
            .get(0);
        assert!(verify_password("correct-horse-battery", &hash).unwrap());
        assert!(!verify_password("wrong-password", &hash).unwrap());
        drop(connection);

        let login_request = LoginRequest {
            username: "round-trip-reader".into(),
            password: "correct-horse-battery".into(),
        };
        let (login_headers, Json(logged_in)) =
            login(State(state.clone()), headers, Json(login_request))
                .await
                .unwrap();
        let set_cookies = login_headers
            .get_all(header::SET_COOKIE)
            .iter()
            .filter_map(|value| value.to_str().ok())
            .collect::<Vec<_>>();
        assert!(set_cookies
            .iter()
            .any(|value| value.starts_with("refresh_token=")));
        assert!(
            set_cookies.iter().any(|value| value.contains("Path=/api")),
            "refresh cookie must be scoped to /api so logout can clear it"
        );
        assert!(set_cookies
            .iter()
            .any(|value| value.starts_with("csrf_token=")));

        let refresh_body = Bytes::from(
            serde_json::to_vec(&serde_json::json!({
                "refresh_token": logged_in.refresh_token
            }))
            .unwrap(),
        );
        let (_, Json(rotated)) = refresh(State(state.clone()), HeaderMap::new(), refresh_body)
            .await
            .unwrap();
        assert_ne!(rotated.refresh_token, logged_in.refresh_token);

        let replay = refresh(
            State(state.clone()),
            HeaderMap::new(),
            Bytes::from(
                serde_json::to_vec(&serde_json::json!({
                    "refresh_token": logged_in.refresh_token
                }))
                .unwrap(),
            ),
        )
        .await;
        assert!(
            replay.is_err(),
            "a rotated refresh token must not be replayed"
        );

        let mut authorization = HeaderMap::new();
        authorization.insert(
            header::AUTHORIZATION,
            HeaderValue::from_str(&format!("Bearer {}", rotated.access_token)).unwrap(),
        );
        let logout_response = logout(State(state.clone()), authorization).await.unwrap();
        let cleared = logout_response
            .headers()
            .get(header::SET_COOKIE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or_default();
        assert!(
            cleared.starts_with("refresh_token=") && cleared.contains("Path=/api"),
            "logout must clear the same /api-scoped refresh cookie that login set"
        );
        assert!(
            crate::auth::authenticate(&state, &rotated.access_token)
                .await
                .is_err(),
            "logout must revoke the exact access token"
        );
    }

    #[tokio::test]
    async fn failed_login_lockout_is_database_backed() {
        let (state, _db) = canonical_auth_state().await;
        let (_, Json(created)) = register(
            State(state.clone()),
            json_headers("198.51.100.20"),
            Json(RegisterRequest {
                username: "lockout-reader".into(),
                email: "lockout@example.com".into(),
                password: "correct-horse-battery".into(),
            }),
        )
        .await
        .unwrap();
        assert!(!created.access_token.is_empty());

        for attempt in 0..5 {
            let response = login(
                State(state.clone()),
                json_headers(&format!("198.51.100.{}", 30 + attempt)),
                Json(LoginRequest {
                    username: "lockout-reader".into(),
                    password: "wrong-password".into(),
                }),
            )
            .await;
            assert!(response.is_err());
        }
        let locked = login(
            State(state.clone()),
            json_headers("198.51.100.99"),
            Json(LoginRequest {
                username: "lockout-reader".into(),
                password: "correct-horse-battery".into(),
            }),
        )
        .await;
        assert!(
            locked.is_err(),
            "five recent failures must lock the username"
        );
    }

    #[tokio::test]
    async fn password_recovery_is_enumeration_safe_and_rotates_credentials() {
        let (state, _db) = canonical_auth_state().await;
        let (_, Json(created)) = register(
            State(state.clone()),
            json_headers("198.51.100.40"),
            Json(RegisterRequest {
                username: "recovery-reader".into(),
                email: "recovery@example.com".into(),
                password: "correct-horse-battery".into(),
            }),
        )
        .await
        .unwrap();

        let service = PasswordResetService::new(state.clone());
        let acknowledgement = forgot_password(
            State(state.clone()),
            json_headers("198.51.100.39"),
            BackgroundTasks::default(),
            Json(ForgotPasswordRequest {
                email: "unknown@example.com".into(),
            }),
        )
        .await
        .unwrap();
        assert_eq!(acknowledgement.0.message, FORGOT_PASSWORD_MESSAGE);
        assert!(
            service
                .begin_reset("unknown@example.com")
                .await
                .unwrap()
                .is_none(),
            "unknown email must not create or reveal a reset token"
        );
        let delivery = service
            .begin_reset("recovery@example.com")
            .await
            .unwrap()
            .expect("known email yields a delivery payload");
        assert_eq!(delivery.username, "recovery-reader");
        assert_eq!(delivery.recipient_email, "recovery@example.com");
        assert!(!delivery.token.is_empty());

        // A below-minimum attempt rolls the token consumption back, so the live
        // token remains usable for the corrected request.
        let too_short = reset_password(
            State(state.clone()),
            json_headers("198.51.100.43"),
            Json(ResetPasswordRequest {
                token: delivery.token.clone(),
                new_password: "short".into(),
            }),
        )
        .await;
        assert!(matches!(too_short, Err(AuthError::PasswordTooShort)));

        let reset = reset_password(
            State(state.clone()),
            json_headers("198.51.100.43"),
            Json(ResetPasswordRequest {
                token: delivery.token.clone(),
                new_password: "brand-new-secret".into(),
            }),
        )
        .await
        .unwrap();
        assert_eq!(reset.0.message, "Password reset successfully.");

        let replay = reset_password(
            State(state.clone()),
            json_headers("198.51.100.43"),
            Json(ResetPasswordRequest {
                token: delivery.token,
                new_password: "another-secret".into(),
            }),
        )
        .await;
        assert!(
            matches!(replay, Err(AuthError::InvalidResetToken)),
            "a consumed reset token must not be replayable"
        );

        assert!(
            crate::auth::authenticate(&state, &created.access_token)
                .await
                .is_err(),
            "the credential epoch bump must invalidate existing access tokens"
        );
        assert!(login(
            State(state.clone()),
            json_headers("198.51.100.41"),
            Json(LoginRequest {
                username: "recovery-reader".into(),
                password: "correct-horse-battery".into(),
            }),
        )
        .await
        .is_err());
        assert!(login(
            State(state.clone()),
            json_headers("198.51.100.42"),
            Json(LoginRequest {
                username: "recovery-reader".into(),
                password: "brand-new-secret".into(),
            }),
        )
        .await
        .is_ok());
    }

    #[tokio::test]
    async fn reset_rejects_garbage_tokens_without_paying_bcrypt_cost() {
        let (state, _db) = canonical_auth_state().await;
        let connection = state.pool.get().await.unwrap();
        let user_id: i32 = connection
            .query_one(
                "INSERT INTO users (username, email, password_hash, password_changed_at, created_at) \
                 VALUES ('reset-cost-reader', 'reset-cost@example.com', 'old-hash', \
                         NOW() - INTERVAL '1 day', NOW()) RETURNING id",
                &[],
            )
            .await
            .unwrap()
            .get(0);
        connection
            .execute(
                "INSERT INTO password_reset_tokens \
                 (user_id, token_digest, expires_at, created_at) \
                 VALUES ($1, $2, NOW() + INTERVAL '30 minutes', NOW())",
                &[&user_id, &token_digest("live-reset-token")],
            )
            .await
            .unwrap();
        drop(connection);

        let before = bcrypt_hash_calls();
        let rejected = PasswordResetService::new(state.clone())
            .complete_reset("anonymous-garbage-token", "brand-new-secret")
            .await;
        assert!(matches!(rejected, Err(AuthError::InvalidResetToken)));
        assert_eq!(
            bcrypt_hash_calls(),
            before,
            "an invalid reset token must be rejected before bcrypt hashing"
        );

        PasswordResetService::new(state.clone())
            .complete_reset("live-reset-token", "brand-new-secret")
            .await
            .expect("a live reset token must still rotate the password");
        assert_eq!(
            bcrypt_hash_calls(),
            before + 1,
            "a live reset token hashes the new password exactly once"
        );

        let connection = state.pool.get().await.unwrap();
        let row = connection
            .query_one(
                "SELECT u.password_hash,
                        u.password_changed_at > NOW() - INTERVAL '1 minute',
                        t.used_at IS NOT NULL
                 FROM users u JOIN password_reset_tokens t ON t.user_id = u.id
                 WHERE u.id = $1 AND t.token_digest = $2",
                &[&user_id, &token_digest("live-reset-token")],
            )
            .await
            .unwrap();
        let hash: String = row.get(0);
        let epoch_bumped: bool = row.get(1);
        let consumed: bool = row.get(2);
        assert!(verify_password("brand-new-secret", &hash).unwrap());
        assert!(epoch_bumped, "a reset must bump the credential epoch");
        assert!(consumed, "a live reset token must be marked used");
    }

    #[tokio::test]
    async fn reset_password_requests_are_rate_limited_per_client() {
        let (state, _db) = canonical_auth_state().await;
        let ip = "198.51.100.240";
        for _ in 0..RESET_PASSWORD_LIMIT_PER_MINUTE {
            let response = reset_password(
                State(state.clone()),
                json_headers(ip),
                Json(ResetPasswordRequest {
                    token: "garbage-token".into(),
                    new_password: "brand-new-secret".into(),
                }),
            )
            .await;
            assert!(matches!(response, Err(AuthError::InvalidResetToken)));
        }
        let limited = reset_password(
            State(state.clone()),
            json_headers(ip),
            Json(ResetPasswordRequest {
                token: "garbage-token".into(),
                new_password: "brand-new-secret".into(),
            }),
        )
        .await;
        assert!(
            matches!(limited, Err(AuthError::RateLimited)),
            "reset-password must reject requests beyond the per-client limit"
        );
    }
}
