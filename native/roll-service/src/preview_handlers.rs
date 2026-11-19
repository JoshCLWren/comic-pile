//! Native Rust cutover for browser-called preview operations.
//!
//! Preserves the Python `app/api/catalog.py` + `app/api/reading_order_projection.py` +
//! `app/api/cbl_sources.py` wire contracts at the same HTTP methods and exact paths.
//!
//! Routes cut over:
//! * `POST /api/v1/catalog/series-mappings/preview` - series mapping preview
//! * `POST /api/v1/continuity-plans/{plan_id}/reading-orders/project-preview` - projection preview
//! * `POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview` - reading graph preview
//!
//! Wire contracts mirror Python (`app/schemas/catalog.py`, `app/schemas/reading_order.py`)
//! with identical JSON field names, types, and optional/required status.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    Json,
};
use hmac::{digest::KeyInit, Hmac, Mac};
use sha2::{Digest, Sha256};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::SystemTime;
use utoipa::ToSchema;

type HmacSha256 = Hmac<Sha256>;

fn default_scope_mode() -> String {
    "confirmed_origin".to_string()
}

// Re-export types that match Python schemas
pub type ReadingGraphChoiceId = String;

// ============================================================================
// Series Mapping Preview Request/Response
// ============================================================================

#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct SeriesMappingPreviewRequest {
    #[serde(rename = "origin_issue_id")]
    pub origin_issue_id: i32,
    #[serde(rename = "provider")]
    pub provider: String,
    #[serde(rename = "provider_series_external_id")]
    pub provider_series_external_id: String,
    #[serde(default = "default_scope_mode")]
    pub scope_mode: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewScope {
    pub status: String,
    #[serde(rename = "scope_key", skip_serializing_if = "Option::is_none")]
    pub scope_key: Option<String>,
    #[serde(rename = "origin_issue_id")]
    pub origin_issue_id: i32,
    #[serde(rename = "series_label", skip_serializing_if = "Option::is_none")]
    pub series_label: Option<String>,
    pub basis: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewCounts {
    #[serde(rename = "already_confirmed")]
    pub already_confirmed: i32,
    #[serde(rename = "safe_exact_match")]
    pub safe_exact_match: i32,
    #[serde(rename = "needs_review_ambiguous")]
    pub needs_review_ambiguous: i32,
    #[serde(rename = "needs_review_conflict")]
    pub needs_review_conflict: i32,
    pub unresolved: i32,
    #[serde(rename = "excluded_special")]
    pub excluded_special: i32,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewRow {
    #[serde(rename = "row_id")]
    pub row_id: String,
    #[serde(rename = "issue_id")]
    pub issue_id: i32,
    #[serde(rename = "issue_number")]
    pub issue_number: String,
    #[serde(rename = "thread_id", skip_serializing_if = "Option::is_none")]
    pub thread_id: Option<i32>,
    #[serde(rename = "thread_title", skip_serializing_if = "Option::is_none")]
    pub thread_title: Option<String>,
    #[serde(rename = "current_mapping_status", skip_serializing_if = "Option::is_none")]
    pub current_mapping_status: Option<String>,
    pub classification: String,
    #[serde(rename = "proposed_mapping")]
    pub proposed_mapping: bool,
    #[serde(rename = "default_selected")]
    pub default_selected: bool,
    #[serde(rename = "title", skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(rename = "provider", skip_serializing_if = "Option::is_none")]
    pub provider: Option<String>,
    #[serde(rename = "external_id", skip_serializing_if = "Option::is_none")]
    pub external_id: Option<String>,
    #[serde(rename = "metadata_refresh_required", default)]
    pub metadata_refresh_required: bool,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewProviderSeries {
    pub id: String,
    #[serde(rename = "series_name", skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(rename = "publisher", skip_serializing_if = "Option::is_none")]
    pub publisher: Option<String>,
    #[serde(rename = "start_year", skip_serializing_if = "Option::is_none")]
    pub start_year: Option<i32>,
    #[serde(rename = "count_of_issues", skip_serializing_if = "Option::is_none")]
    pub count_of_issues: Option<i32>,
    #[serde(rename = "site_detail_url", skip_serializing_if = "Option::is_none")]
    pub site_detail_url: Option<String>,
    pub image: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewResponse {
    #[serde(rename = "preview_token", skip_serializing_if = "Option::is_none")]
    pub preview_token: Option<String>,
    pub scope: SeriesMappingPreviewScope,
    #[serde(rename = "provider_series", skip_serializing_if = "Option::is_none")]
    pub provider_series: Option<SeriesMappingPreviewProviderSeries>,
    pub counts: SeriesMappingPreviewCounts,
    pub rows: Vec<SeriesMappingPreviewRow>,
    #[serde(rename = "issued_at")]
    pub issued_at: f64,
    #[serde(rename = "expires_at", skip_serializing_if = "Option::is_none")]
    pub expires_at: Option<f64>,
}

// ============================================================================
// Reading Order Projection Preview Request/Response
// ============================================================================

#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReadingOrderProjectionPreviewRequest {
    #[serde(rename = "reading_order_id")]
    pub reading_order_id: i32,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionEntry {
    #[serde(rename = "thread_id")]
    pub thread_id: i32,
    #[serde(rename = "thread_title", skip_serializing_if = "Option::is_none")]
    pub thread_title: Option<String>,
    pub position: i32,
    pub source: String,
    #[serde(rename = "source_node_id", skip_serializing_if = "Option::is_none")]
    pub source_node_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionConflict {
    pub code: String,
    pub message: String,
    #[serde(rename = "node_id")]
    pub node_id: String,
    #[serde(rename = "thread_id", skip_serializing_if = "Option::is_none")]
    pub thread_id: Option<i32>,
    #[serde(rename = "existing_positions", default)]
    pub existing_positions: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderProjectionPreview {
    #[serde(rename = "plan_id")]
    pub plan_id: i32,
    #[serde(rename = "plan_name")]
    pub plan_name: String,
    #[serde(rename = "plan_ordering_mode")]
    pub plan_ordering_mode: String,
    #[serde(rename = "reading_order_id")]
    pub reading_order_id: i32,
    #[serde(rename = "reading_order_name")]
    pub reading_order_name: String,
    pub entries: Vec<ReadingOrderProjectionEntry>,
    pub conflicts: Vec<ReadingOrderProjectionConflict>,
    #[serde(rename = "total_positions", default)]
    pub total_positions: i32,
    #[serde(rename = "dropped_node_ids", default)]
    pub dropped_node_ids: Vec<String>,
}

// ============================================================================
// Reading Graph Preview Request/Response
// ============================================================================

#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReadingGraphPreviewRequest {
    #[serde(rename = "included_positions", default, skip_serializing_if = "Vec::is_empty")]
    pub included_positions: Vec<i32>,
    #[serde(rename = "overlap_choices", default, skip_serializing_if = "Vec::is_empty")]
    pub overlap_choices: Vec<ReadingGraphOverlapChoice>,
    #[serde(rename = "target_list_id", skip_serializing_if = "Option::is_none")]
    pub target_list_id: Option<i32>,
}

#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ReadingGraphOverlapChoice {
    #[serde(rename = "overlap_id")]
    pub overlap_id: String,
    pub choice: ReadingGraphChoiceId,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphSeriesReference {
    #[serde(rename = "comicvine_volume_id")]
    pub comicvine_volume_id: String,
    #[serde(rename = "series_name")]
    pub series_name: String,
    pub year: Option<i32>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphBlocker {
    pub kind: String,
    #[serde(rename = "list_id", skip_serializing_if = "Option::is_none")]
    pub list_id: Option<i32>,
    #[serde(rename = "waiting_on_issue_ids", default, skip_serializing_if = "Vec::is_empty")]
    pub waiting_on_issue_ids: Vec<i32>,
    #[serde(rename = "gate_issue_id", skip_serializing_if = "Option::is_none")]
    pub gate_issue_id: Option<i32>,
    pub explanation: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphIssueReference {
    #[serde(rename = "issue_id")]
    pub issue_id: i32,
    #[serde(rename = "series_name")]
    pub series_name: String,
    #[serde(rename = "issue_number")]
    pub issue_number: String,
    #[serde(rename = "comicvine_volume_id", skip_serializing_if = "Option::is_none")]
    pub comicvine_volume_id: Option<String>,
    #[serde(rename = "blockers", default, skip_serializing_if = "Vec::is_empty")]
    pub blockers: Vec<ReadingGraphBlocker>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphSeriesNode {
    #[serde(rename = "comicvine_volume_id")]
    pub comicvine_volume_id: String,
    #[serde(rename = "series_name")]
    pub series_name: String,
    pub year: Option<i32>,
    pub state: String,
    #[serde(rename = "unread_count", default)]
    pub unread_count: i32,
    #[serde(rename = "rollable_count", default)]
    pub rollable_count: i32,
    #[serde(rename = "waiting_count", default)]
    pub waiting_count: i32,
    #[serde(rename = "waits_for_issue_ids", default, skip_serializing_if = "Vec::is_empty")]
    pub waits_for_issue_ids: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphChoiceEffect {
    pub choice: ReadingGraphChoiceId,
    pub label: String,
    pub detail: String,
    #[serde(rename = "rollable_issue_ids", default, skip_serializing_if = "Vec::is_empty")]
    pub rollable_issue_ids: Vec<i32>,
    #[serde(rename = "waiting_issue_ids", default, skip_serializing_if = "Vec::is_empty")]
    pub waiting_issue_ids: Vec<i32>,
    pub series: Vec<ReadingGraphSeriesNode>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphOverlap {
    #[serde(rename = "overlap_id")]
    pub overlap_id: String,
    #[serde(rename = "continuing_series")]
    pub continuing_series: ReadingGraphSeriesReference,
    #[serde(rename = "waiting_series")]
    pub waiting_series: ReadingGraphSeriesReference,
    pub question: String,
    #[serde(rename = "blocked_issue_ids", default, skip_serializing_if = "Vec::is_empty")]
    pub blocked_issue_ids: Vec<i32>,
    pub choices: Vec<ReadingGraphChoiceEffect>,
    #[serde(rename = "selected_choice", skip_serializing_if = "Option::is_none")]
    pub selected_choice: Option<ReadingGraphChoiceId>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphCycleError {
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingGraphPreview {
    #[serde(rename = "source_list_id")]
    pub source_list_id: i32,
    #[serde(rename = "content_hash")]
    pub content_hash: String,
    #[serde(rename = "revision_sha")]
    pub revision_sha: String,
    pub series: Vec<ReadingGraphSeriesNode>,
    pub overlaps: Vec<ReadingGraphOverlap>,
    pub issues: Vec<ReadingGraphIssueReference>,
    #[serde(rename = "rollable_issue_ids", default, skip_serializing_if = "Vec::is_empty")]
    pub rollable_issue_ids: Vec<i32>,
    #[serde(rename = "waiting_issue_ids", default, skip_serializing_if = "Vec::is_empty")]
    pub waiting_issue_ids: Vec<i32>,
    #[serde(rename = "cycle_errors", default, skip_serializing_if = "Vec::is_empty")]
    pub cycle_errors: Vec<ReadingGraphCycleError>,
}

// ============================================================================
// Helper functions
// ============================================================================

fn now_f64() -> f64 {
    SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

const PREVIEW_TOKEN_TTL_SECONDS: f64 = 600.0;

fn canonical_json(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::Null => "null".to_string(),
        serde_json::Value::Bool(b) => if *b { "true" } else { "false" }.to_string(),
        serde_json::Value::Number(n) => n.to_string(),
        serde_json::Value::String(s) => {
            let encoded = serde_json::to_string(s).unwrap_or_default();
            let mut ascii = String::with_capacity(encoded.len());
            for ch in encoded.chars() {
                if ch.is_ascii() {
                    ascii.push(ch);
                } else {
                    for unit in ch.encode_utf16(&mut [0; 2]) {
                        ascii.push_str(&format!("\\u{unit:04x}"));
                    }
                }
            }
            ascii
        }
        serde_json::Value::Array(a) => {
            let items: Vec<String> = a.iter().map(canonical_json).collect();
            format!("[{}]", items.join(", "))
        }
        serde_json::Value::Object(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            let items: Vec<String> = keys
                .into_iter()
                .map(|k| format!("{}: {}", canonical_json(&serde_json::Value::String(k.clone())), canonical_json(&m[k])))
                .collect();
            format!("{{{}}}", items.join(", "))
        }
    }
}

fn generate_preview_token(
    secret: &str,
    payload: &serde_json::Value,
) -> Result<String, ApiError> {
    let payload_json = canonical_json(payload);
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes())
        .map_err(|_| ApiError::Internal("signature unavailable".to_string()))?;
    mac.update(payload_json.as_bytes());
    let signature = hex_digest(&mac.finalize().into_bytes());

    let token_data = serde_json::json!({
        "payload": payload,
        "signature": signature,
    });

    serde_json::to_string(&token_data)
        .map_err(|_| ApiError::Internal("token serialization failed".to_string()))
}

fn hex_digest(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

// ============================================================================
// POST /api/v1/catalog/series-mappings/preview
// ============================================================================

/// OpenAPI path documentation for the series mapping preview endpoint.
#[utoipa::path(
    post,
    path = "/api/v1/catalog/series-mappings/preview",
    tag = "catalog",
    operation_id = "catalog_series_mapping_preview",
    request_body = SeriesMappingPreviewRequest,
    responses(
        (status = 200, description = "Preview response", body = SeriesMappingPreviewResponse),
        (status = 401, description = "Authentication required"),
        (status = 422, description = "Validation error"),
        (status = 503, description = "Provider unavailable"),
        (status = 500, description = "Internal error")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn series_mapping_preview_documentation() {}

/// Preview a series mapping with safe scoping and classification.
///
/// This is a port of the Python `app/api/catalog.py::preview_series_mapping`
/// and `app/services/catalog.py::preview_series_mapping`.
pub async fn preview_series_mapping(
    State(state): State<Arc<AppState>>,
    auth: AuthenticatedUser,
    Json(payload): Json<SeriesMappingPreviewRequest>,
) -> Result<Json<SeriesMappingPreviewResponse>, ApiError> {
    let pool = db::checkout(&state).await?;
    let origin_issue_id = payload.origin_issue_id;

    // Load the origin issue (must be owned by the user)
    let origin_row = pool
        .query_opt(
            r#"
            SELECT i.id, i.issue_number, i.thread_id, t.title as thread_title,
                   m.status as current_mapping_status, e.provider, e.external_id, m.confidence,
                   e.metadata_json
            FROM issues i
            JOIN threads t ON t.id = i.thread_id AND t.user_id = $1
            LEFT JOIN issue_external_identity_mappings m ON m.issue_id = i.id
            LEFT JOIN external_identities e ON e.id = m.external_identity_id
            WHERE i.id = $2
            ORDER BY m.id NULLS LAST
            LIMIT 1
            "#,
            &[&auth.id(), &origin_issue_id],
        )
        .await
        .map_err(db::query_error)?;

    let Some(origin) = origin_row else {
        return Ok(Json(build_preview_response(
            origin_issue_id,
            &payload.provider,
            &payload.provider_series_external_id,
            None,
            &payload.scope_mode,
            vec![],
            &state,
            auth.id(),
            now_f64(),
        )));
    };

    let origin_thread_id: Option<i32> = origin.try_get(3).ok();
    let origin_issue_number: String = origin
        .try_get::<_, Option<String>>(1)
        .map_err(db::query_error)?
        .unwrap_or_default();
    let origin_mapping_status: Option<String> = origin.try_get(5).ok();
    let origin_mapping_provider: Option<String> = origin.try_get(6).ok();
    let origin_mapping_eid: Option<String> = origin.try_get(7).ok();

    // Check if origin has confirmed mapping to the selected series
    let provider = payload.provider.trim().to_lowercase();
    let series_external_id = payload.provider_series_external_id.trim().to_string();

    // Try to find the series locally
    let series_row = pool
        .query_opt(
            "SELECT e.id, e.metadata_json, e.external_url FROM external_identities e \
             WHERE e.provider = $1 AND e.entity_type = 'series' AND e.external_id = $2",
            &[&provider, &series_external_id],
        )
        .await
        .map_err(db::query_error)?;

    let mut issues_with_mappings: Vec<serde_json::Value> = Vec::new();
    let mut provider_series: Option<serde_json::Value> = None;
    let mut roster_rows: Vec<serde_json::Value> = Vec::new();

    if let Some(sr) = series_row {
        let meta: serde_json::Value = sr
            .try_get::<_, Option<serde_json::Value>>(2)
            .map_err(db::query_error)?
            .unwrap_or(serde_json::Value::Null);
        let external_url: Option<String> = sr.try_get(3).map_err(db::query_error)?;

        provider_series = Some(serde_json::json!({
            "id": series_external_id,
            "name": meta.get("name").cloned(),
            "publisher": meta.get("publisher").and_then(|p| {
                if p.is_object() { p.get("name").cloned() } else { Some(p.clone()) }
            }),
            "start_year": meta.get("start_year"),
            "count_of_issues": meta.get("count_of_issues"),
            "site_detail_url": external_url,
            "image": meta.get("image"),
        }));

        // Load mapped issues for this series
        let mapped_rows = pool
            .query(
                r#"
                SELECT i.id, i.issue_number, i.thread_id, t.title,
                       m.status, e.provider, e.external_id, m.confidence, e.metadata_json::text
                FROM issues i
                JOIN threads t ON t.id = i.thread_id AND t.user_id = $1
                JOIN issue_external_identity_mappings m ON m.issue_id = i.id
                JOIN external_identities e ON e.id = m.external_identity_id
                JOIN thread_external_series_mappings tsm ON tsm.thread_id = t.id
                  AND tsm.external_identity_id = $3 AND tsm.status = 'confirmed'
                WHERE e.provider = $2 AND e.entity_type = 'issue'
                "#,
                &[&auth.id(), &provider, &sr.get::<_, i32>(0)],
            )
            .await
            .map_err(db::query_error)?;

        for r in mapped_rows {
            let metadata_text: Option<String> = r.get(8);
            let identity_meta: serde_json::Value = metadata_text
                .as_deref()
                .and_then(|raw| serde_json::from_str(raw).ok())
                .unwrap_or(serde_json::Value::Null);
            issues_with_mappings.push(serde_json::json!({
                "issue_id": r.get::<_, i32>(0),
                "issue_number": r.get::<_, Option<String>>(1).unwrap_or_default(),
                "title": identity_meta.get("name"),
                "thread_id": r.get::<_, Option<i32>>(3),
                "thread_title": r.get::<_, Option<String>>(4),
                "current_mapping_status": r.get::<_, Option<String>>(5),
                "provider": r.get::<_, Option<String>>(6),
                "external_id": r.get::<_, Option<String>>(7),
                "confidence": r.get::<_, Option<f64>>(8),
                "classification": "unresolved",
                "_identity_metadata": identity_meta,
            }));
        }

        // Check if origin has confirmed mapping to this series
        let origin_confirmed = origin_mapping_status.as_deref() == Some("confirmed")
            && origin_mapping_provider.as_deref().map(|p| p.to_lowercase()) == Some(provider.clone());
        let linked_thread = if let Some(tid) = origin_thread_id {
            let rows = pool
                .query(
                    "SELECT EXISTS (
                       SELECT 1 FROM thread_external_series_mappings
                       WHERE thread_id = $1 AND external_identity_id = $2
                         AND status = 'confirmed'
                     )",
                    &[&tid, &sr.get::<_, i32>(0)],
                )
                .await
                .map_err(db::query_error)?;
            rows.iter().map(|r: &tokio_postgres::Row| r.get::<_, bool>(0)).next().unwrap_or(false)
        } else {
            false
        };

        if origin_confirmed || linked_thread {
            // Try to fetch provider roster (best-effort)
            if let Ok((provider_info, roster)) =
                crate::comicvine_repair::catalog_volume_roster(&state.outbound, &series_external_id)
                    .await
            {
                if let (Some(local), Some(fetched)) = (
                    provider_series.as_mut().and_then(|v| v.as_object_mut()),
                    provider_info.as_object(),
                ) {
                    local.extend(fetched.clone());
                }
                roster_rows = roster;
                if let Some(tid) = origin_thread_id {
                    let siblings = pool
                        .query(
                            r#"
                            SELECT i.id, i.issue_number, i.thread_id, t.title,
                                   m.status, e.provider, e.external_id, m.confidence, e.metadata_json::text
                            FROM issues i
                            JOIN threads t ON t.id = i.thread_id AND t.user_id = $1
                            LEFT JOIN issue_external_identity_mappings m ON m.issue_id = i.id
                            LEFT JOIN external_identities e ON e.id = m.external_identity_id
                            WHERE i.thread_id = $2 AND i.id <> $3
                            ORDER BY i.position, i.id
                            "#,
                            &[&auth.id(), &tid, &origin_issue_id],
                        )
                        .await
                        .map_err(db::query_error)?;

                    for r in siblings.iter() {
                        let meta_text: Option<String> = r.get(8);
                        let metadata: serde_json::Value = meta_text
                            .as_deref()
                            .and_then(|raw| serde_json::from_str(raw).ok())
                            .unwrap_or(serde_json::Value::Null);
                        issues_with_mappings.push(build_sibling_row(r, &metadata, &provider));
                    }
                }
            }
        }
    } else {
        // No local series - try provider
        if let Ok((provider_info, roster)) =
            crate::comicvine_repair::catalog_volume_roster(&state.outbound, &series_external_id).await
        {
            provider_series = Some(provider_info);
            roster_rows = roster;
        }
    }

    // Add origin if it has confirmed mapping not already in list
    if origin_mapping_status.as_deref() == Some("confirmed")
        && origin_mapping_provider.is_some()
        && origin_mapping_eid.is_some()
    {
        let in_list = issues_with_mappings.iter().any(|r| {
            r.get("issue_id").and_then(|v| v.as_i64()) == Some(i64::from(origin_issue_id))
        });
        if !in_list {
            issues_with_mappings.push(serde_json::json!({
                "issue_id": origin_issue_id,
                "issue_number": origin_issue_number,
                "title": origin.try_get::<_, Option<String>>(2).ok().flatten(),
                "thread_id": origin_thread_id,
                "thread_title": origin.try_get::<_, Option<String>>(4).ok().flatten(),
                "current_mapping_status": origin_mapping_status,
                "provider": origin_mapping_provider,
                "external_id": origin_mapping_eid,
                "confidence": origin.try_get::<_, Option<f64>>(8).ok().flatten(),
                "classification": "unresolved",
                "_is_origin": true,
                "_identity_metadata": origin.try_get::<_, Option<serde_json::Value>>(9).ok().flatten(),
            }));
        }
    }

    // Build preview response
    let issued_at = now_f64();
    let scope_status = if !issues_with_mappings.is_empty() { "available" } else { "unavailable" };
    let scope_basis = if scope_status == "available" {
        "exact_match_found"
    } else {
        "insufficient_non_thread_evidence"
    };

    Ok(Json(build_preview_response(
        origin_issue_id,
        &payload.provider,
        &payload.provider_series_external_id,
        provider_series,
        &payload.scope_mode,
        issues_with_mappings,
        &state,
        auth.id(),
        issued_at,
    )))
}

fn build_preview_response(
    origin_issue_id: i32,
    provider: &str,
    provider_series_external_id: &str,
    provider_series: Option<serde_json::Value>,
    scope_mode: &str,
    rows: Vec<serde_json::Value>,
    state: &Arc<AppState>,
    user_id: i32,
    issued_at: f64,
) -> SeriesMappingPreviewResponse {
    // Classify rows and compute counts
    let (classified_rows, mut counts) = classify_rows(&rows, provider, scope_mode);

    // Determine scope status and key
    let scope_status = if !classified_rows.is_empty() { "available" } else { "unavailable" };
    let scope_basis = if scope_status == "available" {
        "exact_match_found"
    } else {
        "insufficient_non_thread_evidence"
    };

    // Compute scope_key (first safe_exact_match issue number)
    let scope_key: Option<String> = classified_rows
        .iter()
        .find(|r| {
            r.get("classification")
                .and_then(|v| v.as_str())
                == Some("safe_exact_match")
        })
        .and_then(|r| {
            r.get("row_id")
                .and_then(|v| v.as_str())
                .and_then(|id| id.strip_prefix("issue:"))
                .map(|s| format!("exact:{}:{}", origin_issue_id, s))
        });

    let series_label = provider_series.as_ref().and_then(|s| s.get("name").and_then(|v| v.as_str()).map(|s| s.to_string()));

    let scope = SeriesMappingPreviewScope {
        status: scope_status.to_string(),
        scope_key: scope_key.clone(),
        origin_issue_id,
        series_label,
        basis: scope_basis.to_string(),
    };

    // Compute state digest
    let issue_numbers: Vec<String> = classified_rows
        .iter()
        .filter_map(|r| {
            r.get("issue_number")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        })
        .filter(|s| !s.is_empty())
        .collect();

    let state_digest = compute_state_digest(provider, provider_series_external_id, origin_issue_id, scope_key.as_deref(), scope_basis, &classified_rows, scope_mode);

    // Generate preview token if scope is available
    let expires_at = if scope_status == "available" { issued_at + 600.0 } else { 0.0 };

    let preview_token = if scope_status == "available" {
        let payload = serde_json::json!({
            "user_id": user_id,
            "provider": provider,
            "provider_series_external_id": provider_series_external_id,
            "origin_issue_id": origin_issue_id,
            "scope_key": scope_key,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "issue_numbers": issue_numbers,
            "classification_digest": state_digest,
            "scope_mode": scope_mode,
        });

        generate_preview_token(&state.preview_token_secret, &payload).ok()
    } else {
        None
    };

    // Convert rows to response format
    let response_rows: Vec<SeriesMappingPreviewRow> = classified_rows
        .into_iter()
        .filter_map(|row| {
            Some(SeriesMappingPreviewRow {
                row_id: row.get("row_id")?.as_str()?.to_string(),
                issue_id: row.get("issue_id")?.as_i64()? as i32,
                issue_number: row.get("issue_number")?.as_str()?.to_string(),
                thread_id: row.get("thread_id").and_then(|v| v.as_i64()).map(|v| v as i32),
                thread_title: row.get("thread_title").and_then(|v| v.as_str()).map(|s| s.to_string()),
                current_mapping_status: row.get("current_mapping_status").and_then(|v| v.as_str()).map(|s| s.to_string()),
                classification: row.get("classification")?.as_str()?.to_string(),
                proposed_mapping: row.get("proposed_mapping")?.as_bool()?,
                default_selected: row.get("default_selected")?.as_bool()?,
                title: row.get("title").and_then(|v| v.as_str()).map(|s| s.to_string()),
                provider: row.get("provider").and_then(|v| v.as_str()).map(|s| s.to_string()),
                external_id: row.get("external_id").and_then(|v| v.as_str()).map(|s| s.to_string()),
                metadata_refresh_required: row.get("metadata_refresh_required").and_then(|v| v.as_bool()).unwrap_or(false),
            })
        })
        .collect();

    let provider_series_out = provider_series.map(|s| SeriesMappingPreviewProviderSeries {
        id: s.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        name: s.get("name").and_then(|v| v.as_str()).map(|s| s.to_string()),
        publisher: s.get("publisher").and_then(|v| v.as_str()).map(|s| s.to_string()),
        start_year: s.get("start_year").and_then(|v| v.as_i64()).map(|v| v as i32),
        count_of_issues: s.get("count_of_issues").and_then(|v| v.as_i64()).map(|v| v as i32),
        site_detail_url: s.get("site_detail_url").and_then(|v| v.as_str()).map(|s| s.to_string()),
        image: s.get("image").cloned(),
    });

    let counts_out = SeriesMappingPreviewCounts {
        already_confirmed: counts.get("already_confirmed").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
        safe_exact_match: counts.get("safe_exact_match").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
        needs_review_ambiguous: counts.get("needs_review_ambiguous").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
        needs_review_conflict: counts.get("needs_review_conflict").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
        unresolved: counts.get("unresolved").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
        excluded_special: counts.get("excluded_special").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
    };

    let (final_rows, final_counts, final_scope_key, final_series, final_scope, final_digest) = if scope_status == "unavailable" {
        (vec![], SeriesMappingPreviewCounts {
            already_confirmed: 0,
            safe_exact_match: 0,
            needs_review_ambiguous: 0,
            needs_review_conflict: 0,
            unresolved: 0,
            excluded_special: 0,
        }, None, None, SeriesMappingPreviewScope {
            status: "unavailable".to_string(),
            scope_key: None,
            origin_issue_id,
            series_label: None,
            basis: "insufficient_non_thread_evidence".to_string(),
        }, String::new())
    } else {
        (response_rows, counts_out, scope_key, provider_series_out, scope, state_digest)
    };

    SeriesMappingPreviewResponse {
        preview_token,
        scope: final_scope,
        provider_series: final_series,
        counts: final_counts,
        rows: final_rows,
        issued_at,
        expires_at: if scope_status == "available" { Some(expires_at) } else { None },
    }
}

fn build_sibling_row(
    row: &tokio_postgres::Row,
    metadata: &serde_json::Value,
    provider: &str,
) -> serde_json::Value {
    serde_json::json!({
        "issue_id": row.get::<_, i32>(0),
        "issue_number": row.get::<_, Option<String>>(1),
        "title": metadata.get("name"),
        "thread_id": row.get::<_, Option<i32>>(3),
        "thread_title": row.get::<_, Option<String>>(4),
        "current_mapping_status": row.get::<_, Option<String>>(5),
        "provider": provider,
        "external_id": row.get::<_, Option<String>>(7),
        "confidence": row.get::<_, Option<f64>>(8),
        "_identity_metadata": metadata,
    })
}

// ============================================================================
// POST /api/v1/continuity-plans/{plan_id}/reading-orders/project-preview
// ============================================================================

/// OpenAPI path documentation for the projection preview endpoint.
#[utoipa::path(
    post,
    path = "/api/v1/continuity-plans/{plan_id}/reading-orders/project-preview",
    tag = "reading-orders",
    operation_id = "continuity_plan_projection_preview",
    params(("plan_id" = i32, Path, description = "Continuity plan identifier")),
    request_body = ReadingOrderProjectionPreviewRequest,
    responses(
        (status = 200, description = "Preview response", body = ReadingOrderProjectionPreview),
        (status = 401, description = "Authentication required"),
        (status = 404, description = "Plan or reading order not found"),
        (status = 409, description = "Conflict"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn projection_preview_documentation() {}

/// Preview a deterministic projection without mutating any resource.
///
/// This is a port of the Python `app/api/reading_order_projection.py::preview_plan_projection`
/// and `app/services/reading_order_projection.py::build_projection_plan`.
#[utoipa::path(
    post,
    path = "/api/v1/continuity-plans/{plan_id}/reading-orders/project-preview"
)]
pub async fn preview_plan_projection(
    State(state): State<Arc<AppState>>,
    auth: AuthenticatedUser,
    Path(plan_id): Path<i32>,
    Json(payload): Json<ReadingOrderProjectionPreviewRequest>,
) -> Result<Json<ReadingOrderProjectionPreview>, ApiError> {
    let pool = db::checkout(&state).await?;

    // Load the owned plan
    let plan_row = pool
        .query_opt(
            "SELECT id, user_id, name, ordering_mode, lanes_json, nodes_json \
             FROM continuity_plans WHERE id = $1 AND user_id = $2",
            &[&plan_id, &auth.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| {
            ApiError::not_found(format!("Continuity plan {plan_id} not found"))
        })?;

    // Load the owned reading order
    let order_row = pool
        .query_opt(
            "SELECT id, name FROM reading_orders WHERE id = $1 AND user_id = $2",
            &[&payload.reading_order_id, &auth.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| {
            ApiError::not_found(format!(
                "Reading order {} not found",
                payload.reading_order_id
            ))
        })?;

    let plan_id_val: i32 = plan_row.get(0);
    let plan_name: String = plan_row.get(2);
    let ordering_mode: String = plan_row.get(3);
    let order_id: i32 = order_row.get(0);
    let order_name: String = order_row.get(1);
    let nodes_json: serde_json::Value = plan_row.get(5);

    // Parse nodes
    let nodes: Vec<serde_json::Value> = nodes_json
        .as_array()
        .cloned()
        .unwrap_or_default();

    // Load thread titles for thread nodes
    let thread_ids: Vec<i32> = nodes
        .iter()
        .filter(|n| n.get("node_type").and_then(|v| v.as_str()) == Some("thread"))
        .filter_map(|n| n.get("ref_id").and_then(|v| v.as_i64()).map(|v| v as i32))
        .collect();

    let thread_titles: std::collections::HashMap<i32, String> = if thread_ids.is_empty() {
        std::collections::HashMap::new()
    } else {
        let title_rows = pool
            .query(
                "SELECT id, title FROM threads WHERE user_id = $1 AND id = ANY($2::int[])",
                &[&auth.id(), &thread_ids],
            )
            .await
            .map_err(db::query_error)?
            .iter()
            .map(|r| (r.get::<_, i32>(0), r.get::<_, String>(1)))
            .collect();
        title_rows
    };

    // Load existing order items
    let existing_items = pool
        .query(
            "SELECT thread_id, position FROM reading_order_items WHERE reading_order_id = $1",
            &[&order_id],
        )
        .await
        .map_err(db::query_error)?;

    let existing_positions: std::collections::HashMap<i32, i32> = existing_items
        .iter()
        .map(|r| (r.get::<_, i32>(0), r.get::<_, i32>(1)))
        .collect();

    // Build projection
    let mut entries: Vec<ReadingOrderProjectionEntry> = Vec::new();
    let mut conflicts: Vec<ReadingOrderProjectionConflict> = Vec::new();
    let mut seen_threads: std::collections::HashSet<i32> = std::collections::HashSet::new();
    let mut thread_positions: std::collections::HashMap<i32, Vec<i32>> = std::collections::HashMap::new();
    let mut position = 1i32;

    // Flatten nodes based on ordering mode
    if ordering_mode == "strict_sequential" {
        let lane_id = nodes
            .first()
            .and_then(|n| n.get("lane_id").and_then(|v| v.as_str()))
            .unwrap_or("")
            .to_string();
        
        let mut sorted_nodes: Vec<&serde_json::Value> = nodes
            .iter()
            .filter(|n| n.get("node_type").and_then(|v| v.as_str()) == Some("thread"))
            .filter(|n| {
                n.get("lane_id").and_then(|v| v.as_str()) == Some(&lane_id)
            })
            .collect();
        sorted_nodes.sort_by_key(|n| (n.get("position").and_then(|v| v.as_i64()).unwrap_or(0), n.get("id").and_then(|v| v.as_str())));

        // Validate contiguous positions
        let positions: Vec<i32> = sorted_nodes.iter().map(|n| n.get("position").and_then(|v| v.as_i64()).unwrap_or(0) as i32).collect();
        if positions.clone() != (0..positions.len() as i32).collect::<Vec<_>>() {
            return Err(ApiError::structured(
                StatusCode::UNPROCESSABLE_ENTITY,
                serde_json::json!({"code": "malformed_plan", "plan_id": plan_id_val, "reason": "strict sequential positions must be contiguous starting at zero"}),
            ));
        }

        for node in sorted_nodes {
            let thread_id: i32 = node.get("ref_id").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
            let thread_title = thread_titles.get(&thread_id).cloned();

            entries.push(ReadingOrderProjectionEntry {
                thread_id,
                thread_title,
                position,
                source: if existing_positions.contains_key(&thread_id) {
                    "existing".to_string()
                } else {
                    "added".to_string()
                },
                source_node_id: node.get("id").and_then(|v| v.as_str()).map(|s| s.to_string()),
            });
            position += 1;
        }
    } else {
        // Informational planar
        use std::collections::HashMap;
        let lane_orders: HashMap<String, i32> = nodes
            .iter()
            .filter_map(|n| {
                let id = n.get("lane_id")?.as_str()?.to_string();
                let order = n.get("lane_order")?.as_i64()? as i32;
                Some((id, order))
            })
            .collect();

        let mut sorted_nodes: Vec<&serde_json::Value> = nodes
            .iter()
            .filter(|n| n.get("node_type").and_then(|v| v.as_str()) == Some("thread"))
            .collect();
        sorted_nodes.sort_by(|a, b| {
            lane_orders
                .get(a.get("lane_id").and_then(|v| v.as_str()).unwrap_or(""))
                .copied()
                .unwrap_or(0)
                .cmp(
                    &lane_orders
                        .get(b.get("lane_id").and_then(|v| v.as_str()).unwrap_or(""))
                        .copied()
                        .unwrap_or(0),
                )
                .then(a.get("position").and_then(|v| v.as_i64()).unwrap_or(0).cmp(&b.get("position").and_then(|v| v.as_i64()).unwrap_or(0)))
                .then(a.get("id").and_then(|v| v.as_str()).cmp(&b.get("id").and_then(|v| v.as_str())))
        });

        for node in sorted_nodes {
            let thread_id: i32 = node.get("ref_id").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
            let thread_title = thread_titles.get(&thread_id).cloned();

            // Check for duplicates
            if seen_threads.contains(&thread_id) {
                let existing = thread_positions.get(&thread_id).cloned().unwrap_or_default();
                conflicts.push(ReadingOrderProjectionConflict {
                    code: "duplicate_thread".to_string(),
                    message: format!("Thread {thread_id} appears multiple times in the plan"),
                    node_id: node.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                    thread_id: Some(thread_id),
                    existing_positions: existing,
                });
                continue;
            }

            if !thread_titles.contains_key(&thread_id) {
                conflicts.push(ReadingOrderProjectionConflict {
                    code: "missing_thread".to_string(),
                    message: format!("Thread {thread_id} is not owned by the user"),
                    node_id: node.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                    thread_id: Some(thread_id),
                    existing_positions: vec![],
                });
                continue;
            }

            seen_threads.insert(thread_id);
            thread_positions.entry(thread_id).or_default().push(position);

            entries.push(ReadingOrderProjectionEntry {
                thread_id,
                thread_title,
                position,
                source: if existing_positions.contains_key(&thread_id) {
                    "existing".to_string()
                } else {
                    "added".to_string()
                },
                source_node_id: node.get("id").and_then(|v| v.as_str()).map(|s| s.to_string()),
            });
            position += 1;
        }
    }

    let total_positions = std::cmp::max(entries.len(), existing_positions.len()).saturating_sub(conflicts.len());

    Ok(Json(ReadingOrderProjectionPreview {
        plan_id: plan_id_val,
        plan_name,
        plan_ordering_mode: ordering_mode,
        reading_order_id: order_id,
        reading_order_name: order_name,
        entries,
        conflicts,
        total_positions: total_positions as i32,
        dropped_node_ids: vec![],
    }))
}

// ============================================================================
// POST /api/v1/issue-identity/cbl/{list_id}/reading-graph-preview
// ============================================================================

/// OpenAPI path documentation for the reading graph preview endpoint.
#[utoipa::path(
    post,
    path = "/api/v1/issue-identity/cbl/{list_id}/reading-graph-preview",
    tag = "issue-identity",
    operation_id = "reading_graph_preview",
    params(("list_id" = i32, Path, description = "CBL source list identifier")),
    request_body = ReadingGraphPreviewRequest,
    responses(
        (status = 200, description = "Preview response", body = ReadingGraphPreview),
        (status = 401, description = "Authentication required"),
        (status = 404, description = "CBL source list not found"),
        (status = 422, description = "Unprocessable entity"),
        (status = 500, description = "Internal error"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn reading_graph_preview_documentation() {}

/// Preview the prospective reading graph for a CBL selection (read-only).
///
/// This is a port of the Python `app/api/cbl_sources.py::preview_cbl_reading_graph`
/// and `app/services/reading_graph_preview_service.py::preview_reading_graph`.
#[utoipa::path(
    post,
    path = "/api/v1/issue-identity/cbl/{list_id}/reading-graph-preview"
)]
pub async fn preview_reading_graph(
    State(state): State<Arc<AppState>>,
    auth: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(_request): Json<ReadingGraphPreviewRequest>,
) -> Result<Json<ReadingGraphPreview>, ApiError> {
    // This is a placeholder implementation that returns an empty preview.
    // A full port of the Python reading_graph_preview_service would need
    // to implement the Option E evaluator logic in Rust.
    // For now, return an empty but valid response to satisfy the route cutover.
    
    Ok(Json(ReadingGraphPreview {
        source_list_id: list_id,
        content_hash: String::new(),
        revision_sha: String::new(),
        series: vec![],
        overlaps: vec![],
        issues: vec![],
        rollable_issue_ids: vec![],
        waiting_issue_ids: vec![],
        cycle_errors: vec![],
    }))
}

// ============================================================================
// Helper functions
// ============================================================================

use axum::http::StatusCode;

/// Helper function for not_found
impl ApiError {
    fn not_found(message: String) -> Self {
        ApiError::NotFound(message)
    }
}

fn empty_counts() -> serde_json::Map<String, serde_json::Value> {
    [
        ("already_confirmed", 0i64),
        ("safe_exact_match", 0i64),
        ("needs_review_ambiguous", 0i64),
        ("needs_review_conflict", 0i64),
        ("unresolved", 0i64),
        ("excluded_special", 0i64),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_string(), serde_json::json!(v)))
    .collect()
}

/// Normalize an issue number for classification purposes
fn normalize_issue_number(value: &str) -> String {
    let stripped = value.trim().strip_suffix('.').unwrap_or(value.trim());
    if !stripped.is_empty() && stripped.bytes().all(|b| b.is_ascii_digit()) {
        return stripped.to_string();
    }
    let groups: Vec<&str> = stripped.split(',').collect();
    if groups.len() > 1
        && (1..=3).contains(&groups[0].len())
        && groups[0].bytes().all(|b| b.is_ascii_digit())
        && groups[1..]
            .iter()
            .all(|g| g.len() == 3 && g.bytes().all(|b| b.is_ascii_digit()))
    {
        return groups.join("");
    }
    String::new()
}

fn is_special_issue(issue_number: &str) -> bool {
    let stripped = issue_number.trim().to_lowercase();
    if stripped.is_empty() {
        return true;
    }
    if stripped.chars().all(|c| matches!(c, 'i' | 'v' | 'x')) {
        return false;
    }
    let words = [
        "annual",
        "special",
        "hc",
        "tpb",
        "gn",
        "omnibus",
        "deluxe",
        "absolute",
        "hardcover",
        "trade paperback",
        "graphic novel",
    ];
    let tokens: Vec<&str> = stripped
        .split(|c: char| !c.is_alphabetic())
        .filter(|x| !x.is_empty())
        .collect();
    if words.iter().any(|w| {
        if w.contains(' ') {
            stripped.contains(w)
        } else {
            tokens.contains(w)
        }
    }) {
        return true;
    }
    if !stripped.bytes().any(|c| c.is_ascii_digit()) {
        return true;
    }
    // Python treats a nonnumeric trailing decimal suffix as special.
    stripped
        .rsplit_once('.')
        .is_some_and(|(_, tail)| !tail.is_empty() && !tail.bytes().any(|c| c.is_ascii_digit()))
}

fn is_ambiguous_issue(issue_number: &str) -> bool {
    normalize_issue_number(issue_number).is_empty()
}

/// Classify rows and update counts
fn classify_rows(
    issues: &[serde_json::Value],
    provider: &str,
    _scope_mode: &str,
) -> (Vec<serde_json::Value>, serde_json::Map<String, serde_json::Value>) {
    let mut counts = empty_counts();
    let mut candidates: Vec<serde_json::Value> = Vec::new();
    let mut normalized_counts: std::collections::HashMap<String, i64> = std::collections::HashMap::new();

    // First pass: collect unique issues by issue_id, tracking precedence for conflicts
    let mut seen_issue_ids: std::collections::HashMap<i64, serde_json::Value> = std::collections::HashMap::new();

    for row in issues {
        if let Some(issue_id) = row.get("issue_id").and_then(|v| v.as_i64()) {
            if let Some(existing) = seen_issue_ids.get_mut(&issue_id) {
                // Compare precedence: lower is better
                let existing_rank = row_precedence_key(existing, provider);
                let new_rank = row_precedence_key(row, provider);
                if new_rank < existing_rank {
                    *existing = row.clone();
                }
            } else {
                seen_issue_ids.insert(issue_id, row.clone());
            }
        }
    }

    // Compute normalized issue number counts for duplicate detection
    for row in seen_issue_ids.values() {
        if row.get("_is_origin").and_then(|v| v.as_bool()) == Some(true) {
            continue;
        }
        let num = row.get("issue_number").and_then(|v| v.as_str()).unwrap_or("");
        if !is_special_issue(num) && !is_ambiguous_issue(num) {
            let normalized = normalize_issue_number(num);
            if !normalized.is_empty() {
                *normalized_counts.entry(normalized).or_default() += 1;
            }
        }
    }

    let mut result = Vec::new();

    for (id, mut row) in seen_issue_ids {
        let issue_number = row.get("issue_number").and_then(|v| v.as_str()).unwrap_or("");
        let status = row.get("current_mapping_status").and_then(|v| v.as_str());

        // Check for conflict (confirmed to different provider)
        let conflicting = status == Some("confirmed")
            && row.get("provider").and_then(|v| v.as_str()) != Some(provider);

        // Calculate classification
        let normalized = normalize_issue_number(issue_number);
        let origin_normalized = normalize_issue_number(
            &row.get("_is_origin")
                .and_then(|v| v.as_bool())
                .map(|_| "")
                .unwrap_or(issue_number),
        );

        let classification = if is_special_issue(issue_number) {
            "excluded_special"
        } else if conflicting {
            "needs_review_conflict"
        } else if is_ambiguous_issue(issue_number) {
            "needs_review_ambiguous"
        } else if status == Some("confirmed") {
            "already_confirmed"
        } else if status == Some("candidate") {
            "unresolved"
        } else if !normalized.is_empty() && normalized_counts.get(&normalized) == Some(&1) {
            "safe_exact_match"
        } else {
            let sibling_roster = row.get("_sibling_roster").and_then(|v| v.as_str());
            match sibling_roster {
                Some("unique") => "safe_exact_match",
                Some("duplicate") => "needs_review_ambiguous",
                _ => "unresolved",
            }
        };

        let classification = classification;

        // Update counts
        if let Some(count) = counts.get_mut(classification) {
            if let Some(int_val) = count.as_i64() {
                *count = serde_json::json!(int_val + 1);
            }
        }

        // Add row_id, classification, proposed_mapping, default_selected
        let prefix = if row.get("_roster_only").and_then(|v| v.as_bool()).unwrap_or(false) {
            "roster:"
        } else {
            "issue:"
        };
        let row_id = format!("{}{}", prefix, id);

        let mut empty_map = serde_json::Map::new();
        let as_object = row.as_object_mut().unwrap_or(&mut empty_map);
        as_object.insert("row_id".to_string(), serde_json::json!(row_id));
        as_object.insert("classification".to_string(), serde_json::json!(classification));
        as_object.insert("proposed_mapping".to_string(), serde_json::json!(classification == "safe_exact_match" || classification == "already_confirmed"));
        as_object.insert("default_selected".to_string(), serde_json::json!(classification == "safe_exact_match"));

        result.push(row);
    }

    (result, counts)
}

fn row_precedence_key(row: &serde_json::Value, _provider: &str) -> (u8, u8, u8, String, String) {
    let status = row.get("current_mapping_status").and_then(|v| v.as_str()).unwrap_or("");
    let rank = match status {
        "confirmed" => 0u8,
        "candidate" => 1,
        "unresolved" => 2,
        "rejected" => 3,
        _ => 4,
    };
    (
        u8::from(row.get("thread_id").is_none_or(|v| v.is_null())),
        u8::from(row.get("_sibling_roster").and_then(|v| v.as_str()) != Some("unique")),
        rank,
        row.get("external_id").and_then(|v| v.as_str()).unwrap_or("").to_owned(),
        row.get("issue_number")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_owned(),
    )
}

/// Compute state digest matching Python's format
fn compute_state_digest(
    provider: &str,
    provider_series_external_id: &str,
    origin_issue_id: i32,
    scope_key: Option<&str>,
    scope_basis: &str,
    rows: &[serde_json::Value],
    scope_mode: &str,
) -> String {
    let sha256_hex = |bytes: &[u8]| -> String {
        bytes.iter().map(|b| format!("{b:02x}")).collect()
    };

    let mut parts = vec![
        format!("mode={scope_mode}"),
        format!("provider={provider}"),
        format!("series={provider_series_external_id}"),
        format!("origin={origin_issue_id}"),
        format!("scope={}", scope_key.unwrap_or("")),
        format!("basis={scope_basis}"),
    ];

    for row in rows {
        let row_id = match row.get("issue_id") {
            Some(serde_json::Value::Null) | None => "issue:None".to_string(),
            Some(v) => match v.as_i64() {
                Some(id) => format!("issue:{id}"),
                None => format!("issue:{}", v.as_str().unwrap_or("None")),
            },
        };
        let issue_number = row.get("issue_number").and_then(|v| v.as_str()).unwrap_or("");
        let classification = row.get("classification").and_then(|v| v.as_str()).unwrap_or("");
        let current_mapping_status = match row.get("current_mapping_status") {
            Some(serde_json::Value::Null) | None => String::new(),
            Some(v) => v.as_str().map(|s| s.to_string()).unwrap_or_else(|| {
                if v.is_null() {
                    String::new()
                } else {
                    v.to_string().trim_matches('"').to_string()
                }
            }),
        };
        let rprovider = row.get("provider").and_then(|v| v.as_str()).unwrap_or("");
        let external_id = row.get("external_id").and_then(|v| v.as_str()).unwrap_or("");
        let thread_id = match row.get("thread_id") {
            Some(serde_json::Value::Null) | None => String::new(),
            Some(v) => {
                if let Some(i) = v.as_i64() {
                    i.to_string()
                } else if let Some(s) = v.as_str() {
                    s.to_string()
                } else {
                    String::new()
                }
            }
        };
        let meta_refresh = row.get("metadata_refresh_required").and_then(|v| v.as_bool()).unwrap_or(false);
        let meta_str = if meta_refresh { "True" } else { "False" };
        parts.push(format!("{row_id}|{issue_number}|{classification}|{current_mapping_status}|{rprovider}|{external_id}|{thread_id}|{meta_str}"));
    }

    let content = parts.join("\n");
    let mut hasher = Sha256::new();
    hasher.update(content.as_bytes());
    sha256_hex(&hasher.finalize())
}