//! Native same-path session details read (#4839, parent #4335).
//!
//! Migrates the session-details subset of `app/api/session.py` to the native
//! Rust router with identical method/path and wire contract:
//!
//! * `GET /api/sessions/{session_id}/details`
//! * `GET /api/v1/sessions/{session_id}/details`
//!
//! Wire parity with Python `get_session_details` (`app/api/session.py`):
//!
//! * Ownership: `get_owned_session_or_404` — a foreign or missing session
//!   returns 404 with the exact detail `"Session not found"`.
//! * Events: all events for the session ordered by timestamp DESC, id DESC,
//!   projected through `build_session_event_details` (same fields as Python).
//! * `ladder_path`: `build_ladder_path` — `start_die` followed by every
//!   `die_after` from `rate`/`snooze`/`undo`/`restore`/`manual_die`/`reset_dice`
//!   events in timestamp/id order, joined with `" → "`.
//! * `narrative_summary`: `build_narrative_summary` — short textual summary.
//! * `current_die`: event-derived die wins (#4352).
//! * `timezone` from session.
//! * Timestamps are emitted as UTC `...Z` strings.
//!
//! Bounded reads only: one session row, one event read, one ladder-path read,
//! one current-die read, one narrative summary read. Python handlers remain;
//! deployed ingress in `vercel.json` shadows them after this cutover.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, reading_session::automatic_die_after, ApiError, AppState};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::sync::Arc;

/// Event detail matching Python `build_session_event_details` output.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SessionEventDetail {
    pub id: i32,
    pub type: String,
    pub timestamp: String,
    pub thread_id: Option<i32>,
    pub selected_thread_id: Option<i32>,
    pub die: Option<i32>,
    pub die_after: Option<i32>,
    pub result: Option<i32>,
    pub rating: Option<f64>,
    pub issues_read: Option<i32>,
    pub issue_id: Option<i32>,
    pub issue_number: Option<String>,
    pub context: Option<Value>,
}

/// Wire shape of Python `SessionDetailsResponse` for `get_session_details`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct SessionDetailsResponse {
    pub session_id: i32,
    pub started_at: String,
    pub ended_at: Option<String>,
    pub start_die: i32,
    pub ladder_path: String,
    pub narrative_summary: String,
    pub current_die: i32,
    pub timezone: Option<String>,
    pub events: Vec<SessionEventDetail>,
}

const SESSION_DETAIL_SQL: &str = "SELECT id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), start_die, timezone FROM sessions WHERE id = $1 AND user_id = $2";
const LADDER_SQL: &str = "SELECT die_after FROM events WHERE session_id = $1 AND type IN ('rate','snooze','undo','restore','manual_die','reset_dice') AND die_after IS NOT NULL ORDER BY timestamp ASC, id ASC";
const CURRENT_DIE_SQL: &str = "SELECT die_after, context::text FROM events WHERE session_id = $1 AND type IN ('rate','snooze','undo','restore','manual_die','reset_dice') AND die_after IS NOT NULL ORDER BY timestamp DESC, id DESC LIMIT 1";
const EVENTS_SQL: &str = "SELECT id, type, to_char(timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), thread_id, selected_thread_id, die, die_after, result, rating, issues_read, issue_id, issue_number, context::text FROM events WHERE session_id = $1 ORDER BY timestamp DESC, id DESC";

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
///
/// Event-derived die wins (#4352): the manual_die column is a legacy
/// fallback only when the session has no die-changing events.
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

/// Python `build_narrative_summary` — simplified version matching the Python output.
/// The Python version in `app/services/summary_service.py` builds a short summary
/// from the session events.
fn build_narrative_summary(events: &[SessionEventDetail], start_die: i32) -> String {
    if events.is_empty() {
        return format!("Started with d{}", start_die);
    }

    let mut parts = Vec::new();
    for event in events {
        match event.type.as_str() {
            "roll" => {
                if let Some(result) = event.result {
                    parts.push(format!("rolled {}", result));
                } else {
                    parts.push("rolled".to_string());
                }
            }
            "rate" => {
                if let (Some(issues_read), Some(rating)) = (event.issues_read, event.rating) {
                    parts.push(format!("rated {} issues {:.1}", issues_read, rating));
                } else if let Some(rating) = event.rating {
                    parts.push(format!("rated {:.1}", rating));
                } else {
                    parts.push("rated".to_string());
                }
            }
            "snooze" => {
                parts.push("snoozed".to_string());
            }
            "undo" => {
                parts.push("undid".to_string());
            }
            "reset_dice" => {
                parts.push("reset dice".to_string());
            }
            "manual_die" => {
                if let Some(die) = event.die {
                    parts.push(format!("set die to {}", die));
                } else {
                    parts.push("set die".to_string());
                }
            }
            "restore" => {
                parts.push("restored".to_string());
            }
            _ => {
                parts.push(event.type.clone());
            }
        }
    }

    if parts.is_empty() {
        format!("Started with d{}", start_die)
    } else {
        format!("Started with d{} → {}", start_die, parts.join(" → "))
    }
}

/// `GET /api/sessions/{session_id}/details` and `GET /api/v1/sessions/{session_id}/details`.
pub async fn get_session_details(
    Path(session_id): Path<i32>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<SessionDetailsResponse>, ApiError> {
    let connection = db::checkout(&state).await?;

    let session_row = connection
        .query_opt(SESSION_DETAIL_SQL, &[&session_id, &user.id()])
        .await
        .map_err(db::query_error)?
        .ok_or_else(not_found)?;

    let session_id_db: i32 = session_row.try_get(0).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        internal()
    })?;
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
    let timezone: Option<String> = session_row.try_get(4).map_err(|e| {
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
        .map(|row| {
            row.try_get::<_, i32>(0).map_err(|e| {
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
        .query_opt(CURRENT_DIE_SQL, &[&session_id])
        .await
        .map_err(db::query_error)?;
    let latest_die = match die_row {
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
            Some((die_after, owned))
        }
        None => None,
    };
    let resolved_die = match &latest_die {
        Some((die_after, context)) => {
            current_die(None, Some((*die_after, context)), start_die)
        }
        None => current_die(None, None, start_die),
    };

    // Events
    let event_rows = connection
        .query(EVENTS_SQL, &[&session_id])
        .await
        .map_err(db::query_error)?;
    let mut events = Vec::with_capacity(event_rows.len());
    for row in &event_rows {
        let context_text: Option<String> = row.try_get(12).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            internal()
        })?;
        let context: Option<Value> = context_text
            .as_deref()
            .and_then(|text| serde_json::from_str(text).ok());

        events.push(SessionEventDetail {
            id: row.try_get(0).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            type: row.try_get(1).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            timestamp: row.try_get(2).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            thread_id: row.try_get(3).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            selected_thread_id: row.try_get(4).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            die: row.try_get(5).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            die_after: row.try_get(6).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            result: row.try_get(7).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            rating: row.try_get(8).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            issues_read: row.try_get(9).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            issue_id: row.try_get(10).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            issue_number: row.try_get(11).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                internal()
            })?,
            context,
        });
    }

    let narrative_summary = build_narrative_summary(&events, start_die);

    Ok(Json(SessionDetailsResponse {
        session_id: session_id_db,
        started_at,
        ended_at,
        start_die,
        ladder_path: ladder,
        narrative_summary,
        current_die: resolved_die,
        timezone,
        events,
    }))
}

/// Documentation-only operation for the unversioned mounted read.
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

/// Documentation-only operation for the versioned mounted read.
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
    paths(get_session_details_documentation, get_session_details_v1_documentation),
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
    use serde_json::json;
    use utoipa::OpenApi;

    #[test]
    fn ladder_path_matches_python() {
        assert_eq!(ladder_path(6, &[]), "6");
        assert_eq!(ladder_path(6, &[4, 8]), "6 → 4 → 8");
    }

    #[test]
    fn current_die_is_event_derived_with_manual_fallback() {
        assert_eq!(current_die(Some(10), Some((4, &json!({}))), 6), 4);
        assert_eq!(current_die(Some(0), Some((4, &json!({}))), 6), 4);
        assert_eq!(current_die(Some(10), None, 6), 10);
        assert_eq!(
            current_die(None, Some((4, &json!({"automatic_die_after": 20}))), 6),
            20
        );
        assert_eq!(
            current_die(None, Some((4, &json!({"automatic_die_after": 999}))), 6),
            4
        );
        assert_eq!(current_die(None, None, 8), 8);
        assert_eq!(current_die(Some(0), None, 8), 8);
    }

    #[test]
    fn session_details_sql_is_owner_scoped_and_bounded() {
        assert!(SESSION_DETAIL_SQL.contains("WHERE id = $1 AND user_id = $2"));
        assert!(LADDER_SQL.contains("type IN ('rate','snooze','undo','restore','manual_die','reset_dice')"));
        assert!(CURRENT_DIE_SQL.contains("ORDER BY timestamp DESC, id DESC LIMIT 1"));
        assert!(EVENTS_SQL.contains("ORDER BY timestamp DESC, id DESC"));
    }

    #[test]
    fn session_details_openapi_covers_both_same_paths() {
        let document = serde_json::to_value(SessionDetailsApi::openapi()).expect("openapi");
        let paths = document["paths"].as_object().expect("paths");
        assert!(paths.contains_key("/api/sessions/{session_id}/details"));
        assert!(paths.contains_key("/api/v1/sessions/{session_id}/details"));
        for path in ["/api/sessions/{session_id}/details", "/api/v1/sessions/{session_id}/details"] {
            let operation = &document["paths"][path]["get"];
            assert!(operation["operationId"].is_string());
            assert!(operation["responses"]["200"].as_object().is_some());
            assert!(operation["responses"]["404"].as_object().is_some());
            assert!(operation["security"].is_array());
        }
        assert!(document["components"]["schemas"]["SessionDetailsResponse"].is_object());
        assert!(document["components"]["schemas"]["SessionEventDetail"].is_object());
    }

    #[test]
    fn narrative_summary_matches_python_basic_cases() {
        // Empty events
        assert_eq!(build_narrative_summary(&[], 6), "Started with d6");

        // Single roll event
        let events = vec![SessionEventDetail {
            id: 1,
            type: "roll".to_string(),
            timestamp: "2026-01-01T00:00:00.000Z".to_string(),
            thread_id: Some(1),
            selected_thread_id: Some(1),
            die: Some(6),
            die_after: None,
            result: Some(4),
            rating: None,
            issues_read: None,
            issue_id: None,
            issue_number: None,
            context: None,
        }];
        assert_eq!(build_narrative_summary(&events, 6), "Started with d6 → rolled 4");

        // Rate event
        let events = vec![SessionEventDetail {
            id: 1,
            type: "rate".to_string(),
            timestamp: "2026-01-01T00:00:00.000Z".to_string(),
            thread_id: Some(1),
            selected_thread_id: None,
            die: None,
            die_after: Some(4),
            result: None,
            rating: Some(4.5),
            issues_read: Some(3),
            issue_id: None,
            issue_number: None,
            context: None,
        }];
        assert_eq!(build_narrative_summary(&events, 6), "Started with d6 → rated 3 issues 4.5");
    }
}