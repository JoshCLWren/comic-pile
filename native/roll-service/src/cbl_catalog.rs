//! Read-only browsing of the shared CBL catalog folder tree and search.
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

const MAX_FOLDER_LENGTH: usize = 1000;
const MAX_SEARCH_LENGTH: usize = 200;
const MAX_PAGE_SIZE: i32 = 100;
const ROOT_BREADCRUMB_NAME: &str = "All CBLs";

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
    pub total_pages: i32,
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

fn catalog_error(status: StatusCode, code: &str, message: String) -> Response {
    (
        status,
        Json(serde_json::json!({"detail": {"code": code, "message": message}})),
    )
        .into_response()
}

fn catalog_unavailable() -> Response {
    catalog_error(
        StatusCode::SERVICE_UNAVAILABLE,
        "cbl_catalog_unavailable",
        "The shared CBL catalog is temporarily unavailable.".to_string(),
    )
}

fn normalize_folder(raw: Option<&str>) -> Result<String, (StatusCode, &'static str, String)> {
    let Some(folder) = raw else {
        return Ok(String::new());
    };
    if folder.trim().is_empty() {
        return Ok(String::new());
    }
    if folder.len() > MAX_FOLDER_LENGTH {
        return Err((
            StatusCode::BAD_REQUEST,
            "invalid_folder",
            format!("folder must be at most {MAX_FOLDER_LENGTH} characters"),
        ));
    }
    if folder.contains('\\') {
        return Err((
            StatusCode::BAD_REQUEST,
            "invalid_folder",
            "folder must use '/' separators, not backslashes".to_string(),
        ));
    }
    if folder.chars().any(|c| (c as u32) < 32) {
        return Err((
            StatusCode::BAD_REQUEST,
            "invalid_folder",
            "folder must not contain control characters".to_string(),
        ));
    }
    for segment in folder.split('/') {
        if segment.is_empty() || segment == "." || segment == ".." {
            return Err((
                StatusCode::BAD_REQUEST,
                "invalid_folder",
                "folder must not contain empty, '.' or '..' path segments".to_string(),
            ));
        }
    }
    Ok(folder.to_string())
}

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
            (folder.len() as i32) + 1,
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
    CBLCatalogListItem {
        id: row.get(0),
        name: row.get(1),
        source_path: row.get(2),
        source_repository: row.get(3),
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
    let offset = i64::from((page - 1) * page_size);
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
                (folder.len() as i32) + 1,
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
) -> Response {
    let folder = match normalize_folder(params.folder.as_deref()) {
        Ok(f) => f,
        Err((status, code, msg)) => return catalog_error(status, code, msg),
    };
    let conn = match db::checkout(&state).await {
        Ok(c) => c,
        Err(ApiError::DatabaseUnavailable) => return catalog_unavailable(),
        Err(_) => return catalog_unavailable(),
    };
    let summary = match read_folder(&conn, &folder).await {
        Ok(s) => s,
        Err(_) => return catalog_unavailable(),
    };
    if !folder.is_empty() && summary.folders.is_empty() && summary.direct_list_count == 0 {
        return catalog_error(
            StatusCode::NOT_FOUND,
            "folder_not_found",
            format!("CBL folder not found: {folder}"),
        );
    }
    Json(CBLFolderListingResponse {
        folder: folder.clone(),
        breadcrumbs: breadcrumbs(&folder),
        folders: summary.folders,
        direct_list_count: summary.direct_list_count,
        total_list_count: summary.total_list_count,
    })
    .into_response()
}

/// `GET /api/v1/issue-identity/cbl-sources/browse`
pub async fn browse_cbl_source_catalog(
    _user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
    Query(params): Query<CBLCatalogBrowseQuery>,
) -> Response {
    let folder = match normalize_folder(params.folder.as_deref()) {
        Ok(f) => f,
        Err((status, code, msg)) => return catalog_error(status, code, msg),
    };
    let term = params.q.as_deref().unwrap_or("").trim().to_string();
    if term.len() > MAX_SEARCH_LENGTH {
        return catalog_error(
            StatusCode::BAD_REQUEST,
            "invalid_query",
            format!("query must be at most {MAX_SEARCH_LENGTH} characters"),
        );
    }
    let page = if params.page < 1 { 1 } else { params.page };
    if !(1..=MAX_PAGE_SIZE).contains(&params.page_size) {
        // Python validates via Query(ge=1,le=100) which returns 422; but to be safe handle here.
        // Keep 422-like? FastAPI would reject before handler. We'll return 422 detail string.
        return (
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(serde_json::json!({"detail": "page_size must be between 1 and 100"})),
        )
            .into_response();
    }
    let page_size = params.page_size;

    let conn = match db::checkout(&state).await {
        Ok(c) => c,
        Err(ApiError::DatabaseUnavailable) => return catalog_unavailable(),
        Err(_) => return catalog_unavailable(),
    };

    let is_search = !term.is_empty();
    let (resp_folder, resp_query, resp_breadcrumbs, folders) = if is_search {
        (
            String::new(),
            Some(term.clone()),
            breadcrumbs(""),
            Vec::new(),
        )
    } else {
        let summary = match read_folder(&conn, &folder).await {
            Ok(s) => s,
            Err(_) => return catalog_unavailable(),
        };
        if !folder.is_empty() && summary.folders.is_empty() && summary.direct_list_count == 0 {
            return catalog_error(
                StatusCode::NOT_FOUND,
                "folder_not_found",
                format!("CBL folder not found: {folder}"),
            );
        }
        (folder.clone(), None, breadcrumbs(&folder), summary.folders)
    };

    let query_opt = if is_search { Some(term.as_str()) } else { None };
    let (items, total) = match browse_items(&conn, &folder, query_opt, page, page_size).await {
        Ok(v) => v,
        Err(_) => return catalog_unavailable(),
    };
    let total_pages = if total == 0 {
        0i32
    } else {
        ((total + i64::from(page_size) - 1) / i64::from(page_size)) as i32
    };
    let has_next = page < total_pages;
    let has_previous = page > 1;

    Json(CBLCatalogBrowseResponse {
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
    })
    .into_response()
}
