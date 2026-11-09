//! Same-path native CRUD for the browser's generalized continuity rules.
//!
//! The Python implementation remains in place until production execution is
//! proven. This module deliberately mirrors its owner checks, graph lock,
//! cycle validation, canonical dependency compilation, and response shape.

use crate::{
    auth::AuthenticatedUser, db, issue_service::refresh_blocked_threads, ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::sync::Arc;
use tokio_postgres::{Row, Transaction};
use utoipa::ToSchema;

const CONTINUITY_LOCK_NAMESPACE: i32 = 1_129_274_964;
const RULE_NOTE_PREFIX: &str = "canonical:rule:";

#[derive(Debug, Clone, Deserialize, Serialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ConvergenceTarget {
    #[serde(rename = "type")]
    pub node_type: String,
    pub id: i32,
}

#[derive(Debug, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ContinuityRuleRequest {
    pub source_type: String,
    pub source_id: i32,
    pub target_type: String,
    pub target_id: i32,
    pub satisfaction_type: String,
    pub checkpoint_issue_id: Option<i32>,
    #[serde(default)]
    pub convergence_targets: Vec<ConvergenceTarget>,
    #[serde(default)]
    pub selected_member_issue_ids: Vec<i32>,
    pub note: Option<String>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct ContinuityRuleResponse {
    pub id: i32,
    pub user_id: i32,
    pub source_type: String,
    pub source_id: i32,
    pub target_type: String,
    pub target_id: i32,
    pub satisfaction_type: String,
    pub checkpoint_issue_id: Option<i32>,
    pub convergence_targets: Vec<ConvergenceTarget>,
    pub selected_member_issue_ids: Vec<i32>,
    pub note: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

fn bad_request(detail: impl Into<String>) -> ApiError {
    ApiError(StatusCode::BAD_REQUEST, detail.into())
}

fn conflict(detail: impl Into<String>) -> ApiError {
    ApiError(StatusCode::CONFLICT, detail.into())
}

fn not_found(detail: impl Into<String>) -> ApiError {
    ApiError(StatusCode::NOT_FOUND, detail.into())
}

fn validate_request(request: &ContinuityRuleRequest) -> Result<(), ApiError> {
    if !matches!(request.source_type.as_str(), "issue" | "crossover")
        || !matches!(request.target_type.as_str(), "issue" | "crossover")
    {
        return Err(bad_request(
            "source_type and target_type must be 'issue' or 'crossover'",
        ));
    }
    if request.source_id <= 0 || request.target_id <= 0 {
        return Err(bad_request("IDs must be greater than 0"));
    }
    if request.source_type == request.target_type && request.source_id == request.target_id {
        return Err(bad_request(
            "A continuity rule cannot target its own source node",
        ));
    }
    if !matches!(
        request.satisfaction_type.as_str(),
        "item_read" | "all_members_read" | "checkpoint" | "selected_members_read" | "converged"
    ) {
        return Err(bad_request("Invalid satisfaction_type"));
    }
    if request.satisfaction_type == "checkpoint" && request.checkpoint_issue_id.is_none() {
        return Err(bad_request(
            "checkpoint_issue_id is required for checkpoint rules",
        ));
    }
    if request.satisfaction_type != "checkpoint" && request.checkpoint_issue_id.is_some() {
        return Err(bad_request(
            "checkpoint_issue_id is only valid for checkpoint rules",
        ));
    }
    if request.satisfaction_type == "converged" && request.convergence_targets.is_empty() {
        return Err(bad_request(
            "convergence_targets are required for converged rules",
        ));
    }
    if request.satisfaction_type != "converged" && !request.convergence_targets.is_empty() {
        return Err(bad_request(
            "convergence_targets are only valid for converged rules",
        ));
    }
    if request.satisfaction_type == "selected_members_read"
        && request.selected_member_issue_ids.is_empty()
    {
        return Err(bad_request(
            "selected-member rules require at least one issue",
        ));
    }
    if request.satisfaction_type != "selected_members_read"
        && !request.selected_member_issue_ids.is_empty()
    {
        return Err(bad_request(
            "selected_member_issue_ids are only valid for selected-member rules",
        ));
    }
    if request
        .convergence_targets
        .iter()
        .any(|target| !matches!(target.node_type.as_str(), "issue" | "crossover") || target.id <= 0)
    {
        return Err(bad_request("Invalid convergence target"));
    }
    if request.checkpoint_issue_id.is_some_and(|id| id <= 0)
        || request.selected_member_issue_ids.iter().any(|id| *id <= 0)
    {
        return Err(bad_request("Referenced issue IDs must be greater than 0"));
    }
    if request
        .note
        .as_ref()
        .is_some_and(|note| note.chars().count() > 500)
    {
        return Err(bad_request("String should have at most 500 characters"));
    }
    Ok(())
}

fn normalize_request(request: &mut ContinuityRuleRequest) {
    request.selected_member_issue_ids.sort_unstable();
    request.selected_member_issue_ids.dedup();
    let mut seen = std::collections::HashSet::new();
    request
        .convergence_targets
        .retain(|target| seen.insert((target.node_type.clone(), target.id)));
}

fn edge_pairs(request: &ContinuityRuleRequest) -> Vec<(i32, i32)> {
    match request.satisfaction_type.as_str() {
        "item_read" | "checkpoint"
            if request.source_type == "issue" && request.target_type == "issue" =>
        {
            vec![(
                request.checkpoint_issue_id.unwrap_or(request.source_id),
                request.target_id,
            )]
        }
        "converged" if request.target_type == "issue" => request
            .convergence_targets
            .iter()
            .filter(|target| target.node_type == "issue" && target.id != request.target_id)
            .map(|target| (target.id, request.target_id))
            .collect(),
        _ => Vec::new(),
    }
}

fn require_compilable(request: &ContinuityRuleRequest) -> Result<(), ApiError> {
    if request.satisfaction_type == "converged"
        && request
            .convergence_targets
            .iter()
            .any(|target| target.node_type != "issue")
    {
        let count = request
            .convergence_targets
            .iter()
            .filter(|target| target.node_type != "issue")
            .count();
        return Err(bad_request(format!(
            "Rule has {count} non-issue prerequisite(s); all convergence targets must be issues to compile to canonical edges"
        )));
    }
    if edge_pairs(request).is_empty() {
        return Err(bad_request(format!(
            "Rule with satisfaction_type={}, source_type={}, target_type={} does not compile to canonical edges and would never block Roll",
            request.satisfaction_type, request.source_type, request.target_type
        )));
    }
    Ok(())
}

async fn lock_graph(tx: &Transaction<'_>, user_id: i32) -> Result<(), ApiError> {
    tx.execute(
        "SELECT pg_advisory_xact_lock($1, $2)",
        &[&CONTINUITY_LOCK_NAMESPACE, &user_id],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

async fn owned_node(
    tx: &Transaction<'_>,
    user_id: i32,
    node_type: &str,
    node_id: i32,
) -> Result<bool, ApiError> {
    let row = if node_type == "issue" {
        tx.query_opt(
            "SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id
             WHERE i.id=$1 AND t.user_id=$2",
            &[&node_id, &user_id],
        )
        .await
        .map_err(db::query_error)?
    } else {
        tx.query_opt(
            "SELECT id FROM dependency_groups WHERE id=$1 AND user_id=$2",
            &[&node_id, &user_id],
        )
        .await
        .map_err(db::query_error)?
    };
    Ok(row.is_some())
}

async fn owned_references(
    tx: &Transaction<'_>,
    user_id: i32,
    request: &ContinuityRuleRequest,
) -> Result<(), ApiError> {
    for (kind, id) in [
        (request.source_type.as_str(), request.source_id),
        (request.target_type.as_str(), request.target_id),
    ] {
        if !owned_node(tx, user_id, kind, id).await? {
            return Err(not_found(format!(
                "{} {} not found",
                kind[..1].to_uppercase() + &kind[1..],
                id
            )));
        }
    }
    let mut issue_ids = request.selected_member_issue_ids.clone();
    if let Some(id) = request.checkpoint_issue_id {
        issue_ids.push(id);
    }
    issue_ids.extend(
        request
            .convergence_targets
            .iter()
            .filter(|target| target.node_type == "issue")
            .map(|target| target.id),
    );
    issue_ids.sort_unstable();
    issue_ids.dedup();
    if !issue_ids.is_empty() {
        let row = tx
            .query_one(
                "SELECT count(*)::int FROM issues i JOIN threads t ON t.id=i.thread_id
                 WHERE i.id=ANY($1::int[]) AND t.user_id=$2",
                &[&issue_ids, &user_id],
            )
            .await
            .map_err(db::query_error)?;
        let count: i32 = row.get(0);
        if count != issue_ids.len() as i32 {
            let missing = tx
                .query_opt(
                    "SELECT x.id FROM unnest($1::int[]) x(id)
                     WHERE NOT EXISTS (SELECT 1 FROM issues i JOIN threads t ON t.id=i.thread_id
                                       WHERE i.id=x.id AND t.user_id=$2) LIMIT 1",
                    &[&issue_ids, &user_id],
                )
                .await
                .map_err(db::query_error)?
                .map(|row| row.get::<_, i32>(0))
                .unwrap_or(0);
            return Err(not_found(format!("Issue {missing} not found")));
        }
    }
    let group_ids: Vec<i32> = request
        .convergence_targets
        .iter()
        .filter(|target| target.node_type == "crossover")
        .map(|target| target.id)
        .collect();
    if !group_ids.is_empty() {
        let row = tx
            .query_one(
                "SELECT count(*)::int FROM dependency_groups WHERE id=ANY($1::int[]) AND user_id=$2",
                &[&group_ids, &user_id],
            )
            .await
            .map_err(db::query_error)?;
        let count: i32 = row.get(0);
        if count != group_ids.len() as i32 {
            return Err(not_found(format!("Crossover {} not found", group_ids[0])));
        }
    }
    Ok(())
}

async fn would_create_cycle(
    tx: &Transaction<'_>,
    user_id: i32,
    source_type: &str,
    source_id: i32,
    target_type: &str,
    target_id: i32,
    exclude_rule_id: Option<i32>,
) -> Result<bool, ApiError> {
    if source_type == target_type && source_id == target_id {
        return Ok(true);
    }
    let excluded = exclude_rule_id.unwrap_or(-1);
    let row = tx
        .query_one(
            "WITH RECURSIVE reachable(node_type,node_id) AS (
               SELECT r.target_type, r.target_id FROM continuity_rules r
               WHERE r.user_id=$1 AND r.id<>$6
                 AND ((r.source_type=$2 AND r.source_id=$3)
                  OR COALESCE(r.convergence_targets::jsonb,'[]'::jsonb) @> jsonb_build_array(jsonb_build_object('type',$2::text,'id',$3::int)))
               UNION
               SELECT r.target_type, r.target_id FROM continuity_rules r JOIN reachable n
                 ON r.user_id=$1 AND r.id<>$6
                AND ((r.source_type=n.node_type AND r.source_id=n.node_id)
                  OR COALESCE(r.convergence_targets::jsonb,'[]'::jsonb) @> jsonb_build_array(jsonb_build_object('type',n.node_type,'id',n.node_id)))
             ) SELECT EXISTS(SELECT 1 FROM reachable WHERE node_type=$4 AND node_id=$5)",
            &[&user_id, &target_type, &target_id, &source_type, &source_id, &excluded],
        )
        .await
        .map_err(db::query_error)?;
    Ok(row.get(0))
}

fn response_from_row(row: &Row, selected_member_issue_ids: Vec<i32>) -> ContinuityRuleResponse {
    let targets: Option<String> = row.get(8);
    let convergence_targets = targets
        .and_then(|value| serde_json::from_str::<Value>(&value).ok())
        .and_then(|value| value.as_array().cloned())
        .unwrap_or_default()
        .into_iter()
        .filter_map(|value| {
            Some(ConvergenceTarget {
                node_type: value.get("type")?.as_str()?.to_string(),
                id: value.get("id")?.as_i64()? as i32,
            })
        })
        .collect();
    ContinuityRuleResponse {
        id: row.get(0),
        user_id: row.get(1),
        source_type: row.get(2),
        source_id: row.get(3),
        target_type: row.get(4),
        target_id: row.get(5),
        satisfaction_type: row.get(6),
        checkpoint_issue_id: row.get(7),
        convergence_targets,
        selected_member_issue_ids,
        note: row.get(9),
        created_at: row.get(10),
        updated_at: row.get(11),
    }
}

async fn load_rule(
    tx: &Transaction<'_>,
    user_id: i32,
    rule_id: i32,
) -> Result<Option<ContinuityRuleResponse>, ApiError> {
    let row = tx
        .query_opt(
            "SELECT id,user_id,source_type,source_id,target_type,target_id,satisfaction_type,
                checkpoint_issue_id,convergence_targets::text,note,created_at::text,updated_at::text
         FROM continuity_rules WHERE id=$1 AND user_id=$2",
            &[&rule_id, &user_id],
        )
        .await
        .map_err(db::query_error)?;
    let Some(row) = row else { return Ok(None) };
    let members = tx.query("SELECT issue_id FROM continuity_rule_selected_members WHERE rule_id=$1 ORDER BY issue_id", &[&rule_id])
        .await.map_err(db::query_error)?.into_iter().map(|row| row.get(0)).collect();
    Ok(Some(response_from_row(&row, members)))
}

async fn compile_edges(
    tx: &Transaction<'_>,
    pairs: &[(i32, i32)],
    rule_id: i32,
) -> Result<(), ApiError> {
    if pairs.is_empty() {
        return Ok(());
    }
    let sources: Vec<i32> = pairs.iter().map(|pair| pair.0).collect();
    let targets: Vec<i32> = pairs.iter().map(|pair| pair.1).collect();
    tx.execute(
        "INSERT INTO dependencies (source_issue_id,target_issue_id,note,created_at)
         SELECT * FROM unnest($1::int[],$2::int[],$3::text[],ARRAY(SELECT now() FROM generate_series(1,cardinality($1))))
         ON CONFLICT (source_issue_id,target_issue_id) DO UPDATE SET note=EXCLUDED.note
         WHERE dependencies.note LIKE 'canonical:rule:%' OR dependencies.note LIKE 'canonical:rule-backfill:%'",
        &[&sources, &targets, &vec![format!("{RULE_NOTE_PREFIX}{rule_id}"); pairs.len()]],
    ).await.map_err(db::query_error)?;
    Ok(())
}

async fn retire_edges(
    tx: &Transaction<'_>,
    user_id: i32,
    pairs: &[(i32, i32)],
    exclude_rule_id: i32,
) -> Result<(), ApiError> {
    for (source, target) in pairs {
        let still_used = tx.query_opt(
            "SELECT 1 FROM continuity_rules r
             WHERE r.user_id=$1 AND r.id<>$2 AND (
               (r.satisfaction_type IN ('item_read','checkpoint') AND r.source_type='issue' AND r.target_type='issue' AND COALESCE(r.checkpoint_issue_id,r.source_id)=$3 AND r.target_id=$4)
               OR (r.satisfaction_type='converged' AND r.target_type='issue' AND EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(r.convergence_targets::jsonb,'[]'::jsonb)) t WHERE t->>'type'='issue' AND (t->>'id')::int=$3) AND r.target_id=$4)
             ) LIMIT 1",
            &[&user_id, &exclude_rule_id, &source, &target],
        ).await.map_err(db::query_error)?.is_some();
        if !still_used {
            tx.execute("DELETE FROM dependencies WHERE source_issue_id=$1 AND target_issue_id=$2 AND (note LIKE 'canonical:rule:%' OR note LIKE 'canonical:rule-backfill:%')", &[&source, &target]).await.map_err(db::query_error)?;
        }
    }
    Ok(())
}

async fn insert_members(
    tx: &Transaction<'_>,
    rule_id: i32,
    members: &[i32],
) -> Result<(), ApiError> {
    if members.is_empty() {
        return Ok(());
    }
    tx.execute("INSERT INTO continuity_rule_selected_members (rule_id,issue_id) SELECT $1,x FROM unnest($2::int[]) x", &[&rule_id, &members.to_vec()]).await.map_err(db::query_error)?;
    Ok(())
}

pub async fn list(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<Vec<ContinuityRuleResponse>>, ApiError> {
    let conn = db::checkout(&state).await?;
    let rows = conn.query("SELECT id,user_id,source_type,source_id,target_type,target_id,satisfaction_type,checkpoint_issue_id,convergence_targets::text,note,created_at::text,updated_at::text FROM continuity_rules WHERE user_id=$1 ORDER BY id", &[&user.id()]).await.map_err(db::query_error)?;
    let ids: Vec<i32> = rows.iter().map(|row| row.get(0)).collect();
    let member_rows = if ids.is_empty() {
        Vec::new()
    } else {
        conn.query("SELECT rule_id,issue_id FROM continuity_rule_selected_members WHERE rule_id=ANY($1::int[]) ORDER BY rule_id,issue_id", &[&ids]).await.map_err(db::query_error)?
    };
    let mut members = std::collections::HashMap::<i32, Vec<i32>>::new();
    for row in member_rows {
        members.entry(row.get(0)).or_default().push(row.get(1));
    }
    Ok(Json(
        rows.iter()
            .map(|row| response_from_row(row, members.remove(&row.get(0)).unwrap_or_default()))
            .collect(),
    ))
}

pub async fn get(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(rule_id): Path<i32>,
) -> Result<Json<ContinuityRuleResponse>, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    let response = load_rule(&tx, user.id(), rule_id)
        .await?
        .ok_or_else(|| not_found(format!("Continuity rule {rule_id} not found")))?;
    tx.rollback().await.map_err(db::query_error)?;
    Ok(Json(response))
}

pub async fn create(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(mut request): Json<ContinuityRuleRequest>,
) -> Result<(StatusCode, Json<ContinuityRuleResponse>), ApiError> {
    normalize_request(&mut request);
    validate_request(&request)?;
    require_compilable(&request)?;
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    lock_graph(&tx, user.id()).await?;
    owned_references(&tx, user.id(), &request).await?;
    if would_create_cycle(
        &tx,
        user.id(),
        &request.source_type,
        request.source_id,
        &request.target_type,
        request.target_id,
        None,
    )
    .await?
        || request
            .convergence_targets
            .iter()
            .any(|target| target.node_type == request.target_type && target.id == request.target_id)
        || {
            let mut cycle = false;
            for target in &request.convergence_targets {
                cycle |= would_create_cycle(
                    &tx,
                    user.id(),
                    &target.node_type,
                    target.id,
                    &request.target_type,
                    request.target_id,
                    None,
                )
                .await?;
            }
            cycle
        }
    {
        return Err(conflict("continuity_cycle"));
    }
    let targets = if request.convergence_targets.is_empty() {
        None
    } else {
        Some(
            json!(request
                .convergence_targets
                .iter()
                .map(|target| json!({"type": target.node_type, "id": target.id}))
                .collect::<Vec<_>>())
            .to_string(),
        )
    };
    let row = tx.query_one("INSERT INTO continuity_rules (user_id,source_type,source_id,target_type,target_id,satisfaction_type,checkpoint_issue_id,convergence_targets,note,created_at,updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::text::json,$9,NOW(),NOW()) RETURNING id", &[&user.id(),&request.source_type,&request.source_id,&request.target_type,&request.target_id,&request.satisfaction_type,&request.checkpoint_issue_id,&targets,&request.note]).await.map_err(|error| if error.as_db_error().is_some_and(|e| e.code().code()=="23505") { conflict("continuity_rule_exists") } else { db::query_error(error) })?;
    let rule_id: i32 = row.get(0);
    insert_members(&tx, rule_id, &request.selected_member_issue_ids).await?;
    compile_edges(&tx, &edge_pairs(&request), rule_id).await?;
    refresh_blocked_threads(&tx, user.id()).await?;
    let response = load_rule(&tx, user.id(), rule_id)
        .await?
        .expect("inserted rule");
    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(response)))
}

pub async fn update(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(rule_id): Path<i32>,
    Json(mut request): Json<ContinuityRuleRequest>,
) -> Result<Json<ContinuityRuleResponse>, ApiError> {
    normalize_request(&mut request);
    validate_request(&request)?;
    require_compilable(&request)?;
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    lock_graph(&tx, user.id()).await?;
    let old = load_rule(&tx, user.id(), rule_id)
        .await?
        .ok_or_else(|| not_found(format!("Continuity rule {rule_id} not found")))?;
    owned_references(&tx, user.id(), &request).await?;
    if would_create_cycle(
        &tx,
        user.id(),
        &request.source_type,
        request.source_id,
        &request.target_type,
        request.target_id,
        Some(rule_id),
    )
    .await?
    {
        return Err(conflict("continuity_cycle"));
    }
    for target in &request.convergence_targets {
        if would_create_cycle(
            &tx,
            user.id(),
            &target.node_type,
            target.id,
            &request.target_type,
            request.target_id,
            Some(rule_id),
        )
        .await?
        {
            return Err(conflict("continuity_cycle"));
        }
    }
    let old_request = ContinuityRuleRequest {
        source_type: old.source_type,
        source_id: old.source_id,
        target_type: old.target_type,
        target_id: old.target_id,
        satisfaction_type: old.satisfaction_type,
        checkpoint_issue_id: old.checkpoint_issue_id,
        convergence_targets: old.convergence_targets,
        selected_member_issue_ids: old.selected_member_issue_ids,
        note: old.note,
    };
    let old_pairs = edge_pairs(&old_request);
    let targets = if request.convergence_targets.is_empty() {
        None
    } else {
        Some(
            json!(request
                .convergence_targets
                .iter()
                .map(|target| json!({"type":target.node_type,"id":target.id}))
                .collect::<Vec<_>>())
            .to_string(),
        )
    };
    tx.execute("UPDATE continuity_rules SET source_type=$1,source_id=$2,target_type=$3,target_id=$4,satisfaction_type=$5,checkpoint_issue_id=$6,convergence_targets=$7::text::json,note=$8,updated_at=NOW() WHERE id=$9 AND user_id=$10", &[&request.source_type,&request.source_id,&request.target_type,&request.target_id,&request.satisfaction_type,&request.checkpoint_issue_id,&targets,&request.note,&rule_id,&user.id()]).await.map_err(db::query_error)?;
    tx.execute(
        "DELETE FROM continuity_rule_selected_members WHERE rule_id=$1",
        &[&rule_id],
    )
    .await
    .map_err(db::query_error)?;
    insert_members(&tx, rule_id, &request.selected_member_issue_ids).await?;
    retire_edges(&tx, user.id(), &old_pairs, rule_id).await?;
    compile_edges(&tx, &edge_pairs(&request), rule_id).await?;
    refresh_blocked_threads(&tx, user.id()).await?;
    let response = load_rule(&tx, user.id(), rule_id)
        .await?
        .expect("updated rule");
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(response))
}

pub async fn delete(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(rule_id): Path<i32>,
) -> Result<Response, ApiError> {
    let mut conn = db::checkout(&state).await?;
    let tx = conn
        .build_transaction()
        .start()
        .await
        .map_err(db::query_error)?;
    lock_graph(&tx, user.id()).await?;
    let old = load_rule(&tx, user.id(), rule_id)
        .await?
        .ok_or_else(|| not_found(format!("Continuity rule {rule_id} not found")))?;
    let old_request = ContinuityRuleRequest {
        source_type: old.source_type,
        source_id: old.source_id,
        target_type: old.target_type,
        target_id: old.target_id,
        satisfaction_type: old.satisfaction_type,
        checkpoint_issue_id: old.checkpoint_issue_id,
        convergence_targets: old.convergence_targets,
        selected_member_issue_ids: old.selected_member_issue_ids,
        note: old.note,
    };
    tx.execute(
        "DELETE FROM continuity_rules WHERE id=$1 AND user_id=$2",
        &[&rule_id, &user.id()],
    )
    .await
    .map_err(db::query_error)?;
    retire_edges(&tx, user.id(), &edge_pairs(&old_request), rule_id).await?;
    refresh_blocked_threads(&tx, user.id()).await?;
    tx.commit().await.map_err(db::query_error)?;
    Ok(StatusCode::NO_CONTENT.into_response())
}

#[utoipa::path(get, path="/api/v1/continuity-rules/", tag="continuity", operation_id="continuity_rules_list", responses((status=200, body=Vec<ContinuityRuleResponse>)), security(("HTTPBearer"=[])))]
pub fn list_documentation() {}
#[utoipa::path(post, path="/api/v1/continuity-rules/", tag="continuity", operation_id="continuity_rules_create", request_body=ContinuityRuleRequest, responses((status=201, body=ContinuityRuleResponse)), security(("HTTPBearer"=[])))]
pub fn create_documentation() {}
#[utoipa::path(get, path="/api/v1/continuity-rules/{rule_id}", tag="continuity", operation_id="continuity_rules_get", params(("rule_id"=i32, Path)), responses((status=200, body=ContinuityRuleResponse)), security(("HTTPBearer"=[])))]
pub fn get_documentation() {}
#[utoipa::path(put, path="/api/v1/continuity-rules/{rule_id}", tag="continuity", operation_id="continuity_rules_update", params(("rule_id"=i32, Path)), request_body=ContinuityRuleRequest, responses((status=200, body=ContinuityRuleResponse)), security(("HTTPBearer"=[])))]
pub fn update_documentation() {}
#[utoipa::path(delete, path="/api/v1/continuity-rules/{rule_id}", tag="continuity", operation_id="continuity_rules_delete", params(("rule_id"=i32, Path)), responses((status=204)), security(("HTTPBearer"=[])))]
pub fn delete_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{db, test_support};
    use std::sync::Arc;

    async fn database_fixture() -> (
        Arc<AppState>,
        AuthenticatedUser,
        tokio::sync::MutexGuard<'static, ()>,
    ) {
        let state = test_support::test_state(2)
            .await
            .expect("RUST_ROLL_TEST_DATABASE_URL is required");
        let guard = test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username) VALUES (1001, 'continuity-rules-test');
                 INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status)
                 VALUES (2001, 1001, 'Continuity test', 'Comic', 2, 1, 'active');
                 INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
                 VALUES
                   (3001, 2001, '1', 'unread', NOW(), 1),
                   (3002, 2001, '2', 'unread', NOW(), 2);",
            )
            .await
            .expect("seed continuity rules fixture");
        drop(connection);
        (state, AuthenticatedUser::for_test(1001), guard)
    }

    fn request(satisfaction_type: &str) -> ContinuityRuleRequest {
        ContinuityRuleRequest {
            source_type: "issue".to_string(),
            source_id: 10,
            target_type: "issue".to_string(),
            target_id: 20,
            satisfaction_type: satisfaction_type.to_string(),
            checkpoint_issue_id: None,
            convergence_targets: Vec::new(),
            selected_member_issue_ids: Vec::new(),
            note: None,
        }
    }

    #[tokio::test]
    async fn create_writes_continuity_rule_and_dependency_to_disposable_postgres() {
        let (state, user, _guard) = database_fixture().await;
        let (status, Json(response)) = create(
            State(state),
            user,
            Json(ContinuityRuleRequest {
                source_id: 3001,
                target_id: 3002,
                ..request("item_read")
            }),
        )
        .await
        .expect("create continuity rule");

        assert_eq!(status, StatusCode::CREATED);
        assert_eq!(response.user_id, user.id());
        assert_eq!(response.source_id, 3001);
        assert_eq!(response.target_id, 3002);
    }

    #[tokio::test]
    async fn update_writes_continuity_rule_to_disposable_postgres() {
        let (state, user, _guard) = database_fixture().await;
        let (_, Json(created)) = create(
            State(state.clone()),
            user,
            Json(ContinuityRuleRequest {
                source_id: 3001,
                target_id: 3002,
                ..request("item_read")
            }),
        )
        .await
        .expect("create continuity rule");

        let Json(updated) = update(
            State(state),
            user,
            Path(created.id),
            Json(ContinuityRuleRequest {
                source_id: 3002,
                target_id: 3001,
                note: Some("updated".to_string()),
                ..request("item_read")
            }),
        )
        .await
        .expect("update continuity rule");

        assert_eq!(updated.id, created.id);
        assert_eq!(updated.source_id, 3002);
        assert_eq!(updated.target_id, 3001);
        assert_eq!(updated.note.as_deref(), Some("updated"));
    }

    #[tokio::test]
    async fn delete_removes_continuity_rule_and_dependency_from_disposable_postgres() {
        let (state, user, _guard) = database_fixture().await;
        let (_, Json(created)) = create(
            State(state.clone()),
            user,
            Json(ContinuityRuleRequest {
                source_id: 3001,
                target_id: 3002,
                ..request("item_read")
            }),
        )
        .await
        .expect("create continuity rule");

        let response = delete(State(state.clone()), user, Path(created.id))
            .await
            .expect("delete continuity rule");
        assert_eq!(response.status(), StatusCode::NO_CONTENT);

        let connection = db::checkout(&state).await.expect("verify connection");
        let remaining: i64 = connection
            .query_one(
                "SELECT count(*) FROM continuity_rules WHERE id = $1",
                &[&created.id],
            )
            .await
            .expect("verify rule deletion")
            .get(0);
        assert_eq!(remaining, 0);
    }

    #[test]
    fn canonical_edge_pairs_match_python_compiler_shapes() {
        let mut checkpoint = request("checkpoint");
        checkpoint.checkpoint_issue_id = Some(30);
        assert_eq!(edge_pairs(&checkpoint), vec![(30, 20)]);

        let mut converged = request("converged");
        converged.convergence_targets = vec![
            ConvergenceTarget {
                node_type: "issue".to_string(),
                id: 30,
            },
            ConvergenceTarget {
                node_type: "issue".to_string(),
                id: 20,
            },
        ];
        assert_eq!(edge_pairs(&converged), vec![(30, 20)]);
    }

    #[test]
    fn non_compilable_rule_shapes_are_rejected_before_database_writes() {
        let mut member_rule = request("selected_members_read");
        member_rule.selected_member_issue_ids = vec![30];
        assert!(require_compilable(&member_rule).is_err());

        let mut crossover_rule = request("item_read");
        crossover_rule.target_type = "crossover".to_string();
        assert!(require_compilable(&crossover_rule).is_err());
    }

    #[test]
    fn request_normalization_matches_pydantic_deduplication() {
        let mut input = request("selected_members_read");
        input.selected_member_issue_ids = vec![30, 30, 20];
        input.convergence_targets = vec![
            ConvergenceTarget {
                node_type: "issue".to_string(),
                id: 30,
            },
            ConvergenceTarget {
                node_type: "issue".to_string(),
                id: 30,
            },
        ];
        normalize_request(&mut input);
        assert_eq!(input.selected_member_issue_ids, vec![20, 30]);
        assert_eq!(input.convergence_targets.len(), 1);
    }
}
