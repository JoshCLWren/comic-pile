#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Pooled-socket recovery regressions (#4732).
//!
//! A pooled PostgreSQL socket can be half-open after an idle freeze or platform
//! pause: `is_closed` is false and the driver only learns otherwise when the
//! first statement hangs or the peer resets. `db::checkout` now proves the
//! socket with a bounded read-only probe before any handler statement, so the
//! retry never replays handler SQL, a write, or an audit event.
//!
//! The clean `pg_terminate_backend` fixture is not enough on its own: PostgreSQL
//! closes the socket early, so deadpool discards it before the handler runs and
//! the recovery branch is never exercised (#4578). The fault proxy below drops
//! the next client write on an established, apparently healthy connection. The
//! same armed proxy is then used with recovery disabled to prove the failure it
//! prevents.
//!
//! Every database assertion uses the disposable canonical Alembic schema from
//! `test_support`, never a hand-written approximation, and never production.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, db, router, test_support, threads, AppState};
use serde_json::{json, Value};
use std::{
    net::SocketAddr,
    sync::{
        atomic::{AtomicU16, AtomicUsize, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
};
use tower::ServiceExt;

const PASSWORD: &str = "correct-horse-battery";

/// The bound the probe overhead must stay under on a disposable local database.
///
/// A `SELECT 1` round trip is sub-millisecond locally; the margin only has to
/// catch an accidental per-checkout reconnect or an unbounded retry loop.
const MAX_PROBE_OVERHEAD: Duration = Duration::from_millis(25);

fn state(url: &str, pool_size: usize, connection_recovery: bool) -> Arc<AppState> {
    state_with_timeout(url, pool_size, connection_recovery, 5000)
}

fn state_with_timeout(
    url: &str,
    pool_size: usize,
    connection_recovery: bool,
    request_timeout_ms: u64,
) -> Arc<AppState> {
    let config = Config::from_lookup(|key| match key {
        "RUST_ROLL_DATABASE_URL" => Some(url.into()),
        "RUST_ROLL_JWT_SECRET" => Some(test_support::TEST_JWT_SECRET.into()),
        "RUST_ROLL_POOL_SIZE" => Some(pool_size.to_string()),
        "RUST_ROLL_REQUEST_TIMEOUT_MS" => Some(request_timeout_ms.to_string()),
        _ => None,
    })
    .expect("pool recovery test config");
    let mut state = AppState::new(config).expect("pool recovery test state");
    state.connection_recovery = connection_recovery;
    Arc::new(state)
}

/// A disposable schema, an authenticated reader, and a fault proxy in front of
/// the reader's single pool slot.
struct Fixture {
    direct: Arc<AppState>,
    proxied: Arc<AppState>,
    proxy: FaultProxy,
    token: String,
    csrf: String,
    user_id: i32,
    _db: tokio::sync::MutexGuard<'static, ()>,
}

async fn fixture(connection_recovery: bool) -> Fixture {
    let url = test_support::database_url().await;
    let direct = state(&url, 2, true);
    let _db = test_support::reset_for_test(&direct).await;
    let (token, csrf, user_id) = register(&direct, "pool-reader").await;
    seed_threads(&direct, user_id).await;
    let proxy = FaultProxy::start(authority(&url)).await;
    let proxied = state(
        &redirect(&url, &proxy.address.to_string()),
        1,
        connection_recovery,
    );
    Fixture {
        direct,
        proxied,
        proxy,
        token,
        csrf,
        user_id,
        _db,
    }
}

/// Register through the real mounted router and return the bearer token, the
/// double-submit CSRF token and the database identity.
async fn register(state: &Arc<AppState>, username: &str) -> (String, String, i32) {
    static NEXT_IP: AtomicU16 = AtomicU16::new(1);
    let ip = NEXT_IP.fetch_add(1, Ordering::Relaxed);
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v2/auth/register")
                .header(header::CONTENT_TYPE, "application/json")
                .header("x-forwarded-for", format!("198.51.100.{ip}"))
                .body(Body::from(
                    json!({
                        "username": username,
                        "email": format!("{username}@example.com"),
                        "password": PASSWORD
                    })
                    .to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let csrf = response
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .filter_map(|value| value.to_str().ok())
        .find_map(|cookie| cookie.strip_prefix("csrf_token="))
        .and_then(|rest| rest.split(';').next())
        .expect("register sets a CSRF cookie")
        .to_string();
    let body = to_bytes(response.into_body(), 65536).await.unwrap();
    let value: Value = serde_json::from_slice(&body).unwrap();
    let token = value["access_token"]
        .as_str()
        .expect("register returns an access token")
        .to_string();
    (token, csrf, user_id(state, username).await)
}

async fn user_id(state: &Arc<AppState>, username: &str) -> i32 {
    let connection = db::checkout(state).await.expect("identity connection");
    connection
        .query_one("SELECT id FROM users WHERE username = $1", &[&username])
        .await
        .expect("registered identity")
        .get(0)
}

async fn seed_threads(state: &Arc<AppState>, owner: i32) {
    let connection = db::checkout(state).await.expect("seed connection");
    for id in 1..=3 {
        connection
            .execute(
                "INSERT INTO threads (id, user_id, title, format, issues_remaining, status, \
                 queue_position, is_blocked) \
                 VALUES ($1, $2, $3, 'Comic', 1, 'active', $1, false)",
                &[&id, &owner, &format!("Thread {id}")],
            )
            .await
            .expect("seed thread");
    }
    drop(connection);
}

async fn positions(state: &Arc<AppState>, owner: i32) -> Vec<(i32, i32)> {
    let connection = db::checkout(state).await.expect("positions connection");
    let rows = connection
        .query(
            "SELECT id, queue_position FROM threads WHERE user_id = $1 \
             AND status = 'active' AND queue_position >= 1 ORDER BY queue_position, id",
            &[&owner],
        )
        .await
        .expect("read positions");
    drop(connection);
    rows.iter().map(|row| (row.get(0), row.get(1))).collect()
}

async fn reorder_events(state: &Arc<AppState>) -> i64 {
    let connection = db::checkout(state).await.expect("event connection");
    let row = connection
        .query_one("SELECT count(*) FROM events WHERE type = 'reorder'", &[])
        .await
        .expect("count reorder events");
    drop(connection);
    row.get(0)
}

async fn send(
    state: &Arc<AppState>,
    auth: (&str, &str),
    method: &str,
    path: &str,
    body: Option<Value>,
) -> (StatusCode, Value) {
    let (token, csrf) = auth;
    let mut builder = Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"));
    if body.is_some() {
        builder = builder.header(header::CONTENT_TYPE, "application/json");
    }
    let response = router(state.clone())
        .oneshot(
            builder
                .body(body.map_or_else(Body::empty, |value| Body::from(value.to_string())))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 1 << 20).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

async fn get_threads(fixture: &Fixture) -> (StatusCode, Value) {
    send(
        &fixture.proxied,
        (&fixture.token, &fixture.csrf),
        "GET",
        "/api/v2/threads",
        None,
    )
    .await
}

async fn get_me(fixture: &Fixture) -> (StatusCode, Value) {
    send(
        &fixture.proxied,
        (&fixture.token, &fixture.csrf),
        "GET",
        "/api/v2/auth/me",
        None,
    )
    .await
}

async fn patch_position(fixture: &Fixture, thread_id: i32, position: i32) -> (StatusCode, Value) {
    send(
        &fixture.proxied,
        (&fixture.token, &fixture.csrf),
        "PATCH",
        &format!("/api/v2/queue-entries/{thread_id}"),
        Some(json!({"position": position})),
    )
    .await
}

async fn median_checkout(state: &Arc<AppState>, samples: usize) -> Duration {
    let mut elapsed = Vec::with_capacity(samples);
    for _ in 0..samples {
        let started = Instant::now();
        let connection = db::checkout(state).await.expect("checkout");
        elapsed.push(started.elapsed());
        drop(connection);
    }
    elapsed.sort_unstable();
    elapsed[samples / 2]
}

/// A byte-transparent TCP proxy that can sever the next client statement.
///
/// It forwards startup, TLS negotiation and authentication untouched. Once
/// armed, the next client-to-server write is dropped and both sockets close, so
/// the driver sees a transport failure on exactly that statement while the
/// connection still looked healthy at checkout.
struct FaultProxy {
    address: SocketAddr,
    drops: Arc<AtomicUsize>,
    hangs: Arc<AtomicUsize>,
}

impl FaultProxy {
    async fn start(upstream: String) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind fault proxy");
        let address = listener.local_addr().expect("fault proxy address");
        let drops = Arc::new(AtomicUsize::new(0));
        let hangs = Arc::new(AtomicUsize::new(0));
        let drop_counter = drops.clone();
        let hang_counter = hangs.clone();
        tokio::spawn(async move {
            while let Ok((client, _)) = listener.accept().await {
                let upstream = upstream.clone();
                let drop_counter = drop_counter.clone();
                let hang_counter = hang_counter.clone();
                tokio::spawn(async move {
                    forward(client, &upstream, drop_counter, hang_counter).await
                });
            }
        });
        Self {
            address,
            drops,
            hangs,
        }
    }

    /// Sever the next client statement on an already-established connection.
    fn sever_next_statement(&self) {
        self.drops.store(1, Ordering::SeqCst);
    }

    /// Swallow the next client statement without answering or closing, exactly
    /// like a half-open socket that has not noticed its peer is gone.
    fn hang_next_statement(&self) {
        self.hangs.store(1, Ordering::SeqCst);
    }
}

async fn forward(
    client: TcpStream,
    upstream: &str,
    drops: Arc<AtomicUsize>,
    hangs: Arc<AtomicUsize>,
) {
    let Ok(server) = TcpStream::connect(upstream).await else {
        return;
    };
    let (mut client_read, mut client_write) = client.into_split();
    let (mut server_read, mut server_write) = server.into_split();
    let client_to_server = async {
        let mut buffer = [0u8; 16 * 1024];
        loop {
            let read = match client_read.read(&mut buffer).await {
                Ok(0) | Err(_) => return,
                Ok(read) => read,
            };
            if hangs.load(Ordering::SeqCst) > 0 {
                hangs.fetch_sub(1, Ordering::SeqCst);
                // Hold the socket open and never answer: the statement hangs.
                std::future::pending::<()>().await;
            }
            if drops.load(Ordering::SeqCst) > 0 {
                drops.fetch_sub(1, Ordering::SeqCst);
                // Drop this statement without forwarding it and close both
                // sockets: the driver fails the statement, not the checkout.
                return;
            }
            if server_write.write_all(&buffer[..read]).await.is_err() {
                return;
            }
        }
    };
    let server_to_client = async {
        let mut buffer = [0u8; 16 * 1024];
        loop {
            let read = match server_read.read(&mut buffer).await {
                Ok(0) | Err(_) => return,
                Ok(read) => read,
            };
            if client_write.write_all(&buffer[..read]).await.is_err() {
                return;
            }
        }
    };
    tokio::select! {
        _ = client_to_server => {}
        _ = server_to_client => {}
    }
}

/// Split a URI DSN into its authority and a copy pointing at another host.
fn authority(dsn: &str) -> String {
    let (_, rest) = dsn.split_once("://").expect("URI DSN");
    let tail = rest.rsplit_once('@').map_or(rest, |(_, tail)| tail);
    let slash = tail.find('/').unwrap_or(tail.len());
    let host = &tail[..slash];
    if host.contains(':') {
        host.to_string()
    } else {
        format!("{host}:5432")
    }
}

fn redirect(dsn: &str, host: &str) -> String {
    let (scheme, rest) = dsn.split_once("://").expect("URI DSN");
    let (userinfo, tail) = match rest.rsplit_once('@') {
        Some((userinfo, tail)) => (Some(userinfo), tail),
        None => (None, rest),
    };
    let slash = tail.find('/').unwrap_or(tail.len());
    let path = &tail[slash..];
    match userinfo {
        Some(userinfo) => format!("{scheme}://{userinfo}@{host}{path}"),
        None => format!("{scheme}://{host}{path}"),
    }
}

#[test]
fn redirect_preserves_credentials_database_and_options() {
    assert_eq!(
        authority("postgresql://reader:secret@db.example:5444/app?sslmode=disable"),
        "db.example:5444"
    );
    assert_eq!(
        redirect(
            "postgresql://reader:secret@db.example:5444/app?sslmode=disable",
            "127.0.0.1:1234"
        ),
        "postgresql://reader:secret@127.0.0.1:1234/app?sslmode=disable"
    );
}

/// An authenticated read recovers when a pooled socket fails its first
/// statement. The page statement, which also folds authentication, is issued
/// exactly once: only the read-only probe is retried.
#[tokio::test]
async fn authenticated_read_recovers_when_a_pooled_socket_fails_its_first_statement() {
    let fixture = fixture(true).await;
    let (status, body) = get_threads(&fixture).await;
    assert_eq!(status, StatusCode::OK, "{body}");

    let issued = threads::PAGE_STATEMENTS_ISSUED.load(Ordering::Relaxed);
    fixture.proxy.sever_next_statement();
    let (status, body) = get_threads(&fixture).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(
        threads::PAGE_STATEMENTS_ISSUED.load(Ordering::Relaxed) - issued,
        1,
        "recovery must retry only the probe, never replay the handler statement"
    );
}

/// An authenticated write recovers without a 500 and commits exactly once.
#[tokio::test]
async fn authenticated_write_recovers_and_commits_exactly_once() {
    let fixture = fixture(true).await;
    let (status, body) = get_threads(&fixture).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(
        positions(&fixture.direct, fixture.user_id).await,
        vec![(1, 1), (2, 2), (3, 3)]
    );

    fixture.proxy.sever_next_statement();
    let (status, body) = patch_position(&fixture, 1, 3).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(
        positions(&fixture.direct, fixture.user_id).await,
        vec![(2, 1), (3, 2), (1, 3)]
    );
    assert_eq!(
        reorder_events(&fixture.direct).await,
        1,
        "the recovered write records exactly one reorder event"
    );
}

/// The same armed proxy proves the regression: with recovery disabled the first
/// statement fails and the reader gets the existing transient database envelope,
/// not a 500.
#[tokio::test]
async fn recovery_disabled_surfaces_the_transient_unavailable_envelope() {
    let fixture = fixture(false).await;
    let (status, body) = get_threads(&fixture).await;
    assert_eq!(status, StatusCode::OK, "{body}");

    fixture.proxy.sever_next_statement();
    let (status, body) = get_threads(&fixture).await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE, "{body}");
    assert_eq!(body["error"]["code"], "database_unavailable", "{body}");
    assert_eq!(body["error"]["status"], "SERVICE_UNAVAILABLE", "{body}");
}

/// Authentication state is a credential question; a dead socket is availability.
/// The reader must be told to retry, not signed out.
#[tokio::test]
async fn authentication_reports_unavailability_not_a_false_logout() {
    let fixture = fixture(false).await;
    let (status, body) = get_me(&fixture).await;
    assert_eq!(status, StatusCode::OK, "{body}");

    fixture.proxy.sever_next_statement();
    let (status, body) = get_me(&fixture).await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE, "{body}");
    assert_ne!(status, StatusCode::UNAUTHORIZED, "{body}");
    assert_eq!(body["error"]["code"], "database_unavailable", "{body}");
}

/// A cleanly terminated pooled backend immediately before an authenticated read
/// must not surface a 500.
#[tokio::test]
async fn terminated_pooled_backend_recovers_for_authenticated_read() {
    let fixture = fixture(true).await;
    let pid = pooled_backend_pid(&fixture).await;
    terminate_pooled_backend(&fixture, pid).await;

    // No successful request ran before the termination: the read itself meets
    // the dead pooled socket and must still succeed.
    let (status, body) = get_threads(&fixture).await;
    assert_eq!(status, StatusCode::OK, "{body}");
}

/// The same termination immediately before a write, with no warm read.
#[tokio::test]
async fn terminated_pooled_backend_recovers_for_authenticated_write() {
    let fixture = fixture(true).await;
    let pid = pooled_backend_pid(&fixture).await;
    terminate_pooled_backend(&fixture, pid).await;

    let (status, body) = patch_position(&fixture, 1, 3).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(
        positions(&fixture.direct, fixture.user_id).await,
        vec![(2, 1), (3, 2), (1, 3)]
    );
    assert_eq!(
        reorder_events(&fixture.direct).await,
        1,
        "the write that met the terminated backend commits exactly once"
    );
}

/// Warm the single proxied pool slot and return its backend identity.
async fn pooled_backend_pid(fixture: &Fixture) -> i32 {
    let connection = db::checkout(&fixture.proxied)
        .await
        .expect("backend pid connection");
    let pid: i32 = connection
        .query_one("SELECT pg_backend_pid()", &[])
        .await
        .expect("pooled backend pid")
        .get(0);
    drop(connection);
    pid
}

async fn terminate_pooled_backend(fixture: &Fixture, pid: i32) {
    let killer = db::checkout(&fixture.direct)
        .await
        .expect("termination connection");
    let terminated: bool = killer
        .query_one("SELECT pg_terminate_backend($1)", &[&pid])
        .await
        .expect("terminate the pooled backend")
        .get(0);
    drop(killer);
    assert!(terminated, "the pooled backend must be terminated");
}

/// A probe that never answers (half-open socket) must be bounded and discard
/// the physical connection instead of returning a possibly busy client to the
/// pool or wedging the next request.
#[tokio::test]
async fn a_hung_probe_is_bounded_and_discards_the_physical_connection() {
    let url = test_support::database_url().await;
    let direct = state(&url, 2, true);
    let _db = test_support::reset_for_test(&direct).await;
    let proxy = FaultProxy::start(authority(&url)).await;
    let proxied = state_with_timeout(&redirect(&url, &proxy.address.to_string()), 1, true, 1000);
    // Establish the single pooled connection through the proxy.
    let connection = db::checkout(&proxied).await.expect("warm connection");
    drop(connection);

    proxy.hang_next_statement();
    let started = Instant::now();
    let error = db::checkout(&proxied).await.expect_err("probe must fail");
    assert_eq!(error.status(), StatusCode::SERVICE_UNAVAILABLE);
    assert!(
        started.elapsed() < Duration::from_secs(3),
        "the probe deadline must bound a half-open socket: {:?}",
        started.elapsed()
    );
    assert_eq!(
        proxied.pool.status().size,
        0,
        "a hung probe must discard the physical connection"
    );

    // The discarded slot must not wedge the pool: a later checkout creates a
    // fresh connection through the proxy.
    let connection = db::checkout(&proxied)
        .await
        .expect("checkout after a discarded hung connection");
    drop(connection);
}

/// Measure the probe cost against the raw checkout it protects.
#[tokio::test]
async fn checkout_probe_overhead_is_measured_and_bounded() {
    let url = test_support::database_url().await;
    let direct = state(&url, 2, true);
    let _db = test_support::reset_for_test(&direct).await;
    let recovered = state(&url, 2, true);
    let raw = state(&url, 2, false);
    // Warm both pools so the comparison measures the probe, not connection setup.
    drop(db::checkout(&recovered).await.expect("warm recovered"));
    drop(db::checkout(&raw).await.expect("warm raw"));

    let samples = 40;
    let recovered_median = median_checkout(&recovered, samples).await;
    let raw_median = median_checkout(&raw, samples).await;
    println!(
        "checkout median: probe {recovered_median:?}, raw {raw_median:?} over {samples} samples"
    );
    assert!(
        recovered_median < raw_median + MAX_PROBE_OVERHEAD,
        "probe overhead must stay bounded: {recovered_median:?} vs raw {raw_median:?}"
    );
    assert!(
        recovered_median < Duration::from_millis(50),
        "a local probe must not become a reconnect: {recovered_median:?}"
    );
}
