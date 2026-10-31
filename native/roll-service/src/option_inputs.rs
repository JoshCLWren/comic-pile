//! Complete owner-scoped Option E loader inputs, detached from eligibility evaluation.
use crate::{
    auth::AuthenticatedUser,
    db,
    reading_inputs::{self, CoreReadingInputs},
    ApiError, AppState,
};
use axum::http::StatusCode;
use deadpool_postgres::Object;
use serde::Serialize;
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

async fn load_transaction(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
) -> Result<OptionInputs, tokio_postgres::Error> {
    let core = reading_inputs::load_core_transaction(tx, user).await?;
    let user_id = user.id();
    let owned: HashSet<_> = core.issues.iter().map(|i| i.id).collect();
    let mut unresolved = Vec::new();
    let mut lists = BTreeMap::new();
    for row in tx
        .query(
            "SELECT id, mode FROM custom_cbl_lists WHERE user_id=$1 ORDER BY id",
            &[&user_id],
        )
        .await?
    {
        let id = row.try_get(0)?;
        lists.insert(
            id,
            ReadingList {
                list_id: id,
                mode: row.try_get(1)?,
                entries: vec![],
                overlap_decisions: vec![],
            },
        );
    }
    for row in tx.query("SELECT e.id,e.list_id,e.issue_id,e.gate,e.skipped FROM custom_cbl_entries e JOIN custom_cbl_lists l ON l.id=e.list_id WHERE l.user_id=$1 ORDER BY e.list_id,e.position", &[&user_id]).await? {
        let issue_id = row.try_get(2)?;
        if !owned.contains(&issue_id) { unresolved.push(UnresolvedReference {kind:"list_entry",object_id:row.try_get(0)?}); }
        lists.get_mut(&row.try_get::<_, i32>(1)?).unwrap().entries.push(ReadingEntry {issue_id,gate:row.try_get(3)?,skipped:row.try_get(4)?});
    }
    let mut prerequisites = vec![];
    for row in tx.query("SELECT d.id,d.source_issue_id,d.target_issue_id,d.classification,d.provenance FROM dependencies d WHERE d.origin='reader' AND (d.source_issue_id IN (SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=$1) OR d.target_issue_id IN (SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id WHERE t.user_id=$1)) ORDER BY d.id", &[&user_id]).await? {
        let id = row.try_get(0)?;
        let source = row.try_get(1)?;
        let target = row.try_get(2)?;
        if !owned.contains(&source) || !owned.contains(&target) { unresolved.push(UnresolvedReference {kind:"prerequisite",object_id:id}); }
        let classification: Option<String> = row.try_get(3)?;
        prerequisites.push(Prerequisite {prerequisite_id:id,source_issue_id:source,target_issue_id:target,origin:"reader".into(),provenance:vec![format!("classification:{}",classification.as_deref().unwrap_or("None")),row.try_get::<_,Option<String>>(4)?.unwrap_or_default()]});
    }
    // One evidence query serves both volume exclusions and overlap resolution.
    // Exclusions intentionally don't filter entity_type, matching the Python oracle.
    let rows = tx.query("SELECT t.id,e.provider,e.external_id,e.entity_type FROM threads t JOIN thread_external_series_mappings m ON m.thread_id=t.id JOIN external_identities e ON e.id=m.external_identity_id WHERE t.user_id=$1 AND m.status='confirmed' UNION ALL SELECT t.id,e.provider,e.external_id,e.entity_type FROM threads t JOIN catalog_series s ON s.id=t.catalog_series_id JOIN external_identities e ON e.id=s.canonical_external_identity_id WHERE t.user_id=$1", &[&user_id]).await?;
    let mut evidence = vec![];
    let mut candidates: BTreeMap<i32, BTreeSet<String>> = BTreeMap::new();
    for row in rows {
        let thread_id = row.try_get(0)?;
        let provider: String = row.try_get(1)?;
        let external_id: String = row.try_get(2)?;
        if row.try_get::<_, String>(3)? == "series" {
            if let Some(key) = volume_key(&provider, &external_id) {
                candidates.entry(thread_id).or_default().insert(key);
            }
        }
        evidence.push((thread_id, normalize_volume(&provider, &external_id)));
    }
    let thread_volumes = candidates
        .into_iter()
        .filter_map(|(id, mut keys)| (keys.len() == 1).then(|| (id, keys.pop_first().unwrap())))
        .collect();
    for row in tx.query("SELECT d.list_id,c.provider,c.external_id,w.provider,w.external_id FROM custom_cbl_overlap_decisions d JOIN external_identities c ON c.id=d.continuing_external_identity_id JOIN external_identities w ON w.id=d.waiting_external_identity_id JOIN custom_cbl_lists l ON l.id=d.list_id AND l.user_id=d.user_id WHERE d.user_id=$1 ORDER BY d.id", &[&user_id]).await? {
        if let (Some(c),Some(w)) = (volume_key(row.try_get(1)?,row.try_get(2)?),volume_key(row.try_get(3)?,row.try_get(4)?)) {
            lists.get_mut(&row.try_get::<_,i32>(0)?).unwrap().overlap_decisions.push(OverlapDecision {continuing_volume_id:c,waiting_volume_id:w});
        }
    }
    let mut excluded_issues = HashSet::new();
    let mut excluded_threads = HashSet::new();
    let mut excluded_volumes = HashSet::new();
    for row in tx.query("SELECT issue_id,thread_id,provider,external_volume_id FROM collection_exclusions WHERE user_id=$1", &[&user_id]).await? {
        if let Some(id) = row.try_get::<_,Option<i32>>(0)? { excluded_issues.insert(id); }
        if let Some(id) = row.try_get::<_,Option<i32>>(1)? { excluded_threads.insert(id); }
        if let (Some(p),Some(v)) = (row.try_get::<_,Option<String>>(2)?,row.try_get::<_,Option<String>>(3)?) { excluded_volumes.insert(normalize_volume(&p,&v)); }
    }
    for (id, key) in evidence {
        if excluded_volumes.contains(&key) {
            excluded_threads.insert(id);
        }
    }
    for row in tx.query("SELECT i.id,e.provider,e.external_id FROM issues i JOIN threads t ON t.id=i.thread_id JOIN catalog_issues ci ON ci.id=i.catalog_issue_id JOIN catalog_series s ON s.id=ci.catalog_series_id JOIN external_identities e ON e.id=s.canonical_external_identity_id WHERE t.user_id=$1", &[&user_id]).await? {
        if excluded_volumes.contains(&normalize_volume(row.try_get(1)?,row.try_get(2)?)) { excluded_issues.insert(row.try_get::<_,i32>(0)?); }
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
/// Read all Option E constraints in one bounded, repeatable-read, read-only transaction.
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
            .await?;
        let inputs = load_transaction(&tx, user).await?;
        tx.rollback().await?;
        Ok::<_, tokio_postgres::Error>(inputs)
    })
    .await;
    match result {
        Err(_) => Err(ApiError(
            StatusCode::SERVICE_UNAVAILABLE,
            "Database temporarily unavailable",
        )),
        Ok(Err(error)) => Err(db::query_error(error)),
        Ok(Ok(inputs)) => {
            drop(pending.0.take());
            tracing::info!(
                query_count = 9,
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
}
