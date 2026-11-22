//! Canonical continuity-plan reader.
//!
//! A linked custom Reading List is the sole authority for effective Option E order.
//! Historic plan membership and provenance are never projected as authority.
//! Reads share the exact Rust Reading List evaluation used by Roll and Queue.
//!
//! Plans that never had an authoritative Reading List open as editable legacy
//! plans, including after issues are authored into them. A plan whose owned
//! List link was removed still requires explicit owner recovery.

use crate::{auth::AuthenticatedUser, db, reading_list, ApiError, AppState};
use axum::{
    extract::{Path, State},
    Json,
};
use serde::Serialize;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct PlanReaderBlocker {
    pub issue_id: i32,
    pub thread_id: i32,
    pub thread_title: String,
    pub issue_number: String,
    pub explanation: String,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct PlanReaderIssue {
    pub occurrence_id: String,
    pub issue_id: i32,
    pub lane_id: String,
    pub display_position: i32,
    pub issue_number: String,
    pub thread_id: i32,
    pub thread_title: String,
    pub status: String,
    pub is_checkpoint: bool,
    pub availability: String,
    pub blockers: Vec<PlanReaderBlocker>,
    pub source_paths: Vec<String>,
}

#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct PlanReaderLane {
    pub id: String,
    pub name: String,
    pub order: i32,
    pub issues: Vec<PlanReaderIssue>,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct PlanReaderProgress {
    pub total_issues: usize,
    pub read_issues: usize,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct PlanReaderSource {
    pub id: i32,
    pub raw_source_path: String,
    pub display_name: Option<String>,
    pub repository: Option<String>,
    pub source_path: Option<String>,
    pub revision_sha: Option<String>,
    pub content_hash: Option<String>,
    pub adopted_at: Option<String>,
    pub recorded_at: String,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct PlanReleaseSourceStatus {
    pub source_id: i32,
    pub thread_id: i32,
    pub external_identity_id: i32,
    pub provider_volume_id: String,
    pub provider_title: Option<String>,
    pub provider_publisher: Option<String>,
    pub provider_start_year: Option<i32>,
    pub provider_issue_count: Option<i32>,
    pub enabled: bool,
    pub last_synced_at: Option<String>,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct PlanReleaseCandidate {
    pub thread_id: i32,
    pub thread_title: String,
    pub mapping_state: String,
    pub external_identity_id: Option<i32>,
    pub provider_volume_id: Option<String>,
    pub provider_title: Option<String>,
    pub provider_publisher: Option<String>,
    pub provider_start_year: Option<i32>,
    pub provider_issue_count: Option<i32>,
    pub mapping_status: Option<String>,
    pub enableable: bool,
    pub followed: bool,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct PlanReaderResponse {
    pub execution_mode: String,
    pub plan_id: i32,
    pub name: String,
    pub ordering_mode: String,
    pub progress: PlanReaderProgress,
    pub available_now: Vec<PlanReaderIssue>,
    pub blocked_next: Vec<PlanReaderIssue>,
    pub lanes: Vec<PlanReaderLane>,
    pub sources: Vec<PlanReaderSource>,
    pub release_sources: Vec<PlanReleaseSourceStatus>,
    pub release_candidates: Vec<PlanReleaseCandidate>,
}

fn str_meta(meta: &Value, key: &str) -> Option<String> {
    meta.get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}
fn number_meta(meta: &Value, keys: &[&str]) -> Option<i32> {
    keys.iter()
        .find_map(|key| {
            meta.get(*key).and_then(|value| {
                value
                    .as_i64()
                    .or_else(|| value.as_str().and_then(|s| s.trim().parse().ok()))
            })
        })
        .and_then(|number| i32::try_from(number).ok())
}
fn display_meta(meta: &Value) -> (Option<String>, Option<String>, Option<i32>, Option<i32>) {
    let title = str_meta(meta, "name").or_else(|| str_meta(meta, "title"));
    let publisher = str_meta(meta, "publisher")
        .or_else(|| meta.get("publisher").and_then(|p| str_meta(p, "name")));
    let year = number_meta(meta, &["start_year"]);
    let count = number_meta(meta, &["count_of_issues", "issue_count"]);
    (title, publisher, year, count)
}
fn parse_meta(raw: &str) -> Value {
    serde_json::from_str(raw).unwrap_or(Value::Null)
}

/// GET /api/v2/continuity-plans/{plan_id}/reader
pub async fn read(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(plan_id): Path<i32>,
) -> Result<Json<PlanReaderResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    let plan = conn
        .query_opt(
            "SELECT p.name, p.ordering_mode, p.lanes_json::text
             FROM continuity_plans p WHERE p.id=$1 AND p.user_id=$2",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Reading Plan not found".to_string()))?;
    let plan_name: String = plan.get(0);
    let plan_ordering_mode: String = plan.get(1);
    let plan_lanes_json: String = plan.get(2);

    let source_rows = conn
        .query(
            "SELECT s.id,s.raw_source_path,s.repository,s.source_path,s.revision_sha,
                s.content_hash,s.adopted_at::text,s.recorded_at::text,
                s.custom_cbl_list_id,l.name
         FROM reading_plan_sources s
         LEFT JOIN custom_cbl_lists l ON l.id=s.custom_cbl_list_id AND l.user_id=$2
         WHERE s.plan_id=$1 ORDER BY s.id",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let mut source_list_ids = BTreeSet::new();
    // An owned Reading List is recorded as `custom-cbl:<id>`. When that List is
    // deleted the FK sets custom_cbl_list_id to NULL but the raw path survives,
    // so this marker distinguishes a plan that once had an authority (recovery)
    // from an authored plan that never had one (editable legacy mode).
    let mut had_authoritative_list_source = false;
    let mut sources = Vec::new();
    for row in source_rows {
        let raw_source_path: String = row.get(1);
        let link: Option<i32> = row.get(8);
        if raw_source_path.starts_with("custom-cbl:") || link.is_some() {
            had_authoritative_list_source = true;
        }
        let resolved: Option<String> = row.get(9);
        if let (Some(id), Some(_)) = (link, resolved.as_ref()) {
            source_list_ids.insert(id);
        }
        sources.push(PlanReaderSource {
            id: row.get(0),
            raw_source_path,
            repository: row.get(2),
            source_path: row.get(3),
            revision_sha: row.get(4),
            content_hash: row.get(5),
            adopted_at: row.get(6),
            recorded_at: row.get(7),
            display_name: resolved,
        });
    }
    let mut source_ids = source_list_ids.iter().copied();
    let (Some(list_id), None) = (source_ids.next(), source_ids.next()) else {
        if !source_list_ids.is_empty() {
            return Err(ApiError::Conflict(
                "Ambiguous Reading List association. No Plan membership was changed.".to_string(),
            ));
        }
        if had_authoritative_list_source {
            return Err(ApiError::Conflict(
                "Reading Plan has no linked authoritative Reading List. Open recovery to relink."
                    .to_string(),
            ));
        }

        // This plan never recorded an owned Reading List. It is authored state,
        // so keep it open and editable even after issues are saved into it.
        // Retained membership is shown as a reference with no hard blockers:
        // only a real Reading List drives availability in Option E.
        let retained = conn
            .query(
                "SELECT r.occurrence_id, r.issue_id, r.lane_id, r.display_position,
                        r.is_checkpoint, COALESCE(i.issue_number::text, '#' || r.issue_id::text),
                        COALESCE(i.status::text, 'unread'), COALESCE(t.id, 0),
                        COALESCE(t.title, 'Unknown series')
                 FROM reading_plan_issues r
                 LEFT JOIN issues i ON i.id = r.issue_id
                 LEFT JOIN threads t ON t.id = i.thread_id AND t.user_id = $2
                 WHERE r.plan_id = $1
                 ORDER BY r.lane_id, r.display_position, r.occurrence_id",
                &[&plan_id, &user.id()],
            )
            .await
            .map_err(db::query_error)?;
        let placements = conn
            .query(
                "SELECT sp.occurrence_id, s.raw_source_path
                 FROM reading_plan_source_placements sp
                 JOIN reading_plan_sources s ON s.id = sp.plan_source_id
                 WHERE sp.plan_id = $1
                 ORDER BY sp.occurrence_id, sp.source_position NULLS LAST, s.id",
                &[&plan_id],
            )
            .await
            .map_err(db::query_error)?;
        let mut source_paths: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for row in &placements {
            let occurrence: String = row.get(0);
            source_paths.entry(occurrence).or_default().push(row.get(1));
        }
        let steps: Vec<PlanReaderIssue> = retained
            .iter()
            .map(|row| {
                let occurrence: String = row.get(0);
                let status: String = row.get(6);
                PlanReaderIssue {
                    occurrence_id: occurrence.clone(),
                    issue_id: row.get(1),
                    lane_id: row.get(2),
                    display_position: row.get(3),
                    issue_number: row.get(5),
                    thread_id: row.get(7),
                    thread_title: row.get(8),
                    status: status.clone(),
                    is_checkpoint: row.get(4),
                    availability: if status == "read" { "read" } else { "later" }.to_string(),
                    blockers: Vec::new(),
                    source_paths: source_paths.get(&occurrence).cloned().unwrap_or_default(),
                }
            })
            .collect();
        let total_issues = steps.len();
        let read_issues = steps.iter().filter(|step| step.status == "read").count();
        let mut by_lane: BTreeMap<String, Vec<PlanReaderIssue>> = BTreeMap::new();
        for step in steps {
            by_lane.entry(step.lane_id.clone()).or_default().push(step);
        }
        let mut lane_meta: Vec<(String, String, i32)> =
            serde_json::from_str::<Vec<serde_json::Value>>(&plan_lanes_json)
                .unwrap_or_default()
                .iter()
                .filter_map(|value| {
                    Some((
                        value.get("id")?.as_str()?.to_string(),
                        value
                            .get("name")
                            .and_then(|name| name.as_str())
                            .unwrap_or_default()
                            .to_string(),
                        i32::try_from(
                            value
                                .get("order")
                                .and_then(|order| order.as_i64())
                                .unwrap_or(0),
                        )
                        .unwrap_or(0),
                    ))
                })
                .collect();
        lane_meta.sort_by_key(|(_, _, order)| *order);
        let mut lanes = Vec::new();
        for (id, name, order) in lane_meta {
            if let Some(issues) = by_lane.remove(&id) {
                lanes.push(PlanReaderLane {
                    id,
                    name,
                    order,
                    issues,
                });
            }
        }
        for (id, issues) in by_lane {
            lanes.push(PlanReaderLane {
                id: id.clone(),
                name: id,
                order: i32::MAX,
                issues,
            });
        }

        drop(conn);
        return Ok(Json(PlanReaderResponse {
            execution_mode: "legacy".to_string(),
            plan_id,
            name: plan_name,
            ordering_mode: plan_ordering_mode,
            progress: PlanReaderProgress {
                total_issues,
                read_issues,
            },
            available_now: Vec::new(),
            blocked_next: Vec::new(),
            lanes,
            sources,
            release_sources: Vec::new(),
            release_candidates: Vec::new(),
        }));
    };
    drop(conn);

    // The list reader is the actual authoritative Option E read evaluator.
    // Never run an independent projection that can diverge from Roll/Queue.
    let list = reading_list::read_reading_list(State(state.clone()), user, Path(list_id))
        .await?
        .0;
    let path = format!("custom-cbl:{list_id}");
    let mut steps = Vec::new();
    for entry in list.entries {
        let blockers = entry
            .explanation
            .as_ref()
            .map_or_else(Vec::new, |explanation| {
                explanation
                    .blocking_dependencies
                    .iter()
                    .filter_map(|dep| {
                        dep.issue_id.map(|issue_id| PlanReaderBlocker {
                            issue_id,
                            thread_id: dep.thread_id,
                            thread_title: dep.thread_title.clone(),
                            issue_number: dep.issue_number.clone(),
                            explanation: dep.label.clone(),
                        })
                    })
                    .collect()
            });
        steps.push(PlanReaderIssue {
            occurrence_id: format!("reading-list:{list_id}:{}", entry.issue_id),
            issue_id: entry.issue_id,
            lane_id: "reading-list".to_string(),
            display_position: entry.position,
            issue_number: entry.issue_number,
            thread_id: entry.thread_id,
            thread_title: entry.series_name,
            status: entry.status,
            is_checkpoint: entry.is_checkpoint,
            availability: entry.availability,
            blockers,
            source_paths: vec![path.clone()],
        });
    }

    let conn = db::checkout(&state).await?;
    let follow_rows = conn
        .query(
            "SELECT r.id,r.thread_id,r.external_identity_id,e.external_id,
                e.metadata_json::text,r.enabled,r.last_synced_at::text
         FROM reading_plan_release_sources r
         JOIN external_identities e ON e.id=r.external_identity_id
         WHERE r.plan_id=$1 ORDER BY r.created_at,r.id",
            &[&plan_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut release_sources = Vec::new();
    for row in follow_rows {
        let raw: String = row.get(4);
        let (title, publisher, year, count) = display_meta(&parse_meta(&raw));
        release_sources.push(PlanReleaseSourceStatus {
            source_id: row.get(0),
            thread_id: row.get(1),
            external_identity_id: row.get(2),
            provider_volume_id: row.get(3),
            provider_title: title,
            provider_publisher: publisher,
            provider_start_year: year,
            provider_issue_count: count,
            enabled: row.get(5),
            last_synced_at: row.get(6),
        });
    }
    let candidate_rows = conn
        .query(
            "WITH plan_threads AS (
             SELECT DISTINCT i.thread_id
             FROM reading_plan_issues r JOIN issues i ON i.id=r.issue_id
             WHERE r.plan_id=$1
             UNION
             SELECT (n->>'ref_id')::int FROM continuity_plans p
             CROSS JOIN LATERAL jsonb_array_elements(p.nodes_json::jsonb) n
             WHERE p.id=$1 AND p.user_id=$2 AND n->>'node_type'='thread'
         )
         SELECT t.id,t.title,m.status,e.id,e.external_id,e.metadata_json::text,
                EXISTS(SELECT 1 FROM reading_plan_release_sources r
                       WHERE r.plan_id=$1 AND r.thread_id=t.id
                         AND r.external_identity_id=e.id)
         FROM plan_threads pt
         JOIN threads t ON t.id=pt.thread_id AND t.user_id=$2
         LEFT JOIN thread_external_series_mappings m ON m.thread_id=t.id
             AND m.status != 'rejected'
         LEFT JOIN external_identities e ON e.id=m.external_identity_id
             AND e.provider='comicvine' AND e.entity_type='series'
         WHERE m.id IS NULL OR e.id IS NOT NULL
         ORDER BY t.id,m.id",
            &[&plan_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let mut candidates = Vec::new();
    let confirmed_threads: BTreeSet<i32> = candidate_rows
        .iter()
        .filter(|row| row.get::<_, Option<String>>(2).as_deref() == Some("confirmed"))
        .map(|row| row.get(0))
        .collect();
    for row in candidate_rows {
        let thread_id: i32 = row.get(0);
        let title: String = row.get(1);
        let status: Option<String> = row.get(2);
        let identity: Option<i32> = row.get(3);
        let external: Option<String> = row.get(4);
        let metadata: Option<String> = row.get(5);
        let followed: bool = row.get(6);
        if confirmed_threads.contains(&thread_id) && status.as_deref() != Some("confirmed") {
            continue;
        }
        if followed && status.as_deref() == Some("confirmed") {
            continue;
        }
        let (provider_title, provider_publisher, provider_start_year, provider_issue_count) =
            display_meta(&parse_meta(metadata.as_deref().unwrap_or("null")));
        let mapping_state = if status.as_deref() == Some("confirmed") {
            "confirmed"
        } else if status.is_none() {
            "unmapped"
        } else {
            "ambiguous"
        };
        candidates.push(PlanReleaseCandidate {
            thread_id,
            thread_title: title,
            mapping_state: mapping_state.to_string(),
            external_identity_id: identity,
            provider_volume_id: external,
            provider_title,
            provider_publisher,
            provider_start_year,
            provider_issue_count,
            mapping_status: status,
            enableable: mapping_state == "confirmed" && !followed,
            followed,
        });
    }

    let progress = PlanReaderProgress {
        total_issues: steps.len(),
        read_issues: steps.iter().filter(|step| step.status == "read").count(),
    };
    let available_now = steps
        .iter()
        .filter(|step| step.availability == "available")
        .cloned()
        .collect();
    let blocked_next = steps
        .iter()
        .filter(|step| step.availability == "blocked")
        .cloned()
        .collect();
    Ok(Json(PlanReaderResponse {
        execution_mode: "option_e".to_string(),
        plan_id,
        name: plan_name,
        // The order mode is the plan's explicit saved intent, also shown by the
        // plans index and the planner editor. Deriving it from the linked List's
        // mode here silently downgraded a saved `strict_sequential` plan to
        // `informational` whenever the List was loose or stale (#4724). The
        // List remains the sole authority for the *effective* execution
        // (availability, blockers and explanations come from the shared Rust
        // Reading List evaluator above), not for this display field.
        ordering_mode: plan_ordering_mode,
        progress,
        available_now,
        blocked_next,
        lanes: vec![PlanReaderLane {
            id: "reading-list".to_string(),
            name: "Reading order".to_string(),
            order: 0,
            issues: steps,
        }],
        sources,
        release_sources,
        release_candidates: candidates,
    }))
}

#[utoipa::path(
    get,
    path = "/api/v2/continuity-plans/{plan_id}/reader",
    tag = "continuity-plans",
    params(("plan_id" = i32, Path, description = "Owned Reading Plan identifier")),
    responses(
        (status = 200, description = "Option E plan projected from its authoritative Reading List", body = PlanReaderResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Reading Plan not found"),
        (status = 409, description = "Plan missing its authoritative Reading List")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn read_documentation() {}
