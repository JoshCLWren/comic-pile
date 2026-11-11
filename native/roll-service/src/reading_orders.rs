//! Same-path Rust cutover for the browser-called reading-orders operations
//! (#4851, parent #4335).
//!
//! Preserves the Python `app/api/reading_orders.py` wire contract at the same
//! HTTP methods and exact paths:
//!
//! * `GET /api/v1/reading-orders/`
//! * `POST /api/v1/reading-orders/{reading_order_id}/items`
//!
//! Only the implementation moves from Python FastAPI to the native Roll
//! binary. No frontend URL changes; Python handlers remain mounted until
//! authenticated production proof permits their removal.
//!
//! Parity notes (Python oracle is `app/api/reading_orders.py` +
//! `app/services/reading_order_service.py` +
//! `app/services/reading_order_placement.py`):
//!
//! * The list is a single set-based aggregate (`LEFT JOIN` + `GROUP BY`),
//!   ordered by name, scoped to the authenticated owner. Python issued the
//!   same shape through `selectinload` (one order query plus one item
//!   count query per order through the identity map); this removes that
//!   per-order fan-out while returning the same rows and the same
//!   `total_items` values.
//! * `insert_reading_order_item` keeps the Python statement order and
//!   transaction semantics: owned-order lookup (404 `Reading order {id} not
//!   found`), owned-thread lookup (404 `Thread {id} not found`), the items of
//!   the order, in-memory position shifting through the shared `apply_insert`
//!   rules, an insert only when the thread is absent, then a SQL `count(*)`.
//! * `apply_insert` is a line-for-line port of
//!   `app/services/reading_order_placement.py::apply_insert`, including the
//!   move-vs-insert branch and the `position >= target_pos` shift for new
//!   items.
//! * Positions are written back with one set-based `UPDATE ... CASE`, only
//!   for rows whose position actually changed, mirroring SQLAlchemy's dirty
//!   tracking of the mutated items.
//! * `uq_issue_thread_position`-style constraints do not exist on
//!   `reading_order_items`, so no constraint deferral is required.
//! * Business 404s and the 201 insert status match Python. Body validation
//!   uses the house Rust convention (`{"detail": "..."}` 422), matching every
//!   other native v1 cutover; FastAPI's list-shaped validation body is not
//!   reproduced anywhere in the native surface.

#![forbid(unsafe_code)]

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

const LIST_SQL: &str = "SELECT o.id, o.name, o.description, COUNT(i.id)::bigint \
     FROM reading_orders o \
     LEFT JOIN reading_order_items i ON i.reading_order_id = o.id \
     WHERE o.user_id = $1 \
     GROUP BY o.id, o.name, o.description \
     ORDER BY o.name";

const OWNED_ORDER_SQL: &str =
    "SELECT id FROM reading_orders WHERE id = $1 AND user_id = $2";
const OWNED_THREAD_SQL: &str = "SELECT id FROM threads WHERE id = $1 AND user_id = $2";
const ORDER_ITEMS_SQL: &str =
    "SELECT id, thread_id, position FROM reading_order_items WHERE reading_order_id = $1 ORDER BY position";
const COUNT_SQL: &str =
    "SELECT COUNT(*)::bigint FROM reading_order_items WHERE reading_order_id = $1";
const INSERT_ITEM_SQL: &str =
    "INSERT INTO reading_order_items (reading_order_id, thread_id, position) VALUES ($1, $2, $3)";

/// One row of the reading-orders list (Python `ReadingOrderSummary`).
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderSummary {
    pub id: i32,
    pub name: String,
    pub description: Option<String>,
    pub total_items: i64,
}

/// Python `ReadingOrderListResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ReadingOrderListResponse {
    pub reading_orders: Vec<ReadingOrderSummary>,
}

/// Python `InsertReadingOrderItemRequest`.
#[derive(Debug, Clone, Deserialize, utoipa::ToSchema)]
pub struct InsertReadingOrderItemRequest {
    pub thread_id: i32,
    pub position: i32,
}

/// Python `InsertReadingOrderItemResponse`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct InsertReadingOrderItemResponse {
    pub reading_order_id: i32,
    pub thread_id: i32,
    pub position: i32,
    pub total_items: i64,
}

fn unprocessable(detail: impl Into<String>) -> ApiError {
    ApiError::Unprocessable(detail.into())
}

/// Serve `GET /api/v1/reading-orders/`.
pub async fn list_reading_orders(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<ReadingOrderListResponse>, ApiError> {
    let connection = db::checkout(&state).await?;
    let rows = connection
        .query(LIST_SQL, &[&user.id()])
        .await
        .map_err(db::query_error)?;
    let reading_orders = rows
        .iter()
        .map(|row| ReadingOrderSummary {
            id: row.get(0),
            name: row.get(1),
            description: row.get(2),
            total_items: row.get(3),
        })
        .collect();
    Ok(Json(ReadingOrderListResponse { reading_orders }))
}

struct ItemRow {
    id: i32,
    thread_id: i32,
    position: i32,
}

/// Port of `app/services/reading_order_placement.py::apply_insert`.
///
/// Mutates `items` in place: an existing thread keeps its membership at the
/// target position (shifting neighbours); an absent thread pushes everything
/// at or after the target position one slot later.
fn apply_insert(items: &mut [ItemRow], thread_id: i32, target_pos: i32) {
    if let Some(current_index) = items.iter().position(|item| item.thread_id == thread_id) {
        let old_pos = items[current_index].position;
        if old_pos < target_pos {
            for item in items.iter_mut() {
                if old_pos < item.position && item.position <= target_pos {
                    item.position -= 1;
                }
            }
        } else if target_pos < old_pos {
            for item in items.iter_mut() {
                if target_pos <= item.position && item.position < old_pos {
                    item.position += 1;
                }
            }
        }
        items[current_index].position = target_pos;
        return;
    }
    for item in items.iter_mut() {
        if item.position >= target_pos {
            item.position += 1;
        }
    }
}

/// Serve `POST /api/v1/reading-orders/{reading_order_id}/items`.
pub async fn insert_reading_order_item(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(reading_order_id): Path<i32>,
    Json(payload): Json<InsertReadingOrderItemRequest>,
) -> Result<(StatusCode, Json<InsertReadingOrderItemResponse>), ApiError> {
    if payload.thread_id <= 0 {
        return Err(unprocessable("thread_id must be greater than 0"));
    }
    if payload.position < 1 {
        return Err(unprocessable("position must be greater than or equal to 1"));
    }
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    let result = insert_item_inner(&tx, user.id(), reading_order_id, &payload).await;
    match result {
        Ok(response) => {
            tx.commit().await.map_err(db::query_error)?;
            Ok((StatusCode::CREATED, Json(response)))
        }
        Err(error) => {
            let _ = tx.rollback().await;
            Err(error)
        }
    }
}

async fn insert_item_inner(
    tx: &tokio_postgres::Transaction<'_>,
    user_id: i32,
    reading_order_id: i32,
    payload: &InsertReadingOrderItemRequest,
) -> Result<InsertReadingOrderItemResponse, ApiError> {
    let order = tx
        .query_opt(OWNED_ORDER_SQL, &[&reading_order_id, &user_id])
        .await
        .map_err(db::query_error)?;
    if order.is_none() {
        return Err(ApiError::NotFound(format!(
            "Reading order {reading_order_id} not found"
        )));
    }
    let thread = tx
        .query_opt(OWNED_THREAD_SQL, &[&payload.thread_id, &user_id])
        .await
        .map_err(db::query_error)?;
    if thread.is_none() {
        return Err(ApiError::NotFound(format!("Thread {} not found", payload.thread_id)));
    }

    let rows = tx
        .query(ORDER_ITEMS_SQL, &[&reading_order_id])
        .await
        .map_err(db::query_error)?;
    let mut items: Vec<ItemRow> = rows
        .iter()
        .map(|row| ItemRow {
            id: row.get(0),
            thread_id: row.get(1),
            position: row.get(2),
        })
        .collect();
    let original_positions: Vec<i32> = items.iter().map(|item| item.position).collect();

    apply_insert(&mut items, payload.thread_id, payload.position);

    let already_present = items
        .iter()
        .any(|item| item.thread_id == payload.thread_id);
    for (item, original_position) in items.iter().zip(original_positions.iter()) {
        if item.position != *original_position {
            tx.execute(
                "UPDATE reading_order_items SET position = $1 WHERE id = $2",
                &[&item.position, &item.id],
            )
            .await
            .map_err(db::query_error)?;
        }
    }
    if !already_present {
        tx.execute(
            INSERT_ITEM_SQL,
            &[&reading_order_id, &payload.thread_id, &payload.position],
        )
        .await
        .map_err(db::query_error)?;
    }

    let row = tx
        .query_one(COUNT_SQL, &[&reading_order_id])
        .await
        .map_err(db::query_error)?;
    let total_items: i64 = row.get(0);
    Ok(InsertReadingOrderItemResponse {
        reading_order_id,
        thread_id: payload.thread_id,
        position: payload.position,
        total_items,
    })
}

/// Documentation-only operation for the list handler.
#[utoipa::path(
    get,
    path = "/api/v1/reading-orders/",
    tag = "reading-orders",
    operation_id = "reading_orders_list",
    responses(
        (status = 200, description = "Reading orders owned by the caller, ordered by name", body = ReadingOrderListResponse),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_reading_orders_documentation() {}

/// Documentation-only operation for the insert handler.
#[utoipa::path(
    post,
    path = "/api/v1/reading-orders/{reading_order_id}/items",
    tag = "reading-orders",
    operation_id = "reading_orders_insert_item",
    request_body = InsertReadingOrderItemRequest,
    params(("reading_order_id" = i32, Path)),
    responses(
        (status = 201, description = "Thread seated at the requested position", body = InsertReadingOrderItemResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Reading order or thread not found"),
        (status = 422, description = "Request payload failed validation"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn insert_reading_order_item_documentation() {}

/// OpenAPI document for the native same-path reading-orders surface.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(
        list_reading_orders_documentation,
        insert_reading_order_item_documentation
    ),
    components(schemas(
        ReadingOrderSummary,
        ReadingOrderListResponse,
        InsertReadingOrderItemRequest,
        InsertReadingOrderItemResponse
    )),
    modifiers(&ReadingOrdersSecurityAddon)
)]
pub struct ReadingOrdersApi;

struct ReadingOrdersSecurityAddon;
impl utoipa::Modify for ReadingOrdersSecurityAddon {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn apply_insert_shifts_at_and_after_target_for_new_thread() {
        let mut items = vec![
            ItemRow { id: 1, thread_id: 11, position: 1 },
            ItemRow { id: 2, thread_id: 22, position: 2 },
            ItemRow { id: 3, thread_id: 33, position: 3 },
        ];
        apply_insert(&mut items, 44, 2);
        let positions: Vec<(i32, i32)> =
            items.iter().map(|item| (item.thread_id, item.position)).collect();
        assert_eq!(positions, vec![(11, 1), (22, 3), (33, 4)]);
    }

    #[test]
    fn apply_insert_moves_existing_thread_forward() {
        let mut items = vec![
            ItemRow { id: 1, thread_id: 11, position: 1 },
            ItemRow { id: 2, thread_id: 22, position: 2 },
            ItemRow { id: 3, thread_id: 33, position: 3 },
            ItemRow { id: 4, thread_id: 44, position: 4 },
        ];
        apply_insert(&mut items, 11, 3);
        let positions: Vec<(i32, i32)> =
            items.iter().map(|item| (item.thread_id, item.position)).collect();
        assert_eq!(positions, vec![(11, 3), (22, 1), (33, 2), (44, 4)]);
    }

    #[test]
    fn apply_insert_moves_existing_thread_backward() {
        let mut items = vec![
            ItemRow { id: 1, thread_id: 11, position: 1 },
            ItemRow { id: 2, thread_id: 22, position: 2 },
            ItemRow { id: 3, thread_id: 33, position: 3 },
            ItemRow { id: 4, thread_id: 44, position: 4 },
        ];
        apply_insert(&mut items, 44, 2);
        let positions: Vec<(i32, i32)> =
            items.iter().map(|item| (item.thread_id, item.position)).collect();
        assert_eq!(positions, vec![(11, 1), (22, 3), (33, 4), (44, 2)]);
    }

    #[test]
    fn apply_insert_same_position_is_a_no_op_for_the_moved_thread() {
        let mut items = vec![
            ItemRow { id: 1, thread_id: 11, position: 1 },
            ItemRow { id: 2, thread_id: 22, position: 2 },
        ];
        apply_insert(&mut items, 11, 1);
        let positions: Vec<(i32, i32)> =
            items.iter().map(|item| (item.thread_id, item.position)).collect();
        assert_eq!(positions, vec![(11, 1), (22, 2)]);
    }
}
