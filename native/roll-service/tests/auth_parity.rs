//! Shared synthetic claims and SQL isolation checks; requires a disposable PostgreSQL service.
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
    routing::get,
    Router,
};
use comicpile_roll_service::{auth::AuthenticatedUser, config::Config, db, AppState};
use jsonwebtoken::{encode, Algorithm, EncodingKey, Header};
use serde_json::{json, Value};
use std::{
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};
use tower::ServiceExt;

const SECRET: &str = "synthetic-auth-parity-key";
fn token(claims: &Value) -> String {
    encode(
        &Header::new(Algorithm::HS256),
        claims,
        &EncodingKey::from_secret(SECRET.as_bytes()),
    )
    .unwrap()
}
fn state(url: &str) -> Arc<AppState> {
    Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.into()),
                "RUST_ROLL_JWT_SECRET" => Some(SECRET.into()),
                "RUST_ROLL_POOL_SIZE" => Some("1".into()),
                "RUST_ROLL_POOL_TIMEOUT_MS" => Some("1000".into()),
                "RUST_ROLL_REQUEST_TIMEOUT_MS" => Some("2000".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    )
}
fn app(state: Arc<AppState>) -> Router {
    Router::new()
        .route(
            "/probe",
            get(|user: AuthenticatedUser| async move { axum::Json(json!({"id": user.id()})) }),
        )
        .with_state(state)
}
async fn response(app: Router, authorization: Option<&str>) -> (u16, Value, Option<String>) {
    let mut request = Request::builder().uri("/probe");
    if let Some(value) = authorization {
        request = request.header("authorization", value);
    }
    let response = app
        .oneshot(request.body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = response.status().as_u16();
    let challenge = response
        .headers()
        .get("www-authenticate")
        .map(|v| v.to_str().unwrap().into());
    let body =
        serde_json::from_slice(&to_bytes(response.into_body(), 4096).await.unwrap()).unwrap();
    (status, body, challenge)
}

#[tokio::test]
async fn shared_python_rust_auth_and_ownership_matrix() {
    let url = std::env::var("RUST_ROLL_TEST_DATABASE_URL")
        .expect("disposable RUST_ROLL_TEST_DATABASE_URL required; tests never silently skip");
    let state = state(&url);
    let connection = state.pool.get().await.unwrap();
    // Connection-local tables never touch application data, even on test failure.
    connection.batch_execute("CREATE TEMP TABLE users(id integer, username text, password_changed_at timestamptz); CREATE TEMP TABLE revoked_tokens(jti text); CREATE TEMP TABLE threads(id integer, user_id integer); CREATE TEMP TABLE sessions(id integer, user_id integer); INSERT INTO threads VALUES (1, 1), (2, 2); INSERT INTO sessions VALUES (1, 1), (2, 2);").await.unwrap();
    drop(connection);
    let cases: Vec<Value> = serde_json::from_str(include_str!(
        "../../../tests/fixtures/roll-v2/auth-matrix.json"
    ))
    .unwrap();
    for case in cases {
        let connection = state.pool.get().await.unwrap();
        connection
            .batch_execute("TRUNCATE users, revoked_tokens")
            .await
            .unwrap();
        if case["user_exists"].as_bool().unwrap() {
            let epoch = case["password_epoch"].as_i64().unwrap() as f64;
            connection
                .execute(
                    "INSERT INTO users VALUES (1, 'reader', to_timestamp($1))",
                    &[&epoch],
                )
                .await
                .unwrap();
        }
        if case["revoked"].as_bool().unwrap() {
            connection
                .execute("INSERT INTO revoked_tokens VALUES ('test-jti')", &[])
                .await
                .unwrap();
        }
        drop(connection);
        let mut claims = case["claims"].clone();
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        claims["exp"] = json!(if case["expired"] == true {
            now - 60
        } else {
            now + 3600
        });
        let encoded = token(&claims);
        let bearer = format!("Bearer {encoded}");
        let header = if case["missing"] == true {
            None
        } else if case["malformed"] == true {
            Some("Bearer broken")
        } else {
            Some(bearer.as_str())
        };
        let (status, body, challenge) = response(app(state.clone()), header).await;
        assert_eq!(
            status,
            case["status"].as_u64().unwrap() as u16,
            "{}",
            case["name"]
        );
        if status == 200 {
            assert_eq!(body, json!({"id": 1}));
            assert!(challenge.is_none());
        } else {
            assert_eq!(body, json!({"detail": case["detail"]}), "{}", case["name"]);
            assert_eq!(challenge.as_deref(), Some("Bearer"));
        }
    }
    let connection = state.pool.get().await.unwrap();
    connection
        .batch_execute(
            "TRUNCATE users, revoked_tokens; INSERT INTO users VALUES (1, 'reader', NULL)",
        )
        .await
        .unwrap();
    drop(connection);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let encoded = token(&json!({"sub":"reader","jti":"test-jti","type":"access","exp":now+3600}));
    let user = comicpile_roll_service::auth::authenticate(&state, &encoded)
        .await
        .ok()
        .unwrap();
    assert!(db::require_owned_thread(&state, user, 1).await.is_ok());
    assert!(db::require_owned_session(&state, user, 1).await.is_ok());
    for id in [2, 999] {
        assert_eq!(
            db::require_owned_thread(&state, user, id)
                .await
                .err()
                .unwrap()
                .0,
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            db::require_owned_session(&state, user, id)
                .await
                .err()
                .unwrap()
                .0,
            StatusCode::NOT_FOUND
        );
    }
    // Holding the sole connection exercises bounded pool exhaustion and subsequent recovery.
    let held = state.pool.get().await.unwrap();
    let (status, _, challenge) =
        response(app(state.clone()), Some(&format!("Bearer {encoded}"))).await;
    assert_eq!(status, 503);
    assert!(challenge.is_none());
    drop(held);
    assert!(comicpile_roll_service::auth::authenticate(&state, &encoded)
        .await
        .is_ok());
}

#[tokio::test]
async fn invalid_credentials_do_not_need_database_and_outages_are_not_401() {
    let state = state("postgresql://127.0.0.1:1/unreachable?connect_timeout=1");
    let (status, _, _) = response(app(state.clone()), Some("Bearer broken")).await;
    assert_eq!(status, 401);
    let encoded = token(&json!({"sub":"reader","jti":"test-jti","type":"access"}));
    let (status, body, challenge) = response(app(state), Some(&format!("Bearer {encoded}"))).await;
    assert_eq!(
        body,
        json!({"error": {"code":"database_unavailable", "message":"Database temporarily unavailable. Please retry.", "status":"SERVICE_UNAVAILABLE"}})
    );
    assert_eq!(status, 503);
    assert!(challenge.is_none());
}
