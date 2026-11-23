//! GitHub OAuth sign-in for the public Rotisserie control room.
//!
//! ComicPile only hosts the OAuth exchange and authorized workflow dispatch.
//! GitHub remains the identity provider and Rotisserie owns factory policy.
//! No GitHub access token or application secret ever reaches the public page.
#![forbid(unsafe_code)]

use crate::{outbound::OutboundRequest, ApiError, AppState};
use axum::{
    body::HttpBody,
    extract::{Query, State},
    http::{header, HeaderMap, HeaderValue, Method, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use bytes::Bytes as HttpBytes;
use http_body_util::BodyExt;
use jsonwebtoken::{decode, encode, Algorithm, DecodingKey, EncodingKey, Header, Validation};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{sync::Arc, time::Duration};
use uuid::Uuid;

const REPO: &str = "JoshCLWren/comic-pile";
const PAGES_URL: &str = "https://joshclwren.github.io/comic-pile/";
const PAGES_ORIGIN: &str = "https://joshclwren.github.io";
const CALLBACK_URL: &str = "https://comic-pile.vercel.app/api/v2/factory/github/callback";
const STATE_COOKIE: &str = "rotisserie_github_oauth";
const COOKIE_PATH: &str = "/api/v2/factory/github";
const SESSION_AUDIENCE: &str = "rotisserie-github-admin";
const STATE_AUDIENCE: &str = "rotisserie-github-oauth-state";
const STATE_TTL_SECONDS: usize = 300;
const SESSION_TTL_SECONDS: usize = 20 * 60;
const MAX_PROVIDER_RESPONSE: usize = 20_000;
const MAX_COMMAND_BYTES: usize = 4096;

#[derive(Debug, Serialize, Deserialize)]
struct OAuthState {
    aud: String,
    nonce: String,
    verifier: String,
    exp: usize,
}

#[derive(Debug, Serialize, Deserialize)]
struct AdminSession {
    aud: String,
    sub: String,
    login: String,
    iat: usize,
    exp: usize,
}

#[derive(Debug, Deserialize)]
pub struct CallbackParams {
    code: Option<String>,
    state: Option<String>,
    error: Option<String>,
}

#[derive(Debug, Deserialize)]
struct OAuthToken {
    access_token: Option<String>,
    error: Option<String>,
}

#[derive(Debug, Deserialize)]
struct GitHubUser {
    id: u64,
    login: String,
}

fn seconds() -> usize {
    chrono::Utc::now().timestamp().max(0) as usize
}

fn configured() -> Result<(String, String), ApiError> {
    let client_id = std::env::var("ROTISSERIE_GITHUB_OAUTH_CLIENT_ID").unwrap_or_default();
    let client_secret = std::env::var("ROTISSERIE_GITHUB_OAUTH_CLIENT_SECRET").unwrap_or_default();
    if client_id.is_empty() || client_secret.is_empty() {
        return Err(ApiError::ServiceUnavailable(
            "GitHub sign-in is not configured yet".into(),
        ));
    }
    Ok((client_id, client_secret))
}

/// The allowlist always includes the owner's immutable GitHub user ID.
/// Only trusted server configuration can grant additional access.
fn allowed(id: u64, extra: &str) -> bool {
    if id == 4_014_199 {
        return true;
    }
    if extra.is_empty() {
        return false;
    }
    if extra.split(',').any(|value| {
        value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit())
    }) {
        return false;
    }
    extra
        .split(',')
        .filter_map(|value| value.parse::<u64>().ok())
        .any(|value| value == id)
}

fn is_admin(id: u64) -> bool {
    allowed(
        id,
        &std::env::var("ROTISSERIE_ADMIN_GITHUB_IDS").unwrap_or_default(),
    )
}

fn oauth_encoding_key(state: &AppState) -> Result<EncodingKey, ApiError> {
    EncodingKey::from_secret(state.jwt_secret.as_bytes())
        .map_err(|_| ApiError::Internal("GitHub sign-in unavailable".into()))
}

fn oauth_decoding_key(state: &AppState) -> Result<DecodingKey, ApiError> {
    DecodingKey::from_secret(state.jwt_secret.as_bytes())
        .map_err(|_| ApiError::Unauthorized("GitHub sign-in unavailable".into()))
}

fn jwt_validation(audience: &str) -> Validation {
    let mut validation = Validation::new(Algorithm::HS256);
    validation.set_audience(&[audience]);
    validation.required_spec_claims.insert("exp".into());
    validation
}

fn verified_session(state: &AppState, token: &str) -> Result<AdminSession, ApiError> {
    let claims = decode::<AdminSession>(
        token,
        &oauth_decoding_key(state)?,
        &jwt_validation(SESSION_AUDIENCE),
    )
    .map_err(|_| ApiError::Unauthorized("GitHub sign-in expired or invalid".into()))?
    .claims;
    if claims.aud != SESSION_AUDIENCE
        || claims
            .sub
            .parse::<u64>()
            .ok()
            .is_none_or(|id| !is_admin(id))
        || claims.exp > seconds() + SESSION_TTL_SECONDS
    {
        return Err(ApiError::Forbidden("Not a Rotisserie administrator".into()));
    }
    Ok(claims)
}

fn session_from_headers(state: &AppState, headers: &HeaderMap) -> Result<AdminSession, ApiError> {
    let bearer = headers
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "))
        .ok_or_else(|| ApiError::Unauthorized("Sign in with GitHub first".into()))?;
    verified_session(state, bearer)
}

fn state_cookie(headers: &HeaderMap) -> Option<&str> {
    headers
        .get(header::COOKIE)?
        .to_str()
        .ok()?
        .split(';')
        .map(str::trim)
        .find_map(|part| part.strip_prefix(STATE_COOKIE)?.strip_prefix('='))
}

fn secure_response(mut response: Response) -> Response {
    response
        .headers_mut()
        .insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    response.headers_mut().insert(
        header::REFERRER_POLICY,
        HeaderValue::from_static("no-referrer"),
    );
    response
}

fn redirect(location: &str) -> Response {
    let mut response = StatusCode::SEE_OTHER.into_response();
    if let Ok(header) = HeaderValue::from_str(location) {
        response.headers_mut().insert(header::LOCATION, header);
    }
    secure_response(response)
}

fn with_cookie(mut response: Response, value: &str) -> Response {
    if let Ok(cookie) = HeaderValue::from_str(value) {
        response.headers_mut().insert(header::SET_COOKIE, cookie);
    }
    response
}

fn clear_cookie(response: Response) -> Response {
    with_cookie(
        response,
        &format!("{STATE_COOKIE}=; Path={COOKIE_PATH}; Max-Age=0; Secure; HttpOnly; SameSite=Lax"),
    )
}

fn cors(mut response: Response) -> Response {
    let headers = response.headers_mut();
    headers.insert(
        header::ACCESS_CONTROL_ALLOW_ORIGIN,
        HeaderValue::from_static(PAGES_ORIGIN),
    );
    headers.insert(
        header::ACCESS_CONTROL_ALLOW_METHODS,
        HeaderValue::from_static("GET, POST, OPTIONS"),
    );
    headers.insert(
        header::ACCESS_CONTROL_ALLOW_HEADERS,
        HeaderValue::from_static("Authorization, Content-Type"),
    );
    headers.insert(header::VARY, HeaderValue::from_static("Origin"));
    secure_response(response)
}

/// Navigating here starts an OAuth authorization-code + PKCE redirect.
/// The random verifier and nonce remain in an HTTP-only signed cookie.
pub async fn start(State(state): State<Arc<AppState>>) -> Response {
    let (client_id, _) = match configured() {
        Ok(value) => value,
        Err(error) => return secure_response(error.into_response()),
    };
    let nonce = Uuid::new_v4().simple().to_string();
    let verifier = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple(),);
    let challenge = URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes()));
    let pending = OAuthState {
        aud: STATE_AUDIENCE.into(),
        nonce: nonce.clone(),
        verifier,
        exp: seconds() + STATE_TTL_SECONDS,
    };
    let key = match oauth_encoding_key(&state) {
        Ok(value) => value,
        Err(error) => return secure_response(error.into_response()),
    };
    let cookie_value = match encode(&Header::new(Algorithm::HS256), &pending, &key) {
        Ok(value) => value,
        Err(_) => {
            return secure_response(
                ApiError::Internal("Sign-in unavailable".into()).into_response(),
            )
        }
    };
    let query = form_urlencoded::Serializer::new(String::new())
        .append_pair("client_id", &client_id)
        .append_pair("redirect_uri", CALLBACK_URL)
        .append_pair("scope", "read:user")
        .append_pair("state", &nonce)
        .append_pair("code_challenge", &challenge)
        .append_pair("code_challenge_method", "S256")
        .finish();
    with_cookie(
        redirect(&format!("https://github.com/login/oauth/authorize?{query}")),
        &format!(
            "{STATE_COOKIE}={cookie_value}; Path={COOKIE_PATH}; Max-Age=300; Secure; HttpOnly; SameSite=Lax"
        ),
    )
}

async fn provider_json(
    state: &AppState,
    host: &str,
    request: OutboundRequest,
) -> Result<(StatusCode, Value), ApiError> {
    let response =
        tokio::time::timeout(Duration::from_secs(10), state.outbound.send(host, request))
            .await
            .map_err(|_| ApiError::ServiceUnavailable("GitHub authentication timed out".into()))?
            .map_err(|_| {
                ApiError::ServiceUnavailable("GitHub authentication unavailable".into())
            })?;
    if response
        .body
        .size_hint()
        .upper()
        .is_some_and(|length| length > MAX_PROVIDER_RESPONSE as u64)
    {
        return Err(ApiError::ServiceUnavailable(
            "Invalid GitHub response".into(),
        ));
    }
    let status = response.status;
    let bytes = tokio::time::timeout(Duration::from_secs(10), response.body.collect())
        .await
        .map_err(|_| ApiError::ServiceUnavailable("GitHub response timed out".into()))?
        .map_err(|_| ApiError::ServiceUnavailable("Invalid GitHub response".into()))?
        .to_bytes();
    if bytes.len() > MAX_PROVIDER_RESPONSE {
        return Err(ApiError::ServiceUnavailable(
            "GitHub response too large".into(),
        ));
    }
    let data: Value = serde_json::from_slice(&bytes)
        .map_err(|_| ApiError::ServiceUnavailable("Invalid GitHub response".into()))?;
    Ok((status, data))
}

async fn finish_callback(
    state: Arc<AppState>,
    headers: HeaderMap,
    params: CallbackParams,
) -> Result<Response, ApiError> {
    if params.error.is_some() {
        return Err(ApiError::Unauthorized(
            "GitHub sign-in was cancelled".into(),
        ));
    }
    let code = params
        .code
        .filter(|v| !v.is_empty() && v.len() < 1024)
        .ok_or_else(|| ApiError::Unauthorized("Missing authorization code".into()))?;
    let presented_nonce = params
        .state
        .ok_or_else(|| ApiError::Unauthorized("Missing OAuth state".into()))?;
    let signed_state = state_cookie(&headers)
        .ok_or_else(|| ApiError::Unauthorized("Missing OAuth state cookie".into()))?;
    let pending = decode::<OAuthState>(
        signed_state,
        &oauth_decoding_key(&state)?,
        &jwt_validation(STATE_AUDIENCE),
    )
    .map_err(|_| ApiError::Unauthorized("OAuth state expired".into()))?
    .claims;
    if pending.aud != STATE_AUDIENCE || pending.nonce != presented_nonce {
        return Err(ApiError::Unauthorized("OAuth state mismatch".into()));
    }
    let (client_id, client_secret) = configured()?;
    let form = form_urlencoded::Serializer::new(String::new())
        .append_pair("client_id", &client_id)
        .append_pair("client_secret", &client_secret)
        .append_pair("code", &code)
        .append_pair("redirect_uri", CALLBACK_URL)
        .append_pair("code_verifier", &pending.verifier)
        .finish();
    let request = OutboundRequest {
        method: Method::POST,
        path: "/login/oauth/access_token".into(),
        headers: vec![
            ("Accept".into(), "application/json".into()),
            (
                "Content-Type".into(),
                "application/x-www-form-urlencoded".into(),
            ),
            ("User-Agent".into(), "ComicPile-Rotisserie".into()),
        ],
        body: HttpBytes::from(form),
    };
    let (status, token_body) = provider_json(&state, "github.com", request).await?;
    if !status.is_success() {
        return Err(ApiError::Unauthorized("GitHub authorization failed".into()));
    }
    let token: OAuthToken = serde_json::from_value(token_body)
        .map_err(|_| ApiError::Unauthorized("GitHub authorization failed".into()))?;
    if token.error.is_some() {
        return Err(ApiError::Unauthorized("GitHub authorization failed".into()));
    }
    let access_token = token
        .access_token
        .filter(|token| !token.is_empty())
        .ok_or_else(|| ApiError::Unauthorized("GitHub authorization failed".into()))?;
    let request = OutboundRequest::get(
        "/user",
        vec![
            ("Accept".into(), "application/vnd.github+json".into()),
            ("Authorization".into(), format!("Bearer {access_token}")),
            ("User-Agent".into(), "ComicPile-Rotisserie".into()),
        ],
    );
    let (status, user_body) = provider_json(&state, "api.github.com", request).await?;
    if !status.is_success() {
        return Err(ApiError::Unauthorized(
            "Could not verify GitHub identity".into(),
        ));
    }
    let user: GitHubUser = serde_json::from_value(user_body)
        .map_err(|_| ApiError::Unauthorized("Could not verify GitHub identity".into()))?;
    if !is_admin(user.id) {
        tracing::warn!(github_user_id = user.id, "Rotisserie OAuth admin denied");
        return Err(ApiError::Forbidden(
            "GitHub user is not a Rotisserie administrator".into(),
        ));
    }
    let now = seconds();
    let session = AdminSession {
        aud: SESSION_AUDIENCE.into(),
        sub: user.id.to_string(),
        login: user.login,
        iat: now,
        exp: now + SESSION_TTL_SECONDS,
    };
    let key = oauth_encoding_key(&state)?;
    let signed = encode(&Header::new(Algorithm::HS256), &session, &key)
        .map_err(|_| ApiError::Internal("Sign-in unavailable".into()))?;
    tracing::info!(github_user_id = user.id, "Rotisserie OAuth admin signed in");
    Ok(redirect(&format!(
        "{PAGES_URL}#rotisserie_session={signed}"
    )))
}

/// The server exchanges the code, verifies /user and returns only a short-lived
/// Rotisserie session to the public site. The GitHub token is discarded.
pub async fn callback(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(params): Query<CallbackParams>,
) -> Response {
    let result = finish_callback(state, headers, params).await;
    match result {
        Ok(response) => clear_cookie(response),
        Err(error) => {
            tracing::warn!(
                error_kind = "github_oauth_rejected",
                "Rotisserie OAuth sign-in failed"
            );
            let code = match error {
                ApiError::Forbidden(_) => "not_admin",
                _ => "sign_in_failed",
            };
            clear_cookie(redirect(&format!("{PAGES_URL}#rotisserie_error={code}")))
        }
    }
}

fn same_origin(headers: &HeaderMap) -> bool {
    headers
        .get(header::ORIGIN)
        .and_then(|value| value.to_str().ok())
        == Some(PAGES_ORIGIN)
}

pub async fn options() -> Response {
    cors(StatusCode::NO_CONTENT.into_response())
}

/// Recheck signed identity and server-side allowlist on every read.
pub async fn session(State(state): State<Arc<AppState>>, headers: HeaderMap) -> Response {
    let result = (|| -> Result<Value, ApiError> {
        if !same_origin(&headers) {
            return Err(ApiError::Forbidden("Invalid dashboard origin".into()));
        }
        let session = session_from_headers(&state, &headers)?;
        Ok(
            json!({"authenticated": true, "login": session.login, "github_id": session.sub,
            "expires_at": session.exp}),
        )
    })();
    cors(match result {
        Ok(payload) => Json(payload).into_response(),
        Err(error) => error.into_response(),
    })
}

/// Only send allowlisted command shapes to the existing Rotisserie workflow.
/// That workflow remains responsible for interpreting operations and leases.
pub async fn dispatch(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(command): Json<Value>,
) -> Response {
    let result = dispatch_inner(state, headers, command).await;
    cors(match result {
        Ok(payload) => (StatusCode::ACCEPTED, Json(payload)).into_response(),
        Err(error) => error.into_response(),
    })
}

async fn dispatch_inner(
    state: Arc<AppState>,
    headers: HeaderMap,
    command: Value,
) -> Result<Value, ApiError> {
    if !same_origin(&headers) {
        return Err(ApiError::Forbidden("Invalid dashboard origin".into()));
    }
    let signed = session_from_headers(&state, &headers)?;
    let operation = command
        .get("operation")
        .and_then(Value::as_str)
        .unwrap_or("");
    if !matches!(
        operation,
        "run"
            | "unstick"
            | "cancel"
            | "sync"
            | "doctor_fix"
            | "release_expired"
            | "settings"
            | "prioritize"
    ) {
        return Err(ApiError::BadRequest("Unsupported factory operation".into()));
    }
    let serialized = serde_json::to_string(&command)
        .map_err(|_| ApiError::BadRequest("Invalid command".into()))?;
    if serialized.len() > MAX_COMMAND_BYTES {
        return Err(ApiError::BadRequest("Factory command too large".into()));
    }
    let token = std::env::var("GITHUB_TOKEN")
        .ok()
        .filter(|token| !token.is_empty())
        .ok_or_else(|| {
            ApiError::ServiceUnavailable("GitHub workflow dispatch unavailable".into())
        })?;
    let request = OutboundRequest {
        method: Method::POST,
        path: format!("/repos/{REPO}/actions/workflows/rotisserie-operator.yml/dispatches"),
        headers: vec![
            ("Accept".into(), "application/vnd.github+json".into()),
            ("Authorization".into(), format!("Bearer {token}")),
            ("User-Agent".into(), "ComicPile-Rotisserie".into()),
            ("Content-Type".into(), "application/json".into()),
            ("X-GitHub-Api-Version".into(), "2026-03-10".into()),
        ],
        body: HttpBytes::from(
            serde_json::to_vec(&json!({
                "ref": "main",
                "inputs": {"request": serialized},
            }))
            .map_err(|_| ApiError::Internal("Could not serialize command".into()))?,
        ),
    };
    let result = tokio::time::timeout(
        Duration::from_secs(10),
        state.outbound.send("api.github.com", request),
    )
    .await
    .map_err(|_| ApiError::ServiceUnavailable("GitHub dispatch timed out".into()))?
    .map_err(|_| ApiError::ServiceUnavailable("GitHub dispatch unavailable".into()))?;
    if result.status != StatusCode::NO_CONTENT {
        tracing::warn!(
            github_user_id = signed.sub.as_str(),
            status = result.status.as_u16(),
            operation,
            "Rotisserie operator dispatch failed"
        );
        return Err(ApiError::ServiceUnavailable(
            "GitHub did not accept the factory command".into(),
        ));
    }
    tracing::info!(
        github_user_id = signed.sub.as_str(),
        operation,
        "Rotisserie operator dispatched"
    );
    Ok(json!({
        "result": "submitted",
        "exit_code": 0,
        "scheduler_url": format!("https://github.com/{REPO}/actions/workflows/rotisserie-operator.yml"),
    }))
}

#[cfg(test)]
mod tests {
    use super::{allowed, CALLBACK_URL, PAGES_ORIGIN};

    #[test]
    fn admin_allowlist_uses_immutable_github_ids_and_fails_closed() {
        assert!(allowed(4_014_199, ""));
        assert!(allowed(123, "123,456"));
        assert!(!allowed(123, "123,malformed"));
        assert!(!allowed(123, "123,,456"));
        assert!(!allowed(124, "123,456"));
        assert!(!allowed(12, "123,456"));
    }

    #[test]
    fn oauth_callback_is_exact_and_hosted_origin_is_pinned() {
        assert_eq!(
            CALLBACK_URL,
            "https://comic-pile.vercel.app/api/v2/factory/github/callback"
        );
        assert_eq!(PAGES_ORIGIN, "https://joshclwren.github.io");
    }
}
