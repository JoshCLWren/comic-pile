//! Rust database migration runner backed by [refinery].
//!
//! The schema history starts at a baseline migration (`V1__baseline.sql`) that
//! reproduces the schema of Alembic revision [`BASELINE_SCHEMA_ALEMBIC_HEAD`].
//! A subsequent incremental migration (`V2__queue_exclusion_groups.sql`) advances
//! it to the current Alembic head [`BASELINE_ALEMBIC_HEAD`]. When [`run`] is called:
//!
//! * A database already managed by refinery: only pending migrations apply.
//! * An empty database: all migrations apply, and `alembic_version` is stamped
//!   with the current head so Alembic and Rust agree while both exist.
//! * A database managed by Alembic (production): when `alembic_version` is at
//!   the baseline schema head, V1 is adopted and V2 runs; when it is already at
//!   the queue-exclusion or merged head, both migrations are adopted without
//!   executing. Any other revision, or any unmanaged schema, is refused.
//!
//! Adoption uses refinery's own fake-target facility (`Target::FakeVersion`)
//! guarded by `alembic_version`, so the recorded checksums/names come from the
//! embedded migrations refinery will later verify. A session advisory lock
//! serializes concurrent runners.

use refinery::Target;
use std::fmt;
use tokio_postgres::Client;

mod embedded {
    use refinery::embed_migrations;
    embed_migrations!("migrations");
}

/// Alembic revision whose schema `V1__baseline.sql` reproduces.
///
/// `i5378deferred01` is an idempotent repair that widens two already-wide check
/// constraints; it changes no canonical schema, so the baseline still reproduces
/// it. The V2 queue-exclusion migration then brings the schema to the current head.
pub const BASELINE_SCHEMA_ALEMBIC_HEAD: &str = "c44050000002";

/// Schema-equivalent deferred-identity repair revision (#5378).
const DEFERRED_IDENTITY_REPAIR_HEAD: &str = "i5378deferred01";

/// Alembic head after the queue-exclusion schema migration (before the merge).
const QUEUE_EXCLUSION_HEAD: &str = "s54350000001";

/// Current Alembic head: the merge of the deferred repair and queue-exclusion heads.
pub const BASELINE_ALEMBIC_HEAD: &str = "m54i537800001";

/// Latest refinery migration version embedded in this binary.
const LATEST_MIGRATION_VERSION: i32 = 2;

/// Advisory-lock key serializing concurrent runners.
const MIGRATE_LOCK: i64 = 5_554_000_001;

/// Schema-qualified history table so migrations that clear `search_path`
/// (the baseline dump does) cannot hide refinery's bookkeeping table.
const MIGRATION_TABLE: &str = "public.refinery_schema_history";

/// Failure running migrations.
#[derive(Debug)]
pub struct MigrateError(pub String);

impl fmt::Display for MigrateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for MigrateError {}

impl From<tokio_postgres::Error> for MigrateError {
    fn from(error: tokio_postgres::Error) -> Self {
        match error.as_db_error() {
            Some(db) => MigrateError(format!("database error: {}", db.message())),
            None => MigrateError(format!("database error: {error}")),
        }
    }
}

impl From<refinery::Error> for MigrateError {
    fn from(error: refinery::Error) -> Self {
        MigrateError(format!("migration error: {error}"))
    }
}

/// What a [`run`] did.
#[derive(Debug, PartialEq, Eq)]
pub struct Report {
    /// Versions whose SQL was executed.
    pub applied: Vec<i32>,
    /// Versions recorded as applied without executing (Alembic adoption).
    pub adopted: Vec<i32>,
}

#[derive(Debug, PartialEq, Eq)]
enum AlembicState {
    /// `alembic_version` is at the merged head (or the queue-exclusion head):
    /// both migrations are already reflected in the schema.
    CurrentHead,
    /// `alembic_version` is at the baseline schema head (or its no-op deferred
    /// repair): only V1 is reflected; V2 must still run.
    BaselineHead,
    /// `alembic_version` exists but has no revision row.
    Empty,
    /// `alembic_version` contains other revisions.
    Other(Vec<String>),
}

/// Connect, using TLS when the URL's `sslmode` asks for it.
pub async fn connect(url: &str) -> Result<Client, MigrateError> {
    let config: tokio_postgres::Config = url
        .parse()
        .map_err(|e| MigrateError(format!("invalid database URL: {e}")))?;
    let tls = native_tls::TlsConnector::new()
        .map_err(|e| MigrateError(format!("TLS initialisation failed: {e}")))?;
    let (client, connection) = config
        .connect(postgres_native_tls::MakeTlsConnector::new(tls))
        .await?;
    tokio::spawn(connection);
    Ok(client)
}

fn runner() -> refinery::Runner {
    let mut runner = embedded::migrations::runner();
    runner.set_migration_table_name(MIGRATION_TABLE);
    runner
}

/// Bring the database to the latest migration. See the module docs.
pub async fn run(client: &mut Client) -> Result<Report, MigrateError> {
    client
        .execute("SELECT pg_advisory_lock($1)", &[&MIGRATE_LOCK])
        .await?;
    let result = run_locked(client).await;
    let unlock = client
        .execute("SELECT pg_advisory_unlock($1)", &[&MIGRATE_LOCK])
        .await;
    // The baseline carries session-level settings (empty search_path, ...).
    client.batch_execute("RESET ALL").await?;
    match result {
        Err(e) => {
            let _ = unlock;
            Err(e)
        }
        Ok(report) => {
            unlock?;
            Ok(report)
        }
    }
}

async fn run_locked(client: &mut Client) -> Result<Report, MigrateError> {
    let mut report = Report {
        applied: Vec::new(),
        adopted: Vec::new(),
    };

    let alembic_state = alembic_state(client).await?;
    let baseline_recorded = refinery_has_baseline(client).await?;

    match &alembic_state {
        Some(AlembicState::CurrentHead) | Some(AlembicState::BaselineHead) | None => {}
        Some(AlembicState::Empty) if baseline_recorded => {
            // A verified refinery-managed baseline with an empty alembic_version
            // row means a previous run applied/stamped history but failed before
            // writing the Alembic revision; repair it below.
        }
        Some(AlembicState::Empty) => {
            return Err(MigrateError(
                "alembic_version is empty, expected a supported head; \
                 run Alembic to a supported head before switching to the Rust runner"
                    .to_string(),
            ));
        }
        Some(AlembicState::Other(revisions)) => {
            return Err(MigrateError(format!(
                "alembic_version is {revisions:?}, expected a supported head; \
                 run Alembic to a supported head before switching to the Rust runner"
            )));
        }
    }

    if !baseline_recorded {
        match alembic_state {
            Some(AlembicState::CurrentHead) => {
                // Alembic at the queue-exclusion/merged head already has both
                // schemas: record both migrations as adopted without executing.
                runner()
                    .set_target(Target::FakeVersion(LATEST_MIGRATION_VERSION))
                    .run_async(client)
                    .await?;
                report.adopted.extend([1, LATEST_MIGRATION_VERSION]);
            }
            Some(AlembicState::BaselineHead) => {
                // Alembic at the baseline schema head already has the V1 schema:
                // adopt V1, then apply the pending V2 migration below.
                runner()
                    .set_target(Target::FakeVersion(1))
                    .run_async(client)
                    .await?;
                report.adopted.push(1);
            }
            _ => ensure_empty_or_refinery_managed(client).await?,
        }
    }

    let outcome = runner().run_async(client).await?;
    report
        .applied
        .extend(outcome.applied_migrations().iter().map(|m| m.version()));

    ensure_deferred_identity_status(client).await?;
    ensure_alembic_stamp(client).await?;
    Ok(report)
}

async fn alembic_state(client: &Client) -> Result<Option<AlembicState>, MigrateError> {
    let Some(revisions) = alembic_revisions(client).await? else {
        return Ok(None);
    };
    Ok(Some(match revisions.as_slice() {
        [only] if only == BASELINE_ALEMBIC_HEAD || only == QUEUE_EXCLUSION_HEAD => {
            AlembicState::CurrentHead
        }
        [only] if only == BASELINE_SCHEMA_ALEMBIC_HEAD || only == DEFERRED_IDENTITY_REPAIR_HEAD => {
            AlembicState::BaselineHead
        }
        [] => AlembicState::Empty,
        _ => AlembicState::Other(revisions),
    }))
}

async fn alembic_revisions(client: &Client) -> Result<Option<Vec<String>>, MigrateError> {
    let has_alembic: bool = client
        .query_one(
            "SELECT to_regclass('public.alembic_version') IS NOT NULL",
            &[],
        )
        .await?
        .get(0);
    if !has_alembic {
        return Ok(None);
    }
    let revisions = client
        .query("SELECT version_num FROM public.alembic_version", &[])
        .await?
        .iter()
        .map(|r| r.get(0))
        .collect();
    Ok(Some(revisions))
}

async fn refinery_has_baseline(client: &Client) -> Result<bool, MigrateError> {
    let has_refinery: bool = client
        .query_one(
            "SELECT to_regclass('public.refinery_schema_history') IS NOT NULL",
            &[],
        )
        .await?
        .get(0);
    if !has_refinery {
        return Ok(false);
    }
    Ok(client
        .query_opt(
            "SELECT 1 FROM public.refinery_schema_history WHERE version = 1",
            &[],
        )
        .await?
        .is_some())
}

/// Refuse to baseline a database that has tables but is not managed by
/// Alembic or by this runner's refinery history.
async fn ensure_empty_or_refinery_managed(client: &Client) -> Result<(), MigrateError> {
    let tables: i64 = client
        .query_one(
            "SELECT count(*) FROM pg_tables \
             WHERE schemaname = 'public' AND tablename <> 'refinery_schema_history'",
            &[],
        )
        .await?
        .get(0);
    if tables > 0 {
        return Err(MigrateError(
            "public schema has tables but no alembic_version; refusing to baseline an unmanaged database"
                .into(),
        ));
    }
    Ok(())
}

/// Repair external-identity status checks to allow `deferred` (#5378).
///
/// Databases stamped at the baseline Alembic head may have stale check
/// constraints that predate the deferred-status repair. The current merged
/// Rust/Alembic head includes that repair, so upgrades apply it idempotently
/// before stamping the current head.
async fn ensure_deferred_identity_status(client: &Client) -> Result<(), MigrateError> {
    client
        .batch_execute(
            "DO $$\n\
             BEGIN\n\
               IF EXISTS (\n\
                 SELECT 1 FROM information_schema.tables\n\
                 WHERE table_schema = 'public' AND table_name = 'issue_external_identity_mappings'\n\
               ) THEN\n\
                 ALTER TABLE public.issue_external_identity_mappings\n\
                   DROP CONSTRAINT IF EXISTS ck_issue_external_identity_status;\n\
                 ALTER TABLE public.issue_external_identity_mappings\n\
                   ADD CONSTRAINT ck_issue_external_identity_status\n\
                   CHECK (status IN ('unresolved', 'candidate', 'confirmed', 'rejected', 'deferred'));\n\
               END IF;\n\
               IF EXISTS (\n\
                 SELECT 1 FROM information_schema.tables\n\
                 WHERE table_schema = 'public' AND table_name = 'thread_external_series_mappings'\n\
               ) THEN\n\
                 ALTER TABLE public.thread_external_series_mappings\n\
                   DROP CONSTRAINT IF EXISTS ck_thread_external_series_status;\n\
                 ALTER TABLE public.thread_external_series_mappings\n\
                   ADD CONSTRAINT ck_thread_external_series_status\n\
                   CHECK (status IN ('unresolved', 'candidate', 'confirmed', 'rejected', 'deferred'));\n\
               END IF;\n\
             END\n\
             $$;",
        )
        .await?;
    Ok(())
}

/// Keep Alembic's bookkeeping truthful while both tools exist.
///
/// Replace the revision row so an older head (for example `c44050000002`) is
/// moved forward to the current head, rather than leaving the stale stamp in
/// place via `ON CONFLICT DO NOTHING`.
async fn ensure_alembic_stamp(client: &Client) -> Result<(), MigrateError> {
    let has_alembic: bool = client
        .query_one(
            "SELECT to_regclass('public.alembic_version') IS NOT NULL",
            &[],
        )
        .await?
        .get(0);
    if !has_alembic {
        client
            .batch_execute(
                "CREATE TABLE public.alembic_version (version_num character varying(32) NOT NULL)",
            )
            .await?;
    }
    client
        .execute("DELETE FROM public.alembic_version", &[])
        .await?;
    client
        .execute(
            "INSERT INTO public.alembic_version (version_num) VALUES ($1)",
            &[&BASELINE_ALEMBIC_HEAD],
        )
        .await?;
    Ok(())
}
