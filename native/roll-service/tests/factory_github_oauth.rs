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
            signed_session(&OWNER_ID.to_string(), seconds().saturating_sub(1)).as_str(),
            PAGES_ORIGIN,
            StatusCode::UNAUTHORIZED,
        ),
        (
            signed_session("77", seconds() + 300).as_str(),
            PAGES_ORIGIN,
            StatusCode::FORBIDDEN,
        ),
        (
            signed_session(&OWNER_ID.to_string(), seconds() + 1201).as_str(),
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
            signed_session(&OWNER_ID.to_string(), seconds().saturating_sub(1)).as_str(),
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
        Bytes::from_static(br#"{"id":1234}"#),
    );
    let accepted = send(&state, dispatch(&session_token, PAGES_ORIGIN, "doctor_fix")).await;
    assert_eq!(accepted.status(), StatusCode::ACCEPTED);
    let payload: Value =
        serde_json::from_slice(&to_bytes(accepted.into_body(), 4096).await.unwrap()).unwrap();
    assert_eq!(payload["result"], "submitted");
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
