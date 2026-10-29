//! V2 bootstrap endpoint implementation matching Python contract.

use axum::{
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Json, Response},
};
use deadpool_postgres::{Pool, Row};
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgRow;
use std::sync::Arc;
use tracing::{error, info, warn};

use crate::auth::{authenticate_request, AuthUser};
use crate::schemas::{RollV2BootstrapResponse, RollableItem, RollableRoute};

/// V2 bootstrap request body (currently empty, reserved for future extensions).
#[derive(Deserialize)]
pub struct BootstrapRequest {}

/// V2 bootstrap response body.
#[derive(Serialize)]
pub struct BootstrapResponse {
    pub response: RollV2BootstrapResponse,
    pub tracing: Option<String>,
}

/// Extract timezone from request header.
fn extract_timezone(header: &str) -> Option<String> {
    let header = header.trim();
    if header.is_empty() {
        return None;
    }
    // Validate timezone format (basic check for IANA timezone)
    if header.len() > 100 {
        return None;
    }
    Some(header.to_string())
}

/// Build session bandwidth state from config.
fn build_bandwidth_state(
    predicted: &str,
    active: &str,
    confidence: f64,
    source: &str,
    version: &str,
) -> crate::schemas::SessionBandwidthState {
    crate::schemas::SessionBandwidthState {
        predicted_bandwidth: predicted.to_string(),
        active_bandwidth: active.to_string(),
        confidence,
        source: source.to_string(),
        mode_version: version.to_string(),
    }
}

/// Build session mode state.
fn build_session_mode(
    active_bandwidth: &str,
    predicted_bandwidth: &str,
    bandwidth_confidence: f64,
    bandwidth_source: &str,
    bandwidth_version: &str,
    active_intent: &str,
    predicted_intent: &str,
    intent_confidence: f64,
    intent_source: &str,
    intent_version: &str,
    correction_guidance: Option<&str>,
) -> crate::schemas::SessionMode {
    crate::schemas::SessionMode {
        active_bandwidth: active_bandwidth.to_string(),
        predicted_bandwidth: predicted_bandwidth.to_string(),
        bandwidth_confidence,
        bandwidth_source: bandwidth_source.to_string(),
        bandwidth_version: bandwidth_version.to_string(),
        active_intent: active_intent.to_string(),
        predicted_intent: predicted_intent.to_string(),
        intent_confidence,
        intent_source: intent_source.to_string(),
        intent_version: intent_version.to_string(),
        session_mode_correction_guidance: correction_guidance.map(|s| s.to_string()),
    }
}

/// Build active thread info.
fn build_active_thread(
    id: i64,
    title: &str,
    format: &str,
    last_rolled_result: Option<i32>,
) -> crate::schemas::ActiveThreadInfo {
    crate::schemas::ActiveThreadInfo {
        id,
        title: title.to_string(),
        format: format.to_string(),
        last_rolled_result,
    }
}

/// Build roll recovery info.
fn build_roll_recovery(
    pending_thread_id: Option<i64>,
    pending_thread_title: Option<&str>,
    excluded_thread_ids: Vec<i64>,
) -> crate::schemas::RollRecoveryInfo {
    crate::schemas::RollRecoveryInfo {
        pending_thread_id,
        pending_thread_title: pending_thread_title.map(|s| s.to_string()),
        excluded_thread_ids,
    }
}

/// Build rollable thread.
fn build_rollable_thread(
    id: i64,
    title: &str,
    format: &str,
    last_activity_at: Option<&str>,
) -> crate::schemas::RollableThread {
    crate::schemas::RollableThread::new(
        id,
        title.to_string(),
        format.to_string(),
        last_activity_at.map(|s| s.to_string()),
    )
}

/// Build rollable item.
fn build_rollable_item(
    thread: crate::schemas::RollableThread,
    issue: crate::schemas::RollableIssue,
    identity: crate::schemas::RollableIdentity,
    reader: crate::schemas::RollableReader,
    routes: Vec<crate::schemas::RollableRoute>,
    overflow_routes_count: i32,
) -> crate::schemas::RollableItem {
    crate::schemas::RollableItem::new(thread, issue, identity, reader, routes, overflow_routes_count)
}

/// Build roll last read info.
fn build_roll_last_read(
    issue_id: Option<i64>,
    issue_number: Option<&str>,
    thread_id: Option<i64>,
    thread_title: Option<&str>,
    read_at: Option<&str>,
) -> crate::schemas::RollLastRead {
    crate::schemas::RollLastRead::new(
        issue_id,
        issue_number.map(|s| s.to_string()),
        thread_id,
        thread_title.map(|s| s.to_string()),
        read_at.map(|s| s.to_string()),
    )
}

/// Fetch current session for user.
async fn fetch_session(
    pool: &Pool,
    user_id: i64,
) -> Result<Row, String> {
    let row = sqlx::query(
        r#"
        SELECT
            id,
            start_die,
            manual_die,
            timezone,
            active_bandwidth,
            bandwidth_confidence,
            bandwidth_source,
            bandwidth_version,
            active_intent,
            intent_confidence,
            intent_source,
            intent_version,
            session_mode_correction_guidance,
            pending_thread_id,
            snoozed_thread_ids,
            skipped_thread_ids
        FROM reading_sessions
        WHERE user_id = $1 AND ended_at IS NULL
        ORDER BY started_at DESC
        LIMIT 1
        "#,
    )
    .bind(user_id)
    .fetch_one(pool)
    .await
    .map_err(|e| format!("Failed to fetch session: {}", e))?;

    Ok(row)
}

/// Fetch current die size for session.
async fn fetch_current_die(
    pool: &Pool,
    session_id: i64,
) -> Result<i32, String> {
    let row = sqlx::query(
        r#"
        SELECT
            CASE
                WHEN manual_die IS NOT NULL THEN manual_die
                ELSE start_die
            END as die_size
        FROM reading_sessions
        WHERE id = $1
        "#,
    )
    .bind(session_id)
    .fetch_one(pool)
    .await
    .map_err(|e| format!("Failed to fetch current die: {}", e))?;

    let die_size: i32 = row.get("die_size");
    Ok(die_size)
}

/// Fetch active thread for session.
async fn fetch_active_thread(
    pool: &Pool,
    session_id: i64,
) -> Result<Option<Row>, String> {
    let row = sqlx::query(
        r#"
        SELECT
            t.id,
            t.title,
            t.format,
            t.last_rolled_result
        FROM reading_sessions rs
        JOIN threads t ON rs.pending_thread_id = t.id
        WHERE rs.id = $1
        "#,
    )
    .bind(session_id)
    .fetch_optional(pool)
    .await
    .map_err(|e| format!("Failed to fetch active thread: {}", e))?;

    Ok(row)
}

/// Fetch rollable candidates (bounded by die size).
async fn fetch_rollable_candidates(
    pool: &Pool,
    user_id: i64,
    die_size: i32,
    excluded_thread_ids: Vec<i64>,
) -> Result<Vec<Row>, String> {
    let excluded_list = if excluded_thread_ids.is_empty() {
        String::new()
    } else {
        format!(" AND t.id NOT IN ({})", excluded_thread_ids.join(", "))
    };

    let rows = sqlx::query(
        r#"
        SELECT
            t.id,
            t.title,
            t.format,
            t.last_activity_at,
            i.id as issue_id,
            i.issue_number,
            i.status as issue_status,
            ARRAY(
                SELECT DISTINCT dg.name
                FROM dependency_group_memberships dgm
                JOIN dependency_groups dg ON dgm.group_id = dg.id
                WHERE dgm.thread_id = t.id
                LIMIT 3
            ) as route_labels
        FROM threads t
        LEFT JOIN issues i ON i.thread_id = t.id AND i.status = 'unread'
        WHERE t.user_id = $1
          AND t.status = 'active'
          AND t.queue_position >= 1
          AND t.id NOT IN (
              SELECT thread_id FROM reading_sessions
              WHERE user_id = $1 AND ended_at IS NULL
              AND pending_thread_id = t.id
          )
          $2
        ORDER BY t.queue_position, t.id
        LIMIT $3
        "#,
    )
    .bind(user_id)
    .bind(&excluded_list)
    .bind(die_size)
    .fetch_all(pool)
    .await
    .map_err(|e| format!("Failed to fetch rollable candidates: {}", e))?;

    Ok(rows)
}

/// Fetch snoozed threads.
async fn fetch_snoozed_threads(
    pool: &Pool,
    user_id: i64,
    limit: usize,
) -> Result<Vec<Row>, String> {
    let rows = sqlx::query(
        r#"
        SELECT
            id,
            title,
            format,
            last_activity_at
        FROM threads
        WHERE user_id = $1 AND status = 'snoozed'
        ORDER BY updated_at DESC
        LIMIT $2
        "#,
    )
    .bind(user_id)
    .bind(limit as i32)
    .fetch_all(pool)
    .await
    .map_err(|e| format!("Failed to fetch snoozed threads: {}", e))?;

    Ok(rows)
}

/// Fetch skipped thread IDs.
async fn fetch_skipped_thread_ids(
    pool: &Pool,
    session_id: i64,
) -> Result<Vec<i64>, String> {
    let row = sqlx::query(
        r#"
        SELECT skipped_thread_ids
        FROM reading_sessions
        WHERE id = $1
        "#,
    )
    .bind(session_id)
    .fetch_one(pool)
    .await
    .map_err(|e| format!("Failed to fetch skipped thread IDs: {}", e))?;

    let skipped_ids: Vec<i64> = row.get("skipped_thread_ids");
    Ok(skipped_ids)
}

/// Fetch blocked thread count.
async fn fetch_blocked_count(
    pool: &Pool,
    user_id: i64,
) -> Result<i32, String> {
    let row = sqlx::query(
        r#"
        SELECT COUNT(*) as count
        FROM threads
        WHERE user_id = $1 AND status = 'blocked'
        "#,
    )
    .bind(user_id)
    .fetch_one(pool)
    .await
    .map_err(|e| format!("Failed to fetch blocked count: {}", e))?;

    let count: i32 = row.get("count");
    Ok(count)
}

/// Fetch stale thread count.
async fn fetch_stale_thread_count(
    pool: &Pool,
    user_id: i64,
) -> Result<i32, String> {
    let row = sqlx::query(
        r#"
        SELECT COUNT(*) as count
        FROM threads
        WHERE user_id = $1 AND status = 'stale'
        "#,
    )
    .bind(user_id)
    .fetch_one(pool)
    .await
    .map_err(|e| format!("Failed to fetch stale thread count: {}", e))?;

    let count: i32 = row.get("count");
    Ok(count)
}

/// Fetch latest rate event in session (last read).
async fn fetch_last_read(
    pool: &Pool,
    session_id: i64,
) -> Result<Option<Row>, String> {
    let row = sqlx::query(
        r#"
        SELECT
            e.issue_id,
            COALESCE(i.issue_number, e.issue_number) as issue_number,
            e.thread_id,
            t.title as thread_title,
            e.timestamp
        FROM events e
        LEFT JOIN issues i ON e.issue_id = i.id
        LEFT JOIN threads t ON e.thread_id = t.id AND t.user_id = e.session_id
        WHERE e.session_id = $1
          AND e.type = 'rate'
        ORDER BY e.timestamp DESC, e.id DESC
        LIMIT 1
        "#,
    )
    .bind(session_id)
    .fetch_optional(pool)
    .await
    .map_err(|e| format!("Failed to fetch last read: {}", e))?;

    Ok(row)
}

/// Main bootstrap endpoint handler.
pub async fn bootstrap_v2(
    state: State<Arc<AppState>>,
    auth_header: String,
) -> Result<Json<BootstrapResponse>, Response> {
    // Authenticate user
    let auth_user = match authenticate_request(&auth_header, &state.jwt_secret).await {
        Ok(user) => user,
        Err(_) => {
            return (
                StatusCode::UNAUTHORIZED,
                Json(serde_json::json!({
                    "detail": "Unauthorized"
                })),
            )
            .into_response();
        }
    };

    let user_id = auth_user.user_id;

    // Fetch current session
    let session_row = match fetch_session(&state.pool, user_id).await {
        Ok(row) => row,
        Err(e) => {
            error!("Failed to fetch session for user {}: {}", user_id, e);
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "detail": format!("Internal server error: {}", e)
                })),
            )
            .into_response();
        }
    };

    let session_id: i64 = session_row.get("id");
    let start_die: i32 = session_row.get("start_die");
    let manual_die: Option<i32> = session_row.get("manual_die");
    let timezone: Option<String> = session_row.get("timezone");
    let active_bandwidth: String = session_row.get("active_bandwidth");
    let bandwidth_confidence: f64 = session_row.get("bandwidth_confidence");
    let bandwidth_source: String = session_row.get("bandwidth_source");
    let bandwidth_version: String = session_row.get("bandwidth_version");
    let active_intent: String = session_row.get("active_intent");
    let intent_confidence: f64 = session_row.get("intent_confidence");
    let intent_source: String = session_row.get("intent_source");
    let intent_version: String = session_row.get("intent_version");
    let correction_guidance: Option<String> = session_row.get("session_mode_correction_guidance");
    let pending_thread_id: Option<i64> = session_row.get("pending_thread_id");

    // Fetch current die size
    let current_die = match fetch_current_die(&state.pool, session_id).await {
        Ok(die) => die,
        Err(e) => {
            error!("Failed to fetch current die for session {}: {}", session_id, e);
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "detail": format!("Internal server error: {}", e)
                })),
            )
            .into_response();
        }
    };

    // Fetch active thread
    let active_thread_row = match fetch_active_thread(&state.pool, session_id).await {
        Ok(row) => row,
        Err(e) => {
            error!("Failed to fetch active thread for session {}: {}", session_id, e);
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "detail": format!("Internal server error: {}", e)
                })),
            )
            .into_response();
        }
    };

    let active_thread = match active_thread_row {
        Some(row) => {
            let id: i64 = row.get("id");
            let title: String = row.get("title");
            let format: String = row.get("format");
            let last_rolled_result: Option<i32> = row.get("last_rolled_result");
            Some(build_active_thread(id, &title, &format, last_rolled_result))
        }
        None => None,
    };

    // Fetch rollable candidates
    let skipped_thread_ids = match fetch_skipped_thread_ids(&state.pool, session_id).await {
        Ok(ids) => ids,
        Err(e) => {
            warn!("Failed to fetch skipped thread IDs for session {}: {}", session_id, e);
            Vec::new()
        }
    };

    let rollable_rows = match fetch_rollable_candidates(
        &state.pool,
        user_id,
        current_die,
        skipped_thread_ids.clone(),
    )
    .await
    {
        Ok(rows) => rows,
        Err(e) => {
            error!("Failed to fetch rollable candidates for user {}: {}", user_id, e);
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "detail": format!("Internal server error: {}", e)
                })),
            )
            .into_response();
        }
    };

    // Build rollable items
    let mut rollable_items: Vec<crate::schemas::RollableItem> = Vec::new();
    for row in &rollable_rows {
        let id: i64 = row.get("id");
        let title: String = row.get("title");
        let format: String = row.get("format");
        let last_activity_at: Option<String> = row.get("last_activity_at");
        let issue_id: Option<i64> = row.get("issue_id");
        let issue_number: Option<String> = row.get("issue_number");
        let issue_status: Option<String> = row.get("issue_status");
        let route_labels: Option<Vec<String>> = row.get("route_labels");

        let thread = build_rollable_thread(id, &title, &format, last_activity_at.as_deref());

        let issue = crate::schemas::RollableIssue {
            id: issue_id,
            number: issue_number,
            canonical_series_title: None, // TODO: Fetch from mappings
            cover_url: None, // TODO: Fetch from mappings
        };

        let identity = crate::schemas::RollableIdentity {
            source: "unavailable".to_string(),
            canonical_series_id: None,
            state: "candidate".to_string(),
            series_mapping_state: "unresolved".to_string(),
        };

        let reader = crate::schemas::RollableReader {
            latest_rating: None,
            average_rating: None,
            rating_count: None,
            read_count: None,
            issue_count: None,
            progress_scope: "THREAD".to_string(),
        };

        let routes = route_labels
            .unwrap_or_default()
            .into_iter()
            .map(|name| crate::schemas::RollableRoute {
                kind: "group".to_string(),
                name,
            })
            .collect();

        let item = build_rollable_item(
            thread,
            issue,
            identity,
            reader,
            routes,
            0,
        );

        rollable_items.push(item);
    }

    // Fetch snoozed threads
    let snoozed_rows = match fetch_snoozed_threads(&state.pool, user_id, RollV2BootstrapResponse::SUMMARY_LIMIT).await {
        Ok(rows) => rows,
        Err(e) => {
            warn!("Failed to fetch snoozed threads for user {}: {}", user_id, e);
            Vec::new()
        }
    };

    let snoozed_threads: Vec<crate::schemas::RollableThread> = snoozed_rows
        .into_iter()
        .map(|row| {
            let id: i64 = row.get("id");
            let title: String = row.get("title");
            let format: String = row.get("format");
            let last_activity_at: Option<String> = row.get("last_activity_at");
            build_rollable_thread(id, &title, &format, last_activity_at.as_deref())
        })
        .collect();

    // Fetch blocked count
    let blocked_count = match fetch_blocked_count(&state.pool, user_id).await {
        Ok(count) => count,
        Err(e) => {
            warn!("Failed to fetch blocked count for user {}: {}", user_id, e);
            0
        }
    };

    // Fetch stale thread count
    let stale_thread_count = match fetch_stale_thread_count(&state.pool, user_id).await {
        Ok(count) => count,
        Err(e) => {
            warn!("Failed to fetch stale thread count for user {}: {}", user_id, e);
            0
        }
    };

    // Fetch last read
    let last_read_row = match fetch_last_read(&state.pool, session_id).await {
        Ok(row) => row,
        Err(e) => {
            warn!("Failed to fetch last read for session {}: {}", session_id, e);
            None
        }
    };

    let last_read = match last_read_row {
        Some(row) => {
            let issue_id: Option<i64> = row.get("issue_id");
            let issue_number: Option<String> = row.get("issue_number");
            let thread_id: Option<i64> = row.get("thread_id");
            let thread_title: Option<String> = row.get("thread_title");
            let timestamp: Option<String> = row.get("timestamp");

            Some(build_roll_last_read(issue_id, issue_number.as_deref(), thread_id, thread_title.as_deref(), timestamp.as_deref()))
        }
        None => None,
    };

    // Build response
    let response = crate::schemas::RollV2BootstrapResponse {
        session_id,
        user_id,
        current_die,
        manual_die,
        pending_thread_id,
        last_rolled_result: active_thread.as_ref().and_then(|t| t.last_rolled_result),
        session_mode: build_session_mode(
            &active_bandwidth,
            &active_bandwidth,
            bandwidth_confidence,
            &bandwidth_source,
            &bandwidth_version,
            &active_intent,
            &active_intent,
            intent_confidence,
            &intent_source,
            &intent_version,
            correction_guidance.as_deref(),
        ),
        active_thread,
        roll_recovery: Some(build_roll_recovery(
            pending_thread_id,
            None, // TODO: Fetch pending thread title
            skipped_thread_ids,
        )),
        bandwidth: build_bandwidth_state(
            &active_bandwidth,
            &active_bandwidth,
            bandwidth_confidence,
            &bandwidth_source,
            &bandwidth_version,
        ),
        rollable: rollable_items,
        last_read,
        snoozed_threads,
        snoozed_count: snoozed_threads.len() as i32,
        skipped_thread_ids,
        skipped_threads: Vec::new(), // TODO: Fetch skipped threads
        blocked_count,
        blocked_threads: Vec::new(), // TODO: Fetch blocked threads
        stale_thread_count,
        stale_thread: None, // TODO: Fetch stale thread
        timezone,
    };

    info!(
        user_id = user_id,
        session_id = session_id,
        rollable_count = rollable_items.len(),
        "V2 bootstrap successful"
    );

    Ok(Json(BootstrapResponse {
        response,
        tracing: None,
    }))
}
