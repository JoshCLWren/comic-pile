//! Explicit Reset Dice command for the sessionless Roll flow.
//!
//! Reset records one `reset_dice` event (die becomes d6), discards any pending
//! offer, and never deletes reading progress or past ratings. The browser owns
//! clearing its temporary snooze cookie; the server does not treat it as state.
use crate::{
    auth::AuthenticatedUser,
    db,
    dice_api::Pending,
    dice_mutation::{self, DiceCommand},
    reading_session::{self, SessionPolicy},
    ApiError, AppState,
};
use axum::{extract::State, http::StatusCode, Json};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio_postgres::IsolationLevel;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResetDiceRequest {
    pub idempotency_key: String,
}

#[derive(Debug, Serialize)]
pub struct ResetDiceResponse {
    pub die: i32,
    pub replayed: bool,
}

/// Record the reset event and discard any pending offer in one transaction.
/// Extracted so the real write path can run against disposable PostgreSQL.
pub(crate) async fn persist_reset(
    tx: &tokio_postgres::Transaction<'_>,
    user: AuthenticatedUser,
    idempotency_key: &str,
    session_id: Option<i32>,
) -> Result<dice_mutation::DiceMutation, ApiError> {
    let mutation =
        dice_mutation::persist_in_transaction(tx, user, idempotency_key, &DiceCommand::Reset)
            .await?;
    if let Some(session_id) = session_id {
        let updated = tx
            .execute(
                "UPDATE sessions
                 SET pending_thread_id=NULL,pending_issue_id=NULL,
                     pending_thread_updated_at=NULL,manual_die=NULL
                 WHERE id=$1 AND user_id=$2",
                &[&session_id, &user.id()],
            )
            .await
            .map_err(db::query_error)?;
        if updated != 1 {
            return Err(ApiError(
                StatusCode::CONFLICT,
                "Reading session changed; try again",
            ));
        }
    }
    Ok(mutation)
}

pub async fn reset(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<ResetDiceRequest>,
) -> Result<Json<ResetDiceResponse>, ApiError> {
    dice_mutation::validate(&request.idempotency_key, &DiceCommand::Reset)?;
    let mut pending = Pending::new(db::checkout(&state).await?);
    let tx = pending
        .connection()
        .build_transaction()
        .isolation_level(IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    // The write transaction's first statement is the per-reader advisory lock.
    tx.query_one(
        "SELECT pg_advisory_xact_lock($1::bigint)",
        &[&(user.id() as i64)],
    )
    .await
    .map_err(db::query_error)?;

    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_secs_f64())
        .unwrap_or(0.0);
    let session_id =
        reading_session::current_session_id(&tx, user, now, SessionPolicy::default()).await?;
    let mutation = persist_reset(&tx, user, &request.idempotency_key, session_id).await?;
    tx.commit().await.map_err(db::query_error)?;
    pending.release();
    Ok(Json(ResetDiceResponse {
        die: mutation.die_after,
        replayed: mutation.replayed,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{config::Config, router};
    use axum::{
        body::Body,
        http::{Request, StatusCode},
    };
    use tower::ServiceExt;

    #[test]
    fn request_shape_requires_a_valid_explicit_key() {
        assert!(serde_json::from_str::<ResetDiceRequest>(
            r#"{"idempotency_key":"reset-dice-0123456789"}"#
        )
        .is_ok());
        assert!(serde_json::from_str::<ResetDiceRequest>(r#"{}"#).is_err());
        assert!(serde_json::from_str::<ResetDiceRequest>(
            r#"{"idempotency_key":"reset-dice-0123456789","user_id":9}"#
        )
        .is_err());
        assert!(dice_mutation::validate("short", &DiceCommand::Reset).is_err());
        assert!(dice_mutation::validate("reset dice key", &DiceCommand::Reset).is_err());
    }

    #[tokio::test]
    async fn reset_requires_authentication_before_database_access() {
        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        })
        .unwrap();
        let app = router(Arc::new(AppState::new(config).unwrap()));
        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v2/roll/reset")
                    .header("content-type", "application/json")
                    .body(Body::from(r#"{"idempotency_key":"reset-dice-0123456789"}"#))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }

    async fn test_client(url: &str, schema: &str) -> tokio_postgres::Client {
        let (client, connection) = tokio_postgres::connect(url, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        client
            .batch_execute(&format!("SET search_path TO {schema}, public"))
            .await
            .unwrap();
        client
    }

    #[tokio::test]
    async fn persist_reset_records_d6_and_clears_pending() {
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
        let schema = format!("reset_dice_{}_{}", std::process::id(), nanos);
        admin
            .batch_execute(&format!(
                "CREATE SCHEMA {schema};
                 CREATE TABLE {schema}.users (id integer PRIMARY KEY);
                 CREATE TABLE {schema}.sessions (
                     id integer PRIMARY KEY, user_id integer NOT NULL,
                     started_at timestamptz NOT NULL, ended_at timestamptz,
                     pending_thread_id integer, pending_issue_id integer,
                     pending_thread_updated_at timestamptz, manual_die integer
                 );
                 CREATE TABLE {schema}.events (
                     id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                     user_id integer, type text, session_id integer,
                     timestamp timestamptz DEFAULT NOW(),
                     die integer, die_after integer, thread_id integer,
                     issue_id integer, rating double precision, context json
                 );
                 INSERT INTO {schema}.users VALUES (1);
                 INSERT INTO {schema}.sessions VALUES
                     (1, 1, NOW() - interval '10 hours', NULL, 10, 100,
                      NOW() - interval '10 hours', 12),
                     (2, 1, NOW(), NULL, 20, 200, NOW(), 12);
                 INSERT INTO {schema}.events
                     (user_id, type, session_id, die, die_after, context)
                 VALUES (1, 'manual_die', 2, 6, 20, '{{}}'::json);"
            ))
            .await
            .unwrap();
        let mut client = test_client(&url, &schema).await;
        let user = AuthenticatedUser::for_test(1);

        let tx = client.transaction().await.unwrap();
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs_f64();
        let session_id =
            reading_session::current_session_id(&tx, user, now, SessionPolicy::default())
                .await
                .unwrap();
        assert_eq!(
            session_id,
            Some(2),
            "the stale session must not be selected"
        );
        let mutation = persist_reset(&tx, user, "reset-dice-test-001", session_id)
            .await
            .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(mutation.die_after, 6);
        assert!(!mutation.replayed);

        let event = client
            .query_one(
                "SELECT type,user_id,die,die_after,context->>'dice_command_key'
                 FROM events WHERE id=$1",
                &[&mutation.event_id],
            )
            .await
            .unwrap();
        assert_eq!(event.get::<_, String>(0), "reset_dice");
        assert_eq!(event.get::<_, i32>(1), 1);
        assert_eq!(event.get::<_, i32>(2), 20);
        assert_eq!(event.get::<_, i32>(3), 6);
        assert_eq!(event.get::<_, String>(4), "reset-dice-test-001");

        let pending = client
            .query_one(
                "SELECT pending_thread_id,pending_issue_id,manual_die
                 FROM sessions WHERE id=2",
                &[],
            )
            .await
            .unwrap();
        assert!(pending.get::<_, Option<i32>>(0).is_none());
        assert!(pending.get::<_, Option<i32>>(1).is_none());
        assert!(pending.get::<_, Option<i32>>(2).is_none());

        let stale = client
            .query_one(
                "SELECT pending_thread_id,pending_issue_id,manual_die
                 FROM sessions WHERE id=1",
                &[],
            )
            .await
            .unwrap();
        assert_eq!(stale.get::<_, i32>(0), 10);
        assert_eq!(stale.get::<_, i32>(1), 100);
        assert_eq!(stale.get::<_, i32>(2), 12);

        let tx = client.transaction().await.unwrap();
        let replay = persist_reset(&tx, user, "reset-dice-test-001", session_id)
            .await
            .unwrap();
        tx.commit().await.unwrap();
        assert!(replay.replayed);
        assert_eq!(replay.event_id, mutation.event_id);
        let count = client
            .query_one(
                "SELECT count(*)::int FROM events WHERE type='reset_dice'",
                &[],
            )
            .await
            .unwrap();
        assert_eq!(count.get::<_, i32>(0), 1);

        admin
            .batch_execute(&format!("DROP SCHEMA {schema} CASCADE"))
            .await
            .unwrap();
    }
}
