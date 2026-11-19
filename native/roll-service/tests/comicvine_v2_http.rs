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
use comicpile_roll_service::outbound::RecordingFakeOutbound;
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
    let url = comicpile_roll_service::test_support::database_url().await;
    let state = Arc::new(test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-roll-routes-secret".into()),
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .unwrap(),
    ));
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
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
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
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Race").await;
    let i = issue(&conn, t, "1", 1).await;
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
