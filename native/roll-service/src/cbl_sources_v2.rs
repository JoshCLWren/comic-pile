//! Canonical `/api/v2/cblSources` preview surface (#5714).
//!
//! These three operations replace the legacy v1 CBL preview calls with an
//! AIP-122 resource and two justified AIP-136 custom methods. They are thin
//! transports over the exact same calculations the retained v1 routes use:
//!
//! - `GET  /api/v2/cblSources/{source_id}/adoptionPreview` — read-only
//!   singleton projection with no reader overrides.
//! - `POST /api/v2/cblSources/{source_id}:planAdoption` — repeatable
//!   stateless calculation that applies reader decisions to that projection.
//! - `POST /api/v2/cblSources/{source_id}:previewReadingGraph` — repeatable
//!   stateless prospective Option E graph for the same source selection.
//!
//! None of them writes list membership, reading history, the reading graph or
//! exclusions. The durable write stays on the v2 Reading List adoption-commit
//! resource. The fingerprint returned with each preview is the source revision
//! the commit path validates for stale-preview conflicts; cross-user reads are
//! scoped through the same owner-aware reconcile helpers as v1.

use crate::{
    auth::AuthenticatedUser,
    issue_identity::{
        adoption_preview_for, CblAdoptionPlanRequest, CblAdoptionPreviewResponse, IdentityError,
    },
    issue_identity_cbl_reading_graph_preview::{
        preview_reading_graph_for, PreviewError, ReadingGraphPreview, ReadingGraphPreviewRequest,
    },
    preview_validation::parse_path_int,
    ApiError, AppState,
};
use axum::{
    body::Bytes,
    extract::{rejection::PathRejection, Path, State},
    Json,
};
use std::{collections::HashMap, sync::Arc};

/// Parse the source id for the adoption operations. `cbl_source_lists.id` is an
/// `int4` column, so an id outside that domain is the same 404 as a missing or
/// inactive source, matching the retained v1 preview.
fn parse_source_id(raw: Result<Path<String>, PathRejection>) -> Result<i32, ApiError> {
    let source_id = parse_path_int(raw)?;
    i32::try_from(source_id).map_err(|_| {
        ApiError::NotFound(format!("CBL source list {source_id} not found or not active"))
    })
}

#[utoipa::path(
    get,
    path = "/api/v2/cblSources/{source_id}/adoptionPreview",
    operation_id = "get_cbl_adoption_preview_v2",
    params(("source_id" = i64, Path, description = "CBL source list id")),
    responses(
        (status = 200, description = "Read-only adoption projection", body = CblAdoptionPreviewResponse),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "CBL source list not found or not active"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
pub fn adoption_preview_v2_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/cblSources/{source_id}:planAdoption",
    operation_id = "plan_cbl_adoption_v2",
    request_body = CblAdoptionPlanRequest,
    params(("source_id" = i64, Path, description = "CBL source list id")),
    responses(
        (status = 200, description = "Stateless adoption calculation", body = CblAdoptionPreviewResponse),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "CBL source list not found or not active"),
        (status = 422, description = "Validation failed"),
    ),
    security(("HTTPBearer" = []))
)]
pub fn plan_adoption_v2_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/cblSources/{source_id}:previewReadingGraph",
    operation_id = "preview_cbl_reading_graph_v2",
    request_body = ReadingGraphPreviewRequest,
    params(("source_id" = i64, Path, description = "CBL source list id")),
    responses(
        (status = 200, description = "Read-only prospective graph", body = ReadingGraphPreview),
        (status = 401, description = "Unauthorized"),
        (status = 404, description = "CBL source list or target reading list not found"),
        (status = 422, description = "Validation failed, or unknown/unresolved source position or overlap answer"),
    ),
    security(("HTTPBearer" = []))
)]
pub fn preview_reading_graph_v2_documentation() {}

/// `GET /api/v2/cblSources/{source_id}/adoptionPreview`.
pub async fn adoption_preview_v2_handler(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    source_id: Result<Path<String>, PathRejection>,
) -> Result<Json<CblAdoptionPreviewResponse>, IdentityError> {
    let source_id = parse_source_id(source_id)?;
    let empty = HashMap::new();
    adoption_preview_for(&state, user.id(), source_id, &empty, &empty)
        .await
        .map(Json)
}

/// `POST /api/v2/cblSources/{source_id}:planAdoption`.
pub async fn plan_adoption_v2_handler(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    source_id: Result<Path<String>, PathRejection>,
    Json(request): Json<CblAdoptionPlanRequest>,
) -> Result<Json<CblAdoptionPreviewResponse>, IdentityError> {
    let source_id = parse_source_id(source_id)?;
    adoption_preview_for(
        &state,
        user.id(),
        source_id,
        &request.series_decisions,
        &request.entry_decisions,
    )
    .await
    .map(Json)
}

/// `POST /api/v2/cblSources/{source_id}:previewReadingGraph`.
pub async fn preview_reading_graph_v2_handler(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    source_id: Result<Path<String>, PathRejection>,
    body: Bytes,
) -> Result<Json<ReadingGraphPreview>, PreviewError> {
    // Keep the i64 parse so `load` emits the same structured 404 for an
    // out-of-int4-range id as the retained v1 reading-graph-preview route.
    let source_id = parse_path_int(source_id)?;
    preview_reading_graph_for(&state, user, source_id, &body)
        .await
        .map(Json)
}
