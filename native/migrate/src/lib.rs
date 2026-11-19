//! Rust database migration runner.
//!
//! The schema history starts at a single BASELINE migration that is exactly the
//! schema of the Alembic head [`BASELINE_ALEMBIC_HEAD`]. Three situations are
//! handled when [`run`] is called:
//!
//! * A database already managed by this runner: only pending migrations apply.
//! * An empty database: the baseline is applied, and `alembic_version` is
//!   stamped with the baseline head so Alembic and Rust agree while both exist.
//! * A database managed by Alembic (production): when `alembic_version` equals
//!   [`BASELINE_ALEMBIC_HEAD`] the baseline is recorded as applied WITHOUT
//!   executing it. Any other revision, or any unmanaged schema, is refused.
//!
//! Everything runs in one transaction under an advisory lock, so concurrent
//! runners serialize and a failure leaves the database untouched.

use sha2::{Digest, Sha256};
use std::fmt;
use tokio_postgres::Client;

/// Alembic revision whose schema the baseline migration reproduces.
///
/// `i5378deferred01` is an idempotent repair that widens two already-wide
/// check constraints; it changes no canonical schema, so the baseline still
/// reproduces it. The stamp must track the real Alembic head for the Rust
/// migration runner to adopt already-managed production databases.
pub const BASELINE_ALEMBIC_HEAD: &str = "i5378deferred01";

/// Advisory-lock key serializing concurrent runners.
const MIGRATE_LOCK: i64 = 5_554_000_001;

/// One embedded, ordered migration.
pub struct Migration {
    pub version: i64,
    pub name: &'static str,
    pub sql: &'static str,
}

/// All migrations, in version order. Append only; never edit an applied one.
pub const MIGRATIONS: &[Migration] = &[Migration {
    version: 1,
    name: "baseline",
    sql: include_str!("../migrations/0001_baseline.sql"),
}];

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

/// What a [`run`] did.
#[derive(Debug, PartialEq, Eq)]
pub struct Report {
    /// Versions whose SQL was executed.
    pub applied: Vec<i64>,
    /// Versions recorded as applied without executing (Alembic adoption).
    pub adopted: Vec<i64>,
}

/// Hex SHA-256 of a migration body.
pub fn checksum(sql: &str) -> String {
    let digest = Sha256::digest(sql.as_bytes());
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
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

/// Bring the database to the latest migration. See the module docs.
pub async fn run(client: &mut Client) -> Result<Report, MigrateError> {
    let result = run_in_transaction(client).await;
    if result.is_err() {
        let _ = client.batch_execute("ROLLBACK").await;
    }
    // The baseline carries session-level settings (empty search_path, ...).
    client.batch_execute("RESET ALL").await?;
    result
}

async fn run_in_transaction(client: &mut Client) -> Result<Report, MigrateError> {
    client.batch_execute("BEGIN").await?;
    client
        .execute("SELECT pg_advisory_xact_lock($1)", &[&MIGRATE_LOCK])
        .await?;
    client
        .batch_execute(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations (\
                version bigint PRIMARY KEY, \
                name text NOT NULL, \
                checksum text NOT NULL, \
                adopted boolean NOT NULL DEFAULT false, \
                applied_at timestamptz NOT NULL DEFAULT now())",
        )
        .await?;
    let rows = client
        .query(
            "SELECT version, checksum FROM public.schema_migrations",
            &[],
        )
        .await?;
    let recorded: Vec<(i64, String)> = rows.iter().map(|r| (r.get(0), r.get(1))).collect();
    for (version, stored) in &recorded {
        let Some(migration) = MIGRATIONS.iter().find(|m| m.version == *version) else {
            return Err(MigrateError(format!(
                "database has migration {version} that this binary does not know; refusing to run an older binary"
            )));
        };
        if *stored != checksum(migration.sql) {
            return Err(MigrateError(format!(
                "migration {version} ({}) was modified after it was applied",
                migration.name
            )));
        }
    }

    let mut report = Report {
        applied: Vec::new(),
        adopted: Vec::new(),
    };
    let mut pending: Vec<&Migration> = MIGRATIONS
        .iter()
        .filter(|m| !recorded.iter().any(|(v, _)| *v == m.version))
        .collect();

    if recorded.is_empty() && adopt_alembic_baseline(client).await? {
        let baseline = MIGRATIONS
            .first()
            .ok_or_else(|| MigrateError("no baseline migration embedded".into()))?;
        record(client, baseline, true).await?;
        report.adopted.push(baseline.version);
        pending.retain(|m| m.version != baseline.version);
    }

    for migration in pending {
        client.batch_execute(migration.sql).await?;
        if migration.version == 1 {
            // Keep Alembic's bookkeeping truthful while both tools exist, so a
            // Rust-built database is indistinguishable from an Alembic-built one.
            client
                .execute(
                    "INSERT INTO public.alembic_version (version_num) VALUES ($1)",
                    &[&BASELINE_ALEMBIC_HEAD],
                )
                .await?;
        }
        record(client, migration, false).await?;
        report.applied.push(migration.version);
    }
    client.batch_execute("COMMIT").await?;
    Ok(report)
}

/// Decide whether this unmanaged database is an Alembic database at the
/// baseline head (adopt), or an empty one (apply). Anything else is an error.
async fn adopt_alembic_baseline(client: &Client) -> Result<bool, MigrateError> {
    let has_alembic: bool = client
        .query_one(
            "SELECT to_regclass('public.alembic_version') IS NOT NULL",
            &[],
        )
        .await?
        .get(0);
    if has_alembic {
        let revisions: Vec<String> = client
            .query("SELECT version_num FROM public.alembic_version", &[])
            .await?
            .iter()
            .map(|r| r.get(0))
            .collect();
        return match revisions.as_slice() {
            [only] if only == BASELINE_ALEMBIC_HEAD => Ok(true),
            other => Err(MigrateError(format!(
                "alembic_version is {other:?}, expected exactly [{BASELINE_ALEMBIC_HEAD:?}]; \
                 run Alembic to the baseline head before switching to the Rust runner"
            ))),
        };
    }
    let tables: i64 = client
        .query_one(
            "SELECT count(*) FROM pg_tables \
             WHERE schemaname = 'public' AND tablename <> 'schema_migrations'",
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
    Ok(false)
}

async fn record(client: &Client, migration: &Migration, adopted: bool) -> Result<(), MigrateError> {
    client
        .execute(
            "INSERT INTO public.schema_migrations (version, name, checksum, adopted) \
             VALUES ($1, $2, $3, $4)",
            &[
                &migration.version,
                &migration.name,
                &checksum(migration.sql),
                &adopted,
            ],
        )
        .await?;
    Ok(())
}
