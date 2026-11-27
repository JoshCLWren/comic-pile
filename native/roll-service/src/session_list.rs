//! Canonical owner-scoped reading-session List/Get resource (#5708, #4456,
//! parent #4335).
//!
//! `GET /api/v2/readingSessions` and `GET /api/v2/readingSessions/{session_id}`
//! are the AIP-122 standard methods for the reading-session collection. This is
//! a *derived history view* over durable rows: it never reinstates the retired
//! server session lifetime, pending state or current-session pointer (#4343,
//! #4405). Roll stays sessionless at the wire boundary; the resource only
//! projects recorded dice/read history.
//!
//! ## Bounded reads
//!
//! One statement fetches the page, its event aggregates and its snapshot
//! counts with CTE joins bounded by the page itself, so a page never issues a
//! query per row. The keyset cursor is `(started_at, id)`; every page is owner-scoped by
//! `sessions.user_id`. A missing or foreign session is indistinguishable and
//! returns 404 with the established `"Session not found"` detail.
//!
//! Dice/read writes are persisted without a `session_id` (dice_mutation and
//! issue_service), so an event aggregate that only matches `e.session_id` would
//! silently drop modern history. Like the `/details` projection, each page row
//! claims that reader's session-less `rate`/`snooze`/`unsnooze`/`manual_die`/
//! `reset_dice` events inside its own window: `[started_at, ended_at]` for an
//! ended session, or up to the next session start for an open one. The window is
//! derived set-based in the page CTE, never with a per-row query. Manual
//! selection and Reset carry a die outcome with no earlier die event, so they
//! must take part in both the current-die resolution and the ladder, never be
//! mistaken for a non-die action.

use crate::{
    auth::AuthenticatedUser,
    db,
    session_details::{current_die, ladder_path},
    ApiError, AppState,
};
use axum::{
    extract::{Path, Query, State},
    Json,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;
use utoipa::ToSchema;

const DEFAULT_PAGE_SIZE: i32 = 50;
const MAX_PAGE_SIZE: i32 = 100;

/// One durable, event-derived reading session in the canonical collection.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ReadingSessionResource {
    /// Stable AIP-122 resource name: `readingSessions/{session_id}`.
    pub name: String,
    pub session_id: i32,
    pub started_at: String,
    pub ended_at: Option<String>,
    pub start_die: i32,
    /// Event-derived die, with the legacy `manual_die` column as fallback only.
    pub current_die: i32,
    /// `start_die` followed by the session's recorded `die_after` values.
    pub ladder_path: String,
    pub event_count: i32,
    pub snapshot_count: i32,
    pub timezone: Option<String>,
}

/// One bounded page of the canonical reading-session collection.
#[derive(Debug, Serialize, ToSchema)]
pub struct ListReadingSessionsResponse {
    pub reading_sessions: Vec<ReadingSessionResource>,
    pub next_page_token: Option<String>,
}

/// Standard AIP-132 List query. The cursor lives in `page_token`, never in a
/// cache key, and `page_size` is bounded before it reaches SQL or allocation.
#[derive(Debug, Deserialize)]
pub struct ListReadingSessionsQuery {
    pub page_size: Option<i32>,
    pub page_token: Option<String>,
}

fn bad_page_token() -> ApiError {
    ApiError::BadRequest("Invalid reading session page token".to_string())
}

fn bad_page_size() -> ApiError {
    ApiError::BadRequest("Invalid reading session page size".to_string())
}

fn row_error(error: tokio_postgres::Error) -> ApiError {
    tracing::debug!(
        error_kind = crate::error_kind(&error),
        "preserved underlying row decode error"
    );
    ApiError::Internal("Internal Server Error".to_string())
}

/// Keyset position of a session in `(started_at DESC, id DESC)` order.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct PageKey {
    micros: i64,
    id: i32,
}

/// Decode an opaque token this endpoint issued. Anything else fails closed
/// before SQL, so a client cannot inject an arbitrary timestamp or id.
fn parse_page_token(token: &str) -> Result<PageKey, ApiError> {
    let bytes = URL_SAFE_NO_PAD
        .decode(token)
        .map_err(|_| bad_page_token())?;
    let value: Value = serde_json::from_slice(&bytes).map_err(|_| bad_page_token())?;
    let object = value.as_object().ok_or_else(bad_page_token)?;
    if object.len() != 2 {
        return Err(bad_page_token());
    }
    let micros = object
        .get("t")
        .and_then(Value::as_i64)
        .ok_or_else(bad_page_token)?;
    let id = object
        .get("id")
        .and_then(Value::as_i64)
        .and_then(|id| i32::try_from(id).ok())
        .filter(|id| *id > 0)
        .ok_or_else(bad_page_token)?;
    DateTime::<Utc>::from_timestamp_micros(micros).ok_or_else(bad_page_token)?;
    Ok(PageKey { micros, id })
}

fn encode_page_token(key: PageKey) -> String {
    let payload = serde_json::json!({"t": key.micros, "id": key.id});
    URL_SAFE_NO_PAD.encode(payload.to_string())
}

fn timestamp(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(chrono::SecondsFormat::Micros, true)
}

/// Page (or single-row) projection with its aggregates resolved in one
/// statement. `$2` narrows to one id for Get and is NULL for List.
const SESSION_PAGE_SQL: &str = r#"
WITH page AS (
    SELECT s.id, s.started_at, s.ended_at, s.start_die, s.manual_die, s.timezone,
           -- Same boundary as session_details.rs: an ended session owns events
           -- up to its ended_at, an open one up to the next owned session start.
           (SELECT MIN(s2.started_at)
              FROM sessions s2
             WHERE s2.user_id = s.user_id
               AND s2.id <> s.id
               AND s2.started_at > s.started_at) AS next_started_at
      FROM sessions s
     WHERE s.user_id = $1
       AND ($2::int IS NULL OR s.id = $2::int)
       AND ($3::timestamptz IS NULL OR (s.started_at, s.id) < ($3::timestamptz, $4::int))
     ORDER BY s.started_at DESC, s.id DESC
     LIMIT $5
), event_stats AS (
    -- Die-bearing types mirror session_details::CURRENT_DIE_SQL: a manual
    -- selection or Reset is a recorded die outcome even when it is the first
    -- or last die event in the window. The die_after guard and the explicit
    -- type set keep non-die window actions (e.g. unsnooze) out of the ladder.
    SELECT p.id AS session_id,
           COUNT(e.id)::int AS event_count,
           (array_agg(e.die_after ORDER BY e.timestamp DESC, e.id DESC)
              FILTER (WHERE e.die_after IS NOT NULL AND e.type IN ('rate','snooze','undo','manual_die','reset_dice')))[1] AS latest_die_after,
           (array_agg(e.context::text ORDER BY e.timestamp DESC, e.id DESC)
              FILTER (WHERE e.die_after IS NOT NULL AND e.type IN ('rate','snooze','undo','manual_die','reset_dice')))[1] AS latest_context,
           array_agg(e.die_after ORDER BY e.timestamp ASC, e.id ASC)
              FILTER (WHERE e.die_after IS NOT NULL AND e.type IN ('rate','snooze','undo','manual_die','reset_dice')) AS ladder
      FROM page p
      LEFT JOIN events e
        ON e.session_id = p.id
        OR (e.session_id IS NULL
            AND e.user_id = $1
            -- Dice commands (manual selection, Reset) and the unsnooze command
            -- are also session-less owner-scoped writes; they belong in the
            -- window like rate/snooze, not in a separate die-only projection.
            AND e.type IN ('rate','snooze','unsnooze','manual_die','reset_dice')
            AND e.timestamp >= p.started_at
            AND ((p.ended_at IS NOT NULL AND e.timestamp <= p.ended_at)
              OR (p.ended_at IS NULL
                  AND (p.next_started_at IS NULL OR e.timestamp < p.next_started_at)))
            -- dice_mutation's roll_rating companion is suppressed by /details
            -- in favour of the richer issue-service rate event.
            AND (e.context -> 'dice_command' ->> 'kind') IS DISTINCT FROM 'roll_rating')
     GROUP BY p.id
), snapshot_stats AS (
    SELECT sn.session_id, COUNT(*)::int AS snapshot_count
      FROM snapshots sn
     WHERE sn.session_id IN (SELECT id FROM page)
     GROUP BY sn.session_id
)
SELECT p.id, p.started_at, p.ended_at, p.start_die, p.manual_die, p.timezone,
       COALESCE(es.event_count, 0)::int,
       COALESCE(ss.snapshot_count, 0)::int,
       es.latest_die_after, es.latest_context, es.ladder
  FROM page p
  LEFT JOIN event_stats es ON es.session_id = p.id
  LEFT JOIN snapshot_stats ss ON ss.session_id = p.id
 ORDER BY p.started_at DESC, p.id DESC
"#;

/// Execute the shared projection for one List page or one Get row.
async fn load_sessions(
    state: &Arc<AppState>,
    user_id: i32,
    session_id: Option<i32>,
    cursor: Option<PageKey>,
    limit: i64,
) -> Result<Vec<ReadingSessionResource>, ApiError> {
    let connection = db::checkout(state).await?;
    let cursor_time: Option<DateTime<Utc>> = cursor
        .map(|key| DateTime::<Utc>::from_timestamp_micros(key.micros).ok_or_else(bad_page_token))
        .transpose()?;
    let cursor_id: Option<i32> = cursor.map(|key| key.id);

    // One bounded statement: the page CTE fixes the row set, then the
    // aggregate CTEs join to it. No correlated subquery and no per-row fetch.
    let rows = connection
        .query(
            SESSION_PAGE_SQL,
            &[&user_id, &session_id, &cursor_time, &cursor_id, &limit],
        )
        .await
        .map_err(db::query_error)?;

    let mut resources = Vec::with_capacity(rows.len());
    for row in &rows {
        let id: i32 = row.try_get(0).map_err(row_error)?;
        let started: DateTime<Utc> = row.try_get(1).map_err(row_error)?;
        let ended: Option<DateTime<Utc>> = row.try_get(2).map_err(row_error)?;
        let start_die: i32 = row.try_get(3).map_err(row_error)?;
        let manual_die: Option<i32> = row.try_get(4).map_err(row_error)?;
        let zone: Option<String> = row.try_get(5).map_err(row_error)?;
        let event_count: i32 = row.try_get(6).map_err(row_error)?;
        let snapshot_count: i32 = row.try_get(7).map_err(row_error)?;
        let latest_die: Option<i32> = row.try_get(8).map_err(row_error)?;
        let latest_context: Option<String> = row.try_get(9).map_err(row_error)?;
        let ladder: Option<Vec<i32>> = row.try_get(10).map_err(row_error)?;

        let latest = latest_die.map(|die| {
            let context: Value = latest_context
                .as_deref()
                .and_then(|raw| serde_json::from_str(raw).ok())
                .unwrap_or(Value::Null);
            // Keep the parsed context alive for `current_die` without cloning
            // the whole row set: it is consumed immediately below.
            (die, context)
        });
        let resolved = current_die(
            manual_die,
            latest.as_ref().map(|(die, context)| (*die, context)),
            start_die,
        );

        resources.push(ReadingSessionResource {
            name: format!("readingSessions/{id}"),
            session_id: id,
            started_at: timestamp(started),
            ended_at: ended.map(timestamp),
            start_die,
            current_die: resolved,
            ladder_path: ladder_path(start_die, ladder.as_deref().unwrap_or(&[])),
            event_count,
            snapshot_count,
            timezone: zone,
        });
    }
    Ok(resources)
}

/// `GET /api/v2/readingSessions` — standard AIP-132 List.
pub async fn list_reading_sessions(
    Query(query): Query<ListReadingSessionsQuery>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<ListReadingSessionsResponse>, ApiError> {
    let page_size = query.page_size.unwrap_or(DEFAULT_PAGE_SIZE);
    if !(1..=MAX_PAGE_SIZE).contains(&page_size) {
        return Err(bad_page_size());
    }
    let cursor = query
        .page_token
        .as_deref()
        .filter(|token| !token.is_empty())
        .map(parse_page_token)
        .transpose()?;
    // Fetch one extra row to know whether a continuation is needed.
    let limit = i64::from(page_size)
        .checked_add(1)
        .ok_or_else(bad_page_size)?;
    let mut rows = load_sessions(&state, user.id(), None, cursor, limit).await?;
    let has_more = rows.len() > page_size as usize;
    if has_more {
        rows.truncate(page_size as usize);
    }
    let next_page_token = if has_more {
        rows.last().map(|session| {
            let micros = DateTime::parse_from_rfc3339(&session.started_at)
                .map(|value| value.timestamp_micros())
                .unwrap_or(0);
            encode_page_token(PageKey {
                micros,
                id: session.session_id,
            })
        })
    } else {
        None
    };
    Ok(Json(ListReadingSessionsResponse {
        reading_sessions: rows,
        next_page_token,
    }))
}

/// `GET /api/v2/readingSessions/{session_id}` — standard AIP-121 Get.
pub async fn get_reading_session(
    Path(session_id): Path<i32>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<ReadingSessionResource>, ApiError> {
    let mut rows = load_sessions(&state, user.id(), Some(session_id), None, 1).await?;
    if rows.is_empty() {
        return Err(ApiError::NotFound("Session not found".to_string()));
    }
    Ok(Json(rows.remove(0)))
}

/// Documentation-only List operation for the canonical collection.
#[utoipa::path(
    get,
    path = "/api/v2/readingSessions",
    tag = "sessions",
    params(
        ("page_size" = Option<i32>, Query, description = "Bounded page size (1-100, default 50)"),
        ("page_token" = Option<String>, Query, description = "Opaque continuation token")
    ),
    responses(
        (status = 200, description = "One page of event-derived reading sessions", body = ListReadingSessionsResponse),
        (status = 400, description = "Invalid page size or token"),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_reading_sessions_documentation() {}

/// Documentation-only Get operation for the canonical collection.
#[utoipa::path(
    get,
    path = "/api/v2/readingSessions/{session_id}",
    tag = "sessions",
    params(("session_id" = i32, Path, description = "Owned reading session")),
    responses(
        (status = 200, description = "Event-derived reading session", body = ReadingSessionResource),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Session not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_reading_session_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn page_token_round_trips_and_rejects_forged_values() {
        let key = PageKey {
            micros: 1_767_000_000_000_000,
            id: 42,
        };
        let token = encode_page_token(key);
        assert_eq!(parse_page_token(&token).expect("valid token"), key);

        let forged_tokens = vec![
            String::new(),
            "not-base64!".to_string(),
            "e30".to_string(),
            URL_SAFE_NO_PAD.encode("{\"t\":1}"),
            URL_SAFE_NO_PAD.encode("{\"t\":1,\"id\":0}"),
            URL_SAFE_NO_PAD.encode("{\"t\":999999999999999999999,\"id\":1}"),
        ];
        for forged in forged_tokens {
            assert!(
                parse_page_token(&forged).is_err(),
                "forged token {forged:?} must be rejected before SQL"
            );
        }
    }

    #[test]
    fn page_size_is_clamped_to_the_bounded_range() {
        const { assert!(DEFAULT_PAGE_SIZE >= 1 && DEFAULT_PAGE_SIZE <= MAX_PAGE_SIZE) };
        for invalid in [0, -1, MAX_PAGE_SIZE + 1, i32::MAX] {
            let query = ListReadingSessionsQuery {
                page_size: Some(invalid),
                page_token: None,
            };
            assert!(!(1..=MAX_PAGE_SIZE).contains(&query.page_size.unwrap()));
        }
        let limit = i64::from(MAX_PAGE_SIZE).checked_add(1).expect("bounded");
        assert_eq!(limit, 101);
    }

    #[test]
    fn openapi_publishes_canonical_collection_and_no_hyphenated_alias() {
        let document =
            serde_json::to_value(crate::openapi::canonical_openapi()).expect("openapi document");
        let paths = document["paths"].as_object().expect("paths");
        for path in [
            "/api/v2/readingSessions",
            "/api/v2/readingSessions/{session_id}",
            "/api/v2/readingSessions/{session_id}/details",
            "/api/v2/readingSessions/{session_id}/snapshots",
        ] {
            assert!(paths.contains_key(path), "missing canonical path {path}");
        }
        assert!(!paths.contains_key("/api/v2/reading-sessions"));
        assert!(!paths.contains_key("/api/v2/reading-sessions/{session_id}/details"));
        assert!(!paths.contains_key("/api/v1/sessions/{session_id}"));
        assert!(document["components"]["schemas"]["ReadingSessionResource"].is_object());
        assert!(document["components"]["schemas"]["ListReadingSessionsResponse"].is_object());
    }

    #[test]
    fn resource_name_is_aip_122_stable_and_keys_are_wire_compatible() {
        let resource = ReadingSessionResource {
            name: "readingSessions/7".to_string(),
            session_id: 7,
            started_at: "2026-11-27T00:00:00.000000Z".to_string(),
            ended_at: None,
            start_die: 6,
            current_die: 8,
            ladder_path: "6 → 8".to_string(),
            event_count: 3,
            snapshot_count: 1,
            timezone: Some("UTC".to_string()),
        };
        let wire = serde_json::to_value(&resource).expect("serialize");
        assert_eq!(wire["name"].as_str(), Some("readingSessions/7"));
        assert_eq!(wire["session_id"].as_i64(), Some(7));
        assert!(wire.get("next_page_token").is_none());
    }
}
