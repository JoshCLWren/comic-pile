//! Durable, owner-scoped dice-command writer for Roll #4405.
//!
//! This is deliberately not an HTTP route. The coordinated Roll cutover must
//! call this from authenticated Rust handlers in the SAME transaction as any
//! queue/progress/selection changes. A writer cannot independently determine
//! Option E eligibility or validate the currently offered comic.
//!
//! Postgres user-scoped transaction locks serialize different commands; a
//! unique owner/key index guarantees retry safety even across processes.
//! Every resulting die is persisted with the action, never recomputed on replay.
use crate::{
    auth::AuthenticatedUser,
    db,
    dice_state::{self, DiceAction},
    ApiError,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio_postgres::{Client, IsolationLevel, Transaction};

/// Payload is immutable for a given client-generated idempotency key.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum DiceCommand {
    ManualSelect {
        die: i32,
    },
    Reset,
    /// The caller must prove this is the pending, Option E-readable offer.
    Reroll {
        thread_id: i32,
    },
    /// The caller must complete issue progress in the same transaction.
    RollRating {
        thread_id: i32,
        issue_id: i32,
        rating: f64,
    },
}

/// An already committed receipt is returned unchanged after a lost response.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DiceMutation {
    pub event_id: i32,
    pub die_before: i32,
    pub die_after: i32,
    pub replayed: bool,
}

fn invalid(detail: &str) -> ApiError {
    ApiError::Unprocessable(detail.to_string())
}

pub(crate) fn validate(key: &str, command: &DiceCommand) -> Result<(), ApiError> {
    if !(8..=128).contains(&key.len())
        || !key
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
    {
        return Err(invalid("Invalid dice idempotency key"));
    }
    match command {
        DiceCommand::ManualSelect { die } => {
            dice_state::apply_action(6, DiceAction::ManualSelect(*die)).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                invalid("Invalid manual die")
            })?;
        }
        DiceCommand::Reroll { thread_id } if *thread_id <= 0 => {
            return Err(invalid("Invalid thread"));
        }
        DiceCommand::RollRating {
            thread_id,
            issue_id,
            rating,
        } => {
            if *thread_id <= 0 || *issue_id <= 0 {
                return Err(invalid("Invalid issue"));
            }
            dice_state::apply_action(6, DiceAction::RollRating(*rating)).map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                invalid("Invalid rating")
            })?;
        }
        _ => {}
    }
    Ok(())
}

impl DiceCommand {
    fn action(&self) -> DiceAction {
        match self {
            Self::ManualSelect { die } => DiceAction::ManualSelect(*die),
            Self::Reset => DiceAction::Reset,
            Self::Reroll { .. } => DiceAction::Reroll,
            Self::RollRating { rating, .. } => DiceAction::RollRating(*rating),
        }
    }

    fn event_type(&self) -> &'static str {
        match self {
            Self::ManualSelect { .. } => "manual_die",
            Self::Reset => "reset_dice",
            Self::Reroll { .. } => "snooze",
            Self::RollRating { .. } => "rate",
        }
    }

    fn thread_id(&self) -> Option<i32> {
        match self {
            Self::Reroll { thread_id } | Self::RollRating { thread_id, .. } => Some(*thread_id),
            _ => None,
        }
    }

    fn issue_id(&self) -> Option<i32> {
        match self {
            Self::RollRating { issue_id, .. } => Some(*issue_id),
            _ => None,
        }
    }

    fn rating(&self) -> Option<f64> {
        match self {
            Self::RollRating { rating, .. } => Some(*rating),
            _ => None,
        }
    }
}

/// Add exactly one dice-changing event to an existing transaction.
///
/// The caller MUST commit the transaction. For Roll completion, the progress
/// update and next-offer decision must share this transaction. In particular,
/// this method must not be exposed directly as a rating or reroll HTTP action
/// without the coordinated Option E and current-offer validation.
///
/// Lock ordering: this function takes the per-reader advisory lock as its first
/// database statement, before any row lock. A composite caller must invoke it
/// before acquiring any other row locks for the same reader (for example
/// `UPDATE issues` for progress); taking a row lock first and then calling this
/// function can deadlock against a concurrent same-reader command and surface
/// as a generic 500 (`40P01`).
pub async fn persist_in_transaction(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    idempotency_key: &str,
    command: &DiceCommand,
) -> Result<DiceMutation, ApiError> {
    validate(idempotency_key, command)?;

    // Identical to the legacy per-reader advisory key, with no session lookup.
    // The transaction holds the lock through the caller's commit or rollback.
    tx.query_one(
        "SELECT pg_advisory_xact_lock($1::bigint)",
        &[&(user.id() as i64)],
    )
    .await
    .map_err(db::query_error)?;

    if tx
        .query_opt(
            "SELECT id FROM users WHERE id = $1 FOR KEY SHARE",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?
        .is_none()
    {
        return Err(ApiError::Unauthorized(
            "Could not validate credentials".to_string(),
        ));
    }

    // A retry is checked BEFORE reading the current die. It must never step
    // the ladder twice, even when a later distinct command already occurred.
    let previous = tx
        .query_opt(
            "SELECT id, die, die_after, context::text
             FROM events
             WHERE user_id = $1 AND context->>'dice_command_key' = $2
             LIMIT 1",
            &[&user.id(), &idempotency_key],
        )
        .await
        .map_err(db::query_error)?;
    if let Some(row) = previous {
        let context: String = row.get(3);
        let original: Value = serde_json::from_str(&context).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            ApiError::Internal("Invalid event receipt".to_string())
        })?;
        let expected = serde_json::to_value(command).map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            ApiError::Internal("Invalid dice command".to_string())
        })?;
        if original.get("dice_command") != Some(&expected) {
            return Err(ApiError::Conflict(
                "Idempotency key already used for a different dice command".to_string(),
            ));
        }
        return Ok(DiceMutation {
            event_id: row.get(0),
            die_before: row.get(1),
            die_after: row.get(2),
            replayed: true,
        });
    }

    if let Some(thread_id) = command.thread_id() {
        if tx
            .query_opt(
                "SELECT id FROM threads WHERE id = $1 AND user_id = $2 FOR SHARE",
                &[&thread_id, &user.id()],
            )
            .await
            .map_err(db::query_error)?
            .is_none()
        {
            return Err(ApiError::NotFound("Thread not found".to_string()));
        }
    }
    if let Some(issue_id) = command.issue_id() {
        if tx
            .query_opt(
                "SELECT i.id FROM issues i
                 JOIN threads t ON t.id = i.thread_id
                 WHERE i.id = $1 AND i.thread_id = $2 AND t.user_id = $3
                 FOR SHARE OF i, t",
                &[&issue_id, &command.thread_id(), &user.id()],
            )
            .await
            .map_err(db::query_error)?
            .is_none()
        {
            return Err(ApiError::NotFound("Issue not found".to_string()));
        }
    }

    let before = dice_state::current_die(tx, user).await?;
    let after = dice_state::apply_action(before, command.action()).map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        invalid("Invalid dice command")
    })?;
    let context = json!({
        "dice_command_key": idempotency_key,
        "dice_command": command,
    })
    .to_string();
    let row = tx
        .query_one(
            "INSERT INTO events
               (user_id, type, timestamp, die, die_after, thread_id, issue_id, rating, context)
             VALUES ($1, $2, clock_timestamp(), $3, $4, $5, $6, $7, $8::text::json)
             RETURNING id",
            &[
                &user.id(),
                &command.event_type(),
                &before,
                &after,
                &command.thread_id(),
                &command.issue_id(),
                &command.rating(),
                &context,
            ],
        )
        .await
        .map_err(db::query_error)?;
    Ok(DiceMutation {
        event_id: row.get(0),
        die_before: before,
        die_after: after,
        replayed: false,
    })
}

/// Transaction-owning entry point for independent manual-selection and reset
/// operations. Composite Roll/rating flows must use persist_in_transaction.
pub async fn execute_standalone(
    client: &mut Client,
    user: AuthenticatedUser,
    idempotency_key: &str,
    command: &DiceCommand,
) -> Result<DiceMutation, ApiError> {
    if !matches!(
        command,
        DiceCommand::ManualSelect { .. } | DiceCommand::Reset
    ) {
        return Err(invalid("Composite dice action requires a Roll transaction"));
    }
    let tx = client
        .build_transaction()
        .isolation_level(IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let result = persist_in_transaction(&tx, user, idempotency_key, command).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::StatusCode;
    use tokio_postgres::NoTls;

    #[test]
    fn validate_ladder_inputs_and_no_direct_read_transition() {
        assert!(validate("valid-client-001", &DiceCommand::ManualSelect { die: 2 }).is_ok());
        assert!(validate("valid-client-001", &DiceCommand::ManualSelect { die: 30 }).is_err());
        assert!(validate("short", &DiceCommand::Reset).is_err());
        assert!(validate(
            "valid-client-001",
            &DiceCommand::RollRating {
                thread_id: 10,
                issue_id: 100,
                rating: f64::NAN,
            },
        )
        .is_err());
        assert_eq!(
            dice_state::apply_action(12, DiceAction::DirectMarkRead),
            Ok(12)
        );
        assert_eq!(
            dice_state::apply_action(6, DiceAction::RollRating(4.0)),
            Ok(4)
        );
    }

    async fn connect(url: &str) -> Client {
        let (client, connection) = tokio_postgres::connect(url, NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        client
    }

    /// Seed the canonical Alembic schema and hold it for one serialized test.
    ///
    /// The unique receipt index these tests depend on is a real migration
    /// (`ix_events_user_dice_command_key`), not a test-only fixture.
    async fn seeded(url: &str) -> (Client, tokio::sync::MutexGuard<'static, ()>) {
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let guard = crate::test_support::reset_for_test(&state).await;
        let client = connect(url).await;
        client
            .batch_execute(
                "INSERT INTO users (id, username) VALUES (1, 'reader-1'), (2, 'reader-2'); \
                 INSERT INTO threads (id, user_id, title, format, issues_remaining, status, \
                     queue_position) \
                 VALUES (10, 1, 'First', 'Comic', 1, 'active', 1), \
                        (20, 2, 'Second', 'Comic', 1, 'active', 2); \
                 INSERT INTO issues (id, thread_id, issue_number, status, created_at, position) \
                 VALUES (100, 10, '1', 'unread', now(), 1), (200, 20, '1', 'unread', now(), 1);",
            )
            .await
            .expect("seed canonical schema");
        (client, guard)
    }

    #[tokio::test]
    async fn concurrent_retries_are_exactly_once_and_other_commands_serialize() {
        let _admin = crate::test_support::required_test_admin_url();
        let url = crate::test_support::database_url().await;
        let (seed, _db) = seeded(&url).await;
        drop(seed);
        let mut first = connect(&url).await;
        let mut second = connect(&url).await;
        let cmd = DiceCommand::Reroll { thread_id: 10 };
        let (one, two) = tokio::join!(
            async {
                let tx = first.transaction().await.unwrap();
                let result = persist_in_transaction(
                    &tx,
                    AuthenticatedUser::for_test(1),
                    "same-client-key-001",
                    &cmd,
                )
                .await
                .unwrap();
                tx.commit().await.unwrap();
                result
            },
            async {
                let tx = second.transaction().await.unwrap();
                let result = persist_in_transaction(
                    &tx,
                    AuthenticatedUser::for_test(1),
                    "same-client-key-001",
                    &cmd,
                )
                .await
                .unwrap();
                tx.commit().await.unwrap();
                result
            }
        );
        assert_eq!(one.event_id, two.event_id);
        assert_eq!(one.die_before, 6);
        assert_eq!(one.die_after, 8);
        assert_ne!(one.replayed, two.replayed);

        let mut third = connect(&url).await;
        let mut fourth = connect(&url).await;
        let (a, b) = tokio::join!(
            execute_standalone(
                &mut third,
                AuthenticatedUser::for_test(1),
                "other-client-key-002",
                &DiceCommand::ManualSelect { die: 12 },
            ),
            execute_standalone(
                &mut fourth,
                AuthenticatedUser::for_test(1),
                "other-client-key-003",
                &DiceCommand::Reset,
            )
        );
        let a = a.unwrap();
        let b = b.unwrap();
        assert_ne!(a.event_id, b.event_id);
        assert!(
            (a.die_before == 8 && b.die_before == 12 && b.die_after == 6)
                || (b.die_before == 8 && a.die_before == 6 && a.die_after == 12)
        );
        let client = connect(&url).await;
        let count: i64 = client
            .query_one("SELECT COUNT(*) FROM events WHERE user_id = 1", &[])
            .await
            .unwrap()
            .get(0);
        assert_eq!(count, 3);
    }

    #[tokio::test]
    async fn owner_checks_lock_references_through_commit() {
        let _admin = crate::test_support::required_test_admin_url();
        let url = crate::test_support::database_url().await;
        let (seed, _db) = seeded(&url).await;
        drop(seed);
        let mut writer = connect(&url).await;
        let transfer = connect(&url).await;
        let tx = writer.transaction().await.unwrap();

        let result = persist_in_transaction(
            &tx,
            AuthenticatedUser::for_test(1),
            "owner-transfer-001",
            &DiceCommand::RollRating {
                thread_id: 10,
                issue_id: 100,
                rating: 4.5,
            },
        )
        .await
        .unwrap();
        assert_eq!(result.die_after, 4);

        // An owner check without a held row lock would let this transfer
        // race between validation and the event commit.
        transfer
            .batch_execute("SET lock_timeout = '250ms'")
            .await
            .unwrap();
        let err = transfer
            .execute("UPDATE threads SET user_id = 2 WHERE id = 10", &[])
            .await
            .unwrap_err();
        assert_eq!(
            err.code(),
            Some(&tokio_postgres::error::SqlState::LOCK_NOT_AVAILABLE)
        );
        let err = transfer
            .execute("UPDATE issues SET thread_id = 20 WHERE id = 100", &[])
            .await
            .unwrap_err();
        assert_eq!(
            err.code(),
            Some(&tokio_postgres::error::SqlState::LOCK_NOT_AVAILABLE)
        );

        tx.commit().await.unwrap();
        transfer
            .batch_execute("SET lock_timeout = 0")
            .await
            .unwrap();
        transfer
            .execute("UPDATE threads SET user_id = 2 WHERE id = 10", &[])
            .await
            .unwrap();

        let mut retry = connect(&url).await;
        let tx = retry.transaction().await.unwrap();
        let err = persist_in_transaction(
            &tx,
            AuthenticatedUser::for_test(1),
            "owner-transfer-002",
            &DiceCommand::Reroll { thread_id: 10 },
        )
        .await
        .unwrap_err();
        assert_eq!(err.status(), StatusCode::NOT_FOUND);
        tx.rollback().await.unwrap();
    }

    #[tokio::test]
    async fn rejects_cross_user_references_key_conflicts_and_invalid_rating() {
        let _admin = crate::test_support::required_test_admin_url();
        let url = crate::test_support::database_url().await;
        let (seed, _db) = seeded(&url).await;
        drop(seed);
        let mut client = connect(&url).await;
        let user = AuthenticatedUser::for_test(1);

        let tx = client.transaction().await.unwrap();
        let foreign = persist_in_transaction(
            &tx,
            user,
            "foreign-thread-001",
            &DiceCommand::Reroll { thread_id: 20 },
        )
        .await
        .unwrap_err();
        assert_eq!(foreign.status(), StatusCode::NOT_FOUND);
        tx.rollback().await.unwrap();

        let tx = client.transaction().await.unwrap();
        let foreign_issue = persist_in_transaction(
            &tx,
            user,
            "foreign-issue-001",
            &DiceCommand::RollRating {
                thread_id: 10,
                issue_id: 200,
                rating: 4.5,
            },
        )
        .await
        .unwrap_err();
        assert_eq!(foreign_issue.status(), StatusCode::NOT_FOUND);
        tx.rollback().await.unwrap();

        let result = execute_standalone(
            &mut client,
            user,
            "collision-key-001",
            &DiceCommand::ManualSelect { die: 4 },
        )
        .await
        .unwrap();
        assert_eq!(result.die_after, 4);
        let conflict = execute_standalone(
            &mut client,
            user,
            "collision-key-001",
            &DiceCommand::ManualSelect { die: 20 },
        )
        .await
        .unwrap_err();
        assert_eq!(conflict.status(), StatusCode::CONFLICT);
        let replay = execute_standalone(
            &mut client,
            user,
            "collision-key-001",
            &DiceCommand::ManualSelect { die: 4 },
        )
        .await
        .unwrap();
        assert_eq!(replay.event_id, result.event_id);
        assert!(replay.replayed);
    }

    #[tokio::test]
    async fn idempotency_keys_are_scoped_to_the_reader() {
        let _admin = crate::test_support::required_test_admin_url();
        let url = crate::test_support::database_url().await;
        let (seed, _db) = seeded(&url).await;
        drop(seed);
        let mut client = connect(&url).await;
        let alice = AuthenticatedUser::for_test(1);
        let bob = AuthenticatedUser::for_test(2);

        let alice_receipt = execute_standalone(
            &mut client,
            alice,
            "shared-client-key-001",
            &DiceCommand::ManualSelect { die: 4 },
        )
        .await
        .unwrap();
        // The same key text and command from a different reader is a distinct
        // action and must not replay the first reader's receipt.
        let bob_receipt = execute_standalone(
            &mut client,
            bob,
            "shared-client-key-001",
            &DiceCommand::ManualSelect { die: 4 },
        )
        .await
        .unwrap();
        assert_ne!(alice_receipt.event_id, bob_receipt.event_id);
        assert!(!bob_receipt.replayed);
        assert_eq!(bob_receipt.die_after, 4);
    }
}
