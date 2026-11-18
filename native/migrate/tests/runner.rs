#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Database tests for the migration runner. Each test creates and drops its own
//! scratch database on the server named by `MIGRATE_TEST_DATABASE_URL`.

use comicpile_migrate::{checksum, connect, run, BASELINE_ALEMBIC_HEAD, MIGRATIONS};
use std::sync::atomic::{AtomicU32, Ordering};
use tokio_postgres::Client;

static NEXT: AtomicU32 = AtomicU32::new(0);

fn admin_url() -> String {
    std::env::var("MIGRATE_TEST_DATABASE_URL")
        .expect("MIGRATE_TEST_DATABASE_URL is required for migration runner tests")
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

/// Simulate an Alembic-managed database at the baseline head.
async fn alembic_managed(client: &Client) {
    client.batch_execute(MIGRATIONS[0].sql).await.unwrap();
    client.batch_execute("RESET ALL").await.unwrap();
    client
        .execute(
            "INSERT INTO public.alembic_version (version_num) VALUES ($1)",
            &[&BASELINE_ALEMBIC_HEAD],
        )
        .await
        .unwrap();
}

#[tokio::test]
async fn fresh_database_gets_baseline_and_alembic_stamp() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    let report = run(&mut client).await.unwrap();
    assert_eq!((report.applied, report.adopted), (vec![1], vec![]));
    let stamp: String = client
        .query_one("SELECT version_num FROM public.alembic_version", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(stamp, BASELINE_ALEMBIC_HEAD);
    let adopted: bool = client
        .query_one("SELECT adopted FROM public.schema_migrations", &[])
        .await
        .unwrap()
        .get(0);
    assert!(!adopted);
    let threads: bool = client
        .query_one("SELECT to_regclass('public.threads') IS NOT NULL", &[])
        .await
        .unwrap()
        .get(0);
    assert!(threads);
    let again = run(&mut client).await.unwrap();
    assert_eq!((again.applied, again.adopted), (vec![], vec![]));
    drop(client);
    db.drop_database().await;
}

#[tokio::test]
async fn alembic_database_at_head_is_adopted_without_rerunning() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    alembic_managed(&client).await;
    let report = run(&mut client).await.unwrap();
    assert_eq!((report.applied, report.adopted), (vec![], vec![1]));
    let adopted: bool = client
        .query_one("SELECT adopted FROM public.schema_migrations", &[])
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
async fn alembic_database_at_another_revision_is_refused() {
    let db = Scratch::create().await;
    let mut client = db.client().await;
    alembic_managed(&client).await;
    client
        .batch_execute("UPDATE public.alembic_version SET version_num = 'zzzzzzzzzzzz'")
        .await
        .unwrap();
    let error = run(&mut client).await.unwrap_err();
    assert!(error.0.contains("zzzzzzzzzzzz"), "{error}");
    let tracked: i64 = client
        .query_one(
            "SELECT count(*) FROM pg_tables WHERE tablename = 'schema_migrations'",
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
            "UPDATE public.schema_migrations SET checksum = $1",
            &[&checksum("other")],
        )
        .await
        .unwrap();
    let error = run(&mut client).await.unwrap_err();
    assert!(error.0.contains("modified after it was applied"), "{error}");
    drop(client);
    db.drop_database().await;
}
