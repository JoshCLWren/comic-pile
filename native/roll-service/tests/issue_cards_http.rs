#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Handler-level HTTP regressions for native `POST /api/v2/issues/cards`.
//!
//! Ports the removed successful DB-backed parity coverage to a Rust integration
//! test against the canonical disposable PostgreSQL schema. Exercises auth,
//! owner scoping, request-order projection, confirmed mapping/cover behavior,
//! and request validation through the mounted router. Requires
//! `RUST_ROLL_TEST_DATABASE_URL` and hard-fails without it.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, AppState};
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
    let state = Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
                "RUST_ROLL_JWT_SECRET" => Some("synthetic-roll-routes-secret".into()),
                "RUST_ROLL_POOL_SIZE" => Some("2".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    );
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

async fn send(state: &Arc<AppState>, request: Request<Body>) -> (StatusCode, Value) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 2 * 1024 * 1024).await.unwrap();
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

#[tokio::test]
async fn authenticated_issue_cards_are_owner_scoped_and_bounded() {
    let (state, token, csrf, owner_id, _guard) = setup_user("cards").await;
    let conn = state.pool.get().await.unwrap();

    // Stranger must not leak into the owner's card projection.
    let stranger_id: i32 = conn
        .query_one(
            "INSERT INTO users (username, email, password_hash) VALUES ($1, $2, $3) RETURNING id",
            &[
                &format!("other-{}-{}", std::process::id(), unique_suffix()),
                &format!("other-{}@example.com", unique_suffix()),
                &"hash",
            ],
        )
        .await
        .unwrap()
        .get(0);

    let hellboy_id: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at, total_issues, reading_progress)
             VALUES ($1, $2, 'Comic', 2, 1, 'active', NOW(), 3, 'in_progress') RETURNING id",
            &[&owner_id, &"Hellboy in Hell"],
        )
        .await
        .unwrap()
        .get(0);
    let bprd_id: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at, total_issues, reading_progress)
             VALUES ($1, $2, 'Comic', 1, 2, 'active', NOW(), 1, 'in_progress') RETURNING id",
            &[&owner_id, &"B.P.R.D."],
        )
        .await
        .unwrap()
        .get(0);
    let foreign_thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at, total_issues, reading_progress)
             VALUES ($1, $2, 'Comic', 1, 1, 'active', NOW(), 1, 'in_progress') RETURNING id",
            &[&stranger_id, &"Private run"],
        )
        .await
        .unwrap()
        .get(0);

    let issue_one_id: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at)
             VALUES ($1, '1', 1, 'unread', NOW()) RETURNING id",
            &[&hellboy_id],
        )
        .await
        .unwrap()
        .get(0);
    let issue_two_id: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at)
             VALUES ($1, '2', 2, 'unread', NOW()) RETURNING id",
            &[&hellboy_id],
        )
        .await
        .unwrap()
        .get(0);
    let issue_ten_id: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, read_at, created_at)
             VALUES ($1, '10', 10, 'read', '2026-01-02T03:04:05.123456Z'::timestamptz, NOW()) RETURNING id",
            &[&hellboy_id],
        )
        .await
        .unwrap()
        .get(0);
    let issue_bprd_id: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at)
             VALUES ($1, '1', 1, 'unread', NOW()) RETURNING id",
            &[&bprd_id],
        )
        .await
        .unwrap()
        .get(0);
    let issue_foreign_id: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at)
             VALUES ($1, '1', 1, 'unread', NOW()) RETURNING id",
            &[&foreign_thread_id],
        )
        .await
        .unwrap()
        .get(0);

    conn.execute(
        "UPDATE threads SET next_unread_issue_id = $2 WHERE id = $1",
        &[&hellboy_id, &issue_one_id],
    )
    .await
    .unwrap();
    conn.execute(
        "UPDATE threads SET next_unread_issue_id = $2 WHERE id = $1",
        &[&bprd_id, &issue_bprd_id],
    )
    .await
    .unwrap();
    conn.execute(
        "UPDATE threads SET next_unread_issue_id = $2 WHERE id = $1",
        &[&foreign_thread_id, &issue_foreign_id],
    )
    .await
    .unwrap();

    let identity_ten: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at)
             VALUES ('comicvine', 'issue', '4000-42', $1, NOW(), NOW()) RETURNING id",
            &[&json!({
                "image": {
                    "medium_url": "https://comicvine.example/medium/4000-42.jpg",
                    "original_url": "https://comicvine.example/original/4000-42.jpg"
                }
            })],
        )
        .await
        .unwrap()
        .get(0);
    let identity_two: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at)
             VALUES ('comicvine', 'issue', '4000-43', $1, NOW(), NOW()) RETURNING id",
            &[&json!({
                "image": { "medium_url": "https://comicvine.example/medium/4000-43.jpg" }
            })],
        )
        .await
        .unwrap()
        .get(0);
    let identity_one: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at)
             VALUES ('comicvine', 'issue', '4000-44', $1, NOW(), NOW()) RETURNING id",
            &[&json!({
                "image": { "medium_url": "https://comicvine.example/medium/4000-44.jpg" }
            })],
        )
        .await
        .unwrap()
        .get(0);
    // Regression #4722: confirmed mappings may store only primary_image.
    let identity_bprd: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at)
             VALUES ('comicvine', 'issue', '4000-45', $1, NOW(), NOW()) RETURNING id",
            &[&json!({
                "primary_image": "https://comicvine.example/original/4000-45.jpg"
            })],
        )
        .await
        .unwrap()
        .get(0);
    let identity_foreign: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at)
             VALUES ('comicvine', 'issue', '4000-46', $1, NOW(), NOW()) RETURNING id",
            &[&json!({
                "image": { "medium_url": "https://comicvine.example/medium/4000-46.jpg" }
            })],
        )
        .await
        .unwrap()
        .get(0);

    conn.execute(
        "INSERT INTO issue_external_identity_mappings
            (issue_id, external_identity_id, status, confidence, evidence_json, created_at, updated_at)
         VALUES ($1, $2, 'confirmed', 0.9, '{}'::jsonb, NOW(), NOW())",
        &[&issue_ten_id, &identity_ten],
    )
    .await
    .unwrap();
    conn.execute(
        "INSERT INTO issue_external_identity_mappings
            (issue_id, external_identity_id, status, confidence, evidence_json, created_at, updated_at)
         VALUES ($1, $2, 'candidate', 0.7, '{}'::jsonb, NOW(), NOW())",
        &[&issue_two_id, &identity_two],
    )
    .await
    .unwrap();
    conn.execute(
        "INSERT INTO issue_external_identity_mappings
            (issue_id, external_identity_id, status, evidence_json, created_at, updated_at)
         VALUES ($1, $2, 'rejected', '{}'::jsonb, NOW(), NOW())",
        &[&issue_one_id, &identity_one],
    )
    .await
    .unwrap();
    conn.execute(
        "INSERT INTO issue_external_identity_mappings
            (issue_id, external_identity_id, status, confidence, evidence_json, created_at, updated_at)
         VALUES ($1, $2, 'confirmed', 0.8, '{}'::jsonb, NOW(), NOW())",
        &[&issue_bprd_id, &identity_bprd],
    )
    .await
    .unwrap();
    conn.execute(
        "INSERT INTO issue_external_identity_mappings
            (issue_id, external_identity_id, status, confidence, evidence_json, created_at, updated_at)
         VALUES ($1, $2, 'confirmed', 0.95, '{}'::jsonb, NOW(), NOW())",
        &[&issue_foreign_id, &identity_foreign],
    )
    .await
    .unwrap();

    // Latest rate event provides the effective saved rating for the read issue.
    conn.execute(
        "INSERT INTO events (type, timestamp, user_id, thread_id, issue_id, issue_number, rating, issues_read)
         VALUES ('rate', NOW() - INTERVAL '1 day', $1, $2, $3, '10', 4.5, 1)",
        &[&owner_id, &hellboy_id, &issue_ten_id],
    )
    .await
    .unwrap();

    let requested = vec![
        issue_ten_id,
        issue_two_id,
        issue_one_id,
        issue_bprd_id,
        issue_foreign_id,
        issue_ten_id, // duplicate: must be omitted
    ];
    let (status, body) = send(
        &state,
        authed(
            "POST",
            "/api/v2/issues/cards",
            &token,
            &csrf,
            Some(json!({ "issue_ids": requested })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");

    let expected = json!({
        "items": [
            {
                "issue_id": issue_ten_id,
                "thread_id": hellboy_id,
                "thread_title": "Hellboy in Hell",
                "issue_number": "10",
                "status": "read",
                "read_at": "2026-01-02T03:04:05.123Z",
                "rating": 4.5,
                "has_confirmed_identity": true,
                "mapping_state": "confirmed",
                "comicvine_issue_id": "4000-42",
                "cover_image_url": "https://comicvine.example/original/4000-42.jpg"
            },
            {
                "issue_id": issue_two_id,
                "thread_id": hellboy_id,
                "thread_title": "Hellboy in Hell",
                "issue_number": "2",
                "status": "unread",
                "read_at": null,
                "rating": null,
                "has_confirmed_identity": false,
                "mapping_state": "candidate",
                "comicvine_issue_id": null,
                "cover_image_url": null
            },
            {
                "issue_id": issue_one_id,
                "thread_id": hellboy_id,
                "thread_title": "Hellboy in Hell",
                "issue_number": "1",
                "status": "unread",
                "read_at": null,
                "rating": null,
                "has_confirmed_identity": false,
                "mapping_state": "unmapped",
                "comicvine_issue_id": null,
                "cover_image_url": null
            },
            {
                "issue_id": issue_bprd_id,
                "thread_id": bprd_id,
                "thread_title": "B.P.R.D.",
                "issue_number": "1",
                "status": "unread",
                "read_at": null,
                "rating": null,
                "has_confirmed_identity": true,
                "mapping_state": "confirmed",
                "comicvine_issue_id": "4000-45",
                "cover_image_url": "https://comicvine.example/original/4000-45.jpg"
            }
        ]
    });
    assert_eq!(body, expected);

    for rejected in [
        json!({ "issue_ids": [] }),
        json!({ "issue_ids": (1..=201).collect::<Vec<_>>() }),
        json!({ "issue_ids": [0] }),
    ] {
        let (status, _body) = send(
            &state,
            authed(
                "POST",
                "/api/v2/issues/cards",
                &token,
                &csrf,
                Some(rejected),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    }
}
