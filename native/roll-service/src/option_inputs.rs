//! Complete owner-scoped Option E loader inputs, detached from eligibility evaluation.
use crate::{
    auth::AuthenticatedUser,
    db,
    reading_inputs::{
        self, CoreReadingInputs, ReadingIssue, ReadingThread, StoredThreadEligibility,
    },
    ApiError, AppState,
};
use axum::http::StatusCode;
use deadpool_postgres::Object;
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet, HashSet},
    time::Instant,
};
use tokio_postgres::{IsolationLevel, Transaction};
use unicode_casefold::UnicodeCaseFold;

#[derive(Debug, Serialize)]
pub struct ReadingEntry {
    pub issue_id: i32,
    pub gate: String,
    pub skipped: bool,
}
#[derive(Debug, Serialize)]
pub struct OverlapDecision {
    pub continuing_volume_id: String,
    pub waiting_volume_id: String,
}
#[derive(Debug, Serialize)]
pub struct ReadingList {
    pub list_id: i32,
    pub mode: String,
    pub entries: Vec<ReadingEntry>,
    pub overlap_decisions: Vec<OverlapDecision>,
}
#[derive(Debug, Serialize)]
pub struct Prerequisite {
    pub prerequisite_id: i32,
    pub source_issue_id: i32,
    pub target_issue_id: i32,
    pub origin: String,
    pub provenance: Vec<String>,
}
#[derive(Debug, Serialize, PartialEq, Eq, PartialOrd, Ord)]
pub struct UnresolvedReference {
    pub kind: &'static str,
    pub object_id: i32,
}
#[derive(Debug, Serialize)]
pub struct OptionInputs {
    pub core: CoreReadingInputs,
    pub thread_volumes: BTreeMap<i32, String>,
    pub lists: Vec<ReadingList>,
    pub prerequisites: Vec<Prerequisite>,
    pub excluded_issue_ids: BTreeSet<i32>,
    pub unresolved: Vec<UnresolvedReference>,
}
impl OptionInputs {
    /// Refuse incomplete constraints before an evaluator can use this snapshot.
    pub fn require_resolved(&self) -> Result<(), ApiError> {
        let invalid_lists = self.lists.iter().any(|list| {
            let mut decisions = HashSet::new();
            list.overlap_decisions.iter().any(|d| {
                d.continuing_volume_id == d.waiting_volume_id
                    || !decisions.insert((&d.continuing_volume_id, &d.waiting_volume_id))
            })
        });
        if invalid_lists
            || !self.unresolved.is_empty()
            || !reading_inputs::valid_references(&self.core)
        {
            Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Unresolved reading reference",
            ))
        } else {
            Ok(())
        }
    }
}
// Numeric strings need not fit a machine integer (Python uses arbitrary precision).
fn normalize_volume(provider: &str, external_id: &str) -> (String, String) {
    let provider = provider.trim().case_fold().collect::<String>();
    let value = external_id.trim();
    let digits = value.strip_prefix("4050-").unwrap_or(value);
    let value = if provider == "comicvine"
        && !digits.is_empty()
        && digits.bytes().all(|b| b.is_ascii_digit())
    {
        let significant = digits.trim_start_matches('0');
        if significant.is_empty() {
            "0"
        } else {
            significant
        }
    } else {
        value
    };
    (provider, value.into())
}
fn volume_key(provider: &str, external_id: &str) -> Option<String> {
    let (provider, value) = normalize_volume(provider, external_id);
    (provider == "comicvine").then(|| format!("comicvine:{value}"))
}

// Collect independent, owner-scoped datasets without multiplying list entries by
// issues or prerequisites. This is one PostgreSQL statement, not nine sequential
// network round trips. Eligibility remains exclusively in the Rust Option E evaluator.
const SNAPSHOT_SQL: &str = r#"
WITH
owned_threads AS MATERIALIZED (
    SELECT id, status, title, next_unread_issue_id, is_blocked,
           queue_position, catalog_series_id
    FROM threads WHERE user_id = $1
),
owned_issues AS MATERIALIZED (
    SELECT i.id, i.thread_id, i.position, i.status, i.issue_number,
           i.catalog_issue_id
    FROM issues i JOIN owned_threads t ON t.id = i.thread_id
),
owned_lists AS (
    SELECT id, mode FROM custom_cbl_lists WHERE user_id = $1
),
owned_entries AS (
    SELECT e.id, e.list_id, e.issue_id, e.gate, e.skipped, e.position
    FROM custom_cbl_entries e
    JOIN owned_lists l ON l.id = e.list_id
),
reader_prerequisites AS (
    SELECT d.id, d.source_issue_id, d.target_issue_id,
           d.classification, d.provenance
    FROM dependencies d
    WHERE d.origin = 'reader'
      AND (EXISTS (SELECT 1 FROM owned_issues i WHERE i.id = d.source_issue_id)
        OR EXISTS (SELECT 1 FROM owned_issues i WHERE i.id = d.target_issue_id))
),
volume_evidence AS (
    SELECT t.id AS thread_id, e.provider, e.external_id, e.entity_type
    FROM owned_threads t
    JOIN thread_external_series_mappings m ON m.thread_id = t.id
    JOIN external_identities e ON e.id = m.external_identity_id
    WHERE m.status = 'confirmed'
    UNION ALL
    SELECT t.id AS thread_id, e.provider, e.external_id, e.entity_type
    FROM owned_threads t
    JOIN catalog_series s ON s.id = t.catalog_series_id
    JOIN external_identities e ON e.id = s.canonical_external_identity_id
),
overlap_rows AS (
    SELECT d.id, d.list_id, c.provider AS continuing_provider,
           c.external_id AS continuing_external_id,
           w.provider AS waiting_provider, w.external_id AS waiting_external_id
    FROM custom_cbl_overlap_decisions d
    JOIN external_identities c ON c.id = d.continuing_external_identity_id
    JOIN external_identities w ON w.id = d.waiting_external_identity_id
    JOIN owned_lists l ON l.id = d.list_id
    WHERE d.user_id = $1
),
exclusion_rows AS (
    SELECT issue_id, thread_id, provider, external_volume_id
    FROM collection_exclusions WHERE user_id = $1
),
issue_volume_rows AS (
    SELECT i.id AS issue_id, e.provider, e.external_id
    FROM owned_issues i
    JOIN catalog_issues ci ON ci.id = i.catalog_issue_id
    JOIN catalog_series s ON s.id = ci.catalog_series_id
    JOIN external_identities e ON e.id = s.canonical_external_identity_id
)
SELECT jsonb_build_object(
    'threads', COALESCE((SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)
                         FROM owned_threads t), '[]'::jsonb),
    'issues', COALESCE((SELECT jsonb_agg(to_jsonb(i)
                         ORDER BY i.thread_id, i.position, i.id)
                        FROM owned_issues i), '[]'::jsonb),
    'lists', COALESCE((SELECT jsonb_agg(to_jsonb(l) ORDER BY l.id)
                       FROM owned_lists l), '[]'::jsonb),
    'entries', COALESCE((SELECT jsonb_agg(to_jsonb(e)
                         ORDER BY e.list_id, e.position, e.id)
                         FROM owned_entries e), '[]'::jsonb),
    'prerequisites', COALESCE((SELECT jsonb_agg(to_jsonb(p) ORDER BY p.id)
                              FROM reader_prerequisites p), '[]'::jsonb),
    'evidence', COALESCE((SELECT jsonb_agg(to_jsonb(v))
                         FROM volume_evidence v), '[]'::jsonb),
    'overlaps', COALESCE((SELECT jsonb_agg(to_jsonb(o) ORDER BY o.id)
                         FROM overlap_rows o), '[]'::jsonb),
    'exclusions', COALESCE((SELECT jsonb_agg(to_jsonb(x))
                           FROM exclusion_rows x), '[]'::jsonb),
    'issue_volumes', COALESCE((SELECT jsonb_agg(to_jsonb(v))
                              FROM issue_volume_rows v), '[]'::jsonb)
)::text
"#;

#[derive(Deserialize)]
struct SnapshotRows {
    threads: Vec<ThreadRow>,
    issues: Vec<IssueRow>,
    lists: Vec<ListRow>,
    entries: Vec<EntryRow>,
    prerequisites: Vec<PrerequisiteRow>,
    evidence: Vec<VolumeEvidenceRow>,
    overlaps: Vec<OverlapRow>,
    exclusions: Vec<ExclusionRow>,
    issue_volumes: Vec<IssueVolumeRow>,
}
#[derive(Deserialize)]
struct ThreadRow {
    id: i32,
    status: String,
    title: String,
    next_unread_issue_id: Option<i32>,
    is_blocked: bool,
    queue_position: i32,
}
#[derive(Deserialize)]
struct IssueRow {
    id: i32,
    thread_id: i32,
    position: i32,
    status: String,
    issue_number: String,
}
#[derive(Deserialize)]
struct ListRow {
    id: i32,
    mode: String,
}
#[derive(Deserialize)]
struct EntryRow {
    id: i32,
    list_id: i32,
    issue_id: i32,
    gate: String,
    skipped: bool,
}
#[derive(Deserialize)]
struct PrerequisiteRow {
    id: i32,
    source_issue_id: i32,
    target_issue_id: i32,
    classification: Option<String>,
    provenance: Option<String>,
}
#[derive(Deserialize)]
struct VolumeEvidenceRow {
    thread_id: i32,
    provider: String,
    external_id: String,
    entity_type: String,
}
#[derive(Deserialize)]
struct OverlapRow {
    list_id: i32,
    continuing_provider: String,
    continuing_external_id: String,
    waiting_provider: String,
    waiting_external_id: String,
}
#[derive(Deserialize)]
struct ExclusionRow {
    issue_id: Option<i32>,
    thread_id: Option<i32>,
    provider: Option<String>,
    external_volume_id: Option<String>,
}
#[derive(Deserialize)]
struct IssueVolumeRow {
    issue_id: i32,
    provider: String,
    external_id: String,
}

async fn load_transaction(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
) -> Result<OptionInputs, ApiError> {
    let row = tx
        .query_one(SNAPSHOT_SQL, &[&user.id()])
        .await
        .map_err(db::query_error)?;
    let encoded: String = row.try_get(0).map_err(db::query_error)?;
    let snapshot: SnapshotRows = serde_json::from_str(&encoded).map_err(|error| {
        tracing::error!(%error, "Invalid Option E snapshot response");
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Invalid reading snapshot",
        )
    })?;
    assemble_snapshot(snapshot)
}

fn assemble_snapshot(snapshot: SnapshotRows) -> Result<OptionInputs, ApiError> {
    let core = CoreReadingInputs {
        threads: snapshot
            .threads
            .iter()
            .map(|t| ReadingThread {
                id: t.id,
                status: t.status.clone(),
                title: t.title.clone(),
            })
            .collect(),
        issues: snapshot
            .issues
            .iter()
            .map(|i| ReadingIssue {
                id: i.id,
                thread_id: i.thread_id,
                position: i.position,
                status: i.status.clone(),
                issue_number: i.issue_number.clone(),
            })
            .collect(),
        stored: snapshot
            .threads
            .iter()
            .map(|t| StoredThreadEligibility {
                thread_id: t.id,
                next_issue_id: t.next_unread_issue_id,
                is_blocked: t.is_blocked,
                queue_position: t.queue_position,
            })
            .collect(),
    };
    let owned: HashSet<_> = core.issues.iter().map(|i| i.id).collect();
    let mut unresolved = Vec::new();
    let mut lists = BTreeMap::new();
    for row in snapshot.lists {
        lists.insert(
            row.id,
            ReadingList {
                list_id: row.id,
                mode: row.mode,
                entries: vec![],
                overlap_decisions: vec![],
            },
        );
    }
    for row in snapshot.entries {
        if !owned.contains(&row.issue_id) {
            unresolved.push(UnresolvedReference {
                kind: "list_entry",
                object_id: row.id,
            });
        }
        let list = lists.get_mut(&row.list_id).ok_or(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Invalid reading snapshot",
        ))?;
        list.entries.push(ReadingEntry {
            issue_id: row.issue_id,
            gate: row.gate,
            skipped: row.skipped,
        });
    }
    let mut prerequisites = vec![];
    for row in snapshot.prerequisites {
        if !owned.contains(&row.source_issue_id) || !owned.contains(&row.target_issue_id) {
            unresolved.push(UnresolvedReference {
                kind: "prerequisite",
                object_id: row.id,
            });
        }
        prerequisites.push(Prerequisite {
            prerequisite_id: row.id,
            source_issue_id: row.source_issue_id,
            target_issue_id: row.target_issue_id,
            origin: "reader".into(),
            provenance: vec![
                format!(
                    "classification:{}",
                    row.classification.as_deref().unwrap_or("None")
                ),
                row.provenance.unwrap_or_default(),
            ],
        });
    }
    let mut evidence = vec![];
    let mut candidates: BTreeMap<i32, BTreeSet<String>> = BTreeMap::new();
    for row in snapshot.evidence {
        if row.entity_type == "series" {
            if let Some(key) = volume_key(&row.provider, &row.external_id) {
                candidates.entry(row.thread_id).or_default().insert(key);
            }
        }
        evidence.push((
            row.thread_id,
            normalize_volume(&row.provider, &row.external_id),
        ));
    }
    let thread_volumes = candidates
        .into_iter()
        .filter_map(|(id, mut keys)| (keys.len() == 1).then(|| (id, keys.pop_first().unwrap())))
        .collect();
    for row in snapshot.overlaps {
        if let (Some(c), Some(w)) = (
            volume_key(&row.continuing_provider, &row.continuing_external_id),
            volume_key(&row.waiting_provider, &row.waiting_external_id),
        ) {
            let list = lists.get_mut(&row.list_id).ok_or(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Invalid reading snapshot",
            ))?;
            list.overlap_decisions.push(OverlapDecision {
                continuing_volume_id: c,
                waiting_volume_id: w,
            });
        }
    }
    let mut excluded_issues = HashSet::new();
    let mut excluded_threads = HashSet::new();
    let mut excluded_volumes = HashSet::new();
    for row in snapshot.exclusions {
        if let Some(id) = row.issue_id {
            excluded_issues.insert(id);
        }
        if let Some(id) = row.thread_id {
            excluded_threads.insert(id);
        }
        if let (Some(p), Some(v)) = (row.provider, row.external_volume_id) {
            excluded_volumes.insert(normalize_volume(&p, &v));
        }
    }
    for (id, key) in evidence {
        if excluded_volumes.contains(&key) {
            excluded_threads.insert(id);
        }
    }
    for row in snapshot.issue_volumes {
        if excluded_volumes.contains(&normalize_volume(&row.provider, &row.external_id)) {
            excluded_issues.insert(row.issue_id);
        }
    }
    let excluded_issue_ids = core
        .issues
        .iter()
        .filter(|i| excluded_issues.contains(&i.id) || excluded_threads.contains(&i.thread_id))
        .map(|i| i.id)
        .collect();
    unresolved.sort();
    Ok(OptionInputs {
        core,
        thread_volumes,
        lists: lists.into_values().collect(),
        prerequisites,
        excluded_issue_ids,
        unresolved,
    })
}
struct Pending(Option<Object>);
impl Drop for Pending {
    fn drop(&mut self) {
        if let Some(c) = self.0.take() {
            drop(c);
        }
    }
}
/// Read all Option E constraints in one SQL statement inside a bounded, repeatable-read, read-only transaction.
/// Diagnostics contain owned entry/dependency IDs only, never foreign titles or metadata.
/// Diagnostic-only: preserves unresolved IDs for comparison, never for execution.
pub async fn load_option_diagnostics(
    state: &AppState,
    user: AuthenticatedUser,
) -> Result<OptionInputs, ApiError> {
    let started = Instant::now();
    let mut pending = Pending(Some(db::checkout(state).await?));
    let result = tokio::time::timeout(state.request_timeout, async {
        let tx = pending
            .0
            .as_mut()
            .unwrap()
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(db::query_error)?;
        let inputs = load_transaction(&tx, user).await?;
        tx.rollback().await.map_err(db::query_error)?;
        Ok::<_, ApiError>(inputs)
    })
    .await;
    match result {
        Err(_) => Err(ApiError(
            StatusCode::SERVICE_UNAVAILABLE,
            "Database temporarily unavailable",
        )),
        Ok(Err(error)) => Err(error),
        Ok(Ok(inputs)) => {
            drop(pending.0.take());
            tracing::info!(
                query_count = 1,
                elapsed_us = started.elapsed().as_micros() as u64,
                unresolved_count = inputs.unresolved.len(),
                "Option E inputs loaded"
            );
            Ok(inputs)
        }
    }
}
/// Load execution inputs, failing closed on missing or foreign constraint endpoints.
pub async fn load_option_inputs(
    state: &AppState,
    user: AuthenticatedUser,
) -> Result<crate::reading_constraints::ValidatedReadingInputs, ApiError> {
    let inputs = load_option_diagnostics(state, user).await?;
    crate::reading_constraints::ValidatedReadingInputs::new(inputs, &BTreeMap::new()).map_err(
        |error| match error {
            crate::reading_constraints::ValidationError::Cycle { .. } => ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Reading constraint cycle",
            ),
            crate::reading_constraints::ValidationError::InvalidSnapshot { .. } => ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Unresolved reading reference",
            ),
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    fn decision(continuing: &str, waiting: &str) -> OverlapDecision {
        OverlapDecision {
            continuing_volume_id: continuing.into(),
            waiting_volume_id: waiting.into(),
        }
    }

    #[test]
    fn overlap_validation_rejects_self_and_duplicate_pairs_per_list() {
        let mut inputs = OptionInputs {
            core: CoreReadingInputs {
                threads: vec![],
                issues: vec![],
                stored: vec![],
            },
            thread_volumes: BTreeMap::new(),
            lists: vec![],
            prerequisites: vec![],
            excluded_issue_ids: BTreeSet::new(),
            unresolved: vec![],
        };
        assert!(inputs.require_resolved().is_ok());
        inputs.lists.push(ReadingList {
            list_id: 10,
            mode: "strict".into(),
            entries: vec![],
            overlap_decisions: vec![decision("comicvine:12", "comicvine:12")],
        });
        assert!(inputs.require_resolved().is_err());
        inputs.lists[0].overlap_decisions = vec![
            decision("comicvine:12", "comicvine:13"),
            decision("comicvine:12", "comicvine:13"),
        ];
        assert!(inputs.require_resolved().is_err());
        inputs.lists[0].overlap_decisions[1] = decision("comicvine:12", "comicvine:14");
        assert!(inputs.require_resolved().is_ok());
        // Deduplication is list-local: another list may approve the same pair.
        inputs.lists.push(ReadingList {
            list_id: 11,
            mode: "strict".into(),
            entries: vec![],
            overlap_decisions: vec![decision("comicvine:12", "comicvine:13")],
        });
        assert!(inputs.require_resolved().is_ok());
    }

    #[test]
    fn numeric_volume_identity_is_exact_and_unbounded() {
        assert_eq!(
            volume_key(" ComicVine ", " 4050-000123 "),
            Some("comicvine:123".into())
        );
        assert_eq!(volume_key("comicvine", "000"), Some("comicvine:0".into()));
        assert_eq!(
            volume_key("comicvine", "4050-99999999999999999999999999"),
            Some("comicvine:99999999999999999999999999".into())
        );
        assert_eq!(
            volume_key("comicvine", "comicvine:123"),
            Some("comicvine:comicvine:123".into())
        );
        assert_eq!(volume_key("other", "123"), None);
        assert_eq!(
            normalize_volume(" STRAẞE ", "0012"),
            ("strasse".into(), "0012".into())
        );
    }
    #[test]
    fn cte_snapshot_preserves_option_e_order_exclusions_and_provenance() {
        let snapshot: SnapshotRows = serde_json::from_value(serde_json::json!({
            "threads": [
                {"id": 1, "status": "active", "title": "Alpha",
                 "next_unread_issue_id": 10, "is_blocked": true, "queue_position": 1},
                {"id": 2, "status": "active", "title": "Beta",
                 "next_unread_issue_id": 20, "is_blocked": false, "queue_position": 2}
            ],
            "issues": [
                {"id": 10, "thread_id": 1, "position": 1, "status": "unread",
                 "issue_number": "1"},
                {"id": 20, "thread_id": 2, "position": 1, "status": "unread",
                 "issue_number": "1"}
            ],
            "lists": [{"id": 50, "mode": "strict"}, {"id": 51, "mode": "loose"}],
            "entries": [
                {"id": 100, "list_id": 50, "issue_id": 10,
                 "gate": "after_previous", "skipped": false},
                {"id": 101, "list_id": 50, "issue_id": 20,
                 "gate": "hold", "skipped": false},
                {"id": 102, "list_id": 51, "issue_id": 20,
                 "gate": "after_previous", "skipped": true}
            ],
            "prerequisites": [
                {"id": 90, "source_issue_id": 10, "target_issue_id": 20,
                 "classification": "manual", "provenance": "reader"}
            ],
            "evidence": [
                {"thread_id": 1, "provider": "ComicVine",
                 "external_id": "4050-0007", "entity_type": "series"},
                {"thread_id": 2, "provider": "comicvine",
                 "external_id": "0008", "entity_type": "series"}
            ],
            "overlaps": [
                {"list_id": 50, "continuing_provider": "comicvine",
                 "continuing_external_id": "7", "waiting_provider": "comicvine",
                 "waiting_external_id": "8"}
            ],
            "exclusions": [
                {"issue_id": null, "thread_id": null,
                 "provider": "comicvine", "external_volume_id": "0007"}
            ],
            "issue_volumes": [
                {"issue_id": 10, "provider": "comicvine", "external_id": "7"},
                {"issue_id": 20, "provider": "comicvine", "external_id": "8"}
            ]
        }))
        .unwrap();
        let mut inputs = assemble_snapshot(snapshot).unwrap();
        assert!(inputs.require_resolved().is_ok());
        assert_eq!(inputs.lists.len(), 2);
        assert_eq!(inputs.lists[0].entries[0].issue_id, 10);
        assert_eq!(inputs.lists[0].entries[1].gate, "hold");
        assert!(inputs.lists[1].entries[0].skipped);
        assert_eq!(inputs.prerequisites.len(), 1);
        assert_eq!(inputs.prerequisites[0].origin, "reader");
        assert_eq!(inputs.thread_volumes.get(&1).unwrap(), "comicvine:7");
        assert_eq!(inputs.thread_volumes.get(&2).unwrap(), "comicvine:8");
        assert!(inputs.excluded_issue_ids.contains(&10));
        assert!(!inputs.excluded_issue_ids.contains(&20));
        assert_eq!(inputs.lists[0].overlap_decisions.len(), 1);
        inputs.prerequisites[0].target_issue_id = 999;
        // An unresolved foreign reference cannot be made live by a snapshot.
        inputs.unresolved.push(UnresolvedReference {
            kind: "prerequisite",
            object_id: 90,
        });
        assert!(inputs.require_resolved().is_err());
    }

    #[test]
    fn cte_snapshot_decodes_all_empty_aggregates() {
        let snapshot: SnapshotRows = serde_json::from_value(serde_json::json!({
            "threads": [], "issues": [], "lists": [], "entries": [],
            "prerequisites": [], "evidence": [], "overlaps": [],
            "exclusions": [], "issue_volumes": []
        }))
        .unwrap();
        let inputs = assemble_snapshot(snapshot).unwrap();
        assert!(inputs.require_resolved().is_ok());
        assert!(inputs.core.issues.is_empty());
    }
}
