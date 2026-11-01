//! Sessionless Roll/Reroll offer over the Option E candidate pool.
//!
//! The logical die comes from the owner-scoped dice event history, never from
//! the legacy session die. Selection is uniform among the highest-ranked `N`
//! eligible Option E frontiers, where `N` is that die. Pressing Roll while an
//! offer is pending records one snooze event, steps the die up, excludes the
//! previous offer, and immediately selects again.
use crate::{
    auth::AuthenticatedUser,
    db,
    dice_mutation::{self, DiceCommand},
    dice_state, option_inputs,
    reading_session::{self, SessionPolicy},
    roll_pool::offer_frontiers,
    ApiError, AppState,
};
use axum::{extract::State, http::StatusCode, Json};
use rand::RngExt;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::{collections::HashSet, sync::Arc};
use tokio_postgres::IsolationLevel;

/// Maximum number of browser-supplied temporary snoozes accepted per roll.
const MAX_COOKIE_SNOOZES: usize = 200;
/// Leave room for the derived snooze key inside the writer's 128-byte limit.
const MAX_OFFER_KEY: usize = 100;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RollOfferRequest {
    /// Browser timezone used only by the retained session bridge.
    #[serde(default)]
    pub timezone: Option<String>,
    /// Threads this browser has temporarily snoozed (cookie authority only).
    #[serde(default)]
    pub snoozed_thread_ids: Vec<i32>,
    /// Stable client key; retries return the original offer without re-rolling.
    pub idempotency_key: String,
}

#[derive(Debug, Serialize)]
pub struct RollOfferResponse {
    pub thread_id: i32,
    pub title: String,
    pub format: String,
    pub issues_remaining: i32,
    pub queue_position: i32,
    pub die_size: i32,
    pub result: i32,
    pub offset: i32,
    pub snoozed_count: i32,
    pub issue_id: Option<i32>,
    pub issue_number: Option<String>,
    pub next_issue_id: Option<i32>,
    pub next_issue_number: Option<String>,
    pub total_issues: Option<i32>,
    pub reading_progress: Option<String>,
    pub explanation: Option<String>,
    pub last_rolled_result: Option<i32>,
    /// Thread snoozed by this request so the browser can extend its cookie.
    pub snoozed_thread_id: Option<i32>,
}

fn invalid_key() -> ApiError {
    ApiError(
        StatusCode::UNPROCESSABLE_ENTITY,
        "Invalid idempotency key".to_string(),
    )
}

fn validate_key(key: &str) -> Result<(), ApiError> {
    let valid_length = (8..=MAX_OFFER_KEY).contains(&key.len());
    let valid_chars = key
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-');
    if valid_length && valid_chars {
        Ok(())
    } else {
        Err(invalid_key())
    }
}

fn empty_pool() -> ApiError {
    ApiError(
        StatusCode::BAD_REQUEST,
        "No eligible comics to roll. Add comics or reset temporary snoozes.".to_string(),
    )
}

fn unavailable() -> ApiError {
    ApiError(
        StatusCode::INTERNAL_SERVER_ERROR,
        "Roll offer unavailable".to_string(),
    )
}

/// Cookie IDs are exclusion hints only. Intersecting with the live Option E
/// frontier keeps them from granting or removing anything else, and clearing
/// the cookie restores the thread without touching die history.
fn cookie_exclusions(snoozed: &[i32], eligible: &HashSet<i32>) -> HashSet<i32> {
    snoozed
        .iter()
        .copied()
        .filter(|thread_id| eligible.contains(thread_id))
        .collect()
}

struct OfferMetadata {
    thread_id: i32,
    title: String,
    format: String,
    issues_remaining: i32,
    queue_position: i32,
    total_issues: Option<i32>,
    reading_progress: Option<String>,
}

/// Load the retained thread projection only. Issue identity always comes from
/// the live Option E frontier, never from the denormalized stored pointer.
async fn offer_metadata(
    conn: &tokio_postgres::Client,
    user: AuthenticatedUser,
    thread_id: i32,
) -> Result<OfferMetadata, ApiError> {
    let row = conn
        .query_opt(
            "SELECT t.id,t.title,t.format,t.issues_remaining,t.queue_position,
               t.total_issues,t.reading_progress
             FROM threads t
             WHERE t.id=$1 AND t.user_id=$2",
            &[&thread_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(unavailable)?;
    Ok(OfferMetadata {
        thread_id: row.try_get(0).map_err(db::query_error)?,
        title: row.try_get(1).map_err(db::query_error)?,
        format: row.try_get(2).map_err(db::query_error)?,
        issues_remaining: row.try_get(3).map_err(db::query_error)?,
        queue_position: row.try_get(4).map_err(db::query_error)?,
        total_issues: row.try_get(5).map_err(db::query_error)?,
        reading_progress: row.try_get(6).map_err(db::query_error)?,
    })
}

fn response(
    metadata: OfferMetadata,
    issue_id: Option<i32>,
    issue_number: Option<String>,
    die: i32,
    result: i32,
    snoozed_thread_id: Option<i32>,
) -> RollOfferResponse {
    RollOfferResponse {
        thread_id: metadata.thread_id,
        title: metadata.title,
        format: metadata.format,
        issues_remaining: metadata.issues_remaining,
        queue_position: metadata.queue_position,
        die_size: die,
        result,
        offset: 0,
        snoozed_count: i32::from(snoozed_thread_id.is_some()),
        next_issue_id: issue_id,
        next_issue_number: issue_number.clone(),
        issue_id,
        issue_number,
        total_issues: metadata.total_issues,
        reading_progress: metadata.reading_progress,
        explanation: None,
        last_rolled_result: Some(result),
        snoozed_thread_id,
    }
}

struct StoredOffer {
    thread_id: i32,
    die: i32,
    result: i32,
    issue_id: Option<i32>,
    issue_number: Option<String>,
    snoozed_thread_id: Option<i32>,
}

/// Return a stored offer for an exact key retry, including the thread this
/// offer snoozed so the browser cookie can reconcile an ambiguous response.
async fn existing_offer(
    conn: &tokio_postgres::Client,
    user: AuthenticatedUser,
    key: &str,
) -> Result<Option<StoredOffer>, ApiError> {
    let row = conn
        .query_opt(
            "SELECT selected_thread_id,die,result,issue_id,issue_number,
                    NULLIF(context->>'snoozed_thread_id','')::int
             FROM events
             WHERE user_id=$1 AND type='roll'
               AND selected_thread_id IS NOT NULL
               AND die IS NOT NULL AND result IS NOT NULL
               AND context->>'roll_offer_key'=$2
             ORDER BY timestamp DESC,id DESC LIMIT 1",
            &[&user.id(), &key],
        )
        .await
        .map_err(db::query_error)?;
    match row {
        Some(row) => Ok(Some(StoredOffer {
            thread_id: row.try_get(0).map_err(db::query_error)?,
            die: row.try_get(1).map_err(db::query_error)?,
            result: row.try_get(2).map_err(db::query_error)?,
            issue_id: row.try_get(3).map_err(db::query_error)?,
            issue_number: row.try_get(4).map_err(db::query_error)?,
            snoozed_thread_id: row.try_get(5).map_err(db::query_error)?,
        })),
        None => Ok(None),
    }
}

/// Text-first cast: the driver binds `context` as text, so `$8::json` makes
/// PostgreSQL infer a JSON parameter and reject the String. `::text::json`
/// keeps the wire type text and performs the cast server-side.
const OFFER_EVENT_INSERT: &str = "INSERT INTO events
   (type,user_id,session_id,selected_thread_id,die,result,issue_id,
    issue_number,selection_method,context,timestamp)
 VALUES ('roll',$1,$2,$3,$4,$5,$6,$7,'rust_uniform',$8::text::json,NOW())
 RETURNING id";

pub(crate) struct OfferWrite<'a> {
    pub session_id: i32,
    pub thread_id: i32,
    pub issue_id: i32,
    pub issue_number: Option<String>,
    pub die: i32,
    pub result: i32,
    pub idempotency_key: &'a str,
    pub snoozed_thread_id: Option<i32>,
}

/// Write the roll event and advance the retained pending bridge atomically.
/// Extracted so the real write path can be exercised against disposable Postgres.
pub(crate) async fn persist_offer(
    tx: &tokio_postgres::Transaction<'_>,
    user: AuthenticatedUser,
    write: OfferWrite<'_>,
) -> Result<i32, ApiError> {
    let context = json!({
        "roll_offer_key": write.idempotency_key,
        "snoozed_thread_id": write.snoozed_thread_id,
    });
    let row = tx
        .query_one(
            OFFER_EVENT_INSERT,
            &[
                &user.id(),
                &write.session_id,
                &write.thread_id,
                &write.die,
                &write.result,
                &write.issue_id,
                &write.issue_number,
                &context.to_string(),
            ],
        )
        .await
        .map_err(db::query_error)?;
    // The legacy rating bridge reads both pending columns; leaving the issue
    // unset would make the next bootstrap fail its pending validation.
    let updated = tx
        .execute(
            "UPDATE sessions
             SET pending_thread_id=$1,pending_issue_id=$2,
                 pending_thread_updated_at=NOW()
             WHERE id=$3 AND user_id=$4",
            &[
                &write.thread_id,
                &write.issue_id,
                &write.session_id,
                &user.id(),
            ],
        )
        .await
        .map_err(db::query_error)?;
    if updated != 1 {
        return Err(ApiError(
            StatusCode::CONFLICT,
            "Reading session changed; try again".to_string(),
        ));
    }
    Ok(row.get(0))
}

pub async fn offer(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<RollOfferRequest>,
) -> Result<Json<RollOfferResponse>, ApiError> {
    validate_key(&request.idempotency_key)?;
    if request.snoozed_thread_ids.len() > MAX_COOKIE_SNOOZES {
        return Err(ApiError(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Too many temporary snoozes".to_string(),
        ));
    }
    let active = reading_session::bootstrap(
        &state,
        user,
        request.timezone.as_deref(),
        SessionPolicy::default(),
    )
    .await?;
    // Compute the read-only Option E snapshot before taking the write
    // connection so this request never nests two pool checkouts.
    let validated = option_inputs::load_option_inputs(&state, user).await?;
    let candidates = validated.eligible_frontiers().map_err(|_| {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Invalid reading constraints".to_string(),
        )
    })?;

    let mut pending = crate::dice_api::Pending::new(db::checkout(&state).await?);
    let tx = pending
        .connection()
        .build_transaction()
        .isolation_level(IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    // The write transaction's first statement is the per-reader advisory lock;
    // bootstrap and the read-only snapshot above use their own connections.
    tx.query_one(
        "SELECT pg_advisory_xact_lock($1::bigint)",
        &[&(user.id() as i64)],
    )
    .await
    .map_err(db::query_error)?;

    if let Some(stored) = existing_offer(tx.client(), user, &request.idempotency_key).await? {
        tx.rollback().await.map_err(db::query_error)?;
        let metadata = offer_metadata(&*pending.connection(), user, stored.thread_id).await?;
        return Ok(Json(response(
            metadata,
            stored.issue_id,
            stored.issue_number,
            stored.die,
            stored.result,
            stored.snoozed_thread_id,
        )));
    }

    // Re-read the pending offer under the lock. The bootstrap snapshot above
    // predates it, so relying on it would let two different-key presses both
    // roll and overwrite the first offer without snoozing it.
    let locked = tx
        .query_opt(
            "SELECT pending_thread_id FROM sessions
             WHERE id=$1 AND user_id=$2 FOR UPDATE",
            &[&active.session.id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or(ApiError(
            StatusCode::CONFLICT,
            "Reading session changed; try again".to_string(),
        ))?;
    let previous_offer: Option<i32> = locked.try_get(0).map_err(db::query_error)?;

    // Temporary snoozes are cookie-owned. Legacy session skip/snooze arrays and
    // the durable Fibonacci backoff must not remove candidates from the new
    // offer, or clearing the midnight cookie could not restore them.
    let mut excluded: HashSet<i32> = HashSet::new();
    let candidate_ids: Vec<i32> = candidates
        .iter()
        .map(|candidate| candidate.thread_id)
        .collect();

    let mut die = dice_state::current_die(&tx, user).await?;
    let mut snoozed_thread_id = None;
    if let Some(previous) = previous_offer {
        let snooze_key = format!("{}-snooze", request.idempotency_key);
        let mutation = dice_mutation::persist_in_transaction(
            &tx,
            user,
            &snooze_key,
            &DiceCommand::Reroll {
                thread_id: previous,
            },
        )
        .await?;
        die = mutation.die_after;
        excluded.insert(previous);
        snoozed_thread_id = Some(previous);
    }

    let eligible_threads: HashSet<i32> = candidate_ids.iter().copied().collect();
    excluded.extend(cookie_exclusions(
        &request.snoozed_thread_ids,
        &eligible_threads,
    ));

    let pool = offer_frontiers(&candidates, &excluded, die);
    if pool.is_empty() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(empty_pool());
    }
    let index = rand::rng().random_range(0..pool.len());
    let selected = pool[index];
    let result = index as i32 + 1;

    let issue_number = validated
        .inputs()
        .core
        .issues
        .iter()
        .find(|issue| issue.id == selected.issue_id)
        .map(|issue| issue.issue_number.clone());
    persist_offer(
        &tx,
        user,
        OfferWrite {
            session_id: active.session.id,
            thread_id: selected.thread_id,
            issue_id: selected.issue_id,
            issue_number: issue_number.clone(),
            die,
            result,
            idempotency_key: &request.idempotency_key,
            snoozed_thread_id,
        },
    )
    .await?;
    tx.commit().await.map_err(db::query_error)?;
    let metadata = offer_metadata(&*pending.connection(), user, selected.thread_id).await?;
    pending.release();
    Ok(Json(response(
        metadata,
        Some(selected.issue_id),
        issue_number,
        die,
        result,
        snoozed_thread_id,
    )))
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
    fn rejects_unbounded_or_malformed_idempotency_keys() {
        assert!(validate_key("roll-offer-0123456789").is_ok());
        assert!(validate_key("short").is_err());
        assert!(validate_key(&"a".repeat(MAX_OFFER_KEY + 1)).is_err());
        assert!(validate_key("roll offer key").is_err());
        assert!(validate_key("roll/offer").is_err());
    }

    fn frontier(thread_id: i32) -> crate::reading_constraints::EligibleFrontier {
        crate::reading_constraints::EligibleFrontier {
            thread_id,
            issue_id: thread_id * 100,
            queue_position: thread_id,
        }
    }

    fn ids(pool: &[crate::reading_constraints::EligibleFrontier]) -> Vec<i32> {
        pool.iter().map(|candidate| candidate.thread_id).collect()
    }

    #[test]
    fn bounded_pool_never_backfills_a_snoozed_candidate() {
        let candidates: Vec<_> = (1..=4).map(frontier).collect();
        let excluded = HashSet::from([2, 3]);
        let pool = offer_frontiers(&candidates, &excluded, 2);
        // #2 is inside the d2 scope; removing it shrinks the pool to one choice
        // instead of pulling #3 up from outside the scope.
        assert_eq!(ids(&pool), vec![1]);

        let excluded = HashSet::from([3]);
        let pool = offer_frontiers(&candidates, &excluded, 4);
        assert_eq!(ids(&pool), vec![1, 2, 4]);

        assert!(offer_frontiers(&[], &HashSet::new(), 6).is_empty());
    }

    #[test]
    fn cookie_exclusions_are_bounded_and_restore_when_cleared() {
        let eligible = HashSet::from([1, 2, 3]);
        let snoozed = cookie_exclusions(&[2, 9], &eligible);
        assert_eq!(snoozed, HashSet::from([2]));
        assert!(cookie_exclusions(&[], &eligible).is_empty());

        let candidates: Vec<_> = (1..=3).map(frontier).collect();
        let pool = offer_frontiers(&candidates, &snoozed, 3);
        assert_eq!(ids(&pool), vec![1, 3]);

        let cleared = cookie_exclusions(&[], &eligible);
        let pool = offer_frontiers(&candidates, &cleared, 3);
        assert_eq!(
            ids(&pool),
            vec![1, 2, 3],
            "clearing the midnight cookie restores the candidate"
        );
    }

    #[test]
    fn request_shape_requires_an_explicit_key_and_rejects_unknown_fields() {
        assert!(serde_json::from_str::<RollOfferRequest>(
            r#"{"idempotency_key":"roll-offer-0123456789","snoozed_thread_ids":[4,8]}"#
        )
        .is_ok());
        assert!(serde_json::from_str::<RollOfferRequest>(
            r#"{"idempotency_key":"roll-offer-0123456789","user_id":9}"#
        )
        .is_err());
        assert!(serde_json::from_str::<RollOfferRequest>(r#"{}"#).is_err());
    }

    #[tokio::test]
    async fn offer_requires_authentication_before_database_access() {
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
                    .uri("/api/v2/roll/offer")
                    .header("content-type", "application/json")
                    .body(Body::from(r#"{"idempotency_key":"roll-offer-0123456789"}"#))
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
    async fn stored_offer_lookup_and_metadata_are_owner_scoped() {
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
        let schema = format!("roll_offer_{}_{}", std::process::id(), nanos);
        admin
            .batch_execute(&format!(
                "CREATE SCHEMA {schema};
                 CREATE TABLE {schema}.users (id integer PRIMARY KEY);
                 CREATE TABLE {schema}.threads (
                     id integer PRIMARY KEY, user_id integer NOT NULL, title text,
                     format text, issues_remaining integer, queue_position integer,
                     total_issues integer, reading_progress text, next_unread_issue_id integer
                 );
                 CREATE TABLE {schema}.issues (
                     id integer PRIMARY KEY, thread_id integer, issue_number text
                 );
                 CREATE TABLE {schema}.events (
                     id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                     user_id integer, type text, timestamp timestamptz DEFAULT NOW(),
                     selected_thread_id integer, die integer, result integer,
                     issue_id integer, issue_number text, selection_method text,
                     context json
                 );
                 INSERT INTO {schema}.users VALUES (1), (2);
                 INSERT INTO {schema}.threads VALUES
                     (10, 1, 'Saga', 'Comic', 3, 1, 12, '25%', 100);
                 INSERT INTO {schema}.issues VALUES (100, 10, '1');
                 INSERT INTO {schema}.events
                     (user_id, type, selected_thread_id, die, result, issue_id,
                      issue_number, context)
                 VALUES (1, 'roll', 10, 6, 2, 100, '1',
                         '{{\"roll_offer_key\":\"roll-offer-abc\",\"snoozed_thread_id\":7}}');"
            ))
            .await
            .unwrap();
        let client = test_client(&url, &schema).await;
        let owner = AuthenticatedUser::for_test(1);
        let other = AuthenticatedUser::for_test(2);

        let stored = existing_offer(&client, owner, "roll-offer-abc")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(stored.thread_id, 10);
        assert_eq!(stored.die, 6);
        assert_eq!(stored.result, 2);
        assert_eq!(stored.issue_id, Some(100));
        assert_eq!(stored.issue_number.as_deref(), Some("1"));
        assert_eq!(stored.snoozed_thread_id, Some(7));
        assert!(existing_offer(&client, other, "roll-offer-abc")
            .await
            .unwrap()
            .is_none());

        let metadata = offer_metadata(&client, owner, 10).await.unwrap();
        assert_eq!(metadata.thread_id, 10);
        assert_eq!(metadata.title, "Saga");
        assert!(offer_metadata(&client, other, 10).await.is_err());

        admin
            .batch_execute(&format!("DROP SCHEMA {schema} CASCADE"))
            .await
            .unwrap();
    }

    #[tokio::test]
    async fn offer_event_insert_binds_text_json_context() {
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
        let schema = format!("offer_insert_{}_{}", std::process::id(), nanos);
        admin
            .batch_execute(&format!(
                "CREATE SCHEMA {schema};
                 CREATE TABLE {schema}.users (id integer PRIMARY KEY);
                 CREATE TABLE {schema}.sessions (
                     id integer PRIMARY KEY, user_id integer NOT NULL
                 );
                 CREATE TABLE {schema}.threads (
                     id integer PRIMARY KEY, user_id integer NOT NULL
                 );
                 CREATE TABLE {schema}.issues (
                     id integer PRIMARY KEY, thread_id integer NOT NULL
                 );
                 CREATE TABLE {schema}.events (
                     id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                     type text NOT NULL, user_id integer, session_id integer,
                     selected_thread_id integer, die integer, result integer,
                     issue_id integer, issue_number text, selection_method text,
                     context json, timestamp timestamptz DEFAULT NOW()
                 );
                 INSERT INTO {schema}.users VALUES (1);
                 INSERT INTO {schema}.sessions VALUES (1, 1);
                 INSERT INTO {schema}.threads VALUES (10, 1);
                 INSERT INTO {schema}.issues VALUES (100, 10);"
            ))
            .await
            .unwrap();
        let client = test_client(&url, &schema).await;
        let context = json!({
            "roll_offer_key": "roll-offer-0123456789",
            "snoozed_thread_id": null,
        })
        .to_string();

        // This is the production binding: a Rust String for a text parameter
        // cast server-side to JSON. `$8::json` makes the driver infer JSON and
        // rejects the String, which is the 500 this regression pins.
        let row = client
            .query_one(
                OFFER_EVENT_INSERT,
                &[
                    &1i32,
                    &1i32,
                    &10i32,
                    &6i32,
                    &1i32,
                    &100i32,
                    &Some("1".to_string()),
                    &context,
                ],
            )
            .await
            .unwrap();
        assert!(row.get::<_, i32>(0) > 0);

        admin
            .batch_execute(&format!("DROP SCHEMA {schema} CASCADE"))
            .await
            .unwrap();
    }

    #[tokio::test]
    async fn persist_offer_writes_the_event_and_pending_bridge() {
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
        let schema = format!("offer_write_{}_{}", std::process::id(), nanos);
        admin
            .batch_execute(&format!(
                "CREATE SCHEMA {schema};
                 CREATE TABLE {schema}.users (id integer PRIMARY KEY);
                 CREATE TABLE {schema}.sessions (
                     id integer PRIMARY KEY, user_id integer NOT NULL,
                     pending_thread_id integer, pending_issue_id integer,
                     pending_thread_updated_at timestamptz
                 );
                 CREATE TABLE {schema}.threads (
                     id integer PRIMARY KEY, user_id integer NOT NULL
                 );
                 CREATE TABLE {schema}.issues (
                     id integer PRIMARY KEY, thread_id integer NOT NULL
                 );
                 CREATE TABLE {schema}.events (
                     id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                     type text NOT NULL, user_id integer, session_id integer,
                     selected_thread_id integer, die integer, result integer,
                     issue_id integer, issue_number text, selection_method text,
                     context json, timestamp timestamptz DEFAULT NOW()
                 );
                 INSERT INTO {schema}.users VALUES (1);
                 INSERT INTO {schema}.sessions VALUES (1, 1, NULL, NULL, NULL);
                 INSERT INTO {schema}.threads VALUES (10, 1);
                 INSERT INTO {schema}.issues VALUES (100, 10);"
            ))
            .await
            .unwrap();
        let mut client = test_client(&url, &schema).await;
        let user = AuthenticatedUser::for_test(1);

        let tx = client.transaction().await.unwrap();
        let event_id = persist_offer(
            &tx,
            user,
            OfferWrite {
                session_id: 1,
                thread_id: 10,
                issue_id: 100,
                issue_number: Some("1".to_string()),
                die: 8,
                result: 2,
                idempotency_key: "test-offer-write-001",
                snoozed_thread_id: Some(9),
            },
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();

        let event = client
            .query_one(
                "SELECT type,user_id,session_id,selected_thread_id,die,result,
                        issue_id,issue_number,context->>'roll_offer_key',
                        context->>'snoozed_thread_id'
                 FROM events WHERE id=$1",
                &[&event_id],
            )
            .await
            .unwrap();
        assert_eq!(event.get::<_, String>(0), "roll");
        assert_eq!(event.get::<_, i32>(1), 1);
        assert_eq!(event.get::<_, i32>(2), 1);
        assert_eq!(event.get::<_, i32>(3), 10);
        assert_eq!(event.get::<_, i32>(4), 8);
        assert_eq!(event.get::<_, i32>(5), 2);
        assert_eq!(event.get::<_, i32>(6), 100);
        assert_eq!(event.get::<_, String>(7), "1");
        assert_eq!(event.get::<_, String>(8), "test-offer-write-001");
        assert_eq!(event.get::<_, String>(9), "9");

        let pending = client
            .query_one(
                "SELECT pending_thread_id,pending_issue_id FROM sessions WHERE id=1",
                &[],
            )
            .await
            .unwrap();
        assert_eq!(pending.get::<_, i32>(0), 10);
        assert_eq!(pending.get::<_, i32>(1), 100);

        let stored = existing_offer(&client, user, "test-offer-write-001")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(stored.thread_id, 10);
        assert_eq!(stored.die, 8);
        assert_eq!(stored.result, 2);
        assert_eq!(stored.snoozed_thread_id, Some(9));

        admin
            .batch_execute(&format!("DROP SCHEMA {schema} CASCADE"))
            .await
            .unwrap();
    }
}
