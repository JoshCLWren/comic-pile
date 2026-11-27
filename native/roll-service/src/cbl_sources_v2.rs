//! Canonical owner-authenticated CBL source catalog resource (#5712).
//!
//! This is the v2-only destination for the shared CBL catalog reads. A single
//! `GET /api/v2/cblSources` collection serves both catalog-wide discovery and
//! folder browsing through `filter`, `order_by`, `page_size` and `page_token`;
//! `GET /api/v2/cblSources/{source_id}` is the read-only standard Get, and
//! `GET /api/v2/cblOccurrences` resolves exact Comic Vine issue occurrences.
//!
//! There is no `browse`, `by-*` or `issue-identity` action path here, no same-path
//! v1 port, and no feature flag. All three reads touch only the shared catalog
//! tables (`cbl_sources`, `cbl_source_lists`, `cbl_source_entries`) and their
//! public external identities. No reader-owned reading list, thread or issue is
//! ever joined, so a private list cannot leak through a catalog response.
//!
//! Pagination is AIP-132 shaped: `page_token` is an opaque, self-describing
//! continuation cursor that is replay-checked against the current filter,
//! ordering and page size before it can affect SQL or an offset.

use crate::{auth::AuthenticatedUser, cbl_catalog, db, issue_identity, ApiError, AppState};
use axum::{
    extract::{Path, Query, State},
    Json,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use utoipa::ToSchema;

const DEFAULT_PAGE_SIZE: i64 = 50;
const MAX_PAGE_SIZE: i64 = 100;
const MAX_OCCURRENCE_PAGE_SIZE: i64 = 200;
const MAX_FILTER_LENGTH: usize = 1000;
const MAX_SEARCH_LENGTH: usize = 200;
const MAX_COMICVINE_ID_LENGTH: usize = 100;

/// One root-through-folder breadcrumb.
pub use cbl_catalog::CBLBreadcrumb;
/// One item in a shared catalog page. Field-for-field identical to the
/// discovery item the browser already renders.
pub use cbl_catalog::CBLCatalogListItem;
/// One immediate child folder of a shared catalog folder.
pub use cbl_catalog::CBLSourceFolder;

/// One bounded page of the shared source collection.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ListCblSourcesResponse {
    pub scope: String,
    pub folder: String,
    pub query: Option<String>,
    pub breadcrumbs: Vec<CBLBreadcrumb>,
    pub folders: Vec<CBLSourceFolder>,
    pub items: Vec<CBLCatalogListItem>,
    /// Echoed effective page, kept for the browser's deep-linkable position.
    pub page: i64,
    pub page_size: i64,
    /// Full match total for the applied folder/search scope, not this page.
    pub total: i64,
    /// Whole active shared-catalog total, independent of folder or search.
    pub catalog_total: i64,
    pub total_pages: i64,
    pub has_next: bool,
    pub has_previous: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub next_page_token: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub previous_page_token: Option<String>,
}

/// One bounded page of exact Comic Vine occurrences in the shared catalog.
#[derive(Debug, Serialize, ToSchema)]
pub struct ListCblOccurrencesResponse {
    pub comicvine_issue_id: String,
    pub occurrences_total: i64,
    pub lists_total: i64,
    pub occurrences_offset: i64,
    pub occurrences_limit: i64,
    pub occurrences: Vec<issue_identity::CblComicvineOccurrence>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub next_page_token: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct ListCblSourcesQuery {
    /// `folder=<path>` browses the shared folder tree; `q=<term>` or a bare
    /// term searches names and source paths across the whole shared catalog.
    pub filter: Option<String>,
    /// Stable ordering: `name` (default) or `path`.
    pub order_by: Option<String>,
    pub page_size: Option<String>,
    pub page_token: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct GetCblSourceQuery {
    pub offset: Option<String>,
    pub limit: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct ListCblOccurrencesQuery {
    /// `comicvine_issue_id=<id>` or a bare Comic Vine issue id.
    pub filter: Option<String>,
    pub page_size: Option<String>,
    pub page_token: Option<String>,
    /// Retained bounded paging for deep occurrence sets.
    pub offset: Option<String>,
    pub limit: Option<String>,
}

fn bad_page_token() -> ApiError {
    ApiError::BadRequest("Invalid CBL page token".to_string())
}

fn bad_filter(detail: &str) -> ApiError {
    ApiError::BadRequest(format!("Invalid CBL filter: {detail}"))
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum SourceFilter {
    Folder(String),
    Search(String),
}

impl SourceFilter {
    fn canonical(&self) -> String {
        match self {
            Self::Folder(folder) => format!("folder:{folder}"),
            Self::Search(term) => format!("q:{term}"),
        }
    }
}

/// Parse the single `filter` parameter into a folder browse or catalog search.
/// The literal spellings are part of the HTTP contract; callers must not send
/// raw SQL or a private-list identifier.
fn parse_source_filter(raw: Option<&str>) -> Result<SourceFilter, ApiError> {
    let value = raw.unwrap_or("").trim();
    if value.is_empty() {
        return Ok(SourceFilter::Folder(String::new()));
    }
    if value.chars().count() > MAX_FILTER_LENGTH {
        return Err(bad_filter("filter must be at most 1000 characters"));
    }
    if let Some(rest) = value.strip_prefix("folder:") {
        let folder = cbl_catalog::normalize_folder(Some(rest.trim()))
            .map_err(|error| bad_filter(&error.to_string()))?;
        return Ok(SourceFilter::Folder(folder));
    }
    let term = value.strip_prefix("q:").unwrap_or(value).trim();
    if term.is_empty() {
        return Err(bad_filter("search term must not be empty"));
    }
    if term.chars().count() > MAX_SEARCH_LENGTH {
        return Err(bad_filter("search term must be at most 200 characters"));
    }
    Ok(SourceFilter::Search(term.to_string()))
}

/// Canonical, allowlisted ordering. Both spellings of the path order collapse
/// to one token value so a reordered token can never be replayed silently.
fn parse_order_by(raw: Option<&str>) -> Result<String, ApiError> {
    let value = raw.unwrap_or("name").trim();
    match value {
        "" | "name" => Ok("name".to_string()),
        "path" | "source_path" => Ok("path".to_string()),
        _ => Err(ApiError::BadRequest(
            "order_by must be one of: name, path".to_string(),
        )),
    }
}

fn order_by_sql(order_by: &str) -> &'static str {
    match order_by {
        "path" => "l.source_path ASC, l.name ASC, l.id ASC",
        _ => "l.name ASC, l.source_path ASC, l.id ASC",
    }
}

/// Parse a bounded positive integer query parameter.
fn parse_bounded_int(
    field: &str,
    raw: Option<&str>,
    default: i64,
    max: i64,
) -> Result<i64, ApiError> {
    let Some(value) = raw else {
        return Ok(default);
    };
    let parsed = value
        .parse::<i64>()
        .map_err(|_| ApiError::BadRequest(format!("{field} must be an integer")))?;
    if !(1..=max).contains(&parsed) {
        return Err(ApiError::BadRequest(format!(
            "{field} must be between 1 and {max}"
        )));
    }
    Ok(parsed)
}

fn parse_nonnegative_int(field: &str, raw: Option<&str>, default: i64) -> Result<i64, ApiError> {
    let Some(value) = raw else {
        return Ok(default);
    };
    let parsed = value
        .parse::<i64>()
        .map_err(|_| ApiError::BadRequest(format!("{field} must be an integer")))?;
    if parsed < 0 {
        return Err(ApiError::BadRequest(format!("{field} must be at least 0")));
    }
    Ok(parsed)
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct SourcePageCursor {
    p: i64,
    f: String,
    o: String,
    s: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct OccurrencePageCursor {
    o: i64,
    s: i64,
    f: String,
}

fn encode_cursor<T: Serialize>(cursor: &T) -> String {
    #[allow(clippy::expect_used)]
    let bytes = serde_json::to_vec(cursor).expect("page cursor is serializable");
    URL_SAFE_NO_PAD.encode(bytes)
}

fn decode_cursor<T: serde::de::DeserializeOwned>(token: &str) -> Result<T, ApiError> {
    let bytes = URL_SAFE_NO_PAD
        .decode(token)
        .map_err(|_| bad_page_token())?;
    serde_json::from_slice(&bytes).map_err(|_| bad_page_token())
}

fn source_cursor(
    token: Option<&str>,
    filter: &SourceFilter,
    order_by: &str,
    page_size: i64,
) -> Result<Option<SourcePageCursor>, ApiError> {
    let Some(token) = token.filter(|value| !value.is_empty()) else {
        return Ok(None);
    };
    let cursor: SourcePageCursor = decode_cursor(token)?;
    if cursor.f != filter.canonical()
        || cursor.o != order_by
        || cursor.s != page_size
        || cursor.p < 1
    {
        return Err(bad_page_token());
    }
    Ok(Some(cursor))
}

fn occurrence_cursor(
    token: Option<&str>,
    issue_id: &str,
    page_size: i64,
) -> Result<Option<OccurrencePageCursor>, ApiError> {
    let Some(token) = token.filter(|value| !value.is_empty()) else {
        return Ok(None);
    };
    let cursor: OccurrencePageCursor = decode_cursor(token)?;
    if cursor.f != issue_id || cursor.s != page_size || cursor.o < 0 {
        return Err(bad_page_token());
    }
    Ok(Some(cursor))
}

fn page_offset(page: i64, page_size: i64) -> Result<i64, ApiError> {
    page.checked_sub(1)
        .and_then(|value| value.checked_mul(page_size))
        .ok_or_else(bad_page_token)
}

/// Parse one exact Comic Vine issue id out of the occurrence filter.
fn parse_occurrence_filter(raw: Option<&str>) -> Result<String, ApiError> {
    let value = raw.unwrap_or("").trim();
    let issue_id = value
        .strip_prefix("comicvine_issue_id:")
        .unwrap_or(value)
        .trim();
    if issue_id.is_empty() {
        return Err(ApiError::Unprocessable(
            "cblOccurrences filter requires a Comic Vine issue id".to_string(),
        ));
    }
    if issue_id.chars().count() > MAX_COMICVINE_ID_LENGTH {
        return Err(bad_filter(
            "comicvine_issue_id must be at most 100 characters",
        ));
    }
    Ok(issue_id.to_string())
}

/// Set-based page query: one count statement and one bounded page statement,
/// no per-row lookups. The `FILTER` clause yields the full match total and the
/// whole active catalog total in the same round trip.
async fn query_source_page(
    conn: &deadpool_postgres::Object,
    filter: &SourceFilter,
    order_by: &str,
    page_size: i64,
    offset: i64,
) -> Result<(Vec<CBLCatalogListItem>, i64, i64), ApiError> {
    match filter {
        SourceFilter::Search(term) => {
            let pattern = format!("%{}%", cbl_catalog::escape_like(term));
            let count_row = conn
                .query_one(
                    "SELECT COUNT(*) FILTER (
                                WHERE l.name ILIKE $1 ESCAPE '\\'
                                   OR l.source_path ILIKE $1 ESCAPE '\\'
                            )::bigint AS total,
                            COUNT(*)::bigint AS catalog_total
                     FROM cbl_source_lists l
                     WHERE l.active IS TRUE",
                    &[&pattern],
                )
                .await
                .map_err(db::query_error)?;
            let total: i64 = count_row.get(0);
            let catalog_total: i64 = count_row.get(1);
            let sql = format!(
                "SELECT l.id, l.name, l.source_path, s.repository AS source_repository,
                        l.declared_issue_count, l.content_hash, l.revision_sha
                 FROM cbl_source_lists l
                 JOIN cbl_sources s ON s.id = l.source_id
                 WHERE l.active IS TRUE
                   AND (l.name ILIKE $1 ESCAPE '\\' OR l.source_path ILIKE $1 ESCAPE '\\')
                 ORDER BY {}
                 LIMIT $2::bigint OFFSET $3::bigint",
                order_by_sql(order_by)
            );
            let rows = conn
                .query(&sql, &[&pattern, &page_size, &offset])
                .await
                .map_err(db::query_error)?;
            Ok((
                rows.iter().map(cbl_catalog::map_item).collect(),
                total,
                catalog_total,
            ))
        }
        SourceFilter::Folder(folder) => {
            let (folder_like, prefix_len): (Option<String>, i32) = if folder.is_empty() {
                (None, 0)
            } else {
                (
                    Some(format!("{}/%", cbl_catalog::escape_like(folder))),
                    folder.chars().count() as i32 + 1,
                )
            };
            let count_row = conn
                .query_one(
                    "SELECT COUNT(*) FILTER (
                                WHERE ($1::text IS NULL OR l.source_path LIKE $1 ESCAPE '\\')
                                  AND strpos(substr(l.source_path, $2::int + 1), '/') = 0
                            )::bigint AS total,
                            COUNT(*)::bigint AS catalog_total
                     FROM cbl_source_lists l
                     WHERE l.active IS TRUE",
                    &[&folder_like, &prefix_len],
                )
                .await
                .map_err(db::query_error)?;
            let total: i64 = count_row.get(0);
            let catalog_total: i64 = count_row.get(1);
            let sql = format!(
                "SELECT l.id, l.name, l.source_path, s.repository AS source_repository,
                        l.declared_issue_count, l.content_hash, l.revision_sha
                 FROM cbl_source_lists l
                 JOIN cbl_sources s ON s.id = l.source_id
                 WHERE l.active IS TRUE
                   AND ($1::text IS NULL OR l.source_path LIKE $1 ESCAPE '\\')
                   AND strpos(substr(l.source_path, $2::int + 1), '/') = 0
                 ORDER BY {}
                 LIMIT $3::bigint OFFSET $4::bigint",
                order_by_sql(order_by)
            );
            let rows = conn
                .query(&sql, &[&folder_like, &prefix_len, &page_size, &offset])
                .await
                .map_err(db::query_error)?;
            Ok((
                rows.iter().map(cbl_catalog::map_item).collect(),
                total,
                catalog_total,
            ))
        }
    }
}

/// `GET /api/v2/cblSources` — AIP-132 List over discovery and folder browse.
pub async fn list_cbl_sources(
    _user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
    Query(query): Query<ListCblSourcesQuery>,
) -> Result<Json<ListCblSourcesResponse>, ApiError> {
    let filter = parse_source_filter(query.filter.as_deref())?;
    let order_by = parse_order_by(query.order_by.as_deref())?;
    let page_size = parse_bounded_int(
        "page_size",
        query.page_size.as_deref(),
        DEFAULT_PAGE_SIZE,
        MAX_PAGE_SIZE,
    )?;
    let cursor = source_cursor(query.page_token.as_deref(), &filter, &order_by, page_size)?;
    let requested_page = cursor.as_ref().map_or(1, |value| value.p);

    let conn = db::checkout(&state).await?;

    let (folders, scope, response_folder, response_query, response_breadcrumbs) = match &filter {
        SourceFilter::Search(term) => (
            Vec::new(),
            "search".to_string(),
            String::new(),
            Some(term.clone()),
            cbl_catalog::breadcrumbs(""),
        ),
        SourceFilter::Folder(folder) => {
            let summary = cbl_catalog::read_folder(&conn, folder)
                .await
                .map_err(db::query_error)?;
            if !folder.is_empty() && summary.folders.is_empty() && summary.direct_list_count == 0 {
                return Err(ApiError::NotFound(format!(
                    "CBL folder not found: {folder}"
                )));
            }
            (
                summary.folders,
                "folder".to_string(),
                folder.clone(),
                None,
                cbl_catalog::breadcrumbs(folder),
            )
        }
    };

    let (items, total, catalog_total) = query_source_page(
        &conn,
        &filter,
        &order_by,
        page_size,
        page_offset(requested_page, page_size)?,
    )
    .await?;

    let total_pages = if total == 0 {
        0
    } else {
        (total + page_size - 1) / page_size
    };
    let effective_page = if total > 0 && requested_page > total_pages {
        total_pages
    } else {
        requested_page
    };
    // Re-read the clamped page: an out-of-range token must return the last real
    // page, never an empty slice with a contradictory page indicator.
    let items = if effective_page != requested_page {
        query_source_page(
            &conn,
            &filter,
            &order_by,
            page_size,
            page_offset(effective_page, page_size)?,
        )
        .await?
        .0
    } else {
        items
    };

    let next_page_token = (effective_page < total_pages).then(|| {
        encode_cursor(&SourcePageCursor {
            p: effective_page + 1,
            f: filter.canonical(),
            o: order_by.clone(),
            s: page_size,
        })
    });
    let previous_page_token = (effective_page > 1).then(|| {
        encode_cursor(&SourcePageCursor {
            p: effective_page - 1,
            f: filter.canonical(),
            o: order_by.clone(),
            s: page_size,
        })
    });

    Ok(Json(ListCblSourcesResponse {
        scope,
        folder: response_folder,
        query: response_query,
        breadcrumbs: response_breadcrumbs,
        folders,
        items,
        page: effective_page,
        page_size,
        total,
        catalog_total,
        total_pages,
        has_next: effective_page < total_pages,
        has_previous: effective_page > 1,
        next_page_token,
        previous_page_token,
    }))
}

/// `GET /api/v2/cblSources/{source_id}` — AIP-121 standard Get.
pub async fn get_cbl_source(
    _user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
    Path(source_id): Path<i32>,
    Query(query): Query<GetCblSourceQuery>,
) -> Result<Json<issue_identity::CblSourceListDetail>, ApiError> {
    let offset = parse_nonnegative_int("offset", query.offset.as_deref(), 0)?;
    let limit = parse_bounded_int(
        "limit",
        query.limit.as_deref(),
        1000,
        issue_identity::MAX_ENTRIES_LIMIT,
    )?;
    let conn = db::checkout(&state).await?;
    Ok(Json(
        issue_identity::load_cbl_source_detail(&conn, source_id, offset, limit).await?,
    ))
}

/// `GET /api/v2/cblOccurrences` — bounded exact Comic Vine issue lookup.
pub async fn list_cbl_occurrences(
    _user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
    Query(query): Query<ListCblOccurrencesQuery>,
) -> Result<Json<ListCblOccurrencesResponse>, ApiError> {
    let issue_id = parse_occurrence_filter(query.filter.as_deref())?;
    let page_size = parse_bounded_int(
        "page_size",
        query.page_size.as_deref(),
        50,
        MAX_OCCURRENCE_PAGE_SIZE,
    )?;
    let cursor = occurrence_cursor(query.page_token.as_deref(), &issue_id, page_size)?;
    let offset = match cursor {
        Some(value) => value.o,
        None => parse_nonnegative_int("offset", query.offset.as_deref(), 0)?,
    };
    let limit = parse_bounded_int(
        "limit",
        query.limit.as_deref(),
        page_size,
        MAX_OCCURRENCE_PAGE_SIZE,
    )?;

    let conn = db::checkout(&state).await?;
    let page =
        issue_identity::load_cbl_comicvine_occurrences(&conn, &issue_id, offset, limit).await?;
    let next_page_token =
        (page.occurrences_total as i64 > offset.saturating_add(limit)).then(|| {
            encode_cursor(&OccurrencePageCursor {
                o: offset.saturating_add(limit),
                s: page_size,
                f: issue_id.clone(),
            })
        });

    Ok(Json(ListCblOccurrencesResponse {
        comicvine_issue_id: page.comicvine_issue_id,
        occurrences_total: page.occurrences_total as i64,
        lists_total: page.lists_total as i64,
        occurrences_offset: page.occurrences_offset as i64,
        occurrences_limit: page.occurrences_limit as i64,
        occurrences: page.occurrences,
        next_page_token,
    }))
}

/// Documentation-only List operation for the canonical source collection.
#[utoipa::path(
    get,
    path = "/api/v2/cblSources",
    tag = "cbl-sources",
    params(
        ("filter" = Option<String>, Query, description = "folder=<path> browse or q=<term>/bare term search"),
        ("order_by" = Option<String>, Query, description = "Stable ordering: name (default) or path"),
        ("page_size" = Option<String>, Query, description = "Bounded page size (1-100, default 50)"),
        ("page_token" = Option<String>, Query, description = "Opaque continuation cursor")
    ),
    responses(
        (status = 200, description = "One bounded page of shared CBL sources", body = ListCblSourcesResponse),
        (status = 400, description = "Invalid filter, ordering or token"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Folder not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_cbl_sources_documentation() {}

/// Documentation-only standard Get operation.
#[utoipa::path(
    get,
    path = "/api/v2/cblSources/{source_id}",
    tag = "cbl-sources",
    params(
        ("source_id" = i32, Path, description = "Shared catalog source list id"),
        ("offset" = Option<String>, Query, description = "Ordered entry offset"),
        ("limit" = Option<String>, Query, description = "Bounded entry limit (1-2000, default 1000)")
    ),
    responses(
        (status = 200, description = "One read-only shared source list", body = issue_identity::CblSourceListDetail),
        (status = 400, description = "Invalid paging parameter"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Source not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_cbl_source_documentation() {}

/// Documentation-only occurrence List operation.
#[utoipa::path(
    get,
    path = "/api/v2/cblOccurrences",
    tag = "cbl-sources",
    params(
        ("filter" = Option<String>, Query, description = "comicvine_issue_id=<id> or a bare Comic Vine issue id"),
        ("page_size" = Option<String>, Query, description = "Bounded page size (1-200, default 50)"),
        ("page_token" = Option<String>, Query, description = "Opaque continuation cursor"),
        ("offset" = Option<String>, Query, description = "Retained bounded occurrence offset"),
        ("limit" = Option<String>, Query, description = "Bounded occurrence limit")
    ),
    responses(
        (status = 200, description = "Exact Comic Vine issue occurrences", body = ListCblOccurrencesResponse),
        (status = 400, description = "Invalid filter or token"),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Missing Comic Vine issue id"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_cbl_occurrences_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn filter_parses_folder_search_and_bare_terms() {
        assert_eq!(
            parse_source_filter(None).expect("default filter"),
            SourceFilter::Folder(String::new())
        );
        assert_eq!(
            parse_source_filter(Some("folder:DC/Mister Miracle")).expect("folder"),
            SourceFilter::Folder("DC/Mister Miracle".to_string())
        );
        assert_eq!(
            parse_source_filter(Some("q:JLI")).expect("search"),
            SourceFilter::Search("JLI".to_string())
        );
        assert_eq!(
            parse_source_filter(Some("  Secret Wars  ")).expect("bare term"),
            SourceFilter::Search("Secret Wars".to_string())
        );
    }

    #[test]
    fn filter_rejects_traversal_and_control_characters() {
        for raw in [
            "folder:..",
            "folder:a/../b",
            "folder:a\\b",
            "folder:a\u{0001}b",
            "q:",
        ] {
            assert!(parse_source_filter(Some(raw)).is_err(), "accepted {raw:?}");
        }
        let too_long = format!("q:{}", "x".repeat(MAX_SEARCH_LENGTH + 1));
        assert!(parse_source_filter(Some(&too_long)).is_err());
    }

    #[test]
    fn order_by_is_allowlisted_and_canonicalized() {
        assert_eq!(parse_order_by(None).expect("default"), "name");
        assert_eq!(parse_order_by(Some("source_path")).expect("alias"), "path");
        assert_eq!(parse_order_by(Some("path")).expect("path"), "path");
        assert!(parse_order_by(Some("id; DROP TABLE users")).is_err());
    }

    #[test]
    fn page_size_is_bounded_before_any_allocation() {
        assert_eq!(
            parse_bounded_int("page_size", None, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
                .expect("default"),
            DEFAULT_PAGE_SIZE
        );
        assert!(parse_bounded_int("page_size", Some("0"), 50, 100).is_err());
        assert!(parse_bounded_int("page_size", Some("101"), 50, 100).is_err());
        assert!(parse_bounded_int("page_size", Some("abc"), 50, 100).is_err());
    }

    #[test]
    fn source_token_round_trips_and_rejects_mismatched_queries() {
        let filter = SourceFilter::Folder("DC".to_string());
        let token = encode_cursor(&SourcePageCursor {
            p: 2,
            f: filter.canonical(),
            o: "name".to_string(),
            s: 50,
        });
        let decoded = source_cursor(Some(&token), &filter, "name", 50).expect("valid token");
        assert_eq!(
            decoded,
            Some(SourcePageCursor {
                p: 2,
                f: "folder:DC".to_string(),
                o: "name".to_string(),
                s: 50,
            })
        );
        assert!(source_cursor(Some(&token), &filter, "path", 50).is_err());
        assert!(source_cursor(Some(&token), &filter, "name", 25).is_err());
        assert!(source_cursor(Some("not-a-token"), &filter, "name", 50).is_err());
    }

    #[test]
    fn occurrence_filter_requires_an_exact_issue_id() {
        assert_eq!(
            parse_occurrence_filter(Some("4000-123")).expect("bare id"),
            "4000-123"
        );
        assert_eq!(
            parse_occurrence_filter(Some(" comicvine_issue_id:4000-123 ")).expect("prefixed id"),
            "4000-123"
        );
        assert!(parse_occurrence_filter(None).is_err());
        assert!(parse_occurrence_filter(Some("  ")).is_err());
    }

    #[test]
    fn occurrence_token_round_trips_and_rejects_mismatched_ids() {
        let token = encode_cursor(&OccurrencePageCursor {
            o: 50,
            s: 50,
            f: "4000-123".to_string(),
        });
        assert_eq!(
            occurrence_cursor(Some(&token), "4000-123", 50).expect("valid token"),
            Some(OccurrencePageCursor {
                o: 50,
                s: 50,
                f: "4000-123".to_string(),
            })
        );
        assert!(occurrence_cursor(Some(&token), "4000-999", 50).is_err());
    }

    #[test]
    fn page_offset_uses_checked_arithmetic() {
        assert_eq!(page_offset(1, 50).expect("first page"), 0);
        assert_eq!(page_offset(3, 50).expect("third page"), 100);
        assert!(page_offset(i64::MAX, 100).is_err());
    }
}
