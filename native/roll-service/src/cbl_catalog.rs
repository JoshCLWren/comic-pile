//! Read-only browsing of the shared CBL catalog folder tree and search.
//!
//! These endpoints are deliberately ownership-free: they read the shared
//! `cbl_sources` / `cbl_source_lists` catalog and never join reader-owned
//! Issues, Threads, Reading Lists, or adoption receipts. Folder navigation, search,
//! and pagination therefore produce identical results for every authenticated
//! account, including a brand-new one with no comics.

use crate::{db, ApiError};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use utoipa::ToSchema;

const MAX_PAGE_SIZE: i32 = 100;
const DEFAULT_PAGE_SIZE: i32 = 50;

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

#[derive(Debug, Deserialize, ToSchema)]
pub struct CBLFolderListQuery {
    pub folder: String = "",
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct CBLCatalogBrowseQuery {
    pub folder: String = "",
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

fn validate_page_size(page_size: i32) -> Result<i32, ApiError> {
    if page_size < 1 || page_size > MAX_PAGE_SIZE {
        return Err(ApiError::BadRequest(format!(
            "page_size must be between 1 and {}",
            MAX_PAGE_SIZE
        )));
    }
    Ok(page_size)
}

/// `GET /api/v1/issue-identity/cbl-sources/folders`
///
/// List immediate subfolders of one shared CBL catalog folder.
///
/// The root folder is addressed with an empty `folder` value. A request for a
/// folder with no active CBLs or subfolders returns a stable 404 envelope; a
/// malformed path returns 400.
pub async fn list_cbl_source_folders(
    State(state): State<Arc<crate::AppState>>,
    Query(params): Query<CBLFolderListQuery>,
) -> Result<Json<CBLFolderListingResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    let folder = params.folder.trim();

    // Validate folder path (basic check for now)
    if folder.contains("..") || folder.contains("//") {
        return Err(ApiError::BadRequest("Invalid folder path".to_string()));
    }

    let breadcrumbs = calculate_breadcrumbs(folder);
    let (folders, direct_count, total_count) = get_folders_and_counts(&conn, folder).await?;

    Ok(Json(CBLFolderListingResponse {
        folder: folder.to_string(),
        breadcrumbs,
        folders,
        direct_list_count: direct_count,
        total_list_count: total_count,
    }))
}

/// `GET /api/v1/issue-identity/cbl-sources/browse`
///
/// Browse one catalog folder or search all CBLs by name and source path.
///
/// With a blank `q` the response describes the immediate contents of
/// `folder`. With a non-blank `q` the search spans the entire shared
/// catalog, regardless of `folder`, and `scope` is `"search"`. `total`
/// is the truthful number of matches, so callers can page past 100 results.
pub async fn browse_cbl_source_catalog(
    State(state): State<Arc<crate::AppState>>,
    Query(params): Query<CBLCatalogBrowseQuery>,
) -> Result<Json<CBLCatalogBrowseResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    let folder = params.folder.trim();
    let query = params.q.as_ref().map(|q| q.trim()).filter(|q| !q.is_empty());
    let page = params.page.max(1);
    let page_size = validate_page_size(params.page_size)?;

    // Validate folder path (basic check for now)
    if folder.contains("..") || folder.contains("//") {
        return Err(ApiError::BadRequest("Invalid folder path".to_string()));
    }

    let breadcrumbs = calculate_breadcrumbs(folder);
    let scope = if query.is_some() { "search" } else { "folder" };

    let (folders, direct_count, total_count) = if query.is_some() {
        // For search, we don't need folder-specific counts
        (Vec::new(), 0, 0)
    } else {
        get_folders_and_counts(&conn, folder).await?
    };

    let (items, total) = if let Some(query) = query {
        search_cbl_sources(&conn, query, page, page_size).await?
    } else {
        list_cbl_sources_in_folder(&conn, folder, page, page_size).await?
    };

    let total_pages = (total + page_size as i64 - 1) / page_size as i64;
    let has_next = page < total_pages;
    let has_previous = page > 1;

    Ok(Json(CBLCatalogBrowseResponse {
        scope: scope.to_string(),
        folder: folder.to_string(),
        query: query.map(|s| s.to_string()),
        breadcrumbs,
        folders,
        items,
        page,
        page_size,
        total,
        total_pages: total_pages as i32,
        has_next,
        has_previous,
    }))
}

fn calculate_breadcrumbs(folder: &str) -> Vec<CBLBreadcrumb> {
    let mut breadcrumbs = Vec::new();
    let mut current_path = "";
    
    if !folder.is_empty() {
        for segment in folder.split('/') {
            if !segment.is_empty() {
                let breadcrumb_path = if current_path.is_empty() {
                    format!("/{}", segment)
                } else {
                    format!("{}/{}", current_path, segment)
                };
                breadcrumbs.push(CBLBreadcrumb {
                    name: segment.to_string(),
                    path: breadcrumb_path,
                });
                current_path = if current_path.is_empty() {
                    segment.to_string()
                } else {
                    format!("{}/{}", current_path, segment)
                };
            }
        }
    }
    
    breadcrumbs
}

async fn get_folders_and_counts(
    conn: &deadpool_postgres::Object,
    folder: &str,
) -> Result<(Vec<CBLSourceFolder>, i32, i32), ApiError> {
    let base_query = "
        SELECT f.name, f.path, 
               COUNT(DISTINCT CASE WHEN f.path = $2 THEN s.id END) as direct_count,
               COUNT(DISTINCT s.id) as total_count
        FROM cbl_source_folders f
        LEFT JOIN cbl_source_lists s ON s.source_path LIKE f.path || '/%'
        WHERE f.path LIKE $1 || '/%'
        GROUP BY f.name, f.path
        ORDER BY f.path, f.name
    ";

    let rows = conn
        .query(base_query, &[&format!("{}%", folder), &folder])
        .await
        .map_err(db::query_error)?;

    let mut folders = Vec::new();
    let mut direct_count = 0;
    let mut total_count = 0;

    for row in &rows {
        let name: String = row.get(0);
        let path: String = row.get(1);
        let direct: i64 = row.get(2);
        let total: i64 = row.get(3);

        folders.push(CBLSourceFolder {
            name,
            path,
            direct_list_count: direct as i32,
            total_list_count: total as i32,
        });

        if path == folder {
            direct_count = direct as i32;
            total_count = total as i32;
        }
    }

    Ok((folders, direct_count, total_count))
}

async fn list_cbl_sources_in_folder(
    conn: &deadpool_postgres::Object,
    folder: &str,
    page: i32,
    page_size: i32,
) -> Result<(Vec<CBLCatalogListItem>, i64), ApiError> {
    let offset = (page - 1) * page_size;

    let count_query = "
        SELECT COUNT(*)::bigint
        FROM cbl_source_lists s
        WHERE s.source_path LIKE $1 || '/%'
    ";

    let count: i64 = conn
        .query_one(count_query, &[&format!("{}%", folder)])
        .await
        .map_err(db::query_error)?
        .get(0);

    let data_query = "
        SELECT s.id, s.name, s.source_path, s.source_repository,
               s.declared_issue_count, s.content_hash, s.revision_sha
        FROM cbl_source_lists s
        WHERE s.source_path LIKE $1 || '/%'
        ORDER BY s.name, s.id
        LIMIT $2 OFFSET $3
    ";

    let rows = conn
        .query(data_query, &[&format!("{}%", folder), &page_size, &offset])
        .await
        .map_err(db::query_error)?;

    let items: Vec<CBLCatalogListItem> = rows
        .iter()
        .map(|row| CBLCatalogListItem {
            id: row.get(0),
            name: row.get(1),
            source_path: row.get(2),
            source_repository: row.get(3),
            declared_issue_count: row.get(4),
            content_hash: row.get(5),
            revision_sha: row.get(6),
        })
        .collect();

    Ok((items, count))
}

async fn search_cbl_sources(
    conn: &deadpool_postgres::Object,
    query: &str,
    page: i32,
    page_size: i32,
) -> Result<(Vec<CBLCatalogListItem>, i64), ApiError> {
    let offset = (page - 1) * page_size;

    let count_query = "
        SELECT COUNT(*)::bigint
        FROM cbl_source_lists s
        WHERE LOWER(s.name) LIKE LOWER($1) OR LOWER(s.source_path) LIKE LOWER($1)
    ";

    let search_pattern = format!("%{}%", query);
    let count: i64 = conn
        .query_one(count_query, &[&search_pattern])
        .await
        .map_err(db::query_error)?
        .get(0);

    let data_query = "
        SELECT s.id, s.name, s.source_path, s.source_repository,
               s.declared_issue_count, s.content_hash, s.revision_sha
        FROM cbl_source_lists s
        WHERE LOWER(s.name) LIKE LOWER($1) OR LOWER(s.source_path) LIKE LOWER($1)
        ORDER BY 
            CASE WHEN LOWER(s.name) = LOWER($1) THEN 1
                 WHEN LOWER(s.name) LIKE LOWER($1 || '%') THEN 2
                 ELSE 3 END,
            s.name, s.id
        LIMIT $2 OFFSET $3
    ";

    let rows = conn
        .query(data_query, &[&search_pattern, &page_size, &offset])
        .await
        .map_err(db::query_error)?;

    let items: Vec<CBLCatalogListItem> = rows
        .iter()
        .map(|row| CBLCatalogListItem {
            id: row.get(0),
            name: row.get(1),
            source_path: row.get(2),
            source_repository: row.get(3),
            declared_issue_count: row.get(4),
            content_hash: row.get(5),
            revision_sha: row.get(6),
        })
        .collect();

    Ok((items, count))
}