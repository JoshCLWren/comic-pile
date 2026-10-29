//! Authenticated Roll v2 bootstrap using the already merged native session and Option E loaders.
//! No Python hop and no synthetic "success" values for missing database rows.
use crate::{
    auth::AuthenticatedUser,
    db, option_inputs,
    reading_session::{self, SessionPolicy},
    ApiError, AppState,
};
use axum::{
    extract::{Query, State},
    http::StatusCode,
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
};

#[derive(Deserialize, Default)]
pub struct BootstrapQuery {
    pub timezone: Option<String>,
}

fn unavailable() -> ApiError {
    ApiError(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Invalid native Roll response",
    )
}

fn thread_value(row: &tokio_postgres::Row) -> Result<Value, ApiError> {
    let id: i32 = row.try_get(0).map_err(db::query_error)?;
    let title: String = row.try_get(1).map_err(db::query_error)?;
    let format: String = row.try_get(2).map_err(db::query_error)?;
    let last_activity_at: Option<String> = row.try_get(3).map_err(db::query_error)?;
    Ok(json!({
        "id": id,
        "title": title,
        "format": format,
        "last_activity_at": last_activity_at
    }))
}

fn normalized_source(value: &Option<String>) -> Option<&str> {
    value
        .as_deref()
        .filter(|v| matches!(*v, "inferred" | "manual" | "snooze" | "quiz"))
}

fn candidate_item(row: &tokio_postgres::Row) -> Result<(i32, Value), ApiError> {
    let thread_id: i32 = row.try_get(0).map_err(db::query_error)?;
    let issue_id: i32 = row.try_get(4).map_err(db::query_error)?;
    let issue_number: String = row.try_get(5).map_err(db::query_error)?;
    let metadata: Option<String> = row.try_get(6).map_err(db::query_error)?;
    let mapping_status: Option<String> = row.try_get(7).map_err(db::query_error)?;
    let series_mapping_status: Option<String> = row.try_get(8).map_err(db::query_error)?;
    let read_count: i64 = row.try_get(9).map_err(db::query_error)?;
    let issue_count: i64 = row.try_get(10).map_err(db::query_error)?;
    let latest_rating: Option<f64> = row.try_get(11).map_err(db::query_error)?;
    let average_rating: Option<f64> = row.try_get(12).map_err(db::query_error)?;
    let rating_count: i64 = row.try_get(13).map_err(db::query_error)?;
    let routes: Vec<String> = row.try_get(14).map_err(db::query_error)?;
    let meta: Value = metadata
        .as_deref()
        .and_then(|m| serde_json::from_str(m).ok())
        .unwrap_or(Value::Null);
    let volume = meta.get("volume");
    let canonical_id = volume
        .and_then(|v| v.get("id"))
        .or_else(|| meta.get("volume_id"))
        .and_then(|id| match id {
            Value::String(s) if !s.is_empty() => Some(s.to_owned()),
            Value::Number(n) => Some(n.to_string()),
            _ => None,
        });
    let canonical_title = volume
        .and_then(|v| v.get("name"))
        .or_else(|| meta.get("volume_name"))
        .and_then(Value::as_str);
    let cover = meta
        .get("image_url")
        .or_else(|| meta.get("primary_image"))
        .or_else(|| meta.get("image").and_then(|i| i.get("original_url")))
        .and_then(Value::as_str)
        .filter(|s| s.starts_with("https://") || s.starts_with("http://"))
        .filter(|s| !s.split('/').nth(2).unwrap_or("").contains('@'));
    let source = if canonical_id.is_some() && mapping_status.as_deref() == Some("confirmed") {
        "comicvine"
    } else {
        "unavailable"
    };
    let identity_state = match mapping_status.as_deref() {
        Some("confirmed") if source == "comicvine" => "confirmed",
        Some("candidate") => "candidate",
        Some("ambiguous") => "ambiguous",
        Some("conflicting") => "conflicting",
        _ => "unresolved",
    };
    let series_state = match series_mapping_status.as_deref() {
        Some("confirmed") => "confirmed",
        Some("candidate") => "candidate",
        Some("ambiguous") => "ambiguous",
        Some("conflicting") => "conflicting",
        _ => "unresolved",
    };
    let overflow = routes.len().saturating_sub(3);
    let item = json!({
        "thread": thread_value(row)?,
        "issue": {
            "id": issue_id,
            "number": issue_number,
            "canonical_series_title": canonical_title,
            "cover_url": cover
        },
        "identity": {
            "source": source,
            "canonical_series_id": if source == "comicvine" {canonical_id} else {None},
            "state": identity_state,
            "series_mapping_state": series_state
        },
        "reader": {
            "latest_rating": latest_rating,
            "average_rating": average_rating,
            "rating_count": rating_count,
            "read_count": read_count,
            "issue_count": issue_count,
            "progress_scope": "thread"
        },
        "routes": routes.iter().take(3).map(|name| json!({"kind":"group","name":name})).collect::<Vec<_>>(),
        "overflow_routes_count": overflow
    });
    Ok((thread_id, item))
}

const CANDIDATES: &str = r#"
SELECT t.id, t.title, t.format, t.last_activity_at::text, i.id, i.issue_number,
 mapping.metadata::text, mapping.status, series_mapping.status,
 (SELECT count(*) FROM issues owned WHERE owned.thread_id=t.id AND owned.status='read'),
 (SELECT count(*) FROM issues owned WHERE owned.thread_id=t.id),
 (SELECT e.rating::double precision FROM events e JOIN sessions s ON s.id=e.session_id
    WHERE s.user_id=$1 AND e.thread_id=t.id AND e.type='rate' AND e.rating IS NOT NULL
    ORDER BY e.timestamp DESC,e.id DESC LIMIT 1),
 (SELECT avg(e.rating)::double precision FROM events e JOIN sessions s ON s.id=e.session_id
    WHERE s.user_id=$1 AND e.thread_id=t.id AND e.type='rate' AND e.rating IS NOT NULL),
 (SELECT count(*) FROM events e JOIN sessions s ON s.id=e.session_id
    WHERE s.user_id=$1 AND e.thread_id=t.id AND e.type='rate' AND e.rating IS NOT NULL),
 COALESCE((SELECT array_agg(names.name ORDER BY names.name) FROM (
    SELECT DISTINCT g.name FROM dependency_groups g
    JOIN dependency_group_memberships m ON m.group_id=g.id
    WHERE g.user_id=$1 AND (m.thread_id=t.id OR m.issue_id=i.id)
 ) names),ARRAY[]::text[])
FROM issues i
JOIN threads t ON t.id=i.thread_id
LEFT JOIN LATERAL (
    SELECT e.metadata_json AS metadata,m.status
    FROM issue_external_identity_mappings m JOIN external_identities e ON e.id=m.external_identity_id
    WHERE m.issue_id=i.id AND m.status<>'rejected'
      AND e.provider='comicvine' AND e.entity_type='issue'
    ORDER BY (m.status='confirmed') DESC,m.confidence DESC NULLS LAST,m.id LIMIT 1
) mapping ON TRUE
LEFT JOIN LATERAL (
    SELECT m.status FROM thread_external_series_mappings m
    JOIN external_identities e ON e.id=m.external_identity_id
    WHERE m.thread_id=t.id AND m.status<>'rejected'
      AND e.provider='comicvine' AND e.entity_type='series'
    ORDER BY (m.status='confirmed') DESC,m.confidence DESC NULLS LAST,m.id LIMIT 1
) series_mapping ON TRUE
WHERE t.user_id=$1 AND i.id=ANY($2::int[])
"#;

async fn latest_session_read(
    connection: &deadpool_postgres::Object,
    user: AuthenticatedUser,
    session_id: i32,
) -> Result<Option<Value>, ApiError> {
    let row = connection.query_opt(
        "SELECT e.issue_id,coalesce(i.issue_number,e.issue_number),t.id,t.title,e.timestamp::text
         FROM events e LEFT JOIN issues i ON i.id=e.issue_id
         LEFT JOIN threads t ON t.id=coalesce(i.thread_id,e.thread_id) AND t.user_id=$2
         WHERE e.session_id=$1 AND e.type='rate'
           AND EXISTS (SELECT 1 FROM sessions s WHERE s.id=e.session_id AND s.user_id=$2)
         ORDER BY e.timestamp DESC,e.id DESC LIMIT 1",
        &[&session_id,&user.id()],
    ).await.map_err(db::query_error)?;
    row.map(|row| {
        let issue_id: Option<i32> = row.try_get(0).map_err(db::query_error)?;
        let issue_number: Option<String> = row.try_get(1).map_err(db::query_error)?;
        let thread_id: Option<i32> = row.try_get(2).map_err(db::query_error)?;
        let thread_title: Option<String> = row.try_get(3).map_err(db::query_error)?;
        let read_at: Option<String> = row.try_get(4).map_err(db::query_error)?;
        Ok(
            json!({"issue_id":issue_id,"issue_number":issue_number,"thread_id":thread_id,
            "thread_title":thread_title,"read_at":read_at}),
        )
    })
    .transpose()
}

async fn current_active_thread(
    conn: &deadpool_postgres::Object,
    user: AuthenticatedUser,
    session_id: i32,
    pending_thread_id: Option<i32>,
) -> Result<Option<Value>, ApiError> {
    let Some(thread_id) = pending_thread_id else {
        return Ok(None);
    };
    let row = conn
        .query_opt(
            "SELECT t.id,t.title,t.format,t.issues_remaining,t.queue_position,
               t.total_issues,t.reading_progress,t.last_rating,t.next_unread_issue_id,
               i.issue_number,
               (SELECT count(*)::int FROM issues read WHERE read.thread_id=t.id AND read.status='read'),
               (SELECT e.result FROM events e WHERE e.session_id=$2 AND e.selected_thread_id=t.id
                 AND e.type='roll' ORDER BY e.timestamp DESC,e.id DESC LIMIT 1)
             FROM threads t LEFT JOIN issues i ON i.id=t.next_unread_issue_id AND i.thread_id=t.id
             WHERE t.id=$1 AND t.user_id=$3",
            &[&thread_id, &session_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(unavailable)?;
    let id: i32 = row.try_get(0).map_err(db::query_error)?;
    let title: String = row.try_get(1).map_err(db::query_error)?;
    let format: String = row.try_get(2).map_err(db::query_error)?;
    let issues_remaining: i32 = row.try_get(3).map_err(db::query_error)?;
    let queue_position: i32 = row.try_get(4).map_err(db::query_error)?;
    let total_issues: Option<i32> = row.try_get(5).map_err(db::query_error)?;
    let reading_progress: Option<String> = row.try_get(6).map_err(db::query_error)?;
    let last_rating: Option<f64> = row.try_get(7).map_err(db::query_error)?;
    let next_issue_id: Option<i32> = row.try_get(8).map_err(db::query_error)?;
    let next_issue_number: Option<String> = row.try_get(9).map_err(db::query_error)?;
    let issues_read: i32 = row.try_get(10).map_err(db::query_error)?;
    let last_rolled_result: Option<i32> = row.try_get(11).map_err(db::query_error)?;
    Ok(Some(json!({
        "id": id,
        "title": title,
        "format": format,
        "issues_remaining": issues_remaining,
        "queue_position": queue_position,
        "last_rolled_result": last_rolled_result,
        "total_issues": total_issues,
        "reading_progress": reading_progress,
        "issues_read": issues_read,
        "last_rating": last_rating,
        "tags": [],
        "issue_id": next_issue_id,
        "issue_number": next_issue_number,
        "next_issue_id": next_issue_id,
        "next_issue_number": next_issue_number
    })))
}

pub async fn bootstrap_v2(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(query): Query<BootstrapQuery>,
) -> Result<Json<Value>, ApiError> {
    let active = reading_session::bootstrap(
        &state,
        user,
        query.timezone.as_deref(),
        SessionPolicy::default(),
    )
    .await?;
    let validated = option_inputs::load_option_inputs(&state, user).await?;
    let session = &active.session;
    let skipped = session.skipped_thread_ids.clone().unwrap_or_default();
    let snoozed = session.snoozed_thread_ids.clone().unwrap_or_default();
    let excluded: HashSet<i32> = skipped.iter().chain(snoozed.iter()).copied().collect();
    let candidates = validated.eligible_frontiers().map_err(|_| {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Invalid reading constraints",
        )
    })?;
    let eligible: Vec<_> = candidates
        .iter()
        .filter(|candidate| !excluded.contains(&candidate.thread_id))
        .take(active.current_die.max(0) as usize)
        .collect();
    let ids: Vec<i32> = eligible.iter().map(|item| item.issue_id).collect();

    let conn = db::checkout(&state).await?;
    let rows = conn
        .query(CANDIDATES, &[&user.id(), &ids])
        .await
        .map_err(db::query_error)?;
    let mut by_thread: HashMap<i32, Value> = HashMap::new();
    for row in &rows {
        let (thread_id, item) = candidate_item(row)?;
        by_thread.insert(thread_id, item);
    }
    let mut rollable = vec![];
    for item in eligible {
        let projected = by_thread.remove(&item.thread_id).ok_or_else(unavailable)?;
        rollable.push(projected);
    }
    let last_read = latest_session_read(&conn, user, session.id).await?;

    let summary_rows = conn
        .query(
            "SELECT t.id,t.title,t.format,t.last_activity_at::text,
          (t.last_activity_at < now() - interval '7 days') AS stale
         FROM threads t WHERE t.user_id=$1 ORDER BY t.queue_position,t.id",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let mut known: HashMap<i32, Value> = HashMap::new();
    let mut stale = Vec::new();
    for row in &summary_rows {
        let id: i32 = row.try_get(0).map_err(db::query_error)?;
        let stale_flag: Option<bool> = row.try_get(4).map_err(db::query_error)?;
        let info = thread_value(row)?;
        if stale_flag.unwrap_or(false) {
            stale.push(info.clone());
        }
        known.insert(id, info);
    }
    let summary = |ids: &[i32]| {
        ids.iter()
            .filter_map(|id| known.get(id).cloned())
            .take(20)
            .collect::<Vec<_>>()
    };
    let snoozed_threads = summary(&snoozed);
    let snoozed_count = snoozed_threads.len();
    let skipped_threads = summary(&skipped);
    let eligible_threads: HashSet<i32> = candidates.iter().map(|c| c.thread_id).collect();
    let blocked: Vec<i32> = validated
        .inputs()
        .core
        .threads
        .iter()
        .filter(|thread| thread.status == "active" && !eligible_threads.contains(&thread.id))
        .map(|thread| thread.id)
        .collect();
    let blocked_threads = summary(&blocked);

    let active_thread = current_active_thread(&conn, user, session.id, session.pending_thread_id).await?;
    let last_roll_result = active_thread
        .as_ref()
        .and_then(|thread| thread.get("last_rolled_result"))
        .and_then(Value::as_i64);
    let mode_source = normalized_source(&session.bandwidth_source);
    let intent_source = normalized_source(&session.intent_source);
    let response = json!({
        "session_id": session.id,
        "user_id": user.id(),
        "current_die": active.current_die,
        "manual_die": session.manual_die,
        "pending_thread_id": session.pending_thread_id,
        "last_rolled_result": last_roll_result,
        "session_mode": {
            "active_bandwidth": session.active_bandwidth,
            "predicted_bandwidth": session.predicted_bandwidth,
            "bandwidth_confidence": session.bandwidth_confidence,
            "bandwidth_source": mode_source,
            "bandwidth_version": session.bandwidth_version,
            "active_intent": session.active_intent,
            "predicted_intent": session.predicted_intent,
            "intent_confidence": session.intent_confidence,
            "intent_source": intent_source,
            "intent_version": session.intent_version,
            "session_mode_correction_guidance": session.session_mode_correction_guidance
        },
        "active_thread": active_thread,
        "roll_recovery": Value::Null,
        "bandwidth": {
            "predicted_bandwidth": session.predicted_bandwidth,
            "active_bandwidth": session.active_bandwidth,
            "confidence": session.bandwidth_confidence,
            "source": mode_source,
            "mode_version": session.bandwidth_version
        },
        "rollable": rollable,
        "last_read": last_read,
        "snoozed_threads": snoozed_threads,
        "snoozed_count": snoozed_count,
        "skipped_thread_ids": skipped,
        "skipped_threads": skipped_threads,
        "blocked_count": blocked.len(),
        "blocked_threads": blocked_threads,
        "stale_thread_count": stale.len(),
        "stale_thread": stale.first(),
        "timezone": session.timezone
    });
    Ok(Json(response))
}
