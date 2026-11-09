//! Owner-scoped tag vocabulary, assignments and effective-tag inheritance.
//!
//! Rust replacement for the Python `/api/v1/tags/*` routes. The HTTP method
//! and exact path are preserved; only the implementation moves.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

// ---------------------------------------------------------------------------
// Wire types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct Tag {
    pub id: i32,
    pub name: String,
    pub normalized_name: String,
    pub scope: String,
    pub owner_user_id: Option<i32>,
    pub color: String,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct NearMatch {
    pub id: i32,
    pub name: String,
    pub color: String,
    pub normalized_name: String,
    pub scope: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct TagListResponse {
    pub tags: Vec<Tag>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct CreateTagRequest {
    pub name: String,
    #[serde(default = "default_color")]
    pub color: String,
    #[serde(default = "default_scope")]
    pub scope: String,
    #[serde(default = "default_true")]
    pub include_near_matches: bool,
}

fn default_color() -> String {
    "red".to_string()
}
fn default_scope() -> String {
    "private".to_string()
}
fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct CreateTagResponse {
    pub tag: Tag,
    pub redirected_to_global: bool,
    pub near_matches: Vec<NearMatch>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct UpdateTagRequest {
    pub name: Option<String>,
    pub color: Option<String>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct TagAssignmentResponse {
    pub id: i32,
    pub tag_id: i32,
    pub target_type: String,
    pub target_id: i32,
    pub created_at: String,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct AssignTagRequest {
    pub target_type: String,
    pub target_id: i32,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct BulkAssignRequest {
    pub target_type: String,
    pub target_ids: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct BulkAssignResponse {
    pub tag_id: i32,
    pub target_type: String,
    pub requested_ids: Vec<i32>,
    pub affected_ids: Vec<i32>,
    pub already_ids: Vec<i32>,
    pub still_inherited_ids: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct TagUsageResponse {
    pub tag_id: i32,
    pub total_assignments: i64,
    pub assignments_by_target_type: BTreeMap<String, i64>,
    pub references_removed_by_consumers: BTreeMap<String, i64>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct TagDeleteResponse {
    pub tag_id: i32,
    pub assignments_removed: i64,
    pub references_removed_by_consumers: BTreeMap<String, i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct InheritanceSource {
    pub target_type: String,
    pub target_id: i32,
    pub display_name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct EffectiveTag {
    pub tag: Tag,
    pub direct: bool,
    pub sources: Vec<InheritanceSource>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct EffectiveTagsResponse {
    pub target_type: String,
    pub target_id: i32,
    pub direct_tags: Vec<Tag>,
    pub effective_tags: Vec<EffectiveTag>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ThreadIssuesEffectiveTagsResponse {
    pub thread_id: i32,
    pub issues: Vec<EffectiveTagsResponse>,
}

// ---------------------------------------------------------------------------
// Query types
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
pub struct ListQuery {
    pub search: Option<String>,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn bad_request(detail: &str) -> ApiError {
    ApiError(StatusCode::BAD_REQUEST, detail.to_string())
}
fn not_found(detail: &str) -> ApiError {
    ApiError(StatusCode::NOT_FOUND, detail.to_string())
}
fn forbidden(detail: &str) -> ApiError {
    ApiError(StatusCode::FORBIDDEN, detail.to_string())
}
fn conflict(detail: &str) -> ApiError {
    ApiError(StatusCode::CONFLICT, detail.to_string())
}

fn normalize_tag_name(name: &str) -> String {
    name.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
}

const PALETTE: &[(&str, &str)] = &[
    ("red", "#DC2626"),
    ("orange", "#F97316"),
    ("amber", "#F59E0B"),
    ("yellow", "#EAB308"),
    ("lime", "#84CC16"),
    ("green", "#22C55E"),
    ("emerald", "#10B981"),
    ("teal", "#14B8A6"),
    ("cyan", "#06B6D4"),
    ("sky", "#0EA5E9"),
    ("blue", "#3B82F6"),
    ("indigo", "#6366F1"),
    ("violet", "#8B5CF6"),
    ("purple", "#A855F7"),
    ("fuchsia", "#D946EF"),
    ("pink", "#EC4899"),
    ("rose", "#F43F5E"),
    ("crimson", "#B91C1C"),
    ("burgundy", "#7F1D1D"),
    ("maroon", "#78350F"),
    ("brown", "#92400E"),
    ("gold", "#D97706"),
    ("bronze", "#B45309"),
    ("khaki", "#A16207"),
    ("olive", "#65A30D"),
    ("forest", "#15803D"),
    ("mint", "#34D399"),
    ("ice", "#22D3EE"),
    ("cobalt", "#2563EB"),
    ("royal", "#4F46E5"),
    ("violet-deep", "#7C3AED"),
    ("magenta", "#E879F9"),
];

fn validate_color(color: &str) -> Result<(String, String), ApiError> {
    let normalized = color.trim().to_lowercase();
    if normalized.is_empty() {
        return Err(bad_request("Tag color cannot be empty"));
    }
    for (name, hex) in PALETTE {
        if *name == normalized {
            return Ok((normalized, hex.to_string()));
        }
    }
    if normalized.starts_with('#') && normalized.len() == 7 {
        for (name, hex) in PALETTE {
            if hex.to_lowercase() == normalized {
                return Ok((name.to_string(), hex.to_string()));
            }
        }
    }
    Err(bad_request(&format!(
        "Color '{}' is not in the fixed tag color palette",
        color
    )))
}

fn levenshtein(a: &str, b: &str) -> usize {
    if a.len() < b.len() {
        return levenshtein(b, a);
    }
    if b.is_empty() {
        return a.chars().count();
    }
    let b_chars: Vec<char> = b.chars().collect();
    let mut prev: Vec<usize> = (0..=b_chars.len()).collect();
    for (i, ca) in a.chars().enumerate() {
        let mut cur = vec![i + 1];
        for (j, cb) in b_chars.iter().enumerate() {
            let ins = prev[j + 1] + 1;
            let del = cur[j] + 1;
            let sub = prev[j] + usize::from(ca != *cb);
            cur.push(ins.min(del).min(sub));
        }
        prev = cur;
    }
    prev[b_chars.len()]
}

async fn is_admin_conn(conn: &deadpool_postgres::Object, user_id: i32) -> Result<bool, ApiError> {
    let row = conn
        .query_opt("SELECT is_admin FROM users WHERE id = $1", &[&user_id])
        .await
        .map_err(db::query_error)?;
    Ok(row.map(|r| r.get::<_, bool>(0)).unwrap_or(false))
}

async fn is_admin_tx(tx: &tokio_postgres::Transaction<'_>, user_id: i32) -> Result<bool, ApiError> {
    let row = tx
        .query_opt("SELECT is_admin FROM users WHERE id = $1", &[&user_id])
        .await
        .map_err(db::query_error)?;
    Ok(row.map(|r| r.get::<_, bool>(0)).unwrap_or(false))
}

fn row_to_tag(row: &tokio_postgres::Row) -> Tag {
    Tag {
        id: row.get(0),
        name: row.get(1),
        normalized_name: row.get(2),
        scope: row.get(3),
        owner_user_id: row.get(4),
        color: row.get(5),
        created_at: row.get(6),
        updated_at: row.get(7),
    }
}

const TAG_SELECT: &str = "SELECT id, name, normalized_name, scope, owner_user_id, color, created_at::text, updated_at::text FROM tags";

async fn load_tag_conn(
    conn: &deadpool_postgres::Object,
    tag_id: i32,
) -> Result<Option<Tag>, ApiError> {
    let row = conn
        .query_opt(&format!("{} WHERE id = $1", TAG_SELECT), &[&tag_id])
        .await
        .map_err(db::query_error)?;
    Ok(row.as_ref().map(row_to_tag))
}

async fn load_tag_tx(
    tx: &tokio_postgres::Transaction<'_>,
    tag_id: i32,
) -> Result<Option<Tag>, ApiError> {
    let row = tx
        .query_opt(&format!("{} WHERE id = $1", TAG_SELECT), &[&tag_id])
        .await
        .map_err(db::query_error)?;
    Ok(row.as_ref().map(row_to_tag))
}

// target validation
async fn validate_target_conn(
    conn: &deadpool_postgres::Object,
    user_id: i32,
    target_type: &str,
    target_id: i32,
    enforce_ownership: bool,
) -> Result<(), ApiError> {
    match target_type {
        "Issue" => {
            let sql = if enforce_ownership {
                "SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE i.id=$1 AND t.user_id=$2"
            } else {
                "SELECT i.id FROM issues i WHERE i.id=$1"
            };
            let params: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = if enforce_ownership {
                vec![&target_id, &user_id]
            } else {
                vec![&target_id]
            };
            let row = conn
                .query_opt(sql, &params)
                .await
                .map_err(db::query_error)?;
            if row.is_none() {
                return Err(not_found(&format!(
                    "Issue with id {} does not exist",
                    target_id
                )));
            }
        }
        "Thread" => {
            let sql = if enforce_ownership {
                "SELECT id FROM threads WHERE id=$1 AND user_id=$2"
            } else {
                "SELECT id FROM threads WHERE id=$1"
            };
            let params: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = if enforce_ownership {
                vec![&target_id, &user_id]
            } else {
                vec![&target_id]
            };
            let row = conn
                .query_opt(sql, &params)
                .await
                .map_err(db::query_error)?;
            if row.is_none() {
                return Err(not_found(&format!(
                    "Thread with id {} does not exist",
                    target_id
                )));
            }
        }
        "ContinuityPlan" => {
            let sql = if enforce_ownership {
                "SELECT id FROM continuity_plans WHERE id=$1 AND user_id=$2"
            } else {
                "SELECT id FROM continuity_plans WHERE id=$1"
            };
            let params: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = if enforce_ownership {
                vec![&target_id, &user_id]
            } else {
                vec![&target_id]
            };
            let row = conn
                .query_opt(sql, &params)
                .await
                .map_err(db::query_error)?;
            if row.is_none() {
                return Err(not_found(&format!(
                    "ContinuityPlan with id {} does not exist",
                    target_id
                )));
            }
        }
        _ => {
            return Err(bad_request(&format!(
                "Unsupported target type '{}'. Supported types: Issue, Thread, ContinuityPlan",
                target_type
            )))
        }
    }
    Ok(())
}

async fn validate_target_tx(
    tx: &tokio_postgres::Transaction<'_>,
    user_id: i32,
    target_type: &str,
    target_id: i32,
    enforce_ownership: bool,
) -> Result<(), ApiError> {
    // reuse by delegating with manual (duplicate minimal)
    match target_type {
        "Issue" => {
            let sql = if enforce_ownership {
                "SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE i.id=$1 AND t.user_id=$2"
            } else {
                "SELECT i.id FROM issues i WHERE i.id=$1"
            };
            let row = if enforce_ownership {
                tx.query_opt(sql, &[&target_id, &user_id]).await
            } else {
                tx.query_opt(sql, &[&target_id]).await
            }
            .map_err(db::query_error)?;
            if row.is_none() {
                return Err(not_found(&format!(
                    "Issue with id {} does not exist",
                    target_id
                )));
            }
        }
        "Thread" => {
            let sql = if enforce_ownership {
                "SELECT id FROM threads WHERE id=$1 AND user_id=$2"
            } else {
                "SELECT id FROM threads WHERE id=$1"
            };
            let row = if enforce_ownership {
                tx.query_opt(sql, &[&target_id, &user_id]).await
            } else {
                tx.query_opt(sql, &[&target_id]).await
            }
            .map_err(db::query_error)?;
            if row.is_none() {
                return Err(not_found(&format!(
                    "Thread with id {} does not exist",
                    target_id
                )));
            }
        }
        "ContinuityPlan" => {
            let sql = if enforce_ownership {
                "SELECT id FROM continuity_plans WHERE id=$1 AND user_id=$2"
            } else {
                "SELECT id FROM continuity_plans WHERE id=$1"
            };
            let row = if enforce_ownership {
                tx.query_opt(sql, &[&target_id, &user_id]).await
            } else {
                tx.query_opt(sql, &[&target_id]).await
            }
            .map_err(db::query_error)?;
            if row.is_none() {
                return Err(not_found(&format!(
                    "ContinuityPlan with id {} does not exist",
                    target_id
                )));
            }
        }
        _ => {
            return Err(bad_request(&format!(
                "Unsupported target type '{}'. Supported types: Issue, Thread, ContinuityPlan",
                target_type
            )))
        }
    }
    Ok(())
}

// visible assignments
async fn visible_assignments_conn(
    conn: &deadpool_postgres::Object,
    user_id: i32,
    targets: &[(String, i32)],
) -> Result<Vec<(Tag, String, i32)>, ApiError> {
    if targets.is_empty() {
        return Ok(vec![]);
    }
    // build where
    let mut conditions: Vec<String> = Vec::new();
    let mut params: Vec<Box<dyn tokio_postgres::types::ToSql + Send + Sync>> = Vec::new();
    // We'll use positional params: first user_id? We'll put user_id last maybe. Simpler: params for targets then user_id.
    let mut idx = 1;
    // target conditions
    let mut cond_strs: Vec<String> = Vec::new();
    for (tt, tid) in targets {
        cond_strs.push(format!(
            "(a.target_type = ${} AND a.target_id = ${})",
            idx,
            idx + 1
        ));
        params.push(Box::new(tt.clone()));
        params.push(Box::new(*tid));
        idx += 2;
    }
    let user_param = idx;
    params.push(Box::new(user_id));
    let sql = format!(
        "SELECT t.id, t.name, t.normalized_name, t.scope, t.owner_user_id, t.color, t.created_at::text, t.updated_at::text, a.target_type, a.target_id
         FROM tag_assignments a JOIN tags t ON t.id = a.tag_id
         WHERE ({}) AND (t.scope = 'global' OR t.owner_user_id = ${})
         ORDER BY t.scope DESC, t.normalized_name, a.target_type",
        cond_strs.join(" OR "),
        user_param
    );
    let param_refs: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = params
        .iter()
        .map(|p| p.as_ref() as &(dyn tokio_postgres::types::ToSql + Sync))
        .collect();
    let rows = conn
        .query(&sql, &param_refs)
        .await
        .map_err(db::query_error)?;
    let mut out = Vec::new();
    for row in rows {
        let tag = Tag {
            id: row.get(0),
            name: row.get(1),
            normalized_name: row.get(2),
            scope: row.get(3),
            owner_user_id: row.get(4),
            color: row.get(5),
            created_at: row.get(6),
            updated_at: row.get(7),
        };
        let tt: String = row.get(8);
        let tid: i32 = row.get(9);
        out.push((tag, tt, tid));
    }
    Ok(out)
}

async fn visible_assignments_tx(
    tx: &tokio_postgres::Transaction<'_>,
    user_id: i32,
    targets: &[(String, i32)],
) -> Result<Vec<(Tag, String, i32)>, ApiError> {
    if targets.is_empty() {
        return Ok(vec![]);
    }
    let mut cond_strs: Vec<String> = Vec::new();
    // We need params; use a Vec of owned values then refs. tokio tx query takes &[&(dyn ToSql+Sync)].
    // Build sql with placeholders; params order targets then user.
    let mut sql_params_count = 0;
    // We'll construct query using a helper with Vec of types erased? tokio_postgres requires heterogeneous slice of references.
    // Easier: handle small by building query with IN? Use (target_type,target_id) IN list via row constructors with literals? IDs ints safe, types strings need quotes. We'll instead do multiple queries per target (acceptable) to avoid dynamic param typing. But N small. Simpler: loop targets.
    let mut out = Vec::new();
    for (tt, tid) in targets {
        let rows = tx
            .query(
                &format!(
                    "{} WHERE a.target_type = $1 AND a.target_id = $2 AND (t.scope = 'global' OR t.owner_user_id = $3) ORDER BY t.scope DESC, t.normalized_name",
                    "SELECT t.id, t.name, t.normalized_name, t.scope, t.owner_user_id, t.color, t.created_at::text, t.updated_at::text, a.target_type, a.target_id FROM tag_assignments a JOIN tags t ON t.id = a.tag_id"
                ),
                &[tt, tid, &user_id],
            )
            .await
            .map_err(db::query_error)?;
        for row in rows {
            let tag = Tag {
                id: row.get(0),
                name: row.get(1),
                normalized_name: row.get(2),
                scope: row.get(3),
                owner_user_id: row.get(4),
                color: row.get(5),
                created_at: row.get(6),
                updated_at: row.get(7),
            };
            let rtt: String = row.get(8);
            let rtid: i32 = row.get(9);
            out.push((tag, rtt, rtid));
        }
    }
    // dedup? Python orders by scope/name/target_type. We'll sort.
    out.sort_by(|a, b| {
        (
            a.0.scope.as_str(),
            a.0.normalized_name.as_str(),
            a.1.as_str(),
        )
            .cmp(&(
                b.0.scope.as_str(),
                b.0.normalized_name.as_str(),
                b.1.as_str(),
            ))
    });
    // reverse scope? scope desc: global before private. String desc: "global" > "private", so descending. Our sort ascending would private first. Need descending scope. Let's sort with scope descending.
    out.sort_by(|a, b| {
        b.0.scope
            .cmp(&a.0.scope)
            .then(a.0.normalized_name.cmp(&b.0.normalized_name))
            .then(a.1.cmp(&b.1))
    });
    // dedup duplicate tag assignments? Each assignment row unique. Fine.
    Ok(out)
}

// combine
fn combine_assignments(
    self_type: &str,
    self_id: i32,
    pairs: Vec<(Tag, String, i32, String)>,
) -> EffectiveTagsResponse {
    // by tag id
    let mut by_id: BTreeMap<i32, EffectiveTag> = BTreeMap::new();
    let mut order: Vec<i32> = Vec::new();
    for (tag, source_type, source_id, display_name) in pairs {
        if !by_id.contains_key(&tag.id) {
            by_id.insert(
                tag.id,
                EffectiveTag {
                    tag: tag.clone(),
                    direct: false,
                    sources: vec![],
                },
            );
            order.push(tag.id);
        }
        let entry = by_id.get_mut(&tag.id).unwrap();
        if source_type == self_type && source_id == self_id {
            entry.direct = true;
        }
        entry.sources.push(InheritanceSource {
            target_type: source_type,
            target_id: source_id,
            display_name,
        });
    }
    // Note: by_id moved? We inserted tag before; need tag value. We cloned tag into EffectiveTag. Good.
    let mut effective = Vec::new();
    for id in &order {
        effective.push(by_id.remove(id).unwrap());
    }
    // put back? not needed
    let direct_tags: Vec<Tag> = effective
        .iter()
        .filter(|e| e.direct)
        .map(|e| e.tag.clone())
        .collect();
    // But effective moved? We need effective for response. We built effective Vec. Good.
    // However direct_tags references effective before move? We collected already. Good.
    EffectiveTagsResponse {
        target_type: self_type.to_string(),
        target_id: self_id,
        direct_tags,
        effective_tags: effective,
    }
}

// near matches
async fn find_near_global_tags(
    conn: &deadpool_postgres::Object,
    normalized: &str,
) -> Result<Vec<Tag>, ApiError> {
    let rows = conn
        .query(
            &format!(
                "{} WHERE scope = 'global' ORDER BY normalized_name",
                TAG_SELECT
            ),
            &[],
        )
        .await
        .map_err(db::query_error)?;
    let globals: Vec<Tag> = rows.iter().map(row_to_tag).collect();
    let mut matches: Vec<(usize, Tag)> = Vec::new();
    for tag in globals {
        let dist = levenshtein(normalized, &tag.normalized_name);
        if dist <= 2 {
            matches.push((dist, tag));
            continue;
        }
        if normalized.contains(&tag.normalized_name) || tag.normalized_name.contains(normalized) {
            matches.push((dist, tag));
        }
    }
    matches.sort_by_key(|m| m.0);
    Ok(matches.into_iter().take(8).map(|m| m.1).collect())
}

// user_is_admin helper alias already.

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

/// GET /api/v1/tags/
pub async fn list_tags(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(q): Query<ListQuery>,
) -> Result<Json<TagListResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let user_id = user.id();
    let normalized_search = q
        .search
        .as_deref()
        .map(normalize_tag_name)
        .unwrap_or_default();
    let sql = if normalized_search.is_empty() {
        format!(
            "{} WHERE (scope = 'global' OR owner_user_id = $1) ORDER BY scope DESC, normalized_name",
            TAG_SELECT
        )
    } else {
        format!(
            "{} WHERE (scope = 'global' OR owner_user_id = $1) AND normalized_name LIKE '%' || $2 || '%' ORDER BY scope DESC, normalized_name",
            TAG_SELECT
        )
    };
    let rows = if normalized_search.is_empty() {
        conn.query(&sql, &[&user_id]).await
    } else {
        conn.query(&sql, &[&user_id, &normalized_search]).await
    }
    .map_err(db::query_error)?;
    let tags = rows.iter().map(row_to_tag).collect();
    Ok(Json(TagListResponse { tags }))
}

/// GET /api/v1/tags/{tag_id}/
pub async fn get_tag(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(tag_id): Path<i32>,
) -> Result<Json<Tag>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tag = load_tag_conn(&conn, tag_id).await?;
    let tag = match tag {
        Some(t) => t,
        None => return Err(not_found(&format!("Tag {} does not exist", tag_id))),
    };
    if tag.scope == "private" && tag.owner_user_id != Some(user.id()) {
        return Err(not_found(&format!("Tag {} does not exist", tag_id)));
    }
    Ok(Json(tag))
}

/// POST /api/v1/tags/
pub async fn create_tag(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(req): Json<CreateTagRequest>,
) -> Result<Json<CreateTagResponse>, ApiError> {
    let normalized = normalize_tag_name(&req.name);
    if normalized.is_empty() {
        return Err(bad_request("Tag name cannot be empty"));
    }
    let color_input = if req.color.is_empty() {
        "red".to_string()
    } else {
        req.color.clone()
    };
    let (_, color_hex) = validate_color(&color_input)?;
    let is_admin = {
        let mut conn = db::checkout(&state).await?;
        is_admin_conn(&conn, user.id()).await?
    };
    let effective_scope = match req.scope.as_str() {
        "global" => {
            if !is_admin {
                return Err(forbidden("Only administrators can create global tags"));
            }
            "global"
        }
        "private" => "private",
        other => return Err(bad_request(&format!("Unknown tag scope '{}'", other))),
    };

    let mut conn = db::checkout(&state).await?;
    // exact global match
    let existing_global = conn
        .query_opt(
            &format!(
                "{} WHERE normalized_name = $1 AND scope = 'global'",
                TAG_SELECT
            ),
            &[&normalized],
        )
        .await
        .map_err(db::query_error)?;
    if let Some(row) = existing_global {
        let tag = row_to_tag(&row);
        return Ok(Json(CreateTagResponse {
            tag,
            redirected_to_global: true,
            near_matches: vec![],
        }));
    }

    if effective_scope == "private" {
        let existing_private = conn
            .query_opt(
                &format!(
                    "{} WHERE scope = 'private' AND owner_user_id = $1 AND normalized_name = $2",
                    TAG_SELECT
                ),
                &[&user.id(), &normalized],
            )
            .await
            .map_err(db::query_error)?;
        if existing_private.is_some() {
            return Err(conflict("A tag with this name already exists"));
        }
    }

    let near_matches: Vec<NearMatch> = if req.include_near_matches {
        let tags = find_near_global_tags(&conn, &normalized).await?;
        tags.into_iter()
            .map(|t| NearMatch {
                id: t.id,
                name: t.name,
                color: t.color,
                normalized_name: t.normalized_name,
                scope: t.scope,
            })
            .collect()
    } else {
        vec![]
    };

    // insert
    let owner_user_id: Option<i32> = if effective_scope == "private" {
        Some(user.id())
    } else {
        None
    };
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let row = tx
        .query_one(
            "INSERT INTO tags (name, normalized_name, scope, owner_user_id, color, created_at, updated_at)
             VALUES ($1,$2,$3,$4,$5,NOW(),NOW())
             RETURNING id, name, normalized_name, scope, owner_user_id, color, created_at::text, updated_at::text",
            &[&req.name, &normalized, &effective_scope, &owner_user_id, &color_hex],
        )
        .await;
    match row {
        Ok(r) => {
            let tag = row_to_tag(&r);
            tx.commit().await.map_err(db::query_error)?;
            Ok(Json(CreateTagResponse {
                tag,
                redirected_to_global: false,
                near_matches,
            }))
        }
        Err(e) => {
            let _ = tx.rollback().await;
            // unique violation
            if e.code().map(|c| c.code()) == Some("23505") {
                return Err(conflict("A tag with this name already exists"));
            }
            return Err(db::query_error(e));
        }
    }
}

/// GET /api/v1/tags/{tag_id}/
// (get_tag above)

/// PUT /api/v1/tags/{tag_id}/
pub async fn update_tag(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(tag_id): Path<i32>,
    Json(req): Json<UpdateTagRequest>,
) -> Result<Json<Tag>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tag = load_tag_conn(&conn, tag_id).await?;
    let mut tag = match tag {
        Some(t) => t,
        None => return Err(not_found(&format!("Tag {} does not exist", tag_id))),
    };
    if tag.scope == "private" && tag.owner_user_id != Some(user.id()) {
        return Err(not_found(&format!("Tag {} does not exist", tag_id)));
    }
    let is_admin = is_admin_conn(&conn, user.id()).await?;
    if tag.scope == "global" {
        if !is_admin {
            return Err(forbidden("Only administrators can edit global tags"));
        }
    } else if tag.owner_user_id != Some(user.id()) {
        return Err(forbidden("You can only edit your own private tags"));
    }

    if req.name.is_none() && req.color.is_none() {
        return Ok(Json(tag));
    }

    if let Some(name) = &req.name {
        let normalized = normalize_tag_name(name);
        if normalized.is_empty() {
            return Err(bad_request("Tag name cannot be empty"));
        }
        if normalized != tag.normalized_name {
            // global collision
            let existing = conn
                .query_opt(
                    &format!(
                        "{} WHERE normalized_name = $1 AND scope = 'global'",
                        TAG_SELECT
                    ),
                    &[&normalized],
                )
                .await
                .map_err(db::query_error)?;
            if existing.is_some() {
                return Err(conflict(&format!(
                    "A global tag named '{}' already exists",
                    name
                )));
            }
            if tag.scope == "private" && tag.owner_user_id.is_some() {
                let dup = conn
                    .query_opt(
                        &format!(
                            "{} WHERE scope = 'private' AND owner_user_id = $1 AND normalized_name = $2",
                            TAG_SELECT
                        ),
                        &[&tag.owner_user_id.unwrap(), &normalized],
                    )
                    .await
                    .map_err(db::query_error)?;
                if let Some(d) = dup {
                    let dtag = row_to_tag(&d);
                    if dtag.id != tag.id {
                        return Err(conflict("A tag with this name already exists"));
                    }
                }
            }
        }
        tag.name = name.clone();
        tag.normalized_name = normalized;
    }
    if let Some(color) = &req.color {
        let (_, hex) = validate_color(color)?;
        tag.color = hex;
    }

    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let row = tx
        .query_one(
            "UPDATE tags SET name=$1, normalized_name=$2, color=$3, updated_at=NOW()
             WHERE id=$4
             RETURNING id, name, normalized_name, scope, owner_user_id, color, created_at::text, updated_at::text",
            &[&tag.name, &tag.normalized_name, &tag.color, &tag.id],
        )
        .await;
    match row {
        Ok(r) => {
            let updated = row_to_tag(&r);
            tx.commit().await.map_err(db::query_error)?;
            Ok(Json(updated))
        }
        Err(e) => {
            let _ = tx.rollback().await;
            if e.code().map(|c| c.code()) == Some("23505") {
                return Err(conflict("A tag with this name already exists"));
            }
            Err(db::query_error(e))
        }
    }
}

/// DELETE /api/v1/tags/{tag_id}/
pub async fn delete_tag(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(tag_id): Path<i32>,
) -> Result<Json<TagDeleteResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tag = load_tag_conn(&conn, tag_id).await?;
    let tag = match tag {
        Some(t) => t,
        None => return Err(not_found(&format!("Tag {} does not exist", tag_id))),
    };
    if tag.scope == "private" && tag.owner_user_id != Some(user.id()) {
        return Err(not_found(&format!("Tag {} does not exist", tag_id)));
    }
    let is_admin = is_admin_conn(&conn, user.id()).await?;
    if tag.scope == "global" {
        if !is_admin {
            return Err(forbidden("Only administrators can delete global tags"));
        }
    } else if tag.owner_user_id != Some(user.id()) {
        return Err(forbidden("You can only delete your own private tags"));
    }

    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let del_assign = tx
        .execute("DELETE FROM tag_assignments WHERE tag_id = $1", &[&tag_id])
        .await
        .map_err(db::query_error)?;
    let del_tag = tx
        .execute("DELETE FROM tags WHERE id = $1", &[&tag_id])
        .await
        .map_err(db::query_error)?;
    if del_tag == 0 {
        let _ = tx.rollback().await;
        return Err(not_found(&format!("Tag {} does not exist", tag_id)));
    }
    tx.commit().await.map_err(db::query_error)?;
    let mut refs = BTreeMap::new();
    Ok(Json(TagDeleteResponse {
        tag_id,
        assignments_removed: del_assign as i64,
        references_removed_by_consumers: refs,
    }))
}

/// GET /api/v1/tags/{tag_id}/usage/
pub async fn get_tag_usage(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(tag_id): Path<i32>,
) -> Result<Json<TagUsageResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tag = load_tag_conn(&conn, tag_id).await?;
    let tag = match tag {
        Some(t) => t,
        None => return Err(not_found(&format!("Tag {} does not exist", tag_id))),
    };
    if tag.scope == "private" && tag.owner_user_id != Some(user.id()) {
        return Err(not_found(&format!("Tag {} does not exist", tag_id)));
    }
    let total: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM tag_assignments WHERE tag_id = $1",
            &[&tag_id],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    let rows = conn
        .query(
            "SELECT target_type, COUNT(*)::bigint FROM tag_assignments WHERE tag_id = $1 GROUP BY target_type",
            &[&tag_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut by_type = BTreeMap::new();
    for row in rows {
        let tt: String = row.get(0);
        let c: i64 = row.get(1);
        by_type.insert(tt, c);
    }
    Ok(Json(TagUsageResponse {
        tag_id,
        total_assignments: total,
        assignments_by_target_type: by_type,
        references_removed_by_consumers: BTreeMap::new(),
    }))
}

/// POST /api/v1/tags/{tag_id}/assign/
pub async fn assign_tag(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(tag_id): Path<i32>,
    Json(req): Json<AssignTagRequest>,
) -> Result<Json<TagAssignmentResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tag = load_tag_conn(&conn, tag_id).await?;
    let tag = match tag {
        Some(t) => t,
        None => return Err(not_found(&format!("Tag {} does not exist", tag_id))),
    };
    let is_global = tag.scope == "global";
    if is_global {
        let is_admin = is_admin_conn(&conn, user.id()).await?;
        if !is_admin {
            return Err(forbidden("Only administrators can assign global tags"));
        }
    } else if tag.owner_user_id != Some(user.id()) {
        return Err(forbidden("You can only assign your own private tags"));
    }
    let enforce = !is_global;
    validate_target_conn(&conn, user.id(), &req.target_type, req.target_id, enforce).await?;

    // transaction
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    // insert if not exists
    let existing = tx
        .query_opt(
            "SELECT id, created_at::text FROM tag_assignments WHERE tag_id=$1 AND target_type=$2 AND target_id=$3",
            &[&tag_id, &req.target_type, &req.target_id],
        )
        .await
        .map_err(db::query_error)?;
    let assignment_id: i32;
    let created_at: String;
    if let Some(row) = existing {
        assignment_id = row.get(0);
        created_at = row.get(1);
    } else {
        match tx
            .query_one(
                "INSERT INTO tag_assignments (tag_id, target_type, target_id, created_at) VALUES ($1,$2,$3,NOW()) RETURNING id, created_at::text",
                &[&tag_id, &req.target_type, &req.target_id],
            )
            .await
        {
            Ok(r) => {
                assignment_id = r.get(0);
                created_at = r.get(1);
            }
            Err(e) => {
                let _ = tx.rollback().await;
                if e.code().map(|c| c.code()) == Some("23505") {
                    return Err(conflict("This tag is already assigned to that target"));
                }
                return Err(db::query_error(e));
            }
        }
    }
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(TagAssignmentResponse {
        id: assignment_id,
        tag_id,
        target_type: req.target_type,
        target_id: req.target_id,
        created_at,
    }))
}

/// DELETE /api/v1/tags/{tag_id}/unassign/
pub async fn unassign_tag(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(tag_id): Path<i32>,
    Json(req): Json<AssignTagRequest>,
) -> Result<Json<TagAssignmentResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tag = load_tag_conn(&conn, tag_id).await?;
    let tag = match tag {
        Some(t) => t,
        None => return Err(not_found(&format!("Tag {} does not exist", tag_id))),
    };
    if tag.scope == "global" {
        let is_admin = is_admin_conn(&conn, user.id()).await?;
        if !is_admin {
            return Err(forbidden("Only administrators can unassign global tags"));
        }
    } else if tag.owner_user_id != Some(user.id()) {
        return Err(forbidden("You can only unassign your own private tags"));
    }

    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let row = tx
        .query_opt(
            "SELECT id, created_at::text FROM tag_assignments WHERE tag_id=$1 AND target_type=$2 AND target_id=$3",
            &[&tag_id, &req.target_type, &req.target_id],
        )
        .await
        .map_err(db::query_error)?;
    let (assignment_id, created_at) = match row {
        Some(r) => (r.get::<_, i32>(0), r.get::<_, String>(1)),
        None => {
            let _ = tx.rollback().await;
            return Err(not_found(&format!(
                "Tag {} is not assigned to this {}",
                tag_id, req.target_type
            )));
        }
    };
    tx.execute(
        "DELETE FROM tag_assignments WHERE tag_id=$1 AND target_type=$2 AND target_id=$3",
        &[&tag_id, &req.target_type, &req.target_id],
    )
    .await
    .map_err(db::query_error)?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(TagAssignmentResponse {
        id: assignment_id,
        tag_id,
        target_type: req.target_type,
        target_id: req.target_id,
        created_at,
    }))
}

/// POST /api/v1/tags/{tag_id}/bulk-assign/
pub async fn bulk_assign_tag(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(tag_id): Path<i32>,
    Json(req): Json<BulkAssignRequest>,
) -> Result<Json<BulkAssignResponse>, ApiError> {
    let requested_ids: Vec<i32> = {
        let mut seen = BTreeSet::new();
        let mut out = Vec::new();
        for id in &req.target_ids {
            if seen.insert(*id) {
                out.push(*id);
            }
        }
        out
    };
    if requested_ids.is_empty() {
        return Err(bad_request("At least one target id is required"));
    }
    if !["Issue", "Thread", "ContinuityPlan"].contains(&req.target_type.as_str()) {
        return Err(bad_request("Unsupported target type"));
    }
    let mut conn = db::checkout(&state).await?;
    let tag = load_tag_conn(&conn, tag_id).await?;
    let tag = match tag {
        Some(t) => t,
        None => return Err(not_found(&format!("Tag {} does not exist", tag_id))),
    };
    let is_global = tag.scope == "global";
    if is_global {
        let is_admin = is_admin_conn(&conn, user.id()).await?;
        if !is_admin {
            return Err(forbidden("Only administrators can assign global tags"));
        }
    } else if tag.owner_user_id != Some(user.id()) {
        return Err(forbidden("You can only assign your own private tags"));
    }
    let enforce = !is_global;

    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    // validate all targets first
    for tid in &requested_ids {
        if let Err(e) = validate_target_tx(&tx, user.id(), &req.target_type, *tid, enforce).await {
            let _ = tx.rollback().await;
            return Err(e);
        }
    }
    // insert
    let mut newly: Vec<i32> = Vec::new();
    let mut already: Vec<i32> = Vec::new();
    for tid in &requested_ids {
        let ex = tx
            .query_opt(
                "SELECT id FROM tag_assignments WHERE tag_id=$1 AND target_type=$2 AND target_id=$3",
                &[&tag_id, &req.target_type, tid],
            )
            .await
            .map_err(db::query_error)?;
        if ex.is_some() {
            already.push(*tid);
            continue;
        }
        match tx
            .execute(
                "INSERT INTO tag_assignments (tag_id, target_type, target_id, created_at) VALUES ($1,$2,$3,NOW())",
                &[&tag_id, &req.target_type, tid],
            )
            .await
        {
            Ok(_) => newly.push(*tid),
            Err(e) => {
                let _ = tx.rollback().await;
                if e.code().map(|c| c.code()) == Some("23505") {
                    return Err(conflict("This tag is already assigned to one of those targets"));
                }
                return Err(db::query_error(e));
            }
        }
    }
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(BulkAssignResponse {
        tag_id,
        target_type: req.target_type,
        requested_ids,
        affected_ids: newly,
        already_ids: already,
        still_inherited_ids: vec![],
    }))
}

/// POST /api/v1/tags/{tag_id}/bulk-unassign/
pub async fn bulk_unassign_tag(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(tag_id): Path<i32>,
    Json(req): Json<BulkAssignRequest>,
) -> Result<Json<BulkAssignResponse>, ApiError> {
    let requested_ids: Vec<i32> = {
        let mut seen = BTreeSet::new();
        let mut out = Vec::new();
        for id in &req.target_ids {
            if seen.insert(*id) {
                out.push(*id);
            }
        }
        out
    };
    if requested_ids.is_empty() {
        return Err(bad_request("At least one target id is required"));
    }
    if !["Issue", "Thread", "ContinuityPlan"].contains(&req.target_type.as_str()) {
        return Err(bad_request("Unsupported target type"));
    }
    let mut conn = db::checkout(&state).await?;
    let tag = load_tag_conn(&conn, tag_id).await?;
    let tag = match tag {
        Some(t) => t,
        None => return Err(not_found(&format!("Tag {} does not exist", tag_id))),
    };
    if tag.scope == "global" {
        let is_admin = is_admin_conn(&conn, user.id()).await?;
        if !is_admin {
            return Err(forbidden("Only administrators can unassign global tags"));
        }
    } else if tag.owner_user_id != Some(user.id()) {
        return Err(forbidden("You can only unassign your own private tags"));
    }

    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let mut removed: Vec<i32> = Vec::new();
    let mut already: Vec<i32> = Vec::new();
    for tid in &requested_ids {
        let ex = tx
            .query_opt(
                "SELECT id FROM tag_assignments WHERE tag_id=$1 AND target_type=$2 AND target_id=$3",
                &[&tag_id, &req.target_type, tid],
            )
            .await
            .map_err(db::query_error)?;
        if ex.is_some() {
            tx.execute(
                "DELETE FROM tag_assignments WHERE tag_id=$1 AND target_type=$2 AND target_id=$3",
                &[&tag_id, &req.target_type, tid],
            )
            .await
            .map_err(db::query_error)?;
            removed.push(*tid);
        } else {
            already.push(*tid);
        }
    }
    tx.commit().await.map_err(db::query_error)?;

    let mut still_inherited: Vec<i32> = Vec::new();
    if req.target_type == "Issue" {
        still_inherited =
            issues_still_inheriting_tag(&conn, user.id(), tag_id, &requested_ids).await?;
    }

    Ok(Json(BulkAssignResponse {
        tag_id,
        target_type: req.target_type,
        requested_ids,
        affected_ids: removed,
        already_ids: already,
        still_inherited_ids: still_inherited,
    }))
}

async fn issues_still_inheriting_tag(
    conn: &deadpool_postgres::Object,
    user_id: i32,
    tag_id: i32,
    issue_ids: &[i32],
) -> Result<Vec<i32>, ApiError> {
    let unique: Vec<i32> = {
        let mut seen = BTreeSet::new();
        let mut out = Vec::new();
        for id in issue_ids {
            if seen.insert(*id) {
                out.push(*id);
            }
        }
        out
    };
    if unique.is_empty() {
        return Ok(vec![]);
    }
    // thread_by_issue
    let mut thread_by_issue: BTreeMap<i32, i32> = BTreeMap::new();
    // build IN list
    let placeholders: Vec<String> = (1..=unique.len()).map(|i| format!("${}", i)).collect();
    let sql = format!(
        "SELECT i.id, i.thread_id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE i.id IN ({}) AND t.user_id = ${}",
        placeholders.join(","),
        unique.len() + 1
    );
    let mut params: Vec<Box<dyn tokio_postgres::types::ToSql + Send + Sync>> = Vec::new();
    for id in &unique {
        params.push(Box::new(*id));
    }
    params.push(Box::new(user_id));
    let param_refs: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = params
        .iter()
        .map(|p| p.as_ref() as &(dyn tokio_postgres::types::ToSql + Sync))
        .collect();
    let rows = conn
        .query(&sql, &param_refs)
        .await
        .map_err(db::query_error)?;
    for row in rows {
        let iid: i32 = row.get(0);
        let tid: i32 = row.get(1);
        thread_by_issue.insert(iid, tid);
    }

    // plans_by_issue
    let mut plans_by_issue: BTreeMap<i32, Vec<i32>> = BTreeMap::new();
    for id in &unique {
        plans_by_issue.insert(*id, vec![]);
    }
    let placeholders2: Vec<String> = (1..=unique.len()).map(|i| format!("${}", i)).collect();
    let sql2 = format!(
        "SELECT rpi.issue_id, cp.id FROM continuity_plans cp JOIN reading_plan_issues rpi ON rpi.plan_id=cp.id WHERE rpi.issue_id IN ({}) AND cp.user_id = ${}",
        placeholders2.join(","),
        unique.len() + 1
    );
    let mut params2: Vec<Box<dyn tokio_postgres::types::ToSql + Send + Sync>> = Vec::new();
    for id in &unique {
        params2.push(Box::new(*id));
    }
    params2.push(Box::new(user_id));
    let param_refs2: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = params2
        .iter()
        .map(|p| p.as_ref() as &(dyn tokio_postgres::types::ToSql + Sync))
        .collect();
    let rows2 = conn
        .query(&sql2, &param_refs2)
        .await
        .map_err(db::query_error)?;
    for row in rows2 {
        let iid: i32 = row.get(0);
        let pid: i32 = row.get(1);
        plans_by_issue.entry(iid).or_default().push(pid);
    }

    // targets
    let mut target_set: BTreeSet<(String, i32)> = BTreeSet::new();
    for tid in thread_by_issue.values() {
        target_set.insert(("Thread".to_string(), *tid));
    }
    let mut plan_ids: BTreeSet<i32> = BTreeSet::new();
    for plans in plans_by_issue.values() {
        for pid in plans {
            plan_ids.insert(*pid);
        }
    }
    for pid in &plan_ids {
        target_set.insert(("ContinuityPlan".to_string(), *pid));
    }
    let targets: Vec<(String, i32)> = target_set.into_iter().collect();

    // holder threads/plans with tag
    let mut holder_threads: BTreeSet<i32> = BTreeSet::new();
    let mut holder_plans: BTreeSet<i32> = BTreeSet::new();
    if !targets.is_empty() {
        // query assignments for these targets with tag_id
        // build condition
        let mut cond_strs: Vec<String> = Vec::new();
        let mut params3: Vec<Box<dyn tokio_postgres::types::ToSql + Send + Sync>> = Vec::new();
        let mut idx = 1;
        for (tt, tid) in &targets {
            cond_strs.push(format!(
                "(target_type = ${} AND target_id = ${})",
                idx,
                idx + 1
            ));
            params3.push(Box::new(tt.clone()));
            params3.push(Box::new(*tid));
            idx += 2;
        }
        let tag_param = idx;
        params3.push(Box::new(tag_id));
        let sql3 = format!(
            "SELECT target_type, target_id FROM tag_assignments WHERE tag_id = ${} AND ({})",
            tag_param,
            cond_strs.join(" OR ")
        );
        let param_refs3: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = params3
            .iter()
            .map(|p| p.as_ref() as &(dyn tokio_postgres::types::ToSql + Sync))
            .collect();
        let rows3 = conn
            .query(&sql3, &param_refs3)
            .await
            .map_err(db::query_error)?;
        for row in rows3 {
            let tt: String = row.get(0);
            let tid: i32 = row.get(1);
            if tt == "Thread" {
                holder_threads.insert(tid);
            } else if tt == "ContinuityPlan" {
                holder_plans.insert(tid);
            }
        }
    }

    let mut still = Vec::new();
    for issue_id in &unique {
        let mut inherited = false;
        if let Some(tid) = thread_by_issue.get(issue_id) {
            if holder_threads.contains(tid) {
                inherited = true;
            }
        }
        if !inherited {
            if let Some(plans) = plans_by_issue.get(issue_id) {
                for pid in plans {
                    if holder_plans.contains(pid) {
                        inherited = true;
                        break;
                    }
                }
            }
        }
        if inherited {
            still.push(*issue_id);
        }
    }
    Ok(still)
}

// ---------------------------------------------------------------------------
// Effective tags handlers
// ---------------------------------------------------------------------------

/// GET /api/v1/tags/effective/issue/{issue_id}/
pub async fn effective_for_issue(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(issue_id): Path<i32>,
) -> Result<Json<EffectiveTagsResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let user_id = user.id();
    // issue owned
    let row = conn
        .query_opt(
            "SELECT i.issue_number, i.thread_id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE i.id=$1 AND t.user_id=$2",
            &[&issue_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let (issue_number, thread_id): (String, i32) = match row {
        Some(r) => (r.get(0), r.get(1)),
        None => return Err(not_found(&format!("Issue {} does not exist", issue_id))),
    };
    // thread owned (already by join)
    let thread_row = conn
        .query_opt(
            "SELECT title FROM threads WHERE id=$1 AND user_id=$2",
            &[&thread_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let thread_title: String = match thread_row {
        Some(r) => r.get(0),
        None => return Err(not_found(&format!("Issue {} does not exist", issue_id))),
    };

    // plans containing issue for user
    let plan_rows = conn
        .query(
            "SELECT cp.id, cp.name FROM continuity_plans cp JOIN reading_plan_issues rpi ON rpi.plan_id=cp.id WHERE rpi.issue_id=$1 AND cp.user_id=$2 ORDER BY cp.id",
            &[&issue_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut plan_names: BTreeMap<i32, String> = BTreeMap::new();
    for r in &plan_rows {
        plan_names.insert(r.get(0), r.get(1));
    }

    let mut targets: Vec<(String, i32)> = vec![
        ("Issue".to_string(), issue_id),
        ("Thread".to_string(), thread_id),
    ];
    for pid in plan_names.keys() {
        targets.push(("ContinuityPlan".to_string(), *pid));
    }

    let assignments = visible_assignments_conn(&conn, user_id, &targets).await?;

    let mut display_names: BTreeMap<(String, i32), String> = BTreeMap::new();
    display_names.insert(
        ("Issue".to_string(), issue_id),
        format!("#{}", issue_number),
    );
    display_names.insert(("Thread".to_string(), thread_id), thread_title.clone());
    for (pid, pname) in &plan_names {
        display_names.insert(("ContinuityPlan".to_string(), *pid), pname.clone());
    }

    let mut rows: Vec<(Tag, String, i32, String)> = Vec::new();
    for (tag, tt, tid) in assignments {
        let dn = display_names
            .get(&(tt.clone(), tid))
            .cloned()
            .unwrap_or_default();
        rows.push((tag, tt, tid, dn));
    }

    let resp = combine_assignments("Issue", issue_id, rows);
    Ok(Json(resp))
}

/// GET /api/v1/tags/effective/thread/{thread_id}/
pub async fn effective_for_thread(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(thread_id): Path<i32>,
) -> Result<Json<EffectiveTagsResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let user_id = user.id();
    let thread_row = conn
        .query_opt(
            "SELECT title FROM threads WHERE id=$1 AND user_id=$2",
            &[&thread_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let thread_title: String = match thread_row {
        Some(r) => r.get(0),
        None => return Err(not_found(&format!("Thread {} does not exist", thread_id))),
    };

    let targets = vec![("Thread".to_string(), thread_id)];
    let assignments = visible_assignments_conn(&conn, user_id, &targets).await?;

    let mut rows: Vec<(Tag, String, i32, String)> = Vec::new();
    for (tag, tt, tid) in assignments {
        rows.push((tag, tt, tid, thread_title.clone()));
    }
    let resp = combine_assignments("Thread", thread_id, rows);
    Ok(Json(resp))
}

/// GET /api/v1/tags/effective/plan/{plan_id}/
pub async fn effective_for_plan(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<EffectiveTagsResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let user_id = user.id();
    let plan_row = conn
        .query_opt(
            "SELECT name FROM continuity_plans WHERE id=$1 AND user_id=$2",
            &[&plan_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let plan_name: String = match plan_row {
        Some(r) => r.get(0),
        None => {
            return Err(not_found(&format!(
                "Reading Plan {} does not exist",
                plan_id
            )))
        }
    };

    let targets = vec![("ContinuityPlan".to_string(), plan_id)];
    let assignments = visible_assignments_conn(&conn, user_id, &targets).await?;

    let mut rows: Vec<(Tag, String, i32, String)> = Vec::new();
    for (tag, tt, tid) in assignments {
        rows.push((tag, tt, tid, plan_name.clone()));
    }
    let resp = combine_assignments("ContinuityPlan", plan_id, rows);
    Ok(Json(resp))
}

/// GET /api/v1/tags/effective/thread/{thread_id}/issues/
pub async fn thread_issues_effective(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(thread_id): Path<i32>,
) -> Result<Json<ThreadIssuesEffectiveTagsResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let user_id = user.id();
    let thread_row = conn
        .query_opt(
            "SELECT title FROM threads WHERE id=$1 AND user_id=$2",
            &[&thread_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let thread_title: String = match thread_row {
        Some(r) => r.get(0),
        None => return Err(not_found(&format!("Thread {} does not exist", thread_id))),
    };

    // issues in thread
    let issue_rows = conn
        .query(
            "SELECT id, issue_number FROM issues WHERE thread_id=$1 ORDER BY position, id",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut issue_ids: Vec<i32> = Vec::new();
    let mut issue_numbers: BTreeMap<i32, String> = BTreeMap::new();
    for r in &issue_rows {
        let iid: i32 = r.get(0);
        let num: String = r.get(1);
        issue_ids.push(iid);
        issue_numbers.insert(iid, num);
    }
    if issue_ids.is_empty() {
        return Ok(Json(ThreadIssuesEffectiveTagsResponse {
            thread_id,
            issues: vec![],
        }));
    }

    // plans containing issues for user
    let mut placeholders: Vec<String> = (1..=issue_ids.len()).map(|i| format!("${}", i)).collect();
    let plan_sql = format!(
        "SELECT rpi.issue_id, cp.id, cp.name FROM continuity_plans cp JOIN reading_plan_issues rpi ON rpi.plan_id=cp.id WHERE rpi.issue_id IN ({}) AND cp.user_id = ${}",
        placeholders.join(","),
        issue_ids.len() + 1
    );
    let mut params: Vec<Box<dyn tokio_postgres::types::ToSql + Send + Sync>> = Vec::new();
    for id in &issue_ids {
        params.push(Box::new(*id));
    }
    params.push(Box::new(user_id));
    let param_refs: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = params
        .iter()
        .map(|p| p.as_ref() as &(dyn tokio_postgres::types::ToSql + Sync))
        .collect();
    let plan_rows = conn
        .query(&plan_sql, &param_refs)
        .await
        .map_err(db::query_error)?;

    let mut plans_by_issue: BTreeMap<i32, Vec<i32>> = BTreeMap::new();
    let mut plan_names: BTreeMap<i32, String> = BTreeMap::new();
    for iid in &issue_ids {
        plans_by_issue.insert(*iid, vec![]);
    }
    for r in &plan_rows {
        let iid: i32 = r.get(0);
        let pid: i32 = r.get(1);
        let pname: String = r.get(2);
        plan_names.insert(pid, pname);
        plans_by_issue.entry(iid).or_default().push(pid);
    }

    // targets
    let mut targets: Vec<(String, i32)> = vec![("Thread".to_string(), thread_id)];
    for iid in &issue_ids {
        targets.push(("Issue".to_string(), *iid));
    }
    for pid in plan_names.keys() {
        targets.push(("ContinuityPlan".to_string(), *pid));
    }
    let assignments = visible_assignments_conn(&conn, user_id, &targets).await?;

    let mut display_names: BTreeMap<(String, i32), String> = BTreeMap::new();
    display_names.insert(("Thread".to_string(), thread_id), thread_title.clone());
    for (iid, num) in &issue_numbers {
        display_names.insert(("Issue".to_string(), *iid), format!("#{}", num));
    }
    for (pid, pname) in &plan_names {
        display_names.insert(("ContinuityPlan".to_string(), *pid), pname.clone());
    }

    let mut all_rows: Vec<(Tag, String, i32, String)> = Vec::new();
    for (tag, tt, tid) in assignments {
        let dn = display_names
            .get(&(tt.clone(), tid))
            .cloned()
            .unwrap_or_default();
        all_rows.push((tag, tt, tid, dn));
    }

    let mut results: Vec<EffectiveTagsResponse> = Vec::new();
    for iid in &issue_ids {
        let plan_ids_for_issue: BTreeSet<i32> = plans_by_issue
            .get(iid)
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .collect();
        let contributing: Vec<(Tag, String, i32, String)> = all_rows
            .iter()
            .filter(|(_, tt, tid, _)| {
                (*tt == "Issue" && *tid == *iid)
                    || (*tt == "Thread" && *tid == thread_id)
                    || (*tt == "ContinuityPlan" && plan_ids_for_issue.contains(tid))
            })
            .cloned()
            .collect();
        results.push(combine_assignments("Issue", *iid, contributing));
    }

    Ok(Json(ThreadIssuesEffectiveTagsResponse {
        thread_id,
        issues: results,
    }))
}

// ---------------------------------------------------------------------------
// Documentation (utoipa)
// ---------------------------------------------------------------------------

// We'll declare documentation functions manually below.

#[utoipa::path(get, path = "/api/v1/tags/", tag = "tags",
    responses((status = 200, description = "ok", body = TagListResponse)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn list_tags_documentation() {}

#[utoipa::path(post, path = "/api/v1/tags/", tag = "tags", request_body = CreateTagRequest,
    responses((status = 200, description = "ok", body = CreateTagResponse)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn create_tag_documentation() {}

#[utoipa::path(get, path = "/api/v1/tags/effective/issue/{issue_id}/", tag = "tags",
    params(("issue_id" = i32, Path, description = "Issue id")),
    responses((status = 200, description = "ok", body = EffectiveTagsResponse)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn effective_issue_documentation() {}

#[utoipa::path(get, path = "/api/v1/tags/effective/plan/{plan_id}/", tag = "tags",
    params(("plan_id" = i32, Path, description = "Plan id")),
    responses((status = 200, description = "ok", body = EffectiveTagsResponse)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn effective_plan_documentation() {}

#[utoipa::path(get, path = "/api/v1/tags/effective/thread/{thread_id}/", tag = "tags",
    params(("thread_id" = i32, Path, description = "Thread id")),
    responses((status = 200, description = "ok", body = EffectiveTagsResponse)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn effective_thread_documentation() {}

#[utoipa::path(get, path = "/api/v1/tags/effective/thread/{thread_id}/issues/", tag = "tags",
    params(("thread_id" = i32, Path, description = "Thread id")),
    responses((status = 200, description = "ok", body = ThreadIssuesEffectiveTagsResponse)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn effective_thread_issues_documentation() {}

#[utoipa::path(get, path = "/api/v1/tags/{tag_id}/", tag = "tags",
    params(("tag_id" = i32, Path, description = "Tag id")),
    responses((status = 200, description = "ok", body = Tag)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn get_tag_documentation() {}

#[utoipa::path(put, path = "/api/v1/tags/{tag_id}/", tag = "tags",
    params(("tag_id" = i32, Path, description = "Tag id")),
    request_body = UpdateTagRequest,
    responses((status = 200, description = "ok", body = Tag)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn update_tag_documentation() {}

#[utoipa::path(delete, path = "/api/v1/tags/{tag_id}/", tag = "tags",
    params(("tag_id" = i32, Path, description = "Tag id")),
    responses((status = 200, description = "ok", body = TagDeleteResponse)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn delete_tag_documentation() {}

#[utoipa::path(post, path = "/api/v1/tags/{tag_id}/assign/", tag = "tags",
    params(("tag_id" = i32, Path, description = "Tag id")),
    request_body = AssignTagRequest,
    responses((status = 200, description = "ok", body = TagAssignmentResponse)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn assign_tag_documentation() {}

#[utoipa::path(post, path = "/api/v1/tags/{tag_id}/bulk-assign/", tag = "tags",
    params(("tag_id" = i32, Path, description = "Tag id")),
    request_body = BulkAssignRequest,
    responses((status = 200, description = "ok", body = BulkAssignResponse)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn bulk_assign_tag_documentation() {}

#[utoipa::path(post, path = "/api/v1/tags/{tag_id}/bulk-unassign/", tag = "tags",
    params(("tag_id" = i32, Path, description = "Tag id")),
    request_body = BulkAssignRequest,
    responses((status = 200, description = "ok", body = BulkAssignResponse)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn bulk_unassign_tag_documentation() {}

#[utoipa::path(delete, path = "/api/v1/tags/{tag_id}/unassign/", tag = "tags",
    params(("tag_id" = i32, Path, description = "Tag id")),
    request_body = AssignTagRequest,
    responses((status = 200, description = "ok", body = TagAssignmentResponse)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn unassign_tag_documentation() {}

#[utoipa::path(get, path = "/api/v1/tags/{tag_id}/usage/", tag = "tags",
    params(("tag_id" = i32, Path, description = "Tag id")),
    responses((status = 200, description = "ok", body = TagUsageResponse)),
    security(("HTTPBearer" = [])))]
#[allow(dead_code)]
pub fn usage_tag_documentation() {}

#[cfg(test)]
mod tests {}
