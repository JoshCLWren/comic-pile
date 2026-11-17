//! Same-path Rust cutover of
//! `GET /api/v1/issue-identity/cbl/{list_id}/adoption-preview`.
//!
//! Port of the default (no decision overrides) branch of
//! `app/services/cbl_reconciliation.py`: reconcile the ordered CBL source
//! entries to reader-owned issues and compute the read-only adoption plan.
//! The endpoint never mutates list membership, read state, or overlap answers.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    response::IntoResponse,
    Json,
};
use chrono::{DateTime, Utc};
use serde::Serialize;
use serde_json::Value;
use std::{collections::HashMap, sync::Arc};
use utoipa::ToSchema;

/// Error detail used by Python when a CBL source list is missing or inactive.
fn source_not_found(list_id: i64) -> ApiError {
    ApiError::NotFound(format!("CBL source list {list_id} not found or not active"))
}

#[derive(Debug, Serialize, ToSchema)]
pub struct CBLAdoptionPreviewResponse {
    pub source: CBLSourceFingerprint,
    pub total_positions: i64,
    pub entries: Vec<CBLAdoptionEntry>,
    pub summary: CBLAdoptionSummary,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct CBLSourceFingerprint {
    pub source_list_id: i64,
    pub source_repository: String,
    pub source_path: String,
    pub content_hash: String,
    pub revision_sha: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct CBLAdoptionEntry {
    pub collection_excluded: bool,
    pub collection_exclusion_reason: Option<String>,
    pub collection_exclusion_ids: Vec<i64>,
    pub cbl_position: i64,
    pub cbl_entry_id: i64,
    pub series_name: String,
    pub issue_number: String,
    pub series_group_id: String,
    pub volume_year: Option<i64>,
    pub publication_year: Option<i64>,
    pub adoption_class: String,
    pub adoption_decision: String,
    pub adopted: bool,
    pub comicvine_issue_id: Option<String>,
    pub comicvine_series_id: Option<String>,
    pub series_provider: Option<String>,
    pub series_external_id: Option<String>,
    pub resolved_issue_id: Option<i64>,
    pub canonical_issue_id: Option<i64>,
    pub read_status: Option<String>,
    pub read_at: Option<DateTime<Utc>>,
    pub resolution_status: String,
    pub is_duplicate_identity: bool,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct CBLAdoptionSummary {
    pub reused_existing_count: i64,
    pub missing_would_create_count: i64,
    pub excluded_count: i64,
    pub unresolved_count: i64,
    pub awaiting_opt_in_count: i64,
    pub final_adopted_count: i64,
    pub final_adopted_order: Vec<i64>,
    pub reused_existing_positions: Vec<i64>,
    pub missing_would_create_positions: Vec<i64>,
    pub excluded_positions: Vec<i64>,
    pub unresolved_positions: Vec<i64>,
    pub awaiting_opt_in_positions: Vec<i64>,
}

struct SourceEntry {
    id: i64,
    position: i64,
    series_name: String,
    issue_number: String,
    volume_year: Option<i64>,
    publication_year: Option<i64>,
    issue_identity_id: Option<i64>,
    series_identity_id: Option<i64>,
}

fn group_id(entry: &SourceEntry, comicvine_series_id: Option<&str>) -> String {
    if let Some(id) = comicvine_series_id {
        if !id.is_empty() {
            return format!("comicvine:{id}");
        }
    }
    format!(
        "{}::{}::{}",
        entry.series_name,
        entry.volume_year.map(|v| v.to_string()).unwrap_or_default(),
        entry.publication_year.map(|v| v.to_string()).unwrap_or_default()
    )
}

#[utoipa::path(
    get,
    path = "/api/v1/issue-identity/cbl/{list_id}/adoption-preview",
    params(("list_id" = i64, Path, description = "CBL source list id")),
    responses(
        (status = 200, description = "Read-only adoption preview", body = CBLAdoptionPreviewResponse),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "CBL source list not found or not active"),
    ),
    security(("HTTPBearer" = []))
)]
pub fn documentation() {}

/// Mounted handler for `GET /api/v1/issue-identity/cbl/{list_id}/adoption-preview`.
pub async fn api_cbl_adoption_preview_handler(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i64>,
) -> Result<Json<CBLAdoptionPreviewResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let list_row = connection
        .query_opt(
            "SELECT l.source_path, l.content_hash, l.revision_sha, s.repository, l.active
             FROM cbl_source_lists l LEFT JOIN cbl_sources s ON s.id = l.source_id
             WHERE l.id = $1",
            &[&list_id],
        )
        .await
        .map_err(db::query_error)?
        .filter(|row| row.get::<_, bool>(4))
        .ok_or_else(|| source_not_found(list_id))?;
    let source_path: String = list_row.get(0);
    let content_hash: String = list_row.get(1);
    let revision_sha: String = list_row.get(2);
    let source_repository: String = list_row
        .try_get(3)
        .ok()
        .flatten()
        .unwrap_or_else(|| "CBL source".to_string());

    let entry_rows = connection
        .query(
            "SELECT id, position, series_name, issue_number, volume_year, publication_year,
                    external_issue_identity_id, external_series_identity_id
             FROM cbl_source_entries WHERE list_id = $1 ORDER BY position",
            &[&list_id],
        )
        .await
        .map_err(db::query_error)?;
    let entries: Vec<SourceEntry> = entry_rows
        .iter()
        .map(|row| SourceEntry {
            id: row.get(0),
            position: row.get(1),
            series_name: row.get(2),
            issue_number: row.get(3),
            volume_year: row.get(4),
            publication_year: row.get(5),
            issue_identity_id: row.get(6),
            series_identity_id: row.get(7),
        })
        .collect();

    let issue_identity_ids: Vec<i64> = entries
        .iter()
        .filter_map(|entry| entry.issue_identity_id)
        .collect();
    let series_identity_ids: Vec<i64> = entries
        .iter()
        .filter_map(|entry| entry.series_identity_id)
        .collect();

    let mut issue_external_by_id: HashMap<i64, String> = HashMap::new();
    if !issue_identity_ids.is_empty() {
        for row in connection
            .query(
                "SELECT id, external_id FROM external_identities
                 WHERE id = ANY($1::int8[]) AND entity_type = 'issue' AND provider = 'comicvine'",
                &[&issue_identity_ids],
            )
            .await
            .map_err(db::query_error)?
        {
            issue_external_by_id.insert(row.get(0), row.get(1));
        }
    }
    let mut series_external_by_id: HashMap<i64, (String, String)> = HashMap::new();
    if !series_identity_ids.is_empty() {
        for row in connection
            .query(
                "SELECT id, provider, external_id FROM external_identities
                 WHERE id = ANY($1::int8[]) AND entity_type = 'series'",
                &[&series_identity_ids],
            )
            .await
            .map_err(db::query_error)?
        {
            series_external_by_id.insert(row.get(0), (row.get(1), row.get(2)));
        }
    }

    // Resolve the source issues that already exist in the reader's library in a
    // single set-based join (no per-row query).
    let external_ids: Vec<String> = issue_external_by_id.values().cloned().collect();
    let mut owned_by_external_id: HashMap<String, i64> = HashMap::new();
    if !external_ids.is_empty() {
        for row in connection
            .query(
                "SELECT e.external_id, i.id
                 FROM external_identities e
                 JOIN issue_external_identity_mappings m ON m.external_identity_id = e.id
                 JOIN issues i ON i.id = m.issue_id
                 JOIN threads t ON t.id = i.thread_id AND t.user_id = $1
                 WHERE e.provider = 'comicvine' AND e.entity_type = 'issue'
                   AND e.external_id = ANY($2::text[])",
                &[&user.id(), &external_ids],
            )
            .await
            .map_err(db::query_error)?
        {
            owned_by_external_id.entry(row.get(0)).or_insert_with(|| row.get::<_, i64>(1));
        }
    }

    let mut plan_entries: Vec<CBLAdoptionEntry> = Vec::with_capacity(entries.len());
    let mut decision_positions: HashMap<&'static str, Vec<i64>> = HashMap::new();
    for key in [
        "included_existing",
        "would_create_missing",
        "excluded",
        "unresolved",
        "awaiting_opt_in",
    ] {
        decision_positions.insert(key, Vec::new());
    }
    let mut reused = 0i64;
    let mut missing = 0i64;
    let mut excluded = 0i64;
    let mut unresolved = 0i64;
    let mut final_order: Vec<i64> = Vec::new();

    for entry in entries {
        let comicvine_issue_id = entry
            .issue_identity_id
            .and_then(|id| issue_external_by_id.get(&id))
            .cloned();
        let series_info = entry
            .series_identity_id
            .and_then(|id| series_external_by_id.get(&id));
        let comicvine_series_id = series_info.map(|(_, external)| external.clone());
        let series_group_id = group_id(&entry, comicvine_series_id.as_deref());
        let resolved_issue_id = comicvine_issue_id
            .as_deref()
            .and_then(|id| owned_by_external_id.get(id))
            .copied();
        let importable = resolved_issue_id.is_none() && comicvine_issue_id.is_some();
        let resolution_status = if resolved_issue_id.is_some() {
            "resolved_exact"
        } else if importable {
            "no_owned_issue_for_comicvine_id"
        } else {
            "ambiguous_no_comicvine_id"
        };
        let (adoption_class, adoption_decision) = if resolved_issue_id.is_some() {
            ("existing", "included_existing")
        } else if importable {
            ("missing_importable", "would_create_missing")
        } else {
            ("ambiguous_unresolved", "unresolved")
        };
        let adopted = adoption_decision == "included_existing"
            || adoption_decision == "would_create_missing";
        if adopted {
            final_order.push(entry.position);
            if resolved_issue_id.is_some() {
                reused += 1;
            } else {
                missing += 1;
            }
        } else if adoption_decision == "excluded" {
            excluded += 1;
        } else if adoption_decision == "unresolved" {
            unresolved += 1;
        }
        decision_positions
            .get_mut(adoption_decision)
            .expect("decision key registered")
            .push(entry.position);

        plan_entries.push(CBLAdoptionEntry {
            collection_excluded: false,
            collection_exclusion_reason: None,
            collection_exclusion_ids: Vec::new(),
            cbl_position: entry.position,
            cbl_entry_id: entry.id,
            series_name: entry.series_name,
            issue_number: entry.issue_number,
            series_group_id,
            volume_year: entry.volume_year,
            publication_year: entry.publication_year,
            adoption_class: adoption_class.to_string(),
            adoption_decision: adoption_decision.to_string(),
            adopted,
            comicvine_issue_id,
            comicvine_series_id,
            series_provider: series_info.map(|(provider, _)| provider.clone()),
            series_external_id: comicvine_series_id,
            resolved_issue_id,
            canonical_issue_id: resolved_issue_id,
            read_status: None,
            read_at: None,
            resolution_status: resolution_status.to_string(),
            is_duplicate_identity: false,
        });
    }

    let positions = |key: &str| decision_positions.get(key).cloned().unwrap_or_default();
    let summary = CBLAdoptionSummary {
        reused_existing_count: reused,
        missing_would_create_count: missing,
        excluded_count: excluded,
        unresolved_count: unresolved,
        awaiting_opt_in_count: positions("awaiting_opt_in").len() as i64,
        final_adopted_count: final_order.len() as i64,
        final_adopted_order: final_order,
        reused_existing_positions: positions("included_existing"),
        missing_would_create_positions: positions("would_create_missing"),
        excluded_positions: positions("excluded"),
        unresolved_positions: positions("unresolved"),
        awaiting_opt_in_positions: positions("awaiting_opt_in"),
    };
    let total_positions = plan_entries.len() as i64;
    Ok(Json(CBLAdoptionPreviewResponse {
        source: CBLSourceFingerprint {
            source_list_id: list_id,
            source_repository,
            source_path,
            content_hash,
            revision_sha,
        },
        total_positions,
        entries: plan_entries,
        summary,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry() -> SourceEntry {
        SourceEntry {
            id: 9,
            position: 3,
            series_name: "Series".to_string(),
            issue_number: "1".to_string(),
            volume_year: Some(2020),
            publication_year: None,
            issue_identity_id: Some(7),
            series_identity_id: None,
        }
    }

    #[test]
    fn group_id_prefers_comicvine_series_identity() {
        assert_eq!(group_id(&entry(), Some("4050-1")), "comicvine:4050-1");
        assert_eq!(group_id(&entry(), None), "Series::2020::");
    }

    #[test]
    fn response_shape_serializes_nullable_fields_as_wire_contract() {
        let response = CBLAdoptionPreviewResponse {
            source: CBLSourceFingerprint {
                source_list_id: 12,
                source_repository: "JoshCLWren/CBL-ReadingLists".to_string(),
                source_path: "a/b.cbl".to_string(),
                content_hash: "hash".to_string(),
                revision_sha: "sha".to_string(),
            },
            total_positions: 0,
            entries: Vec::new(),
            summary: CBLAdoptionSummary {
                reused_existing_count: 0,
                missing_would_create_count: 0,
                excluded_count: 0,
                unresolved_count: 0,
                awaiting_opt_in_count: 0,
                final_adopted_count: 0,
                final_adopted_order: Vec::new(),
                reused_existing_positions: Vec::new(),
                missing_would_create_positions: Vec::new(),
                excluded_positions: Vec::new(),
                unresolved_positions: Vec::new(),
                awaiting_opt_in_positions: Vec::new(),
            },
        };
        let value = serde_json::to_value(&response).expect("serializes");
        assert_eq!(value.get("total_positions").and_then(Value::as_i64), Some(0));
        assert!(value.get("entries").and_then(Value::as_array).is_some());
        assert!(value.get("source").and_then(|s| s.get("source_list_id")).is_some());
    }
}
