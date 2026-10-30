//! Native session bootstrap. No public route is mounted until full endpoint parity.
//! All writes share Python's per-user advisory transaction lock and commit atomically
//! with the full-library undo checkpoint. Pure resolution never changes durable state.
use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::http::StatusCode;
use deadpool_postgres::Object;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
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
        "Invalid reading session state",
    )
}
pub(crate) fn decode_session(row: &tokio_postgres::Row) -> Result<ReadingSession, ApiError> {
    serde_json::from_str(row.try_get::<_, &str>(0).map_err(session_error)?)
        .map_err(|_| corrupt())
}
const RESOLVE: &str = "SELECT row_to_json(s)::text FROM sessions s LEFT JOIN LATERAL
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
    tx.query_opt(RESOLVE, &[&user.id(), &now, &policy.gap_hours])
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
        "Database temporarily unavailable",
    )))
}
fn session_error(error: tokio_postgres::Error) -> ApiError {
    if error.code() == Some(&tokio_postgres::error::SqlState::T_R_DEADLOCK_DETECTED) {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Reading session deadlock",
        )
    } else {
        db::query_error(error)
    }
}
async fn bootstrap_once(
    state: &AppState,
    user: AuthenticatedUser,
    timezone: Option<&str>,
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
        // Same lock key as Python get_or_create, held through initialization and snapshot.
        tx.query_one(
            "SELECT pg_advisory_xact_lock($1::bigint)",
            &[&(user.id() as i64)],
        )
        .await
        .map_err(session_error)?;
        if tx
            .query_opt(
                "SELECT id FROM users WHERE id = $1 FOR KEY SHARE",
                &[&user.id()],
            )
            .await
            .map_err(session_error)?
            .is_none()
        {
            return Err(ApiError(
                StatusCode::UNAUTHORIZED,
                "Could not validate credentials",
            ));
        }
        let existing = resolve_current_session(&tx, user, now, policy).await?;
        let created = existing.is_none();
        let mut session = match existing {
            Some(s) => s,
            None => decode_session(
                &tx.query_one(
                    "INSERT INTO sessions (user_id, started_at,
              start_die, reading_mode_suggested) VALUES ($1,to_timestamp($2),$3,false)
              RETURNING row_to_json(sessions)::text",
                    &[&user.id(), &now, &policy.start_die],
                )
                .await
                .map_err(session_error)?,
            )?,
        };
        validate_pending(&tx, user, &session).await?;
        if session.bandwidth_source.is_none() {
            tx.batch_execute("SAVEPOINT bandwidth_inference")
                .await
                .map_err(session_error)?;
            // Python's first history SELECT autoflushes a new ORM session, so
            // started_at is available before infer_bandwidth applies its daypart.
            let prediction =
                super::session_bandwidth::predict(&tx, user, Some(&session.started_at)).await;
            let (level, confidence) = match prediction {
                Ok(prediction) => prediction,
                Err(_) => {
                    tx.batch_execute("ROLLBACK TO SAVEPOINT bandwidth_inference")
                        .await
                        .map_err(session_error)?;
                    tracing::warn!("bandwidth inference failed; using balanced default");
                    ("balanced", 0.1)
                }
            };
            tx.batch_execute("RELEASE SAVEPOINT bandwidth_inference")
                .await
                .map_err(session_error)?;
            tx.execute(
                "UPDATE sessions SET predicted_bandwidth=$2, active_bandwidth=$2,
              bandwidth_confidence=$3, bandwidth_source='inferred', bandwidth_version='v1',
              bandwidth_updated_at=to_timestamp($4) WHERE id=$1 AND user_id=$5",
                &[&session.id, &level, &confidence, &now, &user.id()],
            )
            .await
            .map_err(session_error)?;
        }
        session = decode_session(
            &tx.query_one(
                "SELECT row_to_json(s)::text FROM sessions s WHERE id=$1 AND user_id=$2",
                &[&session.id, &user.id()],
            )
            .await
            .map_err(session_error)?,
        )?;
        if created {
            checkpoint(&tx, user, &session, now).await?;
        }
        // Python captures the browser timezone after the session-start checkpoint.
        if let Some(zone) = timezone
            .filter(|_| session.timezone.is_none())
            .and_then(browser_timezone)
        {
            tx.execute(
                "UPDATE sessions SET timezone=$2 WHERE id=$1 AND user_id=$3",
                &[&session.id, &zone, &user.id()],
            )
            .await
            .map_err(session_error)?;
            session.timezone = Some(zone);
        }
        let (current_die, automatic_die) = dice(&tx, &session).await?;
        tx.commit().await.map_err(session_error)?;
        Ok(SessionBootstrap {
            session,
            current_die,
            automatic_die,
            created,
        })
    })
    .await;
    match result {
        Err(_) => Err(ApiError(
            StatusCode::SERVICE_UNAVAILABLE,
            "Database temporarily unavailable",
        )),
        Ok(result) => {
            if result.is_ok() {
                drop(pending.0.take());
            }
            result
        }
    }
}

async fn validate_pending(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    session: &ReadingSession,
) -> Result<(), ApiError> {
    let valid: bool = tx
        .query_one(
            "SELECT
      ($2::int IS NULL OR EXISTS (SELECT 1 FROM threads WHERE id=$2 AND user_id=$1))
      AND ($3::int IS NULL OR EXISTS (SELECT 1 FROM issues i JOIN threads t ON t.id=i.thread_id
        WHERE i.id=$3 AND t.user_id=$1 AND ($2::int IS NULL OR i.thread_id=$2)))",
            &[
                &user.id(),
                &session.pending_thread_id,
                &session.pending_issue_id,
            ],
        )
        .await
        .map_err(session_error)?
        .get(0);
    if valid {
        Ok(())
    } else {
        Err(corrupt())
    }
}

// PostgreSQL JSON timestamps omit trailing zeroes; checkpoints use Python isoformat.
pub(crate) fn python_timestamp(value: &mut Value) {
    if let Some(s) = value.as_str() {
        if let Some((head, offset)) = s.rsplit_once('+') {
            let normalized = if let Some((seconds, fraction)) = head.split_once('.') {
                format!("{seconds}.{fraction:0<6}+{offset}")
            } else {
                format!("{head}+{offset}")
            };
            *value = Value::String(normalized);
        }
    }
}
async fn checkpoint(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    session: &ReadingSession,
    now: f64,
) -> Result<(), ApiError> {
    let rows = tx
        .query(
            "SELECT row_to_json(t)::text FROM threads t WHERE user_id=$1 ORDER BY id FOR UPDATE",
            &[&user.id()],
        )
        .await
        .map_err(session_error)?;
    let issues = tx.query("SELECT row_to_json(i)::text FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=$1 ORDER BY i.position, i.id", &[&user.id()])
        .await.map_err(session_error)?;
    let mut by_thread = std::collections::HashMap::<i64, Vec<Value>>::new();
    for row in issues {
        let mut i: Value = serde_json::from_str(row.get(0)).map_err(|_| corrupt())?;
        python_timestamp(&mut i["read_at"]);
        by_thread
            .entry(i["thread_id"].as_i64().ok_or_else(corrupt)?)
            .or_default()
            .push(json!({
            "id": i["id"], "number": i["issue_number"], "status": i["status"],
            "read_at": i["read_at"], "position": i["position"] }));
    }
    let mut threads = serde_json::Map::new();
    for row in rows {
        let mut t: Value = serde_json::from_str(row.get(0)).map_err(|_| corrupt())?;
        for key in ["last_activity_at", "created_at"] {
            python_timestamp(&mut t[key]);
        }
        let tracking = !t["total_issues"].is_null();
        let mut capture = serde_json::Map::new();
        for key in [
            "title",
            "format",
            "issues_remaining",
            "last_rating",
            "last_activity_at",
            "queue_position",
            "queue_position_is_manual",
            "status",
            "notes",
            "is_test",
            "is_blocked",
            "created_at",
            "user_id",
        ] {
            capture.insert(key.into(), t[key].clone());
        }
        capture.insert("uses_issue_tracking".into(), json!(tracking));
        capture.insert(
            "issue_states".into(),
            if tracking {
                json!(by_thread
                    .remove(&t["id"].as_i64().ok_or_else(corrupt)?)
                    .unwrap_or_default())
            } else {
                Value::Null
            },
        );
        for key in ["total_issues", "next_unread_issue_id", "reading_progress"] {
            capture.insert(
                key.into(),
                if tracking {
                    t[key].clone()
                } else {
                    Value::Null
                },
            );
        }
        threads.insert(t["id"].to_string(), Value::Object(capture));
    }
    let mut session_state = serde_json::to_value(session).map_err(|_| corrupt())?;
    let keys = [
        "start_die",
        "manual_die",
        "snoozed_thread_ids",
        "active_bandwidth",
        "predicted_bandwidth",
        "bandwidth_confidence",
        "bandwidth_source",
        "bandwidth_version",
        "active_intent",
        "predicted_intent",
        "intent_confidence",
        "intent_source",
        "intent_version",
    ];
    session_state
        .as_object_mut()
        .ok_or_else(corrupt)?
        .retain(|key, _| keys.contains(&key.as_str()));
    session_state["current_die"] = json!(session.start_die);
    let threads = Value::Object(threads).to_string();
    let session_state = session_state.to_string();
    tx.execute("INSERT INTO snapshots (session_id,event_id,thread_states,session_state,created_at,description,snapshot_kind,schema_version)
      VALUES ($1,NULL,$2::text::json,$3::text::json,to_timestamp($4),'Session start','session_start',NULL)",
      &[&session.id,&threads,&session_state,&now]).await.map_err(session_error)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
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
}
