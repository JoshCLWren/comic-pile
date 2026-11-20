#![allow(clippy::unwrap_used, clippy::expect_used)]
//! PostgreSQL-backed HTTP regressions for the native `/api/v2/comicvine/*`
//! operations (#4835). Every provider call goes through the recording fake
//! outbound client; nothing here opens a socket. Requires
//! `RUST_ROLL_TEST_DATABASE_URL` (a disposable local database) and hard-fails
//! without it.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use bytes::Bytes;
use comicpile_roll_service::outbound::{
    OutboundError, OutboundFuture, OutboundHttp, OutboundRequest, OutboundResponse,
    RecordingFakeOutbound,
};
use comicpile_roll_service::{config::Config, router, test_support, AppState};
use serde_json::{json, Value};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use tower::ServiceExt;

static NEXT_TEST_CLIENT: AtomicUsize = AtomicUsize::new(1);

fn unique_suffix() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos()
}

async fn setup_user(
    prefix: &str,
) -> (
    Arc<AppState>,
    String,
    String,
    i32,
    tokio::sync::MutexGuard<'static, ()>,
) {
    setup_user_with(prefix, 2, None).await
}

async fn setup_user_with(
    prefix: &str,
    pool_size: usize,
    outbound: Option<Arc<dyn OutboundHttp>>,
) -> (
    Arc<AppState>,
    String,
    String,
    i32,
    tokio::sync::MutexGuard<'static, ()>,
) {
    let url = comicpile_roll_service::test_support::database_url().await;
    let mut app = test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-roll-routes-secret".into()),
            "RUST_ROLL_POOL_SIZE" => Some(pool_size.to_string()),
            _ => None,
        })
        .unwrap(),
    );
    if let Some(outbound) = outbound {
        app.outbound = outbound;
    }
    let state = Arc::new(app);
    let guard = comicpile_roll_service::test_support::reset_for_test(&state).await;
    let username = format!("{prefix}-{}-{}", std::process::id(), unique_suffix());
    let (token, csrf, user_id) = register_user(&state, &username).await;
    (state, token, csrf, user_id, guard)
}

async fn register_user(state: &Arc<AppState>, username: &str) -> (String, String, i32) {
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/auth/register")
                .header(
                    "x-forwarded-for",
                    format!(
                        "2001:db8::{:x}",
                        NEXT_TEST_CLIENT.fetch_add(1, Ordering::Relaxed)
                    ),
                )
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(
                    json!({
                        "username": username,
                        "email": format!("{username}@example.com"),
                        "password": "correct-horse-battery"
                    })
                    .to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let csrf = response
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .filter_map(|cookie| cookie.to_str().ok())
        .find_map(|cookie| cookie.strip_prefix("csrf_token="))
        .and_then(|cookie| cookie.split(';').next())
        .expect("csrf cookie")
        .to_owned();
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let token = body["access_token"].as_str().unwrap().to_owned();
    let user_id: i32 = state
        .pool
        .get()
        .await
        .unwrap()
        .query_one("SELECT id FROM users WHERE username = $1", &[&username])
        .await
        .unwrap()
        .get(0);
    (token, csrf, user_id)
}

async fn register_extra_user(state: &Arc<AppState>, prefix: &str) -> (String, String, i32) {
    let username = format!("{prefix}-{}-{}", std::process::id(), unique_suffix());
    register_user(state, &username).await
}

async fn send(state: &Arc<AppState>, request: Request<Body>) -> (StatusCode, Value) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 4 * 1024 * 1024)
        .await
        .unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

fn authed(method: &str, path: &str, token: &str, csrf: &str, body: Option<Value>) -> Request<Body> {
    let builder = Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"));
    if let Some(body) = body {
        builder
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(body.to_string()))
            .unwrap()
    } else {
        builder.body(Body::empty()).unwrap()
    }
}

type Conn = deadpool_postgres::Object;

fn fake(state: &Arc<AppState>) -> &RecordingFakeOutbound {
    state
        .outbound
        .as_any()
        .downcast_ref::<RecordingFakeOutbound>()
        .expect("test state uses the recording fake outbound client")
}

/// Queue one canned ComicVine envelope (`status_code: 1`) for the next call.
fn provider_ok(state: &Arc<AppState>, mut payload: Value) {
    payload["status_code"] = json!(1);
    payload["error"] = json!("OK");
    fake(state).push_ok(
        http::StatusCode::OK,
        http::HeaderMap::new(),
        Bytes::from(payload.to_string()),
    );
}

fn set_key(present: bool) {
    if present {
        std::env::set_var("COMICVINE_API_KEY", "TESTKEY123");
    } else {
        std::env::remove_var("COMICVINE_API_KEY");
    }
}

async fn thread(conn: &Conn, user_id: i32, title: &str) -> i32 {
    conn.query_one(
        "INSERT INTO threads (title, format, issues_remaining, total_issues, queue_position, \
         status, user_id) VALUES ($1, 'Comic', 1, 1, 1, 'active', $2) RETURNING id",
        &[&title, &user_id],
    )
    .await
    .unwrap()
    .get(0)
}

async fn issue(conn: &Conn, thread_id: i32, number: &str, position: i32) -> i32 {
    conn.query_one(
        "INSERT INTO issues (thread_id, issue_number, status, created_at, position) \
         VALUES ($1, $2, 'unread', NOW(), $3) RETURNING id",
        &[&thread_id, &number, &position],
    )
    .await
    .unwrap()
    .get(0)
}

fn call(method: &str, path: &str, token: &str, csrf: &str, body: Option<Value>) -> Request<Body> {
    authed(method, path, token, csrf, body)
}

#[tokio::test]
async fn every_operation_requires_authentication_and_csrf() {
    let (state, token, _csrf, _user_id, _guard) = setup_user("cvv2-auth").await;
    let ops: [(&str, &str); 14] = [
        ("GET", "/api/v2/comicvine/issues/1/identity"),
        ("DELETE", "/api/v2/comicvine/issues/1/identity"),
        ("POST", "/api/v2/comicvine/issues/1/identity:confirm"),
        ("POST", "/api/v2/comicvine/issues/1/identity:replace"),
        ("POST", "/api/v2/comicvine/issues/1/metadata:correct"),
        ("GET", "/api/v2/comicvine/issues/1/metadata:corrections"),
        ("POST", "/api/v2/comicvine/issues/1/metadata:refresh"),
        ("POST", "/api/v2/comicvine/issues/1/metadata:revert"),
        ("POST", "/api/v2/comicvine/issues:import"),
        ("GET", "/api/v2/comicvine/resolve?input=x"),
        ("GET", "/api/v2/comicvine/search/series?q=x"),
        ("GET", "/api/v2/comicvine/series/1/issues"),
        ("POST", "/api/v2/comicvine/series:import"),
        ("GET", "/api/v2/comicvine/series/1/import-status"),
    ];
    for (method, path) in ops {
        // Unauthenticated, with a matching CSRF pair so only auth can reject.
        let mut builder = Request::builder()
            .method(method)
            .uri(path)
            .header("x-csrf-token", "pair")
            .header(header::COOKIE, "csrf_token=pair");
        builder = builder.header(header::CONTENT_TYPE, "application/json");
        let (status, body) = send(&state, builder.body(Body::from("{}")).unwrap()).await;
        assert_eq!(
            status,
            StatusCode::UNAUTHORIZED,
            "{method} {path}: {body:?}"
        );
        if method != "GET" {
            // Authenticated but missing the CSRF pair: rejected as 403.
            let (status, body) = send(
                &state,
                Request::builder()
                    .method(method)
                    .uri(path)
                    .header(header::AUTHORIZATION, format!("Bearer {token}"))
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from("{}"))
                    .unwrap(),
            )
            .await;
            assert_eq!(status, StatusCode::FORBIDDEN, "{method} {path}: {body:?}");
        }
    }
}

#[tokio::test]
async fn identity_confirm_replace_remove_flow_matches_python() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-identity").await;
    set_key(false);
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Saga").await;
    let i = issue(&conn, t, "1", 1).await;
    let base = format!("/api/v2/comicvine/issues/{i}");

    // Empty state.
    let (status, body) = send(
        &state,
        call("GET", &format!("{base}/identity"), &token, &csrf, None),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["issue_id"], i);
    assert_eq!(body["thread_id"], t);
    assert_eq!(body["thread_title"], "Saga");
    assert_eq!(body["has_confirmed_identity"], false);
    assert_eq!(body["comicvine_issue_id"], Value::Null);
    assert_eq!(body["confirmed_mappings"], json!([]));
    assert_eq!(body["has_unresolved"], false);

    // Removing before confirming: 400 with the Python message.
    let (status, body) = send(
        &state,
        call("DELETE", &format!("{base}/identity"), &token, &csrf, None),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(
        body["detail"],
        format!("No confirmed ComicVine identity mapping found for issue {i}")
    );

    // Confirm.
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/identity:confirm"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 1111})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["has_confirmed_identity"], true);
    assert_eq!(body["comicvine_issue_id"], "1111");
    let mapping = &body["confirmed_mappings"][0];
    assert_eq!(mapping["provider"], "comicvine");
    assert_eq!(mapping["comicvine_id"], "1111");
    assert_eq!(mapping["status"], "confirmed");
    assert_eq!(mapping["confidence"], 1.0);
    assert_eq!(mapping["evidence_source"], "user_confirmed");
    assert!(mapping["created_at"].as_str().unwrap().ends_with('Z'));
    // Confirming queues exactly one deep-metadata refresh for the identity.
    let queued: i64 = conn
        .query_one(
            "SELECT count(*) FROM comicvine_metadata_refresh_requests WHERE state = 'pending'",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(queued, 1);
    // Re-confirming the same id is idempotent and does not queue a second job.
    let (status, _) = send(
        &state,
        call(
            "POST",
            &format!("{base}/identity:confirm"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 1111})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let queued: i64 = conn
        .query_one(
            "SELECT count(*) FROM comicvine_metadata_refresh_requests",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(queued, 1);

    // A different confirmed id on the same issue is a 400, not a silent swap.
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/identity:confirm"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 2222})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(
        body["detail"],
        "issue already has a confirmed comicvine identity"
    );

    // Replace rejects the old mapping (with the reason) and confirms the new one.
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/identity:replace"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 2222, "reason": "wrong volume"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["comicvine_issue_id"], "2222");
    assert_eq!(body["confirmed_mappings"].as_array().unwrap().len(), 1);
    let rejected: (String, Option<String>) = {
        let row = conn
            .query_one(
                "SELECT m.status, m.rejection_reason FROM issue_external_identity_mappings m \
                 JOIN external_identities e ON e.id = m.external_identity_id \
                 WHERE m.issue_id = $1 AND e.external_id = '1111'",
                &[&i],
            )
            .await
            .unwrap();
        (row.get(0), row.get(1))
    };
    assert_eq!(
        rejected,
        ("rejected".to_owned(), Some("wrong volume".to_owned()))
    );

    // Refresh reports the confirmed id.
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/metadata:refresh"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body,
        json!({"issue_id": i, "refreshed": true, "comicvine_issue_id": "2222"})
    );

    // Remove: mapping becomes unresolved with evidence and confidence cleared.
    let (status, body) = send(
        &state,
        call("DELETE", &format!("{base}/identity"), &token, &csrf, None),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["has_confirmed_identity"], false);
    assert_eq!(body["has_unresolved"], true);
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/metadata:refresh"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body,
        json!({"issue_id": i, "refreshed": false, "comicvine_issue_id": null})
    );

    // Replace with the default reason when none is supplied.
    let (status, _) = send(
        &state,
        call(
            "POST",
            &format!("{base}/identity:confirm"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 3333})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let (status, _) = send(
        &state,
        call(
            "POST",
            &format!("{base}/identity:replace"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 4444})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let reason: Option<String> = conn
        .query_one(
            "SELECT m.rejection_reason FROM issue_external_identity_mappings m \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE m.issue_id = $1 AND e.external_id = '3333'",
            &[&i],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(reason.as_deref(), Some("replaced by user"));
}

#[tokio::test]
async fn identity_mutations_are_owner_scoped() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-owner").await;
    set_key(false);
    let (other_token, other_csrf, other_id) = register_extra_user(&state, "cvv2-other").await;
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Mine").await;
    let i = issue(&conn, t, "1", 1).await;
    let base = format!("/api/v2/comicvine/issues/{i}");
    let _ = other_id;
    let missing = format!("Issue {i} not found");
    for (method, path, body) in [
        ("GET", format!("{base}/identity"), None),
        ("DELETE", format!("{base}/identity"), None),
        (
            "POST",
            format!("{base}/identity:confirm"),
            Some(json!({"comicvine_issue_id": 5})),
        ),
        (
            "POST",
            format!("{base}/identity:replace"),
            Some(json!({"comicvine_issue_id": 5})),
        ),
        ("POST", format!("{base}/metadata:refresh"), None),
        (
            "POST",
            format!("{base}/metadata:correct"),
            Some(json!({"field_name": "name", "canonical_value": "x"})),
        ),
        ("GET", format!("{base}/metadata:corrections"), None),
        (
            "POST",
            format!("{base}/metadata:revert"),
            Some(json!({"correction_id": 1})),
        ),
    ] {
        let (status, resp) =
            send(&state, call(method, &path, &other_token, &other_csrf, body)).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{method} {path}: {resp:?}");
        assert_eq!(resp["detail"], missing, "{method} {path}");
    }
    // Nothing was written for the non-owner.
    let count: i64 = conn
        .query_one("SELECT count(*) FROM issue_external_identity_mappings", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(count, 0);
    let _ = (token, csrf);
}

#[tokio::test]
async fn concurrent_confirms_leave_exactly_one_confirmed_identity() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-race").await;
    set_key(false);
    // Scope the seeding connection: a checked-out connection would otherwise
    // starve the two-connection pool and serialize the "concurrent" requests.
    let (t, i) = {
        let conn = state.pool.get().await.unwrap();
        let t = thread(&conn, user_id, "Race").await;
        let i = issue(&conn, t, "1", 1).await;
        (t, i)
    };
    let _ = t;
    let path = format!("/api/v2/comicvine/issues/{i}/identity:confirm");
    let mut handles = Vec::new();
    for cv in [7001, 7002, 7003, 7004] {
        let state = state.clone();
        let (token, csrf, path) = (token.clone(), csrf.clone(), path.clone());
        handles.push(tokio::spawn(async move {
            send(
                &state,
                call(
                    "POST",
                    &path,
                    &token,
                    &csrf,
                    Some(json!({"comicvine_issue_id": cv})),
                ),
            )
            .await
        }));
    }
    let mut ok = 0;
    for handle in handles {
        let (status, body) = handle.await.unwrap();
        match status {
            StatusCode::OK => ok += 1,
            StatusCode::BAD_REQUEST => {
                assert_eq!(
                    body["detail"],
                    "issue already has a confirmed comicvine identity"
                )
            }
            other => panic!("unexpected {other}: {body:?}"),
        }
    }
    assert_eq!(ok, 1, "exactly one concurrent confirm may win");
    let conn = state.pool.get().await.unwrap();
    let confirmed: i64 = conn
        .query_one(
            "SELECT count(*) FROM issue_external_identity_mappings WHERE issue_id = $1 AND status = 'confirmed'",
            &[&i],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(confirmed, 1);
}

#[tokio::test]
async fn metadata_corrections_apply_list_revert() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-corr").await;
    set_key(false);
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Corr").await;
    let i = issue(&conn, t, "1", 1).await;
    let identity: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, \
             created_at, updated_at) VALUES ('comicvine', 'issue', '9001', $1, NOW(), NOW()) RETURNING id",
            &[&json!({"name": "Provider Name"})],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, \
         created_at, updated_at, evidence_json) VALUES ($1, $2, 'confirmed', NOW(), NOW(), '{}'::json)",
        &[&i, &identity],
    )
    .await
    .unwrap();
    let base = format!("/api/v2/comicvine/issues/{i}");

    let (status, body) = send(
        &state,
        call(
            "GET",
            &format!("{base}/metadata:corrections"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, json!({"issue_id": i, "corrections": []}));

    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/metadata:correct"),
            &token,
            &csrf,
            Some(json!({"field_name": "name", "canonical_value": "My Name", "reason": "typo"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let correction = &body["corrections"][0];
    assert_eq!(correction["field_name"], "name");
    assert_eq!(correction["provider_value"], "Provider Name");
    assert_eq!(correction["canonical_value"], "My Name");
    assert_eq!(correction["provenance"], "user_correction");
    assert_eq!(correction["created_by"], user_id);
    assert!(correction["created_at"].as_str().unwrap().ends_with('Z'));
    let cid = correction["id"].as_i64().unwrap();

    // A field the provider never supplied stores no provider value.
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/metadata:correct"),
            &token,
            &csrf,
            Some(json!({"field_name": "cover_date", "canonical_value": "2020-01-01"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["corrections"][1]["provider_value"], Value::Null);

    // Revert is soft; a second revert of the same id is a 400.
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/metadata:revert"),
            &token,
            &csrf,
            Some(json!({"correction_id": cid})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["corrections"].as_array().unwrap().len(), 1);
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/metadata:revert"),
            &token,
            &csrf,
            Some(json!({"correction_id": cid})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["detail"], format!("Correction {cid} not found"));
}

#[tokio::test]
async fn import_issue_creates_thread_identity_and_reading_order_slot() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-impissue").await;
    set_key(false);
    let (other_token, other_csrf, _) = register_extra_user(&state, "cvv2-impother").await;
    let conn = state.pool.get().await.unwrap();
    let order: i32 = conn
        .query_one(
            "INSERT INTO reading_orders (user_id, name) VALUES ($1, 'Arc') RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    let a = thread(&conn, user_id, "A").await;
    let b = thread(&conn, user_id, "B").await;
    for (thread_id, pos) in [(a, 1), (b, 2)] {
        conn.execute(
            "INSERT INTO reading_order_items (reading_order_id, thread_id, position) VALUES ($1, $2, $3)",
            &[&order, &thread_id, &pos],
        )
        .await
        .unwrap();
    }

    let (status, body) = send(
        &state,
        call(
            "POST",
            "/api/v2/comicvine/issues:import",
            &token,
            &csrf,
            Some(json!({
                "title": "  Annual Special ", "comicvine_issue_id": 555, "issue_number": "7",
                "reading_order_id": order, "anchor_before_thread_id": a, "anchor_after_thread_id": b
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    let new_thread = body["thread_id"].as_i64().unwrap() as i32;
    assert_eq!(body["reading_order_id"], order);
    assert_eq!(body["position"], 2);
    assert_eq!(body["total_items"], 3);
    let row = conn
        .query_one(
            "SELECT title, total_issues, issues_remaining, status FROM threads WHERE id = $1",
            &[&new_thread],
        )
        .await
        .unwrap();
    assert_eq!(row.get::<_, String>(0), "Annual Special");
    assert_eq!(
        (row.get::<_, Option<i32>>(1), row.get::<_, Option<i32>>(2)),
        (Some(1), Some(1))
    );
    let positions: Vec<(i32, i32)> = conn
        .query("SELECT thread_id, position FROM reading_order_items WHERE reading_order_id = $1 ORDER BY position", &[&order])
        .await
        .unwrap()
        .iter()
        .map(|r| (r.get(0), r.get(1)))
        .collect();
    assert_eq!(positions, vec![(a, 1), (new_thread, 2), (b, 3)]);
    let mapped: i64 = conn
        .query_one(
            "SELECT count(*) FROM issue_external_identity_mappings m JOIN issues i ON i.id = m.issue_id \
             WHERE i.thread_id = $1 AND m.status = 'confirmed'",
            &[&new_thread],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(mapped, 1);

    // Duplicate physical issue: 409 with the structured Python body.
    let (status, body) = send(
        &state,
        call(
            "POST",
            "/api/v2/comicvine/issues:import",
            &token,
            &csrf,
            Some(json!({"title": "Again", "comicvine_issue_id": 555})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT);
    let existing = body["detail"]["existing_issue_id"].as_i64().unwrap();
    assert_eq!(body["detail"]["code"], "duplicate_physical_issue");
    assert_eq!(body["detail"]["comicvine_issue_id"], 555);
    assert_eq!(
        body["detail"]["message"],
        format!("ComicVine issue 555 already exists as issue {existing}")
    );

    // Another reader's copy never blocks, and a foreign reading order is a 404.
    let (status, _) = send(
        &state,
        call(
            "POST",
            "/api/v2/comicvine/issues:import",
            &other_token,
            &other_csrf,
            Some(json!({"title": "Theirs", "comicvine_issue_id": 555})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED);
    let (status, body) = send(
        &state,
        call(
            "POST",
            "/api/v2/comicvine/issues:import",
            &other_token,
            &other_csrf,
            Some(json!({"title": "X", "comicvine_issue_id": 556, "reading_order_id": order})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"], format!("Reading order {order} not found"));
}

fn roster_row(id: i64, number: &str, volume: i64) -> Value {
    json!({"id": id, "issue_number": number, "name": format!("Issue {number}"),
           "site_detail_url": format!("https://comicvine.gamespot.com/issue/4000-{id}/"),
           "volume": {"id": volume, "name": "Volume"}})
}

#[tokio::test]
async fn import_series_adopts_roster_and_reuses_on_retry() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-series").await;
    set_key(true);
    let conn = state.pool.get().await.unwrap();

    provider_ok(
        &state,
        json!({"results": {"id": 4242, "name": "The Series"}}),
    );
    provider_ok(
        &state,
        json!({"number_of_total_results": 3, "results": [
        roster_row(1001, "1", 4242), roster_row(1002, "2", 4242), roster_row(1003, "3", 4242)]}),
    );
    let (status, body) = send(
        &state,
        call(
            "POST",
            "/api/v2/comicvine/series:import",
            &token,
            &csrf,
            Some(json!({"comicvine_volume_id": 4242, "already_read_count": 1})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    assert_eq!(body["series_name"], "The Series");
    assert_eq!(body["thread_created"], true);
    assert_eq!(body["total_issues_in_series"], 3);
    assert_eq!(body["issues_adopted"], 3);
    assert_eq!(body["issues_skipped"], 0);
    assert_eq!(body["issues_conflict"], 0);
    let first = &body["issue_results"][0];
    assert_eq!(first["outcome"], "created");
    assert_eq!(first["hydration"], "not_attempted");
    assert_eq!(first["issue_number"], "1");
    let thread_id = body["thread_id"].as_i64().unwrap() as i32;
    let row = conn
        .query_one(
            "SELECT total_issues, issues_remaining, reading_progress, status, next_unread_issue_id \
             FROM threads WHERE id = $1",
            &[&thread_id],
        )
        .await
        .unwrap();
    assert_eq!(row.get::<_, Option<i32>>(0), Some(3));
    assert_eq!(row.get::<_, Option<i32>>(1), Some(2));
    assert_eq!(
        row.get::<_, Option<String>>(2).as_deref(),
        Some("in_progress")
    );
    assert_eq!(row.get::<_, String>(3), "active");
    let statuses: Vec<String> = conn
        .query(
            "SELECT status FROM issues WHERE thread_id = $1 ORDER BY position",
            &[&thread_id],
        )
        .await
        .unwrap()
        .iter()
        .map(|r| r.get(0))
        .collect();
    assert_eq!(statuses, ["read", "unread", "unread"]);
    let events: i64 = conn
        .query_one(
            "SELECT count(*) FROM events WHERE type = 'issues_created' AND thread_id = $1",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(events, 3);
    // Provider calls were made with the shared credential against ComicVine only.
    assert!(fake(&state)
        .calls()
        .iter()
        .all(|c| c.host == "comicvine.gamespot.com"));

    // Import-status now reports the thread.
    let (status, body) = send(
        &state,
        call(
            "GET",
            "/api/v2/comicvine/series/4242/import-status",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["imported"], true);
    assert_eq!(body["thread_id"], thread_id);
    assert_eq!(body["issue_count"], 3);

    // Retry reuses the thread and every issue; a new roster entry is adopted.
    fake(&state).clear();
    provider_ok(
        &state,
        json!({"results": {"id": 4242, "name": "The Series"}}),
    );
    provider_ok(
        &state,
        json!({"number_of_total_results": 4, "results": [
        roster_row(1001, "1", 4242), roster_row(1002, "2", 4242), roster_row(1003, "3", 4242), roster_row(1004, "4", 4242)]}),
    );
    let (status, body) = send(
        &state,
        call(
            "POST",
            "/api/v2/comicvine/series:import",
            &token,
            &csrf,
            Some(json!({"comicvine_volume_id": 4242})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    assert_eq!(body["thread_created"], false);
    assert_eq!(body["thread_id"], thread_id);
    assert_eq!(body["issues_adopted"], 1);
    assert_eq!(body["issues_skipped"], 3);
    let threads: i64 = conn
        .query_one(
            "SELECT count(*) FROM threads WHERE user_id = $1",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(threads, 1);

    // A ComicVine issue already confirmed on another thread is a conflict, never moved.
    let other = thread(&conn, user_id, "Elsewhere").await;
    let elsewhere = issue(&conn, other, "1", 1).await;
    let (status, _) = send(
        &state,
        call(
            "POST",
            &format!("/api/v2/comicvine/issues/{elsewhere}/identity:confirm"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 2001})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    fake(&state).clear();
    provider_ok(&state, json!({"results": {"id": 5151, "name": "Second"}}));
    provider_ok(
        &state,
        json!({"number_of_total_results": 1, "results": [roster_row(2001, "1", 5151)]}),
    );
    let (status, body) = send(
        &state,
        call(
            "POST",
            "/api/v2/comicvine/series:import",
            &token,
            &csrf,
            Some(json!({"comicvine_volume_id": 5151})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    assert_eq!(body["issues_conflict"], 1);
    assert_eq!(body["issue_results"][0]["outcome"], "conflict");
    assert_eq!(body["issue_results"][0]["issue_id"], elsewhere);
    assert_eq!(
        body["issue_results"][0]["conflict_detail"],
        format!("ComicVine issue 2001 is already confirmed on issue {elsewhere} of thread {other}")
    );
}

#[tokio::test]
async fn import_series_error_contract_and_reading_order() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-serr").await;
    let conn = state.pool.get().await.unwrap();
    let path = "/api/v2/comicvine/series:import";

    set_key(false);
    let (status, body) = send(
        &state,
        call(
            "POST",
            path,
            &token,
            &csrf,
            Some(json!({"comicvine_volume_id": 1})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(
        body["detail"],
        json!({"code": "provider_unavailable", "message": "ComicVine is not configured on this server"})
    );

    set_key(true);
    // Unreachable provider (no canned response) -> 502 provider_failure.
    fake(&state).clear();
    let (status, body) = send(
        &state,
        call(
            "POST",
            path,
            &token,
            &csrf,
            Some(json!({"comicvine_volume_id": 1})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_GATEWAY);
    assert_eq!(body["detail"]["code"], "provider_failure");
    assert_eq!(
        body["detail"]["message"],
        "Failed to fetch ComicVine series: ComicVineError"
    );

    provider_ok(&state, json!({"results": {"id": 1, "name": "  "}}));
    let (status, body) = send(
        &state,
        call(
            "POST",
            path,
            &token,
            &csrf,
            Some(json!({"comicvine_volume_id": 1})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_GATEWAY);
    assert_eq!(
        body["detail"],
        json!({"code": "provider_failure", "message": "ComicVine series has no name"})
    );

    provider_ok(&state, json!({"results": {"id": 1, "name": "Empty"}}));
    provider_ok(&state, json!({"number_of_total_results": 0, "results": []}));
    let (status, body) = send(
        &state,
        call(
            "POST",
            path,
            &token,
            &csrf,
            Some(json!({"comicvine_volume_id": 1})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(
        body["detail"],
        json!({"code": "no_issues", "message": "ComicVine series has no issues"})
    );

    provider_ok(&state, json!({"results": {"id": 1, "name": "Two"}}));
    provider_ok(
        &state,
        json!({"number_of_total_results": 2, "results": [roster_row(11, "1", 1), roster_row(12, "2", 1)]}),
    );
    let (status, body) = send(
        &state,
        call(
            "POST",
            path,
            &token,
            &csrf,
            Some(json!({"comicvine_volume_id": 1, "already_read_count": 3})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["detail"]["code"], "invalid_already_read_count");
    assert_eq!(
        body["detail"]["message"],
        "already_read_count cannot exceed the series issue count (2)"
    );

    provider_ok(&state, json!({"results": {"id": 1, "name": "Two"}}));
    provider_ok(
        &state,
        json!({"number_of_total_results": 2, "results": [roster_row(11, "1", 1), roster_row(12, "2", 1)]}),
    );
    let (status, body) = send(
        &state,
        call(
            "POST",
            path,
            &token,
            &csrf,
            Some(json!({"comicvine_volume_id": 1, "reading_order_id": 99999})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"], "Reading order 99999 not found");
    let none: i64 = conn
        .query_one(
            "SELECT count(*) FROM threads WHERE user_id = $1",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(none, 0, "failed imports must not leave a thread behind");

    // Reading-order placement with anchors.
    let order: i32 = conn
        .query_one(
            "INSERT INTO reading_orders (user_id, name) VALUES ($1, 'O') RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    let a = thread(&conn, user_id, "A").await;
    conn.execute("INSERT INTO reading_order_items (reading_order_id, thread_id, position) VALUES ($1, $2, 1)", &[&order, &a])
        .await
        .unwrap();
    provider_ok(&state, json!({"results": {"id": 1, "name": "Two"}}));
    provider_ok(
        &state,
        json!({"number_of_total_results": 2, "results": [roster_row(11, "1", 1), roster_row(12, "2", 1)]}),
    );
    let (status, body) = send(
        &state,
        call("POST", path, &token, &csrf, Some(json!({"comicvine_volume_id": 1, "reading_order_id": order, "anchor_before_thread_id": a}))),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    assert_eq!(
        (body["position"].as_i64(), body["total_items"].as_i64()),
        (Some(2), Some(2))
    );
}

#[tokio::test]
async fn import_series_orders_numbered_issues_naturally_and_marks_all_read() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-natural").await;
    set_key(true);
    let conn = state.pool.get().await.unwrap();
    provider_ok(&state, json!({"results": {"id": 77, "name": "Natural"}}));
    provider_ok(
        &state,
        json!({"number_of_total_results": 3, "results": [
        roster_row(31, "10", 77), roster_row(32, "2", 77), roster_row(33, "1", 77)]}),
    );
    let (status, body) = send(
        &state,
        call(
            "POST",
            "/api/v2/comicvine/series:import",
            &token,
            &csrf,
            Some(json!({"comicvine_volume_id": 77, "already_read_count": 3})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    let thread_id = body["thread_id"].as_i64().unwrap() as i32;
    let numbers: Vec<String> = conn
        .query(
            "SELECT issue_number FROM issues WHERE thread_id = $1 ORDER BY position",
            &[&thread_id],
        )
        .await
        .unwrap()
        .iter()
        .map(|r| r.get(0))
        .collect();
    assert_eq!(numbers, ["1", "2", "10"]);
    let row = conn
        .query_one("SELECT status, issues_remaining, reading_progress FROM threads WHERE id = $1 AND user_id = $2", &[&thread_id, &user_id])
        .await
        .unwrap();
    assert_eq!(row.get::<_, String>(0), "completed");
    assert_eq!(row.get::<_, Option<i32>>(1), Some(0));
    assert_eq!(
        row.get::<_, Option<String>>(2).as_deref(),
        Some("completed")
    );
}

#[tokio::test]
async fn search_resolve_and_series_issues_use_the_faked_provider() {
    let (state, token, csrf, _user_id, _guard) = setup_user("cvv2-reads").await;

    // No key configured: empty, successful responses (Python parity).
    set_key(false);
    let (status, body) = send(
        &state,
        call(
            "GET",
            "/api/v2/comicvine/search/series?q=saga&limit=5&offset=10",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body,
        json!({"query": "saga", "results": [], "total_available": 0, "offset": 10, "limit": 5, "has_more": false, "next_offset": null})
    );
    let (status, body) = send(
        &state,
        call(
            "GET",
            "/api/v2/comicvine/series/9/issues",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body,
        json!({"comicvine_volume_id": 9, "series_name": "Volume 9", "issues": []})
    );
    let (status, body) = send(&state, call("GET", "/api/v2/comicvine/resolve?input=https%3A%2F%2Fcomicvine.gamespot.com%2Fissue%2F4000-123%2F", &token, &csrf, None)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["kind"], "issue");
    assert_eq!(body["validation_error"], "ComicVine is not configured on this server, so pasted links cannot be resolved. Search by title instead.");

    set_key(true);
    // Search paging contract.
    provider_ok(
        &state,
        json!({"number_of_total_results": 25, "results": [
        {"id": 1, "name": "Saga", "publisher": {"name": "Image"}, "start_year": "2012", "count_of_issues": 54,
         "site_detail_url": "https://comicvine.gamespot.com/saga/4050-1/", "image": {"medium_url": "m.jpg", "small_url": "s.jpg"}},
        {"id": "bad", "name": "skipped"}]}),
    );
    let (status, body) = send(
        &state,
        call(
            "GET",
            "/api/v2/comicvine/search/series?q=saga%20the&limit=10&offset=0",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["total_available"], 25);
    assert_eq!(body["has_more"], true);
    assert_eq!(body["next_offset"], 1);
    assert_eq!(
        body["results"][0],
        json!({"comicvine_volume_id": 1, "name": "Saga", "publisher": "Image", "start_year": 2012,
        "issue_count": 54, "site_detail_url": "https://comicvine.gamespot.com/saga/4050-1/", "image_url": "m.jpg"})
    );
    let call_path = fake(&state).calls().last().unwrap().path.clone();
    assert!(
        call_path.contains("query=saga+the")
            && call_path.contains("resources=volume")
            && call_path.contains("page=1"),
        "{call_path}"
    );

    // Resolve: an issue URL, then an off-site URL, then free text.
    provider_ok(
        &state,
        json!({"results": {"id": 123, "name": "Pilot", "issue_number": "1", "volume": {"id": 9, "name": "Saga"},
        "cover_date": "2012-03-01", "image": {"small_url": "s.jpg"}, "site_detail_url": "https://comicvine.gamespot.com/x/4000-123/"}}),
    );
    let (status, body) = send(&state, call("GET", "/api/v2/comicvine/resolve?input=https%3A%2F%2Fcomicvine.gamespot.com%2Fissue%2F4000-123%2F", &token, &csrf, None)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["kind"], "issue");
    assert_eq!(body["issue"]["comicvine_issue_id"], 123);
    assert_eq!(body["issue"]["series_name"], "Saga");
    assert_eq!(body["issue"]["volume_id"], 9);
    assert_eq!(body["issue"]["image_url"], "s.jpg");
    let (status, body) = send(
        &state,
        call(
            "GET",
            "/api/v2/comicvine/resolve?input=https%3A%2F%2Fexample.com%2Fissue%2F4000-1",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["kind"], "search");
    assert!(body["validation_error"]
        .as_str()
        .unwrap()
        .starts_with("That doesn't look like a ComicVine issue or volume URL."));
    let (status, body) = send(
        &state,
        call(
            "GET",
            "/api/v2/comicvine/resolve?input=batman",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(
        (
            status,
            body["kind"].as_str(),
            body["validation_error"].is_null()
        ),
        (StatusCode::OK, Some("search"), true)
    );
    // Provider failure on a recognised link keeps 200 with the retry message.
    fake(&state).clear();
    let (status, body) = send(&state, call("GET", "/api/v2/comicvine/resolve?input=https%3A%2F%2Fcomicvine.gamespot.com%2Fissue%2F4000-5%2F", &token, &csrf, None)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["kind"], "issue");
    assert_eq!(body["validation_error"], "We couldn't resolve that ComicVine link right now. Check the link or search by title instead.");

    // Series issues: roster + volume name lookup.
    provider_ok(
        &state,
        json!({"number_of_total_results": 1, "results": [
        {"id": 5, "issue_number": "1", "name": "One", "cover_date": "2012-03-01", "image": {"small_url": "s.jpg"},
         "site_detail_url": "https://comicvine.gamespot.com/i/4000-5/", "volume": {"id": 9}}]}),
    );
    provider_ok(&state, json!({"results": {"id": 9, "name": "Saga"}}));
    let (status, body) = send(
        &state,
        call(
            "GET",
            "/api/v2/comicvine/series/9/issues",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["series_name"], "Saga");
    assert_eq!(body["issues"][0]["comicvine_issue_id"], 5);
    assert_eq!(body["issues"][0]["issue_number"], "1");
    assert_eq!(body["issues"][0]["image_url"], "s.jpg");
}

/// #5487: removing and re-adding an issue's ComicVine identity must never
/// touch the thread's confirmed series mapping or the series identity's
/// metadata (the source of the Queue row's volume label).
#[tokio::test]
async fn identity_removal_and_readd_leave_thread_series_metadata_untouched() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-5487").await;
    set_key(false);
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Superman").await;
    let i = issue(&conn, t, "4", 1).await;
    let metadata = json!({"volume": {"id": 4050, "name": "Superman (2018)"}, "publisher": {"name": "DC Comics"}, "start_year": 2023});
    let series_identity: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, \
             created_at, updated_at) VALUES ('comicvine', 'series', '4050', $1, NOW(), NOW()) RETURNING id",
            &[&metadata],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO thread_external_series_mappings (thread_id, external_identity_id, status, \
         confidence, created_at, updated_at) VALUES ($1, $2, 'confirmed', 1.0, NOW(), NOW())",
        &[&t, &series_identity],
    )
    .await
    .unwrap();
    let snapshot = |conn: Conn| async move {
        let row = conn
            .query_one(
                "SELECT m.status, m.confidence, e.metadata_json FROM thread_external_series_mappings m \
                 JOIN external_identities e ON e.id = m.external_identity_id WHERE m.thread_id = $1",
                &[&t],
            )
            .await
            .unwrap();
        (
            row.get::<_, String>(0),
            row.get::<_, Option<f64>>(1),
            row.get::<_, Value>(2),
        )
    };
    let before = snapshot(state.pool.get().await.unwrap()).await;
    let base = format!("/api/v2/comicvine/issues/{i}/identity");
    for step in 0..2 {
        let (status, _) = send(
            &state,
            call(
                "POST",
                &format!("{base}:confirm"),
                &token,
                &csrf,
                Some(json!({"comicvine_issue_id": 8800 + step})),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        let (status, _) = send(&state, call("DELETE", &base, &token, &csrf, None)).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(snapshot(state.pool.get().await.unwrap()).await, before);
    }
}

type Pending = tokio::task::JoinHandle<(StatusCode, Value)>;

/// Deterministic signal that `expected` requests are blocked on the reader's
/// queue advisory lock: poll `pg_locks` for ungranted waiters on that exact
/// key. No sleeps or deadlines. A writer that skips the queue lock never
/// becomes a waiter and instead runs to completion, which fails the test
/// immediately instead of hanging it.
async fn wait_for_queue_lock_waiters(
    tx: &deadpool_postgres::Transaction<'_>,
    user_id: i32,
    expected: i64,
    pending: &[&Pending],
) {
    loop {
        let waiting: i64 = tx
            .query_one(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted \
                 AND classid = 699001 AND objid = $1::int4::oid",
                &[&user_id],
            )
            .await
            .unwrap()
            .get(0);
        if waiting >= expected {
            return;
        }
        assert!(
            pending.iter().all(|handle| !handle.is_finished()),
            "a writer finished while the reader's queue lock was held: it never took the queue lock"
        );
        tokio::task::yield_now().await;
    }
}

async fn hold_queue_lock(
    conn: &mut deadpool_postgres::Object,
    user_id: i32,
) -> deadpool_postgres::Transaction<'_> {
    let tx = conn.transaction().await.unwrap();
    tx.execute(
        "SELECT pg_advisory_xact_lock($1, $2)",
        &[&699001_i32, &user_id],
    )
    .await
    .unwrap();
    tx
}

fn spawn_send(state: &Arc<AppState>, request: Request<Body>) -> Pending {
    let state = state.clone();
    tokio::spawn(async move { send(&state, request).await })
}

/// Holds the reader's queue advisory lock in one session and proves a request
/// is blocked on it BEFORE it takes any thread/issue row lock (lock order:
/// queue lock first, then row locks; #5398/#5419). While the request waits, a
/// second session must still be able to `FOR UPDATE NOWAIT` the issue row.
async fn assert_queue_lock_precedes_row_locks(
    state: &Arc<AppState>,
    user_id: i32,
    issue_id: i32,
    request: Request<Body>,
) -> (StatusCode, Value) {
    let mut holder = state.pool.get().await.unwrap();
    let tx = hold_queue_lock(&mut holder, user_id).await;
    let pending = spawn_send(state, request);
    wait_for_queue_lock_waiters(&tx, user_id, 1, &[&pending]).await;
    tx.query_one(
        "SELECT id FROM issues WHERE id = $1 FOR UPDATE NOWAIT",
        &[&issue_id],
    )
    .await
    .expect("writer took an issue row lock before the queue lock");
    tx.commit().await.unwrap();
    drop(holder);
    pending.await.unwrap()
}

#[tokio::test]
async fn identity_and_import_writers_take_the_queue_lock_before_row_locks() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-lockorder").await;
    set_key(false);
    let (t, i) = {
        let conn = state.pool.get().await.unwrap();
        let t = thread(&conn, user_id, "Locks").await;
        (t, issue(&conn, t, "1", 1).await)
    };
    let _ = t;
    let (status, body) = assert_queue_lock_precedes_row_locks(
        &state,
        user_id,
        i,
        call(
            "POST",
            &format!("/api/v2/comicvine/issues/{i}/identity:confirm"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 9101})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let (status, body) = assert_queue_lock_precedes_row_locks(
        &state,
        user_id,
        i,
        call(
            "POST",
            &format!("/api/v2/comicvine/issues/{i}/identity:replace"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 9102, "reason": "wrong"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    // import_issue creates a thread at the queue tail: the queue lock must
    // serialize the duplicate check and position assignment.
    let mut holder = state.pool.get().await.unwrap();
    let tx = hold_queue_lock(&mut holder, user_id).await;
    let pending = spawn_send(
        &state,
        call(
            "POST",
            "/api/v2/comicvine/issues:import",
            &token,
            &csrf,
            Some(json!({"title": "Imported", "comicvine_issue_id": 9103})),
        ),
    );
    wait_for_queue_lock_waiters(&tx, user_id, 1, &[&pending]).await;
    tx.commit().await.unwrap();
    drop(holder);
    let (status, body) = pending.await.unwrap();
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
}

#[tokio::test]
async fn confirmation_reopens_finished_refresh_jobs_instead_of_failing() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-refresh").await;
    set_key(false);
    for (n, finished) in ["failed", "completed", "no_credits"]
        .into_iter()
        .enumerate()
    {
        let cv = 9200 + n as i32;
        let conn = state.pool.get().await.unwrap();
        let t = thread(&conn, user_id, &format!("Refresh {finished}")).await;
        let i = issue(&conn, t, "1", 1).await;
        let identity: i32 = conn
            .query_one(
                "INSERT INTO external_identities (provider, entity_type, external_id, external_url, \
                 metadata_json, created_at, updated_at) \
                 VALUES ('comicvine', 'issue', $1, 'https://comicvine.gamespot.com/', '{}'::jsonb, now(), now()) \
                 RETURNING id",
                &[&cv.to_string()],
            )
            .await
            .unwrap()
            .get(0);
        conn.execute(
            "INSERT INTO comicvine_metadata_refresh_requests \
                (external_identity_id, state, attempts, next_attempt_at, last_error, completed_at, \
                 created_at, updated_at) \
             VALUES ($1, $2, 4, now() + interval '1 day', 'old', now(), now(), now())",
            &[&identity, &finished],
        )
        .await
        .unwrap();
        drop(conn);
        let (status, body) = send(
            &state,
            call(
                "POST",
                &format!("/api/v2/comicvine/issues/{i}/identity:confirm"),
                &token,
                &csrf,
                Some(json!({"comicvine_issue_id": cv})),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{finished}: {body:?}");
        assert_eq!(body["has_confirmed_identity"], true);
        let conn = state.pool.get().await.unwrap();
        let row = conn
            .query_one(
                "SELECT state, attempts, last_error, completed_at IS NULL \
                 FROM comicvine_metadata_refresh_requests WHERE external_identity_id = $1",
                &[&identity],
            )
            .await
            .unwrap();
        assert_eq!(row.get::<_, String>(0), "pending", "{finished}");
        assert_eq!(row.get::<_, i32>(1), 0);
        assert_eq!(row.get::<_, Option<String>>(2), None);
        assert!(row.get::<_, bool>(3));
    }
}

#[tokio::test]
async fn malformed_requests_use_the_production_validation_contract() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-validation").await;
    set_key(false);
    let i = {
        let conn = state.pool.get().await.unwrap();
        let t = thread(&conn, user_id, "Validation").await;
        issue(&conn, t, "1", 1).await
    };
    let expected = json!({"detail": "Validation failed"});
    for (method, path, body) in [
        (
            "POST",
            format!("/api/v2/comicvine/issues/{i}/identity:confirm"),
            Some(json!({})),
        ),
        (
            "POST",
            format!("/api/v2/comicvine/issues/{i}/identity:confirm"),
            Some(json!({"comicvine_issue_id": "x"})),
        ),
        (
            "POST",
            "/api/v2/comicvine/issues/abc/identity:confirm".to_owned(),
            Some(json!({"comicvine_issue_id": 1})),
        ),
        (
            "GET",
            "/api/v2/comicvine/issues/abc/identity".to_owned(),
            None,
        ),
        (
            "POST",
            "/api/v2/comicvine/issues:import".to_owned(),
            Some(json!({"title": "", "comicvine_issue_id": 1})),
        ),
        (
            "POST",
            "/api/v2/comicvine/series:import".to_owned(),
            Some(json!({"comicvine_volume_id": 0})),
        ),
        ("GET", "/api/v2/comicvine/search/series".to_owned(), None),
        (
            "GET",
            "/api/v2/comicvine/search/series?q=saga&limit=0".to_owned(),
            None,
        ),
        (
            "GET",
            "/api/v2/comicvine/search/series?q=saga&limit=51".to_owned(),
            None,
        ),
        (
            "GET",
            "/api/v2/comicvine/search/series?q=saga&offset=-1".to_owned(),
            None,
        ),
        (
            "GET",
            "/api/v2/comicvine/search/series?q=saga&limit=x".to_owned(),
            None,
        ),
        ("GET", "/api/v2/comicvine/resolve".to_owned(), None),
    ] {
        let (status, got) = send(&state, call(method, &path, &token, &csrf, body)).await;
        assert_eq!(
            status,
            StatusCode::UNPROCESSABLE_ENTITY,
            "{method} {path}: {got:?}"
        );
        assert_eq!(got, expected, "{method} {path}");
    }
}

#[tokio::test]
async fn search_series_uses_checked_arithmetic_at_the_offset_boundary() {
    let (state, token, csrf, _user_id, _guard) = setup_user("cvv2-offset-boundary").await;
    set_key(true);
    // i32::MAX with limit=1 must not overflow `offset / limit + 1` or the
    // `next_offset` computation (debug panic / release wrap).
    provider_ok(&state, json!({"number_of_total_results": 0, "results": []}));
    let (status, body) = send(
        &state,
        call(
            "GET",
            "/api/v2/comicvine/search/series?q=saga&limit=1&offset=2147483647",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["offset"], 2147483647);
    assert_eq!(body["limit"], 1);
    assert_eq!(body["has_more"], false);
    assert_eq!(body["next_offset"], Value::Null);
    assert_eq!(body["total_available"], 0);
    assert_eq!(body["results"].as_array().unwrap().len(), 0);
}

fn roster_page(volume: i32, first_id: i32, count: i32, total: Option<i32>) -> Value {
    let results: Vec<Value> = (first_id..first_id + count)
        .map(|id| json!({"id": id, "issue_number": id.to_string(), "volume": {"id": volume}}))
        .collect();
    let mut page = json!({ "results": results });
    if let Some(total) = total {
        page["number_of_total_results"] = json!(total);
    }
    page
}

#[tokio::test]
async fn rosters_beyond_one_thousand_rows_are_fetched_completely() {
    let (state, token, csrf, _user_id, _guard) = setup_user("cvv2-roster").await;
    set_key(true);
    // 1250 rows with a reported total: 13 pages, not 10.
    for page in 0..13 {
        let count = if page == 12 { 50 } else { 100 };
        provider_ok(&state, roster_page(77, page * 100 + 1, count, Some(1250)));
    }
    let (status, body) = send(
        &state,
        call(
            "GET",
            "/api/v2/comicvine/series/77/issues?series_name=Big",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["issues"].as_array().unwrap().len(), 1250);
    // Omitted total: walk forward until a short page.
    provider_ok(&state, roster_page(78, 1, 100, None));
    provider_ok(&state, roster_page(78, 101, 30, None));
    let (status, body) = send(
        &state,
        call(
            "GET",
            "/api/v2/comicvine/series/78/issues?series_name=NoTotal",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["issues"].as_array().unwrap().len(), 130);
}

#[tokio::test]
async fn browser_provider_calls_are_cached_and_honor_throttle_cooldowns() {
    let (state, token, csrf, _user_id, _guard) = setup_user("cvv2-limits").await;
    set_key(true);
    provider_ok(
        &state,
        json!({"number_of_total_results": 1, "results": [{"id": 1, "name": "Saga"}]}),
    );
    let search = "/api/v2/comicvine/search/series?q=saga&limit=10&offset=0";
    for _ in 0..3 {
        let (status, body) = send(&state, call("GET", search, &token, &csrf, None)).await;
        assert_eq!(status, StatusCode::OK, "{body:?}");
        assert_eq!(body["results"][0]["name"], "Saga");
    }
    assert_eq!(
        fake(&state).calls().len(),
        1,
        "repeat searches reuse the cached payload"
    );

    // A 429 starts a cooldown on the bucket: later distinct searches do not
    // reach ComicVine until the requested wait has passed.
    let mut headers = http::HeaderMap::new();
    headers.insert("retry-after", "120".parse().unwrap());
    fake(&state).push_ok(http::StatusCode::TOO_MANY_REQUESTS, headers, Bytes::new());
    let (status, _) = send(
        &state,
        call(
            "GET",
            "/api/v2/comicvine/search/series?q=one",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    let calls = fake(&state).calls().len();
    for q in ["two", "three"] {
        let (status, _) = send(
            &state,
            call(
                "GET",
                &format!("/api/v2/comicvine/search/series?q={q}"),
                &token,
                &csrf,
                None,
            ),
        )
        .await;
        assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    }
    assert_eq!(
        fake(&state).calls().len(),
        calls,
        "cooldown blocks provider calls"
    );
}

#[tokio::test]
async fn series_import_retry_into_a_reading_order_does_not_overcount_items() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-retrycount").await;
    set_key(true);
    let order: i32 = {
        let conn = state.pool.get().await.unwrap();
        let order: i32 = conn
            .query_one(
                "INSERT INTO reading_orders (user_id, name) VALUES ($1, 'O') RETURNING id",
                &[&user_id],
            )
            .await
            .unwrap()
            .get(0);
        for n in 0..2 {
            let t = thread(&conn, user_id, &format!("T{n}")).await;
            conn.execute(
                "INSERT INTO reading_order_items (reading_order_id, thread_id, position) VALUES ($1, $2, $3)",
                &[&order, &t, &(n + 1)],
            )
            .await
            .unwrap();
        }
        order
    };
    let mut totals = Vec::new();
    for _ in 0..2 {
        provider_ok(&state, json!({"results": {"id": 1, "name": "Two"}}));
        provider_ok(
            &state,
            json!({"number_of_total_results": 2, "results": [roster_row(11, "1", 1), roster_row(12, "2", 1)]}),
        );
        let (status, body) = send(
            &state,
            call(
                "POST",
                "/api/v2/comicvine/series:import",
                &token,
                &csrf,
                Some(json!({"comicvine_volume_id": 1, "reading_order_id": order})),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::CREATED, "{body:?}");
        totals.push(body["total_items"].as_i64().unwrap());
    }
    assert_eq!(totals, vec![3, 3], "retry moves the entry; it adds none");
}

/// Concurrent sibling writers: while one session holds the reader's queue
/// lock, `identity:confirm`, `issues:import` (twice) and the native
/// `DELETE /api/v2/issues/{id}` writer all wait on that same lock (none takes
/// a row lock first), then all complete once it is released: no deadlock, and
/// the two imports get distinct queue positions.
#[tokio::test]
async fn identity_and_import_writers_serialize_with_sibling_queue_writers() {
    let (state, token, csrf, user_id, _guard) = setup_user_with("cvv2-siblings", 8, None).await;
    set_key(false);
    let (confirm_issue, deleted_issue) = {
        let conn = state.pool.get().await.unwrap();
        let t = thread(&conn, user_id, "Siblings").await;
        (issue(&conn, t, "1", 1).await, issue(&conn, t, "2", 2).await)
    };
    let mut holder = state.pool.get().await.unwrap();
    let tx = hold_queue_lock(&mut holder, user_id).await;
    let confirm = spawn_send(
        &state,
        call(
            "POST",
            &format!("/api/v2/comicvine/issues/{confirm_issue}/identity:confirm"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 9301})),
        ),
    );
    let delete = spawn_send(
        &state,
        call(
            "DELETE",
            &format!("/api/v2/issues/{deleted_issue}"),
            &token,
            &csrf,
            None,
        ),
    );
    let imports: Vec<Pending> = [9302, 9303]
        .into_iter()
        .map(|cv| {
            spawn_send(
                &state,
                call(
                    "POST",
                    "/api/v2/comicvine/issues:import",
                    &token,
                    &csrf,
                    Some(json!({"title": format!("Sibling {cv}"), "comicvine_issue_id": cv})),
                ),
            )
        })
        .collect();
    wait_for_queue_lock_waiters(
        &tx,
        user_id,
        4,
        &[&confirm, &delete, &imports[0], &imports[1]],
    )
    .await;
    tx.commit().await.unwrap();
    drop(holder);
    let (status, body) = confirm.await.unwrap();
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["comicvine_issue_id"], "9301");
    let (status, body) = delete.await.unwrap();
    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");
    let mut threads = Vec::new();
    for import in imports {
        let (status, body) = import.await.unwrap();
        assert_eq!(status, StatusCode::CREATED, "{body:?}");
        threads.push(body["thread_id"].as_i64().unwrap() as i32);
    }
    let conn = state.pool.get().await.unwrap();
    let positions: Vec<i32> = conn
        .query(
            "SELECT queue_position FROM threads WHERE id = ANY($1) ORDER BY id",
            &[&threads],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| row.get(0))
        .collect();
    assert_eq!(positions.len(), 2);
    assert_ne!(
        positions[0], positions[1],
        "imports must not share a queue slot"
    );
}

/// Series import reuses an existing thread and, like every queue writer, takes
/// the reader's queue advisory lock before any thread/issue row lock: it
/// serializes alongside a sibling `issues:import` writer with no deadlock, and
/// the two threads get distinct queue positions (#5398/#5419).
#[tokio::test]
async fn series_import_serializes_with_sibling_queue_writer() {
    let (state, token, csrf, user_id, _guard) =
        setup_user_with("cvv2-series-sibling", 8, None).await;
    set_key(true);
    let volume_id = 77;
    let existing_thread_id = {
        let conn = state.pool.get().await.unwrap();
        let thread_id = thread(&conn, user_id, "Reused").await;
        let _issue = issue(&conn, thread_id, "1", 1).await;
        let external_volume_id = volume_id.to_string();
        let identity_id: i32 = conn
            .query_one(
                "INSERT INTO external_identities \
                 (provider, entity_type, external_id, external_url, metadata_json, created_at, updated_at) \
                 VALUES ('comicvine', 'series', $1, $2, '{}'::jsonb, now(), now()) RETURNING id",
                &[
                    &external_volume_id,
                    &format!("https://comicvine.gamespot.com/volume/4050-{volume_id}/"),
                ],
            )
            .await
            .unwrap()
            .get(0);
        conn.execute(
            "INSERT INTO thread_external_series_mappings \
             (thread_id, external_identity_id, status, evidence_source, confidence, created_at, updated_at) \
             VALUES ($1, $2, 'confirmed', 'comicvine_series_import', 1.0, now(), now())",
            &[&thread_id, &identity_id],
        )
        .await
        .unwrap();
        thread_id
    };
    provider_ok(
        &state,
        json!({"status_code": 1, "error": "OK", "results": {"id": volume_id, "name": "Shared"}}),
    );
    provider_ok(&state, roster_page(volume_id, 1, 3, Some(3)));
    let mut holder = state.pool.get().await.unwrap();
    let tx = hold_queue_lock(&mut holder, user_id).await;
    let series = spawn_send(
        &state,
        call(
            "POST",
            "/api/v2/comicvine/series:import",
            &token,
            &csrf,
            Some(json!({"comicvine_volume_id": volume_id})),
        ),
    );
    let sibling = spawn_send(
        &state,
        call(
            "POST",
            "/api/v2/comicvine/issues:import",
            &token,
            &csrf,
            Some(json!({"title": "Sibling", "comicvine_issue_id": 9302})),
        ),
    );
    wait_for_queue_lock_waiters(&tx, user_id, 2, &[&series, &sibling]).await;
    tx.commit().await.unwrap();
    drop(holder);
    let (status, body) = series.await.unwrap();
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    assert_eq!(
        body["thread_id"].as_i64().unwrap() as i32,
        existing_thread_id,
        "series import reuses the existing thread"
    );
    let (status, body) = sibling.await.unwrap();
    assert_eq!(status, StatusCode::CREATED, "{body:?}");
    let sibling_thread = body["thread_id"].as_i64().unwrap() as i32;
    assert_ne!(sibling_thread, existing_thread_id, "sibling import gets its own thread");
    let conn = state.pool.get().await.unwrap();
    let thread_ids = vec![existing_thread_id, sibling_thread];
    let positions: Vec<i32> = conn
        .query(
            "SELECT queue_position FROM threads WHERE id = ANY($1) ORDER BY id",
            &[&thread_ids],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| row.get(0))
        .collect();
    assert_eq!(positions.len(), 2);
    assert_ne!(positions[0], positions[1], "threads must not share a queue slot");
}

/// Order-independent fake ComicVine: `/issues` pages are synthesized from the
/// request's `offset`, so concurrent page fetches cannot receive each other's
/// payloads. Every response yields to the scheduler once before resolving,
/// and the fake records the peak number of page requests in flight.
struct PagedComicVine {
    volume: i32,
    total: usize,
    /// Offset whose page is returned without a `results` list.
    malformed_offset: Option<usize>,
    in_flight: Arc<AtomicUsize>,
    peak: AtomicUsize,
    offsets: std::sync::Mutex<Vec<usize>>,
}

impl PagedComicVine {
    fn new(volume: i32, total: usize, malformed_offset: Option<usize>) -> Arc<Self> {
        Arc::new(Self {
            volume,
            total,
            malformed_offset,
            in_flight: Arc::new(AtomicUsize::new(0)),
            peak: AtomicUsize::new(0),
            offsets: std::sync::Mutex::new(Vec::new()),
        })
    }

    fn payload(&self, path: &str) -> Value {
        if path.starts_with(&format!("/api/volume/4050-{}/", self.volume)) {
            return json!({"status_code": 1, "error": "OK", "results": {"id": self.volume, "name": "Paged"}});
        }
        let offset: usize = path
            .split('&')
            .find_map(|part| part.strip_prefix("offset="))
            .unwrap()
            .parse()
            .unwrap();
        self.offsets.lock().unwrap().push(offset);
        if Some(offset) == self.malformed_offset {
            return json!({"status_code": 1, "error": "OK", "number_of_total_results": self.total});
        }
        let end = (offset + 100).min(self.total);
        let results: Vec<Value> = (offset..end)
            .map(|n| json!({"id": 500_000 + n, "issue_number": (n + 1).to_string(), "volume": {"id": self.volume}}))
            .collect();
        json!({"status_code": 1, "error": "OK", "number_of_total_results": self.total, "results": results})
    }
}

impl OutboundHttp for PagedComicVine {
    fn send(&self, _host: &str, request: OutboundRequest) -> OutboundFuture {
        let body = self.payload(&request.path).to_string();
        // Only roster pages count toward the fan-out peak; the overlapping
        // volume read is a separate provider call.
        let page = request.path.starts_with("/api/issues/");
        if page {
            let now = self.in_flight.fetch_add(1, Ordering::SeqCst) + 1;
            self.peak.fetch_max(now, Ordering::SeqCst);
        }
        let counter = Arc::clone(&self.in_flight);
        Box::pin(async move {
            tokio::task::yield_now().await;
            if page {
                counter.fetch_sub(1, Ordering::SeqCst);
            }
            Ok::<_, OutboundError>(OutboundResponse {
                status: http::StatusCode::OK,
                headers: http::HeaderMap::new(),
                body: Body::from(body),
            })
        })
    }

    fn is_fake(&self) -> bool {
        true
    }

    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
}

async fn paged_state(
    prefix: &str,
    fake: &Arc<PagedComicVine>,
) -> (
    Arc<AppState>,
    String,
    String,
    i32,
    tokio::sync::MutexGuard<'static, ()>,
) {
    let outbound: Arc<dyn OutboundHttp> = fake.clone();
    setup_user_with(prefix, 2, Some(outbound)).await
}

/// Python `fetch_volume_issues` fetches the first page alone, then the
/// remaining fixed offsets four at a time. A 1,250-row roster is 13 pages: the
/// 12 remaining pages must overlap (peak 4 in flight, never more), and the
/// rows must come back complete and in offset order on every caller that
/// browses a roster (series issues, volume resolve, series import).
#[tokio::test]
async fn roster_pages_are_fetched_four_at_a_time_in_offset_order() {
    let paged = PagedComicVine::new(77, 1250, None);
    let (state, token, csrf, _user_id, _guard) = paged_state("cvv2-fanout", &paged).await;
    set_key(true);
    let (status, body) = send(
        &state,
        call(
            "GET",
            "/api/v2/comicvine/series/77/issues",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["series_name"], "Paged");
    let issues = body["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 1250);
    let numbers: Vec<String> = issues
        .iter()
        .map(|issue| issue["issue_number"].as_str().unwrap().to_owned())
        .collect();
    let expected: Vec<String> = (1..=1250).map(|n| n.to_string()).collect();
    assert_eq!(numbers, expected, "pages are assembled in offset order");
    assert_eq!(
        paged.peak.load(Ordering::SeqCst),
        4,
        "remaining pages are fetched concurrently, at most four at a time"
    );
    let mut offsets = paged.offsets.lock().unwrap().clone();
    assert_eq!(offsets[0], 0, "the first page is fetched alone first");
    offsets.sort_unstable();
    assert_eq!(offsets, (0..13).map(|page| page * 100).collect::<Vec<_>>());
}

/// Python `_fetch_volume_issue_page` raises on a page without a `results`
/// list. A malformed later page must fail the roster, never truncate it:
/// `series:import` answers the 502 provider failure and writes nothing, and
/// the browse route degrades to an empty roster (Python catches it there).
#[tokio::test]
async fn malformed_roster_pages_fail_instead_of_truncating_the_import() {
    let paged = PagedComicVine::new(88, 200, Some(100));
    let (state, token, csrf, user_id, _guard) = paged_state("cvv2-malformed", &paged).await;
    set_key(true);
    let (status, body) = send(
        &state,
        call(
            "POST",
            "/api/v2/comicvine/series:import",
            &token,
            &csrf,
            Some(json!({"comicvine_volume_id": 88})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_GATEWAY, "{body:?}");
    assert_eq!(
        body["detail"],
        json!({"code": "provider_failure", "message": "Failed to fetch series issues: ComicVineError"})
    );
    let conn = state.pool.get().await.unwrap();
    let threads: i64 = conn
        .query_one(
            "SELECT count(*) FROM threads WHERE user_id = $1",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(threads, 0, "a failed roster creates no thread or issues");
    drop(conn);
    let (status, body) = send(
        &state,
        call(
            "GET",
            "/api/v2/comicvine/series/88/issues?series_name=Named",
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["series_name"], "Named");
    assert_eq!(body["issues"], json!([]));
}

/// Golden values measured from the frozen Python request models (Pydantic v2
/// lax mode, `app/schemas/comicvine_resolution.py`): ints accept `"5"`, `5.0`
/// and `true`; confirm/replace ids have no `gt=0`; `field_name` and
/// `canonical_value` are unconstrained; `reason` is `max_length=500`; an
/// import `title` is bounded before `strip()`. Anything Python rejects is the
/// generic `{"detail": "Validation failed"}` 422.
#[tokio::test]
async fn request_coercion_matches_the_python_models() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-lax").await;
    set_key(false);
    let issues: Vec<i32> = {
        let conn = state.pool.get().await.unwrap();
        let t = thread(&conn, user_id, "Lax").await;
        let mut ids = Vec::new();
        for n in 1..=5 {
            ids.push(issue(&conn, t, &n.to_string(), n).await);
        }
        ids
    };
    let confirm = |issue: i32, body: Value| {
        call(
            "POST",
            &format!("/api/v2/comicvine/issues/{issue}/identity:confirm"),
            &token,
            &csrf,
            Some(body),
        )
    };
    for (issue, body, expected_id) in [
        (issues[0], json!({"comicvine_issue_id": "9401"}), "9401"),
        (issues[1], json!({"comicvine_issue_id": 9402.0}), "9402"),
        (issues[2], json!({"comicvine_issue_id": true}), "1"),
        (issues[3], json!({"comicvine_issue_id": 0}), "0"),
    ] {
        let (status, got) = send(&state, confirm(issue, body.clone())).await;
        assert_eq!(status, StatusCode::OK, "{body}: {got:?}");
        assert_eq!(got["comicvine_issue_id"], expected_id, "{body}");
    }
    let (status, got) = send(
        &state,
        call(
            "POST",
            &format!("/api/v2/comicvine/issues/{}.0/identity:replace", issues[3]),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": -7})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{got:?}");
    assert_eq!(got["comicvine_issue_id"], "-7");

    let (status, got) = send(
        &state,
        call(
            "POST",
            &format!("/api/v2/comicvine/issues/{}/metadata:correct", issues[4]),
            &token,
            &csrf,
            Some(json!({"field_name": "", "canonical_value": ""})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{got:?}");
    assert_eq!(got["corrections"][0]["field_name"], "");

    let (status, got) = send(
        &state,
        call(
            "POST",
            "/api/v2/comicvine/issues:import",
            &token,
            &csrf,
            Some(json!({"title": "   ", "comicvine_issue_id": "9405"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{got:?}");
    let conn = state.pool.get().await.unwrap();
    let title: String = conn
        .query_one(
            "SELECT title FROM threads WHERE id = $1",
            &[&(got["thread_id"].as_i64().unwrap() as i32)],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(title, "", "Python stores the stripped title");
    drop(conn);

    let expected = json!({"detail": "Validation failed"});
    for (path, body) in [
        (
            format!("/api/v2/comicvine/issues/{}/identity:confirm", issues[4]),
            json!({"comicvine_issue_id": 5.5}),
        ),
        (
            format!("/api/v2/comicvine/issues/{}/identity:confirm", issues[4]),
            json!({"comicvine_issue_id": null}),
        ),
        (
            format!("/api/v2/comicvine/issues/{}/metadata:correct", issues[4]),
            json!({"field_name": "a", "canonical_value": "b", "reason": "x".repeat(501)}),
        ),
        (
            "/api/v2/comicvine/issues:import".to_owned(),
            json!({"title": "x", "comicvine_issue_id": "abc"}),
        ),
    ] {
        let (status, got) = send(
            &state,
            call("POST", &path, &token, &csrf, Some(body.clone())),
        )
        .await;
        assert_eq!(
            status,
            StatusCode::UNPROCESSABLE_ENTITY,
            "{path} {body}: {got:?}"
        );
        assert_eq!(got, expected, "{path} {body}");
    }
}
