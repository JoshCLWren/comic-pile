//! Native cutover of `POST /api/v1/roll/dismiss-pending` and its shared-handler alias
//! `POST /api/roll/dismiss-pending`.
//!
//! The Python handler is the behavioral oracle. This module preserves the same
//! request contract (no body), authenticated owner scope, status/error JSON,
//! transactional side effects, and legacy roll-pool semantics. A dismiss
//! event is persisted so the session timeline records the cancellation
//! (#3763). The dismissed series is referenced through ``selected_thread_id``
//! so the record survives a later deletion of the series.
//! #![forbid(unsafe_code)]
use crate::{auth::AuthenticatedUser, db, reading_session, ApiError};
use axum::{
    extract::State,
    http::StatusCode,
};
use deadpool_postgres::Object;

use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio_postgres::IsolationLevel;

fn unavailable() -> ApiError {
    ApiError(
        StatusCode::SERVICE_UNAVAILABLE,
        "Database temporarily unavailable",
    )
}

/// Mutating transaction for the dismiss-pending flow.
#[allow(clippy::too_many_arguments)]
async fn mutate(
    user: AuthenticatedUser,
    session: &reading_session::ReadingSession,
    now: f64,
    connection: &mut Object,
) -> Result<(), ApiError> {
    let tx = connection
        .build_transaction()
        .isolation_level(IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(query_error)?;

    tx.batch_execute("SET LOCAL TIME ZONE 'UTC'")
        .await
        .map_err(query_error)?;

    // persist a dismiss event so the session timeline records the cancellation
    // (issue #3763). Only insert when there is a pending thread, matching
    // the Python handler's behavior of skipping the event when nothing is pending.
    if session.pending_thread_id.is_some() {
        tx.execute(
            "INSERT INTO events (type, timestamp, session_id, selected_thread_id)
             VALUES ('dismiss', to_timestamp($1), $2, $3)",
            &[&now, &session.id, &session.pending_thread_id],
        )
        .await
            .map_err(query_error)?;
    }

    // Clear the pending thread on the session.
    tx.execute(
        "UPDATE sessions SET pending_thread_id = NULL, pending_thread_updated_at = to_timestamp($2)
         WHERE id = $1 AND user_id = $3",
        &[&session.id, &now, &user.id()],
    )
    .await
        .map_err(query_error)?;

    tx.commit().await.map_err(query_error)?;

    Ok(())
}

/// Public handler for dismissing a pending roll.
pub async fn dismiss_pending(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<StatusCode, ApiError> {
    let now = now_seconds();
    let active = reading_session::bootstrap(&state, user.clone(), None, reading_session::SessionPolicy::default()).await?;
    let session = active.session;

    let mut pending = PendingConn(Some(db::checkout(&state).await?));
    let result = tokio::time::timeout(
        state.request_timeout,
        mutate(
            user,
            &session,
            now,
            pending.0.as_mut().unwrap(),
        ),
    )
    .await;
    match result {
        Err(_) => Err(unavailable()),
        Ok(Ok(())) => {
            drop(pending.0.take());
            Ok(StatusCode::NO_CONTENT)
        }
        Ok(Err(err)) => Err(err),
    }
}

/// Helper to manage a checked-out database connection with deterministic drop.
struct PendingConn(Option<Object>);
impl Drop for PendingConn {
    fn drop(&mut self) {
        if let Some(connection) = self.0.take() {
            drop(connection);
        }
    }
}

/// Return the current UTC timestamp as seconds since epoch, matching
/// Python's `datetime.now(UTC).timestamp()`.
fn now_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64()
}

/// PostgreSQL error classification.
fn query_error(error: tokio_postgres::Error) -> ApiError {
    let code = error.code().map(|c| c.code()).unwrap_or_default();
    if error.is_closed()
        || code.starts_with("08")
        || code.starts_with("53")
        || matches!(code, "57P01" | "57P02" | "57P03")
    {
        unavailable()
    } else {
        ApiError(StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error")
    }
}

// ---------------------------------------------------------------------------
// OpenAPI documentation-only operations (emit the generated contract).
// ---------------------------------------------------------------------------

#[utoipa::path(
    post,
    path = "/api/v1/roll/dismiss-pending",
    tag = "roll",
    responses((status = 204, description = "No Content. Pending thread cleared.")),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn dismiss_pending_documentation() {}

/// Also mount the legacy-handler alias.
#[utoipa::path(
    post,
    path = "/api/roll/dismiss-pending",
    tag = "roll",
    responses((status = 204, description = "No Content. Pending thread cleared.")),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn dismiss_pending_legacy_documentation() {}