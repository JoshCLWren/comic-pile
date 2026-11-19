//! Pure Option E evaluation for the prospective reading-graph preview.
//!
//! Faithful port of `app/services/reading_list_evaluator.py::evaluate` and its
//! list-blocker helpers. The preview must evaluate a *hypothetical* list set
//! (the proposed list substituted in, overlap answers applied to that list
//! only) that may even contain a cycle, so it cannot use the stored-state
//! `ValidatedReadingInputs` pipeline. Everything here is pure: no I/O.

use crate::option_inputs::{OptionInputs, Prerequisite, ReadingEntry, ReadingList};
use crate::reading_constraints::{Blocker, ThreadEligibility};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

/// One reader-approved `(continuing_volume_id, waiting_volume_id)` exception.
pub(crate) type Decision = (String, String);

/// The list being previewed: an existing list being updated or a new one.
#[derive(Debug, Clone)]
pub(crate) struct ProposedList {
    pub id: i32,
    pub mode: String,
    pub name: String,
    pub entries: Vec<ReadingEntry>,
}

/// Everything a scenario evaluation reads. Existing lists never carry overlap
/// decisions in the preview (Python builds them without any); only the proposed
/// list takes the reader's answers.
pub(crate) struct EvalInput<'a> {
    pub inputs: &'a OptionInputs,
    pub prerequisites: Vec<&'a Prerequisite>,
    /// Owned lists other than the proposed one, ascending by id.
    pub owned_lists: Vec<&'a ReadingList>,
    pub proposed: &'a ProposedList,
}

fn blocker(kind: &str, list_id: i32, waiting: Vec<i32>, gate: Option<i32>) -> Blocker {
    Blocker {
        kind: kind.to_string(),
        list_id: Some(list_id),
        waiting_on_issue_ids: waiting,
        gate_issue_id: gate,
        prerequisite_id: None,
        origin: None,
        provenance: Vec::new(),
    }
}

#[allow(clippy::too_many_arguments)]
fn list_blockers(
    list_id: i32,
    mode: &str,
    entries: &[ReadingEntry],
    decisions: &[Decision],
    unread: &HashSet<i32>,
    excluded: &BTreeSet<i32>,
    volume_by_issue: &HashMap<i32, Option<&str>>,
) -> HashMap<i32, Vec<Blocker>> {
    let mut waiting_by_volume: HashMap<&str, HashSet<&str>> = HashMap::new();
    for (continuing, waiting) in decisions {
        waiting_by_volume
            .entry(continuing.as_str())
            .or_default()
            .insert(waiting.as_str());
    }
    let mut blockers: HashMap<i32, Vec<Blocker>> = HashMap::new();
    let mut earlier_unread: Vec<i32> = Vec::new();
    let mut hold_issue_id: Option<i32> = None;
    let mut hold_unread: Vec<i32> = Vec::new();
    let mut previous: Option<i32> = None;
    for entry in entries
        .iter()
        .filter(|entry| !entry.skipped && !excluded.contains(&entry.issue_id))
    {
        let mut current: Vec<Blocker> = Vec::new();
        if unread.contains(&entry.issue_id) {
            if mode == "strict" {
                let continuing = volume_by_issue.get(&entry.issue_id).copied().flatten();
                let waiting_volumes = continuing.and_then(|volume| waiting_by_volume.get(volume));
                let predecessors: Vec<i32> = match waiting_volumes {
                    Some(waiting) if !waiting.is_empty() => earlier_unread
                        .iter()
                        .copied()
                        .filter(|predecessor| {
                            volume_by_issue
                                .get(predecessor)
                                .copied()
                                .flatten()
                                .is_none_or(|volume| !waiting.contains(volume))
                        })
                        .collect(),
                    _ => earlier_unread.clone(),
                };
                if !predecessors.is_empty() {
                    current.push(blocker("strict_order", list_id, predecessors, None));
                }
            }
            if !hold_unread.is_empty() {
                current.push(blocker("hold", list_id, hold_unread.clone(), hold_issue_id));
            }
            if entry.gate == "hold" && !earlier_unread.is_empty() {
                current.push(blocker(
                    "hold",
                    list_id,
                    earlier_unread.clone(),
                    Some(entry.issue_id),
                ));
            }
            if entry.gate == "after_previous" && previous.is_some_and(|id| unread.contains(&id)) {
                current.push(blocker(
                    "after_previous",
                    list_id,
                    previous.into_iter().collect(),
                    Some(entry.issue_id),
                ));
            }
            if !current.is_empty() {
                blockers.insert(entry.issue_id, current);
            }
            earlier_unread.push(entry.issue_id);
        }
        if entry.gate == "hold" {
            hold_issue_id = Some(entry.issue_id);
            hold_unread = earlier_unread.clone();
        }
        previous = Some(entry.issue_id);
    }
    blockers
}

type BlockerKey<'a> = (&'a str, i32, i32, i32, &'a [i32]);

fn blocker_key(blocker: &Blocker) -> BlockerKey<'_> {
    (
        blocker.kind.as_str(),
        blocker.list_id.unwrap_or(-1),
        blocker.gate_issue_id.unwrap_or(-1),
        blocker.prerequisite_id.unwrap_or(-1),
        blocker.waiting_on_issue_ids.as_slice(),
    )
}

/// Evaluate every active thread's frontier and blockers for one scenario.
pub(crate) fn evaluate(
    input: &EvalInput<'_>,
    decisions: &[Decision],
) -> BTreeMap<i32, ThreadEligibility> {
    let inputs = input.inputs;
    let unread: HashSet<i32> = inputs
        .core
        .issues
        .iter()
        .filter(|issue| issue.status != "read")
        .map(|issue| issue.id)
        .collect();
    let volume_by_issue: HashMap<i32, Option<&str>> = inputs
        .core
        .issues
        .iter()
        .map(|issue| {
            (
                issue.id,
                inputs
                    .thread_volumes
                    .get(&issue.thread_id)
                    .map(String::as_str),
            )
        })
        .collect();
    let excluded = &inputs.excluded_issue_ids;
    let mut restrictions: HashMap<i32, Vec<Blocker>> = HashMap::new();
    for list in &input.owned_lists {
        for (issue_id, found) in list_blockers(
            list.list_id,
            &list.mode,
            &list.entries,
            &[],
            &unread,
            excluded,
            &volume_by_issue,
        ) {
            restrictions.entry(issue_id).or_default().extend(found);
        }
    }
    for (issue_id, found) in list_blockers(
        input.proposed.id,
        &input.proposed.mode,
        &input.proposed.entries,
        decisions,
        &unread,
        excluded,
        &volume_by_issue,
    ) {
        restrictions.entry(issue_id).or_default().extend(found);
    }
    for prerequisite in &input.prerequisites {
        if unread.contains(&prerequisite.source_issue_id) {
            restrictions
                .entry(prerequisite.target_issue_id)
                .or_default()
                .push(Blocker {
                    kind: "prerequisite".to_string(),
                    list_id: None,
                    waiting_on_issue_ids: vec![prerequisite.source_issue_id],
                    gate_issue_id: None,
                    prerequisite_id: Some(prerequisite.prerequisite_id),
                    origin: Some(prerequisite.origin.clone()),
                    provenance: prerequisite.provenance.clone(),
                });
        }
    }
    let mut ordered: Vec<_> = inputs.core.issues.iter().collect();
    ordered.sort_by_key(|issue| (issue.position, issue.id));
    let mut frontiers: HashMap<i32, i32> = HashMap::new();
    for issue in ordered {
        if unread.contains(&issue.id) && !excluded.contains(&issue.id) {
            frontiers.entry(issue.thread_id).or_insert(issue.id);
        }
    }
    let mut result = BTreeMap::new();
    for thread in inputs.core.threads.iter().filter(|t| t.status == "active") {
        let next_issue_id = frontiers.get(&thread.id).copied();
        let mut blockers = next_issue_id
            .and_then(|id| restrictions.remove(&id))
            .unwrap_or_default();
        blockers.sort_by(|a, b| blocker_key(a).cmp(&blocker_key(b)));
        result.insert(
            thread.id,
            ThreadEligibility {
                thread_id: thread.id,
                next_issue_id,
                eligible: next_issue_id.is_some() && blockers.is_empty(),
                blockers,
            },
        );
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(issue_id: i32, gate: &str, skipped: bool) -> ReadingEntry {
        ReadingEntry {
            issue_id,
            gate: gate.to_string(),
            skipped,
        }
    }

    fn volumes<'a>(pairs: &[(i32, Option<&'a str>)]) -> HashMap<i32, Option<&'a str>> {
        pairs.iter().copied().collect()
    }

    #[test]
    fn strict_order_names_every_earlier_unread_issue() {
        let entries = vec![
            entry(1, "none", false),
            entry(2, "none", false),
            entry(3, "none", false),
        ];
        let unread: HashSet<i32> = [1, 2, 3].into();
        let found = list_blockers(
            7,
            "strict",
            &entries,
            &[],
            &unread,
            &BTreeSet::new(),
            &volumes(&[(1, None), (2, None), (3, None)]),
        );
        assert!(!found.contains_key(&1));
        assert_eq!(found[&2][0].waiting_on_issue_ids, vec![1]);
        assert_eq!(found[&3][0].waiting_on_issue_ids, vec![1, 2]);
        assert_eq!(found[&3][0].kind, "strict_order");
    }

    #[test]
    fn overlap_decision_relaxes_only_the_waiting_volume() {
        let entries = vec![
            entry(1, "none", false),
            entry(2, "none", false),
            entry(3, "none", false),
        ];
        let unread: HashSet<i32> = [1, 2, 3].into();
        let decisions = vec![("comicvine:B".to_string(), "comicvine:A".to_string())];
        let found = list_blockers(
            7,
            "strict",
            &entries,
            &decisions,
            &unread,
            &BTreeSet::new(),
            &volumes(&[
                (1, Some("comicvine:A")),
                (2, Some("comicvine:B")),
                (3, Some("comicvine:B")),
            ]),
        );
        assert!(
            !found.contains_key(&2),
            "B continues past waiting A: {found:?}"
        );
        assert_eq!(found[&3][0].waiting_on_issue_ids, vec![2]);
    }

    #[test]
    fn hold_and_after_previous_gates_apply_in_loose_lists() {
        let entries = vec![
            entry(1, "none", false),
            entry(2, "hold", false),
            entry(3, "none", false),
            entry(4, "after_previous", false),
            entry(5, "none", true),
        ];
        let unread: HashSet<i32> = [1, 2, 3, 4, 5].into();
        let found = list_blockers(
            9,
            "loose",
            &entries,
            &[],
            &unread,
            &BTreeSet::new(),
            &volumes(&[]),
        );
        assert_eq!(found[&2][0].kind, "hold");
        assert_eq!(found[&2][0].gate_issue_id, Some(2));
        assert_eq!(found[&3][0].waiting_on_issue_ids, vec![1, 2]);
        assert_eq!(found[&3][0].gate_issue_id, Some(2));
        let after = found[&4]
            .iter()
            .find(|b| b.kind == "after_previous")
            .expect("after_previous gate");
        assert_eq!(after.waiting_on_issue_ids, vec![3]);
        assert_eq!(after.gate_issue_id, Some(4));
        assert!(!found.contains_key(&5), "skipped entries never gate");
    }

    #[test]
    fn excluded_entries_are_dropped_from_the_list() {
        let entries = vec![entry(1, "none", false), entry(2, "none", false)];
        let unread: HashSet<i32> = [1, 2].into();
        let excluded: BTreeSet<i32> = [1].into();
        let found = list_blockers(
            1,
            "strict",
            &entries,
            &[],
            &unread,
            &excluded,
            &volumes(&[]),
        );
        assert!(found.is_empty());
    }
}
