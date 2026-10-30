//! Owner-scoped scalar inputs. Stored queue fields are diagnostics only.
use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::http::StatusCode;
use deadpool_postgres::Object;
use serde::Serialize;
use std::{collections::HashMap, time::Instant};
use tokio_postgres::{IsolationLevel, Transaction};

#[derive(Debug, PartialEq, Eq, Serialize)]
pub struct ReadingThread {
    pub id: i32,
    pub status: String,
    pub title: String,
}
#[derive(Debug, PartialEq, Eq, Serialize)]
pub struct ReadingIssue {
    pub id: i32,
    pub thread_id: i32,
    pub position: i32,
    pub status: String,
    pub issue_number: String,
}
#[derive(Debug, PartialEq, Eq, Serialize)]
pub struct StoredThreadEligibility {
    pub thread_id: i32,
    pub next_issue_id: Option<i32>,
    pub is_blocked: bool,
    pub queue_position: i32,
}
#[derive(Debug, PartialEq, Eq, Serialize)]
pub struct CoreReadingInputs {
    pub threads: Vec<ReadingThread>,
    pub issues: Vec<ReadingIssue>,
    pub stored: Vec<StoredThreadEligibility>,
}

// Include inactive threads and read issues; natural position defines series order.
pub(crate) async fn load_core_transaction(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
) -> Result<CoreReadingInputs, tokio_postgres::Error> {
    let user_id = user.id();
    let rows = tx.query("SELECT id, status, title, next_unread_issue_id, is_blocked, queue_position FROM threads WHERE user_id = $1 ORDER BY id", &[&user_id]).await?;
    let mut threads = Vec::with_capacity(rows.len());
    let mut stored = Vec::with_capacity(rows.len());
    for row in rows {
        threads.push(ReadingThread {
            id: row.try_get(0)?,
            status: row.try_get(1)?,
            title: row.try_get(2)?,
        });
        stored.push(StoredThreadEligibility {
            thread_id: row.try_get(0)?,
            next_issue_id: row.try_get(3)?,
            is_blocked: row.try_get(4)?,
            queue_position: row.try_get(5)?,
        });
    }
    let rows = tx.query("SELECT i.id, i.thread_id, i.position, i.status, i.issue_number FROM issues i JOIN threads t ON t.id = i.thread_id WHERE t.user_id = $1 ORDER BY i.thread_id, i.position, i.id", &[&user_id]).await?;
    let mut issues = Vec::with_capacity(rows.len());
    for row in rows {
        issues.push(ReadingIssue {
            id: row.try_get(0)?,
            thread_id: row.try_get(1)?,
            position: row.try_get(2)?,
            status: row.try_get(3)?,
            issue_number: row.try_get(4)?,
        });
    }
    Ok(CoreReadingInputs {
        threads,
        issues,
        stored,
    })
}
pub(crate) fn valid_references(inputs: &CoreReadingInputs) -> bool {
    let owners: HashMap<_, _> = inputs.issues.iter().map(|i| (i.id, i.thread_id)).collect();
    inputs.stored.iter().all(|s| {
        s.next_issue_id
            .is_none_or(|id| owners.get(&id) == Some(&s.thread_id))
    })
}
// Cancellation must discard the physical connection until rollback completes.
struct Pending(Option<Object>);
impl Drop for Pending {
    fn drop(&mut self) {
        if let Some(c) = self.0.take() {
            drop(c);
        }
    }
}
/// Bounded repeatable-read/read-only snapshot, requiring verified identity.
/// Unresolved stored references fail closed without exposing foreign data.
pub async fn load_core_inputs(
    state: &AppState,
    user: AuthenticatedUser,
) -> Result<CoreReadingInputs, ApiError> {
    let started = Instant::now();
    let mut pending = Pending(Some(db::checkout(state).await?));
    let result = tokio::time::timeout(state.request_timeout, async {
        let tx = pending
            .0
            .as_mut()
            .unwrap()
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await?;
        let inputs = load_core_transaction(&tx, user).await?;
        tx.rollback().await?;
        Ok::<_, tokio_postgres::Error>(inputs)
    })
    .await;
    match result {
        Err(_) => Err(ApiError(
            StatusCode::SERVICE_UNAVAILABLE,
            "Database temporarily unavailable",
        )),
        Ok(Err(error)) => Err(db::query_error(error)),
        Ok(Ok(inputs)) => {
            drop(pending.0.take());
            if !valid_references(&inputs) {
                return Err(ApiError(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "Unresolved reading reference",
                ));
            }
            tracing::info!(
                query_count = 2,
                elapsed_us = started.elapsed().as_micros() as u64,
                thread_count = inputs.threads.len(),
                issue_count = inputs.issues.len(),
                "core reading inputs loaded"
            );
            Ok(inputs)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn references_require_the_exact_owned_thread_and_allow_empty_threads() {
        let mut inputs = CoreReadingInputs {
            threads: vec![],
            issues: vec![ReadingIssue {
                id: 10,
                thread_id: 20,
                position: 1,
                status: "read".into(),
                issue_number: "1".into(),
            }],
            stored: vec![StoredThreadEligibility {
                thread_id: 20,
                next_issue_id: None,
                is_blocked: true,
                queue_position: -5,
            }],
        };
        assert!(valid_references(&inputs));
        inputs.stored[0].next_issue_id = Some(10);
        assert!(valid_references(&inputs));
        inputs.stored[0].next_issue_id = Some(999);
        assert!(!valid_references(&inputs));
        inputs.stored[0].next_issue_id = Some(10);
        inputs.issues[0].thread_id = 21;
        assert!(!valid_references(&inputs));
    }
    #[tokio::test]
    async fn unfinished_snapshots_discard_connections() {
        use crate::config::Config;
        use std::time::Duration;
        for outer_cancel in [false, true] {
            let url = std::env::var("RUST_ROLL_TEST_DATABASE_URL")
                .expect("disposable PostgreSQL required");
            let mut state = AppState::new(
                Config::from_lookup(|key| match key {
                    "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
                    "RUST_ROLL_JWT_SECRET" => Some("synthetic-core-key".into()),
                    "RUST_ROLL_POOL_SIZE" => Some("1".into()),
                    _ => None,
                })
                .unwrap(),
            )
            .unwrap();
            let connection = state.pool.get().await.unwrap();
            connection.batch_execute("CREATE TEMP TABLE users (id int, username text, password_changed_at timestamptz); CREATE TEMP TABLE revoked_tokens (jti text); INSERT INTO users VALUES (1, 'snapshot-reader', NULL)").await.unwrap();
            drop(connection);
            let token = jsonwebtoken::encode(&jsonwebtoken::Header::default(), &serde_json::json!({"sub":"snapshot-reader", "type":"access", "jti":"synthetic-jti"}), &jsonwebtoken::EncodingKey::from_secret(b"synthetic-core-key")).unwrap();
            let user = crate::auth::authenticate(&state, &token)
                .await
                .ok()
                .unwrap();
            let connection = state.pool.get().await.unwrap();
            connection.batch_execute("CREATE TEMP TABLE source_threads (id int, user_id int, status text, title text, next_unread_issue_id int, is_blocked bool, queue_position int); INSERT INTO source_threads VALUES (1, 1, 'active', 'synthetic', NULL, false, 1); CREATE TEMP VIEW threads AS SELECT source_threads.* FROM source_threads CROSS JOIN pg_sleep(5)").await.unwrap();
            drop(connection);
            if outer_cancel {
                assert!(tokio::time::timeout(
                    Duration::from_millis(20),
                    load_core_inputs(&state, user)
                )
                .await
                .is_err());
            } else {
                state.request_timeout = Duration::from_millis(20);
                let error = load_core_inputs(&state, user).await.err().unwrap();
                assert_eq!(error.0, StatusCode::SERVICE_UNAVAILABLE);
            }
            assert_eq!(state.pool.status().size, 0);
            state.request_timeout = Duration::from_secs(2);
            let connection = db::checkout(&state).await.ok().unwrap();
            let row = connection.query_one("SELECT current_setting('transaction_read_only'), current_setting('transaction_isolation')", &[]).await.unwrap();
            assert_eq!(row.get::<_, String>(0), "off");
            assert_eq!(row.get::<_, String>(1), "read committed");
        }
    }
}
