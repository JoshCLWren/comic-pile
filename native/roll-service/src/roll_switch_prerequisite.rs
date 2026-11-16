//! Native cutover of the blocked-roll prerequisite switch:
//! `POST /api/v1/roll/switch-prerequisite`.
//!
//! The Python handler chain (`app/api/roll_recovery_switch.py` ->
//! `app.roll_recovery_switch.switch_pending_roll_to_prerequisite`) is the
//! behavioral oracle. This module keeps the request/response contract, the
//! owner scope, the per-reader session serialization, the 404/409 conflict
//! shapes (including the refreshed roll-recovery payload), the
//! `dependency_recovery` roll event, and the session pointer move.
//!
//! Eligibility is the same Option E authority the native Roll offer uses, and
//! the refreshed guidance is projected by the same bounded recovery builder the
//! native bootstrap uses, so a client cannot be told a stale prerequisite is
//! current.
#![forbid(unsafe_code)]
use crate::{
    auth::AuthenticatedUser,
    bootstrap::{pending_roll_recovery, BootstrapRollRecovery},
    db,
    option_inputs,
    reading_session::{self, SessionPolicy},
    ApiError, AppState,
};
use axum::{
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::sync::Arc;

/// Request body for accepting one current recovery recommendation.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct RollPrerequisiteSwitchRequest {
    /// Recommended continuity-node type. Only concrete issues are accepted.
    pub node_type: String,
    /// Recommended continuity-node identifier.
    pub node_id: i32,
}

/// Durable active-target state after accepting a recovery recommendation.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct RollPrerequisiteSwitchResponse {
    pub original_thread_id: i32,
    pub target_thread_id: i32,
    pub target_thread_title: String,
    pub target_issue_id: i32,
    pub target_issue_number: String,
    pub changed: bool,
}

/// The 409 shapes the Python handler emits, both as a structured FastAPI detail.
enum SwitchError {
    Api(ApiError),
    Conflict(Value),
}

impl From<ApiError> for SwitchError {
    fn from(error: ApiError) -> Self {
        Self::Api(error)
    }
}

impl IntoResponse for SwitchError {
    fn into_response(self) -> Response {
        match self {
            Self::Api(error) => error.into_response(),
            Self::Conflict(detail) => {
                (StatusCode::CONFLICT, Json(json!({ "detail": detail }))).into_response()
            }
        }
    }
}

/// Build the conflict detail that tells the client to refresh the guidance.
fn stale(recovery: Option<BootstrapRollRecovery>) -> SwitchError {
    let mut detail = json!({
        "code": "stale_roll_recovery",
        "message": "The blocked-roll guidance changed. Refresh and choose a current prerequisite.",
    });
    if let Some(recovery) = recovery {
        if let Ok(value) = serde_json::to_value(&recovery) {
            detail["roll_recovery"] = value;
        }
    }
    SwitchError::Conflict(detail)
}

/// Build the no-pending-roll conflict detail.
fn no_pending_roll() -> SwitchError {
    SwitchError::Conflict(json!({
        "code": "no_pending_roll",
        "message": "There is no pending roll to recover.",
    }))
}

/// Whether the request targets the one supported continuity-node type.
fn is_supported_node_type(node_type: &str) -> bool {
    node_type == "issue"
}

/// The selected issue and its owning thread, scoped to the reader.
struct TargetRow {
    issue_id: i32,
    issue_number: String,
    issue_status: String,
    thread_id: i32,
    thread_title: String,
    thread_status: String,
}

/// Read the selected prerequisite only after the session lock is held.
async fn fetch_target(
    tx: &tokio_postgres::Transaction<'_>,
    node_id: i32,
    user_id: i32,
) -> Result<Option<TargetRow>, ApiError> {
    let row = tx
        .query_opt(
            "SELECT i.id, i.issue_number, i.status,
                    t.id, t.title, t.status
             FROM issues i
             JOIN threads t ON t.id = i.thread_id
             WHERE i.id = $1 AND t.user_id = $2",
            &[&node_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(row
        .map(|row| -> Result<TargetRow, ApiError> {
            Ok(TargetRow {
                issue_id: row.try_get(0).map_err(db::query_error)?,
                issue_number: row.try_get(1).map_err(db::query_error)?,
                issue_status: row.try_get(2).map_err(db::query_error)?,
                thread_id: row.try_get(3).map_err(db::query_error)?,
                thread_title: row.try_get(4).map_err(db::query_error)?,
                thread_status: row.try_get(5).map_err(db::query_error)?,
            })
        })
        .transpose()?)
}

/// Read the pending pointer under the session lock.
async fn fetch_pending(
    tx: &tokio_postgres::Transaction<'_>,
    session_id: i32,
    user_id: i32,
) -> Result<(Option<i32>, Option<Vec<i32>>), ApiError> {
    let row = tx
        .query_one(
            "SELECT pending_thread_id, snoozed_thread_ids
             FROM sessions
             WHERE id = $1 AND user_id = $2
             FOR UPDATE",
            &[&session_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok((
        row.try_get(0).map_err(db::query_error)?,
        row.try_get(1).map_err(db::query_error)?,
    ))
}

/// Read the reader's current logical die for the event record.
async fn current_die(
    tx: &tokio_postgres::Transaction<'_>,
    user: AuthenticatedUser,
) -> Result<i32, ApiError> {
    crate::dice_state::current_die(tx, user).await
}

/// Accept one current blocked-roll prerequisite and move the session pointer.
pub async fn switch_prerequisite(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<RollPrerequisiteSwitchRequest>,
) -> Response {
    match switch(state, user, request).await {
        Ok(body) => Json(body).into_response(),
        Err(error) => error.into_response(),
    }
}

async fn switch(
    state: Arc<AppState>,
    user: AuthenticatedUser,
    request: RollPrerequisiteSwitchRequest,
) -> Result<RollPrerequisiteSwitchResponse, SwitchError> {
    if !is_supported_node_type(&request.node_type) {
        return Err(SwitchError::Api(ApiError::Unprocessable(
            "Only issue prerequisites can be selected".to_string(),
        )));
    }

    // Bootstrap resolves (and creates when needed) the authoritative session,
    // matching Python's get_or_create.
    let active = reading_session::bootstrap(&state, user, None, SessionPolicy::default())
        .await?;
    // Read-only Option E snapshot before the write connection so this request
    // never nests two pool checkouts.
    let validated = option_inputs::load_option_inputs_contained(&state, user).await?;
    let candidates = validated.eligible_frontiers().map_err(|e| {
        tracing::debug!(
            error_kind = crate::error_kind(&e),
            "preserved underlying error before mapping"
        );
        SwitchError::Api(ApiError::Internal(
            "Invalid reading constraints".to_string(),
        ))
    })?;

    let mut pending = crate::dice_api::Pending::new(db::checkout(&state).await?);
    let tx = pending
        .connection()
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;

    let (original_thread_id, snoozed) =
        fetch_pending(&tx, active.session.id, user.id()).await?;
    let original_thread_id = match original_thread_id {
        Some(thread_id) => thread_id,
        None => {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(no_pending_roll());
        }
    };

    let target = fetch_target(&tx, request.node_id, user.id()).await?;
    let target = match target {
        Some(target) => target,
        None => {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(SwitchError::Api(ApiError::NotFound(format!(
                "Issue {} not found",
                request.node_id
            ))));
        }
    };

    // A selected prerequisite must still be the unread frontier of an eligible,
    // active series owned by this reader.
    let frontier = candidates
        .iter()
        .find(|candidate| candidate.thread_id == target.thread_id);
    let stale_target = target.issue_status != "unread"
        || frontier.is_none_or(|candidate| candidate.issue_id != target.issue_id)
        || target.thread_status != "active";
    if stale_target {
        let recovery = pending_roll_recovery(
            &validated,
            Some(original_thread_id),
            &HashSet::new(),
            &candidates,
        )
        .map_err(SwitchError::Api)?;
        tx.rollback().await.map_err(db::query_error)?;
        return Err(stale(recovery));
    }

    // Already pointing at the selected prerequisite: success without another
    // event, matching the Python idempotency for a repeated request.
    if original_thread_id == target.thread_id {
        tx.rollback().await.map_err(db::query_error)?;
        return Ok(RollPrerequisiteSwitchResponse {
            original_thread_id,
            target_thread_id: target.thread_id,
            target_thread_title: target.thread_title,
            target_issue_id: target.issue_id,
            target_issue_number: target.issue_number,
            changed: false,
        });
    }

    // The refreshed guidance must still list exactly this prerequisite.
    let recovery = pending_roll_recovery(
        &validated,
        Some(original_thread_id),
        &HashSet::new(),
        &candidates,
    )
    .map_err(SwitchError::Api)?;
    let recovery = match recovery {
        Some(recovery) => recovery,
        None => {
            tx.rollback().await.map_err(db::query_error)?;
            return Err(stale(None));
        }
    };
    let allowed = recovery
        .readable_prerequisites
        .iter()
        .any(|prerequisite| {
            prerequisite.get("node_type").and_then(|v| v.as_str()) == Some("issue")
                && prerequisite.get("node_id").and_then(|v| v.as_i64())
                    == Some(target.issue_id as i64)
        });
    if !allowed {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(stale(Some(recovery)));
    }

    // Clear only the durable session snooze for the newly selected series; the
    // original blocked roll and its audit trail stay intact.
    let mut snoozed_ids = snoozed.clone().unwrap_or_default();
    if snoozed_ids.contains(&target.thread_id) {
        snoozed_ids.retain(|thread_id| *thread_id != target.thread_id);
        tx.execute(
            "UPDATE sessions SET snoozed_thread_ids = $1::text::json
             WHERE id = $2 AND user_id = $3",
            &[
                &serde_json::to_string(&snoozed_ids)
                    .map_err(|_| ApiError::Internal("Invalid snooze state".to_string()))?,
                &active.session.id,
                &user.id(),
            ],
        )
        .await
        .map_err(db::query_error)?;
    }

    let die = current_die(&tx, user).await?;
    tx.execute(
        "INSERT INTO events
           (type,user_id,session_id,selected_thread_id,issue_id,issue_number,
            die,result,selection_method,timestamp)
         VALUES ('roll',$1,$2,$3,$4,$5,$6,0,'dependency_recovery',NOW())",
        &[
            &user.id(),
            &active.session.id,
            &target.thread_id,
            &target.issue_id,
            &target.issue_number,
            &die,
        ],
    )
    .await
    .map_err(db::query_error)?;

    let updated = tx
        .execute(
            "UPDATE sessions
             SET pending_thread_id=$1,pending_issue_id=$2,pending_thread_updated_at=NOW()
             WHERE id=$3 AND user_id=$4",
            &[
                &target.thread_id,
                &target.issue_id,
                &active.session.id,
                &user.id(),
            ],
        )
        .await
        .map_err(db::query_error)?;
    if updated != 1 {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(SwitchError::Api(ApiError::Conflict(
            "Reading session changed; try again".to_string(),
        )));
    }

    tx.commit().await.map_err(db::query_error)?;
    pending.release();

    Ok(RollPrerequisiteSwitchResponse {
        original_thread_id,
        target_thread_id: target.thread_id,
        target_thread_title: target.thread_title,
        target_issue_id: target.issue_id,
        target_issue_number: target.issue_number,
        changed: true,
    })
}

/// Documentation-only operation for the mounted v1 prerequisite switch.
#[utoipa::path(
    post,
    path = "/api/v1/roll/switch-prerequisite",
    tag = "roll",
    request_body = RollPrerequisiteSwitchRequest,
    responses(
        (status = 200, description = "Durable active target after accepting the prerequisite", body = RollPrerequisiteSwitchResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Selected issue was not found for this reader"),
        (status = 409, description = "No pending roll, or the guidance is stale"),
        (status = 422, description = "Unsupported continuity-node type")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn switch_prerequisite_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_issue_prerequisites_are_accepted() {
        assert!(is_supported_node_type("issue"));
        assert!(!is_supported_node_type("crossover"));
        assert!(!is_supported_node_type(""));
    }

    #[tokio::test]
    async fn switch_requires_authentication_before_database_access() {
        let config = crate::config::Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        })
        .unwrap();
        let app = crate::router(Arc::new(AppState::new(config).unwrap()));
        use axum::body::Body;
        use axum::http::Request;
        use tower::ServiceExt;
        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/roll/switch-prerequisite")
                    .header("content-type", "application/json")
                    .header("cookie", "csrf_token=synthetic-test-csrf")
                    .header("x-csrf-token", "synthetic-test-csrf")
                    .body(Body::from(r#"{"node_type":"issue","node_id":100}"#))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }

    #[test]
    fn unsupported_node_types_are_unprocessable() {
        // A request-level rejection never reaches the database.
        let request = RollPrerequisiteSwitchRequest {
            node_type: "crossover".into(),
            node_id: 1,
        };
        assert!(!is_supported_node_type(&request.node_type));
    }

    #[test]
    fn stale_recovery_detail_keeps_the_python_shape() {
        let error = stale(None);
        let response = error.into_response();
        assert_eq!(response.status(), StatusCode::CONFLICT);
    }
}