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
use utoipa::ToSchema;

/// Python `MAX_FOLDER_LENGTH`, measured in characters.
const MAX_FOLDER_LENGTH: usize = 1000;
/// Python `MAX_SEARCH_LENGTH`, measured in characters.
const MAX_SEARCH_LENGTH: usize = 200;
const MAX_PAGE_SIZE: i32 = 100;
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
    pub page: i32,
    pub page_size: i32,
    pub total: i64,
    /// Python returns an unbounded `int`; keep `i64` so a large `total` cannot wrap.
    pub total_pages: i64,
    pub has_next: bool,
    pub has_previous: bool,
}

#[derive(Debug, Deserialize, ToSchema, Default)]
pub struct CBLFolderListQuery {
    #[serde(default)]
    pub folder: Option<String>,
}

#[derive(Debug, Deserialize, ToSchema, Default)]
pub struct CBLCatalogBrowseQuery {
    #[serde(default)]
    pub folder: Option<String>,
    pub q: Option<String>,
    #[serde(default = "default_page")]
    pub page: i32,
    #[serde(default = "default_page_size")]
    pub page_size: i32,
}

fn default_page() -> i32 {
    1
}

fn default_page_size() -> i32 {
    50
}

#[derive(Debug)]
enum CatalogError {
    InvalidFolder(String),
    FolderNotFound(String),
    Validation(String),
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
            CatalogError::Unavailable => catalog_error(
                StatusCode::SERVICE_UNAVAILABLE,
                CATALOG_UNAVAILABLE_CODE,
                CATALOG_UNAVAILABLE_MESSAGE.to_string(),
            ),
            CatalogError::Database(error) => error.into_response(),
        }
    }
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
    if !folder.trim().is_empty() {
        // keep original content for validation/return
    } else {
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

    // Immediate child folders with direct/total active-list counts.
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

    // Direct active lists in this folder (no further segment below).
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

async fn browse_items(
    conn: &deadpool_postgres::Object,
    folder: &str,
    query_text: Option<&str>,
    page: i32,
    page_size: i32,
) -> Result<(Vec<CBLCatalogListItem>, i64), tokio_postgres::Error> {
    // Python's `int` arithmetic never overflows; widen before multiplying.
    let offset = i64::from(page - 1) * i64::from(page_size);
    let limit = i64::from(page_size);

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
                &[&pattern, &limit, &offset],
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
                &[&folder_like, &prefix_len, &limit, &offset],
            )
            .await?;
        Ok((rows.iter().map(map_item).collect(), total))
    }
}

fn normalize_query(raw: Option<&str>) -> Result<Option<String>, CatalogError> {
    let Some(query) = raw else {
        return Ok(None);
    };
    // Python `Query(max_length=200)` rejects this before the handler with a 422.
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
pub async fn browse_cbl_source_catalog(
    _user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
    Query(params): Query<CBLCatalogBrowseQuery>,
) -> Response {
    async fn inner(
        state: Arc<AppState>,
        params: CBLCatalogBrowseQuery,
    ) -> Result<Json<CBLCatalogBrowseResponse>, CatalogError> {
        let conn = db::checkout(&state).await?;
        let folder = normalize_folder(params.folder.as_deref())?;
        let query_text = normalize_query(params.q.as_deref())?;

        // Python `Query(ge=1)` / `Query(ge=1, le=100)` reject before the handler with 422.
        if params.page < 1 {
            return Err(CatalogError::Validation(
                "page must be greater than or equal to 1".to_string(),
            ));
        }
        if !(1..=MAX_PAGE_SIZE).contains(&params.page_size) {
            return Err(CatalogError::Validation(format!(
                "page_size must be between 1 and {MAX_PAGE_SIZE}"
            )));
        }

        let (response_folder, response_breadcrumbs, folders, scope) = if let Some(_) =
            query_text.as_deref()
        {
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

        let (items, total) = browse_items(
            &conn,
            &folder,
            query_text.as_deref(),
            params.page,
            params.page_size,
        )
        .await?;
        let page_size_i64 = i64::from(params.page_size);
        let total_pages = if total == 0 {
            0
        } else {
            (total + page_size_i64 - 1) / page_size_i64
        };

        Ok(Json(CBLCatalogBrowseResponse {
            scope,
            folder: response_folder,
            query: query_text,
            breadcrumbs: response_breadcrumbs,
            folders,
            items,
            page: params.page,
            page_size: params.page_size,
            total,
            total_pages,
            has_next: i64::from(params.page) < total_pages,
            has_previous: params.page > 1,
        }))
    }

    match inner(state, params).await {
        Ok(response) => response.into_response(),
        Err(error) => error.into_response(),
    }
}
