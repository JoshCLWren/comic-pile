//! Native cutover of the manual Roll pick: `POST /api/v2/roll/override`.
//!
//! The Python handler chain (`app/api/roll.py:override_roll` ->
//! `RollService.execute_override`) is the behavioral oracle. This module keeps
//! the same wire response (`RollResponse`), the same 404/422/400 error shapes,
//! the owner scope, the per-reader serialization, the duplicate-submit guard
//! from #3467, and the durable decision-time context the recommendation
//! explanation read later projects.
//!
//! Selection eligibility is the same Option E authority the native Roll offer
//! uses (`crate::option_inputs` + `crate::reading_constraints`), so a manual
//! pick can never select a series the dice would refuse.
#![forbid(unsafe_code)]
use crate::{
    auth::AuthenticatedUser,
    db, option_inputs,
    reading_constraints::EligibleFrontier,
    reading_session::{self, SessionPolicy},
    roll_exclusions, ApiError, AppState,
};
use axum::{extract::State, Json};
use chrono::Timelike;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::str::FromStr;
use std::sync::Arc;
use tokio_postgres::IsolationLevel;

/// The Python handler's canonical manual-pick algorithm/control identifiers.
const RECOMMENDATION_ALGORITHM_VERSION: &str = "v1-contextual";
const CONTROL_MODE_CONTEXTUAL: &str = "contextual";

/// Request body for the manual override.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct RollOverrideRequest {
    /// Reader-selected thread identifier.
    pub thread_id: i32,
}

/// Response body: the Python `RollResponse` projection for a manual pick.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct RollResponse {
    pub thread_id: i32,
    pub title: String,
    pub format: String,
    pub issues_remaining: i32,
    pub queue_position: i32,
    pub die_size: i32,
    pub result: i32,
    pub offset: i32,
    pub snoozed_count: i32,
    pub issue_id: Option<i32>,
    pub issue_number: Option<String>,
    pub next_issue_id: Option<i32>,
    pub next_issue_number: Option<String>,
    pub total_issues: Option<i32>,
    pub reading_progress: Option<String>,
    pub explanation: Option<String>,
}

/// The stored thread projection the Python handler reads before the commit.
pub(crate) struct OverrideThread {
    pub(crate) id: i32,
    pub(crate) title: String,
    pub(crate) format: String,
    pub(crate) total_issues: Option<i32>,
    pub(crate) reading_progress: Option<String>,
    pub(crate) status: String,
}

/// Mirror `app.models.thread.normalize_format_value`.
fn normalize_format_value(value: &str) -> String {
    match value.trim().to_lowercase().as_str() {
        "comic" | "comics" => "Comic".to_string(),
        "digital" => "Digital".to_string(),
        _ => value.trim().to_string(),
    }
}

/// Count the unread issues the eligibility snapshot reports for one thread.
fn unread_count(inputs: &option_inputs::OptionInputs, thread_id: i32) -> i32 {
    inputs
        .core
        .issues
        .iter()
        .filter(|issue| issue.thread_id == thread_id)
        .filter(|issue| issue.status != "read")
        .filter(|issue| !inputs.excluded_issue_ids.contains(&issue.id))
        .count() as i32
}

/// Resolve the reader's dense Queue ordinal for one thread.
///
/// Python's `display_position` sorts the whole active queue with the same
/// authority (`blocked` first, then `queue_position`, then `id`) and returns the
/// one-based ordinal, or zero for a thread outside the Queue.
fn display_position(candidates: &[EligibleFrontier], thread_id: i32) -> i32 {
    let mut ordered: Vec<&EligibleFrontier> = candidates
        .iter()
        .filter(|candidate| candidate.queue_position >= 1)
        .collect();
    // Python's "position" sort is (blocked, queue_position, id). An eligible
    // frontier is never blocked, so the dense ordinal reduces to
    // (queue_position, id) among Queue members.
    ordered.sort_by_key(|candidate| (candidate.queue_position, candidate.thread_id));
    ordered
        .iter()
        .position(|candidate| candidate.thread_id == thread_id)
        .map(|index| index as i32 + 1)
        .unwrap_or(0)
}

/// Build the decision-time recommendation context the explanation read consumes.
///
/// The shape matches `build_recommendation_context` for the manual-pick path:
/// an explicit neutral effort estimate, a single unit-weight candidate, balanced
/// bandwidth attributed to the manual override, and the canonical algorithm and
/// control-mode identifiers.
fn build_recommendation_context(
    thread_id: i32,
    issue_id: Option<i32>,
    issue_number: Option<&str>,
) -> Value {
    json!({
        "context_version": 2,
        "selected_candidate": {
            "thread_id": thread_id,
            "issue_id": issue_id,
            "issue_number": issue_number,
            // `compute_effort_estimate` returns the neutral estimate when no
            // classified reading history exists for the candidate.
            "effort_minutes": Value::Null,
            "effort_band": "unknown",
            "effort_source": "unknown",
            "effort_confidence": 0.0,
            "effort_sample_count": 0,
        },
        "candidate_weights": [{
            "candidate_id": thread_id,
            "weight": 1.0,
            "reasons": [],
            "factors": [],
        }],
        "selected_weight": 1.0,
        "bandwidth": "balanced",
        "bandwidth_source": "manual_override",
        "bandwidth_confidence": 1.0,
        "random_bypass": false,
        "balanced_neutrality": true,
        "algorithm_version": RECOMMENDATION_ALGORITHM_VERSION,
        "control_mode": CONTROL_MODE_CONTEXTUAL,
    })
}

/// Build the rolling decision snapshot persisted beside the event.
#[allow(clippy::too_many_arguments)]
fn build_rolling_recommendation_context(
    die_size: i32,
    selected_queue_position: i32,
    bounded_candidate_ids: Vec<i32>,
    selection_method: &str,
    session_timezone: Option<&str>,
    local_hour: Option<i32>,
    selected_thread_last_rating: Option<f64>,
    selected_thread_last_activity_at: Option<&str>,
    effort_estimate: &str,
) -> Value {
    json!({
        "schema_version": 1,
        "algorithm_version": RECOMMENDATION_ALGORITHM_VERSION,
        "control_mode": CONTROL_MODE_CONTEXTUAL,
        "die_size": die_size,
        "selected_queue_position": selected_queue_position,
        "bounded_candidate_ids": bounded_candidate_ids,
        "selected_index": 0,
        "selection_method": selection_method,
        "session_timezone": session_timezone,
        "local_hour": local_hour,
        "selected_thread_last_rating": selected_thread_last_rating,
        "selected_thread_last_activity_at": selected_thread_last_activity_at,
        "effort_estimate": effort_estimate,
    })
}

/// Resolve the session's current local hour, mirroring `_get_local_hour_from_timezone`.
fn local_hour(timezone: Option<&str>) -> Option<i32> {
    let timezone = timezone?;
    let zone = chrono_tz::Tz::from_str(timezone).ok()?;
    Some(chrono::Utc::now().with_timezone(&zone).hour() as i32)
}

/// Read one owned thread for update inside the write transaction.
async fn fetch_thread_for_update(
    tx: &tokio_postgres::Transaction<'_>,
    thread_id: i32,
    user_id: i32,
) -> Result<Option<OverrideThread>, ApiError> {
    let row = tx
        .query_opt(
            "SELECT id, title, format, total_issues,
                    reading_progress, status
             FROM threads
             WHERE id = $1 AND user_id = $2
             FOR UPDATE",
            &[&thread_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    row.map(|row| -> Result<OverrideThread, ApiError> {
        Ok(OverrideThread {
            id: row.try_get(0).map_err(db::query_error)?,
            title: row.try_get(1).map_err(db::query_error)?,
            format: row.try_get(2).map_err(db::query_error)?,
            total_issues: row.try_get(3).map_err(db::query_error)?,
            reading_progress: row.try_get(4).map_err(db::query_error)?,
            status: row.try_get(5).map_err(db::query_error)?,
        })
    })
    .transpose()
}

/// Read the session row the Python handler locks for the manual pick.
async fn fetch_session_state(
    tx: &tokio_postgres::Transaction<'_>,
    session_id: i32,
    user_id: i32,
) -> Result<
    (
        Option<i32>,
        Option<Vec<i32>>,
        Option<Vec<i32>>,
        Option<String>,
    ),
    ApiError,
> {
    let row = tx
        .query_opt(
            // `snoozed_thread_ids`/`skipped_thread_ids` are SQLAlchemy `json`
            // columns, so they are read as text and decoded by
            // `reading_session::decode_thread_ids` (#4850).
            "SELECT pending_thread_id, snoozed_thread_ids::text,
                    skipped_thread_ids::text, timezone
             FROM sessions
             WHERE id = $1 AND user_id = $2
             FOR UPDATE",
            &[&session_id, &user_id],
        )
        .await
        .map_err(db::query_error)?
        .ok_or(ApiError::Conflict(
            "Reading session changed; try again".to_string(),
        ))?;
    let snoozed: Option<String> = row.try_get(1).map_err(db::query_error)?;
    let skipped: Option<String> = row.try_get(2).map_err(db::query_error)?;
    Ok((
        row.try_get(0).map_err(db::query_error)?,
        reading_session::decode_thread_ids(snoozed)?,
        reading_session::decode_thread_ids(skipped)?,
        row.try_get(3).map_err(db::query_error)?,
    ))
}

/// The trailing session event the duplicate-submit guard inspects.
struct LatestEvent {
    event_type: String,
    selection_method: Option<String>,
    selected_thread_id: Option<i32>,
}

async fn fetch_latest_session_event(
    tx: &tokio_postgres::Transaction<'_>,
    session_id: i32,
) -> Result<Option<LatestEvent>, ApiError> {
    let row = tx
        .query_opt(
            "SELECT type, selection_method, selected_thread_id
             FROM events
             WHERE session_id = $1
             ORDER BY timestamp DESC, id DESC
             LIMIT 1",
            &[&session_id],
        )
        .await
        .map_err(db::query_error)?;
    row.map(|row| -> Result<LatestEvent, ApiError> {
        Ok(LatestEvent {
            event_type: row.try_get(0).map_err(db::query_error)?,
            selection_method: row.try_get(1).map_err(db::query_error)?,
            selected_thread_id: row.try_get(2).map_err(db::query_error)?,
        })
    })
    .transpose()
}

/// Text-first cast helper: `context` binds as text, so `$n::text::json` keeps
/// the wire type text and lets PostgreSQL perform the JSON cast server-side.
const OVERRIDE_EVENT_INSERT: &str = "INSERT INTO events
   (type,user_id,session_id,selected_thread_id,die,result,issue_id,
    issue_number,selection_method,recommendation_reason_codes,
    recommendation_context,rolling_recommendation_context,timestamp)
 VALUES ('roll',$1,$2,$3,$4,0,$5,$6,'override',$7::text[],
         $8::text::json,$9::text::json,NOW())
 RETURNING id";

/// Persist the override event, its recommendation context row, and the session
/// pointer in one transaction. Extracted so the real write path can be
/// exercised against disposable PostgreSQL.
#[allow(clippy::too_many_arguments)]
pub(crate) async fn persist_override_roll(
    tx: &tokio_postgres::Transaction<'_>,
    user: AuthenticatedUser,
    session_id: i32,
    thread: &OverrideThread,
    issue_id: Option<i32>,
    issue_number: Option<&str>,
    die: i32,
    queue_position: i32,
    bounded_candidate_ids: Vec<i32>,
    timezone: Option<&str>,
    last_rating: Option<f64>,
    last_activity_at: Option<&str>,
    effort_estimate: &str,
) -> Result<i32, ApiError> {
    let recommendation_context = build_recommendation_context(thread.id, issue_id, issue_number);
    let rolling_context = build_rolling_recommendation_context(
        die,
        queue_position,
        bounded_candidate_ids,
        "override",
        timezone,
        local_hour(timezone),
        last_rating,
        last_activity_at,
        effort_estimate,
    );
    let empty_reasons: Vec<String> = Vec::new();
    let row = tx
        .query_one(
            OVERRIDE_EVENT_INSERT,
            &[
                &user.id(),
                &session_id,
                &thread.id,
                &die,
                &issue_id,
                &issue_number,
                &empty_reasons,
                &recommendation_context.to_string(),
                &rolling_context.to_string(),
            ],
        )
        .await
        .map_err(db::query_error)?;
    let event_id: i32 = row.get(0);

    tx.execute(
        // `created_at` is NOT NULL without a server default, so the writer
        // supplies it the same way the SQLAlchemy model default does.
        "INSERT INTO recommendation_contexts
           (event_id,schema_version,created_at,intent,intent_source,intent_confidence,
            bandwidth,bandwidth_source,bandwidth_confidence,candidate_factors,
            final_weight,effort_minutes,effort_band,effort_source,
            effort_confidence,effort_sample_count,random_bypass,balanced_neutrality)
         VALUES ($1,2,NOW(),'balanced','manual_override',1.0,
                 'balanced','manual_override',1.0,NULL,
                 1.0,NULL,'unknown','unknown',
                 0.0,0,false,true)",
        &[&event_id],
    )
    .await
    .map_err(db::query_error)?;

    let updated = tx
        .execute(
            "UPDATE sessions
             SET pending_thread_id=$1,pending_thread_updated_at=NOW()
             WHERE id=$2 AND user_id=$3",
            &[&thread.id, &session_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if updated != 1 {
        return Err(ApiError::Conflict(
            "Reading session changed; try again".to_string(),
        ));
    }
    Ok(event_id)
}

/// Response the Python handler returns for both the fresh and duplicate path.
#[allow(clippy::too_many_arguments)]
fn response(
    thread: &OverrideThread,
    issues_remaining: i32,
    queue_position: i32,
    die: i32,
    snoozed_count: i32,
    issue_id: Option<i32>,
    issue_number: Option<String>,
) -> RollResponse {
    RollResponse {
        thread_id: thread.id,
        title: thread.title.clone(),
        format: normalize_format_value(&thread.format),
        issues_remaining,
        queue_position,
        die_size: die,
        result: 0,
        offset: snoozed_count,
        snoozed_count,
        issue_id,
        next_issue_id: issue_id,
        issue_number: issue_number.clone(),
        next_issue_number: issue_number,
        total_issues: thread.total_issues,
        reading_progress: thread.reading_progress.clone(),
        // The Python handler passes no reason codes, so the primary explanation
        // is always absent for a manual pick.
        explanation: None,
    }
}

/// Manual Roll pick for the authenticated reader.
pub async fn override_roll(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<RollOverrideRequest>,
) -> Result<Json<RollResponse>, ApiError> {
    let active = reading_session::bootstrap(&state, user, None, SessionPolicy::default()).await?;
    // Read-only Option E snapshot before the write connection so this request
    // never nests two pool checkouts.
    let validated = option_inputs::load_option_inputs_contained(&state, user).await?;
    let candidates = validated.eligible_frontiers().map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        ApiError::Internal("Invalid reading constraints".to_string())
    })?;

    let mut pending = crate::dice_api::Pending::new(db::checkout(&state).await?);
    let tx = pending
        .connection()
        .build_transaction()
        .isolation_level(IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    // The write transaction's first statement is the per-reader advisory lock,
    // matching every other native Roll writer.
    tx.query_one(
        "SELECT pg_advisory_xact_lock($1::bigint)",
        &[&(user.id() as i64)],
    )
    .await
    .map_err(db::query_error)?;

    let thread = fetch_thread_for_update(&tx, request.thread_id, user.id()).await?;
    let thread = match thread {
        Some(thread) => thread,
        None => {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(ApiError::NotFound("That series was not found".to_string()));
        }
    };

    // The same eligibility authority the dice pool uses decides whether a
    // manual pick is selectable. When live eligibility exists it is authoritative,
    // so a stale `threads.is_blocked` flag must not reject a selectable frontier
    // (Python: `thread_id not in eligibility.candidate_ids()`).
    let frontier = candidates
        .iter()
        .find(|candidate| candidate.thread_id == thread.id);
    let frontier = match frontier {
        Some(frontier) => *frontier,
        None => {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(ApiError::Unprocessable(format!(
                "\"{}\" is blocked and cannot be selected",
                thread.title
            )));
        }
    };

    if thread.status != "active" {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::Unprocessable(format!(
            "\"{}\" is {} and cannot be selected",
            thread.title, thread.status
        )));
    }

    let issue_number = validated
        .inputs()
        .core
        .issues
        .iter()
        .find(|issue| issue.id == frontier.issue_id)
        .map(|issue| issue.issue_number.clone());
    let issues_remaining = unread_count(validated.inputs(), thread.id);
    let queue_position = display_position(&candidates, thread.id);
    let (pending_thread_id, snoozed, skipped, timezone) =
        fetch_session_state(&tx, active.session.id, user.id()).await?;
    let snoozed_ids: Vec<i32> = snoozed.unwrap_or_default();

    if skipped.is_some_and(|ids| ids.contains(&thread.id)) {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::BadRequest(
            "Unskip this Thread before selecting it".to_string(),
        ));
    }

    // A thread only on durable cross-session snooze backoff stays excluded,
    // while a series surfaced by the current session's picker may be picked
    // without clearing its session snooze (#3446).
    let derived_snoozed = roll_exclusions::durable_snoozed(&tx, user.id()).await?;
    if derived_snoozed.contains(&thread.id) && !snoozed_ids.contains(&thread.id) {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError::BadRequest(format!(
            "\"{}\" is on session-based snooze backoff and cannot be overridden yet.",
            thread.title
        )));
    }

    // #3467: a double-clicked pick must log exactly one roll event. Both the
    // live session pointer and the trailing override event must agree.
    let latest = fetch_latest_session_event(&tx, active.session.id).await?;
    let is_duplicate_override = pending_thread_id == Some(thread.id)
        && latest.is_some_and(|event| {
            event.event_type == "roll"
                && event.selection_method.as_deref() == Some("override")
                && event.selected_thread_id == Some(thread.id)
        });
    if is_duplicate_override {
        tx.rollback().await.map_err(db::query_error)?;
        pending.release();
        return Ok(Json(response(
            &thread,
            issues_remaining,
            queue_position,
            active.current_die,
            snoozed_ids.len() as i32,
            Some(frontier.issue_id),
            issue_number,
        )));
    }

    let last_rating = tx
        .query_opt(
            "SELECT last_rating, last_activity_at::text
             FROM threads WHERE id = $1 AND user_id = $2",
            &[&thread.id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .map(|row| -> Result<(Option<f64>, Option<String>), ApiError> {
            Ok((
                row.try_get(0).map_err(db::query_error)?,
                row.try_get(1).map_err(db::query_error)?,
            ))
        })
        .transpose()?
        .unwrap_or((None, None));

    persist_override_roll(
        &tx,
        user,
        active.session.id,
        &thread,
        Some(frontier.issue_id),
        issue_number.as_deref(),
        active.current_die,
        queue_position,
        vec![thread.id],
        timezone.as_deref(),
        last_rating.0,
        last_rating.1.as_deref(),
        "unknown",
    )
    .await?;
    tx.commit().await.map_err(db::query_error)?;
    pending.release();

    Ok(Json(response(
        &thread,
        issues_remaining,
        queue_position,
        active.current_die,
        snoozed_ids.len() as i32,
        Some(frontier.issue_id),
        issue_number,
    )))
}

/// Documentation-only operation for the mounted v2 manual pick.
#[utoipa::path(
    post,
    path = "/api/v2/roll/override",
    tag = "roll",
    request_body = RollOverrideRequest,
    responses(
        (status = 200, description = "Manually selected thread", body = RollResponse),
        (status = 400, description = "Thread is skipped or on snooze backoff"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Thread was not found for this reader"),
        (status = 422, description = "Thread is blocked or not active")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn override_roll_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;

    fn thread(id: i32) -> OverrideThread {
        OverrideThread {
            id,
            title: format!("Series {id}"),
            format: "Comic".into(),
            total_issues: Some(10),
            reading_progress: Some("in_progress".into()),
            status: "active".into(),
        }
    }

    #[test]
    fn format_normalization_matches_python() {
        assert_eq!(normalize_format_value("Comic"), "Comic");
        assert_eq!(normalize_format_value("comics"), "Comic");
        assert_eq!(normalize_format_value("  Digital "), "Digital");
        assert_eq!(normalize_format_value("Graphic Novel"), "Graphic Novel");
    }

    #[test]
    fn recommendation_context_keeps_the_python_manual_pick_shape() {
        let context = build_recommendation_context(7, Some(70), Some("3"));
        assert_eq!(context["context_version"], 2);
        assert_eq!(context["selected_candidate"]["thread_id"], 7);
        assert_eq!(context["selected_candidate"]["issue_number"], "3");
        assert_eq!(context["selected_candidate"]["effort_band"], "unknown");
        assert_eq!(context["bandwidth"], "balanced");
        assert_eq!(context["bandwidth_source"], "manual_override");
        assert_eq!(context["random_bypass"], false);
        assert_eq!(context["balanced_neutrality"], true);
        assert_eq!(context["algorithm_version"], "v1-contextual");
        assert_eq!(context["control_mode"], "contextual");
        assert_eq!(context["candidate_weights"][0]["weight"], 1.0);
    }

    #[test]
    fn rolling_context_records_the_manual_pick_decision() {
        let rolling = build_rolling_recommendation_context(
            8,
            2,
            vec![7],
            "override",
            Some("America/Chicago"),
            Some(9),
            Some(4.5),
            Some("2026-11-16T10:00:00+00:00"),
            "unknown",
        );
        assert_eq!(rolling["schema_version"], 1);
        assert_eq!(rolling["die_size"], 8);
        assert_eq!(rolling["selected_queue_position"], 2);
        assert_eq!(rolling["selection_method"], "override");
        assert_eq!(rolling["selected_index"], 0);
        assert_eq!(rolling["bounded_candidate_ids"][0], 7);
    }

    #[test]
    fn display_position_is_the_dense_queue_ordinal() {
        let candidates = vec![
            EligibleFrontier {
                thread_id: 10,
                issue_id: 100,
                queue_position: 2,
            },
            EligibleFrontier {
                thread_id: 20,
                issue_id: 200,
                queue_position: 1,
            },
            EligibleFrontier {
                thread_id: 30,
                issue_id: 300,
                queue_position: 0,
            },
        ];
        assert_eq!(display_position(&candidates, 20), 1);
        assert_eq!(display_position(&candidates, 10), 2);
        // Outside the Queue keeps the Python zero ordinal.
        assert_eq!(display_position(&candidates, 30), 0);
        assert_eq!(display_position(&candidates, 999), 0);
    }

    #[test]
    fn response_projects_the_python_roll_response_fields() {
        let body = response(&thread(7), 3, 2, 8, 1, Some(70), Some("3".into()));
        assert_eq!(body.thread_id, 7);
        assert_eq!(body.format, "Comic");
        assert_eq!(body.die_size, 8);
        assert_eq!(body.result, 0);
        assert_eq!(body.offset, 1);
        assert_eq!(body.snoozed_count, 1);
        assert_eq!(body.next_issue_id, Some(70));
        assert_eq!(body.explanation, None);
    }

    #[tokio::test]
    async fn override_requires_authentication_before_database_access() {
        let config = crate::config::Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        })
        .unwrap();
        let app = crate::router(Arc::new(AppState::new(config).unwrap()));
        use axum::body::Body;
        use axum::http::{Request, StatusCode};
        use tower::ServiceExt;
        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v2/roll/override")
                    .header("content-type", "application/json")
                    .header("cookie", "csrf_token=synthetic-test-csrf")
                    .header("x-csrf-token", "synthetic-test-csrf")
                    .body(Body::from(r#"{"thread_id":7}"#))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }

    /// Seed the canonical schema and return a client plus the reset guard.
    async fn seeded(
        statements: &str,
    ) -> (tokio_postgres::Client, tokio::sync::MutexGuard<'static, ()>) {
        let url = crate::test_support::database_url().await;
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let guard = crate::test_support::reset_for_test(&state).await;
        let (client, connection) = tokio_postgres::connect(&url, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        client
            .batch_execute(statements)
            .await
            .expect("seed canonical schema");
        (client, guard)
    }

    #[tokio::test]
    async fn fetch_session_state_reads_the_canonical_json_snooze_columns() {
        // Regression: the canonical Alembic schema types `snoozed_thread_ids`
        // and `skipped_thread_ids` as `json` (#4850). A direct
        // `try_get::<Option<Vec<i32>>>` on those columns is a client-side type
        // mismatch that mapped to a 500 for every authenticated manual pick.
        let _admin = crate::test_support::required_test_admin_url();
        let (mut client, _db) = seeded(
            r#"INSERT INTO users (id, username) VALUES (1, 'reader-1');
                 INSERT INTO threads
                     (id, user_id, title, format, issues_remaining, status, queue_position)
                 VALUES (10, 1, 'Pending', 'Comic', 1, 'active', 1);
                 INSERT INTO sessions
                     (id, user_id, started_at, start_die, pending_thread_id,
                      snoozed_thread_ids, skipped_thread_ids, timezone)
                 VALUES (1, 1, NOW(), 8, 10, '[5]'::json, '[6]'::json,
                         'America/Chicago');"#,
        )
        .await;
        let tx = client.transaction().await.unwrap();
        let (pending, snoozed, skipped, timezone) = fetch_session_state(&tx, 1, 1)
            .await
            .expect("canonical session read");
        tx.rollback().await.unwrap();
        assert_eq!(pending, Some(10));
        assert_eq!(snoozed, Some(vec![5]));
        assert_eq!(skipped, Some(vec![6]));
        assert_eq!(timezone.as_deref(), Some("America/Chicago"));

        // A session without any snooze/skip rows keeps the Python `None` shape.
        client
            .batch_execute(
                r#"INSERT INTO sessions
                       (id, user_id, started_at, start_die)
                   VALUES (2, 1, NOW(), 8);"#,
            )
            .await
            .unwrap();
        let tx = client.transaction().await.unwrap();
        let (pending, snoozed, skipped, timezone) = fetch_session_state(&tx, 2, 1)
            .await
            .expect("empty session read");
        tx.rollback().await.unwrap();
        assert_eq!(pending, None);
        assert_eq!(snoozed, None);
        assert_eq!(skipped, None);
        assert_eq!(timezone, None);
    }

    #[tokio::test]
    async fn persist_override_writes_the_event_context_and_session_pointer() {
        let _admin = crate::test_support::required_test_admin_url();
        let (mut client, _db) = seeded(
            r#"INSERT INTO users (id, username) VALUES (1, 'reader-1');
                 INSERT INTO threads
                     (id, user_id, title, format, issues_remaining, status, queue_position,
                      total_issues, reading_progress)
                 VALUES (10, 1, 'First', 'Comic', 2, 'active', 1, 4, 'in_progress');
                 INSERT INTO issues
                     (id, thread_id, issue_number, status, created_at, position)
                 VALUES (100, 10, '1', 'unread', now(), 1),
                        (101, 10, '2', 'unread', now(), 2);
                 INSERT INTO sessions
                     (id, user_id, started_at, start_die, pending_thread_id)
                 VALUES (1, 1, NOW(), 8, NULL);"#,
        )
        .await;
        let user = AuthenticatedUser::for_test(1);
        let owned = OverrideThread {
            id: 10,
            title: "First".into(),
            format: "Comic".into(),
            total_issues: Some(4),
            reading_progress: Some("in_progress".into()),
            status: "active".into(),
        };

        let tx = client.transaction().await.unwrap();
        let event_id = persist_override_roll(
            &tx,
            user,
            1,
            &owned,
            Some(100),
            Some("1"),
            8,
            1,
            vec![10],
            Some("America/Chicago"),
            None,
            None,
            "unknown",
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();

        let event = client
            .query_one(
                "SELECT type,user_id,session_id,selected_thread_id,die,result,
                        issue_id,issue_number,selection_method,
                        recommendation_context->>'bandwidth_source',
                        rolling_recommendation_context->>'selection_method'
                 FROM events WHERE id=$1",
                &[&event_id],
            )
            .await
            .unwrap();
        assert_eq!(event.get::<_, String>(0), "roll");
        assert_eq!(event.get::<_, i32>(1), 1);
        assert_eq!(event.get::<_, i32>(2), 1);
        assert_eq!(event.get::<_, i32>(3), 10);
        assert_eq!(event.get::<_, i32>(4), 8);
        assert_eq!(event.get::<_, i32>(5), 0);
        assert_eq!(event.get::<_, i32>(6), 100);
        assert_eq!(event.get::<_, Option<String>>(7).as_deref(), Some("1"));
        assert_eq!(event.get::<_, String>(8), "override");
        assert_eq!(
            event.get::<_, Option<String>>(9).as_deref(),
            Some("manual_override")
        );
        assert_eq!(
            event.get::<_, Option<String>>(10).as_deref(),
            Some("override")
        );

        let context = client
            .query_one(
                "SELECT schema_version,intent,intent_source,bandwidth,bandwidth_source,
                        final_weight,random_bypass,balanced_neutrality
                 FROM recommendation_contexts WHERE event_id=$1",
                &[&event_id],
            )
            .await
            .unwrap();
        assert_eq!(context.get::<_, i32>(0), 2);
        assert_eq!(context.get::<_, String>(1), "balanced");
        assert_eq!(context.get::<_, String>(2), "manual_override");
        assert_eq!(context.get::<_, String>(3), "balanced");
        assert_eq!(context.get::<_, String>(4), "manual_override");
        assert_eq!(context.get::<_, f64>(5), 1.0);
        assert!(!context.get::<_, bool>(6));
        assert!(context.get::<_, bool>(7));

        let session = client
            .query_one(
                "SELECT pending_thread_id, pending_thread_updated_at IS NOT NULL
                 FROM sessions WHERE id=1",
                &[],
            )
            .await
            .unwrap();
        assert_eq!(session.get::<_, Option<i32>>(0), Some(10));
        assert!(session.get::<_, bool>(1));
    }

    #[tokio::test]
    async fn persist_override_binds_an_empty_reason_code_array() {
        let _admin = crate::test_support::required_test_admin_url();
        let (mut client, _db) = seeded(
            r#"INSERT INTO users (id, username) VALUES (1, 'reader-1');
                 INSERT INTO threads
                     (id, user_id, title, format, issues_remaining, status, queue_position)
                 VALUES (10, 1, 'First', 'Comic', 1, 'active', 1);
                 INSERT INTO sessions
                     (id, user_id, started_at, start_die)
                 VALUES (1, 1, NOW(), 6);"#,
        )
        .await;
        let user = AuthenticatedUser::for_test(1);
        let owned = OverrideThread {
            id: 10,
            title: "First".into(),
            format: "Comic".into(),
            total_issues: None,
            reading_progress: None,
            status: "active".into(),
        };
        let tx = client.transaction().await.unwrap();
        let event_id = persist_override_roll(
            &tx,
            user,
            1,
            &owned,
            None,
            None,
            6,
            1,
            vec![10],
            None,
            None,
            None,
            "unknown",
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        let codes = client
            .query_one(
                "SELECT recommendation_reason_codes FROM events WHERE id=$1",
                &[&event_id],
            )
            .await
            .unwrap();
        let codes: Vec<String> = codes.get(0);
        assert!(codes.is_empty());
        let context = client
            .query_one(
                "SELECT recommendation_context->'selected_candidate'->>'issue_id'
                 FROM events WHERE id=$1",
                &[&event_id],
            )
            .await
            .unwrap();
        assert_eq!(context.get::<_, Option<String>>(0), None);
    }
}
