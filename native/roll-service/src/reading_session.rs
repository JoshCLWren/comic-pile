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
}
fn corrupt() -> ApiError {
    ApiError(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Invalid reading session state",
    )
}
fn decode_session(row: &tokio_postgres::Row) -> Result<ReadingSession, ApiError> {
    serde_json::from_str(row.try_get::<_, &str>(0).map_err(session_error)?).map_err(|_| corrupt())
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
/// Format epoch seconds as the UTC ISO-8601 spelling Python emits.
fn iso_timestamp(seconds: f64) -> String {
    let whole = seconds.trunc();
    let nanos = ((seconds - whole) * 1_000_000_000.0).round() as u32;
    chrono::DateTime::from_timestamp(whole as i64, nanos)
        .map(|value| value.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false))
        .unwrap_or_else(|| seconds.to_string())
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
        let _created = existing.is_none();
        let mut session = match existing {
            Some(s) => s,
            None => {
                // Build the default session in memory only. GET bootstrap must
                // not INSERT; id=0 marks "no persisted session" for this response.
                ReadingSession {
                    id: 0,
                    user_id: user.id(),
                    started_at: iso_timestamp(now),
                    ended_at: None,
                    start_die: policy.start_die,
                    manual_die: None,
                    pending_thread_id: None,
                    pending_issue_id: None,
                    pending_thread_updated_at: None,
                    snoozed_thread_ids: None,
                    skipped_thread_ids: None,
                    timezone: None,
                    predicted_bandwidth: None,
                    active_bandwidth: None,
                    bandwidth_confidence: None,
                    bandwidth_source: None,
                    bandwidth_version: None,
                    bandwidth_updated_at: None,
                    reading_bandwidth: None,
                    reading_intent: None,
                    reading_mode_source: None,
                    reading_mode_suggested: false,
                    active_intent: None,
                    predicted_intent: None,
                    intent_confidence: None,
                    intent_source: None,
                    intent_version: None,
                    session_mode_correction_guidance: None,
                }
            }
        };
        // Pending selection is disposable UI state. A legacy writer can leave
        // a stale issue pointer (or a dangling thread) behind; dropping that
        // pointer must not wedge every native Roll request with a 500.
        // Since this is a GET endpoint, it must be read-only - no writes allowed.
        let (thread_valid, issue_valid) = pending_validity(
            &tx,
            user,
            session.pending_thread_id,
            session.pending_issue_id,
        )
        .await?;
        if !thread_valid {
            // Return nulled pending projection without persisting changes.
            // Repair will happen on write paths (offer/reset/dismiss).
            session.pending_thread_id = None;
            session.pending_issue_id = None;
            session.pending_thread_updated_at = None;
        } else if !issue_valid {
            // Return nulled pending projection without persisting changes.
            // Repair will happen on write paths (offer/reset/dismiss).
            session.pending_issue_id = None;
        }
        // Python captures the browser timezone after the session-start checkpoint.
        // Since this is a GET endpoint, skip timezone update to maintain read-only behavior.
        // Timezone will be updated on the first write operation.
        let (current_die, automatic_die) = dice(&tx, &session).await?;
        // Bootstrap GET must be read-only - no session creation writes.
        // Always rollback to maintain read-only semantics.
        tx.rollback().await.map_err(session_error)?;
        Ok(SessionBootstrap {
            session,
            current_die,
            automatic_die,
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

    #[tokio::test]
    async fn bootstrap_get_is_read_only() {
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
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let schema = format!("bootstrap_read_only_{}_{}", std::process::id(), nanos);
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
                 CREATE TABLE {schema}.sessions (
                     id integer PRIMARY KEY, user_id integer NOT NULL,
                      started_at timestamptz NOT NULL, ended_at timestamptz, start_die integer NOT NULL,
                     pending_thread_id integer, pending_issue_id integer,
                     pending_thread_updated_at timestamptz, timezone text,
                     predicted_bandwidth text, active_bandwidth text,
                     bandwidth_confidence float8, bandwidth_source text,
                     bandwidth_version timestamptz, reading_bandwidth text,
                     reading_intent text, reading_mode_source text,
                     reading_mode_suggested boolean, active_intent text,
                     predicted_intent text, intent_confidence float8,
                     intent_source text, intent_version timestamptz,
                     session_mode_correction_guidance json
                 );
                 CREATE TABLE {schema}.events (
                     id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                     session_id integer, thread_id integer, issue_id integer,
                     type text, timestamp timestamptz, rating float8,
                     context json, selected_thread_id integer, result integer,
                     die_after integer, metadata_json json
                 );
                 CREATE TABLE {schema}.snapshots (
                     id integer PRIMARY KEY, session_id integer, event_id integer,
                     thread_states json, session_state json, created_at timestamptz,
                     description text, snapshot_kind text, schema_version integer
                 );
                 INSERT INTO {schema}.users VALUES (1);
                 INSERT INTO {schema}.threads VALUES (10, 1);
                 INSERT INTO {schema}.issues VALUES (100, 10);
                 -- Create a session with stale pending pointers to test read-only behavior
                 INSERT INTO {schema}.sessions 
                 (id, user_id, started_at, start_die, pending_thread_id, pending_issue_id,
                  pending_thread_updated_at, reading_mode_suggested) 
                 VALUES (1, 1, NOW() - interval '1 hour', 6, 999, 999, NOW(), false);"
            ))
            .await
            .unwrap();

        let (client, connection) = tokio_postgres::connect(&url, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        client
            .batch_execute(&format!("SET search_path TO {schema}, public"))
            .await
            .unwrap();

        let base = url.split('?').next().unwrap();
        let config = crate::config::Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(format!(
                "{base}?sslmode=disable&options=-csearch_path%3D{schema}"
            )),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic".into()),
            "RUST_ROLL_POOL_SIZE" => Some("1".into()),
            "RUST_ROLL_POOL_TIMEOUT_MS" => Some("10000".into()),
            "RUST_ROLL_REQUEST_TIMEOUT_MS" => Some("10000".into()),
            _ => None,
        })
        .unwrap();
        let state = AppState::new(config).unwrap();
        let user = AuthenticatedUser::for_test(1);

        // Count initial state
        let initial_session_count: i64 = client
            .query_one(&format!("SELECT COUNT(*) FROM {schema}.sessions"), &[])
            .await
            .unwrap()
            .get(0);
        let initial_snapshot_count: i64 = client
            .query_one(&format!("SELECT COUNT(*) FROM {schema}.snapshots"), &[])
            .await
            .unwrap()
            .get(0);
        let initial_event_count: i64 = client
            .query_one(&format!("SELECT COUNT(*) FROM {schema}.events"), &[])
            .await
            .unwrap()
            .get(0);

        // Call bootstrap - should not perform any writes
        let result = crate::reading_session::bootstrap_at(
            &state,
            user,
            None,
            SessionPolicy::default(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_secs_f64(),
        )
        .await;
        assert!(result.is_ok(), "Bootstrap should succeed: {:?}", result);
        let bootstrap = result.unwrap();
        assert!(
            bootstrap.session.pending_thread_id.is_none(),
            "Response should null pending_thread_id"
        );
        assert!(
            bootstrap.session.pending_issue_id.is_none(),
            "Response should null pending_issue_id"
        );

        // Count state after bootstrap - should be unchanged
        let final_session_count: i64 = client
            .query_one(&format!("SELECT COUNT(*) FROM {schema}.sessions"), &[])
            .await
            .unwrap()
            .get(0);
        let final_snapshot_count: i64 = client
            .query_one(&format!("SELECT COUNT(*) FROM {schema}.snapshots"), &[])
            .await
            .unwrap()
            .get(0);
        let final_event_count: i64 = client
            .query_one(&format!("SELECT COUNT(*) FROM {schema}.events"), &[])
            .await
            .unwrap()
            .get(0);

        // Verify no writes occurred
        assert_eq!(
            initial_session_count, final_session_count,
            "No new sessions should be created"
        );
        assert_eq!(
            initial_snapshot_count, final_snapshot_count,
            "No snapshots should be created"
        );
        assert_eq!(
            initial_event_count, final_event_count,
            "No events should be created"
        );

        // Verify the stale pending pointers are not persisted but are nulled in the response
        // The pending pointers should still exist in the database (not persisted)
        let db_pending_thread: Option<i32> = client
            .query_one(
                &format!("SELECT pending_thread_id FROM {schema}.sessions WHERE id=1"),
                &[],
            )
            .await
            .unwrap()
            .get(0);
        let db_pending_issue: Option<i32> = client
            .query_one(
                &format!("SELECT pending_issue_id FROM {schema}.sessions WHERE id=1"),
                &[],
            )
            .await
            .unwrap()
            .get(0);

        // The database should still have the stale pointers (not modified)
        assert_eq!(
            db_pending_thread,
            Some(999),
            "Database should preserve stale pending_thread_id"
        );
        assert_eq!(
            db_pending_issue,
            Some(999),
            "Database should preserve stale pending_issue_id"
        );

        admin
            .batch_execute(&format!("DROP SCHEMA {schema} CASCADE"))
            .await
            .unwrap();
    }

    #[tokio::test]
    async fn bootstrap_get_is_read_only_issue_stale() {
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
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let schema = format!("bootstrap_issue_stale_{}_{}", std::process::id(), nanos);
        let base = url.split('?').next().unwrap();
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
                 CREATE TABLE {schema}.sessions (
                     id integer PRIMARY KEY, user_id integer NOT NULL,
                     started_at timestamptz NOT NULL, ended_at timestamptz,
                     start_die integer NOT NULL,
                     pending_thread_id integer, pending_issue_id integer,
                     pending_thread_updated_at timestamptz, timezone text,
                     predicted_bandwidth text, active_bandwidth text,
                     bandwidth_confidence float8, bandwidth_source text,
                     bandwidth_version timestamptz, reading_bandwidth text,
                     reading_intent text, reading_mode_source text,
                     reading_mode_suggested boolean, active_intent text,
                     predicted_intent text, intent_confidence float8,
                     intent_source text, intent_version timestamptz,
                     session_mode_correction_guidance json
                 );
                 CREATE TABLE {schema}.events (
                     id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                     session_id integer, thread_id integer, issue_id integer,
                     type text, timestamp timestamptz, rating float8,
                     context json, selected_thread_id integer, result integer,
                     die_after integer, metadata_json json
                 );
                 CREATE TABLE {schema}.snapshots (
                     id integer PRIMARY KEY, session_id integer, event_id integer,
                     thread_states json, session_state json, created_at timestamptz,
                     description text, snapshot_kind text, schema_version integer
                 );
                 INSERT INTO {schema}.users VALUES (1);
                 INSERT INTO {schema}.threads VALUES (10, 1);
                 INSERT INTO {schema}.issues VALUES (100, 10);
                 INSERT INTO {schema}.sessions
                 (id, user_id, started_at, start_die, pending_thread_id, pending_issue_id,
                  pending_thread_updated_at, reading_mode_suggested)
                 VALUES (1, 1, NOW() - interval '1 hour', 6, 10, 999, NOW(), false);"
            ))
            .await
            .unwrap();

        let (client, connection) = tokio_postgres::connect(&url, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        client
            .batch_execute(&format!("SET search_path TO {schema}, public"))
            .await
            .unwrap();

        let config = crate::config::Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(format!(
                "{base}?sslmode=disable&options=-csearch_path%3D{schema}"
            )),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic".into()),
            "RUST_ROLL_POOL_SIZE" => Some("1".into()),
            _ => None,
        })
        .unwrap();
        let state = AppState::new(config).unwrap();
        let user = AuthenticatedUser::for_test(1);

        let result = crate::reading_session::bootstrap_at(
            &state,
            user,
            None,
            SessionPolicy::default(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_secs_f64(),
        )
        .await;
        assert!(result.is_ok(), "Bootstrap should succeed: {:?}", result);
        let bootstrap = result.unwrap();
        assert_eq!(
            bootstrap.session.pending_thread_id,
            Some(10),
            "Thread should remain valid"
        );
        assert!(
            bootstrap.session.pending_issue_id.is_none(),
            "Stale issue should be nulled in response"
        );

        let db_pending_thread: Option<i32> = client
            .query_one(
                &format!("SELECT pending_thread_id FROM {schema}.sessions WHERE id=1"),
                &[],
            )
            .await
            .unwrap()
            .get(0);
        let db_pending_issue: Option<i32> = client
            .query_one(
                &format!("SELECT pending_issue_id FROM {schema}.sessions WHERE id=1"),
                &[],
            )
            .await
            .unwrap()
            .get(0);
        assert_eq!(
            db_pending_thread,
            Some(10),
            "Database should preserve pending_thread_id"
        );
        assert_eq!(
            db_pending_issue,
            Some(999),
            "Database should preserve stale pending_issue_id"
        );

        admin
            .batch_execute(&format!("DROP SCHEMA {schema} CASCADE"))
            .await
            .unwrap();
    }

    #[tokio::test]
    async fn bootstrap_skips_bandwidth_inference_write() {
        // Verify that when a session exists without bandwidth,
        // the bootstrap does not perform bandwidth inference writes.
        // This tests requirement: "No test verifies bandwidth inference is skipped"
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
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let schema = format!("bootstrap_bandwidth_skip_{}_{}", std::process::id(), nanos);
        let base = url.split('?').next().unwrap();
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
                 CREATE TABLE {schema}.sessions (
                     id integer PRIMARY KEY, user_id integer NOT NULL,
                     started_at timestamptz NOT NULL, ended_at timestamptz, start_die integer NOT NULL,
                     pending_thread_id integer, pending_issue_id integer,
                     pending_thread_updated_at timestamptz, timezone text,
                     predicted_bandwidth text, active_bandwidth text,
                     bandwidth_confidence float8, bandwidth_source text,
                     bandwidth_version timestamptz, reading_bandwidth text,
                     reading_intent text, reading_mode_source text,
                     reading_mode_suggested boolean, active_intent text,
                     predicted_intent text, intent_confidence float8,
                     intent_source text, intent_version timestamptz,
                     session_mode_correction_guidance json
                 );
                 CREATE TABLE {schema}.events (
                     id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                     session_id integer, thread_id integer, issue_id integer,
                     type text, timestamp timestamptz, rating float8,
                     context json, selected_thread_id integer, result integer,
                     die_after integer, metadata_json json
                 );
                 CREATE TABLE {schema}.snapshots (
                     id integer PRIMARY KEY, session_id integer, event_id integer,
                     thread_states json, session_state json, created_at timestamptz,
                     description text, snapshot_kind text, schema_version integer
                 );
                 INSERT INTO {schema}.users VALUES (1);
                 INSERT INTO {schema}.threads VALUES (10, 1);
                 -- Create a session with NULL bandwidth_source to test skip behavior
                 INSERT INTO {schema}.sessions 
                 (id, user_id, started_at, start_die, reading_mode_suggested,
                  predicted_bandwidth, active_bandwidth, bandwidth_confidence, 
                  bandwidth_source, bandwidth_version) 
                 VALUES (1, 1, NOW() - interval '1 hour', 6, false,
                         NULL, NULL, NULL, NULL, NULL);"
            ))
            .await
            .unwrap();

        let (client, connection) = tokio_postgres::connect(&url, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        client
            .batch_execute(&format!("SET search_path TO {schema}, public"))
            .await
            .unwrap();

        let config = crate::config::Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(format!(
                "{base}?sslmode=disable&options=-csearch_path%3D{schema}"
            )),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic".into()),
            "RUST_ROLL_POOL_SIZE" => Some("1".into()),
            _ => None,
        })
        .unwrap();
        let state = AppState::new(config).unwrap();
        let user = AuthenticatedUser::for_test(1);

        // Record bandwidth values before bootstrap
        let before_bw: Option<String> = client
            .query_one("SELECT predicted_bandwidth FROM sessions WHERE id=1", &[])
            .await
            .unwrap()
            .get(0);

        // Call bootstrap - should not update bandwidth
        let result = crate::reading_session::bootstrap_at(
            &state,
            user,
            None,
            SessionPolicy::default(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_secs_f64(),
        )
        .await;
        assert!(result.is_ok(), "Bootstrap should succeed: {:?}", result);

        // Verify bandwidth was NOT written (should remain NULL)
        let after_bw: Option<String> = client
            .query_one("SELECT predicted_bandwidth FROM sessions WHERE id=1", &[])
            .await
            .unwrap()
            .get(0);
        assert_eq!(before_bw, after_bw, "Bandwidth should not be written");
        assert!(after_bw.is_none(), "predicted_bandwidth should remain NULL");

        admin
            .batch_execute(&format!("DROP SCHEMA {schema} CASCADE"))
            .await
            .unwrap();
    }

    #[tokio::test]
    async fn bootstrap_skips_timezone_write() {
        // Verify that when a session exists, the bootstrap does not write timezone.
        // This tests requirement: "No test verifies timezone update is skipped"
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
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let schema = format!("bootstrap_timezone_skip_{}_{}", std::process::id(), nanos);
        let base = url.split('?').next().unwrap();
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
                 CREATE TABLE {schema}.sessions (
                     id integer PRIMARY KEY, user_id integer NOT NULL,
                     started_at timestamptz NOT NULL, ended_at timestamptz, start_die integer NOT NULL,
                     pending_thread_id integer, pending_issue_id integer,
                     pending_thread_updated_at timestamptz, timezone text,
                     predicted_bandwidth text, active_bandwidth text,
                     bandwidth_confidence float8, bandwidth_source text,
                     bandwidth_version timestamptz, reading_bandwidth text,
                     reading_intent text, reading_mode_source text,
                     reading_mode_suggested boolean, active_intent text,
                     predicted_intent text, intent_confidence float8,
                     intent_source text, intent_version timestamptz,
                     session_mode_correction_guidance json
                 );
                 CREATE TABLE {schema}.events (
                     id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                     session_id integer, thread_id integer, issue_id integer,
                     type text, timestamp timestamptz, rating float8,
                     context json, selected_thread_id integer, result integer,
                     die_after integer, metadata_json json
                 );
                 CREATE TABLE {schema}.snapshots (
                     id integer PRIMARY KEY, session_id integer, event_id integer,
                     thread_states json, session_state json, created_at timestamptz,
                     description text, snapshot_kind text, schema_version integer
                 );
                 INSERT INTO {schema}.users VALUES (1);
                 INSERT INTO {schema}.threads VALUES (10, 1);
                 -- Create a session with timezone = NULL
                 INSERT INTO {schema}.sessions 
                 (id, user_id, started_at, start_die, reading_mode_suggested, timezone) 
                 VALUES (1, 1, NOW() - interval '1 hour', 6, false, NULL);"
            ))
            .await
            .unwrap();

        let (client, connection) = tokio_postgres::connect(&url, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        client
            .batch_execute(&format!("SET search_path TO {schema}, public"))
            .await
            .unwrap();

        let config = crate::config::Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(format!(
                "{base}?sslmode=disable&options=-csearch_path%3D{schema}"
            )),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic".into()),
            "RUST_ROLL_POOL_SIZE" => Some("1".into()),
            _ => None,
        })
        .unwrap();
        let state = AppState::new(config).unwrap();
        let user = AuthenticatedUser::for_test(1);

        // Record timezone before bootstrap (passing a valid timezone parameter)
        let before_tz: Option<String> = client
            .query_one("SELECT timezone FROM sessions WHERE id=1", &[])
            .await
            .unwrap()
            .get(0);

        // Call bootstrap with a browser timezone parameter
        let result = crate::reading_session::bootstrap_at(
            &state,
            user,
            Some("America/New_York"), // browser timezone
            SessionPolicy::default(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_secs_f64(),
        )
        .await;
        assert!(result.is_ok(), "Bootstrap should succeed: {:?}", result);

        // Verify timezone was NOT written (should remain NULL)
        let after_tz: Option<String> = client
            .query_one("SELECT timezone FROM sessions WHERE id=1", &[])
            .await
            .unwrap()
            .get(0);
        assert_eq!(before_tz, after_tz, "Timezone should not be written on GET");
        assert!(after_tz.is_none(), "timezone should remain NULL");

        admin
            .batch_execute(&format!("DROP SCHEMA {schema} CASCADE"))
            .await
            .unwrap();
    }
}
