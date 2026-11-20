//! Plan-owned continuity rule compilation for Custom CBL apply.
//!
//! Mirrors the subset of Python `replace_compiled_rules` that a Custom CBL
//! apply authors: retained strict `item_read` pairs, explicit checkpoint
//! targets, and convergence gates. Membership is rebuilt from the freshly
//! written plan document, and canonical `dependencies` edges are compiled or
//! retired in the same transaction so Roll eligibility cannot keep blocking on
//! rules that the apply removed.

use crate::{continuity_rules, db, ApiError};
use axum::http::StatusCode;
use deadpool_postgres::Transaction;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet, HashMap};

const CONTINUITY_LOCK_NAMESPACE: i32 = 1_129_274_964;

/// One plan-owned rule to compile, identified exactly as Python does.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct CompiledEdge {
    source_type: String,
    source_id: i32,
    target_type: String,
    target_id: i32,
    satisfaction_type: String,
    checkpoint_issue_id: Option<i32>,
    convergence_targets: Vec<(String, i32)>,
}

fn plan_rule_marker(plan_id: i32) -> String {
    format!("continuity-plan:{plan_id}")
}

/// Canonical `(source_issue_id, target_issue_id)` pairs a rule compiles to.
fn edge_pairs(edge: &CompiledEdge) -> Vec<(i32, i32)> {
    match edge.satisfaction_type.as_str() {
        "item_read" | "checkpoint"
            if edge.source_type == "issue" && edge.target_type == "issue" =>
        {
            vec![(
                edge.checkpoint_issue_id.unwrap_or(edge.source_id),
                edge.target_id,
            )]
        }
        "converged" if edge.target_type == "issue" => edge
            .convergence_targets
            .iter()
            .filter(|(kind, id)| kind == "issue" && *id != edge.target_id)
            .map(|(_, id)| (*id, edge.target_id))
            .collect(),
        _ => Vec::new(),
    }
}

fn parse_convergence_targets(raw: Option<&str>) -> Vec<(String, i32)> {
    let Some(raw) = raw else {
        return Vec::new();
    };
    let Ok(Value::Array(values)) = serde_json::from_str::<Value>(raw) else {
        return Vec::new();
    };
    let mut targets: Vec<(String, i32)> = values
        .iter()
        .filter_map(|value| {
            Some((
                value.get("type")?.as_str()?.to_string(),
                i32::try_from(value.get("id")?.as_i64()?).ok()?,
            ))
        })
        .collect();
    targets.sort();
    targets.dedup();
    targets
}

fn node_type(node: &Value) -> &str {
    node.get("node_type").and_then(Value::as_str).unwrap_or("")
}

fn node_lane(node: &Value) -> &str {
    node.get("lane_id").and_then(Value::as_str).unwrap_or("")
}

fn node_ref(node: &Value) -> Option<i32> {
    node.get("ref_id")
        .and_then(Value::as_i64)
        .and_then(|value| i32::try_from(value).ok())
}

fn node_position(node: &Value) -> i32 {
    node.get("position").and_then(Value::as_i64).unwrap_or(0) as i32
}

fn node_key(node: &Value) -> Option<&str> {
    node.get("id").and_then(Value::as_str)
}

/// Checkpoint edges authored on nodes, matching `_checkpoint_edges_from_nodes`.
///
/// An explicit target blocks only that issue. A legacy flag without a target
/// blocks the next node in the same lane. Consecutive positions without an
/// explicit checkpoint never become blockers.
fn checkpoint_edges(nodes: &[Value]) -> Vec<CompiledEdge> {
    let mut by_lane: BTreeMap<&str, Vec<&Value>> = BTreeMap::new();
    for node in nodes {
        by_lane.entry(node_lane(node)).or_default().push(node);
    }
    for lane in by_lane.values_mut() {
        lane.sort_by_key(|node| (node_position(node), node_ref(node).unwrap_or(0)));
    }
    let by_issue: BTreeMap<i32, &Value> = nodes
        .iter()
        .filter(|node| node_type(node) == "issue")
        .filter_map(|node| node_ref(node).map(|id| (id, node)))
        .collect();

    let mut edges = Vec::new();
    for node in nodes {
        if !node
            .get("is_checkpoint")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            continue;
        }
        let Some(source_id) = node_ref(node) else {
            continue;
        };
        let source_type = node_type(node).to_string();
        let checkpoint_issue_id = if source_type == "issue" {
            Some(source_id)
        } else {
            None
        };

        let mut targets: BTreeSet<i32> = BTreeSet::new();
        if let Some(values) = node
            .get("checkpoint_target_ref_ids")
            .and_then(Value::as_array)
        {
            for value in values {
                if let Some(id) = value.as_i64().and_then(|v| i32::try_from(v).ok()) {
                    targets.insert(id);
                }
            }
        }
        if let Some(id) = node
            .get("checkpoint_target_ref_id")
            .and_then(Value::as_i64)
            .and_then(|v| i32::try_from(v).ok())
        {
            targets.insert(id);
        }

        if !targets.is_empty() {
            for target_id in targets {
                let Some(target) = by_issue.get(&target_id) else {
                    continue;
                };
                if target_id == source_id {
                    continue;
                }
                edges.push(CompiledEdge {
                    source_type: source_type.clone(),
                    source_id,
                    target_type: node_type(target).to_string(),
                    target_id,
                    satisfaction_type: "checkpoint".to_string(),
                    checkpoint_issue_id,
                    convergence_targets: Vec::new(),
                });
            }
            continue;
        }

        let lane = by_lane.get(node_lane(node)).cloned().unwrap_or_default();
        let key = node_key(node);
        let Some(index) = lane
            .iter()
            .position(|candidate| node_key(candidate) == key && key.is_some())
        else {
            continue;
        };
        let Some(next) = lane.get(index + 1) else {
            continue;
        };
        let next_id = node_ref(next);
        if node_type(next) == source_type && next_id == Some(source_id) {
            continue;
        }
        let Some(target_id) = next_id else {
            continue;
        };
        edges.push(CompiledEdge {
            source_type,
            source_id,
            target_type: node_type(next).to_string(),
            target_id,
            satisfaction_type: "checkpoint".to_string(),
            checkpoint_issue_id,
            convergence_targets: Vec::new(),
        });
    }
    edges
}

/// Convergence edges authored on nodes, filtering retired same-series chain
/// gates exactly like Python's `is_retired_list_chain_pair` guard.
fn convergence_edges(nodes: &[Value], issue_index: &HashMap<i32, (i32, i32)>) -> Vec<CompiledEdge> {
    let by_key: BTreeMap<&str, &Value> = nodes
        .iter()
        .filter_map(|node| node_key(node).map(|key| (key, node)))
        .collect();
    let mut edges = Vec::new();
    for node in nodes {
        let Some(gate) = node.get("convergence_gate").and_then(Value::as_array) else {
            continue;
        };
        if gate.is_empty() {
            continue;
        }
        let Some(source_id) = node_ref(node) else {
            continue;
        };
        let source_type = node_type(node).to_string();
        let mut targets: Vec<(String, i32)> = Vec::new();
        for entry in gate {
            let Some(reference) = entry.get("node_id").and_then(Value::as_str) else {
                continue;
            };
            let Some(resolved) = by_key.get(reference) else {
                continue;
            };
            let Some(target_id) = node_ref(resolved) else {
                continue;
            };
            // Python checks `is_retired_list_chain_pair(prereq_meta,
            // node_meta)`: the gate target is the prerequisite and the
            // convergence node is the blocked target. A gate that only
            // restates "read my own series predecessor first" is not a hard
            // dependency (docs/roll-eligibility-contract.md).
            if let (
                Some((prerequisite_thread, prerequisite_position)),
                Some((blocked_thread, blocked_position)),
            ) = (issue_index.get(&target_id), issue_index.get(&source_id))
            {
                if prerequisite_thread == blocked_thread
                    && *blocked_position == *prerequisite_position + 1
                {
                    continue;
                }
            }
            targets.push((node_type(resolved).to_string(), target_id));
        }
        if targets.is_empty() {
            continue;
        }
        targets.sort();
        targets.dedup();
        edges.push(CompiledEdge {
            source_type: source_type.clone(),
            source_id,
            target_type: source_type,
            target_id: source_id,
            satisfaction_type: "converged".to_string(),
            checkpoint_issue_id: None,
            convergence_targets: targets,
        });
    }
    edges
}

fn conflict(code: &str, extra: serde_json::Map<String, Value>) -> ApiError {
    let mut detail = serde_json::Map::new();
    detail.insert("code".to_string(), Value::String(code.to_string()));
    detail.extend(extra);
    ApiError::structured(StatusCode::CONFLICT, Value::Object(detail))
}

/// Replace only the plan-owned compiled rules for `plan_id`, then reconcile
/// canonical dependency edges and the membership overlay in one transaction.
pub(crate) async fn replace_compiled_rules(
    tx: &Transaction<'_>,
    user_id: i32,
    plan_id: i32,
    nodes: &[Value],
    ordering_mode: &str,
) -> Result<(), ApiError> {
    let marker = plan_rule_marker(plan_id);
    tx.execute(
        "SELECT pg_advisory_xact_lock($1, $2)",
        &[&CONTINUITY_LOCK_NAMESPACE, &user_id],
    )
    .await
    .map_err(db::query_error)?;

    let old_rows = tx
        .query(
            "SELECT source_type,source_id,target_type,target_id,satisfaction_type,
                    checkpoint_issue_id,convergence_targets::text
             FROM continuity_rules WHERE user_id=$1 AND note=$2",
            &[&user_id, &marker],
        )
        .await
        .map_err(db::query_error)?;
    let mut old_pairs: BTreeSet<(i32, i32)> = BTreeSet::new();
    let mut prior_item_read: BTreeSet<(i32, i32)> = BTreeSet::new();
    for row in &old_rows {
        let edge = CompiledEdge {
            source_type: row.get(0),
            source_id: row.get(1),
            target_type: row.get(2),
            target_id: row.get(3),
            satisfaction_type: row.get(4),
            checkpoint_issue_id: row.get(5),
            convergence_targets: parse_convergence_targets(
                row.get::<_, Option<String>>(6).as_deref(),
            ),
        };
        old_pairs.extend(edge_pairs(&edge));
        if edge.satisfaction_type == "item_read"
            && edge.source_type == "issue"
            && edge.target_type == "issue"
        {
            prior_item_read.insert((edge.source_id, edge.target_id));
        }
    }

    let incoming_ids: BTreeSet<i32> = nodes
        .iter()
        .filter(|node| node_type(node) == "issue")
        .filter_map(node_ref)
        .collect();

    let mut edges: Vec<CompiledEdge> = Vec::new();
    if ordering_mode == "strict_sequential" {
        for (source, target) in &prior_item_read {
            if incoming_ids.contains(source) && incoming_ids.contains(target) {
                edges.push(CompiledEdge {
                    source_type: "issue".to_string(),
                    source_id: *source,
                    target_type: "issue".to_string(),
                    target_id: *target,
                    satisfaction_type: "item_read".to_string(),
                    checkpoint_issue_id: None,
                    convergence_targets: Vec::new(),
                });
            }
        }
    }
    edges.extend(checkpoint_edges(nodes));

    let mut issue_index: HashMap<i32, (i32, i32)> = HashMap::new();
    if nodes.iter().any(|node| {
        node.get("convergence_gate")
            .and_then(Value::as_array)
            .is_some_and(|gate| !gate.is_empty())
    }) {
        let ids: Vec<i32> = incoming_ids.iter().copied().collect();
        let rows = tx
            .query(
                "SELECT i.id, i.thread_id, i.position FROM issues i
                 JOIN threads t ON t.id=i.thread_id WHERE t.user_id=$1 AND i.id=ANY($2)",
                &[&user_id, &ids],
            )
            .await
            .map_err(db::query_error)?;
        for row in &rows {
            issue_index.insert(row.get(0), (row.get(1), row.get(2)));
        }
    }
    edges.extend(convergence_edges(nodes, &issue_index));

    // Membership is authoritative and must reflect the just-written document
    // even when no rules compile. Rebuilding here keeps it inside the same
    // transaction so a later rule conflict rolls the whole apply back.
    crate::reading_plan_sync::rebuild_plan_issues_from_nodes_json(tx, plan_id).await?;

    tx.execute(
        "DELETE FROM continuity_rules WHERE user_id=$1 AND note=$2",
        &[&user_id, &marker],
    )
    .await
    .map_err(db::query_error)?;

    let mut new_pairs: BTreeSet<(i32, i32)> = BTreeSet::new();
    for edge in &edges {
        let existing = tx
            .query_opt(
                "SELECT id,note,satisfaction_type FROM continuity_rules
                 WHERE user_id=$1 AND source_type=$2 AND source_id=$3
                   AND target_type=$4 AND target_id=$5 LIMIT 1",
                &[
                    &user_id,
                    &edge.source_type,
                    &edge.source_id,
                    &edge.target_type,
                    &edge.target_id,
                ],
            )
            .await
            .map_err(db::query_error)?;
        let pairs = edge_pairs(edge);
        if let Some(row) = existing {
            let note: String = row.get(1);
            if note == marker {
                continue;
            }
            let satisfaction: String = row.get(2);
            if edge.satisfaction_type == "item_read" && satisfaction == "item_read" {
                let rule_id: i32 = row.get(0);
                continuity_rules::compile_edges(tx, &pairs, rule_id).await?;
                new_pairs.extend(pairs);
                continue;
            }
            return Err(conflict(
                "plan_rule_conflict",
                serde_json::Map::from_iter([
                    (
                        "source_node_id".to_string(),
                        Value::String(format!("{}-{}", edge.source_type, edge.source_id)),
                    ),
                    (
                        "target_node_id".to_string(),
                        Value::String(format!("{}-{}", edge.target_type, edge.target_id)),
                    ),
                ]),
            ));
        }

        if edge.satisfaction_type != "converged"
            && continuity_rules::would_create_cycle(
                tx,
                user_id,
                &edge.source_type,
                edge.source_id,
                &edge.target_type,
                edge.target_id,
                None,
            )
            .await?
        {
            return Err(conflict(
                "continuity_cycle",
                serde_json::Map::from_iter([
                    (
                        "source_node_id".to_string(),
                        Value::String(format!("{}-{}", edge.source_type, edge.source_id)),
                    ),
                    (
                        "target_node_id".to_string(),
                        Value::String(format!("{}-{}", edge.target_type, edge.target_id)),
                    ),
                ]),
            ));
        }

        let targets = if edge.convergence_targets.is_empty() {
            None
        } else {
            Some(
                json!(edge
                    .convergence_targets
                    .iter()
                    .map(|(kind, id)| json!({"type": kind, "id": id}))
                    .collect::<Vec<_>>())
                .to_string(),
            )
        };
        let row = tx
            .query_one(
                "INSERT INTO continuity_rules
                 (user_id,source_type,source_id,target_type,target_id,satisfaction_type,
                  checkpoint_issue_id,convergence_targets,note,created_at,updated_at)
                 VALUES ($1,$2,$3,$4,$5,$6,$7,$8::text::json,$9,NOW(),NOW()) RETURNING id",
                &[
                    &user_id,
                    &edge.source_type,
                    &edge.source_id,
                    &edge.target_type,
                    &edge.target_id,
                    &edge.satisfaction_type,
                    &edge.checkpoint_issue_id,
                    &targets,
                    &marker,
                ],
            )
            .await
            .map_err(db::query_error)?;
        let rule_id: i32 = row.get(0);
        continuity_rules::compile_edges(tx, &pairs, rule_id).await?;
        new_pairs.extend(pairs);
    }

    let stale: Vec<(i32, i32)> = old_pairs.difference(&new_pairs).copied().collect();
    continuity_rules::retire_edges(tx, user_id, &stale, -1).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn issue(id: i32, lane: &str, position: i32, checkpoint: bool) -> Value {
        json!({
            "id": format!("node-{id}"),
            "node_type": "issue",
            "ref_id": id,
            "lane_id": lane,
            "position": position,
            "is_checkpoint": checkpoint,
            "convergence_gate": [],
        })
    }

    #[test]
    fn checkpoint_without_target_blocks_next_node_in_lane() {
        let nodes = vec![issue(1, "lane", 0, true), issue(2, "lane", 1, false)];
        let edges = checkpoint_edges(&nodes);
        assert_eq!(edges.len(), 1);
        assert_eq!(edges[0].source_id, 1);
        assert_eq!(edges[0].target_id, 2);
        assert_eq!(edges[0].satisfaction_type, "checkpoint");
        assert_eq!(edges[0].checkpoint_issue_id, Some(1));
        assert_eq!(edge_pairs(&edges[0]), vec![(1, 2)]);
    }

    #[test]
    fn checkpoint_explicit_target_blocks_only_that_issue() {
        let mut nodes = vec![issue(1, "lane", 0, true), issue(2, "lane", 1, false)];
        nodes[0]["checkpoint_target_ref_ids"] = json!([2]);
        let edges = checkpoint_edges(&nodes);
        assert_eq!(edges.len(), 1);
        assert_eq!((edges[0].source_id, edges[0].target_id), (1, 2));
    }

    #[test]
    fn last_member_checkpoint_compiles_no_edge() {
        let nodes = vec![issue(1, "lane", 0, true)];
        assert!(checkpoint_edges(&nodes).is_empty());
    }

    #[test]
    fn convergence_drops_retired_same_series_chain_gate() {
        let mut blocker = issue(1, "lane", 0, false);
        blocker["id"] = json!("blocker");
        let mut blocked = issue(2, "lane", 1, false);
        blocked["id"] = json!("blocked");
        blocked["convergence_gate"] = json!([{"node_id": "blocker"}]);
        let nodes = vec![blocker, blocked];
        let index = HashMap::from([(1, (8, 1)), (2, (8, 2))]);
        assert!(convergence_edges(&nodes, &index).is_empty());

        let cross_series = HashMap::from([(1, (8, 1)), (2, (9, 2))]);
        let edges = convergence_edges(&nodes, &cross_series);
        assert_eq!(edges.len(), 1);
        assert_eq!(edges[0].satisfaction_type, "converged");
        assert_eq!(edges[0].convergence_targets, vec![("issue".to_string(), 1)]);
        assert_eq!(edge_pairs(&edges[0]), vec![(1, 2)]);
    }
}
