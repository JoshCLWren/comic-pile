//! Same-path native handlers for the remaining browser-called custom-CBL API.
//!
//! The collection/detail/reader operations deliberately reuse the canonical
//! Reading List handlers.  This module owns the legacy custom-CBL-only edges so
//! their established URLs can be moved as one ingress slice without deleting
//! the Python implementation before production evidence exists.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, Query, State},
    http::{header, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeSet, sync::Arc};

#[derive(Debug, Deserialize, utoipa::IntoParams)]
#[into_params(parameter_in = Query)]
pub struct IssueSearchQuery {
    pub q: Option<String>,
    pub limit: Option<i64>,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct IssueSearchResult {
    pub issue_id: i32,
    pub thread_id: i32,
    pub series_name: String,
    pub issue_number: String,
    pub status: String,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct OverlapDecisionItem {
    pub id: i32,
    pub continuing_volume_id: String,
    pub waiting_volume_id: String,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct OverlapVolumeCandidate {
    pub thread_id: i32,
    pub thread_title: String,
    pub volume_id: String,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct OverlapDecisionSetResponse {
    pub list_id: i32,
    pub updated_at: String,
    pub decisions: Vec<OverlapDecisionItem>,
    pub candidate_volumes: Vec<OverlapVolumeCandidate>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct OverlapDecisionWrite {
    pub continuing_volume_id: String,
    pub waiting_volume_id: String,
    pub expected_updated_at: Option<String>,
}

#[utoipa::path(get, path = "/api/v1/custom-cbls", tag = "custom-cbls",
    responses((status = 200, body = Vec<crate::reading_list::ReadingListSummary>), (status = 401)), security(("HTTPBearer" = [])))]
pub fn custom_cbl_list_documentation() {}

#[utoipa::path(post, path = "/api/v1/custom-cbls", tag = "custom-cbls",
    request_body = crate::reading_list::ReadingListWrite,
    responses((status = 201, body = crate::reading_list::ReadingList), (status = 401)), security(("HTTPBearer" = [])))]
pub fn custom_cbl_create_documentation() {}

#[utoipa::path(get, path = "/api/v1/custom-cbls/{list_id}", tag = "custom-cbls",
    params(("list_id" = i32, Path)), responses((status = 200, body = crate::reading_list::ReadingList), (status = 401), (status = 404)), security(("HTTPBearer" = [])))]
pub fn custom_cbl_get_documentation() {}

#[utoipa::path(put, path = "/api/v1/custom-cbls/{list_id}", tag = "custom-cbls",
    params(("list_id" = i32, Path)), request_body = crate::reading_list::ReadingListWrite,
    responses((status = 200, body = crate::reading_list::ReadingList), (status = 401), (status = 404)), security(("HTTPBearer" = [])))]
pub fn custom_cbl_update_documentation() {}

#[utoipa::path(get, path = "/api/v1/custom-cbls/{list_id}/reader", tag = "custom-cbls",
    params(("list_id" = i32, Path)), responses((status = 200, body = crate::reading_list::ReadingListReader), (status = 401), (status = 404)), security(("HTTPBearer" = [])))]
pub fn custom_cbl_reader_documentation() {}

#[utoipa::path(get, path = "/api/v1/custom-cbls/issue-search", tag = "custom-cbls",
    params(IssueSearchQuery), responses((status = 200, body = Vec<IssueSearchResult>), (status = 401)), security(("HTTPBearer" = [])))]
pub fn custom_cbl_search_documentation() {}

#[utoipa::path(get, path = "/api/v1/custom-cbls/{list_id}/export", tag = "custom-cbls",
    params(("list_id" = i32, Path)), responses((status = 200, body = String), (status = 401), (status = 404)), security(("HTTPBearer" = [])))]
pub fn custom_cbl_export_documentation() {}

#[utoipa::path(get, path = "/api/v1/custom-cbls/{list_id}/overlap-decisions", tag = "custom-cbls",
    params(("list_id" = i32, Path)), responses((status = 200, body = OverlapDecisionSetResponse), (status = 401), (status = 404)), security(("HTTPBearer" = [])))]
pub fn custom_cbl_get_overlap_documentation() {}

#[utoipa::path(put, path = "/api/v1/custom-cbls/{list_id}/overlap-decisions", tag = "custom-cbls",
    params(("list_id" = i32, Path)), request_body = OverlapDecisionWrite,
    responses((status = 200, body = OverlapDecisionSetResponse), (status = 401), (status = 404), (status = 409), (status = 422)), security(("HTTPBearer" = [])))]
pub fn custom_cbl_put_overlap_documentation() {}

#[utoipa::path(delete, path = "/api/v1/custom-cbls/{list_id}/overlap-decisions/{decision_id}", tag = "custom-cbls",
    params(("list_id" = i32, Path), ("decision_id" = i32, Path)), responses((status = 200, body = OverlapDecisionSetResponse), (status = 401), (status = 404)), security(("HTTPBearer" = [])))]
pub fn custom_cbl_delete_overlap_documentation() {}

#[utoipa::path(post, path = "/api/v1/custom-cbls/{list_id}/reading-plans/{plan_id}:apply", tag = "custom-cbls",
    params(("list_id" = i32, Path), ("plan_id" = i32, Path)), request_body = serde_json::Value,
    responses((status = 200, body = serde_json::Value), (status = 401), (status = 404), (status = 422)), security(("HTTPBearer" = [])))]
pub fn custom_cbl_apply_documentation() {}

fn bad_request(message: impl Into<String>) -> ApiError {
    ApiError(StatusCode::UNPROCESSABLE_ENTITY, message.into())
}

fn volume_id(value: &str) -> Option<&str> {
    value
        .strip_prefix("comicvine:")
        .filter(|id| !id.is_empty() && id.len() <= 100)
}

pub async fn search_issues(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(query): Query<IssueSearchQuery>,
) -> Result<Json<Vec<IssueSearchResult>>, ApiError> {
    let limit = query.limit.unwrap_or(30).clamp(1, 100);
    let text = query.q.unwrap_or_default().trim().to_string();
    let pattern = format!("%{text}%");
    let conn = db::checkout(&state).await?;
    let rows = conn
        .query(
            "SELECT i.id,i.thread_id,t.title,i.issue_number,i.status
             FROM issues i JOIN threads t ON t.id=i.thread_id
             WHERE t.user_id=$1 AND ($2='' OR t.title ILIKE $3 OR i.issue_number ILIKE $3
                OR (t.title || ' #' || i.issue_number) ILIKE $3)
             ORDER BY t.title,i.position,i.id LIMIT $4",
            &[&user.id(), &text, &pattern, &limit],
        )
        .await
        .map_err(db::query_error)?;
    Ok(Json(
        rows.iter()
            .map(|row| IssueSearchResult {
                issue_id: row.get(0),
                thread_id: row.get(1),
                series_name: row.get(2),
                issue_number: row.get(3),
                status: row.get(4),
            })
            .collect(),
    ))
}

pub async fn export(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
) -> Result<Response, ApiError> {
    let conn = db::checkout(&state).await?;
    let list = conn
        .query_opt(
            "SELECT name FROM custom_cbl_lists WHERE id=$1 AND user_id=$2",
            &[&list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError(StatusCode::NOT_FOUND, "Reading List not found".into()))?;
    let name: String = list.get(0);
    let rows = conn
        .query(
            "SELECT t.title,i.issue_number FROM custom_cbl_entries e
             JOIN issues i ON i.id=e.issue_id JOIN threads t ON t.id=i.thread_id
             WHERE e.list_id=$1 ORDER BY e.position,e.id",
            &[&list_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut xml = format!(
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<ReadingList>\n  <Name>{}</Name>\n  <NumIssues>{}</NumIssues>\n  <Books>\n",
        escape_xml(&name),
        rows.len()
    );
    for row in &rows {
        xml.push_str(&format!(
            "    <Book Series=\"{}\" Number=\"{}\" />\n",
            escape_xml(&row.get::<_, String>(0)),
            escape_xml(&row.get::<_, String>(1)),
        ));
    }
    xml.push_str("  </Books>\n</ReadingList>\n");
    let mut response = xml.into_response();
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/xml"),
    );
    response.headers_mut().insert(
        header::CONTENT_DISPOSITION,
        HeaderValue::from_str(&format!(
            "attachment; filename=\"custom-cbl-{list_id}.cbl\""
        ))
        .map_err(|_| {
            ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Internal Server Error".into(),
            )
        })?,
    );
    Ok(response)
}

fn escape_xml(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

async fn decision_set(
    conn: &deadpool_postgres::Object,
    user_id: i32,
    list_id: i32,
) -> Result<OverlapDecisionSetResponse, ApiError> {
    let list = conn
        .query_opt(
            "SELECT overlap_decisions_updated_at::text FROM custom_cbl_lists WHERE id=$1 AND user_id=$2",
            &[&list_id, &user_id],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError(StatusCode::NOT_FOUND, "Reading List not found".into()))?;
    let updated_at: String = list.get(0);
    let rows = conn
        .query(
            "SELECT d.id,'comicvine:'||c.external_id,'comicvine:'||w.external_id,
                    d.created_at::text,d.updated_at::text
             FROM custom_cbl_overlap_decisions d
             JOIN external_identities c ON c.id=d.continuing_external_identity_id
             JOIN external_identities w ON w.id=d.waiting_external_identity_id
             WHERE d.list_id=$1 AND d.user_id=$2 ORDER BY d.id",
            &[&list_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let candidates = conn
        .query(
            "SELECT DISTINCT t.id,t.title,'comicvine:'||x.external_id
             FROM threads t
             JOIN thread_external_series_mappings m ON m.thread_id=t.id AND m.status='confirmed'
             JOIN external_identities x ON x.id=m.external_identity_id
             WHERE t.user_id=$1 AND x.provider='comicvine' AND x.entity_type='series'
             ORDER BY t.id",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(OverlapDecisionSetResponse {
        list_id,
        updated_at,
        decisions: rows
            .iter()
            .map(|row| OverlapDecisionItem {
                id: row.get(0),
                continuing_volume_id: row.get(1),
                waiting_volume_id: row.get(2),
                created_at: row.get(3),
                updated_at: row.get(4),
            })
            .collect(),
        candidate_volumes: candidates
            .iter()
            .map(|row| OverlapVolumeCandidate {
                thread_id: row.get(0),
                thread_title: row.get(1),
                volume_id: row.get(2),
            })
            .collect(),
    })
}

pub async fn get_overlap_decisions(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
) -> Result<Json<OverlapDecisionSetResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    Ok(Json(decision_set(&conn, user.id(), list_id).await?))
}

pub async fn put_overlap_decision(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(list_id): Path<i32>,
    Json(request): Json<OverlapDecisionWrite>,
) -> Result<Json<OverlapDecisionSetResponse>, ApiError> {
    let continuing = volume_id(&request.continuing_volume_id)
        .ok_or_else(|| bad_request("An overlap decision must name two exact Comic Vine volumes"))?;
    let waiting = volume_id(&request.waiting_volume_id)
        .ok_or_else(|| bad_request("An overlap decision must name two exact Comic Vine volumes"))?;
    if continuing == waiting {
        return Err(bad_request(
            "An overlap decision must name two distinct volumes",
        ));
    }
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    let current = tx.query_opt("SELECT overlap_decisions_updated_at::text FROM custom_cbl_lists WHERE id=$1 AND user_id=$2 FOR UPDATE", &[&list_id, &user.id()]).await.map_err(db::query_error)?.ok_or_else(|| ApiError(StatusCode::NOT_FOUND, "Reading List not found".into()))?;
    let current_at: String = current.get(0);
    if request
        .expected_updated_at
        .as_deref()
        .is_some_and(|value| value != current_at)
    {
        return Err(ApiError(
            StatusCode::CONFLICT,
            "The Reading List's overlap decisions changed since they were read".into(),
        ));
    }
    let ids = tx.query("SELECT id,external_id FROM external_identities WHERE provider='comicvine' AND entity_type='series' AND external_id=ANY($1::text[])", &[&vec![continuing, waiting]]).await.map_err(db::query_error)?;
    let mut identity_ids = std::collections::HashMap::new();
    for row in ids {
        identity_ids.insert(row.get::<_, String>(1), row.get::<_, i32>(0));
    }
    let continuing_id = *identity_ids
        .get(continuing)
        .ok_or_else(|| bad_request("An overlap decision must name two known Comic Vine volumes"))?;
    let waiting_id = *identity_ids
        .get(waiting)
        .ok_or_else(|| bad_request("An overlap decision must name two known Comic Vine volumes"))?;
    tx.execute("DELETE FROM custom_cbl_overlap_decisions WHERE list_id=$1 AND user_id=$2 AND ((continuing_external_identity_id=$3 AND waiting_external_identity_id=$4) OR (continuing_external_identity_id=$4 AND waiting_external_identity_id=$3))", &[&list_id, &user.id(), &continuing_id, &waiting_id]).await.map_err(db::query_error)?;
    tx.execute("INSERT INTO custom_cbl_overlap_decisions (user_id,list_id,continuing_external_identity_id,waiting_external_identity_id,created_at,updated_at) VALUES ($1,$2,$3,$4,NOW(),NOW())", &[&user.id(), &list_id, &continuing_id, &waiting_id]).await.map_err(db::query_error)?;
    tx.execute(
        "UPDATE custom_cbl_lists SET overlap_decisions_updated_at=NOW() WHERE id=$1 AND user_id=$2",
        &[&list_id, &user.id()],
    )
    .await
    .map_err(db::query_error)?;
    tx.commit().await.map_err(db::query_error)?;
    let conn = db::checkout(&state).await?;
    Ok(Json(decision_set(&conn, user.id(), list_id).await?))
}

pub async fn delete_overlap_decision(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path((list_id, decision_id)): Path<(i32, i32)>,
    Query(_query): Query<std::collections::HashMap<String, String>>,
) -> Result<Json<OverlapDecisionSetResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    let deleted = tx
        .execute(
            "DELETE FROM custom_cbl_overlap_decisions WHERE id=$1 AND list_id=$2 AND user_id=$3",
            &[&decision_id, &list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    if deleted == 0 {
        return Err(ApiError(
            StatusCode::NOT_FOUND,
            "Overlap decision not found".into(),
        ));
    }
    tx.execute(
        "UPDATE custom_cbl_lists SET overlap_decisions_updated_at=NOW() WHERE id=$1 AND user_id=$2",
        &[&list_id, &user.id()],
    )
    .await
    .map_err(db::query_error)?;
    tx.commit().await.map_err(db::query_error)?;
    let conn = db::checkout(&state).await?;
    Ok(Json(decision_set(&conn, user.id(), list_id).await?))
}

pub async fn apply(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path((list_id, plan_id)): Path<(i32, i32)>,
    Json(request): Json<serde_json::Value>,
) -> Result<Response, ApiError> {
    let lane_id = request.get("lane_id").and_then(|value| value.as_str());
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    let list = tx
        .query_opt(
            "SELECT name FROM custom_cbl_lists WHERE id=$1 AND user_id=$2",
            &[&list_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError(StatusCode::NOT_FOUND, "Reading List not found".into()))?;
    let list_name: String = list.get(0);
    let plan = tx
        .query_opt(
            "SELECT name,ordering_mode,nodes_json::text,lanes_json::text FROM continuity_plans
             WHERE id=$1 AND user_id=$2 FOR UPDATE",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError(StatusCode::NOT_FOUND, "Continuity plan not found".into()))?;
    let plan_name: String = plan.get(0);
    let ordering_mode: String = plan.get(1);
    let mut lanes: Vec<serde_json::Value> =
        serde_json::from_str::<serde_json::Value>(&plan.get::<_, String>(3))
            .unwrap_or(serde_json::Value::Array(vec![]))
            .as_array()
            .cloned()
            .unwrap_or_default();
    if lanes.is_empty() {
        lanes.push(serde_json::json!({"id":"custom-cbl","name":"Custom CBL","order":0}));
    }
    let target = if let Some(requested) = lane_id {
        if !lanes
            .iter()
            .any(|lane| lane.get("id").and_then(|id| id.as_str()) == Some(requested))
        {
            return Err(ApiError(
                StatusCode::UNPROCESSABLE_ENTITY,
                format!("custom_cbl_lane_not_found: {requested}"),
            ));
        }
        requested.to_string()
    } else {
        lanes
            .iter()
            .min_by_key(|lane| {
                lane.get("order")
                    .and_then(|order| order.as_i64())
                    .unwrap_or(i64::MAX)
            })
            .and_then(|lane| lane.get("id").and_then(|id| id.as_str()))
            .unwrap_or("custom-cbl")
            .to_string()
    };
    let mut nodes = serde_json::from_str::<serde_json::Value>(&plan.get::<_, String>(2))
        .unwrap_or(serde_json::Value::Array(vec![]))
        .as_array()
        .cloned()
        .unwrap_or_default();
    let entries = tx
        .query(
            "SELECT e.id,e.position,e.issue_id,t.title,i.issue_number,e.is_checkpoint,
                    e.checkpoint_target_issue_ids::text
             FROM custom_cbl_entries e JOIN issues i ON i.id=e.issue_id
             JOIN threads t ON t.id=i.thread_id WHERE e.list_id=$1 ORDER BY e.position,e.id",
            &[&list_id],
        )
        .await
        .map_err(db::query_error)?;
    if entries.is_empty() {
        return Err(ApiError(
            StatusCode::UNPROCESSABLE_ENTITY,
            serde_json::json!({"code":"custom_cbl_empty","message":"Custom CBL has no issues"})
                .to_string(),
        ));
    }
    let source_path = format!("custom-cbl:{list_id}");
    let source_ids: BTreeSet<i32> = entries.iter().map(|row| row.get(2)).collect();
    let mut added = Vec::new();
    let mut skipped = Vec::new();
    nodes.retain(|node| {
        let issue_id = node
            .get("ref_id")
            .and_then(|value| value.as_i64())
            .and_then(|value| i32::try_from(value).ok());
        let same_source = node
            .get("source_paths")
            .and_then(|paths| paths.as_array())
            .is_some_and(|paths| {
                paths
                    .iter()
                    .any(|path| path.as_str() == Some(source_path.as_str()))
            });
        !(same_source && issue_id.is_some_and(|id| source_ids.contains(&id)))
    });
    for row in entries {
        let issue_id: i32 = row.get(2);
        if nodes.iter().any(|node| {
            node.get("node_type").and_then(|value| value.as_str()) == Some("issue")
                && node.get("ref_id").and_then(|value| value.as_i64()) == Some(i64::from(issue_id))
        }) {
            skipped.push(issue_id);
            continue;
        }
        let entry_id: i32 = row.get(0);
        let position: i32 = row.get(1);
        let title: String = row.get(3);
        let number: String = row.get(4);
        let checkpoint: bool = row.get(5);
        let targets: Vec<i32> = serde_json::from_str(&row.get::<_, String>(6)).unwrap_or_default();
        nodes.push(serde_json::json!({
            "id":format!("custom-cbl-{list_id}-{entry_id}"),"node_type":"issue","ref_id":issue_id,
            "lane_id":target,"position":position,"label":format!("{title} #{number}"),
            "source_paths":[source_path],"source_cbl_placements":[{"source_path":format!("custom-cbl:{list_id}"),"position":position}],
            "source_explanation":format!("Added from custom CBL '{list_name}'."),
            "is_checkpoint":checkpoint,"checkpoint_target_ref_ids":targets,"convergence_gate":[]
        }));
        added.push(issue_id);
    }
    let nodes_json = serde_json::Value::Array(nodes.clone());
    let lanes_json = serde_json::Value::Array(lanes.clone());
    let nodes_json = tokio_postgres::types::Json(nodes_json);
    let lanes_json = tokio_postgres::types::Json(lanes_json);
    tx.execute(
        "UPDATE continuity_plans SET nodes_json=$1::json,lanes_json=$2::json,updated_at=NOW() WHERE id=$3 AND user_id=$4",
        &[&nodes_json, &lanes_json, &plan_id, &user.id()],
    )
    .await
    .map_err(db::query_error)?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(serde_json::json!({
        "name":plan_name,"ordering_mode":ordering_mode,"lanes":lanes,"nodes":nodes,
        "added_issue_ids":added,"skipped_existing_issue_ids":skipped
    }))
    .into_response())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    async fn state_and_connection() -> (Arc<AppState>, tokio::sync::MutexGuard<'static, ()>) {
        let state = crate::test_support::test_state(3)
            .await
            .expect("disposable PostgreSQL required");
        let guard = crate::test_support::reset_for_test(&state).await;
        (state, guard)
    }

    #[tokio::test]
    async fn apply_writes_custom_cbl_entries_into_the_plan() {
        let (state, _db_guard) = state_and_connection().await;
        let conn = db::checkout(&state)
            .await
            .expect("disposable Postgres connection");
        conn.batch_execute(
            "INSERT INTO users (id, username, is_admin, created_at)
             VALUES (1, 'custom-cbl-owner', false, NOW());
             INSERT INTO custom_cbl_lists (id, user_id, name, mode, created_at, updated_at)
             VALUES (201, 1, 'Custom CBL', 'strict', NOW(), NOW());
             INSERT INTO continuity_plans
               (id, user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
             VALUES (301, 1, 'Plan', 'strict_sequential', '[]'::json, '[]'::json, NOW(), NOW());
             INSERT INTO threads
               (id, user_id, title, format, issues_remaining, queue_position, status,
                is_blocked, is_test, manual_creator_credits, queue_position_is_manual, created_at)
             VALUES (401, 1, 'Series', 'Comic', 1, 1, 'active', false, false, '[]'::json,
                     false, NOW());
             INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
             VALUES (501, 401, '1', 'unread', NOW(), 1);
             INSERT INTO custom_cbl_entries
               (id, list_id, issue_id, position, created_at, is_checkpoint)
             VALUES (601, 201, 501, 1, NOW(), false);",
        )
        .await
        .expect("seed custom CBL apply fixture");
        drop(conn);

        apply(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path((201, 301)),
            Json(serde_json::json!({})),
        )
        .await
        .expect("custom CBL apply");

        let conn = db::checkout(&state)
            .await
            .expect("read applied plan connection");
        let row = conn
            .query_one(
                "SELECT nodes_json::text FROM continuity_plans WHERE id=301",
                &[],
            )
            .await
            .expect("read applied plan");
        let nodes: Value = serde_json::from_str(row.get(0)).expect("valid plan nodes JSON");
        assert_eq!(nodes.as_array().expect("nodes array").len(), 1);
        assert_eq!(nodes[0]["ref_id"], 501);
    }

    #[tokio::test]
    async fn delete_overlap_decision_removes_the_decision_and_updates_the_list() {
        let (state, _db_guard) = state_and_connection().await;
        let conn = db::checkout(&state)
            .await
            .expect("disposable Postgres connection");
        conn.batch_execute(
            "INSERT INTO users (id, username, is_admin, created_at)
             VALUES (1, 'custom-cbl-owner', false, NOW());
             INSERT INTO custom_cbl_lists (id, user_id, name, mode, created_at, updated_at)
             VALUES (201, 1, 'Custom CBL', 'strict', NOW(), NOW());
             INSERT INTO external_identities
               (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
             VALUES (701, 'comicvine', 'series', '1001', '{}'::json, NOW(), NOW()),
                    (702, 'comicvine', 'series', '1002', '{}'::json, NOW(), NOW());
             INSERT INTO custom_cbl_overlap_decisions
               (id, user_id, list_id, continuing_external_identity_id,
                waiting_external_identity_id, created_at, updated_at)
             VALUES (801, 1, 201, 701, 702, NOW(), NOW());",
        )
        .await
        .expect("seed overlap decision fixture");
        drop(conn);

        let _ = delete_overlap_decision(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Path((201, 801)),
            Query(std::collections::HashMap::new()),
        )
        .await
        .expect("delete overlap decision");

        let conn = db::checkout(&state)
            .await
            .expect("read deleted decision connection");
        let remaining: i64 = conn
            .query_one(
                "SELECT count(*) FROM custom_cbl_overlap_decisions WHERE id=801",
                &[],
            )
            .await
            .expect("read deleted decision")
            .get(0);
        assert_eq!(remaining, 0);
    }
}
