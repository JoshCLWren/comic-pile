//! Read-only browsing of the shared CBL catalog folder tree and search.
//!
//! Same-path native replacement for the browser-called issue-identity catalog reads (#4843):
//!
//! * `GET /api/v1/issue-identity/cbl-sources/folders`
//! * `GET /api/v1/issue-identity/cbl-sources/browse`
//!
//! Ownership-free: reads only `cbl_sources` / `cbl_source_lists` and never joins
//! reader-owned tables, so results are identical for every authenticated account.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio_postgres::Row;
use utoipa::{IntoParams, OpenApi, ToSchema};

/// Python `MAX_FOLDER_LENGTH`, measured in characters.
const MAX_FOLDER_LENGTH: usize = 1000;
/// Python `MAX_SEARCH_LENGTH`, measured in characters.
const MAX_SEARCH_LENGTH: usize = 200;
const MAX_PAGE_SIZE: i64 = 100;
const ROOT_BREADCRUMB_NAME: &str = "All CBLs";
const MIRROR_NAME: &str = "CBL-ReadingLists";
const MIRROR_PATH_MARKER: &str = "/CBL-ReadingLists";
const PUBLIC_REPOSITORY: &str = "JoshCLWren/CBL-ReadingLists";
const PUBLIC_REPOSITORY_FALLBACK: &str = "CBL source";
const CATALOG_UNAVAILABLE_CODE: &str = "cbl_catalog_unavailable";
const CATALOG_UNAVAILABLE_MESSAGE: &str = "The shared CBL catalog is temporarily unavailable.";

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct CBLCatalogListItem {
    pub id: i32,
    pub name: String,
    pub source_path: String,
    pub source_repository: String,
    pub declared_issue_count: Option<i32>,
    pub content_hash: String,
    pub revision_sha: String,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct CBLSourceFolder {
    pub name: String,
    pub path: String,
    pub direct_list_count: i32,
    pub total_list_count: i32,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct CBLBreadcrumb {
    pub name: String,
    pub path: String,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct CBLFolderListingResponse {
    pub folder: String,
    pub breadcrumbs: Vec<CBLBreadcrumb>,
    pub folders: Vec<CBLSourceFolder>,
    pub direct_list_count: i32,
    pub total_list_count: i32,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct CBLCatalogBrowseResponse {
    pub scope: String,
    pub folder: String,
    pub query: Option<String>,
    pub breadcrumbs: Vec<CBLBreadcrumb>,
    pub folders: Vec<CBLSourceFolder>,
    pub items: Vec<CBLCatalogListItem>,
    /// Echoed requested page number; preserved for extreme values (e.g. 2^63).
    #[schema(value_type = i64)]
    pub page: serde_json::Number,
    pub page_size: i64,
    pub total: i64,
    pub total_pages: i64,
    pub has_next: bool,
    pub has_previous: bool,
}

/// Error detail for catalog-originated failures (400/404/503).
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct CBLErrorDetail {
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct CBLErrorResponse {
    pub detail: CBLErrorDetail,
}

/// Global dependency-acquisition outage shape.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct CBLDatabaseUnavailableDetail {
    pub code: String,
    pub message: String,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct CBLDatabaseUnavailableResponse {
    pub error: CBLDatabaseUnavailableDetail,
}

/// FastAPI/Pydantic validation error item shape (422).
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ValidationErrorItem {
    #[serde(rename = "type")]
    pub error_type: String,
    pub loc: Vec<String>,
    pub msg: String,
    pub input: serde_json::Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ctx: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ValidationErrorResponse {
    pub detail: Vec<ValidationErrorItem>,
}

/// Query params for folder listing. Parsed as raw strings so malformed values can be
/// rejected with the Python/FastAPI 422 contract at the handler boundary.
#[derive(Debug, Deserialize, IntoParams, Default)]
pub struct CBLFolderListQuery {
    #[serde(default)]
    pub folder: Option<String>,
}

/// Query params for catalog browse. `page`/`page_size` are raw strings to preserve
/// Python's accepted integer range (including values like 2^63) and to translate
/// malformed/bound failures into FastAPI-compatible 422 responses.
#[derive(Debug, Deserialize, IntoParams, Default)]
pub struct CBLCatalogBrowseQuery {
    #[serde(default)]
    pub folder: Option<String>,
    pub q: Option<String>,
    #[serde(default)]
    pub page: Option<String>,
    #[serde(default)]
    pub page_size: Option<String>,
}

#[derive(Debug)]
enum CatalogError {
    InvalidFolder(String),
    FolderNotFound(String),
    Validation(String),
    ValidationItems(Vec<ValidationErrorItem>),
    Unavailable,
    Database(ApiError),
}

impl From<ApiError> for CatalogError {
    fn from(error: ApiError) -> Self {
        CatalogError::Database(error)
    }
}

impl From<tokio_postgres::Error> for CatalogError {
    fn from(error: tokio_postgres::Error) -> Self {
        tracing::warn!(
            error_kind = crate::error_kind(&error),
            "CBL catalog query failed"
        );
        CatalogError::Unavailable
    }
}

fn catalog_error(status: StatusCode, code: &str, message: String) -> Response {
    (
        status,
        Json(serde_json::json!({"detail": {"code": code, "message": message}})),
    )
        .into_response()
}

impl IntoResponse for CatalogError {
    fn into_response(self) -> Response {
        match self {
            CatalogError::InvalidFolder(message) => {
                catalog_error(StatusCode::BAD_REQUEST, "invalid_folder", message)
            }
            CatalogError::FolderNotFound(folder) => catalog_error(
                StatusCode::NOT_FOUND,
                "folder_not_found",
                format!("CBL folder not found: {folder}"),
            ),
            CatalogError::Validation(message) => (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(serde_json::json!({"detail": message})),
            )
                .into_response(),
            CatalogError::ValidationItems(items) => (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(ValidationErrorResponse { detail: items }),
            )
                .into_response(),
            CatalogError::Unavailable => catalog_error(
                StatusCode::SERVICE_UNAVAILABLE,
                CATALOG_UNAVAILABLE_CODE,
                CATALOG_UNAVAILABLE_MESSAGE.to_string(),
            ),
            CatalogError::Database(error) => error.into_response(),
        }
    }
}

fn validation_int_parsing(field: &str, input: &str) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: "int_parsing".to_string(),
        loc: vec!["query".to_string(), field.to_string()],
        msg: "Input should be a valid integer, unable to parse string as an integer".to_string(),
        input: serde_json::Value::String(input.to_string()),
        ctx: None,
    }
}

fn validation_greater_than_equal(field: &str, input: &str, ge: i64) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: "greater_than_equal".to_string(),
        loc: vec!["query".to_string(), field.to_string()],
        msg: format!("Input should be greater than or equal to {ge}"),
        input: serde_json::Value::String(input.to_string()),
        ctx: Some(serde_json::json!({"ge": ge})),
    }
}

fn validation_less_than_equal(field: &str, input: &str, le: i64) -> ValidationErrorItem {
    ValidationErrorItem {
        error_type: "less_than_equal".to_string(),
        loc: vec!["query".to_string(), field.to_string()],
        msg: format!("Input should be less than or equal to {le}"),
        input: serde_json::Value::String(input.to_string()),
        ctx: Some(serde_json::json!({"le": le})),
    }
}

fn parse_page(raw: Option<&str>) -> Result<i128, CatalogError> {
    let Some(value) = raw else {
        return Ok(1);
    };
    let parsed = value
        .parse::<i128>()
        .map_err(|_| CatalogError::ValidationItems(vec![validation_int_parsing("page", value)]))?;
    if parsed < 1 {
        return Err(CatalogError::ValidationItems(vec![
            validation_greater_than_equal("page", value, 1),
        ]));
    }
    Ok(parsed)
}

fn parse_page_size(raw: Option<&str>) -> Result<i64, CatalogError> {
    let Some(value) = raw else {
        return Ok(50);
    };
    let parsed = match value.parse::<i64>() {
        Ok(parsed) => parsed,
        Err(_) => {
            if value.chars().all(|c| c.is_ascii_digit()) {
                // Python `Query(le=100)` reports values above the i64 range as less_than_equal.
                return Err(CatalogError::ValidationItems(vec![
                    validation_less_than_equal("page_size", value, MAX_PAGE_SIZE),
                ]));
            }
            return Err(CatalogError::ValidationItems(vec![validation_int_parsing(
                "page_size",
                value,
            )]));
        }
    };
    if parsed < 1 {
        return Err(CatalogError::ValidationItems(vec![
            validation_greater_than_equal("page_size", value, 1),
        ]));
    }
    if parsed > MAX_PAGE_SIZE {
        return Err(CatalogError::ValidationItems(vec![
            validation_less_than_equal("page_size", value, MAX_PAGE_SIZE),
        ]));
    }
    Ok(parsed)
}

/// Return True when the stored value looks like a local filesystem location.
///
/// Mirrors `app.services.cbl_source_public._is_filesystem_location`.
fn is_filesystem_location(value: &str) -> bool {
    value.starts_with('/') || value.starts_with("file:") || value.starts_with("mnt/")
}

/// Return a non-filesystem repository identity for public responses.
///
/// Mirrors `app.services.cbl_source_public.public_cbl_repository`.
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

/// Validate and normalize a source-relative folder path.
///
/// Mirrors `normalize_cbl_folder_path`.
fn normalize_folder(raw: Option<&str>) -> Result<String, CatalogError> {
    let Some(folder) = raw else {
        return Ok(String::new());
    };
    if folder.trim().is_empty() {
        return Ok(String::new());
    }

    // Python `Query(max_length=1000)` rejects this before the handler with a 422.
    if folder.chars().count() > MAX_FOLDER_LENGTH {
        return Err(CatalogError::Validation(format!(
            "folder must be at most {MAX_FOLDER_LENGTH} characters"
        )));
    }
    if folder.contains('\\') {
        return Err(CatalogError::InvalidFolder(
            "folder must use '/' separators, not backslashes".to_string(),
        ));
    }
    if folder.chars().any(|c| (c as u32) < 32) {
        return Err(CatalogError::InvalidFolder(
            "folder must not contain control characters".to_string(),
        ));
    }
    for segment in folder.split('/') {
        if segment.is_empty() || segment == "." || segment == ".." {
            return Err(CatalogError::InvalidFolder(
                "folder must not contain empty, '.' or '..' path segments".to_string(),
            ));
        }
    }
    Ok(folder.to_string())
}

/// Zero-based prefix length used with SQL `substr`, counted in characters like Python `len()`.
fn folder_prefix_len(folder: &str) -> i32 {
    folder.chars().count() as i32 + 1
}

/// Build root-through-folder breadcrumbs for a normalized folder path.
fn breadcrumbs(folder: &str) -> Vec<CBLBreadcrumb> {
    let mut out = vec![CBLBreadcrumb {
        name: ROOT_BREADCRUMB_NAME.to_string(),
        path: String::new(),
    }];
    if folder.is_empty() {
        return out;
    }
    let mut cumulative = Vec::new();
    for segment in folder.split('/') {
        if segment.is_empty() {
            continue;
        }
        cumulative.push(segment.to_string());
        out.push(CBLBreadcrumb {
            name: segment.to_string(),
            path: cumulative.join("/"),
        });
    }
    out
}

/// Escape SQL `LIKE` metacharacters in a literal folder or search term.
fn escape_like(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('%', "\\%")
        .replace('_', "\\_")
}

#[derive(Debug, Clone)]
struct FolderSummary {
    folders: Vec<CBLSourceFolder>,
    direct_list_count: i32,
    total_list_count: i32,
}

async fn read_folder(
    conn: &deadpool_postgres::Object,
    folder: &str,
) -> Result<FolderSummary, tokio_postgres::Error> {
    let (folder_like, prefix_len): (Option<String>, i32) = if folder.is_empty() {
        (None, 0)
    } else {
        (
            Some(format!("{}/%", escape_like(folder))),
            folder_prefix_len(folder),
        )
    };
    let child_segment: i32 = if folder.is_empty() {
        1
    } else {
        folder.matches('/').count() as i32 + 2
    };

    let folder_rows = conn
        .query(
            "SELECT
            split_part(l.source_path, '/', $2::int) AS name,
            COUNT(*) FILTER (WHERE array_length(string_to_array(l.source_path, '/'), 1) = $2::int + 1)::int AS direct_list_count,
            COUNT(*)::int AS total_list_count
         FROM cbl_source_lists l
         WHERE l.active IS TRUE
           AND ($1::text IS NULL OR l.source_path LIKE $1 ESCAPE '\\')
           AND strpos(substr(l.source_path, $3::int + 1), '/') > 0
         GROUP BY split_part(l.source_path, '/', $2::int)
         ORDER BY lower(split_part(l.source_path, '/', $2::int)) ASC, split_part(l.source_path, '/', $2::int) ASC",
            &[&folder_like, &child_segment, &prefix_len],
        )
        .await?;

    let mut folders = Vec::with_capacity(folder_rows.len());
    let mut child_total_sum: i32 = 0;
    for row in &folder_rows {
        let name: String = row.get(0);
        let direct: i32 = row.get(1);
        let total: i32 = row.get(2);
        child_total_sum += total;
        let path = if folder.is_empty() {
            name.clone()
        } else {
            format!("{folder}/{name}")
        };
        folders.push(CBLSourceFolder {
            name,
            path,
            direct_list_count: direct,
            total_list_count: total,
        });
    }

    let direct_row = conn
        .query_one(
            "SELECT COUNT(*)::int
         FROM cbl_source_lists l
         WHERE l.active IS TRUE
           AND ($1::text IS NULL OR l.source_path LIKE $1 ESCAPE '\\')
           AND strpos(substr(l.source_path, $2::int + 1), '/') = 0",
            &[&folder_like, &prefix_len],
        )
        .await?;
    let direct_list_count: i32 = direct_row.get(0);

    Ok(FolderSummary {
        folders,
        direct_list_count,
        total_list_count: direct_list_count + child_total_sum,
    })
}

fn map_item(row: &Row) -> CBLCatalogListItem {
    let repository: String = row.get(3);
    CBLCatalogListItem {
        id: row.get(0),
        name: row.get(1),
        source_path: row.get(2),
        source_repository: public_cbl_repository(&repository),
        declared_issue_count: row.get(4),
        content_hash: row.get(5),
        revision_sha: row.get(6),
    }
}

fn page_offset(page: i128, page_size: i64) -> Option<i64> {
    let offset = (page - 1).checked_mul(i128::from(page_size))?;
    if offset > i128::from(i64::MAX) {
        None
    } else {
        Some(offset as i64)
    }
}

async fn folder_total(
    conn: &deadpool_postgres::Object,
    folder: &str,
    query_text: Option<&str>,
) -> Result<i64, tokio_postgres::Error> {
    if let Some(term) = query_text {
        let pattern = format!("%{}%", escape_like(term));
        let count_row = conn
            .query_one(
                "SELECT COUNT(*)::bigint
             FROM cbl_source_lists l
             WHERE l.active IS TRUE
               AND (l.name ILIKE $1 ESCAPE '\\' OR l.source_path ILIKE $1 ESCAPE '\\')",
                &[&pattern],
            )
            .await?;
        Ok(count_row.get(0))
    } else {
        let (folder_like, prefix_len): (Option<String>, i32) = if folder.is_empty() {
            (None, 0)
        } else {
            (
                Some(format!("{}/%", escape_like(folder))),
                folder_prefix_len(folder),
            )
        };
        let count_row = conn
            .query_one(
                "SELECT COUNT(*)::bigint
             FROM cbl_source_lists l
             WHERE l.active IS TRUE
               AND ($1::text IS NULL OR l.source_path LIKE $1 ESCAPE '\\')
               AND strpos(substr(l.source_path, $2::int + 1), '/') = 0",
                &[&folder_like, &prefix_len],
            )
            .await?;
        Ok(count_row.get(0))
    }
}

async fn browse_items(
    conn: &deadpool_postgres::Object,
    folder: &str,
    query_text: Option<&str>,
    page: i128,
    page_size: i64,
) -> Result<(Vec<CBLCatalogListItem>, i64), tokio_postgres::Error> {
    let Some(offset) = page_offset(page, page_size) else {
        // Extreme page: offset would overflow PostgreSQL bigint range.
        let total = folder_total(conn, folder, query_text).await?;
        return Ok((Vec::new(), total));
    };

    if let Some(term) = query_text {
        let pattern = format!("%{}%", escape_like(term));
        let count_row = conn
            .query_one(
                "SELECT COUNT(*)::bigint
             FROM cbl_source_lists l
             WHERE l.active IS TRUE
               AND (l.name ILIKE $1 ESCAPE '\\' OR l.source_path ILIKE $1 ESCAPE '\\')",
                &[&pattern],
            )
            .await?;
        let total: i64 = count_row.get(0);
        if offset >= total {
            return Ok((Vec::new(), total));
        }
        let rows = conn
            .query(
                "SELECT l.id, l.name, l.source_path, s.repository AS source_repository,
                    l.declared_issue_count, l.content_hash, l.revision_sha
             FROM cbl_source_lists l
             JOIN cbl_sources s ON s.id = l.source_id
             WHERE l.active IS TRUE
               AND (l.name ILIKE $1 ESCAPE '\\' OR l.source_path ILIKE $1 ESCAPE '\\')
             ORDER BY l.name ASC, l.source_path ASC, l.id ASC
             LIMIT $2::bigint OFFSET $3::bigint",
                &[&pattern, &page_size, &offset],
            )
            .await?;
        Ok((rows.iter().map(map_item).collect(), total))
    } else {
        let (folder_like, prefix_len): (Option<String>, i32) = if folder.is_empty() {
            (None, 0)
        } else {
            (
                Some(format!("{}/%", escape_like(folder))),
                folder_prefix_len(folder),
            )
        };
        let count_row = conn
            .query_one(
                "SELECT COUNT(*)::bigint
             FROM cbl_source_lists l
             WHERE l.active IS TRUE
               AND ($1::text IS NULL OR l.source_path LIKE $1 ESCAPE '\\')
               AND strpos(substr(l.source_path, $2::int + 1), '/') = 0",
                &[&folder_like, &prefix_len],
            )
            .await?;
        let total: i64 = count_row.get(0);
        if offset >= total {
            return Ok((Vec::new(), total));
        }
        let rows = conn
            .query(
                "SELECT l.id, l.name, l.source_path, s.repository AS source_repository,
                    l.declared_issue_count, l.content_hash, l.revision_sha
             FROM cbl_source_lists l
             JOIN cbl_sources s ON s.id = l.source_id
             WHERE l.active IS TRUE
               AND ($1::text IS NULL OR l.source_path LIKE $1 ESCAPE '\\')
               AND strpos(substr(l.source_path, $2::int + 1), '/') = 0
             ORDER BY l.name ASC, l.source_path ASC, l.id ASC
             LIMIT $3::bigint OFFSET $4::bigint",
                &[&folder_like, &prefix_len, &page_size, &offset],
            )
            .await?;
        Ok((rows.iter().map(map_item).collect(), total))
    }
}

fn normalize_query(raw: Option<&str>) -> Result<Option<String>, CatalogError> {
    let Some(query) = raw else {
        return Ok(None);
    };
    if query.chars().count() > MAX_SEARCH_LENGTH {
        return Err(CatalogError::Validation(format!(
            "q must be at most {MAX_SEARCH_LENGTH} characters"
        )));
    }
    let trimmed = query.trim();
    if trimmed.is_empty() {
        Ok(None)
    } else {
        Ok(Some(trimmed.to_string()))
    }
}

/// `GET /api/v1/issue-identity/cbl-sources/folders`
#[utoipa::path(
    get,
    path = "/api/v1/issue-identity/cbl-sources/folders",
    params(CBLFolderListQuery),
    responses(
        (status = 200, body = CBLFolderListingResponse),
        (status = 400, body = CBLErrorResponse),
        (status = 404, body = CBLErrorResponse),
        (status = 422, body = ValidationErrorResponse),
        (status = 503, body = CBLErrorResponse),
    ),
    tag = "issue-identity",
)]
pub async fn list_cbl_source_folders(
    _user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
    Query(params): Query<CBLFolderListQuery>,
) -> Response {
    async fn inner(
        state: Arc<AppState>,
        params: CBLFolderListQuery,
    ) -> Result<Json<CBLFolderListingResponse>, CatalogError> {
        let conn = db::checkout(&state).await?;
        let folder = normalize_folder(params.folder.as_deref())?;
        let summary = read_folder(&conn, &folder).await?;
        if !folder.is_empty() && summary.folders.is_empty() && summary.direct_list_count == 0 {
            return Err(CatalogError::FolderNotFound(folder.clone()));
        }
        Ok(Json(CBLFolderListingResponse {
            breadcrumbs: breadcrumbs(&folder),
            folder,
            folders: summary.folders,
            direct_list_count: summary.direct_list_count,
            total_list_count: summary.total_list_count,
        }))
    }

    match inner(state, params).await {
        Ok(response) => response.into_response(),
        Err(error) => error.into_response(),
    }
}

/// `GET /api/v1/issue-identity/cbl-sources/browse`
#[utoipa::path(
    get,
    path = "/api/v1/issue-identity/cbl-sources/browse",
    params(CBLCatalogBrowseQuery),
    responses(
        (status = 200, body = CBLCatalogBrowseResponse),
        (status = 400, body = CBLErrorResponse),
        (status = 404, body = CBLErrorResponse),
        (status = 422, body = ValidationErrorResponse),
        (status = 503, body = CBLErrorResponse),
    ),
    tag = "issue-identity",
)]
pub async fn browse_cbl_source_catalog(
    _user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
    Query(params): Query<CBLCatalogBrowseQuery>,
) -> Response {
    async fn inner(
        state: Arc<AppState>,
        params: CBLCatalogBrowseQuery,
    ) -> Result<Json<CBLCatalogBrowseResponse>, CatalogError> {
        let folder = normalize_folder(params.folder.as_deref())?;
        let query_text = normalize_query(params.q.as_deref())?;
        let page = parse_page(params.page.as_deref())?;
        let page_size = parse_page_size(params.page_size.as_deref())?;

        let conn = db::checkout(&state).await?;

        let (response_folder, response_breadcrumbs, folders, scope) = if query_text.is_some() {
            (
                String::new(),
                breadcrumbs(""),
                Vec::new(),
                "search".to_string(),
            )
        } else {
            let summary = read_folder(&conn, &folder).await?;
            if !folder.is_empty() && summary.folders.is_empty() && summary.direct_list_count == 0 {
                return Err(CatalogError::FolderNotFound(folder.clone()));
            }
            (
                folder.clone(),
                breadcrumbs(&folder),
                summary.folders,
                "folder".to_string(),
            )
        };

        let (items, total) =
            browse_items(&conn, &folder, query_text.as_deref(), page, page_size).await?;
        let total_pages = if total == 0 {
            0
        } else {
            (total + page_size - 1) / page_size
        };
        let page_number = if let Ok(n) = i64::try_from(page) {
            serde_json::Number::from(n)
        } else {
            page.to_string()
                .parse::<serde_json::Number>()
                .unwrap_or_else(|_| serde_json::Number::from(i64::MAX))
        };

        Ok(Json(CBLCatalogBrowseResponse {
            scope,
            folder: response_folder,
            query: query_text,
            breadcrumbs: response_breadcrumbs,
            folders,
            items,
            page: page_number,
            page_size,
            total,
            total_pages,
            has_next: page < i128::from(total_pages),
            has_previous: page > 1,
        }))
    }

    match inner(state, params).await {
        Ok(response) => response.into_response(),
        Err(error) => error.into_response(),
    }
}

#[derive(OpenApi)]
#[openapi(
    paths(list_cbl_source_folders, browse_cbl_source_catalog),
    components(schemas(
        CBLCatalogListItem,
        CBLSourceFolder,
        CBLBreadcrumb,
        CBLFolderListingResponse,
        CBLCatalogBrowseResponse,
        CBLErrorDetail,
        CBLErrorResponse,
        CBLDatabaseUnavailableDetail,
        CBLDatabaseUnavailableResponse,
        ValidationErrorItem,
        ValidationErrorResponse,
    ))
)]
pub struct CblCatalogApi;
