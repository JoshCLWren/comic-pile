//! Native cutover of browser-called users/me preferences (v2) and same-path
//! Taste Bank signal operations (v1, #4834, parent #4335).
//!
//! Preferences are served as Rust `/api/v2/users/me/preferences`; the frontend
//! no longer calls `/api/v1/users/me/preferences`. Taste Bank signals remain
//! same-path v1 until their own v2 migration:
//!
//! * `GET /api/v2/users/me/preferences`
//! * `PATCH /api/v2/users/me/preferences`
//! * `GET /api/v1/users/me/taste-signals`
//! * `PUT /api/v1/users/me/taste-signals/{signal_type}/{external_key}/verdict`
//!
//! Night Shift is the sole application-wide visual identity (#5980). The
//! preferences endpoints therefore expose only the authenticated user id and
//! never read, validate, default, or persist the retired theme column. The
//! endpoint remains available for unrelated preference fields without a schema
//! migration. Taste Bank keeps its canonical signal ordering, verdict upsert,
//! and 422 validation for signal types, verdicts, and oversized keys.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    Json,
};
use serde::{Deserialize, Serialize};
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

pub const SIGNAL_TYPES: [&str; 5] = ["creator", "character", "team", "publisher", "era"];
pub const VERDICTS: [&str; 3] = ["confirmed", "sometimes", "rejected"];

/// Current preference values for the authenticated user.
///
/// Night Shift is fixed, so no appearance field is exposed. The user id keeps
/// the existing endpoint shape available for unrelated preference fields.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct UserPreferencesResponse {
    pub user_id: i32,
}

/// Partial update of the authenticated user's preferences.
///
/// The request is intentionally empty. Serde ignores legacy unknown fields, so
/// an older client that still sends `theme` cannot restore or persist a retired
/// appearance preference.
#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
pub struct UserPreferencesPatchRequest {}

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

/// Explicit user verdict on one Taste Bank signal.
#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
pub struct TasteVerdictRequest {
    pub verdict: String,
}

fn unprocessable(detail: &str) -> ApiError {
    ApiError::Unprocessable(detail.to_string())
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
/// Night Shift is fixed. This returns only the authenticated user id and does
/// not consult the retired `user_preferences.theme` column.
pub async fn get_user_preferences(
    user: AuthenticatedUser,
) -> Result<Json<UserPreferencesResponse>, ApiError> {
    Ok(Json(UserPreferencesResponse {
        user_id: user.id(),
    }))
}

/// `PATCH /api/v2/users/me/preferences`
///
/// The request has no writable appearance fields. Legacy unknown fields are
/// ignored by Serde, and no preference row is read, seeded, or updated.
pub async fn patch_user_preferences(
    user: AuthenticatedUser,
    Json(_request): Json<UserPreferencesPatchRequest>,
) -> Result<Json<UserPreferencesResponse>, ApiError> {
    Ok(Json(UserPreferencesResponse {
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
        (status = 422, description = "Invalid request body"),
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
    fn legacy_theme_fields_are_ignored_without_restoring_a_preference() {
        let request: UserPreferencesPatchRequest = serde_json::from_value(serde_json::json!({
            "theme": "command-center"
        }))
        .expect("legacy unknown fields are ignored");
        let serialized = serde_json::to_value(request).expect("serializable request");
        assert_eq!(serialized, serde_json::json!({}));
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
    async fn preferences_never_read_seed_or_update_the_retired_theme_column() {
        let (_state, client, _db) = db_fixture().await;
        client
            .execute(
                "INSERT INTO user_preferences (user_id, theme) VALUES (1, 'ink-gold')",
                &[],
            )
            .await
            .expect("seed legacy preference");
        let statements_before = PREFERENCES_STATEMENTS_ISSUED.load(Ordering::Relaxed);

        let Json(read) = get_user_preferences(AuthenticatedUser::for_test(1))
            .await
            .expect("preferences read must succeed");
        let Json(patched) = patch_user_preferences(
            AuthenticatedUser::for_test(1),
            Json(UserPreferencesPatchRequest {}),
        )
        .await
        .expect("empty patch must succeed");

        assert_eq!(read.user_id, 1);
        assert_eq!(patched.user_id, 1);
        assert_eq!(
            serde_json::to_value(read).expect("serializable response"),
            serde_json::json!({ "user_id": 1 })
        );
        let row = client
            .query_one("SELECT theme FROM user_preferences WHERE user_id=1", &[])
            .await
            .expect("legacy preference remains untouched");
        assert_eq!(row.get::<_, String>(0), "ink-gold");
        let rows = client
            .query_one("SELECT COUNT(*) FROM user_preferences WHERE user_id=2", &[])
            .await
            .expect("missing preference count");
        assert_eq!(rows.get::<_, i64>(0), 0);
        assert_eq!(
            PREFERENCES_STATEMENTS_ISSUED.load(Ordering::Relaxed),
            statements_before
        );
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
}
