//! Vercel's native Rust ingress for the Roll endpoint cutover.
//! The health probe never reads database configuration.
use axum::{
    extract::Request,
    http::{Extensions, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{delete, get, patch, post, put},
    Json, Router,
};
use comicpile_roll_service::{
    auth::BackgroundTasks, config::Config, router as roll_router, AppState,
};
use std::{
    future::Future,
    pin::Pin,
    sync::{Arc, OnceLock},
    task::{Context, Poll},
};
use tower::Service;
use vercel_runtime::{axum::StreamingUtils, AppState as VercelState, Error, ResponseBody};

async fn native_health() -> Response {
    let mut response = Json(serde_json::json!({
        "status": "ok",
        "runtime": "rust",
        "service": "roll",
        "build": {
            "revision": env!("COMICPILE_SOURCE_REVISION"),
            "compiler": env!("COMICPILE_COMPILER"),
            "package": env!("CARGO_PKG_NAME"),
            "version": env!("CARGO_PKG_VERSION")
        },
        "process": {
            "executable": std::env::current_exe().ok()
                .and_then(|path| path.file_name().map(|name| name.to_string_lossy().into_owned())),
            "os": std::env::consts::OS,
            "arch": std::env::consts::ARCH
        }
    }))
    .into_response();
    response
        .headers_mut()
        .insert("x-comicpile-api-runtime", HeaderValue::from_static("rust"));
    response
}

static ROLL_STATE: OnceLock<Result<Arc<AppState>, &'static str>> = OnceLock::new();

#[cfg(test)]
tokio::task_local! {
    static TEST_ROLL_STATE: Arc<AppState>;
}

/// JSON subscriber for Vercel logs. `try_init` keeps isolate reuse and tests
/// from failing when startup runs more than once.
fn init_tracing() {
    let directive = std::env::var("RUST_ROLL_LOG").unwrap_or_else(|_| "info".into());
    let filter = tracing_subscriber::EnvFilter::try_new(directive)
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"));
    let _ = tracing_subscriber::fmt()
        .json()
        .with_env_filter(filter)
        .try_init();
}

/// Drop outer-router `UrlParams` before the inner service router matches the
/// same `{thread_id}` pattern. axum 0.8 extends nested path params, so leaving
/// the ingress params in place makes `Path<i32>` see two arguments and return
/// its built-in 500. Keep only `BackgroundTasks`, which the Vercel service
/// inserts for post-response auth work; every other inner extractor reads
/// router state, headers, or the inner match.
fn prepare_inner_request(request: Request) -> Request {
    let (mut parts, body) = request.into_parts();
    let background = parts.extensions.remove::<BackgroundTasks>();
    parts.extensions = Extensions::new();
    if let Some(background) = background {
        parts.extensions.insert(background);
    }
    Request::from_parts(parts, body)
}

fn resolve_roll_state() -> Result<Arc<AppState>, &'static str> {
    #[cfg(test)]
    if let Ok(state) = TEST_ROLL_STATE.try_with(Clone::clone) {
        return Ok(state);
    }
    ROLL_STATE
        .get_or_init(|| {
            Config::from_vercel_env()
                .and_then(AppState::new)
                .map(Arc::new)
                .map_err(|err| {
                    // ConfigError is a static, credential-free message.
                    eprintln!("native_roll initialisation failed: {err}");
                    err.0
                })
        })
        .clone()
}

async fn native_dispatch(request: Request) -> Response {
    init_tracing();
    // Log only the fixed ingress path, status and elapsed time. Never log query,
    // authorization headers, response JSON or other user data.
    let ingress_path = request.uri().path().to_owned();
    let started = std::time::Instant::now();
    // Cold-start the native Roll pool only for authenticated traffic.
    // Keep health independent of DB secrets and failures.
    let request = prepare_inner_request(request);
    let mut result = match resolve_roll_state() {
        Ok(state) => {
            let mut router = roll_router(state);
            match router.call(request).await {
                Ok(response) => response,
                Err(never) => match never {},
            }
        }
        Err(_) => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({"detail": "Native Roll unavailable"})),
        )
            .into_response(),
    };
    result
        .headers_mut()
        .insert("x-comicpile-api-runtime", HeaderValue::from_static("rust"));
    eprintln!(
        "native_roll route={} runtime=rust status={} elapsed_ms={}",
        ingress_path,
        result.status().as_u16(),
        started.elapsed().as_millis()
    );
    result
}

/// Vercel's stock layer drops the per-invocation runtime state, which owns the
/// `wait_until` tracker. Background auth work (password-recovery email) is only
/// guaranteed to finish when it is registered there, so this service forwards
/// that state into every request as a [`BackgroundTasks`] extension before
/// dispatching to the router.
#[derive(Clone)]
struct NativeVercelService {
    router: Router,
}

impl<B> Service<(VercelState, axum::http::Request<B>)> for NativeVercelService
where
    B: http_body::Body<Data = axum::body::Bytes> + Send + 'static,
    B::Error: Into<Error>,
{
    type Response = vercel_runtime::Response<ResponseBody>;
    type Error = Error;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, (state, request): (VercelState, axum::http::Request<B>)) -> Self::Future {
        let mut router = self.router.clone();
        Box::pin(async move {
            let (parts, body) = request.into_parts();
            let mut request = axum::http::Request::from_parts(parts, axum::body::Body::new(body));
            request
                .extensions_mut()
                .insert(BackgroundTasks::new(move |future| {
                    state.wait_until(future);
                }));
            let response = match router.call(request).await {
                Ok(response) => response,
                Err(never) => match never {},
            };
            StreamingUtils::process_response(response).await
        })
    }
}

/// Unknown API paths must terminate in Rust without initializing Python or Neon.
async fn native_not_found() -> Response {
    let mut response = (
        StatusCode::NOT_FOUND,
        Json(serde_json::json!({"detail": "Not Found"})),
    )
        .into_response();
    response
        .headers_mut()
        .insert("x-comicpile-api-runtime", HeaderValue::from_static("rust"));
    response
}

fn app() -> Router {
    Router::new()
        .route("/api/v2/health", get(native_health))
        .route("/api/v1/identity-inbox", get(native_dispatch))
        .route("/api/v1/identity-inbox/search/issues", get(native_dispatch))
        .route("/api/v1/identity-inbox/{mapping_id}", get(native_dispatch))
        .route(
            "/api/v1/identity-inbox/{mapping_id}/confirm",
            post(native_dispatch),
        )
        .route(
            "/api/v1/identity-inbox/{mapping_id}/defer",
            post(native_dispatch),
        )
        .route(
            "/api/v1/identity-inbox/{mapping_id}/reject",
            post(native_dispatch),
        )
        .route(
            "/api/v1/identity-inbox/{mapping_id}/skip",
            post(native_dispatch),
        )
        .route(
            "/api/v2/maintenance/comicvine-metadata-repairs",
            get(native_dispatch),
        )
        .route("/api/v2/roll/bootstrap", get(native_dispatch))
        .route("/api/v2/reading-sessions", post(native_dispatch))
        .route("/api/sessions/{session_id}", get(native_dispatch))
        .route("/api/v1/sessions/{session_id}", get(native_dispatch))
        .route("/api/v2/roll/dice-command", post(native_dispatch))
        .route("/api/v2/roll/offer", post(native_dispatch))
        .route("/api/v2/roll/reset", post(native_dispatch))
        .route("/api/v2/roll/die-state", get(native_dispatch))
        .route("/api/v2/roll/eligible-issue-ids", get(native_dispatch))
        .route("/api/v2/reading-boundaries", post(native_dispatch))
        .route("/api/v2/queue-entries/{thread_id}", get(native_dispatch))
        .route("/api/v2/queue-entries/{thread_id}", patch(native_dispatch))
        .route("/api/v2/queue-orders", post(native_dispatch))
        .route("/api/v2/threads", get(native_dispatch))
        .route("/api/v1/threads/{thread_id}", get(native_dispatch))
        .route("/api/threads/{thread_id}", get(native_dispatch))
        .route("/api/v2/reading-graph", get(native_dispatch))
        .route("/api/v2/reading-graph/repairs", post(native_dispatch))
        .route("/api/v2/dependencies/", post(native_dispatch))
        .route(
            "/api/v2/dependencies/{dependency_id}",
            delete(native_dispatch),
        )
        .route("/api/v2/threads/{thread_id}/issues", post(native_dispatch))
        .route(
            "/api/v2/threads/{thread_id}/issue-order",
            put(native_dispatch),
        )
        .route("/api/v2/issues/{issue_id}", delete(native_dispatch))
        .route(
            "/api/v2/continuity-plans/{plan_id}/reader",
            get(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/{plan_id}/recovery",
            get(native_dispatch),
        )
        .route(
            "/api/v2/continuity-plans/{plan_id}/recovery",
            post(native_dispatch),
        )
        .route("/api/v2/reading-lists", get(native_dispatch))
        .route("/api/v2/reading-lists", post(native_dispatch))
        .route("/api/v2/reading-lists/{list_id}", get(native_dispatch))
        .route("/api/v2/reading-lists/{list_id}", delete(native_dispatch))
        .route("/api/v2/reading-lists/{list_id}", put(native_dispatch))
        .route(
            "/api/v2/reading-lists/{list_id}/reader",
            get(native_dispatch),
        )
        .route("/api/v2/analytics/metrics", get(native_dispatch))
        .route("/api/v2/issues/{issue_id}/comicvine", get(native_dispatch))
        .route("/api/v1/issues/{issue_id}", get(native_dispatch))
        .route("/api/v1/issues/{issue_id}/comicvine", get(native_dispatch))
        .route(
            "/api/v1/comicvine/series/{comicvine_volume_id}/import-status",
            get(native_dispatch),
        )
        .route(
            "/api/v1/issues/{issue_id}/dependencies",
            get(native_dispatch),
        )
        .route("/api/v1/continuity-rules/", get(native_dispatch))
        .route("/api/v1/continuity-rules/", post(native_dispatch))
        .route("/api/v1/continuity-rules/{rule_id}", get(native_dispatch))
        .route("/api/v1/continuity-rules/{rule_id}", put(native_dispatch))
        .route(
            "/api/v1/continuity-rules/{rule_id}",
            delete(native_dispatch),
        )
        .route("/api/v1/releases/", get(native_dispatch))
        .route("/api/v1/releases/", put(native_dispatch))
        .route("/api/v1/releases/source", get(native_dispatch))
        .route("/api/v1/releases/{release_id}", get(native_dispatch))
        .route(
            "/api/v1/releases/{release_id}/retract",
            post(native_dispatch),
        )
        .route(
            "/api/v1/threads/{thread_id}/issue-dependencies",
            get(native_dispatch),
        )
        .route("/api/v1/roll/dismiss-pending", post(native_dispatch))
        .route("/api/roll/dismiss-pending", post(native_dispatch))
        .route("/api/v2/auth/register", post(native_dispatch))
        .route("/api/v2/auth/login", post(native_dispatch))
        .route("/api/v2/auth/refresh", post(native_dispatch))
        .route("/api/v2/auth/logout", post(native_dispatch))
        .route("/api/v2/auth/csrf", get(native_dispatch))
        .route("/api/v2/auth/me", get(native_dispatch))
        .route("/api/v2/auth/forgot-password", post(native_dispatch))
        .route("/api/v2/auth/reset-password", post(native_dispatch))
        .route("/api/v1/auth/me", get(native_dispatch))
        .route("/api/auth/me", get(native_dispatch))
        .route("/api/v1/auth/login", post(native_dispatch))
        .route("/api/v1/auth/register", post(native_dispatch))
        .route("/api/v1/auth/refresh", post(native_dispatch))
        .route("/api/v1/auth/logout", post(native_dispatch))
        .route("/api/v1/auth/csrf", get(native_dispatch))
        .route("/api/v1/auth/forgot-password", post(native_dispatch))
        .route("/api/v1/auth/reset-password", post(native_dispatch))
        .route("/api/auth/login", post(native_dispatch))
        .route("/api/auth/register", post(native_dispatch))
        .route("/api/auth/refresh", post(native_dispatch))
        .route("/api/auth/logout", post(native_dispatch))
        .route("/api/auth/csrf", get(native_dispatch))
        .route("/api/auth/forgot-password", post(native_dispatch))
        .route("/api/auth/reset-password", post(native_dispatch))
        .route("/api/v1/creators", get(native_dispatch))
        .route("/api/v1/creators/", get(native_dispatch))
        .route("/api/v1/creators/summaries", get(native_dispatch))
        .route(
            "/api/v1/taste/discoveries/{signal_id}/dismiss",
            post(native_dispatch),
        )
        .route("/api/bug-reports/", post(native_dispatch))
        .route("/api/v1/bug-reports/", post(native_dispatch))
        .fallback(native_not_found)
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    init_tracing();
    vercel_runtime::run(NativeVercelService { router: app() }).await
}

#[cfg(test)]
mod tests {
    use super::{app, NativeVercelService, TEST_ROLL_STATE};
    use axum::{
        body::{to_bytes, Body},
        http::{header, Request, StatusCode},
        routing::get,
        Router,
    };
    use comicpile_roll_service::{auth::BackgroundTasks, config::Config, AppState};
    use serde_json::Value;
    use std::sync::Arc;
    use tower::Service;
    use vercel_runtime::{AppState as VercelState, LogContext};

    const JWT_SECRET: &str = "synthetic-ingress-queue-secret";

    #[tokio::test]
    async fn v1_issue_read_ingress_preserves_same_path_and_requires_auth() {
        for uri in [
            "/api/v1/issues/7",
            "/api/v1/issues/7/comicvine",
            "/api/v1/issues/7/dependencies",
        ] {
            let mut router = app();
            let response = router
                .call(
                    Request::builder()
                        .method("GET")
                        .uri(uri)
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .expect("router response");
            assert!(
                response.status() == StatusCode::UNAUTHORIZED
                    || response.status() == StatusCode::SERVICE_UNAVAILABLE,
                "{uri} must require auth and reach Rust, got {}",
                response.status()
            );
            assert_eq!(
                response.headers().get("x-comicpile-api-runtime").unwrap(),
                "rust"
            );
            let bytes = to_bytes(response.into_body(), 8192)
                .await
                .expect("body bytes");
            let text = String::from_utf8_lossy(&bytes);
            assert!(
                !text.contains("Wrong number of path arguments"),
                "numeric issue ids must not fail Path extraction for {uri}: {text}"
            );
        }
    }

    #[tokio::test]
    async fn v1_taste_dismiss_ingress_preserves_same_path_and_requires_auth() {
        let mut router = app();
        let response = router
            .call(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/taste/discoveries/7/dismiss")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .expect("router response");
        assert!(
            response.status() == StatusCode::UNAUTHORIZED
                || response.status() == StatusCode::SERVICE_UNAVAILABLE
                || response.status() == StatusCode::FORBIDDEN,
            "taste dismiss must require auth and reach Rust, got {}",
            response.status()
        );
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime").unwrap(),
            "rust"
        );
        let bytes = to_bytes(response.into_body(), 8192)
            .await
            .expect("body bytes");
        let text = String::from_utf8_lossy(&bytes);
        assert!(
            !text.contains("Wrong number of path arguments"),
            "numeric signal ids must not fail Path extraction: {text}"
        );
    }

    #[tokio::test]
    async fn comicvine_import_status_ingress_preserves_same_path_and_requires_auth() {
        let mut router = app();
        let response = router
            .call(
                Request::builder()
                    .method("GET")
                    .uri("/api/v1/comicvine/series/42/import-status")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .expect("router response");
        assert!(
            response.status() == StatusCode::UNAUTHORIZED
                || response.status() == StatusCode::SERVICE_UNAVAILABLE,
            "ComicVine import status must require auth and reach Rust, got {}",
            response.status()
        );
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime").unwrap(),
            "rust"
        );
    }

    #[tokio::test]
    async fn bug_report_ingress_preserves_same_paths_and_requires_auth() {
        for uri in ["/api/bug-reports/", "/api/v1/bug-reports/"] {
            let mut router = app();
            let response = router
                .call(
                    Request::builder()
                        .method("POST")
                        .uri(uri)
                        .header("content-type", "application/json")
                        .body(Body::from(r#"{"title":"Bug","description":"Details"}"#))
                        .unwrap(),
                )
                .await
                .expect("router response");
            assert!(
                response.status() == StatusCode::UNAUTHORIZED
                    || response.status() == StatusCode::SERVICE_UNAVAILABLE,
                "{uri} must require auth and reach Rust, got {}",
                response.status()
            );
            assert_eq!(
                response.headers().get("x-comicpile-api-runtime").unwrap(),
                "rust"
            );
        }
    }

    #[tokio::test]
    async fn session_detail_ingress_preserves_same_paths_and_requires_auth() {
        for uri in ["/api/sessions/7", "/api/v1/sessions/7"] {
            let mut router = app();
            let response = router
                .call(
                    Request::builder()
                        .method("GET")
                        .uri(uri)
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .expect("router response");
            assert!(
                response.status() == StatusCode::UNAUTHORIZED
                    || response.status() == StatusCode::SERVICE_UNAVAILABLE,
                "{uri} must require auth and reach Rust, got {}",
                response.status()
            );
            assert_eq!(
                response.headers().get("x-comicpile-api-runtime").unwrap(),
                "rust"
            );
            let bytes = to_bytes(response.into_body(), 8192)
                .await
                .expect("body bytes");
            let text = String::from_utf8_lossy(&bytes);
            assert!(
                !text.contains("Wrong number of path arguments"),
                "numeric session ids must not fail Path extraction for {uri}: {text}"
            );
        }
    }

    #[tokio::test]
    async fn unknown_api_route_returns_rust_json_404_without_database() {
        let mut router = app();
        let response = router
            .call(
                Request::builder()
                    .uri("/api/v2/definitely-not-registered")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .expect("router response");
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime").unwrap(),
            "rust"
        );
        let bytes = to_bytes(response.into_body(), 1024)
            .await
            .expect("body bytes");
        assert_eq!(
            serde_json::from_slice::<Value>(&bytes).expect("JSON"),
            serde_json::json!({"detail": "Not Found"})
        );
    }

    async fn disposable_schema_url() -> String {
        let base = std::env::var("RUST_ROLL_TEST_DATABASE_URL")
            .expect("disposable RUST_ROLL_TEST_DATABASE_URL required; tests never silently skip");
        let (admin, connection) = tokio_postgres::connect(&base, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let schema = format!("ingress_queue_{}_{}", std::process::id(), nanos);
        admin
            .batch_execute(&format!(
                "CREATE SCHEMA {schema};
                 CREATE TABLE {schema}.users (
                     id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                     username text UNIQUE NOT NULL,
                     email text,
                     password_hash text,
                     is_admin boolean NOT NULL DEFAULT false,
                     password_changed_at timestamptz,
                     created_at timestamptz NOT NULL
                 );
                 CREATE TABLE {schema}.failed_login_attempts (
                     id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                     username text NOT NULL,
                     ip_address text NOT NULL,
                     attempted_at timestamptz NOT NULL DEFAULT NOW()
                 );
                 CREATE TABLE {schema}.revoked_tokens (
                     id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                     user_id integer NOT NULL,
                     jti text NOT NULL UNIQUE,
                     revoked_at timestamptz NOT NULL DEFAULT NOW(),
                     expires_at timestamptz NOT NULL
                 );
                 CREATE TABLE {schema}.password_reset_tokens (
                     id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                     user_id integer NOT NULL,
                     token_digest text NOT NULL UNIQUE,
                     expires_at timestamptz NOT NULL,
                     used_at timestamptz,
                     created_at timestamptz NOT NULL
                 );
                 CREATE TABLE {schema}.threads (
                     id integer PRIMARY KEY,
                     user_id integer NOT NULL,
                     title text NOT NULL DEFAULT '',
                     status text NOT NULL DEFAULT 'active',
                     queue_position integer NOT NULL,
                     queue_position_is_manual boolean NOT NULL DEFAULT false,
                     is_blocked boolean NOT NULL DEFAULT false
                 );
                 CREATE TABLE {schema}.events (
                     id serial PRIMARY KEY,
                     type text NOT NULL,
                     timestamp timestamptz NOT NULL DEFAULT now(),
                     user_id integer,
                     thread_id integer
                 );"
            ))
            .await
            .expect("ingress queue schema");
        let separator = if base.contains('?') { '&' } else { '?' };
        format!("{base}{separator}sslmode=disable&options=-c%20search_path%3D{schema}")
    }

    fn test_state(url: &str) -> Arc<AppState> {
        Arc::new(
            AppState::new(
                Config::from_lookup(|key| match key {
                    "RUST_ROLL_DATABASE_URL" => Some(url.into()),
                    "RUST_ROLL_JWT_SECRET" => Some(JWT_SECRET.into()),
                    "RUST_ROLL_POOL_SIZE" => Some("2".into()),
                    _ => None,
                })
                .expect("ingress test config"),
            )
            .expect("ingress test state"),
        )
    }

    async fn call_app(request: Request<Body>) -> (StatusCode, Value, Vec<String>, String) {
        let mut router = app();
        let response = router.call(request).await.expect("native response");
        let status = response.status();
        let cookies = response
            .headers()
            .get_all(header::SET_COOKIE)
            .iter()
            .filter_map(|value| value.to_str().ok().map(str::to_owned))
            .collect::<Vec<_>>();
        let body = to_bytes(response.into_body(), 8192)
            .await
            .expect("response body");
        let text = String::from_utf8_lossy(&body).into_owned();
        let json = serde_json::from_slice(&body).unwrap_or(Value::Null);
        (status, json, cookies, text)
    }

    fn csrf_from(cookies: &[String]) -> String {
        cookies
            .iter()
            .find_map(|cookie| {
                cookie
                    .split(';')
                    .next()
                    .and_then(|part| part.strip_prefix("csrf_token="))
                    .map(str::to_owned)
            })
            .expect("csrf cookie")
    }

    fn assert_not_path_extraction_500(status: StatusCode, body: &str) {
        assert!(
            !(status == StatusCode::INTERNAL_SERVER_ERROR
                && body.contains("Wrong number of path arguments")),
            "numeric queue-entry ids must not fail Path extraction: {body}"
        );
    }

    async fn register_session(username: &str) -> (String, String, i32) {
        let (status, body, cookies, text) = call_app(
            Request::builder()
                .method("POST")
                .uri("/api/v2/auth/register")
                .header(header::CONTENT_TYPE, "application/json")
                .header("x-forwarded-for", "198.51.100.20")
                .body(Body::from(
                    serde_json::json!({
                        "username": username,
                        "email": format!("{username}@example.com"),
                        "password": "correct-horse-battery"
                    })
                    .to_string(),
                ))
                .expect("register request"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{text}");
        let access = body["access_token"]
            .as_str()
            .expect("access token")
            .to_owned();
        let connection = TEST_ROLL_STATE
            .try_with(Clone::clone)
            .expect("test state")
            .pool
            .get()
            .await
            .expect("user lookup");
        let user_id: i32 = connection
            .query_one("SELECT id FROM users WHERE username = $1", &[&username])
            .await
            .expect("registered user")
            .get(0);
        (access, csrf_from(&cookies), user_id)
    }

    async fn seed_threads(user_id: i32, rows: &[(i32, i32)]) {
        let connection = TEST_ROLL_STATE
            .try_with(Clone::clone)
            .expect("test state")
            .pool
            .get()
            .await
            .expect("seed connection");
        for (id, position) in rows {
            connection
                .execute(
                    "INSERT INTO threads (id, user_id, status, queue_position) \
                     VALUES ($1, $2, 'active', $3)",
                    &[id, &user_id, position],
                )
                .await
                .expect("seed thread");
        }
    }

    async fn stored_order(user_id: i32) -> Vec<i32> {
        let connection = TEST_ROLL_STATE
            .try_with(Clone::clone)
            .expect("test state")
            .pool
            .get()
            .await
            .expect("order connection");
        connection
            .query(
                "SELECT id FROM threads WHERE user_id = $1 AND status = 'active' \
                 AND queue_position >= 1 ORDER BY queue_position, id",
                &[&user_id],
            )
            .await
            .expect("read order")
            .iter()
            .map(|row| row.get(0))
            .collect()
    }

    async fn queue_request(
        method: &str,
        thread_id: i32,
        access: &str,
        csrf: &str,
        body: Option<Value>,
    ) -> (StatusCode, Value, String) {
        let mut builder = Request::builder()
            .method(method)
            .uri(format!("/api/v2/queue-entries/{thread_id}"))
            .header(header::AUTHORIZATION, format!("Bearer {access}"))
            .header(header::COOKIE, format!("csrf_token={csrf}"))
            .header("x-csrf-token", csrf);
        if body.is_some() {
            builder = builder.header(header::CONTENT_TYPE, "application/json");
        }
        let (status, json, _, text) = call_app(
            builder
                .body(match body {
                    Some(payload) => Body::from(payload.to_string()),
                    None => Body::empty(),
                })
                .expect("queue request"),
        )
        .await;
        assert_not_path_extraction_500(status, &text);
        (status, json, text)
    }

    #[tokio::test]
    async fn canonical_bootstrap_preserves_auth_and_query_through_rust_ingress() {
        let request = Request::builder()
            .method("GET")
            .uri("/api/v2/roll/bootstrap?timezone=America%2FChicago")
            .header("authorization", "Bearer synthetic-test-token")
            .body(Body::empty())
            .expect("canonical request");
        assert_eq!(
            request.uri().to_string(),
            "/api/v2/roll/bootstrap?timezone=America%2FChicago"
        );
        assert_eq!(
            request.headers().get("authorization"),
            Some(&axum::http::HeaderValue::from_static(
                "Bearer synthetic-test-token"
            ))
        );

        // Exercise the actual production Axum router with no special-case URL rewrite.
        let mut router = app();
        let response = router.call(request).await.expect("Rust response");
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime"),
            Some(&axum::http::HeaderValue::from_static("rust"))
        );
        assert!(
            response.status() == StatusCode::SERVICE_UNAVAILABLE
                || response.status() == StatusCode::UNAUTHORIZED,
            "canonical path must reach Rust startup or bearer authentication"
        );
    }

    #[tokio::test]
    async fn native_probe_serves_json_without_config_or_database() {
        let mut router = app();
        let request = Request::builder()
            .method("GET")
            .uri("/api/v2/health")
            .body(Body::empty())
            .expect("valid request");
        let response = router.call(request).await.expect("health response");
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime"),
            Some(&axum::http::HeaderValue::from_static("rust"))
        );
        assert_eq!(
            response.headers().get(header::CONTENT_TYPE),
            Some(&axum::http::HeaderValue::from_static("application/json"))
        );
        let body = to_bytes(response.into_body(), 1024)
            .await
            .expect("health JSON");
        let health: serde_json::Value = serde_json::from_slice(&body).expect("valid JSON");
        assert_eq!(health["status"], "ok");
        assert_eq!(health["runtime"], "rust");
        assert_eq!(health["service"], "roll");
        assert_eq!(
            health["build"]["revision"],
            env!("COMICPILE_SOURCE_REVISION")
        );
        assert!(health["build"]["compiler"]
            .as_str()
            .unwrap()
            .starts_with("rustc "));
        assert_eq!(health["build"]["package"], env!("CARGO_PKG_NAME"));
        let executable = std::env::current_exe().expect("current executable");
        assert_eq!(
            health["process"]["executable"],
            executable.file_name().unwrap().to_string_lossy().as_ref()
        );
        assert_eq!(health["process"]["os"], std::env::consts::OS);
        assert_eq!(health["process"]["arch"], std::env::consts::ARCH);
    }

    #[tokio::test]
    async fn vercel_service_propagates_the_wait_until_tracker_to_handlers() {
        async fn probe(parts: axum::http::request::Parts) -> StatusCode {
            if parts.extensions.get::<BackgroundTasks>().is_some() {
                StatusCode::OK
            } else {
                StatusCode::INTERNAL_SERVER_ERROR
            }
        }

        #[cfg(unix)]
        let log_context = LogContext::new(None, None, None);
        #[cfg(not(unix))]
        let log_context = LogContext::new();

        let mut service = NativeVercelService {
            router: Router::new().route("/probe", get(probe)),
        };
        let request = Request::builder()
            .method("GET")
            .uri("/probe")
            .body(Body::empty())
            .expect("valid probe request");
        let response = Service::call(&mut service, (VercelState::new(log_context), request))
            .await
            .expect("vercel service response");
        assert_eq!(
            response.status(),
            StatusCode::OK,
            "handlers must receive the invocation's tracked background registrar"
        );
    }

    #[tokio::test]
    async fn two_router_queue_entry_stack_repositions_without_path_extraction_500() {
        let url = disposable_schema_url().await;
        let state = test_state(&url);
        TEST_ROLL_STATE
            .scope(state, async {
                let username = format!("queue-ingress-{}", std::process::id());
                let (access, csrf, user_id) = register_session(&username).await;
                seed_threads(user_id, &[(11, 1), (12, 2), (13, 3)]).await;

                let (status, body, text) = queue_request("GET", 13, &access, &csrf, None).await;
                assert_eq!(status, StatusCode::OK, "{text}");
                assert_eq!(body["thread_id"], 13);
                assert_eq!(body["position"], 3);

                let (status, body, text) = queue_request(
                    "PATCH",
                    13,
                    &access,
                    &csrf,
                    Some(serde_json::json!({"position": 1})),
                )
                .await;
                assert_eq!(status, StatusCode::OK, "{text}");
                assert_eq!(body["thread_id"], 13);
                assert_eq!(body["position"], 1);
                assert_eq!(stored_order(user_id).await, vec![13, 11, 12]);

                let (status, body, text) = queue_request(
                    "PATCH",
                    13,
                    &access,
                    &csrf,
                    Some(serde_json::json!({"position": 2_147_483_647})),
                )
                .await;
                assert_eq!(status, StatusCode::OK, "{text}");
                assert_eq!(body["thread_id"], 13);
                assert_eq!(body["position"], 3);
                assert_eq!(stored_order(user_id).await, vec![11, 12, 13]);
            })
            .await;
    }
}
