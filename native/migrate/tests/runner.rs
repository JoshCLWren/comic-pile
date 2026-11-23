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

/// Simulate an Alembic-managed database at the current head: both migration
/// schemas are present.
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

    let release_list_link: bool = client
        .query_one(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns \
             WHERE table_schema = 'public' \
               AND table_name = 'reading_plan_release_sources' \
               AND column_name = 'custom_cbl_list_id')",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert!(release_list_link, "V3 must add the Reading List association");

    let again = run(&mut client).await.unwrap();
    assert_eq!((again.applied, again.adopted), (vec![], vec![]));
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn alembic_database_at_head_is_adopted_without_rerunning() {
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
async fn release_list_backfill_preserves_subscriptions_and_requires_unambiguous_provenance() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    alembic_managed_at_head(&client).await;
    client
        .batch_execute(
            "INSERT INTO public.users (id, username) VALUES
                 (1, 'release-owner'), (2, 'foreign-owner');
             INSERT INTO public.continuity_plans
                 (id, user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
             VALUES
                 (101, 1, 'Single', 'informational', '[]'::json, '[]'::json, NOW(), NOW()),
                 (102, 1, 'Ambiguous', 'informational', '[]'::json, '[]'::json, NOW(), NOW()),
                 (103, 1, 'Foreign', 'informational', '[]'::json, '[]'::json, NOW(), NOW()),
                 (104, 1, 'Unpaired', 'informational', '[]'::json, '[]'::json, NOW(), NOW());
             INSERT INTO public.threads
                 (id, title, format, issues_remaining, queue_position, status, user_id)
             VALUES
                 (1001, 'One', 'Comic', 0, 1, 'active', 1),
                 (1002, 'Two', 'Comic', 0, 2, 'active', 1),
                 (1003, 'Three', 'Comic', 0, 3, 'active', 1),
                 (1004, 'Four', 'Comic', 0, 4, 'active', 1);
             INSERT INTO public.external_identities
                 (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
             VALUES (9001, 'comicvine', 'series', '4050-9001', '{}'::json, NOW(), NOW());
             INSERT INTO public.custom_cbl_lists
                 (id, user_id, name, mode, created_at, updated_at)
             VALUES
                 (201, 1, 'Owned A', 'loose', NOW(), NOW()),
                 (202, 1, 'Owned B', 'loose', NOW(), NOW()),
                 (203, 2, 'Foreign', 'loose', NOW(), NOW());
             INSERT INTO public.reading_plan_sources
                 (plan_id, raw_source_path, custom_cbl_list_id, recorded_at)
             VALUES
                 (101, 'fixture://single', 201, NOW()),
                 (102, 'fixture://ambiguous-a', 201, NOW()),
                 (102, 'fixture://ambiguous-b', 202, NOW()),
                 (103, 'fixture://foreign', 203, NOW());
             INSERT INTO public.reading_plan_release_sources
                 (id, plan_id, thread_id, external_identity_id, enabled,
                  last_synced_at, created_at, updated_at)
             VALUES
                 (1001, 101, 1001, 9001, FALSE,
                  '2024-01-02T03:04:05+00', '2023-01-01T00:00:00+00', '2024-01-02T03:04:05+00'),
                 (1002, 102, 1002, 9001, TRUE,
                  '2024-02-03T04:05:06+00', '2023-01-02T00:00:00+00', '2024-02-03T04:05:06+00'),
                 (1003, 103, 1003, 9001, FALSE,
                  NULL, '2023-01-03T00:00:00+00', '2023-01-03T00:00:00+00'),
                 (1004, 104, 1004, 9001, TRUE,
                  '2024-03-04T05:06:07+00', '2023-01-04T00:00:00+00', '2024-03-04T05:06:07+00');",
        )
        .await
        .unwrap();

    async fn snapshot(client: &Client) -> Vec<(i32, bool, Option<String>, String, String)> {
        client
            .query(
                "SELECT id, enabled, last_synced_at::text, created_at::text, updated_at::text \
                 FROM public.reading_plan_release_sources ORDER BY id",
                &[],
            )
            .await
            .unwrap()
            .iter()
            .map(|row| {
                (
                    row.get::<_, i32>(0),
                    row.get::<_, bool>(1),
                    row.get::<_, Option<String>>(2),
                    row.get::<_, String>(3),
                    row.get::<_, String>(4),
                )
            })
            .collect()
    }
    let before = snapshot(&client).await;

    let report = run(&mut client).await.unwrap();
    assert_eq!((report.applied, report.adopted), (vec![3], vec![1, 2]));

    let after = snapshot(&client).await;
    assert_eq!(after, before, "subscription identity/state/timestamps must survive");
    let links: Vec<Option<i32>> = client
        .query(
            "SELECT custom_cbl_list_id FROM public.reading_plan_release_sources ORDER BY id",
            &[],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| row.get(0))
        .collect();
    assert_eq!(links, vec![Some(201), None, None, None]);

    let again = run(&mut client).await.unwrap();
    assert_eq!((again.applied, again.adopted), (vec![], vec![]));
    assert_eq!(snapshot(&client).await, before);
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn alembic_database_at_baseline_head_adopts_baseline_and_runs_pending() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    alembic_managed_at_baseline(&client).await;

    let report = run(&mut client).await.unwrap();
    assert_eq!((report.applied, report.adopted), (vec![2, 3], vec![1]));

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
    assert_eq!((report.applied, report.adopted), (vec![2, 3], vec![1]));

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
