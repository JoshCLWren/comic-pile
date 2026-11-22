#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Database tests for the refinery-backed migration runner. Each test creates
//! and drops its own scratch database on the server named by
//! `MIGRATE_TEST_DATABASE_URL`.

use comicpile_migrate::{
    connect, needs_work, run, BASELINE_ALEMBIC_HEAD, BASELINE_SCHEMA_ALEMBIC_HEAD,
};
use std::sync::atomic::{AtomicU32, Ordering};
use tokio_postgres::Client;

static NEXT: AtomicU32 = AtomicU32::new(0);

/// P0 guard (2026-11-18 production wipe): this harness creates and drops
/// databases, so the server must be local. It connects to a server-level
/// database (for example `/postgres`) and only ever drops `migrate_test_*`
/// databases it created itself, hence the host-only check.
fn assert_local_server(url: &str) {
    let rest = url
        .strip_prefix("postgresql://")
        .or_else(|| url.strip_prefix("postgres://"))
        .unwrap_or_else(|| panic!("MIGRATE_TEST_DATABASE_URL must be a postgres:// URL"));
    let (main, query) = rest.split_once('?').unwrap_or((rest, ""));
    let authority = main.split('/').next().unwrap_or("");
    let hostport = authority.rsplit_once('@').map_or(authority, |(_, h)| h);
    let mut hosts: Vec<String> = hostport
        .split(',')
        .map(|h| match h.strip_prefix('[') {
            Some(v6) => v6.split(']').next().unwrap_or("").to_string(),
            None => h.rsplit_once(':').map_or(h, |(h, _)| h).to_string(),
        })
        .collect();
    for pair in query.split('&') {
        // The driver percent-decodes keys; refuse encoded keys outright.
        assert!(
            !pair.split('=').next().unwrap_or("").contains('%'),
            "REFUSING to run destructive migration tests: percent-encoded URL query keys are not allowed"
        );
        if let Some((key, value)) = pair.split_once('=') {
            if key == "host" || key == "hostaddr" {
                hosts = value.split(',').map(str::to_string).collect();
            }
        }
    }
    let local = |h: &String| {
        matches!(h.as_str(), "localhost" | "127.0.0.1" | "::1")
            || h.starts_with('/')
            || h.starts_with("%2F")
    };
    assert!(
        !hosts.is_empty() && hosts.iter().all(local),
        "REFUSING to run destructive migration tests: MIGRATE_TEST_DATABASE_URL must point at a \
         local disposable Postgres (localhost/127.0.0.1/::1/unix socket)"
    );
}

fn admin_url() -> String {
    let url = std::env::var("MIGRATE_TEST_DATABASE_URL")
        .expect("MIGRATE_TEST_DATABASE_URL is required for migration runner tests");
    assert_local_server(&url);
    url
}

fn with_database(url: &str, database: &str) -> String {
    let (head, _) = url.rsplit_once('/').expect("URL has a database path");
    format!("{head}/{database}")
}

struct Scratch {
    name: String,
    url: String,
}

impl Scratch {
    async fn create() -> Scratch {
        let name = format!(
            "migrate_test_{}_{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::SeqCst)
        );
        let admin = connect(&admin_url()).await.unwrap();
        admin
            .batch_execute(&format!("CREATE DATABASE {name}"))
            .await
            .unwrap();
        Scratch {
            url: with_database(&admin_url(), &name),
            name,
        }
    }

    async fn client(&self) -> Client {
        connect(&self.url).await.unwrap()
    }

    async fn drop_database(self) {
        let admin = connect(&admin_url()).await.unwrap();
        admin
            .batch_execute(&format!("DROP DATABASE {} WITH (FORCE)", self.name))
            .await
            .unwrap();
    }
}

/// Simulate an Alembic-managed database at the baseline schema head: only the
/// V1 baseline schema is present.
async fn alembic_managed_at_baseline(client: &Client) {
    client
        .batch_execute(include_str!("../migrations/V1__baseline.sql"))
        .await
        .unwrap();
    client.batch_execute("RESET ALL").await.unwrap();
    client
        .execute(
            "INSERT INTO public.alembic_version (version_num) VALUES ($1)",
            &[&BASELINE_SCHEMA_ALEMBIC_HEAD],
        )
        .await
        .unwrap();
}

/// Simulate an Alembic-managed database at the current head: both schema
/// migrations are present, while later data repairs remain pending.
async fn alembic_managed_at_head(client: &Client) {
    alembic_managed_at_baseline(client).await;
    client
        .batch_execute(include_str!("../migrations/V2__queue_exclusion_groups.sql"))
        .await
        .unwrap();
    client.batch_execute("RESET ALL").await.unwrap();
    client
        .execute(
            "UPDATE public.alembic_version SET version_num = $1",
            &[&BASELINE_ALEMBIC_HEAD],
        )
        .await
        .unwrap();
}

#[tokio::test]
async fn fresh_database_gets_all_migrations_and_alembic_stamp() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    let report = run(&mut client).await.unwrap();
    assert_eq!((report.applied, report.adopted), (vec![1, 2, 3], vec![]));

    let stamp: String = client
        .query_one("SELECT version_num FROM public.alembic_version", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(stamp, BASELINE_ALEMBIC_HEAD);

    let recorded: i64 = client
        .query_one("SELECT count(*) FROM public.refinery_schema_history", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(recorded, 3);

    let threads: bool = client
        .query_one("SELECT to_regclass('public.threads') IS NOT NULL", &[])
        .await
        .unwrap()
        .get(0);
    assert!(threads);

    let queue_groups: bool = client
        .query_one(
            "SELECT to_regclass('public.queue_exclusion_groups') IS NOT NULL",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert!(queue_groups, "V2 must create the queue-exclusion schema");

    let again = run(&mut client).await.unwrap();
    assert_eq!((again.applied, again.adopted), (vec![], vec![]));
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn alembic_schema_at_head_is_adopted_and_data_repairs_run() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    alembic_managed_at_head(&client).await;
    client
        .batch_execute("CREATE TABLE public.adopt_preserved (marker int PRIMARY KEY)")
        .await
        .unwrap();
    client
        .execute(
            "INSERT INTO public.adopt_preserved (marker) VALUES (42)",
            &[],
        )
        .await
        .unwrap();

    let report = run(&mut client).await.unwrap();
    assert_eq!((report.applied, report.adopted), (vec![3], vec![1, 2]));

    let recorded: bool = client
        .query_one(
            "SELECT EXISTS(SELECT 1 FROM public.refinery_schema_history WHERE version = 2)",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert!(recorded);

    let marker: i32 = client
        .query_one("SELECT marker FROM public.adopt_preserved", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(marker, 42, "adoption must preserve existing data");

    let again = run(&mut client).await.unwrap();
    assert_eq!((again.applied, again.adopted), (vec![], vec![]));
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn cbl_natural_order_repair_runs_after_alembic_schema_adoption_3483() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    alembic_managed_at_head(&client).await;

    let mut spider_labels: Vec<String> = (7..=24).map(|number| number.to_string()).collect();
    spider_labels.extend(["2".to_string(), "1".to_string()]);
    let manual_labels = vec!["2".to_string(), "1".to_string()];

    // The high issues are read and the appended low issues are unread, so the
    // repair must move both their positions and the next-unread pointer to #1.
    let issue_values = |thread_id: i32, first_id: i32, labels: &[String], read_count: usize| {
        labels
            .iter()
            .enumerate()
            .map(|(index, label)| {
                let status = if index < read_count { "read" } else { "unread" };
                format!(
                    "({}, {}, '{}', {}, '{}', NOW())",
                    first_id + index as i32,
                    thread_id,
                    label,
                    index + 1,
                    status
                )
            })
            .collect::<Vec<_>>()
            .join(",\n          ")
    };
    let all_values = [
        issue_values(17977, 348300, &spider_labels, 18),
        issue_values(17978, 348400, &manual_labels, 0),
    ]
    .join(",\n          ");
    client
        .batch_execute(&format!(
            r#"
            INSERT INTO public.users (id, username)
            VALUES (3483, 'migrate-3483');
            INSERT INTO public.threads
              (id, title, format, issues_remaining, queue_position, status, user_id,
               total_issues, reading_progress)
            VALUES
              (17977, 'Ultimate Spider-Man', 'comic', 2, 1, 'active', 3483, 20, 'in_progress'),
              (17978, 'Manual order control', 'comic', 2, 2, 'active', 3483, 2, 'in_progress');
            INSERT INTO public.issues
              (id, thread_id, issue_number, position, status, created_at)
            VALUES
              {all_values};
            UPDATE public.threads AS t
            SET next_unread_issue_id = (
              SELECT i.id FROM public.issues AS i
              WHERE i.thread_id = t.id AND i.issue_number = '2'
            )
            WHERE t.id IN (17977, 17978);
            "#
        ))
        .await
        .unwrap();

    let report = run(&mut client).await.unwrap();
    assert_eq!((report.applied, report.adopted), (vec![3], vec![1, 2]));

    let rows = client
        .query(
            "SELECT thread_id, issue_number FROM public.issues \
             WHERE thread_id IN (17977, 17978) ORDER BY thread_id, position, id",
            &[],
        )
        .await
        .unwrap();
    let mut actual: std::collections::BTreeMap<i32, Vec<String>> =
        std::collections::BTreeMap::new();
    for row in rows {
        actual
            .entry(row.get(0))
            .or_default()
            .push(row.get::<_, String>(1));
    }
    let mut expected_spider = vec!["1".to_string(), "2".to_string()];
    expected_spider.extend((7..=24).map(|number| number.to_string()));
    assert_eq!(actual.get(&17977), Some(&expected_spider));
    assert_eq!(
        actual.get(&17978),
        Some(&manual_labels),
        "the data repair must not rewrite unrelated manual ordering"
    );

    let next_rows = client
        .query(
            "SELECT t.id, i.issue_number FROM public.threads AS t \
             JOIN public.issues AS i ON i.id = t.next_unread_issue_id \
             WHERE t.id IN (17977, 17978) ORDER BY t.id",
            &[],
        )
        .await
        .unwrap();
    let next: Vec<(i32, String)> = next_rows
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();
    assert_eq!(
        next,
        vec![(17977, "1".to_string()), (17978, "2".to_string())]
    );

    let again = run(&mut client).await.unwrap();
    assert_eq!((again.applied, again.adopted), (vec![], vec![]));
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn alembic_database_at_baseline_head_adopts_baseline_and_runs_pending() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    alembic_managed_at_baseline(&client).await;

    let report = run(&mut client).await.unwrap();
    assert_eq!((report.applied, report.adopted), (vec![2], vec![1]));

    let queue_groups: bool = client
        .query_one(
            "SELECT to_regclass('public.queue_exclusion_groups') IS NOT NULL",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert!(
        queue_groups,
        "the pending V2 migration must run after adoption"
    );

    let stamp: String = client
        .query_one("SELECT version_num FROM public.alembic_version", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        stamp, BASELINE_ALEMBIC_HEAD,
        "the old head must be moved forward"
    );

    let again = run(&mut client).await.unwrap();
    assert_eq!((again.applied, again.adopted), (vec![], vec![]));
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn alembic_database_at_another_revision_is_refused() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    alembic_managed_at_baseline(&client).await;
    client
        .batch_execute("UPDATE public.alembic_version SET version_num = 'zzzzzzzzzzzz'")
        .await
        .unwrap();
    let error = run(&mut client).await.unwrap_err();
    assert!(error.0.contains("zzzzzzzzzzzz"), "{error}");
    let tracked: i64 = client
        .query_one(
            "SELECT count(*) FROM pg_tables WHERE tablename = 'refinery_schema_history'",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(tracked, 0, "a refused run must leave no trace");
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn unmanaged_database_with_tables_is_refused() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    client
        .batch_execute("CREATE TABLE public.stray (id int)")
        .await
        .unwrap();
    let error = run(&mut client).await.unwrap_err();
    assert!(error.0.contains("unmanaged"), "{error}");
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn edited_applied_migration_is_refused() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    run(&mut client).await.unwrap();
    client
        .execute(
            "UPDATE public.refinery_schema_history SET checksum = 0 WHERE version = 1",
            &[],
        )
        .await
        .unwrap();
    let error = run(&mut client).await.unwrap_err();
    let msg = error.0.to_lowercase();
    assert!(
        msg.contains("divergent")
            || msg.contains("different")
            || msg.contains("checksum")
            || msg.contains("modified"),
        "expected checksum/divergence error, got: {error}"
    );
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn interrupted_fresh_setup_repairs_missing_alembic_stamp() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    run(&mut client).await.unwrap();

    // Simulate a crash after refinery recorded/applied the migrations but before
    // the Alembic head stamp was written.
    client
        .batch_execute("DELETE FROM public.alembic_version")
        .await
        .unwrap();

    let report = run(&mut client).await.unwrap();
    assert_eq!((report.applied, report.adopted), (vec![], vec![]));

    let stamp: String = client
        .query_one("SELECT version_num FROM public.alembic_version", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(stamp, BASELINE_ALEMBIC_HEAD);

    let recorded: bool = client
        .query_one(
            "SELECT EXISTS(SELECT 1 FROM public.refinery_schema_history WHERE version = 1)",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert!(recorded);
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn alembic_baseline_with_stale_deferred_checks_is_repaired_before_stamp() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    client
        .batch_execute(include_str!("../migrations/V1__baseline.sql"))
        .await
        .unwrap();
    client.batch_execute("RESET ALL").await.unwrap();
    client
        .batch_execute(
            "ALTER TABLE public.issue_external_identity_mappings \
             DROP CONSTRAINT IF EXISTS ck_issue_external_identity_status; \
             ALTER TABLE public.issue_external_identity_mappings \
             ADD CONSTRAINT ck_issue_external_identity_status \
             CHECK (status IN ('unresolved', 'candidate', 'confirmed', 'rejected')); \
             ALTER TABLE public.thread_external_series_mappings \
             DROP CONSTRAINT IF EXISTS ck_thread_external_series_status; \
             ALTER TABLE public.thread_external_series_mappings \
             ADD CONSTRAINT ck_thread_external_series_status \
             CHECK (status IN ('unresolved', 'candidate', 'confirmed', 'rejected')); \
             INSERT INTO public.alembic_version (version_num) VALUES ('c44050000002');",
        )
        .await
        .unwrap();

    let report = run(&mut client).await.unwrap();
    assert_eq!((report.applied, report.adopted), (vec![2], vec![1]));

    let stamp: String = client
        .query_one("SELECT version_num FROM public.alembic_version", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(stamp, BASELINE_ALEMBIC_HEAD);

    let issue_check: String = client
        .query_one(
            "SELECT pg_get_constraintdef(c.oid) \
             FROM pg_constraint c \
             JOIN pg_class t ON t.oid = c.conrelid \
             WHERE t.relname = 'issue_external_identity_mappings' \
               AND c.conname = 'ck_issue_external_identity_status'",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert!(issue_check.contains("deferred"), "{issue_check}");

    let thread_check: String = client
        .query_one(
            "SELECT pg_get_constraintdef(c.oid) \
             FROM pg_constraint c \
             JOIN pg_class t ON t.oid = c.conrelid \
             WHERE t.relname = 'thread_external_series_mappings' \
               AND c.conname = 'ck_thread_external_series_status'",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert!(thread_check.contains("deferred"), "{thread_check}");

    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn plan_refuses_divergent_applied_checksum() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    run(&mut client).await.unwrap();
    assert!(
        !needs_work(&mut client).await.unwrap(),
        "fully migrated db has no work"
    );
    client
        .execute(
            "UPDATE public.refinery_schema_history SET checksum = 0 WHERE version = 1",
            &[],
        )
        .await
        .unwrap();
    let error = needs_work(&mut client).await.unwrap_err();
    assert!(
        error.0.contains("divergent"),
        "expected divergence error, got: {error}"
    );
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn plan_refuses_unknown_applied_version() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    run(&mut client).await.unwrap();
    client
        .execute(
            "INSERT INTO public.refinery_schema_history (version, name, applied_on, checksum) \
             VALUES (999, 'from_a_newer_binary', '2026-11-20T00:00:00Z', '1')",
            &[],
        )
        .await
        .unwrap();
    let error = needs_work(&mut client).await.unwrap_err();
    assert!(
        error.0.contains("missing from this binary"),
        "expected unknown-version error, got: {error}"
    );
    drop(client);
    db.drop_database().await;
}
