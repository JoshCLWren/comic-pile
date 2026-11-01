//! Native session bootstrap. No public route is mounted until full endpoint parity.
//! All writes share Python's per-user advisory transaction lock and commit atomically
//! with the full-library undo checkpoint. Pure resolution never changes durable state.
use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::http::StatusCode;
use deadpool_postgres::Object;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    path::{Component, Path},
    time::{SystemTime, UNIX_EPOCH},
};
use tokio_postgres::Transaction;

/// Python-compatible session policy, validated before database work.
#[derive(Clone, Copy)]
pub struct SessionPolicy {
    pub gap_hours: i32,
    pub start_die: i32,
}
impl SessionPolicy {
    pub fn new(gap_hours: i32, start_die: i32) -> Result<Self, &'static str> {
        if !(1..=168).contains(&gap_hours) || !(4..=20).contains(&start_die) {
            return Err("invalid reading session policy");
        }
        Ok(Self {
            gap_hours,
            start_die,
        })
    }
}
impl Default for SessionPolicy {
    fn default() -> Self {
        Self {
            gap_hours: 6,
            start_die: 6,
        }
    }
}

/// Complete persisted session state, independent of response assembly (#4309).
#[derive(Debug, Serialize, Deserialize)]
pub struct ReadingSession {
    pub id: i32,
    pub user_id: i32,
    pub started_at: String,
    pub ended_at: Option<String>,
    pub start_die: i32,
    pub manual_die: Option<i32>,
    pub pending_thread_id: Option<i32>,
    pub pending_issue_id: Option<i32>,
    pub pending_thread_updated_at: Option<String>,
    pub snoozed_thread_ids: Option<Vec<i32>>,
    pub skipped_thread_ids: Option<Vec<i32>>,
    pub timezone: Option<String>,
    pub predicted_bandwidth: Option<String>,
    pub active_bandwidth: Option<String>,
    pub bandwidth_confidence: Option<f64>,
    pub bandwidth_source: Option<String>,
    pub bandwidth_version: Option<String>,
    pub bandwidth_updated_at: Option<String>,
    pub reading_bandwidth: Option<String>,
    pub reading_intent: Option<String>,
    pub reading_mode_source: Option<String>,
    pub reading_mode_suggested: bool,
    pub active_intent: Option<String>,
    pub predicted_intent: Option<String>,
    pub intent_confidence: Option<f64>,
    pub intent_source: Option<String>,
    pub intent_version: Option<String>,
    pub session_mode_correction_guidance: Option<Value>,
}
#[derive(Debug, Serialize)]
pub struct SessionBootstrap {
    pub session: ReadingSession,
    pub current_die: i32,
    pub automatic_die: i32,
    pub created: bool,
}
fn corrupt() -> ApiError {
    ApiError(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Invalid reading session state".to_string(),
    )
}
fn decode_session(row: &tokio_postgres::Row) -> Result<ReadingSession, ApiError> {
    let json = row.try_get::<_, &str>(0).map_err(session_error)?;
    decode_session_json(json)
}

/// Decode one session row, normalizing fields whose persisted JSON shape drifted.
///
/// `row_to_json` always emits valid JSON, so a deserialization failure means a
/// persisted column no longer matches [`ReadingSession`] (for example a legacy
/// `NULL` boolean or a malformed JSON list). Replacing the whole session would
/// drop the pending roll and its durable events, and an unrepaired session makes
/// every Roll bootstrap return 500 until some other actor ends it. Repair only
/// the individually unreadable fields and keep the session identity so pending
/// state, events and roll results survive.
fn decode_session_json(json: &str) -> Result<ReadingSession, ApiError> {
    match serde_json::from_str(json) {
        Ok(session) => Ok(session),
        Err(_) => {
            let mut value: Value = serde_json::from_str(json).map_err(|_| corrupt())?;
            let repaired = repair_session_value(&mut value);
            if repaired.is_empty() {
                return Err(corrupt());
            }
            let session: ReadingSession = serde_json::from_value(value).map_err(|_| corrupt())?;
            tracing::warn!(
                session_id = session.id,
                fields = ?repaired,
                "repaired reading session fields with unusable values"
            );
            Ok(session)
        }
    }
}

/// Null out optional session fields that do not deserialize, and coerce the one
/// required boolean. Required identity fields are left alone so genuine schema
/// corruption still fails closed instead of fabricating a session.
fn repair_session_value(value: &mut Value) -> Vec<&'static str> {
    fn repair_optional<T: serde::de::DeserializeOwned>(
        object: &mut serde_json::Map<String, Value>,
        key: &'static str,
        repaired: &mut Vec<&'static str>,
    ) {
        let Some(field) = object.get_mut(key) else {
            return;
        };
        if serde_json::from_value::<Option<T>>(field.clone()).is_err() {
            *field = Value::Null;
            repaired.push(key);
        }
    }
    let Some(object) = value.as_object_mut() else {
        return Vec::new();
    };
    let mut repaired = Vec::new();
    for key in ["manual_die", "pending_thread_id", "pending_issue_id"] {
        repair_optional::<i32>(object, key, &mut repaired);
    }
    for key in ["snoozed_thread_ids", "skipped_thread_ids"] {
        repair_optional::<Vec<i32>>(object, key, &mut repaired);
    }
    for key in [
        "ended_at",
        "pending_thread_updated_at",
        "timezone",
        "predicted_bandwidth",
        "active_bandwidth",
        "bandwidth_source",
        "bandwidth_version",
        "bandwidth_updated_at",
        "reading_bandwidth",
        "reading_intent",
        "reading_mode_source",
        "active_intent",
        "predicted_intent",
        "intent_source",
        "intent_version",
    ] {
        repair_optional::<String>(object, key, &mut repaired);
    }
    for key in ["bandwidth_confidence", "intent_confidence"] {
        repair_optional::<f64>(object, key, &mut repaired);
    }
    if let Some(field) = object.get_mut("reading_mode_suggested") {
        if !field.is_boolean() {
            *field = Value::Bool(false);
            repaired.push("reading_mode_suggested");
        }
    }
    repaired
}
const RESOLVE_FROM: &str = "FROM sessions s LEFT JOIN LATERAL
 (SELECT max(timestamp) AS last_event FROM events WHERE session_id = s.id) e ON true
 WHERE s.user_id = $1 AND s.ended_at IS NULL
 AND greatest(s.started_at, CASE WHEN s.pending_thread_id IS NOT NULL OR s.pending_issue_id IS NOT NULL
 THEN s.pending_thread_updated_at END, e.last_event) >= to_timestamp($2) - make_interval(hours => $3)
 ORDER BY (s.pending_thread_id IS NOT NULL OR s.pending_issue_id IS NOT NULL) DESC,
 greatest(s.started_at, CASE WHEN s.pending_thread_id IS NOT NULL OR s.pending_issue_id IS NOT NULL
 THEN s.pending_thread_updated_at END, e.last_event) DESC, s.started_at DESC, s.id DESC LIMIT 1";

/// Read-only authority lookup; takes a caller-owned transaction and injected UTC clock.
pub async fn resolve_current_session(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    now: f64,
    policy: SessionPolicy,
) -> Result<Option<ReadingSession>, ApiError> {
    let sql = format!("SELECT row_to_json(s)::text {RESOLVE_FROM}");
    tx.query_opt(&sql, &[&user.id(), &now, &policy.gap_hours])
        .await
        .map_err(session_error)?
        .as_ref()
        .map(decode_session)
        .transpose()
}

/// Resolve the suspended automatic die, excluding booleans, floats and invalid ladder sizes.
pub fn automatic_die_after(die_after: i32, context: &Value) -> i32 {
    context
        .get("automatic_die_after")
        .and_then(Value::as_i64)
        .filter(|v| [4, 6, 8, 10, 12, 20, 30, 50, 100].contains(v))
        .map(|v| v as i32)
        .unwrap_or(die_after)
}
pub(crate) async fn dice(
    tx: &Transaction<'_>,
    session: &ReadingSession,
) -> Result<(i32, i32), ApiError> {
    let row = tx.query_opt("SELECT die_after, context::text FROM events WHERE session_id = $1
      AND type IN ('rate','snooze','undo') AND die_after IS NOT NULL ORDER BY timestamp DESC, id DESC LIMIT 1",
      &[&session.id]).await.map_err(session_error)?;
    let automatic = if let Some(row) = row {
        let context: Option<&str> = row.try_get(1).map_err(session_error)?;
        automatic_die_after(
            row.try_get(0).map_err(session_error)?,
            &context
                .and_then(|s| serde_json::from_str(s).ok())
                .unwrap_or(Value::Null),
        )
    } else {
        session.start_die
    };
    // Python truthiness: a legacy zero override is not a manual selection.
    Ok((
        session.manual_die.filter(|v| *v != 0).unwrap_or(automatic),
        automatic,
    ))
}

/// Same IANA tzdata as Python ZoneInfo. Reject path traversal before filesystem lookup.
/// Deployments must install tzdata; invalid/missing browser zones are a soft failure.
pub fn browser_timezone(value: &str) -> Option<String> {
    let value = value.trim();
    let path = Path::new(value);
    if value.is_empty()
        || value.chars().count() > 100
        || path.is_absolute()
        || path
            .components()
            .any(|p| !matches!(p, Component::Normal(_)))
        || value
            .split('/')
            .any(|p| p.is_empty() || p == "." || p == "..")
    {
        return None;
    }
    let bytes = std::fs::read(Path::new("/usr/share/zoneinfo").join(path)).ok()?;
    bytes.starts_with(b"TZif").then(|| value.to_owned())
}

// Discard a connection on outer cancellation, query timeout, or aborted transaction.
struct Pending(Option<Object>);
impl Drop for Pending {
    fn drop(&mut self) {
        if let Some(c) = self.0.take() {
            drop(Object::take(c));
        }
    }
}

/// Bootstrap with a real clock. Caller must pass the same policy as the Python backend.
pub async fn bootstrap(
    state: &AppState,
    user: AuthenticatedUser,
    timezone: Option<&str>,
    policy: SessionPolicy,
) -> Result<SessionBootstrap, ApiError> {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| corrupt())?
        .as_secs_f64();
    bootstrap_at(state, user, timezone, policy, now).await
}

/// Bounded, cancellation-safe transactional entry point with deterministic clock for parity.
/// This GET creates/initializes sessions only; it never rolls, cancels, rates or reorders.
pub async fn bootstrap_at(
    state: &AppState,
    user: AuthenticatedUser,
    timezone: Option<&str>,
    policy: SessionPolicy,
    now: f64,
) -> Result<SessionBootstrap, ApiError> {
    tokio::time::timeout(state.request_timeout, async {
        for attempt in 0..3 {
            let result = bootstrap_once(state, user, timezone, policy, now).await;
            if !matches!(&result, Err(e) if e.1 == "Reading session deadlock") || attempt == 2 {
                return result;
            }
            tokio::time::sleep(std::time::Duration::from_millis(100 << attempt)).await;
        }
        unreachable!()
    })
    .await
    .unwrap_or(Err(ApiError(
        StatusCode::SERVICE_UNAVAILABLE,
        "Database temporarily unavailable".to_string(),
    )))
}
fn session_error(error: tokio_postgres::Error) -> ApiError {
    if error.code() == Some(&tokio_postgres::error::SqlState::T_R_DEADLOCK_DETECTED) {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Reading session deadlock".to_string(),
        )
    } else {
        db::query_error(error)
    }
}
async fn bootstrap_once(
    state: &AppState,
    user: AuthenticatedUser,
    _timezone: Option<&str>,
    policy: SessionPolicy,
    now: f64,
) -> Result<SessionBootstrap, ApiError> {
    SessionPolicy::new(policy.gap_hours, policy.start_die).map_err(|_| corrupt())?;
    if !now.is_finite() {
        return Err(corrupt());
    }
    let mut pending = Pending(Some(db::checkout(state).await?));
    let result = tokio::time::timeout(state.request_timeout, async {
        let tx = pending
            .0
            .as_mut()
            .unwrap()
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(session_error)?;
        tx.batch_execute("SET LOCAL TIME ZONE 'UTC'")
            .await
            .map_err(session_error)?;
        if tx
            .query_opt("SELECT id FROM users WHERE id = $1", &[&user.id()])
            .await
            .map_err(session_error)?
            .is_none()
        {
            return Err(ApiError(
                StatusCode::UNAUTHORIZED,
                "Could not validate credentials".to_string(),
            ));
        }
        let existing = resolve_current_session(&tx, user, now, policy).await?;
        let mut session = match existing {
            Some(s) => s,
            None => {
                return Err(ApiError(
                    StatusCode::NOT_FOUND,
                    "No active session".to_string(),
                ))
            }
        };
        // Pending selection is disposable UI state. Return a nulled projection for
        // stale pointers without persisting any repair; write paths repair on offer/reset/dismiss.
        let (thread_valid, issue_valid) = pending_validity(
            &tx,
            user,
            session.pending_thread_id,
            session.pending_issue_id,
        )
        .await?;
        if !thread_valid {
            session.pending_thread_id = None;
            session.pending_issue_id = None;
            session.pending_thread_updated_at = None;
        } else if !issue_valid {
            session.pending_issue_id = None;
        }
        // Read-only bootstrap: do not infer bandwidth, checkpoint, or persist timezone.
        // Timezone is returned as stored; client preference is not persisted on GET.
        let (current_die, automatic_die) = dice(&tx, &session).await?;
        // Rollback to guarantee zero writes for the GET path.
        tx.rollback().await.map_err(session_error)?;
        Ok(SessionBootstrap {
            session,
            current_die,
            automatic_die,
            created: false,
        })
    })
    .await;
    match result {
        Err(_) => Err(ApiError(
            StatusCode::SERVICE_UNAVAILABLE,
            "Database temporarily unavailable".to_string(),
        )),
        Ok(result) => {
            if result.is_ok() {
                drop(pending.0.take());
            }
            result
        }
    }
}

/// Return the authoritative current session id without creating a session or
/// writing a checkpoint. Uses the same window and ordering as the Roll/Python
/// resolver so Reset clears the session the rest of the app reads.
pub(crate) async fn current_session_id(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    now: f64,
    policy: SessionPolicy,
) -> Result<Option<i32>, ApiError> {
    let sql = format!("SELECT s.id {RESOLVE_FROM}");
    let row = tx
        .query_opt(&sql, &[&user.id(), &now, &policy.gap_hours])
        .await
        .map_err(session_error)?;
    Ok(row.map(|row| row.get(0)))
}

async fn pending_validity(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    pending_thread_id: Option<i32>,
    pending_issue_id: Option<i32>,
) -> Result<(bool, bool), ApiError> {
    let row = tx
        .query_one(
            "SELECT
      ($2::int IS NULL OR EXISTS (SELECT 1 FROM threads WHERE id=$2 AND user_id=$1)),
      ($3::int IS NULL OR EXISTS (SELECT 1 FROM issues i JOIN threads t ON t.id=i.thread_id
        WHERE i.id=$3 AND t.user_id=$1 AND ($2::int IS NULL OR i.thread_id=$2)))",
            &[&user.id(), &pending_thread_id, &pending_issue_id],
        )
        .await
        .map_err(session_error)?;
    Ok((row.get(0), row.get(1)))
}

// PostgreSQL JSON timestamps omit trailing zeroes; checkpoints use Python isoformat.

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn timezone_validation_and_manual_ladder() {
        assert_eq!(
            browser_timezone(" America/Chicago ").as_deref(),
            Some("America/Chicago")
        );
        for invalid in [
            "",
            "../etc/passwd",
            "/etc/passwd",
            "America//Chicago",
            "No/SuchZone",
        ] {
            assert!(browser_timezone(invalid).is_none());
        }
        assert_eq!(
            automatic_die_after(20, &json!({"automatic_die_after":8})),
            8
        );
        for value in [json!(true), json!(8.0), json!("8"), json!(7), Value::Null] {
            assert_eq!(
                automatic_die_after(20, &json!({"automatic_die_after":value})),
                20
            );
        }
        assert!(SessionPolicy::new(0, 6).is_err());
        assert!(SessionPolicy::new(6, 21).is_err());
    }

    fn session_json() -> Value {
        json!({
            "id": 7,
            "user_id": 3,
            "started_at": "2026-10-29T08:00:00+00:00",
            "ended_at": null,
            "start_die": 6,
            "manual_die": null,
            "pending_thread_id": 11,
            "pending_issue_id": 12,
            "pending_thread_updated_at": "2026-10-29T07:55:00+00:00",
            "snoozed_thread_ids": [11],
            "skipped_thread_ids": null,
            "timezone": null,
            "predicted_bandwidth": null,
            "active_bandwidth": null,
            "bandwidth_confidence": null,
            "bandwidth_source": null,
            "bandwidth_version": null,
            "bandwidth_updated_at": null,
            "reading_bandwidth": null,
            "reading_intent": null,
            "reading_mode_source": null,
            "reading_mode_suggested": true,
            "active_intent": null,
            "predicted_intent": null,
            "intent_confidence": null,
            "intent_source": null,
            "intent_version": null,
            "session_mode_correction_guidance": null
        })
    }

    #[test]
    fn healthy_session_json_needs_no_repair() {
        let session = decode_session_json(&session_json().to_string()).unwrap();
        assert_eq!(session.id, 7);
        assert_eq!(session.pending_thread_id, Some(11));
        assert_eq!(session.snoozed_thread_ids, Some(vec![11]));
        assert!(session.reading_mode_suggested);
    }

    #[test]
    fn unreadable_session_fields_are_repaired_without_losing_pending_state() {
        let mut value = session_json();
        value["snoozed_thread_ids"] = json!({"not": "a list"});
        value["reading_mode_suggested"] = Value::Null;
        let repaired = repair_session_value(&mut value);
        assert_eq!(repaired, ["snoozed_thread_ids", "reading_mode_suggested"]);

        // The same payload that previously produced "Invalid reading session state"
        // now decodes with identity, pending roll and events untouched.
        let session = decode_session_json(&value.to_string()).unwrap();
        assert_eq!(session.id, 7);
        assert_eq!(session.user_id, 3);
        assert_eq!(session.pending_thread_id, Some(11));
        assert_eq!(session.pending_issue_id, Some(12));
        assert_eq!(
            session.pending_thread_updated_at.as_deref(),
            Some("2026-10-29T07:55:00+00:00")
        );
        assert_eq!(session.snoozed_thread_ids, None);
        assert!(!session.reading_mode_suggested);
    }

    #[test]
    fn unrecoverable_session_identity_still_fails_closed() {
        let mut value = session_json();
        value["id"] = json!("not-an-integer");
        let error = decode_session_json(&value.to_string()).unwrap_err();
        assert_eq!(error.1, "Invalid reading session state");
    }

    #[tokio::test]
    async fn stale_pending_pointers_are_detected_for_repair() {
        let Ok(url) = std::env::var("RUST_ROLL_TEST_DATABASE_URL") else {
            return;
        };
        let (admin, connection) = tokio_postgres::connect(&url, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let schema = format!("pending_validity_{}_{}", std::process::id(), nanos);
        admin
            .batch_execute(&format!(
                "CREATE SCHEMA {schema};
                 CREATE TABLE {schema}.users (id integer PRIMARY KEY);
                 CREATE TABLE {schema}.threads (
                     id integer PRIMARY KEY, user_id integer NOT NULL
                 );
                 CREATE TABLE {schema}.issues (
                     id integer PRIMARY KEY, thread_id integer NOT NULL
                 );
                 INSERT INTO {schema}.users VALUES (1), (2);
                 INSERT INTO {schema}.threads VALUES (10, 1), (20, 2);
                 INSERT INTO {schema}.issues VALUES (100, 10), (200, 20);"
            ))
            .await
            .unwrap();
        let (mut client, connection) = tokio_postgres::connect(&url, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        client
            .batch_execute(&format!("SET search_path TO {schema}, public"))
            .await
            .unwrap();
        let tx = client.transaction().await.unwrap();
        let user = AuthenticatedUser::for_test(1);

        assert_eq!(
            pending_validity(&tx, user, Some(10), Some(100))
                .await
                .unwrap(),
            (true, true)
        );
        // Legacy Python Roll can leave an issue from another thread in place.
        assert_eq!(
            pending_validity(&tx, user, Some(10), Some(200))
                .await
                .unwrap(),
            (true, false)
        );
        // A dangling or foreign thread invalidates the whole pending pointer.
        assert_eq!(
            pending_validity(&tx, user, Some(20), None).await.unwrap(),
            (false, true)
        );
        assert_eq!(
            pending_validity(&tx, user, None, None).await.unwrap(),
            (true, true)
        );

        tx.rollback().await.unwrap();
        admin
            .batch_execute(&format!("DROP SCHEMA {schema} CASCADE"))
            .await
            .unwrap();
    }
}
