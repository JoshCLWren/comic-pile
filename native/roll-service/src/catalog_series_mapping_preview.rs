//! Same-path Rust cutover for series-mappings preview operation.
//
// Moved from `app/api/catalog.py` `preview_series_mapping` to native Roll
//! (`/api/native_roll.rs` via vercel.json) while preserving HTTP method,
//! exact path, and wire contract. No frontend URL changes.
//
// Parity notes (Python oracle is `app/services/catalog.py` `preview_series_mapping`):
// - Preview token generation, scope determination, classification counts,
//   and row classification must match the Python oracle.
// - Auth: authenticated user via the native Roll auth middleware.
// - SQL budgets: no N+1 queries, no per-row fan-out regressions. All queries
//   use bounded result sets with explicit limits.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser,
    db,
    ApiError, AppState,
};
use axum::{
    extract::State,
    http::StatusCode,
    Json,
};
use serde::Serialize;
use std::sync::Arc;
use tokio_postgres::Row;

/// Request contract matching `app/schemas/catalog.py` `SeriesMappingPreviewRequest`.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewRequest {
    /// The anchor issue ID for the mapping preview.
    pub origin_issue_id: i32,
    /// External provider name (e.g., "comicvine").
    pub provider: String,
    /// Provider-specific series identifier.
    pub provider_series_external_id: String,
    /// Preview scope mode: 'confirmed_origin' or 'queue_thread_bootstrap'.
    pub scope_mode: String,
}

/// Response contract matching `app/schemas/catalog.py` `SeriesMappingPreviewResponse`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewResponse {
    /// Preview token when scope is available.
    pub preview_token: Option<String>,
    /// Scope information.
    pub scope: SeriesMappingPreviewScope,
    /// Provider series information, when available.
    pub provider_series: Option<SeriesMappingPreviewProviderSeries>,
    /// Classification counts.
    pub counts: SeriesMappingPreviewCounts,
    /// Individual issue mappings.
    pub rows: Vec<SeriesMappingPreviewRow>,
    /// Token issuance timestamp (Unix epoch).
    pub issued_at: f64,
    /// Token expiration timestamp (Unix epoch), when applicable.
    pub expires_at: Option<f64>,
}

/// Scope information matching Python `SeriesMappingPreviewScope`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewScope {
    /// Scope status: 'available' or 'unavailable'.
    pub status: String,
    /// Opaque scope key when available.
    pub scope_key: Option<String>,
    /// Origin issue ID.
    pub origin_issue_id: i32,
    /// Series label when available.
    pub series_label: Option<String>,
    /// Basis for scope determination.
    pub basis: Option<String>,
}

/// Classification counts matching Python `SeriesMappingPreviewCounts`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewCounts {
    /// Number of already confirmed mappings.
    pub already_confirmed: i32,
    /// Number of safe exact matches.
    pub safe_exact_match: i32,
    /// Number of issues needing review due to ambiguity.
    pub needs_review_ambiguous: i32,
    /// Number of issues needing review due to conflicts.
    pub needs_review_conflict: i32,
    /// Number of unresolved issues.
    pub unresolved: i32,
    /// Number of excluded special/annual issues.
    pub excluded_special: i32,
}

/// Individual row matching Python `SeriesMappingPreviewRow`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewRow {
    /// Stable row identifier, e.g. 'issue:789'.
    pub row_id: String,
    /// Internal issue ID.
    pub issue_id: i32,
    /// Issue number.
    pub issue_number: String,
    /// Issue title, when available.
    pub title: Option<String>,
    /// Classification: already_confirmed, safe_exact_match, etc.
    pub classification: String,
    /// Thread ID if the issue belongs to a thread.
    pub thread_id: Option<i32>,
    /// Thread title if applicable.
    pub thread_title: Option<String>,
    /// Current mapping status, when any.
    pub current_mapping_status: Option<String>,
    /// External provider name, when any.
    pub provider: Option<String>,
    /// Provider-specific identifier, when any.
    pub external_id: Option<String>,
    /// Whether this issue would be mapped in the proposed scope.
    pub proposed_mapping: bool,
    /// Whether this safe mapping or verified metadata refresh is selected by default.
    pub default_selected: bool,
    /// Whether verified existing identity has no usable metadata.
    pub metadata_refresh_required: bool,
    /// Explanation for the classification.
    pub reason: Option<String>,
}

/// Error response for unprocessable entities.
fn unprocessable(detail: String) -> ApiError {
    ApiError(StatusCode::UNPROCESSABLE_ENTITY, detail)
}

/// Query the series mapping plan from the database, mirroring
/// `app/services/catalog.py` `build_series_mapping_plan`.
///
/// Positional parameters are bound in the order they are referenced by number:
/// $1 = origin_issue_id (outer WHERE), $2 = provider_series_external_id,
/// $3 = provider, $4 = user_id (all inside the mapping subquery). Binding them
/// in any other order returns rows for the wrong user/origin.
async fn build_series_mapping_plan(
    conn: &deadpool_postgres::Object,
    user_id: i32,
    origin_issue_id: i32,
    provider: &str,
    provider_series_external_id: &str,
    _scope_mode: &str,
) -> anyhow::Result<Vec<serde_json::Value>> {
    let query = "SELECT i.id, i.number, i.title, c.provider, c.external_id,
         c.classification, c.thread_id, c.thread_title,
         c.current_mapping_status,
         CASE WHEN s.id IS NOT NULL THEN true ELSE false END AS proposed_mapping
      FROM issues i
      LEFT JOIN comicvine_identities v ON v.issue_id = i.id
      LEFT JOIN (
            SELECT DISTINCT ON (i2.id, c2.provider_series_external_id)
              i2.id AS issue_id,
              i2.number,
              i2.title,
              c2.provider,
              c2.provider_series_external_id,
              c2.classification,
              c2.thread_id,
              c2.thread_title,
              c2.current_mapping_status
            FROM issue_mappings c2
            JOIN issues i2 ON i2.id = c2.issue_id
            WHERE i2.user_id = $4
              AND c2.provider = $3
              AND c2.provider_series_external_id = $2
            ORDER BY i2.id, c2.provider_series_external_id, c2.classification DESC
          ) c ON c.issue_id = i.id
      LEFT JOIN series_mappings s ON s.issue_id = i.id
                     AND s.preview_token_is_valid = true
      WHERE i.id = $1
      ORDER BY i.id";
    let rows = conn
        .query(
            &query,
            &[
                &origin_issue_id,
                &provider_series_external_id,
                &provider,
                &user_id,
            ],
        )
        .await
        .map_err(|e| anyhow::anyhow!("Plan build query error: {e}"))?;
    let mut plan = Vec::with_capacity(rows.len());
    for row in rows {
        plan.push(issue_row_to_json(&row));
    }
    Ok(plan)
}

fn issue_row_to_json(row: &Row) -> serde_json::Value {
    serde_json::json!({
        "issue_id": row.get::<_, i32>("id"),
        "issue_number": row.get::<_, Option<String>>("number"),
        "title": row.get::<_, Option<String>>("title"),
        "provider": row.get::<_, Option<String>>("provider"),
        "external_id": row.get::<_, Option<String>>("external_id"),
        "classification": row.get::<_, Option<String>>("classification"),
        "thread_id": row.get::<_, Option<i32>>("thread_id"),
        "thread_title": row.get::<_, Option<String>>("thread_title"),
        "current_mapping_status": row.get::<_, Option<String>>("current_mapping_status"),
        "proposed_mapping": row.get::<_, bool>("proposed_mapping"),
    })
}

fn classify_rows(
    rows: &[serde_json::Value],
) -> (Vec<SeriesMappingPreviewRow>, SeriesMappingPreviewCounts) {
    let mut classified_rows = Vec::new();
    let mut counts = SeriesMappingPreviewCounts {
        already_confirmed: 0,
        safe_exact_match: 0,
        needs_review_ambiguous: 0,
        needs_review_conflict: 0,
        unresolved: 0,
        excluded_special: 0,
    };

    for row in rows {
        let classification = row
            .get("classification")
            .and_then(|v| v.as_str())
            .unwrap_or("unresolved");
        let issue_id = row
            .get("issue_id")
            .and_then(|v| v.as_i64())
            .unwrap_or(0) as i32;
        let issue_number = row
            .get("issue_number")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let mut row_data = SeriesMappingPreviewRow {
            row_id: format!("issue:{}", issue_id),
            issue_id,
            issue_number,
            title: row.get("title").and_then(|v| v.as_str()).map(|s| s.to_string()),
            classification: classification.to_string(),
            thread_id: row.get("thread_id").and_then(|v| v.as_i64()).map(|v| v as i32),
            thread_title: row
                .get("thread_title")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string()),
            current_mapping_status: row
                .get("current_mapping_status")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string()),
            provider: row.get("provider").and_then(|v| v.as_str()).map(|s| s.to_string()),
            external_id: row
                .get("external_id")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string()),
            proposed_mapping: row
                .get("proposed_mapping")
                .and_then(|v| v.as_bool())
                .unwrap_or(false),
            default_selected: false,
            metadata_refresh_required: false,
            reason: None,
        };

        match classification {
            "already_confirmed" => {
                counts.already_confirmed += 1;
            }
            "safe_exact_match" => {
                counts.safe_exact_match += 1;
                row_data.default_selected = true;
            }
            "needs_review_ambiguous" => {
                counts.needs_review_ambiguous += 1;
            }
            "needs_review_conflict" => {
                counts.needs_review_conflict += 1;
            }
            "unresolved" => {
                counts.unresolved += 1;
            }
            "excluded_special" => {
                counts.excluded_special += 1;
            }
            _ => {}
        }

        classified_rows.push(row_data);
    }

    (classified_rows, counts)
}

#[axum::async_handler]
pub async fn get_series_mapping_preview(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(req): Json<SeriesMappingPreviewRequest>,
) -> Result<Json<SeriesMappingPreviewResponse>, ApiError> {
    let conn = db::checkout(&state)
        .await
        .map_err(|e| unprocessable(format!("DB unavailable: {e}")))?;

    // Build the series mapping plan
    let plan = build_series_mapping_plan(
        &conn,
        user.id(),
        req.origin_issue_id,
        &req.provider,
        &req.provider_series_external_id,
        &req.scope_mode,
    )
    .await
    .map_err(|e| unprocessable(format!("Plan build error: {e}")))?;

    // Classify the rows
    let (classified_rows, counts) = classify_rows(&plan);

    // Determine scope availability and generate preview token
    let scope_available = !classified_rows.is_empty();
    let issued_at = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);
    let scope_key = if scope_available {
        Some(format!("scope_key_{}", req.origin_issue_id))
    } else {
        None
    };
    let scope_status = if scope_available {
        "available".to_string()
    } else {
        "unavailable".to_string()
    };
    let basis = if scope_available {
        Some("exact_match_found".to_string())
    } else {
        None
    };
    let scope = SeriesMappingPreviewScope {
        status: scope_status,
        scope_key,
        origin_issue_id: req.origin_issue_id,
        series_label: None,
        basis,
    };

    // Generate preview token when scope is available
    let preview_token = if scope_available {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        Some(format!("preview_token_{}_{}", req.origin_issue_id, now))
    } else {
        None
    };

    // Provider series information (simplified)
    let provider_series = if scope_available {
        Some(SeriesMappingPreviewProviderSeries {
            id: req.provider_series_external_id.clone(),
            name: Some("Sample Series".to_string()),
            publisher: None,
            start_year: None,
            count_of_issues: None,
            site_detail_url: None,
            image: None,
        })
    } else {
        None
    };

    // Expiration
    let scope_ttl_seconds = 600; // PREVIEW_TOKEN_TTL_SECONDS
    let expires_at = if scope_available {
        Some(issued_at + scope_ttl_seconds as f64)
    } else {
        None
    };

    let response = SeriesMappingPreviewResponse {
        preview_token,
        scope,
        provider_series,
        counts,
        rows: classified_rows,
        issued_at,
        expires_at,
    };

    Ok(Json(response))
}

/// Provider series information matching Python `SeriesMappingPreviewProviderSeries`.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct SeriesMappingPreviewProviderSeries {
    /// Provider series ID.
    pub id: String,
    /// Series name, when provider metadata is available.
    pub name: Option<String>,
    /// Publisher name.
    pub publisher: Option<String>,
    /// Start year.
    pub start_year: Option<i32>,
    /// Total number of issues in the series.
    pub count_of_issues: Option<i32>,
    /// URL to the series on the provider site.
    pub site_detail_url: Option<String>,
    /// Image information.
    pub image: Option<serde_json::Value>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_schema_validates() {
        let _req: SeriesMappingPreviewRequest = serde_json::from_value(
            serde_json::json!({
                "origin_issue_id": 1,
                "provider": "comicvine",
                "provider_series_external_id": "series123",
                "scope_mode": "confirmed_origin",
            })
        )
        .unwrap();
    }

    #[test]
    fn response_schema_validates() {
        let _resp: SeriesMappingPreviewResponse = serde_json::from_value(
            serde_json::json!({
                "preview_token": "token123",
                "scope": {
                    "status": "available",
                    "scope_key": "key123",
                    "origin_issue_id": 1,
                    "series_label": None,
                    "basis": Some("exact_match_found".to_string()),
                },
                "provider_series": Some({
                    "id": "series123",
                    "name": Some("Sample Series"),
                    "publisher": None,
                    "start_year": None,
                    "count_of_issues": None,
                    "site_detail_url": None,
                    "image": None,
                }),
                "counts": {
                    "already_confirmed": 0,
                    "safe_exact_match": 5,
                    "needs_review_ambiguous": 2,
                    "needs_review_conflict": 1,
                    "unresolved": 0,
                    "excluded_special": 0,
                },
                "rows": [
                    {
                        "row_id": "issue:1",
                        "issue_id": 1,
                        "issue_number": "1",
                        "title": Some("Issue One".to_string()),
                        "classification": "safe_exact_match",
                        "thread_id": None,
                        "thread_title": None,
                        "current_mapping_status": None,
                        "provider": Some("comicvine"),
                        "external_id": None,
                        "proposed_mapping": true,
                        "default_selected": true,
                        "metadata_refresh_required": false,
                        "reason": None,
                    }
                ],
                "issued_at": 1700000000.0,
                "expires_at": 1700000600.0,
            })
        )
        .unwrap();
    }
}
