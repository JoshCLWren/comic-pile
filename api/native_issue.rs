//! Vercel's native Rust ingress for the Issue endpoint cutover.
//! The health probe never reads database configuration.
use axum::{
    extract::Request,
    http::{Extensions, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, patch, post},
    Json, Router,
};
use comicpile_roll_service::{
    auth::BackgroundTasks, config::Config, router as issue_router, AppState,
};
use std::sync::{Arc, OnceLock};
use tower::{Service, ServiceBuilder};
use vercel_runtime::{axum::VercelLayer, Error};

async fn native_health() -> Response {
    let mut response = Json(serde_json::json!({
        "status": "ok",
        "runtime": "rust",
        "service": "issue"
    }))
    .into_response();
    response
        .headers_mut()
        .insert("x-comicpile-api-runtime", HeaderValue::from_static("rust"));
    response
}

static ISSUE_STATE: OnceLock<Result<Arc<AppState>, &'static str>> = OnceLock::new();

#[cfg(test)]
tokio::task_local! {
    static TEST_ISSUE_STATE: Arc<AppState>;
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
/// same `{issue_id}` pattern. axum 0.8 extends nested path params, so leaving
/// the ingress params in place makes `Path<i32>` see two arguments and return
/// its built-in 500. Keep only `BackgroundTasks` when the Vercel layer provided
/// one; issue handlers do not require any other outer extension.
fn prepare_inner_request(request: Request) -> Request {
    let (mut parts, body) = request.into_parts();
    let background = parts.extensions.remove::<BackgroundTasks>();
    parts.extensions = Extensions::new();
    if let Some(background) = background {
        parts.extensions.insert(background);
    }
    Request::from_parts(parts, body)
}

fn resolve_issue_state() -> Result<Arc<AppState>, &'static str> {
    #[cfg(test)]
    if let Ok(state) = TEST_ISSUE_STATE.try_with(Clone::clone) {
        return Ok(state);
    }
    ISSUE_STATE
        .get_or_init(|| {
            Config::from_vercel_env()
                .and_then(AppState::new)
                .map(Arc::new)
                .map_err(|err| {
                    // ConfigError is a static, credential-free message.
                    eprintln!("native_issue initialisation failed: {err}");
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
    // Cold-start the native Issue service only for authenticated traffic.
    // Keep health independent of DB secrets and failures.
    let request = prepare_inner_request(request);
    let mut result = match resolve_issue_state() {
        Ok(state) => {
            let mut router = issue_router(state);
            match router.call(request).await {
                Ok(response) => response,
                Err(never) => match never {},
            }
        }
        Err(_) => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({"detail": "Native Issue unavailable"})),
        )
            .into_response(),
    };
    result
        .headers_mut()
        .insert("x-comicpile-api-runtime", HeaderValue::from_static("rust"));
    eprintln!(
        "native_issue route={} runtime=rust status={} elapsed_ms={}",
        ingress_path,
        result.status().as_u16(),
        started.elapsed().as_millis()
    );
    result
}

fn app() -> Router {
    Router::new()
        .route("/api/_native_issue/health", get(native_health))
        .route("/api/v2/issues/{issue_id}", patch(native_dispatch))
        .route("/api/v2/issues/cards", post(native_dispatch))
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    init_tracing();
    vercel_runtime::run(
        ServiceBuilder::new()
            .layer(VercelLayer::new())
            .service(app()),
    )
    .await
}

#[cfg(test)]
mod tests {
    use super::{app, TEST_ISSUE_STATE};
    use axum::{
        body::{to_bytes, Body},
        http::{header, Request, StatusCode},
    };
    use comicpile_roll_service::{config::Config, router as service_router, AppState};
    use serde_json::Value;
    use std::sync::Arc;
    use tower::Service;

    const JWT_SECRET: &str = "synthetic-ingress-issue-secret";

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
        let schema = format!("ingress_issue_{}_{}", std::process::id(), nanos);
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
                     title text NOT NULL,
                     status text NOT NULL,
                     issues_remaining integer NOT NULL,
                     total_issues integer,
                     next_unread_issue_id integer,
                     reading_progress text,
                     last_rating double precision,
                     queue_position integer NOT NULL,
                     queue_position_is_manual boolean NOT NULL DEFAULT false,
                     last_activity_at timestamptz,
                     is_blocked boolean NOT NULL DEFAULT false
                 );
                 CREATE TABLE {schema}.issues (
                     id integer PRIMARY KEY,
                     thread_id integer NOT NULL,
                     issue_number text NOT NULL,
                     status text NOT NULL,
                     position integer NOT NULL,
                     read_at timestamptz,
                     catalog_issue_id bigint
                 );
                 CREATE TABLE {schema}.snapshots (
                     id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                     session_id integer NOT NULL,
                     event_id integer,
                     thread_states json NOT NULL,
                     session_state json,
                     created_at timestamptz NOT NULL DEFAULT NOW(),
                     description text,
                     snapshot_kind text,
                     schema_version integer
                 );
                 CREATE TABLE {schema}.events (
                     id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                     user_id integer,
                     type text,
                     timestamp timestamptz DEFAULT NOW(),
                     thread_id integer,
                     issue_id integer,
                     issue_number text,
                     rating double precision,
                     issues_read integer,
                     die integer,
                     die_after integer,
                     session_id integer,
                     source_roll_event_id integer,
                     context json
                 );
                 CREATE TABLE {schema}.dependencies (
                     id integer PRIMARY KEY,
                     source_issue_id integer NOT NULL,
                     target_issue_id integer NOT NULL,
                     note text
                 );
                 CREATE TABLE {schema}.sessions (
                     id integer PRIMARY KEY,
                     user_id integer,
                     started_at timestamptz NOT NULL DEFAULT NOW(),
                     start_die integer NOT NULL DEFAULT 6,
                     pending_thread_id integer,
                     pending_issue_id integer,
                     pending_thread_updated_at timestamptz,
                     snoozed_thread_ids json,
                     manual_die integer,
                     ended_at timestamptz,
                     predicted_bandwidth text,
                     active_bandwidth text,
                     bandwidth_confidence double precision,
                     bandwidth_source text,
                     bandwidth_version text,
                     bandwidth_updated_at timestamptz,
                     active_intent text,
                     predicted_intent text,
                     intent_confidence double precision,
                     intent_source text,
                     intent_version text
                 );
                 CREATE TABLE {schema}.external_identities (
                     id integer PRIMARY KEY,
                     provider text,
                     entity_type text,
                     external_id text,
                     metadata_json json
                 );
                 CREATE TABLE {schema}.issue_external_identity_mappings (
                     id integer PRIMARY KEY,
                     issue_id integer,
                     external_identity_id integer,
                     status text,
                     confidence double precision,
                     updated_at timestamptz DEFAULT NOW()
                 );"
            ))
            .await
            .expect("ingress issue schema");
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
                .expect("ingress issue config"),
            )
            .expect("ingress issue state"),
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

    #[tokio::test]
    async fn isolated_health_serves_json_without_config_or_database() {
        let mut router = app();
        let request = Request::builder()
            .method("GET")
            .uri("/api/_native_issue/health")
            .body(Body::empty())
            .expect("valid request");
        let response = router.call(request).await.expect("health response");
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers().get("x-comicpile-api-runtime"),
            Some(&axum::http::HeaderValue::from_static("rust")),
            "native health probe requires the Rust runtime marker"
        );
        assert_eq!(
            response.headers().get(header::CONTENT_TYPE),
            Some(&axum::http::HeaderValue::from_static("application/json"))
        );
        let body = to_bytes(response.into_body(), 1024)
            .await
            .expect("health JSON");
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&body).expect("valid JSON"),
            serde_json::json!({"status": "ok", "runtime": "rust", "service": "issue"})
        );
    }

    #[tokio::test]
    async fn two_router_issue_patch_stack_does_not_500_on_numeric_path() {
        let url = disposable_schema_url().await;
        let state = test_state(&url);
        TEST_ISSUE_STATE
            .scope(state.clone(), async {
                let username = format!("issue-ingress-{}", std::process::id());
                // Auth is not mounted on the issue ingress; mint the session
                // through the shared inner service router, then PATCH via app().
                let mut inner = service_router(state);
                let response = inner
                    .call(
                        Request::builder()
                            .method("POST")
                            .uri("/api/v2/auth/register")
                            .header(header::CONTENT_TYPE, "application/json")
                            .header("x-forwarded-for", "198.51.100.21")
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
                    .await
                    .expect("inner register");
                let status = response.status();
                let cookies = response
                    .headers()
                    .get_all(header::SET_COOKIE)
                    .iter()
                    .filter_map(|value| value.to_str().ok().map(str::to_owned))
                    .collect::<Vec<_>>();
                let body = to_bytes(response.into_body(), 8192)
                    .await
                    .expect("register body");
                let text = String::from_utf8_lossy(&body).into_owned();
                assert_eq!(status, StatusCode::OK, "{text}");
                let body: Value = serde_json::from_slice(&body).expect("register json");
                let access = body["access_token"]
                    .as_str()
                    .expect("access token")
                    .to_owned();
                let csrf = csrf_from(&cookies);
                let connection = TEST_ISSUE_STATE
                    .try_with(Clone::clone)
                    .expect("test state")
                    .pool
                    .get()
                    .await
                    .expect("seed connection");
                let user_id: i32 = connection
                    .query_one("SELECT id FROM users WHERE username = $1", &[&username])
                    .await
                    .expect("registered user")
                    .get(0);
                connection
                    .execute(
                        "INSERT INTO threads (
                             id, user_id, title, status, issues_remaining, total_issues,
                             next_unread_issue_id, reading_progress, last_rating,
                             queue_position, queue_position_is_manual, is_blocked
                         ) VALUES (40, $1, 'Ingress run', 'active', 1, 1, 401, 'in_progress',
                                   NULL, 1, false, false)",
                        &[&user_id],
                    )
                    .await
                    .expect("seed thread");
                connection
                    .execute(
                        "INSERT INTO issues (id, thread_id, issue_number, status, position)
                         VALUES (401, 40, '1', 'unread', 1)",
                        &[],
                    )
                    .await
                    .expect("seed issue");

                let (status, body, _, text) = call_app(
                    Request::builder()
                        .method("PATCH")
                        .uri("/api/v2/issues/401")
                        .header(header::CONTENT_TYPE, "application/json")
                        .header(header::AUTHORIZATION, format!("Bearer {access}"))
                        .header(header::COOKIE, format!("csrf_token={csrf}"))
                        .header("x-csrf-token", csrf)
                        .body(Body::from(
                            r#"{"status":"read","idempotency_key":"ingress-issue-012345"}"#,
                        ))
                        .expect("issue patch"),
                )
                .await;
                assert!(
                    !(status == StatusCode::INTERNAL_SERVER_ERROR
                        && text.contains("Wrong number of path arguments")),
                    "numeric issue ids must not fail Path extraction: {text}"
                );
                assert_eq!(status, StatusCode::OK, "{text}");
                assert_eq!(body["issue"]["issue_id"], 401);
                assert_eq!(body["issue"]["status"], "read");
            })
            .await;
    }
}
