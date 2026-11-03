//! Bounded database reads. All reading-domain lookups require verified ownership.
use crate::{auth::AuthenticatedUser, ApiError, AppState};
use axum::http::StatusCode;
use deadpool_postgres::Object;
use tokio_postgres::{types::ToSql, Row};

fn unavailable() -> ApiError {
    ApiError(
        StatusCode::SERVICE_UNAVAILABLE,
        "Database temporarily unavailable".to_string(),
    )
}

/// Pool wait/create deadlines are configured at startup; no unbounded retry loop.
pub async fn checkout(state: &AppState) -> Result<Object, ApiError> {
    tokio::time::timeout(state.request_timeout, state.pool.get())
        .await
        .map_err(|_| unavailable())?
        .map_err(|_| unavailable())
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
        Err(_) => Err(unavailable()),
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
            unavailable()
        }
        _ => {
            tracing::error!(
                operation,
                sqlstate = sqlstate.unwrap_or("none"),
                "database statement failed"
            );
            ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Internal Server Error".to_string(),
            )
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
    .ok_or(ApiError(
        StatusCode::NOT_FOUND,
        "Thread not found".to_string(),
    ))?;
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
    .ok_or(ApiError(
        StatusCode::NOT_FOUND,
        "Session not found".to_string(),
    ))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;
    use std::time::Duration;

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
        let url =
            std::env::var("RUST_ROLL_TEST_DATABASE_URL").expect("disposable PostgreSQL required");
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
        assert_eq!(error.0, StatusCode::INTERNAL_SERVER_ERROR);
        let connection = checkout(&state).await.ok().unwrap();
        let error = query_one_optional(&state, connection, "SELECT $1::int4", &[&"wrong type"])
            .await
            .err()
            .unwrap();
        assert_eq!(error.0, StatusCode::INTERNAL_SERVER_ERROR);
        let connection = checkout(&state).await.ok().unwrap();
        state.request_timeout = Duration::from_millis(20);
        let error = query_one_optional(&state, connection, "SELECT pg_sleep(5)", &[])
            .await
            .err()
            .unwrap();
        assert_eq!(error.0, StatusCode::SERVICE_UNAVAILABLE);
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
