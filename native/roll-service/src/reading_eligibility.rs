//! Option E eligibility evaluation for native Rust.
//! Mirrors Python's reading_list_evaluator.evaluate() function.

use crate::reading_constraints::{
    Blocker, ConstraintEdge, ThreadEligibility, ValidatedReadingInputs, ValidationError,
};
use std::collections::{BTreeMap, HashMap, HashSet};

/// Evaluate the complete reading constraint graph and produce thread eligibility.
/// Mirrors Python's reading_list_evaluator.evaluate().
pub fn evaluate(
    validated: &ValidatedReadingInputs,
) -> Result<HashMap<i32, ThreadEligibility>, crate::ApiError> {
    let inputs = validated.inputs();
    let _topological_order = validated.topological_order();

    // Build issue -> thread mapping
    let issue_thread: HashMap<i32, i32> = inputs
        .core
        .issues
        .iter()
        .map(|i| (i.id, i.thread_id))
        .collect();

    // Build thread -> issues in position order
    let mut thread_issues: BTreeMap<i32, Vec<(i32, i32)>> = BTreeMap::new();
    for issue in &inputs.core.issues {
        thread_issues
            .entry(issue.thread_id)
            .or_default()
            .push((issue.position, issue.id));
    }
    for issues in thread_issues.values_mut() {
        issues.sort_unstable();
    }

    // Build adjacency for topological processing
    let mut incoming: HashMap<i32, Vec<ConstraintEdge>> = HashMap::new();
    let edges = validated.unsatisfied_edges().map_err(|e| match e {
        ValidationError::InvalidSnapshot { message } => crate::ApiError(
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            Box::leak(message.into_boxed_str()),
        ),
        ValidationError::Cycle {
            message: _,
            edges: _,
        } => crate::ApiError(
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            "Reading constraint cycle",
        ),
    })?;

    for edge in edges {
        incoming.entry(edge.target_issue_id).or_default().push(edge);
    }

    // Determine read status and excluded status
    let read_issues: HashSet<i32> = inputs
        .core
        .issues
        .iter()
        .filter(|i| i.status == "read" || inputs.excluded_issue_ids.contains(&i.id))
        .map(|i| i.id)
        .collect();

    // Process in topological order to find first unread issue per thread
    let mut next_unread: HashMap<i32, i32> = HashMap::new();
    let mut issue_satisfied: HashMap<i32, bool> = HashMap::new();

    for &issue_id in _topological_order {
        let is_read = read_issues.contains(&issue_id);
        let is_satisfied = is_read;

        issue_satisfied.insert(issue_id, is_satisfied);

        if !is_satisfied && !next_unread.contains_key(&issue_thread[&issue_id]) {
            next_unread.insert(issue_thread[&issue_id], issue_id);
        }
    }

    // Build thread eligibility
    let mut result = HashMap::new();

    for thread in &inputs.core.threads {
        if thread.status != "active" {
            result.insert(
                thread.id,
                ThreadEligibility {
                    thread_id: thread.id,
                    next_issue_id: None,
                    eligible: false,
                    blockers: vec![],
                },
            );
            continue;
        }

        let next_issue_id = next_unread.get(&thread.id).copied();

        if next_issue_id.is_none() {
            result.insert(
                thread.id,
                ThreadEligibility {
                    thread_id: thread.id,
                    next_issue_id: None,
                    eligible: false,
                    blockers: vec![],
                },
            );
            continue;
        }

        let next_issue_id = next_issue_id.unwrap();

        // Check if this issue is blocked by unsatisfied edges
        let empty_vec: Vec<ConstraintEdge> = vec![];
        let blocked_edges: Vec<&ConstraintEdge> = incoming
            .get(&next_issue_id)
            .unwrap_or(&empty_vec)
            .iter()
            .filter(|e| !read_issues.contains(&e.source_issue_id))
            .collect();

        if blocked_edges.is_empty() {
            result.insert(
                thread.id,
                ThreadEligibility {
                    thread_id: thread.id,
                    next_issue_id: Some(next_issue_id),
                    eligible: true,
                    blockers: vec![],
                },
            );
            continue;
        }

        // Group blockers by kind and list_id
        let mut blocker_map: BTreeMap<(String, Option<i32>), Blocker> = BTreeMap::new();

        for edge in blocked_edges {
            let key = (
                edge.origin.clone(),
                if edge.prerequisite_origin.is_some() {
                    None
                } else {
                    // Extract list_id from origin string like "list JLI strict order"
                    edge.origin
                        .strip_prefix("list ")
                        .and_then(|s| s.split(' ').next())
                        .and_then(|s| s.parse().ok())
                },
            );

            let entry = blocker_map.entry(key).or_insert_with(|| {
                if edge.prerequisite_origin.is_some() {
                    Blocker {
                        kind: "prerequisite".to_string(),
                        list_id: None,
                        waiting_on_issue_ids: vec![],
                        prerequisite_id: edge
                            .provenance
                            .iter()
                            .find_map(|p| p.strip_prefix("prerequisite "))
                            .and_then(|s| s.split(' ').next())
                            .and_then(|s| s.strip_suffix('('))
                            .and_then(|s| s.parse().ok()),
                        gate_issue_id: None,
                        origin: edge.prerequisite_origin.clone(),
                        provenance: edge.provenance.clone(),
                    }
                } else if edge.origin.contains("hold") {
                    Blocker {
                        kind: "hold".to_string(),
                        list_id: edge
                            .origin
                            .strip_prefix("list ")
                            .and_then(|s| s.split(' ').next())
                            .and_then(|s| s.parse().ok()),
                        waiting_on_issue_ids: vec![],
                        prerequisite_id: None,
                        gate_issue_id: None,
                        origin: None,
                        provenance: vec![],
                    }
                } else if edge.origin.contains("strict_order") {
                    Blocker {
                        kind: "strict_order".to_string(),
                        list_id: edge
                            .origin
                            .strip_prefix("list ")
                            .and_then(|s| s.split(' ').next())
                            .and_then(|s| s.parse().ok()),
                        waiting_on_issue_ids: vec![],
                        prerequisite_id: None,
                        gate_issue_id: None,
                        origin: None,
                        provenance: vec![],
                    }
                } else if edge.origin.contains("after_previous") {
                    Blocker {
                        kind: "after_previous".to_string(),
                        list_id: edge
                            .origin
                            .strip_prefix("list ")
                            .and_then(|s| s.split(' ').next())
                            .and_then(|s| s.parse().ok()),
                        waiting_on_issue_ids: vec![],
                        prerequisite_id: None,
                        gate_issue_id: None,
                        origin: None,
                        provenance: vec![],
                    }
                } else {
                    Blocker {
                        kind: edge.origin.clone(),
                        list_id: None,
                        waiting_on_issue_ids: vec![],
                        prerequisite_id: None,
                        gate_issue_id: None,
                        origin: None,
                        provenance: vec![],
                    }
                }
            });

            entry.waiting_on_issue_ids.push(edge.source_issue_id);
        }

        let mut blockers: Vec<Blocker> = blocker_map.into_values().collect();

        // Sort waiting_on_issue_ids for deterministic output
        for blocker in &mut blockers {
            blocker.waiting_on_issue_ids.sort_unstable();
            blocker.waiting_on_issue_ids.dedup();
        }

        result.insert(
            thread.id,
            ThreadEligibility {
                thread_id: thread.id,
                next_issue_id: Some(next_issue_id),
                eligible: false,
                blockers,
            },
        );
    }

    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        option_inputs::OptionInputs,
        reading_inputs::{CoreReadingInputs, ReadingIssue, ReadingThread, StoredThreadEligibility},
    };
    use std::collections::{BTreeMap, BTreeSet};

    fn test_inputs() -> OptionInputs {
        OptionInputs {
            core: CoreReadingInputs {
                threads: vec![
                    ReadingThread {
                        id: 1,
                        status: "active".to_string(),
                        title: "Series A".to_string(),
                    },
                    ReadingThread {
                        id: 2,
                        status: "active".to_string(),
                        title: "Series B".to_string(),
                    },
                ],
                issues: vec![
                    ReadingIssue {
                        id: 10,
                        thread_id: 1,
                        position: 1,
                        status: "read".to_string(),
                        issue_number: "1".to_string(),
                    },
                    ReadingIssue {
                        id: 11,
                        thread_id: 1,
                        position: 2,
                        status: "unread".to_string(),
                        issue_number: "2".to_string(),
                    },
                    ReadingIssue {
                        id: 20,
                        thread_id: 2,
                        position: 1,
                        status: "unread".to_string(),
                        issue_number: "1".to_string(),
                    },
                ],
                stored: vec![
                    StoredThreadEligibility {
                        thread_id: 1,
                        next_issue_id: Some(11),
                        is_blocked: false,
                        queue_position: 1,
                    },
                    StoredThreadEligibility {
                        thread_id: 2,
                        next_issue_id: Some(20),
                        is_blocked: false,
                        queue_position: 2,
                    },
                ],
            },
            thread_volumes: BTreeMap::new(),
            lists: vec![],
            prerequisites: vec![],
            excluded_issue_ids: BTreeSet::new(),
            unresolved: vec![],
        }
    }

    #[test]
    fn evaluate_basic_eligibility() {
        let inputs = test_inputs();
        let validated = ValidatedReadingInputs::new(inputs, &BTreeMap::new()).unwrap();
        let result = evaluate(&validated).unwrap();

        // Series A: issue 10 is read, issue 11 is next unread -> eligible
        assert!(result[&1].eligible);
        assert_eq!(result[&1].next_issue_id, Some(11));

        // Series B: issue 20 is next unread -> eligible
        assert!(result[&2].eligible);
        assert_eq!(result[&2].next_issue_id, Some(20));
    }

    #[test]
    fn evaluate_blocked_by_prerequisite() {
        let mut inputs = test_inputs();
        inputs
            .prerequisites
            .push(crate::option_inputs::Prerequisite {
                prerequisite_id: 1,
                source_issue_id: 11,
                target_issue_id: 20,
                origin: "reader".to_string(),
                provenance: vec!["classification:A".to_string(), "reader".to_string()],
            });

        let validated = ValidatedReadingInputs::new(inputs, &BTreeMap::new()).unwrap();
        let result = evaluate(&validated).unwrap();

        // Series B is now blocked by Series A #2
        assert!(!result[&2].eligible);
        assert_eq!(result[&2].next_issue_id, Some(20));
        assert_eq!(result[&2].blockers.len(), 1);
        assert_eq!(result[&2].blockers[0].kind, "prerequisite");
        assert!(result[&2].blockers[0].waiting_on_issue_ids.contains(&11));
    }
}
