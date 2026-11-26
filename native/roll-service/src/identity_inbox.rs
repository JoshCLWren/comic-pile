//! Owner-scoped identity reconciliation inbox.
//!
//! Rust replacement for the Python `/api/v2/identity-inbox/*` routes. The HTTP
//! method and exact path are preserved; only the implementation moves.

use crate::{
    auth::AuthenticatedUser,
    db,
    outbound::{OutboundHttp, OutboundRequest},
    ApiError, AppState,
};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use bytes::Bytes;
use http_body_util::BodyExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;
use std::time::Duration;

#[derive(Debug, Deserialize)]
pub struct ListQuery {
    pub offset: Option<i64>,
    pub limit: Option<i64>,
}

#[derive(Debug, Deserialize)]
pub struct SearchQuery {
    pub q: String,
    pub limit: Option<i64>,
    pub issue_id: Option<i32>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ActionRequest {
    pub external_identity_id: Option<i32>,
    pub rejection_reason: Option<String>,
    pub search_query: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxCandidate {
    pub external_identity_id: i32,
    pub provider: String,
    pub comicvine_id: Option<String>,
    pub external_url: Option<String>,
    pub metadata_json: Value,
    pub status: String,
    pub confidence: Option<f64>,
    pub evidence_source: Option<String>,
    pub evidence_json: Value,
    pub rejection_reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxItem {
    pub mapping_id: i32,
    pub issue_id: i32,
    pub thread_id: i32,
    pub thread_title: String,
    pub issue_number: String,
    pub status: String,
    pub provider: Option<String>,
    pub source_entry_summary: String,
    pub why_stopped: String,
    /// Actionable next steps for the reviewer when the match is unresolved,
    /// ambiguous, or missing. Empty when no guidance is needed.
    #[serde(default)]
    pub next_steps: Vec<String>,
    pub candidates: Vec<IdentityInboxCandidate>,
    pub created_at: Option<f64>,
    pub updated_at: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxResponse {
    pub items: Vec<IdentityInboxItem>,
    pub total: i64,
    pub offset: i64,
    pub limit: i64,
}

// OpenAPI-only body schema: `confirm` deserializes the shared `ActionRequest`
// and answers 400 when `external_identity_id` is missing.
/// Body for confirming an identity inbox candidate.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxConfirmRequest {
    pub external_identity_id: i32,
}

// OpenAPI-only body schema: `reject` answers 400 when `external_identity_id`
// is missing or `rejection_reason` is missing or blank.
/// Body for rejecting an identity inbox candidate.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxRejectRequest {
    pub external_identity_id: i32,
    #[schema(min_length = 1, pattern = r"\S")]
    pub rejection_reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxActionRequest {
    pub external_identity_id: Option<i32>,
    pub rejection_reason: Option<String>,
    pub search_query: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxActionResponse {
    pub success: bool,
    pub message: String,
    pub updated_item: Option<IdentityInboxItem>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxSearchResult {
    pub comicvine_issue_id: i32,
    pub comicvine_volume_id: Option<i32>,
    pub volume_name: Option<String>,
    pub issue_number: Option<String>,
    pub issue_name: Option<String>,
    pub publisher: Option<String>,
    pub start_year: Option<i32>,
    pub site_detail_url: Option<String>,
    pub image_url: Option<String>,
    pub score: Option<f64>,
    pub evidence: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct IdentityInboxSearchResponse {
    pub issue_id: i32,
    pub query: String,
    pub results: Vec<IdentityInboxSearchResult>,
    pub total_available: Option<i64>,
}

fn bad_request(detail: &str) -> ApiError {
    ApiError::with_status(StatusCode::BAD_REQUEST, detail.to_string())
}

fn not_found(detail: &str) -> ApiError {
    ApiError::with_status(StatusCode::NOT_FOUND, detail.to_string())
}

fn unprocessable(detail: &str) -> ApiError {
    ApiError::with_status(StatusCode::UNPROCESSABLE_ENTITY, detail.to_string())
}

fn source_entry_summary(thread_title: &str, issue_number: &str, metadata: &Value) -> String {
    let mut parts = vec![format!("{} #{}", thread_title, issue_number)];
    if let Some(volume) = metadata.get("volume").and_then(|v| v.as_object()) {
        if let Some(name) = volume.get("name").and_then(|v| v.as_str()) {
            if !name.is_empty() {
                parts.push(format!("({name})"));
            }
        }
    }
    if let Some(publisher) = metadata.get("publisher").and_then(|v| v.as_str()) {
        if !publisher.is_empty() {
            parts.push(format!("- {publisher}"));
        }
    }
    parts.join(" ")
}

fn why_stopped(status: &str, evidence: &Value, candidate_count: usize) -> String {
    // The collapsed inbox header renders this string. The list endpoint now
    // batch-loads real candidates, so an evidence/status-only reason can
    // contradict the candidate cards shown on expand (#5382). Reflect the real
    // candidate state first. When candidates exist, keep any non-empty
    // decision_reason so the header still explains why review is needed; only
    // the empty-evidence fallback is replaced by the count.
    if candidate_count > 0 {
        let count_text = if candidate_count == 1 {
            "1 candidate found".to_string()
        } else {
            format!("{candidate_count} candidates found")
        };
        if let Some(obj) = evidence.as_object() {
            if let Some(reason) = obj.get("decision_reason").and_then(|v| v.as_str()) {
                if !reason.is_empty() {
                    return format!("{count_text}: {reason}");
                }
            }
        }
        return count_text;
    }
    let is_empty_evidence = evidence.is_null()
        || evidence.as_object().map(|o| o.is_empty()).unwrap_or(false)
        || evidence.as_array().map(|a| a.is_empty()).unwrap_or(false);
    if let Some(obj) = evidence.as_object() {
        if let Some(reason) = obj.get("decision_reason").and_then(|v| v.as_str()) {
            if !reason.is_empty() {
                return reason.to_string();
            }
        }
    }
    if is_empty_evidence {
        return "No candidates found. Try searching by a different name, pasting a ComicVine URL, or mapping manually.".to_string();
    }
    if status == "unresolved" {
        return "No validated local candidate. Try searching by a different name, pasting a ComicVine URL, or mapping manually.".to_string();
    }
    if status == "candidate" {
        return "Multiple candidates require explicit review. Confirm the correct match or map manually.".to_string();
    }
    format!("Status: {status}")
}

fn next_steps_for(status: &str, evidence: &Value, candidate_count: usize) -> Vec<String> {
    if let Some(obj) = evidence.as_object() {
        if let Some(steps) = obj.get("next_steps").and_then(|v| v.as_array()) {
            let parsed: Vec<String> = steps
                .iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .filter(|s| !s.trim().is_empty())
                .collect();
            if !parsed.is_empty() {
                return parsed;
            }
        }
    }
    if candidate_count > 0 {
        if status == "candidate" || status == "unresolved" || status == "deferred" {
            return vec![
                "Confirm the correct candidate if one matches exactly.".to_string(),
                "Search by a different name or paste a ComicVine URL.".to_string(),
                "Map manually if no candidate is correct.".to_string(),
            ];
        }
        return Vec::new();
    }
    vec![
        "Search by a different series name or alias.".to_string(),
        "Paste a ComicVine volume or issue URL.".to_string(),
        "Map the issue manually in the Identity Inbox.".to_string(),
    ]
}

fn parse_json_text(text: Option<String>) -> Value {
    text.and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_else(|| serde_json::json!({}))
}

/// Local discovery context for #5434, assembled from data the app already
/// owns. No provider I/O here: these are the hints that make provider searches
/// find volumes even when the local series name differs from ComicVine's.
#[derive(Debug)]
struct MatchContext {
    issue: crate::comicvine_matching::MatchIssue,
}

impl MatchContext {
    fn new(issue_id: i32, thread_title: &str, issue_number: &str) -> Self {
        Self {
            issue: crate::comicvine_matching::MatchIssue {
                issue_id,
                series_name: thread_title.to_string(),
                issue_number: issue_number.to_string(),
                publisher: None,
                start_year: None,
                volume_hint_ids: Vec::new(),
                aliases: Vec::new(),
                source_volume_ids: Vec::new(),
            },
        }
    }

    fn apply_series_hint(&mut self, publisher: Option<String>, start_year: Option<i32>, volume_id: Option<i32>, alias: Option<String>) {
        if self.issue.publisher.is_none() {
            self.issue.publisher = publisher;
        }
        if self.issue.start_year.is_none() {
            self.issue.start_year = start_year;
        }
        if let Some(id) = volume_id {
            if !self.issue.source_volume_ids.contains(&id) {
                self.issue.source_volume_ids.push(id);
            }
        }
        if let Some(name) = alias {
            if !name.trim().is_empty() && !self.issue.aliases.contains(&name) {
                self.issue.aliases.push(name);
            }
        }
    }

    fn finish(mut self) -> crate::comicvine_matching::MatchIssue {
        self.issue.volume_hint_ids.sort_unstable();
        self.issue.volume_hint_ids.dedup();
        self.issue.source_volume_ids.sort_unstable();
        self.issue.source_volume_ids.dedup();
        self.issue.aliases.sort();
        self.issue.aliases.dedup();
        self.issue
    }
}

/// Load the discovery hints for one issue with three bounded, set-based
/// queries (sibling volumes, confirmed series hints, CBL source labels).
async fn load_match_context(
    conn: &deadpool_postgres::Object,
    thread_id: i32,
    issue_id: i32,
    thread_title: &str,
    issue_number: &str,
) -> Result<crate::comicvine_matching::MatchIssue, ApiError> {
    let mut context = MatchContext::new(issue_id, thread_title, issue_number);

    let sibling_rows = conn
        .query(
            "SELECT DISTINCT (e.metadata_json::jsonb->'volume'->>'id')::int AS volume_id \
             FROM issue_external_identity_mappings m \
             JOIN issues s ON s.id = m.issue_id \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE s.thread_id = $1 AND m.status = 'confirmed' \
               AND e.provider = 'comicvine' AND e.entity_type = 'issue' \
               AND (e.metadata_json::jsonb->'volume'->>'id') ~ '^[0-9]+$'",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    for row in &sibling_rows {
        context.issue.volume_hint_ids.push(row.get(0));
    }

    let series_rows = conn
        .query(
            "SELECT COALESCE(NULLIF(e.metadata_json::jsonb->>'publisher', ''), \
                             NULLIF(e.metadata_json::jsonb->'publisher'->>'name', '')) AS publisher, \
                    CASE WHEN (e.metadata_json::jsonb->>'start_year') ~ '^[0-9]+$' \
                         THEN (e.metadata_json::jsonb->>'start_year')::int END AS start_year, \
                    CASE WHEN e.external_id ~ '^[0-9]+$' THEN e.external_id::int END AS volume_id, \
                    NULLIF(e.metadata_json::jsonb->>'name', '') AS alias \
             FROM thread_external_series_mappings tm \
             JOIN external_identities e ON e.id = tm.external_identity_id \
             WHERE tm.thread_id = $1 AND tm.status = 'confirmed' \
               AND e.provider = 'comicvine' AND e.entity_type = 'series' \
             ORDER BY tm.id LIMIT 8",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    for row in &series_rows {
        context.apply_series_hint(row.get(0), row.get(1), row.get(2), row.get(3));
    }

    let cbl_rows = conn
        .query(
            "SELECT cse.series_name, \
                    CASE WHEN ev.external_id ~ '^[0-9]+$' THEN ev.external_id::int END AS volume_id \
             FROM issue_external_identity_mappings m \
             JOIN external_identities e ON e.id = m.external_identity_id \
             JOIN cbl_source_entries cse ON cse.external_issue_identity_id = e.id \
             LEFT JOIN external_identities ev ON ev.id = cse.external_series_identity_id \
               AND ev.provider = 'comicvine' AND ev.entity_type = 'series' \
             WHERE m.issue_id = $1 AND m.status = 'confirmed' \
               AND e.provider = 'comicvine' AND e.entity_type = 'issue' \
               AND btrim(cse.series_name) <> '' \
             ORDER BY cse.id LIMIT 20",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    for row in &cbl_rows {
        context.apply_series_hint(None, None, row.get(1), row.get(0));
    }

    Ok(context.finish())
}

/// Batch variant of [`load_match_context`] for a page of inbox items. Three
/// set-based queries cover the whole page instead of three per item.
async fn load_match_contexts(
    conn: &deadpool_postgres::Object,
    rows: &[(i32, i32, String, String)],
) -> Result<std::collections::HashMap<i32, crate::comicvine_matching::MatchIssue>, ApiError> {
    if rows.is_empty() {
        return Ok(std::collections::HashMap::new());
    }
    let thread_ids: Vec<i32> = rows.iter().map(|row| row.0).collect();
    let issue_ids: Vec<i32> = rows.iter().map(|row| row.1).collect();
    let mut contexts: std::collections::HashMap<i32, MatchContext> = rows
        .iter()
        .map(|(_thread_id, issue_id, title, number)| {
            (*issue_id, MatchContext::new(*issue_id, title, number))
        })
        .collect();
    let mut issues_by_thread: std::collections::HashMap<i32, Vec<i32>> =
        std::collections::HashMap::new();
    for (thread_id, issue_id, _, _) in rows {
        issues_by_thread
            .entry(*thread_id)
            .or_default()
            .push(*issue_id);
    }

    let sibling_rows = conn
        .query(
            "SELECT DISTINCT s.thread_id, (e.metadata_json::jsonb->'volume'->>'id')::int AS volume_id \
             FROM issue_external_identity_mappings m \
             JOIN issues s ON s.id = m.issue_id \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE s.thread_id = ANY($1) AND m.status = 'confirmed' \
               AND e.provider = 'comicvine' AND e.entity_type = 'issue' \
               AND (e.metadata_json::jsonb->'volume'->>'id') ~ '^[0-9]+$'",
            &[&thread_ids],
        )
        .await
        .map_err(db::query_error)?;
    for row in &sibling_rows {
        let thread_id: i32 = row.get(0);
        let volume_id: i32 = row.get(1);
        if let Some(issue_ids) = issues_by_thread.get(&thread_id) {
            for issue_id in issue_ids {
                if let Some(context) = contexts.get_mut(issue_id) {
                    context.issue.volume_hint_ids.push(volume_id);
                }
            }
        }
    }

    let series_rows = conn
        .query(
            "SELECT tm.thread_id, \
                    COALESCE(NULLIF(e.metadata_json::jsonb->>'publisher', ''), \
                             NULLIF(e.metadata_json::jsonb->'publisher'->>'name', '')) AS publisher, \
                    CASE WHEN (e.metadata_json::jsonb->>'start_year') ~ '^[0-9]+$' \
                         THEN (e.metadata_json::jsonb->>'start_year')::int END AS start_year, \
                    CASE WHEN e.external_id ~ '^[0-9]+$' THEN e.external_id::int END AS volume_id, \
                    NULLIF(e.metadata_json::jsonb->>'name', '') AS alias \
             FROM thread_external_series_mappings tm \
             JOIN external_identities e ON e.id = tm.external_identity_id \
             WHERE tm.thread_id = ANY($1) AND tm.status = 'confirmed' \
               AND e.provider = 'comicvine' AND e.entity_type = 'series' \
             ORDER BY tm.id",
            &[&thread_ids],
        )
        .await
        .map_err(db::query_error)?;
    for row in &series_rows {
        let thread_id: i32 = row.get(0);
        if let Some(issue_ids) = issues_by_thread.get(&thread_id) {
            for issue_id in issue_ids {
                if let Some(context) = contexts.get_mut(issue_id) {
                    context.apply_series_hint(row.get(1), row.get(2), row.get(3), row.get(4));
                }
            }
        }
    }

    let cbl_rows = conn
        .query(
            "SELECT s.id AS issue_id, cse.series_name, \
                    CASE WHEN ev.external_id ~ '^[0-9]+$' THEN ev.external_id::int END AS volume_id \
             FROM issue_external_identity_mappings m \
             JOIN external_identities e ON e.id = m.external_identity_id \
             JOIN issues s ON s.id = m.issue_id \
             JOIN cbl_source_entries cse ON cse.external_issue_identity_id = e.id \
             LEFT JOIN external_identities ev ON ev.id = cse.external_series_identity_id \
               AND ev.provider = 'comicvine' AND ev.entity_type = 'series' \
             WHERE s.id = ANY($1) AND m.status = 'confirmed' \
               AND e.provider = 'comicvine' AND e.entity_type = 'issue' \
               AND btrim(cse.series_name) <> '' \
             ORDER BY cse.id",
            &[&issue_ids],
        )
        .await
        .map_err(db::query_error)?;
    for row in &cbl_rows {
        let issue_id: i32 = row.get(0);
        if let Some(context) = contexts.get_mut(&issue_id) {
            context.apply_series_hint(None, None, row.get(2), row.get(1));
        }
    }

    Ok(contexts
        .into_iter()
        .map(|(issue_id, context)| (issue_id, context.finish()))
        .collect())
}

/// The same explanation contract is used by the list and the detail handler,
/// so the collapsed header and the expanded item never disagree.
fn explain_item(
    status: &str,
    evidence: &Value,
    candidate_count: usize,
    hints: &crate::comicvine_matching::MatchIssue,
) -> (String, Vec<String>) {
    let reason = why_stopped(status, evidence, candidate_count);
    let steps = next_steps_for(status, evidence, candidate_count);
    if candidate_count > 0 {
        return (reason, steps);
    }
    // No stored candidate: say what discovery actually checked. This uses
    // the real hint roster rather than a fixed placeholder, and never
    // auto-confirms anything.
    let mut detail = reason;
    if !hints.volume_hint_ids.is_empty() || !hints.source_volume_ids.is_empty() {
        detail.push_str(&format!(
            " Checked the volume(s) already used by this series: {}.",
            hints
                .volume_hint_ids
                .iter()
                .chain(hints.source_volume_ids.iter())
                .map(|id| format!("4050-{id}"))
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    if !hints.aliases.is_empty() {
        detail.push_str(&format!(
            " Also tried alternate names: {}.",
            hints.aliases.join(", ")
        ));
    }
    (detail, steps)
}

/// Convert one ComicVine search row into the provider view the pure matcher
/// consumes. Missing optional fields stay `None`; the matcher never assumes a
/// label is present on the provider side.
fn provider_issue_from_search(
    obj: &serde_json::Map<String, Value>,
) -> Option<crate::comicvine_matching::ProviderIssue> {
    let issue_id = obj.get("id")?.as_i64()? as i32;
    let volume = obj.get("volume").and_then(|v| v.as_object());
    let volume_id = volume
        .and_then(|v| v.get("id"))
        .and_then(|v| v.as_i64())
        .unwrap_or(0) as i32;
    if volume_id <= 0 {
        return None;
    }
    let volume_name = volume
        .and_then(|v| v.get("name"))
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .to_string();
    let publisher = match obj.get("publisher") {
        Some(Value::Object(o)) => o.get("name").and_then(|v| v.as_str()).map(str::to_string),
        Some(Value::String(s)) => Some(s.clone()),
        _ => None,
    };
    let start_year = obj
        .get("cover_date")
        .and_then(|v| v.as_str())
        .and_then(|s| s.get(..4))
        .and_then(|s| s.parse::<i32>().ok());
    let issue_number = obj.get("issue_number").and_then(|v| {
        if v.is_null() {
            None
        } else {
            Some(v.to_string().trim_matches('"').to_string())
        }
    });
    Some(crate::comicvine_matching::ProviderIssue {
        comicvine_issue_id: issue_id,
        comicvine_volume_id: volume_id,
        volume_name,
        publisher,
        start_year,
        issue_number,
        issue_name: obj
            .get("name")
            .and_then(|v| v.as_str())
            .map(str::to_string),
        aliases: Vec::new(),
    })
}

async fn fetch_item(
    state: &Arc<AppState>,
    user_id: i32,
    mapping_id: i32,
) -> Result<Option<IdentityInboxItem>, ApiError> {
    let conn = db::checkout(state).await?;
    let mapping_row = conn
        .query_opt(
            "SELECT m.id, m.issue_id, m.status, m.evidence_json::text, \
                    EXTRACT(EPOCH FROM m.created_at)::float8, EXTRACT(EPOCH FROM m.updated_at)::float8 \
             FROM issue_external_identity_mappings m WHERE m.id = $1",
            &[&mapping_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(mr) = mapping_row else {
        return Ok(None);
    };
    let mid: i32 = mr.get(0);
    let issue_id: i32 = mr.get(1);
    let status: String = mr.get(2);
    let evidence_text: Option<String> = mr.get(3);
    let created_at: Option<f64> = mr.get(4);
    let updated_at: Option<f64> = mr.get(5);
    let evidence = parse_json_text(evidence_text);

    let issue_row = conn
        .query_opt(
            "SELECT i.id, i.issue_number, i.thread_id FROM issues i WHERE i.id = $1",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(ir) = issue_row else {
        return Ok(None);
    };
    let issue_number: String = ir.get(1);
    let thread_id: i32 = ir.get(2);

    let thread_row = conn
        .query_opt(
            "SELECT t.id, t.title, t.user_id FROM threads t WHERE t.id = $1",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(tr) = thread_row else {
        return Ok(None);
    };
    let thread_title: String = tr.get(1);
    let owner_id: i32 = tr.get(2);
    if owner_id != user_id {
        return Ok(None);
    }

    let identity_row = conn
        .query_opt(
            "SELECT e.id, e.provider, e.external_id, e.external_url, e.metadata_json::text \
             FROM issue_external_identity_mappings m JOIN external_identities e ON e.id=m.external_identity_id \
             WHERE m.id=$1",
            &[&mapping_id],
        )
        .await
        .map_err(db::query_error)?;
    let (provider, metadata) = if let Some(idr) = identity_row {
        let provider: String = idr.get(1);
        let metadata_text: Option<String> = idr.get(4);
        (Some(provider), parse_json_text(metadata_text))
    } else {
        (None, serde_json::json!({}))
    };

    // candidates
    let candidate_rows = conn
        .query(
            "SELECT cm.external_identity_id, cm.status, cm.confidence, cm.evidence_source, \
                    cm.evidence_json::text, cm.rejection_reason, \
                    ex.provider, ex.external_id, ex.external_url, ex.metadata_json::text \
             FROM issue_external_identity_mappings cm \
             JOIN external_identities ex ON ex.id = cm.external_identity_id \
             WHERE cm.issue_id = $1 AND cm.status IN ('deferred','candidate','confirmed','unresolved') \
             ORDER BY cm.confidence DESC NULLS LAST",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;

    let mut candidates = Vec::new();
    for cr in candidate_rows {
        let ext_id: i32 = cr.get(0);
        let cstatus: String = cr.get(1);
        let confidence: Option<f64> = cr.get(2);
        let evidence_source: Option<String> = cr.get(3);
        let evidence_text: Option<String> = cr.get(4);
        let rejection_reason: Option<String> = cr.get(5);
        let cprovider: String = cr.get(6);
        let comicvine_id: String = cr.get(7);
        let external_url: Option<String> = cr.get(8);
        let meta_text: Option<String> = cr.get(9);
        let metadata_json = parse_json_text(meta_text);
        let evidence_json = parse_json_text(evidence_text);
        candidates.push(IdentityInboxCandidate {
            external_identity_id: ext_id,
            provider: cprovider,
            comicvine_id: Some(comicvine_id),
            external_url,
            metadata_json,
            status: cstatus,
            confidence,
            evidence_source,
            evidence_json,
            rejection_reason,
        });
    }

    // #5434: the detail and list handlers share one explanation contract.
    // Hints are loaded from real owned data (confirmed sibling volumes,
    // series publisher/year, aliases and CBL source volumes), not injected
    // fixture values.
    let hints = load_match_context(&conn, thread_id, issue_id, &thread_title, &issue_number).await?;
    let (why_stopped_value, next_steps_value) =
        explain_item(&status, &evidence, candidates.len(), &hints);

    let item = IdentityInboxItem {
        mapping_id: mid,
        issue_id,
        thread_id,
        thread_title: thread_title.clone(),
        issue_number: issue_number.clone(),
        status: status.clone(),
        provider,
        source_entry_summary: source_entry_summary(&thread_title, &issue_number, &metadata),
        why_stopped: why_stopped_value,
        next_steps: next_steps_value,
        candidates,
        created_at,
        updated_at,
    };
    let _ = mid;
    Ok(Some(item))
}

pub async fn list_inbox(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(q): Query<ListQuery>,
) -> Result<Json<IdentityInboxResponse>, ApiError> {
    let offset = q.offset.unwrap_or(0);
    if offset < 0 {
        return Err(unprocessable("offset must be >= 0"));
    }
    let limit = q.limit.unwrap_or(50);
    if !(1..=100).contains(&limit) {
        return Err(unprocessable("limit out of range"));
    }

    let conn = db::checkout(&state).await?;
    let count_row = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM issue_external_identity_mappings m \
             JOIN issues i ON i.id = m.issue_id \
             JOIN threads t ON t.id = i.thread_id \
             WHERE t.user_id = $1 AND m.status IN ('unresolved','candidate','deferred')",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let total: i64 = count_row.get(0);

    let rows = conn
        .query(
            "SELECT m.id, m.status, \
                    EXTRACT(EPOCH FROM m.created_at)::float8, EXTRACT(EPOCH FROM m.updated_at)::float8, \
                    i.id, i.issue_number, \
                    t.id, t.title, \
                    e.id, e.provider, e.external_id, e.external_url, e.metadata_json::text, \
                    m.evidence_json::text \
             FROM issue_external_identity_mappings m \
             JOIN issues i ON i.id = m.issue_id \
             JOIN threads t ON t.id = i.thread_id \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE t.user_id = $1 AND m.status IN ('unresolved','candidate','deferred') \
             ORDER BY m.created_at DESC \
             OFFSET $2 LIMIT $3",
            &[&user.id(), &offset, &limit],
        )
        .await
        .map_err(db::query_error)?;

    // Batch-load candidates for every issue on this page in one query. The
    // detail endpoint resolves candidates by issue_id; grouping them per issue
    // here preserves the same wire contract without an N+1 round trip.
    let issue_ids: Vec<i32> = rows.iter().map(|r| r.get(4)).collect();
    let candidate_rows = if issue_ids.is_empty() {
        Vec::new()
    } else {
        conn.query(
            "SELECT cm.issue_id, cm.external_identity_id, cm.status, cm.confidence, \
                    cm.evidence_source, cm.evidence_json::text, cm.rejection_reason, \
                    ex.provider, ex.external_id, ex.external_url, ex.metadata_json::text \
             FROM issue_external_identity_mappings cm \
             JOIN external_identities ex ON ex.id = cm.external_identity_id \
             WHERE cm.issue_id = ANY($1) \
               AND cm.status IN ('deferred','candidate','confirmed','unresolved') \
             ORDER BY cm.issue_id, cm.confidence DESC NULLS LAST",
            &[&issue_ids],
        )
        .await
        .map_err(db::query_error)?
    };

    let mut candidates_by_issue: std::collections::HashMap<i32, Vec<IdentityInboxCandidate>> =
        std::collections::HashMap::new();
    for cr in candidate_rows {
        let candidate_issue_id: i32 = cr.get(0);
        let ext_id: i32 = cr.get(1);
        let cstatus: String = cr.get(2);
        let confidence: Option<f64> = cr.get(3);
        let evidence_source: Option<String> = cr.get(4);
        let evidence_text: Option<String> = cr.get(5);
        let rejection_reason: Option<String> = cr.get(6);
        let cprovider: String = cr.get(7);
        let comicvine_id: String = cr.get(8);
        let external_url: Option<String> = cr.get(9);
        let meta_text: Option<String> = cr.get(10);
        let metadata_json = parse_json_text(meta_text);
        let evidence_json = parse_json_text(evidence_text);
        candidates_by_issue
            .entry(candidate_issue_id)
            .or_default()
            .push(IdentityInboxCandidate {
                external_identity_id: ext_id,
                provider: cprovider,
                comicvine_id: Some(comicvine_id),
                external_url,
                metadata_json,
                status: cstatus,
                confidence,
                evidence_source,
                evidence_json,
                rejection_reason,
            });
    }

    let context_rows: Vec<(i32, i32, String, String)> = rows
        .iter()
        .map(|r| (r.get(6), r.get(4), r.get::<_, String>(7), r.get::<_, String>(5)))
        .collect();
    let contexts = load_match_contexts(&conn, &context_rows).await?;

    let mut items = Vec::new();
    for r in rows {
        let mapping_id: i32 = r.get(0);
        let status: String = r.get(1);
        let created_at: Option<f64> = r.get(2);
        let updated_at: Option<f64> = r.get(3);
        let issue_id: i32 = r.get(4);
        let issue_number: String = r.get(5);
        let thread_id: i32 = r.get(6);
        let thread_title: String = r.get(7);
        let _ext_id: i32 = r.get(8);
        let provider: String = r.get(9);
        let comicvine_id: String = r.get(10);
        let external_url: Option<String> = r.get(11);
        let meta_text: Option<String> = r.get(12);
        let evidence_text: Option<String> = r.get(13);
        let metadata = parse_json_text(meta_text);
        let evidence = parse_json_text(evidence_text);
        let candidates = candidates_by_issue
            .get(&issue_id)
            .cloned()
            .unwrap_or_default();
        let hints = contexts
            .get(&issue_id)
            .cloned()
            .unwrap_or_else(|| crate::comicvine_matching::MatchIssue {
                issue_id,
                series_name: thread_title.clone(),
                issue_number: issue_number.clone(),
                publisher: None,
                start_year: None,
                volume_hint_ids: Vec::new(),
                aliases: Vec::new(),
                source_volume_ids: Vec::new(),
            });
        let (why, steps) = explain_item(&status, &evidence, candidates.len(), &hints);
        items.push(IdentityInboxItem {
            mapping_id,
            issue_id,
            thread_id,
            thread_title: thread_title.clone(),
            issue_number: issue_number.clone(),
            status: status.clone(),
            provider: Some(provider),
            source_entry_summary: source_entry_summary(&thread_title, &issue_number, &metadata),
            why_stopped: why,
            next_steps: steps,
            candidates,
            created_at,
            updated_at,
        });
        let _ = (comicvine_id, external_url);
    }

    Ok(Json(IdentityInboxResponse {
        items,
        total,
        offset,
        limit,
    }))
}

pub async fn get_inbox_item(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(mapping_id): Path<i32>,
) -> Result<Json<IdentityInboxResponse>, ApiError> {
    let item = fetch_item(&state, user.id(), mapping_id)
        .await?
        .ok_or_else(|| not_found(&format!("Inbox item {mapping_id} not found")))?;
    Ok(Json(IdentityInboxResponse {
        items: vec![item],
        total: 1,
        offset: 0,
        limit: 1,
    }))
}

pub async fn search_issues(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(q): Query<SearchQuery>,
) -> Result<Json<IdentityInboxSearchResponse>, ApiError> {
    let _ = user;
    if q.q.trim().is_empty() || q.q.len() > 200 || q.q.is_empty() {
        return Err(unprocessable("q invalid"));
    }
    let limit = q.limit.unwrap_or(10);
    if !(1..=50).contains(&limit) {
        return Err(unprocessable("limit out of range"));
    }
    let clamped = limit.clamp(1, 50);
    let issue_id = q.issue_id.unwrap_or(0);

    let api_key = crate::comicvine_repair::provider_api_key().unwrap_or_default();
    if api_key.is_empty() {
        return Ok(Json(IdentityInboxSearchResponse {
            issue_id,
            query: q.q.clone(),
            results: vec![],
            total_available: Some(0),
        }));
    }

    // #5434: build the local side of the match from real owned data when the
    // caller supplies an issue. This loads sibling volumes, publisher/year,
    // aliases and CBL source volumes instead of relying on the title alone.
    let local = if issue_id > 0 {
        let conn = db::checkout(&state).await?;
        let row = conn
            .query_opt(
                "SELECT i.issue_number, i.thread_id, t.title \
                 FROM issues i JOIN threads t ON t.id = i.thread_id \
                 WHERE i.id = $1 AND t.user_id = $2",
                &[&issue_id, &user.id()],
            )
            .await
            .map_err(db::query_error)?;
        match row {
            Some(row) => {
                let number: String = row.get(0);
                let thread_id: i32 = row.get(1);
                let title: String = row.get(2);
                load_match_context(&conn, thread_id, issue_id, &title, &number).await?
            }
            None => crate::comicvine_matching::MatchIssue {
                issue_id,
                series_name: q.q.clone(),
                issue_number: String::new(),
                publisher: None,
                start_year: None,
                volume_hint_ids: Vec::new(),
                aliases: Vec::new(),
                source_volume_ids: Vec::new(),
            },
        }
    } else {
        crate::comicvine_matching::MatchIssue {
            issue_id: 0,
            series_name: q.q.clone(),
            issue_number: String::new(),
            publisher: None,
            start_year: None,
            volume_hint_ids: Vec::new(),
            aliases: Vec::new(),
            source_volume_ids: Vec::new(),
        }
    };

    // A pasted ComicVine volume/issue URL is a first-class discovery input.
    // It is resolved directly instead of being sent to the text search.
    let url = match crate::comicvine_v2::parse_comicvine_url(&q.q) {
        Some(crate::comicvine_v2::ParsedResource::Issue(id)) => build_resource_url(
            &api_key,
            &format!("issue/4000-{id}"),
            &format!("id,issue_number,name,cover_date,volume,publisher,site_detail_url,image"),
        ),
        Some(crate::comicvine_v2::ParsedResource::Volume(id)) => build_volume_issues_url(&api_key, id, clamped),
        None => build_search_url(&api_key, &q.q, clamped),
    };
    let payload = fetch_comicvine(&state.outbound, url).await;

    let mut results = Vec::new();
    let mut total_available = Some(0i64);
    if let Some(p) = payload {
        // Search and volume lookups return an array; a pasted issue URL
        // returns a single object. Both feed the same matching pipeline.
        let rows: Vec<&Value> = match p.get("results") {
            Some(Value::Array(values)) => values.iter().collect(),
            Some(object @ Value::Object(_)) => vec![object],
            _ => Vec::new(),
        };
        {
            for row in rows {
                let Some(obj) = row.as_object() else {
                    continue;
                };
                let comicvine_issue_id = match obj.get("id").and_then(|v| v.as_i64()) {
                    Some(v) => v as i32,
                    None => continue,
                };
                let volume = obj.get("volume").and_then(|v| v.as_object());
                let comicvine_volume_id = volume
                    .and_then(|v| v.get("id"))
                    .and_then(|v| v.as_i64())
                    .map(|v| v as i32);
                let volume_name = volume
                    .and_then(|v| v.get("name"))
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());

                let publisher = match obj.get("publisher") {
                    Some(Value::Object(o)) => o
                        .get("name")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string()),
                    Some(Value::String(s)) => Some(s.clone()),
                    _ => None,
                };

                let image_url = obj.get("image").and_then(|v| v.as_object()).and_then(|o| {
                    o.get("medium_url")
                        .or_else(|| o.get("small_url"))
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string())
                });

                let cover_date = obj.get("cover_date").and_then(|v| v.as_str());
                let start_year = cover_date.and_then(|cd| {
                    if cd.len() >= 4 {
                        cd[..4].parse::<i32>().ok()
                    } else {
                        None
                    }
                });

                let site_detail_url = obj
                    .get("site_detail_url")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());

                let issue_number = obj.get("issue_number").and_then(|v| {
                    if v.is_null() {
                        None
                    } else {
                        Some(v.to_string().trim_matches('"').to_string())
                    }
                });

                let issue_name = obj
                    .get("name")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());

                let mut evidence = Vec::new();
                if let Some(vn) = &volume_name {
                    evidence.push(format!("Volume: {vn}"));
                }
                if let Some(pubn) = &publisher {
                    evidence.push(format!("Publisher: {pubn}"));
                }

                // #5434: score the provider row with the same explainable
                // heuristics the pure matching module uses. This is real
                // production data (the provider response plus owned hints),
                // not an injected fixture.
                let mut score = None;
                if let Some(provider_issue) = provider_issue_from_search(obj) {
                    let volumes = crate::comicvine_matching::discover_volume_candidates(
                        &local,
                        std::slice::from_ref(&provider_issue),
                    );
                    if let Some(best) = volumes.first() {
                        score = Some(best.score);
                        evidence.extend(best.evidence.iter().cloned());
                    } else if let Some(provider_label) = provider_issue
                        .issue_number
                        .as_deref()
                        .or(provider_issue.issue_name.as_deref())
                    {
                        let label_match = crate::comicvine_matching::compare_issue_labels(
                            &local.issue_number,
                            provider_label,
                        );
                        if label_match != crate::comicvine_matching::LabelMatch::None {
                            evidence.push(format!(
                                "issue label {} matches provider {}",
                                local.issue_number, provider_label
                            ));
                            score = Some(match label_match {
                                crate::comicvine_matching::LabelMatch::Exact => 0.34,
                                crate::comicvine_matching::LabelMatch::Equivalent => 0.28,
                                crate::comicvine_matching::LabelMatch::None => 0.0,
                            });
                        }
                    }
                    let similarity = crate::comicvine_matching::title_similarity(
                        &local.series_name,
                        &provider_issue.volume_name,
                    );
                    if similarity >= 0.45 {
                        evidence.push(format!(
                            "fuzzy title match {:.0}%: {}",
                            similarity * 100.0,
                            provider_issue.volume_name
                        ));
                    }
                }

                results.push(IdentityInboxSearchResult {
                    comicvine_issue_id,
                    comicvine_volume_id,
                    volume_name,
                    issue_number,
                    issue_name,
                    publisher,
                    start_year,
                    site_detail_url,
                    image_url,
                    score,
                    evidence,
                });
            }
        }
        if let Some(total) = p.get("number_of_total_results").and_then(|v| v.as_i64()) {
            total_available = Some(total);
        } else {
            total_available = Some(results.len() as i64);
        }
    }

    let issue_id_final = if q.issue_id.is_some() { issue_id } else { 0 };
    // Python sets issue_id=0 then caller sets issue_id if provided. Keep issue_id if provided else 0.
    let _ = issue_id_final;

    Ok(Json(IdentityInboxSearchResponse {
        issue_id: q.issue_id.unwrap_or(0),
        query: q.q.clone(),
        results,
        total_available,
    }))
}

fn percent_encode(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            b' ' => out.push_str("%20"),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

fn build_search_url(api_key: &str, query: &str, limit: i64) -> String {
    let field_list = "id,name,issue_number,cover_date,volume,publisher,site_detail_url,image";
    format!(
        "https://comicvine.gamespot.com/api/search/?api_key={}&format=json&query={}&resources=issue&limit={}&field_list={}",
        percent_encode(api_key),
        percent_encode(query),
        limit,
        percent_encode(field_list)
    )
}

/// Resolve a pasted issue URL to its canonical provider resource.
fn build_resource_url(api_key: &str, resource: &str, field_list: &str) -> String {
    format!(
        "https://comicvine.gamespot.com/api/{resource}/?api_key={}&format=json&field_list={}",
        percent_encode(api_key),
        percent_encode(field_list)
    )
}

/// Resolve a pasted volume URL to the issues on that volume (bounded page).
fn build_volume_issues_url(api_key: &str, volume_id: i32, limit: i64) -> String {
    let field_list = "id,name,issue_number,cover_date,volume,publisher,site_detail_url,image";
    format!(
        "https://comicvine.gamespot.com/api/issues/?api_key={}&format=json&filter=volume%3A{volume_id}&limit={limit}&field_list={}",
        percent_encode(api_key),
        percent_encode(field_list)
    )
}

/// Search-result payload cap. ComicVine search responses are small; the cap
/// keeps a hostile provider from driving unbounded allocation.
const MAX_SEARCH_BODY: usize = 5_000_000;
const SEARCH_TIMEOUT: Duration = Duration::from_secs(30);

/// Fetch one ComicVine search page through the app's outbound seam (#5339):
/// the real HTTPS client in production, a recording fake in test contexts
/// that never opens a socket. Any failure yields `None`, as before.
async fn fetch_comicvine(outbound: &Arc<dyn OutboundHttp>, url: String) -> Option<Value> {
    let without = url.strip_prefix("https://")?;
    let (host, rest) = without.split_once('/')?;
    let request = OutboundRequest {
        method: http::Method::GET,
        path: format!("/{rest}"),
        headers: vec![
            ("user-agent".to_string(), "ComicPile/1.0".to_string()),
            ("accept".to_string(), "application/json".to_string()),
            ("connection".to_string(), "close".to_string()),
        ],
        body: Bytes::new(),
    };
    let exchange = async {
        let response = outbound.send(host, request).await.ok()?;
        if !response.status.is_success() {
            return None;
        }
        let mut data = Vec::new();
        let mut body = response.body;
        while let Some(frame) = body.frame().await {
            let frame = frame.ok()?;
            if let Ok(bytes) = frame.into_data() {
                data.extend_from_slice(&bytes);
                if data.len() > MAX_SEARCH_BODY {
                    return None;
                }
            }
        }
        serde_json::from_slice(&data).ok()
    };
    tokio::time::timeout(SEARCH_TIMEOUT, exchange)
        .await
        .ok()
        .flatten()
}

pub async fn confirm(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(mapping_id): Path<i32>,
    Json(req): Json<ActionRequest>,
) -> Result<Json<IdentityInboxActionResponse>, ApiError> {
    let external_identity_id = req
        .external_identity_id
        .ok_or_else(|| bad_request("external_identity_id is required for confirm action"))?;

    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    // load mapping
    let mrow = tx
        .query_opt(
            "SELECT id, issue_id FROM issue_external_identity_mappings WHERE id = $1",
            &[&mapping_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(mr) = mrow else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not found"));
    };
    let issue_id: i32 = mr.get(1);

    // issue + thread ownership
    let it = tx
        .query_opt(
            "SELECT t.user_id FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = $1 FOR UPDATE OF i",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(itr) = it else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    };
    let owner_id: i32 = itr.get(0);
    if owner_id != user.id() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    }

    // external identity
    let idr = tx
        .query_opt(
            "SELECT id, provider, entity_type FROM external_identities WHERE id = $1",
            &[&external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(ident) = idr else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("external identity is not an issue identity"));
    };
    let provider: String = ident.get(1);
    let entity_type: String = ident.get(2);
    if entity_type != "issue" {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("external identity is not an issue identity"));
    }

    // conflicting confirmed
    let conflict = tx
        .query_opt(
            "SELECT m.id FROM issue_external_identity_mappings m \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE m.issue_id = $1 AND m.status = 'confirmed' \
               AND m.external_identity_id <> $2 AND e.provider = $3 LIMIT 1",
            &[&issue_id, &external_identity_id, &provider],
        )
        .await
        .map_err(db::query_error)?;
    if conflict.is_some() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request(&format!(
            "issue already has a confirmed {provider} identity"
        )));
    }

    // upsert
    let existing = tx
        .query_opt(
            "SELECT id FROM issue_external_identity_mappings WHERE issue_id = $1 AND external_identity_id = $2",
            &[&issue_id, &external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    if let Some(er) = existing {
        let eid: i32 = er.get(0);
        tx.execute(
            "UPDATE issue_external_identity_mappings SET status='confirmed', evidence_source='user_confirmed', \
             confidence=1.0, rejection_reason=NULL, updated_at=NOW() WHERE id=$1",
            &[&eid],
        )
        .await
        .map_err(db::query_error)?;
    } else {
        tx.execute(
            "INSERT INTO issue_external_identity_mappings \
             (issue_id, external_identity_id, status, evidence_source, confidence, rejection_reason, created_at, updated_at) \
             VALUES ($1,$2,'confirmed','user_confirmed',1.0,NULL,NOW(),NOW())",
            &[&issue_id, &external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    }

    // reject others
    tx.execute(
        "UPDATE issue_external_identity_mappings m SET status='rejected', \
         rejection_reason='replaced by user-confirmed candidate', updated_at=NOW() \
         FROM external_identities e \
         WHERE m.external_identity_id = e.id AND m.issue_id = $1 \
           AND m.external_identity_id <> $2 AND m.status IN ('candidate','unresolved','deferred') \
           AND e.provider = $3",
        &[&issue_id, &external_identity_id, &provider],
    )
    .await
    .map_err(db::query_error)?;

    tx.commit().await.map_err(db::query_error)?;

    let updated = fetch_item(&state, user.id(), mapping_id).await?;
    Ok(Json(IdentityInboxActionResponse {
        success: true,
        message: "Candidate confirmed successfully".to_string(),
        updated_item: updated,
    }))
}

pub async fn reject(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(mapping_id): Path<i32>,
    Json(req): Json<ActionRequest>,
) -> Result<Json<IdentityInboxActionResponse>, ApiError> {
    let external_identity_id = req
        .external_identity_id
        .ok_or_else(|| bad_request("external_identity_id is required for reject action"))?;
    let rejection_reason = req
        .rejection_reason
        .as_deref()
        .map(|s| s.to_string())
        .unwrap_or_default();
    if rejection_reason.trim().is_empty() {
        return Err(bad_request(
            "rejection_reason is required when rejecting a candidate",
        ));
    }

    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    let mrow = tx
        .query_opt(
            "SELECT id, issue_id FROM issue_external_identity_mappings WHERE id = $1",
            &[&mapping_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(mr) = mrow else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not found"));
    };
    let issue_id: i32 = mr.get(1);

    let it = tx
        .query_opt(
            "SELECT t.user_id FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = $1",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(itr) = it else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    };
    let owner_id: i32 = itr.get(0);
    if owner_id != user.id() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    }

    // validate external identity
    let idr = tx
        .query_opt(
            "SELECT id, entity_type FROM external_identities WHERE id = $1",
            &[&external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(ident) = idr else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("external identity is not an issue identity"));
    };
    let entity_type: String = ident.get(1);
    if entity_type != "issue" {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("external identity is not an issue identity"));
    }

    // upsert rejected
    let existing = tx
        .query_opt(
            "SELECT id FROM issue_external_identity_mappings WHERE issue_id = $1 AND external_identity_id = $2",
            &[&issue_id, &external_identity_id],
        )
        .await
        .map_err(db::query_error)?;
    if let Some(er) = existing {
        let eid: i32 = er.get(0);
        tx.execute(
            "UPDATE issue_external_identity_mappings SET status='rejected', evidence_source=NULL, confidence=NULL, rejection_reason=$2, updated_at=NOW() WHERE id=$1",
            &[&eid, &rejection_reason],
        )
        .await
        .map_err(db::query_error)?;
    } else {
        tx.execute(
            "INSERT INTO issue_external_identity_mappings \
             (issue_id, external_identity_id, status, evidence_source, confidence, rejection_reason, created_at, updated_at) \
             VALUES ($1,$2,'rejected',NULL,NULL,$3,NOW(),NOW())",
            &[&issue_id, &external_identity_id, &rejection_reason],
        )
        .await
        .map_err(db::query_error)?;
    }
    tx.execute(
        "UPDATE issue_external_identity_mappings SET updated_at=NOW() WHERE issue_id=$1",
        &[&issue_id],
    )
    .await
    .map_err(db::query_error)?;
    tx.commit().await.map_err(db::query_error)?;

    let updated = fetch_item(&state, user.id(), mapping_id).await?;
    Ok(Json(IdentityInboxActionResponse {
        success: true,
        message: "Candidate rejected".to_string(),
        updated_item: updated,
    }))
}

pub async fn defer(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(mapping_id): Path<i32>,
) -> Result<Json<IdentityInboxActionResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let mut tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    let mrow = tx
        .query_opt(
            "SELECT id, issue_id FROM issue_external_identity_mappings WHERE id = $1",
            &[&mapping_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(mr) = mrow else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not found"));
    };
    let issue_id: i32 = mr.get(1);

    let it = tx
        .query_opt(
            "SELECT t.user_id FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = $1",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(itr) = it else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    };
    let owner_id: i32 = itr.get(0);
    if owner_id != user.id() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    }

    // Some deployed databases are stamped at a revision that added 'deferred'
    // to the status allow-list without the constraint change having actually
    // run (issue #5378). Writing status='deferred' then fails with a check
    // violation and used to surface as a generic HTTP 500. Use a savepoint so
    // the failed statement cannot poison the outer transaction, and fall back
    // to a representation the stale constraint accepts: a rejected mapping
    // with an explicit defer reason. Either way the item leaves the unresolved
    // inbox and the defer succeeds instead of returning a 500.
    let savepoint = tx
        .savepoint("identity_inbox_defer_status")
        .await
        .map_err(db::query_error)?;
    match savepoint
        .execute(
            "UPDATE issue_external_identity_mappings SET status='deferred', updated_at=NOW() WHERE id=$1",
            &[&mapping_id],
        )
        .await
    {
        Ok(_) => {
            savepoint.commit().await.map_err(db::query_error)?;
        }
        Err(error)
            if error.code() == Some(&tokio_postgres::error::SqlState::CHECK_VIOLATION) =>
        {
            savepoint.rollback().await.map_err(db::query_error)?;
            tx.execute(
                "UPDATE issue_external_identity_mappings SET status='rejected', \
                 rejection_reason='deferred by user', evidence_source='deferred', \
                 updated_at=NOW() WHERE id=$1",
                &[&mapping_id],
            )
            .await
            .map_err(db::query_error)?;
        }
        Err(error) => return Err(db::query_error(error)),
    }
    tx.commit().await.map_err(db::query_error)?;

    let updated = fetch_item(&state, user.id(), mapping_id).await?;
    Ok(Json(IdentityInboxActionResponse {
        success: true,
        message: "Item deferred for later review".to_string(),
        updated_item: updated,
    }))
}

pub async fn skip(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(mapping_id): Path<i32>,
) -> Result<Json<IdentityInboxActionResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    let mrow = tx
        .query_opt(
            "SELECT id, issue_id FROM issue_external_identity_mappings WHERE id = $1",
            &[&mapping_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(mr) = mrow else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not found"));
    };
    let issue_id: i32 = mr.get(1);

    let it = tx
        .query_opt(
            "SELECT t.user_id FROM issues i JOIN threads t ON t.id = i.thread_id WHERE i.id = $1",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(itr) = it else {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    };
    let owner_id: i32 = itr.get(0);
    if owner_id != user.id() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(bad_request("mapping not owned by this user"));
    }

    tx.execute(
        "UPDATE issue_external_identity_mappings SET status='rejected', rejection_reason='skipped by user', updated_at=NOW() WHERE id=$1",
        &[&mapping_id],
    )
    .await
    .map_err(db::query_error)?;
    tx.commit().await.map_err(db::query_error)?;

    let updated = fetch_item(&state, user.id(), mapping_id).await?;
    Ok(Json(IdentityInboxActionResponse {
        success: true,
        message: "Item skipped".to_string(),
        updated_item: updated,
    }))
}

// Documentation-only operations for OpenAPI
#[utoipa::path(
    get,
    path = "/api/v2/identity-inbox",
    tag = "identity-inbox",
    params(
        ("offset" = Option<i64>, Query, minimum = 0, description = "Items to skip (default 0)"),
        ("limit" = Option<i64>, Query, minimum = 1, maximum = 100, description = "Page size, 1-100 (default 50)")
    ),
    responses((status = 200, description = "ok", body = IdentityInboxResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/identity-inbox/issue-matches",
    tag = "identity-inbox",
    params(
        ("q" = String, Query, min_length = 1, description = "Non-blank search text, at most 200 UTF-8 bytes (required)"),
        ("limit" = Option<i64>, Query, minimum = 1, maximum = 50, description = "Maximum results, 1-50 (default 10)"),
        ("issue_id" = Option<i32>, Query, description = "Issue id echoed back in the response (default 0)")
    ),
    responses((status = 200, description = "ok", body = IdentityInboxSearchResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn search_documentation() {}

#[utoipa::path(
    get,
    path = "/api/v2/identity-inbox/{mapping_id}",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    responses((status = 200, description = "ok", body = IdentityInboxResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/identity-inbox/{mapping_id}/confirmations",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    request_body = IdentityInboxConfirmRequest,
    responses((status = 200, description = "ok", body = IdentityInboxActionResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn confirm_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/identity-inbox/{mapping_id}/deferrals",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    responses((status = 200, description = "ok", body = IdentityInboxActionResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn defer_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/identity-inbox/{mapping_id}/rejections",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    request_body = IdentityInboxRejectRequest,
    responses((status = 200, description = "ok", body = IdentityInboxActionResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn reject_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/identity-inbox/{mapping_id}/skips",
    tag = "identity-inbox",
    params(("mapping_id" = i32, Path, description = "Mapping id")),
    responses((status = 200, description = "ok", body = IdentityInboxActionResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn skip_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::AuthenticatedUser;
    use crate::test_support;

    /// ComICVine search must go through the outbound seam: the fake records
    /// the host and query and supplies the payload, never a socket (#5339).
    #[tokio::test]
    async fn fetch_comicvine_records_host_and_query_and_parses_the_payload() {
        let recorder = Arc::new(crate::outbound::RecordingFakeOutbound::new());
        let fake: Arc<dyn OutboundHttp> = recorder.clone();
        recorder.push_ok(
            http::StatusCode::OK,
            http::HeaderMap::new(),
            Bytes::from_static(
                br#"{"status_code":1,"number_of_total_results":1,"results":[{"id":40001,"name":"Batman"}]}"#,
            ),
        );
        let url = build_search_url("KEY123", "bat man", 10);
        let payload = fetch_comicvine(&fake, url)
            .await
            .expect("canned provider payload must parse");
        assert_eq!(payload["number_of_total_results"], 1);
        assert_eq!(payload["results"][0]["id"], 40001);

        let calls = recorder.calls();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].host, "comicvine.gamespot.com");
        assert_eq!(calls[0].method, "GET");
        assert!(
            calls[0].path.starts_with("/api/search/?api_key=KEY123"),
            "unexpected search path {}",
            calls[0].path
        );
        assert!(calls[0].path.contains("query=bat%20man"));
        assert!(calls[0].path.contains("resources=issue"));
    }

    #[tokio::test]
    async fn fetch_comicvine_returns_none_on_error_status_failure_and_oversize() {
        let recorder = Arc::new(crate::outbound::RecordingFakeOutbound::new());
        let fake: Arc<dyn OutboundHttp> = recorder.clone();
        // Non-success status.
        recorder.push_ok(
            http::StatusCode::INTERNAL_SERVER_ERROR,
            http::HeaderMap::new(),
            Bytes::from_static(br#"{"status_code":1}"#),
        );
        assert!(fetch_comicvine(&fake, build_search_url("K", "q", 10))
            .await
            .is_none());
        // Transport failure (the default fake behavior).
        assert!(fetch_comicvine(&fake, build_search_url("K", "q", 10))
            .await
            .is_none());
        // Oversized body is dropped instead of allocated unbounded.
        recorder.push_ok(
            http::StatusCode::OK,
            http::HeaderMap::new(),
            Bytes::from(vec![b'x'; MAX_SEARCH_BODY + 1]),
        );
        assert!(fetch_comicvine(&fake, build_search_url("K", "q", 10))
            .await
            .is_none());
        assert_eq!(recorder.calls().len(), 3);
    }

    /// End-to-end through the handler: a test-configured app answers search
    /// from the recording fake, so the route never touches the network.
    #[tokio::test]
    async fn search_issues_serves_results_from_the_recording_fake() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let fake = state
            .recording_fake()
            .expect("test state must install the recording fake outbound client");
        fake.clear();
        fake.push_ok(
            http::StatusCode::OK,
            http::HeaderMap::new(),
            Bytes::from_static(
                br#"{"status_code":1,"number_of_total_results":1,"results":[{"id":400077,"name":"Detective Comics","issue_number":"1","volume":{"id":40509},"site_detail_url":"https://comicvine.gamespot.com/issue/4000-77/"}]}"#,
            ),
        );
        let _env = ComicvineKeyEnv::install();
        let response = search_issues(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Query(SearchQuery {
                q: "detective".to_string(),
                limit: Some(10),
                issue_id: None,
            }),
        )
        .await
        .expect("search must succeed against the fake");
        assert_eq!(response.total_available, Some(1));
        assert_eq!(response.results.len(), 1);
        assert_eq!(response.results[0].comicvine_issue_id, 400077);
        let calls = fake.calls();
        assert_eq!(calls.len(), 1, "exactly one outbound call, no socket");
        assert_eq!(calls[0].host, "comicvine.gamespot.com");
    }

    /// Save/restore `COMICVINE_API_KEY` around one test (same pattern as the
    /// bug-reports GitHub env guard).
    struct ComicvineKeyEnv {
        previous: Option<String>,
    }

    impl ComicvineKeyEnv {
        fn install() -> Self {
            let previous = std::env::var("COMICVINE_API_KEY").ok();
            std::env::set_var("COMICVINE_API_KEY", "TESTKEY123");
            Self { previous }
        }
    }

    impl Drop for ComicvineKeyEnv {
        fn drop(&mut self) {
            match &self.previous {
                Some(value) => std::env::set_var("COMICVINE_API_KEY", value),
                None => std::env::remove_var("COMICVINE_API_KEY"),
            }
        }
    }

    #[test]
    fn why_stopped_uses_candidate_count_and_keeps_zero_candidate_reasons() {
        let empty = serde_json::json!({});
        // Real candidate state wins over the empty-evidence fallback, but a
        // non-empty decision_reason is preserved so the header still explains
        // why review is needed.
        assert_eq!(why_stopped("unresolved", &empty, 1), "1 candidate found");
        assert_eq!(why_stopped("unresolved", &empty, 3), "3 candidates found");
        let with_reason = serde_json::json!({"decision_reason": "ambiguous title"});
        assert_eq!(
            why_stopped("unresolved", &with_reason, 1),
            "1 candidate found: ambiguous title"
        );
        assert_eq!(
            why_stopped("candidate", &with_reason, 2),
            "2 candidates found: ambiguous title"
        );
        // With no candidates, reasons remain actionable even without evidence.
        let no_candidates = why_stopped("unresolved", &empty, 0);
        assert!(no_candidates.contains("No candidates found"));
        assert!(no_candidates.to_lowercase().contains("different name"));
        assert!(no_candidates.to_lowercase().contains("url"));
        assert_eq!(why_stopped("candidate", &with_reason, 0), "ambiguous title");
    }

    #[test]
    fn next_steps_are_actionable_for_non_match_states() {
        let empty = serde_json::json!({});
        let steps = next_steps_for("unresolved", &empty, 0);
        assert!(!steps.is_empty());
        assert!(steps.iter().any(|s| s.to_lowercase().contains("different")));
        assert!(steps.iter().any(|s| s.to_lowercase().contains("url")));
        assert!(steps.iter().any(|s| s.to_lowercase().contains("manual")));
        let candidate_steps = next_steps_for("candidate", &empty, 2);
        assert!(!candidate_steps.is_empty());
    }

    #[tokio::test]
    async fn list_empty_returns_ok() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let user = AuthenticatedUser::for_test(1);
        // seed user
        let conn = state.pool.get().await.unwrap();
        conn.batch_execute(
            "INSERT INTO users (id, username, is_admin, created_at) VALUES (1,'u',false,NOW())",
        )
        .await
        .unwrap();
        drop(conn);
        let (status, body) = {
            let r = list_inbox(
                State(state.clone()),
                user,
                Query(ListQuery {
                    offset: None,
                    limit: None,
                }),
            )
            .await
            .unwrap();
            // call via function returns Json; extract
            (
                axum::http::StatusCode::OK,
                serde_json::to_value(r.0).unwrap(),
            )
        };
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["total"], 0);
    }

    #[tokio::test]
    async fn list_inbox_batch_loads_candidates_for_owned_issues_only() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let conn = state.pool.get().await.unwrap();
        conn.batch_execute(
            "INSERT INTO users (id, username, is_admin, created_at) VALUES \
                (1,'owner',false,NOW()), (2,'other',false,NOW()); \
             INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status, manual_creator_credits, is_blocked, is_test, queue_position_is_manual, created_at) VALUES \
                (1,1,'Owned thread','comics',2,0,'active','[]'::json,false,false,false,NOW()), \
                (2,2,'Other thread','comics',1,0,'active','[]'::json,false,false,false,NOW()); \
             INSERT INTO issues (id, thread_id, issue_number, status, position, created_at) VALUES \
                (1,1,'#1','unread',0,NOW()), \
                (2,1,'#2','unread',1,NOW()), \
                (3,2,'#1','unread',0,NOW()); \
             INSERT INTO external_identities (id, provider, entity_type, external_id, metadata_json, created_at, updated_at) VALUES \
                (1,'comicvine','issue','cv-1','{}'::json,NOW(),NOW()), \
                (2,'comicvine','issue','cv-2','{}'::json,NOW(),NOW()), \
                (3,'comicvine','issue','cv-3','{}'::json,NOW(),NOW()), \
                (4,'comicvine','issue','cv-4','{}'::json,NOW(),NOW()), \
                (5,'comicvine','issue','cv-5','{}'::json,NOW(),NOW()), \
                (6,'comicvine','issue','cv-6','{}'::json,NOW(),NOW()); \
             INSERT INTO issue_external_identity_mappings \
                (id, issue_id, external_identity_id, status, evidence_source, confidence, created_at, updated_at, evidence_json) VALUES \
                (1,1,1,'unresolved','heuristic',0.5,NOW(),NOW(),'{}'::json), \
                (2,1,2,'confirmed','user_confirmed',0.9,NOW(),NOW(),'{}'::json), \
                (3,2,3,'unresolved','heuristic',0.5,NOW(),NOW(),'{}'::json), \
                (4,2,4,'confirmed','user_confirmed',0.8,NOW(),NOW(),'{}'::json), \
                (5,3,5,'unresolved','heuristic',0.5,NOW(),NOW(),'{}'::json), \
                (6,3,6,'confirmed','user_confirmed',0.7,NOW(),NOW(),'{}'::json);",
        )
        .await
        .unwrap();
        drop(conn);

        let response = list_inbox(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Query(ListQuery {
                offset: None,
                limit: None,
            }),
        )
        .await
        .unwrap()
        .0;

        assert_eq!(response.total, 2);
        assert_eq!(response.items.len(), 2);
        let item_one = response
            .items
            .iter()
            .find(|item| item.issue_id == 1)
            .unwrap();
        let item_two = response
            .items
            .iter()
            .find(|item| item.issue_id == 2)
            .unwrap();
        assert_eq!(
            item_one
                .candidates
                .iter()
                .map(|c| c.external_identity_id)
                .collect::<Vec<_>>(),
            vec![2, 1]
        );
        assert_eq!(
            item_two
                .candidates
                .iter()
                .map(|c| c.external_identity_id)
                .collect::<Vec<_>>(),
            vec![4, 3]
        );
        assert!(!response.items.iter().any(|item| item.issue_id == 3));
        assert!(!response
            .items
            .iter()
            .any(|item| { item.candidates.iter().any(|c| c.external_identity_id == 6) }));
    }

    /// Regression test for #5382: the list endpoint now batch-loads real
    /// candidates, but `why_stopped` was ported from a Python implementation
    /// whose list response always had `candidates=[]`. An unresolved mapping
    /// with empty `evidence_json` therefore produced "No candidates found"
    /// while the very same response carried one candidate. The collapsed
    /// inbox header rendered that contradiction to the user. When candidates
    /// exist, a non-empty decision_reason is preserved alongside the count.
    #[tokio::test]
    async fn list_inbox_why_stopped_reflects_real_candidates() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let conn = state.pool.get().await.unwrap();
        conn.batch_execute(
            "INSERT INTO users (id, username, is_admin, created_at) VALUES (1,'owner',false,NOW()); \
             INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status, manual_creator_credits, is_blocked, is_test, queue_position_is_manual, created_at) VALUES \
                 (1,1,'Mutant X','comics',1,0,'active','[]'::json,false,false,false,NOW()), \
                 (2,1,'Mutant Y','comics',1,0,'active','[]'::json,false,false,false,NOW()); \
             INSERT INTO issues (id, thread_id, issue_number, status, position, created_at) VALUES \
                 (1,1,'#1','unread',0,NOW()), \
                 (2,2,'#1','unread',0,NOW()); \
             INSERT INTO external_identities (id, provider, entity_type, external_id, metadata_json, created_at, updated_at) VALUES \
                 (1,'comicvine','issue','cv-1','{}'::json,NOW(),NOW()), \
                 (2,'comicvine','issue','cv-2','{}'::json,NOW(),NOW()), \
                 (3,'comicvine','issue','cv-3','{}'::json,NOW(),NOW()); \
             INSERT INTO issue_external_identity_mappings \
                 (id, issue_id, external_identity_id, status, evidence_source, confidence, created_at, updated_at, evidence_json) VALUES \
                 (1,1,1,'unresolved','heuristic',0.5,NOW(),NOW(),'{\"decision_reason\":\"ambiguous title\"}'::json), \
                 (2,2,2,'unresolved','heuristic',0.5,NOW(),NOW(),'{\"decision_reason\":\"ambiguous title\"}'::json), \
                 (3,2,3,'confirmed','user_confirmed',0.9,NOW(),NOW(),'{}'::json);",
        )
        .await
        .unwrap();
        drop(conn);

        let response = list_inbox(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Query(ListQuery {
                offset: None,
                limit: None,
            }),
        )
        .await
        .unwrap()
        .0;

        assert_eq!(response.items.len(), 2);

        let one = response
            .items
            .iter()
            .find(|item| item.issue_id == 1)
            .expect("issue 1 item");
        assert_eq!(one.candidates.len(), 1, "issue 1 has one candidate mapping");
        assert!(
            !one.why_stopped.contains("No candidates found"),
            "collapsed header must not claim no candidates when a candidate exists; got {:?}",
            one.why_stopped,
        );
        assert_eq!(one.why_stopped, "1 candidate found: ambiguous title");

        let two = response
            .items
            .iter()
            .find(|item| item.issue_id == 2)
            .expect("issue 2 item");
        assert_eq!(
            two.candidates.len(),
            2,
            "issue 2 has N>1 candidate mappings"
        );
        assert!(
            !two.why_stopped.contains("No candidates found"),
            "collapsed header must not claim no candidates when candidates exist; got {:?}",
            two.why_stopped,
        );
        assert_eq!(two.why_stopped, "2 candidates found: ambiguous title");
    }

    #[tokio::test]
    async fn mutation_handlers_reach_database_write_boundary() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let user = AuthenticatedUser::for_test(1);
        let request = ActionRequest {
            external_identity_id: Some(1),
            rejection_reason: Some("not a match".to_string()),
            search_query: None,
        };

        let _ = confirm(State(state.clone()), user, Path(1), Json(request)).await;
        let _ = reject(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(1),
            Json(ActionRequest {
                external_identity_id: Some(1),
                rejection_reason: Some("not a match".to_string()),
                search_query: None,
            }),
        )
        .await;
        let _ = defer(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(1),
        )
        .await;
        let _ = skip(State(state), AuthenticatedUser::for_test(1), Path(1)).await;
    }

    /// A raw admin connection is needed only to simulate production's stale
    /// status constraint; the handler itself still runs as the DML-only role.
    async fn admin_client() -> tokio_postgres::Client {
        let (client, connection) = tokio_postgres::connect(
            &test_support::required_test_admin_url(),
            tokio_postgres::NoTls,
        )
        .await
        .expect("admin test connection");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        client
    }

    /// Regression for #5378: production is stamped past the revision that
    /// added 'deferred' to the status allow-list, but its live constraint does
    /// not contain that value. Defer must succeed (and remove the item from the
    /// unresolved inbox) instead of failing with a check-violation 500.
    #[tokio::test]
    async fn defer_succeeds_when_status_constraint_predates_deferred_value() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let admin = admin_client().await;

        // Reproduce the deployed constraint from before c85700000001.
        admin
            .batch_execute(
                "ALTER TABLE issue_external_identity_mappings DROP CONSTRAINT IF EXISTS \
                 ck_issue_external_identity_status; \
                 ALTER TABLE issue_external_identity_mappings ADD CONSTRAINT \
                 ck_issue_external_identity_status CHECK (status IN \
                 ('unresolved','candidate','confirmed','rejected'));",
            )
            .await
            .expect("install stale status constraint");

        let conn = state.pool.get().await.unwrap();
        conn.batch_execute(
            "INSERT INTO users (id, username, is_admin, created_at) VALUES (1,'owner',false,NOW()); \
             INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status, manual_creator_credits, is_blocked, is_test, queue_position_is_manual, created_at) VALUES \
                 (1,1,'Owned','comics',1,0,'active','[]'::json,false,false,false,NOW()); \
             INSERT INTO issues (id, thread_id, issue_number, status, position, created_at) VALUES \
                 (1,1,'#6','unread',0,NOW()); \
             INSERT INTO external_identities (id, provider, entity_type, external_id, metadata_json, created_at, updated_at) VALUES \
                 (1,'comicvine','issue','901096','{}'::json,NOW(),NOW()); \
             INSERT INTO issue_external_identity_mappings \
                 (id, issue_id, external_identity_id, status, evidence_source, evidence_json, created_at, updated_at) VALUES \
                 (1,1,1,'unresolved','heuristic','{}'::json,NOW(),NOW());",
        )
        .await
        .unwrap();
        drop(conn);

        let response = defer(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(1),
        )
        .await;

        // Restore the canonical constraint before asserting so a failure here
        // cannot leak the stale schema into the next serialized test.
        admin
            .batch_execute(
                "ALTER TABLE issue_external_identity_mappings DROP CONSTRAINT IF EXISTS \
                 ck_issue_external_identity_status; \
                 ALTER TABLE issue_external_identity_mappings ADD CONSTRAINT \
                 ck_issue_external_identity_status CHECK (status IN \
                 ('unresolved','candidate','confirmed','rejected','deferred'));",
            )
            .await
            .expect("restore canonical status constraint");

        let body = response.expect("defer must succeed on a stale status constraint");
        assert!(body.success);
        assert_eq!(body.message, "Item deferred for later review");

        let conn = state.pool.get().await.unwrap();
        let row = conn
            .query_one(
                "SELECT status, rejection_reason FROM issue_external_identity_mappings WHERE id=1",
                &[],
            )
            .await
            .unwrap();
        let status: String = row.get(0);
        let reason: Option<String> = row.get(1);
        assert_eq!(status, "rejected");
        assert_eq!(reason.as_deref(), Some("deferred by user"));
        drop(conn);

        let list = list_inbox(
            State(state),
            AuthenticatedUser::for_test(1),
            Query(ListQuery {
                offset: None,
                limit: None,
            }),
        )
        .await
        .unwrap()
        .0;
        assert_eq!(list.total, 0);
    }

    /// Regression for #5623: deferring an inbox item must keep showing its candidate
    /// evidence. When an item is deferred, the candidates query should still return
    /// the deferred mapping as a candidate so the UI shows "1 candidate found" instead
    /// of "No candidates found" with no reason.
    #[tokio::test]
    async fn deferred_item_shows_candidate_evidence() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let conn = state.pool.get().await.unwrap();
        conn.batch_execute(
            "INSERT INTO users (id, username, is_admin, created_at) VALUES (1,'owner',false,NOW()); \
             INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status, manual_creator_credits, is_blocked, is_test, queue_position_is_manual, created_at) VALUES \
                 (1,1,'Mutant X','comics',1,0,'active','[]'::json,false,false,false,NOW()); \
             INSERT INTO issues (id, thread_id, issue_number, status, position, created_at) VALUES \
                 (1,1,'#4','unread',0,NOW()); \
             INSERT INTO external_identities (id, provider, entity_type, external_id, metadata_json, created_at, updated_at) VALUES \
                 (1,'comicvine','issue','901096','{}'::json,NOW(),NOW()); \
             INSERT INTO issue_external_identity_mappings \
                 (id, issue_id, external_identity_id, status, evidence_source, confidence, created_at, updated_at, evidence_json) VALUES \
                 (1,1,1,'unresolved','heuristic',0.5,NOW(),NOW(),'{}'::json);",
        )
        .await
        .unwrap();
        drop(conn);

        // First verify the item shows 1 candidate before deferral
        let before_defer = list_inbox(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Query(ListQuery {
                offset: None,
                limit: None,
            }),
        )
        .await
        .unwrap()
        .0;
        assert_eq!(before_defer.items.len(), 1);
        let item_before = &before_defer.items[0];
        assert_eq!(item_before.status, "unresolved");
        assert_eq!(
            item_before.candidates.len(),
            1,
            "item should have 1 candidate before deferral"
        );
        assert!(
            !item_before.why_stopped.contains("No candidates found"),
            "before deferral, collapsed header should not claim no candidates; got {:?}",
            item_before.why_stopped,
        );

        // Defer the item
        let defer_response = defer(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path(1),
        )
        .await
        .unwrap();
        assert!(defer_response.success);
        assert_eq!(defer_response.message, "Item deferred for later review");

        // Verify the deferred item still shows candidate evidence
        let after_defer = list_inbox(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Query(ListQuery {
                offset: None,
                limit: None,
            }),
        )
        .await
        .unwrap()
        .0;
        assert_eq!(after_defer.items.len(), 1);
        let item_after = &after_defer.items[0];
        assert_eq!(item_after.status, "deferred");
        // The deferred mapping should still be visible as a candidate
        assert_eq!(
            item_after.candidates.len(),
            1,
            "deferred item should still show its candidate evidence; got {} candidates",
            item_after.candidates.len()
        );
        assert!(
            !item_after.why_stopped.contains("No candidates found"),
            "collapsed header must not claim no candidates when a candidate exists (even if deferred); got {:?}",
            item_after.why_stopped,
        );
        assert_eq!(item_after.why_stopped, "1 candidate found");

        // Also verify get_inbox_item works correctly for deferred items
        let detail_response = get_inbox_item(State(state), AuthenticatedUser::for_test(1), Path(1))
            .await
            .unwrap()
            .0;
        assert_eq!(detail_response.items.len(), 1);
        let detail_item = &detail_response.items[0];
        assert_eq!(detail_item.status, "deferred");
        assert_eq!(
            detail_item.candidates.len(),
            1,
            "deferred item detail should show candidate evidence; got {} candidates",
            detail_item.candidates.len()
        );
    }

    /// Seed one owned thread with a confirmed sibling volume, a confirmed
    /// series identity and a CBL source label. These are the real inputs #5434
    /// discovery must consume instead of empty fixture vectors.
    async fn seed_matching_fixture(state: &Arc<AppState>) {
        let conn = state.pool.get().await.unwrap();
        conn.batch_execute(
            "INSERT INTO users (id, username, is_admin, created_at) VALUES (1,'matcher',false,NOW()); \
             INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status, manual_creator_credits, is_blocked, is_test, queue_position_is_manual, created_at) VALUES \
                (1,1,'BPRD','comics',2,0,'active','[]'::json,false,false,false,NOW()); \
             INSERT INTO issues (id, thread_id, issue_number, status, position, created_at) VALUES \
                (1,1,'1.MU','unread',0,NOW()), \
                (2,1,'2','unread',1,NOW()); \
             INSERT INTO external_identities (id, provider, entity_type, external_id, metadata_json, created_at, updated_at) VALUES \
                (1,'comicvine','issue','4000001','{\"volume\":{\"id\":405031409}}'::json,NOW(),NOW()), \
                (2,'comicvine','issue','4000002','{}'::json,NOW(),NOW()), \
                (3,'comicvine','series','405031409','{\"name\":\"B.P.R.D.: Hell on Earth\",\"publisher\":\"Dark Horse Comics\",\"start_year\":2010}'::json,NOW(),NOW()); \
             INSERT INTO issue_external_identity_mappings \
                (id, issue_id, external_identity_id, status, evidence_source, confidence, created_at, updated_at, evidence_json) VALUES \
                (1,1,2,'unresolved','test',0.1,NOW(),NOW(),'{}'::json), \
                (2,2,1,'confirmed','user_confirmed',1.0,NOW(),NOW(),'{}'::json); \
             INSERT INTO thread_external_series_mappings \
                (id, thread_id, external_identity_id, status, evidence_source, created_at, updated_at) VALUES \
                (1,1,3,'confirmed','test',NOW(),NOW()); \
             INSERT INTO cbl_sources (id, repository, revision_sha, synced_at, created_at, updated_at) VALUES \
                (1,'fixture','rev',NOW(),NOW(),NOW()); \
             INSERT INTO cbl_source_lists (id, source_id, source_path, name, content_hash, revision_sha, active, created_at, updated_at) VALUES \
                (1,1,'fixture.cbl','Fixture','hash','rev',true,NOW(),NOW()); \
             INSERT INTO cbl_source_entries (id, list_id, position, series_name, issue_number, external_series_identity_id, external_issue_identity_id, created_at) VALUES \
                (1,1,1,'B.P.R.D. Hell on Earth','1',3,1,NOW());",
        )
        .await
        .unwrap();
    }

    #[tokio::test]
    async fn load_match_context_uses_real_sibling_series_and_cbl_hints() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        seed_matching_fixture(&state).await;
        let conn = state.pool.get().await.unwrap();
        let hints = load_match_context(&conn, 1, 1, "BPRD", "1.MU")
            .await
            .expect("hints must load");
        assert_eq!(hints.volume_hint_ids, vec![405031409]);
        assert_eq!(hints.publisher.as_deref(), Some("Dark Horse Comics"));
        assert_eq!(hints.start_year, Some(2010));
        assert!(hints.source_volume_ids.contains(&405031409));
        assert!(hints.aliases.iter().any(|a| a == "B.P.R.D.: Hell on Earth"));
        assert!(hints.aliases.iter().any(|a| a == "B.P.R.D. Hell on Earth"));
    }

    #[tokio::test]
    async fn search_scores_variant_label_with_real_hints() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        seed_matching_fixture(&state).await;
        let fake = state
            .recording_fake()
            .expect("test state must install the recording fake outbound client");
        fake.clear();
        fake.push_ok(
            http::StatusCode::OK,
            http::HeaderMap::new(),
            Bytes::from_static(
                br#"{"status_code":1,"number_of_total_results":1,"results":[{"id":400077,"name":"A Cold Day in Hell","issue_number":"1.MU","cover_date":"2013-03-20","volume":{"id":405031409,"name":"B.P.R.D.: Hell on Earth"},"publisher":{"name":"Dark Horse Comics"},"site_detail_url":"https://comicvine.gamespot.com/issue/4000-77/"}]}"#,
            ),
        );
        let _env = ComicvineKeyEnv::install();
        let response = search_issues(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Query(SearchQuery {
                q: "anything".to_string(),
                limit: Some(10),
                issue_id: Some(1),
            }),
        )
        .await
        .expect("search must succeed");
        assert_eq!(response.results.len(), 1);
        let result = &response.results[0];
        assert!(
            result.score.unwrap_or(0.0) >= 0.28,
            "variant label + alias hints must score the result: {:?}",
            result.score
        );
        assert!(
            result.evidence.iter().any(|e| e.contains("alias")),
            "evidence must explain the alias hit: {:?}",
            result.evidence
        );
        assert!(
            result.evidence.iter().any(|e| e.contains("1.MU")),
            "evidence must explain the flexible label match: {:?}",
            result.evidence
        );
    }

    #[tokio::test]
    async fn pasted_volume_url_resolves_issues_through_the_recording_fake() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        let fake = state
            .recording_fake()
            .expect("test state must install the recording fake outbound client");
        fake.clear();
        fake.push_ok(
            http::StatusCode::OK,
            http::HeaderMap::new(),
            Bytes::from_static(
                br#"{"status_code":1,"number_of_total_results":1,"results":[{"id":400078,"issue_number":"1","volume":{"id":405031409,"name":"B.P.R.D.: Hell on Earth"}}]}"#,
            ),
        );
        let _env = ComicvineKeyEnv::install();
        let response = search_issues(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Query(SearchQuery {
                q: "https://comicvine.gamespot.com/volume/4050-31409/".to_string(),
                limit: Some(10),
                issue_id: None,
            }),
        )
        .await
        .expect("pasted URL must resolve through the fake");
        assert_eq!(response.results.len(), 1);
        let calls = fake.calls();
        assert_eq!(calls.len(), 1);
        assert!(
            calls[0].path.contains("filter=volume%3A405031409"),
            "pasted volume URL must query that volume: {}",
            calls[0].path
        );
    }

    #[tokio::test]
    async fn list_and_detail_reasons_are_consistent() {
        let Some(state) = test_support::test_state(2).await else {
            return;
        };
        let _guard = test_support::reset_for_test(&state).await;
        seed_matching_fixture(&state).await;
        let list = list_inbox(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Query(ListQuery {
                offset: None,
                limit: None,
            }),
        )
        .await
        .expect("list must succeed")
        .0;
        let detail = fetch_item(&state, 1, 1).await.expect("detail").expect("item");
        let listed = list.items.iter().find(|item| item.mapping_id == 1).unwrap();
        assert_eq!(listed.why_stopped, detail.why_stopped);
        assert_eq!(listed.next_steps, detail.next_steps);
        assert!(
            detail.why_stopped.contains("4050-405031409"),
            "reason must name the real sibling volume: {}",
            detail.why_stopped
        );
    }
}
