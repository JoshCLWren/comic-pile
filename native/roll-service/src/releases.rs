//! Same-path native What's New release ledger.
//!
//! The Python implementation was deleted once production traffic proved the
//! native ingress serves these operations (see issue #4849). This module owns
//! the writer-token authorization, idempotent source identity, public-read
//! filters, provenance validation, deterministic copy repair, and response
//! shapes.

use crate::{db, ApiError, AppState};
use axum::{
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::sync::{Arc, OnceLock};
use tokio_postgres::Row;
use utoipa::ToSchema;

// ---------------------------------------------------------------------------
// DTOs (wire shapes preserved from app/schemas/release.py)
// ---------------------------------------------------------------------------

/// Idempotent release publication payload from trusted automation.
#[derive(Debug, Clone, Deserialize, Serialize, ToSchema)]
pub struct ReleaseUpsertRequest {
    pub source_repository: String,
    #[serde(default)]
    pub source_pr_number: Option<i32>,
    #[serde(default)]
    pub source_merge_sha: Option<String>,
    #[serde(default)]
    #[schema(value_type = String, format = "date-time")]
    pub merged_at: Option<String>,
    #[schema(value_type = String, format = "date-time")]
    pub released_at: String,
    pub category: String,
    pub title: String,
    pub summary: String,
    #[serde(default)]
    pub body: Option<String>,
    #[serde(default = "default_visibility")]
    pub visibility: String,
    #[serde(default = "default_status")]
    pub status: String,
    #[serde(default)]
    pub sort_order: i32,
    #[serde(default)]
    pub provenance_json: Value,
}

fn default_visibility() -> String {
    "public".to_string()
}

fn default_status() -> String {
    "published".to_string()
}

/// One complete release ledger record returned to trusted automation.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReleaseResponse {
    pub id: i32,
    pub source_repository: String,
    pub source_pr_number: Option<i32>,
    pub source_merge_sha: Option<String>,
    #[schema(value_type = String, format = "date-time")]
    pub merged_at: Option<String>,
    #[schema(value_type = String, format = "date-time")]
    pub released_at: String,
    pub category: String,
    pub title: String,
    pub summary: String,
    pub body: Option<String>,
    pub visibility: String,
    pub status: String,
    pub sort_order: i32,
    pub provenance_json: Value,
    #[schema(value_type = String, format = "date-time")]
    pub created_at: String,
    #[schema(value_type = String, format = "date-time")]
    pub updated_at: String,
}

/// One release ledger record returned by public-facing endpoints.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct PublicReleaseResponse {
    pub id: i32,
    #[schema(value_type = String, format = "date-time")]
    pub released_at: String,
    pub category: String,
    pub title: String,
    pub summary: String,
    pub body: Option<String>,
    pub sort_order: i32,
    #[schema(value_type = String, format = "date-time")]
    pub created_at: String,
    #[schema(value_type = String, format = "date-time")]
    pub updated_at: String,
}

/// Paginated published releases for What's New.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReleaseListResponse {
    pub releases: Vec<PublicReleaseResponse>,
    pub total: i64,
    pub limit: i32,
    pub offset: i32,
}

/// Minimal release data for reconciliation endpoints (no body).
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct MinimalReleaseResponse {
    pub id: i32,
    pub source_repository: String,
    pub source_pr_number: Option<i32>,
    pub source_merge_sha: Option<String>,
    #[schema(value_type = String, format = "date-time")]
    pub merged_at: Option<String>,
    #[schema(value_type = String, format = "date-time")]
    pub released_at: String,
    pub category: String,
    pub title: String,
    pub summary: String,
    pub visibility: String,
    pub status: String,
    pub sort_order: i32,
    pub provenance_json: Value,
    #[schema(value_type = String, format = "date-time")]
    pub created_at: String,
    #[schema(value_type = String, format = "date-time")]
    pub updated_at: String,
}

/// Result of reconciling a GitHub source identity with the ledger.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReleaseSourceResponse {
    pub exists: bool,
    pub release: Option<MinimalReleaseResponse>,
}

// ---------------------------------------------------------------------------
// Error helpers (Python HTTPException detail strings preserved)
// ---------------------------------------------------------------------------

fn unprocessable(detail: impl Into<String>) -> ApiError {
    ApiError::with_status(StatusCode::UNPROCESSABLE_ENTITY, detail.into())
}

fn not_found(detail: impl Into<String>) -> ApiError {
    ApiError::with_status(StatusCode::NOT_FOUND, detail.into())
}

fn conflict(detail: impl Into<String>) -> ApiError {
    ApiError::with_status(StatusCode::CONFLICT, detail.into())
}

fn unavailable(detail: impl Into<String>) -> ApiError {
    ApiError::with_status(StatusCode::SERVICE_UNAVAILABLE, detail.into())
}

fn unauthorized(detail: impl Into<String>) -> ApiError {
    ApiError::with_status(StatusCode::UNAUTHORIZED, detail.into())
}

// ---------------------------------------------------------------------------
// Writer-token authorization (mirrors require_release_writer_token)
// ---------------------------------------------------------------------------

fn constant_time_eq(left: &str, right: &str) -> bool {
    let (left, right) = (left.as_bytes(), right.as_bytes());
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right)
        .fold(0u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

/// Validate the release-writer credential against an expected token.
///
/// `expected` is the stripped `RELEASE_WRITER_TOKEN` value (empty when
/// unconfigured). Matches Python: 503 when unconfigured, 401 when missing or
/// mismatched.
fn check_writer_token(presented: Option<&str>, expected: &str) -> Result<(), ApiError> {
    if expected.is_empty() {
        return Err(unavailable(
            "Release writer authorization is not configured",
        ));
    }
    match presented {
        Some(value) if constant_time_eq(value, expected) => Ok(()),
        _ => Err(unauthorized("Invalid release writer credential")),
    }
}

fn expected_writer_token() -> String {
    std::env::var("RELEASE_WRITER_TOKEN")
        .unwrap_or_default()
        .trim()
        .to_string()
}

fn check_writer_from_headers(headers: &HeaderMap) -> Result<(), ApiError> {
    let presented = headers
        .get("x-release-writer-token")
        .and_then(|value| value.to_str().ok());
    check_writer_token(presented, &expected_writer_token())
}

// ---------------------------------------------------------------------------
// Regexes (Python `re` patterns; lookaround handled manually where the Rust
// `regex` crate has no lookbehind/lookahead support)
// ---------------------------------------------------------------------------

fn compiled(pattern: &str, case_insensitive: bool) -> Regex {
    match regex::RegexBuilder::new(pattern)
        .case_insensitive(case_insensitive)
        .build()
    {
        Ok(regex) => regex,
        Err(error) => panic!("static release regex must compile: {error}"),
    }
}

fn markdown_link() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| compiled(r"\[([^\]]+)\]\((https?://[^)]+)\)", false))
}

fn backtick() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| compiled(r"`([^`]+)`", false))
}

fn schema_ident() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| compiled(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", false))
}

fn phase_term_schema() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        compiled(
            r"\bphases?\s+(?:\d+(?:\.\d+)*|one|two|three|four|five|six|seven|eight|nine|ten)\b",
            true,
        )
    })
}

fn unfinished() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        compiled(
            r"\b(?:incomplete|unfinished|todo|wip|not yet implemented)\b",
            true,
        )
    })
}

fn escaped_u() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| compiled(r"\\+u(0027|2018|2019)", true))
}

fn escaped_apos() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| compiled(r"\\+'", false))
}

fn capability_claim() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        compiled(
            r"\b(?:you can now|can now|now\s+(?:supports|includes|lets\s+you|handles)|(?:is|are)\s+now\s+available)\b",
            true,
        )
    })
}

fn phase_term_copy() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        compiled(
            r"\bphases?\s+(?:\d+(?:\.\d+)*|one|two|three|four|five|six|seven|eight|nine|ten)(?:\s+(?:and|or)\s+(?:\d+(?:\.\d+)*|one|two|three|four|five|six|seven|eight|nine|ten))?\b",
            true,
        )
    })
}

fn phase_prefix() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        compiled(
            r"^\s*phases?\s+(?:\d+(?:\.\d+)*|one|two|three|four|five|six|seven|eight|nine|ten)(?:\s+(?:and|or)\s+(?:\d+(?:\.\d+)*|one|two|three|four|five|six|seven|eight|nine|ten))?\s*[:\-–—]\s*",
            true,
        )
    })
}

fn phase_inline() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        compiled(
            r"\bphases?\s+(?:\d+(?:\.\d+)*|one|two|three|four|five|six|seven|eight|nine|ten)(?:\s+(?:and|or)\s+(?:\d+(?:\.\d+)*|one|two|three|four|five|six|seven|eight|nine|ten))?\s*(?:of\s+)?",
            true,
        )
    })
}

fn internal_path_tail() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        compiled(
            r"\b[\w-]+(?:/[\w-]+)*\.(?:py|ts|tsx|js|jsx|json|toml|ya?ml|css|md|sh|sql)\b",
            false,
        )
    })
}

fn internal_path_head() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        compiled(
            r"(?:app|comic_pile|frontend|static|scripts|tests|alembic)(?:/[\w.-]+)+",
            false,
        )
    })
}

fn dangling_connective() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        compiled(
            r"\s+\b(?:and|but|or|in|inside|within|from|under|to|of|for|via|using|with)\s*$",
            true,
        )
    })
}

fn word_char() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| compiled(r"[0-9A-Za-z]", false))
}

fn test_narrative() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        compiled(
            r"\b\d[\d,]*\s+(?:new\s+)?assertions?\b|\b(?:unit|integration|regression|playwright|vitest|pytest)\s+(?:tests?|specs?|coverage|suite)\b|\btests?\s+(?:suite|coverage)\b|\b[\w-]+\.(?:spec|test)\.(?:ts|tsx|js|jsx)\b",
            true,
        )
    })
}

fn leading_sep() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| compiled(r"^\s*[:;,\-–—|]+\s*", false))
}

fn parenthetical() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| compiled(r"\s*\([^()]*\)", false))
}

fn artifact_clause() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        compiled(
            r",\s*(?:closing|resolving|resolves|fixes|with|including|via|using|tracked in|covered by|backed by)\b[^.;!?]*",
            true,
        )
    })
}

fn dangling_head() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        compiled(
            r"^(?:of|for|to|with|and|or|in|on|at|by|from|that|which|whose|where|when|while|as)\b",
            false,
        )
    })
}

fn engineering_only() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        compiled(
            r"\b(?:api|backend|frontend|schema|repository|service|migration|endpoint|hook|component|module|refactor|implementation)\b",
            true,
        )
    })
}

fn reader_cue() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| compiled(r"\b(?:you|your|reader|readers)\b", true))
}

fn ticket_candidate() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| compiled(r"#\d{1,7}\b", false))
}

/// True when the character before `start` is absent or not a word/`&` char,
/// matching Python `(?<![\w&])`.
fn ticket_preceding_ok(text: &str, start: usize) -> bool {
    if start == 0 {
        return true;
    }
    let before = &text[..start];
    let Some(ch) = before.chars().last() else {
        return true;
    };
    !(ch == '&' || ch == '_' || ch.is_alphanumeric())
}

fn remove_tickets(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut pos = 0;
    for matched in ticket_candidate().find_iter(text) {
        if !ticket_preceding_ok(text, matched.start()) {
            continue;
        }
        out.push_str(&text[pos..matched.start()]);
        pos = matched.end();
    }
    out.push_str(&text[pos..]);
    out
}

fn ticket_search(text: &str) -> Option<(usize, usize)> {
    for matched in ticket_candidate().find_iter(text) {
        if ticket_preceding_ok(text, matched.start()) {
            return Some((matched.start(), matched.end()));
        }
    }
    None
}

/// Remove internal paths (both alternatives) honouring the standalone-start
/// lookbehind for the directory form.
fn remove_internal_paths(text: &str) -> String {
    // First alternative: (app|...) (/...) with (?<![\w/]) guard.
    let mut candidates: Vec<(usize, usize)> = Vec::new();
    for matched in internal_path_head().find_iter(text) {
        if matched.start() == 0 {
            candidates.push((matched.start(), matched.end()));
            continue;
        }
        let before = &text[..matched.start()];
        let ch = before.chars().last().unwrap_or(' ');
        if ch == '/' || ch == '_' || ch.is_alphanumeric() {
            continue;
        }
        candidates.push((matched.start(), matched.end()));
    }
    for matched in internal_path_tail().find_iter(text) {
        candidates.push((matched.start(), matched.end()));
    }
    candidates.sort();
    // De-duplicate overlapping spans, keeping the earliest/longest order.
    let mut spans: Vec<(usize, usize)> = Vec::new();
    for span in candidates {
        if let Some(last) = spans.last() {
            if span.0 < last.1 {
                continue;
            }
        }
        spans.push(span);
    }
    let mut out = String::with_capacity(text.len());
    let mut pos = 0;
    for (start, end) in spans {
        if start < pos {
            continue;
        }
        out.push_str(&text[pos..start]);
        pos = end;
    }
    out.push_str(&text[pos..]);
    out
}

fn internal_path_search(text: &str) -> Option<String> {
    for matched in internal_path_head().find_iter(text) {
        if matched.start() == 0 {
            return Some(matched.as_str().to_string());
        }
        let before = &text[..matched.start()];
        let ch = before.chars().last().unwrap_or(' ');
        if ch == '/' || ch == '_' || ch.is_alphanumeric() {
            continue;
        }
        return Some(matched.as_str().to_string());
    }
    internal_path_tail()
        .find(text)
        .map(|m| m.as_str().to_string())
}

// ---------------------------------------------------------------------------
// Escape decoding + visible text (shared by validation and repair)
// ---------------------------------------------------------------------------

/// Decode escaped apostrophes that leak into reader-facing release copy.
fn decode_release_escapes(value: &str) -> String {
    let after_u = escaped_u().replace_all(value, |caps: &regex::Captures<'_>| {
        match caps[1].to_lowercase().as_str() {
            "0027" => "'".to_string(),
            "2018" => "\u{2018}".to_string(),
            "2019" => "\u{2019}".to_string(),
            _ => caps[0].to_string(),
        }
    });
    escaped_apos().replace_all(&after_u, "'").to_string()
}

fn visible_release_text(value: &str) -> String {
    let after_links = markdown_link().replace_all(value, "$1");
    backtick().replace_all(&after_links, "$1").to_string()
}

fn display_length(value: &str) -> usize {
    visible_release_text(value).trim().chars().count()
}

// ---------------------------------------------------------------------------
// Write-gate validation (mirrors app/schemas/release.py)
// ---------------------------------------------------------------------------

const SCHEMA_TYPOS: [(&str, &str); 14] = [
    ("appearnence", "appearance"),
    ("appearence", "appearance"),
    ("recieve", "receive"),
    ("recieved", "received"),
    ("seperate", "separate"),
    ("seperated", "separated"),
    ("occured", "occurred"),
    ("untill", "until"),
    ("definately", "definitely"),
    ("accross", "across"),
    ("existance", "existence"),
    ("persistant", "persistent"),
    ("successfull", "successful"),
    ("compatability", "compatibility"),
];

/// Describe the first internal artifact in reader-facing copy, or None.
fn find_internal_artifact(field_name: &str, value: &str) -> Option<String> {
    let text = visible_release_text(value);
    let reason = |kind: &str, fragment: &str| {
        format!("{field_name} must use reader-facing product language: {kind} '{fragment}'")
    };
    if let Some((start, end)) = ticket_search(&text) {
        return Some(reason("internal ticket reference", &text[start..end]));
    }
    if let Some(m) = schema_ident().find(&text) {
        return Some(reason("database/schema identifier", m.as_str()));
    }
    if let Some(m) = phase_term_schema().find(&text) {
        return Some(reason("implementation phase terminology", m.as_str()));
    }
    if let Some(m) = unfinished().find(&text) {
        return Some(reason("unfinished-work commentary", m.as_str()));
    }
    let lowered = text.to_lowercase();
    for (wrong, right) in SCHEMA_TYPOS {
        let needle = format!(r"\b{}\b", regex::escape(wrong));
        let Ok(re) = Regex::new(&needle) else {
            continue;
        };
        if re.is_match(&lowered) {
            return Some(format!(
                "{field_name} must be spell-checked before publication: '{wrong}' (did you mean '{right}'?)"
            ));
        }
    }
    None
}

fn provenance_text(provenance: &Value, name: &str, minimum: usize) -> Result<String, ApiError> {
    let value = provenance.get(name);
    let Some(text) = value.and_then(Value::as_str) else {
        return Err(unprocessable(format!(
            "provenance_json.{name} must be a string to justify a public release"
        )));
    };
    let trimmed = text.trim().to_string();
    let maximum = match name {
        "classification_reason" => 1000,
        "user_visible_evidence" => 2000,
        "reader_reachable_path" => 500,
        _ => 1000,
    };
    if trimmed.chars().count() < minimum {
        return Err(unprocessable(format!(
            "provenance_json.{name} must describe the change in at least {minimum} characters to justify a public release"
        )));
    }
    if trimmed.chars().count() > maximum {
        return Err(unprocessable(format!(
            "provenance_json.{name} must be at most {maximum} characters"
        )));
    }
    Ok(trimmed)
}

fn provenance_string_list(provenance: &Value, name: &str) -> Result<Vec<String>, ApiError> {
    let value = provenance.get(name);
    let Some(list) = value
        .cloned()
        .unwrap_or(Value::Array(Vec::new()))
        .as_array()
        .cloned()
    else {
        return Err(unprocessable(format!(
            "provenance_json.{name} must be a list of non-empty strings"
        )));
    };
    let mut entries = Vec::new();
    for item in list {
        let Some(text) = item.as_str() else {
            return Err(unprocessable(format!(
                "provenance_json.{name} must be a list of non-empty strings"
            )));
        };
        if text.trim().is_empty() {
            return Err(unprocessable(format!(
                "provenance_json.{name} must be a list of non-empty strings"
            )));
        }
        entries.push(text.trim().to_string());
    }
    Ok(entries)
}

fn provenance_issue_numbers(provenance: &Value) -> Result<Vec<i64>, ApiError> {
    let value = provenance.get("inspected_issue_numbers");
    let list = value
        .cloned()
        .unwrap_or(Value::Array(Vec::new()))
        .as_array()
        .cloned();
    let Some(items) = list else {
        return Err(unprocessable(
            "provenance_json.inspected_issue_numbers must be a list of issue numbers",
        ));
    };
    let mut numbers = Vec::new();
    for item in items {
        let Some(number) = item.as_i64() else {
            return Err(unprocessable(
                "provenance_json.inspected_issue_numbers must be a list of issue numbers",
            ));
        };
        if number < 1 {
            return Err(unprocessable(
                "provenance_json.inspected_issue_numbers must be a list of issue numbers",
            ));
        }
        numbers.push(number);
    }
    numbers.sort_unstable();
    numbers.dedup();
    Ok(numbers)
}

fn capability_claim_present(values: &[&str]) -> bool {
    values
        .iter()
        .any(|value| capability_claim().is_match(value))
}

fn decode_upsert(request: &mut ReleaseUpsertRequest) {
    request.category = decode_release_escapes(&request.category);
    request.title = decode_release_escapes(&request.title);
    request.summary = decode_release_escapes(&request.summary);
    if let Some(body) = request.body.clone() {
        request.body = Some(decode_release_escapes(&body));
    }
}

/// Validate one publication payload exactly as
/// `ReleaseUpsertRequest`'s model validators do (after escape decoding).
fn validate_upsert_request(request: &ReleaseUpsertRequest) -> Result<(), ApiError> {
    if request.source_repository.is_empty() || request.source_repository.chars().count() > 255 {
        return Err(unprocessable(
            "source_repository must be between 1 and 255 characters",
        ));
    }
    if let Some(number) = request.source_pr_number {
        if number < 1 {
            return Err(unprocessable("source_pr_number must be at least 1"));
        }
    }
    if let Some(sha) = &request.source_merge_sha {
        if sha.chars().count() < 7 || sha.chars().count() > 64 {
            return Err(unprocessable(
                "source_merge_sha must be between 7 and 64 characters",
            ));
        }
    }
    if request.category.is_empty() || request.category.chars().count() > 100 {
        return Err(unprocessable(
            "category must be between 1 and 100 characters",
        ));
    }
    if request.title.is_empty() || request.title.chars().count() > 255 {
        return Err(unprocessable("title must be between 1 and 255 characters"));
    }
    if request.summary.is_empty() || request.summary.chars().count() < 1 {
        return Err(unprocessable("summary must not be empty"));
    }
    if !matches!(request.visibility.as_str(), "public" | "internal") {
        return Err(unprocessable("visibility must be 'public' or 'internal'"));
    }
    if !matches!(request.status.as_str(), "draft" | "published" | "retracted") {
        return Err(unprocessable(
            "status must be 'draft', 'published' or 'retracted'",
        ));
    }
    // Datetime fields must be parseable when supplied.
    if !is_parseable_datetime(&request.released_at) {
        return Err(unprocessable("released_at must be a valid date-time"));
    }
    if let Some(merged) = &request.merged_at {
        if !is_parseable_datetime(merged) {
            return Err(unprocessable("merged_at must be a valid date-time"));
        }
    }
    // require_github_identity
    if request.source_pr_number.is_none() && request.source_merge_sha.is_none() {
        return Err(unprocessable(
            "source_pr_number or source_merge_sha is required",
        ));
    }
    if request.status != "published" || request.visibility != "public" {
        return Ok(());
    }
    // enforce_reader_facing_copy (category, title, summary)
    for (field, value) in [
        ("category", request.category.as_str()),
        ("title", request.title.as_str()),
        ("summary", request.summary.as_str()),
    ] {
        if let Some(artifact) = find_internal_artifact(field, value) {
            return Err(unprocessable(artifact));
        }
    }
    // validate_meaningful_content
    for (field, value, minimum) in [
        ("category", request.category.as_str(), 2usize),
        ("title", request.title.as_str(), 4usize),
        ("summary", request.summary.as_str(), 12usize),
    ] {
        if display_length(value) < minimum {
            return Err(unprocessable(format!(
                "{field} must contain meaningful release content (at least {minimum} visible characters)"
            )));
        }
    }
    // require_public_classification_evidence
    let provenance = &request.provenance_json;
    if provenance.get("classification").and_then(Value::as_str) != Some("public") {
        return Err(unprocessable(
            "provenance_json.classification must be \"public\" for a public release",
        ));
    }
    let _ = provenance_text(provenance, "classification_reason", 1)?;
    let _ = provenance_text(provenance, "user_visible_evidence", 20)?;
    if provenance.get("reader_reachable").and_then(Value::as_bool) != Some(true) {
        return Err(unprocessable(
            "provenance_json.reader_reachable must be true for a public release; classify the change as internal when no shipped reader path exists",
        ));
    }
    let _ = provenance_issue_numbers(provenance)?;
    let scope_fences = provenance_string_list(provenance, "scope_fences")?;
    let contradicting = provenance_string_list(provenance, "contradicting_evidence")?;
    if !scope_fences.is_empty() && contradicting.is_empty() {
        return Err(unprocessable(format!(
            "linked issue scope fences contradict a public release ({}); classify the change as internal or record provenance_json.contradicting_evidence explaining the shipped reader path",
            scope_fences.join(", ")
        )));
    }
    if capability_claim_present(&[
        request.category.as_str(),
        request.title.as_str(),
        request.summary.as_str(),
    ]) {
        let _ = provenance_text(provenance, "reader_reachable_path", 1)?;
    }
    Ok(())
}

fn is_parseable_datetime(value: &str) -> bool {
    if value.trim().is_empty() {
        return false;
    }
    // RFC3339 (covers Python's ISO-8601 output) or Postgres-style text.
    chrono::DateTime::parse_from_rfc3339(value).is_ok()
        || chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S%.f").is_ok()
        || chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S").is_ok()
        || chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S%.f").is_ok()
        || chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S").is_ok()
}

// ---------------------------------------------------------------------------
// Copy repair (mirrors comic_pile/release_copy.py)
// ---------------------------------------------------------------------------

struct CuratedRepair {
    original_title: &'static str,
    title: &'static str,
    summary: Option<&'static str>,
}

fn curated_repair(repository: &str, pr_number: Option<i32>) -> Option<CuratedRepair> {
    let pr = pr_number?;
    match (repository, pr) {
        ("JoshCLWren/comic-pile", 1881) => Some(CuratedRepair {
            original_title: "time on what\u{2019}s new",
            title: "Show relative and absolute timestamps on What's New",
            summary: Some(
                "The What's New page now shows when each release was published, using your local time zone.",
            ),
        }),
        ("JoshCLWren/comic-pile", 1889) => Some(CuratedRepair {
            original_title: "errors when changing themes",
            title: "Theme changes now save your preference",
            summary: Some(
                "Choosing a different theme now saves your preference instead of leaving the selection unsaved.",
            ),
        }),
        ("JoshCLWren/comic-pile", 2394) => Some(CuratedRepair {
            original_title: "Commit reviewed material into a Reading Plan",
            title: "Add reviewed material to an existing Reading Plan",
            summary: None,
        }),
        ("JoshCLWren/comic-pile", 2493) => Some(CuratedRepair {
            original_title: "Roling should not move the user to anywhere ont he screen",
            title: "Keep the Roll page at the cover art when reading boundaries load",
            summary: None,
        }),
        _ => None,
    }
}

fn strip_repeated_title(summary: &str, title: &str) -> String {
    let normalized_title = visible_release_text(title)
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .trim_matches(|c: char| " .:;,!?–—-".contains(c))
        .to_string();
    if normalized_title.is_empty() {
        return summary.to_string();
    }
    let pattern = format!(
        r"(?i)^{}(?:\s*[.:;,!?–—-]\s*|\s+)",
        regex::escape(&normalized_title)
    );
    let Ok(re) = Regex::new(&pattern) else {
        return summary.to_string();
    };
    if let Some(m) = re.find(summary) {
        if m.start() == 0 && !summary[m.end()..].trim().is_empty() {
            return summary[m.end()..].to_string();
        }
    }
    summary.to_string()
}

fn contains_artifact(text: &str) -> bool {
    if ticket_search(text).is_some() {
        return true;
    }
    if schema_ident().is_match(text) {
        return true;
    }
    if phase_term_copy().is_match(text) {
        return true;
    }
    if internal_path_search(text).is_some() {
        return true;
    }
    test_narrative().is_match(text)
}

fn ends_with_phase_terminology(text: &str) -> bool {
    let trimmed = text.trim_end_matches([' ', '\t', '.', ',', ';', ':', '!', '?']);
    if let Some(m) = phase_term_copy().find(trimmed) {
        return m.end() == trimmed.len();
    }
    false
}

fn only_reference_artifacts(text: &str) -> bool {
    !(schema_ident().is_match(text)
        || internal_path_search(text).is_some()
        || test_narrative().is_match(text))
}

fn remove_artifact_parentheticals(text: &str) -> String {
    parenthetical()
        .replace_all(text, |caps: &regex::Captures<'_>| match caps.get(0) {
            Some(full) if contains_artifact(full.as_str()) => String::new(),
            Some(full) => full.as_str().to_string(),
            None => String::new(),
        })
        .to_string()
}

fn remove_artifact_clauses(text: &str) -> String {
    artifact_clause()
        .replace_all(text, |caps: &regex::Captures<'_>| match caps.get(0) {
            Some(full) if contains_artifact(full.as_str()) => String::new(),
            Some(full) => full.as_str().to_string(),
            None => String::new(),
        })
        .to_string()
}

fn is_engineering_only(text: &str) -> bool {
    if reader_cue().is_match(text) {
        return false;
    }
    let mut terms = std::collections::HashSet::new();
    for m in engineering_only().find_iter(text) {
        terms.insert(m.as_str().to_lowercase());
    }
    terms.len() >= 2
}

fn clean_punctuation(text: &str) -> String {
    let mut cleaned = if let Ok(regex) = Regex::new(r"\(\s*\)|\[\s*\]|\{\s*\}") {
        regex.replace_all(text, "").to_string()
    } else {
        text.to_string()
    };
    cleaned = if let Ok(regex) = Regex::new(r"\s+([,.;:!?])") {
        regex.replace_all(&cleaned, "$1").to_string()
    } else {
        cleaned
    };
    cleaned = if let Ok(regex) = Regex::new(r"([,;:])(?:\s*[,;:])+") {
        regex.replace_all(&cleaned, "$1").to_string()
    } else {
        cleaned
    };
    // \.\s*\.(?![.]) -> "." unless the next character is "." (ellipsis).
    cleaned = fix_double_dots(&cleaned);
    cleaned = if let Ok(regex) = Regex::new(r"\s{2,}") {
        regex.replace_all(&cleaned, " ").to_string()
    } else {
        cleaned
    };
    cleaned.trim_matches([' ', '\t']).to_string()
}

fn fix_double_dots(text: &str) -> String {
    let Ok(re) = Regex::new(r"\.\s*\.") else {
        return text.to_string();
    };
    let mut out = String::with_capacity(text.len());
    let mut pos = 0;
    for m in re.find_iter(text) {
        let next = text[m.end()..].chars().next();
        if next == Some('.') {
            continue;
        }
        out.push_str(&text[pos..m.start()]);
        out.push('.');
        pos = m.end();
    }
    out.push_str(&text[pos..]);
    out
}

fn normalize_title(title: &str) -> String {
    let mut text = visible_release_text(title);
    text = phase_prefix().replace_all(&text, "").to_string();
    text = leading_sep().replace_all(&text, "").to_string();
    text = remove_artifact_parentheticals(&text);
    text = remove_tickets(&text);
    text = schema_ident().replace_all(&text, "").to_string();
    let after_path = remove_internal_paths(&text);
    let mut without_artifacts = phase_inline().replace_all(&after_path, "").to_string();
    if without_artifacts != text {
        without_artifacts = dangling_connective()
            .replace_all(&without_artifacts, "")
            .to_string();
    }
    let mut text = clean_punctuation(&without_artifacts);
    text = text
        .trim_matches([' ', '\t', ',', ';', ':', '-', '–', '—'])
        .to_string();
    if let Some(first) = text.chars().next() {
        if first.is_lowercase() {
            let head = first.to_uppercase().to_string();
            let rest: String = text.chars().skip(1).collect();
            text = head + &rest;
        }
    }
    if !word_char().is_match(&text) {
        return String::new();
    }
    text
}

fn split_sentences(text: &str) -> Vec<String> {
    // Mirrors re.split(r"(?<=[.!?])\s+", text): split on whitespace runs
    // whose preceding non-whitespace character is sentence punctuation.
    let chars: Vec<(usize, char)> = text.char_indices().collect();
    let mut sentences = Vec::new();
    let mut start = 0;
    let mut i = 0;
    while i < chars.len() {
        let (idx, ch) = chars[i];
        if ch.is_whitespace() {
            // Look back to the most recent non-whitespace character.
            let mut j = i;
            while j > 0 && chars[j - 1].1.is_whitespace() {
                // Unreachable: i is the first whitespace char of its run.
                j -= 1;
            }
            let prev = if i == 0 { None } else { Some(chars[i - 1].1) };
            if matches!(prev, Some('.' | '!' | '?')) {
                let mut k = i;
                while k < chars.len() && chars[k].1.is_whitespace() {
                    k += 1;
                }
                let end = if k < chars.len() {
                    chars[k].0
                } else {
                    text.len()
                };
                sentences.push(text[start..idx].to_string());
                start = end;
                i = k;
                continue;
            }
        }
        i += 1;
    }
    sentences.push(text[start..].to_string());
    sentences
}

fn repair_summary(summary: &str, title: &str) -> String {
    let mut text = visible_release_text(summary);
    text = strip_repeated_title(&text, title);
    text = remove_artifact_parentheticals(&text);
    text = remove_artifact_clauses(&text);

    let mut kept: Vec<String> = Vec::new();
    for sentence in split_sentences(&text) {
        let deduped = leading_sep().replace_all(&sentence, "").to_string();
        let cleaned = clean_punctuation(deduped.trim());
        if cleaned.is_empty() {
            continue;
        }
        if !word_char().is_match(&cleaned) {
            continue;
        }
        if dangling_head().is_match(&cleaned) {
            continue;
        }
        if contains_artifact(&cleaned) {
            if !only_reference_artifacts(&cleaned) {
                continue;
            }
            if ends_with_phase_terminology(&cleaned) {
                continue;
            }
            let after_ticket = remove_tickets(&cleaned);
            let after_phase = phase_inline().replace_all(&after_ticket, "").to_string();
            let cleaned = clean_punctuation(&after_phase);
            if cleaned.is_empty() {
                continue;
            }
            if !word_char().is_match(&cleaned) {
                continue;
            }
            if is_engineering_only(&cleaned) {
                continue;
            }
            kept.push(cleaned);
            continue;
        }
        if is_engineering_only(&cleaned) {
            continue;
        }
        kept.push(cleaned);
    }
    let result = kept.join(" ");
    if result == title {
        return String::new();
    }
    clean_punctuation(&result)
}

fn repair_release_copy(
    source_repository: &str,
    source_pr_number: Option<i32>,
    title: &str,
    summary: &str,
) -> (String, String) {
    if source_pr_number.is_none() {
        return (title.to_string(), summary.to_string());
    }
    if let Some(repair) = curated_repair(source_repository, source_pr_number) {
        if title.trim() == repair.original_title {
            let repaired_title = normalize_title(repair.title);
            let repaired_summary = match repair.summary {
                Some(summary) => summary.to_string(),
                None => repair_summary(summary, &repaired_title),
            };
            return (repaired_title, repaired_summary);
        }
    }
    let repaired_title = normalize_title(title);
    let repaired_summary = repair_summary(summary, &repaired_title);
    (repaired_title, repaired_summary)
}

// ---------------------------------------------------------------------------
// Row mapping
// ---------------------------------------------------------------------------

struct FullRelease {
    id: i32,
    source_repository: String,
    source_pr_number: Option<i32>,
    source_merge_sha: Option<String>,
    merged_at: Option<String>,
    released_at: String,
    category: String,
    title: String,
    summary: String,
    body: Option<String>,
    visibility: String,
    status: String,
    sort_order: i32,
    provenance_json: Value,
    created_at: String,
    updated_at: String,
}

struct MinimalRelease {
    id: i32,
    source_repository: String,
    source_pr_number: Option<i32>,
    source_merge_sha: Option<String>,
    merged_at: Option<String>,
    released_at: String,
    category: String,
    title: String,
    summary: String,
    visibility: String,
    status: String,
    sort_order: i32,
    provenance_json: Value,
    created_at: String,
    updated_at: String,
}

fn provenance_from_row(row: &Row, column: &str) -> Value {
    let text: Option<String> = row.try_get(column).ok();
    match text {
        Some(raw) => serde_json::from_str(&raw).unwrap_or(json!({})),
        None => json!({}),
    }
}

fn full_from_row(row: &Row) -> FullRelease {
    FullRelease {
        id: row.get("id"),
        source_repository: row.get("source_repository"),
        source_pr_number: row.get("source_pr_number"),
        source_merge_sha: row.get("source_merge_sha"),
        merged_at: row.get("merged_at"),
        released_at: row.get("released_at"),
        category: row.get("category"),
        title: row.get("title"),
        summary: row.get("summary"),
        body: row.get("body"),
        visibility: row.get("visibility"),
        status: row.get("status"),
        sort_order: row.get("sort_order"),
        provenance_json: provenance_from_row(row, "provenance_json"),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
    }
}

fn minimal_from_row(row: &Row) -> MinimalRelease {
    MinimalRelease {
        id: row.get("id"),
        source_repository: row.get("source_repository"),
        source_pr_number: row.get("source_pr_number"),
        source_merge_sha: row.get("source_merge_sha"),
        merged_at: row.get("merged_at"),
        released_at: row.get("released_at"),
        category: row.get("category"),
        title: row.get("title"),
        summary: row.get("summary"),
        visibility: row.get("visibility"),
        status: row.get("status"),
        sort_order: row.get("sort_order"),
        provenance_json: provenance_from_row(row, "provenance_json"),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
    }
}

fn public_from_full(release: &FullRelease) -> PublicReleaseResponse {
    let (repaired_title, repaired_summary) = repair_release_copy(
        &release.source_repository,
        release.source_pr_number,
        &release.title,
        &release.summary,
    );
    PublicReleaseResponse {
        id: release.id,
        released_at: release.released_at.clone(),
        category: decode_release_escapes(&release.category),
        title: decode_release_escapes(&repaired_title),
        summary: decode_release_escapes(&repaired_summary),
        body: release
            .body
            .as_ref()
            .map(|body| decode_release_escapes(body)),
        sort_order: release.sort_order,
        created_at: release.created_at.clone(),
        updated_at: release.updated_at.clone(),
    }
}

fn full_response(release: &FullRelease) -> ReleaseResponse {
    ReleaseResponse {
        id: release.id,
        source_repository: release.source_repository.clone(),
        source_pr_number: release.source_pr_number,
        source_merge_sha: release.source_merge_sha.clone(),
        merged_at: release.merged_at.clone(),
        released_at: release.released_at.clone(),
        category: decode_release_escapes(&release.category),
        title: decode_release_escapes(&release.title),
        summary: decode_release_escapes(&release.summary),
        body: release
            .body
            .as_ref()
            .map(|body| decode_release_escapes(body)),
        visibility: release.visibility.clone(),
        status: release.status.clone(),
        sort_order: release.sort_order,
        provenance_json: release.provenance_json.clone(),
        created_at: release.created_at.clone(),
        updated_at: release.updated_at.clone(),
    }
}

fn minimal_response(release: &MinimalRelease) -> MinimalReleaseResponse {
    MinimalReleaseResponse {
        id: release.id,
        source_repository: release.source_repository.clone(),
        source_pr_number: release.source_pr_number,
        source_merge_sha: release.source_merge_sha.clone(),
        merged_at: release.merged_at.clone(),
        released_at: release.released_at.clone(),
        category: decode_release_escapes(&release.category),
        title: decode_release_escapes(&release.title),
        summary: decode_release_escapes(&release.summary),
        visibility: release.visibility.clone(),
        status: release.status.clone(),
        sort_order: release.sort_order,
        provenance_json: release.provenance_json.clone(),
        created_at: release.created_at.clone(),
        updated_at: release.updated_at.clone(),
    }
}

// ---------------------------------------------------------------------------
// Query parameter parsing (manual so failures are 422, not Axum 400)
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize, Default)]
pub struct ListQuery {
    limit: Option<String>,
    offset: Option<String>,
}

#[derive(Debug, Deserialize, Default)]
pub struct SourceQuery {
    source_repository: Option<String>,
    source_pr_number: Option<String>,
    source_merge_sha: Option<String>,
}

fn parse_limit(value: Option<&str>) -> Result<i32, ApiError> {
    match value {
        None => Ok(20),
        Some(raw) => {
            let parsed: i32 = raw.parse().map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                unprocessable("limit must be an integer")
            })?;
            if !(1..=100).contains(&parsed) {
                return Err(unprocessable("limit must be between 1 and 100"));
            }
            Ok(parsed)
        }
    }
}

fn parse_offset(value: Option<&str>) -> Result<i32, ApiError> {
    match value {
        None => Ok(0),
        Some(raw) => {
            let parsed: i32 = raw.parse().map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                unprocessable("offset must be an integer")
            })?;
            if parsed < 0 {
                return Err(unprocessable("offset must be at least 0"));
            }
            Ok(parsed)
        }
    }
}

fn parse_source_pr(value: Option<&str>) -> Result<Option<i32>, ApiError> {
    match value {
        None => Ok(None),
        Some(raw) => {
            let parsed: i32 = raw.parse().map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                unprocessable("source_pr_number must be an integer")
            })?;
            if parsed < 1 {
                return Err(unprocessable("source_pr_number must be at least 1"));
            }
            Ok(Some(parsed))
        }
    }
}

// ---------------------------------------------------------------------------
// SQL helpers
// ---------------------------------------------------------------------------

const PUBLIC_FILTER: &str = "status = 'published' AND visibility = 'public' AND title <> summary";

async fn list_published(
    state: &AppState,
    limit: i32,
    offset: i32,
) -> Result<(Vec<FullRelease>, i64), ApiError> {
    let conn = db::checkout(state).await?;
    let total_row = conn
        .query_one(
            &format!("SELECT count(*)::bigint FROM releases WHERE {PUBLIC_FILTER}"),
            &[],
        )
        .await
        .map_err(db::query_error)?;
    let total: i64 = total_row.get(0);
    let (limit, offset) = (i64::from(limit), i64::from(offset));
    let rows = conn
        .query(
            &format!(
                "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, body, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE {PUBLIC_FILTER} ORDER BY released_at DESC, sort_order DESC, id DESC OFFSET $1 LIMIT $2"
            ),
            &[&offset, &limit],
        )
        .await
        .map_err(db::query_error)?;
    Ok((rows.iter().map(full_from_row).collect(), total))
}

async fn get_published(state: &AppState, release_id: i32) -> Result<Option<FullRelease>, ApiError> {
    let conn = db::checkout(state).await?;
    let row = conn
        .query_opt(
            &format!(
                "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, body, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE id = $1 AND {PUBLIC_FILTER}"
            ),
            &[&release_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(row.map(|row| full_from_row(&row)))
}

async fn find_minimal_by_source(
    state: &AppState,
    source_repository: &str,
    source_pr_number: Option<i32>,
    source_merge_sha: Option<&str>,
) -> Result<Vec<MinimalRelease>, ApiError> {
    let conn = db::checkout(state).await?;
    let sql = match (source_pr_number, source_merge_sha) {
        (Some(_), Some(_)) => "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE source_repository = $1 AND (source_pr_number = $2 OR source_merge_sha = $3)",
        (Some(_), None) => "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE source_repository = $1 AND source_pr_number = $2",
        (None, Some(_)) => "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE source_repository = $1 AND source_merge_sha = $2",
        (None, None) => return Ok(Vec::new()),
    };
    let rows = match (source_pr_number, source_merge_sha) {
        (Some(pr), Some(sha)) => conn
            .query(sql, &[&source_repository, &pr, &sha.to_string()])
            .await
            .map_err(db::query_error)?,
        (Some(pr), None) => conn
            .query(sql, &[&source_repository, &pr])
            .await
            .map_err(db::query_error)?,
        (None, Some(sha)) => conn
            .query(sql, &[&source_repository, &sha.to_string()])
            .await
            .map_err(db::query_error)?,
        (None, None) => Vec::new(),
    };
    Ok(rows.iter().map(minimal_from_row).collect())
}

async fn find_full_by_source(
    state: &AppState,
    source_repository: &str,
    source_pr_number: Option<i32>,
    source_merge_sha: Option<&str>,
) -> Result<Vec<FullRelease>, ApiError> {
    let conn = db::checkout(state).await?;
    let sql = match (source_pr_number, source_merge_sha) {
        (Some(_), Some(_)) => "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, body, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE source_repository = $1 AND (source_pr_number = $2 OR source_merge_sha = $3)",
        (Some(_), None) => "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, body, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE source_repository = $1 AND source_pr_number = $2",
        (None, Some(_)) => "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, body, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE source_repository = $1 AND source_merge_sha = $2",
        (None, None) => return Ok(Vec::new()),
    };
    let rows = match (source_pr_number, source_merge_sha) {
        (Some(pr), Some(sha)) => conn
            .query(sql, &[&source_repository, &pr, &sha.to_string()])
            .await
            .map_err(db::query_error)?,
        (Some(pr), None) => conn
            .query(sql, &[&source_repository, &pr])
            .await
            .map_err(db::query_error)?,
        (None, Some(sha)) => conn
            .query(sql, &[&source_repository, &sha.to_string()])
            .await
            .map_err(db::query_error)?,
        (None, None) => Vec::new(),
    };
    Ok(rows.iter().map(full_from_row).collect())
}

fn is_unique_violation(error: &tokio_postgres::Error) -> bool {
    error
        .as_db_error()
        .is_some_and(|e| e.code().code() == "23505")
}

fn apply_payload_assert(
    existing_pr: Option<i32>,
    existing_sha: Option<&str>,
    payload: &ReleaseUpsertRequest,
) -> Result<(), ApiError> {
    if let (Some(existing), Some(intended)) = (existing_pr, payload.source_pr_number) {
        if existing != intended {
            return Err(conflict(
                "merge SHA is already attached to another source PR",
            ));
        }
    }
    if let (Some(existing), Some(intended)) = (existing_sha, payload.source_merge_sha.as_deref()) {
        if existing != intended {
            return Err(conflict(
                "source PR is already attached to another merge SHA",
            ));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

pub async fn list(
    State(state): State<Arc<AppState>>,
    Query(query): Query<ListQuery>,
) -> Result<Json<ReleaseListResponse>, ApiError> {
    let limit = parse_limit(query.limit.as_deref())?;
    let offset = parse_offset(query.offset.as_deref())?;
    let (releases, total) = list_published(&state, limit, offset).await?;
    Ok(Json(ReleaseListResponse {
        releases: releases.iter().map(public_from_full).collect(),
        total,
        limit,
        offset,
    }))
}

pub async fn get(
    State(state): State<Arc<AppState>>,
    Path(release_id): Path<i32>,
) -> Result<Json<PublicReleaseResponse>, ApiError> {
    let release = get_published(&state, release_id)
        .await?
        .ok_or_else(|| not_found("Release not found"))?;
    Ok(Json(public_from_full(&release)))
}

pub async fn reconcile(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(query): Query<SourceQuery>,
) -> Result<Json<ReleaseSourceResponse>, ApiError> {
    check_writer_from_headers(&headers)?;
    let repository = query.source_repository.as_deref().unwrap_or("").to_string();
    if repository.is_empty() || repository.chars().count() > 255 {
        return Err(unprocessable(
            "source_repository must be between 1 and 255 characters",
        ));
    }
    if let Some(sha) = query.source_merge_sha.as_deref() {
        if sha.chars().count() < 7 || sha.chars().count() > 64 {
            return Err(unprocessable(
                "source_merge_sha must be between 7 and 64 characters",
            ));
        }
    }
    let pr_number = parse_source_pr(query.source_pr_number.as_deref())?;
    let sha = query.source_merge_sha.clone();
    if pr_number.is_none() && sha.is_none() {
        return Err(unprocessable(
            "source_pr_number or source_merge_sha is required",
        ));
    }
    let matches = find_minimal_by_source(&state, &repository, pr_number, sha.as_deref()).await?;
    if matches.len() > 1 {
        return Err(conflict(
            "source PR and merge SHA already identify different release records",
        ));
    }
    Ok(Json(match matches.first() {
        Some(release) => ReleaseSourceResponse {
            exists: true,
            release: Some(minimal_response(release)),
        },
        None => ReleaseSourceResponse {
            exists: false,
            release: None,
        },
    }))
}

async fn upsert_once(
    state: &AppState,
    payload: &ReleaseUpsertRequest,
    allow_insert_retry_lookup: bool,
) -> Result<FullRelease, ApiError> {
    let _ = allow_insert_retry_lookup;
    let mut conn = db::checkout(state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    // Identity lookup inside the transaction window.
    let lookup_sql = match (payload.source_pr_number, payload.source_merge_sha.as_deref()) {
        (Some(_), Some(_)) => "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, body, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE source_repository = $1 AND (source_pr_number = $2 OR source_merge_sha = $3)",
        (Some(_), None) => "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, body, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE source_repository = $1 AND source_pr_number = $2",
        (None, Some(_)) => "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, body, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE source_repository = $1 AND source_merge_sha = $2",
        (None, None) => return Err(unprocessable(
            "source_pr_number or source_merge_sha is required",
        )),
    };
    let found: Vec<Row> = match (
        payload.source_pr_number,
        payload.source_merge_sha.as_deref(),
    ) {
        (Some(pr), Some(sha)) => tx
            .query(
                lookup_sql,
                &[&payload.source_repository, &pr, &sha.to_string()],
            )
            .await
            .map_err(db::query_error)?,
        (Some(pr), None) => tx
            .query(lookup_sql, &[&payload.source_repository, &pr])
            .await
            .map_err(db::query_error)?,
        (None, Some(sha)) => tx
            .query(lookup_sql, &[&payload.source_repository, &sha.to_string()])
            .await
            .map_err(db::query_error)?,
        (None, None) => Vec::new(),
    };
    if found.len() > 1 {
        let _ = tx.rollback().await;
        return Err(conflict(
            "source PR and merge SHA already identify different release records",
        ));
    }
    let provenance_text = payload.provenance_json.to_string();
    if let Some(row) = found.first() {
        let existing = full_from_row(row);
        if let Err(error) = apply_payload_assert(
            existing.source_pr_number,
            existing.source_merge_sha.as_deref(),
            payload,
        ) {
            let _ = tx.rollback().await;
            return Err(error);
        }
        // _apply_payload skips None PR/SHA; every other field overwrites.
        // Merged-at/released-at are supplied as text cast to timestamptz.
        tx.execute(
            "UPDATE releases SET source_repository = $1, source_pr_number = COALESCE($2, source_pr_number), source_merge_sha = COALESCE($3, source_merge_sha), merged_at = $4::text::timestamptz, released_at = $5::text::timestamptz, category = $6, title = $7, summary = $8, body = $9, visibility = $10, status = $11, sort_order = $12, provenance_json = $13::text::json, updated_at = NOW() WHERE id = $14",
            &[
                &payload.source_repository,
                &payload.source_pr_number,
                &payload.source_merge_sha,
                &payload.merged_at,
                &payload.released_at,
                &payload.category,
                &payload.title,
                &payload.summary,
                &payload.body,
                &payload.visibility,
                &payload.status,
                &payload.sort_order,
                &provenance_text,
                &existing.id,
            ],
        )
        .await
        .map_err(db::query_error)?;
        let updated = tx
            .query_one(
                "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, body, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE id = $1",
                &[&existing.id],
            )
            .await
            .map_err(db::query_error)?;
        let result = full_from_row(&updated);
        tx.commit().await.map_err(db::query_error)?;
        return Ok(result);
    }
    // No post-commit refresh semantics for inserts: RETURNING keeps one
    // round trip and avoids re-transferring the large body column.
    let inserted = match tx
        .query_one(
            "INSERT INTO releases (source_repository, source_pr_number, source_merge_sha, merged_at, released_at, category, title, summary, body, visibility, status, sort_order, provenance_json, created_at, updated_at) VALUES ($1,$2,$3,$4::text::timestamptz,$5::text::timestamptz,$6,$7,$8,$9,$10,$11,$12,$13::text::json,NOW(),NOW()) RETURNING id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, body, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at",
            &[
                &payload.source_repository,
                &payload.source_pr_number,
                &payload.source_merge_sha,
                &payload.merged_at,
                &payload.released_at,
                &payload.category,
                &payload.title,
                &payload.summary,
                &payload.body,
                &payload.visibility,
                &payload.status,
                &payload.sort_order,
                &provenance_text,
            ],
        )
        .await
    {
        Ok(row) => row,
        Err(error) if is_unique_violation(&error) => {
            let _ = tx.rollback().await;
            return Err(ApiError::UniqueViolation);
        }
        Err(error) => {
            let _ = tx.rollback().await;
            return Err(db::query_error(error));
        }
    };
    let result = full_from_row(&inserted);
    tx.commit().await.map_err(db::query_error)?;
    Ok(result)
}

pub async fn publish(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut payload): Json<ReleaseUpsertRequest>,
) -> Result<Json<ReleaseResponse>, ApiError> {
    decode_upsert(&mut payload);
    validate_upsert_request(&payload)?;
    check_writer_from_headers(&headers)?;
    match upsert_once(&state, &payload, false).await {
        Ok(release) => Ok(Json(full_response(&release))),
        Err(error) if error.is_unique_violation() => {
            // Concurrent duplicate retry: re-resolve identity and apply.
            let matches = find_full_by_source(
                &state,
                &payload.source_repository,
                payload.source_pr_number,
                payload.source_merge_sha.as_deref(),
            )
            .await?;
            let Some(existing) = matches.first() else {
                return Err(ApiError::with_status(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "Internal Server Error".to_string(),
                ));
            };
            if matches.len() > 1 {
                return Err(conflict(
                    "source PR and merge SHA already identify different release records",
                ));
            }
            apply_payload_assert(
                existing.source_pr_number,
                existing.source_merge_sha.as_deref(),
                &payload,
            )?;
            let mut conn = db::checkout(&state).await?;
            let tx = conn
                .build_transaction()
                .start()
                .await
                .map_err(db::query_error)?;
            let provenance_text = payload.provenance_json.to_string();
            tx.execute(
                "UPDATE releases SET source_repository = $1, source_pr_number = COALESCE($2, source_pr_number), source_merge_sha = COALESCE($3, source_merge_sha), merged_at = $4::text::timestamptz, released_at = $5::text::timestamptz, category = $6, title = $7, summary = $8, body = $9, visibility = $10, status = $11, sort_order = $12, provenance_json = $13::text::json, updated_at = NOW() WHERE id = $14",
                &[
                    &payload.source_repository,
                    &payload.source_pr_number,
                    &payload.source_merge_sha,
                    &payload.merged_at,
                    &payload.released_at,
                    &payload.category,
                    &payload.title,
                    &payload.summary,
                    &payload.body,
                    &payload.visibility,
                    &payload.status,
                    &payload.sort_order,
                    &provenance_text,
                    &existing.id,
                ],
            )
            .await
            .map_err(db::query_error)?;
            let updated = tx
                .query_one(
                    "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, body, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE id = $1",
                    &[&existing.id],
                )
                .await
                .map_err(db::query_error)?;
            let result = full_from_row(&updated);
            tx.commit().await.map_err(db::query_error)?;
            Ok(Json(full_response(&result)))
        }
        Err(error) => Err(error),
    }
}

pub async fn retract(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Path(release_id): Path<i32>,
) -> Result<Json<ReleaseResponse>, ApiError> {
    check_writer_from_headers(&headers)?;
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    let existing = tx
        .query_opt(
            "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, body, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE id = $1 AND status = 'published'",
            &[&release_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(_row) = existing else {
        let _ = tx.rollback().await;
        return Err(not_found("Release not found"));
    };
    tx.execute(
        "UPDATE releases SET status = 'retracted', updated_at = NOW() WHERE id = $1",
        &[&release_id],
    )
    .await
    .map_err(db::query_error)?;
    let updated = tx
        .query_one(
            "SELECT id, source_repository, source_pr_number, source_merge_sha, merged_at::text AS merged_at, released_at::text AS released_at, category, title, summary, body, visibility, status, sort_order, provenance_json::text AS provenance_json, created_at::text AS created_at, updated_at::text AS updated_at FROM releases WHERE id = $1",
            &[&release_id],
        )
        .await
        .map_err(db::query_error)?;
    let result = full_from_row(&updated);
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(full_response(&result)))
}

// ---------------------------------------------------------------------------
// Documentation-only operations (canonical OpenAPI)
// ---------------------------------------------------------------------------

/// Documentation-only operation for the mounted releases list handler.
#[utoipa::path(get, path = "/api/v1/releases/", tag = "releases", operation_id = "releases_list", params(("limit" = Option<i32>, Query, description = "Maximum releases to return (1-100, default 20)"), ("offset" = Option<i32>, Query, description = "Number of matching releases to skip (default 0)")), responses((status = 200, body = ReleaseListResponse), (status = 422, description = "Invalid pagination")))]
#[allow(dead_code)]
pub fn list_documentation() {}

/// Documentation-only operation for the mounted releases get handler.
#[utoipa::path(get, path = "/api/v1/releases/{release_id}", tag = "releases", operation_id = "releases_get", params(("release_id" = i32, Path)), responses((status = 200, body = PublicReleaseResponse), (status = 404, description = "Release not found")))]
#[allow(dead_code)]
pub fn get_documentation() {}

/// Documentation-only operation for the mounted releases source handler.
#[utoipa::path(get, path = "/api/v1/releases/source", tag = "releases", operation_id = "releases_reconcile", params(("source_repository" = String, Query), ("source_pr_number" = Option<i32>, Query), ("source_merge_sha" = Option<String>, Query), ("x-release-writer-token" = String, Header, description = "Server-only release-writer credential")), responses((status = 200, body = ReleaseSourceResponse), (status = 401, description = "Invalid release writer credential"), (status = 409, description = "Source identities identify different records"), (status = 422, description = "Missing source identity or invalid query"), (status = 503, description = "Release writer authorization is not configured")))]
#[allow(dead_code)]
pub fn reconcile_documentation() {}

/// Documentation-only operation for the mounted releases publish handler.
#[utoipa::path(put, path = "/api/v1/releases/", tag = "releases", operation_id = "releases_publish", params(("x-release-writer-token" = String, Header, description = "Server-only release-writer credential")), request_body = ReleaseUpsertRequest, responses((status = 200, body = ReleaseResponse), (status = 401, description = "Invalid release writer credential"), (status = 409, description = "Source identities conflict"), (status = 422, description = "Request payload failed validation"), (status = 503, description = "Release writer authorization is not configured")))]
#[allow(dead_code)]
pub fn publish_documentation() {}

/// Documentation-only operation for the mounted releases retract handler.
#[utoipa::path(post, path = "/api/v1/releases/{release_id}/retract", tag = "releases", operation_id = "releases_retract", params(("release_id" = i32, Path), ("x-release-writer-token" = String, Header, description = "Server-only release-writer credential")), responses((status = 200, body = ReleaseResponse), (status = 401, description = "Invalid release writer credential"), (status = 404, description = "Release not found"), (status = 503, description = "Release writer authorization is not configured")))]
#[allow(dead_code)]
pub fn retract_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{db, test_support};

    fn public_provenance() -> Value {
        json!({
            "classification": "public",
            "classification_reason": "Queue page behavior changed for every reader.",
            "user_visible_evidence": "frontend/src/pages/QueuePage.tsx now shows a saved-search filter.",
            "reader_reachable": true,
            "inspected_issue_numbers": [1070],
            "scope_fences": [],
            "contradicting_evidence": [],
            "reader_reachable_path": "Queue page at /queue",
        })
    }

    fn valid_payload(pr_number: i32, merge_sha: &str) -> ReleaseUpsertRequest {
        ReleaseUpsertRequest {
            source_repository: "JoshCLWren/comic-pile".to_string(),
            source_pr_number: Some(pr_number),
            source_merge_sha: Some(merge_sha.to_string()),
            merged_at: Some("2026-01-01T00:00:00Z".to_string()),
            released_at: "2026-01-01T00:00:00Z".to_string(),
            category: "What's New".to_string(),
            title: format!("Release {pr_number}"),
            summary: "A user-facing release summary".to_string(),
            body: Some("More release detail".to_string()),
            visibility: "public".to_string(),
            status: "published".to_string(),
            sort_order: 0,
            provenance_json: public_provenance(),
        }
    }

    async fn database_fixture() -> (Arc<AppState>, tokio::sync::MutexGuard<'static, ()>) {
        let state = test_support::test_state(2)
            .await
            .expect("RUST_ROLL_TEST_DATABASE_URL is required");
        let guard = test_support::reset_for_test(&state).await;
        (state, guard)
    }

    /// Serialize process-global writer-token access alongside the DB lock.
    fn set_writer_token(token: Option<&str>) {
        match token {
            Some(value) => std::env::set_var("RELEASE_WRITER_TOKEN", value),
            None => std::env::remove_var("RELEASE_WRITER_TOKEN"),
        }
    }

    fn writer_headers() -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(
            "x-release-writer-token",
            "writer-secret".parse().expect("writer token header"),
        );
        headers
    }

    fn empty_headers() -> HeaderMap {
        HeaderMap::new()
    }

    #[test]
    fn writer_token_requires_configuration_then_credential() {
        assert_eq!(
            check_writer_token(Some("writer-secret"), "")
                .unwrap_err()
                .status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
        assert_eq!(
            check_writer_token(None, "writer-secret")
                .unwrap_err()
                .status(),
            StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            check_writer_token(Some("wrong"), "writer-secret")
                .unwrap_err()
                .status(),
            StatusCode::UNAUTHORIZED
        );
        assert!(check_writer_token(Some("writer-secret"), "writer-secret").is_ok());
    }

    #[test]
    fn escape_decoding_matches_python() {
        assert_eq!(
            decode_release_escapes(r"GitHub links added to What\u0027s New page"),
            "GitHub links added to What's New page"
        );
        assert_eq!(
            decode_release_escapes(r"The Roll page\'s rating view"),
            "The Roll page's rating view"
        );
    }

    #[test]
    fn repair_matches_python_title_cases() {
        for (stored, expected) in [
            (
                ": add occasional ComicPile-noticed taste discovery card",
                "Add occasional ComicPile-noticed taste discovery card",
            ),
            (
                "Phase 2: capture the reader timezone on reading sessions",
                "Capture the reader timezone on reading sessions",
            ),
            ("Fix source_roll_event_id tracking", "Fix tracking"),
            (
                "Added `source_roll_event_id` instrumentation detail",
                "Added instrumentation detail",
            ),
            ("A new service in app/services/queue.py", "A new service"),
            ("...", ""),
        ] {
            let (title, _) = repair_release_copy(
                "JoshCLWren/comic-pile",
                Some(9101),
                stored,
                "A complete reader-facing summary for this release.",
            );
            assert_eq!(title, expected, "stored={stored}");
        }
    }

    #[test]
    fn repair_summary_matches_python_cases() {
        assert_eq!(
            repair_summary(
                "of the recommendation-selection refactor introduces app/services/recommendation_selection.py, preserving exact candidate-pool boundaries",
                "Preserve exact legacy selection"
            ),
            ""
        );
        assert_eq!(
            repair_summary(
                "A new service in app/services/queue.py keeps your place. Reopening a comic resumes on the page you left.",
                "Queue keeps your place"
            ),
            "Reopening a comic resumes on the page you left."
        );
        assert_eq!(
            repair_summary(
                "Roll recovery now resumes interrupted sessions (#1886).",
                "Roll recovery now resumes interrupted sessions"
            ),
            ""
        );
        assert_eq!(
            repair_summary("The rollout reached phase 2.", "Rollout status"),
            ""
        );
        assert_eq!(
            repair_summary(
                "The API now supports importing a saved reading list.",
                "Improve imports"
            ),
            "The API now supports importing a saved reading list."
        );
        assert_eq!(
            repair_summary(
                "Refactor the repository layout and migrate the schema. Your saved filters now survive a reload.",
                "Saved filters survive reloads"
            ),
            "Your saved filters now survive a reload."
        );
    }

    #[test]
    fn curated_repairs_match_python() {
        for (pr, stored, expected) in [
            (
                1881,
                "time on what\u{2019}s new",
                "Show relative and absolute timestamps on What's New",
            ),
            (
                1889,
                "errors when changing themes",
                "Theme changes now save your preference",
            ),
            (
                2394,
                "Commit reviewed material into a Reading Plan",
                "Add reviewed material to an existing Reading Plan",
            ),
            (
                2493,
                "Roling should not move the user to anywhere ont he screen",
                "Keep the Roll page at the cover art when reading boundaries load",
            ),
        ] {
            let (title, summary) = repair_release_copy(
                "JoshCLWren/comic-pile",
                Some(pr),
                stored,
                "Historical stored summary for this release.",
            );
            assert_eq!(title, expected);
            assert!(!summary.is_empty());
        }
    }

    #[test]
    fn validation_mirrors_python_gates() {
        let mut payload = valid_payload(1201, &"a".repeat(40));
        assert!(validate_upsert_request(&payload).is_ok());

        payload.title = "T".to_string();
        let error = validate_upsert_request(&payload).unwrap_err();
        assert_eq!(error.status(), StatusCode::UNPROCESSABLE_ENTITY);
        assert!(error.detail().contains("title must contain meaningful"));

        payload = valid_payload(1213, &"7".repeat(40));
        payload.title = "incomplete #1551 fix for roll recovery".to_string();
        assert_eq!(
            validate_upsert_request(&payload).unwrap_err().status(),
            StatusCode::UNPROCESSABLE_ENTITY
        );

        payload = valid_payload(1220, &"5".repeat(40));
        payload.provenance_json = json!({"source": "github"});
        assert!(validate_upsert_request(&payload)
            .unwrap_err()
            .detail()
            .contains("provenance_json.classification"));
    }

    #[tokio::test]
    async fn publish_upsert_reconcile_retract_round_trip() {
        let (state, _guard) = database_fixture().await;
        set_writer_token(Some("writer-secret"));
        let payload = valid_payload(1202, &"b".repeat(40));

        let Json(first) = publish(
            State(state.clone()),
            writer_headers(),
            Json(payload.clone()),
        )
        .await
        .expect("publish creates the ledger row");
        assert_eq!(first.source_pr_number, Some(1202));

        let mut updated_payload = payload.clone();
        updated_payload.summary = "Updated release summary".to_string();
        let Json(retry) = publish(
            State(state.clone()),
            writer_headers(),
            Json(updated_payload),
        )
        .await
        .expect("publish retries idempotently");
        assert_eq!(retry.id, first.id);
        assert_eq!(retry.summary, "Updated release summary");

        // Source reconciliation resolves the same identity without body.
        let Json(reconciled) = reconcile(
            State(state.clone()),
            writer_headers(),
            Query(SourceQuery {
                source_repository: Some("JoshCLWren/comic-pile".to_string()),
                source_pr_number: Some("1202".to_string()),
                source_merge_sha: None,
            }),
        )
        .await
        .expect("source reconciles");
        assert!(reconciled.exists);
        assert_eq!(reconciled.release.expect("release").id, first.id);

        // Public list/get serve the repaired projection.
        let Json(listed) = list(
            State(state.clone()),
            Query(ListQuery {
                limit: None,
                offset: None,
            }),
        )
        .await
        .expect("list serves");
        assert!(listed.releases.iter().any(|item| item.id == first.id));

        let Json(fetched) = get(State(state.clone()), Path(first.id))
            .await
            .expect("get serves");
        assert_eq!(fetched.id, first.id);

        // Retraction removes it from the public ledger.
        let Json(retracted) = retract(State(state.clone()), writer_headers(), Path(first.id))
            .await
            .expect("retract succeeds");
        assert_eq!(retracted.status, "retracted");
        let fetched_after = get(State(state.clone()), Path(first.id)).await;
        assert_eq!(fetched_after.unwrap_err().status(), StatusCode::NOT_FOUND);

        let missing = retract(State(state.clone()), writer_headers(), Path(999999))
            .await
            .unwrap_err();
        assert_eq!(missing.status(), StatusCode::NOT_FOUND);

        set_writer_token(None);
    }

    #[tokio::test]
    async fn publish_rejects_unauthorized_writers_and_conflicts() {
        let (state, _guard) = database_fixture().await;
        set_writer_token(Some("writer-secret"));
        let payload = valid_payload(1203, &"c".repeat(40));

        let rejected = publish(State(state.clone()), empty_headers(), Json(payload.clone()))
            .await
            .unwrap_err();
        assert_eq!(rejected.status(), StatusCode::UNAUTHORIZED);

        let Json(_) = publish(
            State(state.clone()),
            writer_headers(),
            Json(payload.clone()),
        )
        .await
        .expect("first publish");

        let conflicting = valid_payload(1204, &"c".repeat(40));
        let conflict_error = publish(State(state.clone()), writer_headers(), Json(conflicting))
            .await
            .unwrap_err();
        assert_eq!(conflict_error.status(), StatusCode::CONFLICT);

        set_writer_token(None);
    }

    #[tokio::test]
    async fn public_read_hides_title_equals_summary_but_retract_still_works() {
        let (state, _guard) = database_fixture().await;
        set_writer_token(Some("writer-secret"));
        let mut payload = valid_payload(1303, &"c".repeat(40));
        payload.title = "makes issue and pull-request".to_string();
        payload.summary = "makes issue and pull-request".to_string();
        payload.category = "ROLL RECOVERY".to_string();

        let Json(created) = publish(State(state.clone()), writer_headers(), Json(payload))
            .await
            .expect("hidden row publishes");
        let fetched = get(State(state.clone()), Path(created.id)).await;
        assert_eq!(fetched.unwrap_err().status(), StatusCode::NOT_FOUND);

        let Json(retracted) = retract(State(state.clone()), writer_headers(), Path(created.id))
            .await
            .expect("hidden row retracts");
        assert_eq!(retracted.status, "retracted");

        set_writer_token(None);
    }

    #[tokio::test]
    async fn public_list_repairs_historical_copy_without_mutating_rows() {
        let (state, _guard) = database_fixture().await;
        let connection = db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                "INSERT INTO releases (source_repository, source_pr_number, released_at, category, title, summary, visibility, status, sort_order, provenance_json, created_at, updated_at) VALUES ('JoshCLWren/comic-pile', 9201, NOW(), 'What''s New', ': add occasional ComicPile-noticed taste discovery card', 'A new service in app/services/queue.py keeps your place.', 'public', 'published', 0, '{}'::json, NOW(), NOW())",
            )
            .await
            .expect("seed repair fixture");
        drop(connection);

        let Json(listed) = list(
            State(state.clone()),
            Query(ListQuery {
                limit: Some("100".to_string()),
                offset: Some("0".to_string()),
            }),
        )
        .await
        .expect("list repairs");
        let item = listed
            .releases
            .iter()
            .find(|item| item.title == "Add occasional ComicPile-noticed taste discovery card")
            .expect("repaired title is served");
        assert!(!item.summary.contains("app/services"));

        set_writer_token(None);
    }
}
