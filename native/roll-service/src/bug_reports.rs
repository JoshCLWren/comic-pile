//! Same-path Rust cutover for the bug-report family (#4852, parent #4335).
//!
//! Preserves the Python `app/api/bug_report.py` wire contract at the same
//! HTTP methods and exact paths (`POST /api/bug-reports/` and
//! `POST /api/v1/bug-reports/`); only the implementation moves from Python
//! FastAPI to the native Roll binary. No frontend URL changes. Python
//! handlers stay mounted until authenticated production proof permits their
//! removal.
//!
//! Parity with the Python oracle (`app/api/bug_report.py` +
//! `app/services/github_issue_rate_limit.py` +
//! `app/services/github_service.py`):
//!
//! * Request `BugReportCreate` (`report_type` default `"bug"`, `title`
//!   1..=200 chars, `description` 1..=2000 chars, optional `diagnostics`
//!   with camelCase aliases `userAgent`/`pixelRatio`/`domContentLoaded`/
//!   `loadComplete`) is validated before any configuration or database work.
//!   Whitespace-only title/description after stripping returns 422 with the
//!   exact Python detail `"Title and description must not be blank"`.
//! * Unconfigured GitHub settings return 503 `"GitHub integration not
//!   configured"` before claiming the rate-limit slot, matching Python order.
//! * Non-admin callers are limited to one successful GitHub issue per
//!   rolling hour via one atomic `INSERT ... ON CONFLICT DO UPDATE ...
//!   WHERE` claim. Admins bypass the limit and never touch the limit table.
//!   A failed GitHub call rolls the claim back so the allowance is not
//!   consumed. Blocked callers return 429 with the exact Python detail plus
//!   `Retry-After` and `X-RateLimit-Reset` headers.
//! * GitHub failures return 502 with the Python `RuntimeError` shape
//!   (`"Failed to create GitHub issue: ..."`); success returns 201 with
//!   `{"issue_url": "<html_url>"}`.
//! * The GitHub issue body (labels, `factory-execution:manual-only` prefix
//!   for feature requests, backtick escaping, diagnostics `<details>` block)
//!   is byte-identical to the Python builder for the same inputs.
//! * Timestamps use Unix seconds + `to_timestamp()` in SQL so the driver
//!   never needs a chrono mapping, matching the existing auth/analytics
//!   convention.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    body::Bytes,
    extract::State,
    http::{HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use bytes::Bytes as HyperBytes;
use chrono::{DateTime, Utc};
use http_body_util::{BodyExt, Full};
use hyper::client::conn::http1;
use hyper_util::rt::TokioIo;
use serde::{Deserialize, Serialize};
use std::{future::Future, pin::Pin, sync::Arc, time::Duration};
use tokio_postgres::Transaction;

const MAX_TITLE_CHARS: usize = 200;
const MAX_DESCRIPTION_CHARS: usize = 2000;
const GITHUB_HOST: &str = "api.github.com";
const GITHUB_TIMEOUT: Duration = Duration::from_secs(8);
const MAX_GITHUB_BODY: usize = 100_000;

/// Rolling-hour allowance for non-admin submitters.
const WINDOW_SECONDS: i64 = 3_600;

const CLAIM_SQL: &str = "INSERT INTO github_issue_submission_limits (user_id, last_submitted_at) VALUES ($1, NULL) ON CONFLICT (user_id) DO UPDATE SET last_submitted_at = github_issue_submission_limits.last_submitted_at WHERE github_issue_submission_limits.last_submitted_at IS NULL OR github_issue_submission_limits.last_submitted_at <= to_timestamp($2) RETURNING user_id";
const FETCH_LIMIT_SQL: &str =
    "SELECT extract(epoch from last_submitted_at)::double precision FROM github_issue_submission_limits WHERE user_id = $1";
const RECORD_SQL: &str =
    "UPDATE github_issue_submission_limits SET last_submitted_at = to_timestamp($2) WHERE user_id = $1";
const USER_SQL: &str = "SELECT username, is_admin FROM users WHERE id = $1";

/// Report kind, mirroring Python `ReportType = Literal["bug", "feature"]`.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Deserialize, Serialize, utoipa::ToSchema)]
#[serde(rename_all = "lowercase")]
pub enum ReportType {
    #[default]
    Bug,
    Feature,
}

/// Screen diagnostic information (`pixelRatio` alias on the wire).
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DiagnosticScreen {
    pub width: i32,
    pub height: i32,
    #[serde(rename = "pixelRatio")]
    pub pixel_ratio: f64,
}

/// Viewport diagnostic information.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DiagnosticViewport {
    pub width: i32,
    pub height: i32,
}

/// Scroll position diagnostic information.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DiagnosticScroll {
    pub x: i32,
    pub y: i32,
}

/// Performance timing diagnostic information (both fields optional).
#[derive(Debug, Clone, Default, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DiagnosticPerformance {
    #[serde(rename = "domContentLoaded", default)]
    pub dom_content_loaded: Option<f64>,
    #[serde(rename = "loadComplete", default)]
    pub load_complete: Option<f64>,
}

/// A captured console error entry.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DiagnosticError {
    pub message: String,
    pub timestamp: String,
}

/// Structured browser diagnostics (`userAgent` alias on the wire).
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct BugReportDiagnostics {
    pub timestamp: String,
    pub url: String,
    #[serde(rename = "userAgent")]
    pub user_agent: String,
    pub screen: DiagnosticScreen,
    pub viewport: DiagnosticViewport,
    pub scroll: DiagnosticScroll,
    pub performance: DiagnosticPerformance,
    pub errors: Vec<DiagnosticError>,
}

/// Request schema for creating a bug report or feature request.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct BugReportCreate {
    #[serde(default)]
    pub report_type: ReportType,
    pub title: String,
    pub description: String,
    #[serde(default)]
    pub diagnostics: Option<BugReportDiagnostics>,
}

impl ReportType {
    fn label(self) -> &'static str {
        match self {
            Self::Bug => "Bug report",
            Self::Feature => "Feature request",
        }
    }
}

/// Response after successfully creating a GitHub issue.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct BugReportResponse {
    pub issue_url: String,
}

fn unprocessable(detail: String) -> ApiError {
    ApiError::with_status(StatusCode::UNPROCESSABLE_ENTITY, detail)
}

fn not_configured() -> ApiError {
    ApiError::with_status(
        StatusCode::SERVICE_UNAVAILABLE,
        "GitHub integration not configured".to_string(),
    )
}

/// GitHub integration settings loaded from the process environment.
///
/// Python `GitHubSettings.is_configured` requires all three values to be
/// non-blank after stripping; the same rule applies here. Values are used
/// trimmed, matching the canonical `owner/repo` shape in production config.
#[derive(Debug, Clone)]
pub struct GithubSettings {
    pub token: String,
    pub owner: String,
    pub repo: String,
}

impl GithubSettings {
    fn from_lookup(get: impl Fn(&str) -> Option<String>) -> Self {
        Self {
            token: get("GITHUB_TOKEN").unwrap_or_default(),
            owner: get("GITHUB_REPO_OWNER").unwrap_or_default(),
            repo: get("GITHUB_REPO_NAME").unwrap_or_default(),
        }
    }

    fn is_configured(&self) -> bool {
        !self.token.trim().is_empty()
            && !self.owner.trim().is_empty()
            && !self.repo.trim().is_empty()
    }

    fn trimmed_owner(&self) -> String {
        self.owner.trim().to_string()
    }

    fn trimmed_repo(&self) -> String {
        self.repo.trim().to_string()
    }

    fn trimmed_token(&self) -> String {
        self.token.trim().to_string()
    }
}

fn github_settings() -> GithubSettings {
    GithubSettings::from_lookup(|name| std::env::var(name).ok())
}

/// Escape backticks so diagnostic values cannot break Markdown code blocks.
///
/// Mirrors Python `_escape_markdown_code`.
fn escape_markdown_code(value: &str) -> String {
    value.replace('`', "\\`")
}

fn labels_for_report_type(report_type: ReportType) -> Vec<&'static str> {
    match report_type {
        ReportType::Feature => vec!["enhancement", "user-reported"],
        ReportType::Bug => vec!["bug", "user-reported"],
    }
}

/// Format a float like Python `str(float)` for the GitHub body.
///
/// Python prints whole-number floats with a trailing `.0` (`"3.0"`), while
/// Rust `Display` prints `"3"`. Integral values get one decimal place here;
/// all other values use the shortest round-trip form, matching Python.
fn python_float(value: f64) -> String {
    if value.is_finite() && value.fract() == 0.0 && value.abs() < 1e15 {
        format!("{value:.1}")
    } else {
        format!("{value}")
    }
}

/// Build the GitHub issue body exactly like Python `_create_bug_report_issue_sync`.
fn build_github_issue_body(
    username: &str,
    report_type: ReportType,
    description: &str,
    diagnostics: Option<&BugReportDiagnostics>,
) -> String {
    let mut body = format!(
        "**Reported by:** {}\n**Report type:** {}\n\n{}",
        escape_markdown_code(username),
        report_type.label(),
        description
    );
    if report_type == ReportType::Feature {
        body = format!("<!-- factory-execution:manual-only -->\n\n{body}");
    }
    if let Some(diag) = diagnostics {
        let performance = &diag.performance;
        let mut perf_str = String::new();
        if performance.dom_content_loaded.is_some() || performance.load_complete.is_some() {
            let mut parts: Vec<String> = Vec::new();
            if let Some(value) = performance.dom_content_loaded {
                parts.push(format!("DOMContentLoaded: {value:.0}ms"));
            }
            if let Some(value) = performance.load_complete {
                parts.push(format!("Load: {value:.0}ms"));
            }
            perf_str = parts.join(", ");
        }
        let errors_str = if diag.errors.is_empty() {
            "None".to_string()
        } else {
            diag.errors
                .iter()
                .map(|error| format!("```\n{}\n```", escape_markdown_code(&error.message)))
                .collect::<Vec<_>>()
                .join("\n")
        };
        body.push_str(&format!(
            "\n\n<details>\n<summary>Diagnostic Information</summary>\n\n**Timestamp:** {}\n**URL:** {}\n**User Agent:** {}\n**Screen:** {}×{} @{}x\n**Viewport:** {}×{}\n**Scroll:** ({}, {})\n",
            escape_markdown_code(&diag.timestamp),
            escape_markdown_code(&diag.url),
            escape_markdown_code(&diag.user_agent),
            diag.screen.width,
            diag.screen.height,
            python_float(diag.screen.pixel_ratio),
            diag.viewport.width,
            diag.viewport.height,
            diag.scroll.x,
            diag.scroll.y,
        ));
        if !perf_str.is_empty() {
            body.push_str(&format!("**Performance:** {perf_str}\n"));
        }
        body.push_str(&format!(
            "\n**Console Errors (last {}):**\n{}\n</details>",
            diag.errors.len(),
            errors_str
        ));
    }
    body
}

/// Client-facing 429 explanation, mirroring Python `_rate_limit_detail`.
fn rate_limit_detail(retry_after_seconds: i64, resets_at: DateTime<Utc>) -> String {
    let minutes = ((retry_after_seconds as f64) / 60.0).ceil() as i64;
    let minutes = minutes.max(1);
    format!(
        "Non-admin accounts can submit one GitHub issue per hour. Try again in {minutes} minute(s), after {} UTC.",
        resets_at.format("%Y-%m-%d %H:%M")
    )
}

fn retry_after_seconds(resets_at: DateTime<Utc>, now: DateTime<Utc>) -> i64 {
    let diff_micros = resets_at.timestamp_micros() - now.timestamp_micros();
    let seconds = (diff_micros as f64 / 1_000_000.0).ceil() as i64;
    seconds.max(1)
}

/// A provider connection must not outlive its awaited Vercel request.
struct ConnectionGuard(tokio::task::JoinHandle<()>);

impl Drop for ConnectionGuard {
    fn drop(&mut self) {
        self.0.abort();
    }
}

async fn create_github_issue(
    settings: GithubSettings,
    title: String,
    body: String,
    labels: Vec<String>,
) -> Result<String, String> {
    let token = settings.trimmed_token();
    let owner = settings.trimmed_owner();
    let repo = settings.trimmed_repo();
    if owner.is_empty() || repo.is_empty() || owner.contains('/') || repo.contains('/') {
        return Err("Failed to create GitHub issue: invalid repository".to_string());
    }
    let payload = serde_json::json!({"title": title, "body": body, "labels": labels});
    let payload_bytes = payload.to_string().into_bytes();
    let path = format!("/repos/{owner}/{repo}/issues");

    let connect = async move {
        let tcp = tokio::net::TcpStream::connect((GITHUB_HOST, 443))
            .await
            .map_err(|_| "Failed to create GitHub issue: network error".to_string())?;
        let tls = native_tls::TlsConnector::new()
            .map_err(|_| "Failed to create GitHub issue: TLS not available".to_string())?;
        let tls = tokio_native_tls::TlsConnector::from(tls)
            .connect(GITHUB_HOST, tcp)
            .await
            .map_err(|_| "Failed to create GitHub issue: TLS handshake failed".to_string())?;
        let (mut sender, connection) = http1::handshake(TokioIo::new(tls))
            .await
            .map_err(|_| "Failed to create GitHub issue: connection failed".to_string())?;
        let _connection_guard = ConnectionGuard(tokio::spawn(async move {
            let _ = connection.await;
        }));
        let authorization = format!("Bearer {token}");
        let request = http::Request::builder()
            .method("POST")
            .uri(path)
            .header("host", GITHUB_HOST)
            .header("accept", "application/vnd.github+json")
            .header("authorization", authorization)
            .header("x-github-api-version", "2022-11-28")
            .header("user-agent", "comic-pile-native/1.0 (bug report)")
            .header("content-type", "application/json")
            .header("content-length", payload_bytes.len().to_string())
            .body(Full::new(HyperBytes::from(payload_bytes)))
            .map_err(|_| "Failed to create GitHub issue: request invalid".to_string())?;
        let mut response = sender
            .send_request(request)
            .await
            .map_err(|_| "Failed to create GitHub issue: network error".to_string())?;
        let status = response.status();
        let mut data = Vec::new();
        while let Some(frame) = response.body_mut().frame().await {
            let frame = frame.map_err(|_| "Failed to create GitHub issue".to_string())?;
            if let Ok(bytes) = frame.into_data() {
                if data.len() + bytes.len() > MAX_GITHUB_BODY {
                    break;
                }
                data.extend_from_slice(&bytes);
            }
        }
        if status.is_success() {
            let value: serde_json::Value = serde_json::from_slice(&data).map_err(|_| {
                "Failed to create GitHub issue: invalid provider payload".to_string()
            })?;
            let url = value
                .get("html_url")
                .and_then(|item| item.as_str())
                .filter(|url| !url.is_empty())
                .ok_or_else(|| {
                    "Failed to create GitHub issue: invalid provider payload".to_string()
                })?;
            return Ok(url.to_string());
        }
        let text = String::from_utf8_lossy(&data).to_string();
        let snippet: String = text.chars().take(300).collect();
        Err(format!(
            "Failed to create GitHub issue: GitHub API returned {} {}",
            status.as_u16(),
            snippet.trim()
        ))
    };
    tokio::time::timeout(GITHUB_TIMEOUT, connect)
        .await
        .map_err(|_| "Failed to create GitHub issue: timeout".to_string())?
}

type GithubFuture = Pin<Box<dyn Future<Output = Result<String, String>> + Send>>;
type GithubIssuer<'a> =
    dyn Fn(GithubSettings, String, String, Vec<String>) -> GithubFuture + Send + Sync + 'a;

async fn claim_slot(
    tx: &Transaction<'_>,
    user_id: i32,
    window_start_seconds: f64,
) -> Result<bool, ApiError> {
    let row = tx
        .query_opt(CLAIM_SQL, &[&user_id, &window_start_seconds])
        .await
        .map_err(db::query_error)?;
    Ok(row.is_some())
}

async fn fetch_limit(
    tx: &Transaction<'_>,
    user_id: i32,
) -> Result<Option<DateTime<Utc>>, ApiError> {
    let row = tx
        .query_opt(FETCH_LIMIT_SQL, &[&user_id])
        .await
        .map_err(db::query_error)?;
    let Some(row) = row else {
        return Ok(None);
    };
    let seconds: Option<f64> = row.try_get(0).map_err(db::query_error)?;
    let Some(seconds) = seconds else {
        return Ok(None);
    };
    let micros = (seconds * 1_000_000.0).round() as i64;
    Ok(DateTime::from_timestamp_micros(micros))
}

async fn record_success(
    tx: &Transaction<'_>,
    user_id: i32,
    submitted_at_seconds: f64,
) -> Result<(), ApiError> {
    tx.execute(RECORD_SQL, &[&user_id, &submitted_at_seconds])
        .await
        .map_err(db::query_error)?;
    Ok(())
}

async fn load_user(state: &AppState, user_id: i32) -> Result<(String, bool), ApiError> {
    let connection = db::checkout(state).await?;
    let row = connection
        .query_opt(USER_SQL, &[&user_id])
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| {
            ApiError::with_status(StatusCode::UNAUTHORIZED, "User not found".to_string())
        })?;
    Ok((row.get(0), row.get(1)))
}

fn validate_create(request: &BugReportCreate) -> Result<(String, String), ApiError> {
    let title_chars = request.title.chars().count();
    if title_chars == 0 || title_chars > MAX_TITLE_CHARS {
        return Err(unprocessable(
            "title length must be between 1 and 200 characters".to_string(),
        ));
    }
    let description_chars = request.description.chars().count();
    if description_chars == 0 || description_chars > MAX_DESCRIPTION_CHARS {
        return Err(unprocessable(
            "description length must be between 1 and 2000 characters".to_string(),
        ));
    }
    let title = request.title.trim().to_string();
    let description = request.description.trim().to_string();
    if title.is_empty() || description.is_empty() {
        return Err(unprocessable(
            "Title and description must not be blank".to_string(),
        ));
    }
    Ok((title, description))
}

fn rate_limit_response(retry_after_seconds: i64, resets_at: DateTime<Utc>) -> Response {
    let detail = rate_limit_detail(retry_after_seconds, resets_at);
    let mut response = (
        StatusCode::TOO_MANY_REQUESTS,
        Json(serde_json::json!({"detail": detail})),
    )
        .into_response();
    if let Ok(value) = HeaderValue::from_str(&retry_after_seconds.to_string()) {
        response.headers_mut().insert("Retry-After", value);
    }
    if let Ok(value) = HeaderValue::from_str(&resets_at.to_rfc3339()) {
        response.headers_mut().insert("X-RateLimit-Reset", value);
    }
    response
}

/// Shared create flow with an injectable GitHub issuer for parity tests.
///
/// The axum handler supplies the real HTTPS issuer; tests supply a fake one
/// that returns a canned `html_url` or failure. Database semantics (claim,
/// fetch, record, commit/rollback) are exercised identically in both cases.
async fn submit_with_issuer(
    state: &Arc<AppState>,
    user_id: i32,
    username: String,
    is_admin: bool,
    request: BugReportCreate,
    settings: GithubSettings,
    issuer: &GithubIssuer<'_>,
) -> Result<Response, ApiError> {
    let (title, description) = validate_create(&request)?;
    if !settings.is_configured() {
        return Err(not_configured());
    }
    let body = build_github_issue_body(
        &username,
        request.report_type,
        &description,
        request.diagnostics.as_ref(),
    );
    let labels: Vec<String> = labels_for_report_type(request.report_type)
        .into_iter()
        .map(str::to_string)
        .collect();

    if is_admin {
        let issue_url = issuer(settings, title, body, labels)
            .await
            .map_err(|detail| ApiError::with_status(StatusCode::BAD_GATEWAY, detail))?;
        return Ok((StatusCode::CREATED, Json(BugReportResponse { issue_url })).into_response());
    }

    let mut connection = db::checkout(state).await?;
    let tx = connection
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    let now = Utc::now();
    let window_start_seconds =
        (now.timestamp_micros() as f64 / 1_000_000.0) - (WINDOW_SECONDS as f64);
    let claimed = claim_slot(&tx, user_id, window_start_seconds).await?;
    if !claimed {
        let last = fetch_limit(&tx, user_id).await?;
        tx.rollback().await.map_err(db::query_error)?;
        let resets_at = match last {
            Some(stamp) => stamp + chrono::Duration::seconds(WINDOW_SECONDS),
            None => Utc::now() + chrono::Duration::seconds(WINDOW_SECONDS),
        };
        let retry = retry_after_seconds(resets_at, Utc::now());
        return Ok(rate_limit_response(retry, resets_at));
    }
    let issue_url = match issuer(settings, title, body, labels).await {
        Ok(url) => url,
        Err(detail) => {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(ApiError::with_status(StatusCode::BAD_GATEWAY, detail));
        }
    };
    let submitted_at_seconds = Utc::now().timestamp_micros() as f64 / 1_000_000.0;
    record_success(&tx, user_id, submitted_at_seconds).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(BugReportResponse { issue_url })).into_response())
}

/// `POST /api/bug-reports/` and `POST /api/v1/bug-reports/`.
///
/// Wire parity with Python `create_bug_report`: same method/path, 201 on
/// success, 422 validation, 503 unconfigured, 429 rate-limit with headers,
/// 502 GitHub failures.
pub async fn create(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    body: Bytes,
) -> Result<Response, ApiError> {
    let request: BugReportCreate = serde_json::from_slice(&body).map_err(|_| {
        unprocessable("Invalid request body: expected a bug-report JSON object".to_string())
    })?;
    let (username, is_admin) = load_user(&state, user.id()).await?;
    let settings = github_settings();
    let issuer =
        |settings: GithubSettings,
         title: String,
         body: String,
         labels: Vec<String>|
         -> GithubFuture { Box::pin(create_github_issue(settings, title, body, labels)) };
    submit_with_issuer(
        &state,
        user.id(),
        username,
        is_admin,
        request,
        settings,
        &issuer,
    )
    .await
}

/// Documentation-only operation for the mounted unversioned create.
#[utoipa::path(
    post,
    path = "/api/bug-reports/",
    tag = "bug-reports",
    request_body = BugReportCreate,
    responses(
        (status = 201, description = "GitHub issue created", body = BugReportResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Invalid or blank title/description, or invalid diagnostics"),
        (status = 429, description = "Non-admin GitHub issue rate limit reached"),
        (status = 502, description = "GitHub issue creation failed"),
        (status = 503, description = "GitHub integration not configured")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn create_documentation() {}

/// Documentation-only operation for the mounted versioned create.
#[utoipa::path(
    post,
    path = "/api/v1/bug-reports/",
    tag = "bug-reports",
    request_body = BugReportCreate,
    responses(
        (status = 201, description = "GitHub issue created", body = BugReportResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Invalid or blank title/description, or invalid diagnostics"),
        (status = 429, description = "Non-admin GitHub issue rate limit reached"),
        (status = 502, description = "GitHub issue creation failed"),
        (status = 503, description = "GitHub integration not configured")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn create_v1_documentation() {}

/// OpenAPI document for the bug-report same-path surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(create_documentation, create_v1_documentation),
    components(schemas(
        ReportType,
        DiagnosticScreen,
        DiagnosticViewport,
        DiagnosticScroll,
        DiagnosticPerformance,
        DiagnosticError,
        BugReportDiagnostics,
        BugReportCreate,
        BugReportResponse
    )),
    modifiers(&BugReportsSecurityAddon)
)]
pub struct BugReportsApi;

struct BugReportsSecurityAddon;

impl utoipa::Modify for BugReportsSecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme(
                "HTTPBearer",
                utoipa::openapi::security::SecurityScheme::Http(
                    utoipa::openapi::security::Http::new(
                        utoipa::openapi::security::HttpAuthScheme::Bearer,
                    ),
                ),
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use utoipa::OpenApi;

    fn sample_diagnostics() -> BugReportDiagnostics {
        BugReportDiagnostics {
            timestamp: "2024-01-01T00:00:00.000Z".to_string(),
            url: "http://test.com".to_string(),
            user_agent: "test-agent".to_string(),
            screen: DiagnosticScreen {
                width: 390,
                height: 844,
                pixel_ratio: 3.0,
            },
            viewport: DiagnosticViewport {
                width: 390,
                height: 664,
            },
            scroll: DiagnosticScroll { x: 0, y: 234 },
            performance: DiagnosticPerformance {
                dom_content_loaded: Some(1234.0),
                load_complete: Some(2345.0),
            },
            errors: vec![],
        }
    }

    #[test]
    fn request_wire_matches_python_schema() {
        let value = serde_json::to_value(BugReportResponse {
            issue_url: "https://github.com/test/repo/issues/1".to_string(),
        })
        .expect("serializable response");
        assert_eq!(
            value,
            serde_json::json!({"issue_url": "https://github.com/test/repo/issues/1"})
        );
    }

    #[test]
    fn diagnostics_wire_uses_camel_case_aliases() {
        let value = serde_json::to_value(sample_diagnostics()).expect("diagnostics");
        assert_eq!(value["userAgent"], "test-agent");
        assert_eq!(value["screen"]["pixelRatio"], 3.0);
        assert_eq!(value["performance"]["domContentLoaded"], 1234.0);
        assert_eq!(value["performance"]["loadComplete"], 2345.0);
    }

    #[test]
    fn blank_title_or_description_returns_python_detail() {
        for request in [
            BugReportCreate {
                report_type: ReportType::Bug,
                title: "   ".to_string(),
                description: "details".to_string(),
                diagnostics: None,
            },
            BugReportCreate {
                report_type: ReportType::Bug,
                title: "bug".to_string(),
                description: "   ".to_string(),
                diagnostics: None,
            },
        ] {
            let error = validate_create(&request).expect_err("blank must fail");
            assert_eq!(error.status(), StatusCode::UNPROCESSABLE_ENTITY);
            assert_eq!(error.detail(), "Title and description must not be blank");
        }
    }

    #[test]
    fn title_and_description_lengths_are_enforced() {
        let too_long_title = BugReportCreate {
            report_type: ReportType::Bug,
            title: "A".repeat(201),
            description: "d".to_string(),
            diagnostics: None,
        };
        assert_eq!(
            validate_create(&too_long_title).unwrap_err().status(),
            StatusCode::UNPROCESSABLE_ENTITY
        );
        let too_long_description = BugReportCreate {
            report_type: ReportType::Bug,
            title: "t".to_string(),
            description: "D".repeat(2001),
            diagnostics: None,
        };
        assert_eq!(
            validate_create(&too_long_description).unwrap_err().status(),
            StatusCode::UNPROCESSABLE_ENTITY
        );
        let valid = BugReportCreate {
            report_type: ReportType::Bug,
            title: "t".to_string(),
            description: "d".to_string(),
            diagnostics: None,
        };
        assert!(validate_create(&valid).is_ok());
    }

    #[test]
    fn issue_body_matches_python_builder() {
        let body = build_github_issue_body("reporter", ReportType::Bug, "Something broke", None);
        assert_eq!(
            body,
            "**Reported by:** reporter\n**Report type:** Bug report\n\nSomething broke"
        );
        let feature =
            build_github_issue_body("reporter", ReportType::Feature, "Please add X", None);
        assert!(feature.starts_with("<!-- factory-execution:manual-only -->\n\n**Reported by:**"));
        assert!(feature.contains("**Report type:** Feature request"));
        assert_eq!(
            labels_for_report_type(ReportType::Feature),
            vec!["enhancement", "user-reported"]
        );
        assert_eq!(
            labels_for_report_type(ReportType::Bug),
            vec!["bug", "user-reported"]
        );
    }

    #[test]
    fn diagnostics_body_includes_details_and_escapes_backticks() {
        let diag = BugReportDiagnostics {
            user_agent: "agent```injected```".to_string(),
            errors: vec![DiagnosticError {
                message: "error with `backtick`".to_string(),
                timestamp: "2024-01-01T00:00:00.000Z".to_string(),
            }],
            ..sample_diagnostics()
        };
        let body = build_github_issue_body("reporter", ReportType::Bug, "desc", Some(&diag));
        assert!(body.contains("<details>"));
        assert!(body.contains("**Timestamp:** 2024-01-01T00:00:00.000Z"));
        assert!(body.contains("**Screen:** 390×844 @3.0x"));
        assert!(body.contains("**Viewport:** 390×664"));
        assert!(body.contains("**Scroll:** (0, 234)"));
        assert!(body.contains("**Performance:** DOMContentLoaded: 1234ms, Load: 2345ms"));
        assert!(!body.contains("```injected```"));
        assert!(!body.contains("error with `backtick`"));
        assert!(body.contains("**Console Errors (last 1):**"));
        assert!(body.contains("```"));
    }

    #[test]
    fn diagnostics_body_is_byte_identical_to_python_oracle() {
        let body = build_github_issue_body(
            "reporter",
            ReportType::Bug,
            "Something broke",
            Some(&sample_diagnostics()),
        );
        assert_eq!(
            body,
            "**Reported by:** reporter\n**Report type:** Bug report\n\nSomething broke\n\n<details>\n<summary>Diagnostic Information</summary>\n\n**Timestamp:** 2024-01-01T00:00:00.000Z\n**URL:** http://test.com\n**User Agent:** test-agent\n**Screen:** 390×844 @3.0x\n**Viewport:** 390×664\n**Scroll:** (0, 234)\n**Performance:** DOMContentLoaded: 1234ms, Load: 2345ms\n\n**Console Errors (last 0):**\nNone\n</details>"
        );
    }

    #[test]
    fn rate_limit_detail_matches_python_format() {
        let resets_at = Utc
            .with_ymd_and_hms(2026, 11, 8, 4, 5, 0)
            .single()
            .expect("valid date");
        let detail = rate_limit_detail(3600, resets_at);
        assert_eq!(
            detail,
            "Non-admin accounts can submit one GitHub issue per hour. Try again in 60 minute(s), after 2026-11-08 04:05 UTC."
        );
        assert_eq!(retry_after_seconds(resets_at, resets_at), 1);
    }

    #[test]
    fn claim_sql_is_atomic_and_bounded() {
        assert!(CLAIM_SQL.contains("ON CONFLICT (user_id) DO UPDATE"));
        assert!(CLAIM_SQL.contains("to_timestamp($2)"));
        assert!(CLAIM_SQL.contains("RETURNING user_id"));
        assert!(!CLAIM_SQL.contains(';'));
        assert!(FETCH_LIMIT_SQL.contains("extract(epoch from last_submitted_at)"));
        assert!(RECORD_SQL.contains("to_timestamp($2)"));
    }

    #[test]
    fn github_settings_require_all_three_values() {
        let configured = GithubSettings::from_lookup(|name| match name {
            "GITHUB_TOKEN" => Some("tok".to_string()),
            "GITHUB_REPO_OWNER" => Some("owner".to_string()),
            "GITHUB_REPO_NAME" => Some("repo".to_string()),
            _ => None,
        });
        assert!(configured.is_configured());
        let missing = GithubSettings::from_lookup(|name| match name {
            "GITHUB_TOKEN" => Some("tok".to_string()),
            _ => None,
        });
        assert!(!missing.is_configured());
        let blank = GithubSettings::from_lookup(|name| match name {
            "GITHUB_TOKEN" => Some("   ".to_string()),
            "GITHUB_REPO_OWNER" => Some("owner".to_string()),
            "GITHUB_REPO_NAME" => Some("repo".to_string()),
            _ => None,
        });
        assert!(!blank.is_configured());
    }

    #[test]
    fn bug_reports_openapi_covers_both_same_paths() {
        let document = serde_json::to_value(BugReportsApi::openapi()).expect("openapi");
        let paths = document["paths"].as_object().expect("paths");
        assert!(paths.contains_key("/api/bug-reports/"));
        assert!(paths.contains_key("/api/v1/bug-reports/"));
        for path in ["/api/bug-reports/", "/api/v1/bug-reports/"] {
            let operation = &document["paths"][path]["post"];
            assert!(operation["operationId"].is_string());
            assert!(operation["responses"]["201"].as_object().is_some());
            assert!(operation["security"].is_array());
        }
        assert!(document["components"]["schemas"]["BugReportCreate"].is_object());
        assert!(document["components"]["schemas"]["BugReportResponse"].is_object());
    }

    /// Set configured GitHub env vars for the current test process, restoring
    /// any previous values on drop so parallel test threads observe the
    /// original environment.
    struct TempGitHubEnv {
        previous: Vec<(&'static str, Option<String>)>,
    }

    impl TempGitHubEnv {
        fn install() -> Self {
            let values: Vec<(&'static str, &str)> = vec![
                ("GITHUB_TOKEN", "synthetic-test-token"),
                ("GITHUB_REPO_OWNER", "comic-pile-test"),
                ("GITHUB_REPO_NAME", "synthetic"),
            ];
            let previous = values
                .iter()
                .map(|(name, _)| (*name, std::env::var(name).ok()))
                .collect();
            for (name, value) in values {
                std::env::set_var(name, value);
            }
            Self { previous }
        }
    }

    impl Drop for TempGitHubEnv {
        fn drop(&mut self) {
            for (name, previous) in &self.previous {
                match previous {
                    Some(value) => std::env::set_var(name, value),
                    None => std::env::remove_var(name),
                }
            }
        }
    }

    #[tokio::test]
    async fn create_claims_rate_limit_slot_in_disposable_postgres_and_rolls_back_on_issuer_failure()
    {
        use crate::{db, test_support};

        let state = test_support::test_state(2)
            .await
            .expect("RUST_ROLL_TEST_DATABASE_URL is required");
        let _guard = test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username, is_admin) VALUES (1101, 'bug-reports-test', false);",
            )
            .await
            .expect("seed bug reports user");
        drop(connection);

        let _env = TempGitHubEnv::install();
        let error = create(
            State(state.clone()),
            AuthenticatedUser::for_test(1101),
            Bytes::from(r#"{"title":"Something broke","description":"Details"}"#),
        )
        .await
        .expect_err("synthetic issuer must fail so the claim rolls back");
        assert_eq!(error.status(), StatusCode::BAD_GATEWAY);

        let connection = db::checkout(&state).await.expect("verify connection");
        let consumed: i64 = connection
            .query_one(
                "SELECT count(*) FROM github_issue_submission_limits WHERE user_id = $1 AND last_submitted_at IS NOT NULL",
                &[&1101],
            )
            .await
            .expect("verify claim rollback")
            .get(0);
        assert_eq!(
            consumed, 0,
            "a failed issuer must not consume the rolling-hour allowance"
        );
    }

    #[tokio::test]
    async fn bug_reports_require_auth_through_service_router() {
        use crate::{config::Config, router};
        use axum::{body::Body, http::Request};
        use tower::ServiceExt;

        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        })
        .unwrap();
        let app = router(Arc::new(AppState::new(config).unwrap()));
        for uri in ["/api/bug-reports/", "/api/v1/bug-reports/"] {
            let response = app
                .clone()
                .oneshot(
                    Request::builder()
                        .method("POST")
                        .uri(uri)
                        .header("content-type", "application/json")
                        .header("cookie", "csrf_token=synthetic-test-csrf")
                        .header("x-csrf-token", "synthetic-test-csrf")
                        .body(Body::from(r#"{"title":"Bug","description":"Details"}"#))
                        .unwrap(),
                )
                .await
                .unwrap();
            assert_eq!(
                response.status(),
                StatusCode::UNAUTHORIZED,
                "{uri} must require auth through the service router"
            );
        }
    }
}
