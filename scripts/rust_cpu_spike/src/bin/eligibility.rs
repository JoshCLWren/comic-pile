//! Pure Option E eligibility evaluator experiment.
//! JSON stdin -> JSON stdout. No database, Python, HTTP or mutations.
//! This models the canonical evaluate() algorithm, not cycle validation.
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::io::{self, Read};

#[derive(Deserialize)]
struct Snapshot {
    threads: Vec<Thread>,
    issues: Vec<Issue>,
    #[serde(default)]
    lists: Vec<ReadingList>,
    #[serde(default)]
    prerequisites: Vec<Prerequisite>,
    #[serde(default)]
    excluded_issue_ids: Vec<i64>,
}
#[derive(Deserialize)]
struct Thread {
    thread_id: i64,
    status: String,
    comicvine_volume_id: Option<String>,
}
#[derive(Deserialize)]
struct Issue {
    issue_id: i64,
    thread_id: i64,
    position: i64,
    status: String,
}
#[derive(Deserialize)]
struct ReadingList {
    list_id: i64,
    mode: String,
    entries: Vec<Entry>,
    #[serde(default)]
    overlap_decisions: Vec<Overlap>,
}
#[derive(Deserialize)]
struct Entry {
    issue_id: i64,
    gate: String,
    skipped: bool,
}
#[derive(Deserialize)]
struct Overlap {
    continuing_volume_id: String,
    waiting_volume_id: String,
}
#[derive(Deserialize)]
struct Prerequisite {
    prerequisite_id: i64,
    source_issue_id: i64,
    target_issue_id: i64,
    origin: String,
    #[serde(default)]
    provenance: Vec<String>,
}
#[derive(Serialize, PartialEq, Eq)]
struct Blocker {
    kind: String,
    list_id: Option<i64>,
    waiting_on_issue_ids: Vec<i64>,
    gate_issue_id: Option<i64>,
    prerequisite_id: Option<i64>,
    origin: Option<String>,
    provenance: Vec<String>,
}
#[derive(Serialize)]
struct Eligibility {
    thread_id: i64,
    next_issue_id: Option<i64>,
    blockers: Vec<Blocker>,
    eligible: bool,
}

fn blocker(kind: &str, list_id: Option<i64>, waiting: Vec<i64>, gate: Option<i64>) -> Blocker {
    Blocker {
        kind: kind.into(), list_id, waiting_on_issue_ids: waiting,
        gate_issue_id: gate, prerequisite_id: None, origin: None, provenance: vec![],
    }
}

fn evaluate(input: Snapshot) -> Result<Vec<Eligibility>, String> {
    let mut thread_ids = HashSet::new();
    let volumes: HashMap<i64, Option<String>> = input.threads.iter().map(|t| {
        if !thread_ids.insert(t.thread_id) { return Err("duplicate thread"); }
        Ok((t.thread_id, t.comicvine_volume_id.clone()))
    }).collect::<Result<_,_>>()?;
    let mut issue_ids = HashSet::new();
    let mut issue_volume: HashMap<i64, Option<String>> = HashMap::new();
    for issue in &input.issues {
        if !issue_ids.insert(issue.issue_id) { return Err("duplicate issue".into()); }
        let volume = volumes.get(&issue.thread_id).ok_or("missing issue thread")?;
        issue_volume.insert(issue.issue_id, volume.clone());
    }
    let excluded: HashSet<i64> = input.excluded_issue_ids.into_iter().collect();
    if !excluded.is_subset(&issue_ids) { return Err("missing excluded issue".into()); }
    let unread: HashSet<i64> = input.issues.iter().filter(|i| i.status != "read")
        .map(|i| i.issue_id).collect();
    let mut restrictions: HashMap<i64, Vec<Blocker>> = HashMap::new();
    let mut list_ids = HashSet::new();

    for list in &input.lists {
        if !list_ids.insert(list.list_id) || !matches!(list.mode.as_str(), "strict" | "loose") {
            return Err("invalid list".into());
        }
        let mut placed = HashSet::new();
        for entry in &list.entries {
            if !placed.insert(entry.issue_id) || !issue_ids.contains(&entry.issue_id)
                || !matches!(entry.gate.as_str(), "none" | "hold" | "after_previous") {
                return Err("invalid list entry".into());
            }
        }
        let mut waiting: HashMap<&str, HashSet<&str>> = HashMap::new();
        for decision in &list.overlap_decisions {
            if decision.continuing_volume_id.is_empty() || decision.waiting_volume_id.is_empty()
                || decision.continuing_volume_id == decision.waiting_volume_id
                || !waiting.entry(&decision.continuing_volume_id)
                    .or_default().insert(&decision.waiting_volume_id) {
                return Err("invalid overlap decision".into());
            }
        }
        let entries: Vec<&Entry> = list.entries.iter()
            .filter(|e| !e.skipped && !excluded.contains(&e.issue_id)).collect();
        let mut earlier = Vec::<i64>::new();
        let mut hold_id = None;
        let mut hold_unread = Vec::<i64>::new();
        let mut previous = None;
        for entry in entries {
            let mut current = Vec::new();
            if unread.contains(&entry.issue_id) {
                if list.mode == "strict" {
                    let current_volume = issue_volume.get(&entry.issue_id).and_then(|v| v.as_deref());
                    let approved = current_volume.and_then(|v| waiting.get(v));
                    let predecessors: Vec<i64> = earlier.iter().copied().filter(|id| {
                        let before = issue_volume.get(id).and_then(|v| v.as_deref());
                        !before.is_some_and(|v| approved.is_some_and(|set| set.contains(v)))
                    }).collect();
                    if !predecessors.is_empty() {
                        current.push(blocker("strict_order", Some(list.list_id), predecessors, None));
                    }
                }
                if !hold_unread.is_empty() {
                    current.push(blocker("hold", Some(list.list_id), hold_unread.clone(), hold_id));
                }
                if entry.gate == "hold" && !earlier.is_empty() {
                    current.push(blocker("hold", Some(list.list_id), earlier.clone(), Some(entry.issue_id)));
                }
                if entry.gate == "after_previous" && previous.is_some_and(|p| unread.contains(&p)) {
                    current.push(blocker("after_previous", Some(list.list_id), vec![previous.unwrap()], Some(entry.issue_id)));
                }
                restrictions.entry(entry.issue_id).or_default().extend(current);
                earlier.push(entry.issue_id);
            }
            if entry.gate == "hold" {
                hold_id = Some(entry.issue_id);
                hold_unread = earlier.clone();
            }
            previous = Some(entry.issue_id);
        }
    }
    let mut prereq_ids = HashSet::new();
    for p in &input.prerequisites {
        if !prereq_ids.insert(p.prerequisite_id) || !issue_ids.contains(&p.source_issue_id)
            || !issue_ids.contains(&p.target_issue_id)
            || excluded.contains(&p.source_issue_id)
            || !matches!(p.origin.as_str(), "reader" | "converted") {
            return Err("invalid prerequisite".into());
        }
        if unread.contains(&p.source_issue_id) {
            let mut b = blocker("prerequisite", None, vec![p.source_issue_id], None);
            b.prerequisite_id = Some(p.prerequisite_id);
            b.origin = Some(p.origin.clone());
            b.provenance = p.provenance.clone();
            restrictions.entry(p.target_issue_id).or_default().push(b);
        }
    }
    let mut sorted_issues = input.issues;
    sorted_issues.sort_by_key(|i| (i.position, i.issue_id));
    let mut frontiers = HashMap::new();
    for i in sorted_issues {
        if unread.contains(&i.issue_id) && !excluded.contains(&i.issue_id) {
            frontiers.entry(i.thread_id).or_insert(i.issue_id);
        }
    }
    let mut threads = input.threads;
    threads.sort_by_key(|t| t.thread_id);
    let mut output = Vec::new();
    for t in threads {
        if t.status != "active" { continue; }
        let next = frontiers.get(&t.thread_id).copied();
        let mut blockers = next.and_then(|id| restrictions.remove(&id)).unwrap_or_default();
        blockers.sort_by(|a, b| {
            a.kind.cmp(&b.kind)
                .then_with(|| a.list_id.unwrap_or(-1).cmp(&b.list_id.unwrap_or(-1)))
                .then_with(|| a.gate_issue_id.unwrap_or(-1).cmp(&b.gate_issue_id.unwrap_or(-1)))
                .then_with(|| a.prerequisite_id.unwrap_or(-1).cmp(&b.prerequisite_id.unwrap_or(-1)))
                .then_with(|| a.waiting_on_issue_ids.cmp(&b.waiting_on_issue_ids))
        });
        output.push(Eligibility { thread_id: t.thread_id, next_issue_id: next,
                                  eligible: next.is_some() && blockers.is_empty(), blockers });
    }
    Ok(output)
}

fn main() {
    let mut raw = String::new();
    io::stdin().read_to_string(&mut raw).expect("read stdin");
    let snapshot: Snapshot = serde_json::from_str(&raw).expect("parse snapshot");
    match evaluate(snapshot) {
        Ok(result) => println!("{}", serde_json::to_string(&result).expect("serialize")),
        Err(err) => { eprintln!("invalid snapshot: {err}"); std::process::exit(1); }
    }
}
