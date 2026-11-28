//! #4026: source-aware, transactional replacement of one explicitly selected
//! Reading List, with a reversible list-only snapshot for Undo.
//!
//! A replacement always targets the authenticated reader's canonical
//! `custom_cbl_lists` row named by the URL path. It never resolves a target by
//! display name, so two identically named lists (or two readers with the same
//! name) can never collide. Source identity, reconciliation, checkbox selection
//! and collection-exclusion evaluation are reused from the adoption engine;
//! this module only projects those decisions onto an already-owned list.
//!
//! The commit guard is atomic: reader row lock + `FOR UPDATE` on the target
//! list + `expected_updated_at` + source revision/hash are all checked in one
//! transaction before any row is touched. The before-state snapshot contains
//! only list membership/order/gating/overlap choices, so Undo restores exactly
//! those choices and cannot reverse a later read, rating or collection event.

use crate::{
    auth::AuthenticatedUser,
    db,
    issue_identity::{adoption_preview_for, IdentityError},
    ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value as JsonValue};
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    sync::Arc,
};

/// One projected list entry. `gate`/`skipped`/checkpoint intents are carried so
/// an Undo restores the exact stored list rather than just issue membership.
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ReplacementEntryView {
    pub issue_id: i32,
    pub position: i32,
    pub series_name: String,
    pub issue_number: String,
    pub is_checkpoint: bool,
    #[serde(default)]
    pub checkpoint_target_issue_ids: Vec<i32>,
    pub gate: String,
    pub skipped: bool,
    /// True when the entry was on the list before the reviewed replacement.
    #[serde(default)]
    pub saved: bool,
    /// True when the entry is a reader-added comic absent from the source CBL.
    #[serde(default)]
    pub manual: bool,
}

/// Read-only, explicit-target preview request.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ReplacementPreviewRequest {
    /// Stable `cbl_source_lists` ID of the globally shared CBL.
    pub source_list_id: i32,
    /// Series-level include/exclude overrides keyed by series group ID.
    #[serde(default)]
    pub series_decisions: HashMap<String, bool>,
    /// Per-occurrence include/exclude overrides keyed by `cbl_entry_id`.
    #[serde(default)]
    pub entry_decisions: HashMap<String, bool>,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReplacementPreviewResponse {
    /// The exact owned list this preview targets (never inferred by name).
    pub target_list_id: i32,
    pub target_list_name: String,
    pub source_list_id: i32,
    pub content_hash: String,
    pub revision_sha: String,
    /// Send this exact token back as `expected_updated_at` on commit.
    pub expected_updated_at: String,
    pub before: Vec<ReplacementEntryView>,
    pub after: Vec<ReplacementEntryView>,
    /// Saved entries absent from the source that would be dropped unless the
    /// reader explicitly approves their removal on commit.
    pub omitted_manual_issue_ids: Vec<i32>,
    /// Source rows that could not be resolved to a canonical owned Issue.
    pub unresolved_count: i32,
    /// Exact source/overlap choices projected from the canonical evaluator.
    #[schema(value_type = Object)]
    pub adoption_entries: Vec<JsonValue>,
    /// Overlap choices already saved for this list; restored on Undo.
    #[schema(value_type = Object)]
    pub overlap_decisions: JsonValue,
}

/// Transactional replacement commit. The target is the URL path list ID; this
/// body carries only source provenance and the reader's reviewed choices.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ReplacementCommitRequest {
    pub source_list_id: i32,
    pub content_hash: String,
    pub revision_sha: String,
    /// Version token read from the preview; a changed list is a 409 with no writes.
    pub expected_updated_at: String,
    /// Exact reviewed membership in the intended final order.
    pub issue_ids: Vec<i32>,
    /// Per-entry gating intents. Retained entries keep their current intent when
    /// an intent is not supplied.
    #[serde(default)]
    pub entry_intents: Option<BTreeMap<i32, ReplacementEntryIntent>>,
    /// Approved overlap decisions (same shape as the overlap-decisions API).
    #[serde(default)]
    pub overlap_decisions: Option<JsonValue>,
    /// Reader-approved removal of saved manual entries. Without this, omitting
    /// a saved manual entry is rejected so nothing is silently discarded.
    #[serde(default)]
    pub confirm_manual_removals: bool,
    /// Replaying an identical request returns its original snapshot.
    #[serde(default)]
    pub idempotency_key: Option<String>,
    #[serde(default)]
    pub series_decisions: HashMap<String, bool>,
    #[serde(default)]
    pub entry_decisions: HashMap<String, bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ReplacementEntryIntent {
    #[serde(default)]
    pub is_checkpoint: bool,
    #[serde(default)]
    pub checkpoint_target_issue_ids: Vec<i32>,
    #[serde(default = "default_gate")]
    pub gate: String,
    #[serde(default)]
    pub skipped: bool,
}

fn default_gate() -> String {
    "none".to_string()
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReplacementCommitResponse {
    pub target_list_id: i32,
    /// Snapshot ID to pass to Undo (the latest un-undone snapshot is used when
    /// no snapshot ID is supplied).
    pub snapshot_id: i32,
    pub updated_at: String,
    pub applied_issue_ids: Vec<i32>,
    pub preserved_manual_issue_ids: Vec<i32>,
    #[serde(default)]
    pub replayed: bool,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ReplacementUndoRequest {
    /// Version token from the replacement commit; a later edit makes Undo a
    /// 409 so a snapshot can never overwrite newer reader work.
    pub expected_updated_at: String,
    /// Optional exact snapshot; defaults to the latest un-undone snapshot.
    #[serde(default)]
    pub snapshot_id: Option<i32>,
    #[serde(default)]
    pub idempotency_key: Option<String>,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ReplacementUndoResponse {
    pub target_list_id: i32,
    pub snapshot_id: i32,
    pub updated_at: String,
    pub restored_issue_ids: Vec<i32>,
}

fn structured(
    status: axum::http::StatusCode,
    code: &str,
    message: impl Into<String>,
) -> ApiError {
    let message = message.into();
    ApiError::StructuredDetail {
        status,
        message: message.clone(),
        detail: json!({"code": code, "message": message}),
    }
}

fn identity_error(error: IdentityError) -> ApiError {
    match error {
        IdentityError::Api(error) => error,
        IdentityError::Validation(items) => structured(
            axum::http::StatusCode::UNPROCESSABLE_ENTITY,
            "validation_failed",
            serde_json::to_string(&items).unwrap_or_else(|_| "Validation failed".to_string()),
        ),
    }
}

#[derive(Debug, Clone)]
struct EntryRow {
    issue_id: i32,
    position: i32,
    series_name: String,
    issue_number: String,
    is_checkpoint: bool,
    checkpoint_target_issue_ids: Vec<i32>,
    gate: String,
    skipped: bool,
}

impl EntryRow {
    fn view(&self, saved: bool, manual: bool) -> ReplacementEntryView {
        ReplacementEntryView {
            issue_id: self.issue_id,
            position: self.position,
            series_name: self.series_name.clone(),
            issue_number: self.issue_number.clone(),
            is_checkpoint: self.is_checkpoint,
            checkpoint_target_issue_ids: self.checkpoint_target_issue_ids.clone(),
            gate: self.gate.clone(),
            skipped: self.skipped,
            saved,
            manual,
        }
    }
}

async fn load_entries(
    tx: &tokio_postgres::Transaction<'_>,
    list_id: i32,
) -> Result<Vec<EntryRow>, ApiError> {
    let rows = tx
        .query(
            "SELECT e.issue_id, e.position, t.title, i.issue_number,
                    e.is_checkpoint, e.checkpoint_target_issue_ids::text,
                    e.gate, e.skipped
             FROM custom_cbl_entries e
             JOIN issues i ON i.id = e.issue_id
             JOIN threads t ON t.id = i.thread_id
             WHERE e.list_id = $1
             ORDER BY e.position, e.id",
            &[&list_id],
        )
        .await
        .map_err(db::query_error)?;
    rows.into_iter()
        .map(|row| {
            let targets: Vec<i32> =
                serde_json::from_str(&row.get::<_, String>(5)).unwrap_or_default();
            Ok(EntryRow {
                issue_id: row.get(0),
                position: row.get(1),
                series_name: row.get(2),
                issue_number: row.get(3),
                is_checkpoint: row.get(4),
                checkpoint_target_issue_ids: targets,
                gate: row.get(6),
                skipped: row.get(7),
            })
        })
        .collect()
}

async fn load_overlap_decisions(
    tx: &tokio_postgres::Transaction<'_>,
    user_id: i32,
    list_id: i32,
) -> Result<JsonValue, ApiError> {
    let rows = tx
        .query(
            "SELECT continuing_external_identity_id, waiting_external_identity_id
             FROM custom_cbl_overlap_decisions
             WHERE user_id = $1 AND list_id = $2
             ORDER BY id",
            &[&user_id, &list_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(json!(rows
        .iter()
        .map(|row| {
            json!({
                "continuing_external_identity_id": row.get::<_, i32>(0),
                "waiting_external_identity_id": row.get::<_, i32>(1),
            })
        })
        .collect::<Vec<_>>()))
}

/// Resolve adopted canonical issue IDs from the shared evaluator without
/// inventing a second resolution or exclusion engine.
async fn adopted_issue_ids(
    state: &Arc<AppState>,
    user_id: i32,
    source_list_id: i32,
    series_decisions: &HashMap<String, bool>,
    entry_decisions: &HashMap<String, bool>,
) -> Result<(CblSourceFingerprint, Vec<i32>, i32), ApiError> {
    let preview = adoption_preview_for(
        state,
        user_id,
        source_list_id,
        series_decisions,
        entry_decisions,
    )
    .await
    .map_err(identity_error)?;
    let mut ids = Vec::new();
    let mut seen = HashSet::new();
    let mut unresolved = 0;
    for entry in &preview.entries {
        if entry.adopted {
            if let Some(issue_id) = entry.resolved_issue_id {
                if seen.insert(issue_id) {
                    ids.push(issue_id);
                }
            } else {
                unresolved += 1;
            }
        } else {
            unresolved += 1;
        }
    }
    Ok((
        CblSourceFingerprint {
            source_list_id: preview.source.source_list_id,
            content_hash: preview.source.content_hash,
            revision_sha: preview.source.revision_sha,
        },
        ids,
        unresolved,
    ))
}

#[derive(Debug, Clone)]
struct CblSourceFingerprint {
    source_list_id: i32,
    content_hash: String,
    revision_sha: String,
}

fn intent_json(
    old: &[EntryRow],
    requested: &Option<BTreeMap<i32, ReplacementEntryIntent>>,
) -> JsonValue {
    let mut map = serde_json::Map::new();
    for entry in old {
        map.insert(
            entry.issue_id.to_string(),
            json!({
                "is_checkpoint": entry.is_checkpoint,
                "checkpoint_target_issue_ids": entry.checkpoint_target_issue_ids,
                "gate": entry.gate,
                "skipped": entry.skipped,
            }),
        );
    }
    if let Some(intents) = requested {
        for (issue_id, intent) in intents {
            map.insert(
                issue_id.to_string(),
                json!({
                    "is_checkpoint": intent.is_checkpoint,
                    "checkpoint_target_issue_ids": intent.checkpoint_target_issue_ids,
                    "gate": intent.gate,
                    "skipped": intent.skipped,
                }),
            );
        }
    }
    JsonValue::Object(map)
}

fn state_json(
    name: &str,
    description: Option<&str>,
    mode: &str,
    entries: &[EntryRow],
    overlaps: &JsonValue,
) -> JsonValue {
    json!({
        "name": name,
        "description": description,
        "mode": mode,
        "entries": entries.iter().map(|entry| {
            json!({
                "issue_id": entry.issue_id,
                "position": entry.position,
                "series_name": entry.series_name,
                "issue_number": entry.issue_number,
                "is_checkpoint": entry.is_checkpoint,
                "checkpoint_target_issue_ids": entry.checkpoint_target_issue_ids,
                "gate": entry.gate,
                "skipped": entry.skipped,
            })
        }).collect::<Vec<_>>(),
        "overlap_decisions": overlaps,
    })
}

fn entries_from_state(state: &JsonValue) -> Result<Vec<EntryRow>, ApiError> {
    let entries = state
        .get("entries")
        .and_then(|value| value.as_array())
        .ok_or_else(|| {
            structured(
                axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                "replacement_snapshot_invalid",
                "Replacement snapshot has no entries",
            )
        })?;
    entries
        .iter()
        .map(|entry| {
            let targets = entry
                .get("checkpoint_target_issue_ids")
                .and_then(|value| value.as_array())
                .map(|items| {
                    items
                        .iter()
                        .filter_map(|value| value.as_i64().map(|id| id as i32))
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            Ok(EntryRow {
                issue_id: entry
                    .get("issue_id")
                    .and_then(|value| value.as_i64())
                    .ok_or_else(|| {
                        structured(
                            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                            "replacement_snapshot_invalid",
                            "Replacement snapshot entry has no issue_id",
                        )
                    })? as i32,
                position: entry
                    .get("position")
                    .and_then(|value| value.as_i64())
                    .unwrap_or(0) as i32,
                series_name: entry
                    .get("series_name")
                    .and_then(|value| value.as_str())
                    .unwrap_or_default()
                    .to_string(),
                issue_number: entry
                    .get("issue_number")
                    .and_then(|value| value.as_str())
                    .unwrap_or_default()
                    .to_string(),
                is_checkpoint: entry
                    .get("is_checkpoint")
                    .and_then(|value| value.as_bool())
                    .unwrap_or(false),
                checkpoint_target_issue_ids: targets,
                gate: entry
                    .get("gate")
                    .and_then(|value| value.as_str())
                    .unwrap_or("none")
                    .to_string(),
                skipped: entry
                    .get("skipped")
                    .and_then(|value| value.as_bool())
                    .unwrap_or(false),
            })
        })
        .collect()
}

/// Set-based membership write. Intents for retained entries are merged in SQL
/// from a single JSONB parameter; no per-issue round trip is issued.
async fn write_entries(
    tx: &tokio_postgres::Transaction<'_>,
    list_id: i32,
    ids: &[i32],
    intents: &JsonValue,
) -> Result<(), ApiError> {
    tx.execute(
        "DELETE FROM custom_cbl_entries WHERE list_id = $1 AND NOT (issue_id = ANY($2::int[]))",
        &[&list_id, &ids],
    )
    .await
    .map_err(db::query_error)?;
    if ids.is_empty() {
        return Ok(());
    }
    tx.execute(
        r#"
        INSERT INTO custom_cbl_entries
          (list_id, issue_id, position, created_at, is_checkpoint,
           checkpoint_target_issue_ids, gate, skipped)
        SELECT $1, ids.issue_id, (ids.ord - 1)::int, NOW(),
               COALESCE((intent ->> 'is_checkpoint')::bool, false),
               COALESCE(intent -> 'checkpoint_target_issue_ids', '[]'::jsonb)::json,
               COALESCE(intent ->> 'gate', 'none'),
               COALESCE((intent ->> 'skipped')::bool, false)
        FROM unnest($2::int[]) WITH ORDINALITY AS ids(issue_id, ord)
        CROSS JOIN LATERAL (SELECT $3::jsonb -> ids.issue_id::text AS intent) AS chosen
        ON CONFLICT (list_id, issue_id) DO UPDATE SET
          position = EXCLUDED.position,
          is_checkpoint = EXCLUDED.is_checkpoint,
          checkpoint_target_issue_ids = EXCLUDED.checkpoint_target_issue_ids,
          gate = EXCLUDED.gate,
          skipped = EXCLUDED.skipped
        "#,
        &[&list_id, &ids, &tokio_postgres::types::Json(intents)],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

async fn write_overlap_decisions(
    tx: &tokio_postgres::Transaction<'_>,
    user_id: i32,
    list_id: i32,
    decisions: &JsonValue,
) -> Result<(), ApiError> {
    tx.execute(
        "DELETE FROM custom_cbl_overlap_decisions WHERE user_id = $1 AND list_id = $2",
        &[&user_id, &list_id],
    )
    .await
    .map_err(db::query_error)?;
    let items = decisions.as_array().cloned().unwrap_or_default();
    if items.is_empty() {
        return Ok(());
    }
    tx.execute(
        r#"
        INSERT INTO custom_cbl_overlap_decisions
          (user_id, list_id, continuing_external_identity_id,
           waiting_external_identity_id, created_at, updated_at)
        SELECT $1, $2, (d ->> 'continuing_external_identity_id')::int,
               (d ->> 'waiting_external_identity_id')::int, NOW(), NOW()
        FROM jsonb_array_elements($3::jsonb) AS d
        WHERE (d ->> 'continuing_external_identity_id') IS NOT NULL
          AND (d ->> 'waiting_external_identity_id') IS NOT NULL
          AND (d ->> 'continuing_external_identity_id')::int
              <> (d ->> 'waiting_external_identity_id')::int
        "#,
        &[&user_id, &list_id, &tokio_postgres::types::Json(decisions)],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

fn project_after(
    source_ids: &[i32],
    old: &[EntryRow],
    kept_manual: &[i32],
    requested_intents: &Option<BTreeMap<i32, ReplacementEntryIntent>>,
    series_names: &HashMap<i32, (String, String)>,
) -> Vec<EntryRow> {
    let mut ordered = source_ids.to_vec();
    for id in kept_manual {
        if !ordered.contains(id) {
            ordered.push(*id);
        }
    }
    let old_by_id: BTreeMap<i32, &EntryRow> = old.iter().map(|entry| (entry.issue_id, entry)).collect();
    ordered
        .into_iter()
        .enumerate()
        .map(|(index, issue_id)| {
            let old_entry = old_by_id.get(&issue_id).copied();
            let intent = requested_intents.and_then(|intents| intents.get(&issue_id));
            let (series_name, issue_number) = series_names
                .get(&issue_id)
                .cloned()
                .or_else(|| old_entry.map(|entry| (entry.series_name.clone(), entry.issue_number.clone())))
                .unwrap_or_else(|| (format!("Issue {issue_id}"), String::new()));
            EntryRow {
                issue_id,
                position: index as i32,
                series_name,
                issue_number,
                is_checkpoint: intent
                    .map(|value| value.is_checkpoint)
                    .or_else(|| old_entry.map(|entry| entry.is_checkpoint))
                    .unwrap_or(false),
                checkpoint_target_issue_ids: intent
                    .map(|value| value.checkpoint_target_issue_ids.clone())
                    .or_else(|| {
                        old_entry.map(|entry| entry.checkpoint_target_issue_ids.clone())
                    })
                    .unwrap_or_default(),
                gate: intent
                    .map(|value| value.gate.clone())
                    .or_else(|| old_entry.map(|entry| entry.gate.clone()))
                    .unwrap_or_else(default_gate),
                skipped: intent
                    .map(|value| value.skipped)
                    .or_else(|| old_entry.map(|entry| entry.skipped))
                    .unwrap_or(false),
            }
        })
        .collect()
}

async fn source_series_names(
    state: &Arc<AppState>,
    source_list_id: i32,
    user_id: i32,
    series_decisions: &HashMap<String, bool>,
    entry_decisions: &HashMap<String, bool>,
) -> Result<HashMap<i32, (String, String)>, ApiError> {
    let preview = adoption_preview_for(
        state,
        user_id,
        source_list_id,
        series_decisions,
        entry_decisions,
    )
    .await
    .map_err(identity_error)?;
    Ok(preview
        .entries
        .into_iter()
        .filter_map(|entry| {
            let issue_id = entry.resolved_issue_id?;
            Some((issue_id, (entry.series_name, entry.issue_number)))
        })
        .collect())
}

/// `POST /api/v2/reading-lists/{list_id}/replacements:preview`
///
/// Read-only. Shows the exact owned list, the source-evaluated after state,
/// manual extras that would be dropped, and overlap choices. No rows are
/// written, so canceling the review cannot change the list.
#[utoipa::path(
    post,
    path = "/api/v2/reading-lists/{list_id}/replacements:preview",
    tag = "reading-lists",
    operation_id = "replacement_preview",
    params(("list_id" = i32, Path, description = "Explicit owned Reading List id")),
    request_body = ReplacementPreviewRequest,
    responses(
        (status = 200, description = "Read-only before/after replacement review", body = ReplacementPreviewResponse),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "Reading List or CBL source not found"),
    ),
    security(("HTTPBearer" = []))
)]
pub async fn preview_replacement(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(request): Json<ReplacementPreviewRequest>,
) -> Result<Json<ReplacementPreviewResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let row = tx
        .query_opt(
            "SELECT name, description, mode, updated_at::text FROM custom_cbl_lists
             WHERE id = $1 AND user_id = $2",
            &[&list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound(format!("Reading List {list_id} not found")))?;
    let name: String = row.get(0);
    let expected_updated_at: String = row.get(3);
    let old = load_entries(&tx, list_id).await?;
    let overlaps = load_overlap_decisions(&tx, user.id(), list_id).await?;
    tx.rollback().await.map_err(db::query_error)?;
    drop(conn);

    let (fingerprint, source_ids, unresolved_count) = adopted_issue_ids(
        &state,
        user.id(),
        request.source_list_id,
        &request.series_decisions,
        &request.entry_decisions,
    )
    .await?;
    let series_names = source_series_names(
        &state,
        request.source_list_id,
        user.id(),
        &request.series_decisions,
        &request.entry_decisions,
    )
    .await?;
    let source_set: HashSet<i32> = source_ids.iter().copied().collect();
    let omitted_manual_issue_ids = old
        .iter()
        .filter(|entry| !source_set.contains(&entry.issue_id))
        .map(|entry| entry.issue_id)
        .collect::<Vec<_>>();
    let kept_manual = omitted_manual_issue_ids.clone();
    let after = project_after(
        &source_ids,
        &old,
        &kept_manual,
        &None,
        &series_names,
    );
    let before = old
        .iter()
        .map(|entry| entry.view(true, !source_set.contains(&entry.issue_id)))
        .collect();
    let after_views = after
        .iter()
        .map(|entry| entry.view(source_set.contains(&entry.issue_id), !source_set.contains(&entry.issue_id)))
        .collect();
    let adoption_entries = adoption_preview_for(
        &state,
        user.id(),
        request.source_list_id,
        &request.series_decisions,
        &request.entry_decisions,
    )
    .await
    .map_err(identity_error)?
    .entries
    .into_iter()
    .map(|entry| serde_json::to_value(entry).unwrap_or(JsonValue::Null))
    .collect();

    Ok(Json(ReplacementPreviewResponse {
        target_list_id: list_id,
        target_list_name: name,
        source_list_id: fingerprint.source_list_id,
        content_hash: fingerprint.content_hash,
        revision_sha: fingerprint.revision_sha,
        expected_updated_at,
        before,
        after: after_views,
        omitted_manual_issue_ids,
        unresolved_count,
        adoption_entries,
        overlap_decisions: overlaps,
    }))
}

/// `POST /api/v2/reading-lists/{list_id}/replacements`
///
/// Commits one owner-scoped transaction. A stale list version, stale source
/// hash/revision, or an unapproved removal of a saved manual entry fails before
/// any row is touched. On success a list-only snapshot is retained for Undo.
#[utoipa::path(
    post,
    path = "/api/v2/reading-lists/{list_id}/replacements",
    tag = "reading-lists",
    operation_id = "replacement_commit",
    params(("list_id" = i32, Path, description = "Explicit owned Reading List id")),
    request_body = ReplacementCommitRequest,
    responses(
        (status = 200, description = "Replacement committed with a reversible snapshot", body = ReplacementCommitResponse),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "Reading List or CBL source not found"),
        (status = 409, description = "Stale source/list version or unapproved manual removal; nothing changed"),
    ),
    security(("HTTPBearer" = []))
)]
pub async fn commit_replacement(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(request): Json<ReplacementCommitRequest>,
) -> Result<Json<ReplacementCommitResponse>, ApiError> {
    // Reuse the canonical evaluator before opening the write transaction. The
    // source hash/revision and list version are re-checked inside it, so a
    // concurrent source refresh cannot leak into a committed replacement.
    let (fingerprint, source_ids, _) = adopted_issue_ids(
        &state,
        user.id(),
        request.source_list_id,
        &request.series_decisions,
        &request.entry_decisions,
    )
    .await?;
    let series_names = source_series_names(
        &state,
        request.source_list_id,
        user.id(),
        &request.series_decisions,
        &request.entry_decisions,
    )
    .await?;

    let mut conn = db::checkout(&state).await?;
    let mut tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    tx.execute(
        "SELECT 1 FROM users WHERE id = $1 FOR UPDATE",
        &[&user.id()],
    )
    .await
    .map_err(db::query_error)?;
    let list_row = tx
        .query_opt(
            "SELECT name, description, mode, updated_at::text FROM custom_cbl_lists
             WHERE id = $1 AND user_id = $2 FOR UPDATE",
            &[&list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound(format!("Reading List {list_id} not found")))?;
    let current_updated_at: String = list_row.get(3);
    if current_updated_at != request.expected_updated_at {
        return Err(structured(
            axum::http::StatusCode::CONFLICT,
            "reading_list_replacement_stale",
            format!(
                "This Reading List changed since you reviewed it (expected {}, current {})",
                request.expected_updated_at, current_updated_at
            ),
        ));
    }
    let source_row = tx
        .query_opt(
            "SELECT content_hash, revision_sha FROM cbl_source_lists WHERE id = $1 AND active",
            &[&request.source_list_id],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| {
            ApiError::NotFound(format!("CBL source list {} not found", request.source_list_id))
        })?;
    if source_row.get::<_, String>(0) != request.content_hash
        || source_row.get::<_, String>(1) != request.revision_sha
    {
        return Err(structured(
            axum::http::StatusCode::CONFLICT,
            "cbl_source_revision_stale",
            "The CBL source revision changed after you reviewed it",
        ));
    }

    if let Some(key) = request.idempotency_key.as_deref() {
        let replay = tx
            .query_opt(
                "SELECT id, response_json::text FROM custom_cbl_replacement_snapshots
                 WHERE user_id = $1 AND list_id = $2 AND idempotency_key = $3",
                &[&user.id(), &list_id, &key],
            )
            .await
            .map_err(db::query_error)?;
        if let Some(row) = replay {
            let mut response: ReplacementCommitResponse =
                serde_json::from_str(&row.get::<_, String>(1)).unwrap_or(ReplacementCommitResponse {
                    target_list_id: list_id,
                    snapshot_id: row.get(0),
                    updated_at: current_updated_at.clone(),
                    applied_issue_ids: Vec::new(),
                    preserved_manual_issue_ids: Vec::new(),
                    replayed: true,
                });
            response.replayed = true;
            tx.commit().await.map_err(db::query_error)?;
            return Ok(Json(response));
        }
    }

    let old = load_entries(&tx, list_id).await?;
    let overlaps = load_overlap_decisions(&tx, user.id(), list_id).await?;
    let source_set: HashSet<i32> = source_ids.iter().copied().collect();
    let manual_issue_ids: Vec<i32> = old
        .iter()
        .filter(|entry| !source_set.contains(&entry.issue_id))
        .map(|entry| entry.issue_id)
        .collect();
    let requested: HashSet<i32> = request.issue_ids.iter().copied().collect();
    let dropped: Vec<i32> = manual_issue_ids
        .iter()
        .copied()
        .filter(|id| !requested.contains(id))
        .collect();
    if !dropped.is_empty() && !request.confirm_manual_removals {
        return Err(structured(
            axum::http::StatusCode::CONFLICT,
            "manual_entry_removal_requires_confirmation",
            format!("Saved manual entries would be dropped: {dropped:?}"),
        ));
    }
    let kept_manual: Vec<i32> = manual_issue_ids
        .iter()
        .copied()
        .filter(|id| requested.contains(id))
        .collect();

    let unique_requested: HashSet<i32> = requested.clone();
    if unique_requested.len() != request.issue_ids.len() {
        return Err(structured(
            axum::http::StatusCode::BAD_REQUEST,
            "duplicate_issue_ids",
            "issue_ids must be unique",
        ));
    }
    let owned_count: i64 = tx
        .query_one(
            "SELECT COUNT(*)::bigint FROM issues i JOIN threads t ON t.id = i.thread_id
             WHERE t.user_id = $1 AND i.id = ANY($2::int[])",
            &[&user.id(), &request.issue_ids],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    if owned_count != request.issue_ids.len() as i64 {
        return Err(ApiError::NotFound("Issue not found".to_string()));
    }

    // The reviewed `issue_ids` are authoritative: a source occurrence the
    // reader unchecked must not be re-added by the evaluator projection.
    let selected_source_ids: Vec<i32> = source_ids
        .into_iter()
        .filter(|id| requested.contains(id))
        .collect();
    let after_entries = project_after(
        &selected_source_ids,
        &old,
        &kept_manual,
        &request.entry_intents,
        &series_names,
    );
    let final_ids: Vec<i32> = after_entries.iter().map(|entry| entry.issue_id).collect();
    let before_state = state_json(
        &list_row.get::<_, String>(0),
        list_row.get::<_, Option<String>>(1).as_deref(),
        &list_row.get::<_, String>(2),
        &old,
        &overlaps,
    );
    let new_overlaps = request
        .overlap_decisions
        .clone()
        .unwrap_or_else(|| overlaps.clone());

    write_entries(&tx, list_id, &final_ids, &intent_json(&old, &request.entry_intents)).await?;
    if request.overlap_decisions.is_some() {
        write_overlap_decisions(&tx, user.id(), list_id, &new_overlaps).await?;
    }
    tx.execute(
        "UPDATE custom_cbl_lists SET updated_at = NOW() WHERE id = $1 AND user_id = $2",
        &[&list_id, &user.id()],
    )
    .await
    .map_err(db::query_error)?;
    let updated_at: String = tx
        .query_one(
            "SELECT updated_at::text FROM custom_cbl_lists WHERE id = $1",
            &[&list_id],
        )
        .await
        .map_err(db::query_error)?
        .get(0);

    let response = ReplacementCommitResponse {
        target_list_id: list_id,
        snapshot_id: 0,
        updated_at: updated_at.clone(),
        applied_issue_ids: final_ids.clone(),
        preserved_manual_issue_ids: kept_manual.clone(),
        replayed: false,
    };
    let row = tx
        .query_one(
            r#"
            INSERT INTO custom_cbl_replacement_snapshots
              (user_id, list_id, source_list_id, source_revision_sha, source_content_hash,
               idempotency_key, list_version_before, list_version_after,
               before_state_json, after_state_json, response_json, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,0,1,$7::jsonb,$8::jsonb,$9::jsonb,NOW())
            RETURNING id
            "#,
            &[
                &user.id(),
                &list_id,
                &fingerprint.source_list_id,
                &fingerprint.revision_sha,
                &fingerprint.content_hash,
                &request.idempotency_key,
                &tokio_postgres::types::Json(&before_state),
                &tokio_postgres::types::Json(&after_state),
                &tokio_postgres::types::Json(&response),
            ],
        )
        .await
        .map_err(|error| {
            if error.code().map(|code| code.code() == "23505").unwrap_or(false) {
                structured(
                    axum::http::StatusCode::CONFLICT,
                    "replacement_idempotency_conflict",
                    "A replacement with this idempotency key already exists",
                )
            } else {
                db::query_error(error)
            }
        })?;
    let snapshot_id: i32 = row.get(0);
    let response = ReplacementCommitResponse {
        snapshot_id,
        ..response
    };
    tx.execute(
        "UPDATE custom_cbl_replacement_snapshots SET response_json = $1::jsonb WHERE id = $2",
        &[&tokio_postgres::types::Json(&response), &snapshot_id],
    )
    .await
    .map_err(db::query_error)?;
    tx.commit().await.map_err(db::query_error)?;

    Ok(Json(response))
}

/// `POST /api/v2/reading-lists/{list_id}/replacements:undo`
///
/// Restores only list membership, ordering, gating intents and overlap choices
/// from the retained snapshot. Read events, ratings, collections, other lists
/// and all physical Issues are untouched. A changed list version fails closed.
#[utoipa::path(
    post,
    path = "/api/v2/reading-lists/{list_id}/replacements:undo",
    tag = "reading-lists",
    operation_id = "replacement_undo",
    params(("list_id" = i32, Path, description = "Explicit owned Reading List id")),
    request_body = ReplacementUndoRequest,
    responses(
        (status = 200, description = "List-only snapshot restored", body = ReplacementUndoResponse),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "Reading List or snapshot not found"),
        (status = 409, description = "List changed after replacement; nothing changed"),
    ),
    security(("HTTPBearer" = []))
)]
pub async fn undo_replacement(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(request): Json<ReplacementUndoRequest>,
) -> Result<Json<ReplacementUndoResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let mut tx = conn
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    tx.execute(
        "SELECT 1 FROM users WHERE id = $1 FOR UPDATE",
        &[&user.id()],
    )
    .await
    .map_err(db::query_error)?;
    let row = tx
        .query_opt(
            "SELECT updated_at::text FROM custom_cbl_lists WHERE id = $1 AND user_id = $2 FOR UPDATE",
            &[&list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound(format!("Reading List {list_id} not found")))?;
    let current_updated_at: String = row.get(0);
    if current_updated_at != request.expected_updated_at {
        return Err(structured(
            axum::http::StatusCode::CONFLICT,
            "replacement_undo_stale",
            format!(
                "This Reading List changed since the replacement (expected {}, current {})",
                request.expected_updated_at, current_updated_at
            ),
        ));
    }

    if let Some(key) = request.idempotency_key.as_deref() {
        let replay = tx
            .query_opt(
                "SELECT id, before_state_json::text FROM custom_cbl_replacement_snapshots
                 WHERE user_id = $1 AND list_id = $2 AND idempotency_key = $3
                   AND undone_at IS NOT NULL",
                &[&user.id(), &list_id, &key],
            )
            .await
            .map_err(db::query_error)?;
        if let Some(row) = replay {
            let entries = entries_from_state(&JsonValue::Null).unwrap_or_default();
            let _ = entries;
            let before: JsonValue = serde_json::from_str(&row.get::<_, String>(1))
                .map_err(|error| ApiError::Internal(error.to_string()))?;
            let ids = before
                .get("entries")
                .and_then(|value| value.as_array())
                .map(|items| {
                    items
                        .iter()
                        .filter_map(|item| {
                            item.get("issue_id").and_then(|id| id.as_i64()).map(|id| id as i32)
                        })
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            tx.commit().await.map_err(db::query_error)?;
            return Ok(Json(ReplacementUndoResponse {
                target_list_id: list_id,
                snapshot_id: row.get(0),
                updated_at: current_updated_at,
                restored_issue_ids: ids,
            }));
        }
    }

    let snapshot = tx
        .query_opt(
            r#"
            SELECT id, before_state_json::text, after_state_json::text
            FROM custom_cbl_replacement_snapshots
            WHERE user_id = $1 AND list_id = $2 AND undone_at IS NULL
              AND ($3::int IS NULL OR id = $3::int)
            ORDER BY id DESC
            FOR UPDATE
            LIMIT 1
            "#,
            &[&user.id(), &list_id, &request.snapshot_id],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| {
            ApiError::NotFound(format!(
                "No reversible replacement snapshot for Reading List {list_id}"
            ))
        })?;
    let snapshot_id: i32 = snapshot.get(0);
    let before: JsonValue = serde_json::from_str(&snapshot.get::<_, String>(1))
        .map_err(|error| ApiError::Internal(error.to_string()))?;
    let after: JsonValue = serde_json::from_str(&snapshot.get::<_, String>(2))
        .map_err(|error| ApiError::Internal(error.to_string()))?;
    // The snapshot must be the state that produced the version token the
    // client reviewed. Otherwise a later replacement already changed the list.
    let after_updated_marker = after
        .get("updated_at")
        .and_then(|value| value.as_str())
        .unwrap_or_default();
    if !after_updated_marker.is_empty() && after_updated_marker != current_updated_at {
        return Err(structured(
            axum::http::StatusCode::CONFLICT,
            "replacement_undo_stale",
            "The retained snapshot is not the last applied replacement",
        ));
    }

    let entries = entries_from_state(&before)?;
    let ids: Vec<i32> = entries.iter().map(|entry| entry.issue_id).collect();
    let intents = intent_json(&entries, &None);
    write_entries(&tx, list_id, &ids, &intents).await?;
    let before_overlaps = before
        .get("overlap_decisions")
        .cloned()
        .unwrap_or_else(|| json!([]));
    write_overlap_decisions(&tx, user.id(), list_id, &before_overlaps).await?;
    tx.execute(
        "UPDATE custom_cbl_lists
         SET name = $3, description = $4, mode = $5, updated_at = NOW()
         WHERE id = $1 AND user_id = $2",
        &[
            &list_id,
            &user.id(),
            &before
                .get("name")
                .and_then(|value| value.as_str())
                .unwrap_or_default(),
            &before
                .get("description")
                .and_then(|value| value.as_str()),
            &before
                .get("mode")
                .and_then(|value| value.as_str())
                .unwrap_or("loose"),
        ],
    )
    .await
    .map_err(db::query_error)?;
    let updated_at: String = tx
        .query_one(
            "SELECT updated_at::text FROM custom_cbl_lists WHERE id = $1",
            &[&list_id],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    tx.execute(
        "UPDATE custom_cbl_replacement_snapshots SET undone_at = NOW() WHERE id = $1",
        &[&snapshot_id],
    )
    .await
    .map_err(db::query_error)?;
    tx.commit().await.map_err(db::query_error)?;

    Ok(Json(ReplacementUndoResponse {
        target_list_id: list_id,
        snapshot_id,
        updated_at,
        restored_issue_ids: ids,
    }))
}

/// OpenAPI document for this resource family.
#[derive(utoipa::OpenApi)]
#[openapi(
    info(title = "Reading List replacement", version = "1.0.0"),
    paths(preview_replacement, commit_replacement, undo_replacement),
    components(schemas(
        ReplacementEntryView,
        ReplacementPreviewRequest,
        ReplacementPreviewResponse,
        ReplacementCommitRequest,
        ReplacementCommitResponse,
        ReplacementEntryIntent,
        ReplacementUndoRequest,
        ReplacementUndoResponse,
    )),
    modifiers(&ReplacementSecurityAddon)
)]
pub(crate) struct ReadingListReplacementApi;

struct ReplacementSecurityAddon;

impl utoipa::Modify for ReplacementSecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme(
                "HTTPBearer",
                utoipa::openapi::security::SecurityScheme::Http(
                    utoipa::openapi::security::Http::new(
                        utoipa::openapi::security::HttpAuthScheme::Bearer,
                    ),
                ),
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn project_after_keeps_manual_extras_in_order() {
        let old = vec![
            EntryRow {
                issue_id: 1,
                position: 0,
                series_name: "A".into(),
                issue_number: "1".into(),
                is_checkpoint: false,
                checkpoint_target_issue_ids: vec![],
                gate: "none".into(),
                skipped: false,
            },
            EntryRow {
                issue_id: 2,
                position: 1,
                series_name: "B".into(),
                issue_number: "1".into(),
                is_checkpoint: false,
                checkpoint_target_issue_ids: vec![],
                gate: "none".into(),
                skipped: false,
            },
        ];
        let projected = project_after(&[3], &old, &[2], &None, &HashMap::new());
        assert_eq!(projected.iter().map(|entry| entry.issue_id).collect::<Vec<_>>(), vec![3, 2]);
        assert_eq!(projected[1].series_name, "B");
        assert_eq!(projected[1].position, 1);
    }
}
