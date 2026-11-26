#![allow(clippy::unwrap_used, clippy::expect_used)]
//! PostgreSQL-backed HTTP regressions for the mounted Rotisserie GitHub OAuth
//! routes. GitHub responses come from the recording fake, so no test opens a
//! socket and no real credential is required.

use axum::{
    body::{to_bytes, Body},
    http::{header, HeaderMap, Request, Response, StatusCode},
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use bytes::Bytes;
use comicpile_roll_service::{config::Config, router, test_support, AppState};
use jsonwebtoken::{encode, Algorithm, EncodingKey, Header};
use serde::Serialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{collections::HashMap, sync::Arc};
use tower::ServiceExt;

const PAGES_ORIGIN: &str = "https://joshclwren.github.io";
const PAGES_URL: &str = "https://joshclwren.github.io/comic-pile/";
const OWNER_ID: u64 = 4_014_199;

#[derive(Serialize)]
struct TestAdminSession<'a> {
    aud: &'a str,
    sub: &'a str,
    login: &'a str,
    iat: usize,
    exp: usize,
}

async fn database() -> (Arc<AppState>, tokio::sync::MutexGuard<'static, ()>) {
    let url = test_support::database_url().await;
    let state = Arc::new(test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some(test_support::TEST_JWT_SECRET.into()),
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .unwrap(),
    ));
    let guard = test_support::reset_for_test(&state).await;
    (state, guard)
}

async fn send(state: &Arc<AppState>, request: Request<Body>) -> Response<Body> {
    router(state.clone()).oneshot(request).await.unwrap()
}

fn header_text(response: &Response<Body>, name: header::HeaderName) -> &str {
    response
        .headers()
        .get(name)
        .and_then(|value| value.to_str().ok())
        .expect("response header must be text")
}

fn form(body: &[u8]) -> HashMap<String, String> {
    form_urlencoded::parse(body)
        .into_owned()
        .collect::<HashMap<_, _>>()
}

async fn start(state: &Arc<AppState>) -> (String, String, HashMap<String, String>) {
    let response = send(
        state,
        Request::builder()
            .method("GET")
            .uri("/api/v2/factory/github/start")
            .body(Body::empty())
            .unwrap(),
    )
    .await;
    assert_eq!(response.status(), StatusCode::SEE_OTHER);
    let location = header_text(&response, header::LOCATION).to_owned();
    let cookie = header_text(&response, header::SET_COOKIE)
        .split(';')
        .next()
        .unwrap()
        .to_owned();
    let full_cookie = header_text(&response, header::SET_COOKIE);
    assert!(full_cookie.contains("Secure"));
    assert!(full_cookie.contains("HttpOnly"));
    assert!(full_cookie.contains("SameSite=Lax"));
    assert!(full_cookie.contains("Path=/api/v2/factory/github"));
    let query = location.split_once('?').unwrap().1;
    let params = form(query.as_bytes());
    assert_eq!(params["client_id"], "synthetic-client-id");
    assert_eq!(params["code_challenge_method"], "S256");
    assert_eq!(
        params["redirect_uri"],
        "https://comic-pile.vercel.app/api/v2/factory/github/callback"
    );
    (location, cookie, params)
}

fn callback(state: &str, cookie: &str) -> Request<Body> {
    Request::builder()
        .method("GET")
        .uri(format!(
            "/api/v2/factory/github/callback?code=synthetic-code&state={state}"
        ))
        .header(header::COOKIE, cookie)
        .body(Body::empty())
        .unwrap()
}

fn session(token: &str, origin: &str) -> Request<Body> {
    Request::builder()
        .method("GET")
        .uri("/api/v2/factory/github/session")
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header(header::ORIGIN, origin)
        .body(Body::empty())
        .unwrap()
}

fn dispatch(token: &str, origin: &str, operation: &str) -> Request<Body> {
    Request::builder()
        .method("POST")
        .uri("/api/v2/factory/github/dispatch")
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header(header::ORIGIN, origin)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(json!({"operation": operation}).to_string()))
        .unwrap()
}

fn dispatch_details(run_id: u64) -> String {
    json!({
        "workflow_run_id": run_id,
        "run_url": format!("https://api.github.com/repos/JoshCLWren/comic-pile/actions/runs/{run_id}"),
        "html_url": format!("https://github.com/JoshCLWren/comic-pile/actions/runs/{run_id}"),
    })
    .to_string()
}

fn seconds() -> usize {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as usize
}

fn signed_session(sub: &str, exp: usize) -> String {
    let now = seconds();
    let claims = TestAdminSession {
        aud: "rotisserie-github-admin",
        sub,
        login: "synthetic-user",
        iat: now.saturating_sub(60),
        exp,
    };
    encode(
        &Header::new(Algorithm::HS256),
        &claims,
        &EncodingKey::from_secret(test_support::TEST_JWT_SECRET.as_bytes()).unwrap(),
    )
    .unwrap()
}

#[tokio::test]
async fn mounted_oauth_flow_preserves_pkce_admin_sessions_and_dispatch_boundaries() {
    let (state, _db) = database().await;
    std::env::set_var("ROTISSERIE_GITHUB_OAUTH_CLIENT_ID", "synthetic-client-id");
    std::env::set_var(
        "ROTISSERIE_GITHUB_OAUTH_CLIENT_SECRET",
        "synthetic-client-secret",
    );
    std::env::set_var("ROTISSERIE_ADMIN_GITHUB_IDS", "");
    std::env::set_var("GITHUB_TOKEN", "synthetic-workflow-token");

    let fake = state.recording_fake().unwrap();
    let (_location, cookie, params) = start(&state).await;

    // A state mismatch is rejected before either provider request.
    let mismatch = send(&state, callback("wrong-state", &cookie)).await;
    assert_eq!(mismatch.status(), StatusCode::SEE_OTHER);
    assert_eq!(
        header_text(&mismatch, header::LOCATION),
        format!("{PAGES_URL}#rotisserie_error=sign_in_failed")
    );
    assert!(fake.calls().is_empty());

    fake.push_ok(
        StatusCode::OK,
        HeaderMap::new(),
        Bytes::from_static(br#"{"access_token":"synthetic-github-user-token"}"#),
    );
    fake.push_ok(
        StatusCode::OK,
        HeaderMap::new(),
        Bytes::from(format!(r#"{{"id":{OWNER_ID},"login":"JoshCLWren"}}"#)),
    );
    let callback_response = send(&state, callback(&params["state"], &cookie)).await;
    assert_eq!(callback_response.status(), StatusCode::SEE_OTHER);
    let location = header_text(&callback_response, header::LOCATION).to_owned();
    let session_token = location
        .strip_prefix(&format!("{PAGES_URL}#rotisserie_session="))
        .expect("approved callback returns only a Rotisserie session")
        .to_owned();
    assert!(!location.contains("synthetic-github-user-token"));
    assert!(!location.contains("synthetic-client-secret"));
    assert!(header_text(&callback_response, header::SET_COOKIE).contains("Max-Age=0"));
    assert_eq!(
        header_text(&callback_response, header::CACHE_CONTROL),
        "no-store"
    );

    let calls = fake.calls();
    assert_eq!(calls.len(), 2);
    assert_eq!(calls[0].host, "github.com");
    assert_eq!(calls[0].path, "/login/oauth/access_token");
    let token_form = form(&calls[0].body);
    assert_eq!(token_form["code"], "synthetic-code");
    assert_eq!(token_form["client_secret"], "synthetic-client-secret");
    let verifier = token_form["code_verifier"].as_bytes();
    assert_eq!(
        URL_SAFE_NO_PAD.encode(Sha256::digest(verifier)),
        params["code_challenge"]
    );
    assert_eq!(calls[1].host, "api.github.com");
    assert_eq!(calls[1].path, "/user");
    assert!(calls[1]
        .headers
        .iter()
        .any(|(name, value)| name == "Authorization"
            && value == "Bearer synthetic-github-user-token"));

    let authenticated = send(&state, session(&session_token, PAGES_ORIGIN)).await;
    assert_eq!(authenticated.status(), StatusCode::OK);
    assert_eq!(
        header_text(&authenticated, header::ACCESS_CONTROL_ALLOW_ORIGIN),
        PAGES_ORIGIN
    );
    let payload: Value =
        serde_json::from_slice(&to_bytes(authenticated.into_body(), 4096).await.unwrap()).unwrap();
    assert_eq!(payload["authenticated"], true);
    assert_eq!(payload["login"], "JoshCLWren");
    assert_eq!(payload["github_id"], OWNER_ID.to_string());

    for (token, origin, expected) in [
        (
            session_token.as_str(),
            "https://attacker.example",
            StatusCode::FORBIDDEN,
        ),
        ("forged-session", PAGES_ORIGIN, StatusCode::UNAUTHORIZED),
        (
            signed_session(&OWNER_ID.to_string(), 0).as_str(),
            PAGES_ORIGIN,
            StatusCode::UNAUTHORIZED,
        ),
        (
            signed_session("77", seconds() + 300).as_str(),
            PAGES_ORIGIN,
            StatusCode::FORBIDDEN,
        ),
        (
            signed_session(&OWNER_ID.to_string(), seconds() + 3600).as_str(),
            PAGES_ORIGIN,
            StatusCode::FORBIDDEN,
        ),
    ] {
        let rejected = send(&state, session(token, origin)).await;
        assert_eq!(rejected.status(), expected);
    }

    // The dispatch route has a narrow non-ambient-bearer CSRF exemption, but
    // Origin, session expiry, administrator status and operation shape still
    // reject requests before any privileged workflow call.
    for (token, origin, operation, expected) in [
        (
            session_token.as_str(),
            "https://attacker.example",
            "doctor_fix",
            StatusCode::FORBIDDEN,
        ),
        (
            session_token.as_str(),
            PAGES_ORIGIN,
            "arbitrary_shell",
            StatusCode::BAD_REQUEST,
        ),
        (
            signed_session(&OWNER_ID.to_string(), 0).as_str(),
            PAGES_ORIGIN,
            "doctor_fix",
            StatusCode::UNAUTHORIZED,
        ),
        (
            signed_session("77", seconds() + 300).as_str(),
            PAGES_ORIGIN,
            "doctor_fix",
            StatusCode::FORBIDDEN,
        ),
    ] {
        let rejected = send(&state, dispatch(token, origin, operation)).await;
        assert_eq!(rejected.status(), expected);
    }
    assert_eq!(fake.calls().len(), 2, "rejected requests reached GitHub");

    // The configured GitHub API version returns 200 with workflow details.
    fake.push_ok(
        StatusCode::OK,
        HeaderMap::new(),
        Bytes::from(dispatch_details(1234)),
    );
    let accepted = send(&state, dispatch(&session_token, PAGES_ORIGIN, "doctor_fix")).await;
    assert_eq!(accepted.status(), StatusCode::ACCEPTED);
    let payload: Value =
        serde_json::from_slice(&to_bytes(accepted.into_body(), 4096).await.unwrap()).unwrap();
    assert_eq!(payload["result"], "accepted");
    assert_eq!(payload["run_id"], 1234);
    assert_eq!(
        payload["run_url"],
        "https://github.com/JoshCLWren/comic-pile/actions/runs/1234"
    );
    let calls = fake.calls();
    assert_eq!(calls.len(), 3);
    let workflow = &calls[2];
    assert_eq!(workflow.host, "api.github.com");
    assert_eq!(
        workflow.path,
        "/repos/JoshCLWren/comic-pile/actions/workflows/rotisserie-operator.yml/dispatches"
    );
    assert!(
        workflow
            .headers
            .iter()
            .any(|(name, value)| name == "Authorization"
                && value == "Bearer synthetic-workflow-token")
    );
    assert!(!workflow
        .headers
        .iter()
        .any(|(_, value)| value.contains(&session_token)));
    let workflow_body: Value = serde_json::from_slice(&workflow.body).unwrap();
    assert_eq!(workflow_body["ref"], "main");
    let command: Value =
        serde_json::from_str(workflow_body["inputs"]["request"].as_str().unwrap()).unwrap();
    assert_eq!(command, json!({"operation": "doctor_fix"}));

    // A verified GitHub identity outside the immutable allowlist never gets a
    // Rotisserie session, even after a successful OAuth code exchange.
    let (_location, denied_cookie, denied_params) = start(&state).await;
    fake.push_ok(
        StatusCode::OK,
        HeaderMap::new(),
        Bytes::from_static(br#"{"access_token":"denied-github-user-token"}"#),
    );
    fake.push_ok(
        StatusCode::OK,
        HeaderMap::new(),
        Bytes::from_static(br#"{"id":77,"login":"not-an-admin"}"#),
    );
    let denied = send(&state, callback(&denied_params["state"], &denied_cookie)).await;
    assert_eq!(denied.status(), StatusCode::SEE_OTHER);
    assert_eq!(
        header_text(&denied, header::LOCATION),
        format!("{PAGES_URL}#rotisserie_error=not_admin")
    );
    assert_eq!(fake.calls().len(), 5);
}

const WRITE_OPERATIONS: [&str; 22] = [
    "run",
    "cancel",
    "prioritize",
    "sync",
    "unstick",
    "settings",
    "provider_switch",
    "model_switch",
    "incident_start",
    "incident_stop",
    "doctor_fix",
    "release_expired",
    "claim",
    "finish",
    "labels",
    "estimate_neon",
    "close",
    "backoffs_reset",
    "allow_self_review",
    "store_selftest",
    "store_export",
    "store_migrate",
];
const WORKFLOWS: &str = "/repos/JoshCLWren/comic-pile/actions/workflows";

async fn operator_state() -> (Arc<AppState>, tokio::sync::MutexGuard<'static, ()>, String) {
    let (state, guard) = database().await;
    std::env::set_var("ROTISSERIE_ADMIN_GITHUB_IDS", "");
    std::env::set_var("GITHUB_TOKEN", "synthetic-workflow-token");
    let token = signed_session(&OWNER_ID.to_string(), seconds() + 300);
    (state, guard, token)
}

fn dispatch_body(token: &str, body: Value) -> Request<Body> {
    Request::builder()
        .method("POST")
        .uri("/api/v2/factory/github/dispatch")
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header(header::ORIGIN, PAGES_ORIGIN)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(body.to_string()))
        .unwrap()
}

fn run_request(token: &str, origin: &str, run_id: &str) -> Request<Body> {
    Request::builder()
        .method("GET")
        .uri(format!("/api/v2/factory/github/runs/{run_id}"))
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header(header::ORIGIN, origin)
        .body(Body::empty())
        .unwrap()
}

async fn json_body(response: Response<Body>) -> Value {
    serde_json::from_slice(&to_bytes(response.into_body(), 1 << 21).await.unwrap()).unwrap()
}

fn push_json(fake: &comicpile_roll_service::outbound::RecordingFakeOutbound, body: Value) {
    fake.push_ok(
        StatusCode::OK,
        HeaderMap::new(),
        Bytes::from(body.to_string()),
    );
}

fn workflow_run(run_id: u64, workflow: &str, status: &str) -> Value {
    json!({
        "id": run_id,
        "path": format!(".github/workflows/{workflow}"),
        "status": status,
        "conclusion": if status == "completed" { json!("success") } else { Value::Null },
        "html_url": format!("https://github.com/JoshCLWren/comic-pile/actions/runs/{run_id}"),
    })
}

fn artifacts(run_id: u64, size: u64) -> Value {
    json!({"total_count": 1, "artifacts": [{
        "id": 77,
        "name": format!("rotisserie-operator-{run_id}"),
        "size_in_bytes": size,
        "expired": false,
    }]})
}

fn redirect_to(location: &str) -> HeaderMap {
    let mut headers = HeaderMap::new();
    headers.insert(header::LOCATION, location.parse().unwrap());
    headers
}

/// A streamed archive like upload-artifact writes: zero sizes in the local
/// header, real sizes in a data descriptor and the central directory.
fn streamed_zip(name: &str, content: &[u8]) -> Vec<u8> {
    let data = miniz_oxide::deflate::compress_to_vec(content, 6);
    let sizes = [data.len() as u32, content.len() as u32];
    let mut zip = Vec::new();
    zip.extend_from_slice(&0x0403_4b50u32.to_le_bytes());
    zip.extend_from_slice(&[20, 0, 8, 0, 8, 0]);
    zip.extend_from_slice(&[0; 16]);
    zip.extend_from_slice(&(name.len() as u16).to_le_bytes());
    zip.extend_from_slice(&[0; 2]);
    zip.extend_from_slice(name.as_bytes());
    zip.extend_from_slice(&data);
    zip.extend_from_slice(&0x0807_4b50u32.to_le_bytes());
    zip.extend_from_slice(&[0; 4]);
    sizes
        .iter()
        .for_each(|size| zip.extend_from_slice(&size.to_le_bytes()));
    let directory = zip.len() as u32;
    zip.extend_from_slice(&0x0201_4b50u32.to_le_bytes());
    zip.extend_from_slice(&[20, 0, 20, 0, 8, 0, 8, 0]);
    zip.extend_from_slice(&[0; 8]);
    sizes
        .iter()
        .for_each(|size| zip.extend_from_slice(&size.to_le_bytes()));
    zip.extend_from_slice(&(name.len() as u16).to_le_bytes());
    zip.extend_from_slice(&[0; 12]);
    zip.extend_from_slice(&0u32.to_le_bytes());
    zip.extend_from_slice(name.as_bytes());
    let directory_len = zip.len() as u32 - directory;
    zip.extend_from_slice(&0x0605_4b50u32.to_le_bytes());
    zip.extend_from_slice(&[0, 0, 0, 0, 1, 0, 1, 0]);
    zip.extend_from_slice(&directory_len.to_le_bytes());
    zip.extend_from_slice(&directory.to_le_bytes());
    zip.extend_from_slice(&[0; 2]);
    zip
}

#[tokio::test]
async fn dispatch_accepts_every_rotisserie_operation_and_routes_reads() {
    let (state, _db, token) = operator_state().await;
    let fake = state.recording_fake().unwrap();

    for (index, operation) in WRITE_OPERATIONS.iter().enumerate() {
        let run_id = 500 + index as u64;
        fake.push_ok(
            StatusCode::OK,
            HeaderMap::new(),
            Bytes::from(dispatch_details(run_id)),
        );
        let response = send(
            &state,
            dispatch_body(
                &token,
                json!({"operation": operation, "request_id": "request-1"}),
            ),
        )
        .await;
        assert_eq!(response.status(), StatusCode::ACCEPTED, "{operation}");
        let payload = json_body(response).await;
        assert_eq!(payload["run_id"], run_id, "{operation}");
        assert_eq!(payload["request_id"], "request-1");
        let call = fake.calls().pop().unwrap();
        assert_eq!(
            call.path,
            format!("{WORKFLOWS}/rotisserie-operator.yml/dispatches"),
            "{operation}"
        );
    }

    fake.push_ok(
        StatusCode::OK,
        HeaderMap::new(),
        Bytes::from(dispatch_details(900)),
    );
    let read = json!({
        "operation": "read",
        "request_id": "0b8f6d2e-6f4f-4a51-9f3c-3d1f0f8a2b11",
        "reads": [{"name": "leases"}],
    });
    let response = send(&state, dispatch_body(&token, read.clone())).await;
    assert_eq!(response.status(), StatusCode::ACCEPTED);
    let payload = json_body(response).await;
    assert_eq!(payload["run_id"], 900);
    assert_eq!(
        payload["run_url"],
        "https://github.com/JoshCLWren/comic-pile/actions/runs/900"
    );
    assert_eq!(payload["request_id"], read["request_id"]);
    let call = fake.calls().pop().unwrap();
    assert_eq!(
        call.path,
        format!("{WORKFLOWS}/rotisserie-operator-read.yml/dispatches")
    );
    let body: Value = serde_json::from_slice(&call.body).unwrap();
    let forwarded: Value =
        serde_json::from_str(body["inputs"]["request"].as_str().unwrap()).unwrap();
    assert_eq!(forwarded, read);

    // An accepted dispatch without run details still succeeds without a run.
    fake.push_ok(StatusCode::NO_CONTENT, HeaderMap::new(), Bytes::new());
    let response = send(&state, dispatch_body(&token, json!({"operation": "claim"}))).await;
    assert_eq!(response.status(), StatusCode::ACCEPTED);
    let payload = json_body(response).await;
    assert_eq!(payload["run_id"], Value::Null);
    assert_eq!(payload["result"], "accepted");

    let calls_before = fake.calls().len();
    for rejected in [
        json!({"operation": "arbitrary_shell"}),
        json!({"operation": "Read"}),
        json!({"operation": "doctor"}),
        json!({"operation": ""}),
        json!({}),
        json!({"operation": "read", "request_id": "bad id"}),
        json!({"operation": "run", "request_id": 7}),
        json!({"operation": "run", "request_id": "short"}),
        json!({"operation": "read", "reads": "x".repeat(5000)}),
    ] {
        let response = send(&state, dispatch_body(&token, rejected.clone())).await;
        assert_eq!(response.status(), StatusCode::BAD_REQUEST, "{rejected}");
    }
    assert_eq!(
        fake.calls().len(),
        calls_before,
        "rejected commands reached GitHub"
    );
}

#[tokio::test]
async fn run_status_enforces_session_origin_and_refuses_foreign_workflows() {
    let (state, _db, token) = operator_state().await;
    let fake = state.recording_fake().unwrap();

    let expired = signed_session(&OWNER_ID.to_string(), 0);
    let outsider = signed_session("77", seconds() + 300);
    for (session, origin, run_id, expected) in [
        (
            token.as_str(),
            "https://attacker.example",
            "5",
            StatusCode::FORBIDDEN,
        ),
        (
            "forged-session",
            PAGES_ORIGIN,
            "5",
            StatusCode::UNAUTHORIZED,
        ),
        (
            expired.as_str(),
            PAGES_ORIGIN,
            "5",
            StatusCode::UNAUTHORIZED,
        ),
        (outsider.as_str(), PAGES_ORIGIN, "5", StatusCode::FORBIDDEN),
        (token.as_str(), PAGES_ORIGIN, "abc", StatusCode::NOT_FOUND),
        (
            token.as_str(),
            PAGES_ORIGIN,
            "123456789012345678901",
            StatusCode::NOT_FOUND,
        ),
    ] {
        let response = send(&state, run_request(session, origin, run_id)).await;
        assert_eq!(response.status(), expected, "{origin} {run_id}");
        assert_eq!(
            header_text(&response, header::ACCESS_CONTROL_ALLOW_ORIGIN),
            PAGES_ORIGIN
        );
    }
    assert!(
        fake.calls().is_empty(),
        "rejected run lookups reached GitHub"
    );

    push_json(fake, workflow_run(41, "ci.yml", "completed"));
    let foreign = send(&state, run_request(&token, PAGES_ORIGIN, "41")).await;
    assert_eq!(foreign.status(), StatusCode::NOT_FOUND);
    push_json(
        fake,
        workflow_run(99, "rotisserie-operator.yml", "completed"),
    );
    let mismatched = send(&state, run_request(&token, PAGES_ORIGIN, "42")).await;
    assert_eq!(mismatched.status(), StatusCode::NOT_FOUND);
    fake.push_ok(StatusCode::NOT_FOUND, HeaderMap::new(), Bytes::new());
    let missing = send(&state, run_request(&token, PAGES_ORIGIN, "43")).await;
    assert_eq!(missing.status(), StatusCode::NOT_FOUND);
    // GitHub's own 401 or 403 must not sign the page out.
    fake.push_ok(StatusCode::FORBIDDEN, HeaderMap::new(), Bytes::new());
    let denied = send(&state, run_request(&token, PAGES_ORIGIN, "44")).await;
    assert_eq!(denied.status(), StatusCode::SERVICE_UNAVAILABLE);
    let calls = fake.calls();
    assert_eq!(calls.len(), 4);
    assert_eq!(
        calls[0].path,
        "/repos/JoshCLWren/comic-pile/actions/runs/41"
    );
    assert!(
        calls[0]
            .headers
            .iter()
            .any(|(name, value)| name == "Authorization"
                && value == "Bearer synthetic-workflow-token")
    );

    push_json(
        fake,
        workflow_run(45, "rotisserie-operator-read.yml", "in_progress"),
    );
    let running = send(&state, run_request(&token, PAGES_ORIGIN, "45")).await;
    assert_eq!(running.status(), StatusCode::OK);
    let payload = json_body(running).await;
    assert_eq!(payload["run_id"], 45);
    assert_eq!(payload["status"], "in_progress");
    assert_eq!(payload["conclusion"], Value::Null);
    assert_eq!(payload["result"], Value::Null);
    assert_eq!(
        payload["run_url"],
        "https://github.com/JoshCLWren/comic-pile/actions/runs/45"
    );
    assert_eq!(fake.calls().len(), 5, "an unfinished run downloads nothing");
}

#[tokio::test]
async fn completed_run_returns_the_artifact_json_and_caps_its_size() {
    let (state, _db, token) = operator_state().await;
    let fake = state.recording_fake().unwrap();
    let storage = "https://productionresultssa1.blob.core.windows.net/actions/77.zip?sig=synthetic";
    let envelope = json!({"request_id": "req-9", "kind": "read", "exit_code": 0, "reads": []});

    push_json(
        fake,
        workflow_run(60, "rotisserie-operator-read.yml", "completed"),
    );
    push_json(fake, artifacts(60, 300));
    fake.push_ok(StatusCode::FOUND, redirect_to(storage), Bytes::new());
    fake.push_ok(
        StatusCode::OK,
        HeaderMap::new(),
        Bytes::from(streamed_zip(
            "rotisserie-result.json",
            envelope.to_string().as_bytes(),
        )),
    );
    let response = send(&state, run_request(&token, PAGES_ORIGIN, "60")).await;
    assert_eq!(response.status(), StatusCode::OK);
    let payload = json_body(response).await;
    assert_eq!(payload["status"], "completed");
    assert_eq!(payload["conclusion"], "success");
    assert_eq!(payload["result"], envelope);
    let calls = fake.calls();
    assert_eq!(calls.len(), 4);
    assert_eq!(
        calls[1].path,
        "/repos/JoshCLWren/comic-pile/actions/runs/60/artifacts?name=rotisserie-operator-60&per_page=10"
    );
    assert_eq!(
        calls[2].path,
        "/repos/JoshCLWren/comic-pile/actions/artifacts/77/zip"
    );
    assert_eq!(calls[3].host, "productionresultssa1.blob.core.windows.net");
    assert_eq!(calls[3].path, "/actions/77.zip?sig=synthetic");
    assert!(
        !calls[3]
            .headers
            .iter()
            .any(|(name, _)| name == "Authorization"),
        "the GitHub token must not reach artifact storage"
    );

    // No artifact yet, or an expired one, gives a null result.
    push_json(
        fake,
        workflow_run(61, "rotisserie-operator.yml", "completed"),
    );
    push_json(fake, json!({"total_count": 0, "artifacts": []}));
    let payload = json_body(send(&state, run_request(&token, PAGES_ORIGIN, "61")).await).await;
    assert_eq!(payload["result"], Value::Null);
    push_json(
        fake,
        workflow_run(62, "rotisserie-operator.yml", "completed"),
    );
    push_json(fake, artifacts(62, 300));
    fake.push_ok(StatusCode::GONE, HeaderMap::new(), Bytes::new());
    let payload = json_body(send(&state, run_request(&token, PAGES_ORIGIN, "62")).await).await;
    assert_eq!(payload["result"], Value::Null);

    // A declared size over 1 MB is refused before any download.
    let before = fake.calls().len();
    push_json(
        fake,
        workflow_run(63, "rotisserie-operator.yml", "completed"),
    );
    push_json(fake, artifacts(63, 1024 * 1024 + 1));
    let response = send(&state, run_request(&token, PAGES_ORIGIN, "63")).await;
    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(fake.calls().len(), before + 2);

    // An archive that streams more than 1 MB is refused.
    push_json(
        fake,
        workflow_run(64, "rotisserie-operator.yml", "completed"),
    );
    push_json(fake, artifacts(64, 300));
    fake.push_ok(StatusCode::FOUND, redirect_to(storage), Bytes::new());
    fake.push_ok(
        StatusCode::OK,
        HeaderMap::new(),
        Bytes::from(vec![b'P'; 1024 * 1024 + 1]),
    );
    let response = send(&state, run_request(&token, PAGES_ORIGIN, "64")).await;
    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);

    // A small archive whose JSON file inflates past 1 MB is refused.
    let inflated = format!("\"{}\"", " ".repeat(1024 * 1024 + 1));
    push_json(
        fake,
        workflow_run(65, "rotisserie-operator.yml", "completed"),
    );
    push_json(fake, artifacts(65, 300));
    fake.push_ok(StatusCode::FOUND, redirect_to(storage), Bytes::new());
    fake.push_ok(
        StatusCode::OK,
        HeaderMap::new(),
        Bytes::from(streamed_zip("rotisserie-result.json", inflated.as_bytes())),
    );
    let response = send(&state, run_request(&token, PAGES_ORIGIN, "65")).await;
    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);

    // A redirect off the artifact storage hosts is never followed.
    let before = fake.calls().len();
    push_json(
        fake,
        workflow_run(66, "rotisserie-operator.yml", "completed"),
    );
    push_json(fake, artifacts(66, 300));
    fake.push_ok(
        StatusCode::FOUND,
        redirect_to("https://attacker.example/x.zip"),
        Bytes::new(),
    );
    let response = send(&state, run_request(&token, PAGES_ORIGIN, "66")).await;
    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(fake.calls().len(), before + 3);
}
