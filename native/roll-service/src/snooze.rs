//! Native cutover of `POST /api/v1/snooze/` and alias `POST /api/snooze/`.
use crate::{
    auth::AuthenticatedUser,
    db,
    reading_session::{self, ReadingSession, SessionPolicy},
    ApiError, AppState,
};
use axum::{extract::State, http::StatusCode, Json};
use deadpool_postgres::Object;
use serde::Serialize;
use serde_json::{json, Value};
use std::sync::Arc;
use tokio_postgres::Transaction;

fn now_seconds() -> Result<f64, ApiError> {
    use std::time::{SystemTime, UNIX_EPOCH};
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| internal())?
        .as_secs_f64())
}
fn internal() -> ApiError {
    ApiError(StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error")
}
fn unavailable() -> ApiError {
    ApiError(StatusCode::SERVICE_UNAVAILABLE, "Database temporarily unavailable")
}
fn bad_request(msg: &'static str) -> ApiError {
    ApiError(StatusCode::BAD_REQUEST, msg)
}

const DICE_LADDER: [i32; 9] = [4, 6, 8, 10, 12, 20, 30, 50, 100];
fn step_up(die: i32) -> i32 {
    let idx = DICE_LADDER.iter().position(|&d| d == die).unwrap_or(0);
    if idx + 1 < DICE_LADDER.len() {
        DICE_LADDER[idx + 1]
    } else {
        die
    }
}

#[derive(Debug, Serialize)]
struct SnoozedThreadInfo {
    id: i32,
    title: String,
}
#[derive(Debug, Serialize)]
struct ActiveThreadInfo {
    id: Option<i32>,
    title: String,
    format: String,
    issues_remaining: i32,
    queue_position: i32,
    last_rolled_result: Option<i32>,
}
#[derive(Debug, Serialize)]
struct SessionBandwidthState {
    #[serde(skip_serializing_if = "Option::is_none")]
    predicted_bandwidth: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    active_bandwidth: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    confidence: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    source: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    mode_version: Option<String>,
}
#[derive(Debug, Serialize)]
struct SessionIntentState {
    #[serde(skip_serializing_if = "Option::is_none")]
    predicted_intent: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    active_intent: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    confidence: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    source: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    mode_version: Option<String>,
}
#[derive(Debug, Serialize)]
struct SnoozeCorrectionInfo {
    bandwidth_changed: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    active_bandwidth: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    active_confidence: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    predicted_bandwidth: Option<String>,
    reason_code: &'static str,
    suggest_clarification: bool,
}

#[derive(Debug, Serialize)]
pub struct SessionResponse {
    id: i32,
    started_at: String,
    ended_at: Option<String>,
    start_die: i32,
    manual_die: Option<i32>,
    user_id: i32,
    ladder_path: String,
    active_thread: Option<ActiveThreadInfo>,
    current_die: i32,
    last_rolled_result: Option<i32>,
    has_restore_point: bool,
    snapshot_count: i32,
    snoozed_thread_ids: Vec<i32>,
    snoozed_threads: Vec<SnoozedThreadInfo>,
    skipped_thread_ids: Vec<i32>,
    skipped_threads: Vec<SnoozedThreadInfo>,
    pending_thread_id: Option<i32>,
    timezone: Option<String>,
    reading_bandwidth: Option<String>,
    reading_intent: Option<String>,
    reading_mode_source: Option<String>,
    reading_mode_suggested: bool,
    bandwidth: Option<SessionBandwidthState>,
    intent: Option<SessionIntentState>,
    correction: Option<SnoozeCorrectionInfo>,
}

struct Pending(Option<Object>);
impl Drop for Pending {
    fn drop(&mut self) {
        // Let `Object`'s own Drop return the connection to the pool.
        // Do not call a non-existent `Object::take`; just take the option out
        // so the inner `Object` is dropped here.
        if let Some(conn) = self.0.take() {
            drop(conn);
        }
    }
}

pub async fn snooze_thread(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<SessionResponse>, ApiError> {
    let active = reading_session::bootstrap(&state, user.clone(), None, SessionPolicy::default()).await?;
    let session = active.session;
    let current_die = active.current_die;
    let Some(pending_thread_id) = session.pending_thread_id else {
        return Err(bad_request("No pending thread to snooze. Please roll the dice first."));
    };

    let mut pending = Pending(Some(db::checkout(&state).await?));
    let result = tokio::time::timeout(
        state.request_timeout,
        mutate(
            &state,
            user,
            &session,
            pending_thread_id,
            current_die,
            pending.0.as_mut().unwrap(),
        ),
    )
    .await;
    match result {
        Err(_) => Err(unavailable()),
        Ok(Ok(resp)) => {
            drop(pending.0.take());
            Ok(Json(resp))
        }
        Ok(Err(e)) => Err(e),
    }
}

async fn mutate(
    _state: &AppState,
    user: AuthenticatedUser,
    session: &ReadingSession,
    pending_thread_id: i32,
    current_die: i32,
    conn: &mut Object,
) -> Result<SessionResponse, ApiError> {
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    tx.batch_execute("SET LOCAL TIME ZONE 'UTC'")
        .await
        .map_err(db::query_error)?;

    // Lock user row
    tx.query_one("SELECT id FROM users WHERE id = $1 FOR KEY SHARE", &[&user.id()])
        .await
        .map_err(db::query_error)?;

    // Load fresh session JSON
    let session_row: String = tx
        .query_one(
            "SELECT row_to_json(s)::text FROM sessions s WHERE id = $1 AND user_id = $2",
            &[&session.id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    let session_json: Value = serde_json::from_str(&session_row).map_err(|_| internal())?;

    // Determine new die
    let manual_die: Option<i32> = session_json.get("manual_die").and_then(|v| v.as_i64()).map(|v| v as i32);
    let new_die = if let Some(d) = manual_die.filter(|d| *d != 0) {
        d
    } else {
        step_up(current_die)
    };

    // Load thread for active info
    let thread_row = tx
        .query_opt(
            "SELECT id, title, format, issues_remaining, queue_position FROM threads WHERE id = $1 AND user_id = $2",
            &[&pending_thread_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let (thread_title, thread_format, thread_issues, thread_queue) = if let Some(row) = thread_row {
        (
            row.get::<_, String>(1),
            row.get::<_, String>(2),
            row.get::<_, i32>(3),
            row.get::<_, i32>(4),
        )
    } else {
        // Thread missing
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError(StatusCode::BAD_REQUEST, "Pending thread not found"));
    };

    // Find last roll result
    let roll_result: Option<i32> = tx
        .query_opt(
            "SELECT result FROM events WHERE session_id = $1 AND type = 'roll' AND selected_thread_id = $2 ORDER BY timestamp DESC, id DESC LIMIT 1",
            &[&session.id, &pending_thread_id],
        )
        .await
        .map_err(db::query_error)?
        .map(|r| r.get(0));

    // Update snoozed list
    let snoozed_ids: Vec<i32> = session_json
        .get("snoozed_thread_ids")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|v| v.as_i64().map(|n| n as i32)).collect())
        .unwrap_or_default();
    let mut updated_snoozed = snoozed_ids;
    if !updated_snoozed.contains(&pending_thread_id) {
        updated_snoozed.push(pending_thread_id);
    }

    // Determine bandwidth correction (stub: no change)
    let active_bandwidth_str = session_json.get("active_bandwidth").and_then(|v| v.as_str()).map(|s| s.to_string());
    let bandwidth_confidence = session_json.get("bandwidth_confidence").and_then(|v| v.as_f64());
    let predicted_bandwidth_str = session_json.get("predicted_bandwidth").and_then(|v| v.as_str()).map(|s| s.to_string());

    let correction = SnoozeCorrectionInfo {
        bandwidth_changed: false,
        active_bandwidth: active_bandwidth_str.clone(),
        active_confidence: bandwidth_confidence,
        predicted_bandwidth: predicted_bandwidth_str.clone(),
        reason_code: "no_correction",
        suggest_clarification: false,
    };

    // Record snooze event
    let now = now_seconds()?;
    let context = json!({
        "bandwidth_before": active_bandwidth_str,
        "bandwidth_after": active_bandwidth_str,
        "bandwidth_source": "snooze",
        "reason_code": "no_correction",
    });
    tx.execute(
        "INSERT INTO events (type, timestamp, session_id, thread_id, die, die_after, context) VALUES ('snooze', to_timestamp($1), $2, $3, $4, $5, $6::json)",
        &[&now, &session.id, &pending_thread_id, &current_die, &new_die, &context.to_string()],
    )
    .await
    .map_err(db::query_error)?;

    // Update session
    let snoozed_json = serde_json::to_string(&updated_snoozed).map_err(|_| internal())?;
    tx.execute(
        "UPDATE sessions SET snoozed_thread_ids = $2::json, pending_thread_id = NULL, pending_thread_updated_at = NULL WHERE id = $1 AND user_id = $3",
        &[&session.id, &snoozed_json, &user.id()],
    )
    .await
    .map_err(db::query_error)?;

    // Build ladder path
    let ladder_path = build_ladder_path(&tx, session.id).await?;

    // Snapshot count
    let snapshot_count: i32 = tx
        .query_one("SELECT count(*) FROM snapshots WHERE session_id = $1", &[&session.id])
        .await
        .map_err(db::query_error)?
        .get(0);

    // Load snoozed threads titles
    let snoozed_threads = if updated_snoozed.is_empty() {
        vec![]
    } else {
        // Simple query
        let rows = tx
            .query(
                "SELECT id, title FROM threads WHERE id = ANY($1::int[]) AND user_id = $2",
                &[&&updated_snoozed[..], &user.id()],
            )
            .await
            .map_err(db::query_error)?;
        rows.iter()
            .map(|r| SnoozedThreadInfo { id: r.get(0), title: r.get(1) })
            .collect()
    };

    // Skipped threads
    let skipped_ids: Vec<i32> = session_json
        .get("skipped_thread_ids")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|v| v.as_i64().map(|n| n as i32)).collect())
        .unwrap_or_default();
    let skipped_threads = if skipped_ids.is_empty() {
        vec![]
    } else {
        let rows = tx
            .query(
                "SELECT id, title FROM threads WHERE id = ANY($1::int[]) AND user_id = $2",
                &[&&skipped_ids[..], &user.id()],
            )
            .await
            .map_err(db::query_error)?;
        rows.iter().map(|r| SnoozedThreadInfo { id: r.get(0), title: r.get(1) }).collect()
    };

    // Refresh session row
    let refreshed_row: String = tx
        .query_one(
            "SELECT row_to_json(s)::text FROM sessions s WHERE id = $1 AND user_id = $2",
            &[&session.id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    let refreshed: Value = serde_json::from_str(&refreshed_row).map_err(|_| internal())?;

    tx.commit().await.map_err(db::query_error)?;

    let started_at = refreshed.get("started_at").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let ended_at = refreshed.get("ended_at").and_then(|v| v.as_str()).map(|s| s.to_string());
    let start_die = refreshed.get("start_die").and_then(|v| v.as_i64()).unwrap_or(0) as i32;
    let manual_die_opt = refreshed.get("manual_die").and_then(|v| v.as_i64()).map(|v| v as i32);
    let timezone = refreshed.get("timezone").and_then(|v| v.as_str()).map(|s| s.to_string());
    let reading_bandwidth = refreshed.get("reading_bandwidth").and_then(|v| v.as_str()).map(|s| s.to_string());
    let reading_intent = refreshed.get("reading_intent").and_then(|v| v.as_str()).map(|s| s.to_string());
    let reading_mode_source = refreshed.get("reading_mode_source").and_then(|v| v.as_str()).map(|s| s.to_string());
    let reading_mode_suggested = refreshed.get("reading_mode_suggested").and_then(|v| v.as_bool()).unwrap_or(false);

    let active_thread = Some(ActiveThreadInfo {
        id: Some(pending_thread_id),
        title: thread_title,
        format: normalize_format(&thread_format),
        issues_remaining: thread_issues,
        queue_position: thread_queue,
        last_rolled_result: roll_result,
    });

    let bandwidth_state = SessionBandwidthState {
        predicted_bandwidth: predicted_bandwidth_str,
        active_bandwidth: active_bandwidth_str,
        confidence: bandwidth_confidence,
        source: refreshed.get("bandwidth_source").and_then(|v| v.as_str()).map(|s| s.to_string()),
        mode_version: refreshed.get("bandwidth_version").and_then(|v| v.as_str()).map(|s| s.to_string()),
    };
    let intent_state = SessionIntentState {
        predicted_intent: refreshed.get("predicted_intent").and_then(|v| v.as_str()).map(|s| s.to_string()),
        active_intent: refreshed.get("active_intent").and_then(|v| v.as_str()).map(|s| s.to_string()),
        confidence: refreshed.get("intent_confidence").and_then(|v| v.as_f64()),
        source: refreshed.get("intent_source").and_then(|v| v.as_str()).map(|s| s.to_string()),
        mode_version: refreshed.get("intent_version").and_then(|v| v.as_str()).map(|s| s.to_string()),
    };

    Ok(SessionResponse {
        id: session.id,
        started_at,
        ended_at,
        start_die,
        manual_die: manual_die_opt,
        user_id: session.user_id,
        ladder_path,
        active_thread,
        current_die: new_die,
        last_rolled_result: roll_result,
        has_restore_point: snapshot_count > 0,
        snapshot_count,
        snoozed_thread_ids: updated_snoozed,
        snoozed_threads,
        skipped_thread_ids: skipped_ids,
        skipped_threads,
        pending_thread_id: None,
        timezone,
        reading_bandwidth,
        reading_intent,
        reading_mode_source,
        reading_mode_suggested,
        bandwidth: Some(bandwidth_state),
        intent: Some(intent_state),
        correction: Some(correction),
    })
}

async fn build_ladder_path(tx: &Transaction<'_>, session_id: i32) -> Result<String, ApiError> {
    let rows = tx
        .query(
            "SELECT die_after FROM events WHERE session_id = $1 AND type IN ('rate','snooze','undo') AND die_after IS NOT NULL ORDER BY timestamp, id",
            &[&session_id],
        )
        .await
        .map_err(db::query_error)?;
    // Need start_die
    let start_die_row = tx
        .query_one("SELECT start_die FROM sessions WHERE id = $1", &[&session_id])
        .await
        .map_err(db::query_error)?;
    let start_die: i32 = start_die_row.get(0);
    let mut path = vec![start_die];
    for row in rows {
        let die: Option<i32> = row.try_get(0).map_err(db::query_error)?;
        if let Some(d) = die {
            path.push(d);
        }
    }
    Ok(path.iter().map(|d| d.to_string()).collect::<Vec<_>>().join(" → "))
}

fn normalize_format(value: &str) -> String {
    let v = value.trim();
    match v.to_lowercase().as_str() {
        "comic" | "comics" => "Comic".into(),
        "digital" => "Digital".into(),
        _ => v.into(),
    }
}
