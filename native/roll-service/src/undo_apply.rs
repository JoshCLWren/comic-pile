//! Native same-path undo apply snapshot (#4839, parent #4335).
//!
//! Migrates `POST /api/undo/{session_id}/undo/{snapshot_id}` and
//! `POST /api/v1/undo/{session_id}/undo/{snapshot_id}` to the native
//! Rust router with identical method/path and wire contract.
//!
//! Wire parity with Python `undo_to_snapshot` (`app/api/undo.py`):
//!
//! * Ownership: session and snapshot must belong to the authenticated user (404 if not found or foreign).
//! * Applies a snapshot to restore session state (full or delta snapshot).
//! * Delta snapshots can only be applied if they are the latest (409 Conflict otherwise).
//! * Returns full SessionResponse with restored state.
//! * Deadlock retry handling (3 attempts with exponential backoff).
//! * Delta snapshots are deleted after successful application.
//!
//! This is the most complex operation as it involves:
//! - Session ownership verification
//! - Snapshot ownership and type detection (full vs delta)
//! - Full snapshot: restores entire library state (threads, issues, session)
//! - Delta snapshot: restores only changed state from a rating event
//! - Event issue reference cleanup for counter-only threads
//! - Undo event recording
//! - Delta snapshot deletion after apply
//! - Pre-computed response values to avoid post-commit MissingGreenlet

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, reading_session::automatic_die_after, ApiError, AppState};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Arc;
use utoipa::ToSchema;

/// Full session response matching Python SessionResponse.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct UndoApplyResponse {
    pub id: i32,
    pub started_at: String,
    pub ended_at: Option<String>,
    pub start_die: i32,
    pub manual_die: Option<i32>,
    pub user_id: i32,
    pub ladder_path: String,
    pub active_thread: Option<SessionActiveThread>,
    pub current_die: i32,
    pub last_rolled_result: Option<i32>,
    pub has_restore_point: bool,
    pub snapshot_count: i32,
    pub snoozed_thread_ids: Vec<i32>,
    pub snoozed_threads: Vec<SessionThreadSummary>,
    pub skipped_thread_ids: Vec<i32>,
    pub skipped_threads: Vec<SessionThreadSummary>,
    pub pending_thread_id: Option<i32>,
    pub timezone: Option<String>,
    pub reading_bandwidth: Option<String>,
    pub reading_intent: Option<String>,
    pub reading_mode_source: Option<String>,
    pub reading_mode_suggested: bool,
    pub bandwidth: Option<SessionBandwidthState>,
    pub intent: Option<SessionIntentState>,
}

/// Active thread projection.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionActiveThread {
    pub id: i32,
    pub title: String,
    pub format: String,
    pub issues_remaining: i32,
    pub queue_position: i32,
    pub last_rolled_result: Option<i32>,
    pub total_issues: Option<i32>,
    pub reading_progress: Option<String>,
    pub issues_read: Option<i32>,
    pub last_rating: Option<f64>,
    pub tags: Vec<SessionTag>,
    pub issue_id: Option<i32>,
    pub issue_number: Option<String>,
    pub next_issue_id: Option<i32>,
    pub next_issue_number: Option<String>,
}

/// Compact thread summary.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionThreadSummary {
    pub id: i32,
    pub title: String,
}

/// Direct visible tag.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionTag {
    pub id: i32,
    pub name: String,
    pub normalized_name: String,
    pub scope: String,
    pub owner_user_id: Option<i32>,
    pub color: String,
    pub created_at: String,
    pub updated_at: String,
}

/// Canonical bandwidth state.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionBandwidthState {
    pub predicted_bandwidth: Option<String>,
    pub active_bandwidth: Option<String>,
    pub confidence: Option<f64>,
    pub source: Option<String>,
    pub mode_version: Option<String>,
}

/// Canonical intent state.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionIntentState {
    pub predicted_intent: Option<String>,
    pub active_intent: Option<String>,
    pub confidence: Option<f64>,
    pub source: Option<String>,
    pub mode_version: Option<String>,
}

const SESSION_OWNERSHIP_SQL: &str = "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, user_id, pending_thread_id, timezone, reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested, predicted_bandwidth, active_bandwidth, bandwidth_confidence, bandwidth_source, bandwidth_version, predicted_intent, active_intent, intent_confidence, intent_source, intent_version, snoozed_thread_ids FROM sessions WHERE id = $1 AND user_id = $2";
const SNAPSHOT_SQL: &str = "SELECT id, thread_states, session_state, snapshot_kind FROM snapshots WHERE id = $1 AND session_id = $2";
const LATEST_DELTA_SQL: &str = "SELECT id FROM snapshots WHERE session_id = $1 AND (thread_states->>'_snapshot_version')::int = 2 ORDER BY created_at DESC, id DESC LIMIT 1";
const SNAPSHOT_COUNT_SQL: &str = "SELECT count(*)::int FROM snapshots WHERE session_id = $1";
const LADDER_SQL: &str = "SELECT die_after FROM events WHERE session_id = $1 AND type IN ('rate','snooze','undo') AND die_after IS NOT NULL ORDER BY timestamp ASC, id ASC";
const CURRENT_DIE_SQL: &str = "SELECT die_after, context::text FROM events WHERE session_id = $1 AND type IN ('rate','snooze','undo') AND die_after IS NOT NULL ORDER BY timestamp DESC, id DESC LIMIT 1";
const LATEST_ACTION_SQL: &str = "SELECT type, selected_thread_id, result FROM events WHERE session_id = $1 AND type IN ('roll','rate','snooze','rolled_but_skipped') ORDER BY timestamp DESC, id DESC LIMIT 1";
const PENDING_THREAD_SQL: &str = "SELECT id, title, format, issues_remaining, total_issues, reading_progress, next_unread_issue_id, user_id FROM threads WHERE id = $1 AND user_id = $2";
const ROLLED_THREAD_SQL: &str = "SELECT id, title, format, issues_remaining, total_issues, reading_progress, next_unread_issue_id, user_id FROM threads WHERE id = $1";
const UNREAD_COUNT_SQL: &str = "SELECT count(*)::int FROM issues WHERE thread_id = $1 AND status = 'unread'";
const NEXT_ISSUE_SQL: &str = "SELECT id, issue_number FROM issues WHERE id = $1";
const TAGS_SQL: &str = "SELECT tag.id, tag.name, tag.normalized_name, tag.scope, tag.owner_user_id, tag.color, to_char(tag.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(tag.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') FROM tag_assignments assignment JOIN tags tag ON tag.id = assignment.tag_id WHERE assignment.target_type = 'Thread' AND assignment.target_id = $1 AND (tag.scope = 'global' OR tag.owner_user_id = $2) ORDER BY tag.scope DESC, tag.normalized_name ASC";
const QUEUE_POSITION_SQL: &str = "SELECT seq::int FROM (SELECT id, row_number() OVER (ORDER BY is_blocked ASC, queue_position ASC, id ASC) AS seq FROM threads WHERE user_id = $1 AND status = 'active' AND queue_position >= 1) ranked WHERE id = $2";

const SNAPSHOT_VERSION: i32 = 2;
const SNAPSHOT_VERSION_KEY: &str = "_snapshot_version";
const USES_ISSUE_TRACKING_KEY: &str = "uses_issue_tracking";
const ISSUE_STATES_KEY: &str = "issue_states";
const ISSUE_CHANGES_KEY: &str = "issue_changes";
const CREATED_ISSUES_KEY: &str = "created_issues";
const DELETED_ISSUES_KEY: &str = "deleted_issues";
const QUEUE_CHANGES_KEY: &str = "queue_changes";
const BLOCKED_CHANGES_KEY: &str = "blocked_changes";

fn not_found() -> ApiError {
    ApiError::with_status(StatusCode::NOT_FOUND, "Session not found".to_string())
}

fn snapshot_not_found() -> ApiError {
    ApiError::with_status(StatusCode::NOT_FOUND, "Snapshot not found".to_string())
}

fn conflict_only_latest() -> ApiError {
    ApiError::with_status(
        StatusCode::CONFLICT,
        "Only the latest rating can be undone".to_string(),
    )
}

fn internal() -> ApiError {
    ApiError::with_status(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Internal Server Error".to_string(),
    )
}

/// Python `normalize_format_value`: trim, then map known variants.
pub(crate) fn normalize_format(value: &str) -> String {
    let stripped = value.trim();
    match stripped.to_ascii_lowercase().as_str() {
        "comic" | "comics" => "Comic".to_string(),
        "digital" => "Digital".to_string(),
        _ => stripped.to_string(),
    }
}

fn normalize_bandwidth_level(value: Option<&str>) -> Option<String> {
    match value {
        Some("light" | "balanced" | "deep") => value.map(str::to_owned),
        _ => None,
    }
}

fn normalize_intent_level(value: Option<&str>) -> Option<String> {
    match value {
        Some("balanced" | "momentum" | "familiar" | "explore" | "random") => value.map(str::to_owned),
        _ => None,
    }
}

fn normalize_source(value: Option<&str>) -> Option<String> {
    match value {
        Some("inferred" | "manual" | "snooze" | "quiz") => value.map(str::to_owned),
        _ => None,
    }
}

fn normalize_confidence(value: Option<f64>) -> Option<f64> {
    value.filter(|confidence| (0.0..=1.0).contains(confidence))
}

fn bandwidth_state(
    predicted: Option<&str>,
    active: Option<&str>,
    confidence: Option<f64>,
    source: Option<&str>,
    version: Option<&str>,
) -> SessionBandwidthState {
    SessionBandwidthState {
        predicted_bandwidth: normalize_bandwidth_level(predicted),
        active_bandwidth: normalize_bandwidth_level(active),
        confidence: normalize_confidence(confidence),
        source: normalize_source(source),
        mode_version: version.map(str::to_owned),
    }
}

fn intent_state(
    predicted: Option<&str>,
    active: Option<&str>,
    confidence: Option<f64>,
    source: Option<&str>,
    version: Option<&str>,
) -> SessionIntentState {
    SessionIntentState {
        predicted_intent: normalize_intent_level(predicted),
        active_intent: normalize_intent_level(active),
        confidence: normalize_confidence(confidence),
        source: normalize_source(source),
        mode_version: version.map(str::to_owned),
    }
}

/// Python `build_ladder_path`: start die plus chronological die-after values.
pub(crate) fn ladder_path(start_die: i32, die_after: &[i32]) -> String {
    let mut parts = vec![start_die.to_string()];
    parts.extend(die_after.iter().map(i32::to_string));
    parts.join(" → ")
}

/// Python `get_current_die` resolution.
pub(crate) fn current_die(
    manual_die: Option<i32>,
    latest: Option<(i32, &Value)>,
    start_die: i32,
) -> i32 {
    if let Some((die_after, context)) = latest {
        return automatic_die_after(die_after, context);
    }
    manual_die.filter(|value| *value != 0).unwrap_or(start_die)
}

/// Check if a snapshot uses the version-two delta contract.
fn is_delta_snapshot(thread_states: &Option<Value>) -> bool {
    thread_states
        .as_ref()
        .and_then(|v| v.as_object())
        .and_then(|obj| obj.get(SNAPSHOT_VERSION_KEY))
        .and_then(|v| v.as_i64())
        .map(|v| v == SNAPSHOT_VERSION as i64)
        .unwrap_or(false)
}

/// Apply a full (session-start or legacy) snapshot.
async fn apply_full_snapshot(
    connection: &deadpool_postgres::Object,
    session: &mut SessionState,
    snapshot_thread_states: &Value,
    snapshot_session_state: &Option<Value>,
    user_id: i32,
) -> Result<(), ApiError> {
    let current_threads = connection
        .query("SELECT id FROM threads WHERE user_id = $1", &[&user_id])
        .await
        .map_err(db::query_error)?;
    let current_thread_ids: std::collections::HashSet<i32> = current_threads
        .iter()
        .map(|row| row.try_get(0).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        }))
        .collect::<Result<_, ApiError>>()?;

    let snapshot_thread_ids: std::collections::HashSet<i32> = snapshot_thread_states
        .as_object()
        .map(|obj| {
            obj.keys()
                .filter_map(|k| k.parse::<i32>().ok())
                .collect()
        })
        .unwrap_or_default();

    let threads_to_delete = current_thread_ids.difference(&snapshot_thread_ids).copied().collect::<Vec<_>>();

    if !threads_to_delete.is_empty() {
        // Clear pending thread references
        connection
            .execute(
                "UPDATE sessions SET pending_thread_id = NULL, pending_issue_id = NULL, pending_thread_updated_at = NULL WHERE id = $1 AND user_id = $2",
                &[&session.id, &user_id],
            )
            .await
            .map_err(db::query_error)?;

        // Clear event references
        connection
            .execute(
                "UPDATE events SET thread_id = NULL WHERE session_id = $1 AND thread_id = ANY($2)",
                &[&session.id, &threads_to_delete],
            )
            .await
            .map_err(db::query_error)?;

        // Delete threads
        connection
            .execute(
                "DELETE FROM threads WHERE id = ANY($1) AND user_id = $2",
                &[&threads_to_delete, &user_id],
            )
            .await
            .map_err(db::query_error)?;
    }

    // Restore threads from snapshot
    let restore_thread_ids: Vec<i32> = snapshot_thread_states
        .as_object()
        .map(|obj| {
            obj.keys()
                .filter_map(|k| {
                    let tid = k.parse::<i32>().ok()?;
                    if !k.starts_with('_') {
                        Some(tid)
                    } else {
                        None
                    }
                })
                .collect()
        })
        .unwrap_or_default();

    if !restore_thread_ids.is_empty() {
        let threads_rows = connection
            .query(
                &format!(
                    "SELECT id, title, format, issues_remaining, total_issues, reading_progress, next_unread_issue_id, user_id FROM threads WHERE id = ANY($1)",
                ),
                &[&restore_thread_ids],
            )
            .await
            .map_err(db::query_error)?;
        let mut threads_by_id: HashMap<i32, tokio_postgres::Row> = HashMap::new();
        for row in threads_rows {
            let tid: i32 = row.try_get(0).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            threads_by_id.insert(tid, row);
        }

        for (thread_id_str, state_val) in snapshot_thread_states.as_object().unwrap_or(&serde_json::Map::new()) {
            if thread_id_str.starts_with('_') {
                continue;
            }
            let tid: i32 = thread_id_str.parse().map_err(|_| internal())?;
            let thread = threads_by_id.get(&tid).cloned();

            restore_thread_from_state(connection, tid, state_val, user_id, thread).await?;
        }
    }

    // Restore session state
    if let Some(sess_state) = snapshot_session_state {
        if let Some(start_die) = sess_state.get("start_die").and_then(|v| v.as_i64()) {
            session.start_die = start_die as i32;
        }
        if let Some(manual_die) = sess_state.get("manual_die").and_then(|v| v.as_i64()) {
            session.manual_die = Some(manual_die as i32);
        }
        if let Some(pending_thread_id) = sess_state.get("pending_thread_id").and_then(|v| v.as_i64()) {
            session.pending_thread_id = Some(pending_thread_id as i32);
        }
        if let Some(pending_issue_id) = sess_state.get("pending_issue_id").and_then(|v| v.as_i64()) {
            session.pending_issue_id = Some(pending_issue_id as i32);
        }
        if let Some(pending_thread_updated_at) = sess_state.get("pending_thread_updated_at").and_then(|v| v.as_str()) {
            session.pending_thread_updated_at = Some(pending_thread_updated_at.to_string());
        }
        if let Some(ended_at) = sess_state.get("ended_at").and_then(|v| v.as_str()) {
            session.ended_at = Some(ended_at.to_string());
        }
        if let Some(snoozed_thread_ids) = sess_state.get("snoozed_thread_ids").and_then(|v| v.as_array()) {
            session.snoozed_thread_ids = snoozed_thread_ids.iter().filter_map(|v| v.as_i64().map(|i| i as i32)).collect();
        }
        // Restore ephemeral bandwidth/intent from session state
        if let Some(predicted_bandwidth) = sess_state.get("predicted_bandwidth").and_then(|v| v.as_str()) {
            session.predicted_bandwidth = Some(predicted_bandwidth.to_string());
        }
        if let Some(active_bandwidth) = sess_state.get("active_bandwidth").and_then(|v| v.as_str()) {
            session.active_bandwidth = Some(active_bandwidth.to_string());
        }
        if let Some(bandwidth_confidence) = sess_state.get("bandwidth_confidence").and_then(|v| v.as_f64()) {
            session.bandwidth_confidence = Some(bandwidth_confidence);
        }
        if let Some(bandwidth_source) = sess_state.get("bandwidth_source").and_then(|v| v.as_str()) {
            session.bandwidth_source = Some(bandwidth_source.to_string());
        }
        if let Some(bandwidth_version) = sess_state.get("bandwidth_version").and_then(|v| v.as_str()) {
            session.bandwidth_version = Some(bandwidth_version.to_string());
        }
        if let Some(predicted_intent) = sess_state.get("predicted_intent").and_then(|v| v.as_str()) {
            session.predicted_intent = Some(predicted_intent.to_string());
        }
        if let Some(active_intent) = sess_state.get("active_intent").and_then(|v| v.as_str()) {
            session.active_intent = Some(active_intent.to_string());
        }
        if let Some(intent_confidence) = sess_state.get("intent_confidence").and_then(|v| v.as_f64()) {
            session.intent_confidence = Some(intent_confidence);
        }
        if let Some(intent_source) = sess_state.get("intent_source").and_then(|v| v.as_str()) {
            session.intent_source = Some(intent_source.to_string());
        }
        if let Some(intent_version) = sess_state.get("intent_version").and_then(|v| v.as_str()) {
            session.intent_version = Some(intent_version.to_string());
        }
    }

    Ok(())
}

/// Apply a delta (rating) snapshot.
async fn apply_delta_snapshot(
    connection: &deadpool_postgres::Object,
    session: &mut SessionState,
    snapshot_thread_states: &Value,
    snapshot_session_state: &Option<Value>,
    user_id: i32,
) -> Result<(), ApiError> {
    let empty_map = serde_json::Map::new();
    let thread_states = snapshot_thread_states.as_object().unwrap_or(&empty_map);

    // Handle queue position changes
    if let Some(queue_changes) = thread_states.get(QUEUE_CHANGES_KEY).and_then(|v| v.as_object()) {
        let mut changes: HashMap<i32, i32> = HashMap::new();
        for (thread_id_str, old_position) in queue_changes {
            if let (Ok(tid), Some(pos)) = (thread_id_str.parse::<i32>(), old_position.as_i64()) {
                changes.insert(tid, pos as i32);
            }
        }
        if !changes.is_empty() {
            for (tid, pos) in changes {
                connection
                    .execute(
                        "UPDATE threads SET queue_position = $1 WHERE id = $2 AND user_id = $3",
                        &[&pos, &tid, &user_id],
                    )
                    .await
                    .map_err(db::query_error)?;
            }
        }
    }

    // Handle blocked state changes
    if let Some(blocked_changes) = thread_states.get(BLOCKED_CHANGES_KEY).and_then(|v| v.as_object()) {
        for (thread_id_str, old_value) in blocked_changes {
            if let (Ok(tid), Some(blocked)) = (thread_id_str.parse::<i32>(), old_value.as_bool()) {
                connection
                    .execute(
                        "UPDATE threads SET is_blocked = $1 WHERE id = $2 AND user_id = $3",
                        &[&blocked, &tid, &user_id],
                    )
                    .await
                    .map_err(db::query_error)?;
            }
        }
    }

    // Restore threads from delta state
    let restore_thread_ids: Vec<i32> = thread_states
        .keys()
        .filter_map(|k| {
            let tid = k.parse::<i32>().ok()?;
            if !k.starts_with('_') {
                Some(tid)
            } else {
                None
            }
        })
        .collect();

    if !restore_thread_ids.is_empty() {
        let threads_rows = connection
            .query(
                &format!(
                    "SELECT id, title, format, issues_remaining, total_issues, reading_progress, next_unread_issue_id, user_id FROM threads WHERE id = ANY($1)",
                ),
                &[&restore_thread_ids],
            )
            .await
            .map_err(db::query_error)?;
        let mut threads_by_id: HashMap<i32, tokio_postgres::Row> = HashMap::new();
        for row in threads_rows {
            let tid: i32 = row.try_get(0).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            threads_by_id.insert(tid, row);
        }

        for (thread_id_str, state_val) in thread_states {
            if thread_id_str.starts_with('_') {
                continue;
            }
            let tid: i32 = thread_id_str.parse().map_err(|_| internal())?;
            let thread = threads_by_id.get(&tid).cloned();

            restore_thread_from_state(connection, tid, state_val, user_id, thread).await?;
        }
    }

    // Restore session state from delta
    if let Some(sess_state) = snapshot_session_state {
        if let Some(start_die) = sess_state.get("start_die").and_then(|v| v.as_i64()) {
            session.start_die = start_die as i32;
        }
        if let Some(manual_die) = sess_state.get("manual_die").and_then(|v| v.as_i64()) {
            session.manual_die = Some(manual_die as i32);
        }
        if let Some(pending_thread_id) = sess_state.get("pending_thread_id").and_then(|v| v.as_i64()) {
            session.pending_thread_id = Some(pending_thread_id as i32);
        }
        if let Some(pending_issue_id) = sess_state.get("pending_issue_id").and_then(|v| v.as_i64()) {
            session.pending_issue_id = Some(pending_issue_id as i32);
        }
        if let Some(pending_thread_updated_at) = sess_state.get("pending_thread_updated_at").and_then(|v| v.as_str()) {
            session.pending_thread_updated_at = Some(pending_thread_updated_at.to_string());
        }
        if let Some(ended_at) = sess_state.get("ended_at").and_then(|v| v.as_str()) {
            session.ended_at = Some(ended_at.to_string());
        }
        if let Some(snoozed_thread_ids) = sess_state.get("snoozed_thread_ids").and_then(|v| v.as_array()) {
            session.snoozed_thread_ids = snoozed_thread_ids.iter().filter_map(|v| v.as_i64().map(|i| i as i32)).collect();
        }
    }

    Ok(())
}

/// Restore a single thread from snapshot state (full or delta).
async fn restore_thread_from_state(
    connection: &deadpool_postgres::Object,
    thread_id: i32,
    state: &Value,
    user_id: i32,
    pre_loaded_thread: Option<tokio_postgres::Row>,
) -> Result<(), ApiError> {
    let uses_issue_tracking = state
        .get(USES_ISSUE_TRACKING_KEY)
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    let has_issue_changes = state.get(ISSUE_CHANGES_KEY).is_some();
    let has_issue_states = state.get(ISSUE_STATES_KEY).is_some();

    // Compact delta path: apply only changed-issue preimages
    if has_issue_changes {
        // Drop the thread's issue pointer before surgery
        connection
            .execute(
                "UPDATE threads SET next_unread_issue_id = NULL WHERE id = $1 AND user_id = $2",
                &[&thread_id, &user_id],
            )
            .await
            .map_err(db::query_error)?;

        let existing_issues = if let Some(pre_loaded) = pre_loaded_thread {
            vec![pre_loaded]
        } else {
            connection
                .query(
                    "SELECT id, thread_id, issue_number, status, read_at, position FROM issues WHERE thread_id = $1",
                    &[&thread_id],
                )
                .await
                .map_err(db::query_error)?
        };
        let existing_by_id: HashMap<i32, tokio_postgres::Row> = existing_issues
            .into_iter()
            .filter_map(|row| row.try_get(0).ok().map(|id: i32| (id, row)))
            .collect();

        // Recreate deleted issues
        if let Some(deleted) = state.get(DELETED_ISSUES_KEY).and_then(|v| v.as_array()) {
            for deleted_issue in deleted {
                let deleted_id = deleted_issue.get("id").and_then(|v| v.as_i64()).ok_or_else(internal)?;
                if !existing_by_id.contains_key(&(deleted_id as i32)) {
                    let issue_number = deleted_issue.get("issue_number").and_then(|v| v.as_str()).unwrap_or("");
                    let position = deleted_issue.get("position").and_then(|v| v.as_i64()).unwrap_or(1);
                    connection
                        .execute(
                            "INSERT INTO issues (id, thread_id, issue_number, status, position) VALUES ($1, $2, $3, 'unread', $4)",
                            &[&deleted_id, &thread_id, &issue_number, &(position as i32)],
                        )
                        .await
                        .map_err(db::query_error)?;
                }
            }
        }

        // Restore changed issues
        if let Some(changes) = state.get(ISSUE_CHANGES_KEY).and_then(|v| v.as_array()) {
            for ch in changes {
                let issue_id = ch.get("id").and_then(|v| v.as_i64()).ok_or_else(internal)?;
                let issue_number = ch.get("issue_number").and_then(|v| v.as_str()).unwrap_or("");
                let status = ch.get("status").and_then(|v| v.as_str()).unwrap_or("unread");
                let read_at = ch.get("read_at").and_then(|v| v.as_str());
                let position = ch.get("position").and_then(|v| v.as_i64()).unwrap_or(1);

                connection
                    .execute(
                        "INSERT INTO issues (id, thread_id, issue_number, status, read_at, position) VALUES ($1, $2, $3, $4, $5, $6)
                         ON CONFLICT (id) DO UPDATE SET issue_number = $3, status = $4, read_at = $5, position = $6",
                        &[&issue_id, &thread_id, &issue_number, &status, &read_at, &(position as i32)],
                    )
                    .await
                    .map_err(db::query_error)?;
            }
        }

        // Delete created issues
        if let Some(created) = state.get(CREATED_ISSUES_KEY).and_then(|v| v.as_array()) {
            let created_ids: Vec<i64> = created.iter().filter_map(|c| c.get("id").and_then(|v| v.as_i64())).collect();
            if !created_ids.is_empty() {
                connection
                    .execute(
                        &format!("DELETE FROM issues WHERE id = ANY($1)"),
                        &[&created_ids],
                    )
                    .await
                    .map_err(db::query_error)?;
            }
        }

        // Restore thread counters from state
        if let Some(total_issues) = state.get("total_issues").and_then(|v| v.as_i64()) {
            connection
                .execute(
                    "UPDATE threads SET total_issues = $1 WHERE id = $2 AND user_id = $3",
                    &[&(total_issues as i32), &thread_id, &user_id],
                )
                .await
                .map_err(db::query_error)?;
        }
        if let Some(next_unread_issue_id) = state.get("next_unread_issue_id").and_then(|v| v.as_i64()) {
            connection
                .execute(
                    "UPDATE threads SET next_unread_issue_id = $1 WHERE id = $2 AND user_id = $3",
                    &[&(next_unread_issue_id as i32), &thread_id, &user_id],
                )
                .await
                .map_err(db::query_error)?;
        }
        if let Some(reading_progress) = state.get("reading_progress").and_then(|v| v.as_str()) {
            connection
                .execute(
                    "UPDATE threads SET reading_progress = $1 WHERE id = $2 AND user_id = $3",
                    &[&reading_progress, &thread_id, &user_id],
                )
                .await
                .map_err(db::query_error)?;
        }
        if let Some(issues_remaining) = state.get("issues_remaining").and_then(|v| v.as_i64()) {
            connection
                .execute(
                    "UPDATE threads SET issues_remaining = $1 WHERE id = $2 AND user_id = $3",
                    &[&(issues_remaining as i32), &thread_id, &user_id],
                )
                .await
                .map_err(db::query_error)?;
        }

        return Ok(());
    }

    // Full snapshot path: restore issue_states
    if has_issue_states || uses_issue_tracking {
        // Drop issue pointer
        connection
            .execute(
                "UPDATE threads SET next_unread_issue_id = NULL WHERE id = $1 AND user_id = $2",
                &[&thread_id, &user_id],
            )
            .await
            .map_err(db::query_error)?;

        let existing_issues = connection
            .query(
                "SELECT id FROM issues WHERE thread_id = $1",
                &[&thread_id],
            )
            .await
            .map_err(db::query_error)?;
        let existing_ids: std::collections::HashSet<i32> = existing_issues
            .iter()
            .filter_map(|row| row.try_get(0).ok())
            .collect();

        let snapshot_issues = state.get(ISSUE_STATES_KEY).and_then(|v| v.as_array()).unwrap_or(&Vec::new());
        let snapshot_ids: std::collections::HashSet<i32> = snapshot_issues
            .iter()
            .filter_map(|i| i.get("id").and_then(|v| v.as_i64().map(|x| x as i32)))
            .collect();

        // Delete extra issues
        let extra_ids: Vec<i32> = existing_ids.difference(&snapshot_ids).copied().collect();
        if !extra_ids.is_empty() {
            connection
                .execute(
                    &format!("DELETE FROM issues WHERE id = ANY($1)"),
                    &[&extra_ids],
                )
                .await
                .map_err(db::query_error)?;
        }

        // Restore/create issues
        for (pos, issue_state) in snapshot_issues.iter().enumerate() {
            let issue_id = issue_state.get("id").and_then(|v| v.as_i64()).ok_or_else(internal)?;
            let issue_number = issue_state.get("issue_number").and_then(|v| v.as_str()).unwrap_or("");
            let status = issue_state.get("status").and_then(|v| v.as_str()).unwrap_or("unread");
            let read_at = issue_state.get("read_at").and_then(|v| v.as_str());
            let position = issue_state.get("position").and_then(|v| v.as_i64()).unwrap_or((pos + 1) as i64);

            connection
                .execute(
                    "INSERT INTO issues (id, thread_id, issue_number, status, read_at, position) VALUES ($1, $2, $3, $4, $5, $6)
                     ON CONFLICT (id) DO UPDATE SET issue_number = $3, status = $4, read_at = $5, position = $6",
                    &[&issue_id, &thread_id, &issue_number, &status, &read_at, &(position as i32)],
                )
                .await
                .map_err(db::query_error)?;
        }

        // Restore thread counters
        if let Some(total_issues) = state.get("total_issues").and_then(|v| v.as_i64()) {
            connection
                .execute(
                    "UPDATE threads SET total_issues = $1 WHERE id = $2 AND user_id = $3",
                    &[&(total_issues as i32), &thread_id, &user_id],
                )
                .await
                .map_err(db::query_error)?;
        }
        if let Some(next_unread_issue_id) = state.get("next_unread_issue_id").and_then(|v| v.as_i64()) {
            connection
                .execute(
                    "UPDATE threads SET next_unread_issue_id = $1 WHERE id = $2 AND user_id = $3",
                    &[&(next_unread_issue_id as i32), &thread_id, &user_id],
                )
                .await
                .map_err(db::query_error)?;
        }
        if let Some(reading_progress) = state.get("reading_progress").and_then(|v| v.as_str()) {
            connection
                .execute(
                    "UPDATE threads SET reading_progress = $1 WHERE id = $2 AND user_id = $3",
                    &[&reading_progress, &thread_id, &user_id],
                )
                .await
                .map_err(db::query_error)?;
        }
        if let Some(issues_remaining) = state.get("issues_remaining").and_then(|v| v.as_i64()) {
            connection
                .execute(
                    "UPDATE threads SET issues_remaining = $1 WHERE id = $2 AND user_id = $3",
                    &[&(issues_remaining as i32), &thread_id, &user_id],
                )
                .await
                .map_err(db::query_error)?;
        }

        return Ok(());
    }

    // Counter-only thread (no issue tracking): just update thread fields
    if let Some(pre_loaded) = pre_loaded_thread {
        // Update thread from state
        if let Some(title) = state.get("title").and_then(|v| v.as_str()) {
            connection
                .execute(
                    "UPDATE threads SET title = $1 WHERE id = $2 AND user_id = $3",
                    &[&title, &thread_id, &user_id],
                )
                .await
                .map_err(db::query_error)?;
        }
        if let Some(format) = state.get("format").and_then(|v| v.as_str()) {
            connection
                .execute(
                    "UPDATE threads SET format = $1 WHERE id = $2 AND user_id = $3",
                    &[&format, &thread_id, &user_id],
                )
                .await
                .map_err(db::query_error)?;
        }
        if let Some(issues_remaining) = state.get("issues_remaining").and_then(|v| v.as_i64()) {
            connection
                .execute(
                    "UPDATE threads SET issues_remaining = $1 WHERE id = $2 AND user_id = $3",
                    &[&(issues_remaining as i32), &thread_id, &user_id],
                )
                .await
                .map_err(db::query_error)?;
        }
    }

    Ok(())
}

/// Clear event issue references for counter-only threads.
async fn clear_event_issue_references(
    connection: &deadpool_postgres::Object,
    session_id: i32,
    counter_thread_ids: &[i32],
) -> Result<(), ApiError> {
    if counter_thread_ids.is_empty() {
        return Ok(());
    }
    connection
        .execute(
            "UPDATE events SET issue_number = NULL WHERE session_id = $1 AND thread_id = ANY($2)",
            &[&session_id, &counter_thread_ids],
        )
        .await
        .map_err(db::query_error)?;
    Ok(())
}

/// Record an undo event.
async fn record_undo_event(
    connection: &deadpool_postgres::Object,
    session_id: i32,
    snapshot: &Value,
) -> Result<(), ApiError> {
    connection
        .execute(
            "INSERT INTO events (session_id, type, timestamp, context) VALUES ($1, 'undo', NOW(), $2)",
            &[&session_id, &json!({"snapshot_id": snapshot.get("id").and_then(|v| v.as_i64()).unwrap_or(0)})],
        )
        .await
        .map_err(db::query_error)?;
    Ok(())
}

/// Delete a delta snapshot after applying.
async fn delete_delta_snapshot(
    connection: &deadpool_postgres::Object,
    snapshot_id: i32,
) -> Result<(), ApiError> {
    connection
        .execute("DELETE FROM snapshots WHERE id = $1", &[&snapshot_id])
        .await
        .map_err(db::query_error)?;
    Ok(())
}

/// Minimal session state for undo apply.
#[derive(Debug)]
struct SessionState {
    id: i32,
    started_at: String,
    ended_at: Option<String>,
    start_die: i32,
    manual_die: Option<i32>,
    user_id: i32,
    pending_thread_id: Option<i32>,
    pending_issue_id: Option<i32>,
    pending_thread_updated_at: Option<String>,
    timezone: Option<String>,
    reading_bandwidth: Option<String>,
    reading_intent: Option<String>,
    reading_mode_source: Option<String>,
    reading_mode_suggested: bool,
    predicted_bandwidth: Option<String>,
    active_bandwidth: Option<String>,
    bandwidth_confidence: Option<f64>,
    bandwidth_source: Option<String>,
    bandwidth_version: Option<String>,
    predicted_intent: Option<String>,
    active_intent: Option<String>,
    intent_confidence: Option<f64>,
    intent_source: Option<String>,
    intent_version: Option<String>,
    snoozed_thread_ids: Vec<i32>,
}

/// `POST /api/undo/{session_id}/undo/{snapshot_id}` and
/// `POST /api/v1/undo/{session_id}/undo/{snapshot_id}`.
pub async fn undo_to_snapshot(
    Path((session_id, snapshot_id)): Path<(i32, i32)>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<UndoApplyResponse>, ApiError> {
    // Deadlock retry handling (matching Python)
    const MAX_RETRIES: u32 = 3;
    const INITIAL_DELAY_MS: u64 = 100;

    for attempt in 0..MAX_RETRIES {
        let connection = db::checkout(&state).await?;

        let result = async {
            // Get session with ownership check
            let session_row = connection
                .query_opt(SESSION_OWNERSHIP_SQL, &[&session_id, &user.id()])
                .await
                .map_err(db::query_error)?
                .ok_or_else(not_found)?;

            let mut session = SessionState {
                id: session_id,
                started_at: session_row.try_get(1).map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    internal()
                })?,
                ended_at: session_row.try_get(2).ok().flatten(),
                start_die: session_row.try_get(3).map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    internal()
                })?,
                manual_die: session_row.try_get(4).ok().flatten(),
                user_id: session_row.try_get(5).map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    internal()
                })?,
                pending_thread_id: session_row.try_get(6).ok().flatten(),
                pending_issue_id: None,
                pending_thread_updated_at: None,
                timezone: session_row.try_get(7).ok().flatten(),
                reading_bandwidth: session_row.try_get(8).ok().flatten(),
                reading_intent: session_row.try_get(9).ok().flatten(),
                reading_mode_source: session_row.try_get(10).ok().flatten(),
                reading_mode_suggested: session_row.try_get(11).ok().flatten().unwrap_or(false),
                predicted_bandwidth: session_row.try_get(12).ok().flatten(),
                active_bandwidth: session_row.try_get(13).ok().flatten(),
                bandwidth_confidence: session_row.try_get(14).ok().flatten(),
                bandwidth_source: session_row.try_get(15).ok().flatten(),
                bandwidth_version: session_row.try_get(16).ok().flatten(),
                predicted_intent: session_row.try_get(17).ok().flatten(),
                active_intent: session_row.try_get(18).ok().flatten(),
                intent_confidence: session_row.try_get(19).ok().flatten(),
                intent_source: session_row.try_get(20).ok().flatten(),
                intent_version: session_row.try_get(21).ok().flatten(),
                snoozed_thread_ids: session_row.try_get(22).ok().flatten().unwrap_or_default(),
            };

            // Get snapshot
            let snapshot_row = connection
                .query_opt(SNAPSHOT_SQL, &[&snapshot_id, &session_id])
                .await
                .map_err(db::query_error)?
                .ok_or_else(snapshot_not_found)?;

            let snapshot_thread_states: Value = snapshot_row.try_get(1).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            let snapshot_session_state: Option<Value> = snapshot_row.try_get(2).ok();
            let snapshot_kind: Option<String> = snapshot_row.try_get(3).ok();

            // Check if delta snapshot and validate it's the latest
            let is_delta = is_delta_snapshot(&Some(snapshot_thread_states.clone()));
            if is_delta {
                let latest_delta_row = connection
                    .query_opt(LATEST_DELTA_SQL, &[&session_id])
                    .await
                    .map_err(db::query_error)?;
                let latest_delta_id: Option<i32> = latest_delta_row
                    .map(|row| row.try_get(0).ok().flatten())
                    .flatten();
                if latest_delta_id != Some(snapshot_id) {
                    return Err(conflict_only_latest());
                }
            }

            // Apply snapshot
            if is_delta {
                apply_delta_snapshot(&connection, &mut session, &snapshot_thread_states, &snapshot_session_state, user.id()).await?;
            } else {
                apply_full_snapshot(&connection, &mut session, &snapshot_thread_states, &snapshot_session_state, user.id()).await?;
            }

            // Handle counter-only snapshots - clear event issue references
            let counter_thread_ids: Vec<i32> = snapshot_thread_states
                .as_object()
                .map(|obj| {
                    obj.iter()
                        .filter_map(|(k, v)| {
                            let tid = k.parse::<i32>().ok()?;
                            if v.get(USES_ISSUE_TRACKING_KEY).and_then(|v| v.as_bool()) == Some(false) {
                                Some(tid)
                            } else {
                                None
                            }
                        })
                        .collect()
                })
                .unwrap_or_default();
            if !counter_thread_ids.is_empty() {
                clear_event_issue_references(&connection, session_id, &counter_thread_ids).await?;
            }

            // Record undo event
            record_undo_event(&connection, session_id, &snapshot_thread_states).await?;

            // Delete delta snapshot after applying
            if is_delta {
                delete_delta_snapshot(&connection, snapshot_id).await?;
            }

            Ok(session)
        }.await;

        match result {
            Ok(mut session) => {
                // Build response after successful commit
                let connection = db::checkout(&state).await?;

                // Snapshot count
                let snapshot_count: i32 = connection
                    .query_one(SNAPSHOT_COUNT_SQL, &[&session_id])
                    .await
                    .map_err(db::query_error)?
                    .try_get(0)
                    .map_err(|e| {
                        tracing::debug!(
                            error_kind = crate::error_kind(&e),
                            "preserved underlying error before mapping"
                        );
                        internal()
                    })?;

                // Ladder path
                let ladder_rows = connection
                    .query(LADDER_SQL, &[&session_id])
                    .await
                    .map_err(db::query_error)?;
                let ladder_values: Vec<i32> = ladder_rows
                    .iter()
                    .map(|row| row.try_get(0).map_err(|e| {
                        tracing::debug!(
                            error_kind = crate::error_kind(&e),
                            "preserved underlying error before mapping"
                        );
                        internal()
                    }))
                    .collect::<Result<_, ApiError>>()?;
                let ladder = ladder_path(session.start_die, &ladder_values);

                // Current die
                let die_row = connection
                    .query_opt(CURRENT_DIE_SQL, &[&session_id])
                    .await
                    .map_err(db::query_error)?;
                let resolved_die = match die_row {
                    Some(row) => {
                        let die_after: i32 = row.try_get(0).map_err(|e| {
                            tracing::debug!(
                                error_kind = crate::error_kind(&e),
                                "preserved underlying error before mapping"
                            );
                            internal()
                        })?;
                        let context_text: Option<String> = row.try_get(1).map_err(|e| {
                            tracing::debug!(
                                error_kind = crate::error_kind(&e),
                                "preserved underlying error before mapping"
                            );
                            internal()
                        })?;
                        let context: Value = context_text
                            .as_deref()
                            .and_then(|text| serde_json::from_str(text).ok())
                            .unwrap_or(Value::Null);
                        current_die(session.manual_die, Some((die_after, &context)), session.start_die)
                    }
                    None => current_die(session.manual_die, None, session.start_die),
                };

                // Latest action event
                let action_row = connection
                    .query_opt(LATEST_ACTION_SQL, &[&session_id])
                    .await
                    .map_err(db::query_error)?;
                let (action_type, selected_thread_id, roll_result) = match action_row {
                    Some(row) => (
                        row.try_get(0).map_err(|e| {
                            tracing::debug!(
                                error_kind = crate::error_kind(&e),
                                "preserved underlying error before mapping"
                            );
                            internal()
                        })?,
                        row.try_get(1).map_err(|e| {
                            tracing::debug!(
                                error_kind = crate::error_kind(&e),
                                "preserved underlying error before mapping"
                            );
                            internal()
                        })?,
                        row.try_get(2).map_err(|e| {
                            tracing::debug!(
                                error_kind = crate::error_kind(&e),
                                "preserved underlying error before mapping"
                            );
                            internal()
                        })?,
                    ),
                    None => (String::new(), None, None),
                };
                let is_roll = action_type == "roll";
                let last_rolled_result = if is_roll { roll_result } else { None };

                // Active thread
                let active_candidate: Option<i32> = if session.pending_thread_id.is_some() {
                    session.pending_thread_id
                } else if is_roll {
                    selected_thread_id
                } else {
                    None
                };
                let active_thread = match active_candidate {
                    None => None,
                    Some(thread_id) => {
                        let thread_row = if session.pending_thread_id.is_some() {
                            connection
                                .query_opt(PENDING_THREAD_SQL, &[&thread_id, &user.id()])
                                .await
                                .map_err(db::query_error)?
                        } else {
                            connection
                                .query_opt(ROLLED_THREAD_SQL, &[&thread_id])
                                .await
                                .map_err(db::query_error)?
                        };
                        match thread_row {
                            None => None,
                            Some(thread_row) => {
                                let thread_owner: i32 = thread_row.try_get(7).map_err(|e| {
                                    tracing::debug!(
                                        error_kind = crate::error_kind(&e),
                                        "preserved underlying error before mapping"
                                    );
                                    internal()
                                })?;
                                if session.pending_thread_id.is_none() && thread_owner != session.user_id {
                                    None
                                } else {
                                    let thread_id_value: i32 = thread_row.try_get(0).map_err(|e| {
                                        tracing::debug!(
                                            error_kind = crate::error_kind(&e),
                                            "preserved underlying error before mapping"
                                        );
                                        internal()
                                    })?;
                                    let title: String = thread_row.try_get(1).map_err(|e| {
                                        tracing::debug!(
                                            error_kind = crate::error_kind(&e),
                                            "preserved underlying error before mapping"
                                        );
                                        internal()
                                    })?;
                                    let format: String = thread_row.try_get(2).map_err(|e| {
                                        tracing::debug!(
                                            error_kind = crate::error_kind(&e),
                                            "preserved underlying error before mapping"
                                        );
                                        internal()
                                    })?;
                                    let stored_remaining: i32 = thread_row.try_get(3).map_err(|e| {
                                        tracing::debug!(
                                            error_kind = crate::error_kind(&e),
                                            "preserved underlying error before mapping"
                                        );
                                        internal()
                                    })?;
                                    let total_issues: Option<i32> = thread_row.try_get(4).map_err(|e| {
                                        tracing::debug!(
                                            error_kind = crate::error_kind(&e),
                                            "preserved underlying error before mapping"
                                        );
                                        internal()
                                    })?;
                                    let reading_progress: Option<String> =
                                        thread_row.try_get(5).map_err(|e| {
                                            tracing::debug!(
                                                error_kind = crate::error_kind(&e),
                                                "preserved underlying error before mapping"
                                            );
                                            internal()
                                        })?;
                                    let next_unread_issue_id: Option<i32> =
                                        thread_row.try_get(6).map_err(|e| {
                                            tracing::debug!(
                                                error_kind = crate::error_kind(&e),
                                                "preserved underlying error before mapping"
                                            );
                                            internal()
                                        })?;

                                    let issues_remaining = if total_issues.is_some() {
                                        connection
                                            .query_one(UNREAD_COUNT_SQL, &[&thread_id_value])
                                            .await
                                            .map_err(db::query_error)?
                                            .try_get(0)
                                            .map_err(|e| {
                                                tracing::debug!(
                                                    error_kind = crate::error_kind(&e),
                                                    "preserved underlying error before mapping"
                                                );
                                                internal()
                                            })?
                                    } else {
                                        stored_remaining
                                    };

                                    let (next_issue_id, next_issue_number) = match next_unread_issue_id {
                                        Some(issue_id) if total_issues.is_some() => {
                                            let issue_row = connection
                                                .query_opt(NEXT_ISSUE_SQL, &[&issue_id])
                                                .await
                                                .map_err(db::query_error)?;
                                            match issue_row {
                                                Some(issue_row) => (
                                                    Some(issue_row.try_get(0).map_err(|e| {
                                                        tracing::debug!(
                                                            error_kind = crate::error_kind(&e),
                                                            "preserved underlying error before mapping"
                                                        );
                                                        internal()
                                                    })?),
                                                    issue_row.try_get(1).map_err(|e| {
                                                        tracing::debug!(
                                                            error_kind = crate::error_kind(&e),
                                                            "preserved underlying error before mapping"
                                                        );
                                                        internal()
                                                    })?,
                                                ),
                                                None => (None, None),
                                            }
                                        }
                                        _ => (None, None),
                                    };

                                    let tag_rows = connection
                                        .query(TAGS_SQL, &[&thread_id_value, &user.id()])
                                        .await
                                        .map_err(db::query_error)?;
                                    let mut tags = Vec::with_capacity(tag_rows.len());
                                    for tag_row in &tag_rows {
                                        tags.push(SessionTag {
                                            id: tag_row.try_get(0).map_err(|e| {
                                                tracing::debug!(
                                                    error_kind = crate::error_kind(&e),
                                                    "preserved underlying error before mapping"
                                                );
                                                internal()
                                            })?,
                                            name: tag_row.try_get(1).map_err(|e| {
                                                tracing::debug!(
                                                    error_kind = crate::error_kind(&e),
                                                    "preserved underlying error before mapping"
                                                );
                                                internal()
                                            })?,
                                            normalized_name: tag_row.try_get(2).map_err(|e| {
                                                tracing::debug!(
                                                    error_kind = crate::error_kind(&e),
                                                    "preserved underlying error before mapping"
                                                );
                                                internal()
                                            })?,
                                            scope: tag_row.try_get(3).map_err(|e| {
                                                tracing::debug!(
                                                    error_kind = crate::error_kind(&e),
                                                    "preserved underlying error before mapping"
                                                );
                                                internal()
                                            })?,
                                            owner_user_id: tag_row.try_get(4).map_err(|e| {
                                                tracing::debug!(
                                                    error_kind = crate::error_kind(&e),
                                                    "preserved underlying error before mapping"
                                                );
                                                internal()
                                            })?,
                                            color: tag_row.try_get(5).map_err(|e| {
                                                tracing::debug!(
                                                    error_kind = crate::error_kind(&e),
                                                    "preserved underlying error before mapping"
                                                );
                                                internal()
                                            })?,
                                            created_at: tag_row.try_get(6).map_err(|e| {
                                                tracing::debug!(
                                                    error_kind = crate::error_kind(&e),
                                                    "preserved underlying error before mapping"
                                                );
                                                internal()
                                            })?,
                                            updated_at: tag_row.try_get(7).map_err(|e| {
                                                tracing::debug!(
                                                    error_kind = crate::error_kind(&e),
                                                    "preserved underlying error before mapping"
                                                );
                                                internal()
                                            })?,
                                        });
                                    }

                                    let queue_row = connection
                                        .query_opt(QUEUE_POSITION_SQL, &[&user.id(), &thread_id_value])
                                        .await
                                        .map_err(db::query_error)?;
                                    let queue_position: i32 = match queue_row {
                                        Some(row) => row.try_get(0).map_err(|e| {
                                            tracing::debug!(
                                                error_kind = crate::error_kind(&e),
                                                "preserved underlying error before mapping"
                                            );
                                            internal()
                                        })?,
                                        None => 0,
                                    };
                                    let safe_result = roll_result.filter(|r| *r > 0);

                                    Some(SessionActiveThread {
                                        id: thread_id_value,
                                        title,
                                        format: normalize_format(&format),
                                        issues_remaining,
                                        queue_position,
                                        last_rolled_result: safe_result,
                                        total_issues,
                                        reading_progress,
                                        issues_read: None,
                                        last_rating: None,
                                        tags,
                                        issue_id: next_issue_id,
                                        issue_number: next_issue_number.clone(),
                                        next_issue_id,
                                        next_issue_number,
                                    })
                                }
                            }
                        }
                    }
                };

                // Snoozed threads
                let mut snoozed_threads = Vec::new();
                if !session.snoozed_thread_ids.is_empty() {
                    let snoozed_rows = connection
                        .query(
                            &format!("SELECT id, title FROM threads WHERE id = ANY($1)"),
                            &[&session.snoozed_thread_ids],
                        )
                        .await
                        .map_err(db::query_error)?;
                    for row in snoozed_rows {
                        snoozed_threads.push(SessionThreadSummary {
                            id: row.try_get(0).map_err(|e| {
                                tracing::debug!(
                                    error_kind = crate::error_kind(&e),
                                    "preserved underlying error before mapping"
                                );
                                internal()
                            })?,
                            title: row.try_get(1).map_err(|e| {
                                tracing::debug!(
                                    error_kind = crate::error_kind(&e),
                                    "preserved underlying error before mapping"
                                );
                                internal()
                            })?,
                        });
                    }
                }

                return Ok(Json(UndoApplyResponse {
                    id: session_id,
                    started_at: session.started_at,
                    ended_at: session.ended_at,
                    start_die: session.start_die,
                    manual_die: session.manual_die,
                    user_id: session.user_id,
                    ladder_path: ladder,
                    active_thread: active_thread.clone(),
                    current_die: resolved_die,
                    last_rolled_result: active_thread
                        .as_ref()
                        .and_then(|thread| thread.last_rolled_result),
                    has_restore_point: snapshot_count > 0,
                    snapshot_count,
                    snoozed_thread_ids: session.snoozed_thread_ids.clone(),
                    snoozed_threads,
                    skipped_thread_ids: Vec::new(),
                    skipped_threads: Vec::new(),
                    pending_thread_id: session.pending_thread_id,
                    timezone: session.timezone,
                    reading_bandwidth: session.reading_bandwidth,
                    reading_intent: session.reading_intent,
                    reading_mode_source: session.reading_mode_source,
                    reading_mode_suggested: session.reading_mode_suggested,
                    bandwidth: Some(bandwidth_state(
                        session.predicted_bandwidth.as_deref(),
                        session.active_bandwidth.as_deref(),
                        session.bandwidth_confidence,
                        session.bandwidth_source.as_deref(),
                        session.bandwidth_version.as_deref(),
                    )),
                    intent: Some(intent_state(
                        session.predicted_intent.as_deref(),
                        session.active_intent.as_deref(),
                        session.intent_confidence,
                        session.intent_source.as_deref(),
                        session.intent_version.as_deref(),
                    )),
                }));
            }
            Err(e) => {
                // Check for deadlock
                let is_deadlock = matches!(&e, ApiError::DeadlockDetected);
                if is_deadlock && attempt < MAX_RETRIES - 1 {
                    tokio::time::sleep(std::time::Duration::from_millis(
                        INITIAL_DELAY_MS * (2_u64.pow(attempt)),
                    ))
                    .await;
                    continue;
                }
                return Err(e);
            }
        }
    }

    Err(ApiError::with_status(
        StatusCode::INTERNAL_SERVER_ERROR,
        format!("Failed to undo to snapshot after {MAX_RETRIES} retries"),
    ))
}

/// Documentation-only operation for the unversioned undo apply.
#[utoipa::path(
    post,
    path = "/api/undo/{session_id}/undo/{snapshot_id}",
    tag = "undo",
    params(
        ("session_id" = i32, Path, description = "Owned reading session"),
        ("snapshot_id" = i32, Path, description = "Snapshot to restore")
    ),
    responses(
        (status = 200, description = "Restored session", body = UndoApplyResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session or snapshot not found"),
        (status = 409, description = "Only the latest rating can be undone"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn undo_to_snapshot_documentation() {}

/// Documentation-only operation for the versioned undo apply.
#[utoipa::path(
    post,
    path = "/api/v1/undo/{session_id}/undo/{snapshot_id}",
    tag = "undo",
    params(
        ("session_id" = i32, Path, description = "Owned reading session"),
        ("snapshot_id" = i32, Path, description = "Snapshot to restore")
    ),
    responses(
        (status = 200, description = "Restored session", body = UndoApplyResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session or snapshot not found"),
        (status = 409, description = "Only the latest rating can be undone"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn undo_to_snapshot_v1_documentation() {}

/// OpenAPI document for the undo apply same-path surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(
        undo_to_snapshot_documentation,
        undo_to_snapshot_v1_documentation
    ),
    components(schemas(
        UndoApplyResponse,
        SessionActiveThread,
        SessionThreadSummary,
        SessionTag,
        SessionBandwidthState,
        SessionIntentState
    )),
    modifiers(&UndoApplySecurityAddon)
)]
pub struct UndoApplyApi;

struct UndoApplySecurityAddon;

impl utoipa::Modify for UndoApplySecurityAddon {
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
    use crate::{db, test_support};
    use utoipa::OpenApi;

    #[test]
    fn undo_apply_openapi_covers_both_same_paths() {
        let document = serde_json::to_value(UndoApplyApi::openapi()).expect("openapi");
        let paths = document["paths"].as_object().expect("paths");
        assert!(paths.contains_key("/api/undo/{session_id}/undo/{snapshot_id}"));
        assert!(paths.contains_key("/api/v1/undo/{session_id}/undo/{snapshot_id}"));
        for path in [
            "/api/undo/{session_id}/undo/{snapshot_id}",
            "/api/v1/undo/{session_id}/undo/{snapshot_id}",
        ] {
            let operation = &document["paths"][path]["post"];
            assert!(operation["operationId"].is_string());
            assert!(operation["responses"]["200"].as_object().is_some());
            assert!(operation["responses"]["404"].as_object().is_some());
            assert!(operation["responses"]["409"].as_object().is_some());
            assert!(operation["security"].is_array());
        }
        assert!(document["components"]["schemas"]["UndoApplyResponse"].is_object());
    }
}