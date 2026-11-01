//! Bounded database reads. All reading-domain lookups require verified ownership.
use crate::{auth::AuthenticatedUser, ApiError, AppState};
use axum::http::StatusCode;
use deadpool_postgres::Object;
use serde::{Deserialize, Serialize};
use tokio_postgres::{types::ToSql, Row};

/// Database model for an issue.
#[derive(Debug, Serialize, Deserialize, sqlx::FromRow)]
pub struct Issue {
    pub id: i32,
    pub thread_id: i32,
    pub issue_number: String,
    pub position: i32,
    pub status: String,
    pub read_at: Option<chrono::DateTime<chrono::Utc>>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub catalog_issue_id: Option<i32>,
    pub rating: Option<f64>,
    pub user_id: i32,
}

/// Database model for a thread.
#[derive(Debug, Serialize, Deserialize, sqlx::FromRow)]
pub struct Thread {
    pub id: i32,
    pub title: String,
    pub format: String,
    pub issues_remaining: i32,
    pub total_issues: Option<i32>,
    pub next_unread_issue_id: Option<i32>,
    pub reading_progress: Option<String>,
    pub queue_position: i32,
    pub queue_order_key: Option<i64>,
    pub status: String,
    pub last_rating: Option<f64>,
    pub last_activity_at: Option<chrono::DateTime<chrono::Utc>>,
    pub notes: Option<String>,
    pub manual_creator_credits: Vec<serde_json::Value>,
    pub is_test: bool,
    pub is_blocked: bool,
    pub queue_position_is_manual: bool,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub user_id: i32,
    pub catalog_series_id: Option<i32>,
}

fn unavailable() -> ApiError {
    ApiError(
        StatusCode::SERVICE_UNAVAILABLE,
        "Database temporarily unavailable",
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

pub(crate) fn query_error(error: tokio_postgres::Error) -> ApiError {
    if error.is_closed()
        || error.as_db_error().is_some_and(|e| {
            let code = e.code().code();
            code.starts_with("08")
                || code.starts_with("53")
                || matches!(code, "57P01" | "57P02" | "57P03")
        })
    {
        unavailable()
    } else {
        ApiError(StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error")
    }
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
    .ok_or(ApiError(StatusCode::NOT_FOUND, "Thread not found"))?;
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
    .ok_or(ApiError(StatusCode::NOT_FOUND, "Session not found"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;
    use std::time::Duration;

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
