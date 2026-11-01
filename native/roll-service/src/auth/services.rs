//! Authentication business logic for the Rust v2 first-party auth surface.
//!
//! Behavior mirrors `app/api/auth.py` and `app/auth.py`: bcrypt credentials,
//! HS256 access/refresh JWTs sharing one `jti`, database-backed login lockout,
//! revocation by `jti`, and password-epoch invalidation. Password recovery
//! delivery remains in Python until an equivalent Rust mailer is introduced.

use std::sync::Arc;

use jsonwebtoken::{decode, encode, Algorithm, DecodingKey, EncodingKey, Header, Validation};

use crate::auth::{
    dto::{Claims, LoginRequest, RegisterRequest, TokenResponse, UserData, UserResponse},
    error::{AuthError, AuthResult},
    utils::{generate_token, hash_password, token_digest, verify_password},
};
use crate::db::{checkout, query_error, query_one_optional};
use crate::AppState;

const ALGORITHM: Algorithm = Algorithm::HS256;
const MAX_USERNAME_FAILURES: i64 = 5;
const MAX_IP_FAILURES: i64 = 10;

/// Account lifecycle service. Stateless beyond the shared application pool.
pub struct AuthService {
    state: Arc<AppState>,
}

impl AuthService {
    /// Create a service bound to the process application state.
    pub fn new(state: Arc<AppState>) -> Self {
        Self { state }
    }

    /// Register a new account and issue an initial token pair.
    pub async fn register(&self, request: &RegisterRequest) -> AuthResult<TokenResponse> {
        if request.username.contains('@') {
            return Err(AuthError::InvalidUsername);
        }
        let password_hash = hash_password(&request.password)?;

        let connection = checkout(&self.state).await?;
        let existing = connection
            .query_opt(
                "SELECT username, email FROM users WHERE username = $1 OR email = $2 LIMIT 1",
                &[&request.username, &request.email],
            )
            .await
            .map_err(query_error)?;
        if let Some(row) = existing {
            let username: String = row.get(0);
            if username == request.username {
                return Err(AuthError::UsernameExists);
            }
            return Err(AuthError::EmailExists);
        }

        let inserted = connection
            .query_opt(
                "INSERT INTO users (username, email, password_hash) VALUES ($1, $2, $3) \
                 ON CONFLICT DO NOTHING RETURNING id",
                &[&request.username, &request.email, &password_hash],
            )
            .await
            .map_err(query_error)?;
        inserted.ok_or(AuthError::UserExists)?;
        drop(connection);

        self.issue_tokens(&request.username, 0).await
    }

    /// Authenticate a username/password pair.
    pub async fn login(
        &self,
        request: &LoginRequest,
        client_ip: &str,
    ) -> AuthResult<TokenResponse> {
        if request.username.contains('@') {
            return Err(AuthError::EmailLogin);
        }

        let connection = checkout(&self.state).await?;
        let username_failures: i64 = connection
            .query_one(
                "SELECT count(*) FROM failed_login_attempts \
                 WHERE username = $1 AND attempted_at >= NOW() - INTERVAL '15 minutes'",
                &[&request.username],
            )
            .await
            .map_err(query_error)?
            .get(0);
        let ip_failures: i64 = connection
            .query_one(
                "SELECT count(*) FROM failed_login_attempts \
                 WHERE ip_address = $1 AND attempted_at >= NOW() - INTERVAL '30 minutes'",
                &[&client_ip],
            )
            .await
            .map_err(query_error)?
            .get(0);
        if username_failures >= MAX_USERNAME_FAILURES || ip_failures >= MAX_IP_FAILURES {
            return Err(AuthError::InvalidCredentials);
        }

        let user = self
            .user_by_username(&connection, &request.username)
            .await?;
        let Some(user) = user else {
            self.record_failed_attempt(&connection, &request.username, client_ip)
                .await?;
            return Err(AuthError::InvalidCredentials);
        };
        let Some(password_hash) = user.password_hash.as_deref() else {
            self.record_failed_attempt(&connection, &request.username, client_ip)
                .await?;
            return Err(AuthError::InvalidCredentials);
        };
        if !verify_password(&request.password, password_hash)? {
            self.record_failed_attempt(&connection, &request.username, client_ip)
                .await?;
            return Err(AuthError::InvalidCredentials);
        }

        connection
            .execute(
                "DELETE FROM failed_login_attempts WHERE username = $1",
                &[&request.username],
            )
            .await
            .map_err(query_error)?;
        drop(connection);

        self.issue_tokens(&user.username, user.password_epoch).await
    }

    /// Rotate a refresh token, revoking its predecessor to detect replay.
    pub async fn refresh(&self, refresh_token: &str) -> AuthResult<TokenResponse> {
        let claims = decode_claims(
            refresh_token,
            self.state.jwt_secret.as_bytes(),
            Some("refresh"),
        )
        .map_err(|_| AuthError::InvalidRefreshToken)?;
        let connection = checkout(&self.state).await?;
        let row = query_one_optional(
            &self.state,
            connection,
            "SELECT u.id, u.username, \
             COALESCE(trunc(extract(epoch FROM u.password_changed_at))::bigint, 0), \
             EXISTS(SELECT 1 FROM revoked_tokens r WHERE r.jti = $2) \
             FROM users u WHERE u.username = $1 LIMIT 1",
            &[&claims.sub, &claims.jti],
        )
        .await?;
        let row = row.ok_or(AuthError::RefreshUserNotFound)?;
        if row.get::<_, bool>(3) {
            return Err(AuthError::RefreshTokenRevoked);
        }
        let password_epoch: i64 = row.get(2);
        if claims.pc < password_epoch {
            return Err(AuthError::PasswordChanged);
        }
        let user_id: i32 = row.get(0);

        if !self.revoke_jti(user_id, &claims.jti, claims.exp).await? {
            return Err(AuthError::RefreshTokenRevoked);
        }
        self.issue_tokens(&claims.sub, password_epoch).await
    }

    /// Revoke the presented access token. Invalid tokens still log out cleanly.
    pub async fn logout(&self, access_token: &str) -> AuthResult<()> {
        let Ok(claims) = decode_claims(access_token, self.state.jwt_secret.as_bytes(), None) else {
            return Ok(());
        };
        let connection = checkout(&self.state).await?;
        let user_id = connection
            .query_opt(
                "SELECT id FROM users WHERE username = $1 LIMIT 1",
                &[&claims.sub],
            )
            .await
            .map_err(query_error)?
            .map(|row| row.get::<_, i32>(0));
        if let Some(user_id) = user_id {
            drop(connection);
            self.revoke_jti(user_id, &claims.jti, claims.exp).await?;
        }
        Ok(())
    }

    /// Return the authenticated account profile.
    pub async fn get_user_info(&self, user_id: i32) -> AuthResult<UserResponse> {
        let connection = checkout(&self.state).await?;
        let row = connection
            .query_opt(
                "SELECT id, username, email, is_admin FROM users WHERE id = $1 LIMIT 1",
                &[&user_id],
            )
            .await
            .map_err(query_error)?;
        let row = row.ok_or(AuthError::UserNotFound)?;
        Ok(UserResponse {
            id: row.get(0),
            username: row.get(1),
            email: row.get(2),
            is_admin: row.get(3),
        })
    }

    async fn user_by_username(
        &self,
        connection: &deadpool_postgres::Object,
        username: &str,
    ) -> AuthResult<Option<UserData>> {
        let row = connection
            .query_opt(
                "SELECT id, username, email, password_hash, is_admin, \
                 COALESCE(trunc(extract(epoch FROM password_changed_at))::bigint, 0) \
                 FROM users WHERE username = $1 LIMIT 1",
                &[&username],
            )
            .await
            .map_err(query_error)?;
        Ok(row.map(|row| UserData {
            id: row.get(0),
            username: row.get(1),
            email: row.get(2),
            password_hash: row.get(3),
            is_admin: row.get(4),
            password_epoch: row.get(5),
        }))
    }

    async fn record_failed_attempt(
        &self,
        connection: &deadpool_postgres::Object,
        username: &str,
        client_ip: &str,
    ) -> AuthResult<()> {
        connection
            .execute(
                "INSERT INTO failed_login_attempts (username, ip_address) VALUES ($1, $2)",
                &[&username, &client_ip],
            )
            .await
            .map_err(query_error)?;
        Ok(())
    }

    async fn revoke_jti(&self, user_id: i32, jti: &str, expires_at: i64) -> AuthResult<bool> {
        let connection = checkout(&self.state).await?;
        let expires_at = expires_at as f64;
        let inserted = connection
            .execute(
                "INSERT INTO revoked_tokens (user_id, jti, revoked_at, expires_at) \
                 VALUES ($1, $2, NOW(), to_timestamp($3)) ON CONFLICT (jti) DO NOTHING",
                &[&user_id, &jti, &expires_at],
            )
            .await
            .map_err(query_error)?;
        Ok(inserted > 0)
    }

    async fn issue_tokens(&self, username: &str, password_epoch: i64) -> AuthResult<TokenResponse> {
        let jti = generate_token(32);
        let access = Claims::access(username, &jti, password_epoch);
        let refresh = Claims::refresh(username, &jti, password_epoch);
        let access_token = encode_token(&access, self.state.jwt_secret.as_bytes())?;
        let refresh_token = encode_token(&refresh, self.state.jwt_secret.as_bytes())?;
        Ok(TokenResponse::bearer(access_token, refresh_token))
    }
}

fn encode_token(claims: &Claims, secret: &[u8]) -> AuthResult<String> {
    encode(
        &Header::new(ALGORITHM),
        claims,
        &EncodingKey::from_secret(secret),
    )
    .map_err(|error| {
        tracing::error!("token encoding failed: {error}");
        AuthError::InternalError
    })
}

/// Decode and validate a JWT, optionally requiring a specific token `type`.
pub fn decode_claims(
    token: &str,
    secret: &[u8],
    expected_type: Option<&str>,
) -> AuthResult<Claims> {
    let mut validation = Validation::new(ALGORITHM);
    validation.required_spec_claims.clear();
    validation.validate_exp = false;
    validation.validate_nbf = false;
    validation.validate_aud = false;
    let claims = decode::<Claims>(token, &DecodingKey::from_secret(secret), &validation)
        .map_err(|_| AuthError::InvalidToken)?
        .claims;
    if claims.sub.is_empty() || claims.jti.is_empty() {
        return Err(AuthError::InvalidToken);
    }
    if expected_type.is_some_and(|expected| claims.token_type != expected) {
        return Err(AuthError::InvalidToken);
    }
    if claims.exp < jsonwebtoken::get_current_timestamp() as i64 {
        return Err(AuthError::InvalidToken);
    }
    Ok(claims)
}

/// Password-recovery service. Delivery is owned by the Python mailer today, so
/// this service preserves the shared token-digest and credential-epoch contract
/// for the future native cutover without exposing an unrouted HTTP handler.
pub struct PasswordResetService {
    state: Arc<AppState>,
}

impl PasswordResetService {
    /// Create a service bound to the process application state.
    pub fn new(state: Arc<AppState>) -> Self {
        Self { state }
    }

    /// Store a single-use reset digest and return the raw token for delivery.
    pub async fn begin_reset(&self, email: &str) -> AuthResult<Option<String>> {
        let connection = checkout(&self.state).await?;
        let user_id = connection
            .query_opt("SELECT id FROM users WHERE email = $1 LIMIT 1", &[&email])
            .await
            .map_err(query_error)?
            .map(|row| row.get::<_, i32>(0));
        let Some(user_id) = user_id else {
            return Ok(None);
        };
        let raw_token = generate_token(43);
        let digest = token_digest(&raw_token);
        let mut connection = connection;
        let transaction = connection.transaction().await.map_err(query_error)?;
        transaction
            .execute(
                "DELETE FROM password_reset_tokens WHERE user_id = $1",
                &[&user_id],
            )
            .await
            .map_err(query_error)?;
        transaction
            .execute(
                "INSERT INTO password_reset_tokens (user_id, token_digest, expires_at) \
                 VALUES ($1, $2, NOW() + INTERVAL '30 minutes')",
                &[&user_id, &digest],
            )
            .await
            .map_err(query_error)?;
        transaction.commit().await.map_err(query_error)?;
        Ok(Some(raw_token))
    }

    /// Consume a reset token, rotate the password hash and bump the credential epoch.
    pub async fn complete_reset(&self, token: &str, new_password: &str) -> AuthResult<()> {
        let password_hash = hash_password(new_password)?;
        let digest = token_digest(token);
        let mut connection = checkout(&self.state).await?;
        let transaction = connection.transaction().await.map_err(query_error)?;
        let token_id = transaction
            .query_opt(
                "SELECT id, user_id FROM password_reset_tokens \
                 WHERE token_digest = $1 AND used_at IS NULL AND expires_at > NOW() \
                 LIMIT 1 FOR UPDATE",
                &[&digest],
            )
            .await
            .map_err(query_error)?;
        let Some(row) = token_id else {
            return Err(AuthError::InvalidToken);
        };
        let id: i32 = row.get(0);
        let user_id: i32 = row.get(1);
        transaction
            .execute(
                "UPDATE password_reset_tokens SET used_at = NOW() WHERE id = $1 AND used_at IS NULL",
                &[&id],
            )
            .await
            .map_err(query_error)?;
        transaction
            .execute(
                "UPDATE users SET password_hash = $1, password_changed_at = NOW() WHERE id = $2",
                &[&password_hash, &user_id],
            )
            .await
            .map_err(query_error)?;
        transaction.commit().await.map_err(query_error)?;
        Ok(())
    }
}
