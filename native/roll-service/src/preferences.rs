//! Native cutover of browser-called users/me preferences (v2), same-path
//! Taste Bank signal operations (v1, #4834, parent #4335) and the canonical
//! v2 Taste Bank signal resource (#5717).
//!
//! Preferences are served as Rust `/api/v2/users/me/preferences`; the frontend
//! no longer calls `/api/v1/users/me/preferences`. Taste Bank signals are also
//! served as the canonical v2 resource; the retained v1 spellings stay mounted
//! until production acceptance retires them:
//!
//! * `GET /api/v2/users/me/preferences`
//! * `PATCH /api/v2/users/me/preferences`
//! * `PATCH /api/v2/users/me/tasteSignals/{signal_name}`
//! * `GET /api/v1/users/me/taste-signals`
//! * `PUT /api/v1/users/me/taste-signals/{signal_type}/{external_key}/verdict`
//!
//! The wire contract is preserved: the same JSON fields, the same
//! `classic` default when no preference row exists, the same
//! seed-on-empty-PATCH behaviour, the same canonical Taste Bank signal
//! ordering (signal type, then external key), the same verdict upsert that
//! never touches inferred evidence columns, and the same 422 validation
//! status for unknown themes, signal types, verdicts and oversized keys.
//! Every operation is scoped to the authenticated owner and issues a
//! bounded constant number of statements: one read for each GET, one atomic
//! upsert for a theme write or a verdict write, and insert-then-read for the
//! empty-PATCH seeding path (matching the Python repository). There is no
//! per-row fan-out.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    body::Bytes,
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};
use tokio_postgres::Row;

/// Handler-level statement count for the preferences operations.
///
/// This counts only the statements the preferences handlers themselves
/// issue (authentication performs its own bounded lookup), so the focused
/// parity runner can prove each request stays at a constant budget.
pub static PREFERENCES_STATEMENTS_ISSUED: AtomicU64 = AtomicU64::new(0);

/// Handler-level statement count for the Taste Bank signal operations.
///
/// Same caveat as [`PREFERENCES_STATEMENTS_ISSUED`]: it counts the
/// handler's own statement, not every statement the server may execute for
/// the connection or for authentication.
pub static TASTE_STATEMENTS_ISSUED: AtomicU64 = AtomicU64::new(0);

pub const DEFAULT_THEME: &str = "classic";
pub const SUPPORTED_THEMES: [&str; 3] = ["classic", "ink-gold", "command-center"];
pub const SIGNAL_TYPES: [&str; 5] = ["creator", "character", "team", "publisher", "era"];
pub const VERDICTS: [&str; 3] = ["confirmed", "sometimes", "rejected"];

/// Current preference values for the authenticated user.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct UserPreferencesResponse {
    pub theme: String,
    pub user_id: i32,
}

/// Partial update of the authenticated user's preferences.
///
/// `theme` is optional: when omitted or explicit JSON null the current
/// preference is left unchanged and a missing row is seeded with the
/// default, exactly like the Python `UserPreferencesPatchRequest`.
#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
pub struct UserPreferencesPatchRequest {
    pub theme: Option<String>,
}

/// Canonical representation of one persisted Taste Bank signal.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct TasteSignalResponse {
    pub user_id: i32,
    pub signal_type: String,
    pub external_key: String,
    pub display_name: String,
    pub affinity_estimate: Option<f64>,
    pub confidence: Option<f64>,
    pub evidence_count: i32,
    pub distinct_thread_count: i32,
    pub user_verdict: Option<String>,
    pub verdict_at: Option<String>,
    pub first_observed_at: Option<String>,
    pub last_observed_at: Option<String>,
    pub last_prompted_at: Option<String>,
}

/// All Taste Bank signals owned by the authenticated user.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct TasteSignalListResponse {
    pub signals: Vec<TasteSignalResponse>,
}

/// Explicit user verdict on one Taste Bank signal (retained v1 spelling).
#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
pub struct TasteVerdictRequest {
    pub verdict: String,
}

/// AIP-134 partial update of the canonical v2 Taste Bank signal resource.
///
/// Only `user_verdict` is patchable. An explicit `update_mask` restricts the
/// write to the named field; a masked field missing from the body clears the
/// verdict. Without a mask, an omitted verdict leaves the signal untouched.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct TasteSignalPatchRequest {
    pub user_verdict: Option<String>,
    pub update_mask: Option<Vec<String>>,
}

/// The only field a caller may name in a Taste Bank signal `update_mask`.
pub const TASTE_SIGNAL_PATCH_FIELDS: [&str; 1] = ["user_verdict"];

/// Canonical stable name for the composite `(signal_type, external_key)`
/// identity. The whole name is one path segment, URL-encoded by the client;
/// a `:` separator keeps colon-shaped external keys intact (#5717).
pub fn taste_signal_name(signal_type: &str, external_key: &str) -> String {
    format!("{signal_type}:{external_key}")
}

/// Decode a canonical signal name into its two typed identity parts.
///
/// Splitting at the *first* colon is deliberate: external keys such as
/// `creator:writer:alan-moore` are themselves colon-shaped. Both parts keep the
/// v1 validators, so the v2 resource reports the same 422 details for an
/// unknown type or an oversized key.
pub fn parse_taste_signal_name(raw: &str) -> Result<(String, String), ApiError> {
    let (signal_type, external_key) = raw.split_once(':').ok_or_else(|| {
        unprocessable("signal_name must be <signal_type>:<external_key>")
    })?;
    validate_signal_type(signal_type)?;
    validate_external_key(external_key)?;
    Ok((signal_type.to_owned(), external_key.to_owned()))
}

fn unprocessable(detail: &str) -> ApiError {
    ApiError::Unprocessable(detail.to_string())
}

/// Validate an optional theme exactly like the Python `ThemeId` literal.
fn validate_theme(theme: Option<String>) -> Result<Option<String>, ApiError> {
    match theme {
        None => Ok(None),
        Some(value) if SUPPORTED_THEMES.contains(&value.as_str()) => Ok(Some(value)),
        Some(_) => Err(unprocessable(
            "theme must be one of classic, ink-gold, command-center",
        )),
    }
}

/// Validate a Taste Bank signal type exactly like the Python literal.
fn validate_signal_type(signal_type: &str) -> Result<(), ApiError> {
    if SIGNAL_TYPES.contains(&signal_type) {
        Ok(())
    } else {
        Err(unprocessable(
            "signal_type must be one of creator, character, team, publisher, era",
        ))
    }
}

/// Validate a Taste Bank verdict exactly like the Python literal.
fn validate_verdict(verdict: &str) -> Result<(), ApiError> {
    if VERDICTS.contains(&verdict) {
        Ok(())
    } else {
        Err(unprocessable(
            "verdict must be one of confirmed, sometimes, rejected",
        ))
    }
}

/// Validate an external key exactly like the Python path constraint
/// (`min_length=1, max_length=255`).
fn validate_external_key(external_key: &str) -> Result<(), ApiError> {
    let length = external_key.chars().count();
    if (1..=255).contains(&length) {
        Ok(())
    } else {
        Err(unprocessable(
            "external_key must be between 1 and 255 characters",
        ))
    }
}

/// Derive the display name for a newly created signal, matching Python:
/// the segment after the final `:` when non-empty, otherwise the whole
/// key, truncated to 200 characters.
fn display_name_for(external_key: &str) -> String {
    let after_colon = external_key.rsplit(':').next().unwrap_or(external_key);
    let source = if after_colon.is_empty() {
        external_key
    } else {
        after_colon
    };
    source.chars().take(200).collect()
}

/// Python-compatible ISO-8601 timestamp spelling for one `timestamptz`
/// column (`Z` suffix; the fractional part is omitted on whole seconds,
/// mirroring the projection used by the other native v2 resources).
fn iso_timestamp(column: &str) -> String {
    format!(
        "CASE WHEN {column} IS NULL THEN NULL \
         WHEN date_trunc('second', {column}) = {column} \
         THEN to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         ELSE to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') END"
    )
}

fn taste_signal_columns() -> String {
    format!(
        "user_id, signal_type, external_key, display_name, affinity_estimate, \
         confidence, evidence_count, distinct_thread_count, user_verdict, \
         {}, {}, {}, {}",
        iso_timestamp("verdict_at"),
        iso_timestamp("first_observed_at"),
        iso_timestamp("last_observed_at"),
        iso_timestamp("last_prompted_at"),
    )
}

fn taste_signal_from_row(row: &Row) -> TasteSignalResponse {
    TasteSignalResponse {
        user_id: row.get(0),
        signal_type: row.get(1),
        external_key: row.get(2),
        display_name: row.get(3),
        affinity_estimate: row.get(4),
        confidence: row.get(5),
        evidence_count: row.get(6),
        distinct_thread_count: row.get(7),
        user_verdict: row.get(8),
        verdict_at: row.get(9),
        first_observed_at: row.get(10),
        last_observed_at: row.get(11),
        last_prompted_at: row.get(12),
    }
}

/// `GET /api/v2/users/me/preferences`
///
/// Returns the persisted theme, resolving to `classic` when no preference
/// row exists yet, exactly like the Python service.
pub async fn get_user_preferences(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<UserPreferencesResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let row = connection
        .query_opt(
            "SELECT theme FROM user_preferences WHERE user_id = $1",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    PREFERENCES_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed);
    let theme: String = row
        .map(|row| row.get::<_, String>(0))
        .unwrap_or_else(|| DEFAULT_THEME.to_string());
    Ok(Json(UserPreferencesResponse {
        theme,
        user_id: user.id(),
    }))
}

/// `PATCH /api/v2/users/me/preferences`
///
/// A present theme is applied as a single atomic upsert so overlapping
/// first-time writes resolve as updates instead of surfacing a unique
/// violation (issue #1872). An omitted or explicit-null theme leaves an
/// existing row unchanged and seeds a missing row with the default.
pub async fn patch_user_preferences(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<UserPreferencesPatchRequest>,
) -> Result<Json<UserPreferencesResponse>, ApiError> {
    let theme = validate_theme(request.theme)?;
    let connection = db::checkout(&state).await?;
    let persisted_theme = match theme {
        Some(theme) => {
            let row = connection
                .query_one(
                    "INSERT INTO user_preferences (user_id, theme, created_at, updated_at) \
                     VALUES ($1, $2, NOW(), NOW()) \
                     ON CONFLICT (user_id) DO UPDATE \
                     SET theme = EXCLUDED.theme, updated_at = NOW() \
                     RETURNING theme",
                    &[&user.id(), &theme],
                )
                .await
                .map_err(db::query_error)?;
            PREFERENCES_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed);
            row.get::<_, String>(0)
        }
        None => {
            connection
                .execute(
                    "INSERT INTO user_preferences (user_id, theme, created_at, updated_at) \
                     VALUES ($1, $2, NOW(), NOW()) \
                     ON CONFLICT (user_id) DO NOTHING",
                    &[&user.id(), &DEFAULT_THEME],
                )
                .await
                .map_err(db::query_error)?;
            PREFERENCES_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed);
            let row = connection
                .query_opt(
                    "SELECT theme FROM user_preferences WHERE user_id = $1",
                    &[&user.id()],
                )
                .await
                .map_err(db::query_error)?;
            PREFERENCES_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed);
            row.map(|row| row.get::<_, String>(0))
                .unwrap_or_else(|| DEFAULT_THEME.to_string())
        }
    };
    Ok(Json(UserPreferencesResponse {
        theme: persisted_theme,
        user_id: user.id(),
    }))
}

/// `GET /api/v1/users/me/taste-signals`
///
/// Returns every Taste Bank signal owned by the authenticated user,
/// ordered by signal type then external key.
pub async fn list_taste_signals(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<TasteSignalListResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let sql = format!(
        "SELECT {} FROM taste_signals WHERE user_id = $1 \
         ORDER BY signal_type, external_key",
        taste_signal_columns()
    );
    let rows = connection
        .query(&sql, &[&user.id()])
        .await
        .map_err(db::query_error)?;
    TASTE_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed);
    Ok(Json(TasteSignalListResponse {
        signals: rows.iter().map(taste_signal_from_row).collect(),
    }))
}

/// `PUT /api/v1/users/me/taste-signals/{signal_type}/{external_key}/verdict`
///
/// Records an explicit verdict as a single atomic upsert. Only the
/// verdict columns are written on conflict, so inferred evidence columns
/// survive every recomputation and repeated verdicts are idempotent. A
/// missing row is created with zero inferred evidence so direct user
/// assertions work without prior inference.
pub async fn set_taste_signal_verdict(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path((signal_type, external_key)): Path<(String, String)>,
    Json(request): Json<TasteVerdictRequest>,
) -> Result<Json<TasteSignalResponse>, ApiError> {
    validate_signal_type(&signal_type)?;
    validate_external_key(&external_key)?;
    validate_verdict(&request.verdict)?;
    let display_name = display_name_for(&external_key);
    let connection = db::checkout(&state).await?;
    let sql = format!(
        "INSERT INTO taste_signals \
         (user_id, signal_type, external_key, display_name, user_verdict, \
          verdict_at, first_observed_at, last_observed_at, \
          evidence_count, distinct_thread_count, created_at, updated_at) \
         VALUES ($1, $2, $3, $4, $5, NOW(), NOW(), NOW(), 0, 0, NOW(), NOW()) \
         ON CONFLICT (user_id, signal_type, external_key) DO UPDATE \
         SET user_verdict = EXCLUDED.user_verdict, \
             verdict_at = EXCLUDED.verdict_at, \
             updated_at = EXCLUDED.updated_at \
         RETURNING {}",
        taste_signal_columns()
    );
    let row = connection
        .query_one(
            &sql,
            &[
                &user.id(),
                &signal_type,
                &external_key,
                &display_name,
                &request.verdict,
            ],
        )
        .await
        .map_err(db::query_error)?;
    TASTE_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed);
    Ok(Json(taste_signal_from_row(&row)))
}

/// Resolved v2 PATCH intent for the single patchable field.
#[derive(Debug, Clone, PartialEq, Eq)]
enum VerdictPatch {
    /// No effective field was named: read the current resource, write nothing.
    Unchanged,
    /// Set (or replace) the explicit verdict.
    Set(String),
    /// Clear the explicit verdict on an existing signal.
    Clear,
}

/// Parse the AIP-134 PATCH body. Both the array and canonical comma-separated
/// `update_mask` forms are accepted; an unsupported mask field is a 422.
fn parse_taste_signal_patch(body: &[u8]) -> Result<VerdictPatch, ApiError> {
    let value: Value =
        serde_json::from_slice(body).map_err(|_| unprocessable("Validation failed"))?;
    let map = value
        .as_object()
        .ok_or_else(|| unprocessable("Validation failed"))?;

    let mask = match map.get("update_mask") {
        None | Some(Value::Null) => None,
        Some(Value::String(text)) => {
            let names: Vec<String> = text
                .split(',')
                .map(str::trim)
                .filter(|name| !name.is_empty())
                .map(str::to_owned)
                .collect();
            Some(names)
        }
        Some(Value::Array(items)) => {
            let mut names = Vec::with_capacity(items.len());
            for item in items {
                let name = item
                    .as_str()
                    .ok_or_else(|| unprocessable("Validation failed"))?;
                names.push(name.to_owned());
            }
            Some(names)
        }
        Some(_) => return Err(unprocessable("Validation failed")),
    };
    if let Some(names) = &mask {
        for name in names {
            if !TASTE_SIGNAL_PATCH_FIELDS.contains(&name.as_str()) {
                return Err(unprocessable(&format!("Unsupported field mask: {name}")));
            }
        }
    }
    let masked = mask
        .as_ref()
        .is_some_and(|names| names.iter().any(|name| name == "user_verdict"));

    let verdict_value = map.get("user_verdict");
    let verdict_present = verdict_value.is_some_and(|value| !value.is_null());
    match (mask.as_ref(), masked, verdict_present) {
        (None, _, true) | (Some(_), true, true) => {
            let verdict = verdict_value
                .and_then(Value::as_str)
                .ok_or_else(|| unprocessable("Validation failed"))?;
            validate_verdict(verdict)?;
            Ok(VerdictPatch::Set(verdict.to_owned()))
        }
        (Some(_), true, false) => Ok(VerdictPatch::Clear),
        _ => Ok(VerdictPatch::Unchanged),
    }
}

/// `PATCH /api/v2/users/me/tasteSignals/{signal_name}`
///
/// The resource name is one stable string segment (`<signal_type>:<external_key>`)
/// rather than two untyped identity segments. Ownership is part of every
/// `WHERE` clause, so a name belonging to another reader cannot be observed or
/// changed. Repeated identical verdicts are idempotent: `verdict_at` and
/// `updated_at` are not churned, and inferred evidence columns are never
/// written. No reading-history or rating table is touched.
pub async fn patch_taste_signal_v2(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(raw_name): Path<String>,
    body: Bytes,
) -> Result<Json<TasteSignalResponse>, ApiError> {
    let (signal_type, external_key) = parse_taste_signal_name(&raw_name)?;
    let patch = parse_taste_signal_patch(&body)?;
    let display_name = display_name_for(&external_key);
    let connection = db::checkout(&state).await?;

    let row = match patch {
        VerdictPatch::Set(verdict) => {
            let sql = format!(
                "INSERT INTO taste_signals \
                 (user_id, signal_type, external_key, display_name, user_verdict, \
                  verdict_at, first_observed_at, last_observed_at, \
                  evidence_count, distinct_thread_count, created_at, updated_at) \
                 VALUES ($1, $2, $3, $4, $5, NOW(), NOW(), NOW(), 0, 0, NOW(), NOW()) \
                 ON CONFLICT (user_id, signal_type, external_key) DO UPDATE \
                 SET user_verdict = EXCLUDED.user_verdict, \
                     verdict_at = CASE WHEN taste_signals.user_verdict IS DISTINCT FROM EXCLUDED.user_verdict \
                         THEN NOW() ELSE taste_signals.verdict_at END, \
                     updated_at = CASE WHEN taste_signals.user_verdict IS DISTINCT FROM EXCLUDED.user_verdict \
                         THEN NOW() ELSE taste_signals.updated_at END \
                 RETURNING {}",
                taste_signal_columns()
            );
            connection
                .query_opt(
                    &sql,
                    &[
                        &user.id(),
                        &signal_type,
                        &external_key,
                        &display_name,
                        &verdict,
                    ],
                )
                .await
                .map_err(db::query_error)?
        }
        VerdictPatch::Clear => {
            let sql = format!(
                "UPDATE taste_signals SET user_verdict = NULL, verdict_at = NULL, updated_at = NOW() \
                 WHERE user_id = $1 AND signal_type = $2 AND external_key = $3 \
                 RETURNING {}",
                taste_signal_columns()
            );
            connection
                .query_opt(&sql, &[&user.id(), &signal_type, &external_key])
                .await
                .map_err(db::query_error)?
        }
        VerdictPatch::Unchanged => {
            let sql = format!(
                "SELECT {} FROM taste_signals \
                 WHERE user_id = $1 AND signal_type = $2 AND external_key = $3",
                taste_signal_columns()
            );
            connection
                .query_opt(&sql, &[&user.id(), &signal_type, &external_key])
                .await
                .map_err(db::query_error)?
        }
    };
    TASTE_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed);
    let row = row.ok_or_else(|| {
        ApiError::with_status(
            StatusCode::NOT_FOUND,
            format!("Taste signal {raw_name} not found"),
        )
    })?;
    Ok(Json(taste_signal_from_row(&row)))
}

/// Documentation-only operation for the canonical v2 Taste Bank signal PATCH.
#[utoipa::path(
    patch,
    path = "/api/v2/users/me/tasteSignals/{signal_name}",
    tag = "taste",
    operation_id = "patch_taste_signal_v2",
    description = "Partially update one owned Taste Bank signal (AIP-134). The resource name is the stable composite <signal_type>:<external_key> encoded as one path segment. Only user_verdict is patchable; an update_mask restricts the write, and a masked-but-absent verdict clears it. Repeated identical verdicts are idempotent and inferred evidence is never mutated.",
    params(("signal_name" = String, Path, description = "Stable composite signal name, URL-encoded")),
    request_body = TasteSignalPatchRequest,
    responses(
        (status = 200, description = "Canonical signal after the patch", body = TasteSignalResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Taste signal not found"),
        (status = 422, description = "Validation failed"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn patch_taste_signal_v2_documentation() {}

/// OpenAPI document for the native same-path Taste Bank signal surface (v1).
///
/// Preferences v2 operations are documented in the canonical v2 OpenAPI.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(
        list_taste_signals_documentation,
        set_taste_signal_verdict_documentation
    ),
    components(schemas(
        TasteSignalResponse,
        TasteSignalListResponse,
        TasteVerdictRequest
    )),
    modifiers(&PreferencesSecurityAddon)
)]
pub struct PreferencesApi;

struct PreferencesSecurityAddon;
impl utoipa::Modify for PreferencesSecurityAddon {
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

/// Documentation-only operation for reading user preferences.
#[utoipa::path(
    get,
    path = "/api/v2/users/me/preferences",
    tag = "users",
    responses(
        (status = 200, description = "The authenticated user's preferences", body = UserPreferencesResponse),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub(crate) fn get_user_preferences_documentation() {}

/// Documentation-only operation for updating user preferences.
#[utoipa::path(
    patch,
    path = "/api/v2/users/me/preferences",
    tag = "users",
    request_body = UserPreferencesPatchRequest,
    responses(
        (status = 200, description = "The user's preferences after the update", body = UserPreferencesResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Unknown theme id"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub(crate) fn patch_user_preferences_documentation() {}

/// Documentation-only operation for listing Taste Bank signals.
#[utoipa::path(
    get,
    path = "/api/v1/users/me/taste-signals",
    tag = "taste-signals",
    responses(
        (status = 200, description = "Every Taste Bank signal owned by the authenticated user", body = TasteSignalListResponse),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn list_taste_signals_documentation() {}

/// Documentation-only operation for recording a Taste Bank verdict.
#[utoipa::path(
    put,
    path = "/api/v1/users/me/taste-signals/{signal_type}/{external_key}/verdict",
    tag = "taste-signals",
    params(
        ("signal_type" = String, Path, description = "Category of the targeted signal"),
        ("external_key" = String, Path, description = "Stable normalized key of the targeted feature")
    ),
    request_body = TasteVerdictRequest,
    responses(
        (status = 200, description = "The canonical updated signal after the verdict is persisted", body = TasteSignalResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Unknown signal type, verdict, or oversized external key"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn set_taste_signal_verdict_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::StatusCode;
    use utoipa::OpenApi;

    #[test]
    fn supported_themes_are_accepted_and_unknown_themes_are_422() {
        for theme in SUPPORTED_THEMES {
            assert_eq!(
                validate_theme(Some(theme.to_string())).expect("supported theme"),
                Some(theme.to_string())
            );
        }
        assert_eq!(validate_theme(None).expect("omitted theme"), None);
        let error = validate_theme(Some("neon-pink".to_string()))
            .expect_err("unknown theme must be rejected");
        assert_eq!(error.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[test]
    fn signal_types_and_verdicts_match_the_python_literals() {
        for signal_type in SIGNAL_TYPES {
            assert!(validate_signal_type(signal_type).is_ok());
        }
        assert_eq!(
            validate_signal_type("color")
                .expect_err("unknown signal type")
                .status(),
            StatusCode::UNPROCESSABLE_ENTITY
        );
        for verdict in VERDICTS {
            assert!(validate_verdict(verdict).is_ok());
        }
        assert_eq!(
            validate_verdict("love-it")
                .expect_err("unknown verdict")
                .status(),
            StatusCode::UNPROCESSABLE_ENTITY
        );
    }

    #[test]
    fn external_keys_follow_the_python_length_bounds() {
        assert!(validate_external_key("creator:writer:dk").is_ok());
        assert!(validate_external_key("").is_err());
        assert!(validate_external_key(&"x".repeat(255)).is_ok());
        assert!(validate_external_key(&"x".repeat(256)).is_err());
    }

    #[test]
    fn stable_signal_name_round_trips_colon_shaped_external_keys() {
        let name = taste_signal_name("creator", "creator:writer:dk");
        assert_eq!(name, "creator:creator:writer:dk");
        assert_eq!(
            parse_taste_signal_name(&name).expect("canonical name"),
            ("creator".to_string(), "creator:writer:dk".to_string())
        );
        assert_eq!(
            parse_taste_signal_name("era:1990s").expect("simple key"),
            ("era".to_string(), "1990s".to_string())
        );
        for invalid in ["no-separator", "color:red", "creator:", ":missing-type"] {
            assert_eq!(
                parse_taste_signal_name(invalid)
                    .expect_err("malformed composite name")
                    .status(),
                StatusCode::UNPROCESSABLE_ENTITY,
                "name={invalid}"
            );
        }
        let oversized = format!("creator:{}", "x".repeat(256));
        assert_eq!(
            parse_taste_signal_name(&oversized)
                .expect_err("oversized key")
                .status(),
            StatusCode::UNPROCESSABLE_ENTITY
        );
    }

    #[test]
    fn patch_body_supports_masks_and_preserves_aip134_semantics() {
        let set = parse_taste_signal_patch(br#"{"user_verdict":"sometimes","update_mask":["user_verdict"]}"#)
            .expect("masked set");
        assert_eq!(set, VerdictPatch::Set("sometimes".to_string()));
        assert_eq!(
            parse_taste_signal_patch(br#"{"user_verdict":"rejected"}"#).expect("presence set"),
            VerdictPatch::Set("rejected".to_string())
        );
        assert_eq!(
            parse_taste_signal_patch(br#"{"update_mask":"user_verdict"}"#).expect("string mask clears"),
            VerdictPatch::Clear
        );
        assert_eq!(
            parse_taste_signal_patch(br#"{"update_mask":["user_verdict"],"user_verdict":null}"#)
                .expect("explicit null clears"),
            VerdictPatch::Clear
        );
        assert_eq!(
            parse_taste_signal_patch(b"{}").expect("empty patch"),
            VerdictPatch::Unchanged
        );
        for invalid in [
            br#"{"user_verdict":"love-it"}"#.as_slice(),
            br#"{"update_mask":["theme"]}"#,
            br#"{"update_mask":42}"#,
            b"[]",
        ] {
            assert_eq!(
                parse_taste_signal_patch(invalid)
                    .expect_err("invalid patch")
                    .status(),
                StatusCode::UNPROCESSABLE_ENTITY
            );
        }
    }

    #[test]
    fn display_name_derivation_matches_the_python_handler() {
        assert_eq!(display_name_for("creator:writer:dk"), "dk");
        assert_eq!(display_name_for("plain-key"), "plain-key");
        assert_eq!(display_name_for("creator:writer:"), "creator:writer:");
        let long = format!("prefix:{}", "y".repeat(250));
        assert_eq!(display_name_for(&long).chars().count(), 200);
    }

    #[test]
    fn preferences_openapi_documents_every_same_path_operation() {
        let document = serde_json::to_value(PreferencesApi::openapi()).expect("OpenAPI");
        let paths = document["paths"].as_object().expect("paths");
        let mut operations: Vec<(String, String)> = paths
            .iter()
            .flat_map(|(path, item)| {
                item.as_object()
                    .expect("path item")
                    .keys()
                    .map(move |method| (method.clone(), path.clone()))
            })
            .collect();
        operations.sort();
        assert_eq!(
            operations,
            vec![
                (
                    "get".to_string(),
                    "/api/v1/users/me/taste-signals".to_string()
                ),
                (
                    "put".to_string(),
                    "/api/v1/users/me/taste-signals/{signal_type}/{external_key}/verdict"
                        .to_string()
                ),
            ]
        );
        for schema in [
            "TasteSignalResponse",
            "TasteSignalListResponse",
            "TasteVerdictRequest",
        ] {
            assert!(
                document["components"]["schemas"].get(schema).is_some(),
                "missing schema {schema}"
            );
        }
    }

    #[test]
    fn checked_in_openapi_contract_is_current() {
        let checked_in = include_str!("../../../native/contracts/preferences-v1.openapi.json");
        let generated = PreferencesApi::openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document");
        assert_eq!(
            checked_in.trim_end(),
            generated.trim_end(),
            "Regenerate native/contracts/preferences-v1.openapi.json with \
             cargo run --example preferences_openapi"
        );
    }

    async fn db_fixture() -> (
        std::sync::Arc<AppState>,
        tokio_postgres::Client,
        tokio::sync::MutexGuard<'static, ()>,
    ) {
        let _admin = crate::test_support::required_test_admin_url();
        let url = crate::test_support::database_url().await;
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let guard = crate::test_support::reset_for_test(&state).await;
        let (client, connection) = tokio_postgres::connect(&url, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        client
            .batch_execute("INSERT INTO users (id, username) VALUES (1, 'reader-1')")
            .await
            .expect("seed reader");
        (state, client, guard)
    }

    #[tokio::test]
    async fn patch_user_preferences_persists_then_preserves_the_theme() {
        let (state, client, _db) = db_fixture().await;
        let Json(first) = patch_user_preferences(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Json(UserPreferencesPatchRequest {
                theme: Some("ink-gold".into()),
            }),
        )
        .await
        .expect("theme patch must succeed");
        assert_eq!(first.theme, "ink-gold");
        let Json(second) = patch_user_preferences(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Json(UserPreferencesPatchRequest { theme: None }),
        )
        .await
        .expect("omitted theme must preserve the row");
        assert_eq!(second.theme, "ink-gold");
        let row = client
            .query_one("SELECT theme FROM user_preferences WHERE user_id=1", &[])
            .await
            .expect("persisted preferences");
        assert_eq!(row.get::<_, String>(0), "ink-gold");
    }

    #[tokio::test]
    async fn set_taste_signal_verdict_persists_the_verdict() {
        use axum::extract::Path;
        let (state, client, _db) = db_fixture().await;
        let Json(signal) = set_taste_signal_verdict(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(("creator".into(), "jim-lee".into())),
            Json(TasteVerdictRequest {
                verdict: "confirmed".into(),
            }),
        )
        .await
        .expect("verdict must succeed");
        assert_eq!(signal.signal_type, "creator");
        assert_eq!(signal.external_key, "jim-lee");
        assert_eq!(signal.user_verdict.as_deref(), Some("confirmed"));
        let row = client
            .query_one(
                "SELECT user_verdict FROM taste_signals \
                 WHERE user_id=1 AND signal_type='creator' AND external_key='jim-lee'",
                &[],
            )
            .await
            .expect("persisted verdict");
        assert_eq!(
            row.get::<_, Option<String>>(0).as_deref(),
            Some("confirmed")
        );
    }

    #[tokio::test]
    async fn v2_signal_route_mounts_encoded_composite_name() {
        use crate::{config::Config, router, AppState};
        use axum::{
            body::Body,
            http::{Request, StatusCode},
        };
        use tower::ServiceExt;

        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        })
        .expect("test config");
        let app = router(Arc::new(AppState::new(config).expect("test state")));
        let response = app
            .oneshot(
                Request::builder()
                    .method("PATCH")
                    .uri("/api/v2/users/me/tasteSignals/creator%3Acreator%3Awriter%3Adk")
                    .header("content-type", "application/json")
                    .body(Body::from(r#"{"user_verdict":"confirmed"}"#))
                    .expect("request"),
            )
            .await
            .expect("router response");
        assert_eq!(
            response.status(),
            StatusCode::UNAUTHORIZED,
            "the encoded composite-name route must be mounted and authenticated"
        );
    }

    #[tokio::test]
    async fn v2_patch_is_owner_scoped_idempotent_and_verdict_only() {
        use axum::body::Bytes;
        let (state, client, _db) = db_fixture().await;
        client
            .batch_execute(
                "INSERT INTO users (id, username) VALUES (2, 'reader-2');
                 INSERT INTO taste_signals \
                   (user_id, signal_type, external_key, display_name, affinity_estimate, \
                    confidence, evidence_count, distinct_thread_count, created_at, updated_at) \
                 VALUES \
                   (1, 'creator', 'creator:writer:dk', 'dk', 0.8, 0.9, 4, 2, NOW(), NOW()), \
                   (2, 'creator', 'creator:writer:dk', 'dk', 0.5, 0.7, 9, 6, NOW(), NOW());",
            )
            .await
            .expect("seed owner and foreign taste signals");

        let name = taste_signal_name("creator", "creator:writer:dk");
        let body = Bytes::from(
            serde_json::json!({"user_verdict": "confirmed", "update_mask": ["user_verdict"]})
                .to_string(),
        );
        let Json(first) = patch_taste_signal_v2(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(name.clone()),
            body.clone(),
        )
        .await
        .expect("v2 verdict patch");
        assert_eq!(first.user_verdict.as_deref(), Some("confirmed"));
        assert_eq!(first.evidence_count, 4, "inferred evidence must survive");

        let Json(second) = patch_taste_signal_v2(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(name.clone()),
            body,
        )
        .await
        .expect("duplicate v2 verdict patch");
        assert_eq!(
            serde_json::to_value(&first).expect("first wire body"),
            serde_json::to_value(&second).expect("second wire body"),
            "identical verdicts must be byte-idempotent"
        );

        let owner = client
            .query_one(
                "SELECT user_verdict, verdict_at, evidence_count, distinct_thread_count \
                 FROM taste_signals WHERE user_id=1 AND signal_type='creator' \
                 AND external_key='creator:writer:dk'",
                &[],
            )
            .await
            .expect("owner row");
        assert_eq!(
            owner.get::<_, Option<String>>(0).as_deref(),
            Some("confirmed")
        );
        assert!(owner.get::<_, Option<chrono::DateTime<chrono::Utc>>>(1).is_some());
        assert_eq!(owner.get::<_, i32>(2), 4);
        assert_eq!(owner.get::<_, i32>(3), 2);

        let foreign = client
            .query_one(
                "SELECT user_verdict, evidence_count FROM taste_signals \
                 WHERE user_id=2 AND signal_type='creator' AND external_key='creator:writer:dk'",
                &[],
            )
            .await
            .expect("foreign row");
        assert_eq!(foreign.get::<_, Option<String>>(0), None);
        assert_eq!(foreign.get::<_, i32>(1), 9, "foreign evidence untouched");

        let Json(cleared) = patch_taste_signal_v2(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(name.clone()),
            Bytes::from(br#"{"update_mask":["user_verdict"]}"#.to_vec()),
        )
        .await
        .expect("masked verdict clear");
        assert_eq!(cleared.user_verdict, None);

        let missing = patch_taste_signal_v2(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(taste_signal_name("era", "1990s")),
            Bytes::from(br#"{"user_verdict":"confirmed"}"#.to_vec()),
        )
        .await
        .expect("direct verdict creates the owned signal");
        assert_eq!(missing.user_verdict.as_deref(), Some("confirmed"));
        assert_eq!(missing.evidence_count, 0);

        let no_fields = patch_taste_signal_v2(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(taste_signal_name("era", "1980s")),
            Bytes::from(b"{}".to_vec()),
        )
        .await
        .expect_err("a no-op patch cannot invent a signal");
        assert_eq!(no_fields.status(), StatusCode::NOT_FOUND);
    }
}
