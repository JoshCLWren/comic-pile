//! Owner-scoped Queue entry resources for the v2 API.
//!
//! `PATCH /api/v2/queue-entries/{thread_id}` replaces the action-shaped v1
//! `front`/`back`/`position` routes: front and back are simply target ranks for
//! the same `position` field. `POST /api/v2/queue-orders` records a durable,
//! idempotent queue-order revision for a shuffle instead of an opaque action
//! call.
//!
//! The thread id is the canonical queue-entry identity because it is the stable
//! identifier every existing frontend caller already knows; there is no separate
//! queue-entry row. `position` is the reader-visible dense ordinal the Queue
//! displays (readable rows before blocked rows), which is also the space the
//! reposition dialog submits. `ordering_version` is the entry's monotonic
//! `threads.queue_order_key` revision, bumped whenever a mutation changes that
//! entry's rank.
//!
//! Every mutation takes the same transaction-scoped advisory lock the Python
//! queue writer uses, so concurrent moves and shuffles serialize per reader.
//! Reorder and shuffle events reuse the durable `events` table, so retries can
//! recover the recorded revision instead of re-shuffling.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use deadpool_postgres::Object;
use rand::RngExt;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio_postgres::Transaction;

/// Advisory-lock namespace shared with `comic_pile.queue.ADVISORY_LOCK_NAMESPACE`.
const QUEUE_LOCK_NAMESPACE: i32 = 699001;

/// Queue entry resource returned by GET and PATCH.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct QueueEntryResponse {
    /// Canonical queue-entry identity: the owned Thread id.
    pub thread_id: i32,
    /// One-based dense reader-visible Queue ordinal.
    pub position: i32,
    /// Monotonic ordering revision for this entry (0 before its first change).
    pub ordering_version: i64,
}

/// Resource patch for one queue entry.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QueueEntryPatch {
    /// Target reader-visible ordinal. Ranks beyond the end place the entry last.
    pub position: i32,
}

/// Queue-order (shuffle) creation request.
#[derive(Debug, Default, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct QueueOrderRequest {
    /// Client retry key. Replaying a committed key returns the same revision.
    pub idempotency_key: Option<String>,
}

/// Durable queue-order revision.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct QueueOrderResponse {
    /// Persisted `events.id` of this queue-order revision.
    pub event_id: i32,
    /// True when an identical `idempotency_key` was already committed.
    pub replayed: bool,
    /// Number of entries whose position this revision wrote.
    pub shuffled: i32,
}

/// A cancelled PostgreSQL command must never recycle a possibly busy connection.
struct Pending(Option<Object>);
impl Drop for Pending {
    fn drop(&mut self) {
        if let Some(connection) = self.0.take() {
            drop(Object::take(connection));
        }
    }
}

fn bad_request(detail: String) -> ApiError {
    ApiError(StatusCode::BAD_REQUEST, detail)
}

fn not_found(thread_id: i32) -> ApiError {
    ApiError(
        StatusCode::NOT_FOUND,
        format!("Thread {thread_id} not found"),
    )
}

fn option_e_enabled() -> bool {
    std::env::var("OPTION_E_ENABLED")
        .map(|value| {
            matches!(
                value.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "t" | "yes" | "y" | "on"
            )
        })
        .unwrap_or(false)
}

/// Return the blocked grouping authority used by Queue ordering.
///
/// Production defaults to the stored `threads.is_blocked` flag, matching the
/// legacy authority Python uses when Option E is disabled. When Option E is
/// explicitly enabled, ordering follows the same evaluated eligibility graph
/// instead of silently reverting to the stored flag.
async fn blocked_thread_ids(
    state: &AppState,
    user: AuthenticatedUser,
    queued: &[(i32, i32, bool)],
) -> Result<Option<std::collections::HashSet<i32>>, ApiError> {
    if !option_e_enabled() {
        return Ok(None);
    }
    let validated = crate::option_inputs::load_option_inputs(state, user).await?;
    let evaluated = crate::reading_eligibility::evaluate(&validated)?;
    Ok(Some(
        queued
            .iter()
            .map(|(id, _, _)| *id)
            .filter(|id| !evaluated.get(id).is_some_and(|thread| thread.eligible))
            .collect(),
    ))
}

struct OrderedEntry {
    thread_id: i32,
    queue_position: i32,
    is_blocked: bool,
}

/// Load the owner's active queued rows in reader-visible order.
async fn load_ordered_queue(
    state: &AppState,
    transaction: &Transaction<'_>,
    user: AuthenticatedUser,
) -> Result<Vec<OrderedEntry>, ApiError> {
    let rows = transaction
        .query(
            "SELECT id, queue_position, is_blocked FROM threads \
             WHERE user_id = $1::int AND status = 'active' AND queue_position >= 1",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let mut entries: Vec<OrderedEntry> = rows
        .iter()
        .map(|row| OrderedEntry {
            thread_id: row.get(0),
            queue_position: row.get(1),
            is_blocked: row.get(2),
        })
        .collect();
    let raw: Vec<(i32, i32, bool)> = entries
        .iter()
        .map(|entry| (entry.thread_id, entry.queue_position, entry.is_blocked))
        .collect();
    if let Some(blocked) = blocked_thread_ids(state, user, &raw).await? {
        for entry in &mut entries {
            entry.is_blocked = blocked.contains(&entry.thread_id);
        }
    }
    // Readable entries sort ahead of blocked entries; queue rank then id breaks
    // ties deterministically, exactly like Python's `build_sort_order`.
    entries.sort_by_key(|entry| (entry.is_blocked, entry.queue_position, entry.thread_id));
    Ok(entries)
}

fn ordinal_of(entries: &[OrderedEntry], thread_id: i32) -> Option<usize> {
    entries
        .iter()
        .position(|entry| entry.thread_id == thread_id)
        .map(|index| index + 1)
}

/// Read one owned queue entry.
pub async fn get_queue_entry(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(thread_id): Path<i32>,
) -> Result<Json<QueueEntryResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let row = db::query_one_optional(
        &state,
        connection,
        "WITH ordered AS ( \
             SELECT id, queue_order_key, \
                    (row_number() OVER (ORDER BY is_blocked, queue_position, id))::int AS ordinal \
             FROM threads \
             WHERE user_id = $2::int AND status = 'active' AND queue_position >= 1 \
         ) \
         SELECT ordinal, COALESCE(queue_order_key, 0) FROM ordered WHERE id = $1",
        &[&thread_id, &user.id()],
    )
    .await?
    .ok_or_else(|| not_found(thread_id))?;
    Ok(Json(QueueEntryResponse {
        thread_id,
        position: row.get(0),
        ordering_version: row.get(1),
    }))
}

/// Move one owned queue entry to the requested reader-visible ordinal.
pub async fn update_queue_entry(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(thread_id): Path<i32>,
    Json(patch): Json<QueueEntryPatch>,
) -> Result<Json<QueueEntryResponse>, ApiError> {
    if patch.position < 1 {
        return Err(bad_request(format!(
            "Position must be at least 1, got {}",
            patch.position
        )));
    }
    let user_id = user.id();
    let mut pending = Pending(Some(db::checkout(&state).await?));
    let transaction = pending
        .0
        .as_mut()
        .expect("checked-out PostgreSQL client")
        .transaction()
        .await
        .map_err(db::query_error)?;
    transaction
        .execute(
            "SELECT pg_advisory_xact_lock($1, $2)",
            &[&QUEUE_LOCK_NAMESPACE, &user_id],
        )
        .await
        .map_err(db::query_error)?;

    let entries = load_ordered_queue(&state, &transaction, user).await?;
    let current = ordinal_of(&entries, thread_id).ok_or_else(|| not_found(thread_id))?;
    let total = entries.len();
    // A rank beyond the end expresses "back" without a custom action method.
    let requested = usize::try_from(patch.position)
        .unwrap_or(usize::MAX)
        .min(total);
    // Blocked rows always display after every readable row, so clamp a target
    // that crosses groups to the nearest reachable ordinal (#4181).
    let first_blocked = entries
        .iter()
        .position(|entry| entry.is_blocked)
        .unwrap_or(total);
    let target_is_blocked = entries[current - 1].is_blocked;
    let group_start = if target_is_blocked {
        first_blocked + 1
    } else {
        1
    };
    let group_end = if target_is_blocked {
        total
    } else {
        first_blocked
    };
    let target = requested.clamp(group_start, group_end);

    // Translate the displayed target ordinal into the dense stored rank the
    // move statement rewrites, exactly like Python's anchored calculation.
    let anchor = &entries[target - 1];
    let raw_target = 1 + entries
        .iter()
        .filter(|entry| {
            (entry.queue_position, entry.thread_id) < (anchor.queue_position, anchor.thread_id)
        })
        .count();

    let raw_target = i32::try_from(raw_target).unwrap_or(i32::MAX);
    let rows = transaction
        .query(
            "WITH ranked AS ( \
                 SELECT id, queue_position AS old_position, \
                        row_number() OVER (ORDER BY queue_position, id) AS seq \
                 FROM threads \
                 WHERE user_id = $1::int AND status = 'active' AND queue_position >= 1 \
             ), \
             target AS (SELECT seq FROM ranked WHERE id = $2::int), \
             moved AS ( \
                 SELECT ranked.id, ranked.old_position, \
                        CASE \
                            WHEN ranked.id = $2::int THEN $3::int \
                            WHEN target.seq < $3::int THEN \
                                CASE WHEN ranked.seq > target.seq AND ranked.seq <= $3::int \
                                     THEN ranked.seq - 1 ELSE ranked.seq END \
                            ELSE \
                                CASE WHEN ranked.seq >= $3::int AND ranked.seq < target.seq \
                                     THEN ranked.seq + 1 ELSE ranked.seq END \
                        END AS new_position \
                 FROM ranked CROSS JOIN target \
             ) \
             UPDATE threads AS t \
             SET queue_position = moved.new_position, \
                 queue_position_is_manual = (t.queue_position_is_manual OR t.id = $2::int), \
                 queue_order_key = CASE \
                     WHEN moved.new_position <> moved.old_position \
                     THEN COALESCE(t.queue_order_key, 0) + 1 \
                     ELSE t.queue_order_key \
                 END \
             FROM moved \
             WHERE t.id = moved.id \
             RETURNING t.id, t.queue_position, moved.old_position, COALESCE(t.queue_order_key, 0)",
            &[&user_id, &thread_id, &raw_target],
        )
        .await
        .map_err(db::query_error)?;

    let changed = rows
        .iter()
        .any(|row| row.get::<_, i32>(1) != row.get::<_, i32>(2));
    let ordering_version: i64 = rows
        .iter()
        .find(|row| row.get::<_, i32>(0) == thread_id)
        .map(|row| row.get(3))
        .unwrap_or(0);
    if changed {
        transaction
            .execute(
                "INSERT INTO events (type, timestamp, user_id, thread_id) \
                 VALUES ('reorder', now(), $1::int, $2::int)",
                &[&user_id, &thread_id],
            )
            .await
            .map_err(db::query_error)?;
    }
    transaction.commit().await.map_err(db::query_error)?;
    drop(pending.0.take());

    Ok(Json(QueueEntryResponse {
        thread_id,
        position: i32::try_from(target).unwrap_or(i32::MAX),
        ordering_version,
    }))
}

fn validate_idempotency_key(key: &str) -> Result<(), ApiError> {
    if key.is_empty() || key.len() > 100 {
        return Err(bad_request(
            "idempotency_key must contain between 1 and 100 characters".to_string(),
        ));
    }
    Ok(())
}

/// Create one durable queue-order revision by shuffling the reader's queue.
pub async fn create_queue_order(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<QueueOrderRequest>,
) -> Result<(StatusCode, Json<QueueOrderResponse>), ApiError> {
    if let Some(key) = request.idempotency_key.as_deref() {
        validate_idempotency_key(key)?;
    }
    let user_id = user.id();
    let mut pending = Pending(Some(db::checkout(&state).await?));
    let transaction = pending
        .0
        .as_mut()
        .expect("checked-out PostgreSQL client")
        .transaction()
        .await
        .map_err(db::query_error)?;
    transaction
        .execute(
            "SELECT pg_advisory_xact_lock($1, $2)",
            &[&QUEUE_LOCK_NAMESPACE, &user_id],
        )
        .await
        .map_err(db::query_error)?;

    if let Some(key) = request.idempotency_key.as_deref() {
        let replayed = transaction
            .query_opt(
                "SELECT id, COALESCE((context->>'shuffled')::int, 0) FROM events \
                 WHERE user_id = $1 AND type = 'shuffle' AND context->>'idempotency_key' = $2 \
                 ORDER BY id DESC LIMIT 1",
                &[&user_id, &key],
            )
            .await
            .map_err(db::query_error)?;
        if let Some(row) = replayed {
            transaction.commit().await.map_err(db::query_error)?;
            drop(pending.0.take());
            return Ok((
                StatusCode::OK,
                Json(QueueOrderResponse {
                    event_id: row.get(0),
                    replayed: true,
                    shuffled: row.get(1),
                }),
            ));
        }
    }

    let rows = transaction
        .query(
            "SELECT id FROM threads \
             WHERE user_id = $1 AND status = 'active' AND queue_position >= 1 \
             ORDER BY queue_position, id",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut ids: Vec<i32> = rows.iter().map(|row| row.get(0)).collect();
    {
        // ThreadRng is not Send, so keep it inside a block that ends before the
        // next await; axum Handlers require a Send future.
        let mut rng = rand::rng();
        for index in (1..ids.len()).rev() {
            let swap = rng.random_range(0..=index);
            ids.swap(index, swap);
        }
    }
    let positions: Vec<i32> = (1..=ids.len() as i32).collect();
    if !ids.is_empty() {
        transaction
            .execute(
                "UPDATE threads AS t \
                 SET queue_position = shuffled.new_position, \
                     queue_position_is_manual = FALSE, \
                     queue_order_key = COALESCE(t.queue_order_key, 0) + 1 \
                 FROM unnest($2::int4[], $3::int4[]) AS shuffled(thread_id, new_position) \
                 WHERE t.id = shuffled.thread_id \
                   AND t.user_id = $1 \
                   AND t.status = 'active' \
                   AND t.queue_position >= 1",
                &[&user_id, &ids, &positions],
            )
            .await
            .map_err(db::query_error)?;
    }
    let shuffled = i32::try_from(ids.len()).unwrap_or(i32::MAX);
    let context = serde_json::json!({
        "shuffled": shuffled,
        "idempotency_key": request.idempotency_key,
    })
    .to_string();
    let event_id: i32 = transaction
        .query_one(
            "INSERT INTO events (type, timestamp, user_id, context) \
             VALUES ('shuffle', now(), $1, $2::text::json) RETURNING id",
            &[&user_id, &context],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    transaction.commit().await.map_err(db::query_error)?;
    drop(pending.0.take());

    Ok((
        StatusCode::CREATED,
        Json(QueueOrderResponse {
            event_id,
            replayed: false,
            shuffled,
        }),
    ))
}

/// OpenAPI document for the v2 queue resources.
///
/// Generated from the Rust request/response types so the published contract
/// cannot drift from the mounted handlers.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(
        get_queue_entry_documentation,
        update_queue_entry_documentation,
        create_queue_order_documentation
    ),
    components(schemas(
        QueueEntryResponse,
        QueueEntryPatch,
        QueueOrderRequest,
        QueueOrderResponse
    )),
    modifiers(&QueueSecurityAddon)
)]
pub struct QueueApi;

struct QueueSecurityAddon;
impl utoipa::Modify for QueueSecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme(
                "HTTPBearer",
                utoipa::openapi::security::SecurityScheme::Http(
                    utoipa::openapi::security::Http::new(
                        utoipa::openapi::security::HttpAuthScheme::Bearer,
                    ),
                ),
            );
        }
    }
}

/// Documentation-only operation used to emit the generated OpenAPI contract.
#[utoipa::path(
    get,
    path = "/api/v2/queue-entries/{thread_id}",
    tag = "queue-entries",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    responses(
        (status = 200, description = "Queue entry", body = QueueEntryResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Queue entry not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn get_queue_entry_documentation() {}

/// Documentation-only operation used to emit the generated OpenAPI contract.
#[utoipa::path(
    patch,
    path = "/api/v2/queue-entries/{thread_id}",
    tag = "queue-entries",
    params(("thread_id" = i32, Path, description = "Owned Thread identifier")),
    request_body = QueueEntryPatch,
    responses(
        (status = 200, description = "Updated queue entry", body = QueueEntryResponse),
        (status = 400, description = "Invalid target position"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Queue entry not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn update_queue_entry_documentation() {}

/// Documentation-only operation used to emit the generated OpenAPI contract.
#[utoipa::path(
    post,
    path = "/api/v2/queue-orders",
    tag = "queue-orders",
    request_body = QueueOrderRequest,
    responses(
        (status = 201, description = "Queue-order revision created", body = QueueOrderResponse),
        (status = 200, description = "Idempotent replay of the recorded revision", body = QueueOrderResponse),
        (status = 400, description = "Invalid idempotency key"),
        (status = 401, description = "Not authenticated")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn create_queue_order_documentation() {}

/// Test-database schema for the queue module's disposable-Postgres coverage.
///
/// A dedicated PostgreSQL schema keyed off `RUST_ROLL_TEST_DATABASE_URL`
/// keeps these focused tables out of the canonical schema the Python parity
/// suite creates in the same database.
#[cfg(test)]
fn test_database_url() -> String {
    let base =
        std::env::var("RUST_ROLL_TEST_DATABASE_URL").expect("disposable PostgreSQL required");
    let separator = if base.contains('?') { '&' } else { '?' };
    format!("{base}{separator}options=-csearch_path%3Dqueue_unit_test%2Cpublic")
}

#[cfg(test)]
mod tests {
    //! Disposable-PostgreSQL coverage for every mounted queue write handler.
    use super::*;
    use crate::config::Config;
    use utoipa::OpenApi;

    static DB_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

    async fn state() -> Arc<AppState> {
        let url = test_database_url();
        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-queue-test".into()),
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .expect("queue test config");
        Arc::new(AppState::new(config).expect("queue test state"))
    }

    async fn reset(state: &AppState) {
        let connection = db::checkout(state).await.expect("test connection");
        connection
            .batch_execute(
                "CREATE SCHEMA IF NOT EXISTS queue_unit_test; \
                 CREATE TABLE IF NOT EXISTS queue_unit_test.threads ( \
                     id integer PRIMARY KEY, \
                     user_id integer NOT NULL, \
                     title text NOT NULL DEFAULT '', \
                     status text NOT NULL DEFAULT 'active', \
                     queue_position integer NOT NULL, \
                     queue_position_is_manual boolean NOT NULL DEFAULT false, \
                     queue_order_key bigint, \
                     is_blocked boolean NOT NULL DEFAULT false \
                 ); \
                 CREATE TABLE IF NOT EXISTS queue_unit_test.events ( \
                     id serial PRIMARY KEY, \
                     type text NOT NULL, \
                     timestamp timestamptz NOT NULL DEFAULT now(), \
                     user_id integer, \
                     thread_id integer, \
                     context json \
                 ); \
                 TRUNCATE queue_unit_test.threads, queue_unit_test.events RESTART IDENTITY;",
            )
            .await
            .expect("queue test schema");
        drop(Object::take(connection));
    }

    async fn seed(db: &AppState, user_id: i32, ids: &[(i32, i32, bool)]) {
        let connection = db::checkout(db).await.expect("seed connection");
        for (id, position, blocked) in ids {
            connection
                .execute(
                    "INSERT INTO threads (id, user_id, status, queue_position, is_blocked) \
                     VALUES ($1, $2, 'active', $3, $4)",
                    &[id, &user_id, position, blocked],
                )
                .await
                .expect("seed thread");
        }
        drop(Object::take(connection));
    }

    async fn positions(db: &AppState, user_id: i32) -> Vec<(i32, i32)> {
        let connection = db::checkout(db).await.expect("read connection");
        let rows = connection
            .query(
                "SELECT id, queue_position FROM threads WHERE user_id = $1 \
                 AND status = 'active' AND queue_position >= 1 ORDER BY queue_position, id",
                &[&user_id],
            )
            .await
            .expect("read positions");
        drop(Object::take(connection));
        rows.iter().map(|row| (row.get(0), row.get(1))).collect()
    }

    async fn event_count(db: &AppState, event_type: &str) -> i64 {
        let connection = db::checkout(db).await.expect("event connection");
        let row = connection
            .query_one(
                "SELECT count(*) FROM events WHERE type = $1",
                &[&event_type],
            )
            .await
            .expect("event count");
        drop(Object::take(connection));
        row.get(0)
    }

    #[test]
    fn queue_openapi_documents_every_mounted_resource_operation() {
        let document = serde_json::to_value(QueueApi::openapi()).expect("queue OpenAPI document");
        let entry_path = &document["paths"]["/api/v2/queue-entries/{thread_id}"];
        assert!(entry_path["get"].is_object());
        assert!(entry_path["patch"].is_object());
        assert!(document["paths"]["/api/v2/queue-orders"]["post"].is_object());
        for schema in [
            "QueueEntryResponse",
            "QueueEntryPatch",
            "QueueOrderRequest",
            "QueueOrderResponse",
        ] {
            assert!(
                document["components"]["schemas"][schema].is_object(),
                "missing generated schema {schema}"
            );
        }
    }

    #[tokio::test]
    async fn update_queue_entry_moves_front_middle_and_back_with_reorder_events() {
        let _guard = DB_LOCK.lock().await;
        let state = state().await;
        reset(&state).await;
        let user = AuthenticatedUser::for_test(7);
        seed(&state, 7, &[(1, 1, false), (2, 2, false), (3, 3, false)]).await;

        let front = update_queue_entry(
            State(state.clone()),
            user,
            Path(3),
            Json(QueueEntryPatch { position: 1 }),
        )
        .await
        .expect("move to front");
        assert_eq!(front.0.position, 1);
        assert_eq!(positions(&state, 7).await, vec![(3, 1), (1, 2), (2, 3)]);
        assert_eq!(event_count(&state, "reorder").await, 1);

        let middle = update_queue_entry(
            State(state.clone()),
            user,
            Path(2),
            Json(QueueEntryPatch { position: 2 }),
        )
        .await
        .expect("move to middle");
        assert_eq!(middle.0.position, 2);
        assert_eq!(positions(&state, 7).await, vec![(3, 1), (2, 2), (1, 3)]);

        let back = update_queue_entry(
            State(state.clone()),
            user,
            Path(3),
            Json(QueueEntryPatch { position: i32::MAX }),
        )
        .await
        .expect("move to back");
        assert_eq!(back.0.position, 3);
        assert_eq!(positions(&state, 7).await, vec![(2, 1), (1, 2), (3, 3)]);
        assert!(back.0.ordering_version > 0);
    }

    #[tokio::test]
    async fn queue_entries_are_owner_scoped_and_reject_invalid_positions() {
        let _guard = DB_LOCK.lock().await;
        let state = state().await;
        reset(&state).await;
        seed(&state, 7, &[(1, 1, false)]).await;
        seed(&state, 9, &[(2, 1, false)]).await;

        let foreign = get_queue_entry(
            State(state.clone()),
            AuthenticatedUser::for_test(9),
            Path(1),
        )
        .await;
        assert_eq!(foreign.expect_err("foreign entry").0, StatusCode::NOT_FOUND);
        let foreign_move = update_queue_entry(
            State(state.clone()),
            AuthenticatedUser::for_test(9),
            Path(1),
            Json(QueueEntryPatch { position: 1 }),
        )
        .await;
        assert_eq!(
            foreign_move.expect_err("foreign move").0,
            StatusCode::NOT_FOUND
        );
        let invalid = update_queue_entry(
            State(state.clone()),
            AuthenticatedUser::for_test(7),
            Path(1),
            Json(QueueEntryPatch { position: 0 }),
        )
        .await;
        assert_eq!(
            invalid.expect_err("invalid position").0,
            StatusCode::BAD_REQUEST
        );

        let own = get_queue_entry(
            State(state.clone()),
            AuthenticatedUser::for_test(7),
            Path(1),
        )
        .await
        .expect("owned entry");
        assert_eq!(own.0.position, 1);
        assert_eq!(positions(&state, 9).await, vec![(2, 1)]);
    }

    #[tokio::test]
    async fn concurrent_moves_serialize_into_one_dense_queue() {
        let _guard = DB_LOCK.lock().await;
        let state = state().await;
        reset(&state).await;
        let user = AuthenticatedUser::for_test(7);
        seed(&state, 7, &[(1, 1, false), (2, 2, false), (3, 3, false)]).await;

        let first = update_queue_entry(
            State(state.clone()),
            user,
            Path(1),
            Json(QueueEntryPatch { position: 3 }),
        );
        let second = update_queue_entry(
            State(state.clone()),
            user,
            Path(3),
            Json(QueueEntryPatch { position: 1 }),
        );
        let (first, second) = tokio::join!(first, second);
        assert!(first.is_ok(), "first concurrent move failed");
        assert!(second.is_ok(), "second concurrent move failed");

        // The advisory lock serializes both writers; neither can observe or
        // write a half-applied order, so ranks stay a dense 1..n permutation
        // and the roll pool still draws each entry exactly once.
        let final_positions = positions(&state, 7).await;
        assert_eq!(
            final_positions
                .iter()
                .map(|(_, position)| *position)
                .collect::<Vec<_>>(),
            vec![1, 2, 3]
        );
        assert_eq!(event_count(&state, "reorder").await, 2);
    }

    #[tokio::test]
    async fn create_queue_order_replays_idempotent_shuffle_and_preserves_owner_isolation() {
        let _guard = DB_LOCK.lock().await;
        let state = state().await;
        reset(&state).await;
        let user = AuthenticatedUser::for_test(7);
        seed(
            &state,
            7,
            &[(1, 1, false), (2, 2, false), (3, 3, false), (4, 4, false)],
        )
        .await;
        seed(&state, 9, &[(5, 1, false)]).await;

        let first = create_queue_order(
            State(state.clone()),
            user,
            Json(QueueOrderRequest {
                idempotency_key: Some("shuffle-once".into()),
            }),
        )
        .await
        .expect("first shuffle");
        assert_eq!(first.0, StatusCode::CREATED);
        assert_eq!(first.1.shuffled, 4);
        assert!(!first.1.replayed);
        let after_first = positions(&state, 7).await;
        assert_eq!(
            after_first
                .iter()
                .map(|(id, _)| *id)
                .collect::<std::collections::BTreeSet<_>>(),
            [1, 2, 3, 4].into_iter().collect()
        );
        assert_eq!(
            after_first.iter().map(|(_, pos)| *pos).collect::<Vec<_>>(),
            vec![1, 2, 3, 4]
        );

        let replay = create_queue_order(
            State(state.clone()),
            user,
            Json(QueueOrderRequest {
                idempotency_key: Some("shuffle-once".into()),
            }),
        )
        .await
        .expect("replayed shuffle");
        assert_eq!(replay.0, StatusCode::OK);
        assert!(replay.1.replayed);
        assert_eq!(replay.1.event_id, first.1.event_id);
        assert_eq!(positions(&state, 7).await, after_first);
        assert_eq!(event_count(&state, "shuffle").await, 1);
        assert_eq!(positions(&state, 9).await, vec![(5, 1)]);

        let invalid = create_queue_order(
            State(state.clone()),
            user,
            Json(QueueOrderRequest {
                idempotency_key: Some(String::new()),
            }),
        )
        .await;
        assert_eq!(invalid.expect_err("empty key").0, StatusCode::BAD_REQUEST);
    }
}
