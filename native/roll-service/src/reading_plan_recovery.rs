//! Owner-scoped, explicit recovery for orphaned Option E continuity plans.
//! The persisted Plan is historical provenance; the selected Reading List becomes
//! the authority only after a before/after preview and an optimistic-lock check.
//! No existing membership, issue, rating, or event is rewritten.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    Json,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::sync::Arc;

const QUEUE_LOCK_NAMESPACE: i32 = 699001;

#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema, PartialEq, Eq)]
pub struct RecoveryStep {
    pub issue_id: i32,
    pub label: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct RecoveryCandidate {
    pub list_id: i32,
    pub name: String,
    pub mode: String,
    pub list_updated_at: String,
    pub steps: Vec<RecoveryStep>,
    pub added_steps: Vec<RecoveryStep>,
    pub removed_steps: Vec<RecoveryStep>,
    pub order_changed: bool,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct PlanRecoveryPreview {
    pub plan_id: i32,
    pub plan_name: String,
    pub plan_updated_at: String,
    /// A linked plan is not eligible for destructive association changes.
    pub status: String,
    pub linked_list_id: Option<i32>,
    pub retained_steps: Vec<RecoveryStep>,
    pub candidates: Vec<RecoveryCandidate>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct PlanRelinkRequest {
    pub list_id: i32,
    pub expected_plan_updated_at: String,
    pub expected_list_updated_at: String,
    /// Explicit confirmation of the candidate's membership and order differences.
    pub confirm: bool,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct PlanRelinkResult {
    pub plan_id: i32,
    pub list_id: i32,
    pub status: String,
}

fn candidate_diff(
    retained: &[RecoveryStep],
    steps: &[RecoveryStep],
) -> (Vec<RecoveryStep>, Vec<RecoveryStep>, bool) {
    let old: BTreeSet<i32> = retained.iter().map(|step| step.issue_id).collect();
    let new: BTreeSet<i32> = steps.iter().map(|step| step.issue_id).collect();
    let added = steps
        .iter()
        .filter(|step| !old.contains(&step.issue_id))
        .cloned()
        .collect();
    let removed = retained
        .iter()
        .filter(|step| !new.contains(&step.issue_id))
        .cloned()
        .collect();
    let old_common: Vec<i32> = retained
        .iter()
        .filter(|step| new.contains(&step.issue_id))
        .map(|step| step.issue_id)
        .collect();
    let new_common: Vec<i32> = steps
        .iter()
        .filter(|step| old.contains(&step.issue_id))
        .map(|step| step.issue_id)
        .collect();
    (added, removed, old_common != new_common)
}

/// `GET /api/v2/continuity-plans/{plan_id}/recovery`
///
/// Only owner-owned plans and owner-owned candidate lists are ever returned.
pub async fn preview(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<PlanRecoveryPreview>, ApiError> {
    let conn = db::checkout(&state).await?;
    let plan = conn
        .query_opt(
            "SELECT name, updated_at::text FROM continuity_plans WHERE id=$1 AND user_id=$2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Reading Plan not found".to_string()))?;
    let source_rows = conn
        .query(
            "SELECT DISTINCT s.custom_cbl_list_id FROM reading_plan_sources s
         JOIN custom_cbl_lists l ON l.id=s.custom_cbl_list_id AND l.user_id=$2
         WHERE s.plan_id=$1",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let linked_ids: Vec<i32> = source_rows
        .iter()
        .filter_map(|row| row.get::<_, Option<i32>>(0))
        .collect();

    let saved = conn.query(
        "SELECT r.issue_id, COALESCE(NULLIF(r.label,''), t.title || ' #' || i.issue_number, 'Issue #' || r.issue_id::text)
         FROM reading_plan_issues r
         LEFT JOIN issues i ON i.id=r.issue_id
         LEFT JOIN threads t ON t.id=i.thread_id AND t.user_id=$2
         WHERE r.plan_id=$1 ORDER BY r.display_position, r.occurrence_id",
        &[&plan_id, &user.id()],
    ).await.map_err(db::query_error)?;
    let retained_steps: Vec<RecoveryStep> = saved
        .iter()
        .map(|row| RecoveryStep {
            issue_id: row.get(0),
            label: row.get(1),
        })
        .collect();

    let lists = conn
        .query(
            "SELECT l.id, l.name, l.mode, l.updated_at::text,
                COALESCE(jsonb_agg(jsonb_build_object(
                    'issue_id',e.issue_id,'label',t.title || ' #' || i.issue_number)
                    ORDER BY e.position,e.id)
                    FILTER (WHERE e.id IS NOT NULL), '[]'::jsonb)::text
         FROM custom_cbl_lists l
         LEFT JOIN custom_cbl_entries e ON e.list_id=l.id
         LEFT JOIN issues i ON i.id=e.issue_id
         LEFT JOIN threads t ON t.id=i.thread_id AND t.user_id=l.user_id
         WHERE l.user_id=$1
         GROUP BY l.id ORDER BY lower(l.name),l.id",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;

    let mut candidates = Vec::with_capacity(lists.len());
    for row in lists {
        let steps_text: String = row.get(4);
        let steps: Vec<RecoveryStep> = serde_json::from_str(&steps_text).map_err(|e| {
            tracing::debug!(error = ?e, "preserved underlying error before mapping");
            ApiError::Internal("Invalid Reading List snapshot".to_string())
        })?;
        let (added_steps, removed_steps, order_changed) = candidate_diff(&retained_steps, &steps);
        candidates.push(RecoveryCandidate {
            list_id: row.get(0),
            name: row.get(1),
            mode: row.get(2),
            list_updated_at: row.get(3),
            steps,
            added_steps,
            removed_steps,
            order_changed,
        });
    }
    Ok(Json(PlanRecoveryPreview {
        plan_id,
        plan_name: plan.get(0),
        plan_updated_at: plan.get(1),
        status: if linked_ids.len() == 1 {
            "linked"
        } else if linked_ids.is_empty() {
            "orphaned"
        } else {
            "ambiguous"
        }
        .to_string(),
        linked_list_id: if linked_ids.len() == 1 {
            Some(linked_ids[0])
        } else {
            None
        },
        retained_steps,
        candidates,
    }))
}

/// `POST /api/v2/continuity-plans/{plan_id}/recovery`
///
/// Adds new provenance for a deliberately chosen list. Never mutates the Plan
/// snapshot, membership, issue identities, reading events or ratings.
pub async fn relink(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
    Json(request): Json<PlanRelinkRequest>,
) -> Result<Json<PlanRelinkResult>, ApiError> {
    if !request.confirm {
        return Err(ApiError::BadRequest(
            "Preview and confirm the Reading List before relinking".to_string(),
        ));
    }
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    tx.execute(
        "SELECT pg_advisory_xact_lock($1,$2)",
        &[&QUEUE_LOCK_NAMESPACE, &user.id()],
    )
    .await
    .map_err(db::query_error)?;
    let plan = tx
        .query_opt(
            "SELECT updated_at::text FROM continuity_plans WHERE id=$1 AND user_id=$2 FOR UPDATE",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Reading Plan not found".to_string()))?;
    let updated_at: String = plan.get(0);
    if updated_at != request.expected_plan_updated_at {
        return Err(ApiError::Conflict(
            "Reading Plan changed; refresh the repair preview".to_string(),
        ));
    }
    let list = tx
        .query_opt(
            "SELECT updated_at::text FROM custom_cbl_lists WHERE id=$1 AND user_id=$2 FOR UPDATE",
            &[&request.list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Reading List not found".to_string()))?;
    let list_updated_at: String = list.get(0);
    if list_updated_at != request.expected_list_updated_at {
        return Err(ApiError::Conflict(
            "Reading List changed; refresh the repair preview".to_string(),
        ));
    }
    let source_rows = tx
        .query(
            "SELECT custom_cbl_list_id FROM reading_plan_sources WHERE plan_id=$1",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    let linked: BTreeSet<i32> = source_rows
        .iter()
        .filter_map(|row| row.get::<_, Option<i32>>(0))
        .collect();
    if !linked.is_empty() {
        if linked.len() == 1 && linked.contains(&request.list_id) {
            tx.rollback().await.map_err(db::query_error)?;
            return Ok(Json(PlanRelinkResult {
                plan_id,
                list_id: request.list_id,
                status: "already_linked".to_string(),
            }));
        }
        return Err(ApiError::Conflict(
            "Reading Plan is already linked to another authoritative Reading List".to_string(),
        ));
    }

    let source_path = format!("custom-cbl:{}", request.list_id);
    // A legacy deleted source may retain the exact path with a NULL FK.
    let existing = tx
        .execute(
            "UPDATE reading_plan_sources SET custom_cbl_list_id=$1
         WHERE plan_id=$2 AND raw_source_path=$3 AND custom_cbl_list_id IS NULL",
            &[&request.list_id, &plan_id, &source_path],
        )
        .await
        .map_err(db::query_error)?;
    if existing == 0 {
        tx.execute(
            "INSERT INTO reading_plan_sources (plan_id,raw_source_path,custom_cbl_list_id,recorded_at)
             VALUES ($1,$2,$3,NOW())",
            &[&plan_id, &source_path, &request.list_id],
        ).await.map_err(db::query_error)?;
    }
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(PlanRelinkResult {
        plan_id,
        list_id: request.list_id,
        status: "relinked".to_string(),
    }))
}

#[utoipa::path(
    get,
    path = "/api/v2/continuity-plans/{plan_id}/recovery",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Owned Reading Plan identifier")),
    responses(
        (status = 200, description = "Owner-scoped recovery preview", body = PlanRecoveryPreview),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan not found")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn preview_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v2/continuity-plans/{plan_id}/recovery",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Owned Reading Plan identifier")),
    request_body = PlanRelinkRequest,
    responses(
        (status = 200, description = "Relinked or idempotently already linked", body = PlanRelinkResult),
        (status = 400, description = "Confirmation required"),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Plan or list not found"),
        (status = 409, description = "Stale preview or different authoritative list")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn relink_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::StatusCode;
    #[test]
    fn preview_reports_changed_membership_without_replacing_identity() {
        let original = vec![
            RecoveryStep {
                issue_id: 101,
                label: "Superman #1".into(),
            },
            RecoveryStep {
                issue_id: 103,
                label: "Superman #3".into(),
            },
            RecoveryStep {
                issue_id: 201,
                label: "Batman #1".into(),
            },
        ];
        let candidate = vec![
            original[0].clone(),
            RecoveryStep {
                issue_id: 302,
                label: "Superman #2 (replacement)".into(),
            },
            original[2].clone(),
            original[1].clone(),
        ];
        let (added, removed, reordered) = candidate_diff(&original, &candidate);
        assert_eq!(added[0].issue_id, 302);
        assert!(removed.is_empty());
        assert!(reordered);
    }

    /// Exercise the mounted Rust write handler against the canonical Alembic
    /// schema. A replay must not duplicate source provenance or alter the Plan.
    #[tokio::test]
    async fn relink_writes_owned_source_once_and_rejects_other_owner() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _db_guard = crate::test_support::reset_for_test(&state).await;
        let conn = state
            .pool
            .get()
            .await
            .expect("disposable Postgres connection");
        conn.batch_execute(
            "INSERT INTO users (id, username)
             VALUES (1,'plan-recovery-owner'),(2,'plan-recovery-other');
             INSERT INTO continuity_plans
               (id,user_id,name,ordering_mode,nodes_json,lanes_json,created_at,updated_at)
             VALUES (101,1,'Orphaned Plan A','strict_sequential',
                     '[]'::json,'[]'::json,NOW(),NOW());
             INSERT INTO custom_cbl_lists
               (id,user_id,name,mode,created_at,updated_at)
             VALUES (201,1,'Chosen authoritative Reading List','strict',NOW(),NOW());",
        )
        .await
        .expect("canonical Plan A and candidate list fixtures");
        let plan_updated_at: String = conn
            .query_one(
                "SELECT updated_at::text FROM continuity_plans WHERE id=101",
                &[],
            )
            .await
            .unwrap()
            .get(0);
        let list_updated_at: String = conn
            .query_one(
                "SELECT updated_at::text FROM custom_cbl_lists WHERE id=201",
                &[],
            )
            .await
            .unwrap()
            .get(0);

        let request = || PlanRelinkRequest {
            list_id: 201,
            expected_plan_updated_at: plan_updated_at.clone(),
            expected_list_updated_at: list_updated_at.clone(),
            confirm: true,
        };
        let (first, second) = (
            relink(
                State(state.clone()),
                AuthenticatedUser::for_test(1),
                Path(101),
                Json(request()),
            )
            .await
            .expect("owned first relink")
            .0,
            relink(
                State(state.clone()),
                AuthenticatedUser::for_test(1),
                Path(101),
                Json(request()),
            )
            .await
            .expect("idempotent relink replay")
            .0,
        );
        assert_eq!(first.status, "relinked");
        assert_eq!(second.status, "already_linked");
        assert_eq!(first.list_id, 201);
        assert_eq!(second.list_id, 201);

        let count: i64 = conn
            .query_one(
                "SELECT count(*) FROM reading_plan_sources
                 WHERE plan_id=101 AND custom_cbl_list_id=201",
                &[],
            )
            .await
            .unwrap()
            .get(0);
        assert_eq!(
            count, 1,
            "idempotent replay must never duplicate provenance"
        );

        let foreign = relink(
            State(state.clone()),
            AuthenticatedUser::for_test(2),
            Path(101),
            Json(request()),
        )
        .await
        .expect_err("another owner cannot relink Plan A");
        assert_eq!(foreign.status(), StatusCode::NOT_FOUND);
        let count_after: i64 = conn
            .query_one(
                "SELECT count(*) FROM reading_plan_sources WHERE plan_id=101",
                &[],
            )
            .await
            .unwrap()
            .get(0);
        assert_eq!(
            count_after, 1,
            "foreign attempt must leave provenance intact"
        );
    }
}
