//! Complete owner-scoped Option E loader inputs, detached from eligibility evaluation.
use crate::{
    auth::AuthenticatedUser,
    db,
    reading_inputs::{
        self, CoreReadingInputs, ReadingIssue, ReadingThread, StoredThreadEligibility,
    },
    ApiError, AppState,
};
use deadpool_postgres::Object;
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet, HashSet},
    sync::OnceLock,
    time::Instant,
};
use tokio_postgres::{IsolationLevel, Transaction};
use unicode_casefold::UnicodeCaseFold;

#[derive(Debug, Clone, Serialize)]
pub struct ReadingEntry {
    pub issue_id: i32,
    pub gate: String,
    pub skipped: bool,
}
#[derive(Debug, Clone, Serialize)]
pub struct OverlapDecision {
    pub continuing_volume_id: String,
    pub waiting_volume_id: String,
}
#[derive(Debug, Clone, Serialize)]
pub struct ReadingList {
    pub list_id: i32,
    pub mode: String,
    /// Internal diagnostics only. The Python parity/debug projection does not
    /// serialize list titles, so keep this out of the shared wire shape.
    #[serde(skip_serializing)]
    pub name: String,
    pub entries: Vec<ReadingEntry>,
    pub overlap_decisions: Vec<OverlapDecision>,
}
#[derive(Debug, Clone, Serialize)]
pub struct Prerequisite {
    pub prerequisite_id: i32,
    pub source_issue_id: i32,
    pub target_issue_id: i32,
    pub origin: String,
    pub provenance: Vec<String>,
}
#[derive(Debug, Clone, Serialize, PartialEq, Eq, PartialOrd, Ord)]
pub struct UnresolvedReference {
    pub kind: &'static str,
    pub object_id: i32,
}
#[derive(Debug, Clone, Serialize)]
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
            Err(ApiError::Internal(
                "Unresolved reading reference".to_string(),
            ))
        } else {
            Ok(())
        }
    }
}
// Numeric strings need not fit a machine integer (Python uses arbitrary precision).
pub(crate) fn normalize_volume(provider: &str, external_id: &str) -> (String, String) {
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
//
// MEMORY CONSIDERATION: This query aggregates all owner-scoped data into a single JSONB response.
// For users with thousands of threads/issues/lists/entries, this could produce large responses
// (tens of MB). The risk of memory pressure on both PostgreSQL (JSONB aggregation) and the
// Rust client (deserialization) is acknowledged. This optimization targets the observed 17-call
// bootstrap total; remaining session and presentation reads are still separate.
//
// TODO: Consider defensive pagination or payload limiting if memory usage becomes problematic
// in production. Monitor payload sizes and consider adding a LIMIT clause for large datasets.
//
// The statement is split into its CTE body and its JSON projection so the
// same owner-scoped constraints can be assembled with different owner-id
// sources. Every owned row is filtered by the single `me` CTE, which the
// caller declares: the pre-authenticated loader binds the verified owner id,
// while the single-statement resource loader resolves it from the folded
// authentication CTE. One constraint set, two owner-id sources.
pub(crate) const SNAPSHOT_CTES: &str = r#"owned_threads AS MATERIALIZED (
    SELECT id, status, title, next_unread_issue_id, is_blocked,
           queue_position, catalog_series_id
    FROM threads WHERE user_id = (SELECT user_id FROM me)
),
owned_issues AS MATERIALIZED (
    SELECT i.id, i.thread_id, i.position, i.status, i.issue_number,
           i.catalog_issue_id
    FROM issues i JOIN owned_threads t ON t.id = i.thread_id
    WHERE i.merged_into_issue_id IS NULL
),
owned_lists AS (
    SELECT id, mode, name FROM custom_cbl_lists WHERE user_id = (SELECT user_id FROM me)
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
    -- Read-only catalog fallback: a confirmed mapping is the authority, but a
    -- thread whose canonical series identity exists only in catalog_series must
    -- keep its existing volume evidence until the #3221/#3231 census proves no
    -- such reader rows remain. Bounded by owned_threads and owner scope, with no title inference.
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
    WHERE d.user_id = (SELECT user_id FROM me)
),
exclusion_rows AS (
    SELECT issue_id, thread_id, provider, external_volume_id
    FROM collection_exclusions WHERE user_id = (SELECT user_id FROM me)
),
issue_volume_rows AS (
    SELECT DISTINCT i.id AS issue_id, ei.provider, ei.external_id
    FROM owned_issues i
    JOIN issue_external_identity_mappings ieim ON ieim.issue_id = i.id AND ieim.status = 'confirmed'
    JOIN external_identities ei ON ei.id = ieim.external_identity_id
    WHERE ei.entity_type = 'series'
    UNION
    SELECT DISTINCT i.id AS issue_id, ei.provider,
           COALESCE(
               NULLIF(ei.metadata_json->>'volume_id', ''),
               NULLIF(ei.metadata_json->'volume'->>'id', '')
           ) AS external_id
    FROM owned_issues i
    JOIN issue_external_identity_mappings ieim ON ieim.issue_id = i.id AND ieim.status = 'confirmed'
    JOIN external_identities ei ON ei.id = ieim.external_identity_id
    WHERE COALESCE(NULLIF(ei.metadata_json->>'volume_id', ''), NULLIF(ei.metadata_json->'volume'->>'id', '')) IS NOT NULL
    UNION
    SELECT DISTINCT i.id AS issue_id, ei.provider, ei.external_id
    FROM owned_issues i
    JOIN thread_external_series_mappings tesm ON tesm.thread_id = i.thread_id AND tesm.status = 'confirmed'
    JOIN external_identities ei ON ei.id = tesm.external_identity_id
    WHERE ei.entity_type = 'series'
    UNION
    -- Read-only catalog fallback for catalog-only links: an issue that has no
    -- confirmed issue/thread mapping still carries canonical volume evidence
    -- through catalog_issues -> catalog_series -> canonical external identity.
    -- Retained until the #3221/#3231 census/rehearsal proves none remain. The
    -- UNION deduplicates identical evidence already derived from mappings.
    SELECT i.id AS issue_id, e.provider, e.external_id
    FROM owned_issues i
    JOIN catalog_issues ci ON ci.id = i.catalog_issue_id
    JOIN catalog_series s ON s.id = ci.catalog_series_id
    JOIN external_identities e ON e.id = s.canonical_external_identity_id
)"#;

/// The snapshot JSON projection over [`SNAPSHOT_CTES`].
///
/// The projection is a CTE rather than the statement's final `SELECT` so one
/// caller can embed the snapshot inside a larger single-statement response
/// instead of issuing a second statement for the same owner-scoped data.
pub(crate) const SNAPSHOT_PROJECTION: &str = r#"snapshot AS (
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
    ) AS value
)"#;

/// The owner-scoped snapshot statement for an already authenticated owner.
///
/// The verified owner id is bound as `$1`, so this loader never issues an
/// authentication statement of its own.
fn preauthenticated_statement() -> &'static str {
    static SQL: OnceLock<String> = OnceLock::new();
    SQL.get_or_init(|| {
        format!(
            "WITH me AS (SELECT $1::int AS user_id),\n{SNAPSHOT_CTES},\n{SNAPSHOT_PROJECTION}\nSELECT value::text FROM snapshot"
        )
    })
}

/// The snapshot statement plus the inert legacy/converted dependency evidence
/// for the read-only frontier audit (#4198), in one statement over the same
/// owner-scoped CTEs. The rows never enter the evaluator: the Option E
/// snapshot keeps loading only `origin='reader'` prerequisites, so converted
/// and legacy edges stay inert (#2366, #3676).
fn frontier_diagnostics_statement() -> &'static str {
    static SQL: OnceLock<String> = OnceLock::new();
    SQL.get_or_init(|| {
        format!(
            "WITH me AS (SELECT $1::int AS user_id),\n{SNAPSHOT_CTES},\n{SNAPSHOT_PROJECTION},\n\
             legacy_dependency_rows AS (\n\
             \x20 SELECT d.id, d.source_issue_id, d.target_issue_id, d.origin,\n\
             \x20        d.classification, d.provenance, d.note,\n\
             \x20        (si.id IS NOT NULL) AS source_owned\n\
             \x20 FROM dependencies d\n\
             \x20 JOIN owned_issues ti ON ti.id = d.target_issue_id AND ti.status = 'unread'\n\
             \x20 LEFT JOIN owned_issues si ON si.id = d.source_issue_id\n\
             \x20 WHERE d.origin IS DISTINCT FROM 'reader'\n\
             \x20   AND (si.id IS NULL OR si.status <> 'read')\n\
             )\n\
             SELECT snapshot.value::text,\n\
                    COALESCE((SELECT jsonb_agg(to_jsonb(x) ORDER BY x.id)\n\
                              FROM legacy_dependency_rows x), '[]'::jsonb)::text\n\
             FROM snapshot"
        )
    })
}

#[derive(Debug, Deserialize)]
pub(crate) struct SnapshotRows {
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
#[derive(Debug, Deserialize)]
struct ThreadRow {
    id: i32,
    status: String,
    title: String,
    next_unread_issue_id: Option<i32>,
    is_blocked: bool,
    queue_position: i32,
}
#[derive(Debug, Deserialize)]
struct IssueRow {
    id: i32,
    thread_id: i32,
    position: i32,
    status: String,
    issue_number: String,
}
#[derive(Debug, Deserialize)]
struct ListRow {
    id: i32,
    mode: String,
    name: String,
}
#[derive(Debug, Deserialize)]
struct EntryRow {
    id: i32,
    list_id: i32,
    issue_id: i32,
    gate: String,
    skipped: bool,
}
#[derive(Debug, Deserialize)]
struct PrerequisiteRow {
    id: i32,
    source_issue_id: i32,
    target_issue_id: i32,
    classification: Option<String>,
    provenance: Option<String>,
}
#[derive(Debug, Deserialize)]
struct VolumeEvidenceRow {
    thread_id: i32,
    provider: String,
    external_id: String,
    entity_type: String,
}
#[derive(Debug, Deserialize)]
struct OverlapRow {
    list_id: i32,
    continuing_provider: String,
    continuing_external_id: String,
    waiting_provider: String,
    waiting_external_id: String,
}
#[derive(Debug, Deserialize)]
struct ExclusionRow {
    issue_id: Option<i32>,
    thread_id: Option<i32>,
    provider: Option<String>,
    external_volume_id: Option<String>,
}
#[derive(Debug, Deserialize)]
struct IssueVolumeRow {
    issue_id: i32,
    provider: String,
    external_id: String,
}

/// One inert legacy/converted dependency row that points at an owned unread
/// issue from a source that is not read (or is foreign). Loaded for the
/// read-only frontier audit only (#4198): these rows never enter the Option E
/// evaluator, which keeps converted and legacy edges inert (#2366, #3676).
#[derive(Debug, Clone, Deserialize)]
pub struct LegacyDependencyRow {
    pub id: i32,
    pub source_issue_id: i32,
    pub target_issue_id: i32,
    pub origin: Option<String>,
    pub classification: Option<String>,
    pub provenance: Option<String>,
    pub note: Option<String>,
    pub source_owned: bool,
}

/// Read-only owner diagnostics plus the inert legacy dependency evidence the
/// Option E snapshot deliberately ignores.
#[derive(Debug)]
pub struct OptionDiagnostics {
    pub inputs: OptionInputs,
    pub legacy_dependencies: Vec<LegacyDependencyRow>,
}

async fn load_transaction(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
) -> Result<OptionInputs, ApiError> {
    let row = tx
        .query_one(preauthenticated_statement(), &[&user.id()])
        .await
        .map_err(db::query_error)?;
    let encoded: String = row.try_get(0).map_err(db::query_error)?;
    let snapshot: SnapshotRows = serde_json::from_str(&encoded).map_err(|error| {
        tracing::error!(%error, "Invalid Option E snapshot response");
        ApiError::Internal("Invalid reading snapshot".to_string())
    })?;
    assemble_snapshot(snapshot)
}

/// Assemble the owner snapshot plus the inert legacy evidence rows in one
/// decoded response. Diagnostic-only: the legacy rows are audit evidence,
/// never execution input.
async fn load_frontier_diagnostics_transaction(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
) -> Result<OptionDiagnostics, ApiError> {
    let row = tx
        .query_one(frontier_diagnostics_statement(), &[&user.id()])
        .await
        .map_err(db::query_error)?;
    let encoded: String = row.try_get(0).map_err(db::query_error)?;
    let snapshot: SnapshotRows = serde_json::from_str(&encoded).map_err(|error| {
        tracing::error!(%error, "Invalid Option E snapshot response");
        ApiError::Internal("Invalid reading snapshot".to_string())
    })?;
    let inputs = assemble_snapshot(snapshot)?;
    let legacy_encoded: String = row.try_get(1).map_err(db::query_error)?;
    let legacy_dependencies: Vec<LegacyDependencyRow> = serde_json::from_str(&legacy_encoded)
        .map_err(|error| {
            tracing::error!(%error, "Invalid legacy dependency diagnostics response");
            ApiError::Internal("Invalid reading snapshot".to_string())
        })?;
    Ok(OptionDiagnostics {
        inputs,
        legacy_dependencies,
    })
}

/// Assemble the validated Option E inputs from one decoded snapshot.
///
/// The caller owns the statement that produced the snapshot; this only turns
/// the owner-scoped rows into the evaluator's inputs and fails closed on a
/// row that references data the reader does not own.
pub(crate) fn assemble_snapshot(snapshot: SnapshotRows) -> Result<OptionInputs, ApiError> {
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
                name: row.name,
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
        let list = lists
            .get_mut(&row.list_id)
            .ok_or(ApiError::Internal("Invalid reading snapshot".to_string()))?;
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
        .filter_map(|(id, mut keys)| {
            if keys.len() == 1 {
                keys.pop_first().map(|key| (id, key))
            } else {
                None
            }
        })
        .collect();
    for row in snapshot.overlaps {
        if let (Some(c), Some(w)) = (
            volume_key(&row.continuing_provider, &row.continuing_external_id),
            volume_key(&row.waiting_provider, &row.waiting_external_id),
        ) {
            let list = lists
                .get_mut(&row.list_id)
                .ok_or(ApiError::Internal("Invalid reading snapshot".to_string()))?;
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
        #[allow(clippy::unwrap_used)]
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
        Err(e) => {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            Err(ApiError::DatabaseUnavailable)
        }
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
/// Validate loaded inputs, failing closed on missing or foreign constraint endpoints.
pub(crate) fn validated(
    inputs: OptionInputs,
) -> Result<crate::reading_constraints::ValidatedReadingInputs, ApiError> {
    let names = list_names(&inputs);
    crate::reading_constraints::ValidatedReadingInputs::new(inputs, &names).map_err(|error| {
        match error {
            crate::reading_constraints::ValidationError::Cycle { .. } => {
                ApiError::Internal("Reading constraint cycle".to_string())
            }
            crate::reading_constraints::ValidationError::InvalidSnapshot { .. } => {
                ApiError::Internal("Unresolved reading reference".to_string())
            }
        }
    })
}

fn list_names(inputs: &OptionInputs) -> BTreeMap<i32, String> {
    inputs
        .lists
        .iter()
        .map(|list| (list.list_id, list.name.clone()))
        .collect()
}

/// Validate for a read path: isolate cyclic components instead of failing the request.
pub(crate) fn validated_contained(
    inputs: OptionInputs,
) -> Result<crate::reading_constraints::ValidatedReadingInputs, ApiError> {
    let names = list_names(&inputs);
    crate::reading_constraints::ValidatedReadingInputs::contained(inputs, &names).map_err(|error| {
        match error {
            crate::reading_constraints::ValidationError::Cycle { .. } => {
                ApiError::Internal("Reading constraint cycle".to_string())
            }
            crate::reading_constraints::ValidationError::InvalidSnapshot { .. } => {
                ApiError::Internal("Unresolved reading reference".to_string())
            }
        }
    })
}

/// Read the Option E constraints plus the inert legacy dependency evidence in
/// one SQL statement inside a bounded, repeatable-read, read-only transaction.
/// Diagnostic-only: the legacy rows feed the read-only frontier audit (#4198)
/// and never the evaluator; converted and legacy edges stay inert.
pub async fn load_frontier_diagnostics(
    state: &AppState,
    user: AuthenticatedUser,
) -> Result<OptionDiagnostics, ApiError> {
    let started = Instant::now();
    let mut pending = Pending(Some(db::checkout(state).await?));
    let result = tokio::time::timeout(state.request_timeout, async {
        #[allow(clippy::unwrap_used)]
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
        let diagnostics = load_frontier_diagnostics_transaction(&tx, user).await?;
        tx.rollback().await.map_err(db::query_error)?;
        Ok::<_, ApiError>(diagnostics)
    })
    .await;
    match result {
        Err(e) => {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            Err(ApiError::DatabaseUnavailable)
        }
        Ok(Err(error)) => Err(error),
        Ok(Ok(diagnostics)) => {
            drop(pending.0.take());
            tracing::info!(
                query_count = 1,
                elapsed_us = started.elapsed().as_micros() as u64,
                unresolved_count = diagnostics.inputs.unresolved.len(),
                legacy_dependency_rows = diagnostics.legacy_dependencies.len(),
                "Option E frontier diagnostics loaded"
            );
            Ok(diagnostics)
        }
    }
}

/// Load execution inputs, failing closed on missing or foreign constraint endpoints.
pub async fn load_option_inputs(
    state: &AppState,
    user: AuthenticatedUser,
) -> Result<crate::reading_constraints::ValidatedReadingInputs, ApiError> {
    validated(load_option_diagnostics(state, user).await?)
}

/// Load read-path inputs, containing an existing cycle to its own subgraph.
pub async fn load_option_inputs_contained(
    state: &AppState,
    user: AuthenticatedUser,
) -> Result<crate::reading_constraints::ValidatedReadingInputs, ApiError> {
    validated_contained(load_option_diagnostics(state, user).await?)
}

/// Load read-path inputs inside an existing transaction, containing any cycle.
pub(crate) async fn load_validated_contained_in_transaction(
    transaction: &Transaction<'_>,
    user: AuthenticatedUser,
) -> Result<crate::reading_constraints::ValidatedReadingInputs, ApiError> {
    validated_contained(load_transaction(transaction, user).await?)
}

/// Load raw inputs inside an existing write transaction for a pre-commit preflight.
pub(crate) async fn load_inputs_in_transaction(
    transaction: &Transaction<'_>,
    user: AuthenticatedUser,
) -> Result<OptionInputs, ApiError> {
    load_transaction(transaction, user).await
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
            name: "First".into(),
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
            name: "Second".into(),
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
            "lists": [{"id": 50, "mode": "strict", "name": "First"}, {"id": 51, "mode": "loose", "name": "Second"}],
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
        let mut inputs = assemble_snapshot(snapshot).ok().unwrap();
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
    fn dangling_list_entry_is_reported_as_unresolved() {
        // A persisted list entry can outlive the issue it references. The
        // snapshot join yields no owned issue for it, so assembly must retain a
        // typed unresolved marker that fails execution closed instead of
        // silently dropping the entry.
        let snapshot: SnapshotRows = serde_json::from_value(serde_json::json!({
            "threads": [
                {"id": 1, "status": "active", "title": "Alpha",
                 "next_unread_issue_id": 10, "is_blocked": false, "queue_position": 1}
            ],
            "issues": [
                {"id": 10, "thread_id": 1, "position": 1, "status": "unread",
                 "issue_number": "1"}
            ],
            "lists": [{"id": 50, "mode": "strict", "name": "Strict"}],
            "entries": [
                {"id": 100, "list_id": 50, "issue_id": 999,
                 "gate": "after_previous", "skipped": false}
            ],
            "prerequisites": [], "evidence": [], "overlaps": [],
            "exclusions": [], "issue_volumes": []
        }))
        .unwrap();
        let inputs = assemble_snapshot(snapshot).ok().unwrap();
        assert_eq!(inputs.unresolved.len(), 1);
        assert_eq!(inputs.unresolved[0].kind, "list_entry");
        assert_eq!(inputs.unresolved[0].object_id, 100);
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
        let inputs = assemble_snapshot(snapshot).ok().unwrap();
        assert!(inputs.require_resolved().is_ok());
        assert!(inputs.core.issues.is_empty());
    }

    #[test]
    fn frontier_diagnostics_statement_reports_both_columns() {
        let sql = frontier_diagnostics_statement();
        assert!(sql.contains("legacy_dependency_rows"));
        assert!(sql.contains("origin IS DISTINCT FROM 'reader'"));
        assert!(sql.contains("jsonb_agg"));
    }

    #[test]
    fn legacy_dependency_rows_decode_from_the_diagnostics_projection() {
        let rows: Vec<LegacyDependencyRow> = serde_json::from_value(serde_json::json!([
            {
                "id": 1860,
                "source_issue_id": 101875,
                "target_issue_id": 2029,
                "origin": null,
                "classification": null,
                "provenance": null,
                "note": null,
                "source_owned": false
            },
            {
                "id": 1861,
                "source_issue_id": 2102,
                "target_issue_id": 2029,
                "origin": "converted",
                "classification": "C",
                "provenance": "generation evidence",
                "note": "cbl-order:legacy-materialization",
                "source_owned": true
            }
        ]))
        .unwrap();
        assert_eq!(rows.len(), 2);
        assert!(!rows[0].source_owned);
        assert_eq!(rows[1].classification.as_deref(), Some("C"));
    }

    /// Two-reader synthetic PostgreSQL fixture for the #3221 catalog-indirection
    /// retirement. Reader A carries catalog-only issue volume evidence; reader B
    /// carries confirmed-mapping evidence only (series entity and metadata
    /// volume). The baseline query in the test is the pre-change
    /// `issue_volume_rows` catalog branch, so the comparison is literal.
    async fn two_reader_fixture() -> (
        std::sync::Arc<crate::AppState>,
        tokio::sync::MutexGuard<'static, ()>,
    ) {
        let state = crate::test_support::test_state(2)
            .await
            .expect("RUST_ROLL_TEST_DATABASE_URL is required");
        let guard = crate::test_support::reset_for_test(&state).await;
        let conn = db::checkout(&state).await.expect("fixture connection");
        conn.batch_execute(
            r#"
            INSERT INTO users (id, username, created_at) VALUES
                (9101, 'catalog-only-reader', NOW()), (9102, 'confirmed-reader', NOW());
            INSERT INTO external_identities
                (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
            VALUES
                (8001, 'comicvine', 'series', '4050-1000', '{}'::json, NOW(), NOW()),
                (8002, 'comicvine', 'series', '4050-2000', '{}'::json, NOW(), NOW()),
                (8101, 'comicvine', 'issue', '4000-1', '{}'::json, NOW(), NOW()),
                (8102, 'comicvine', 'issue', '4000-2', '{}'::json, NOW(), NOW()),
                (8103, 'comicvine', 'issue', '4000-3', '{"volume_id":"4050-1000"}'::json, NOW(), NOW());
            INSERT INTO catalog_series (id, canonical_external_identity_id, created_at, updated_at)
            VALUES (1001, 8001, NOW(), NOW()), (1002, 8002, NOW(), NOW());
            INSERT INTO catalog_issues
                (id, canonical_external_identity_id, catalog_series_id, created_at, updated_at)
            VALUES (9001, 8101, 1001, NOW(), NOW()), (9002, 8102, 1002, NOW(), NOW());
            INSERT INTO threads
                (id, user_id, title, format, issues_remaining, queue_position, status,
                 created_at, catalog_series_id)
            VALUES (9201, 9101, 'Catalog Only', 'comic', 2, 1, 'active', NOW(), NULL),
                   (9401, 9102, 'Confirmed Series', 'comic', 1, 1, 'active', NOW(), NULL),
                   (9402, 9102, 'Confirmed Metadata', 'comic', 1, 2, 'active', NOW(), NULL);
            INSERT INTO issues
                (id, thread_id, issue_number, status, created_at, position, catalog_issue_id)
            VALUES (9201, 9201, '1', 'unread', NOW(), 1, 9001),
                   (9202, 9201, '2', 'unread', NOW(), 2, 9002),
                   (9401, 9401, '1', 'unread', NOW(), 1, NULL),
                   (9402, 9402, '1', 'unread', NOW(), 1, NULL);
            INSERT INTO issue_external_identity_mappings
                (id, issue_id, external_identity_id, status, evidence_source, evidence_json,
                 created_at, updated_at)
            VALUES (9301, 9401, 8002, 'confirmed', 'test', '{}'::json, NOW(), NOW()),
                   (9302, 9402, 8103, 'confirmed', 'test', '{}'::json, NOW(), NOW());
            INSERT INTO custom_cbl_lists
                (id, user_id, name, created_at, updated_at, mode)
            VALUES (9301, 9101, 'A strict', NOW(), NOW(), 'strict'),
                   (9302, 9102, 'B loose', NOW(), NOW(), 'loose');
            INSERT INTO custom_cbl_entries
                (id, list_id, issue_id, position, created_at, gate, skipped)
            VALUES (9501, 9301, 9201, 1, NOW(), 'none', false),
                   (9502, 9301, 9202, 2, NOW(), 'after_previous', false),
                   (9601, 9302, 9401, 1, NOW(), 'none', false),
                   (9602, 9302, 9402, 2, NOW(), 'hold', false);
            INSERT INTO dependencies
                (id, created_at, source_issue_id, target_issue_id, origin, classification, provenance)
            VALUES (9701, NOW(), 9401, 9402, 'reader', 'A', 'two-reader fixture');
            INSERT INTO collection_exclusions
                (id, user_id, provider, external_volume_id, created_at)
            VALUES (9801, 9101, 'comicvine', '4050-1000', NOW());
            "#,
        )
        .await
        .expect("seed two-reader fixture");
        drop(conn);
        (state, guard)
    }

    fn volume_map(snapshot: &SnapshotRows) -> BTreeMap<i32, BTreeSet<(String, String)>> {
        let mut map: BTreeMap<i32, BTreeSet<(String, String)>> = BTreeMap::new();
        for row in &snapshot.issue_volumes {
            map.entry(row.issue_id)
                .or_default()
                .insert(normalize_volume(&row.provider, &row.external_id));
        }
        map
    }

    async fn snapshot_for(state: &crate::AppState, user_id: i32) -> SnapshotRows {
        let mut conn = db::checkout(state).await.expect("snapshot connection");
        let tx = conn
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .expect("snapshot transaction");
        let row = tx
            .query_one(preauthenticated_statement(), &[&user_id])
            .await
            .expect("snapshot row");
        let encoded: String = row.get(0);
        let snapshot: SnapshotRows =
            serde_json::from_str(&encoded).expect("decode two-reader snapshot");
        tx.rollback().await.expect("rollback snapshot");
        snapshot
    }

    #[tokio::test]
    async fn catalog_only_volume_evidence_survives_two_reader_parity() {
        let (state, _guard) = two_reader_fixture().await;

        // The pre-change `issue_volume_rows` catalog branch, against the same
        // fixture, is the "before" side of the before/after comparison.
        let conn = db::checkout(&state).await.expect("baseline connection");
        let baseline = conn
            .query(
                "SELECT i.id, e.provider, e.external_id FROM issues i \
                 JOIN threads t ON t.id = i.thread_id \
                 JOIN catalog_issues ci ON ci.id = i.catalog_issue_id \
                 JOIN catalog_series s ON s.id = ci.catalog_series_id \
                 JOIN external_identities e ON e.id = s.canonical_external_identity_id \
                 WHERE t.user_id = $1",
                &[&9101],
            )
            .await
            .expect("baseline catalog evidence");
        drop(conn);
        let mut before: BTreeMap<i32, BTreeSet<(String, String)>> = BTreeMap::new();
        for row in &baseline {
            let issue_id: i32 = row.get(0);
            let provider: String = row.get(1);
            let external_id: String = row.get(2);
            before
                .entry(issue_id)
                .or_default()
                .insert(normalize_volume(&provider, &external_id));
        }
        assert_eq!(
            before.get(&9201),
            Some(&BTreeSet::from([(
                "comicvine".to_string(),
                "1000".to_string()
            )]))
        );

        let a_snapshot = snapshot_for(&state, 9101).await;
        let a_after = volume_map(&a_snapshot);
        for (issue_id, keys) in &before {
            for key in keys {
                assert!(
                    a_after
                        .get(issue_id)
                        .is_some_and(|after| after.contains(key)),
                    "catalog-only evidence {issue_id} {key:?} lost: {a_after:?}"
                );
            }
        }
        // Reader B has no catalog rows; confirmed-mapping evidence is additive.
        let b_snapshot = snapshot_for(&state, 9102).await;
        let b_after = volume_map(&b_snapshot);
        assert_eq!(
            b_after.get(&9401),
            Some(&BTreeSet::from([(
                "comicvine".to_string(),
                "2000".to_string()
            )]))
        );
        assert_eq!(
            b_after.get(&9402),
            Some(&BTreeSet::from([(
                "comicvine".to_string(),
                "1000".to_string()
            )]))
        );

        let a_inputs = assemble_snapshot(a_snapshot).expect("A snapshot");
        a_inputs.require_resolved().expect("A resolved");
        assert_eq!(
            a_inputs
                .excluded_issue_ids
                .iter()
                .copied()
                .collect::<Vec<_>>(),
            vec![9201]
        );
        assert_eq!(a_inputs.lists[0].mode, "strict");
        assert_eq!(a_inputs.lists[0].entries[1].gate, "after_previous");
        let a_validated = validated_contained(a_inputs).expect("A validated");
        assert!(a_validated.unsatisfied_edges().expect("A edges").is_empty());
        let a_frontiers = a_validated.eligible_frontiers().expect("A frontiers");
        assert_eq!(a_frontiers.len(), 1, "{a_frontiers:?}");
        assert_eq!(a_frontiers[0].issue_id, 9202);

        let b_inputs = assemble_snapshot(b_snapshot).expect("B snapshot");
        b_inputs.require_resolved().expect("B resolved");
        // A's volume exclusion must not leak to B even though B's issue 9402
        // carries the same comicvine:1000 volume via confirmed metadata.
        assert!(
            b_inputs.excluded_issue_ids.is_empty(),
            "{:?}",
            b_inputs.excluded_issue_ids
        );
        assert_eq!(b_inputs.lists[0].mode, "loose");
        assert_eq!(b_inputs.lists[0].entries[1].gate, "hold");
        let b_validated = validated_contained(b_inputs).expect("B validated");
        let b_blockers = b_validated.frontier_blockers().expect("B blockers");
        assert_eq!(
            b_blockers
                .iter()
                .map(|f| (f.queue_position, f.issue_id))
                .collect::<Vec<_>>(),
            vec![(1, 9401), (2, 9402)],
            "frontiers stay in queue order: {b_blockers:?}"
        );
        let b_edges = b_validated.unsatisfied_edges().expect("B edges");
        assert!(
            b_edges
                .iter()
                .any(|e| e.source_issue_id == 9401 && e.target_issue_id == 9402),
            "reader prerequisite and hold must block 9402: {b_edges:?}"
        );
        let b_frontiers = b_validated.eligible_frontiers().expect("B frontiers");
        assert_eq!(b_frontiers.len(), 1, "{b_frontiers:?}");
        assert_eq!(b_frontiers[0].issue_id, 9401);
    }

    /// #3231 rehearsal fixture. Two readers confirm the same external series and
    /// even share a catalog-only issue link, but every reader-private column is
    /// distinct: issue/thread IDs, read progress, rating events, notes, queue
    /// positions, Reading Lists and their strict/loose gates, exclusions and
    /// authored prerequisites. Reader A also owns a catalog-only issue and an
    /// issue with no identity evidence at all; reader B owns a distinct edition.
    async fn rehearsal_fixture() -> (
        std::sync::Arc<crate::AppState>,
        tokio::sync::MutexGuard<'static, ()>,
    ) {
        let state = crate::test_support::test_state(4)
            .await
            .expect("RUST_ROLL_TEST_DATABASE_URL is required");
        let guard = crate::test_support::reset_for_test(&state).await;
        let conn = db::checkout(&state).await.expect("rehearsal connection");
        conn.batch_execute(
            r#"
            INSERT INTO users (id, username, created_at) VALUES
                (9101, 'rehearsal-a', NOW()), (9102, 'rehearsal-b', NOW());

            -- Shared confirmed external identities plus two distinct editions.
            INSERT INTO external_identities
                (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
            VALUES
                (8001, 'comicvine', 'series', '4050-1000', '{}'::json, NOW(), NOW()),
                (8002, 'comicvine', 'series', '4050-2000', '{}'::json, NOW(), NOW()),
                (8101, 'comicvine', 'issue', '4050-0001', '{}'::json, NOW(), NOW()),
                (8102, 'comicvine', 'issue', '4050-0002', '{}'::json, NOW(), NOW()),
                (8103, 'comicvine', 'issue', '4050-0003',
                    '{"volume_id":"4050-1000"}'::json, NOW(), NOW()),
                (8104, 'comicvine', 'issue', '4050-1001',
                    '{"volume_id":"4050-2000"}'::json, NOW(), NOW());
            INSERT INTO catalog_series (id, canonical_external_identity_id, created_at, updated_at)
            VALUES (1001, 8001, NOW(), NOW()), (1002, 8002, NOW(), NOW());
            INSERT INTO catalog_issues
                (id, canonical_external_identity_id, catalog_series_id, created_at, updated_at)
            VALUES (9001, 8101, 1001, NOW(), NOW()),
                   (9002, 8102, 1002, NOW(), NOW()),
                   (9003, 8104, 1002, NOW(), NOW());

            INSERT INTO threads
                (id, user_id, title, format, issues_remaining, queue_position, status,
                 created_at, catalog_series_id, notes, last_rating, reading_progress)
            VALUES
                (9201, 9101, 'A catalog thread', 'comic', 2, 1, 'active', NOW(), NULL,
                    'A private notes', 4.0, 'reading'),
                (9401, 9102, 'B confirmed thread', 'comic', 2, 2, 'active', NOW(), 1001,
                    'B private notes', 3.0, 'in_progress');
            INSERT INTO issues
                (id, thread_id, issue_number, status, created_at, position, catalog_issue_id)
            VALUES
                (9201, 9201, '1', 'unread', NOW(), 1, 9001),
                (9202, 9201, '2', 'unread', NOW(), 2, 9002),
                (9203, 9201, '3', 'unread', NOW(), 3, NULL),
                (9204, 9201, '4', 'unread', NOW(), 4, NULL),
                (9401, 9401, '1', 'unread', NOW(), 1, 9001),
                (9402, 9401, '2', 'unread', NOW(), 2, NULL),
                (9403, 9401, '3', 'unread', NOW(), 3, 9003);

            -- Reader B confirms the shared series identity; reader A confirms
            -- the same external issue identity on its own private issue row.
            INSERT INTO thread_external_series_mappings
                (id, thread_id, external_identity_id, status, evidence_source, created_at, updated_at)
            VALUES (9602, 9401, 8001, 'confirmed', 'rehearsal', NOW(), NOW());
            -- A confirms identity 8103 and B confirms the same 8103: a
            -- legitimate cross-owner shared reference, not a duplicate.
            -- A's final issue has neither mapping nor catalog evidence.
            INSERT INTO issue_external_identity_mappings
                (id, issue_id, external_identity_id, status, evidence_source, evidence_json,
                 created_at, updated_at)
            VALUES (9701, 9203, 8103, 'confirmed', 'rehearsal', '{}'::json, NOW(), NOW()),
                   (9702, 9402, 8103, 'confirmed', 'rehearsal', '{}'::json, NOW(), NOW()),
                   (9703, 9403, 8104, 'confirmed', 'rehearsal', '{}'::json, NOW(), NOW());

            INSERT INTO events (id, type, "timestamp", thread_id, issue_id, rating, user_id)
            VALUES (9801, 'rate', NOW(), 9201, 9201, 4.0, 9101),
                   (9802, 'roll', NOW(), 9401, 9402, 3.0, 9102);

            INSERT INTO custom_cbl_lists
                (id, user_id, name, created_at, updated_at, mode)
            VALUES (9301, 9101, 'A strict', NOW(), NOW(), 'strict'),
                   (9302, 9102, 'B loose', NOW(), NOW(), 'loose');
            INSERT INTO custom_cbl_entries
                (id, list_id, issue_id, position, created_at, gate, skipped)
            VALUES (9501, 9301, 9201, 1, NOW(), 'none', false),
                   (9502, 9301, 9202, 2, NOW(), 'after_previous', false),
                   (9503, 9301, 9203, 3, NOW(), 'none', false),
                   (9504, 9301, 9204, 4, NOW(), 'none', false),
                   (9601, 9302, 9401, 1, NOW(), 'none', false),
                   (9602, 9302, 9402, 2, NOW(), 'hold', false),
                   (9603, 9302, 9403, 3, NOW(), 'none', false);

            INSERT INTO dependencies
                (id, created_at, source_issue_id, target_issue_id, origin, classification, provenance)
            VALUES (9901, NOW(), 9202, 9204, 'reader', 'A', 'rehearsal-authored'),
                   (9902, NOW(), 9401, 9402, 'reader', 'B', 'rehearsal-authored');

            INSERT INTO collection_exclusions
                (id, user_id, provider, external_volume_id, created_at)
            VALUES (9903, 9101, 'comicvine', '4050-1000', NOW()),
                   (9904, 9102, 'comicvine', '4050-2000', NOW());
            "#,
        )
        .await
        .expect("seed #3231 rehearsal fixture");
        drop(conn);
        (state, guard)
    }

    #[tokio::test]
    async fn rehearsal_two_readers_keep_private_state_while_sharing_confirmed_identity() {
        let (state, _guard) = rehearsal_fixture().await;
        let conn = db::checkout(&state)
            .await
            .expect("rehearsal verification connection");

        // The same external issue identity is confirmed by both readers.
        let shared: Vec<tokio_postgres::Row> = conn
            .query(
                "SELECT t.user_id FROM issue_external_identity_mappings m \
                 JOIN issues i ON i.id = m.issue_id \
                 JOIN threads t ON t.id = i.thread_id \
                 WHERE m.external_identity_id = 8103 AND m.status = 'confirmed' \
                 ORDER BY t.user_id",
                &[],
            )
            .await
            .expect("shared confirmed identity");
        assert_eq!(
            shared
                .iter()
                .map(|r| r.get::<_, i32>(0))
                .collect::<Vec<_>>(),
            vec![9101, 9102]
        );
        // The same catalog issue is referenced by both readers; the issue rows
        // themselves stay private.
        let shared_catalog: Vec<tokio_postgres::Row> = conn
            .query(
                "SELECT user_id FROM ( \
                    SELECT t.user_id, i.catalog_issue_id FROM issues i \
                    JOIN threads t ON t.id = i.thread_id WHERE i.catalog_issue_id = 9001 \
                 ) s ORDER BY user_id",
                &[],
            )
            .await
            .expect("shared catalog reference");
        assert_eq!(
            shared_catalog
                .iter()
                .map(|r| r.get::<_, i32>(0))
                .collect::<Vec<_>>(),
            vec![9101, 9102]
        );

        for (
            user_id,
            ids,
            notes,
            rating,
            queue,
            progress,
            event,
            mode,
            gate,
            exclusion,
            dependency,
        ) in [
            (
                9101,
                vec![9201, 9202, 9203, 9204],
                "A private notes",
                4.0,
                1,
                "reading",
                ("rate", 4.0, 9201),
                "strict",
                "after_previous",
                "4050-1000",
                (9202, 9204),
            ),
            (
                9102,
                vec![9401, 9402, 9403],
                "B private notes",
                3.0,
                2,
                "in_progress",
                ("roll", 3.0, 9402),
                "loose",
                "hold",
                "4050-2000",
                (9401, 9402),
            ),
        ] {
            let owned: Vec<tokio_postgres::Row> = conn
                .query(
                    "SELECT i.id FROM issues i JOIN threads t ON t.id = i.thread_id \
                     WHERE t.user_id = $1 ORDER BY i.id",
                    &[&user_id],
                )
                .await
                .expect("owned issues");
            assert_eq!(
                owned.iter().map(|r| r.get::<_, i32>(0)).collect::<Vec<_>>(),
                ids,
                "reader {user_id} issue IDs must stay private"
            );
            let private: (String, f64, i32, String) = {
                let row = conn
                    .query_one(
                        "SELECT notes, last_rating, queue_position, reading_progress \
                         FROM threads WHERE user_id = $1",
                        &[&user_id],
                    )
                    .await
                    .expect("reader thread private state");
                (row.get(0), row.get(1), row.get(2), row.get(3))
            };
            assert_eq!(private.0, notes);
            assert_eq!(private.1, rating);
            assert_eq!(private.2, queue);
            assert_eq!(private.3, progress, "read progress must stay reader-private");
            let reader_event: (String, f64, Option<i32>) = {
                let row = conn
                    .query_one(
                        "SELECT type, rating, issue_id FROM events \
                         WHERE user_id = $1 ORDER BY id",
                        &[&user_id],
                    )
                    .await
                    .expect("reader rating/roll event");
                (row.get(0), row.get(1), row.get(2))
            };
            assert_eq!(
                reader_event,
                (event.0.to_string(), event.1, Some(event.2)),
                "reader {user_id} event must stay private"
            );
            let list: (String, String) = {
                let row = conn
                    .query_one(
                        "SELECT l.mode, e.gate FROM custom_cbl_lists l \
                         JOIN custom_cbl_entries e ON e.list_id = l.id \
                         WHERE l.user_id = $1 ORDER BY e.position LIMIT 1 OFFSET 1",
                        &[&user_id],
                    )
                    .await
                    .expect("reader Reading List gate");
                (row.get(0), row.get(1))
            };
            assert_eq!(list, (mode.to_string(), gate.to_string()));
            let excluded: String = conn
                .query_one(
                    "SELECT external_volume_id FROM collection_exclusions WHERE user_id = $1",
                    &[&user_id],
                )
                .await
                .expect("reader exclusion")
                .get(0);
            assert_eq!(excluded, exclusion);
            let authored: (i32, i32) = {
                let row = conn
                    .query_one(
                        "SELECT d.source_issue_id, d.target_issue_id FROM dependencies d \
                         JOIN issues i ON i.id = d.target_issue_id \
                         JOIN threads t ON t.id = i.thread_id \
                         WHERE t.user_id = $1 AND d.origin = 'reader'",
                        &[&user_id],
                    )
                    .await
                    .expect("reader-authored prerequisite");
                (row.get(0), row.get(1))
            };
            assert_eq!(authored, dependency);
        }
        drop(conn);
    }

    #[tokio::test]
    async fn rehearsal_before_after_eligibility_volume_and_blocker_parity() {
        let (state, _guard) = rehearsal_fixture().await;

        // "Before": the original catalog-only volume evidence query from the
        // pre-#3221 `issue_volume_rows` branch, run on the same fixture.
        let conn = db::checkout(&state).await.expect("baseline connection");
        let baseline = conn
            .query(
                "SELECT i.id, e.provider, e.external_id FROM issues i \
                 JOIN threads t ON t.id = i.thread_id \
                 JOIN catalog_issues ci ON ci.id = i.catalog_issue_id \
                 JOIN catalog_series s ON s.id = ci.catalog_series_id \
                 JOIN external_identities e ON e.id = s.canonical_external_identity_id \
                 WHERE t.user_id = $1",
                &[&9101],
            )
            .await
            .expect("baseline catalog evidence");
        drop(conn);
        let mut before: BTreeMap<i32, BTreeSet<(String, String)>> = BTreeMap::new();
        for row in &baseline {
            before
                .entry(row.get(0))
                .or_default()
                .insert(normalize_volume(
                    &row.get::<_, String>(1),
                    &row.get::<_, String>(2),
                ));
        }
        assert_eq!(
            before.get(&9201),
            Some(&BTreeSet::from([("comicvine".into(), "1000".into())]))
        );
        assert_eq!(
            before.get(&9202),
            Some(&BTreeSet::from([("comicvine".into(), "2000".into())]))
        );

        // "After": the current owner-scoped snapshot CTE for each reader.
        let a_snapshot = snapshot_for(&state, 9101).await;
        let a_after = volume_map(&a_snapshot);
        for (issue_id, keys) in &before {
            for key in keys {
                assert!(
                    a_after.get(issue_id).is_some_and(|v| v.contains(key)),
                    "catalog-only evidence {issue_id} {key:?} lost: {a_after:?}"
                );
            }
        }
        // The confirmed issue mapping on 9203 yields exactly its metadata
        // volume; the issue with neither mapping nor catalog link stays unknown.
        assert_eq!(
            a_after.get(&9203),
            Some(&BTreeSet::from([("comicvine".into(), "1000".into())])),
            "confirmed evidence must not be invented: {a_after:?}"
        );
        assert!(
            !a_after.contains_key(&9204),
            "unknown issue gained evidence"
        );

        let a_inputs = assemble_snapshot(a_snapshot).expect("A snapshot");
        a_inputs.require_resolved().expect("A resolved");
        assert_eq!(
            a_inputs
                .excluded_issue_ids
                .iter()
                .copied()
                .collect::<Vec<_>>(),
            vec![9201, 9203],
            "A's volume exclusion covers its catalog-only and confirmed-volume issues only"
        );
        let a_validated = validated_contained(a_inputs).expect("A validated");
        let a_edges = a_validated.unsatisfied_edges().expect("A edges");
        assert!(
            a_edges
                .iter()
                .all(|e| e.source_issue_id >= 9201 && e.source_issue_id <= 9204),
            "A's authored prerequisite must stay inside A: {a_edges:?}"
        );
        assert!(
            a_edges
                .iter()
                .any(|e| e.prerequisite_origin.as_deref() == Some("reader")
                    && e.source_issue_id == 9202
                    && e.target_issue_id == 9204),
            "A's authored prerequisite must be live: {a_edges:?}"
        );
        let a_blockers = a_validated.frontier_blockers().expect("A blockers");
        assert_eq!(
            a_blockers
                .iter()
                .map(|f| (f.queue_position, f.issue_id, f.unsatisfied.len()))
                .collect::<Vec<_>>(),
            vec![(1, 9202, 0)],
            "exact A frontier/blocker shape: {a_blockers:?}"
        );
        let a_frontiers = a_validated.eligible_frontiers().expect("A frontiers");
        assert_eq!(
            a_frontiers.iter().map(|f| f.issue_id).collect::<Vec<_>>(),
            vec![9202]
        );

        let b_snapshot = snapshot_for(&state, 9102).await;
        let b_after = volume_map(&b_snapshot);
        assert_eq!(
            b_after.get(&9401),
            Some(&BTreeSet::from([("comicvine".into(), "1000".into())])),
            "B's catalog-only evidence survives"
        );
        assert_eq!(
            b_after.get(&9402),
            Some(&BTreeSet::from([("comicvine".into(), "1000".into())])),
            "B's confirmed metadata volume survives"
        );
        assert!(
            b_after
                .get(&9403)
                .is_some_and(|v| v.contains(&("comicvine".into(), "2000".into()))),
            "B's distinct edition keeps its own volume key: {b_after:?}"
        );

        let b_inputs = assemble_snapshot(b_snapshot).expect("B snapshot");
        b_inputs.require_resolved().expect("B resolved");
        assert_eq!(
            b_inputs
                .excluded_issue_ids
                .iter()
                .copied()
                .collect::<Vec<_>>(),
            vec![9403],
            "A's volume exclusion must not leak to B; B excludes its own edition"
        );
        let b_validated = validated_contained(b_inputs).expect("B validated");
        let b_edges = b_validated.unsatisfied_edges().expect("B edges");
        assert_eq!(
            b_edges
                .iter()
                .filter(|e| e.prerequisite_origin.as_deref() == Some("reader"))
                .map(|e| (e.source_issue_id, e.target_issue_id))
                .collect::<Vec<_>>(),
            vec![(9401, 9402)],
            "B's authored prerequisite blocks only B: {b_edges:?}"
        );
        let b_blockers = b_validated.frontier_blockers().expect("B blockers");
        assert_eq!(
            b_blockers
                .iter()
                .map(|f| (f.queue_position, f.issue_id, f.unsatisfied.len()))
                .collect::<Vec<_>>(),
            vec![(1, 9401, 0)],
            "B's frontier stays at its first unread issue: {b_blockers:?}"
        );
        let b_frontiers = b_validated.eligible_frontiers().expect("B frontiers");
        assert_eq!(
            b_frontiers.iter().map(|f| f.issue_id).collect::<Vec<_>>(),
            vec![9401]
        );
    }

    #[tokio::test]
    async fn rehearsal_card_projection_is_owner_scoped_confirmed_only_and_bounded() {
        let (state, _guard) = rehearsal_fixture().await;
        let conn = db::checkout(&state)
            .await
            .expect("card projection connection");

        // One set-based call for a mixed batch: A's issues, B's issue and an
        // unknown id. The foreign and unknown ids are omitted, order preserved.
        let response = crate::issue_service::cards(
            &conn,
            crate::auth::AuthenticatedUser::for_test(9101),
            &[9201, 9401, 9202, 9204, 9999],
        )
        .await
        .expect("A card projection");
        assert_eq!(
            response
                .items
                .iter()
                .map(|c| c.issue_id)
                .collect::<Vec<_>>(),
            vec![9201, 9202, 9204],
            "card projection must be owner-scoped and preserve first-request order"
        );
        let catalog_only = &response.items[0];
        assert!(!catalog_only.has_confirmed_identity);
        assert_eq!(catalog_only.mapping_state, "unmapped");
        assert_eq!(catalog_only.comicvine_issue_id, None);
        assert_eq!(catalog_only.cover_image_url, None);
        assert_eq!(
            catalog_only.rating,
            Some(4.0),
            "A's own rating must survive"
        );
        let missing_mapping = &response.items[2];
        assert_eq!(missing_mapping.mapping_state, "unmapped");
        assert!(!missing_mapping.has_confirmed_identity);

        let b_response = crate::issue_service::cards(
            &conn,
            crate::auth::AuthenticatedUser::for_test(9102),
            &[9401, 9402, 9403, 9201],
        )
        .await
        .expect("B card projection");
        assert_eq!(
            b_response
                .items
                .iter()
                .map(|c| c.issue_id)
                .collect::<Vec<_>>(),
            vec![9401, 9402, 9403]
        );
        let confirmed = &b_response.items[1];
        assert!(confirmed.has_confirmed_identity);
        assert_eq!(confirmed.mapping_state, "confirmed");
        assert_eq!(confirmed.comicvine_issue_id.as_deref(), Some("4050-0003"));
        assert_eq!(confirmed.rating, None, "A's rating must not leak to B");
        // A distinct edition is a separate confirmed identity, never merged
        // into the shared volume just because both readers confirmed it.
        assert_eq!(
            b_response.items[2].comicvine_issue_id.as_deref(),
            Some("4050-1001")
        );

        // Bounded input: the batch cap rejects oversized requests before any
        // projection work, and a single call resolves the whole bounded batch.
        assert!(
            crate::issue_service::validate_cards(&crate::issue_service::IssueCardsRequest {
                issue_ids: (1..=201).collect(),
            })
            .is_err()
        );
        drop(conn);
    }
}
