#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Database tests for the migration runner. Each test creates and drops its own
//! scratch database on the server named by `MIGRATE_TEST_DATABASE_URL`.

use comicpile_migrate::{
    checksum, connect, run, BASELINE_ALEMBIC_HEAD, BASELINE_SCHEMA_ALEMBIC_HEAD, MIGRATIONS,
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

/// Simulate an Alembic-managed database at the original baseline schema head.
async fn alembic_managed_at_baseline(client: &Client) {
    client.batch_execute(MIGRATIONS[0].sql).await.unwrap();
    client.batch_execute("RESET ALL").await.unwrap();
    client
        .execute(
            "INSERT INTO public.alembic_version (version_num) VALUES ($1)",
            &[&BASELINE_SCHEMA_ALEMBIC_HEAD],
        )
        .await
        .unwrap();
}

/// Simulate an Alembic-managed database at the current Alembic head.
async fn alembic_managed_at_head(client: &Client) {
    for migration in MIGRATIONS {
        client.batch_execute(migration.sql).await.unwrap();
        client.batch_execute("RESET ALL").await.unwrap();
    }
    client
        .execute(
            "INSERT INTO public.alembic_version (version_num) VALUES ($1)",
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
    let versions: Vec<i64> = MIGRATIONS.iter().map(|m| m.version).collect();
    assert_eq!(report.applied, versions);
    assert!(report.adopted.is_empty());
    let stamp: String = client
        .query_one("SELECT version_num FROM public.alembic_version", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(stamp, BASELINE_ALEMBIC_HEAD);
    let adopted: bool = client
        .query_one(
            "SELECT bool_and(NOT adopted) FROM public.schema_migrations",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert!(adopted);
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
    assert!(queue_groups);
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
    let pending: Vec<i64> = MIGRATIONS.iter().skip(1).map(|m| m.version).collect();
    assert_eq!(report.applied, pending);
    assert_eq!(report.adopted, vec![MIGRATIONS[0].version]);
    let stamp: String = client
        .query_one("SELECT version_num FROM public.alembic_version", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(stamp, BASELINE_ALEMBIC_HEAD);
    let adopted: bool = client
        .query_one(
            "SELECT adopted FROM public.schema_migrations WHERE version = 1",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert!(adopted);
    let again = run(&mut client).await.unwrap();
    assert_eq!((again.applied, again.adopted), (vec![], vec![]));
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn alembic_database_at_current_head_is_adopted_without_rerunning() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    alembic_managed_at_head(&client).await;
    let report = run(&mut client).await.unwrap();
    let versions: Vec<i64> = MIGRATIONS.iter().map(|m| m.version).collect();
    assert_eq!(report.applied, Vec::<i64>::new());
    assert_eq!(report.adopted, versions);
    let all_adopted: bool = client
        .query_one(
            "SELECT bool_and(adopted) FROM public.schema_migrations",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert!(all_adopted);
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
        .execute(
            "UPDATE public.alembic_version SET version_num = $1",
            &["some_other_revision"],
        )
        .await
        .unwrap();
    let err = run(&mut client).await.unwrap_err();
    assert!(err.0.contains("alembic_version"), "{err}");
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn checksum_mismatch_is_refused() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    run(&mut client).await.unwrap();
    client
        .execute(
            "UPDATE public.schema_migrations SET checksum = 'bad' WHERE version = 1",
            &[],
        )
        .await
        .unwrap();
    let err = run(&mut client).await.unwrap_err();
    assert!(err.0.contains("modified after it was applied"), "{err}");
    drop(client);
    db.drop_database().await;
}
