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
