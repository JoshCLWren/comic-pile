//! Pure global stored-constraint validation, including read and excluded issues.
use crate::option_inputs::OptionInputs;
use serde::{Deserialize, Serialize};
use std::{
    cmp::Reverse,
    collections::{BTreeMap, BTreeSet, BinaryHeap, HashMap, HashSet},
};

#[derive(Debug, Deserialize, Serialize)]
pub struct Thread {
    pub thread_id: i32,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub comicvine_volume_id: Option<String>,
}
#[derive(Debug, Deserialize, Serialize)]
pub struct Issue {
    pub issue_id: i32,
    pub thread_id: i32,
    pub position: i32,
}
#[derive(Debug, Deserialize, Serialize)]
pub struct Entry {
    pub issue_id: i32,
    #[serde(default = "none_gate")]
    pub gate: String,
    #[serde(default)]
    pub skipped: bool,
}
fn none_gate() -> String {
    "none".into()
}
#[derive(Debug, Deserialize, Serialize)]
pub struct Overlap {
    pub continuing_volume_id: String,
    pub waiting_volume_id: String,
}
#[derive(Debug, Deserialize, Serialize)]
pub struct List {
    pub list_id: i32,
    pub mode: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub entries: Vec<Entry>,
    #[serde(default)]
    pub overlap_decisions: Vec<Overlap>,
}
#[derive(Debug, Deserialize, Serialize)]
pub struct Prerequisite {
    pub prerequisite_id: i32,
    pub source_issue_id: i32,
    pub target_issue_id: i32,
    pub origin: String,
    #[serde(default)]
    pub provenance: Vec<String>,
}
#[derive(Debug, Default, Deserialize, Serialize)]
pub struct Snapshot {
    #[serde(default)]
    pub threads: Vec<Thread>,
    #[serde(default)]
    pub issues: Vec<Issue>,
    #[serde(default)]
    pub lists: Vec<List>,
    #[serde(default)]
    pub prerequisites: Vec<Prerequisite>,
    #[serde(default)]
    pub excluded_issue_ids: BTreeSet<i32>,
}
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize)]
pub struct ConstraintEdge {
    pub source_issue_id: i32,
    pub target_issue_id: i32,
    pub origin: String,
    pub prerequisite_origin: Option<String>,
    pub provenance: Vec<String>,
}
impl ConstraintEdge {
    fn new(a: i32, b: i32, origin: &str) -> Self {
        Self {
            source_issue_id: a,
            target_issue_id: b,
            origin: origin.into(),
            prerequisite_origin: None,
            provenance: vec![],
        }
    }
}
#[derive(Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ValidationError {
    InvalidSnapshot {
        message: String,
    },
    Cycle {
        message: String,
        edges: Vec<ConstraintEdge>,
    },
}
fn invalid(message: impl Into<String>) -> ValidationError {
    ValidationError::InvalidSnapshot {
        message: message.into(),
    }
}
impl Snapshot {
    /// Preserve every owner-scoped constraint. Names default to stable numeric labels.
    pub fn from_inputs(inputs: &OptionInputs, names: &BTreeMap<i32, String>) -> Self {
        Self {
            threads: inputs
                .core
                .threads
                .iter()
                .map(|t| Thread {
                    thread_id: t.id,
                    name: t.title.clone(),
                    comicvine_volume_id: inputs.thread_volumes.get(&t.id).cloned(),
                })
                .collect(),
            issues: inputs
                .core
                .issues
                .iter()
                .map(|i| Issue {
                    issue_id: i.id,
                    thread_id: i.thread_id,
                    position: i.position,
                })
                .collect(),
            lists: inputs
                .lists
                .iter()
                .map(|l| List {
                    list_id: l.list_id,
                    mode: l.mode.clone(),
                    name: names.get(&l.list_id).cloned().unwrap_or_default(),
                    entries: l
                        .entries
                        .iter()
                        .map(|e| Entry {
                            issue_id: e.issue_id,
                            gate: e.gate.clone(),
                            skipped: e.skipped,
                        })
                        .collect(),
                    overlap_decisions: l
                        .overlap_decisions
                        .iter()
                        .map(|d| Overlap {
                            continuing_volume_id: d.continuing_volume_id.clone(),
                            waiting_volume_id: d.waiting_volume_id.clone(),
                        })
                        .collect(),
                })
                .collect(),
            prerequisites: inputs
                .prerequisites
                .iter()
                .map(|p| Prerequisite {
                    prerequisite_id: p.prerequisite_id,
                    source_issue_id: p.source_issue_id,
                    target_issue_id: p.target_issue_id,
                    origin: p.origin.clone(),
                    provenance: p.provenance.clone(),
                })
                .collect(),
            excluded_issue_ids: inputs.excluded_issue_ids.clone(),
        }
    }
    fn check_references(&self) -> Result<(), ValidationError> {
        let threads: HashSet<_> = self.threads.iter().map(|t| t.thread_id).collect();
        let issues: HashSet<_> = self.issues.iter().map(|i| i.issue_id).collect();
        if threads.len() != self.threads.len()
            || issues.len() != self.issues.len()
            || self
                .lists
                .iter()
                .map(|l| l.list_id)
                .collect::<HashSet<_>>()
                .len()
                != self.lists.len()
            || self
                .prerequisites
                .iter()
                .map(|p| p.prerequisite_id)
                .collect::<HashSet<_>>()
                .len()
                != self.prerequisites.len()
        {
            return Err(invalid("Duplicate snapshot identity"));
        }
        if self.issues.iter().any(|i| !threads.contains(&i.thread_id)) {
            return Err(invalid("Issue references a missing Thread"));
        }
        let mut referenced = self.excluded_issue_ids.clone();
        for l in &self.lists {
            if !matches!(l.mode.as_str(), "strict" | "loose") {
                return Err(invalid(format!("Unknown list mode: {}", l.mode)));
            }
            if l.entries
                .iter()
                .map(|e| e.issue_id)
                .collect::<HashSet<_>>()
                .len()
                != l.entries.len()
            {
                return Err(invalid(format!("Duplicate issue in list {}", l.list_id)));
            }
            if l.entries
                .iter()
                .any(|e| !matches!(e.gate.as_str(), "none" | "hold" | "after_previous"))
            {
                return Err(invalid(format!("Unknown gate in list {}", l.list_id)));
            }
            let mut decisions = HashSet::new();
            for d in &l.overlap_decisions {
                if d.continuing_volume_id.is_empty() || d.waiting_volume_id.is_empty() {
                    return Err(invalid("Overlap decision requires both volume identities"));
                }
                if d.continuing_volume_id == d.waiting_volume_id {
                    return Err(invalid(
                        "Overlap decision cannot exempt a volume from itself",
                    ));
                }
                if !decisions.insert((&d.continuing_volume_id, &d.waiting_volume_id)) {
                    return Err(invalid(format!(
                        "Duplicate overlap decision in list {}",
                        l.list_id
                    )));
                }
            }
            referenced.extend(l.entries.iter().map(|e| e.issue_id));
        }
        for p in &self.prerequisites {
            if !matches!(p.origin.as_str(), "reader" | "converted") {
                return Err(invalid(format!(
                    "Unknown prerequisite origin: {}",
                    p.origin
                )));
            }
            referenced.extend([p.source_issue_id, p.target_issue_id]);
        }
        let missing: Vec<_> = referenced
            .into_iter()
            .filter(|id| !issues.contains(id))
            .collect();
        if !missing.is_empty() {
            return Err(invalid(format!(
                "Snapshot is missing referenced issues: {missing:?}"
            )));
        }
        if self
            .prerequisites
            .iter()
            .any(|p| self.excluded_issue_ids.contains(&p.source_issue_id))
        {
            return Err(invalid(
                "Collection exclusion strands an explicit prerequisite",
            ));
        }
        Ok(())
    }
}
fn label(name: &str, id: i32) -> String {
    if name.trim().is_empty() {
        format!("#{id}")
    } else {
        name.trim().into()
    }
}
fn strict_covers(
    index: usize,
    volumes: &[Option<&str>],
    waiting: &HashMap<&str, HashSet<&str>>,
) -> Vec<usize> {
    let empty = HashSet::new();
    let target_waiting = volumes[index]
        .and_then(|v| waiting.get(v))
        .unwrap_or(&empty);
    let mut covers = vec![];
    let mut intersection: Option<HashSet<&str>> = None;
    for position in (0..index).rev() {
        let volume = volumes[position];
        if volume.is_some_and(|v| target_waiting.contains(v)) {
            continue;
        }
        if intersection
            .as_ref()
            .is_none_or(|set| volume.is_some_and(|v| set.contains(v)))
        {
            covers.push(position);
        }
        let wait_for = volume.and_then(|v| waiting.get(v)).unwrap_or(&empty);
        intersection = Some(match intersection {
            None => wait_for.clone(),
            Some(set) => set.intersection(wait_for).copied().collect(),
        });
        if intersection
            .as_ref()
            .unwrap()
            .difference(target_waiting)
            .next()
            .is_none()
        {
            break;
        }
    }
    covers
}
/// Exact Python ordering rules with iterative topological sort and cycle traversal.
fn constraint_edges(snapshot: &Snapshot) -> Result<BTreeSet<ConstraintEdge>, ValidationError> {
    snapshot.check_references()?;
    let mut edges = BTreeSet::new();
    let threads: HashMap<_, _> = snapshot.threads.iter().map(|t| (t.thread_id, t)).collect();
    let mut by_thread: BTreeMap<i32, Vec<(i32, i32)>> = BTreeMap::new();
    let mut volumes = HashMap::new();
    for i in &snapshot.issues {
        by_thread
            .entry(i.thread_id)
            .or_default()
            .push((i.position, i.issue_id));
        volumes.insert(
            i.issue_id,
            threads[&i.thread_id].comicvine_volume_id.as_deref(),
        );
    }
    for (id, mut issues) in by_thread {
        issues.sort_unstable();
        let origin = format!("Thread {} series order", label(&threads[&id].name, id));
        for pair in issues.windows(2) {
            edges.insert(ConstraintEdge::new(pair[0].1, pair[1].1, &origin));
        }
    }
    for l in &snapshot.lists {
        let entries: Vec<_> = l.entries.iter().filter(|e| !e.skipped).collect();
        let name = label(&l.name, l.list_id);
        if l.mode == "strict" {
            let origin = format!("list {name} strict order");
            let mut waiting: HashMap<&str, HashSet<&str>> = HashMap::new();
            for d in &l.overlap_decisions {
                waiting
                    .entry(&d.continuing_volume_id)
                    .or_default()
                    .insert(&d.waiting_volume_id);
            }
            if waiting.is_empty() {
                for pair in entries.windows(2) {
                    edges.insert(ConstraintEdge::new(
                        pair[0].issue_id,
                        pair[1].issue_id,
                        &origin,
                    ));
                }
            } else {
                let entry_volumes: Vec<_> = entries.iter().map(|e| volumes[&e.issue_id]).collect();
                for index in 1..entries.len() {
                    for cover in strict_covers(index, &entry_volumes, &waiting) {
                        edges.insert(ConstraintEdge::new(
                            entries[cover].issue_id,
                            entries[index].issue_id,
                            &origin,
                        ));
                    }
                }
            }
        }
        let mut previous_hold = None;
        let mut since_hold = vec![];
        for (index, entry) in entries.iter().enumerate() {
            let origin = format!("list {name} hold");
            if let Some(previous) = previous_hold {
                edges.insert(ConstraintEdge::new(previous, entry.issue_id, &origin));
            }
            if entry.gate == "after_previous" && index > 0 {
                edges.insert(ConstraintEdge::new(
                    entries[index - 1].issue_id,
                    entry.issue_id,
                    &format!("list {name} after_previous"),
                ));
            }
            if entry.gate == "hold" {
                for source in since_hold.drain(..) {
                    edges.insert(ConstraintEdge::new(source, entry.issue_id, &origin));
                }
                previous_hold = Some(entry.issue_id);
            } else {
                since_hold.push(entry.issue_id);
            }
        }
    }
    for p in &snapshot.prerequisites {
        let suffix = if p
            .provenance
            .iter()
            .any(|v| v == "historical classification unknown")
        {
            "; historical classification unknown"
        } else {
            ""
        };
        edges.insert(ConstraintEdge {
            source_issue_id: p.source_issue_id,
            target_issue_id: p.target_issue_id,
            origin: format!("prerequisite {} ({}{suffix})", p.prerequisite_id, p.origin),
            prerequisite_origin: Some(p.origin.clone()),
            provenance: p.provenance.clone(),
        });
    }
    Ok(edges)
}

pub fn validate(snapshot: &Snapshot) -> Result<Vec<i32>, ValidationError> {
    let edges = constraint_edges(snapshot)?;
    let mut adjacency: BTreeMap<i32, Vec<ConstraintEdge>> = snapshot
        .issues
        .iter()
        .map(|i| (i.issue_id, vec![]))
        .collect();
    let mut indegree: HashMap<i32, usize> =
        snapshot.issues.iter().map(|i| (i.issue_id, 0)).collect();
    for edge in edges {
        *indegree.get_mut(&edge.target_issue_id).unwrap() += 1;
        adjacency.get_mut(&edge.source_issue_id).unwrap().push(edge);
    }
    let mut ready: BinaryHeap<_> = indegree
        .iter()
        .filter(|(_, d)| **d == 0)
        .map(|(&id, _)| Reverse(id))
        .collect();
    let mut ordered = Vec::with_capacity(adjacency.len());
    while let Some(Reverse(id)) = ready.pop() {
        ordered.push(id);
        for edge in &adjacency[&id] {
            let degree = indegree.get_mut(&edge.target_issue_id).unwrap();
            *degree -= 1;
            if *degree == 0 {
                ready.push(Reverse(edge.target_issue_id));
            }
        }
    }
    if ordered.len() == adjacency.len() {
        return Ok(ordered);
    }
    let residual: BTreeSet<_> = indegree
        .iter()
        .filter(|(_, d)| **d > 0)
        .map(|(&id, _)| id)
        .collect();
    let mut visited = HashSet::new();
    for &start in &residual {
        if visited.contains(&start) {
            continue;
        }
        let mut active = HashMap::from([(start, 0)]);
        let mut path: Vec<ConstraintEdge> = vec![];
        let mut stack = vec![(start, 0usize)];
        while let Some((node, index)) = stack.last_mut() {
            if let Some(edge) = adjacency[node].get(*index) {
                *index += 1;
                let target = edge.target_issue_id;
                if !residual.contains(&target) {
                    continue;
                }
                if let Some(&offset) = active.get(&target) {
                    let mut cycle = path[offset..].to_vec();
                    cycle.push(edge.clone());
                    let description = cycle
                        .iter()
                        .map(|e| {
                            format!(
                                "Issue {} --[{}]--> Issue {}",
                                e.source_issue_id, e.origin, e.target_issue_id
                            )
                        })
                        .collect::<Vec<_>>()
                        .join(" -> ");
                    return Err(ValidationError::Cycle {
                        message: format!("Reading constraint cycle: {description}"),
                        edges: cycle,
                    });
                }
                if !visited.contains(&target) {
                    active.insert(target, path.len() + 1);
                    path.push(edge.clone());
                    stack.push((target, 0));
                }
            } else {
                visited.insert(*node);
                active.remove(node);
                stack.pop();
                path.pop();
            }
        }
    }
    Err(invalid("Residual graph has no cycle"))
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EligibleFrontier {
    pub thread_id: i32,
    pub issue_id: i32,
    pub queue_position: i32,
}

/// Only this type may be consumed by future native eligible-candidate projection.
/// Private fields prevent raw/incomplete loader data from masquerading as validated.
pub struct ValidatedReadingInputs {
    inputs: OptionInputs,
    topological_order: Vec<i32>,
}
impl ValidatedReadingInputs {
    pub fn new(
        inputs: OptionInputs,
        names: &BTreeMap<i32, String>,
    ) -> Result<Self, ValidationError> {
        inputs
            .require_resolved()
            .map_err(|_| invalid("Unresolved reading reference"))?;
        let topological_order = validate(&Snapshot::from_inputs(&inputs, names))?;
        Ok(Self {
            inputs,
            topological_order,
        })
    }
    pub fn inputs(&self) -> &OptionInputs {
        &self.inputs
    }
    pub fn topological_order(&self) -> &[i32] {
        &self.topological_order
    }
    /// Live Option E frontiers. Ignore stale stored blocked/frontier fields:
    /// the validated dependency graph and issue statuses are authoritative.
    /// Exactly one next unread issue per active queue thread can be eligible.
    pub fn eligible_frontiers(&self) -> Result<Vec<EligibleFrontier>, ValidationError> {
        let snapshot = Snapshot::from_inputs(&self.inputs, &BTreeMap::new());
        let edges = constraint_edges(&snapshot)?;
        let excluded = &self.inputs.excluded_issue_ids;
        let incomplete: HashSet<i32> = self
            .inputs
            .core
            .issues
            .iter()
            .filter(|issue| issue.status != "read" && !excluded.contains(&issue.id))
            .map(|issue| issue.id)
            .collect();
        let blocked: HashSet<i32> = edges
            .iter()
            .filter(|edge| incomplete.contains(&edge.source_issue_id))
            .map(|edge| edge.target_issue_id)
            .collect();

        let mut next_unread: BTreeMap<i32, (i32, i32)> = BTreeMap::new();
        for issue in &self.inputs.core.issues {
            if issue.status != "unread" || excluded.contains(&issue.id) {
                continue;
            }
            let key = (issue.position, issue.id);
            let first = next_unread.entry(issue.thread_id).or_insert(key);
            if key < *first {
                *first = key;
            }
        }
        let active: HashSet<i32> = self
            .inputs
            .core
            .threads
            .iter()
            .filter(|thread| thread.status == "active")
            .map(|thread| thread.id)
            .collect();

        let mut candidates: Vec<EligibleFrontier> = self
            .inputs
            .core
            .stored
            .iter()
            .filter(|stored| active.contains(&stored.thread_id) && stored.queue_position >= 1)
            .filter_map(|stored| {
                let (_, issue_id) = next_unread.get(&stored.thread_id)?;
                (!blocked.contains(issue_id)).then_some(EligibleFrontier {
                    thread_id: stored.thread_id,
                    issue_id: *issue_id,
                    queue_position: stored.queue_position,
                })
            })
            .collect();
        candidates.sort_by_key(|candidate| (candidate.queue_position, candidate.thread_id));
        Ok(candidates)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        option_inputs::{ReadingEntry, ReadingList, UnresolvedReference},
        reading_inputs::{CoreReadingInputs, ReadingIssue, ReadingThread},
    };
    fn inputs() -> OptionInputs {
        OptionInputs {
            core: CoreReadingInputs {
                threads: vec![ReadingThread {
                    id: 8,
                    status: "completed".into(),
                    title: "Series".into(),
                }],
                issues: vec![
                    ReadingIssue {
                        id: 12,
                        thread_id: 8,
                        position: 1,
                        status: "read".into(),
                        issue_number: "1".into(),
                    },
                    ReadingIssue {
                        id: 13,
                        thread_id: 8,
                        position: 2,
                        status: "unread".into(),
                        issue_number: "2".into(),
                    },
                ],
                stored: vec![],
            },
            thread_volumes: BTreeMap::new(),
            lists: vec![],
            prerequisites: vec![],
            excluded_issue_ids: BTreeSet::from([12]),
            unresolved: vec![],
        }
    }
    #[test]
    fn execution_capability_checks_cycles_read_and_excluded_nodes_and_unresolved_references() {
        let valid = ValidatedReadingInputs::new(inputs(), &BTreeMap::new())
            .ok()
            .unwrap();
        assert_eq!(valid.topological_order(), &[12, 13]);
        assert_eq!(valid.inputs().core.issues.len(), 2);
        let mut cyclic = inputs();
        cyclic.lists.push(ReadingList {
            list_id: 9,
            mode: "strict".into(),
            entries: vec![
                ReadingEntry {
                    issue_id: 13,
                    gate: "none".into(),
                    skipped: false,
                },
                ReadingEntry {
                    issue_id: 12,
                    gate: "none".into(),
                    skipped: false,
                },
            ],
            overlap_decisions: vec![],
        });
        let error = ValidatedReadingInputs::new(cyclic, &BTreeMap::from([(9, "Curated".into())]))
            .err()
            .unwrap();
        let ValidationError::Cycle { message, edges } = error else {
            panic!("expected cycle")
        };
        assert!(message.contains("list Curated strict order"));
        assert_eq!(edges.len(), 2);
        let mut unresolved = inputs();
        unresolved.unresolved.push(UnresolvedReference {
            kind: "list_entry",
            object_id: 99,
        });
        assert!(matches!(
            ValidatedReadingInputs::new(unresolved, &BTreeMap::new()),
            Err(ValidationError::InvalidSnapshot { .. })
        ));
    }
}
