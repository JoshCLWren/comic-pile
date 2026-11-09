use crate::{
    auth::VerifiedAccessClaims,
    db::{checkout, query_error},
    ApiError, AppState,
};
use axum::{
    extract::{Query, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet, HashMap, HashSet},
    sync::Arc,
};
use utoipa::{IntoParams, ToSchema};

const MAX_CREATOR_KEYS: usize = 50;
const HEADLINE_ROLES: &[&str] = &[
    "writer", "artist", "penciler", "inker", "colorist", "letterer",
];
const MANUAL_CREATOR_ID_BASE: i64 = 1_000_000_000;

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorSummaryCoverage {
    pub rated_issues_total: i64,
    pub rated_issues_with_creator_metadata: i64,
    pub ratings_complete: bool,
    pub read_unrated_issues_total: i64,
    pub read_unrated_issues_with_creator_metadata: i64,
    pub read_unrated_complete: bool,
    pub unread_issues_total: i64,
    pub unread_issues_with_creator_metadata: i64,
    pub upcoming_complete: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorSummaryItem {
    pub canonical_creator_key: String,
    pub display_name: String,
    pub normalized_roles: Vec<String>,
    pub average_rating: Option<f64>,
    pub ratings_count: i64,
    pub read_unrated_count: i64,
    pub upcoming_count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorSummariesResponse {
    pub summaries: BTreeMap<String, CreatorSummaryItem>,
    pub coverage: CreatorSummaryCoverage,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorListItem {
    pub canonical_creator_key: String,
    pub display_name: String,
    pub normalized_roles: Vec<String>,
    pub average_rating: Option<f64>,
    pub ratings_count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct CreatorListResponse {
    pub items: Vec<CreatorListItem>,
    pub total: i64,
    pub limit: i64,
    pub offset: i64,
    pub coverage: CreatorSummaryCoverage,
}

#[derive(Debug, Deserialize, IntoParams)]
pub struct SummariesQuery {
    pub keys: Option<String>,
}

#[derive(Debug, Deserialize, IntoParams)]
pub struct CreatorListQuery {
    pub search: Option<String>,
    pub sort: Option<String>,
    pub limit: Option<i64>,
    pub offset: Option<i64>,
    pub min_ratings: Option<i64>,
}

fn bad_request(msg: impl Into<String>) -> ApiError {
    ApiError(StatusCode::BAD_REQUEST, msg.into())
}

fn parse_creator_key(key: &str) -> Option<i64> {
    let parts: Vec<&str> = key.split(':').collect();
    if parts.len() == 2
        && parts[0] == "creator"
        && parts[1].chars().all(|c| c.is_ascii_digit())
        && !parts[1].is_empty()
    {
        parts[1].parse().ok()
    } else {
        None
    }
}

fn split_keys(raw: &str) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for part in raw.split(',') {
        let k = part.trim();
        if !k.is_empty() && seen.insert(k.to_string()) {
            out.push(k.to_string());
        }
    }
    out
}

fn validate_creator_keys(raw: Option<&str>) -> Result<Vec<String>, ApiError> {
    let raw = raw
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| {
            bad_request("keys must be a non-empty comma-separated list of creator keys")
        })?;
    let keys = split_keys(raw);
    if keys.is_empty() {
        return Err(bad_request(
            "keys must be a non-empty comma-separated list of creator keys",
        ));
    }
    if keys.len() > MAX_CREATOR_KEYS {
        return Err(bad_request(format!(
            "keys may list at most {MAX_CREATOR_KEYS} creators per request"
        )));
    }
    for key in &keys {
        let parts: Vec<&str> = key.split(':').collect();
        let valid = parts.len() == 2
            && parts[0] == "creator"
            && !parts[1].is_empty()
            && parts[1].chars().all(|c| c.is_ascii_digit());
        if !valid {
            return Err(bad_request(format!(
                "Invalid creator key {key:?}: expected creator:<external-person-id> (stable ComicVine person id, no display names)"
            )));
        }
    }
    Ok(keys)
}

fn headline_role(role: &str) -> bool {
    HEADLINE_ROLES.contains(&role)
}

#[derive(Debug, Clone)]
struct CreatorCredit {
    external_id: i64,
    roles: Vec<String>,
    display_name: String,
}

fn normalize_manual_role(role: &str) -> Option<String> {
    let normalized = role
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase();
    if normalized.is_empty() {
        return None;
    }
    let mapped = match normalized.as_str() {
        "cover artist" => "cover",
        "penciller" => "penciler",
        _ => normalized.as_str(),
    };
    Some(mapped.to_string())
}

fn manual_creator_id(name: &str) -> i64 {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(name.as_bytes());
    let digest = hasher.finalize();
    // take first 16 hex chars worth? Python does int(hexdigest, 16) % MANUAL_CREATOR_ID_BASE
    // we need big int mod; easier to use the lower 64 bits carefully
    let mut val: u128 = 0;
    for b in digest.iter().take(16) {
        // 128 bits
        val = (val << 8) | (*b as u128);
    }
    // but Python uses full 256-bit hex digest mod base; to be safe, use u64 chunks?
    // Actually: int(hexdigest, 16) is a big int; % MANUAL_CREATOR_ID_BASE (10^9) can be computed
    // by processing hex in chunks. Easier: use decimal string approach via big integer logic is not in std.
    // Alternative: compute mod stepwise over the digest bytes.
    let mut acc: u64 = 0;
    let base = MANUAL_CREATOR_ID_BASE as u64;
    // process full 32 bytes as a big-endian number mod base
    let hex = format!("{digest:x}");
    // hex is 64 chars
    for ch in hex.chars() {
        let digit = ch.to_digit(16).unwrap() as u64;
        acc = (acc * 16 + digit) % base;
    }
    MANUAL_CREATOR_ID_BASE + acc as i64
}

fn extract_manual_creator_credits(manual_credits: &Value) -> Vec<CreatorCredit> {
    let arr = match manual_credits.as_array() {
        Some(a) => a,
        None => return vec![],
    };
    let mut credits = Vec::new();
    let mut seen: HashSet<(i64, Vec<String>)> = HashSet::new();
    for item in arr {
        let obj = match item.as_object() {
            Some(o) => o,
            None => continue,
        };
        let name = match obj.get("name").and_then(|v| v.as_str()) {
            Some(n) if !n.trim().is_empty() => n,
            _ => continue,
        };
        let normalized_name = name.split_whitespace().collect::<Vec<_>>().join(" ");
        let roles_raw: Vec<String> = match obj.get("roles") {
            Some(Value::Array(a)) => a
                .iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect(),
            Some(Value::String(s)) => s.split(',').map(|s| s.to_string()).collect(),
            _ => vec![],
        };
        let mut role_set: BTreeSet<String> = BTreeSet::new();
        for r in roles_raw {
            if let Some(nr) = normalize_manual_role(&r) {
                role_set.insert(nr);
            }
        }
        let roles: Vec<String> = role_set.into_iter().collect();
        let synthetic_id = manual_creator_id(&normalized_name);
        let key = (synthetic_id, roles.clone());
        if seen.contains(&key) {
            continue;
        }
        seen.insert(key);
        credits.push(CreatorCredit {
            external_id: synthetic_id,
            roles,
            display_name: normalized_name,
        });
    }
    credits
}

fn coerce_creator_id(v: &Value) -> Option<i64> {
    if let Some(i) = v.as_i64() {
        return Some(i);
    }
    if let Some(u) = v.as_u64() {
        return Some(u as i64);
    }
    if let Some(s) = v.as_str() {
        if !s.is_empty() && s.chars().all(|c| c.is_ascii_digit()) {
            return s.parse().ok();
        }
    }
    None
}

fn extract_creator_credit_list(raw: &Value) -> Vec<CreatorCredit> {
    let arr = match raw.as_array() {
        Some(a) => a,
        None => return vec![],
    };
    let mut credits = Vec::new();
    let mut seen: HashSet<(i64, Vec<String>)> = HashSet::new();
    for item in arr {
        let obj = match item.as_object() {
            Some(o) => o,
            None => continue,
        };
        let creator_id = match obj.get("id").and_then(coerce_creator_id) {
            Some(id) => id,
            None => continue,
        };
        let name = match obj.get("name").and_then(|v| v.as_str()) {
            Some(n) if !n.trim().is_empty() => n.trim().to_string(),
            _ => continue,
        };
        let roles: Vec<String> = match obj.get("role") {
            Some(Value::Null) | None => vec![],
            Some(v) => {
                let s = match v {
                    Value::String(s) => s.clone(),
                    other => other.to_string().trim_matches('"').to_string(),
                };
                let mut set: BTreeSet<String> = BTreeSet::new();
                for part in s.split(',') {
                    let p = part.trim();
                    if !p.is_empty() {
                        set.insert(p.to_string());
                    }
                }
                set.into_iter().collect()
            }
        };
        let key = (creator_id, roles.clone());
        if seen.contains(&key) {
            continue;
        }
        seen.insert(key);
        credits.push(CreatorCredit {
            external_id: creator_id,
            roles,
            display_name: name,
        });
    }
    credits
}

async fn resolve_user_id(state: &AppState, claims: &VerifiedAccessClaims) -> Result<i32, ApiError> {
    let username = claims.username().to_string();
    let jti = claims.jti().to_string();
    let expected_epoch = claims.expected_epoch().unwrap_or(i64::MAX);
    let conn = checkout(state).await?;
    let row = crate::db::query_one_optional(
        state,
        conn,
        "WITH auth AS (
            SELECT u.id AS user_id,
                   COALESCE(trunc(extract(epoch FROM u.password_changed_at))::bigint, 0) AS password_epoch,
                   EXISTS(SELECT 1 FROM revoked_tokens r WHERE r.jti = $2) AS revoked
            FROM users u WHERE u.username = $1 LIMIT 1
         )
         SELECT user_id, password_epoch, revoked FROM auth",
        &[&username, &jti],
    ).await?;
    let row =
        row.ok_or_else(|| ApiError(StatusCode::UNAUTHORIZED, "User not found".to_string()))?;
    let user_id: i32 = row.get(0);
    let epoch: i64 = row.get(1);
    let revoked: bool = row.get(2);
    if revoked {
        return Err(ApiError(
            StatusCode::UNAUTHORIZED,
            "Token has been revoked".to_string(),
        ));
    }
    if expected_epoch < epoch {
        return Err(ApiError(
            StatusCode::UNAUTHORIZED,
            "Password changed; please sign in again.".to_string(),
        ));
    }
    Ok(user_id)
}

struct SummaryInputs {
    owned_issues: HashMap<i32, String>, // issue_id -> status
    issue_creator_credits: HashMap<i32, Vec<CreatorCredit>>,
    issues_with_creator_metadata: HashSet<i32>,
    effective_ratings: HashMap<i32, f64>,
}

async fn load_full_inputs(state: &AppState, user_id: i32) -> Result<SummaryInputs, ApiError> {
    let conn = checkout(state).await?;
    // 1. owned issues
    let rows = conn
        .query(
            "SELECT i.id, i.status, i.thread_id, i.issue_number
         FROM issues i JOIN threads t ON t.id = i.thread_id
         WHERE t.user_id = $1",
            &[&user_id],
        )
        .await
        .map_err(query_error)?;
    let mut owned_issues = HashMap::new();
    let mut issue_thread_ids: HashMap<i32, i32> = HashMap::new();
    let mut thread_ids: HashSet<i32> = HashSet::new();
    for row in &rows {
        let id: i32 = row.get(0);
        let status: String = row.get(1);
        let thread_id: i32 = row.get(2);
        owned_issues.insert(id, status);
        issue_thread_ids.insert(id, thread_id);
        thread_ids.insert(thread_id);
    }
    // 2. thread titles and manual credits
    let mut thread_manual: HashMap<i32, Value> = HashMap::new();
    if !thread_ids.is_empty() {
        let rows = conn
            .query(
                "SELECT id, title, manual_creator_credits::text FROM threads WHERE user_id = $1",
                &[&user_id],
            )
            .await
            .map_err(query_error)?;
        for row in &rows {
            let tid: i32 = row.get(0);
            let mc: Option<String> = row.try_get(2).ok();
            if let Some(text) = mc {
                if let Ok(v) = serde_json::from_str::<Value>(&text) {
                    if !v.is_null() {
                        thread_manual.insert(tid, v);
                    }
                }
            }
        }
    }
    // 3. confirmed ComicVine creator credits (projected)
    let rows = conn
        .query(
            "SELECT i.id, e.metadata_json->'creator_credits'
         FROM issues i
         JOIN threads t ON t.id = i.thread_id
         JOIN issue_external_identity_mappings m ON m.issue_id = i.id
         JOIN external_identities e ON e.id = m.external_identity_id
         WHERE t.user_id = $1 AND m.status = 'confirmed' AND e.provider = 'comicvine'",
            &[&user_id],
        )
        .await
        .map_err(query_error)?;
    let mut per_issue: HashMap<i32, BTreeMap<(i64, Vec<String>), CreatorCredit>> = HashMap::new();
    let mut issues_with_creator_metadata: HashSet<i32> = HashSet::new();
    for row in &rows {
        let iid: i32 = row.get(0);
        let raw_text: Option<String> = row.try_get(1).ok();
        let credits = raw_text
            .as_deref()
            .and_then(|t| serde_json::from_str::<Value>(t).ok())
            .as_ref()
            .map(extract_creator_credit_list)
            .unwrap_or_default();
        if !credits.is_empty() {
            issues_with_creator_metadata.insert(iid);
        }
        let by_key = per_issue.entry(iid).or_default();
        for c in credits {
            by_key.entry((c.external_id, c.roles.clone())).or_insert(c);
        }
    }
    // 4. manual credits for issues without ComicVine metadata
    for (iid, tid) in &issue_thread_ids {
        if issues_with_creator_metadata.contains(iid) {
            continue;
        }
        if let Some(mc) = thread_manual.get(tid) {
            let credits = extract_manual_creator_credits(mc);
            if !credits.is_empty() {
                issues_with_creator_metadata.insert(*iid);
                let by_key = per_issue.entry(*iid).or_default();
                for c in credits {
                    by_key.entry((c.external_id, c.roles.clone())).or_insert(c);
                }
            }
        }
    }
    let mut issue_creator_credits: HashMap<i32, Vec<CreatorCredit>> = HashMap::new();
    for (iid, by_key) in per_issue {
        let mut v: Vec<CreatorCredit> = by_key.into_values().collect();
        v.sort_by(|a, b| {
            a.external_id
                .cmp(&b.external_id)
                .then(a.roles.cmp(&b.roles))
        });
        issue_creator_credits.insert(iid, v);
    }
    // 5. latest effective ratings
    let rows = conn.query(
        "SELECT DISTINCT ON (ev.issue_id) ev.issue_id, ev.rating
         FROM events ev
         JOIN issues i ON i.id = ev.issue_id
         JOIN threads t ON t.id = i.thread_id
         WHERE t.user_id = $1 AND ev.type = 'rate' AND ev.issue_id IS NOT NULL AND ev.rating IS NOT NULL
         ORDER BY ev.issue_id, ev.timestamp DESC, ev.id DESC",
        &[&user_id],
    ).await.map_err(query_error)?;
    let mut effective_ratings = HashMap::new();
    for row in &rows {
        let iid: Option<i32> = row.get(0);
        let rating: Option<f64> = row
            .try_get::<_, f64>(1)
            .ok()
            .or_else(|| row.try_get::<_, f32>(1).ok().map(|f| f as f64));
        if let (Some(iid), Some(r)) = (iid, rating) {
            effective_ratings.insert(iid, r);
        }
    }
    Ok(SummaryInputs {
        owned_issues,
        issue_creator_credits,
        issues_with_creator_metadata,
        effective_ratings,
    })
}

fn build_coverage(inputs: &SummaryInputs) -> CreatorSummaryCoverage {
    let rated_ids: HashSet<i32> = inputs.effective_ratings.keys().copied().collect();
    let mut read_unrated_ids = HashSet::new();
    let mut unread_ids = HashSet::new();
    for (iid, status) in &inputs.owned_issues {
        if status == "read" && !inputs.effective_ratings.contains_key(iid) {
            read_unrated_ids.insert(*iid);
        } else if status == "unread" {
            unread_ids.insert(*iid);
        }
    }
    let with_meta = |ids: &HashSet<i32>| {
        ids.iter()
            .filter(|id| inputs.issues_with_creator_metadata.contains(id))
            .count() as i64
    };
    let rated_total = rated_ids.len() as i64;
    let rated_with = with_meta(&rated_ids);
    let read_total = read_unrated_ids.len() as i64;
    let read_with = with_meta(&read_unrated_ids);
    let unread_total = unread_ids.len() as i64;
    let unread_with = with_meta(&unread_ids);
    CreatorSummaryCoverage {
        rated_issues_total: rated_total,
        rated_issues_with_creator_metadata: rated_with,
        ratings_complete: rated_with >= rated_total,
        read_unrated_issues_total: read_total,
        read_unrated_issues_with_creator_metadata: read_with,
        read_unrated_complete: read_with >= read_total,
        unread_issues_total: unread_total,
        unread_issues_with_creator_metadata: unread_with,
        upcoming_complete: unread_with >= unread_total,
    }
}

pub async fn get_summaries(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    Query(q): Query<SummariesQuery>,
) -> Result<Json<CreatorSummariesResponse>, ApiError> {
    let keys = validate_creator_keys(q.keys.as_deref())?;
    let user_id = resolve_user_id(&state, &claims).await?;
    let mut requested_id_map: BTreeMap<String, i64> = BTreeMap::new();
    let mut requested_ids: HashSet<i64> = HashSet::new();
    for key in &keys {
        if let Some(id) = parse_creator_key(key) {
            requested_id_map.insert(key.clone(), id);
            requested_ids.insert(id);
        }
    }
    let inputs = load_full_inputs(&state, user_id).await?;
    let coverage = build_coverage(&inputs);
    // build per-creator aggregates
    let mut creator_issues: HashMap<i64, HashSet<i32>> = HashMap::new();
    let mut creator_headline_issues: HashMap<i64, HashSet<i32>> = HashMap::new();
    let mut creator_roles: HashMap<i64, BTreeSet<String>> = HashMap::new();
    let mut creator_names: HashMap<i64, String> = HashMap::new();
    for (iid, credits) in &inputs.issue_creator_credits {
        for c in credits {
            if !requested_ids.contains(&c.external_id) {
                continue;
            }
            creator_issues
                .entry(c.external_id)
                .or_default()
                .insert(*iid);
            creator_names
                .entry(c.external_id)
                .or_insert_with(|| c.display_name.clone());
            let roles = creator_roles.entry(c.external_id).or_default();
            for r in &c.roles {
                roles.insert(r.clone());
            }
            if c.roles.iter().any(|r| headline_role(r)) {
                creator_headline_issues
                    .entry(c.external_id)
                    .or_default()
                    .insert(*iid);
            }
        }
    }
    let mut summaries = BTreeMap::new();
    for (key, cid) in &requested_id_map {
        let Some(issue_ids) = creator_issues.get(cid) else {
            continue;
        };
        let headline = creator_headline_issues.get(cid);
        let mut ratings: Vec<f64> = Vec::new();
        for iid in issue_ids {
            let is_headline = headline.map(|h| h.contains(iid)).unwrap_or(false);
            if is_headline {
                if let Some(r) = inputs.effective_ratings.get(iid) {
                    ratings.push(*r);
                }
            }
        }
        let ratings_count = ratings.len() as i64;
        let average_rating = if ratings_count > 0 {
            let avg = ratings.iter().sum::<f64>() / ratings_count as f64;
            Some((avg * 100.0).round() / 100.0)
        } else {
            None
        };
        let read_unrated_count = issue_ids
            .iter()
            .filter(|iid| {
                inputs
                    .owned_issues
                    .get(*iid)
                    .map(|s| s == "read")
                    .unwrap_or(false)
                    && !inputs.effective_ratings.contains_key(*iid)
            })
            .count() as i64;
        let upcoming_count = issue_ids
            .iter()
            .filter(|iid| {
                inputs
                    .owned_issues
                    .get(*iid)
                    .map(|s| s == "unread")
                    .unwrap_or(false)
            })
            .count() as i64;
        let roles: Vec<String> = creator_roles
            .get(cid)
            .map(|s| s.iter().cloned().collect())
            .unwrap_or_default();
        summaries.insert(
            key.clone(),
            CreatorSummaryItem {
                canonical_creator_key: key.clone(),
                display_name: creator_names.get(cid).cloned().unwrap_or_default(),
                normalized_roles: roles,
                average_rating,
                ratings_count,
                read_unrated_count,
                upcoming_count,
            },
        );
    }
    Ok(Json(CreatorSummariesResponse {
        summaries,
        coverage,
    }))
}

pub async fn list_creators(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    Query(q): Query<CreatorListQuery>,
) -> Result<Json<CreatorListResponse>, ApiError> {
    let user_id = resolve_user_id(&state, &claims).await?;
    let search = q
        .search
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(|s| {
            if s.len() > 100 {
                s[..100].to_string()
            } else {
                s.to_string()
            }
        });
    let sort = q.sort.as_deref().unwrap_or("name").to_string();
    if !["name", "ratings_count", "average_rating"].contains(&sort.as_str()) {
        // FastAPI/Pydantic would 422, but preserve reasonable behavior; Python validates via Literal
    }
    let limit = q.limit.unwrap_or(20).clamp(1, 50);
    let offset = q.offset.unwrap_or(0).max(0);
    let min_ratings = q.min_ratings.unwrap_or(0).max(0);
    let inputs = load_full_inputs(&state, user_id).await?;
    let coverage = build_coverage(&inputs);
    // aggregate per creator (all)
    let mut creator_issues: HashMap<i64, HashSet<i32>> = HashMap::new();
    let mut creator_headline_issues: HashMap<i64, HashSet<i32>> = HashMap::new();
    let mut creator_roles: HashMap<i64, BTreeSet<String>> = HashMap::new();
    let mut creator_names: HashMap<i64, String> = HashMap::new();
    for (iid, credits) in &inputs.issue_creator_credits {
        for c in credits {
            creator_issues
                .entry(c.external_id)
                .or_default()
                .insert(*iid);
            creator_names
                .entry(c.external_id)
                .or_insert_with(|| c.display_name.clone());
            let roles = creator_roles.entry(c.external_id).or_default();
            for r in &c.roles {
                roles.insert(r.clone());
            }
            if c.roles.iter().any(|r| headline_role(r)) {
                creator_headline_issues
                    .entry(c.external_id)
                    .or_default()
                    .insert(*iid);
            }
        }
    }
    let mut items: Vec<CreatorListItem> = Vec::new();
    for (cid, issue_ids) in &creator_issues {
        let headline = creator_headline_issues.get(cid);
        let mut headline_rated: Vec<f64> = Vec::new();
        for iid in issue_ids {
            let is_headline = headline.map(|h| h.contains(iid)).unwrap_or(false);
            if is_headline {
                if let Some(r) = inputs.effective_ratings.get(iid) {
                    headline_rated.push(*r);
                }
            }
        }
        let ratings_count = headline_rated.len() as i64;
        if ratings_count == 0 {
            continue;
        }
        if ratings_count < min_ratings {
            continue;
        }
        let average_rating = if ratings_count > 0 {
            Some(
                (headline_rated.iter().sum::<f64>() / ratings_count as f64 * 100.0).round() / 100.0,
            )
        } else {
            None
        };
        let display_name = creator_names.get(cid).cloned().unwrap_or_default();
        if let Some(ref s) = search {
            if !display_name.to_lowercase().contains(&s.to_lowercase()) {
                continue;
            }
        }
        let roles: Vec<String> = creator_roles
            .get(cid)
            .map(|s| s.iter().cloned().collect())
            .unwrap_or_default();
        items.push(CreatorListItem {
            canonical_creator_key: format!("creator:{cid}"),
            display_name,
            normalized_roles: roles,
            average_rating,
            ratings_count,
        });
    }
    // sort
    match sort.as_str() {
        "ratings_count" => {
            items.sort_by(|a, b| {
                b.ratings_count
                    .cmp(&a.ratings_count)
                    .then_with(|| {
                        a.display_name
                            .to_lowercase()
                            .cmp(&b.display_name.to_lowercase())
                    })
                    .then_with(|| a.canonical_creator_key.cmp(&b.canonical_creator_key))
            });
        }
        "average_rating" => {
            items.sort_by(|a, b| {
                let an = a.average_rating.is_none();
                let bn = b.average_rating.is_none();
                // nulls last
                (an as u8)
                    .cmp(&(bn as u8))
                    .then_with(|| {
                        let aa = a.average_rating.unwrap_or(0.0);
                        let ba = b.average_rating.unwrap_or(0.0);
                        ba.partial_cmp(&aa).unwrap_or(std::cmp::Ordering::Equal)
                    })
                    .then_with(|| b.ratings_count.cmp(&a.ratings_count))
                    .then_with(|| {
                        a.display_name
                            .to_lowercase()
                            .cmp(&b.display_name.to_lowercase())
                    })
                    .then_with(|| a.canonical_creator_key.cmp(&b.canonical_creator_key))
            });
        }
        _ => {
            items.sort_by(|a, b| {
                a.display_name
                    .to_lowercase()
                    .cmp(&b.display_name.to_lowercase())
                    .then_with(|| a.canonical_creator_key.cmp(&b.canonical_creator_key))
            });
        }
    }
    let total = items.len() as i64;
    let start = offset as usize;
    let end = (start + limit as usize).min(items.len());
    let paged = if start >= items.len() {
        vec![]
    } else {
        items[start..end].to_vec()
    };
    Ok(Json(CreatorListResponse {
        items: paged,
        total,
        limit,
        offset,
        coverage,
    }))
}
