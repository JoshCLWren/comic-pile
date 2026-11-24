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
        ValidationError::InvalidSnapshot { message } => crate::ApiError::Internal(message),
        ValidationError::Cycle {
            message: _,
            edges: _,
        } => crate::ApiError::Internal("Reading constraint cycle".to_string()),
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

        let Some(next_issue_id) = next_issue_id else {
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
        };

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
            let key = (edge.origin.clone(), edge.list_id);

            let entry = blocker_map.entry(key).or_insert_with(|| {
                if edge.prerequisite_origin.is_some() {
                    Blocker {
                        kind: "prerequisite".to_string(),
                        list_id: None,
                        waiting_on_issue_ids: vec![],
                        prerequisite_id: edge
                            .origin
                            .strip_prefix("prerequisite ")
                            .and_then(|s| s.split_whitespace().next())
                            .and_then(|s| s.parse().ok()),
                        gate_issue_id: None,
                        origin: edge.prerequisite_origin.clone(),
                        provenance: edge.provenance.clone(),
                    }
                } else if edge.origin.contains("hold") {
                    Blocker {
                        kind: "hold".to_string(),
                        list_id: edge.list_id,
                        waiting_on_issue_ids: vec![],
                        prerequisite_id: None,
                        gate_issue_id: None,
                        origin: None,
                        provenance: vec![],
                    }
                } else if edge.origin.contains("strict_order")
                    || edge.origin.contains("strict order")
                {
                    Blocker {
                        kind: "strict_order".to_string(),
                        list_id: edge.list_id,
                        waiting_on_issue_ids: vec![],
                        prerequisite_id: None,
                        gate_issue_id: None,
                        origin: None,
                        provenance: vec![],
                    }
                } else if edge.origin.contains("after_previous") {
                    Blocker {
                        kind: "after_previous".to_string(),
                        list_id: edge.list_id,
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
        // Match Python's stable reader-facing blocker order so projected
        // reasons and deduplicated requirement labels stay identical.
        blockers.sort_by(|left, right| {
            (
                &left.kind,
                left.list_id.unwrap_or(-1),
                left.gate_issue_id.unwrap_or(-1),
                left.prerequisite_id.unwrap_or(-1),
                &left.waiting_on_issue_ids,
            )
                .cmp(&(
                    &right.kind,
                    right.list_id.unwrap_or(-1),
                    right.gate_issue_id.unwrap_or(-1),
                    right.prerequisite_id.unwrap_or(-1),
                    &right.waiting_on_issue_ids,
                ))
        });

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

    // A persisted cycle is isolated to its own Threads. Healthy Threads above
    // keep their normal frontiers; affected Threads are blocked with the exact
    // cyclic Issues so Queue/Roll can name a repair instead of returning 500.
    if let Some(problem) = validated.graph_problem() {
        for thread in &inputs.core.threads {
            if thread.status != "active" || !problem.affected_thread_ids.contains(&thread.id) {
                continue;
            }
            let mut cyclic_here: Vec<i32> = problem
                .cyclic_issue_ids
                .iter()
                .filter(|issue_id| issue_thread.get(issue_id) == Some(&thread.id))
                .copied()
                .collect();
            cyclic_here.sort_unstable();
            let next_issue_id = inputs
                .core
                .issues
                .iter()
                .filter(|issue| {
                    issue.thread_id == thread.id && problem.cyclic_issue_ids.contains(&issue.id)
                })
                .min_by_key(|issue| (issue.position, issue.id))
                .map(|issue| issue.id);
            result.insert(
                thread.id,
                ThreadEligibility {
                    thread_id: thread.id,
                    next_issue_id,
                    eligible: false,
                    blockers: vec![Blocker {
                        kind: "reading_cycle".to_string(),
                        list_id: None,
                        waiting_on_issue_ids: cyclic_here,
                        prerequisite_id: None,
                        gate_issue_id: None,
                        origin: None,
                        provenance: vec![],
                    }],
                },
            );
        }
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

    #[test]
    fn out_of_order_reads_do_not_unlock_julix_later_frontiers() {
        let mut inputs = test_inputs();
        // Abe #31 follows already-read #30 locally, and Acheron follows an
        // already-read Abe #27 in Julix. Neither can bypass unread Abe #2.
        inputs.core.issues[2].position = 2;
        inputs.core.issues[2].issue_number = "31".into();
        inputs.core.issues.push(ReadingIssue {
            id: 21,
            thread_id: 2,
            position: 1,
            status: "read".into(),
            issue_number: "30".into(),
        });
        inputs.core.threads.push(ReadingThread {
            id: 3,
            status: "active".into(),
            title: "Sir Edward Grey: Acheron".into(),
        });
        inputs.core.issues.push(ReadingIssue {
            id: 30,
            thread_id: 3,
            position: 1,
            status: "unread".into(),
            issue_number: "1".into(),
        });
        inputs.core.stored.push(StoredThreadEligibility {
            thread_id: 3,
            next_issue_id: Some(30),
            is_blocked: false,
            queue_position: 3,
        });
        inputs.core.threads.push(ReadingThread {
            id: 4,
            status: "completed".into(),
            title: "Previously rated Abe #27".into(),
        });
        inputs.core.issues.push(ReadingIssue {
            id: 40,
            thread_id: 4,
            position: 1,
            status: "read".into(),
            issue_number: "27".into(),
        });
        inputs.core.stored.push(StoredThreadEligibility {
            thread_id: 4,
            next_issue_id: None,
            is_blocked: false,
            queue_position: 4,
        });
        inputs.lists.push(crate::option_inputs::ReadingList {
            list_id: 2,
            mode: "strict".into(),
            name: "Mignolaverse - Julix".into(),
            entries: [10, 11, 21, 20, 40, 30]
                .into_iter()
                .map(|issue_id| crate::option_inputs::ReadingEntry {
                    issue_id,
                    gate: "none".into(),
                    skipped: false,
                })
                .collect(),
            overlap_decisions: vec![],
        });

        let validated = ValidatedReadingInputs::new(inputs.clone(), &BTreeMap::new()).unwrap();
        let states = evaluate(&validated).unwrap();
        assert!(states[&1].eligible, "Abe #2 should be rollable");
        assert!(!states[&2].eligible, "Abe #31 must wait for Abe #2");
        assert!(
            !states[&3].eligible,
            "Acheron must wait for earlier Julix entries"
        );
        assert!(states[&2].blockers.iter().any(|blocker| {
            blocker.kind == "strict_order" && blocker.waiting_on_issue_ids.contains(&11)
        }));
        assert!(states[&3].blockers.iter().any(|blocker| {
            blocker.kind == "strict_order"
                && blocker.waiting_on_issue_ids.contains(&11)
                && blocker.waiting_on_issue_ids.contains(&20)
        }));
        let eligible = validated.eligible_frontiers().unwrap();
        assert_eq!(eligible.len(), 1);
        assert_eq!(eligible[0].issue_id, 11);

        // Finishing the earliest unread entry releases #31, not Acheron.
        inputs
            .core
            .issues
            .iter_mut()
            .find(|issue| issue.id == 11)
            .unwrap()
            .status = "read".into();
        let validated = ValidatedReadingInputs::new(inputs.clone(), &BTreeMap::new()).unwrap();
        let states = evaluate(&validated).unwrap();
        assert!(states[&2].eligible);
        assert!(!states[&3].eligible);
        inputs
            .core
            .issues
            .iter_mut()
            .find(|issue| issue.id == 20)
            .unwrap()
            .status = "read".into();
        let validated = ValidatedReadingInputs::new(inputs, &BTreeMap::new()).unwrap();
        let states = evaluate(&validated).unwrap();
        assert!(states[&3].eligible);
    }

    #[test]
    fn julix_king_of_fear_waits_for_dead_remembered_and_all_intervening_unread_entries() {
        // Production #3735: source Issue 117250 (The Dead Remembered #2) at
        // Julix position 23 must be the sole eligible frontier. King of Fear #1
        // (source Issue 117275) at position 54 has a satisfied Wild Hunt #8
        // prerequisite, but that read node must not hide older unread entries.
        let mut inputs = test_inputs();
        inputs.core.threads[0].title = "B.P.R.D.: The Dead Remembered".into();
        inputs.core.threads[1].title = "B.P.R.D.: King of Fear".into();
        inputs.core.threads.extend([
            ReadingThread {
                id: 3,
                status: "active".into(),
                title: "B.P.R.D.: Killing Ground".into(),
            },
            ReadingThread {
                id: 4,
                status: "active".into(),
                title: "B.P.R.D.: The Black Goddess".into(),
            },
            ReadingThread {
                id: 5,
                status: "completed".into(),
                title: "Hellboy: The Wild Hunt".into(),
            },
        ]);
        inputs.core.issues[0].issue_number = "1".into();
        inputs.core.issues[1].issue_number = "2".into();
        inputs.core.issues[2].issue_number = "1".into();
        inputs.core.issues.extend([
            ReadingIssue {
                id: 12,
                thread_id: 1,
                position: 3,
                status: "unread".into(),
                issue_number: "3".into(),
            },
            ReadingIssue {
                id: 30,
                thread_id: 3,
                position: 1,
                status: "unread".into(),
                issue_number: "1".into(),
            },
            ReadingIssue {
                id: 40,
                thread_id: 4,
                position: 5,
                status: "unread".into(),
                issue_number: "5".into(),
            },
            ReadingIssue {
                id: 50,
                thread_id: 5,
                position: 8,
                status: "read".into(),
                issue_number: "8".into(),
            },
        ]);
        inputs.core.stored[1].queue_position = 320;
        inputs.core.stored.extend([
            StoredThreadEligibility {
                thread_id: 3,
                next_issue_id: Some(30),
                is_blocked: false,
                queue_position: 25,
            },
            StoredThreadEligibility {
                thread_id: 4,
                next_issue_id: Some(40),
                is_blocked: false,
                queue_position: 45,
            },
            StoredThreadEligibility {
                thread_id: 5,
                next_issue_id: None,
                is_blocked: false,
                queue_position: 0,
            },
        ]);
        inputs.lists.push(crate::option_inputs::ReadingList {
            list_id: 2,
            mode: "strict".into(),
            name: "Mignolaverse — Julix Comics (Unread)".into(),
            // Positions 22, 23, 24, 25, 45, 53, 54 in the production list.
            entries: [10, 11, 12, 30, 40, 50, 20]
                .into_iter()
                .map(|issue_id| crate::option_inputs::ReadingEntry {
                    issue_id,
                    gate: "none".into(),
                    skipped: false,
                })
                .collect(),
            overlap_decisions: vec![],
        });
        inputs
            .prerequisites
            .push(crate::option_inputs::Prerequisite {
                prerequisite_id: 1_724_900,
                source_issue_id: 50,
                target_issue_id: 20,
                origin: "reader".into(),
                provenance: vec!["continuity-rule:1715697".into()],
            });

        let validated = ValidatedReadingInputs::new(inputs.clone(), &BTreeMap::new()).unwrap();
        let states = evaluate(&validated).unwrap();
        assert!(states[&1].eligible);
        assert_eq!(states[&1].next_issue_id, Some(11));
        for blocked_thread in [2, 3, 4] {
            assert!(
                !states[&blocked_thread].eligible,
                "thread {blocked_thread} must wait for earlier Julix entries"
            );
        }
        let king = &states[&2];
        let strict = king
            .blockers
            .iter()
            .find(|blocker| blocker.kind == "strict_order")
            .unwrap();
        assert_eq!(strict.waiting_on_issue_ids, vec![11, 12, 30, 40]);
        assert!(
            !king
                .blockers
                .iter()
                .any(|blocker| blocker.kind == "prerequisite"),
            "the already-read Wild Hunt prerequisite is satisfied"
        );
        let eligible = validated.eligible_frontiers().unwrap();
        assert_eq!(eligible.len(), 1);
        assert_eq!(eligible[0].issue_id, 11);
        assert_eq!(eligible[0].thread_id, 1);

        for issue in &mut inputs.core.issues {
            if [11, 12, 30, 40].contains(&issue.id) {
                issue.status = "read".into();
            }
        }
        let validated = ValidatedReadingInputs::new(inputs, &BTreeMap::new()).unwrap();
        assert!(evaluate(&validated).unwrap()[&2].eligible);
        let eligible = validated.eligible_frontiers().unwrap();
        assert_eq!(eligible.len(), 1);
        assert_eq!(eligible[0].issue_id, 20);
    }

    #[test]
    fn approved_volume_overlap_still_exempts_only_its_waiting_volume() {
        let mut inputs = test_inputs();
        inputs.thread_volumes.insert(1, "comicvine:11".into());
        inputs.thread_volumes.insert(2, "comicvine:20".into());
        inputs.lists.push(crate::option_inputs::ReadingList {
            list_id: 2,
            mode: "strict".into(),
            name: "Overlapping volumes".into(),
            entries: [11, 20]
                .into_iter()
                .map(|issue_id| crate::option_inputs::ReadingEntry {
                    issue_id,
                    gate: "none".into(),
                    skipped: false,
                })
                .collect(),
            overlap_decisions: vec![crate::option_inputs::OverlapDecision {
                continuing_volume_id: "comicvine:20".into(),
                waiting_volume_id: "comicvine:11".into(),
            }],
        });
        let validated = ValidatedReadingInputs::new(inputs.clone(), &BTreeMap::new()).unwrap();
        assert!(evaluate(&validated).unwrap()[&2].eligible);
        assert_eq!(validated.eligible_frontiers().unwrap().len(), 2);

        inputs.lists[0].overlap_decisions.clear();
        let validated = ValidatedReadingInputs::new(inputs, &BTreeMap::new()).unwrap();
        assert!(!evaluate(&validated).unwrap()[&2].eligible);
    }

    #[test]
    fn read_hold_does_not_release_later_issue_while_earlier_issue_is_unread() {
        let mut inputs = test_inputs();
        inputs.core.threads.push(ReadingThread {
            id: 3,
            status: "completed".into(),
            title: "Read milestone".into(),
        });
        inputs.core.issues.push(ReadingIssue {
            id: 30,
            thread_id: 3,
            position: 1,
            status: "read".into(),
            issue_number: "milestone".into(),
        });
        inputs.core.stored.push(StoredThreadEligibility {
            thread_id: 3,
            next_issue_id: None,
            is_blocked: false,
            queue_position: 3,
        });
        inputs.lists.push(crate::option_inputs::ReadingList {
            list_id: 2,
            mode: "loose".into(),
            name: "Milestone".into(),
            entries: vec![
                crate::option_inputs::ReadingEntry {
                    issue_id: 11,
                    gate: "none".into(),
                    skipped: false,
                },
                crate::option_inputs::ReadingEntry {
                    issue_id: 30,
                    gate: "hold".into(),
                    skipped: false,
                },
                crate::option_inputs::ReadingEntry {
                    issue_id: 20,
                    gate: "none".into(),
                    skipped: false,
                },
            ],
            overlap_decisions: vec![],
        });
        let validated = ValidatedReadingInputs::new(inputs, &BTreeMap::new()).unwrap();
        let states = evaluate(&validated).unwrap();
        assert!(states[&1].eligible);
        assert!(!states[&2].eligible);
        assert!(states[&2].blockers.iter().any(|blocker| {
            blocker.kind == "hold" && blocker.waiting_on_issue_ids.contains(&11)
        }));
    }

    #[test]
    fn loose_named_handoff_tracks_read_and_undo_without_stalling_other_series() {
        // Issue #4199: Ultimate Universe stays loose. Spider-Man #20 waits only
        // for the immediately preceding included entry, Black Panther #19, while
        // Black Panther #11 and unrelated series keep their natural frontiers.
        let mut inputs = OptionInputs {
            core: CoreReadingInputs {
                threads: [
                    (1, "Ultimate Spider-Man"),
                    (2, "Ultimate Black Panther"),
                    (3, "Independent series"),
                    (4, "Hold milestone"),
                    (5, "After hold"),
                ]
                .into_iter()
                .map(|(id, title)| ReadingThread {
                    id,
                    status: "active".into(),
                    title: title.into(),
                })
                .collect(),
                issues: [
                    (100, 1, 1, "read", "19"),
                    (101, 1, 2, "unread", "20"),
                    (200, 2, 1, "unread", "11"),
                    (201, 2, 2, "unread", "19"),
                    (300, 3, 1, "unread", "1"),
                    (400, 4, 1, "unread", "1"),
                    (500, 5, 1, "unread", "1"),
                ]
                .into_iter()
                .map(
                    |(id, thread_id, position, status, issue_number)| ReadingIssue {
                        id,
                        thread_id,
                        position,
                        status: status.into(),
                        issue_number: issue_number.into(),
                    },
                )
                .collect(),
                stored: (1..=5)
                    .map(|thread_id| StoredThreadEligibility {
                        thread_id,
                        next_issue_id: None,
                        is_blocked: false,
                        queue_position: thread_id,
                    })
                    .collect(),
            },
            thread_volumes: BTreeMap::new(),
            lists: vec![
                crate::option_inputs::ReadingList {
                    list_id: 4199,
                    mode: "loose".into(),
                    name: "Ultimate Universe".into(),
                    entries: vec![
                        crate::option_inputs::ReadingEntry {
                            issue_id: 100,
                            gate: "none".into(),
                            skipped: false,
                        },
                        crate::option_inputs::ReadingEntry {
                            issue_id: 200,
                            gate: "none".into(),
                            skipped: false,
                        },
                        crate::option_inputs::ReadingEntry {
                            issue_id: 201,
                            gate: "none".into(),
                            skipped: false,
                        },
                        crate::option_inputs::ReadingEntry {
                            issue_id: 101,
                            gate: "after_previous".into(),
                            skipped: false,
                        },
                        crate::option_inputs::ReadingEntry {
                            issue_id: 300,
                            gate: "none".into(),
                            skipped: false,
                        },
                    ],
                    overlap_decisions: vec![],
                },
                crate::option_inputs::ReadingList {
                    list_id: 4200,
                    mode: "loose".into(),
                    name: "Separate hold".into(),
                    entries: vec![
                        crate::option_inputs::ReadingEntry {
                            issue_id: 400,
                            gate: "hold".into(),
                            skipped: false,
                        },
                        crate::option_inputs::ReadingEntry {
                            issue_id: 500,
                            gate: "none".into(),
                            skipped: false,
                        },
                    ],
                    overlap_decisions: vec![],
                },
            ],
            prerequisites: vec![crate::option_inputs::Prerequisite {
                prerequisite_id: 1_723_987,
                source_issue_id: 201,
                target_issue_id: 101,
                origin: "converted".into(),
                provenance: vec!["historical classification unknown".into()],
            }],
            excluded_issue_ids: BTreeSet::new(),
            unresolved: vec![],
        };
        let eligible_ids = |validated: &ValidatedReadingInputs| {
            validated
                .eligible_frontiers()
                .unwrap()
                .into_iter()
                .map(|frontier| frontier.issue_id)
                .collect::<Vec<_>>()
        };
        let offer_ids = |validated: &ValidatedReadingInputs, snoozed: &HashSet<i32>| {
            crate::roll_pool::offer_frontiers(&validated.eligible_frontiers().unwrap(), snoozed, 20)
                .into_iter()
                .map(|frontier| frontier.issue_id)
                .collect::<Vec<_>>()
        };

        let validated = ValidatedReadingInputs::new(inputs.clone(), &BTreeMap::new()).unwrap();
        let states = evaluate(&validated).unwrap();
        assert_eq!(states[&1].next_issue_id, Some(101));
        assert!(!states[&1].eligible);
        assert_eq!(states[&1].blockers.len(), 1, "{:?}", states[&1]);
        assert_eq!(states[&1].blockers[0].kind, "after_previous");
        assert_eq!(states[&1].blockers[0].list_id, Some(4199));
        assert_eq!(states[&1].blockers[0].waiting_on_issue_ids, vec![201]);
        assert!(states[&2].eligible, "Black Panther #11 stays eligible");
        assert_eq!(states[&2].next_issue_id, Some(200));
        assert!(
            states[&3].eligible,
            "plain loose entries do not gate other series"
        );
        assert!(
            states[&4].eligible,
            "the hold milestone itself is reachable"
        );
        assert!(!states[&5].eligible);
        assert_eq!(states[&5].blockers[0].kind, "hold");
        assert_eq!(states[&5].blockers[0].waiting_on_issue_ids, vec![400]);
        assert_eq!(eligible_ids(&validated), vec![200, 300, 400]);
        assert_eq!(
            offer_ids(&validated, &HashSet::from([2])),
            vec![300, 400],
            "snoozing Black Panther #11 leaves unrelated loose series in the Roll pool"
        );

        let gates =
            crate::reading_blocker_projection::describe_blocker_gates(states[&1].blockers.clone());
        assert_eq!(gates.len(), 1);
        assert_eq!(gates[0].described_issue_ids, vec![201]);
        assert_eq!(
            crate::reading_blocker_projection::requirement_count(&gates),
            1
        );
        assert!(states[&1]
            .blockers
            .iter()
            .all(|blocker| blocker.kind != "prerequisite"));

        // Reading the named predecessor releases Spider-Man #20 without changing
        // the loose list or retroactively authoring the converted dependency.
        inputs
            .core
            .issues
            .iter_mut()
            .find(|issue| issue.id == 201)
            .unwrap()
            .status = "read".into();
        let validated = ValidatedReadingInputs::new(inputs.clone(), &BTreeMap::new()).unwrap();
        let states = evaluate(&validated).unwrap();
        assert!(states[&1].eligible);
        assert_eq!(states[&1].next_issue_id, Some(101));
        assert!(states[&1].blockers.is_empty());
        assert!(states[&2].eligible, "Black Panther #11 remains independent");
        assert!(states[&3].eligible);
        assert!(!states[&5].eligible, "the separate hold still applies");
        assert_eq!(eligible_ids(&validated), vec![101, 200, 300, 400]);
        assert_eq!(
            offer_ids(&validated, &HashSet::from([2])),
            vec![101, 300, 400],
            "Spider-Man #20 enters the Roll pool without backfilling the snoozed series"
        );
        assert_eq!(inputs.lists[0].mode, "loose");
        assert_eq!(inputs.prerequisites[0].origin, "converted");

        // Undo restores the predecessor to unread, so the same named handoff is
        // blocked again on the next canonical evaluation.
        inputs
            .core
            .issues
            .iter_mut()
            .find(|issue| issue.id == 201)
            .unwrap()
            .status = "unread".into();
        let validated = ValidatedReadingInputs::new(inputs.clone(), &BTreeMap::new()).unwrap();
        let states = evaluate(&validated).unwrap();
        assert!(!states[&1].eligible);
        assert_eq!(states[&1].blockers[0].waiting_on_issue_ids, vec![201]);
        assert_eq!(eligible_ids(&validated), vec![200, 300, 400]);

        inputs
            .core
            .issues
            .iter_mut()
            .find(|issue| issue.id == 400)
            .unwrap()
            .status = "read".into();
        let validated = ValidatedReadingInputs::new(inputs, &BTreeMap::new()).unwrap();
        let states = evaluate(&validated).unwrap();
        assert!(
            states[&5].eligible,
            "reading the hold milestone releases later entries"
        );
        assert_eq!(states[&5].next_issue_id, Some(500));
        assert_eq!(eligible_ids(&validated), vec![200, 300, 500]);
    }

    #[test]
    fn contained_cycle_blocks_only_the_affected_thread() {
        let mut inputs = test_inputs();
        inputs.core.threads.push(ReadingThread {
            id: 3,
            status: "active".to_string(),
            title: "Unaffected series".to_string(),
        });
        inputs.core.issues.push(ReadingIssue {
            id: 30,
            thread_id: 3,
            position: 1,
            status: "unread".to_string(),
            issue_number: "1".to_string(),
        });
        inputs.core.stored.push(StoredThreadEligibility {
            thread_id: 3,
            next_issue_id: None,
            is_blocked: false,
            queue_position: 3,
        });
        // Series order 10 -> 11 conflicts with a strict list that puts 11 first.
        inputs.lists.push(crate::option_inputs::ReadingList {
            list_id: 1,
            mode: "strict".to_string(),
            name: "Curated".to_string(),
            entries: vec![
                crate::option_inputs::ReadingEntry {
                    issue_id: 11,
                    gate: "none".to_string(),
                    skipped: false,
                },
                crate::option_inputs::ReadingEntry {
                    issue_id: 10,
                    gate: "none".to_string(),
                    skipped: false,
                },
            ],
            overlap_decisions: vec![],
        });
        let validated = ValidatedReadingInputs::contained(inputs, &BTreeMap::new()).unwrap();
        let result = evaluate(&validated).unwrap();
        assert!(!result[&1].eligible);
        assert_eq!(result[&1].blockers[0].kind, "reading_cycle");
        assert!(result[&1].blockers[0].waiting_on_issue_ids.contains(&10));
        // The unrelated series keeps its normal live frontier.
        assert!(result[&3].eligible);
        assert_eq!(result[&3].next_issue_id, Some(30));
    }
}
