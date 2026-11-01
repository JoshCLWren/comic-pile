//! Authentication business logic services

use chrono::{DateTime, Utc};
use jsonwebtoken::{encode, Algorithm, EncodingKey, Header, DecodingKey, Validation};
use rand::Rng;
use serde::Serialize;
use sha2::{Sha256, Digest};
use std::collections::HashMap;
use tokio::time::{Duration, Instant};
use tracing::{error, info, warn};

use crate::auth::{
    dto::*,
    error::{AuthError, AuthResult},
    utils::{hash_password, verify_password},
};
use crate::{AppState, db::PoolError};

/// JWT configuration
const ALGORITHM: Algorithm = Algorithm::HS256;
const ACCESS_TOKEN_EXPIRY_MINUTES: i64 = 30;
const REFRESH_TOKEN_EXPIRY_DAYS: i64 = 7;

/// Main authentication service
pub struct AuthService {
    state: Arc<AppState>,
    login_attempts: Arc<std::sync::RwLock<HashMap<String, Vec<Instant>>>>,
}

impl AuthService {
    pub fn new(state: Arc<AppState>) -> Self {
        Self {
            state,
            login_attempts: Arc::new(std::sync::RwLock::new(HashMap::new())),
        }
    }

    /// Register a new user
    pub async fn register(&self, request: &RegisterRequest) -> AuthResult<TokenResponse> {
        // Check if username already exists
        if self.username_exists(&request.username).await? {
            return Err(AuthError::UsernameExists);
        }

        // Check if email already exists
        if self.email_exists(&request.email).await? {
            return Err(AuthError::EmailExists);
        }

        // Validate username doesn't contain '@'
        if request.username.contains('@') {
            return Err(AuthError::InvalidUsername);
        }

        // Hash password
        let password_hash = hash_password(&request.password)?;

        // Create user in database
        let user_id = self.create_user(&request.username, &request.email, &password_hash).await?;

        // Generate tokens
        let (access_token, refresh_token) = self.generate_tokens(user_id, &request.username, 0).await?;

        Ok(TokenResponse {
            access_token,
            refresh_token,
            token_type: "bearer".to_string(),
        })
    }

    /// Login user
    pub async fn login(&self, request: &LoginRequest) -> AuthResult<TokenResponse> {
        // Check login attempts
        self.check_login_attempts(&request.username).await?;

        // Get user by username
        let user = match self.get_user_by_username(&request.username).await {
            Some(user) => user,
            None => {
                // Record failed attempt for non-existent user
                self.record_failed_attempt(&request.username, None).await?;
                return Err(AuthError::InvalidCredentials);
            }
        };

        // Verify password
        if !verify_password(&request.password, &user.password_hash)? {
            // Record failed attempt
            self.record_failed_attempt(&request.username, None).await?;
            return Err(AuthError::InvalidCredentials);
        }

        // Clear failed attempts on successful login
        self.clear_failed_attempts(&request.username).await?;

        // Generate tokens with password epoch
        let pc = user.password_epoch();
        let (access_token, refresh_token) = self.generate_tokens(user.id, &user.username, pc).await?;

        Ok(TokenResponse {
            access_token,
            refresh_token,
            token_type: "bearer".to_string(),
        })
    }

    /// Refresh access token
    pub async fn refresh_token(&self, refresh_token: &str) -> AuthResult<TokenResponse> {
        // Verify refresh token
        let claims = self.verify_token(refresh_token, "refresh")?;
        
        // Check if token is revoked
        if self.is_token_revoked(&claims.sub, &claims.jti).await? {
            return Err(AuthError::TokenRevoked);
        }

        // Get user
        let user = match self.get_user_by_username(&claims.sub).await {
            Some(user) => user,
            None => return Err(AuthError::UserNotFound),
        };

        // Check password change
        let user_pc = user.password_epoch();
        if claims.pc < user_pc {
            return Err(AuthError::PasswordChanged);
        }

        // Generate new tokens
        let (access_token, refresh_token) = self.generate_tokens(user.id, &user.username, user_pc).await?;

        Ok(TokenResponse {
            access_token,
            refresh_token,
            token_type: "bearer".to_string(),
        })
    }

    /// Logout user by revoking token
    pub async fn logout(&self, token: &str) -> AuthResult<()> {
        let claims = match self.verify_token(token, "access") {
            Ok(claims) => claims,
            Err(_) => return Ok(()), // Don't fail if token is invalid
        };

        // Revoke the token
        self.revoke_token(&claims.sub, &claims.jti, claims.exp).await?;

        Ok(())
    }

    /// Get user information
    pub async fn get_user_info(&self, user_id: i32) -> AuthResult<UserResponse> {
        let user = self.get_user_by_id(user_id).await
            .ok_or(AuthError::UserNotFound)?;

        Ok(UserResponse {
            id: user.id,
            username: user.username,
            email: user.email,
            is_admin: user.is_admin,
        })
    }

    /// Check if username exists
    async fn username_exists(&self, username: &str) -> AuthResult<bool> {
        let query = r#"
            SELECT 1 FROM users WHERE username = $1 LIMIT 1
        "#;
        
        let result = self.state.pool.get().await?
            .query_opt(query, &[&username])
            .await?;

        Ok(result.is_some())
    }

    /// Check if email exists
    async fn email_exists(&self, email: &str) -> AuthResult<bool> {
        let query = r#"
            SELECT 1 FROM users WHERE email = $1 LIMIT 1
        "#;
        
        let result = self.state.pool.get().await?
            .query_opt(query, &[&email])
            .await?;

        Ok(result.is_some())
    }

    /// Create user in database
    async fn create_user(&self, username: &str, email: &str, password_hash: &str) -> AuthResult<i32> {
        let query = r#"
            INSERT INTO users (username, email, password_hash, created_at)
            VALUES ($1, $2, $3, NOW())
            RETURNING id
        "#;

        let conn = self.state.pool.get().await?;
        let result = conn.query_one(query, &[&username, &email, &password_hash]).await?;
        Ok(result.get(0))
    }

    /// Get user by username
    async fn get_user_by_username(&self, username: &str) -> Option<UserData> {
        let query = r#"
            SELECT id, username, email, password_hash, is_admin, password_changed_at
            FROM users 
            WHERE username = $1 
            LIMIT 1
        "#;

        let conn = match self.state.pool.get().await {
            Ok(conn) => conn,
            Err(_) => return None,
        };

        match conn.query_opt(query, &[&username]).await {
            Ok(row) => {
                Some(UserData {
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

    /// Get user by ID
    async fn get_user_by_id(&self, user_id: i32) -> Option<UserData> {
        let query = r#"
            SELECT id, username, email, password_hash, is_admin, password_changed_at
            FROM users 
            WHERE id = $1 
            LIMIT 1
        "#;

        let conn = match self.state.pool.get().await {
            Ok(conn) => conn,
            Err(_) => return None,
        };

        match conn.query_opt(query, &[&user_id]).await {
            Ok(row) => {
                Some(UserData {
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

    /// Generate JWT tokens
    async fn generate_tokens(&self, user_id: i32, username: &str, pc: i64) -> AuthResult<(String, String)> {
        let jti = self.generate_jti();
        
        // Access token
        let access_claims = Claims::access_token(username, &jti, pc);
        let access_token = self.encode_token(&access_claims)?;

        // Refresh token
        let refresh_claims = Claims::refresh_token(username, &jti, pc);
        let refresh_token = self.encode_token(&refresh_claims)?;

        // Store refresh token for revocation check
        self.store_refresh_token(user_id, &jti, refresh_claims.exp).await?;

        Ok((access_token, refresh_token))
    }

    /// Encode JWT token
    fn encode_token(&self, claims: &Claims) -> AuthResult<String> {
        let key = EncodingKey::from_secret(self.state.jwt_secret.as_bytes());
        encode(&Header::new(ALGORITHM), claims, &key)
            .map_err(|e| {
                error!("Failed to encode token: {}", e);
                AuthError::InternalError
            })
    }

    /// Verify JWT token
    fn verify_token(&self, token: &str, expected_type: &str) -> AuthResult<Claims> {
        let key = DecodingKey::from_secret(self.state.jwt_secret.as_bytes());
        let mut validation = Validation::new(ALGORITHM);
        validation.set_required_spec_claims(&["sub", "jti", "exp", "iat", "typ"]);
        validation.validate_exp = true;
        validation.validate_nbf = false;
        validation.validate_aud = false;

        let token_data = decode::<Claims>(token, &key, &validation)
            .map_err(|e| {
                warn!("Token verification failed: {}", e);
                AuthError::InvalidToken
            })?;

        if token_data.claims.typ != expected_type {
            return Err(AuthError::InvalidToken);
        }

        Ok(token_data.claims)
    }

    /// Check if token is revoked
    async fn is_token_revoked(&self, username: &str, jti: &str) -> AuthResult<bool> {
        let query = r#"
            SELECT 1 FROM revoked_tokens rt
            JOIN users u ON rt.user_id = u.id
            WHERE u.username = $1 AND rt.jti = $2
        "#;

        let conn = self.state.pool.get().await?;
        let result = conn.query_opt(query, &[&username, &jti]).await?;
        
        Ok(result.is_some())
    }

    /// Store refresh token for revocation check
    async fn store_refresh_token(&self, user_id: i32, jti: &str, expires_at: i64) -> AuthResult<()> {
        let query = r#"
            INSERT INTO revoked_tokens (user_id, jti, revoked_at, expires_at)
            VALUES ($1, $2, NOW(), TO_TIMESTAMP($3))
        "#;

        let conn = self.state.pool.get().await?;
        conn.execute(query, &[&user_id, &jti, &expires_at]).await?;
        
        Ok(())
    }

    /// Revoke token
    async fn revoke_token(&self, username: &str, jti: &str, expires_at: i64) -> AuthResult<()> {
        let query = r#"
            INSERT INTO revoked_tokens (user_id, jti, revoked_at, expires_at)
            SELECT u.id, $2, NOW(), TO_TIMESTAMP($3)
            FROM users u WHERE u.username = $1
        "#;

        let conn = self.state.pool.get().await?;
        conn.execute(query, &[&username, &jti, &expires_at]).await?;
        
        Ok(())
    }

    /// Generate JTI for token
    fn generate_jti(&self) -> String {
        rand::thread_rng()
            .sample_iter(&rand::distributions::Alphanumeric)
            .take(32)
            .map(char::from)
            .collect()
    }

    /// Check login attempts
    async fn check_login_attempts(&self, username: &str) -> AuthResult<()> {
        let mut attempts = self.login_attempts.write().unwrap();
        let user_attempts = attempts.entry(username.to_string()).or_insert_with(Vec::new);

        // Remove attempts older than 5 minutes
        let now = Instant::now();
        user_attempts.retain(|&attempt| now.duration_since(attempt) < Duration::from_secs(300));

        if user_attempts.len() >= 5 {
            return Err(AuthError::AccountLocked);
        }

        Ok(())
    }

    /// Record failed login attempt
    async fn record_failed_attempt(&self, username: &str, ip_address: Option<String>) -> AuthResult<()> {
        let mut attempts = self.login_attempts.write().unwrap();
        let user_attempts = attempts.entry(username.to_string()).or_insert_with(Vec::new);
        user_attempts.push(Instant::now());

        // Store in database for persistent tracking
        let query = r#"
            INSERT INTO login_attempts (username, ip_address, created_at)
            VALUES ($1, $2, NOW())
        "#;

        let conn = self.state.pool.get().await?;
        conn.execute(query, &[&username, &ip_address]).await?;

        Ok(())
    }

    /// Clear failed login attempts
    async fn clear_failed_attempts(&self, username: &str) -> AuthResult<()> {
        let mut attempts = self.login_attempts.write().unwrap();
        attempts.remove(username);

        // Clear from database
        let query = r#"
            DELETE FROM login_attempts 
            WHERE username = $1 AND created_at < NOW() - INTERVAL '5 minutes'
        "#;

        let conn = self.state.pool.get().await?;
        conn.execute(query, &[&username]).await?;

        Ok(())
    }
}

/// Password reset service
pub struct PasswordResetService {
    state: Arc<AppState>,
}

impl PasswordResetService {
    pub fn new(state: Arc<AppState>) -> Self {
        Self { state }
    }

    /// Initiate password reset flow
    pub async fn initiate_forgot_password(&self, email: &str) -> AuthResult<()> {
        // Check if user exists
        let query = r#"
            SELECT id, username, email FROM users WHERE email = $1 LIMIT 1
        "#;

        let conn = self.state.pool.get().await?;
        let user = match conn.query_opt(query, &[&email]).await {
            Ok(row) => {
                Some((row.get(0), row.get(1), row.get(2)))
            }
            Err(_) => None,
        };

        if let Some((user_id, username, user_email)) = user {
            // Generate reset token
            let reset_token = self.generate_reset_token();
            let token_hash = self.hash_token(&reset_token);
            let expires_at = Utc::now() + Duration::minutes(30);

            // Store reset token
            let query = r#"
                INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET
                    token_hash = $2,
                    expires_at = $3,
                    created_at = NOW()
            "#;

            conn.execute(query, &[&user_id, &token_hash, &expires_at]).await?;

            // TODO: Send email (for now, just log the token)
            info!("Password reset token for {}: {}", username, reset_token);
        }

        // Always return success to prevent user enumeration
        Ok(())
    }

    /// Complete password reset
    pub async fn complete_reset(&self, token: &str, new_password: &str) -> AuthResult<()> {
        // Validate password
        if new_password.len() < 8 {
            return Err(AuthError::PasswordTooShort);
        }

        // Hash token
        let token_hash = self.hash_token(token);

        // Find valid reset token
        let query = r#"
            SELECT u.id, u.username FROM password_reset_tokens prt
            JOIN users u ON prt.user_id = u.id
            WHERE prt.token_hash = $1 AND prt.expires_at > NOW()
            LIMIT 1
        "#;

        let conn = self.state.pool.get().await?;
        let user = match conn.query_opt(query, &[&token_hash]).await {
            Ok(row) => Some((row.get(0), row.get(1))),
            Err(_) => None,
        };

        let (user_id, username) = user.ok_or(AuthError::InvalidToken)?;

        // Hash new password
        let password_hash = hash_password(new_password)?;

        // Update user password
        let query = r#"
            UPDATE users 
            SET password_hash = $1, password_changed_at = NOW()
            WHERE id = $2
        "#;

        conn.execute(query, &[&password_hash, &user_id]).await?;

        // Invalidate all existing tokens for this user
        self.revoke_all_user_tokens(user_id).await?;

        info!("Password reset completed for user: {}", username);

        Ok(())
    }

    /// Generate random reset token
    fn generate_reset_token(&self) -> String {
        rand::thread_rng()
            .sample_iter(&rand::distributions::Alphanumeric)
            .take(32)
            .map(char::from)
            .collect()
    }

    /// Hash token for storage
    fn hash_token(&self, token: &str) -> String {
        let mut hasher = Sha256::new();
        hasher.update(token.as_bytes());
        format!("{:x}", hasher.finalize())
    }

    /// Revoke all tokens for a user
    async fn revoke_all_user_tokens(&self, user_id: i32) -> AuthResult<()> {
        let query = r#"
            INSERT INTO revoked_tokens (user_id, jti, revoked_at, expires_at)
            SELECT u.id, rt.jti, NOW(), rt.expires_at
            FROM refresh_tokens rt
            JOIN users u ON rt.user_id = u.id
            WHERE u.id = $1
        "#;

        let conn = self.state.pool.get().await?;
        conn.execute(query, &[&user_id]).await?;

        Ok(())
    }
}