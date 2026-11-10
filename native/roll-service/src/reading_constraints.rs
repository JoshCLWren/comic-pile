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
    /// Owning Reading List for list-ordered edges, so projection never parses a name.
    /// Internal plumbing only: the Python cycle-error contract has no such field.
    #[serde(skip)]
    pub list_id: Option<i32>,
}
impl ConstraintEdge {
    fn new(a: i32, b: i32, origin: &str) -> Self {
        Self {
            source_issue_id: a,
            target_issue_id: b,
            origin: origin.into(),
            prerequisite_origin: None,
            provenance: vec![],
            list_id: None,
        }
    }
    fn in_list(a: i32, b: i32, origin: &str, list_id: i32) -> Self {
        Self {
            list_id: Some(list_id),
            ..Self::new(a, b, origin)
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

/// Concrete unread requirements and their stable list or prerequisite origin.
/// Mirrors Python's reading_list_evaluator.Blocker.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Blocker {
    pub kind: String,
    pub list_id: Option<i32>,
    pub waiting_on_issue_ids: Vec<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub gate_issue_id: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub prerequisite_id: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub origin: Option<String>,
    #[serde(default)]
    pub provenance: Vec<String>,
}

/// An active Thread's derived frontier and every applicable restriction.
/// Mirrors Python's reading_list_evaluator.ThreadEligibility.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThreadEligibility {
    pub thread_id: i32,
    pub next_issue_id: Option<i32>,
    pub eligible: bool,
    pub blockers: Vec<Blocker>,
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
        let Some(current) = intersection.as_ref() else {
            continue;
        };
        if current.difference(target_waiting).next().is_none() {
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
                    edges.insert(ConstraintEdge::in_list(
                        pair[0].issue_id,
                        pair[1].issue_id,
                        &origin,
                        l.list_id,
                    ));
                }
            } else {
                let entry_volumes: Vec<_> = entries.iter().map(|e| volumes[&e.issue_id]).collect();
                for index in 1..entries.len() {
                    for cover in strict_covers(index, &entry_volumes, &waiting) {
                        edges.insert(ConstraintEdge::in_list(
                            entries[cover].issue_id,
                            entries[index].issue_id,
                            &origin,
                            l.list_id,
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
                edges.insert(ConstraintEdge::in_list(
                    previous,
                    entry.issue_id,
                    &origin,
                    l.list_id,
                ));
            }
            if entry.gate == "after_previous" && index > 0 {
                edges.insert(ConstraintEdge::in_list(
                    entries[index - 1].issue_id,
                    entry.issue_id,
                    &format!("list {name} after_previous"),
                    l.list_id,
                ));
            }
            if entry.gate == "hold" {
                for source in since_hold.drain(..) {
                    edges.insert(ConstraintEdge::in_list(
                        source,
                        entry.issue_id,
                        &origin,
                        l.list_id,
                    ));
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
            list_id: None,
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
        let Some(degree) = indegree.get_mut(&edge.target_issue_id) else {
            return Err(invalid("Constraint edge targets an unknown issue"));
        };
        *degree += 1;
        let Some(outgoing) = adjacency.get_mut(&edge.source_issue_id) else {
            return Err(invalid("Constraint edge sources an unknown issue"));
        };
        outgoing.push(edge);
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
            let Some(degree) = indegree.get_mut(&edge.target_issue_id) else {
                return Err(invalid("Constraint edge targets an unknown issue"));
            };
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

/// Why the Roll pool has no in-play faces.
///
/// Derived from the already-loaded Option E inputs and the eligible frontier
/// set. This is a single reason, never a list or a whole-library report, and it
/// adds no database work: it exists so a genuinely non-empty library does not
/// render the false "reading queue is empty" state (#4441).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, utoipa::ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum PoolReason {
    /// At least one next-unread frontier is eligible for the dice pool.
    Ready,
    /// The reader owns no series at all.
    NoSeries,
    /// In-play series exist, but every next-unread frontier waits on a prerequisite.
    AllBlocked,
    /// Every owned issue is read.
    AllCompleted,
    /// Unread issues exist, but none is in the active queue or all are excluded.
    AllOutOfPool,
}

/// Classify an empty Roll pool without materializing any diagnostic rows.
pub fn pool_reason(inputs: &OptionInputs, candidates: &[EligibleFrontier]) -> PoolReason {
    if !candidates.is_empty() {
        return PoolReason::Ready;
    }
    if inputs.core.threads.is_empty() {
        return PoolReason::NoSeries;
    }
    let snapshot = Snapshot::from_inputs(inputs, &BTreeMap::new());
    let Ok(edges) = constraint_edges(&snapshot) else {
        return PoolReason::AllBlocked;
    };
    let excluded = &inputs.excluded_issue_ids;
    let incomplete: HashSet<i32> = inputs
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
    let mut next_unread: HashMap<i32, (i32, i32)> = HashMap::new();
    for issue in &inputs.core.issues {
        if issue.status != "unread" || excluded.contains(&issue.id) {
            continue;
        }
        let key = (issue.position, issue.id);
        let first = next_unread.entry(issue.thread_id).or_insert(key);
        if key < *first {
            *first = key;
        }
    }
    let active: HashSet<i32> = inputs
        .core
        .threads
        .iter()
        .filter(|thread| thread.status == "active")
        .map(|thread| thread.id)
        .collect();
    let mut blocked_frontier = false;
    for stored in &inputs.core.stored {
        if !active.contains(&stored.thread_id) || stored.queue_position < 1 {
            continue;
        }
        let Some((_, issue_id)) = next_unread.get(&stored.thread_id) else {
            continue;
        };
        if blocked.contains(issue_id) {
            blocked_frontier = true;
        } else {
            // The eligible frontier set already covers this case; stay honest
            // rather than claiming a blocked-only library if it ever diverges.
            return PoolReason::Ready;
        }
    }
    if blocked_frontier {
        return PoolReason::AllBlocked;
    }
    if inputs
        .core
        .issues
        .iter()
        .any(|issue| issue.status == "unread")
    {
        return PoolReason::AllOutOfPool;
    }
    PoolReason::AllCompleted
}

/// One concrete cycle, with the edges that close it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GraphCycle {
    pub message: String,
    pub edges: Vec<ConstraintEdge>,
}

/// A persisted cyclic subgraph, isolated from the rest of the reader's graph.
///
/// Read paths use this to keep healthy Threads usable while naming the exact
/// written constraints that must be repaired. It is never produced by a write
/// path: authoring still rejects the complete graph before commit.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct GraphProblem {
    pub cycles: Vec<GraphCycle>,
    /// Every stored edge internal to a cyclic component, used to offer repairs.
    pub affected_edges: Vec<ConstraintEdge>,
    pub cyclic_issue_ids: BTreeSet<i32>,
    pub affected_thread_ids: BTreeSet<i32>,
    pub affected_list_ids: BTreeSet<i32>,
}
impl GraphProblem {
    /// Reader-facing summary suitable for a containment error response.
    pub fn summary(&self) -> String {
        self.cycles
            .first()
            .map(|cycle| cycle.message.clone())
            .unwrap_or_else(|| "Reading constraint cycle".to_string())
    }
}

/// Strongly connected components, including single-node self-loops.
fn cyclic_components(issue_ids: &BTreeSet<i32>, edges: &BTreeSet<ConstraintEdge>) -> Vec<Vec<i32>> {
    let mut adjacency: BTreeMap<i32, Vec<i32>> = issue_ids.iter().map(|id| (*id, vec![])).collect();
    let mut reverse: BTreeMap<i32, Vec<i32>> = issue_ids.iter().map(|id| (*id, vec![])).collect();
    let mut self_loops = HashSet::new();
    for edge in edges {
        if edge.source_issue_id == edge.target_issue_id {
            self_loops.insert(edge.source_issue_id);
            continue;
        }
        adjacency
            .entry(edge.source_issue_id)
            .or_default()
            .push(edge.target_issue_id);
        reverse
            .entry(edge.target_issue_id)
            .or_default()
            .push(edge.source_issue_id);
    }

    let mut visited = HashSet::new();
    let mut finish: Vec<i32> = Vec::with_capacity(issue_ids.len());
    for &start in issue_ids {
        if visited.contains(&start) {
            continue;
        }
        let mut stack = vec![(start, false)];
        while let Some((node, post)) = stack.pop() {
            if post {
                finish.push(node);
                continue;
            }
            if !visited.insert(node) {
                continue;
            }
            stack.push((node, true));
            for &next in adjacency.get(&node).into_iter().flatten().rev() {
                if !visited.contains(&next) {
                    stack.push((next, false));
                }
            }
        }
    }

    let mut assigned = HashSet::new();
    let mut components = vec![];
    for &start in finish.iter().rev() {
        if !assigned.insert(start) {
            continue;
        }
        let mut component = vec![];
        let mut stack = vec![start];
        while let Some(node) = stack.pop() {
            component.push(node);
            for &next in reverse.get(&node).into_iter().flatten() {
                if assigned.insert(next) {
                    stack.push(next);
                }
            }
        }
        let cyclic = component.len() > 1 || self_loops.contains(&start);
        if cyclic {
            components.push(component);
        }
    }
    components
}

/// Find one concrete cycle through `start` inside its strongly connected component.
fn cycle_path(
    start: i32,
    component: &HashSet<i32>,
    by_source: &BTreeMap<i32, Vec<ConstraintEdge>>,
) -> Option<Vec<ConstraintEdge>> {
    let mut visited = HashSet::from([start]);
    let mut path: Vec<ConstraintEdge> = vec![];
    let mut stack: Vec<(i32, usize)> = vec![(start, 0)];
    while let Some((node, index)) = stack.last_mut() {
        let outgoing = by_source.get(node).map(Vec::as_slice).unwrap_or(&[]);
        let Some(edge) = outgoing.get(*index) else {
            stack.pop();
            if !path.is_empty() {
                path.pop();
            }
            continue;
        };
        *index += 1;
        if !component.contains(&edge.target_issue_id) {
            continue;
        }
        if edge.target_issue_id == start {
            let mut cycle = path.clone();
            cycle.push(edge.clone());
            return Some(cycle);
        }
        if visited.insert(edge.target_issue_id) {
            path.push(edge.clone());
            stack.push((edge.target_issue_id, 0));
        }
    }
    None
}

fn cycle_message(edges: &[ConstraintEdge]) -> String {
    let description = edges
        .iter()
        .map(|edge| {
            format!(
                "Issue {} --[{}]--> Issue {}",
                edge.source_issue_id, edge.origin, edge.target_issue_id
            )
        })
        .collect::<Vec<_>>()
        .join(" -> ");
    format!("Reading constraint cycle: {description}")
}

fn analyze_cycles(
    snapshot: &Snapshot,
    edges: &BTreeSet<ConstraintEdge>,
) -> (GraphProblem, BTreeSet<i32>) {
    let issue_ids: BTreeSet<i32> = snapshot.issues.iter().map(|issue| issue.issue_id).collect();
    let mut by_source: BTreeMap<i32, Vec<ConstraintEdge>> = BTreeMap::new();
    for edge in edges {
        by_source
            .entry(edge.source_issue_id)
            .or_default()
            .push(edge.clone());
    }
    let thread_by_issue: HashMap<i32, i32> = snapshot
        .issues
        .iter()
        .map(|issue| (issue.issue_id, issue.thread_id))
        .collect();
    let mut problem = GraphProblem::default();
    for component in cyclic_components(&issue_ids, edges) {
        let members: HashSet<i32> = component.iter().copied().collect();
        let start = component.iter().copied().min().unwrap_or_default();
        for edge in edges {
            if members.contains(&edge.source_issue_id) && members.contains(&edge.target_issue_id) {
                problem.affected_edges.push(edge.clone());
                if let Some(list_id) = edge.list_id {
                    problem.affected_list_ids.insert(list_id);
                }
            }
        }
        let cycle = cycle_path(start, &members, &by_source)
            .or_else(|| {
                edges
                    .iter()
                    .find(|edge| {
                        edge.source_issue_id == edge.target_issue_id
                            && members.contains(&edge.source_issue_id)
                    })
                    .map(|edge| vec![edge.clone()])
            })
            .unwrap_or_default();
        for issue_id in &component {
            problem.cyclic_issue_ids.insert(*issue_id);
            if let Some(thread_id) = thread_by_issue.get(issue_id) {
                problem.affected_thread_ids.insert(*thread_id);
            }
        }
        for edge in &cycle {
            if let Some(list_id) = edge.list_id {
                problem.affected_list_ids.insert(list_id);
            }
        }
        if !cycle.is_empty() {
            problem.cycles.push(GraphCycle {
                message: cycle_message(&cycle),
                edges: cycle,
            });
        }
    }
    problem
        .cycles
        .sort_by(|left, right| left.message.cmp(&right.message));
    let cyclic = problem.cyclic_issue_ids.clone();
    (problem, cyclic)
}

fn topological_order(
    snapshot: &Snapshot,
    edges: &BTreeSet<ConstraintEdge>,
    excluded: &BTreeSet<i32>,
) -> Option<Vec<i32>> {
    let mut adjacency: BTreeMap<i32, Vec<&ConstraintEdge>> = snapshot
        .issues
        .iter()
        .filter(|issue| !excluded.contains(&issue.issue_id))
        .map(|issue| (issue.issue_id, vec![]))
        .collect();
    let mut indegree: BTreeMap<i32, usize> = adjacency.keys().map(|id| (*id, 0)).collect();
    for edge in edges {
        if excluded.contains(&edge.source_issue_id) || excluded.contains(&edge.target_issue_id) {
            continue;
        }
        adjacency.get_mut(&edge.source_issue_id)?.push(edge);
        *indegree.get_mut(&edge.target_issue_id)? += 1;
    }
    let mut ready: BinaryHeap<_> = indegree
        .iter()
        .filter(|(_, degree)| **degree == 0)
        .map(|(&id, _)| Reverse(id))
        .collect();
    let mut ordered = Vec::with_capacity(adjacency.len());
    while let Some(Reverse(id)) = ready.pop() {
        ordered.push(id);
        for edge in &adjacency[&id] {
            let degree = indegree.get_mut(&edge.target_issue_id)?;
            *degree -= 1;
            if *degree == 0 {
                ready.push(Reverse(edge.target_issue_id));
            }
        }
    }
    (ordered.len() == adjacency.len()).then_some(ordered)
}

/// Only this type may be consumed by future native eligible-candidate projection.
/// Private fields prevent raw/incomplete loader data from masquerading as validated.
pub struct ValidatedReadingInputs {
    inputs: OptionInputs,
    topological_order: Vec<i32>,
    edges: BTreeSet<ConstraintEdge>,
    graph_problem: Option<GraphProblem>,
    cyclic_issue_ids: BTreeSet<i32>,
}
impl ValidatedReadingInputs {
    /// Strict authoring validation: any cycle rejects the complete write.
    pub fn new(
        inputs: OptionInputs,
        names: &BTreeMap<i32, String>,
    ) -> Result<Self, ValidationError> {
        inputs.require_resolved().map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            invalid("Unresolved reading reference")
        })?;
        let snapshot = Snapshot::from_inputs(&inputs, names);
        let topological_order = validate(&snapshot)?;
        let edges = constraint_edges(&snapshot)?;
        Ok(Self {
            inputs,
            topological_order,
            edges,
            graph_problem: None,
            cyclic_issue_ids: BTreeSet::new(),
        })
    }

    /// Read-path containment: isolate cyclic components instead of failing a whole request.
    ///
    /// The returned structure reports the exact cycle and excludes only the
    /// cyclic Issues from eligibility. Writes must still use [`Self::new`].
    pub fn contained(
        inputs: OptionInputs,
        names: &BTreeMap<i32, String>,
    ) -> Result<Self, ValidationError> {
        inputs.require_resolved().map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            invalid("Unresolved reading reference")
        })?;
        let snapshot = Snapshot::from_inputs(&inputs, names);
        let edges = constraint_edges(&snapshot)?;
        // Acyclic data must be byte-for-byte identical to the strict result.
        // Only run cycle analysis after the canonical validator reports one.
        match validate(&snapshot) {
            Ok(topological_order) => Ok(Self {
                inputs,
                topological_order,
                edges,
                graph_problem: None,
                cyclic_issue_ids: BTreeSet::new(),
            }),
            Err(ValidationError::Cycle { .. }) => {
                let (problem, cyclic) = analyze_cycles(&snapshot, &edges);
                let topological_order = topological_order(&snapshot, &edges, &cyclic)
                    .ok_or_else(|| invalid("Reading graph containment failed"))?;
                let graph_problem = (!problem.cycles.is_empty()).then_some(problem);
                Ok(Self {
                    inputs,
                    topological_order,
                    edges,
                    graph_problem,
                    cyclic_issue_ids: cyclic,
                })
            }
            Err(other) => Err(other),
        }
    }
    pub fn inputs(&self) -> &OptionInputs {
        &self.inputs
    }
    pub fn topological_order(&self) -> &[i32] {
        &self.topological_order
    }
    pub fn graph_problem(&self) -> Option<&GraphProblem> {
        self.graph_problem.as_ref()
    }
    /// Return all currently unsatisfied incoming edges, including for a
    /// pending thread held behind prerequisites. Preserve original provenance.
    /// Edges touching a cyclic component are excluded so one corrupt subgraph
    /// cannot block healthy Threads.
    pub fn unsatisfied_edges(&self) -> Result<Vec<ConstraintEdge>, ValidationError> {
        let incomplete: HashSet<i32> = self
            .inputs
            .core
            .issues
            .iter()
            .filter(|issue| {
                issue.status != "read" && !self.inputs.excluded_issue_ids.contains(&issue.id)
            })
            .map(|issue| issue.id)
            .collect();

        let mut unsatisfied: BTreeSet<ConstraintEdge> = self
            .edges
            .iter()
            .filter(|edge| {
                // A cyclic source stays unread until repair, so its explicit
                // prerequisite/ordering edge must keep blocking a healthy
                // target. Only edges wholly inside the cyclic component are
                // neutralized.
                !self.cyclic_issue_ids.contains(&edge.target_issue_id)
                    && incomplete.contains(&edge.source_issue_id)
            })
            .cloned()
            .collect();

        // The graph used for cycle validation has adjacent strict-list edges.
        // Those edges alone cannot enforce live strict order after an out-of-order
        // read: A (unread) -> B (read) -> C (unread) makes C appear eligible.
        // Add runtime-only blockers from every earlier unread list entry to the
        // current Thread frontiers. Do not add these edges to the stable graph:
        // cycle validation must remain independent of mutable reading status.
        //
        // This matches Python reading_list_evaluator._list_blockers, including
        // list skips, collection exclusions, approved volume overlaps, and holds.
        let mut first_unread: HashMap<i32, (i32, i32)> = HashMap::new();
        for issue in &self.inputs.core.issues {
            if !incomplete.contains(&issue.id) {
                continue;
            }
            let key = (issue.position, issue.id);
            let first = first_unread.entry(issue.thread_id).or_insert(key);
            if key < *first {
                *first = key;
            }
        }
        let frontiers: HashSet<i32> = first_unread.values().map(|&(_, id)| id).collect();
        let volumes: HashMap<i32, &str> = self
            .inputs
            .core
            .issues
            .iter()
            .filter_map(|issue| {
                self.inputs
                    .thread_volumes
                    .get(&issue.thread_id)
                    .map(|volume| (issue.id, volume.as_str()))
            })
            .collect();

        for list in &self.inputs.lists {
            let list_name = label(&list.name, list.list_id);
            let strict_origin = format!("list {list_name} strict order");
            let hold_origin = format!("list {list_name} hold");
            let mut waiting_by_volume: HashMap<&str, HashSet<&str>> = HashMap::new();
            for decision in &list.overlap_decisions {
                waiting_by_volume
                    .entry(decision.continuing_volume_id.as_str())
                    .or_default()
                    .insert(decision.waiting_volume_id.as_str());
            }

            let mut earlier_unread: Vec<i32> = Vec::new();
            let mut hold_unread: Vec<i32> = Vec::new();
            for entry in list.entries.iter().filter(|entry| {
                !entry.skipped && !self.inputs.excluded_issue_ids.contains(&entry.issue_id)
            }) {
                if incomplete.contains(&entry.issue_id) {
                    if frontiers.contains(&entry.issue_id)
                        && !self.cyclic_issue_ids.contains(&entry.issue_id)
                    {
                        if list.mode == "strict" {
                            let waiting = volumes
                                .get(&entry.issue_id)
                                .and_then(|volume| waiting_by_volume.get(volume));
                            for source in &earlier_unread {
                                let exempt = waiting.is_some_and(|waiting_volumes| {
                                    volumes
                                        .get(source)
                                        .is_some_and(|volume| waiting_volumes.contains(volume))
                                });
                                if !exempt {
                                    unsatisfied.insert(ConstraintEdge::in_list(
                                        *source,
                                        entry.issue_id,
                                        &strict_origin,
                                        list.list_id,
                                    ));
                                }
                            }
                        }
                        for source in &hold_unread {
                            unsatisfied.insert(ConstraintEdge::in_list(
                                *source,
                                entry.issue_id,
                                &hold_origin,
                                list.list_id,
                            ));
                        }
                        if entry.gate == "hold" {
                            for source in &earlier_unread {
                                unsatisfied.insert(ConstraintEdge::in_list(
                                    *source,
                                    entry.issue_id,
                                    &hold_origin,
                                    list.list_id,
                                ));
                            }
                        }
                    }
                    earlier_unread.push(entry.issue_id);
                }
                if entry.gate == "hold" {
                    // A previously read hold cannot release later entries while
                    // an issue preceding that hold is still unread.
                    hold_unread.clone_from(&earlier_unread);
                }
            }
        }

        Ok(unsatisfied.into_iter().collect())
    }

    /// Live Option E frontiers. Ignore stale stored blocked/frontier fields:
    /// the validated dependency graph and issue statuses are authoritative.
    /// Exactly one next unread issue per active queue thread can be eligible.
    pub fn eligible_frontiers(&self) -> Result<Vec<EligibleFrontier>, ValidationError> {
        let edges = self.unsatisfied_edges()?;
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
            if issue.status != "unread"
                || excluded.contains(&issue.id)
                || self.cyclic_issue_ids.contains(&issue.id)
            {
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
            .filter(|stored| {
                self.graph_problem
                    .as_ref()
                    .is_none_or(|problem| !problem.affected_thread_ids.contains(&stored.thread_id))
            })
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
        option_inputs::{
            Prerequisite as OptionPrerequisite, ReadingEntry, ReadingList, UnresolvedReference,
        },
        reading_inputs::{CoreReadingInputs, ReadingIssue, ReadingThread, StoredThreadEligibility},
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
    fn option_e_frontier_uses_live_graph_and_next_unread_not_stale_stored_flags() {
        use crate::reading_inputs::StoredThreadEligibility;
        fn fixture(strict: bool, skipped: bool, exclude_other: bool) -> OptionInputs {
            let mut source = inputs();
            source.core.threads[0].status = "active".into();
            source.core.threads.push(ReadingThread {
                id: 9,
                status: "active".into(),
                title: "Other series".into(),
            });
            source.core.issues.push(ReadingIssue {
                id: 22,
                thread_id: 9,
                position: 1,
                status: "unread".into(),
                issue_number: "1".into(),
            });
            source.core.stored.extend([
                StoredThreadEligibility {
                    thread_id: 8,
                    next_issue_id: None,
                    is_blocked: true,
                    queue_position: 2,
                },
                StoredThreadEligibility {
                    thread_id: 9,
                    next_issue_id: Some(22),
                    is_blocked: false,
                    queue_position: 1,
                },
            ]);
            if strict {
                source.lists.push(ReadingList {
                    list_id: 44,
                    mode: "strict".into(),
                    name: "Curated".into(),
                    entries: vec![
                        ReadingEntry {
                            issue_id: 13,
                            gate: "none".into(),
                            skipped,
                        },
                        ReadingEntry {
                            issue_id: 22,
                            gate: "none".into(),
                            skipped: false,
                        },
                    ],
                    overlap_decisions: vec![],
                });
            }
            if exclude_other {
                source.excluded_issue_ids.insert(22);
            }
            source
        }
        let frontiers = |source: OptionInputs| {
            ValidatedReadingInputs::new(source, &BTreeMap::new())
                .unwrap()
                .eligible_frontiers()
                .unwrap()
                .into_iter()
                .map(|candidate| candidate.issue_id)
                .collect::<Vec<_>>()
        };
        // Stale stored blockers/frontier pointers cannot decide eligibility.
        assert_eq!(frontiers(fixture(false, false, false)), vec![22, 13]);
        assert_eq!(frontiers(fixture(true, false, false)), vec![13]);
        // Skipped list entries do not create predecessor gates.
        assert_eq!(frontiers(fixture(true, true, false)), vec![22, 13]);
        // Collection exclusions never return excluded issues.
        assert_eq!(frontiers(fixture(false, false, true)), vec![13]);
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
            name: "Curated".into(),
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

    fn pool_inputs(
        thread_status: &str,
        queue_position: i32,
        issue_status: &str,
        excluded: bool,
    ) -> OptionInputs {
        let mut source = OptionInputs {
            core: CoreReadingInputs {
                threads: vec![ReadingThread {
                    id: 8,
                    status: thread_status.into(),
                    title: "Series".into(),
                }],
                issues: vec![ReadingIssue {
                    id: 13,
                    thread_id: 8,
                    position: 1,
                    status: issue_status.into(),
                    issue_number: "1".into(),
                }],
                stored: vec![StoredThreadEligibility {
                    thread_id: 8,
                    next_issue_id: None,
                    is_blocked: false,
                    queue_position,
                }],
            },
            thread_volumes: BTreeMap::new(),
            lists: vec![],
            prerequisites: vec![],
            excluded_issue_ids: BTreeSet::new(),
            unresolved: vec![],
        };
        if excluded {
            source.excluded_issue_ids.insert(13);
        }
        source
    }

    fn reason(source: OptionInputs) -> PoolReason {
        let validated = ValidatedReadingInputs::new(source, &BTreeMap::new()).unwrap();
        let candidates = validated.eligible_frontiers().unwrap();
        pool_reason(validated.inputs(), &candidates)
    }

    #[test]
    fn empty_pool_reason_distinguishes_completed_out_of_pool_and_no_series() {
        assert_eq!(
            reason(pool_inputs("active", 1, "read", false)),
            PoolReason::AllCompleted
        );
        assert_eq!(
            reason(pool_inputs("active", 1, "unread", true)),
            PoolReason::AllOutOfPool
        );
        assert_eq!(
            reason(pool_inputs("active", 0, "unread", false)),
            PoolReason::AllOutOfPool
        );
        assert_eq!(
            reason(pool_inputs("completed", 1, "unread", false)),
            PoolReason::AllOutOfPool
        );
        let mut empty = pool_inputs("active", 1, "unread", false);
        empty.core.threads.clear();
        empty.core.issues.clear();
        empty.core.stored.clear();
        assert_eq!(reason(empty), PoolReason::NoSeries);
    }

    #[test]
    fn empty_pool_reason_reports_all_blocked_and_ready_frontiers() {
        assert_eq!(
            reason(pool_inputs("active", 1, "unread", false)),
            PoolReason::Ready
        );

        // An owner-scoped prerequisite from an unqueued series blocks the only
        // in-play frontier, so the pool is empty for a real reading-order reason.
        let mut blocked = pool_inputs("active", 1, "unread", false);
        blocked.core.threads.push(ReadingThread {
            id: 9,
            status: "active".into(),
            title: "Prequel series".into(),
        });
        blocked.core.issues.push(ReadingIssue {
            id: 22,
            thread_id: 9,
            position: 1,
            status: "unread".into(),
            issue_number: "1".into(),
        });
        blocked.core.stored.push(StoredThreadEligibility {
            thread_id: 9,
            next_issue_id: None,
            is_blocked: false,
            queue_position: 0,
        });
        blocked.prerequisites.push(OptionPrerequisite {
            prerequisite_id: 77,
            source_issue_id: 22,
            target_issue_id: 13,
            origin: "reader".into(),
            provenance: vec![],
        });
        assert_eq!(reason(blocked), PoolReason::AllBlocked);
    }

    fn graph_inputs() -> OptionInputs {
        OptionInputs {
            core: CoreReadingInputs {
                threads: vec![
                    ReadingThread {
                        id: 8,
                        status: "active".into(),
                        title: "B.P.R.D.: Hell on Earth — Wasteland".into(),
                    },
                    ReadingThread {
                        id: 9,
                        status: "active".into(),
                        title: "Healthy series".into(),
                    },
                ],
                issues: vec![
                    ReadingIssue {
                        id: 11,
                        thread_id: 8,
                        position: 1,
                        status: "unread".into(),
                        issue_number: "130".into(),
                    },
                    ReadingIssue {
                        id: 12,
                        thread_id: 8,
                        position: 2,
                        status: "unread".into(),
                        issue_number: "139".into(),
                    },
                    ReadingIssue {
                        id: 13,
                        thread_id: 8,
                        position: 3,
                        status: "unread".into(),
                        issue_number: "140".into(),
                    },
                    ReadingIssue {
                        id: 14,
                        thread_id: 8,
                        position: 4,
                        status: "unread".into(),
                        issue_number: "142".into(),
                    },
                    ReadingIssue {
                        id: 21,
                        thread_id: 9,
                        position: 1,
                        status: "unread".into(),
                        issue_number: "1".into(),
                    },
                ],
                stored: vec![
                    StoredThreadEligibility {
                        thread_id: 8,
                        next_issue_id: None,
                        is_blocked: false,
                        queue_position: 1,
                    },
                    StoredThreadEligibility {
                        thread_id: 9,
                        next_issue_id: None,
                        is_blocked: false,
                        queue_position: 2,
                    },
                ],
            },
            thread_volumes: BTreeMap::new(),
            lists: vec![ReadingList {
                list_id: 7,
                mode: "strict".into(),
                name: "Julix Comics (Unread)".into(),
                entries: vec![
                    ReadingEntry {
                        issue_id: 14,
                        gate: "none".into(),
                        skipped: false,
                    },
                    ReadingEntry {
                        issue_id: 11,
                        gate: "none".into(),
                        skipped: false,
                    },
                ],
                overlap_decisions: vec![],
            }],
            prerequisites: vec![],
            excluded_issue_ids: BTreeSet::new(),
            unresolved: vec![],
        }
    }

    fn muse_inputs() -> OptionInputs {
        OptionInputs {
            core: CoreReadingInputs {
                threads: vec![
                    ReadingThread {
                        id: 1,
                        status: "active".into(),
                        title: "Superman".into(),
                    },
                    ReadingThread {
                        id: 2,
                        status: "active".into(),
                        title: "Batman".into(),
                    },
                    ReadingThread {
                        id: 3,
                        status: "active".into(),
                        title: "Unaffected".into(),
                    },
                ],
                issues: vec![
                    ReadingIssue {
                        id: 101,
                        thread_id: 1,
                        position: 1,
                        status: "unread".into(),
                        issue_number: "1".into(),
                    },
                    ReadingIssue {
                        id: 102,
                        thread_id: 1,
                        position: 2,
                        status: "unread".into(),
                        issue_number: "2".into(),
                    },
                    ReadingIssue {
                        id: 201,
                        thread_id: 2,
                        position: 1,
                        status: "unread".into(),
                        issue_number: "1".into(),
                    },
                    ReadingIssue {
                        id: 202,
                        thread_id: 2,
                        position: 2,
                        status: "unread".into(),
                        issue_number: "2".into(),
                    },
                    ReadingIssue {
                        id: 301,
                        thread_id: 3,
                        position: 1,
                        status: "unread".into(),
                        issue_number: "1".into(),
                    },
                ],
                stored: vec![
                    StoredThreadEligibility {
                        thread_id: 1,
                        next_issue_id: None,
                        is_blocked: false,
                        queue_position: 1,
                    },
                    StoredThreadEligibility {
                        thread_id: 2,
                        next_issue_id: None,
                        is_blocked: false,
                        queue_position: 2,
                    },
                    StoredThreadEligibility {
                        thread_id: 3,
                        next_issue_id: None,
                        is_blocked: false,
                        queue_position: 3,
                    },
                ],
            },
            thread_volumes: BTreeMap::new(),
            lists: vec![
                ReadingList {
                    list_id: 1,
                    mode: "strict".into(),
                    name: "List One".into(),
                    entries: vec![
                        ReadingEntry {
                            issue_id: 102,
                            gate: "none".into(),
                            skipped: false,
                        },
                        ReadingEntry {
                            issue_id: 201,
                            gate: "none".into(),
                            skipped: false,
                        },
                    ],
                    overlap_decisions: vec![],
                },
                ReadingList {
                    list_id: 2,
                    mode: "strict".into(),
                    name: "List Two".into(),
                    entries: vec![
                        ReadingEntry {
                            issue_id: 202,
                            gate: "none".into(),
                            skipped: false,
                        },
                        ReadingEntry {
                            issue_id: 101,
                            gate: "none".into(),
                            skipped: false,
                        },
                    ],
                    overlap_decisions: vec![],
                },
            ],
            prerequisites: vec![],
            excluded_issue_ids: BTreeSet::new(),
            unresolved: vec![],
        }
    }

    #[test]
    fn bp_rd_cycle_is_isolated_and_strict_authoring_still_rejects_it() {
        let names = BTreeMap::from([(7, "Julix Comics (Unread)".to_string())]);
        let error = ValidatedReadingInputs::new(graph_inputs(), &names)
            .err()
            .expect("authoring must reject the cycle");
        let ValidationError::Cycle { message, edges } = error else {
            panic!("expected a cycle")
        };
        assert!(message.contains("list Julix Comics (Unread) strict order"));
        assert_eq!(edges.len(), 4);

        let contained = ValidatedReadingInputs::contained(graph_inputs(), &names).unwrap();
        let problem = contained.graph_problem().expect("cycle is reported");
        assert_eq!(problem.cyclic_issue_ids, BTreeSet::from([11, 12, 13, 14]));
        assert_eq!(problem.affected_thread_ids, BTreeSet::from([8]));
        assert_eq!(problem.affected_list_ids, BTreeSet::from([7]));
        assert!(problem
            .summary()
            .contains("Issue 14 --[list Julix Comics (Unread) strict order]--> Issue 11"));
        // The unrelated Thread remains rollable; only the cyclic component is withheld.
        let frontiers = contained.eligible_frontiers().unwrap();
        assert_eq!(frontiers.len(), 1);
        assert_eq!(frontiers[0].thread_id, 9);
        assert_eq!(frontiers[0].issue_id, 21);
    }

    #[test]
    fn muse_two_list_two_series_cycle_does_not_stop_unaffected_readers() {
        let contained = ValidatedReadingInputs::contained(muse_inputs(), &BTreeMap::new()).unwrap();
        let problem = contained.graph_problem().expect("cycle is reported");
        assert_eq!(problem.affected_thread_ids, BTreeSet::from([1, 2]));
        assert_eq!(problem.affected_list_ids, BTreeSet::from([1, 2]));
        let frontiers = contained.eligible_frontiers().unwrap();
        assert_eq!(frontiers.len(), 1);
        assert_eq!(frontiers[0].thread_id, 3);
        assert_eq!(frontiers[0].issue_id, 301);
    }

    #[test]
    fn legacy_strict_read_projection_would_return_500_for_the_incident_fixtures() {
        // The former read mapping used `validated`, which turns either exact
        // fixture into a global 500. The containment endpoints are what keep
        // Roll/Queue/History alive; this pins the failure mode the fixtures
        // reproduce without mocking the validator.
        for fixture in [graph_inputs(), muse_inputs()] {
            let error = crate::option_inputs::validated(fixture)
                .err()
                .expect("the incident fixture must be cyclic");
            assert_eq!(
                error.status(),
                axum::http::StatusCode::INTERNAL_SERVER_ERROR
            );
        }
    }

    fn skip_inputs(read: &[i32], list_entries: &[i32]) -> OptionInputs {
        OptionInputs {
            core: CoreReadingInputs {
                threads: vec![ReadingThread {
                    id: 1,
                    status: "active".into(),
                    title: "Series".into(),
                }],
                issues: (1..=5)
                    .map(|id| ReadingIssue {
                        id,
                        thread_id: 1,
                        position: id,
                        status: if read.contains(&id) { "read" } else { "unread" }.into(),
                        issue_number: id.to_string(),
                    })
                    .collect(),
                stored: vec![StoredThreadEligibility {
                    thread_id: 1,
                    next_issue_id: None,
                    is_blocked: false,
                    queue_position: 1,
                }],
            },
            thread_volumes: BTreeMap::new(),
            lists: vec![ReadingList {
                list_id: 9,
                mode: "strict".into(),
                name: "Sparse list".into(),
                entries: list_entries
                    .iter()
                    .map(|issue_id| ReadingEntry {
                        issue_id: *issue_id,
                        gate: "none".into(),
                        skipped: false,
                    })
                    .collect(),
                overlap_decisions: vec![],
            }],
            prerequisites: vec![],
            excluded_issue_ids: BTreeSet::new(),
            unresolved: vec![],
        }
    }

    #[test]
    fn strict_list_skipping_issues_never_hides_a_healthy_frontier() {
        // Series #1..#5 with a strict list containing only #1 and #5. After #1
        // is read the frontier is #2, not "no available issue".
        let contained =
            ValidatedReadingInputs::contained(skip_inputs(&[1], &[1, 5]), &BTreeMap::new())
                .unwrap();
        assert!(contained.graph_problem().is_none());
        let frontiers = contained.eligible_frontiers().unwrap();
        assert_eq!(
            frontiers
                .iter()
                .map(|frontier| frontier.issue_id)
                .collect::<Vec<_>>(),
            vec![2]
        );
    }

    #[test]
    fn strict_list_with_an_earlier_gap_offers_the_next_unread_in_series_order() {
        // #1 and #2 are read; a list edge #2 -> #4 must not skip #3.
        let contained =
            ValidatedReadingInputs::contained(skip_inputs(&[1, 2], &[2, 4]), &BTreeMap::new())
                .unwrap();
        assert!(contained.graph_problem().is_none());
        let frontiers = contained.eligible_frontiers().unwrap();
        assert_eq!(
            frontiers
                .iter()
                .map(|frontier| frontier.issue_id)
                .collect::<Vec<_>>(),
            vec![3]
        );
    }

    #[test]
    fn prerequisite_from_a_cyclic_source_still_blocks_a_healthy_target() {
        let mut source = graph_inputs();
        source.prerequisites.push(OptionPrerequisite {
            prerequisite_id: 77,
            source_issue_id: 11,
            target_issue_id: 21,
            origin: "reader".into(),
            provenance: vec![],
        });
        let contained = ValidatedReadingInputs::contained(source, &BTreeMap::new()).unwrap();
        assert!(contained.graph_problem().is_some());
        // Issue 11 is unread inside the cycle, so its explicit prerequisite
        // must keep the healthy target blocked rather than silently dropping it.
        assert!(contained
            .eligible_frontiers()
            .unwrap()
            .iter()
            .all(|frontier| frontier.issue_id != 21));
    }

    #[test]
    fn healthy_graph_has_no_problem_and_is_not_filtered() {
        let mut source = graph_inputs();
        // Keep the strict order and the series order consistent.
        source.lists[0].entries = vec![
            ReadingEntry {
                issue_id: 11,
                gate: "none".into(),
                skipped: false,
            },
            ReadingEntry {
                issue_id: 14,
                gate: "none".into(),
                skipped: false,
            },
        ];
        let contained = ValidatedReadingInputs::contained(source, &BTreeMap::new()).unwrap();
        assert!(contained.graph_problem().is_none());
        let frontiers = contained.eligible_frontiers().unwrap();
        assert_eq!(
            frontiers
                .iter()
                .map(|frontier| frontier.issue_id)
                .collect::<Vec<_>>(),
            vec![11, 21]
        );
    }
}
