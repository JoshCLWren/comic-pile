//! Read-only browsing of the shared CBL catalog folder tree and search.
//!
//! Same-path native replacement for the browser-called issue-identity catalog reads (#4843):
//!
//! * `GET /api/v1/issue-identity/cbl-sources/folders`
//! * `GET /api/v1/issue-identity/cbl-sources/browse`
//!
//! Ownership-free: reads only `cbl_sources` / `cbl_source_lists` and never joins
//! reader-owned tables, so results are identical for every authenticated account.
//!
//! Wire parity with Python (`app/api/cbl_catalog.py`, `app/services/cbl_catalog.py`,
//! `app/repositories/cbl_catalog_repository.py`, `app/services/cbl_source_public.py`):
//!
//! * Folder paths are source-relative and `/`-separated. The length bound, the SQL
//!   `substr` prefix length and the search bound all count Unicode code points, matching
//!   Python `len()`; a byte length would slice multi-byte folder names incorrectly.
//! * `folder`/`q` bounds above 1000/200 characters are pre-handler FastAPI `Query`
//!   constraints, so they answer 422 rather than the service-level 400. The 422 body uses
//!   this service's string `detail` convention instead of FastAPI's validation-error list;
//!   status, path and message semantics are preserved.
//! * `page < 1` and `page_size` outside `1..=100` are also `Query` constraints and answer
//!   422, never a silent clamp.
//! * Malformed paths keep the Python 400 `invalid_folder` envelope, missing folders the 404
//!   `folder_not_found` envelope, and query failures the 503 `cbl_catalog_unavailable`
//!   envelope. A pool-acquisition failure keeps the application-wide
//!   `database_unavailable` 503 envelope.
//! * `source_repository` is masked through the same `public_cbl_repository` rule as Python so
//!   a stored local mirror path (`/mnt/bigdata/CBL-ReadingLists`) never reaches a browser.
//! * Python's `InvalidCBLSearchQueryError` (400 `invalid_query`) is unreachable behind
//!   `Query(max_length=200)`, so the native boundary reproduces the reachable 422 only.

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

/// Native catalog failures, each mapped to the Python response it replaces.
#[derive(Debug)]
enum CatalogError {
    /// 400 `invalid_folder` for a malformed source-relative path.
    InvalidFolder(String),
    /// 404 `folder_not_found` for a folder with no active lists or subfolders.
    FolderNotFound(String),
    /// 422 for a bound FastAPI rejected before the Python handler ran.
    Validation(String),
    /// 503 `cbl_catalog_unavailable` for a failed catalog query.
    Unavailable,
    /// Pool acquisition failure keeps the application-wide envelope.
    Database(ApiError),
}

impl From<ApiError> for CatalogError {
    fn from(error: ApiError) -> Self {
        CatalogError::Database(error)
    }
}

impl From<tokio_postgres::Error> for CatalogError {
    fn from(error: tokio_postgres::Error) -> Self {
        // Only the error type is logged: SQL and parameter values stay out of logs.
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
/// Mirrors `app.services.cbl_source_public.public_cbl_repository`: a stored local mirror path
/// becomes the GitHub repository, any other filesystem location becomes `CBL source`, and a
/// real repository identity is returned unchanged.
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
/// Mirrors `normalize_cbl_folder_path`: only the root (`""`) and syntactically valid relative
/// paths are accepted; the original value is returned otherwise so lookups round-trip.
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
        cumulative.push(segment);
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
    let folder_rows = conn.query(
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
    ).await?;

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
           AND strpos(substr(l.source_path, $3::int + 1), '/') = 0",
            &[&folder_like, &child_segment, &prefix_len],
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

/// `GET /api/v1/issue-identity/cbl-sources/folders`
pub async fn list_cbl_source_folders(
    _user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
    Query(params): Query<CBLFolderListQuery>,
) -> Result<Json<CBLFolderListingResponse>, CatalogError> {
    let folder = normalize_folder(params.folder.as_deref())?;
    let conn = db::checkout(&state).await?;
    let summary = read_folder(&conn, &folder).await?;
    if !folder.is_empty() && summary.folders.is_empty() && summary.direct_list_count == 0 {
        return Err(CatalogError::FolderNotFound(folder));
    }
    Ok(Json(CBLFolderListingResponse {
        folder: folder.clone(),
        breadcrumbs: breadcrumbs(&folder),
        folders: summary.folders,
        direct_list_count: summary.direct_list_count,
        total_list_count: summary.total_list_count,
    }))
}

/// `GET /api/v1/issue-identity/cbl-sources/browse`
pub async fn browse_cbl_source_catalog(
    _user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
    Query(params): Query<CBLCatalogBrowseQuery>,
) -> Result<Json<CBLCatalogBrowseResponse>, CatalogError> {
    let folder = normalize_folder(params.folder.as_deref())?;
    let term = params.q.as_deref().unwrap_or("").trim().to_string();
    if term.chars().count() > MAX_SEARCH_LENGTH {
        return Err(CatalogError::Validation(format!(
            "q must be at most {MAX_SEARCH_LENGTH} characters"
        )));
    }
    if params.page < 1 {
        return Err(CatalogError::Validation(
            "page must be at least 1".to_string(),
        ));
    }
    if !(1..=MAX_PAGE_SIZE).contains(&params.page_size) {
        return Err(CatalogError::Validation(format!(
            "page_size must be between 1 and {MAX_PAGE_SIZE}"
        )));
    }
    let page = params.page;
    let page_size = params.page_size;

    let conn = db::checkout(&state).await?;

    let is_search = !term.is_empty();
    let (resp_folder, resp_query, resp_breadcrumbs, folders) = if is_search {
        (
            String::new(),
            Some(term.clone()),
            breadcrumbs(""),
            Vec::new(),
        )
    } else {
        let summary = read_folder(&conn, &folder).await?;
        if !folder.is_empty() && summary.folders.is_empty() && summary.direct_list_count == 0 {
            return Err(CatalogError::FolderNotFound(folder));
        }
        let crumbs = breadcrumbs(&folder);
        (folder, None, crumbs, summary.folders)
    };

    let query_opt = if is_search { Some(term.as_str()) } else { None };
    let (items, total) = browse_items(&conn, &resp_folder, query_opt, page, page_size).await?;
    let total_pages = if total == 0 {
        0
    } else {
        (total + i64::from(page_size) - 1) / i64::from(page_size)
    };
    let has_next = i64::from(page) < total_pages;
    let has_previous = page > 1;

    Ok(Json(CBLCatalogBrowseResponse {
        scope: if is_search {
            "search".to_string()
        } else {
            "folder".to_string()
        },
        folder: resp_folder,
        query: resp_query,
        breadcrumbs: resp_breadcrumbs,
        folders,
        items,
        page,
        page_size,
        total,
        total_pages,
        has_next,
        has_previous,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bounds_match_the_python_contract() {
        assert_eq!(MAX_FOLDER_LENGTH, 1000);
        assert_eq!(MAX_SEARCH_LENGTH, 200);
        assert_eq!(MAX_PAGE_SIZE, 100);
    }

    #[test]
    fn normalize_folder_keeps_the_root_and_valid_paths() {
        assert_eq!(normalize_folder(None).ok(), Some(String::new()));
        assert_eq!(normalize_folder(Some("")).ok(), Some(String::new()));
        assert_eq!(normalize_folder(Some("   ")).ok(), Some(String::new()));
        assert_eq!(
            normalize_folder(Some("DC/Vertigo ")).ok(),
            Some("DC/Vertigo ".to_string())
        );
    }

    #[test]
    fn normalize_folder_rejects_malformed_paths() {
        assert!(matches!(
            normalize_folder(Some("DC\\Vertigo")),
            Err(CatalogError::InvalidFolder(_))
        ));
        assert!(matches!(
            normalize_folder(Some("DC//Vertigo")),
            Err(CatalogError::InvalidFolder(_))
        ));
        assert!(matches!(
            normalize_folder(Some("DC/../etc")),
            Err(CatalogError::InvalidFolder(_))
        ));
        assert!(matches!(
            normalize_folder(Some("DC/\u{1}")),
            Err(CatalogError::InvalidFolder(_))
        ));
    }

    #[test]
    fn normalize_folder_bounds_and_prefixes_count_characters_not_bytes() {
        let at_limit = "é".repeat(MAX_FOLDER_LENGTH);
        assert_eq!(at_limit.len(), MAX_FOLDER_LENGTH * 2);
        let normalized = normalize_folder(Some(&at_limit)).expect("at-limit folder is accepted");
        assert_eq!(normalized.chars().count(), MAX_FOLDER_LENGTH);
        assert_eq!(folder_prefix_len(&normalized), MAX_FOLDER_LENGTH as i32 + 1);

        let too_long = "é".repeat(MAX_FOLDER_LENGTH + 1);
        assert!(matches!(
            normalize_folder(Some(&too_long)),
            Err(CatalogError::Validation(_))
        ));
    }

    #[test]
    fn folder_prefix_len_matches_python_len() {
        assert_eq!(folder_prefix_len(""), 1);
        assert_eq!(folder_prefix_len("DC"), 3);
        assert_eq!(folder_prefix_len("DC/Vertigo"), 11);
        assert_eq!(folder_prefix_len("é/ü"), 4);
    }

    #[test]
    fn breadcrumbs_are_cumulative_from_the_catalog_root() {
        let root = breadcrumbs("");
        assert_eq!(root.len(), 1);
        assert_eq!(root[0].name, ROOT_BREADCRUMB_NAME);
        assert_eq!(root[0].path, "");

        let nested = breadcrumbs("DC/Vertigo/Hellblazer");
        assert_eq!(
            nested
                .iter()
                .map(|crumb| (crumb.name.as_str(), crumb.path.as_str()))
                .collect::<Vec<_>>(),
            vec![
                (ROOT_BREADCRUMB_NAME, ""),
                ("DC", "DC"),
                ("Vertigo", "DC/Vertigo"),
                ("Hellblazer", "DC/Vertigo/Hellblazer"),
            ]
        );
    }

    #[test]
    fn escape_like_escapes_every_metacharacter() {
        assert_eq!(escape_like("100%_raw\\"), "100\\%\\_raw\\\\");
        assert_eq!(escape_like("plain"), "plain");
    }

    #[test]
    fn public_cbl_repository_masks_local_mirror_paths() {
        // Production stored the local mirror path as the repository.
        assert_eq!(
            public_cbl_repository("/mnt/bigdata/CBL-ReadingLists"),
            PUBLIC_REPOSITORY
        );
        assert_eq!(
            public_cbl_repository("/mnt/bigdata/CBL-ReadingLists/"),
            PUBLIC_REPOSITORY
        );
        assert_eq!(
            public_cbl_repository("\\mnt\\bigdata\\CBL-ReadingLists"),
            PUBLIC_REPOSITORY
        );
        assert_eq!(
            public_cbl_repository("  /mnt/bigdata/CBL-ReadingLists  "),
            PUBLIC_REPOSITORY
        );

        // Any other filesystem location is reduced to an opaque label.
        assert_eq!(public_cbl_repository("/srv/mirrors/lists"), "CBL source");
        assert_eq!(public_cbl_repository("mnt/bigdata/lists"), "CBL source");
        assert_eq!(public_cbl_repository("file:///tmp/lists"), "CBL source");

        // Real repository identities are returned exactly as stored.
        assert_eq!(
            public_cbl_repository("JoshCLWren/CBL-ReadingLists"),
            "JoshCLWren/CBL-ReadingLists"
        );
        assert_eq!(public_cbl_repository(" owner/repo "), " owner/repo ");
    }
}
