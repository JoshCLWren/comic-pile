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
    ApiError(
        StatusCode::SERVICE_UNAVAILABLE,
        "Database temporarily unavailable",
    )
}
fn bad_request(msg: &'static str) -> ApiError {
    ApiError(StatusCode::BAD_REQUEST, msg)
}

/// Python isoformat for a PostgreSQL `timestamp with time zone` text value.
fn python_timestamp(value: &str) -> String {
    let Some((date, time)) = value.split_once(' ') else {
        return value.to_owned();
    };
    let offset_start = time
        .char_indices()
        .rev()
        .find(|(index, character)| *index >= 8 && matches!(character, '+' | '-'))
        .map(|(index, _)| index);
    let time = match offset_start {
        Some(index) => {
            let (clock, offset) = time.split_at(index);
            let (sign, offset) = offset.split_at(1);
            let offset = offset.trim();
            let normalized = if offset.contains(':') {
                offset.to_owned()
            } else if offset.len() == 2 {
                format!("{offset}:00")
            } else if offset.len() == 4 {
                format!("{}:{}", &offset[..2], &offset[2..])
            } else {
                offset.to_owned()
            };
            format!("{clock}{sign}{normalized}")
        }
        None => time.to_owned(),
    };
    format!("{date}T{time}")
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
struct TagResponse {
    id: i32,
    name: String,
    color: Option<String>,
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
    total_issues: Option<i32>,
    reading_progress: Option<String>,
    issues_read: Option<i32>,
    last_rating: Option<f64>,
    tags: Vec<TagResponse>,
    issue_id: Option<i32>,
    issue_number: Option<String>,
    next_issue_id: Option<i32>,
    next_issue_number: Option<String>,
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
    let active = reading_session::bootstrap(&state, user, None, SessionPolicy::default()).await?;
    let session = active.session;
    let current_die = active.current_die;
    let Some(pending_thread_id) = session.pending_thread_id else {
        return Err(bad_request(
            "No pending thread to snooze. Please roll the dice first.",
        ));
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
    tx.query_one(
        "SELECT id FROM users WHERE id = $1 FOR KEY SHARE",
        &[&user.id()],
    )
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
    let manual_die: Option<i32> = session_json
        .get("manual_die")
        .and_then(|v| v.as_i64())
        .map(|v| v as i32);
    let new_die = if let Some(d) = manual_die.filter(|d| *d != 0) {
        d
    } else {
        step_up(current_die)
    };

    // Load thread for active info
    let thread_row = tx
        .query_opt(
            "SELECT id, title, format, issues_remaining FROM threads WHERE id = $1 AND user_id = $2",
            &[&pending_thread_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let (thread_title, thread_format, thread_issues) = if let Some(row) = thread_row {
        (
            row.get::<_, String>(1),
            row.get::<_, String>(2),
            row.get::<_, i32>(3),
        )
    } else {
        // Thread missing
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "Pending thread not found",
        ));
    };
    // Dense display position matching legacy dense_positions.
    let pos_rows = tx
        .query(
            "SELECT id FROM threads WHERE user_id = $1 AND status = 'active' ORDER BY is_blocked, queue_position, id",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let thread_queue = pos_rows
        .iter()
        .position(|r| r.get::<_, i32>(0) == pending_thread_id)
        .map(|i| i as i32 + 1)
        .unwrap_or(0);

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
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_i64().map(|n| n as i32))
                .collect()
        })
        .unwrap_or_default();
    let mut updated_snoozed = snoozed_ids;
    if !updated_snoozed.contains(&pending_thread_id) {
        updated_snoozed.push(pending_thread_id);
    }

    // Original bandwidth state before correction.
    let original_active_bw = session_json
        .get("active_bandwidth")
        .and_then(|v| v.as_str())
        .unwrap_or("balanced")
        .to_string();
    let original_confidence = session_json
        .get("bandwidth_confidence")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.5);
    let original_predicted_bw = session_json
        .get("predicted_bandwidth")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| original_active_bw.clone());

    // Recent snooze evidence for consecutive count + last direction.
    let recent_rows = tx
        .query(
            "SELECT die, die_after FROM events WHERE session_id = $1 AND type = 'snooze' ORDER BY timestamp DESC, id DESC LIMIT 10",
            &[&session.id],
        )
        .await
        .map_err(db::query_error)?;
    let consecutive_snoozes = recent_rows.len() as i32 + 1;
    let last_snooze_direction: Option<String> = if recent_rows.is_empty() {
        None
    } else {
        let prev_die: i32 = recent_rows[0]
            .try_get::<_, Option<i32>>(0)
            .ok()
            .flatten()
            .unwrap_or(6);
        let prev_after: i32 = recent_rows[0]
            .try_get::<_, Option<i32>>(1)
            .ok()
            .flatten()
            .unwrap_or(8);
        match prev_after.cmp(&prev_die) {
            std::cmp::Ordering::Greater => Some("heavier".to_string()),
            std::cmp::Ordering::Less => Some("lighter".to_string()),
            std::cmp::Ordering::Equal => None,
        }
    };

    // Classify candidate effort (no effort model yet, defaults to balanced)
    let candidate_effort = classify_candidate_effort(None, None);

    let correction_result = compute_snooze_correction(
        &original_active_bw,
        original_confidence,
        &original_predicted_bw,
        &candidate_effort,
        consecutive_snoozes,
        last_snooze_direction.as_deref(),
    );

    let corrected_active_bw = correction_result.active_bandwidth.clone();
    let corrected_confidence = correction_result.active_confidence;
    let corrected_predicted_bw = correction_result.predicted_bandwidth.clone();

    let correction = SnoozeCorrectionInfo {
        bandwidth_changed: correction_result.bandwidth_changed,
        active_bandwidth: Some(corrected_active_bw.clone()),
        active_confidence: Some(corrected_confidence),
        predicted_bandwidth: Some(corrected_predicted_bw.clone()),
        reason_code: correction_result.reason_code,
        suggest_clarification: correction_result.suggest_clarification,
    };

    // Values used for response bandwidth state.
    let active_bandwidth_str = Some(corrected_active_bw.clone());
    let bandwidth_confidence = Some(corrected_confidence);
    let predicted_bandwidth_str = Some(corrected_predicted_bw.clone());

    // Source roll event id
    let source_roll_event_id: Option<i32> = tx
        .query_opt(
            "SELECT id FROM events WHERE session_id = $1 AND type = 'roll' AND selected_thread_id = $2 ORDER BY timestamp DESC, id DESC LIMIT 1",
            &[&session.id, &pending_thread_id],
        )
        .await
        .map_err(db::query_error)?
        .map(|r| r.get(0));

    // Record snooze event
    let now = now_seconds()?;
    // confidence_before captured before mutation
    let confidence_before = original_confidence;
    let context = json!({
        "bandwidth_before": original_active_bw,
        "bandwidth_after": corrected_active_bw,
        "confidence_before": confidence_before,
        "confidence_after": corrected_confidence,
        "bandwidth_source": "snooze",
        "reason_code": correction_result.reason_code,
        "consecutive_snoozes": consecutive_snoozes,
        "suggest_clarification": correction_result.suggest_clarification,
    });
    tx.execute(
        "INSERT INTO events (type, timestamp, session_id, thread_id, die, die_after, context, source_roll_event_id) VALUES ('snooze', to_timestamp($1), $2, $3, $4, $5, $6::json, $7)",
        &[&now, &session.id, &pending_thread_id, &current_die, &new_die, &context.to_string(), &source_roll_event_id],
    )
    .await
    .map_err(db::query_error)?;

    // Update session
    let snoozed_json = serde_json::to_string(&updated_snoozed).map_err(|_| internal())?;
    tx.execute(
        "UPDATE sessions SET snoozed_thread_ids = $2::json, pending_thread_id = NULL, pending_thread_updated_at = NULL, active_bandwidth = $4, bandwidth_confidence = $5, bandwidth_source = 'snooze', predicted_bandwidth = COALESCE(predicted_bandwidth, $6) WHERE id = $1 AND user_id = $3",
        &[&session.id, &snoozed_json, &user.id(), &corrected_active_bw, &corrected_confidence, &original_predicted_bw],
    )
    .await
    .map_err(db::query_error)?;

    // Build ladder path
    let ladder_path = build_ladder_path(&tx, session.id).await?;

    // Snapshot count
    let snapshot_count: i32 = tx
        .query_one(
            "SELECT count(*) FROM snapshots WHERE session_id = $1",
            &[&session.id],
        )
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
            .map(|r| SnoozedThreadInfo {
                id: r.get(0),
                title: r.get(1),
            })
            .collect()
    };

    // Skipped threads
    let skipped_ids: Vec<i32> = session_json
        .get("skipped_thread_ids")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_i64().map(|n| n as i32))
                .collect()
        })
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
        rows.iter()
            .map(|r| SnoozedThreadInfo {
                id: r.get(0),
                title: r.get(1),
            })
            .collect()
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

    let started_at = refreshed
        .get("started_at")
        .and_then(|v| v.as_str())
        .map(python_timestamp)
        .unwrap_or_default();
    let ended_at = refreshed
        .get("ended_at")
        .and_then(|v| v.as_str())
        .map(python_timestamp);
    let start_die = refreshed
        .get("start_die")
        .and_then(|v| v.as_i64())
        .unwrap_or(0) as i32;
    let manual_die_opt = refreshed
        .get("manual_die")
        .and_then(|v| v.as_i64())
        .map(|v| v as i32);
    let timezone = refreshed
        .get("timezone")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let reading_bandwidth = refreshed
        .get("reading_bandwidth")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let reading_intent = refreshed
        .get("reading_intent")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let reading_mode_source = refreshed
        .get("reading_mode_source")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());
    let reading_mode_suggested = refreshed
        .get("reading_mode_suggested")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    let active_thread = Some(ActiveThreadInfo {
        id: Some(pending_thread_id),
        title: thread_title,
        format: normalize_format(&thread_format),
        issues_remaining: thread_issues,
        queue_position: thread_queue,
        last_rolled_result: roll_result,
        total_issues: None,
        reading_progress: None,
        issues_read: None,
        last_rating: None,
        tags: Vec::new(),
        issue_id: None,
        issue_number: None,
        next_issue_id: None,
        next_issue_number: None,
    });

    let bandwidth_state = SessionBandwidthState {
        predicted_bandwidth: predicted_bandwidth_str,
        active_bandwidth: active_bandwidth_str,
        confidence: bandwidth_confidence,
        source: refreshed
            .get("bandwidth_source")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
        mode_version: refreshed
            .get("bandwidth_version")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
    };
    let intent_state = SessionIntentState {
        predicted_intent: refreshed
            .get("predicted_intent")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
        active_intent: refreshed
            .get("active_intent")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
        confidence: refreshed.get("intent_confidence").and_then(|v| v.as_f64()),
        source: refreshed
            .get("intent_source")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
        mode_version: refreshed
            .get("intent_version")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
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
        .query_one(
            "SELECT start_die FROM sessions WHERE id = $1",
            &[&session_id],
        )
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
    Ok(path
        .iter()
        .map(|d| d.to_string())
        .collect::<Vec<_>>()
        .join(" → "))
}

fn normalize_format(value: &str) -> String {
    let v = value.trim();
    match v.to_lowercase().as_str() {
        "comic" | "comics" => "Comic".into(),
        "digital" => "Digital".into(),
        _ => v.into(),
    }
}

struct CorrectionResult {
    active_bandwidth: String,
    active_confidence: f64,
    bandwidth_changed: bool,
    reason_code: &'static str,
    suggest_clarification: bool,
    predicted_bandwidth: String,
}

fn bandwidth_index(level: &str) -> i32 {
    match level {
        "light" => 0,
        "balanced" => 1,
        "deep" => 2,
        _ => 1,
    }
}

fn classify_candidate_effort(effort_source: Option<&str>, effort_minutes: Option<f64>) -> String {
    // Maps effort estimates to a coarse bandwidth level for correction comparison.
    // This is intentionally simple; richer effort modeling lives in the reading-effort model.
    if effort_minutes.is_none() || effort_source.is_none() || effort_source == Some("none") {
        return "balanced".to_string();
    }

    let minutes = effort_minutes.unwrap();
    if minutes < 12.0 {
        "light".to_string()
    } else if minutes < 20.0 {
        "balanced".to_string()
    } else {
        "deep".to_string()
    }
}

fn compute_snooze_correction(
    current_bandwidth: &str,
    current_confidence: f64,
    predicted_bandwidth: &str,
    candidate_effort_level: &str,
    consecutive_snoozes: i32,
    last_snooze_direction: Option<&str>,
) -> CorrectionResult {
    let current_idx = bandwidth_index(current_bandwidth);
    let candidate_idx = bandwidth_index(candidate_effort_level);

    // Contradictory snooze pattern
    if consecutive_snoozes >= 3 && last_snooze_direction.is_some() {
        let dir = last_snooze_direction.unwrap();
        if dir != "heavier" && candidate_idx >= current_idx {
            return CorrectionResult {
                active_bandwidth: current_bandwidth.to_string(),
                active_confidence: (current_confidence - 0.15).max(0.0),
                bandwidth_changed: false,
                reason_code: "clarification_needed",
                suggest_clarification: true,
                predicted_bandwidth: predicted_bandwidth.to_string(),
            };
        }
        if dir != "lighter" && candidate_idx <= current_idx {
            return CorrectionResult {
                active_bandwidth: current_bandwidth.to_string(),
                active_confidence: (current_confidence - 0.15).max(0.0),
                bandwidth_changed: false,
                reason_code: "clarification_needed",
                suggest_clarification: true,
                predicted_bandwidth: predicted_bandwidth.to_string(),
            };
        }
    }

    // Heavy candidate snooze: shift toward lighter bandwidth
    if candidate_idx > current_idx {
        let (new_bandwidth, new_confidence) = if current_bandwidth == "balanced" {
            ("light".to_string(), (current_confidence + 0.1).min(1.0))
        } else if current_bandwidth == "deep" {
            ("balanced".to_string(), (current_confidence + 0.05).min(1.0))
        } else {
            (
                current_bandwidth.to_string(),
                (current_confidence - 0.1).max(0.0),
            )
        };
        if new_bandwidth != current_bandwidth {
            return CorrectionResult {
                active_bandwidth: new_bandwidth,
                active_confidence: new_confidence,
                bandwidth_changed: true,
                reason_code: "heavy_snooze_shift",
                suggest_clarification: false,
                predicted_bandwidth: predicted_bandwidth.to_string(),
            };
        }
        return CorrectionResult {
            active_bandwidth: new_bandwidth,
            active_confidence: new_confidence,
            bandwidth_changed: false,
            reason_code: "light_snooze_deflate",
            suggest_clarification: false,
            predicted_bandwidth: predicted_bandwidth.to_string(),
        };
    }

    // Light candidate snooze: degrade confidence or shift toward deeper
    if candidate_idx < current_idx {
        let (new_bandwidth, new_confidence) = if current_bandwidth == "balanced" {
            ("deep".to_string(), (current_confidence + 0.05).min(1.0))
        } else if current_bandwidth == "light" {
            ("balanced".to_string(), (current_confidence + 0.05).min(1.0))
        } else {
            (
                current_bandwidth.to_string(),
                (current_confidence - 0.1).max(0.0),
            )
        };
        if new_bandwidth != current_bandwidth {
            return CorrectionResult {
                active_bandwidth: new_bandwidth,
                active_confidence: new_confidence,
                bandwidth_changed: true,
                reason_code: "light_snooze_deflate",
                suggest_clarification: false,
                predicted_bandwidth: predicted_bandwidth.to_string(),
            };
        }
        return CorrectionResult {
            active_bandwidth: new_bandwidth,
            active_confidence: new_confidence,
            bandwidth_changed: false,
            reason_code: "light_snooze_deflate",
            suggest_clarification: false,
            predicted_bandwidth: predicted_bandwidth.to_string(),
        };
    }

    // Same-level candidate
    CorrectionResult {
        active_bandwidth: current_bandwidth.to_string(),
        active_confidence: (current_confidence - 0.05).max(0.0),
        bandwidth_changed: false,
        reason_code: "confidence_degrade",
        suggest_clarification: false,
        predicted_bandwidth: predicted_bandwidth.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn correction_heavy_candidate_shifts_lighter() {
        let r = compute_snooze_correction("balanced", 0.5, "balanced", "deep", 1, None);
        assert!(r.bandwidth_changed);
        assert_eq!(r.active_bandwidth, "light");
        assert_eq!(r.reason_code, "heavy_snooze_shift");
    }

    #[test]
    fn correction_no_change_stays_no_correction_for_same_level() {
        // same level candidate degrades confidence
        let r = compute_snooze_correction("balanced", 0.5, "balanced", "balanced", 1, None);
        assert!(!r.bandwidth_changed);
        assert_eq!(r.reason_code, "confidence_degrade");
    }

    #[test]
    fn deep_mode_boundary_keeps_bandwidth_same() {
        // Deep-mode boundary with deep candidate keeps bandwidth, degrades confidence
        let r = compute_snooze_correction("deep", 0.7, "balanced", "deep", 1, None);
        assert!(!r.bandwidth_changed);
        assert_eq!(r.active_bandwidth, "deep");
        assert!(r.active_confidence < 0.7);
        assert_eq!(r.reason_code, "confidence_degrade");
    }

    #[test]
    fn light_snooze_shifts_balanced_to_deep() {
        // Snoozing a light candidate while balanced shifts to deep
        let r = compute_snooze_correction("balanced", 0.5, "balanced", "light", 1, None);
        assert!(r.bandwidth_changed);
        assert_eq!(r.active_bandwidth, "deep");
        assert_eq!(r.reason_code, "light_snooze_deflate");
    }

    #[test]
    fn light_mode_boundary_keeps_bandwidth_same() {
        // Light-mode boundary with light candidate keeps bandwidth, degrades confidence
        let r = compute_snooze_correction("light", 0.7, "balanced", "light", 1, None);
        assert!(!r.bandwidth_changed);
        assert_eq!(r.active_bandwidth, "light");
        assert!(r.active_confidence < 0.7);
        assert_eq!(r.reason_code, "confidence_degrade");
    }

    #[test]
    fn already_light_cannot_go_lighter() {
        // Snoozing a deep candidate while already light degrades confidence
        let r = compute_snooze_correction("light", 0.7, "balanced", "deep", 1, None);
        assert!(!r.bandwidth_changed);
        assert_eq!(r.active_bandwidth, "light");
        assert!(r.active_confidence < 0.7);
        assert_eq!(r.reason_code, "light_snooze_deflate");
    }

    #[test]
    fn already_deep_cannot_go_deeper() {
        // Snoozing a light candidate while already deep degrades confidence
        let r = compute_snooze_correction("deep", 0.7, "balanced", "light", 1, None);
        assert!(!r.bandwidth_changed);
        assert_eq!(r.active_bandwidth, "deep");
        assert!(r.active_confidence < 0.7);
        assert_eq!(r.reason_code, "light_snooze_deflate");
    }

    #[test]
    fn preserves_predicted_bandwidth() {
        // Predicted bandwidth is always passed through unchanged
        let r = compute_snooze_correction("balanced", 0.5, "deep", "balanced", 1, None);
        assert_eq!(r.predicted_bandwidth, "deep");
    }

    #[test]
    fn confidence_never_exceeds_1() {
        // Confidence is capped at 1.0
        let r = compute_snooze_correction("balanced", 0.95, "balanced", "deep", 1, None);
        assert!(r.active_confidence <= 1.0);
    }

    #[test]
    fn confidence_never_below_0() {
        // Confidence is floored at 0.0
        let r = compute_snooze_correction("light", 0.05, "balanced", "deep", 1, None);
        assert!(r.active_confidence >= 0.0);
    }

    #[test]
    fn contradictory_snoozes_request_clarification() {
        // Three consecutive contradictory snoozes suggest clarification
        // Previous snoozes were shifting heavier, now a balanced candidate
        let r =
            compute_snooze_correction("balanced", 0.5, "balanced", "balanced", 3, Some("heavier"));
        assert!(r.suggest_clarification);
        assert_eq!(r.reason_code, "clarification_needed");
        assert!(!r.bandwidth_changed);
    }

    #[test]
    fn three_snoozes_contradictory_direction_requests_clarification() {
        // Three consecutive snoozes with contradictory direction request clarification
        let r =
            compute_snooze_correction("balanced", 0.5, "balanced", "balanced", 3, Some("heavier"));
        assert!(r.suggest_clarification);
    }

    #[test]
    fn two_snoozes_no_clarification() {
        // Two consecutive snoozes do not trigger clarification
        let r =
            compute_snooze_correction("balanced", 0.5, "balanced", "balanced", 2, Some("heavier"));
        assert!(!r.suggest_clarification);
    }

    #[test]
    fn deterministic_output() {
        // Same inputs always produce the same output
        let args = ("balanced", 0.5, "balanced", "deep", 2, Some("lighter"));
        let r1 = compute_snooze_correction(args.0, args.1, args.2, args.3, args.4, args.5);
        let r2 = compute_snooze_correction(args.0, args.1, args.2, args.3, args.4, args.5);
        assert_eq!(r1.active_bandwidth, r2.active_bandwidth);
        assert_eq!(r1.active_confidence, r2.active_confidence);
        assert_eq!(r1.reason_code, r2.reason_code);
        assert_eq!(r1.bandwidth_changed, r2.bandwidth_changed);
        assert_eq!(r1.suggest_clarification, r2.suggest_clarification);
    }

    #[test]
    fn classify_candidate_effort_defaults_to_balanced() {
        assert_eq!(classify_candidate_effort(None, None), "balanced");
        assert_eq!(classify_candidate_effort(Some("none"), None), "balanced");
        assert_eq!(classify_candidate_effort(None, Some(15.0)), "balanced");
    }

    #[test]
    fn classify_candidate_effort_maps_by_minutes() {
        assert_eq!(
            classify_candidate_effort(Some("observed"), Some(10.0)),
            "light"
        );
        assert_eq!(
            classify_candidate_effort(Some("observed"), Some(15.0)),
            "balanced"
        );
        assert_eq!(
            classify_candidate_effort(Some("observed"), Some(25.0)),
            "deep"
        );
    }

    #[test]
    fn classify_candidate_effort_boundaries() {
        // Exactly 12 minutes is balanced
        assert_eq!(
            classify_candidate_effort(Some("observed"), Some(12.0)),
            "balanced"
        );
        // Exactly 20 minutes is deep
        assert_eq!(
            classify_candidate_effort(Some("observed"), Some(20.0)),
            "deep"
        );
        // Zero minutes with source is still light (0 < 12)
        assert_eq!(
            classify_candidate_effort(Some("observed"), Some(0.0)),
            "light"
        );
        // 'none' source returns balanced
        assert_eq!(
            classify_candidate_effort(Some("none"), Some(10.0)),
            "balanced"
        );
        // Publication-era source works like any other
        assert_eq!(
            classify_candidate_effort(Some("publication_era"), Some(22.0)),
            "deep"
        );
    }

    #[test]
    fn contradictory_snooze_heavier_then_lighter_candidate() {
        // Last snooze was heavier, now lighter candidate - contradictory
        let r = compute_snooze_correction("balanced", 0.5, "balanced", "light", 3, Some("heavier"));
        assert!(r.suggest_clarification);
        assert_eq!(r.reason_code, "clarification_needed");
    }

    #[test]
    fn contradictory_snooze_lighter_then_heavier_candidate() {
        // Last snooze was lighter, now heavier candidate - contradictory
        let r = compute_snooze_correction("balanced", 0.5, "balanced", "deep", 3, Some("lighter"));
        assert!(r.suggest_clarification);
        assert_eq!(r.reason_code, "clarification_needed");
    }

    #[test]
    fn timestamp_normalization_matches_python() {
        // PostgreSQL timestamps should be normalized to Python ISO format
        assert_eq!(
            python_timestamp("2026-10-30 12:34:56.123456+00"),
            "2026-10-30T12:34:56.123456+00:00"
        );
        assert_eq!(
            python_timestamp("2026-10-30 12:34:56+00"),
            "2026-10-30T12:34:56+00:00"
        );
        assert_eq!(
            python_timestamp("2026-10-30 12:34:56.5-05"),
            "2026-10-30T12:34:56.5-05:00"
        );
        // Already correct format passes through
        assert_eq!(python_timestamp("already-correct"), "already-correct");
    }
}
