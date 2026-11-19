//! Same-path Rust cutover of
//! `GET /api/v1/issue-identity/cbl/{list_id}/adoption-preview`.
//!
//! Python serves this route with `preview_cbl_adoption(db, user_id, list_id)`
//! and no decision overrides, which is exactly the `adoption-plan` computation
//! with empty `series_decisions` / `entry_decisions`. The native route therefore
//! delegates to the same reconcile + plan code as `POST .../adoption-plan`
//! (canonical resolution, collection-exclusion guard, read status, duplicate
//! identity) instead of carrying a second, weaker copy. Read-only: it never
//! mutates list membership, read state, or overlap answers.

use crate::{
    auth::AuthenticatedUser,
    issue_identity::{adoption_preview_for, CblAdoptionPreviewResponse, IdentityError},
    preview_validation::parse_path_int,
    ApiError, AppState,
};
use axum::{
    extract::{rejection::PathRejection, Path, State},
    Json,
};
use std::{collections::HashMap, sync::Arc};

#[utoipa::path(
    get,
    path = "/api/v1/issue-identity/cbl/{list_id}/adoption-preview",
    operation_id = "api_cbl_adoption_preview_api_v1_issue_identity_cbl__list_id__adoption_preview_get",
    params(("list_id" = i64, Path, description = "CBL source list id")),
    responses(
        (status = 200, description = "Read-only adoption preview", body = CblAdoptionPreviewResponse),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "CBL source list not found or not active"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
pub fn documentation() {}

/// Mounted handler for `GET /api/v1/issue-identity/cbl/{list_id}/adoption-preview`.
pub async fn api_cbl_adoption_preview_handler(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    list_id: Result<Path<String>, PathRejection>,
) -> Result<Json<CblAdoptionPreviewResponse>, IdentityError> {
    let list_id = parse_path_int(list_id)?;
    // `cbl_source_lists.id` is an int4 column: an id outside that domain cannot
    // match a row, so it is the same 404 as a missing/inactive list.
    let list_id = i32::try_from(list_id).map_err(|_| {
        ApiError::NotFound(format!("CBL source list {list_id} not found or not active"))
    })?;
    let empty = HashMap::new();
    adoption_preview_for(&state, user.id(), list_id, &empty, &empty)
        .await
        .map(Json)
}
