#![allow(clippy::unwrap_used, clippy::expect_used)]
//! DB-backed regressions for the offline CBL mirror ingester (#4171).
//!
//! Database-backed cases use the canonical disposable PostgreSQL schema and
//! real local mirror fixtures. They prove that a pinned revision is applied
//! idempotently, that a changed revision only replaces changed lists, that
//! removed paths are deactivated without deleting their rows, that malformed
//! paths retain their last-known-good lists, and that a legacy repository alias
//! is reconciled in place.

use chrono::{TimeZone, Utc};
use comicpile_roll_service::{
    cbl_ingest::{
        build_inventory, discover_cbl_files, parse_cbl_file, sync_cbl_lists, CBLList,
        CBLParseFailure,
    },
    config::Config,
    test_support, AppState,
};
use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
};
use tokio::sync::Barrier;

static NEXT_FIXTURE: AtomicUsize = AtomicUsize::new(1);

struct MirrorFixture {
    root: PathBuf,
}

impl MirrorFixture {
    fn new(files: &[(&str, &str)]) -> Self {
        let root = std::env::temp_dir().join(format!(
            "comicpile-cbl-ingest-{}-{}",
            std::process::id(),
            NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).unwrap();
        for (path, body) in files {
            let absolute = root.join(path);
            fs::create_dir_all(absolute.parent().unwrap()).unwrap();
            fs::write(absolute, body).unwrap();
        }
        Self { root }
    }

    fn parse(&self) -> (Vec<CBLList>, Vec<CBLParseFailure>) {
        let mut parsed = Vec::new();
        let mut failures = Vec::new();
        for path in discover_cbl_files(&self.root).unwrap() {
            match parse_cbl_file(&path, &self.root) {
                Ok(list) => parsed.push(list),
                Err(error) => failures.push(CBLParseFailure {
                    source_path: path
                        .strip_prefix(&self.root)
                        .unwrap()
                        .to_string_lossy()
                        .replace('\\', "/"),
                    message: error.to_string(),
                }),
            }
        }
        (parsed, failures)
    }
}

impl Drop for MirrorFixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

async fn setup() -> (Arc<AppState>, tokio::sync::MutexGuard<'static, ()>) {
    let url = test_support::database_url().await;
    let state = Arc::new(test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some(test_support::TEST_JWT_SECRET.into()),
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .unwrap(),
    ));
    let guard = test_support::reset_for_test(&state).await;
    (state, guard)
}

fn synced_at() -> chrono::DateTime<Utc> {
    Utc.with_ymd_and_hms(2026, 11, 27, 12, 0, 0).unwrap()
}

fn protected(failures: &[CBLParseFailure]) -> BTreeSet<String> {
    failures
        .iter()
        .map(|failure| failure.source_path.clone())
        .collect()
}

async fn apply(
    state: &Arc<AppState>,
    parsed: &[CBLList],
    failures: &[CBLParseFailure],
    revision: &str,
    alias: Option<&str>,
) -> comicpile_roll_service::cbl_ingest::SyncSummary {
    apply_at(state, parsed, failures, revision, alias, synced_at()).await
}

async fn apply_at(
    state: &Arc<AppState>,
    parsed: &[CBLList],
    failures: &[CBLParseFailure],
    revision: &str,
    alias: Option<&str>,
    applied_at: chrono::DateTime<Utc>,
) -> comicpile_roll_service::cbl_ingest::SyncSummary {
    let mut conn = state.pool.get().await.unwrap();
    let transaction = conn.transaction().await.unwrap();
    let aliases = alias
        .map(|value| vec![value.to_string()])
        .unwrap_or_default();
    let summary = sync_cbl_lists(
        &*transaction,
        "JoshCLWren/CBL-ReadingLists",
        revision,
        parsed,
        &protected(failures),
        &aliases,
        false,
        applied_at,
    )
    .await
    .unwrap();
    transaction.commit().await.unwrap();
    summary
}

async fn scalar<T>(state: &Arc<AppState>, sql: &str) -> T
where
    T: tokio_postgres::types::FromSqlOwned,
{
    scalar_with(state, sql, &[]).await
}

async fn scalar_with<T>(
    state: &Arc<AppState>,
    sql: &str,
    parameters: &[&(dyn tokio_postgres::types::ToSql + Sync)],
) -> T
where
    T: tokio_postgres::types::FromSqlOwned,
{
    let conn = state.pool.get().await.unwrap();
    conn.query_one(sql, parameters)
        .await
        .unwrap()
        .get::<_, T>(0)
}

fn cbl(name: &str, entries: &[(&str, &str, Option<&str>, Option<&str>)]) -> String {
    let books = entries
        .iter()
        .map(|(series, number, series_id, issue_id)| {
            let database = series_id
                .or(*issue_id)
                .map(|_| "<Database Name=\"ComicVine\" />".to_string());
            let ids = series_id.map(|id| format!(" SeriesID=\"{id}\"")).unwrap_or_default();
            let ids = format!(
                "{ids}{}",
                issue_id.map(|id| format!(" IssueID=\"{id}\"")).unwrap_or_default()
            );
            format!(
                "<Book Series=\"{series}\" Number=\"{number}\" Volume=\"2016\" Year=\"None\"{ids}>{}</Book>",
                database.unwrap_or_default()
            )
        })
        .collect::<Vec<_>>()
        .join("");
    format!(
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\
         <ReadingList><Name>{name}</Name><NumIssues>{}</NumIssues><Books>{books}</Books></ReadingList>",
        entries.len()
    )
}

#[tokio::test]
async fn dry_run_reports_counts_without_writing_any_rows() {
    let (state, _guard) = setup().await;
    let fixture = MirrorFixture::new(&[
        (
            "DC/Batman/Batman.cbl",
            &cbl("Batman 001", &[("Batman", "1", Some("4059"), Some("9001"))]),
        ),
        (
            "Marvel/Teams/Fantastic Four.cbl",
            &cbl(
                "Fantastic Four 001",
                &[("Fantastic Four", "1", None, Some("7002"))],
            ),
        ),
    ]);
    let (parsed, failures) = fixture.parse();
    assert!(failures.is_empty(), "{failures:?}");
    let inventory = build_inventory(&parsed, &failures).unwrap();
    assert_eq!(inventory.total_files, 2);
    assert_eq!(inventory.total_entries, 2);

    let conn = state.pool.get().await.unwrap();
    let summary = sync_cbl_lists(
        &**conn,
        "JoshCLWren/CBL-ReadingLists",
        "abc1234",
        &parsed,
        &BTreeSet::new(),
        &[],
        true,
        synced_at(),
    )
    .await
    .unwrap();
    assert!(summary.dry_run);
    assert!(summary.changed);
    assert!(summary.source_created);
    assert_eq!(summary.inserted_lists, 2);
    assert_eq!(summary.entries_written, 2);
    assert_eq!(summary.identities_upserted, 3);
    let sources: i64 = scalar(&state, "SELECT COUNT(*) FROM cbl_sources").await;
    let lists: i64 = scalar(&state, "SELECT COUNT(*) FROM cbl_source_lists").await;
    assert_eq!((sources, lists), (0, 0));
}

#[tokio::test]
async fn applying_a_pinned_revision_is_idempotent_and_records_provenance() {
    let (state, _guard) = setup().await;
    let fixture = MirrorFixture::new(&[
        (
            "DC/Batman/Batman.cbl",
            &cbl("Batman 001", &[("Batman", "1", Some("4059"), Some("9001"))]),
        ),
        (
            "DC/Batman/Robin.cbl",
            &cbl("Robin 002", &[("Robin", "2", Some("4070"), Some("9002"))]),
        ),
    ]);
    let (parsed, failures) = fixture.parse();
    assert!(failures.is_empty());

    let first = apply(&state, &parsed, &failures, "abc1234", None).await;
    assert!(first.changed);
    assert_eq!(first.inserted_lists, 2);
    assert_eq!(first.entries_written, 2);
    assert_eq!(first.identities_upserted, 4);
    let sources: i64 = scalar(&state, "SELECT COUNT(*) FROM cbl_sources").await;
    let lists: i64 = scalar(&state, "SELECT COUNT(*) FROM cbl_source_lists").await;
    let entries: i64 = scalar(&state, "SELECT COUNT(*) FROM cbl_source_entries").await;
    let identities: i64 = scalar(&state, "SELECT COUNT(*) FROM external_identities").await;
    assert_eq!((sources, lists, entries, identities), (1, 2, 2, 4));
    let revision: String = scalar(&state, "SELECT revision_sha FROM cbl_sources").await;
    assert_eq!(revision, "abc1234");
    let stored: String = scalar(
        &state,
        "SELECT s.content_hash FROM cbl_source_lists s WHERE s.source_path = 'DC/Batman/Batman.cbl'",
    )
    .await;
    assert_eq!(stored, parsed[0].content_hash);
    let linked: i64 = scalar(
        &state,
        "SELECT COUNT(*) FROM cbl_source_entries e \
         JOIN external_identities s ON s.id = e.external_series_identity_id \
         JOIN external_identities i ON i.id = e.external_issue_identity_id \
         WHERE s.external_id = '4059' AND i.external_id = '9001'",
    )
    .await;
    assert_eq!(linked, 1);

    let second = apply_at(
        &state,
        &parsed,
        &failures,
        "abc1234",
        None,
        synced_at() + chrono::Duration::days(1),
    )
    .await;
    assert!(!second.changed);
    assert_eq!(second.inserted_lists, 0);
    assert_eq!(second.updated_lists, 0);
    assert_eq!(second.unchanged_lists, 2);
    assert_eq!(second.entries_written, 0);
    let entries: i64 = scalar(&state, "SELECT COUNT(*) FROM cbl_source_entries").await;
    let original_synced: i64 = scalar(
        &state,
        "SELECT COUNT(*) FROM cbl_sources WHERE synced_at = '2026-11-27 12:00:00+00'",
    )
    .await;
    let restamped: i64 = scalar(
        &state,
        "SELECT COUNT(*) FROM cbl_sources WHERE synced_at = '2026-11-28 12:00:00+00'",
    )
    .await;
    assert_eq!((entries, original_synced, restamped), (2, 1, 0));
}

#[tokio::test]
async fn changed_revision_deactivates_removed_paths_without_deleting_rows() {
    let (state, _guard) = setup().await;
    let original = MirrorFixture::new(&[
        (
            "DC/Batman/Batman.cbl",
            &cbl("Batman 001", &[("Batman", "1", Some("4059"), Some("9001"))]),
        ),
        (
            "DC/Batman/Robin.cbl",
            &cbl("Robin 002", &[("Robin", "2", None, Some("9002"))]),
        ),
    ]);
    let (parsed, failures) = original.parse();
    apply(&state, &parsed, &failures, "aaa1111", None).await;
    let removed_id: i32 = scalar(
        &state,
        "SELECT id FROM cbl_source_lists WHERE source_path = 'DC/Batman/Robin.cbl'",
    )
    .await;

    let changed = MirrorFixture::new(&[(
        "DC/Batman/Batman.cbl",
        &cbl(
            "Batman 001 revised",
            &[
                ("Batman", "1", Some("4059"), Some("9001")),
                ("Batman", "2", None, Some("9003")),
            ],
        ),
    )]);
    let (next, failures) = changed.parse();
    let summary = apply(&state, &next, &failures, "bbb2222", None).await;
    assert_eq!(summary.updated_lists, 1);
    assert_eq!(summary.deactivated_lists, 1);
    assert_eq!(summary.entries_written, 2);

    // The removed row still exists with its original entries and provenance.
    let row = {
        let conn = state.pool.get().await.unwrap();
        conn.query_one(
            "SELECT active, revision_sha FROM cbl_source_lists WHERE id = $1",
            &[&removed_id],
        )
        .await
        .unwrap()
    };
    assert!(!row.get::<_, bool>(0));
    assert_eq!(row.get::<_, String>(1), "bbb2222");
    let preserved: i64 = scalar_with(
        &state,
        "SELECT COUNT(*) FROM cbl_source_entries WHERE list_id = $1",
        &[&removed_id],
    )
    .await;
    assert_eq!(preserved, 1);
    let current: i64 = scalar(
        &state,
        "SELECT COUNT(*) FROM cbl_source_entries e \
         JOIN cbl_source_lists l ON l.id = e.list_id \
         WHERE l.source_path = 'DC/Batman/Batman.cbl'",
    )
    .await;
    assert_eq!(current, 2);
    let revision: String = scalar(&state, "SELECT revision_sha FROM cbl_sources").await;
    assert_eq!(revision, "bbb2222");
}

#[tokio::test]
async fn unchanged_reappearing_list_reactivates_without_replacing_entry_ids() {
    let (state, _guard) = setup().await;
    let body = cbl("Batman 001", &[("Batman", "1", Some("4059"), Some("9001"))]);
    let original = MirrorFixture::new(&[("DC/Batman/Batman.cbl", &body)]);
    let (parsed, failures) = original.parse();
    apply(&state, &parsed, &failures, "aaa1111", None).await;
    let entry_id: i32 = scalar(
        &state,
        "SELECT e.id FROM cbl_source_entries e
         JOIN cbl_source_lists l ON l.id = e.list_id
         WHERE l.source_path = 'DC/Batman/Batman.cbl'",
    )
    .await;

    let removed = MirrorFixture::new(&[]);
    let (empty, failures) = removed.parse();
    let removal = apply(&state, &empty, &failures, "bbb2222", None).await;
    assert_eq!(removal.deactivated_lists, 1);

    let restored = MirrorFixture::new(&[("DC/Batman/Batman.cbl", &body)]);
    let (parsed, failures) = restored.parse();
    let summary = apply(&state, &parsed, &failures, "ccc3333", None).await;
    assert_eq!(summary.updated_lists, 1);
    assert_eq!(summary.entries_written, 0);
    let restored_entry_id: i32 = scalar(
        &state,
        "SELECT e.id FROM cbl_source_entries e
         JOIN cbl_source_lists l ON l.id = e.list_id
         WHERE l.source_path = 'DC/Batman/Batman.cbl'",
    )
    .await;
    assert_eq!(restored_entry_id, entry_id);
    let active: bool = scalar(
        &state,
        "SELECT active FROM cbl_source_lists WHERE source_path = 'DC/Batman/Batman.cbl'",
    )
    .await;
    assert!(active);
    let revision: String = scalar(
        &state,
        "SELECT revision_sha FROM cbl_source_lists WHERE source_path = 'DC/Batman/Batman.cbl'",
    )
    .await;
    assert_eq!(revision, "ccc3333");
}

#[tokio::test]
async fn a_parse_failure_protects_the_last_known_good_list() {
    let (state, _guard) = setup().await;
    let fixture = MirrorFixture::new(&[(
        "Marvel/Fantastic Four.cbl",
        &cbl("Fantastic Four 001", &[("Fantastic Four", "1", None, None)]),
    )]);
    let (parsed, failures) = fixture.parse();
    apply(&state, &parsed, &failures, "ccc3333", None).await;

    let broken = MirrorFixture::new(&[(
        "Marvel/Fantastic Four.cbl",
        "<ReadingList><Books><Book Series=\"X\"></Books></ReadingList>",
    )]);
    let (empty, failures) = broken.parse();
    assert_eq!(failures.len(), 1);
    let summary = apply(&state, &empty, &failures, "ddd4444", None).await;
    assert_eq!(summary.deactivated_lists, 0);
    let row = {
        let conn = state.pool.get().await.unwrap();
        conn.query_one(
            "SELECT active, content_hash, revision_sha FROM cbl_source_lists \
             WHERE source_path = 'Marvel/Fantastic Four.cbl'",
            &[],
        )
        .await
        .unwrap()
    };
    assert!(row.get::<_, bool>(0));
    assert_eq!(row.get::<_, String>(1), parsed[0].content_hash);
    assert_eq!(row.get::<_, String>(2), "ccc3333");
}

#[tokio::test]
async fn trailing_character_data_is_protected_as_a_parse_failure() {
    let (state, _guard) = setup().await;
    let fixture = MirrorFixture::new(&[(
        "DC/Batman.cbl",
        &cbl("Batman 001", &[("Batman", "1", None, None)]),
    )]);
    let (parsed, failures) = fixture.parse();
    apply(&state, &parsed, &failures, "aaa1111", None).await;

    let broken = MirrorFixture::new(&[(
        "DC/Batman.cbl",
        "<ReadingList><Name>Batman 001</Name><Books /></ReadingList>junk",
    )]);
    let (empty, failures) = broken.parse();
    assert_eq!(failures.len(), 1);
    let summary = apply(&state, &empty, &failures, "bbb2222", None).await;
    assert_eq!(summary.deactivated_lists, 0);
    let row = {
        let conn = state.pool.get().await.unwrap();
        conn.query_one(
            "SELECT active, content_hash, revision_sha FROM cbl_source_lists \
             WHERE source_path = 'DC/Batman.cbl'",
            &[],
        )
        .await
        .unwrap()
    };
    assert!(row.get::<_, bool>(0));
    assert_eq!(row.get::<_, String>(1), parsed[0].content_hash);
    assert_eq!(row.get::<_, String>(2), "aaa1111");
}

#[tokio::test]
async fn repository_alias_is_reconciled_in_place() {
    let (state, _guard) = setup().await;
    let conn = state.pool.get().await.unwrap();
    conn.batch_execute(
        "INSERT INTO cbl_sources
            (repository, revision_sha, synced_at, created_at, updated_at)
         VALUES ('/mnt/bigdata/CBL-ReadingLists', 'old', NOW(), NOW(), NOW());
         INSERT INTO cbl_source_lists
            (source_id, source_path, name, declared_issue_count, content_hash,
             revision_sha, active, created_at, updated_at)
         VALUES (1, 'DC/One.cbl', 'One', 1, 'hash', 'old', TRUE, NOW(), NOW());",
    )
    .await
    .unwrap();
    let fixture = MirrorFixture::new(&[("DC/One.cbl", &cbl("One", &[("One", "1", None, None)]))]);
    let (parsed, failures) = fixture.parse();
    let summary = apply(
        &state,
        &parsed,
        &failures,
        "eee5555",
        Some("/mnt/bigdata/CBL-ReadingLists"),
    )
    .await;
    assert!(summary.repository_reconciled);
    let source_id: i32 = scalar(
        &state,
        "SELECT id FROM cbl_sources WHERE repository = 'JoshCLWren/CBL-ReadingLists'",
    )
    .await;
    assert_eq!(source_id, 1);
    let list_id: i32 = scalar(&state, "SELECT id FROM cbl_source_lists").await;
    assert_eq!(list_id, 1);
    let entries: i64 = scalar(&state, "SELECT COUNT(*) FROM cbl_source_entries").await;
    assert_eq!(entries, 1);
}

fn ensure_path(value: &Path) -> String {
    value.to_string_lossy().into_owned()
}

#[test]
fn fixture_paths_are_relative_to_the_mirror_root() {
    let fixture = MirrorFixture::new(&[("DC/Nested/One.cbl", "<ReadingList />")]);
    let paths = discover_cbl_files(&fixture.root).unwrap();
    assert_eq!(paths.len(), 1);
    assert_eq!(
        ensure_path(&paths[0]),
        ensure_path(&fixture.root.join("DC/Nested/One.cbl"))
    );
}
