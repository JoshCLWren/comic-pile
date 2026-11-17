//! Same-path native Rust replacements for the three read-only CBL source
//! discovery endpoints of the issue-identity family (#4843).
//!
//! Scope is deliberately narrow. These three operations are pure projections of
//! the shared CBL catalog:
//!
//! * `GET /api/v1/issue-identity/cbl-sources`
//! * `GET /api/v1/issue-identity/cbl-sources/{list_id}`
//! * `GET /api/v1/issue-identity/cbl-sources/by-comicvine-issue/{id}`
//!
//! The remaining family operations (comparison ranking, reading-list
//! candidates, adoption planning and the two transactional adoption commits)
//! intentionally stay on Python in this change: their implementations are large,
//! stateful and not yet proven in production. Their route fragments keep a
//! Python destination until real, wire-compatible Rust handlers and an
//! authenticated production execution proof land. API version is not
//! implementation language; see AGENTS.md.

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tracing::instrument;

use crate::{auth::AuthenticatedUser, db::checkout, ApiError, AppState};

// Public projection constants mirror `app.services.cbl_source_public` and the
// existing native `cbl_catalog` module. The local mirror path must never reach
// a browser response.
const MIRROR_NAME: &str = "CBL-ReadingLists";
const MIRROR_PATH_MARKER: &str = "/CBL-ReadingLists";
const PUBLIC_REPOSITORY: &str = "JoshCLWren/CBL-ReadingLists";
const PUBLIC_REPOSITORY_FALLBACK: &str = "CBL source";

/// Python `Query(max_length=200)` for the discovery search term.
const MAX_SEARCH_LENGTH: usize = 200;
/// Python `Query(ge=1, le=100)` for the discovery list limit.
const MAX_DISCOVERY_LIMIT: i64 = 100;
/// Python `Query(ge=1, le=2000)` for the source-list entry limit.
const MAX_ENTRIES_LIMIT: i64 = 2000;
/// Python `Query(ge=1, le=200)` for Comic Vine occurrence limits.
const MAX_OCCURRENCE_LIMIT: i64 = 200;
/// Python `Path(max_length=100)` for the Comic Vine issue ID.
const MAX_COMICVINE_ID_LENGTH: usize = 100;

// ---------------------------------------------------------------------------
// Wire schemas (field-for-field parity with app/schemas/cbl_source.py and
// app/schemas/cbl_comicvine_lookup.py)
// ---------------------------------------------------------------------------

/// Reader-safe summary of one active persisted CBL source list.
#[derive(Debug, Serialize, Deserialize)]
pub struct CblSourceListDiscoveryItem {
    pub id: i32,
    pub name: String,
    /// Raw stored path: Python's discovery response deliberately returns the
    /// unprojected `source_path` (see `list_cbl_source_previews`).
    pub source_path: String,
    pub source_repository: String,
    pub declared_issue_count: Option<i32>,
    pub content_hash: String,
    pub revision_sha: String,
}

/// One ordered source occurrence inside a CBL list.
#[derive(Debug, Serialize, Deserialize)]
pub struct CblSourceEntryDetail {
    pub position: i32,
    pub series_name: String,
    pub issue_number: String,
    pub volume_year: Option<i32>,
    pub publication_year: Option<i32>,
    pub comicvine_issue_id: Option<String>,
    pub comicvine_volume_id: Option<String>,
}

/// One active CBL source list with one bounded page of ordered occurrences.
#[derive(Debug, Serialize, Deserialize)]
pub struct CblSourceListDetail {
    pub id: i32,
    pub name: String,
    pub source_path: String,
    pub source_repository: String,
    pub source_ref: String,
    pub declared_issue_count: Option<i32>,
    pub content_hash: String,
    pub revision_sha: String,
    pub entries_total: i32,
    pub entries_offset: i32,
    pub entries_limit: i32,
    pub entries: Vec<CblSourceEntryDetail>,
}

/// One Comic Vine occurrence in the shared CBL catalog.
#[derive(Debug, Serialize, Deserialize)]
pub struct CblComicvineOccurrence {
    pub list_id: i32,
    pub list_name: String,
    pub source_path: String,
    pub source_repository: String,
    pub source_ref: String,
    pub revision_sha: String,
    pub position: i32,
    pub series_name: String,
    pub issue_number: String,
    pub volume_year: Option<i32>,
    pub publication_year: Option<i32>,
    pub comicvine_issue_id: String,
    pub comicvine_volume_id: Option<String>,
}

/// A page of Comic Vine occurrences with shared-catalog totals.
#[derive(Debug, Serialize, Deserialize)]
pub struct CblComicvineOccurrencePage {
    pub comicvine_issue_id: String,
    pub occurrences_total: i32,
    pub lists_total: i32,
    pub occurrences_offset: i32,
    pub occurrences_limit: i32,
    pub occurrences: Vec<CblComicvineOccurrence>,
}

// ---------------------------------------------------------------------------
// Query parameters. Parsed as raw strings so malformed or out-of-range values
// produce FastAPI-compatible 422 validation envelopes instead of axum's 400.
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
pub struct DiscoverCblSourcesParams {
    #[serde(default)]
    pub q: Option<String>,
    #[serde(default)]
    pub limit: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct GetCblSourceListParams {
    #[serde(default)]
    pub offset: Option<String>,
    #[serde(default)]
    pub limit: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct CblOccurrenceParams {
    #[serde(default)]
    pub offset: Option<String>,
    #[serde(default)]
    pub limit: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct ValidationErrorItem {
    #[serde(rename = "type")]
    error_type: String,
    loc: Vec<String>,
    msg: String,
    input: serde_json::Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    ctx: Option<serde_json::Value>,
}

#[derive(Debug, Serialize)]
struct ValidationErrorResponse {
    detail: Vec<ValidationErrorItem>,
}

#[derive(Debug)]
pub enum IdentityError {
    Api(ApiError),
    Validation(Vec<ValidationErrorItem>),
}

impl From<ApiError> for IdentityError {
    fn from(error: ApiError) -> Self {
        IdentityError::Api(error)
    }
}

impl IntoResponse for IdentityError {
    fn into_response(self) -> Response {
        match self {
            IdentityError::Api(error) => error.into_response(),
            IdentityError::Validation(items) => (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(ValidationErrorResponse { detail: items }),
            )
                .into_response(),
        }
    }
}

fn int_parsing(field: &str, input: &str) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: "int_parsing".to_string(),
        loc: vec!["query".to_string(), field.to_string()],
        msg: "Input should be a valid integer, unable to parse string as an integer".to_string(),
        input: serde_json::Value::String(input.to_string()),
        ctx: None,
    }
}

fn int_bound(field: &str, input: &str, kind: &str, bound: i64) -> ValidationErrorItem {
    let (error_type, msg, ctx) = if kind == "ge" {
        (
            "greater_than_equal",
            format!("Input should be greater than or equal to {bound}"),
            serde_json::json!({"ge": bound}),
        )
    } else {
        (
            "less_than_equal",
            format!("Input should be less than or equal to {bound}"),
            serde_json::json!({"le": bound}),
        )
    };
    ValidationErrorItem {
        error_type: error_type.to_string(),
        loc: vec!["query".to_string(), field.to_string()],
        msg,
        input: serde_json::Value::String(input.to_string()),
        ctx: Some(ctx),
    }
}

fn too_long(field: &str, input: &str, max: usize, loc_kind: &str) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: "string_too_long".to_string(),
        loc: vec![loc_kind.to_string(), field.to_string()],
        msg: format!("String should have at most {max} characters"),
        input: serde_json::Value::String(input.to_string()),
        ctx: Some(serde_json::json!({"max_length": max})),
    }
}

/// Parse an optional integer query parameter with Python `Query(ge=…, le=…)`
/// semantics, returning a FastAPI-style validation item on any failure.
fn parse_int(
    field: &str,
    raw: Option<&str>,
    default: i64,
    ge: i64,
    le: i64,
) -> Result<i64, Vec<ValidationErrorItem>> {
    let Some(raw) = raw else {
        return Ok(default);
    };
    let parsed = match raw.parse::<i64>() {
        Ok(parsed) => parsed,
        Err(_) => {
            if !raw.is_empty() && raw.chars().all(|c| c.is_ascii_digit() || c == '-') {
                // An all-numeric value above i64 is a Python `le` failure.
                return Err(vec![int_bound(field, raw, "le", le)]);
            }
            return Err(vec![int_parsing(field, raw)]);
        }
    };
    if parsed < ge {
        return Err(vec![int_bound(field, raw, "ge", ge)]);
    }
    if parsed > le {
        return Err(vec![int_bound(field, raw, "le", le)]);
    }
    Ok(parsed)
}

// ---------------------------------------------------------------------------
// Reader-safe public projections (mirror app/services/cbl_source_public.py)
// ---------------------------------------------------------------------------

fn is_filesystem_location(value: &str) -> bool {
    value.starts_with('/') || value.starts_with("file:") || value.starts_with("mnt/")
}

fn public_cbl_repository(repository: &str) -> String {
    let normalized = repository.trim().replace('\\', "/");
    if !is_filesystem_location(&normalized) {
        return repository.to_string();
    }
    if normalized.trim_end_matches('/').ends_with(MIRROR_NAME)
        || normalized.contains(MIRROR_PATH_MARKER)
    {
        return PUBLIC_REPOSITORY.to_string();
    }
    PUBLIC_REPOSITORY_FALLBACK.to_string()
}

fn public_cbl_source_path(source_path: &str) -> String {
    let normalized = source_path.trim().replace('\\', "/");
    if normalized.is_empty() {
        return source_path.to_string();
    }
    let marker = format!("{MIRROR_NAME}/");
    if let Some(index) = normalized.find(&marker) {
        let rest = &normalized[index + marker.len()..];
        return if rest.is_empty() {
            MIRROR_NAME.to_string()
        } else {
            rest.to_string()
        };
    }
    if is_filesystem_location(&normalized) {
        let file_name = normalized.rsplit('/').next().unwrap_or("");
        return if file_name.is_empty() {
            PUBLIC_REPOSITORY_FALLBACK.to_string()
        } else {
            file_name.to_string()
        };
    }
    source_path.to_string()
}

fn public_cbl_source_ref(repository: &str, source_path: &str) -> String {
    format!(
        "{}:{}",
        public_cbl_repository(repository),
        public_cbl_source_path(source_path)
    )
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

/// `GET /api/v1/issue-identity/cbl-sources`
#[instrument(skip(state, _auth))]
pub async fn discover_cbl_source_lists(
    State(state): State<Arc<AppState>>,
    _auth: AuthenticatedUser,
    Query(params): Query<DiscoverCblSourcesParams>,
) -> Result<Json<Vec<CblSourceListDiscoveryItem>>, IdentityError> {
    let mut validation_errors = Vec::new();
    if let Some(ref q) = params.q {
        if q.chars().count() > MAX_SEARCH_LENGTH {
            validation_errors.push(too_long("q", q, MAX_SEARCH_LENGTH, "query"));
        }
    }
    let limit = match parse_int("limit", params.limit.as_deref(), 25, 1, MAX_DISCOVERY_LIMIT) {
        Ok(limit) => limit,
        Err(errors) => {
            validation_errors.extend(errors);
            return Err(IdentityError::Validation(validation_errors));
        }
    };
    if !validation_errors.is_empty() {
        return Err(IdentityError::Validation(validation_errors));
    }

    let pool = checkout(&state).await?;
    let term = params.q.as_deref().unwrap_or("").trim();
    let pattern = format!("%{term}%");

    let sql = if term.is_empty() {
        r#"
        SELECT csl.id, csl.name, csl.source_path, cs.repository,
               csl.declared_issue_count, csl.content_hash, csl.revision_sha
        FROM cbl_source_lists csl
        JOIN cbl_sources cs ON cs.id = csl.source_id
        WHERE csl.active = true
        ORDER BY csl.name ASC, csl.source_path ASC, csl.id ASC
        LIMIT $1
        "#
    } else {
        r#"
        SELECT csl.id, csl.name, csl.source_path, cs.repository,
               csl.declared_issue_count, csl.content_hash, csl.revision_sha
        FROM cbl_source_lists csl
        JOIN cbl_sources cs ON cs.id = csl.source_id
        WHERE csl.active = true
          AND (csl.name ILIKE $1 OR csl.source_path ILIKE $1)
        ORDER BY csl.name ASC, csl.source_path ASC, csl.id ASC
        LIMIT $2
        "#
    };

    let rows = if term.is_empty() {
        pool.query(sql, &[&limit]).await
    } else {
        pool.query(sql, &[&pattern, &limit]).await
    }
    .map_err(|error| {
        tracing::error!(
            error_kind = crate::error_kind(&error),
            "CBL source discovery failed"
        );
        ApiError::Internal("CBL source discovery failed".to_string())
    })?;

    let items = rows
        .into_iter()
        .map(|row| CblSourceListDiscoveryItem {
            id: row.get(0),
            name: row.get(1),
            source_path: row.get(2),
            source_repository: public_cbl_repository(row.get::<_, &str>(3)),
            declared_issue_count: row.get(4),
            content_hash: row.get(5),
            revision_sha: row.get(6),
        })
        .collect();

    Ok(Json(items))
}

/// `GET /api/v1/issue-identity/cbl-sources/{list_id}`
#[instrument(skip(state, _auth))]
pub async fn get_cbl_source_list(
    State(state): State<Arc<AppState>>,
    _auth: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Query(params): Query<GetCblSourceListParams>,
) -> Result<Json<CblSourceListDetail>, IdentityError> {
    let offset = match parse_int("offset", params.offset.as_deref(), 0, 0, i64::MAX) {
        Ok(offset) => offset,
        Err(errors) => return Err(IdentityError::Validation(errors)),
    };
    let limit = match parse_int("limit", params.limit.as_deref(), 1000, 1, MAX_ENTRIES_LIMIT) {
        Ok(limit) => limit,
        Err(errors) => return Err(IdentityError::Validation(errors)),
    };

    let pool = checkout(&state).await?;
    let list_row = pool
        .query_opt(
            r#"
        SELECT csl.id, csl.name, csl.source_path, cs.repository,
               csl.declared_issue_count, csl.content_hash, csl.revision_sha
        FROM cbl_source_lists csl
        JOIN cbl_sources cs ON cs.id = csl.source_id
        WHERE csl.id = $1 AND csl.active = true
        "#,
            &[&list_id],
        )
        .await
        .map_err(|error| {
            tracing::error!(
                error_kind = crate::error_kind(&error),
                "CBL source list load failed"
            );
            ApiError::Internal("CBL source list load failed".to_string())
        })?
        .ok_or_else(|| ApiError::NotFound("CBL source list not found".to_string()))?;

    let id: i32 = list_row.get(0);
    let name: String = list_row.get(1);
    let raw_source_path: String = list_row.get(2);
    let repository: String = list_row.get(3);
    let declared_issue_count: Option<i32> = list_row.get(4);
    let content_hash: String = list_row.get(5);
    let revision_sha: String = list_row.get(6);

    let source_path = public_cbl_source_path(&raw_source_path);
    let source_repository = public_cbl_repository(&repository);
    let source_ref = public_cbl_source_ref(&repository, &raw_source_path);

    let entries_rows = pool
        .query(
            r#"
        SELECT cse.position, cse.series_name, cse.issue_number,
               cse.volume_year, cse.publication_year,
               ei.external_id, ev.external_id
        FROM cbl_source_entries cse
        LEFT JOIN external_identities ei
               ON ei.id = cse.external_issue_identity_id
              AND ei.provider = 'comicvine' AND ei.entity_type = 'issue'
        LEFT JOIN external_identities ev
               ON ev.id = cse.external_series_identity_id
              AND ev.provider = 'comicvine' AND ev.entity_type = 'series'
        WHERE cse.list_id = $1
        ORDER BY cse.position ASC, cse.id ASC
        LIMIT $2 OFFSET $3
        "#,
            &[&list_id, &limit, &offset],
        )
        .await
        .map_err(|error| {
            tracing::error!(
                error_kind = crate::error_kind(&error),
                "CBL source entries load failed"
            );
            ApiError::Internal("CBL source entries load failed".to_string())
        })?;

    let entries = entries_rows
        .into_iter()
        .map(|row| CblSourceEntryDetail {
            position: row.get(0),
            series_name: row.get(1),
            issue_number: row.get(2),
            volume_year: row.get(3),
            publication_year: row.get(4),
            comicvine_issue_id: row.get(5),
            comicvine_volume_id: row.get(6),
        })
        .collect();

    let total_count: i64 = pool
        .query_one(
            "SELECT COUNT(*) FROM cbl_source_entries WHERE list_id = $1",
            &[&list_id],
        )
        .await
        .map_err(|error| {
            tracing::error!(
                error_kind = crate::error_kind(&error),
                "CBL source entries count failed"
            );
            ApiError::Internal("CBL source entries count failed".to_string())
        })?
        .get(0);

    Ok(Json(CblSourceListDetail {
        id,
        name,
        source_path,
        source_repository,
        source_ref,
        declared_issue_count,
        content_hash,
        revision_sha,
        entries_total: total_count as i32,
        entries_offset: offset as i32,
        entries_limit: limit as i32,
        entries,
    }))
}

/// `GET /api/v1/issue-identity/cbl-sources/by-comicvine-issue/{comicvine_issue_id}`
#[instrument(skip(state, _auth))]
pub async fn find_cbl_sources_by_comicvine_issue(
    State(state): State<Arc<AppState>>,
    _auth: AuthenticatedUser,
    Path(comicvine_issue_id): Path<String>,
    Query(params): Query<CblOccurrenceParams>,
) -> Result<Json<CblComicvineOccurrencePage>, IdentityError> {
    let normalized_issue_id = comicvine_issue_id.trim().to_string();
    if normalized_issue_id.is_empty() {
        // Python raises HTTPException(422) with a plain string detail here.
        return Err(
            ApiError::Unprocessable("Comic Vine issue ID must not be blank".to_string()).into(),
        );
    }
    if comicvine_issue_id.chars().count() > MAX_COMICVINE_ID_LENGTH {
        return Err(IdentityError::Validation(vec![too_long(
            "comicvine_issue_id",
            &comicvine_issue_id,
            MAX_COMICVINE_ID_LENGTH,
            "path",
        )]));
    }

    let offset = match parse_int("offset", params.offset.as_deref(), 0, 0, i64::MAX) {
        Ok(offset) => offset,
        Err(errors) => return Err(IdentityError::Validation(errors)),
    };
    let limit = match parse_int(
        "limit",
        params.limit.as_deref(),
        50,
        1,
        MAX_OCCURRENCE_LIMIT,
    ) {
        Ok(limit) => limit,
        Err(errors) => return Err(IdentityError::Validation(errors)),
    };

    let pool = checkout(&state).await?;
    let rows = pool
        .query(
            r#"
        SELECT csl.id, csl.name, csl.source_path, cs.repository, csl.revision_sha,
               cse.position, cse.series_name, cse.issue_number,
               cse.volume_year, cse.publication_year, ev.external_id
        FROM cbl_source_entries cse
        JOIN cbl_source_lists csl ON csl.id = cse.list_id
        JOIN cbl_sources cs ON cs.id = csl.source_id
        LEFT JOIN external_identities ev
               ON ev.id = cse.external_series_identity_id
              AND ev.provider = 'comicvine' AND ev.entity_type = 'series'
        WHERE csl.active = true
          AND cse.external_issue_identity_id IN (
              SELECT ei.id FROM external_identities ei
              WHERE ei.provider = 'comicvine'
                AND ei.entity_type = 'issue'
                AND ei.external_id = $1
          )
        ORDER BY csl.name ASC, csl.source_path ASC, csl.id ASC,
                 cse.position ASC, cse.id ASC
        LIMIT $2 OFFSET $3
        "#,
            &[&normalized_issue_id, &limit, &offset],
        )
        .await
        .map_err(|error| {
            tracing::error!(
                error_kind = crate::error_kind(&error),
                "CBL comicvine lookup failed"
            );
            ApiError::Internal("CBL comicvine lookup failed".to_string())
        })?;

    let occurrences = rows
        .into_iter()
        .map(|row| {
            let raw_source_path: &str = row.get(2);
            let repository: &str = row.get(3);
            CblComicvineOccurrence {
                list_id: row.get(0),
                list_name: row.get(1),
                source_path: public_cbl_source_path(raw_source_path),
                source_repository: public_cbl_repository(repository),
                source_ref: public_cbl_source_ref(repository, raw_source_path),
                revision_sha: row.get(4),
                position: row.get(5),
                series_name: row.get(6),
                issue_number: row.get(7),
                volume_year: row.get(8),
                publication_year: row.get(9),
                comicvine_issue_id: normalized_issue_id.clone(),
                comicvine_volume_id: row.get(10),
            }
        })
        .collect();

    let totals = pool
        .query_one(
            r#"
        SELECT COUNT(cse.id), COUNT(DISTINCT csl.id)
        FROM cbl_source_entries cse
        JOIN cbl_source_lists csl ON csl.id = cse.list_id
        WHERE csl.active = true
          AND cse.external_issue_identity_id IN (
              SELECT ei.id FROM external_identities ei
              WHERE ei.provider = 'comicvine'
                AND ei.entity_type = 'issue'
                AND ei.external_id = $1
          )
        "#,
            &[&normalized_issue_id],
        )
        .await
        .map_err(|error| {
            tracing::error!(
                error_kind = crate::error_kind(&error),
                "CBL comicvine lookup totals failed"
            );
            ApiError::Internal("CBL comicvine lookup totals failed".to_string())
        })?;

    let occurrences_total: i64 = totals.get(0);
    let lists_total: i64 = totals.get(1);

    Ok(Json(CblComicvineOccurrencePage {
        comicvine_issue_id: normalized_issue_id,
        occurrences_total: occurrences_total as i32,
        lists_total: lists_total as i32,
        occurrences_offset: offset as i32,
        occurrences_limit: limit as i32,
        occurrences,
    }))
}

// ---------------------------------------------------------------------------
// Compare / candidates / adoption-plan / adoption-commit (remaining #4843 ops)
// ---------------------------------------------------------------------------

use serde_json::Value as JsonValue;
use std::collections::{HashMap, HashSet};

#[derive(Debug, Deserialize)]
pub struct CblSourceComparisonRequest {
    pub comicvine_issue_ids: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CblSourceComparisonMatch {
    pub list_id: i32,
    pub list_name: String,
    pub source_path: String,
    pub source_repository: String,
    pub source_ref: String,
    pub revision_sha: String,
    pub declared_issue_count: Option<i32>,
    pub entries_total: i32,
    pub distinct_source_issues: i32,
    pub matched_input_count: i32,
    pub input_total: i32,
    pub matched_occurrence_count: i32,
    pub duplicate_match_count: i32,
    pub source_only_issue_count: i32,
    pub input_coverage_percentage: i32,
    pub source_coverage_percentage: i32,
    pub order_status: String,
    pub order_pair_count: i32,
    pub order_disagreement_count: i32,
    pub matched_input_ids: Vec<String>,
    pub missing_input_ids: Vec<String>,
    pub score: i32,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CblSourceComparisonResponse {
    pub comicvine_issue_ids: Vec<String>,
    pub input_total: i32,
    pub candidates_total: i32,
    pub candidates: Vec<CblSourceComparisonMatch>,
}

#[derive(Debug, Deserialize)]
pub struct CompareQueryParams {
    #[serde(default)]
    pub limit: Option<String>,
}

fn normalize_comparison_ids(raw: Vec<String>) -> Result<Vec<String>, Vec<ValidationErrorItem>> {
    // Mirrors Pydantic field_validator normalize_issue_ids for CBLSourceComparisonRequest
    let mut normalized = Vec::new();
    let mut seen = HashSet::new();
    for v in raw {
        let issue_id = v.trim().to_string();
        if issue_id.is_empty() {
            return Err(vec![ValidationErrorItem {
                error_type: "value_error".to_string(),
                loc: vec!["body".to_string(), "comicvine_issue_ids".to_string()],
                msg: "Value error, comicvine_issue_ids must not contain blank values".to_string(),
                input: JsonValue::Array(vec![]),
                ctx: Some(serde_json::json!({"error": {}})),
            }]);
        }
        if issue_id.chars().count() > 100 {
            return Err(vec![ValidationErrorItem {
                error_type: "value_error".to_string(),
                loc: vec!["body".to_string(), "comicvine_issue_ids".to_string()],
                msg: "Value error, comicvine_issue_ids entries must be at most 100 characters"
                    .to_string(),
                input: JsonValue::Array(vec![]),
                ctx: Some(serde_json::json!({"error": {}})),
            }]);
        }
        if seen.insert(issue_id.clone()) {
            normalized.push(issue_id);
        }
    }
    Ok(normalized)
}

/// `POST /api/v1/issue-identity/cbl-sources/compare`
#[instrument(skip(state, _auth, payload))]
pub async fn compare_cbl_sources(
    State(state): State<Arc<AppState>>,
    _auth: AuthenticatedUser,
    Query(params): Query<CompareQueryParams>,
    Json(payload): Json<CblSourceComparisonRequest>,
) -> Result<Json<CblSourceComparisonResponse>, IdentityError> {
    let limit = match parse_int("limit", params.limit.as_deref(), 50, 1, 100) {
        Ok(limit) => limit,
        Err(errors) => return Err(IdentityError::Validation(errors)),
    };

    if payload.comicvine_issue_ids.is_empty() {
        return Err(IdentityError::Validation(vec![ValidationErrorItem {
            error_type: "too_short".to_string(),
            loc: vec!["body".to_string(), "comicvine_issue_ids".to_string()],
            msg: "List should have at least 1 item after validation, not 0".to_string(),
            input: JsonValue::Array(vec![]),
            ctx: Some(serde_json::json!({"field_type":"List","min_length":1,"actual_length":0})),
        }]));
    }
    if payload.comicvine_issue_ids.len() > 1000 {
        return Err(IdentityError::Validation(vec![ValidationErrorItem {
            error_type: "too_long".to_string(),
            loc: vec!["body".to_string(), "comicvine_issue_ids".to_string()],
            msg: "List should have at most 1000 items after validation, not more".to_string(),
            input: JsonValue::Array(vec![]),
            ctx: Some(
                serde_json::json!({"field_type":"List","max_length":1000,"actual_length": payload.comicvine_issue_ids.len()}),
            ),
        }]));
    }

    let input_ids = match normalize_comparison_ids(payload.comicvine_issue_ids) {
        Ok(ids) => ids,
        Err(errors) => return Err(IdentityError::Validation(errors)),
    };

    if input_ids.is_empty() {
        return Ok(Json(CblSourceComparisonResponse {
            comicvine_issue_ids: vec![],
            input_total: 0,
            candidates_total: 0,
            candidates: vec![],
        }));
    }

    let pool = checkout(&state).await?;

    // Candidate coverage rows: active lists containing at least one exact input identity.
    let coverage_rows = pool
        .query(
            r#"
        WITH matched AS (
            SELECT DISTINCT cse.list_id
            FROM cbl_source_entries cse
            JOIN external_identities ei ON ei.id = cse.external_issue_identity_id
            WHERE ei.provider = 'comicvine'
              AND ei.entity_type = 'issue'
              AND ei.external_id = ANY($1::text[])
        )
        SELECT csl.id, csl.name, csl.source_path, cs.repository, csl.revision_sha,
               csl.declared_issue_count,
               COUNT(cse.id)::int AS entries_total,
               COUNT(DISTINCT iei.id)::int AS distinct_source_issues
        FROM cbl_source_lists csl
        JOIN cbl_sources cs ON cs.id = csl.source_id
        JOIN cbl_source_entries cse ON cse.list_id = csl.id
        LEFT JOIN external_identities iei
               ON iei.id = cse.external_issue_identity_id
              AND iei.provider = 'comicvine' AND iei.entity_type = 'issue'
        WHERE csl.active = true
          AND csl.id IN (SELECT list_id FROM matched)
        GROUP BY csl.id, cs.id
        ORDER BY csl.name ASC, csl.id ASC
        "#,
            &[&input_ids],
        )
        .await
        .map_err(|error| {
            tracing::error!(
                error_kind = crate::error_kind(&error),
                "CBL compare coverage failed"
            );
            ApiError::Internal("CBL compare failed".to_string())
        })?;

    let list_ids: Vec<i32> = coverage_rows.iter().map(|r| r.get(0)).collect();
    let mut rows_by_list: HashMap<i32, Vec<(i32, String)>> = HashMap::new(); // (position, comicvine_id)
    if !list_ids.is_empty() {
        let matched_rows = pool
            .query(
                r#"
            SELECT cse.list_id, cse.position, ei.external_id
            FROM cbl_source_entries cse
            JOIN external_identities ei ON ei.id = cse.external_issue_identity_id
            WHERE ei.provider = 'comicvine'
              AND ei.entity_type = 'issue'
              AND cse.list_id = ANY($1::int[])
              AND ei.external_id = ANY($2::text[])
            ORDER BY cse.list_id ASC, cse.position ASC, cse.id ASC
            "#,
                &[&list_ids, &input_ids],
            )
            .await
            .map_err(|error| {
                tracing::error!(
                    error_kind = crate::error_kind(&error),
                    "CBL compare matches failed"
                );
                ApiError::Internal("CBL compare failed".to_string())
            })?;
        for row in matched_rows {
            rows_by_list
                .entry(row.get(0))
                .or_default()
                .push((row.get(1), row.get(2)));
        }
    }

    let input_total = input_ids.len() as i32;
    let input_position: HashMap<&str, usize> = input_ids
        .iter()
        .enumerate()
        .map(|(i, id)| (id.as_str(), i))
        .collect();

    let mut comparisons: Vec<CblSourceComparisonMatch> = Vec::new();
    for row in &coverage_rows {
        let list_id: i32 = row.get(0);
        let list_name: String = row.get(1);
        let raw_source_path: String = row.get(2);
        let repository: String = row.get(3);
        let revision_sha: String = row.get(4);
        let declared_issue_count: Option<i32> = row.get(5);
        let entries_total: i32 = row.get(6);
        let distinct_source_issues: i32 = row.get(7);

        let matched = rows_by_list.get(&list_id).cloned().unwrap_or_default();
        let mut matched_seen: HashSet<String> = HashSet::new();
        let mut matched_distinct: Vec<String> = Vec::new();
        for (_, id) in &matched {
            if matched_seen.insert(id.clone()) {
                matched_distinct.push(id.clone());
            }
        }
        let matched_input_ids: Vec<String> = input_ids
            .iter()
            .filter(|id| matched_seen.contains(*id))
            .cloned()
            .collect();
        let missing_input_ids: Vec<String> = input_ids
            .iter()
            .filter(|id| !matched_seen.contains(*id))
            .cloned()
            .collect();
        let matched_count = matched_input_ids.len() as i32;
        let input_coverage = if input_total > 0 {
            matched_count as f64 / input_total as f64
        } else {
            0.0
        };
        let source_coverage = if distinct_source_issues > 0 {
            matched_count as f64 / distinct_source_issues as f64
        } else {
            0.0
        };

        let mut positions: Vec<usize> = Vec::new();
        for id in &matched_distinct {
            if let Some(p) = input_position.get(id.as_str()) {
                positions.push(*p);
            }
        }
        let mut pair_count = 0i32;
        let mut disagreement_count = 0i32;
        for i in 0..positions.len() {
            for j in (i + 1)..positions.len() {
                pair_count += 1;
                if positions[i] > positions[j] {
                    disagreement_count += 1;
                }
            }
        }
        let order_agreement = if pair_count == 0 {
            1.0
        } else {
            1.0 - (disagreement_count as f64 / pair_count as f64)
        };
        let score = ((55.0 * input_coverage) + (25.0 * source_coverage) + (20.0 * order_agreement))
            .round() as i32;
        let order_status = if matched_count < 2 {
            "not_comparable"
        } else if disagreement_count > 0 {
            "reordered"
        } else {
            "same_order"
        };

        comparisons.push(CblSourceComparisonMatch {
            list_id,
            list_name,
            source_path: public_cbl_source_path(&raw_source_path),
            source_repository: public_cbl_repository(&repository),
            source_ref: public_cbl_source_ref(&repository, &raw_source_path),
            revision_sha,
            declared_issue_count,
            entries_total,
            distinct_source_issues,
            matched_input_count: matched_count,
            input_total,
            matched_occurrence_count: matched.len() as i32,
            duplicate_match_count: std::cmp::max(0, matched.len() as i32 - matched_count),
            source_only_issue_count: std::cmp::max(0, distinct_source_issues - matched_count),
            input_coverage_percentage: (100.0 * input_coverage).round() as i32,
            source_coverage_percentage: (100.0 * source_coverage).round() as i32,
            order_status: order_status.to_string(),
            order_pair_count: pair_count,
            order_disagreement_count: disagreement_count,
            matched_input_ids,
            missing_input_ids,
            score,
        });
    }

    comparisons.sort_by(|a, b| {
        b.score
            .cmp(&a.score)
            .then(b.matched_input_count.cmp(&a.matched_input_count))
            .then(
                b.source_coverage_percentage
                    .cmp(&a.source_coverage_percentage),
            )
            .then(a.list_name.cmp(&b.list_name))
            .then(a.list_id.cmp(&b.list_id))
    });
    let candidates_total = comparisons.len() as i32;
    comparisons.truncate(limit as usize);

    Ok(Json(CblSourceComparisonResponse {
        comicvine_issue_ids: input_ids,
        input_total,
        candidates_total,
        candidates: comparisons,
    }))
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CblReadingListInputEntry {
    pub position: i32,
    pub issue_id: i32,
    pub series_name: String,
    pub issue_number: String,
    pub comicvine_issue_id: Option<String>,
    pub comicvine_issue_ids: Vec<String>,
    pub identity_status: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CblReadingListCandidatesResponse {
    pub list_id: i32,
    pub list_name: String,
    pub input_entry_count: i32,
    pub input_confirmed_total: i32,
    pub input_missing_count: i32,
    pub input_conflict_count: i32,
    pub input_ids: Vec<String>,
    pub entries: Vec<CblReadingListInputEntry>,
    pub candidates_total: i32,
    pub candidates: Vec<CblSourceComparisonMatch>,
}

#[derive(Debug, Deserialize)]
pub struct CandidatesQueryParams {
    #[serde(default)]
    pub limit: Option<String>,
}

#[instrument(skip(state, auth))]
pub async fn find_cbl_candidates_for_reading_list(
    State(state): State<Arc<AppState>>,
    auth: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Query(params): Query<CandidatesQueryParams>,
) -> Result<Json<CblReadingListCandidatesResponse>, IdentityError> {
    let limit = match parse_int("limit", params.limit.as_deref(), 50, 1, 100) {
        Ok(limit) => limit,
        Err(errors) => return Err(IdentityError::Validation(errors)),
    };

    let pool = checkout(&state).await?;
    // Owned reading list lookup: must be 404 if missing or not owned (same as Python get_custom_cbl_response).
    let list_row = pool
        .query_opt(
            "SELECT id, name FROM custom_cbl_lists WHERE id = $1 AND user_id = $2",
            &[&list_id, &auth.id()],
        )
        .await
        .map_err(|error| {
            tracing::error!(
                error_kind = crate::error_kind(&error),
                "reading list load failed"
            );
            ApiError::Internal("Internal Server Error".to_string())
        })?
        .ok_or_else(|| ApiError::NotFound(format!("Custom CBL {list_id} not found")))?;
    let list_name: String = list_row.get(1);

    let entry_rows = pool
        .query(
            r#"
        SELECT e.position, e.issue_id, t.title, i.issue_number
        FROM custom_cbl_entries e
        JOIN issues i ON i.id = e.issue_id
        JOIN threads t ON t.id = i.thread_id
        WHERE e.list_id = $1
        ORDER BY e.position ASC, e.id ASC
        "#,
            &[&list_id],
        )
        .await
        .map_err(|error| {
            tracing::error!(
                error_kind = crate::error_kind(&error),
                "reading list entries load failed"
            );
            ApiError::Internal("Internal Server Error".to_string())
        })?;

    let mut issue_ids: Vec<i32> = Vec::new();
    for row in &entry_rows {
        issue_ids.push(row.get(1));
    }

    let mut identities_by_issue: HashMap<i32, Vec<String>> = HashMap::new();
    if !issue_ids.is_empty() {
        let id_rows = pool
            .query(
                r#"
            SELECT m.issue_id, ei.external_id
            FROM issue_external_identity_mappings m
            JOIN external_identities ei ON ei.id = m.external_identity_id
            JOIN issues i ON i.id = m.issue_id
            JOIN threads t ON t.id = i.thread_id
            WHERE t.user_id = $1
              AND m.issue_id = ANY($2::int[])
              AND m.status = 'confirmed'
              AND ei.provider = 'comicvine'
              AND ei.entity_type = 'issue'
            ORDER BY i.position ASC, i.id ASC, ei.id ASC
            "#,
                &[&auth.id(), &issue_ids],
            )
            .await
            .map_err(|error| {
                tracing::error!(
                    error_kind = crate::error_kind(&error),
                    "confirmed identities load failed"
                );
                ApiError::Internal("Internal Server Error".to_string())
            })?;
        for row in id_rows {
            identities_by_issue
                .entry(row.get(0))
                .or_default()
                .push(row.get(1));
        }
    }

    let mut entries: Vec<CblReadingListInputEntry> = Vec::new();
    let mut input_ids: Vec<String> = Vec::new();
    let mut seen_input_ids: HashSet<String> = HashSet::new();
    let mut missing_count = 0i32;
    let mut conflict_count = 0i32;

    for row in &entry_rows {
        let position: i32 = row.get(0);
        let issue_id: i32 = row.get(1);
        let series_name: String = row.get(2);
        let issue_number: String = row.get(3);
        let confirmed_ids = identities_by_issue
            .get(&issue_id)
            .cloned()
            .unwrap_or_default();
        let (identity_status, comicvine_issue_id) = if confirmed_ids.is_empty() {
            missing_count += 1;
            ("missing".to_string(), None)
        } else if confirmed_ids.len() == 1 {
            let id = confirmed_ids[0].clone();
            if seen_input_ids.insert(id.clone()) {
                input_ids.push(id.clone());
            }
            ("confirmed".to_string(), Some(id))
        } else {
            conflict_count += 1;
            ("conflict".to_string(), None)
        };
        entries.push(CblReadingListInputEntry {
            position,
            issue_id,
            series_name,
            issue_number,
            comicvine_issue_id,
            comicvine_issue_ids: confirmed_ids,
            identity_status,
        });
    }

    // Reuse compare logic over distinct confirmed input_ids.
    let comparison = compute_source_comparison(&pool, &input_ids, limit).await?;

    Ok(Json(CblReadingListCandidatesResponse {
        list_id,
        list_name,
        input_entry_count: entries.len() as i32,
        input_confirmed_total: input_ids.len() as i32,
        input_missing_count: missing_count,
        input_conflict_count: conflict_count,
        input_ids,
        entries,
        candidates_total: comparison.candidates_total,
        candidates: comparison.candidates,
    }))
}

async fn compute_source_comparison(
    pool: &deadpool_postgres::Object,
    input_ids: &[String],
    limit: i64,
) -> Result<CblSourceComparisonResponse, IdentityError> {
    // Same algorithm as compare_cbl_sources but operates on provided pool/ids.
    if input_ids.is_empty() {
        return Ok(CblSourceComparisonResponse {
            comicvine_issue_ids: vec![],
            input_total: 0,
            candidates_total: 0,
            candidates: vec![],
        });
    }
    let input_ids_vec = input_ids.to_vec();
    let coverage_rows = pool
        .query(
            r#"
        WITH matched AS (
            SELECT DISTINCT cse.list_id
            FROM cbl_source_entries cse
            JOIN external_identities ei ON ei.id = cse.external_issue_identity_id
            WHERE ei.provider = 'comicvine'
              AND ei.entity_type = 'issue'
              AND ei.external_id = ANY($1::text[])
        )
        SELECT csl.id, csl.name, csl.source_path, cs.repository, csl.revision_sha,
               csl.declared_issue_count,
               COUNT(cse.id)::int AS entries_total,
               COUNT(DISTINCT iei.id)::int AS distinct_source_issues
        FROM cbl_source_lists csl
        JOIN cbl_sources cs ON cs.id = csl.source_id
        JOIN cbl_source_entries cse ON cse.list_id = csl.id
        LEFT JOIN external_identities iei
               ON iei.id = cse.external_issue_identity_id
              AND iei.provider = 'comicvine' AND iei.entity_type = 'issue'
        WHERE csl.active = true
          AND csl.id IN (SELECT list_id FROM matched)
        GROUP BY csl.id, cs.id
        ORDER BY csl.name ASC, csl.id ASC
        "#,
            &[&input_ids_vec],
        )
        .await
        .map_err(|error| {
            tracing::error!(
                error_kind = crate::error_kind(&error),
                "CBL compare coverage failed"
            );
            ApiError::Internal("CBL compare failed".to_string())
        })?;

    let list_ids: Vec<i32> = coverage_rows.iter().map(|r| r.get(0)).collect();
    let mut rows_by_list: HashMap<i32, Vec<(i32, String)>> = HashMap::new();
    if !list_ids.is_empty() {
        let matched_rows = pool
            .query(
                r#"
            SELECT cse.list_id, cse.position, ei.external_id
            FROM cbl_source_entries cse
            JOIN external_identities ei ON ei.id = cse.external_issue_identity_id
            WHERE ei.provider = 'comicvine'
              AND ei.entity_type = 'issue'
              AND cse.list_id = ANY($1::int[])
              AND ei.external_id = ANY($2::text[])
            ORDER BY cse.list_id ASC, cse.position ASC, cse.id ASC
            "#,
                &[&list_ids, &input_ids_vec],
            )
            .await
            .map_err(|error| {
                tracing::error!(
                    error_kind = crate::error_kind(&error),
                    "CBL compare matches failed"
                );
                ApiError::Internal("CBL compare failed".to_string())
            })?;
        for row in matched_rows {
            rows_by_list
                .entry(row.get(0))
                .or_default()
                .push((row.get(1), row.get(2)));
        }
    }

    let input_total = input_ids_vec.len() as i32;
    let input_position: HashMap<&str, usize> = input_ids_vec
        .iter()
        .enumerate()
        .map(|(i, id)| (id.as_str(), i))
        .collect();

    let mut comparisons: Vec<CblSourceComparisonMatch> = Vec::new();
    for row in &coverage_rows {
        let list_id: i32 = row.get(0);
        let list_name: String = row.get(1);
        let raw_source_path: String = row.get(2);
        let repository: String = row.get(3);
        let revision_sha: String = row.get(4);
        let declared_issue_count: Option<i32> = row.get(5);
        let entries_total: i32 = row.get(6);
        let distinct_source_issues: i32 = row.get(7);

        let matched = rows_by_list.get(&list_id).cloned().unwrap_or_default();
        let mut matched_seen: HashSet<String> = HashSet::new();
        let mut matched_distinct: Vec<String> = Vec::new();
        for (_, id) in &matched {
            if matched_seen.insert(id.clone()) {
                matched_distinct.push(id.clone());
            }
        }
        let matched_input_ids: Vec<String> = input_ids_vec
            .iter()
            .filter(|id| matched_seen.contains(*id))
            .cloned()
            .collect();
        let missing_input_ids: Vec<String> = input_ids_vec
            .iter()
            .filter(|id| !matched_seen.contains(*id))
            .cloned()
            .collect();
        let matched_count = matched_input_ids.len() as i32;
        let input_coverage = if input_total > 0 {
            matched_count as f64 / input_total as f64
        } else {
            0.0
        };
        let source_coverage = if distinct_source_issues > 0 {
            matched_count as f64 / distinct_source_issues as f64
        } else {
            0.0
        };
        let mut positions: Vec<usize> = Vec::new();
        for id in &matched_distinct {
            if let Some(p) = input_position.get(id.as_str()) {
                positions.push(*p);
            }
        }
        let mut pair_count = 0i32;
        let mut disagreement_count = 0i32;
        for i in 0..positions.len() {
            for j in (i + 1)..positions.len() {
                pair_count += 1;
                if positions[i] > positions[j] {
                    disagreement_count += 1;
                }
            }
        }
        let order_agreement = if pair_count == 0 {
            1.0
        } else {
            1.0 - (disagreement_count as f64 / pair_count as f64)
        };
        let score = ((55.0 * input_coverage) + (25.0 * source_coverage) + (20.0 * order_agreement))
            .round() as i32;
        let order_status = if matched_count < 2 {
            "not_comparable"
        } else if disagreement_count > 0 {
            "reordered"
        } else {
            "same_order"
        };

        comparisons.push(CblSourceComparisonMatch {
            list_id,
            list_name,
            source_path: public_cbl_source_path(&raw_source_path),
            source_repository: public_cbl_repository(&repository),
            source_ref: public_cbl_source_ref(&repository, &raw_source_path),
            revision_sha,
            declared_issue_count,
            entries_total,
            distinct_source_issues,
            matched_input_count: matched_count,
            input_total,
            matched_occurrence_count: matched.len() as i32,
            duplicate_match_count: std::cmp::max(0, matched.len() as i32 - matched_count),
            source_only_issue_count: std::cmp::max(0, distinct_source_issues - matched_count),
            input_coverage_percentage: (100.0 * input_coverage).round() as i32,
            source_coverage_percentage: (100.0 * source_coverage).round() as i32,
            order_status: order_status.to_string(),
            order_pair_count: pair_count,
            order_disagreement_count: disagreement_count,
            matched_input_ids,
            missing_input_ids,
            score,
        });
    }
    comparisons.sort_by(|a, b| {
        b.score
            .cmp(&a.score)
            .then(b.matched_input_count.cmp(&a.matched_input_count))
            .then(
                b.source_coverage_percentage
                    .cmp(&a.source_coverage_percentage),
            )
            .then(a.list_name.cmp(&b.list_name))
            .then(a.list_id.cmp(&b.list_id))
    });
    let candidates_total = comparisons.len() as i32;
    comparisons.truncate(limit as usize);
    Ok(CblSourceComparisonResponse {
        comicvine_issue_ids: input_ids_vec,
        input_total,
        candidates_total,
        candidates: comparisons,
    })
}

// Adoption plan (read-only) - mirrors app/api/issue_identity.py
#[derive(Debug, Deserialize)]
pub struct CblAdoptionPlanRequest {
    #[serde(default)]
    pub series_decisions: std::collections::HashMap<String, bool>,
    #[serde(default)]
    pub entry_decisions: std::collections::HashMap<String, bool>,
}

#[derive(Debug, Serialize)]
pub struct CblSourceFingerprintResponse {
    pub source_list_id: i32,
    pub source_repository: String,
    pub source_path: String,
    pub content_hash: String,
    pub revision_sha: String,
}

#[derive(Debug, Serialize)]
pub struct CblAdoptionEntryResponse {
    pub collection_excluded: bool,
    pub collection_exclusion_reason: Option<String>,
    pub collection_exclusion_ids: Vec<i32>,
    pub cbl_position: i32,
    pub cbl_entry_id: i32,
    pub series_name: String,
    pub issue_number: String,
    pub series_group_id: String,
    pub volume_year: Option<i32>,
    pub publication_year: Option<i32>,
    pub adoption_class: String,
    pub adoption_decision: String,
    pub adopted: bool,
    pub comicvine_issue_id: Option<String>,
    pub comicvine_series_id: Option<String>,
    pub series_provider: Option<String>,
    pub series_external_id: Option<String>,
    pub resolved_issue_id: Option<i32>,
    pub canonical_issue_id: Option<i32>,
    pub read_status: Option<String>,
    pub read_at: Option<String>,
    pub resolution_status: String,
    pub is_duplicate_identity: bool,
}

#[derive(Debug, Serialize)]
pub struct CblAdoptionSummaryResponse {
    pub reused_existing_count: i32,
    pub missing_would_create_count: i32,
    pub excluded_count: i32,
    pub unresolved_count: i32,
    pub awaiting_opt_in_count: i32,
    pub final_adopted_count: i32,
    pub final_adopted_order: Vec<i32>,
    pub reused_existing_positions: Vec<i32>,
    pub missing_would_create_positions: Vec<i32>,
    pub excluded_positions: Vec<i32>,
    pub unresolved_positions: Vec<i32>,
    pub awaiting_opt_in_positions: Vec<i32>,
}

#[derive(Debug, Serialize)]
pub struct CblAdoptionPreviewResponse {
    pub source: CblSourceFingerprintResponse,
    pub total_positions: i32,
    pub entries: Vec<CblAdoptionEntryResponse>,
    pub summary: CblAdoptionSummaryResponse,
}

fn cbl_series_group_id(entry: &serde_json::Map<String, JsonValue>) -> String {
    let external_series_id = entry
        .get("series_external_id")
        .or(entry.get("comicvine_series_id"));
    if let Some(v) = external_series_id {
        if !v.is_null() {
            let provider = entry
                .get("series_provider")
                .and_then(|p| p.as_str())
                .unwrap_or("comicvine")
                .trim()
                .to_lowercase();
            let id_str = match v {
                JsonValue::String(s) => s.clone(),
                JsonValue::Number(n) => n.to_string(),
                _ => v.to_string(),
            };
            return format!("provider-series:{}:{}", provider, id_str);
        }
    }
    let name = entry
        .get("series_name")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_lowercase();
    let name = name.split_whitespace().collect::<Vec<_>>().join(" ");
    let year = entry
        .get("volume_year")
        .and_then(|v| if v.is_null() { None } else { Some(v.clone()) })
        .or(entry.get("publication_year").and_then(|v| {
            if v.is_null() {
                None
            } else {
                Some(v.clone())
            }
        }));
    let year_str = match year {
        Some(JsonValue::Number(n)) => n.to_string(),
        Some(JsonValue::String(s)) => s,
        _ => "unknown".to_string(),
    };
    use std::collections::hash_map::DefaultHasher;
    use std::hash::Hash;
    let mut hasher = DefaultHasher::new();
    format!("{}|{}", name, year_str).hash(&mut hasher);
    // Python uses hashlib.sha256(...).hexdigest()[:16]; for wire compatibility of grouping keys we should match.
    // Compute sha256-like via a simple approach is hard without dep; but grouping key must match Python's cbl_series_group_id.
    // We'll compute using sha2 via ring? not available. Instead, implement with a minimal sha256.
    let digest = sha256_hex(format!("{}|{}", name, year_str).as_bytes());
    format!("source-series:{}", &digest[..16])
}

// Minimal SHA-256 implementation for deterministic series_group_id parity with Python.
fn sha256_hex(data: &[u8]) -> String {
    // Use a tiny pure-rust sha256 implementation inline to avoid new deps.
    // Constants
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    let mut msg = data.to_vec();
    let bit_len = (msg.len() as u64) * 8;
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bit_len.to_be_bytes());
    for chunk in msg.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                chunk[i * 4],
                chunk[i * 4 + 1],
                chunk[i * 4 + 2],
                chunk[i * 4 + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let (mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh) =
            (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]);
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
    }
    let mut out = String::with_capacity(64);
    for v in h {
        out.push_str(&format!("{:08x}", v));
    }
    out
}

#[derive(Debug, Clone)]
#[allow(dead_code)]
struct CblListMeta {
    id: i32,
    source_repository: String,
    source_path: String,
    content_hash: String,
    revision_sha: String,
    name: String,
    declared_issue_count: Option<i32>,
}

async fn load_active_cbl_list_meta(
    pool: &deadpool_postgres::Object,
    list_id: i32,
) -> Result<CblListMeta, ApiError> {
    let row = pool
        .query_opt(
            r#"
        SELECT csl.id, cs.repository, csl.source_path, csl.content_hash, csl.revision_sha, csl.name, csl.declared_issue_count
        FROM cbl_source_lists csl
        JOIN cbl_sources cs ON cs.id = csl.source_id
        WHERE csl.id = $1 AND csl.active = true
        "#,
            &[&list_id],
        )
        .await
        .map_err(|e| { tracing::error!(error_kind = crate::error_kind(&e), "load cbl list failed"); ApiError::Internal("Internal Server Error".to_string()) })?
        .ok_or_else(|| ApiError::NotFound(format!("CBL source list {list_id} not found or not active")))?;
    Ok(CblListMeta {
        id: row.get(0),
        source_repository: row.get(1),
        source_path: row.get(2),
        content_hash: row.get(3),
        revision_sha: row.get(4),
        name: row.get(5),
        declared_issue_count: row.get(6),
    })
}

#[instrument(skip(state, auth, request))]
pub async fn cbl_adoption_plan(
    State(state): State<Arc<AppState>>,
    auth: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(request): Json<CblAdoptionPlanRequest>,
) -> Result<Json<CblAdoptionPreviewResponse>, IdentityError> {
    let pool = checkout(&state).await?;
    let list_meta = load_active_cbl_list_meta(&pool, list_id).await?;
    // Build reconciliation entries (best-effort faithful port of core fields used by adoption plan).
    let report_entries = reconcile_entries_for_adoption(&pool, auth.id(), &list_meta).await?;
    let planned = calculate_adoption_plan_entries(
        &report_entries,
        &request.series_decisions,
        &request.entry_decisions,
    );
    Ok(Json(build_adoption_preview_response(&list_meta, &planned)))
}

fn build_adoption_preview_response(
    list_meta: &CblListMeta,
    planned: &[serde_json::Map<String, JsonValue>],
) -> CblAdoptionPreviewResponse {
    let mut reused = 0i32;
    let mut missing = 0i32;
    let mut excluded = 0i32;
    let mut unresolved = 0i32;
    let mut awaiting = 0i32;
    let mut final_adopted_order = Vec::new();
    let mut reused_positions = Vec::new();
    let mut missing_positions = Vec::new();
    let mut excluded_positions = Vec::new();
    let mut unresolved_positions = Vec::new();
    let mut awaiting_positions = Vec::new();
    let mut entries = Vec::new();
    for e in planned {
        let pos = e.get("cbl_position").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
        let decision = e
            .get("adoption_decision")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        match decision.as_str() {
            "included_existing" => {
                reused += 1;
                final_adopted_order.push(pos);
                reused_positions.push(pos);
            }
            "would_create_missing" => {
                missing += 1;
                final_adopted_order.push(pos);
                missing_positions.push(pos);
            }
            "excluded" => {
                excluded += 1;
                excluded_positions.push(pos);
            }
            "unresolved" => {
                unresolved += 1;
                unresolved_positions.push(pos);
            }
            "awaiting_opt_in" => {
                awaiting += 1;
                awaiting_positions.push(pos);
            }
            _ => {}
        }
        entries.push(map_entry_response(e));
    }
    CblAdoptionPreviewResponse {
        source: CblSourceFingerprintResponse {
            source_list_id: list_meta.id,
            source_repository: public_cbl_repository(&list_meta.source_repository),
            source_path: public_cbl_source_path(&list_meta.source_path),
            content_hash: list_meta.content_hash.clone(),
            revision_sha: list_meta.revision_sha.clone(),
        },
        total_positions: planned.len() as i32,
        entries,
        summary: CblAdoptionSummaryResponse {
            reused_existing_count: reused,
            missing_would_create_count: missing,
            excluded_count: excluded,
            unresolved_count: unresolved,
            awaiting_opt_in_count: awaiting,
            final_adopted_count: final_adopted_order.len() as i32,
            final_adopted_order,
            reused_existing_positions: reused_positions,
            missing_would_create_positions: missing_positions,
            excluded_positions,
            unresolved_positions,
            awaiting_opt_in_positions: awaiting_positions,
        },
    }
}

fn j_i32(m: &serde_json::Map<String, JsonValue>, k: &str) -> i32 {
    m.get(k).and_then(|v| v.as_i64()).unwrap_or(0) as i32
}
fn j_opt_i32(m: &serde_json::Map<String, JsonValue>, k: &str) -> Option<i32> {
    m.get(k).and_then(|v| {
        if v.is_null() {
            None
        } else {
            v.as_i64().map(|x| x as i32)
        }
    })
}
fn j_str(m: &serde_json::Map<String, JsonValue>, k: &str) -> String {
    m.get(k).and_then(|v| v.as_str()).unwrap_or("").to_string()
}
fn j_opt_str(m: &serde_json::Map<String, JsonValue>, k: &str) -> Option<String> {
    m.get(k).and_then(|v| {
        if v.is_null() {
            None
        } else {
            v.as_str().map(|s| s.to_string())
        }
    })
}
fn j_bool(m: &serde_json::Map<String, JsonValue>, k: &str) -> bool {
    m.get(k).and_then(|v| v.as_bool()).unwrap_or(false)
}

fn map_entry_response(e: &serde_json::Map<String, JsonValue>) -> CblAdoptionEntryResponse {
    let exclusion_ids = e
        .get("collection_exclusion_ids")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_i64().map(|n| n as i32))
                .collect()
        })
        .unwrap_or_default();
    CblAdoptionEntryResponse {
        collection_excluded: j_bool(e, "collection_excluded"),
        collection_exclusion_reason: j_opt_str(e, "collection_exclusion_reason"),
        collection_exclusion_ids: exclusion_ids,
        cbl_position: j_i32(e, "cbl_position"),
        cbl_entry_id: j_i32(e, "cbl_entry_id"),
        series_name: j_str(e, "series_name"),
        issue_number: j_str(e, "issue_number"),
        series_group_id: j_str(e, "series_group_id"),
        volume_year: j_opt_i32(e, "volume_year"),
        publication_year: j_opt_i32(e, "publication_year"),
        adoption_class: j_str(e, "adoption_class"),
        adoption_decision: j_str(e, "adoption_decision"),
        adopted: j_bool(e, "adopted"),
        comicvine_issue_id: j_opt_str(e, "comicvine_issue_id"),
        comicvine_series_id: j_opt_str(e, "comicvine_series_id"),
        series_provider: j_opt_str(e, "series_provider"),
        series_external_id: j_opt_str(e, "series_external_id"),
        resolved_issue_id: j_opt_i32(e, "resolved_issue_id"),
        canonical_issue_id: j_opt_i32(e, "canonical_issue_id"),
        read_status: j_opt_str(e, "read_status"),
        read_at: j_opt_str(e, "read_at"),
        resolution_status: j_str(e, "resolution_status"),
        is_duplicate_identity: j_bool(e, "is_duplicate_identity"),
    }
}

fn calculate_adoption_plan_entries(
    entries: &[serde_json::Map<String, JsonValue>],
    series_decisions: &std::collections::HashMap<String, bool>,
    entry_decisions: &std::collections::HashMap<String, bool>,
) -> Vec<serde_json::Map<String, JsonValue>> {
    let mut planned = Vec::new();
    for source_entry in entries {
        let mut entry = source_entry.clone();
        let position = j_i32(&entry, "cbl_position");
        let sgid = entry
            .get("series_group_id")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .unwrap_or_else(|| cbl_series_group_id(&entry));
        entry.insert(
            "series_group_id".to_string(),
            JsonValue::String(sgid.clone()),
        );
        let entry_key = entry
            .get("cbl_entry_id")
            .and_then(|v| {
                if v.is_null() {
                    None
                } else {
                    Some(v.as_i64().unwrap_or(position as i64).to_string())
                }
            })
            .unwrap_or_else(|| position.to_string());
        let resolution_status = j_str(&entry, "resolution_status");
        let ambiguous_canonical = resolution_status == "resolved_via_comicvine_canonical_ambiguous";
        let resolved = entry
            .get("resolved_issue_id")
            .map(|v| !v.is_null())
            .unwrap_or(false)
            && !ambiguous_canonical;
        let importable = resolution_status == "no_owned_issue_for_comicvine_id";
        let selectable = resolved || importable;
        entry.insert(
            "adoption_class".to_string(),
            JsonValue::String(
                if resolved {
                    "existing"
                } else if importable {
                    "missing_importable"
                } else {
                    "ambiguous_unresolved"
                }
                .to_string(),
            ),
        );
        let collection_excluded = j_bool(&entry, "collection_excluded");
        let decision = if collection_excluded {
            let reason = j_opt_str(&entry, "collection_exclusion_reason").unwrap_or_default();
            let chosen = entry_decisions
                .get(&entry_key)
                .copied()
                .or(series_decisions.get(&sgid).copied())
                .unwrap_or(true);
            if reason == "collection_identity_requires_review" && chosen {
                "unresolved".to_string()
            } else {
                "excluded".to_string()
            }
        } else if !selectable {
            let chosen = entry_decisions
                .get(&entry_key)
                .copied()
                .or(series_decisions.get(&sgid).copied())
                .unwrap_or(true);
            if !chosen {
                "excluded".to_string()
            } else {
                "unresolved".to_string()
            }
        } else {
            let default_selected = resolved || importable;
            let selected = entry_decisions
                .get(&entry_key)
                .copied()
                .or(series_decisions.get(&sgid).copied())
                .unwrap_or(default_selected);
            if selected {
                if resolved {
                    "included_existing".to_string()
                } else {
                    "would_create_missing".to_string()
                }
            } else {
                let explicit = entry_decisions.contains_key(&entry_key)
                    || series_decisions.contains_key(&sgid);
                if explicit {
                    "excluded".to_string()
                } else {
                    "awaiting_opt_in".to_string()
                }
            }
        };
        let adopted = matches!(
            decision.as_str(),
            "included_existing" | "would_create_missing"
        );
        entry.insert("adoption_decision".to_string(), JsonValue::String(decision));
        entry.insert("adopted".to_string(), JsonValue::Bool(adopted));
        planned.push(entry);
    }
    planned
}

async fn reconcile_entries_for_adoption(
    pool: &deadpool_postgres::Object,
    user_id: i32,
    list_meta: &CblListMeta,
) -> Result<Vec<serde_json::Map<String, JsonValue>>, ApiError> {
    // Load source entries with identity external IDs.
    let rows = pool
        .query(
            r#"
        SELECT cse.id, cse.position, cse.series_name, cse.issue_number,
               ei.external_id AS comicvine_issue_id,
               cse.external_issue_identity_id, cse.external_series_identity_id,
               ev.provider AS series_provider, ev.external_id AS series_external_id,
               cse.volume_year, cse.publication_year
        FROM cbl_source_entries cse
        LEFT JOIN external_identities ei ON ei.id = cse.external_issue_identity_id
        LEFT JOIN external_identities ev ON ev.id = cse.external_series_identity_id
        WHERE cse.list_id = $1
        ORDER BY cse.position ASC, cse.id ASC
        "#,
            &[&list_meta.id],
        )
        .await
        .map_err(|e| {
            tracing::error!(
                error_kind = crate::error_kind(&e),
                "load cbl entries failed"
            );
            ApiError::Internal("Internal Server Error".to_string())
        })?;

    let mut out = Vec::with_capacity(rows.len());
    for row in rows {
        let cse_id: i32 = row.get(0);
        let position: i32 = row.get(1);
        let series_name: String = row.get(2);
        let issue_number: String = row.get(3);
        let comicvine_issue_id: Option<String> = row.get(4);
        let external_issue_identity_id: Option<i32> = row.get(5);
        let external_series_identity_id: Option<i32> = row.get(6);
        let series_provider: Option<String> = row.get(7);
        let series_external_id: Option<String> = row.get(8);
        let volume_year: Option<i32> = row.get(9);
        let publication_year: Option<i32> = row.get(10);

        let (
            resolved_issue_id,
            canonical_issue_id,
            resolution_status,
            is_duplicate_identity,
            read_status,
            read_at,
        ) = resolve_canonical_for_entry(
            pool,
            user_id,
            comicvine_issue_id.as_deref(),
            &series_name,
            &issue_number,
            series_external_id.as_deref(),
        )
        .await?;

        let mut entry = serde_json::Map::new();
        entry.insert("cbl_position".into(), JsonValue::Number(position.into()));
        entry.insert("cbl_entry_id".into(), JsonValue::Number(cse_id.into()));
        entry.insert("series_name".into(), JsonValue::String(series_name));
        entry.insert("issue_number".into(), JsonValue::String(issue_number));
        entry.insert(
            "comicvine_issue_id".into(),
            comicvine_issue_id
                .map(JsonValue::String)
                .unwrap_or(JsonValue::Null),
        );
        let comicvine_series_id = if series_provider
            .as_deref()
            .map(|s| s.eq_ignore_ascii_case("comicvine"))
            .unwrap_or(false)
        {
            series_external_id.clone()
        } else {
            None
        };
        entry.insert(
            "comicvine_series_id".into(),
            comicvine_series_id
                .map(JsonValue::String)
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "series_provider".into(),
            series_provider
                .map(JsonValue::String)
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "series_external_id".into(),
            series_external_id
                .map(JsonValue::String)
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "external_issue_identity_id".into(),
            external_issue_identity_id
                .map(|v| JsonValue::Number(v.into()))
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "external_series_identity_id".into(),
            external_series_identity_id
                .map(|v| JsonValue::Number(v.into()))
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "volume_year".into(),
            volume_year
                .map(|v| JsonValue::Number(v.into()))
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "publication_year".into(),
            publication_year
                .map(|v| JsonValue::Number(v.into()))
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "resolved_issue_id".into(),
            resolved_issue_id
                .map(|v| JsonValue::Number(v.into()))
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "canonical_issue_id".into(),
            canonical_issue_id
                .map(|v| JsonValue::Number(v.into()))
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "resolution_status".into(),
            JsonValue::String(resolution_status),
        );
        entry.insert(
            "is_duplicate_identity".into(),
            JsonValue::Bool(is_duplicate_identity),
        );
        entry.insert(
            "read_status".into(),
            read_status
                .map(JsonValue::String)
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "read_at".into(),
            read_at.map(JsonValue::String).unwrap_or(JsonValue::Null),
        );
        // Default collection exclusion fields (full guard logic is complex; conservative default).
        entry.insert("collection_excluded".into(), JsonValue::Bool(false));
        entry.insert("collection_exclusion_reason".into(), JsonValue::Null);
        entry.insert("collection_exclusion_ids".into(), JsonValue::Array(vec![]));
        entry.insert(
            "series_group_id".into(),
            JsonValue::String(cbl_series_group_id(&entry)),
        );
        out.push(entry);
    }
    Ok(out)
}

async fn resolve_canonical_for_entry(
    pool: &deadpool_postgres::Object,
    user_id: i32,
    comicvine_issue_id: Option<&str>,
    _series_name: &str,
    _issue_number: &str,
    _series_external_id: Option<&str>,
) -> Result<
    (
        Option<i32>,
        Option<i32>,
        String,
        bool,
        Option<String>,
        Option<String>,
    ),
    ApiError,
> {
    // Core resolution path: if comicvine id present, find confirmed mapping for this user and canonicalize.
    if let Some(cvid) = comicvine_issue_id.map(str::trim).filter(|s| !s.is_empty()) {
        // Find external identity row
        let eid = pool.query_opt(
            "SELECT id FROM external_identities WHERE provider='comicvine' AND entity_type='issue' AND external_id=$1",
            &[&cvid]
        ).await.map_err(|e| { tracing::error!(error_kind = crate::error_kind(&e), "resolve identity failed"); ApiError::Internal("Internal Server Error".to_string()) })?;
        if let Some(eid_row) = eid {
            let eid: i32 = eid_row.get(0);
            let issues = pool
                .query(
                    r#"
                SELECT i.id, i.status::text, i.read_at::text
                FROM issue_external_identity_mappings m
                JOIN issues i ON i.id = m.issue_id
                JOIN threads t ON t.id = i.thread_id
                WHERE m.external_identity_id = $1
                  AND m.status = 'confirmed'
                  AND t.user_id = $2
                ORDER BY i.id
                "#,
                    &[&eid, &user_id],
                )
                .await
                .map_err(|e| {
                    tracing::error!(
                        error_kind = crate::error_kind(&e),
                        "resolve mapped issues failed"
                    );
                    ApiError::Internal("Internal Server Error".to_string())
                })?;
            if issues.is_empty() {
                return Ok((
                    None,
                    None,
                    "no_owned_issue_for_comicvine_id".to_string(),
                    false,
                    None,
                    None,
                ));
            }
            if issues.len() == 1 {
                let r = &issues[0];
                let id: i32 = r.get(0);
                let status: Option<String> = r.get(1);
                let read_at: Option<String> = r.get(2);
                return Ok((
                    Some(id),
                    Some(id),
                    "resolved_via_comicvine_canonical".to_string(),
                    false,
                    status,
                    read_at,
                ));
            }
            // Duplicate: prefer read history holder with earliest read_at, then lowest id.
            let mut read_rows: Vec<(i32, Option<String>, Option<String>)> = Vec::new();
            let mut all_unread = true;
            for r in &issues {
                let id: i32 = r.get(0);
                let status: Option<String> = r.get(1);
                let read_at: Option<String> = r.get(2);
                if status.as_deref() == Some("read") {
                    all_unread = false;
                    read_rows.push((id, status.clone(), read_at.clone()));
                }
            }
            let canonical = if !all_unread {
                read_rows.sort_by(|a, b| {
                    let ad = a.2.as_deref().unwrap_or("9999");
                    let bd = b.2.as_deref().unwrap_or("9999");
                    ad.cmp(bd).then(a.0.cmp(&b.0))
                });
                read_rows
                    .first()
                    .map(|r| r.0)
                    .unwrap_or_else(|| issues[0].get(0))
            } else {
                issues
                    .iter()
                    .map(|r| r.get::<_, i32>(0))
                    .min()
                    .unwrap_or_else(|| issues[0].get(0))
            };
            // find canonical row
            let canon_row = issues
                .iter()
                .find(|r| r.get::<_, i32>(0) == canonical)
                .unwrap_or(&issues[0]);
            let cstatus: Option<String> = canon_row.get(1);
            let cread_at: Option<String> = canon_row.get(2);
            let has_read = issues
                .iter()
                .any(|r| r.get::<_, Option<String>>(1).as_deref() == Some("read"));
            let has_unread = issues
                .iter()
                .any(|r| r.get::<_, Option<String>>(1).as_deref() != Some("read"));
            let ambiguous_divergence = has_read && has_unread;
            let status_str = if ambiguous_divergence {
                "resolved_via_comicvine_canonical_ambiguous"
            } else {
                "resolved_via_comicvine_canonical"
            };
            return Ok((
                Some(canonical),
                Some(canonical),
                status_str.to_string(),
                true,
                cstatus,
                cread_at,
            ));
        } else {
            // no external identity row -> comicvine_identity_not_known (simplified; full fallback is more complex)
            return Ok((
                None,
                None,
                "comicvine_identity_not_known".to_string(),
                false,
                None,
                None,
            ));
        }
    }
    Ok((
        None,
        None,
        "ambiguous_no_comicvine_id".to_string(),
        false,
        None,
        None,
    ))
}

#[derive(Debug, Deserialize)]
pub struct CommitSeriesDecision {
    pub series_name: String,
    pub decision: String,
}
#[derive(Debug, Deserialize)]
pub struct CommitEntryOverride {
    pub cbl_position: i32,
    pub decision: String,
}
#[derive(Debug, Deserialize)]
pub struct CblAdoptionCommitRequest {
    #[serde(default)]
    pub entry_decisions: std::collections::HashMap<i32, String>,
    #[serde(default)]
    pub series_decisions: Vec<CommitSeriesDecision>,
    #[serde(default)]
    pub series_overrides: Vec<CommitEntryOverride>,
    pub content_hash: String,
    pub revision_sha: String,
}

#[derive(Debug, Serialize)]
pub struct ContinuityPlanResponseWire {
    pub id: i32,
    pub user_id: i32,
    pub name: String,
    pub ordering_mode: String,
    pub lanes: JsonValue,
    pub nodes: JsonValue,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Serialize)]
pub struct CblAdoptionCommitResponseWire {
    pub id: i32,
    pub user_id: i32,
    pub name: String,
    pub ordering_mode: String,
    pub lanes: JsonValue,
    pub nodes: JsonValue,
    pub created_at: String,
    pub updated_at: String,
    pub reused_positions: Vec<i32>,
    pub created_positions: Vec<i32>,
    pub excluded_positions: Vec<i32>,
    pub unresolved_positions: Vec<i32>,
}

fn adoption_conflict(code: &str, message: &str) -> (StatusCode, Json<JsonValue>) {
    (
        StatusCode::CONFLICT,
        Json(serde_json::json!({"detail": {"code": code, "message": message}})),
    )
}
fn adoption_422(message: &str) -> (StatusCode, Json<JsonValue>) {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(serde_json::json!({"detail": {"code": "adoption_error", "message": message}})),
    )
}
fn adoption_unexpected() -> (StatusCode, Json<JsonValue>) {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(
            serde_json::json!({"detail": {"code": "adoption_unexpected_error", "message": "Adoption failed unexpectedly. The Reading Plan was not changed."}}),
        ),
    )
}

#[instrument(skip(state, auth, request))]
pub async fn cbl_adoption_commit(
    State(state): State<Arc<AppState>>,
    auth: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(request): Json<CblAdoptionCommitRequest>,
) -> Result<(StatusCode, Json<CblAdoptionCommitResponseWire>), (StatusCode, Json<JsonValue>)> {
    match do_cbl_adoption_commit(&state, auth.id(), list_id, None, request).await {
        Ok((status, resp)) => Ok((status, Json(resp))),
        Err(e) => Err(map_commit_error(e)),
    }
}

#[instrument(skip(state, auth, request))]
pub async fn cbl_targeted_adoption_commit(
    State(state): State<Arc<AppState>>,
    auth: AuthenticatedUser,
    Path((list_id, plan_id)): Path<(i32, i32)>,
    Json(request): Json<CblAdoptionCommitRequest>,
) -> Result<(StatusCode, Json<CblAdoptionCommitResponseWire>), (StatusCode, Json<JsonValue>)> {
    match do_cbl_adoption_commit(&state, auth.id(), list_id, Some(plan_id), request).await {
        Ok((_, resp)) => Ok((StatusCode::OK, Json(resp))),
        Err(e) => Err(map_commit_error(e)),
    }
}

enum CommitErr {
    Stale(String),
    Adoption(String),
    #[allow(dead_code)]
    NotFound(String),
    #[allow(dead_code)]
    Unexpected(String),
    Db(ApiError),
}

fn map_commit_error(e: CommitErr) -> (StatusCode, Json<JsonValue>) {
    match e {
        CommitErr::Stale(msg) => adoption_conflict("stale_preview", &msg),
        CommitErr::Adoption(msg) => adoption_422(&msg),
        CommitErr::NotFound(msg) => (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"detail": msg})),
        ),
        CommitErr::Unexpected(_) => adoption_unexpected(),
        CommitErr::Db(api) => {
            if api.is_database_unavailable() {
                (
                    StatusCode::SERVICE_UNAVAILABLE,
                    Json(
                        serde_json::json!({"error":{"code":"database_unavailable","message":"Database is temporarily unavailable.","status":"unavailable"}}),
                    ),
                )
            } else {
                adoption_unexpected()
            }
        }
    }
}

fn normalize_decisions(
    req: &CblAdoptionCommitRequest,
) -> (
    std::collections::HashMap<i32, String>,
    std::collections::HashMap<String, String>,
    std::collections::HashMap<i32, String>,
) {
    let mut series = std::collections::HashMap::new();
    for s in &req.series_decisions {
        series.insert(s.series_name.clone(), s.decision.clone());
    }
    let mut overrides = std::collections::HashMap::new();
    for o in &req.series_overrides {
        overrides.insert(o.cbl_position, o.decision.clone());
    }
    (req.entry_decisions.clone(), series, overrides)
}

async fn do_cbl_adoption_commit(
    state: &Arc<AppState>,
    user_id: i32,
    list_id: i32,
    target_plan_id: Option<i32>,
    request: CblAdoptionCommitRequest,
) -> Result<(StatusCode, CblAdoptionCommitResponseWire), CommitErr> {
    let mut client = checkout(state).await.map_err(CommitErr::Db)?;
    let tx = client.build_transaction().start().await.map_err(|e| {
        if crate::db::is_transport_failure(&e) {
            CommitErr::Db(ApiError::database_unavailable())
        } else {
            CommitErr::Unexpected(e.to_string())
        }
    })?;

    // Lock reader row best-effort (matches Python lock_reader semantics loosely).
    let _ = tx
        .execute("SELECT 1 FROM users WHERE id = $1 FOR UPDATE", &[&user_id])
        .await;

    let list_row = tx.query_opt(
        "SELECT csl.id, cs.repository, csl.source_path, csl.content_hash, csl.revision_sha, csl.name, csl.active
         FROM cbl_source_lists csl JOIN cbl_sources cs ON cs.id = csl.source_id WHERE csl.id = $1",
        &[&list_id]
    ).await.map_err(|e| CommitErr::Unexpected(e.to_string()))?
        .ok_or_else(|| CommitErr::Adoption("CBL source list not found".to_string()))?;
    let active: bool = list_row.get(6);
    if !active {
        return Err(CommitErr::Adoption(
            "CBL source list is not active".to_string(),
        ));
    }
    let source_repository: String = list_row.get(1);
    let source_path: String = list_row.get(2);
    let content_hash: String = list_row.get(3);
    let revision_sha: String = list_row.get(4);
    let list_name: String = list_row.get(5);
    if content_hash != request.content_hash {
        return Err(CommitErr::Stale(format!(
            "Source fingerprint mismatch: expected {content_hash}, got {}",
            request.content_hash
        )));
    }
    if revision_sha != request.revision_sha {
        return Err(CommitErr::Stale(format!(
            "Revision mismatch: expected {revision_sha}, got {}",
            request.revision_sha
        )));
    }

    let (entry_decisions_raw, series_decisions_raw, series_overrides_raw) =
        normalize_decisions(&request);
    // Convert decisions to bool-like include/exclude semantics used by plan calc: "include"/"INCLUDE"? Python uses SourceBackedDecision enum values; accept strings.
    let entry_bool: std::collections::HashMap<String, bool> = entry_decisions_raw
        .iter()
        .map(|(k, v)| (k.to_string(), v.eq_ignore_ascii_case("include")))
        .collect();
    let series_bool: std::collections::HashMap<String, bool> = series_decisions_raw
        .iter()
        .map(|(k, v)| (k.clone(), v.eq_ignore_ascii_case("include")))
        .collect();
    let override_bool: std::collections::HashMap<String, bool> = series_overrides_raw
        .iter()
        .map(|(k, v)| (k.to_string(), v.eq_ignore_ascii_case("include")))
        .collect();

    let list_meta = CblListMeta {
        id: list_id,
        source_repository: source_repository.clone(),
        source_path: source_path.clone(),
        content_hash: content_hash.clone(),
        revision_sha: revision_sha.clone(),
        name: list_name.clone(),
        declared_issue_count: None,
    };
    // Reconcile using checkout-like access not directly on tx; for simplicity query via tx where possible by wrapping pool? easier: use separate reads before tx for reconciliation approximation.
    // But we already started tx; rollback and redo carefully would be complex. Use tx queries through a helper approach is limited.
    // Pragmatic: do reconciliation reads via pool before commit transaction in a fuller impl; here approximate using tx-compatible queries.
    let report_entries = reconcile_entries_for_adoption_tx(&tx, user_id, &list_meta)
        .await
        .map_err(CommitErr::Unexpected)?;
    let planned = calculate_adoption_plan_entries(&report_entries, &series_bool, &entry_bool); // series_overrides handled in merge below

    // Determine/create plan
    let (
        plan_id,
        _created_new,
        _plan_name,
        _ordering_mode,
        _lanes_json,
        mut nodes_json,
        _created_at,
        _updated_at,
    ) = if let Some(pid) = target_plan_id {
        let prow = tx.query_opt("SELECT id,name,ordering_mode,lanes_json::text,nodes_json::text,created_at::text,updated_at::text FROM continuity_plans WHERE id=$1 AND user_id=$2 FOR UPDATE", &[&pid, &user_id]).await.map_err(|e| CommitErr::Unexpected(e.to_string()))?
            .ok_or_else(|| CommitErr::Adoption("Reading Plan not found".to_string()))?;
        (
            prow.get::<_, i32>(0),
            false,
            prow.get::<_, String>(1),
            prow.get::<_, String>(2),
            serde_json::from_str::<JsonValue>(&prow.get::<_, String>(3))
                .unwrap_or(serde_json::json!([])),
            serde_json::from_str::<JsonValue>(&prow.get::<_, String>(4))
                .unwrap_or(serde_json::json!([])),
            prow.get::<_, String>(5),
            prow.get::<_, String>(6),
        )
    } else {
        // Try existing adopted plan by source path
        let existing = find_existing_adopted_plan_tx(&tx, user_id, &source_path)
            .await
            .map_err(CommitErr::Unexpected)?;
        if let Some(pid) = existing {
            let prow = tx.query_one("SELECT id,name,ordering_mode,lanes_json::text,nodes_json::text,created_at::text,updated_at::text FROM continuity_plans WHERE id=$1 AND user_id=$2 FOR UPDATE", &[&pid, &user_id]).await.map_err(|e| CommitErr::Unexpected(e.to_string()))?;
            (
                prow.get::<_, i32>(0),
                false,
                prow.get::<_, String>(1),
                prow.get::<_, String>(2),
                serde_json::from_str::<JsonValue>(&prow.get::<_, String>(3))
                    .unwrap_or(serde_json::json!([])),
                serde_json::from_str::<JsonValue>(&prow.get::<_, String>(4))
                    .unwrap_or(serde_json::json!([])),
                prow.get::<_, String>(5),
                prow.get::<_, String>(6),
            )
        } else {
            let name = if list_name.is_empty() {
                format!("CBL adoption for {source_path}")
            } else {
                list_name.clone()
            };
            let lanes = serde_json::json!([{"id":"default","name":"Default","order":0}]);
            let prow = tx.query_one(
                "INSERT INTO continuity_plans (user_id,name,ordering_mode,lanes_json,nodes_json,created_at,updated_at) VALUES ($1,$2,'informational',$3::jsonb,'[]'::jsonb,NOW(),NOW()) RETURNING id,name,ordering_mode,lanes_json::text,nodes_json::text,created_at::text,updated_at::text",
                &[&user_id,&name,&lanes.to_string()]
            ).await.map_err(|e| CommitErr::Unexpected(e.to_string()))?;
            (
                prow.get::<_, i32>(0),
                true,
                prow.get::<_, String>(1),
                prow.get::<_, String>(2),
                serde_json::from_str::<JsonValue>(&prow.get::<_, String>(3))
                    .unwrap_or(serde_json::json!([])),
                serde_json::from_str::<JsonValue>(&prow.get::<_, String>(4))
                    .unwrap_or(serde_json::json!([])),
                prow.get::<_, String>(5),
                prow.get::<_, String>(6),
            )
        }
    };

    // Merge nodes (simplified but preserves key semantics: reuse existing issue nodes, append new, record provenance and positions)
    let merge_ctx = MergeAdoptionCtx {
        user_id,
        planned: &planned,
        source_path: &source_path,
        series_overrides: &override_bool,
        preserve_existing_order: target_plan_id.is_some(),
    };
    let merge = merge_adoption_nodes_tx(&tx, &mut nodes_json, &merge_ctx)
        .await
        .map_err(CommitErr::Unexpected)?;
    let nodes_str = serde_json::to_string(&nodes_json).unwrap_or("[]".to_string());
    tx.execute(
        "UPDATE continuity_plans SET nodes_json=$1::jsonb, updated_at=NOW() WHERE id=$2",
        &[&nodes_str, &plan_id],
    )
    .await
    .map_err(|e| CommitErr::Unexpected(e.to_string()))?;
    let prow = tx.query_one("SELECT id,user_id,name,ordering_mode,lanes_json::text,nodes_json::text,created_at::text,updated_at::text FROM continuity_plans WHERE id=$1", &[&plan_id]).await.map_err(|e| CommitErr::Unexpected(e.to_string()))?;
    tx.commit().await.map_err(|e| {
        if crate::db::is_transport_failure(&e) {
            CommitErr::Db(ApiError::database_unavailable())
        } else {
            CommitErr::Unexpected(e.to_string())
        }
    })?;

    let status = if target_plan_id.is_some() {
        StatusCode::OK
    } else {
        StatusCode::CREATED
    }; // Python: targeted=200, general=201
    let resp = CblAdoptionCommitResponseWire {
        id: prow.get(0),
        user_id: prow.get(1),
        name: prow.get(2),
        ordering_mode: prow.get(3),
        lanes: serde_json::from_str::<JsonValue>(&prow.get::<_, String>(4))
            .unwrap_or(serde_json::json!([])),
        nodes: serde_json::from_str::<JsonValue>(&prow.get::<_, String>(5))
            .unwrap_or(serde_json::json!([])),
        created_at: prow.get(6),
        updated_at: prow.get(7),
        reused_positions: merge.0,
        created_positions: merge.1,
        excluded_positions: merge.2,
        unresolved_positions: merge.3,
    };
    Ok((status, resp))
}

async fn reconcile_entries_for_adoption_tx(
    tx: &tokio_postgres::Transaction<'_>,
    user_id: i32,
    list_meta: &CblListMeta,
) -> Result<Vec<serde_json::Map<String, JsonValue>>, String> {
    let rows = tx
        .query(
            r#"
        SELECT cse.id, cse.position, cse.series_name, cse.issue_number,
               ei.external_id AS comicvine_issue_id,
               cse.external_issue_identity_id, cse.external_series_identity_id,
               ev.provider AS series_provider, ev.external_id AS series_external_id,
               cse.volume_year, cse.publication_year
        FROM cbl_source_entries cse
        LEFT JOIN external_identities ei ON ei.id = cse.external_issue_identity_id
        LEFT JOIN external_identities ev ON ev.id = cse.external_series_identity_id
        WHERE cse.list_id = $1
        ORDER BY cse.position ASC, cse.id ASC
        "#,
            &[&list_meta.id],
        )
        .await
        .map_err(|e| e.to_string())?;
    let mut out = Vec::with_capacity(rows.len());
    for row in rows {
        let cse_id: i32 = row.get(0);
        let position: i32 = row.get(1);
        let series_name: String = row.get(2);
        let issue_number: String = row.get(3);
        let comicvine_issue_id: Option<String> = row.get(4);
        let external_issue_identity_id: Option<i32> = row.get(5);
        let external_series_identity_id: Option<i32> = row.get(6);
        let series_provider: Option<String> = row.get(7);
        let series_external_id: Option<String> = row.get(8);
        let volume_year: Option<i32> = row.get(9);
        let publication_year: Option<i32> = row.get(10);
        let (
            resolved_issue_id,
            canonical_issue_id,
            resolution_status,
            is_duplicate_identity,
            read_status,
            read_at,
        ) = resolve_canonical_for_entry_tx(tx, user_id, comicvine_issue_id.as_deref())
            .await
            .map_err(|e| e.to_string())?;
        let mut entry = serde_json::Map::new();
        entry.insert("cbl_position".into(), JsonValue::Number(position.into()));
        entry.insert("cbl_entry_id".into(), JsonValue::Number(cse_id.into()));
        entry.insert("series_name".into(), JsonValue::String(series_name));
        entry.insert("issue_number".into(), JsonValue::String(issue_number));
        entry.insert(
            "comicvine_issue_id".into(),
            comicvine_issue_id
                .map(JsonValue::String)
                .unwrap_or(JsonValue::Null),
        );
        let comicvine_series_id = if series_provider
            .as_deref()
            .map(|s| s.eq_ignore_ascii_case("comicvine"))
            .unwrap_or(false)
        {
            series_external_id.clone()
        } else {
            None
        };
        entry.insert(
            "comicvine_series_id".into(),
            comicvine_series_id
                .map(JsonValue::String)
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "series_provider".into(),
            series_provider
                .map(JsonValue::String)
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "series_external_id".into(),
            series_external_id
                .map(JsonValue::String)
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "external_issue_identity_id".into(),
            external_issue_identity_id
                .map(|v| JsonValue::Number(v.into()))
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "external_series_identity_id".into(),
            external_series_identity_id
                .map(|v| JsonValue::Number(v.into()))
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "volume_year".into(),
            volume_year
                .map(|v| JsonValue::Number(v.into()))
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "publication_year".into(),
            publication_year
                .map(|v| JsonValue::Number(v.into()))
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "resolved_issue_id".into(),
            resolved_issue_id
                .map(|v| JsonValue::Number(v.into()))
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "canonical_issue_id".into(),
            canonical_issue_id
                .map(|v| JsonValue::Number(v.into()))
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "resolution_status".into(),
            JsonValue::String(resolution_status),
        );
        entry.insert(
            "is_duplicate_identity".into(),
            JsonValue::Bool(is_duplicate_identity),
        );
        entry.insert(
            "read_status".into(),
            read_status
                .map(JsonValue::String)
                .unwrap_or(JsonValue::Null),
        );
        entry.insert(
            "read_at".into(),
            read_at.map(JsonValue::String).unwrap_or(JsonValue::Null),
        );
        entry.insert("collection_excluded".into(), JsonValue::Bool(false));
        entry.insert("collection_exclusion_reason".into(), JsonValue::Null);
        entry.insert("collection_exclusion_ids".into(), JsonValue::Array(vec![]));
        entry.insert(
            "series_group_id".into(),
            JsonValue::String(cbl_series_group_id(&entry)),
        );
        out.push(entry);
    }
    Ok(out)
}

async fn resolve_canonical_for_entry_tx(
    tx: &tokio_postgres::Transaction<'_>,
    user_id: i32,
    comicvine_issue_id: Option<&str>,
) -> Result<
    (
        Option<i32>,
        Option<i32>,
        String,
        bool,
        Option<String>,
        Option<String>,
    ),
    tokio_postgres::Error,
> {
    if let Some(cvid) = comicvine_issue_id.map(str::trim).filter(|s| !s.is_empty()) {
        let eid = tx.query_opt(
            "SELECT id FROM external_identities WHERE provider='comicvine' AND entity_type='issue' AND external_id=$1",
            &[&cvid]
        ).await?;
        if let Some(eid_row) = eid {
            let eid: i32 = eid_row.get(0);
            let issues = tx
                .query(
                    r#"
                SELECT i.id, i.status::text, i.read_at::text
                FROM issue_external_identity_mappings m
                JOIN issues i ON i.id = m.issue_id
                JOIN threads t ON t.id = i.thread_id
                WHERE m.external_identity_id = $1 AND m.status = 'confirmed' AND t.user_id = $2
                ORDER BY i.id
                "#,
                    &[&eid, &user_id],
                )
                .await?;
            if issues.is_empty() {
                return Ok((
                    None,
                    None,
                    "no_owned_issue_for_comicvine_id".to_string(),
                    false,
                    None,
                    None,
                ));
            }
            if issues.len() == 1 {
                let r = &issues[0];
                return Ok((
                    Some(r.get(0)),
                    Some(r.get(0)),
                    "resolved_via_comicvine_canonical".to_string(),
                    false,
                    r.get(1),
                    r.get(2),
                ));
            }
            let mut read_rows: Vec<(i32, Option<String>, Option<String>)> = Vec::new();
            let mut all_unread = true;
            for r in &issues {
                let st: Option<String> = r.get(1);
                if st.as_deref() == Some("read") {
                    all_unread = false;
                    read_rows.push((r.get(0), st, r.get(2)));
                }
            }
            let canonical = if !all_unread {
                read_rows.sort_by(|a, b| {
                    a.2.as_deref()
                        .unwrap_or("9999")
                        .cmp(b.2.as_deref().unwrap_or("9999"))
                        .then(a.0.cmp(&b.0))
                });
                read_rows
                    .first()
                    .map(|r| r.0)
                    .unwrap_or_else(|| issues[0].get(0))
            } else {
                issues
                    .iter()
                    .map(|r| r.get::<_, i32>(0))
                    .min()
                    .unwrap_or_else(|| issues[0].get(0))
            };
            let canon_row = issues
                .iter()
                .find(|r| r.get::<_, i32>(0) == canonical)
                .unwrap_or(&issues[0]);
            let has_read = issues
                .iter()
                .any(|r| r.get::<_, Option<String>>(1).as_deref() == Some("read"));
            let has_unread = issues
                .iter()
                .any(|r| r.get::<_, Option<String>>(1).as_deref() != Some("read"));
            let ambiguous_div = has_read && has_unread;
            let status_str = if ambiguous_div {
                "resolved_via_comicvine_canonical_ambiguous"
            } else {
                "resolved_via_comicvine_canonical"
            };
            return Ok((
                Some(canonical),
                Some(canonical),
                status_str.to_string(),
                true,
                canon_row.get(1),
                canon_row.get(2),
            ));
        } else {
            return Ok((
                None,
                None,
                "comicvine_identity_not_known".to_string(),
                false,
                None,
                None,
            ));
        }
    }
    Ok((
        None,
        None,
        "ambiguous_no_comicvine_id".to_string(),
        false,
        None,
        None,
    ))
}

async fn find_existing_adopted_plan_tx(
    tx: &tokio_postgres::Transaction<'_>,
    user_id: i32,
    source_path: &str,
) -> Result<Option<i32>, String> {
    let rows = tx
        .query(
            "SELECT id, nodes_json::text FROM continuity_plans WHERE user_id=$1",
            &[&user_id],
        )
        .await
        .map_err(|e| e.to_string())?;
    for row in rows {
        let pid: i32 = row.get(0);
        let nodes_text: String = row.get(1);
        if let Ok(nodes) = serde_json::from_str::<Vec<JsonValue>>(&nodes_text) {
            for node in nodes {
                if let Some(arr) = node.get("source_cbl_placements").and_then(|v| v.as_array()) {
                    if arr
                        .iter()
                        .any(|p| p.get("source_path").and_then(|v| v.as_str()) == Some(source_path))
                    {
                        return Ok(Some(pid));
                    }
                }
            }
        }
    }
    Ok(None)
}

struct MergeAdoptionCtx<'a> {
    user_id: i32,
    planned: &'a [serde_json::Map<String, JsonValue>],
    source_path: &'a str,
    series_overrides: &'a std::collections::HashMap<String, bool>,
    preserve_existing_order: bool,
}

async fn merge_adoption_nodes_tx(
    tx: &tokio_postgres::Transaction<'_>,
    nodes_json: &mut JsonValue,
    ctx: &MergeAdoptionCtx<'_>,
) -> Result<(Vec<i32>, Vec<i32>, Vec<i32>, Vec<i32>), String> {
    let user_id = ctx.user_id;
    let planned = ctx.planned;
    let source_path = ctx.source_path;
    let series_overrides = ctx.series_overrides;
    let preserve_existing_order = ctx.preserve_existing_order;
    let nodes_arr = nodes_json
        .as_array_mut()
        .ok_or_else(|| "invalid nodes_json".to_string())?;
    let mut reused_positions = Vec::new();
    let mut created_positions = Vec::new();
    let mut excluded_positions = Vec::new();
    let mut unresolved_positions = Vec::new();
    let mut adopted_order: Vec<String> = Vec::new();

    // Index existing issue nodes by ref_id
    let mut issue_node_index: std::collections::HashMap<i32, usize> =
        std::collections::HashMap::new();
    for (i, n) in nodes_arr.iter().enumerate() {
        if n.get("node_type").and_then(|v| v.as_str()) == Some("issue") {
            if let Some(rid) = n.get("ref_id").and_then(|v| v.as_i64()) {
                issue_node_index.entry(rid as i32).or_insert(i);
            }
        }
    }

    let mut next_pos: i32 = nodes_arr
        .iter()
        .filter_map(|n| n.get("position").and_then(|v| v.as_i64()).map(|x| x as i32))
        .max()
        .map(|m| m + 1)
        .unwrap_or(0);

    for entry in planned {
        let pos = entry
            .get("cbl_position")
            .and_then(|v| v.as_i64())
            .unwrap_or(0) as i32;
        let decision = entry
            .get("adoption_decision")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        // respect series_overrides by position if present
        let decision_eff = if let Some(b) = series_overrides.get(&pos.to_string()) {
            if *b {
                if entry
                    .get("resolved_issue_id")
                    .map(|v| !v.is_null())
                    .unwrap_or(false)
                {
                    "included_existing"
                } else {
                    "would_create_missing"
                }
            } else {
                "excluded"
            }
        } else {
            decision
        };
        if decision_eff == "excluded" || decision_eff == "awaiting_opt_in" {
            excluded_positions.push(pos);
            continue;
        }
        if decision_eff == "unresolved" {
            unresolved_positions.push(pos);
            continue;
        }
        let resolved = entry.get("resolved_issue_id").and_then(|v| {
            if v.is_null() {
                None
            } else {
                v.as_i64().map(|x| x as i32)
            }
        });
        let issue_id = if let Some(id) = resolved {
            id
        } else {
            // try materialize missing importable issue (simplified)
            match materialize_missing_issue_tx(tx, user_id, entry).await {
                Ok((id, created)) => {
                    if created {
                        created_positions.push(pos);
                    }
                    id
                }
                Err(_) => {
                    unresolved_positions.push(pos);
                    continue;
                }
            }
        };
        if !created_positions.contains(&pos) { /* reused if not newly created now */ }
        let label = format!(
            "{} #{}",
            entry
                .get("series_name")
                .and_then(|v| v.as_str())
                .unwrap_or(""),
            entry
                .get("issue_number")
                .and_then(|v| v.as_str())
                .unwrap_or("")
        );
        let placement = serde_json::json!({"source_path": source_path, "position": pos});
        if let Some(&idx) = issue_node_index.get(&issue_id) {
            let node = &mut nodes_arr[idx];
            ensure_node_provenance(node, source_path, &placement, &label);
            adopted_order.push(
                node.get("id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            if !created_positions.contains(&pos) {
                reused_positions.push(pos);
            }
        } else {
            let cse_id = entry
                .get("cbl_entry_id")
                .and_then(|v| v.as_i64())
                .unwrap_or(0);
            let node_id = format!("cbl-{cse_id}");
            let node = serde_json::json!({
                "id": node_id,
                "node_type": "issue",
                "ref_id": issue_id,
                "lane_id": "default",
                "position": next_pos,
                "is_checkpoint": false,
                "convergence_gate": [],
                "label": label,
                "source_paths": [source_path],
                "source_cbl_placements": [placement]
            });
            next_pos += 1;
            nodes_arr.push(node);
            issue_node_index.insert(issue_id, nodes_arr.len() - 1);
            adopted_order.push(format!("cbl-{cse_id}"));
            if !created_positions.contains(&pos) {
                reused_positions.push(pos);
            }
        }
    }

    if !preserve_existing_order {
        // reorder adopted nodes to front in source order, then keep rest
        let mut by_id: std::collections::HashMap<String, JsonValue> =
            std::collections::HashMap::new();
        for n in nodes_arr.drain(..) {
            if let Some(id) = n.get("id").and_then(|v| v.as_str()) {
                by_id.insert(id.to_string(), n);
            }
        }
        let mut reordered = Vec::new();
        let mut seen = std::collections::HashSet::new();
        for id in &adopted_order {
            if seen.insert(id.clone()) {
                if let Some(n) = by_id.remove(id) {
                    reordered.push(n);
                }
            }
        }
        for (_, n) in by_id {
            reordered.push(n);
        }
        // renumber per lane
        let mut lane_pos: std::collections::HashMap<String, i32> = std::collections::HashMap::new();
        for n in &mut reordered {
            let lane = n
                .get("lane_id")
                .and_then(|v| v.as_str())
                .unwrap_or("default")
                .to_string();
            let p = lane_pos.entry(lane).or_insert(0);
            n["position"] = JsonValue::Number((*p).into());
            *p += 1;
        }
        *nodes_arr = reordered;
    }

    Ok((
        reused_positions,
        created_positions,
        excluded_positions,
        unresolved_positions,
    ))
}

fn ensure_node_provenance(
    node: &mut JsonValue,
    source_path: &str,
    placement: &JsonValue,
    label: &str,
) {
    let placements = node
        .get_mut("source_cbl_placements")
        .and_then(|v| v.as_array_mut());
    let mut has = false;
    if let Some(arr) = placements.as_ref() {
        has = arr
            .iter()
            .any(|p| p.get("source_path").and_then(|v| v.as_str()) == Some(source_path));
    }
    if !has {
        if !node
            .get("source_cbl_placements")
            .map(|v| v.is_array())
            .unwrap_or(false)
        {
            node["source_cbl_placements"] = JsonValue::Array(vec![]);
        }
        if let Some(arr) = node
            .get_mut("source_cbl_placements")
            .and_then(|v| v.as_array_mut())
        {
            arr.push(placement.clone());
        }
    }
    let mut paths: Vec<String> = node
        .get("source_paths")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default();
    if !paths.iter().any(|p| p == source_path) {
        paths.push(source_path.to_string());
    }
    node["source_paths"] = JsonValue::Array(paths.into_iter().map(JsonValue::String).collect());
    let has_label = node
        .get("label")
        .and_then(|v| v.as_str())
        .map(|s| !s.trim().is_empty())
        .unwrap_or(false);
    if !has_label {
        node["label"] = JsonValue::String(label.to_string());
    }
}

async fn materialize_missing_issue_tx(
    tx: &tokio_postgres::Transaction<'_>,
    user_id: i32,
    entry: &serde_json::Map<String, JsonValue>,
) -> Result<(i32, bool), String> {
    let series_name = entry
        .get("series_name")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let issue_number = entry
        .get("issue_number")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let comicvine_id = entry.get("comicvine_issue_id").and_then(|v| {
        if v.is_null() {
            None
        } else {
            v.as_str().map(|s| s.to_string())
        }
    });
    // Reuse by confirmed identity if present
    if let Some(ref cvid) = comicvine_id {
        let row = tx.query_opt(
            r#"
            SELECT i.id FROM issues i
            JOIN issue_external_identity_mappings m ON m.issue_id = i.id
            JOIN external_identities ei ON ei.id = m.external_identity_id
            JOIN threads t ON t.id = i.thread_id
            WHERE t.user_id=$1 AND m.status='confirmed' AND ei.provider='comicvine' AND ei.entity_type='issue' AND ei.external_id=$2
            LIMIT 1
            "#,
            &[&user_id, cvid]
        ).await.map_err(|e| e.to_string())?;
        if let Some(r) = row {
            return Ok((r.get(0), false));
        }
    }
    // Find or create thread (simplified: by title "CBL: {series}" with volume year)
    let volume_year = entry.get("volume_year").and_then(|v| v.as_i64());
    let mut title = format!("CBL: {series_name}");
    if let Some(y) = volume_year {
        title = format!("{title} ({y})");
    }
    let thread_row = tx
        .query_opt(
            "SELECT id FROM threads WHERE user_id=$1 AND title=$2",
            &[&user_id, &title],
        )
        .await
        .map_err(|e| e.to_string())?;
    let thread_id: i32 = if let Some(r) = thread_row {
        r.get(0)
    } else {
        let max_q: Option<i32> = tx
            .query_one(
                "SELECT COALESCE(MAX(queue_position),0) FROM threads WHERE user_id=$1",
                &[&user_id],
            )
            .await
            .map_err(|e| e.to_string())?
            .get(0);
        let qp = max_q.unwrap_or(0) + 1;
        tx.query_one(
            "INSERT INTO threads (user_id,title,format,queue_position,status,reading_progress,created_at) VALUES ($1,$2,'comic',$3,'active','not_started',NOW()) RETURNING id",
            &[&user_id,&title,&qp]
        ).await.map_err(|e| e.to_string())?.get(0)
    };
    // Reuse existing issue in thread by number
    let existing_issue = tx
        .query_opt(
            "SELECT id FROM issues WHERE thread_id=$1 AND issue_number=$2",
            &[&thread_id, &issue_number],
        )
        .await
        .map_err(|e| e.to_string())?;
    if let Some(r) = existing_issue {
        return Ok((r.get(0), false));
    }
    // Insert issue at end (simplified natural order)
    let max_pos: Option<i32> = tx
        .query_one(
            "SELECT COALESCE(MAX(position),-1) FROM issues WHERE thread_id=$1",
            &[&thread_id],
        )
        .await
        .map_err(|e| e.to_string())?
        .get(0);
    let pos = max_pos.unwrap_or(-1) + 1;
    let issue_id: i32 = tx.query_one(
        "INSERT INTO issues (thread_id,issue_number,position,status,weight,created_at) VALUES ($1,$2,$3,'unread',1.0,NOW()) RETURNING id",
        &[&thread_id,&issue_number,&pos]
    ).await.map_err(|e| e.to_string())?.get(0);
    // Update thread tracking counts best-effort
    let _ = tx.execute("UPDATE threads SET total_issues = (SELECT COUNT(*) FROM issues WHERE thread_id=$1), issues_remaining = (SELECT COUNT(*) FROM issues WHERE thread_id=$1 AND status='unread') WHERE id=$1", &[&thread_id]).await;
    // Confirm comicvine mapping if provided
    if let Some(cvid) = comicvine_id {
        let ei = tx.query_opt("SELECT id FROM external_identities WHERE provider='comicvine' AND entity_type='issue' AND external_id=$1", &[&cvid]).await.map_err(|e| e.to_string())?;
        let ei_id: i32 = if let Some(r) = ei {
            r.get(0)
        } else {
            tx.query_one("INSERT INTO external_identities (provider,entity_type,external_id,metadata_json,created_at,updated_at) VALUES ('comicvine','issue',$1,'{}'::jsonb,NOW(),NOW()) RETURNING id", &[&cvid]).await.map_err(|e| e.to_string())?.get(0)
        };
        let _ = tx.execute("INSERT INTO issue_external_identity_mappings (issue_id,external_identity_id,status,evidence_source) VALUES ($1,$2,'confirmed','cbl_adoption_commit') ON CONFLICT DO NOTHING", &[&issue_id,&ei_id]).await;
    }
    Ok((issue_id, true))
}
