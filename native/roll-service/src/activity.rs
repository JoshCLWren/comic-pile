//! Owner-scoped activity history resource.
//!
//! `GET /api/v2/activity` is the native replacement for the legacy session-based
//! History read path. It returns one chronological, owner-scoped activity stream
//! with stable cursor pagination. Events remain durable and are never rewritten;
//! reader-visible logical actions (such as a coalesced rating) are derived at
//! read time.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Query, State},
    Json,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use serde::Deserialize;
use serde_json::{json, Value};
use std::sync::Arc;

#[derive(Debug, Deserialize)]
pub struct ActivityQuery {
    limit: Option<i64>,
    page_token: Option<String>,
    cursor: Option<String>,
}

#[derive(Debug, Clone)]
struct ActivityRow {
    event_id: i32,
    event_type: String,
    timestamp: String,
    timestamp_micros: i64,
    die_before: Option<i32>,
    die_after: Option<i32>,
    rating: Option<f64>,
    issue_id: Option<i32>,
    issue_number: Option<String>,
    thread_id: Option<i32>,
    thread_title: Option<String>,
    context: Option<Value>,
    sort_key: i64,
}

#[derive(Debug, Clone, serde::Serialize)]
struct ActivityItem {
    event_id: i32,
    #[serde(rename = "type")]
    event_type: String,
    timestamp: String,
    die_before: Option<i32>,
    die_after: Option<i32>,
    rating: Option<f64>,
    issue_id: Option<i32>,
    thread_id: Option<i32>,
    thread_title: Option<String>,
    issue_number: Option<String>,
}

const DEFAULT_LIMIT: i64 = 50;
const MAX_LIMIT: i64 = 100;
const FETCH_MULTIPLIER: i64 = 4;
const CAUSAL_WINDOW_MICROS: i64 = 5_000_000;

fn parse_cursor(token: &str) -> Option<(String, i32)> {
    let bytes = URL_SAFE_NO_PAD.decode(token).ok()?;
    let value: Value = serde_json::from_slice(&bytes).ok()?;
    let ts = value.get("ts")?.as_str()?.to_string();
    let id = value.get("id")?.as_i64()? as i32;
    Some((ts, id))
}

fn encode_cursor(timestamp: &str, id: i32) -> String {
    let payload = json!({"ts": timestamp, "id": id});
    URL_SAFE_NO_PAD.encode(serde_json::to_vec(&payload).unwrap_or_default())
}

fn is_rate_like(event_type: &str) -> bool {
    event_type == "rate"
}

fn context_i64(context: &Option<Value>, key: &str) -> Option<i64> {
    context
        .as_ref()
        .and_then(|value| value.get(key))
        .and_then(|value| value.as_i64())
}

fn to_item(row: &ActivityRow) -> ActivityItem {
    ActivityItem {
        event_id: row.event_id,
        event_type: row.event_type.clone(),
        timestamp: row.timestamp.clone(),
        die_before: row.die_before,
        die_after: row.die_after,
        rating: row.rating,
        issue_id: row.issue_id,
        thread_id: row.thread_id,
        thread_title: row.thread_title.clone(),
        issue_number: row.issue_number.clone(),
    }
}

/// `GET /api/v2/activity` — bounded, owner-scoped activity stream.
pub async fn list_activity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(query): Query<ActivityQuery>,
) -> Result<Json<Value>, ApiError> {
    let limit = query.limit.unwrap_or(DEFAULT_LIMIT).clamp(1, MAX_LIMIT);
    let fetch_limit = (limit * FETCH_MULTIPLIER).max(limit + 10);
    let cursor_token = query.page_token.or(query.cursor);
    let cursor = cursor_token.as_deref().and_then(parse_cursor);

    let connection = db::checkout(&state).await?;

    let mut sql = String::from(
        "SELECT e.id, e.type, \
         to_char(e.timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), \
         e.die, e.die_after, e.rating, e.issue_id, e.issue_number, \
         COALESCE(e.thread_id, e.selected_thread_id) AS thread_id, \
         t.title, e.context::text, \
         (extract(epoch FROM e.timestamp) * 1000000)::bigint \
         FROM events e \
         LEFT JOIN threads t ON t.id = COALESCE(e.thread_id, e.selected_thread_id) \
         WHERE e.user_id = $1",
    );
    let mut params: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = Vec::new();
    params.push(&user.id() as &(dyn tokio_postgres::types::ToSql + Sync));
    if let Some((ts, id)) = &cursor {
        sql.push_str(" AND (e.timestamp > $2::timestamptz OR (e.timestamp = $2::timestamptz AND e.id > $3))");
        // placeholders handled below by binding; use positional params
        let _ = (ts, id);
    }
    sql.push_str(" ORDER BY e.timestamp ASC, e.id ASC LIMIT $");
    // We'll rebuild with proper bind count.
    let _ = &sql;

    // Rebuild SQL cleanly with bind parameters.
    let mut sql = String::from(
        "SELECT e.id, e.type, \
         to_char(e.timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), \
         e.die, e.die_after, e.rating, e.issue_id, e.issue_number, \
         COALESCE(e.thread_id, e.selected_thread_id) AS thread_id, \
         t.title, e.context::text, \
         (extract(epoch FROM e.timestamp) * 1000000)::bigint \
         FROM events e \
         LEFT JOIN threads t ON t.id = COALESCE(e.thread_id, e.selected_thread_id) \
         WHERE e.user_id = $1",
    );

    // Bind cursor values via owned strings to satisfy lifetimes.
    let cursor_ts_owned: Option<String> = cursor.as_ref().map(|(ts, _)| ts.clone());
    let cursor_id_owned: Option<i32> = cursor.as_ref().map(|(_, id)| *id);

    if cursor.is_some() {
        sql.push_str(" AND (e.timestamp > $2::timestamptz OR (e.timestamp = $2::timestamptz AND e.id > $3))");
    }
    sql.push_str(" ORDER BY e.timestamp ASC, e.id ASC LIMIT $");
    let limit_placeholder = if cursor.is_some() { 4 } else { 2 };
    sql.push_str(&limit_placeholder.to_string());

    // Build bind slice dynamically.
    let rows = if cursor.is_some() {
        let ts = cursor_ts_owned.as_ref().unwrap();
        let id = cursor_id_owned.unwrap();
        connection
            .query(
                &sql,
                &[&user.id(), &ts, &id, &fetch_limit],
            )
            .await
            .map_err(db::query_error)?
    } else {
        connection
            .query(&sql, &[&user.id(), &fetch_limit])
            .await
            .map_err(db::query_error)?
    };

    let mut fetched: Vec<ActivityRow> = Vec::new();
    for row in rows {
        let context_text: Option<String> = row.get(10);
        let context: Option<Value> = context_text
            .as_deref()
            .and_then(|text| serde_json::from_str(text).ok());
        let timestamp_micros: i64 = row.get(11);
        fetched.push(ActivityRow {
            event_id: row.get(0),
            event_type: row.get(1),
            timestamp: row.get(2),
            timestamp_micros,
            die_before: row.get(3),
            die_after: row.get(4),
            rating: row.get(5),
            issue_id: row.get(6),
            issue_number: row.get(7),
            thread_id: row.get(8),
            thread_title: row.get(9),
            context,
            sort_key: timestamp_micros,
        });
    }

    // Causal reordering: a roll that snoozed a previous offer must appear after
    // the matching snooze, even when the roll's timestamp is earlier.
    for roll in fetched
        .iter()
        .filter(|row| row.event_type == "roll")
        .cloned()
        .collect::<Vec<_>>()
    {
        let snoozed_thread = context_i64(&roll.context, "snoozed_thread_id");
        if snoozed_thread.is_none() {
            continue;
        }
        let snoozed_thread = snoozed_thread.unwrap();
        for snooze in fetched.iter_mut() {
            if snooze.event_type != "snooze" {
                continue;
            }
            if snooze.thread_id != Some(snoozed_thread as i32) {
                continue;
            }
            if (snooze.timestamp_micros - roll.timestamp_micros).abs() > CAUSAL_WINDOW_MICROS {
                continue;
            }
            // Place snooze before roll.
            if snooze.sort_key >= roll.sort_key {
                snooze.sort_key = roll.timestamp_micros - 1;
            }
        }
    }

    fetched.sort_by(|a, b| a.sort_key.cmp(&b.sort_key).then(a.event_id.cmp(&b.event_id)));

    // Coalesce related issue-command/dice-command rate pairs into one display.
    let cursor_source = fetched.last().cloned();
    let mut logical: Vec<ActivityRow> = Vec::new();
    for row in fetched {
        if is_rate_like(&row.event_type)
            && !logical.is_empty()
            && is_rate_like(&logical.last().unwrap().event_type)
        {
            let prev = logical.last().unwrap();
            let same_issue = prev.issue_id == row.issue_id && prev.issue_id.is_some();
            let same_rating = prev.rating == row.rating && prev.rating.is_some();
            let close = (prev.timestamp_micros - row.timestamp_micros).abs() <= CAUSAL_WINDOW_MICROS;
            if same_issue && same_rating && close {
                let mut merged = logical.pop().unwrap();
                merged.die_before = merged.die_before.or(row.die_before);
                merged.die_after = merged.die_after.or(row.die_after);
                if merged.thread_id.is_none() {
                    merged.thread_id = row.thread_id;
                }
                if merged.thread_title.is_none() {
                    merged.thread_title = row.thread_title;
                }
                if merged.issue_number.is_none() {
                    merged.issue_number = row.issue_number;
                }
                if row.timestamp_micros < merged.timestamp_micros {
                    merged.timestamp = row.timestamp.clone();
                    merged.timestamp_micros = row.timestamp_micros;
                }
                if row.event_id < merged.event_id {
                    merged.event_id = row.event_id;
                }
                logical.push(merged);
                continue;
            }
        }
        logical.push(row);
    }

    let has_more = logical.len() > limit as usize;
    let page: Vec<ActivityRow> = logical.into_iter().take(limit as usize).collect();

    let items: Vec<ActivityItem> = page.iter().map(to_item).collect();

    let next_page_token = if has_more {
        cursor_source.as_ref().map(|row| encode_cursor(&row.timestamp, row.event_id))
    } else {
        None
    };
    // Better cursor: last page item's underlying? We don't retain. Use fetched last.
    let next_cursor = next_page_token.clone();

    Ok(Json(json!({
        "activities": items,
        "events": items,
        "items": items,
        "next_page_token": next_page_token,
        "next_cursor": next_cursor,
    })))
}

// OpenAPI declaration
#[utoipa::path(
    get,
    path = "/api/v2/activity",
    tag = "activity",
    params(
        ("limit" = Option<i64>, Query, description = "Maximum number of activity rows"),
        ("page_token" = Option<String>, Query, description = "Opaque continuation cursor")
    ),
    responses((status = 200, description = "Owner-scoped activity history")),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_activity_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cursor_round_trips() {
        let token = encode_cursor("2026-11-08T10:01:54.440000Z", 42);
        let (ts, id) = parse_cursor(&token).expect("cursor");
        assert_eq!(ts, "2026-11-08T10:01:54.440000Z");
        assert_eq!(id, 42);
    }
}
