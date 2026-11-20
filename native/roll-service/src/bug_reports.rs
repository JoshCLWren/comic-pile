//! Same-path Rust cutover for the bug-report family (#4852, parent #4335).
//!
//! Serves the retired Python `app/api/bug_report.py` wire contract at the
//! same HTTP methods and exact paths (`POST /api/bug-reports/` and
//! `POST /api/v1/bug-reports/`); only the implementation moved from Python
//! FastAPI to the native Roll binary (Python handler deleted in #5162). No
//! frontend URL changes.
//!
//! Parity with the retired Python oracle (`app/api/bug_report.py` +
//! `app/services/github_issue_rate_limit.py`, since removed; the shared
//! `app/services/github_service.py` remains for performance issues):
//!
//! * Request `BugReportCreate` (`report_type` default `"bug"`, `title`
//!   1..=200 chars, `description` 1..=2000 chars, optional `diagnostics`
//!   with camelCase aliases `userAgent`/`pixelRatio`/`domContentLoaded`/
//!   `loadComplete`) is validated before any configuration or database work.
//!   Pydantic-level failures (malformed JSON, missing fields, wrong types and
//!   length limits) return the FastAPI `{"detail": [ ... ]}` 422 shape, while
//!   whitespace-only title/description after stripping keeps the handler's
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

use crate::{
    auth::AuthenticatedUser,
    db,
    outbound::{OutboundError, OutboundHttp, OutboundRequest},
    ApiError, AppState,
};
use axum::{
    body::Bytes,
    extract::State,
    http::{HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use bytes::Bytes as HyperBytes;
use chrono::{DateTime, Utc};
use http_body_util::BodyExt;
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

// Numeric fields use lax deserializers (see `pydantic_lax_int` /
// `pydantic_lax_float`) so the values Pydantic v2 accepts for `int`/`float`
// (e.g. `"5"`, `true`, `5.0`, `" 1.5 "`) are coerced into the declared Rust
// types instead of being rejected by serde *after* validation already accepted
// them. Serialization and `ToSchema` are unchanged: a plain `//` comment keeps
// the generated OpenAPI description identical to the retired Python handler.
/// Screen diagnostic information (`pixelRatio` alias on the wire).
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DiagnosticScreen {
    #[serde(deserialize_with = "deserialize_lax_i128")]
    pub width: i128,
    #[serde(deserialize_with = "deserialize_lax_i128")]
    pub height: i128,
    #[serde(rename = "pixelRatio", deserialize_with = "deserialize_lax_f64")]
    pub pixel_ratio: f64,
}

/// Viewport diagnostic information.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DiagnosticViewport {
    #[serde(deserialize_with = "deserialize_lax_i128")]
    pub width: i128,
    #[serde(deserialize_with = "deserialize_lax_i128")]
    pub height: i128,
}

/// Scroll position diagnostic information.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DiagnosticScroll {
    #[serde(deserialize_with = "deserialize_lax_i128")]
    pub x: i128,
    #[serde(deserialize_with = "deserialize_lax_i128")]
    pub y: i128,
}

/// Performance timing diagnostic information (both fields optional).
#[derive(Debug, Clone, Default, Deserialize, Serialize, utoipa::ToSchema)]
pub struct DiagnosticPerformance {
    #[serde(
        rename = "domContentLoaded",
        default,
        deserialize_with = "deserialize_lax_opt_f64"
    )]
    pub dom_content_loaded: Option<f64>,
    #[serde(
        rename = "loadComplete",
        default,
        deserialize_with = "deserialize_lax_opt_f64"
    )]
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

/// Error for the bug-report handler.
///
/// The retired FastAPI handler had two distinct 422 shapes: Pydantic request
/// validation produced `{"detail": [ ... ]}`, while the handler's own
/// whitespace check raised `HTTPException(422, detail="...")`. Both are kept
/// distinct here so the wire contract survives the same-path cutover.
#[derive(Debug)]
pub enum BugReportError {
    /// Shared API error (401/503/502 and the handler's blank-field 422).
    Api(ApiError),
    /// FastAPI/Pydantic-style 422 validation error items.
    Validation(Vec<serde_json::Value>),
}

impl BugReportError {
    /// HTTP status for this error, independent of its message.
    pub fn status(&self) -> StatusCode {
        match self {
            Self::Api(error) => error.status(),
            Self::Validation(_) => StatusCode::UNPROCESSABLE_ENTITY,
        }
    }

    /// Wire `detail` value, used by focused tests to pin both 422 shapes.
    pub fn detail_json(&self) -> serde_json::Value {
        match self {
            Self::Api(error) => serde_json::Value::String(error.detail().to_string()),
            Self::Validation(items) => serde_json::json!({"detail": items}),
        }
    }

    /// Sanitize validation internals in production, mirroring FastAPI's
    /// `RequestValidationError` handler: detailed `detail[]` only in
    /// non-production, generic `{"detail":"Validation failed"}` in production.
    /// String-detail 422s raised as explicit API errors (e.g. blank after trim)
    /// are preserved unchanged.
    pub fn sanitized_for(self, environment: crate::config::Environment) -> Self {
        if environment == crate::config::Environment::Production {
            match self {
                Self::Validation(_) => Self::Api(ApiError::with_status(
                    StatusCode::UNPROCESSABLE_ENTITY,
                    "Validation failed".to_string(),
                )),
                other => other,
            }
        } else {
            self
        }
    }
}

impl From<ApiError> for BugReportError {
    fn from(error: ApiError) -> Self {
        Self::Api(error)
    }
}

impl IntoResponse for BugReportError {
    fn into_response(self) -> Response {
        match self {
            Self::Api(error) => error.into_response(),
            Self::Validation(items) => (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(serde_json::json!({"detail": items})),
            )
                .into_response(),
        }
    }
}

fn unprocessable(detail: String) -> ApiError {
    ApiError::with_status(StatusCode::UNPROCESSABLE_ENTITY, detail)
}

/// One segment of a Pydantic `loc` path: a field name or a list index.
///
/// FastAPI serializes list positions as JSON numbers (`0`), not strings
/// (`"0"`). The `loc` helpers are generic over the segment type so every
/// error builder can take either plain string paths or a mixed path built
/// from [`LocSegment::Index`] for list positions.
#[derive(Clone, Copy, Debug, Serialize)]
#[serde(untagged)]
enum LocSegment<'a> {
    Field(&'a str),
    Index(usize),
}

/// FastAPI/Pydantic `missing` validation item.
fn validation_missing<T: Serialize>(loc: &[T], input: &serde_json::Value) -> serde_json::Value {
    serde_json::json!({
        "type": "missing",
        "loc": loc,
        "msg": "Field required",
        "input": input,
    })
}

/// FastAPI/Pydantic `string_type` validation item.
fn validation_string_type<T: Serialize>(loc: &[T], input: &serde_json::Value) -> serde_json::Value {
    serde_json::json!({
        "type": "string_type",
        "loc": loc,
        "msg": "Input should be a valid string",
        "input": input,
    })
}

/// FastAPI/Pydantic `string_too_short` validation item.
fn validation_string_too_short<T: Serialize>(
    loc: &[T],
    input: &serde_json::Value,
    min_length: usize,
) -> serde_json::Value {
    serde_json::json!({
        "type": "string_too_short",
        "loc": loc,
        "msg": format!(
            "String should have at least {min_length} character{}",
            if min_length == 1 { "" } else { "s" }
        ),
        "input": input,
        "ctx": {"min_length": min_length},
    })
}

/// FastAPI/Pydantic `string_too_long` validation item.
fn validation_string_too_long<T: Serialize>(
    loc: &[T],
    input: &serde_json::Value,
    max_length: usize,
) -> serde_json::Value {
    serde_json::json!({
        "type": "string_too_long",
        "loc": loc,
        "msg": format!(
            "String should have at most {max_length} character{}",
            if max_length == 1 { "" } else { "s" }
        ),
        "input": input,
        "ctx": {"max_length": max_length},
    })
}

/// FastAPI/Pydantic `json_invalid` validation item.
fn validation_json_invalid(pos: usize, error: &str) -> serde_json::Value {
    serde_json::json!({
        "type": "json_invalid",
        "loc": ["body", pos],
        "msg": "JSON decode error",
        "input": {},
        "ctx": {"error": error},
    })
}

/// FastAPI/Pydantic `model_attributes_type` validation item.
fn validation_model_type<T: Serialize>(loc: &[T], input: &serde_json::Value) -> serde_json::Value {
    serde_json::json!({
        "type": "model_attributes_type",
        "loc": loc,
        "msg": "Input should be a valid dictionary or object to extract fields from",
        "input": input,
    })
}

/// FastAPI/Pydantic `literal_error` validation item for `report_type`.
fn validation_literal_error<T: Serialize>(
    loc: &[T],
    input: &serde_json::Value,
) -> serde_json::Value {
    serde_json::json!({
        "type": "literal_error",
        "loc": loc,
        "msg": "Input should be 'bug' or 'feature'",
        "input": input,
        "ctx": {"expected": "'bug' or 'feature'"},
    })
}

/// Validate the raw wire body with the retired Pydantic schema's shape.
///
/// `BugReportCreate` carried `min_length`/`max_length` constraints, so FastAPI
/// rejected malformed bodies before the handler ran with a `detail` array.
/// The native service must produce the same shape even though serde has no
/// field-level length constraints.
fn python_json_error_message(serde_msg: &str) -> String {
    let base = serde_msg
        .split(" at line ")
        .next()
        .unwrap_or(serde_msg)
        .trim();
    match base {
        "key must be a string" | "EOF while parsing an object" => {
            "Expecting property name enclosed in double quotes".to_string()
        }
        // serde says "expected value"; Python's JSONDecodeError says
        // "Expecting value" for the same malformed token.
        "expected value" | "EOF while parsing a value" => "Expecting value".to_string(),
        _ => base.to_string(),
    }
}

/// Character offset of a JSON decode error from the start of the whole body.
///
/// FastAPI derives `loc[1]` from `json.JSONDecodeError.pos`, which counts
/// **characters from the beginning of the request body**. serde_json instead
/// reports a one-based `line()` plus a zero-based `column()` measured in bytes
/// within that line, so a naive `column()` is wrong for multi-line bodies and
/// can drift from Python for non-ASCII text (bytes vs characters). Convert to
/// an absolute byte offset first, then count characters in that prefix.
fn json_error_pos(err: &serde_json::Error, body: &[u8]) -> usize {
    let text = String::from_utf8_lossy(body);
    let line_start_byte: usize = text
        .split_inclusive('\n')
        .take(err.line().saturating_sub(1))
        .map(str::len)
        .sum();
    // On EOF serde's column already points at the end of the line; otherwise
    // it points one byte past the offending byte (peek position).
    let within_line = if err.to_string().contains("EOF") {
        err.column()
    } else {
        err.column().saturating_sub(1)
    };
    let mut byte_pos = (line_start_byte + within_line).min(text.len());
    while byte_pos > 0 && !text.is_char_boundary(byte_pos) {
        byte_pos -= 1;
    }
    text[..byte_pos].chars().count()
}

/// Coerce a wire value the way Pydantic v2 (2.12.5) lax mode coerces into an
/// `int` field (`width: int` in the retired schema). Returns the canonical
/// `i128` value, or `None` when Pydantic would reject the input.
///
/// Golden rules verified with the frozen `BugReportCreate` schema + FastAPI
/// `TestClient` (see the `pydantic_lax_*_golden_table` test):
///
/// * booleans -> `1`/`0`; JSON integers -> exact signed/unsigned values;
///   integral JSON floats -> their integer value.
/// * decimal strings: an optional sign, ASCII digits (single underscores
///   allowed between integer digits only), and an optional `.<zeros>` suffix.
///   Exponents (`"1e3"`), trailing/leading dots (`"5."`, `".5"`), non-zero
///   fractions (`"5.1"`, `"5.0000000000000001"`) and misplaced underscores
///   (`"_5"`, `"5_"`, `"1__0"`, `"1.0_0"`) are `int_parsing` errors.
/// * Python `int` is arbitrary precision; `i128` covers every realistic
///   diagnostic value (including the `> i32::MAX` cases Pydantic accepts).
///
/// This is the single source of truth shared by the 422 validator and the
/// serde deserializer so accepted values can never be rejected later by
/// `from_value` with a fabricated `value_error`.
pub(crate) fn pydantic_lax_int(value: &serde_json::Value) -> Option<i128> {
    if let Some(flag) = value.as_bool() {
        return Some(i128::from(flag));
    }
    if let Some(number) = value.as_i64() {
        return Some(i128::from(number));
    }
    if let Some(number) = value.as_u64() {
        return Some(i128::from(number));
    }
    if let Some(number) = value.as_f64() {
        return integral_f64_to_i128(number);
    }
    if let Some(text) = value.as_str() {
        return parse_pydantic_int_string(text.trim());
    }
    None
}

/// Parse an int string with Pydantic 2.12.5 lax-int rules: optional sign,
/// digits with underscores only between integer digits, optional all-zero
/// fractional part. No exponent, hex, or trailing/leading dot.
fn parse_pydantic_int_string(text: &str) -> Option<i128> {
    let (sign, rest) = match text.as_bytes().first() {
        Some(b'+') => (1i128, &text[1..]),
        Some(b'-') => (-1i128, &text[1..]),
        _ => (1i128, text),
    };
    if rest.is_empty() {
        return None;
    }
    let (integer_part, fractional_part) = match rest.split_once('.') {
        Some((integer, fraction)) => (integer, Some(fraction)),
        None => (rest, None),
    };
    if !digits_with_underscores(integer_part) {
        return None;
    }
    if let Some(fraction) = fractional_part {
        // Pydantic allows a `.0`/`.00` suffix but no underscores there and no
        // non-zero digit (so `"5.0000000000000001"` is int_parsing, unlike the
        // float coercion of the same text).
        if fraction.is_empty() || !fraction.bytes().all(|byte| byte == b'0') {
            return None;
        }
    }
    let digits: String = integer_part.chars().filter(|c| *c != '_').collect();
    Some(sign * digits.parse::<i128>().ok()?)
}

/// `true` for a non-empty run of ASCII digits whose only separators are single
/// underscores, each flanked by digits (Pydantic's int underscore rule).
fn digits_with_underscores(text: &str) -> bool {
    let bytes = text.as_bytes();
    if bytes.is_empty() {
        return false;
    }
    let mut previous_was_digit = false;
    for (index, &byte) in bytes.iter().enumerate() {
        if byte.is_ascii_digit() {
            previous_was_digit = true;
        } else if byte == b'_' {
            if !previous_was_digit || index + 1 >= bytes.len() || !bytes[index + 1].is_ascii_digit()
            {
                return false;
            }
            previous_was_digit = false;
        } else {
            return false;
        }
    }
    true
}

fn integral_f64_to_i128(number: f64) -> Option<i128> {
    if number.is_finite()
        && number.fract() == 0.0
        && number >= i128::MIN as f64
        && number <= i128::MAX as f64
    {
        Some(number as i128)
    } else {
        None
    }
}

/// Remove underscores from a float string the way Pydantic 2.12.5 does: a
/// leading `_`, trailing `_`, or consecutive `__` is `float_parsing`, but an
/// underscore next to `.`, `e`, `+` or `-` is removed (`"1_.0"` -> `1.0`,
/// `"1e1_0"` -> `1e10`). Compare [`digits_with_underscores`] for int fields.
fn strip_float_underscores(text: &str) -> Option<String> {
    let bytes = text.as_bytes();
    if bytes.first() == Some(&b'_') || bytes.last() == Some(&b'_') || text.contains("__") {
        return None;
    }
    Some(text.replace('_', ""))
}

/// Coerce a wire value the way Pydantic v2 (2.12.5) lax mode coerces into a
/// `float` field (`pixelRatio: float`, `domContentLoaded: float | None`, ...).
fn pydantic_lax_float(value: &serde_json::Value) -> Option<f64> {
    if let Some(flag) = value.as_bool() {
        return Some(if flag { 1.0 } else { 0.0 });
    }
    if let Some(number) = value.as_f64() {
        return Some(number);
    }
    if let Some(text) = value.as_str() {
        let cleaned = strip_float_underscores(text.trim())?;
        return cleaned.parse::<f64>().ok();
    }
    None
}

fn deserialize_lax_i128<'de, D>(deserializer: D) -> Result<i128, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = serde_json::Value::deserialize(deserializer)?;
    pydantic_lax_int(&value).ok_or_else(|| serde::de::Error::custom("invalid integer"))
}

fn deserialize_lax_f64<'de, D>(deserializer: D) -> Result<f64, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = serde_json::Value::deserialize(deserializer)?;
    pydantic_lax_float(&value).ok_or_else(|| serde::de::Error::custom("invalid number"))
}

fn deserialize_lax_opt_f64<'de, D>(deserializer: D) -> Result<Option<f64>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = serde_json::Value::deserialize(deserializer)?;
    if value.is_null() {
        return Ok(None);
    }
    pydantic_lax_float(&value)
        .map(Some)
        .ok_or_else(|| serde::de::Error::custom("invalid number"))
}

fn validate_int_field<T: Serialize>(
    loc: &[T],
    value: &serde_json::Value,
    items: &mut Vec<serde_json::Value>,
) {
    if pydantic_lax_int(value).is_some() {
        return;
    }
    let (typ, msg) = if value.is_null() {
        ("int_type", "Input should be a valid integer")
    } else if value.as_f64().map(|f| f.fract() != 0.0).unwrap_or(false) {
        (
            "int_from_float",
            "Input should be a valid integer, got a number with a fractional part",
        )
    } else if value.is_string() {
        (
            "int_parsing",
            "Input should be a valid integer, unable to parse string as an integer",
        )
    } else {
        ("int_type", "Input should be a valid integer")
    };
    items.push(serde_json::json!({
        "type": typ,
        "loc": loc,
        "msg": msg,
        "input": value,
    }));
}

fn validate_float_field<T: Serialize>(
    loc: &[T],
    value: &serde_json::Value,
    items: &mut Vec<serde_json::Value>,
) {
    // Required floats such as `screen.pixelRatio` reject null with a
    // `float_type` item at the field's own loc. Optional performance floats
    // are filtered by `validate_performance` before reaching this helper, so
    // their null stays valid without weakening this required-field check.
    if pydantic_lax_float(value).is_some() {
        return;
    }
    let (typ, msg) = if value.is_string() {
        (
            "float_parsing",
            "Input should be a valid number, unable to parse string as a number",
        )
    } else {
        ("float_type", "Input should be a valid number")
    };
    items.push(serde_json::json!({
        "type": typ,
        "loc": loc,
        "msg": msg,
        "input": value,
    }));
}

fn validate_screen(screen: &serde_json::Value, items: &mut Vec<serde_json::Value>) {
    let input = screen.clone();
    for field in ["width", "height"] {
        match screen.get(field) {
            None => items.push(validation_missing(
                &["body", "diagnostics", "screen", field],
                &input,
            )),
            Some(v) => validate_int_field(&["body", "diagnostics", "screen", field], v, items),
        }
    }
    match screen.get("pixelRatio") {
        None => items.push(validation_missing(
            &["body", "diagnostics", "screen", "pixelRatio"],
            &input,
        )),
        Some(v) => validate_float_field(&["body", "diagnostics", "screen", "pixelRatio"], v, items),
    }
}

fn validate_viewport(viewport: &serde_json::Value, items: &mut Vec<serde_json::Value>) {
    let input = viewport.clone();
    for field in ["width", "height"] {
        match viewport.get(field) {
            None => items.push(validation_missing(
                &["body", "diagnostics", "viewport", field],
                &input,
            )),
            Some(v) => validate_int_field(&["body", "diagnostics", "viewport", field], v, items),
        }
    }
}

fn validate_scroll(scroll: &serde_json::Value, items: &mut Vec<serde_json::Value>) {
    let input = scroll.clone();
    for field in ["x", "y"] {
        match scroll.get(field) {
            None => items.push(validation_missing(
                &["body", "diagnostics", "scroll", field],
                &input,
            )),
            Some(v) => validate_int_field(&["body", "diagnostics", "scroll", field], v, items),
        }
    }
}

fn validate_performance(perf: &serde_json::Value, items: &mut Vec<serde_json::Value>) {
    let input = perf.clone();
    for (wire, _rust) in [("domContentLoaded", ()), ("loadComplete", ())] {
        if let Some(v) = perf.get(wire) {
            if !v.is_null() {
                validate_float_field(&["body", "diagnostics", "performance", wire], v, items);
            }
        }
    }
    // required? performance object itself required; fields optional with defaults
    let _ = input;
}

fn validate_diagnostics(diag: &serde_json::Value, items: &mut Vec<serde_json::Value>) {
    let input = diag.clone();
    for field in ["timestamp", "url"] {
        // wire field same
        match diag.get(field) {
            None => items.push(validation_missing(&["body", "diagnostics", field], &input)),
            Some(v) => {
                if !v.is_string() {
                    items.push(validation_string_type(&["body", "diagnostics", field], v));
                }
            }
        }
    }
    // userAgent alias
    match diag.get("userAgent") {
        None => items.push(validation_missing(
            &["body", "diagnostics", "userAgent"],
            &input,
        )),
        Some(v) => {
            if !v.is_string() {
                items.push(validation_string_type(
                    &["body", "diagnostics", "userAgent"],
                    v,
                ));
            }
        }
    }
    // screen
    match diag.get("screen") {
        None => items.push(validation_missing(
            &["body", "diagnostics", "screen"],
            &input,
        )),
        Some(v) => {
            if !v.is_object() {
                items.push(validation_model_type(&["body", "diagnostics", "screen"], v));
            } else {
                validate_screen(v, items);
            }
        }
    }
    // viewport
    match diag.get("viewport") {
        None => items.push(validation_missing(
            &["body", "diagnostics", "viewport"],
            &input,
        )),
        Some(v) => {
            if !v.is_object() {
                items.push(validation_model_type(
                    &["body", "diagnostics", "viewport"],
                    v,
                ));
            } else {
                validate_viewport(v, items);
            }
        }
    }
    // scroll
    match diag.get("scroll") {
        None => items.push(validation_missing(
            &["body", "diagnostics", "scroll"],
            &input,
        )),
        Some(v) => {
            if !v.is_object() {
                items.push(validation_model_type(&["body", "diagnostics", "scroll"], v));
            } else {
                validate_scroll(v, items);
            }
        }
    }
    // performance required
    match diag.get("performance") {
        None => items.push(validation_missing(
            &["body", "diagnostics", "performance"],
            &input,
        )),
        Some(v) => {
            if !v.is_object() {
                items.push(validation_model_type(
                    &["body", "diagnostics", "performance"],
                    v,
                ));
            } else {
                validate_performance(v, items);
            }
        }
    }
    // errors required list
    match diag.get("errors") {
        None => items.push(validation_missing(
            &["body", "diagnostics", "errors"],
            &input,
        )),
        Some(v) => {
            if !v.is_array() {
                items.push(serde_json::json!({
                    "type": "list_type",
                    "loc": ["body", "diagnostics", "errors"],
                    "msg": "Input should be a valid list",
                    "input": v,
                }));
            } else if let Some(arr) = v.as_array() {
                for (index, item) in arr.iter().enumerate() {
                    let item_loc = [
                        LocSegment::Field("body"),
                        LocSegment::Field("diagnostics"),
                        LocSegment::Field("errors"),
                        LocSegment::Index(index),
                    ];
                    if !item.is_object() {
                        items.push(validation_model_type(&item_loc, item));
                        continue;
                    }
                    for field in ["message", "timestamp"] {
                        let field_loc = [
                            LocSegment::Field("body"),
                            LocSegment::Field("diagnostics"),
                            LocSegment::Field("errors"),
                            LocSegment::Index(index),
                            LocSegment::Field(field),
                        ];
                        match item.get(field) {
                            None => items.push(validation_missing(&field_loc, item)),
                            Some(value) if !value.is_string() => {
                                items.push(validation_string_type(&field_loc, value));
                            }
                            Some(_) => {}
                        }
                    }
                }
            }
        }
    }
}

fn parse_request(body: &[u8]) -> Result<BugReportCreate, BugReportError> {
    // FastAPI treats a zero-length request body as a missing body parameter,
    // not as malformed JSON: `{"type":"missing","loc":["body"],
    // "msg":"Field required","input":null}`. A non-empty but invalid body
    // still goes through the JSON decoder below.
    if body.is_empty() {
        return Err(BugReportError::Validation(vec![validation_missing(
            &["body"],
            &serde_json::Value::Null,
        )]));
    }
    let err = match serde_json::from_slice::<serde_json::Value>(body) {
        Ok(v) => v,
        Err(e) => {
            let pos = json_error_pos(&e, body);
            let msg = python_json_error_message(&e.to_string());
            return Err(BugReportError::Validation(vec![validation_json_invalid(
                pos, &msg,
            )]));
        }
    };
    let value = err;
    let Some(object) = value.as_object() else {
        return Err(BugReportError::Validation(vec![validation_model_type(
            &["body"],
            &value,
        )]));
    };

    let mut items: Vec<serde_json::Value> = Vec::new();
    for (field, max_length) in [
        ("title", MAX_TITLE_CHARS),
        ("description", MAX_DESCRIPTION_CHARS),
    ] {
        let loc = if field == "title" {
            ["body", "title"]
        } else {
            ["body", "description"]
        };
        match object.get(field) {
            None => items.push(validation_missing(&loc, &value)),
            Some(input) => match input.as_str() {
                None => items.push(validation_string_type(&loc, input)),
                Some(text) => {
                    let length = text.chars().count();
                    if length < 1 {
                        items.push(validation_string_too_short(&loc, input, 1));
                    }
                    if length > max_length {
                        items.push(validation_string_too_long(&loc, input, max_length));
                    }
                }
            },
        }
    }
    if let Some(input) = object.get("report_type") {
        if !matches!(input.as_str(), Some("bug") | Some("feature")) {
            items.push(validation_literal_error(&["body", "report_type"], input));
        }
    }
    if let Some(input) = object.get("diagnostics") {
        if input.is_null() {
            // allowed (Option)
        } else if !input.is_object() {
            items.push(validation_model_type(&["body", "diagnostics"], input));
        } else {
            validate_diagnostics(input, &mut items);
        }
    }
    if !items.is_empty() {
        return Err(BugReportError::Validation(items));
    }

    // Every field that could make serde reject a validated body is now
    // deserialized through the same Pydantic-lax coercion the validators above
    // use, so this fallback is a defensive invariant and is unreachable for
    // bodies that passed validation (no fabricated `value_error` 422).
    serde_json::from_value(value).map_err(|error| {
        BugReportError::Validation(vec![serde_json::json!({
            "type": "value_error",
            "loc": ["body"],
            "msg": error.to_string(),
            "input": null,
        })])
    })
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

/// Build the GitHub issue body exactly like the retired Python
/// `_create_bug_report_issue_sync` builder.
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

/// Map a transport failure to the exact production GitHub error string.
fn github_transport_error(error: &OutboundError) -> String {
    let reason = match error {
        OutboundError::Connect(_) | OutboundError::Send(_) => "network error",
        OutboundError::TlsSetup(_) => "TLS not available",
        OutboundError::TlsHandshake(_) => "TLS handshake failed",
        OutboundError::HttpHandshake(_) => "connection failed",
        OutboundError::RequestInvalid(_) => "request invalid",
    };
    format!("Failed to create GitHub issue: {reason}")
}

/// Create the GitHub issue through the app's outbound seam. Production uses
/// the real HTTPS client; test-configured apps hold a recording fake that
/// never opens a socket (#5339).
async fn create_github_issue(
    outbound: Arc<dyn OutboundHttp>,
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
    let request = OutboundRequest {
        method: http::Method::POST,
        path: format!("/repos/{owner}/{repo}/issues"),
        headers: vec![
            (
                "accept".to_string(),
                "application/vnd.github+json".to_string(),
            ),
            ("authorization".to_string(), format!("Bearer {token}")),
            ("x-github-api-version".to_string(), "2022-11-28".to_string()),
            (
                "user-agent".to_string(),
                "comic-pile-native/1.0 (bug report)".to_string(),
            ),
            ("content-type".to_string(), "application/json".to_string()),
            (
                "content-length".to_string(),
                payload_bytes.len().to_string(),
            ),
        ],
        body: HyperBytes::from(payload_bytes),
    };

    let exchange = async {
        let response = outbound.send(GITHUB_HOST, request).await.map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            github_transport_error(&e)
        })?;
        let status = response.status;
        let mut data = Vec::new();
        let mut body = response.body;
        while let Some(frame) = body.frame().await {
            let frame = frame.map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                "Failed to create GitHub issue".to_string()
            })?;
            if let Ok(bytes) = frame.into_data() {
                if data.len() + bytes.len() > MAX_GITHUB_BODY {
                    break;
                }
                data.extend_from_slice(&bytes);
            }
        }
        if status.is_success() {
            let value: serde_json::Value = serde_json::from_slice(&data).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                {
                    "Failed to create GitHub issue: invalid provider payload".to_string()
                }
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
    tokio::time::timeout(GITHUB_TIMEOUT, exchange)
        .await
        .map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            "Failed to create GitHub issue: timeout".to_string()
        })?
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

fn validate_create(request: &BugReportCreate) -> Result<(String, String), BugReportError> {
    let title_chars = request.title.chars().count();
    if title_chars < 1 {
        return Err(BugReportError::Validation(vec![
            validation_string_too_short(
                &["body", "title"],
                &serde_json::Value::String(request.title.clone()),
                1,
            ),
        ]));
    }
    if title_chars > MAX_TITLE_CHARS {
        return Err(BugReportError::Validation(vec![
            validation_string_too_long(
                &["body", "title"],
                &serde_json::Value::String(request.title.clone()),
                MAX_TITLE_CHARS,
            ),
        ]));
    }
    let description_chars = request.description.chars().count();
    if description_chars < 1 {
        return Err(BugReportError::Validation(vec![
            validation_string_too_short(
                &["body", "description"],
                &serde_json::Value::String(request.description.clone()),
                1,
            ),
        ]));
    }
    if description_chars > MAX_DESCRIPTION_CHARS {
        return Err(BugReportError::Validation(vec![
            validation_string_too_long(
                &["body", "description"],
                &serde_json::Value::String(request.description.clone()),
                MAX_DESCRIPTION_CHARS,
            ),
        ]));
    }
    let title = request.title.trim().to_string();
    let description = request.description.trim().to_string();
    if title.is_empty() || description.is_empty() {
        return Err(BugReportError::Api(unprocessable(
            "Title and description must not be blank".to_string(),
        )));
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
) -> Result<Response, BugReportError> {
    let (title, description) = validate_create(&request)?;
    if !settings.is_configured() {
        return Err(BugReportError::Api(not_configured()));
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
            .map_err(|detail| {
                BugReportError::Api(ApiError::with_status(StatusCode::BAD_GATEWAY, detail))
            })?;
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
            return Err(BugReportError::Api(ApiError::with_status(
                StatusCode::BAD_GATEWAY,
                detail,
            )));
        }
    };
    let submitted_at_seconds = Utc::now().timestamp_micros() as f64 / 1_000_000.0;
    record_success(&tx, user_id, submitted_at_seconds).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(BugReportResponse { issue_url })).into_response())
}

/// Same create flow as the axum handler with an explicitly injected issuer.
///
/// Production [`create`] always passes the real HTTPS GitHub issuer. Tests
/// pass an in-process fake so no network request is ever made while still
/// exercising parsing, validation, rate limiting and transaction semantics.
async fn create_with_issuer(
    state: Arc<AppState>,
    user_id: i32,
    body: Bytes,
    issuer: &GithubIssuer<'_>,
) -> Result<Response, BugReportError> {
    let environment = state.environment;
    let request = parse_request(&body).map_err(|e| e.sanitized_for(environment))?;
    let (username, is_admin) = load_user(&state, user_id)
        .await
        .map_err(|e| BugReportError::from(e).sanitized_for(environment))?;
    let settings = github_settings();
    submit_with_issuer(
        &state, user_id, username, is_admin, request, settings, issuer,
    )
    .await
    .map_err(|e| e.sanitized_for(environment))
}

/// `POST /api/bug-reports/` and `POST /api/v1/bug-reports/`.
///
/// Wire parity with the retired Python `create_bug_report`: same method/path,
/// 201 on success, 422 validation, 503 unconfigured, 429 rate-limit with
/// headers, 502 GitHub failures. Validation detail arrays are exposed only in
/// non-production; production returns `{"detail":"Validation failed"}`.
pub async fn create(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    body: Bytes,
) -> Result<Response, BugReportError> {
    // The issuer resolves through the app's outbound seam (#5339): production
    // uses the real HTTPS GitHub client, test-configured apps hold a recording
    // fake. The `GithubIssuer` closure shape is unchanged so focused tests can
    // still inject their own issuer through `create_with_issuer`.
    let outbound = state.outbound.clone();
    let issuer = move |settings: GithubSettings,
                       title: String,
                       body: String,
                       labels: Vec<String>|
          -> GithubFuture {
        Box::pin(create_github_issue(
            outbound.clone(),
            settings,
            title,
            body,
            labels,
        ))
    };
    create_with_issuer(state, user.id(), body, &issuer).await
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
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Mutex,
    };
    use utoipa::OpenApi;

    /// Records issuer calls so a handler-boundary test can prove the in-process
    /// fake ran and that `create_github_issue` (real network) was never used.
    struct IssuerProbe {
        calls: Arc<AtomicUsize>,
        body: Arc<Mutex<String>>,
    }

    impl IssuerProbe {
        fn new() -> Self {
            Self {
                calls: Arc::new(AtomicUsize::new(0)),
                body: Arc::new(Mutex::new(String::new())),
            }
        }

        fn issuer(
            &self,
            detail: &'static str,
        ) -> impl Fn(GithubSettings, String, String, Vec<String>) -> GithubFuture + Send + Sync + '_
        {
            let calls = Arc::clone(&self.calls);
            let body = Arc::clone(&self.body);
            move |_settings, _title, issue_body, _labels| {
                calls.fetch_add(1, Ordering::SeqCst);
                *body.lock().expect("record issuer body") = issue_body;
                let detail = detail.to_string();
                Box::pin(async move { Err(detail) }) as GithubFuture
            }
        }

        fn assert_issued_via_fake(&self, error: &BugReportError) {
            assert_eq!(
                self.calls.load(Ordering::SeqCst),
                1,
                "the injected fake issuer must be used; no real GitHub request may be made"
            );
            assert_eq!(
                error.detail_json(),
                serde_json::Value::String("SYNTHETIC_ISSUER_FAILURE".to_string()),
                "the 502 detail must come from the fake issuer, not the network path"
            );
        }

        fn captured_body(&self) -> String {
            self.body.lock().expect("read issuer body").clone()
        }
    }

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
            assert_eq!(
                error.detail_json(),
                serde_json::Value::String("Title and description must not be blank".to_string())
            );
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

    /// The retired Pydantic schema rejected these bodies before the handler
    /// ran, so the native port must emit the same `detail` array shape.
    #[test]
    fn parse_request_preserves_pydantic_validation_error_shapes() {
        let cases: Vec<(&str, Vec<u8>, serde_json::Value)> = vec![
            (
                "empty body is a missing body, not malformed JSON",
                Vec::new(),
                serde_json::json!([{
                    "type": "missing",
                    "loc": ["body"],
                    "msg": "Field required",
                    "input": null
                }]),
            ),
            (
                "malformed JSON",
                b"{not json".to_vec(),
                serde_json::json!([{
                    "type": "json_invalid",
                    "loc": ["body", 1],
                    "msg": "JSON decode error",
                    "input": {},
                    "ctx": {"error": "Expecting property name enclosed in double quotes"}
                }]),
            ),
            (
                "non-object body",
                br#"[]"#.to_vec(),
                serde_json::json!([{
                    "type": "model_attributes_type",
                    "loc": ["body"],
                    "msg": "Input should be a valid dictionary or object to extract fields from",
                    "input": []
                }]),
            ),
            (
                "missing required fields",
                br#"{}"#.to_vec(),
                serde_json::json!([
                    {"type":"missing","loc":["body","title"],"msg":"Field required","input":{}},
                    {"type":"missing","loc":["body","description"],"msg":"Field required","input":{}}
                ]),
            ),
            (
                "empty title",
                br#"{"title":"","description":"details"}"#.to_vec(),
                serde_json::json!([{
                    "type": "string_too_short",
                    "loc": ["body", "title"],
                    "msg": "String should have at least 1 character",
                    "input": "",
                    "ctx": {"min_length": 1}
                }]),
            ),
            (
                "overlong description",
                format!(
                    r#"{{"title":"title","description":"{}"}}"#,
                    "d".repeat(2001)
                )
                .into_bytes(),
                serde_json::json!([{
                    "type": "string_too_long",
                    "loc": ["body", "description"],
                    "msg": "String should have at most 2000 characters",
                    "input": "d".repeat(2001),
                    "ctx": {"max_length": 2000}
                }]),
            ),
            (
                "non-string title",
                br#"{"title":3,"description":"details"}"#.to_vec(),
                serde_json::json!([{
                    "type": "string_type",
                    "loc": ["body", "title"],
                    "msg": "Input should be a valid string",
                    "input": 3
                }]),
            ),
            (
                "invalid report type",
                br#"{"title":"title","description":"details","report_type":"other"}"#.to_vec(),
                serde_json::json!([{
                    "type": "literal_error",
                    "loc": ["body", "report_type"],
                    "msg": "Input should be 'bug' or 'feature'",
                    "input": "other",
                    "ctx": {"expected": "'bug' or 'feature'"}
                }]),
            ),
            (
                "non-object diagnostics",
                br#"{"title":"title","description":"details","diagnostics":"broken"}"#.to_vec(),
                serde_json::json!([{
                    "type": "model_attributes_type",
                    "loc": ["body", "diagnostics"],
                    "msg": "Input should be a valid dictionary or object to extract fields from",
                    "input": "broken"
                }]),
            ),
        ];

        for (name, body, expected) in cases {
            let error = parse_request(&body).expect_err(name);
            assert_eq!(error.status(), StatusCode::UNPROCESSABLE_ENTITY, "{name}");
            assert_eq!(
                error.detail_json(),
                serde_json::json!({"detail": expected.as_array().cloned().unwrap_or_default()}),
                "{name}"
            );
        }
    }

    #[test]
    fn parse_request_accepts_valid_wire_body_with_camel_case_diagnostics() {
        let body = br#"{"title":"Bug","description":"Details","diagnostics":{"timestamp":"t","url":"u","userAgent":"a","screen":{"width":390,"height":844,"pixelRatio":3},"viewport":{"width":390,"height":664},"scroll":{"x":0,"y":1},"performance":{},"errors":[]}}"#;
        let request = parse_request(body).expect("valid body");
        assert_eq!(request.report_type, ReportType::Bug);
        assert_eq!(request.title, "Bug");
        assert!(request.diagnostics.is_some());
    }

    /// Pydantic v2 lax mode coerces these numeric forms into `int`/`float`
    /// fields and the retired Python handler filed the issue. The native port
    /// must accept the same values (no fabricated `value_error` 422) and store
    /// the coerced values that the GitHub issue body renders.
    #[test]
    fn parse_request_accepts_pydantic_lax_numeric_diagnostics() {
        let body = br#"{
            "title":"Bug","description":"Details",
            "diagnostics":{
                "timestamp":"t","url":"u","userAgent":"a",
                "screen":{"width":"5","height":true,"pixelRatio":"2.5"},
                "viewport":{"width":3.0,"height":"4"},
                "scroll":{"x":"0","y":5.0},
                "performance":{"domContentLoaded":"2","loadComplete":true},
                "errors":[]
            }
        }"#;
        let request = parse_request(body).expect("lax numeric diagnostics must be accepted");
        let diag = request.diagnostics.expect("diagnostics");
        assert_eq!(diag.screen.width, 5);
        assert_eq!(diag.screen.height, 1);
        assert_eq!(diag.screen.pixel_ratio, 2.5);
        assert_eq!(diag.viewport.width, 3);
        assert_eq!(diag.viewport.height, 4);
        assert_eq!(diag.scroll.x, 0);
        assert_eq!(diag.scroll.y, 5);
        assert_eq!(diag.performance.dom_content_loaded, Some(2.0));
        assert_eq!(diag.performance.load_complete, Some(1.0));

        // The coerced values flow into the byte-identical Python issue body.
        let issue = build_github_issue_body("reporter", ReportType::Bug, "Details", Some(&diag));
        assert!(issue.contains("**Screen:** 5×1 @2.5x"));
        assert!(issue.contains("**Viewport:** 3×4"));
        assert!(issue.contains("**Scroll:** (0, 5)"));
        assert!(issue.contains("**Performance:** DOMContentLoaded: 2ms, Load: 1ms"));
    }

    /// Wider lax-mode matrix: signed/whitespace-padded strings,
    /// integer-valued float strings, negative integers and booleans all mirror
    /// Pydantic v2 lax coercion for the declared `int`/`float` field types.
    #[test]
    fn parse_request_accepts_every_pydantic_lax_numeric_form() {
        let body = br#"{
            "title":"Bug","description":"Details",
            "diagnostics":{
                "timestamp":"t","url":"u","userAgent":"a",
                "screen":{"width":" 6 ","height":"7.0","pixelRatio":" 3.5 "},
                "viewport":{"width":"+8","height":-9},
                "scroll":{"x":"10.0","y":false},
                "performance":{"domContentLoaded":"11.5","loadComplete":"12"},
                "errors":[]
            }
        }"#;
        let request = parse_request(body).expect("all lax numeric forms must be accepted");
        let diag = request.diagnostics.expect("diagnostics");
        assert_eq!(diag.screen.width, 6);
        assert_eq!(diag.screen.height, 7);
        assert_eq!(diag.screen.pixel_ratio, 3.5);
        assert_eq!(diag.viewport.width, 8);
        assert_eq!(diag.viewport.height, -9);
        assert_eq!(diag.scroll.x, 10);
        assert_eq!(diag.scroll.y, 0);
        assert_eq!(diag.performance.dom_content_loaded, Some(11.5));
        assert_eq!(diag.performance.load_complete, Some(12.0));
    }

    /// Invalid numeric diagnostics still produce real Pydantic-shaped 422
    /// items (and never the fabricated `value_error` fallback), proving the
    /// lax coercion did not weaken validation.
    #[test]
    fn parse_request_rejects_invalid_numeric_diagnostics_with_pydantic_shapes() {
        let body = br#"{
            "title":"Bug","description":"Details",
            "diagnostics":{
                "timestamp":"t","url":"u","userAgent":"a",
                "screen":{"width":5.5,"height":"abc","pixelRatio":true},
                "viewport":{"width":1,"height":2},
                "scroll":{"x":0,"y":1},
                "performance":{},"errors":[]
            }
        }"#;
        let error =
            parse_request(body).expect_err("fractional int and unparseable string must fail");
        assert_eq!(error.status(), StatusCode::UNPROCESSABLE_ENTITY);
        let detail = error.detail_json();
        let items = detail["detail"].as_array().expect("detail array");
        let types: Vec<&str> = items
            .iter()
            .map(|item| item["type"].as_str().expect("string type"))
            .collect();
        assert!(types.contains(&"int_from_float"), "{detail}");
        assert!(types.contains(&"int_parsing"), "{detail}");
        assert!(
            !types.contains(&"value_error"),
            "no fabricated fallback: {detail}"
        );
    }

    /// Golden table captured empirically from the retired Pydantic 2.12.5
    /// `BugReportCreate` schema (commit f0d6b24e6) with the frozen FastAPI
    /// `create_bug_report` handler signature and `TestClient`. These are the
    /// exact accept/reject + coercion + 422 `type` diagnostics that production
    /// returned for diagnostic numeric fields; the native port must match.
    #[test]
    fn pydantic_numeric_coercion_golden_table() {
        fn int_outcome(raw: serde_json::Value) -> Result<i128, String> {
            let body = serde_json::json!({
                "title": "Bug", "description": "Details",
                "diagnostics": {
                    "timestamp": "t", "url": "u", "userAgent": "a",
                    "screen": {"width": raw, "height": 1, "pixelRatio": 1.0},
                    "viewport": {"width": 1, "height": 2},
                    "scroll": {"x": 0, "y": 1},
                    "performance": {}, "errors": []
                }
            });
            let bytes = serde_json::to_vec(&body).expect("body");
            match parse_request(&bytes) {
                Ok(request) => Ok(request.diagnostics.expect("diagnostics").screen.width),
                Err(error) => {
                    assert_eq!(error.status(), StatusCode::UNPROCESSABLE_ENTITY);
                    let detail = error.detail_json();
                    assert_eq!(
                        detail["detail"][0]["loc"],
                        serde_json::json!(["body", "diagnostics", "screen", "width"])
                    );
                    Err(detail["detail"][0]["type"]
                        .as_str()
                        .expect("type")
                        .to_string())
                }
            }
        }

        fn float_outcome(raw: serde_json::Value) -> Result<f64, String> {
            let body = serde_json::json!({
                "title": "Bug", "description": "Details",
                "diagnostics": {
                    "timestamp": "t", "url": "u", "userAgent": "a",
                    "screen": {"width": 1, "height": 1, "pixelRatio": raw},
                    "viewport": {"width": 1, "height": 2},
                    "scroll": {"x": 0, "y": 1},
                    "performance": {}, "errors": []
                }
            });
            let bytes = serde_json::to_vec(&body).expect("body");
            match parse_request(&bytes) {
                Ok(request) => Ok(request.diagnostics.expect("diagnostics").screen.pixel_ratio),
                Err(error) => {
                    assert_eq!(error.status(), StatusCode::UNPROCESSABLE_ENTITY);
                    let detail = error.detail_json();
                    assert_eq!(
                        detail["detail"][0]["loc"],
                        serde_json::json!(["body", "diagnostics", "screen", "pixelRatio"])
                    );
                    Err(detail["detail"][0]["type"]
                        .as_str()
                        .expect("type")
                        .to_string())
                }
            }
        }

        // (raw wire value, Pydantic outcome). `Ok` is the exact coerced value;
        // `Err` is the exact 422 `type` Pydantic emitted.
        let int_cases: Vec<(serde_json::Value, Result<i128, &str>)> = vec![
            // Previously over-accepted by Rust `parse::<f64>()`: Pydantic -> int_parsing.
            (serde_json::json!("1e3"), Err("int_parsing")),
            (serde_json::json!("1E3"), Err("int_parsing")),
            (serde_json::json!("1e0"), Err("int_parsing")),
            (serde_json::json!("5."), Err("int_parsing")),
            (serde_json::json!("5.0000000000000001"), Err("int_parsing")),
            (serde_json::json!("1e-3"), Err("int_parsing")),
            // Integral decimal strings are accepted by Pydantic int.
            (serde_json::json!("5.0"), Ok(5)),
            (serde_json::json!("5.00"), Ok(5)),
            (serde_json::json!("-5.0"), Ok(-5)),
            (serde_json::json!("+5.0"), Ok(5)),
            // Underscores accepted only between integer digits.
            (serde_json::json!("1_000"), Ok(1000)),
            (serde_json::json!("1_0.0"), Ok(10)),
            (serde_json::json!("+1_0"), Ok(10)),
            (serde_json::json!("-1_0"), Ok(-10)),
            (serde_json::json!("  1_000  "), Ok(1000)),
            (serde_json::json!("_5"), Err("int_parsing")),
            (serde_json::json!("5_"), Err("int_parsing")),
            (serde_json::json!("1__0"), Err("int_parsing")),
            (serde_json::json!("1_.0"), Err("int_parsing")),
            (serde_json::json!("1._0"), Err("int_parsing")),
            (serde_json::json!("1.0_0"), Err("int_parsing")),
            // Beyond i32: Python int is arbitrary precision.
            (serde_json::json!(2147483648i64), Ok(2147483648)),
            (serde_json::json!(10000000000i64), Ok(10000000000)),
            (serde_json::json!(9007199254740993i64), Ok(9007199254740993)),
            (
                serde_json::json!("9223372036854775808"),
                Ok(9223372036854775808),
            ),
            (
                serde_json::json!("1000000000000000000000000000000"),
                Ok(1000000000000000000000000000000),
            ),
            // Booleans, JSON integral floats and fractional floats.
            (serde_json::json!(true), Ok(1)),
            (serde_json::json!(false), Ok(0)),
            (serde_json::json!(5.0), Ok(5)),
            (serde_json::json!(5.5), Err("int_from_float")),
        ];
        for (raw, expected) in int_cases {
            let actual = int_outcome(raw.clone());
            assert_eq!(actual, expected.map_err(str::to_string), "int raw={raw}");
        }

        let float_cases: Vec<(serde_json::Value, Result<f64, &str>)> = vec![
            // Previously rejected by Rust: Pydantic float accepts all of these.
            (serde_json::json!("1e3"), Ok(1000.0)),
            (serde_json::json!("1E3"), Ok(1000.0)),
            (serde_json::json!("5."), Ok(5.0)),
            (serde_json::json!("  2.5  "), Ok(2.5)),
            (serde_json::json!("1_000"), Ok(1000.0)),
            (serde_json::json!("1_0.0"), Ok(10.0)),
            (serde_json::json!("1_000.5"), Ok(1000.5)),
            (serde_json::json!("1_.0"), Ok(1.0)),
            (serde_json::json!("1e1_0"), Ok(10_000_000_000.0)),
            (serde_json::json!("inf"), Ok(f64::INFINITY)),
            (serde_json::json!("nan"), Ok(f64::NAN)),
            // Misplaced underscores remain float_parsing.
            (serde_json::json!("_5"), Err("float_parsing")),
            (serde_json::json!("5_"), Err("float_parsing")),
            (serde_json::json!("1__0"), Err("float_parsing")),
            (serde_json::json!("0x10"), Err("float_parsing")),
            // Required float rejects null with float_type at the field loc.
            (serde_json::json!(null), Err("float_type")),
        ];
        for (raw, expected) in float_cases {
            let actual = float_outcome(raw.clone());
            match expected {
                Ok(want) if want.is_nan() => {
                    assert!(actual.expect("nan").is_nan(), "float raw={raw}");
                }
                Ok(want) => assert_eq!(actual, Ok(want), "float raw={raw}"),
                Err(kind) => assert_eq!(actual, Err(kind.to_string()), "float raw={raw}"),
            }
        }
    }

    /// Empirical 422 golden table for the FastAPI validation-shape parity
    /// findings, captured from the frozen Pydantic 2.12.5 `BugReportCreate`
    /// (commit f0d6b24e6) via a FastAPI `TestClient` posting the exact bytes
    /// below. These pin the non-production detailed `detail[]` shapes that the
    /// retired app's custom handler exposed outside production; in production
    /// the handler sanitized request-validation errors to
    /// `{"detail":"Validation failed"}` (see the production sanitization tests).
    #[test]
    fn pydantic_validation_shape_golden_table() {
        fn diagnostic_body(screen: serde_json::Value, errors: serde_json::Value) -> Vec<u8> {
            serde_json::to_vec(&serde_json::json!({
                "title": "Bug",
                "description": "Details",
                "diagnostics": {
                    "timestamp": "t",
                    "url": "u",
                    "userAgent": "a",
                    "screen": screen,
                    "viewport": {"width": 390, "height": 664},
                    "scroll": {"x": 0, "y": 1},
                    "performance": {},
                    "errors": errors,
                }
            }))
            .expect("golden body")
        }

        let valid_screen = serde_json::json!({"width": 390, "height": 844, "pixelRatio": 3});
        let detail = |body: &[u8]| {
            let error = parse_request(body).expect_err("golden body must fail validation");
            assert_eq!(error.status(), StatusCode::UNPROCESSABLE_ENTITY);
            error.detail_json()["detail"].clone()
        };

        // (1) A required float's null is a field-level float_type, not the
        // fabricated fallback value_error at ["body"], and it is not hidden
        // by other invalid fields. Optional performance null stays valid.
        assert_eq!(
            detail(&diagnostic_body(
                serde_json::json!({"width": 390, "height": 844, "pixelRatio": null}),
                serde_json::json!([])
            )),
            serde_json::json!([{
                "type": "float_type",
                "loc": ["body", "diagnostics", "screen", "pixelRatio"],
                "msg": "Input should be a valid number",
                "input": null
            }])
        );
        assert_eq!(
            detail(&diagnostic_body(
                serde_json::json!({"width": "abc", "height": 844, "pixelRatio": null}),
                serde_json::json!([])
            )),
            serde_json::json!([
                {
                    "type": "int_parsing",
                    "loc": ["body", "diagnostics", "screen", "width"],
                    "msg": "Input should be a valid integer, unable to parse string as an integer",
                    "input": "abc"
                },
                {
                    "type": "float_type",
                    "loc": ["body", "diagnostics", "screen", "pixelRatio"],
                    "msg": "Input should be a valid number",
                    "input": null
                }
            ])
        );
        let optional_nulls = diagnostic_body(valid_screen.clone(), serde_json::json!([]));
        let optional_nulls_value: serde_json::Value =
            serde_json::from_slice(&optional_nulls).expect("golden body json");
        let mut optional_nulls_object = optional_nulls_value.as_object().expect("object").clone();
        optional_nulls_object["diagnostics"]["performance"] = serde_json::json!({
            "domContentLoaded": null,
            "loadComplete": null
        });
        let optional_null_bytes = serde_json::to_vec(&optional_nulls_object).expect("body");
        assert!(parse_request(&optional_null_bytes).is_ok());

        // (2) List positions in nested loc arrays are JSON numbers.
        assert_eq!(
            detail(&diagnostic_body(
                valid_screen.clone(),
                serde_json::json!([{}])
            )),
            serde_json::json!([
                {
                    "type": "missing",
                    "loc": ["body", "diagnostics", "errors", 0, "message"],
                    "msg": "Field required",
                    "input": {}
                },
                {
                    "type": "missing",
                    "loc": ["body", "diagnostics", "errors", 0, "timestamp"],
                    "msg": "Field required",
                    "input": {}
                }
            ])
        );
        assert_eq!(
            detail(&diagnostic_body(
                valid_screen,
                serde_json::json!([
                    {"message": "ok", "timestamp": "t"},
                    {"message": 3, "timestamp": false}
                ])
            )),
            serde_json::json!([
                {
                    "type": "string_type",
                    "loc": ["body", "diagnostics", "errors", 1, "message"],
                    "msg": "Input should be a valid string",
                    "input": 3
                },
                {
                    "type": "string_type",
                    "loc": ["body", "diagnostics", "errors", 1, "timestamp"],
                    "msg": "Input should be a valid string",
                    "input": false
                }
            ])
        );

        // (3) json_invalid loc is the character offset from the start of the
        // body: single-line, multi-line, non-ASCII (chars vs bytes), both
        // combined, and EOF after a newline.
        let json_cases: Vec<(&str, &[u8], usize, &str)> = vec![
            (
                "single line",
                b"{not json",
                1,
                "Expecting property name enclosed in double quotes",
            ),
            (
                "multi line",
                b"{\n  \"title\": \"Bug\",\n  \"description\": \"Details\",\n  \"diagnostics\": {\"oops\": }\n}",
                74,
                "Expecting value",
            ),
            (
                "non-ASCII",
                "{\"title\": \"café 😀\", \"description\": \"d\", \"diagnostics\": {\"oops\": }}"
                    .as_bytes(),
                64,
                "Expecting value",
            ),
            (
                "non-ASCII multi line",
                "{\n  \"title\": \"café 😀\",\n  \"description\": \"d\",\n  \"diagnostics\": {\"oops\": }\n}"
                    .as_bytes(),
                71,
                "Expecting value",
            ),
            // Python's message here is "Expecting ',' delimiter", which the
            // shared message mapper does not reproduce from serde's single
            // "EOF while parsing an object" category; pin only the loc/type
            // that this fix covers.
            ("EOF multi line", b"{\n  \"title\": \"Bug\"\n", 19, ""),
        ];
        for (name, body, pos, message) in json_cases {
            let items = detail(body);
            assert_eq!(items[0]["loc"], serde_json::json!(["body", pos]), "{name}");
            assert_eq!(items[0]["type"], "json_invalid", "{name}");
            assert_eq!(items[0]["msg"], "JSON decode error", "{name}");
            assert_eq!(items[0]["input"], serde_json::json!({}), "{name}");
            if !message.is_empty() {
                assert_eq!(items[0]["ctx"]["error"], message, "{name}");
            }
        }
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

    /// Production must return only `{"detail":"Validation failed"}` for each
    /// request-validation failure class, mirroring FastAPI's
    /// RequestValidationError handler in production (no validation internals).
    /// Detailed `detail[]` remains the non-production shape (golden tables).
    #[tokio::test]
    async fn production_sanitizes_validation_errors_to_generic_detail() {
        use crate::config::Environment;
        use axum::body::to_bytes;

        // Bodies covering each required validation failure class.
        let cases: Vec<(&str, Vec<u8>)> = vec![
            ("missing body", Vec::new()),
            ("json_invalid", b"{not json".to_vec()),
            (
                "float_type",
                serde_json::to_vec(&serde_json::json!({
                    "title": "Bug",
                    "description": "Details",
                    "diagnostics": {
                        "timestamp": "t",
                        "url": "u",
                        "userAgent": "a",
                        "screen": {"width": 390, "height": 844, "pixelRatio": null},
                        "viewport": {"width": 390, "height": 664},
                        "scroll": {"x": 0, "y": 1},
                        "performance": {},
                        "errors": []
                    }
                }))
                .unwrap(),
            ),
            (
                "int parsing",
                serde_json::to_vec(&serde_json::json!({
                    "title": "Bug",
                    "description": "Details",
                    "diagnostics": {
                        "timestamp": "t",
                        "url": "u",
                        "userAgent": "a",
                        "screen": {"width": "abc", "height": 844, "pixelRatio": 3},
                        "viewport": {"width": 390, "height": 664},
                        "scroll": {"x": 0, "y": 1},
                        "performance": {},
                        "errors": []
                    }
                }))
                .unwrap(),
            ),
            (
                "nested list errors",
                serde_json::to_vec(&serde_json::json!({
                    "title": "Bug",
                    "description": "Details",
                    "diagnostics": {
                        "timestamp": "t",
                        "url": "u",
                        "userAgent": "a",
                        "screen": {"width": 390, "height": 844, "pixelRatio": 3},
                        "viewport": {"width": 390, "height": 664},
                        "scroll": {"x": 0, "y": 1},
                        "performance": {},
                        "errors": [{}]
                    }
                }))
                .unwrap(),
            ),
        ];

        // Production state: parse-level validation is sanitized before any DB
        // access, so a lazy pool against a dummy TLS-required URL is sufficient.
        let config = crate::config::Config::from_lookup(|name| match name {
            "RUST_ROLL_ENV" => Some("production".into()),
            "RUST_ROLL_DATABASE_URL" => {
                Some("postgresql://reader:password@localhost/unused?sslmode=require".into())
            }
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        })
        .expect("production test config");
        assert_eq!(config.environment, Environment::Production);
        let state = Arc::new(AppState::new(config).expect("production test state"));

        for (name, body) in cases {
            let error = create_with_issuer(
                state.clone(),
                1,
                Bytes::from(body),
                &|_: GithubSettings, _: String, _: String, _: Vec<String>| -> GithubFuture {
                    Box::pin(async { panic!("issuer must not run for validation failures") })
                },
            )
            .await
            .expect_err(name);
            assert_eq!(error.status(), StatusCode::UNPROCESSABLE_ENTITY, "{name}");
            let response = error.into_response();
            assert_eq!(
                response.status(),
                StatusCode::UNPROCESSABLE_ENTITY,
                "{name}"
            );
            let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
            let payload: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
            assert_eq!(
                payload,
                serde_json::json!({"detail": "Validation failed"}),
                "{name}"
            );
        }
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
        // The test-configured app must hold the recording fake outbound
        // client, so this call can never reach the real GitHub API (#5339).
        let fake = state
            .recording_fake()
            .expect("test state must install the recording fake outbound client");
        assert!(state.outbound.is_fake());
        fake.clear();
        let error = create(
            State(state.clone()),
            AuthenticatedUser::for_test(1101),
            Bytes::from(r#"{"title":"Something broke","description":"Details"}"#),
        )
        .await
        .expect_err("the recording fake must fail closed so the claim rolls back");
        assert_eq!(error.status(), StatusCode::BAD_GATEWAY);

        // The fake received exactly one GitHub issue creation carrying the
        // submitted report, and opened no socket.
        let calls = fake.calls();
        assert_eq!(calls.len(), 1, "the fake must record the issuer call");
        assert_eq!(calls[0].host, "api.github.com");
        assert_eq!(calls[0].method, "POST");
        assert!(
            calls[0].path.starts_with("/repos/") && calls[0].path.ends_with("/issues"),
            "unexpected GitHub path {}",
            calls[0].path
        );
        let sent: serde_json::Value =
            serde_json::from_slice(&calls[0].body).expect("recorded GitHub payload is JSON");
        assert_eq!(sent["title"], "Something broke");
        assert!(sent["body"]
            .as_str()
            .is_some_and(|body| body.contains("Details")));

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

    /// Pydantic-lax numeric diagnostics must pass request validation at the
    /// real handler boundary so the issue is filed (reaches the issuer) just
    /// like Python, instead of being stopped by a fabricated `value_error` 422.
    /// The synthetic issuer fails, so success here is a 502 after validation —
    /// a 422 would mean the lax values were still rejected.
    #[tokio::test]
    async fn lax_numeric_diagnostics_reach_the_issuer_in_disposable_postgres() {
        use crate::{db, test_support};

        let state = test_support::test_state(2)
            .await
            .expect("RUST_ROLL_TEST_DATABASE_URL is required");
        let _guard = test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username, is_admin) VALUES (1102, 'bug-reports-lax-test', false);",
            )
            .await
            .expect("seed lax bug reports user");
        drop(connection);

        let _env = TempGitHubEnv::install();
        let probe = IssuerProbe::new();
        let error = create_with_issuer(
            state.clone(),
            1102,
            Bytes::from(
                br#"{"title":"Bug","description":"Details","diagnostics":{"timestamp":"t","url":"u","userAgent":"a","screen":{"width":"5","height":true,"pixelRatio":"2.5"},"viewport":{"width":3.0,"height":"4"},"scroll":{"x":"0","y":5.0},"performance":{"domContentLoaded":"2","loadComplete":true},"errors":[]}}"#
                    .to_vec(),
            ),
            &probe.issuer("SYNTHETIC_ISSUER_FAILURE"),
        )
        .await
        .expect_err("synthetic issuer must fail so the request reaches filing");
        assert_eq!(
            error.status(),
            StatusCode::BAD_GATEWAY,
            "lax diagnostics must clear Pydantic validation and reach the issuer, not return a fabricated 422"
        );
        probe.assert_issued_via_fake(&error);
        // The coerced Pydantic values, not the raw wire strings, reach the
        // issue body builder that the real issuer would have called.
        let issued_body = probe.captured_body();
        assert!(
            issued_body.contains("**Screen:** 5×1 @2.5x"),
            "{issued_body}"
        );
        assert!(issued_body.contains("**Viewport:** 3×4"), "{issued_body}");
        assert!(issued_body.contains("**Scroll:** (0, 5)"), "{issued_body}");
        assert!(
            issued_body.contains("**Performance:** DOMContentLoaded: 2ms, Load: 1ms"),
            "{issued_body}"
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
