//! Reader-facing blocker gate projection.
//! Mirrors Python's reading_blocker_projection module.

use crate::reading_constraints::Blocker;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DescribedBlockerGate {
    pub blocker: Blocker,
    pub described_issue_ids: Vec<i32>,
}

pub fn describe_blocker_gates(blockers: Vec<Blocker>) -> Vec<DescribedBlockerGate> {
    let mut gates = Vec::new();
    let mut described: HashSet<i32> = HashSet::new();

    for blocker in blockers {
        let waiting = &blocker.waiting_on_issue_ids;
        let new_issues: Vec<i32> = waiting
            .iter()
            .filter(|id| !described.contains(id))
            .copied()
            .collect();

        gates.push(DescribedBlockerGate {
            blocker: blocker.clone(),
            described_issue_ids: new_issues.clone(),
        });

        for id in new_issues {
            described.insert(id);
        }
    }

    gates
}

pub fn requirement_count(gates: &[DescribedBlockerGate]) -> usize {
    let mut unique = HashSet::new();
    for gate in gates {
        for id in &gate.described_issue_ids {
            unique.insert(*id);
        }
    }
    unique.len()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::reading_constraints::Blocker;

    #[test]
    fn distinct_blocking_issues_counted_once() {
        let blockers = vec![
            Blocker {
                kind: "prerequisite".to_string(),
                list_id: None,
                waiting_on_issue_ids: vec![1, 2],
                prerequisite_id: Some(1),
                gate_issue_id: None,
                origin: Some("reader".to_string()),
                provenance: vec!["reader".to_string()],
            },
            Blocker {
                kind: "hold".to_string(),
                list_id: Some(10),
                waiting_on_issue_ids: vec![2, 3],
                prerequisite_id: None,
                gate_issue_id: None,
                origin: None,
                provenance: vec![],
            },
        ];

        let gates = describe_blocker_gates(blockers);
        assert_eq!(requirement_count(&gates), 3);
        assert_eq!(gates[0].described_issue_ids, vec![1, 2]);
        assert_eq!(gates[1].described_issue_ids, vec![3]);
    }

    #[test]
    fn empty_blockers_returns_empty() {
        let gates = describe_blocker_gates(vec![]);
        assert_eq!(gates, vec![]);
        assert_eq!(requirement_count(&gates), 0);
    }
}
