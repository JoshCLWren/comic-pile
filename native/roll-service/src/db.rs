//! Bounded database reads. All reading-domain lookups require verified ownership.
use crate::{auth::AuthenticatedUser, ApiError, AppState};
use axum::http::StatusCode;
use deadpool_postgres::Object;
use std::time::Duration;
use tokio_postgres::{types::ToSql, Row};

/// Physical connections one checkout may try before reporting unavailability.
///
/// A single idle socket is the production failure (#4732); a few attempts also
/// cover a small pool whose sockets all died in the same freeze. The bound keeps
/// recovery from turning into an unbounded connect loop.
const CHECKOUT_ATTEMPTS: usize = 3;

/// A live database answers `SELECT 1` in milliseconds; a half-open socket hangs.
///
/// The probe is capped so a bounded recovery still fits inside the request
/// deadline instead of letting the outer middleware turn it into a generic
/// request timeout.
const MAX_PROBE_TIMEOUT: Duration = Duration::from_secs(2);

/// Pool wait/create deadlines are configured at startup; no unbounded retry loop.
///
/// Every checkout first proves the physical socket can carry a statement. A
/// pooled connection can be half-open after an idle freeze or platform pause:
/// `is_closed` is false and the driver only learns otherwise when the first
/// statement hangs or the peer resets. Validating here means every mounted
/// handler, authentication included, starts on a live connection before it can
/// write anything. The probe is the request's first statement, so recovery never
/// replays handler SQL, a write, or an audit event.
///
/// A connection that cannot carry the probe is discarded rather than returned to
/// the pool. Ordinary SQL errors never reach this path: the probe cannot produce
/// one, and handler statements keep their existing classification in
/// [`query_error_for`].
pub async fn checkout(state: &AppState) -> Result<Object, ApiError> {
    if !state.connection_recovery {
        return acquire(state).await;
    }
    tokio::time::timeout(state.request_timeout, recover(state))
        .await
        .unwrap_or_else(|_| Err(ApiError::database_unavailable()))
}

/// Replace pooled sockets that cannot carry a statement, bounded to
/// [`CHECKOUT_ATTEMPTS`].
async fn recover(state: &AppState) -> Result<Object, ApiError> {
    let mut attempt = 1;
    loop {
        let connection = acquire(state).await?;
        match probe(state, connection).await {
            Ok(connection) => return Ok(connection),
            Err(error) if error.is_database_unavailable() && attempt < CHECKOUT_ATTEMPTS => {
                tracing::warn!(
                    attempt,
                    max_attempts = CHECKOUT_ATTEMPTS,
                    "discarding a pooled connection that could not carry its first statement"
                );
                attempt += 1;
            }
            Err(error) => return Err(error),
        }
    }
}

/// Bounded pool acquisition; no unbounded retry loop.
async fn acquire(state: &AppState) -> Result<Object, ApiError> {
    tokio::time::timeout(state.request_timeout, state.pool.get())
        .await
        .map_err(|e| {
            tracing::debug!(error = ?e, "preserved underlying error before mapping");
            ApiError::database_unavailable()
        })?
        .map_err(|e| {
            tracing::debug!(error = ?e, "preserved underlying error before mapping");
            ApiError::database_unavailable()
        })
}

/// Prove a checked-out connection can carry a statement.
///
/// Dropping the probe future (timeout or outer request cancellation) discards
/// the physical connection, because PostgreSQL may still be executing work on
/// it. A failed or cancelled probe is never returned to the pool.
async fn probe(state: &AppState, connection: Object) -> Result<Object, ApiError> {
    struct Pending(Option<Object>);
    impl Drop for Pending {
        fn drop(&mut self) {
            if let Some(connection) = self.0.take() {
                drop(Object::take(connection));
            }
        }
    }
    let mut pending = Pending(Some(connection));
    let result = tokio::time::timeout(
        state.request_timeout.min(MAX_PROBE_TIMEOUT),
        pending
            .0
            .as_ref()
            .expect("checked-out PostgreSQL client")
            .simple_query("SELECT 1"),
    )
    .await;
    match result {
        Err(e) => {
            tracing::debug!(error = ?e, "preserved underlying error before mapping");
            Err(ApiError::database_unavailable())
        }
        Ok(Ok(_)) => Ok(pending.0.take().expect("checked-out PostgreSQL client")),
        Ok(Err(error)) => Err(query_error_for("database.checkout_probe", error)),
    }
}

pub(crate) async fn query_one_optional(
    state: &AppState,
    connection: Object,
    sql: &str,
    params: &[&(dyn ToSql + Sync)],
) -> Result<Option<Row>, ApiError> {
    // Dropping a query future does not cancel PostgreSQL work. Discard the
    // physical connection on timeout or outer request cancellation instead of
    // returning a busy connection to the pool.
    struct Pending(Option<Object>);
    impl Drop for Pending {
        fn drop(&mut self) {
            if let Some(connection) = self.0.take() {
                drop(Object::take(connection));
            }
        }
    }
    let mut pending = Pending(Some(connection));
    let result = tokio::time::timeout(
        state.request_timeout,
        pending.0.as_ref().unwrap().query_opt(sql, params),
    )
    .await;
    match result {
        Err(e) => {
            tracing::debug!(error = ?e, "preserved underlying error before mapping");
            Err(ApiError::database_unavailable())
        }
        Ok(result) => {
            drop(pending.0.take()); // Complete response consumed: safe to recycle.
            result.map_err(query_error)
        }
    }
}

/// True when a statement never reached the server because the connection failed.
///
/// `is_closed` covers a cleanly detached connection; transport failures keep the
/// OS or TLS error as their cause, which is what a half-open socket after an
/// idle freeze surfaces on the first write. Value and row-shape errors
/// (`ToSql`, `FromSql`, wrong column/parameter counts) carry no transport cause
/// and stay internal: they are defects, not transport state.
pub(crate) fn is_transport_failure(error: &tokio_postgres::Error) -> bool {
    if error.is_closed() {
        return true;
    }
    if error.as_db_error().is_some() {
        return false;
    }
    match std::error::Error::source(error) {
        Some(source) => {
            source.downcast_ref::<std::io::Error>().is_some()
                || source.downcast_ref::<native_tls::Error>().is_some()
        }
        None => false,
    }
}

fn is_availability_code(code: &str) -> bool {
    code.starts_with("08") || code.starts_with("53") || matches!(code, "57P01" | "57P02" | "57P03")
}

/// Classify a database-layer failure into the public status contract.
///
/// A statement the server never saw (`transport`) or rejected for availability
/// reasons takes the retryable "database unavailable" contract [`checkout`]
/// already returns: the reader cannot fix a connection that died between
/// requests, and a 5xx is a hard failure for the client. Reporting transport
/// state as an internal error is wrong (#4535).
///
/// A statement the server did reject stays a 500: only a data or schema defect
/// produces that, and the diagnostic log records the operation label and
/// SQLSTATE so it stays attributable.
pub(crate) fn failure_status(sqlstate: Option<&str>, transport: bool) -> StatusCode {
    if transport {
        return StatusCode::SERVICE_UNAVAILABLE;
    }
    match sqlstate {
        Some(code) if is_availability_code(code) => StatusCode::SERVICE_UNAVAILABLE,
        _ => StatusCode::INTERNAL_SERVER_ERROR,
    }
}

/// Map a database-layer failure using only an operation label and SQLSTATE.
///
/// Never log SQL text, bind parameters, user identity, credentials or the
/// server's message: the label plus the SQLSTATE is enough to attribute a
/// failure without exposing reader data. The public body keeps its generic
/// redacted contract.
pub(crate) fn query_error_for(operation: &'static str, error: tokio_postgres::Error) -> ApiError {
    let sqlstate = error.as_db_error().map(|e| e.code().code());
    let transport = is_transport_failure(&error);
    match failure_status(sqlstate, transport) {
        StatusCode::SERVICE_UNAVAILABLE => {
            // Transport failures have no SQLSTATE; the cause is an OS/TLS
            // condition, never reader data.
            tracing::warn!(
                operation,
                sqlstate = sqlstate.unwrap_or("none"),
                transport,
                closed = error.is_closed(),
                "database connection unavailable"
            );
            ApiError::database_unavailable()
        }
        _ => {
            tracing::error!(
                operation,
                sqlstate = sqlstate.unwrap_or("none"),
                "database statement failed"
            );
            ApiError::Internal("Internal Server Error".to_string())
        }
    }
}

pub(crate) fn query_error(error: tokio_postgres::Error) -> ApiError {
    query_error_for("database.statement", error)
}

/// Foreign/missing threads are indistinguishable; no unscoped identifier lookup.
pub async fn require_owned_thread(
    state: &AppState,
    user: AuthenticatedUser,
    id: i32,
) -> Result<(), ApiError> {
    let connection = checkout(state).await?;
    query_one_optional(
        state,
        connection,
        "SELECT id FROM threads WHERE id = $1 AND user_id = $2",
        &[&id, &user.id()],
    )
    .await?
    .ok_or(ApiError::NotFound("Thread not found".to_string()))?;
    Ok(())
}

/// Reading history is owned data, never a substitute for an access credential.
pub async fn require_owned_reading_session(
    state: &AppState,
    user: AuthenticatedUser,
    id: i32,
) -> Result<(), ApiError> {
    let connection = checkout(state).await?;
    query_one_optional(
        state,
        connection,
        "SELECT id FROM sessions WHERE id = $1 AND user_id = $2",
        &[&id, &user.id()],
    )
    .await?
    .ok_or(ApiError::NotFound("Session not found".to_string()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;

    /// #4535: a statement that never reached the server is transport state, not
    /// an internal error. A server-rejected statement and a value/shape defect
    /// stay 500.
    #[test]
    fn transport_failures_are_retryable_but_server_rejections_are_internal() {
        // No answer from the server: the connection could not carry it.
        assert_eq!(failure_status(None, true), StatusCode::SERVICE_UNAVAILABLE);
        for code in ["08000", "08006", "53300", "57P01", "57P02", "57P03"] {
            assert_eq!(
                failure_status(Some(code), false),
                StatusCode::SERVICE_UNAVAILABLE,
                "{code} is an availability failure"
            );
        }
        // Value and row-shape defects keep the existing internal contract.
        assert_eq!(
            failure_status(None, false),
            StatusCode::INTERNAL_SERVER_ERROR
        );
        for code in ["23503", "23514", "25006", "42703", "25P02", "57014"] {
            assert_eq!(
                failure_status(Some(code), false),
                StatusCode::INTERNAL_SERVER_ERROR,
                "{code} is a server-rejected statement"
            );
        }
    }

    #[tokio::test]
    async fn canceled_queries_discard_connections_and_query_bugs_remain_500() {
        let url = crate::test_support::database_url().await;
        let config = Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic".into()),
            "RUST_ROLL_POOL_SIZE" => Some("1".into()),
            _ => None,
        })
        .unwrap();
        let mut state = AppState::new(config).unwrap();
        let connection = checkout(&state).await.ok().unwrap();
        let error = query_one_optional(
            &state,
            connection,
            "SELECT * FROM missing_auth_test_table",
            &[],
        )
        .await
        .err()
        .unwrap();
        assert_eq!(error.status(), StatusCode::INTERNAL_SERVER_ERROR);
        let connection = checkout(&state).await.ok().unwrap();
        let error = query_one_optional(&state, connection, "SELECT $1::int4", &[&"wrong type"])
            .await
            .err()
            .unwrap();
        assert_eq!(error.status(), StatusCode::INTERNAL_SERVER_ERROR);
        let connection = checkout(&state).await.ok().unwrap();
        state.request_timeout = Duration::from_millis(20);
        let error = query_one_optional(&state, connection, "SELECT pg_sleep(5)", &[])
            .await
            .err()
            .unwrap();
        assert_eq!(error.status(), StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(state.pool.status().size, 0);
        state.request_timeout = Duration::from_secs(2);
        let connection = checkout(&state).await.ok().unwrap();
        let result = tokio::time::timeout(
            Duration::from_millis(20),
            query_one_optional(&state, connection, "SELECT pg_sleep(5)", &[]),
        )
        .await;
        assert!(result.is_err());
        assert_eq!(state.pool.status().size, 0);
        let connection = checkout(&state).await.ok().unwrap();
        assert!(query_one_optional(&state, connection, "SELECT 1", &[])
            .await
            .ok()
            .unwrap()
            .is_some());
    }
}
