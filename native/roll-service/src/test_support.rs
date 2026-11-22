//! Canonical PostgreSQL schema fixture for native Roll tests.
//!
//! The native Roll service is a pure cutover of the Roll API: it reads and
//! writes rows and never issues schema DDL. Tests therefore must not hand-write
//! tables, either — hand-rolled fixtures only approximated production, which is
//! how a production-only schema difference escaped the suite (#4578). The
//! #4535 incident itself was ultimately an axum path-parameter defect
//! (#4583); the dead-pooled-connection retry (#4572, #4732) is a separate
//! robustness path, and a clean `pg_terminate_backend` may not exercise that
//! retry branch (#4578).
//!
//! Every test loads the canonical Alembic fixture, a `pg_dump --schema-only` of a database
//! that Alembic migrated to head. Regenerate it with `make roll-test-schema`;
//! CI regenerates and diffs it, so a stale fixture fails instead of drifting.
//!
//! Test scaffolding only: unwraps may panic loudly in tests, never in handlers,
//! so the production `unwrap_used`/`expect_used` denies do not apply here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

use crate::{db, AppState};

/// Load the canonical Alembic head schema only when a test actually needs it.
///
/// `V1__baseline.sql` is the original Alembic baseline fixture; later SQL
/// migrations advance it to the current Alembic head. Loading every migration
/// in version order keeps tests aligned with `comicpile-migrate up`.
fn canonical_schema() -> String {
    let migrations_dir =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../migrate/migrations");
    let mut paths: Vec<std::path::PathBuf> = std::fs::read_dir(&migrations_dir)
        .unwrap_or_else(|error| {
            panic!(
                "read migrations directory {}: {error}",
                migrations_dir.display()
            )
        })
        .filter_map(|entry| entry.ok().map(|entry| entry.path()))
        .filter(|path| path.extension().is_some_and(|ext| ext == "sql"))
        .collect();
    paths.sort();
    assert!(
        !paths.is_empty(),
        "no migration SQL files found in {}",
        migrations_dir.display()
    );
    let mut schema = String::new();
    for path in paths {
        let sql = std::fs::read_to_string(&path).unwrap_or_else(|error| {
            panic!(
                "read canonical schema migration {}: {error}",
                path.display()
            )
        });
        schema.push_str(&sql);
        if !sql.ends_with('\n') {
            schema.push('\n');
        }
    }
    schema
}

/// Advisory-lock key that serializes the one-time schema load.
const SCHEMA_LOAD_LOCK: i64 = 4_535_000_001;

/// Create the canonical schema in `public` when this database lacks it.
///
/// Idempotent and safe for parallel test threads and binaries: a transaction
/// advisory lock plus the `public.threads` existence check mean exactly one
/// loader runs, and every other caller waits for it and then proceeds against
/// the same schema. A loader that loses the race to a duplicate-object error
/// (another process applied the fixture without our lock) rolls back and
/// re-probes instead of failing the test.
pub async fn ensure_schema(state: &AppState) {
    assert_safe_test_database(&required_test_admin_url());
    for _ in 0..3 {
        let connection = db::checkout(state).await.expect("schema connection");
        connection
            .batch_execute("BEGIN")
            .await
            .expect("schema transaction");
        connection
            .execute("SELECT pg_advisory_xact_lock($1)", &[&SCHEMA_LOAD_LOCK])
            .await
            .expect("schema load lock");
        let loaded: bool = connection
            .query_one("SELECT to_regclass('public.threads') IS NOT NULL", &[])
            .await
            .expect("schema probe")
            .get(0);
        if loaded {
            connection
                .batch_execute("COMMIT")
                .await
                .expect("schema commit");
            return;
        }
        match connection.batch_execute(&canonical_schema()).await {
            Ok(()) => {
                connection
                    .batch_execute("COMMIT")
                    .await
                    .expect("schema commit");
                return;
            }
            Err(error) if is_duplicate_object(&error) => {
                connection
                    .batch_execute("ROLLBACK")
                    .await
                    .expect("schema rollback");
            }
            Err(error) => panic!("load Alembic schema fixture: {error:?}"),
        }
    }
    let connection = db::checkout(state)
        .await
        .expect("schema recheck connection");
    let loaded: bool = connection
        .query_one("SELECT to_regclass('public.threads') IS NOT NULL", &[])
        .await
        .expect("schema recheck")
        .get(0);
    assert!(loaded, "the canonical schema never finished loading");
}

/// Whether a failed schema load collided with objects another loader created.
fn is_duplicate_object(error: &tokio_postgres::Error) -> bool {
    matches!(
        error.code().map(|code| code.code()),
        Some("42P06" | "42P07" | "42710")
    )
}

/// Empty every application table, keeping the canonical schema in place.
///
/// The table list comes from the catalog rather than a hand-written list, so new
/// migrations are covered automatically and no fixture can go stale.
pub async fn truncate_application_tables(state: &AppState) {
    assert_safe_test_database(&required_test_admin_url());
    let connection = db::checkout(state).await.expect("truncate connection");
    let rows = connection
        .query(
            "SELECT tablename FROM pg_tables \
             WHERE schemaname = 'public' AND tablename NOT IN ('alembic_version', 'refinery_schema_history') \
             ORDER BY tablename",
            &[],
        )
        .await
        .expect("catalog tables");
    let tables = rows
        .iter()
        .map(|row| format!("public.\"{}\"", row.get::<_, String>(0)))
        .collect::<Vec<_>>()
        .join(", ");
    connection
        .batch_execute(&format!("TRUNCATE TABLE {tables} CASCADE"))
        .await
        .expect("truncate application tables");
    // `RESTART IDENTITY` needs sequence ownership, which the DML-only test role
    // deliberately lacks. `setval` only needs UPDATE on the sequence, so reset
    // the counters the same way without granting ownership.
    connection
        .batch_execute(
            "SELECT setval(c.oid::regclass, 1, false) \
             FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace \
             WHERE c.relkind = 'S' AND n.nspname = 'public'",
        )
        .await
        .expect("reset application sequences");
}

/// Role every Rust test connects as.
///
/// It holds DML only, so the suite physically cannot create, alter or drop
/// persistent schema — PostgreSQL enforces the rule instead of a text linter.
/// Temporary objects are still allowed: `CREATE TEMP` needs `TEMP` on the
/// database, not `CREATE` on the schema.
const TEST_ROLE: &str = "roll_test_dml";
const TEST_ROLE_PASSWORD: &str = "roll-test-dml";

/// Require a disposable database for every database-backed Rust test.
///
/// Do not offer an implicit or opt-in "skip" path. Tests returning success
/// without executing their SQL made missing local DB configuration look green.
fn require_test_db_config(url: Option<String>, skip_requested: bool) -> String {
    assert!(
        !skip_requested,
        "RUST_ROLL_ALLOW_DB_SKIP is forbidden: database-backed Rust tests must execute"
    );
    url.expect(
        "RUST_ROLL_TEST_DATABASE_URL is required for database-backed Rust tests. \
         Set it to a disposable PostgreSQL database provisioned for the canonical \
         Alembic schema (see native/roll-service/README.md), then rerun cargo test --locked.",
    )
}

/// Refuse any database that is not a local, disposable test database.
///
/// P0 incident 2026-11-18: a test run pointed at production truncated every
/// application table. Every destructive test path (role provisioning, schema
/// load, truncate, reset) must pass through this guard first. It panics unless
/// the URL is a `postgres://`/`postgresql://` URL whose host (including any
/// `host=`/`hostaddr=` query override) is `localhost`, `127.0.0.1`, `::1` or a
/// unix-socket path, AND whose database name (including any `dbname=` override)
/// contains `test`. CI service containers satisfy this: they run on
/// `127.0.0.1` with `*_test` database names.
pub fn assert_safe_test_database(url: &str) {
    if let Err(reason) = check_safe_test_database(url) {
        panic!(
            "REFUSING to run destructive test setup: {reason}. Database-backed tests may only \
             target a disposable LOCAL Postgres (host localhost/127.0.0.1/::1/unix socket) whose \
             database name contains \"test\". Never point RUST_ROLL_TEST_DATABASE_URL at a \
             shared, staging or production database."
        );
    }
}

/// Pure host-only variant for scratch-database harnesses that connect to a
/// server-level database (for example `/postgres`) and only create/drop
/// databases they named themselves.
pub fn check_local_host(url: &str) -> Result<(), String> {
    parse_target(url).and_then(|(hosts, _)| check_hosts(&hosts))
}

fn check_hosts(hosts: &[String]) -> Result<(), String> {
    if hosts.is_empty() {
        return Err("no host in database URL (implicit host is not allowed)".to_string());
    }
    for host in hosts {
        let host = host.trim_start_matches('[').trim_end_matches(']');
        let local = matches!(host, "localhost" | "127.0.0.1" | "::1") || host.starts_with('/');
        if !local {
            return Err(format!("host {host:?} is not local"));
        }
    }
    Ok(())
}

fn check_safe_test_database(url: &str) -> Result<(), String> {
    let (hosts, database) = parse_target(url)?;
    check_hosts(&hosts)?;
    if !database.to_ascii_lowercase().contains("test") {
        return Err(format!(
            "database name {database:?} does not contain \"test\""
        ));
    }
    Ok(())
}

/// Extract (hosts, database) the way tokio-postgres would resolve them.
fn parse_target(url: &str) -> Result<(Vec<String>, String), String> {
    let rest = url
        .strip_prefix("postgresql://")
        .or_else(|| url.strip_prefix("postgres://"))
        .ok_or_else(|| "only postgres:// or postgresql:// URLs are accepted".to_string())?;
    let (main, query) = rest.split_once('?').unwrap_or((rest, ""));
    let (authority, path) = main.split_once('/').unwrap_or((main, ""));
    let hostport = authority.rsplit_once('@').map_or(authority, |(_, h)| h);
    let mut hosts: Vec<String> = Vec::new();
    for part in hostport.split(',').filter(|p| !p.is_empty()) {
        let host = if let Some(stripped) = part.strip_prefix('[') {
            stripped.split(']').next().unwrap_or("").to_string()
        } else {
            part.rsplit_once(':').map_or(part, |(h, _)| h).to_string()
        };
        hosts.push(percent_decode(&host));
    }
    let mut database = percent_decode(path);
    for pair in query.split('&').filter(|p| !p.is_empty()) {
        let (key, value) = pair.split_once('=').unwrap_or((pair, ""));
        // The driver percent-decodes keys, so `%64bname=` is `dbname=`.
        match percent_decode(key).as_str() {
            "host" | "hostaddr" => {
                hosts = value.split(',').map(percent_decode).collect::<Vec<_>>();
            }
            "dbname" => database = percent_decode(value),
            _ => {}
        }
    }
    Ok((hosts, database))
}

/// Require the test admin DSN; never allow a missing env var to silently skip.
pub fn required_test_admin_url() -> String {
    let url = require_test_db_config(
        std::env::var("RUST_ROLL_TEST_DATABASE_URL").ok(),
        std::env::var_os("RUST_ROLL_ALLOW_DB_SKIP").is_some(),
    );
    assert_safe_test_database(&url);
    url
}

/// The admin DSN, used only to apply the Alembic fixture and provision the role.
///
/// Keep the existing Option signature for callers, but never return None:
/// this lets existing test-state consumers fail loudly instead of self-skipping.
fn admin_url() -> Option<String> {
    Some(required_test_admin_url())
}

/// Rewrite a DSN to connect as the DML-only role.
///
/// Fails closed: a keyword/value DSN cannot be rewritten safely here, and URI
/// query parameters such as `?user=` override URI credentials in
/// `tokio-postgres`, so they are stripped rather than forwarded. Anything this
/// function cannot reason about is a panic, never a silent fall-back to admin.
fn percent_decode(input: &str) -> String {
    let bytes = input.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' && index + 2 < bytes.len() {
            let high = (bytes[index + 1] as char).to_digit(16);
            let low = (bytes[index + 2] as char).to_digit(16);
            if let (Some(high), Some(low)) = (high, low) {
                out.push((high * 16 + low) as u8);
                index += 3;
                continue;
            }
        }
        out.push(bytes[index]);
        index += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn restricted_url(admin: &str) -> String {
    let Some((scheme, rest)) = admin.split_once("://") else {
        panic!(
            "RUST_ROLL_TEST_DATABASE_URL must be a postgresql:// URI so the suite can be \
             restricted to the DML-only `{TEST_ROLE}` role; a keyword/value DSN cannot be \
             rewritten safely, and silently keeping admin rights would defeat the guard"
        );
    };
    let (before_query, query) = match rest.split_once('?') {
        Some((head, tail)) => (head, Some(tail)),
        None => (rest, None),
    };
    let (authority, path) = match before_query.split_once('/') {
        Some((host, database)) => (host, format!("/{database}")),
        None => (before_query, String::new()),
    };
    let host = authority
        .rsplit_once('@')
        .map(|(_, host)| host)
        .unwrap_or(authority);

    let mut url = format!("{scheme}://{TEST_ROLE}:{TEST_ROLE_PASSWORD}@{host}{path}");
    if let Some(query) = query {
        let kept: Vec<&str> = query
            .split('&')
            .filter(|pair| {
                // Percent-encoded keys (`%75ser`) are decoded by the driver, so
                // decode before comparing or they slip through unchecked.
                let key = percent_decode(pair.split('=').next().unwrap_or_default());
                !key.eq_ignore_ascii_case("user") && !key.eq_ignore_ascii_case("password")
            })
            .collect();
        if !kept.is_empty() {
            url.push('?');
            url.push_str(&kept.join("&"));
        }
    }
    url
}

/// Signing secret every canonical test state uses, so tests can mint tokens
/// that the mounted router accepts without restating the value.
pub const TEST_JWT_SECRET: &str = "synthetic-native-test";

/// Build an [`AppState`] for a test binary with the recording fake outbound
/// client forced in, and assert it is actually fake: a test-configured app
/// must never construct a real network client (#5339 guard).
pub fn test_app_state(config: crate::config::Config) -> AppState {
    let state = AppState::with_outbound(
        config,
        std::sync::Arc::new(crate::outbound::RecordingFakeOutbound::new()),
    )
    .expect("test app state");
    assert!(
        state.outbound.is_fake(),
        "test app state must use the recording fake outbound client"
    );
    state
}

/// [`test_app_state`] with a caller-selected pool recycling method.
pub fn test_app_state_with_recycling(
    config: crate::config::Config,
    recycling_method: deadpool_postgres::RecyclingMethod,
) -> AppState {
    let state = AppState::with_recycling_and_outbound(
        config,
        recycling_method,
        std::sync::Arc::new(crate::outbound::RecordingFakeOutbound::new()),
    )
    .expect("test app state");
    assert!(
        state.outbound.is_fake(),
        "test app state must use the recording fake outbound client"
    );
    state
}

fn state_from_url(url: &str, pool_size: usize) -> AppState {
    let config = crate::config::Config::from_lookup(|name| match name {
        "RUST_ROLL_DATABASE_URL" => Some(url.to_string()),
        "RUST_ROLL_JWT_SECRET" => Some(TEST_JWT_SECRET.into()),
        "RUST_ROLL_POOL_SIZE" => Some(pool_size.to_string()),
        _ => None,
    })
    .expect("canonical test config");
    test_app_state(config)
}

static ADMIN_STATE: tokio::sync::OnceCell<std::sync::Arc<AppState>> =
    tokio::sync::OnceCell::const_new();
static SCHEMA_READY: tokio::sync::OnceCell<()> = tokio::sync::OnceCell::const_new();
static PROVISIONED: tokio::sync::OnceCell<()> = tokio::sync::OnceCell::const_new();

/// Connections the admin pool needs: one is enough because every admin
/// operation runs exactly once per process, guarded by [`SCHEMA_READY`] and
/// [`PROVISIONED`], rather than once per test.
const ADMIN_POOL_SIZE: usize = 1;

/// Admin pool, used only to load the fixture and provision the test role.
async fn admin_state() -> Option<std::sync::Arc<AppState>> {
    let url = admin_url()?;
    let state = ADMIN_STATE
        .get_or_init(|| async move { std::sync::Arc::new(state_from_url(&url, ADMIN_POOL_SIZE)) })
        .await;
    Some(state.clone())
}

/// Apply the Alembic fixture once per process, however many tests start at once.
async fn ensure_canonical_schema() {
    SCHEMA_READY
        .get_or_init(|| async {
            if let Some(admin) = admin_state().await {
                ensure_schema(&admin).await;
            }
        })
        .await;
}

/// Ensure the canonical schema exists and the DML-only role can use it.
async fn provision() {
    assert_safe_test_database(&required_test_admin_url());
    PROVISIONED
        .get_or_init(|| async {
            let Some(admin) = admin_state().await else {
                return;
            };
            ensure_canonical_schema().await;
            let connection = db::checkout(&admin).await.expect("admin connection");
            connection
                .batch_execute(&format!(
                    "DO $$ BEGIN \
                         IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{TEST_ROLE}') THEN \
                             CREATE ROLE {TEST_ROLE} LOGIN PASSWORD '{TEST_ROLE_PASSWORD}'; \
                         END IF; \
                     END $$; \
                     REVOKE CREATE ON SCHEMA public FROM PUBLIC; \
                     REVOKE CREATE ON SCHEMA public FROM {TEST_ROLE}; \
                     GRANT USAGE ON SCHEMA public TO {TEST_ROLE}; \
                     GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE \
                         ON ALL TABLES IN SCHEMA public TO {TEST_ROLE}; \
                     GRANT USAGE, SELECT, UPDATE \
                         ON ALL SEQUENCES IN SCHEMA public TO {TEST_ROLE}; \
                     ALTER DEFAULT PRIVILEGES IN SCHEMA public \
                         GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE \
                         ON TABLES TO {TEST_ROLE}; \
                     ALTER DEFAULT PRIVILEGES IN SCHEMA public \
                         GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {TEST_ROLE};"
                ))
                .await
                .expect("provision DML-only test role");
        })
        .await;
}

/// The DSN tests must use: the DML-only role, which cannot create schema.
pub async fn database_url() -> String {
    provision().await;
    restricted_url(&admin_url().expect("RUST_ROLL_TEST_DATABASE_URL is required"))
}

/// Reset the database to an empty canonical schema before one serialized test.
pub async fn reset(state: &AppState) {
    assert_safe_test_database(&required_test_admin_url());
    ensure_canonical_schema().await;
    truncate_application_tables(state).await;
}

/// Crate-wide lock serializing every test that touches the canonical schema.
///
/// The canonical Alembic schema lives in `public`, so tests cannot each get a
/// private namespace without issuing DDL — which is exactly what this module
/// exists to prevent. Tests therefore take this lock, reset, seed and assert
/// while holding it. Doing so keeps one shared, production-identical schema
/// instead of a per-test approximation.
pub(crate) static DB_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

/// Build the canonical test [`AppState`] and require a disposable database.
///
/// Existing Option-returning callers now panic with setup instructions when
/// RUST_ROLL_TEST_DATABASE_URL is missing instead of reporting a passing test.
pub async fn test_state(pool_size: usize) -> Option<std::sync::Arc<AppState>> {
    admin_url()?;
    let url = database_url().await;
    Some(std::sync::Arc::new(state_from_url(&url, pool_size)))
}

/// Lock and reset the canonical schema, returning the guard for the test body.
///
/// Hold the returned guard for the whole test; dropping it releases the next
/// test. This replaces the per-test `CREATE SCHEMA`/`CREATE TABLE` fixtures that
/// let production-only schema differences escape the suite (#4578).
pub async fn reset_for_test(state: &AppState) -> tokio::sync::MutexGuard<'static, ()> {
    let guard = DB_LOCK.lock().await;
    reset(state).await;
    guard
}

/// Test scaffolding: synthetic provider volume rosters.
///
/// The live ComicVine roster is an HTTP dependency, so a handler test that
/// needs a deterministic roster installs one here instead. `catalog_volume_roster`
/// returns the installed fixture for a matching external id before touching the
/// network. Entries are keyed by volume id, never globally toggled, so parallel
/// tests cannot leak a fixture into each other; tests must use unique volume
/// ids and clear the fixture when done. Nothing here runs unless a test calls
/// [`install_test_volume_roster`].
type TestVolumeRosterFixture = (serde_json::Value, Vec<serde_json::Value>);

static TEST_VOLUME_ROSTERS: std::sync::Mutex<
    Option<std::collections::HashMap<String, TestVolumeRosterFixture>>,
> = std::sync::Mutex::new(None);

/// Install a synthetic `(series_info, roster)` returned for `external_id`.
///
/// Overwrites any previous fixture for the same volume id.
pub fn install_test_volume_roster(
    external_id: &str,
    series: serde_json::Value,
    roster: Vec<serde_json::Value>,
) {
    let mut guard = TEST_VOLUME_ROSTERS
        .lock()
        .expect("test volume roster registry poisoned");
    guard
        .get_or_insert_with(std::collections::HashMap::new)
        .insert(external_id.to_owned(), (series, roster));
}

/// Remove the fixture for `external_id`, if any.
pub fn clear_test_volume_roster(external_id: &str) {
    let mut guard = TEST_VOLUME_ROSTERS
        .lock()
        .expect("test volume roster registry poisoned");
    if let Some(map) = guard.as_mut() {
        map.remove(external_id);
    }
}

/// Look up an installed fixture. `None` outside tests and when unset.
pub(crate) fn lookup_test_volume_roster(external_id: &str) -> Option<TestVolumeRosterFixture> {
    let guard = TEST_VOLUME_ROSTERS.lock().ok()?;
    guard.as_ref().and_then(|map| map.get(external_id).cloned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn guard_accepts_local_test_databases() {
        for url in [
            "postgresql://postgres:pw@127.0.0.1:5432/native_auth_test",
            "postgres://u:p@localhost/comic_pile_test",
            "postgresql://u:p@[::1]:5433/my_TEST_db",
            "postgresql://u@/native_test?host=/var/run/postgresql",
            "postgresql://u@%2Fvar%2Frun%2Fpostgresql/native_test",
        ] {
            assert_safe_test_database(url);
        }
    }

    #[test]
    fn guard_rejects_remote_hosts_and_non_test_names() {
        for url in [
            "postgresql://u:p@example.neon.tech/neondb",
            "postgresql://u:p@example.neon.tech/native_test",
            "postgresql://u:p@127.0.0.1:5432/neondb",
            "postgresql://u:p@localhost/postgres",
            "postgresql://u:p@localhost/native_test?host=example.neon.tech",
            "postgresql://u:p@localhost/neondb?dbname=prod",
            "postgresql://u:p@127.0.0.1.evil.example/native_test",
            "postgresql://u:p@localhost,example.neon.tech/native_test",
            "postgresql://u:p@evil.example/x@127.0.0.1/native_test",
            "postgresql:///native_test",
            "postgresql://u:p@localhost/native_test?%64bname=production",
            "postgresql://u:p@localhost/native_test?%68ost=example.neon.tech",
            "host=example.neon.tech dbname=native_test",
            "",
        ] {
            assert!(
                check_safe_test_database(url).is_err(),
                "guard must refuse {url:?}"
            );
        }
    }

    #[test]
    #[should_panic(expected = "REFUSING to run destructive test setup")]
    fn guard_panics_for_remote_url_before_any_connection() {
        assert_safe_test_database("postgresql://u:p@example.neon.tech/neondb");
    }

    #[test]
    fn local_host_check_allows_server_level_database() {
        assert!(check_local_host("postgresql://postgres:pw@127.0.0.1:5432/postgres").is_ok());
        assert!(check_local_host("postgresql://u:p@example.neon.tech/postgres").is_err());
    }

    #[test]
    fn required_db_config_accepts_a_disposable_url() {
        assert_eq!(
            require_test_db_config(
                Some("postgresql://localhost/native_auth_test".into()),
                false
            ),
            "postgresql://localhost/native_auth_test"
        );
    }

    #[test]
    #[should_panic(expected = "RUST_ROLL_TEST_DATABASE_URL is required")]
    fn required_db_config_rejects_missing_database() {
        require_test_db_config(None, false);
    }

    #[test]
    #[should_panic(expected = "RUST_ROLL_ALLOW_DB_SKIP is forbidden")]
    fn required_db_config_rejects_any_skip_override() {
        require_test_db_config(Some("postgresql://localhost/native_auth_test".into()), true);
    }

    #[test]
    fn canonical_schema_fixture_is_available_in_test_checkout() {
        assert!(
            canonical_schema().contains("CREATE TABLE"),
            "the Alembic schema fixture must contain DDL"
        );
    }

    /// The point of the DML-only role: PostgreSQL itself refuses persistent
    /// schema changes, so no linter has to guess at spellings.
    #[tokio::test]
    async fn the_test_role_cannot_create_persistent_schema() {
        let Some(state) = test_state(1).await else {
            return;
        };
        let _db = reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("test connection");

        let error = connection
            .batch_execute("CREATE TABLE schema_guard_probe (id integer)")
            .await
            .expect_err("the DML-only role must not create persistent tables");
        assert_eq!(
            error.code(),
            Some(&tokio_postgres::error::SqlState::INSUFFICIENT_PRIVILEGE),
            "expected a privilege error, got {error:?}"
        );

        let error = connection
            .batch_execute("DROP TABLE threads")
            .await
            .expect_err("the DML-only role must not drop canonical tables");
        assert_eq!(
            error.code(),
            Some(&tokio_postgres::error::SqlState::INSUFFICIENT_PRIVILEGE),
            "expected a privilege error, got {error:?}"
        );

        // Session-local fixtures stay usable: `CREATE TEMP` needs TEMP on the
        // database, not CREATE on the schema.
        connection
            .batch_execute("CREATE TEMP TABLE schema_guard_temp (id integer)")
            .await
            .expect("temporary tables remain available to tests");
    }

    #[test]
    fn restricted_url_replaces_credentials_and_keeps_the_database() {
        assert_eq!(
            restricted_url("postgresql://postgres:secret@db.example:5432/native_test"),
            format!("postgresql://{TEST_ROLE}:{TEST_ROLE_PASSWORD}@db.example:5432/native_test")
        );
        assert_eq!(
            restricted_url("postgresql://db.example/native_test"),
            format!("postgresql://{TEST_ROLE}:{TEST_ROLE_PASSWORD}@db.example/native_test")
        );
    }

    #[test]
    fn restricted_url_drops_query_credentials_that_would_override_the_role() {
        let url = restricted_url(
            "postgresql://postgres:secret@db/native_test?user=postgres&password=secret&sslmode=disable",
        );
        assert_eq!(
            url,
            format!("postgresql://{TEST_ROLE}:{TEST_ROLE_PASSWORD}@db/native_test?sslmode=disable")
        );
    }

    #[test]
    fn restricted_url_drops_percent_encoded_query_credentials() {
        let url = restricted_url(
            "postgresql://postgres:secret@db/native_test?%75ser=postgres&%70assword=secret&sslmode=disable",
        );
        assert_eq!(
            url,
            format!("postgresql://{TEST_ROLE}:{TEST_ROLE_PASSWORD}@db/native_test?sslmode=disable")
        );
    }

    #[test]
    #[should_panic(expected = "must be a postgresql:// URI")]
    fn restricted_url_fails_closed_on_keyword_dsns() {
        restricted_url("host=db user=postgres password=secret dbname=native_test");
    }
}
