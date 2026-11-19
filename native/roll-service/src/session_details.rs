//! Native same-path session details read (#4839, parent #4335).
//!
//! Migrates `GET /api/sessions/{session_id}/details` and
//! `GET /api/v1/sessions/{session_id}/details` to the native Rust router with
//! identical method/path and wire contract.
//!
//! Wire parity with Python `get_session_details` (`app/api/session.py`):
//!
//! * Ownership: `get_owned_session_or_404` — a foreign or missing session returns 404 with detail `"Session not found"`.
//! * Returns all session events formatted for the history timeline, plus narrative summary.
//! * `ladder_path`: `build_ladder_path` — `start_die` followed by every `die_after` from `rate`/`snooze`/`undo` events.
//! * `current_die`: event-derived die wins (#4352).
//! * Timestamps emitted as UTC `...Z` strings.
//!
//! Bounded reads: one session row, all events for that session (single query), narrative summary via shared service.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser, db, reading_session::automatic_die_after, ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::Serialize;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;
use utoipa::ToSchema;

/// Event detail for session details response.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionEventDetail {
    pub id: i32,
    // Python's event-detail contract and the frontend expect the JSON key `type`.
    // Keep the Rust field name `type_` (reserved keyword) but serialize as `type`.
    #[serde(rename = "type")]
    pub type_: String,
    pub timestamp: String,
    pub thread_title: Option<String>,
    pub thread_deleted: bool,
    pub issue_number: Option<String>,
    pub description: Option<String>,
    pub die: Option<i32>,
    pub result: Option<i32>,
    pub selection_method: Option<String>,
    pub rating: Option<f64>,
    pub issues_read: Option<i32>,
    pub queue_move: Option<String>,
    pub die_after: Option<i32>,
}

/// Full session details response with events and narrative summary.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct SessionDetailsResponse {
    pub session_id: i32,
    pub started_at: String,
    pub ended_at: Option<String>,
    pub start_die: i32,
    pub ladder_path: String,
    pub narrative_summary: HashMap<String, Vec<String>>,
    pub current_die: i32,
    pub timezone: Option<String>,
    pub events: Vec<SessionEventDetail>,
}

const SESSION_SQL: &str = "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, user_id, pending_thread_id, timezone, reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested, predicted_bandwidth, active_bandwidth, bandwidth_confidence, bandwidth_source, bandwidth_version, predicted_intent, active_intent, intent_confidence, intent_source, intent_version, snoozed_thread_ids FROM sessions WHERE id = $1 AND user_id = $2";
const EVENTS_SQL: &str = "SELECT id, type, to_char(timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), thread_id, selected_thread_id, issue_number, context, die, result, selection_method, rating, issues_read, queue_move, die_after FROM events WHERE session_id = $1 ORDER BY timestamp DESC, id DESC";
const SNAPSHOT_TITLES_SQL: &str = "SELECT thread_states::text FROM snapshots WHERE session_id = $1 ORDER BY created_at DESC, id DESC";
const LADDER_SQL: &str = "SELECT die_after FROM events WHERE session_id = $1 AND type IN ('rate','snooze','undo') AND die_after IS NOT NULL ORDER BY timestamp ASC, id ASC";
const CURRENT_DIE_SQL: &str = "SELECT die_after, context::text FROM events WHERE (user_id = $1 OR session_id = $2) AND type IN ('rate','snooze','undo','reset_dice','manual_die') AND die_after IS NOT NULL ORDER BY timestamp DESC, id DESC LIMIT 1";

fn not_found() -> ApiError {
    ApiError::with_status(StatusCode::NOT_FOUND, "Session not found".to_string())
}

fn internal() -> ApiError {
    ApiError::with_status(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Internal Server Error".to_string(),
    )
}

/// Python `build_ladder_path`: start die plus chronological die-after values.
pub(crate) fn ladder_path(start_die: i32, die_after: &[i32]) -> String {
    let mut parts = vec![start_die.to_string()];
    parts.extend(die_after.iter().map(i32::to_string));
    parts.join(" → ")
}

/// Python `get_current_die` resolution for one already-loaded session.
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

/// Reader-friendly verbs for session event types on the history timeline.
fn event_word(event_type: &str) -> String {
    match event_type {
        "skip" => "Skipped".to_string(),
        "rolled_but_skipped" => "Skipped".to_string(),
        "complete" => "Completed".to_string(),
        "completion" => "Completed".to_string(),
        "reorder" => "Reordered".to_string(),
        "undo" => "Restored".to_string(),
        "restore" => "Restored".to_string(),
        "move" => "Moved".to_string(),
        "shuffle" => "Shuffled".to_string(),
        "roll" => "Rolled".to_string(),
        "rate" => "Rated".to_string(),
        "unsnooze" => "Unsnoozed".to_string(),
        "dismiss" => "Dismissed".to_string(),
        _ => {
            let s = event_type.replace('_', " ");
            let mut chars = s.chars();
            match chars.next() {
                Some(first) => first.to_uppercase().to_string() + chars.as_str(),
                None => s,
            }
        }
    }
}

fn deleted_title(title: &str) -> String {
    format!("{} (deleted)", title)
}

fn mode_label(value: &str) -> String {
    let label = value.replace('_', " ").trim().to_string();
    if label.is_empty() {
        return value.to_string();
    }
    let mut chars = label.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().to_string() + chars.as_str(),
        None => value.to_string(),
    }
}

fn session_mode_description(event: &serde_json::Value) -> String {
    let context = event.get("context");
    let changed = context
        .and_then(|c| c.get("changed"))
        .and_then(|c| c.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str())
                .collect::<std::collections::HashSet<_>>()
        })
        .unwrap_or_default();

    let mut parts = Vec::new();
    if changed.contains("bandwidth") {
        if let Some(bandwidth) = context
            .and_then(|c| c.get("bandwidth"))
            .and_then(|v| v.as_str())
        {
            parts.push(format!("Bandwidth set to {}", mode_label(bandwidth)));
        }
    }
    if changed.contains("intent") {
        if let Some(intent) = context
            .and_then(|c| c.get("intent"))
            .and_then(|v| v.as_str())
        {
            parts.push(format!("Intent set to {}", mode_label(intent)));
        }
    }
    if parts.is_empty() {
        "Session mode changed".to_string()
    } else {
        parts.join(" · ")
    }
}

/// `GET /api/sessions/{session_id}/details` and `GET /api/v1/sessions/{session_id}/details`.
pub async fn get_session_details(
    Path(session_id): Path<i32>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<SessionDetailsResponse>, ApiError> {
    let connection = db::checkout(&state).await?;

    // Get owned session
    let session_row = connection
        .query_opt(SESSION_SQL, &[&session_id, &user.id()])
        .await
        .map_err(db::query_error)?
        .ok_or_else(not_found)?;

    let started_at: String = session_row.try_get(1).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let ended_at: Option<String> = session_row.try_get(2).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let start_die: i32 = session_row.try_get(3).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let manual_die: Option<i32> = session_row.try_get(4).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let timezone: Option<String> = session_row.try_get(7).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    // Python `build_narrative_summary` treats a persisted snooze column as the
    // authoritative boundary state and only replays the event stream when it is
    // absent. Preserve the null/empty distinction here.
    let snoozed_raw: Option<Value> = session_row.try_get(21).ok();

    // Fetch all events for this session
    let event_rows = connection
        .query(EVENTS_SQL, &[&session_id])
        .await
        .map_err(db::query_error)?;

    // Build ladder path
    let ladder_rows = connection
        .query(LADDER_SQL, &[&session_id])
        .await
        .map_err(db::query_error)?;
    let ladder_values: Vec<i32> = ladder_rows
        .iter()
        .map(|row| {
            row.try_get(0).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })
        })
        .collect::<Result<_, ApiError>>()?;
    let ladder = ladder_path(start_die, &ladder_values);

    // Current die
    let die_row = connection
        .query_opt(CURRENT_DIE_SQL, &[&user.id(), &session_id])
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
            let owned = context;
            current_die(manual_die, Some((die_after, &owned)), start_die)
        }
        None => current_die(manual_die, None, start_die),
    };

    // Collect thread IDs for title resolution
    let mut thread_ids = std::collections::HashSet::new();
    for row in &event_rows {
        let thread_id: Option<i32> = row.try_get(3).ok();
        let selected_thread_id: Option<i32> = row.try_get(4).ok();
        if let Some(tid) = thread_id.or(selected_thread_id) {
            thread_ids.insert(tid);
        }
    }

    // Load live thread titles
    let mut thread_titles = HashMap::new();
    if !thread_ids.is_empty() {
        let thread_id_list: Vec<i32> = thread_ids.iter().copied().collect();
        let thread_rows = connection
            .query(
                "SELECT id, title FROM threads WHERE id = ANY($1)",
                &[&thread_id_list],
            )
            .await
            .map_err(db::query_error)?;
        for row in thread_rows {
            let tid: i32 = row.try_get(0).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            let title: String = row.try_get(1).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?;
            thread_titles.insert(tid, title);
        }
    }

    // Python `build_session_event_details` recovers a deleted thread's last-known
    // title from the session's snapshots (newest first, first title wins). Events
    // stay flagged `thread_deleted`; the recovered title only softens the label.
    let mut snapshot_titles: HashMap<i32, String> = HashMap::new();
    let missing_ids: Vec<i32> = thread_ids
        .iter()
        .copied()
        .filter(|tid| !thread_titles.contains_key(tid))
        .collect();
    if !missing_ids.is_empty() {
        let snapshot_rows = connection
            .query(SNAPSHOT_TITLES_SQL, &[&session_id])
            .await
            .map_err(db::query_error)?;
        for row in snapshot_rows {
            let states_text: Option<String> = row.try_get(0).ok();
            let Some(states_text) = states_text else {
                continue;
            };
            let Ok(states) = serde_json::from_str::<Value>(&states_text) else {
                continue;
            };
            let Some(object) = states.as_object() else {
                continue;
            };
            for (key, state) in object {
                if key.starts_with('_') {
                    continue;
                }
                let Ok(tid) = key.parse::<i32>() else {
                    continue;
                };
                if !missing_ids.contains(&tid) || snapshot_titles.contains_key(&tid) {
                    continue;
                }
                let title = state
                    .get("title")
                    .and_then(|value| value.as_str())
                    .map(str::trim)
                    .filter(|title| !title.is_empty());
                if let Some(title) = title {
                    snapshot_titles.insert(tid, title.to_string());
                }
            }
            if snapshot_titles.len() == missing_ids.len() {
                break;
            }
        }
    }

    // Python `build_narrative_summary` always returns four keys, including
    // `snoozed` (series still snoozed at the session boundary).
    let still_snoozed_ids: Vec<i32> = match snoozed_raw.as_ref().and_then(|value| value.as_array())
    {
        Some(ids) => ids
            .iter()
            .filter_map(|value| value.as_i64())
            .filter_map(|id| i32::try_from(id).ok())
            .collect(),
        None => {
            // No persisted boundary state: replay the session's own ordered
            // snooze/unsnooze actions. EVENTS_SQL is DESC, so reverse for ASC.
            let mut replay = std::collections::BTreeSet::new();
            for row in event_rows.iter().rev() {
                let event_type: Option<String> = row.try_get(1).ok();
                let tid: Option<i32> = row.try_get(3).ok();
                match (event_type.as_deref(), tid) {
                    (Some("snooze"), Some(tid)) => {
                        replay.insert(tid);
                    }
                    (Some("unsnooze"), Some(tid)) => {
                        replay.remove(&tid);
                    }
                    _ => {}
                }
            }
            replay.into_iter().collect()
        }
    };
    let snoozed_titles: Vec<String> = {
        let titles: std::collections::BTreeSet<String> = still_snoozed_ids
            .into_iter()
            .map(|tid| {
                thread_titles
                    .get(&tid)
                    .cloned()
                    .unwrap_or_else(|| format!("Thread #{}", tid))
            })
            .collect();
        titles.into_iter().collect()
    };

    let mut narrative_summary: HashMap<String, Vec<String>> = HashMap::new();
    narrative_summary.insert("read".to_string(), Vec::new());
    narrative_summary.insert("skipped".to_string(), Vec::new());
    narrative_summary.insert("snoozed".to_string(), snoozed_titles);
    narrative_summary.insert("completed".to_string(), Vec::new());

    // Format events
    let mut formatted_events = Vec::with_capacity(event_rows.len());
    for row in &event_rows {
        let id: i32 = row.try_get(0).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let type_: String = row.try_get(1).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let timestamp: String = row.try_get(2).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let thread_id: Option<i32> = row.try_get(3).ok();
        let selected_thread_id: Option<i32> = row.try_get(4).ok();
        let issue_number: Option<String> = row.try_get(5).ok();
        let context_text: Option<String> = row.try_get(6).ok();
        let die: Option<i32> = row.try_get(7).ok();
        let result: Option<i32> = row.try_get(8).ok();
        let selection_method: Option<String> = row.try_get(9).ok();
        let rating: Option<f64> = row.try_get(10).ok();
        let issues_read: Option<i32> = row.try_get(11).ok();
        let queue_move: Option<String> = row.try_get(12).ok();
        let die_after: Option<i32> = row.try_get(13).ok();

        let event_thread_id = if type_ == "roll" {
            selected_thread_id
        } else {
            thread_id.or(selected_thread_id)
        };

        let live_title = event_thread_id.and_then(|tid| thread_titles.get(&tid));
        let thread_title = live_title
            .or_else(|| event_thread_id.and_then(|tid| snapshot_titles.get(&tid)))
            .map(|title| title.as_str());
        let thread_deleted = event_thread_id.is_some() && live_title.is_none();

        let context: Value = context_text
            .as_deref()
            .and_then(|text| serde_json::from_str(text).ok())
            .unwrap_or(Value::Null);

        let description = match type_.as_str() {
            "roll" => Some(format!(
                "Selected {}",
                thread_title
                    .map(deleted_title)
                    .unwrap_or_else(|| "a thread".to_string())
            )),
            "rate" => {
                let mut parts = vec!["Rated".to_string()];
                if let Some(tt) = thread_title {
                    parts.push(if thread_deleted {
                        deleted_title(tt)
                    } else {
                        tt.to_string()
                    });
                } else if thread_deleted {
                    parts.push("deleted thread".to_string());
                }
                if let Some(ir) = issues_read {
                    let noun = if ir == 1 { "issue" } else { "issues" };
                    parts.push(format!("{} {} read", ir, noun));
                }
                if let Some(r) = rating {
                    parts.push(format!("{:.1}/5", r));
                }
                Some(parts.join(" · "))
            }
            "snooze" => Some(format!(
                "Snoozed {}",
                thread_title
                    .map(deleted_title)
                    .unwrap_or("thread".to_string())
            )),
            "unsnooze" => Some(format!(
                "Unsnoozed {}",
                thread_title
                    .map(deleted_title)
                    .unwrap_or("thread".to_string())
            )),
            "dismiss" => {
                let word = event_word("dismiss");
                Some(format!(
                    "{} {}",
                    word,
                    thread_title
                        .map(deleted_title)
                        .unwrap_or("thread".to_string())
                ))
            }
            "skip" | "rolled_but_skipped" => {
                let word = event_word(&type_);
                Some(format!(
                    "{} {}",
                    word,
                    thread_title
                        .map(deleted_title)
                        .unwrap_or("thread".to_string())
                ))
            }
            "move" => Some(format!(
                "Moved {}",
                thread_title
                    .map(deleted_title)
                    .unwrap_or("thread".to_string())
            )),
            "shuffle" => Some(format!(
                "Shuffled {}",
                thread_title
                    .map(deleted_title)
                    .unwrap_or("thread".to_string())
            )),
            "session_mode" => Some(session_mode_description(&context)),
            "reorder" | "undo" | "restore" => {
                let word = event_word(&type_);
                let mut desc_parts = vec![format!(
                    "{} {}",
                    word,
                    thread_title
                        .map(deleted_title)
                        .unwrap_or("thread".to_string())
                )];
                if let Some(r) = rating {
                    desc_parts.push(format!("rating {:.1}", r));
                }
                if let Some(inum) = issue_number.as_ref() {
                    desc_parts.push(format!("#{}", inum));
                }
                Some(desc_parts.join(" · "))
            }
            _ => Some(event_word(&type_)),
        };

        // Add to narrative summary
        if type_ == "rate" && rating.is_some_and(|r| r >= 3.0) {
            if let Some(tt) = thread_title {
                narrative_summary
                    .entry("read".to_string())
                    .or_default()
                    .push(tt.to_string());
            }
        } else if matches!(type_.as_str(), "skip" | "rolled_but_skipped") {
            if let Some(tt) = thread_title {
                narrative_summary
                    .entry("skipped".to_string())
                    .or_default()
                    .push(tt.to_string());
            }
        } else if matches!(type_.as_str(), "complete" | "completion") {
            if let Some(tt) = thread_title {
                narrative_summary
                    .entry("completed".to_string())
                    .or_default()
                    .push(tt.to_string());
            }
        }

        formatted_events.push(SessionEventDetail {
            id,
            type_,
            timestamp,
            thread_title: thread_title.map(str::to_owned),
            thread_deleted,
            issue_number,
            description,
            die,
            result,
            selection_method,
            rating,
            issues_read,
            queue_move,
            die_after,
        });
    }

    Ok(Json(SessionDetailsResponse {
        session_id,
        started_at,
        ended_at,
        start_die,
        ladder_path: ladder,
        narrative_summary,
        current_die: resolved_die,
        timezone,
        events: formatted_events,
    }))
}

/// Documentation-only operation for the unversioned details.
#[utoipa::path(
    get,
    path = "/api/sessions/{session_id}/details",
    tag = "sessions",
    params(("session_id" = i32, Path, description = "Owned reading session")),
    responses(
        (status = 200, description = "Session details with events", body = SessionDetailsResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_session_details_documentation() {}

/// Documentation-only operation for the versioned details.
#[utoipa::path(
    get,
    path = "/api/v1/sessions/{session_id}/details",
    tag = "sessions",
    params(("session_id" = i32, Path, description = "Owned reading session")),
    responses(
        (status = 200, description = "Session details with events", body = SessionDetailsResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_session_details_v1_documentation() {}

/// OpenAPI document for the session details same-path surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(
        get_session_details_documentation,
        get_session_details_v1_documentation
    ),
    components(schemas(
        SessionEventDetail,
        SessionDetailsResponse
    )),
    modifiers(&SessionDetailsSecurityAddon)
)]
pub struct SessionDetailsApi;

struct SessionDetailsSecurityAddon;

impl utoipa::Modify for SessionDetailsSecurityAddon {
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
    fn session_details_openapi_covers_both_same_paths() {
        let document = serde_json::to_value(SessionDetailsApi::openapi()).expect("openapi");
        let paths = document["paths"].as_object().expect("paths");
        assert!(paths.contains_key("/api/sessions/{session_id}/details"));
        assert!(paths.contains_key("/api/v1/sessions/{session_id}/details"));
        for path in [
            "/api/sessions/{session_id}/details",
            "/api/v1/sessions/{session_id}/details",
        ] {
            let operation = &document["paths"][path]["get"];
            assert!(operation["operationId"].is_string());
            assert!(operation["responses"]["200"].as_object().is_some());
            assert!(operation["responses"]["404"].as_object().is_some());
            assert!(operation["security"].is_array());
        }
        assert!(document["components"]["schemas"]["SessionDetailsResponse"].is_object());
        let event_schema = &document["components"]["schemas"]["SessionEventDetail"];
        let props = event_schema["properties"]
            .as_object()
            .expect("event properties");
        assert!(
            props.contains_key("type"),
            "generated schema must expose the Python/frontend wire key `type`"
        );
        assert!(
            !props.contains_key("type_"),
            "generated schema must not leak the Rust field name `type_`"
        );
    }

    #[test]
    fn session_event_detail_serializes_type_wire_key() {
        let detail = SessionEventDetail {
            id: 7,
            type_: "roll".to_string(),
            timestamp: "2026-11-17T00:00:00.000000Z".to_string(),
            thread_title: None,
            thread_deleted: false,
            issue_number: None,
            description: None,
            die: None,
            result: None,
            selection_method: None,
            rating: None,
            issues_read: None,
            queue_move: None,
            die_after: None,
        };
        let wire = serde_json::to_value(&detail).expect("serialize event detail");
        assert_eq!(wire["type"].as_str(), Some("roll"));
        assert!(wire.get("type_").is_none());
    }

    async fn database_fixture() -> (
        Arc<AppState>,
        AuthenticatedUser,
        tokio::sync::MutexGuard<'static, ()>,
    ) {
        let state = test_support::test_state(2)
            .await
            .expect("RUST_ROLL_TEST_DATABASE_URL is required");
        let guard = test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username) VALUES (9101, 'session-details-test'), (9102, 'session-details-other');
                 INSERT INTO threads (id, user_id, title, format, issues_remaining, total_issues, reading_progress, queue_position, status, is_blocked) VALUES (9201, 9101, 'Owned Comic', 'comics', 3, NULL, NULL, 1, 'active', false), (9202, 9102, 'Foreign Comic', 'Comic', 2, NULL, NULL, 1, 'active', false);
                 INSERT INTO sessions (id, user_id, started_at, ended_at, start_die, manual_die, pending_thread_id, reading_mode_suggested, snoozed_thread_ids) VALUES (9301, 9101, NOW(), NULL, 6, NULL, 9201, false, NULL), (9302, 9102, NOW(), NULL, 6, NULL, 9202, false, NULL), (9303, 9101, NOW(), NULL, 6, NULL, NULL, false, NULL), (9304, 9101, NOW(), NULL, 6, NULL, NULL, false, '[9201]');
                 INSERT INTO events (session_id, type, timestamp, selected_thread_id, thread_id, die, die_after, result) VALUES (9301, 'roll', NOW(), 9201, NULL, 6, NULL, 4), (9301, 'rate', NOW() + interval '1 minute', NULL, 9201, 6, 4, NULL), (9303, 'roll', NOW(), 9201, NULL, 6, NULL, 2), (9304, 'roll', NOW(), 9203, NULL, 6, NULL, 4), (9304, 'snooze', NOW() + interval '1 minute', NULL, 9201, NULL, NULL, NULL);
                  INSERT INTO snapshots (session_id, thread_states, session_state, created_at, description) VALUES (9304, '{\"9203\": {\"title\": \"Lost Comic\"}, \"_meta\": 1}'::json, '{}'::json, NOW(), 'Session start');",
            )
            .await
            .expect("seed session details fixture");
        drop(connection);
        (state, AuthenticatedUser::for_test(9101), guard)
    }

    #[tokio::test]
    async fn get_session_details_returns_owned_projection_to_disposable_postgres() {
        let (state, user, _guard) = database_fixture().await;
        let Json(response) = get_session_details(Path(9301), user, State(state.clone()))
            .await
            .expect("session details");
        assert_eq!(response.session_id, 9301);
        assert_eq!(response.start_die, 6);
        assert_eq!(response.current_die, 4);
        assert_eq!(response.ladder_path, "6 → 4");
        assert!(!response.events.is_empty());
        let wire = serde_json::to_value(&response).expect("serialize details response");
        for event in wire["events"].as_array().expect("events") {
            assert!(
                event["type"].as_str().is_some(),
                "each event must serialize the `type` wire key"
            );
            assert!(event.get("type_").is_none());
        }
        // Check event formatting
        let roll_event = response
            .events
            .iter()
            .find(|e| e.type_ == "roll")
            .expect("roll event");
        assert_eq!(roll_event.die, Some(6));
        assert_eq!(roll_event.result, Some(4));
        assert!(roll_event
            .description
            .as_ref()
            .unwrap()
            .contains("Owned Comic"));
    }

    #[tokio::test]
    async fn get_session_details_rejects_missing_and_foreign() {
        let (state, user, _guard) = database_fixture().await;
        let missing = get_session_details(Path(9999), user, State(state.clone()))
            .await
            .expect_err("missing must 404");
        assert_eq!(missing.status(), StatusCode::NOT_FOUND);
        assert_eq!(missing.detail(), "Session not found");

        let foreign = get_session_details(Path(9302), user, State(state.clone()))
            .await
            .expect_err("foreign must 404");
        assert_eq!(foreign.status(), StatusCode::NOT_FOUND);
        assert_eq!(foreign.detail(), "Session not found");
    }

    #[tokio::test]
    async fn session_details_narrative_summary_includes_snoozed_key() {
        let (state, user, _guard) = database_fixture().await;
        let Json(response) = get_session_details(Path(9304), user, State(state.clone()))
            .await
            .expect("session details");
        let wire = serde_json::to_value(&response).expect("serialize details response");
        let summary = wire["narrative_summary"]
            .as_object()
            .expect("narrative summary");
        for key in ["read", "skipped", "snoozed", "completed"] {
            assert!(
                summary.contains_key(key),
                "narrative_summary must expose `{}` like the Python service",
                key
            );
            assert!(summary[key].is_array(), "`{}` must be a list", key);
        }
        let snoozed = summary["snoozed"].as_array().expect("snoozed list");
        assert_eq!(snoozed.len(), 1);
        assert_eq!(snoozed[0].as_str(), Some("Owned Comic"));
    }

    #[tokio::test]
    async fn session_details_recovers_deleted_thread_title_from_snapshot() {
        let (state, user, _guard) = database_fixture().await;
        let Json(response) = get_session_details(Path(9304), user, State(state.clone()))
            .await
            .expect("session details");
        let roll = response
            .events
            .iter()
            .find(|event| event.type_ == "roll")
            .expect("roll event");
        assert_eq!(roll.thread_title.as_deref(), Some("Lost Comic"));
        assert!(roll.thread_deleted, "thread is missing from live threads");
        assert_eq!(
            roll.description.as_deref(),
            Some("Selected Lost Comic (deleted)")
        );
    }
}
