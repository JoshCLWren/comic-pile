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
    ApiError(StatusCode::UNPROCESSABLE_ENTITY, "Invalid idempotency key")
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
        "No eligible comics to roll. Add comics or reset temporary snoozes.",
    )
}

fn unavailable() -> ApiError {
    ApiError(StatusCode::INTERNAL_SERVER_ERROR, "Roll offer unavailable")
}

/// Take the highest-ranked `die` eligible candidates, then apply temporary
/// exclusions without backfilling from below that bound.
fn bounded_pool<T>(
    candidates: impl IntoIterator<Item = T>,
    is_excluded: impl Fn(&T) -> bool,
    die: i32,
) -> Vec<T> {
    candidates
        .into_iter()
        .take(die.max(0) as usize)
        .filter(|candidate| !is_excluded(candidate))
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

pub async fn offer(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<RollOfferRequest>,
) -> Result<Json<RollOfferResponse>, ApiError> {
    validate_key(&request.idempotency_key)?;
    if request.snoozed_thread_ids.len() > MAX_COOKIE_SNOOZES {
        return Err(ApiError(
            StatusCode::UNPROCESSABLE_ENTITY,
            "Too many temporary snoozes",
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
            "Invalid reading constraints",
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
            "Reading session changed; try again",
        ))?;
    let previous_offer: Option<i32> = locked.try_get(0).map_err(db::query_error)?;

    let mut excluded: HashSet<i32> = active
        .session
        .skipped_thread_ids
        .clone()
        .unwrap_or_default()
        .into_iter()
        .chain(
            active
                .session
                .snoozed_thread_ids
                .clone()
                .unwrap_or_default(),
        )
        .collect();
    let candidate_ids: Vec<i32> = candidates
        .iter()
        .map(|candidate| candidate.thread_id)
        .collect();
    excluded.extend(crate::bootstrap::durable_snoozed(tx.client(), user, &candidate_ids).await?);

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

    // Cookie IDs are exclusion hints only. Intersecting with the live Option E
    // frontier keeps them from granting or removing anything else.
    let eligible_threads: HashSet<i32> = candidate_ids.iter().copied().collect();
    excluded.extend(
        request
            .snoozed_thread_ids
            .into_iter()
            .filter(|thread_id| eligible_threads.contains(thread_id)),
    );

    let pool = bounded_pool(
        candidates.iter().copied(),
        |candidate| excluded.contains(&candidate.thread_id),
        die,
    );
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
    let context = json!({
        "roll_offer_key": request.idempotency_key,
        "snoozed_thread_id": snoozed_thread_id,
    });
    tx.query_one(
        "INSERT INTO events
           (type,user_id,session_id,selected_thread_id,die,result,issue_id,
            issue_number,selection_method,context,timestamp)
         VALUES ('roll',$1,$2,$3,$4,$5,$6,$7,'rust_uniform',$8::json,NOW())
         RETURNING id",
        &[
            &user.id(),
            &active.session.id,
            &selected.thread_id,
            &die,
            &result,
            &selected.issue_id,
            &issue_number,
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
                &selected.thread_id,
                &selected.issue_id,
                &active.session.id,
                &user.id(),
            ],
        )
        .await
        .map_err(db::query_error)?;
    if updated != 1 {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(ApiError(
            StatusCode::CONFLICT,
            "Reading session changed; try again",
        ));
    }
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

    #[test]
    fn bounded_pool_never_backfills_a_snoozed_candidate() {
        let candidates = vec![(1, "first"), (2, "second"), (3, "third"), (4, "fourth")];
        let excluded = HashSet::from([2, 3]);
        let pool = bounded_pool(candidates, |candidate| excluded.contains(&candidate.0), 2);
        // #2 is inside the d2 scope; removing it shrinks the pool to one choice
        // instead of pulling #3 up from outside the scope.
        assert_eq!(pool, vec![(1, "first")]);

        let candidates = vec![(1, "first"), (2, "second"), (3, "third"), (4, "fourth")];
        let excluded = HashSet::from([3]);
        let pool = bounded_pool(candidates, |candidate| excluded.contains(&candidate.0), 4);
        assert_eq!(pool, vec![(1, "first"), (2, "second"), (4, "fourth")]);

        let empty: Vec<(i32, &str)> = Vec::new();
        assert!(bounded_pool(empty, |_| false, 6).is_empty());
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
                         '{{\"roll_offer_key\":\"roll-offer-abc\"}}');"
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
        assert_eq!(stored.snoozed_thread_id, None);
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
}
