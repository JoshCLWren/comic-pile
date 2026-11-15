//! Native same-path session details read (#4839, parent #4335).
//!
//! Migrates the session-details read from `app/api/session.py` to the native
//! Rust router with identical method/path and wire contract:
//!
//! * `GET /api/sessions/{session_id}/details`
//! * `GET /api/v1/sessions/{session_id}/details`
//!
//! Wire parity with Python `get_session_details` ('app/api/session.py'):
//!
//! * Ownership: `get_owned_session_or_404` — a foreign or missing session
//!   returns 404 with the exact detail `"Session not found"`.
//! * `ladder_path`: `build_ladder_path` — `start_die` followed by every
//!   truthy `die_after` from `rate`/`snooze`/`undo` events in timestamp/id
//!   order, joined with `" → "` (a stored `0` die is skipped, matching
//!   Python's `if event.die_after:` truthiness test).
//! * `current_die`: `comic_pile.reading_session.get_current_die` — the latest
//!   die-changing event (`rate`/`snooze`/`undo`/`reset_dice`/`manual_die`
//!   with `die_after IS NOT NULL`) resolved through
//!   [`crate::reading_session::automatic_die_after`] wins; otherwise the
//!   legacy non-zero `manual_die`; otherwise `start_die`. The wider event set
//!   matches the Python oracle exactly (the earlier single-session slice's
//!   narrower `('rate','snooze','undo')` read is a known divergence from that
//!   oracle and is tracked separately).
//! * `narrative_summary`: `app.services.summary_service.build_narrative_summary`
//!   — `read` entries for every not-undone `rate` event, `skipped` for
//!   `rolled_but_skipped`/`dismiss`, `completed` for rated threads whose status
//!   is `completed`, and `snoozed` as the still-snoozed set at the session
//!   boundary (the persisted `snoozed_thread_ids` column when present, else the
//!   session-start snapshot's recorded set replayed over the session's own
//!   snooze/unsnooze events). Titles fall back to `Thread #{id}` for deleted
//!   references.
//! * `events`: `build_session_event_details` — every session event newest
//!   first, with its referenced thread's title (or `(deleted)` marker plus the
//!   last snapshot title), the denormalized issue number, and the per-type
//!   reader-language description strings.
//! * Defaults Python leaves unset on this endpoint stay unset: `die`,
//!   `result`, `selection_method`, `rating`, `issues_read`, `queue_move`,
//!   `die_after` are `null` except on the event types that carry them.
//! * Timestamps are emitted as UTC `...Z` strings, matching the earlier
//!   session-snapshots Rust slice (PR #4888); the frontend parses both the
//!   Python `+00:00` and Rust `Z` forms as dates.
//!
//! Bounded reads only: one owned session row, one event read, one batched
//! thread read, one snapshot-title read (only when a referenced thread is
//! missing), one session-start snapshot read (only when the snooze column is
//! NULL), one ladder read and one die-event read. No per-row fan-out. Python
//! handlers remain; deployed ingress in `vercel.json` shadows them after this
//! cutover.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser, db, reading_session::automatic_die_after, ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeSet, HashMap};
use std::sync::Arc;

/// One formatted timeline event (Python `EventDetail`).
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SessionEventDetail {
    pub id: i32,
    #[serde(rename = "type")]
    pub event_type: String,
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

/// Narrative summary buckets (Python `dict[str, list[str]]`).
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SessionNarrativeSummary {
    pub read: Vec<String>,
    pub skipped: Vec<String>,
    pub snoozed: Vec<String>,
    pub completed: Vec<String>,
}

/// Wire shape of Python `SessionDetailsResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SessionDetailsResponse {
    pub session_id: i32,
    pub started_at: String,
    pub ended_at: Option<String>,
    pub start_die: i32,
    pub ladder_path: String,
    pub narrative_summary: SessionNarrativeSummary,
    pub current_die: i32,
    pub timezone: Option<String>,
    pub events: Vec<SessionEventDetail>,
}

const SESSION_SQL: &str = "SELECT to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, manual_die, snoozed_thread_ids::text, timezone FROM sessions WHERE id = $1 AND user_id = $2";
const EVENTS_SQL: &str = "SELECT id, type, to_char(timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), thread_id, selected_thread_id, issue_number, die, result, selection_method, rating, issues_read, queue_move, die_after, context::text FROM events WHERE session_id = $1 ORDER BY timestamp DESC, id DESC";
const THREADS_SQL: &str =
    "SELECT id, title, user_id, status FROM threads WHERE id = ANY($1::int[])";
const SNAPSHOT_TITLES_SQL: &str = "SELECT thread_states::text FROM snapshots WHERE session_id = $1 ORDER BY created_at DESC, id DESC";
const FIRST_START_SNAPSHOT_SQL: &str = "SELECT session_state::text FROM snapshots WHERE session_id = $1 AND description = 'Session start' ORDER BY created_at ASC LIMIT 1";
const LADDER_SQL: &str = "SELECT die_after FROM events WHERE session_id = $1 AND type IN ('rate','snooze','undo') AND die_after IS NOT NULL ORDER BY timestamp ASC, id ASC";
const CURRENT_DIE_SQL: &str = "SELECT die_after, context::text FROM events WHERE (user_id = $2 OR session_id = $1) AND type IN ('rate','snooze','undo','reset_dice','manual_die') AND die_after IS NOT NULL ORDER BY timestamp DESC, id DESC LIMIT 1";

fn not_found() -> ApiError {
    ApiError::with_status(StatusCode::NOT_FOUND, "Session not found".to_string())
}

/// Lenient JSON parse for a JSON column value.
///
/// Malformed JSON is logged with the column context and falls back to
/// [`Value::Null`] — matching the Python oracle's tolerance for absent
/// context payloads — but the corruption stays visible in the logs instead
/// of being silently swallowed.
fn lenient_json(text: Option<&str>, column: &'static str) -> Value {
    match text {
        Some(text) => serde_json::from_str(text).unwrap_or_else(|error| {
            tracing::warn!(
                error_kind = crate::error_kind(&error),
                column,
                "malformed JSON column treated as absent; see logs"
            );
            Value::Null
        }),
        None => Value::Null,
    }
}

fn internal() -> ApiError {
    ApiError::with_status(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Internal Server Error".to_string(),
    )
}

fn query_error(error: tokio_postgres::Error) -> ApiError {
    tracing::debug!(
        error_kind = crate::error_kind(&error),
        "preserved underlying error before mapping"
    );
    db::query_error(error)
}

/// Python `_event_word` / `EVENT_TYPE_DESCRIPTIONS`.
fn event_word(event_type: &str) -> String {
    match event_type {
        "skip" | "rolled_but_skipped" => return "Skipped".to_string(),
        "complete" | "completion" => return "Completed".to_string(),
        "reorder" => return "Reordered".to_string(),
        "undo" | "restore" => return "Restored".to_string(),
        "move" => return "Moved".to_string(),
        "shuffle" => return "Shuffled".to_string(),
        "roll" => return "Rolled".to_string(),
        "rate" => return "Rated".to_string(),
        // Python's timeline branch hardcodes `Snoozed` for `snooze`
        // (`EVENT_TYPE_DESCRIPTIONS` has no `snooze` key because that branch
        // never calls `_event_word`), while `unsnooze` is dict-mapped.
        "snooze" => return "Snoozed".to_string(),
        "unsnooze" => return "Unsnoozed".to_string(),
        "dismiss" => return "Dismissed".to_string(),
        _ => {}
    }
    // Python `event_type.replace("_", " ").capitalize()`: the first character
    // is upper-cased and every remaining character is lower-cased.
    let replaced = event_type.replace('_', " ");
    let mut characters = replaced.chars();
    match characters.next() {
        Some(first) => {
            let mut word = first.to_uppercase().to_string();
            word.extend(characters.flat_map(char::to_lowercase));
            word
        }
        None => String::new(),
    }
}

/// Python `_deleted_title`.
fn deleted_title(title: Option<&str>) -> String {
    match title {
        Some(title) if !title.is_empty() => format!("{title} (deleted)"),
        _ => "deleted thread".to_string(),
    }
}

/// Python f-string rendering of a float: integral values keep one decimal.
fn python_float(value: f64) -> String {
    if value.fract() == 0.0 && value.abs() < 1e16 {
        format!("{value:.1}")
    } else {
        format!("{value}")
    }
}

/// Python f-string `{value:.1f}`.
fn python_float_one(value: f64) -> String {
    format!("{value:.1}")
}

/// Python `_context_text`: a trimmed non-empty string from a JSON context.
fn context_text(context: &Value, key: &str) -> Option<String> {
    let value = context.get(key)?;
    if !value.is_string() {
        return None;
    }
    let text = value.as_str().unwrap_or_default().trim();
    if text.is_empty() {
        return None;
    }
    Some(text.to_string())
}

/// Python `_mode_label`.
fn mode_label(value: &str) -> String {
    let label = value.replace('_', " ");
    let trimmed = label.trim();
    if trimmed.is_empty() {
        return value.to_string();
    }
    let mut characters = trimmed.chars();
    match characters.next() {
        Some(first) => first.to_uppercase().collect::<String>() + characters.as_str(),
        None => value.to_string(),
    }
}

/// Python `_session_mode_description`.
fn session_mode_description(context: &Value) -> String {
    let changed: BTreeSet<String> = match context.get("changed") {
        Some(Value::Array(values)) => values
            .iter()
            .filter_map(Value::as_str)
            .map(str::to_string)
            .collect(),
        _ => BTreeSet::new(),
    };
    let mut parts: Vec<String> = Vec::new();
    if changed.contains("bandwidth") {
        if let Some(bandwidth) = context_text(context, "bandwidth") {
            parts.push(format!("Bandwidth set to {}", mode_label(&bandwidth)));
        }
    }
    if changed.contains("intent") {
        if let Some(intent) = context_text(context, "intent") {
            parts.push(format!("Intent set to {}", mode_label(&intent)));
        }
    }
    if parts.is_empty() {
        "Session mode changed".to_string()
    } else {
        parts.join(" · ")
    }
}

/// One raw event row in display order.
#[derive(Debug, Clone)]
struct EventRow {
    id: i32,
    event_type: String,
    timestamp: String,
    thread_id: Option<i32>,
    selected_thread_id: Option<i32>,
    issue_number: Option<String>,
    die: Option<i32>,
    result: Option<i32>,
    selection_method: Option<String>,
    rating: Option<f64>,
    issues_read: Option<i32>,
    queue_move: Option<String>,
    die_after: Option<i32>,
    context: Value,
}

impl EventRow {
    /// Python `session_response._event_thread_id`: rolls and dismissals name
    /// their thread through `selected_thread_id`; every other type prefers
    /// `thread_id` and falls back to `selected_thread_id`.
    fn timeline_thread_id(&self) -> Option<i32> {
        if self.event_type == "roll" {
            return self.selected_thread_id;
        }
        if self.thread_id.is_some() {
            return self.thread_id;
        }
        self.selected_thread_id
    }

    /// Python `summary_service._event_thread_id`: a dismissal names its
    /// cancelled roll through `selected_thread_id`; everything else uses
    /// `thread_id` only.
    fn summary_thread_id(&self) -> Option<i32> {
        if self.event_type == "dismiss" {
            return self.selected_thread_id;
        }
        self.thread_id
    }
}

/// One thread projection needed by the timeline and narrative builders.
#[derive(Debug, Clone)]
struct ThreadRow {
    title: String,
    user_id: i32,
    status: String,
}

/// `GET /api/sessions/{session_id}/details` and `GET /api/v1/...` twin.
pub async fn get_session_details(
    Path(session_id): Path<i32>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<SessionDetailsResponse>, ApiError> {
    let connection = db::checkout(&state).await?;

    let session_row = connection
        .query_opt(SESSION_SQL, &[&session_id, &user.id()])
        .await
        .map_err(query_error)?
        .ok_or_else(not_found)?;
    let started_at: String = session_row.try_get(0).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let ended_at: Option<String> = session_row.try_get(1).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let start_die: i32 = session_row.try_get(2).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let manual_die: Option<i32> = session_row.try_get(3).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let snoozed_thread_ids_text: Option<String> = session_row.try_get(4).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
    let timezone: Option<String> = session_row.try_get(5).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;

    let event_rows = connection
        .query(EVENTS_SQL, &[&session_id])
        .await
        .map_err(query_error)?;
    let mut events: Vec<EventRow> = Vec::with_capacity(event_rows.len());
    for row in &event_rows {
        // Column order of EVENTS_SQL: id(0), type(1), timestamp(2),
        // thread_id(3), selected_thread_id(4), issue_number(5), die(6),
        // result(7), selection_method(8), rating(9), issues_read(10),
        // queue_move(11), die_after(12), context(13).
        let context_text: Option<String> = row.try_get(13).map_err(projection_error)?;
        events.push(EventRow {
            id: row.try_get(0).map_err(projection_error)?,
            event_type: row.try_get(1).map_err(projection_error)?,
            timestamp: row.try_get(2).map_err(projection_error)?,
            thread_id: row.try_get(3).map_err(projection_error)?,
            selected_thread_id: row.try_get(4).map_err(projection_error)?,
            issue_number: row.try_get(5).map_err(projection_error)?,
            die: row.try_get(6).map_err(projection_error)?,
            result: row.try_get(7).map_err(projection_error)?,
            selection_method: row.try_get(8).map_err(projection_error)?,
            rating: row.try_get(9).map_err(projection_error)?,
            issues_read: row.try_get(10).map_err(projection_error)?,
            queue_move: row.try_get(11).map_err(projection_error)?,
            die_after: row.try_get(12).map_err(projection_error)?,
            context: lenient_json(context_text.as_deref(), "events.context"),
        });
    }

    // Batched thread read for every thread the timeline or summary names.
    let mut thread_ids: BTreeSet<i32> = BTreeSet::new();
    for event in &events {
        if let Some(thread_id) = event.timeline_thread_id() {
            thread_ids.insert(thread_id);
        }
        if let Some(thread_id) = event.summary_thread_id() {
            thread_ids.insert(thread_id);
        }
    }
    let recorded_snoozed: Option<Vec<i32>> = match snoozed_thread_ids_text.as_deref() {
        Some(text) if !text.is_empty() && text != "null" => {
            match serde_json::from_str::<Value>(text) {
                Ok(Value::Array(values)) => Some(
                    values
                        .iter()
                        .filter_map(Value::as_i64)
                        .map(|value| value as i32)
                        .collect(),
                ),
                Ok(_) => {
                    tracing::warn!(
                        column = "sessions.snoozed_thread_ids",
                        "non-array snoozed_thread_ids column; falling back to event projection"
                    );
                    None
                }
                Err(error) => {
                    tracing::warn!(
                        error_kind = crate::error_kind(&error),
                        column = "sessions.snoozed_thread_ids",
                        "malformed snoozed_thread_ids column; falling back to event projection"
                    );
                    None
                }
            }
        }
        _ => None,
    };
    let still_snoozed_ids: Vec<i32> = match &recorded_snoozed {
        Some(ids) => {
            let mut ids = ids.clone();
            ids.sort_unstable();
            ids
        }
        None => project_still_snoozed_thread_ids(
            &events,
            &snapshot_recovered_snoozes(&connection, session_id).await?,
        ),
    };
    for thread_id in &still_snoozed_ids {
        thread_ids.insert(*thread_id);
    }

    let mut threads: HashMap<i32, ThreadRow> = HashMap::new();
    if !thread_ids.is_empty() {
        let ids: Vec<i32> = thread_ids.iter().copied().collect();
        let thread_rows = connection
            .query(THREADS_SQL, &[&ids])
            .await
            .map_err(query_error)?;
        for row in &thread_rows {
            let id: i32 = row.try_get(0).map_err(projection_error)?;
            let title: String = row.try_get(1).map_err(projection_error)?;
            let thread_user_id: i32 = row.try_get(2).map_err(projection_error)?;
            let status: String = row.try_get(3).map_err(projection_error)?;
            threads.insert(
                id,
                ThreadRow {
                    title,
                    user_id: thread_user_id,
                    status,
                },
            );
        }
    }

    // Snapshot-recovered titles for threads deleted after the events fired.
    let mut snapshot_titles: HashMap<i32, String> = HashMap::new();
    let missing_timeline_ids: BTreeSet<i32> = thread_ids
        .iter()
        .copied()
        .filter(|thread_id| !threads.contains_key(thread_id))
        .collect();
    if !missing_timeline_ids.is_empty() {
        snapshot_titles = snapshot_thread_titles(&connection, session_id).await?;
    }

    let narrative_summary =
        build_narrative_summary(&events, &threads, user.id(), &still_snoozed_ids);

    let ladder_values: Vec<i32> = {
        let rows = connection
            .query(LADDER_SQL, &[&session_id])
            .await
            .map_err(query_error)?;
        rows.iter()
            .map(|row| {
                row.try_get::<_, i32>(0).map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    internal()
                })
            })
            .collect::<Result<_, _>>()?
    };
    let mut ladder_parts: Vec<String> = vec![start_die.to_string()];
    ladder_parts.extend(
        ladder_values
            .iter()
            .filter(|die_after| **die_after != 0)
            .map(|die_after| die_after.to_string()),
    );
    let ladder = ladder_parts.join(" → ");

    let current_die = {
        // Python `get_current_die` scopes die history to
        // `or_(Event.user_id == session.user_id, Event.session_id == session.id)`:
        // Rust commands write sessionless `manual_die`/`snooze` events, so a
        // session-only lookup would miss the reader's latest die.
        let die_row = connection
            .query_opt(CURRENT_DIE_SQL, &[&session_id, &user.id()])
            .await
            .map_err(query_error)?;
        match die_row {
            Some(row) => {
                let die_after: i32 = row.try_get(0).map_err(projection_error)?;
                let context_text: Option<String> = row.try_get(1).map_err(projection_error)?;
                let context: Value = lenient_json(context_text.as_deref(), "current_die.context");
                automatic_die_after(die_after, &context)
            }
            None => manual_die.filter(|value| *value != 0).unwrap_or(start_die),
        }
    };

    let timeline = build_session_event_details(&events, &threads, &snapshot_titles);

    Ok(Json(SessionDetailsResponse {
        session_id,
        started_at,
        ended_at,
        start_die,
        ladder_path: ladder,
        narrative_summary,
        current_die,
        timezone,
        events: timeline,
    }))
}

/// Row-projection failures share one mapped outcome.
///
/// Takes the underlying driver error so every `try_get` can be mapped through
/// `map_err(projection_error)` while still recording the cause first.
fn projection_error(error: tokio_postgres::Error) -> ApiError {
    tracing::debug!(
        error_kind = crate::error_kind(&error),
        "preserved underlying error before mapping"
    );
    internal()
}

/// Python `project_still_snoozed_thread_ids`.
///
/// The input arrives in timeline display order (newest first); Python replays
/// `(timestamp, id)` ascending, so iterate reversed to keep snooze/unsnooze
/// pairing order identical.
fn project_still_snoozed_thread_ids(events: &[EventRow], start_thread_ids: &[i32]) -> Vec<i32> {
    let mut still_snoozed: BTreeSet<i32> = start_thread_ids.iter().copied().collect();
    for event in events.iter().rev() {
        if event.event_type != "snooze" && event.event_type != "unsnooze" {
            continue;
        }
        let Some(thread_id) = event.thread_id else {
            continue;
        };
        if event.event_type == "snooze" {
            still_snoozed.insert(thread_id);
        } else {
            still_snoozed.remove(&thread_id);
        }
    }
    still_snoozed.into_iter().collect()
}

/// Python `_recorded_start_snoozes`: the session-start snapshot's snooze set.
async fn snapshot_recovered_snoozes(
    connection: &deadpool_postgres::Object,
    session_id: i32,
) -> Result<Vec<i32>, ApiError> {
    let row = connection
        .query_opt(FIRST_START_SNAPSHOT_SQL, &[&session_id])
        .await
        .map_err(query_error)?;
    // Python `_recorded_start_snoozes(None)` returns the empty set when the
    // session has no `Session start` snapshot; that is not an error.
    let Some(row) = row else {
        return Ok(Vec::new());
    };
    let state_text: Option<String> = row.try_get(0).map_err(projection_error)?;
    let state: Value = lenient_json(state_text.as_deref(), "snapshots.session_state");
    let ids = match state.get("snoozed_thread_ids") {
        Some(Value::Array(values)) => values
            .iter()
            .filter_map(Value::as_i64)
            .map(|value| value as i32)
            .collect(),
        _ => Vec::new(),
    };
    Ok(ids)
}

/// Python `reading_session_repository.snapshot_thread_titles`.
async fn snapshot_thread_titles(
    connection: &deadpool_postgres::Object,
    session_id: i32,
) -> Result<HashMap<i32, String>, ApiError> {
    let rows = connection
        .query(SNAPSHOT_TITLES_SQL, &[&session_id])
        .await
        .map_err(query_error)?;
    let mut titles: HashMap<i32, String> = HashMap::new();
    for row in &rows {
        let states_text: String = row.try_get(0).map_err(projection_error)?;
        let states: Value = match serde_json::from_str(&states_text) {
            Ok(states) => states,
            Err(error) => {
                tracing::warn!(
                    error_kind = crate::error_kind(&error),
                    column = "snapshots.thread_states",
                    "malformed thread_states JSON in snapshot; skipping snapshot row"
                );
                continue;
            }
        };
        let Value::Object(map) = states else {
            continue;
        };
        for (key, value) in map {
            if key.starts_with('_') {
                continue;
            }
            let Ok(thread_id) = key.parse::<i32>() else {
                continue;
            };
            if titles.contains_key(&thread_id) {
                continue;
            }
            if let Some(title) = value.get("title").and_then(Value::as_str) {
                if !title.trim().is_empty() {
                    titles.insert(thread_id, title.to_string());
                }
            }
        }
    }
    Ok(titles)
}

/// Python `summary_service.build_narrative_summary`.
///
/// The input arrives in timeline display order (newest first); Python reads
/// the event stream `(timestamp, id)` ascending for both the undo netting and
/// the chronological `read` list, so iterate reversed.
fn build_narrative_summary(
    events: &[EventRow],
    threads: &HashMap<i32, ThreadRow>,
    session_user_id: i32,
    still_snoozed_ids: &[i32],
) -> SessionNarrativeSummary {
    // Net undo events against rate events: each undo reverts the most recent
    // not-yet-undone rate before it.
    let mut undone_rate_ids: BTreeSet<i32> = BTreeSet::new();
    let mut open_rate_ids: Vec<i32> = Vec::new();
    for event in events.iter().rev() {
        if event.event_type == "rate" {
            open_rate_ids.push(event.id);
        } else if event.event_type == "undo" {
            if let Some(undone) = open_rate_ids.pop() {
                undone_rate_ids.insert(undone);
            }
        }
    }

    // The persisted snooze column is the authoritative boundary state whenever
    // it exists; otherwise the projection above already rebuilt it. Scope the
    // set to the reader who owns the session: a malformed event naming another
    // reader's series must not leak that title.
    let snoozed_ids: Vec<i32> = still_snoozed_ids
        .iter()
        .copied()
        .filter(|thread_id| {
            !threads.contains_key(thread_id) || threads[thread_id].user_id == session_user_id
        })
        .collect();

    let mut snoozed_titles: BTreeSet<String> = BTreeSet::new();
    for thread_id in &snoozed_ids {
        match threads.get(thread_id) {
            Some(thread) => {
                snoozed_titles.insert(thread.title.clone());
            }
            None => {
                snoozed_titles.insert(format!("Thread #{thread_id}"));
            }
        }
    }

    let mut read_entries: Vec<String> = Vec::new();
    let mut skipped_titles: BTreeSet<String> = BTreeSet::new();
    let mut completed_titles: BTreeSet<String> = BTreeSet::new();

    for event in events.iter().rev() {
        let thread_id = event.summary_thread_id();
        let thread = thread_id.and_then(|thread_id| threads.get(&thread_id));
        let title = match (thread, thread_id) {
            (Some(thread), _) => thread.title.clone(),
            (None, Some(thread_id)) => format!("Thread #{thread_id}"),
            // Python f-string over a `None` thread id renders `Thread #None`.
            (None, None) => "Thread #None".to_string(),
        };
        let issue_suffix = match &event.issue_number {
            Some(issue_number) if !issue_number.is_empty() => format!(" #{issue_number}"),
            _ => String::new(),
        };

        if event.event_type == "rate" && !undone_rate_ids.contains(&event.id) {
            let rating = match event.rating {
                Some(rating) => python_float(rating),
                None => "None".to_string(),
            };
            read_entries.push(format!("{title}{issue_suffix} ({rating}/5.0)"));
            if let Some(thread) = thread {
                if thread.status == "completed" {
                    completed_titles.insert(format!("{title}{issue_suffix}"));
                }
            }
        } else if event.event_type == "rolled_but_skipped" || event.event_type == "dismiss" {
            skipped_titles.insert(format!("{title}{issue_suffix}"));
        }
    }

    SessionNarrativeSummary {
        read: read_entries,
        skipped: skipped_titles.into_iter().collect(),
        snoozed: snoozed_titles.into_iter().collect(),
        completed: completed_titles.into_iter().collect(),
    }
}

/// Python `session_response.build_session_event_details`.
fn build_session_event_details(
    events: &[EventRow],
    threads: &HashMap<i32, ThreadRow>,
    snapshot_titles: &HashMap<i32, String>,
) -> Vec<SessionEventDetail> {
    let mut formatted: Vec<SessionEventDetail> = Vec::with_capacity(events.len());
    for event in events {
        let thread_id = event.timeline_thread_id();
        let mut thread_title: Option<String> = None;
        let mut thread_deleted = false;
        if let Some(thread_id) = thread_id {
            match threads.get(&thread_id) {
                Some(thread) => thread_title = Some(thread.title.clone()),
                None => {
                    thread_deleted = true;
                    thread_title = snapshot_titles.get(&thread_id).cloned();
                }
            }
        }

        let mut detail = SessionEventDetail {
            id: event.id,
            event_type: event.event_type.clone(),
            timestamp: event.timestamp.clone(),
            thread_title,
            thread_deleted,
            issue_number: event.issue_number.clone(),
            description: None,
            die: None,
            result: None,
            selection_method: None,
            rating: None,
            issues_read: None,
            queue_move: None,
            die_after: None,
        };

        match event.event_type.as_str() {
            "roll" => {
                detail.die = event.die;
                detail.result = event.result;
                detail.selection_method = event.selection_method.clone();
                detail.description = Some(if thread_deleted {
                    format!("Selected {}", deleted_title(detail.thread_title.as_deref()))
                } else if !detail
                    .thread_title
                    .as_deref()
                    .unwrap_or_default()
                    .is_empty()
                {
                    format!(
                        "Selected {}",
                        detail.thread_title.as_deref().unwrap_or_default()
                    )
                } else {
                    "Selected a thread".to_string()
                });
            }
            "rate" => {
                detail.die = event.die;
                detail.rating = event.rating;
                detail.issues_read = event.issues_read;
                detail.queue_move = event.queue_move.clone();
                detail.die_after = event.die_after;
                let mut parts: Vec<String> = vec!["Rated".to_string()];
                if !detail
                    .thread_title
                    .as_deref()
                    .unwrap_or_default()
                    .is_empty()
                {
                    let title = if thread_deleted {
                        deleted_title(detail.thread_title.as_deref())
                    } else {
                        detail.thread_title.clone().unwrap_or_default()
                    };
                    parts.push(title);
                } else if thread_deleted {
                    parts.push("deleted thread".to_string());
                }
                if let Some(issues_read) = event.issues_read {
                    if issues_read != 0 {
                        let noun = if issues_read == 1 { "issue" } else { "issues" };
                        parts.push(format!("{issues_read} {noun} read"));
                    }
                }
                if let Some(rating) = event.rating {
                    parts.push(format!("{}/5", python_float_one(rating)));
                }
                detail.description = Some(parts.join(" · "));
            }
            "snooze" | "unsnooze" => {
                detail.die = event.die;
                detail.die_after = event.die_after;
                let word = event_word(&event.event_type);
                let target = if thread_deleted {
                    deleted_title(detail.thread_title.as_deref())
                } else if !detail
                    .thread_title
                    .as_deref()
                    .unwrap_or_default()
                    .is_empty()
                {
                    detail.thread_title.clone().unwrap_or_default()
                } else {
                    "thread".to_string()
                };
                detail.description = Some(format!("{word} {target}"));
            }
            "dismiss" => {
                // Python's dismiss branch sets neither `die` nor `die_after`.
                let word = event_word(&event.event_type);
                let target = if thread_deleted {
                    deleted_title(detail.thread_title.as_deref())
                } else if !detail
                    .thread_title
                    .as_deref()
                    .unwrap_or_default()
                    .is_empty()
                {
                    detail.thread_title.clone().unwrap_or_default()
                } else {
                    "thread".to_string()
                };
                detail.description = Some(format!("{word} {target}"));
            }
            "skip" | "rolled_but_skipped" => {
                detail.die = event.die;
                detail.die_after = event.die_after;
                let word = event_word(&event.event_type);
                let target = if thread_deleted {
                    deleted_title(detail.thread_title.as_deref())
                } else if !detail
                    .thread_title
                    .as_deref()
                    .unwrap_or_default()
                    .is_empty()
                {
                    detail.thread_title.clone().unwrap_or_default()
                } else {
                    "thread".to_string()
                };
                detail.description = Some(format!("{word} {target}"));
            }
            "move" | "shuffle" => {
                detail.die = event.die;
                detail.die_after = event.die_after;
                let word = event_word(&event.event_type);
                let target = if thread_deleted {
                    deleted_title(detail.thread_title.as_deref())
                } else if !detail
                    .thread_title
                    .as_deref()
                    .unwrap_or_default()
                    .is_empty()
                {
                    detail.thread_title.clone().unwrap_or_default()
                } else {
                    "thread".to_string()
                };
                detail.description = Some(format!("{word} {target}"));
            }
            "session_mode" => {
                detail.description = Some(session_mode_description(&event.context));
            }
            "reorder" | "undo" | "restore" => {
                detail.rating = event.rating;
                let word = event_word(&event.event_type);
                let mut parts: Vec<String> = vec![if thread_deleted {
                    format!("{word} {}", deleted_title(detail.thread_title.as_deref()))
                } else if !detail
                    .thread_title
                    .as_deref()
                    .unwrap_or_default()
                    .is_empty()
                {
                    format!(
                        "{word} {}",
                        detail.thread_title.as_deref().unwrap_or_default()
                    )
                } else {
                    format!("{word} thread")
                }];
                if let Some(rating) = event.rating {
                    parts.push(format!("rating {}", python_float_one(rating)));
                }
                if let Some(issue_number) = &event.issue_number {
                    if !issue_number.is_empty() {
                        parts.push(format!("#{issue_number}"));
                    }
                }
                detail.description = Some(parts.join(" · "));
            }
            _ => {}
        }

        formatted.push(detail);
    }
    formatted
}

/// Query parameter bag kept for contract documentation symmetry.
#[derive(Debug, Default, Deserialize)]
pub struct SessionDetailsQuery {
    #[serde(default)]
    pub _unused: Option<String>,
}

/// OpenAPI declaration for both legacy and versioned same-path aliases.
#[utoipa::path(
    get,
    path = "/api/v1/sessions/{session_id}/details",
    tag = "sessions",
    params(("session_id" = i32, Path, description = "Owned reading session")),
    responses(
        (status = 200, description = "Session details with events", body = SessionDetailsResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_session_details_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{db, test_support};

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
                "INSERT INTO users (id, username) VALUES (9101, 'details-owner'), (9102, 'details-other');
                 INSERT INTO threads (id, user_id, title, format, issues_remaining, total_issues, reading_progress, queue_position, status, is_blocked)
                   VALUES (9201, 9101, 'Owned Comic', 'comics', 3, NULL, NULL, 1, 'completed', false),
                          (9202, 9102, 'Foreign Comic', 'Comic', 2, NULL, NULL, 1, 'active', false);
                 INSERT INTO sessions (id, user_id, started_at, ended_at, start_die, manual_die, reading_mode_suggested)
                   VALUES (9301, 9101, '2026-01-01T00:00:00Z', NULL, 6, NULL, false),
                          (9302, 9102, '2026-01-01T00:00:00Z', NULL, 6, NULL, false);
                 INSERT INTO events (session_id, type, timestamp, selected_thread_id, thread_id, die, die_after, result, rating, issues_read, queue_move)
                   VALUES (9301, 'roll', '2026-01-01T00:00:00Z', 9201, NULL, 6, NULL, 3, NULL, NULL, NULL),
                          (9301, 'rate', '2026-01-01T00:01:00Z', NULL, 9201, 6, 4, NULL, 4.5, 1, 'keep');",
            )
            .await
            .expect("seed session details fixture");
        drop(connection);
        (state, AuthenticatedUser::for_test(9101), guard)
    }

    #[tokio::test]
    async fn get_session_details_returns_owned_projection() {
        let (state, user, _guard) = database_fixture().await;
        let Json(response) = get_session_details(Path(9301), user, State(state.clone()))
            .await
            .expect("owned session details");
        assert_eq!(response.session_id, 9301);
        assert_eq!(response.start_die, 6);
        assert_eq!(response.current_die, 4);
        assert_eq!(response.ladder_path, "6 → 4");
        assert_eq!(
            response.narrative_summary.read,
            vec!["Owned Comic (4.5/5.0)"]
        );
        assert_eq!(response.narrative_summary.completed, vec!["Owned Comic"]);
        assert_eq!(response.narrative_summary.skipped.len(), 0);
        assert_eq!(response.events.len(), 2);
        assert_eq!(
            response.events[0].event_type, "rate",
            "events must be newest first"
        );
        assert_eq!(response.events[1].event_type, "roll");
        assert!(
            response.started_at.ends_with('Z'),
            "started_at must be a UTC Z-suffix timestamp, got {}",
            response.started_at
        );
        assert!(response
            .events
            .iter()
            .all(|event| event.timestamp.ends_with('Z')));
    }

    #[tokio::test]
    async fn get_session_details_rejects_missing_and_foreign_sessions() {
        let (state, user, _guard) = database_fixture().await;
        let missing = get_session_details(Path(9999), user, State(state.clone()))
            .await
            .expect_err("missing session must 404");
        assert_eq!(missing.status(), StatusCode::NOT_FOUND);
        assert_eq!(missing.detail(), "Session not found");

        let foreign = get_session_details(Path(9302), user, State(state.clone()))
            .await
            .expect_err("foreign session must 404");
        assert_eq!(foreign.status(), StatusCode::NOT_FOUND);
        assert_eq!(foreign.detail(), "Session not found");
    }
}
