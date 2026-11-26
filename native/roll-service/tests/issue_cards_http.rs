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
    let bytes = to_bytes(response.into_body(), 2 * 1024 * 1024)
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
                "display_issue_number": "10",
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
                "display_issue_number": "2",
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
                "display_issue_number": "1",
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
                "display_issue_number": "1",
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

#[tokio::test]
async fn issue_cards_find_cover_in_raw_provider_payload_image() {
    let (state, token, csrf, owner_id, _guard) = setup_user("cards-raw-cover").await;
    let conn = state.pool.get().await.unwrap();

    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at, total_issues, reading_progress)
             VALUES ($1, $2, 'Comic', 1, 1, 'active', NOW(), 1, 'in_progress') RETURNING id",
            &[&owner_id, &"Detective Comics"],
        )
        .await
        .unwrap()
        .get(0);
    let issue_id: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at)
             VALUES ($1, '5', 1, 'unread', NOW()) RETURNING id",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get(0);

    let identity_id: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at)
             VALUES ('comicvine', 'issue', '4000-5677', $1, NOW(), NOW()) RETURNING id",
            &[&json!({
                "raw_provider_payload": {
                    "image": {
                        "thumb_url": "https://comicvine.gamespot.com/a/uploads/scale_avatar/0/4/5677-5.jpg"
                    }
                }
            })],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO issue_external_identity_mappings
            (issue_id, external_identity_id, status, confidence, evidence_json, created_at, updated_at)
         VALUES ($1, $2, 'confirmed', 1.0, '{}'::jsonb, NOW(), NOW())",
        &[&issue_id, &identity_id],
    )
    .await
    .unwrap();

    let (status, body) = send(
        &state,
        authed(
            "POST",
            "/api/v2/issues/cards",
            &token,
            &csrf,
            Some(json!({ "issue_ids": [issue_id] })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body["items"][0]["cover_image_url"],
        "https://comicvine.gamespot.com/a/uploads/scale_avatar/0/4/5677-5.jpg"
    );
}

#[tokio::test]
async fn issue_cards_expose_alias_and_provider_issue_number() {
    let (state, token, csrf, owner_id, _guard) = setup_user("alias-cards").await;
    let conn = state.pool.get().await.unwrap();

    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at, total_issues, reading_progress)
             VALUES ($1, 'Saga', 'Comic', 1, 1, 'active', NOW(), 1, 'in_progress') RETURNING id",
            &[&owner_id],
        )
        .await
        .unwrap()
        .get(0);
    let issue_id: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, issue_number_alias, position, status, created_at)
             VALUES ($1, '3', '100', 1, 'unread', NOW()) RETURNING id",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get(0);

    let identity_id: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at)
             VALUES ('comicvine', 'issue', '4000-999', $1, NOW(), NOW()) RETURNING id",
            &[&json!({
                "issue_number": "100",
                "image_url": "https://example.test/cover.jpg"
            })],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO issue_external_identity_mappings
            (issue_id, external_identity_id, status, confidence, evidence_json, created_at, updated_at)
         VALUES ($1, $2, 'confirmed', 1.0, '{}'::jsonb, NOW(), NOW())",
        &[&issue_id, &identity_id],
    )
    .await
    .unwrap();

    let (status, body) = send(
        &state,
        authed(
            "POST",
            "/api/v2/issues/cards",
            &token,
            &csrf,
            Some(json!({ "issue_ids": [issue_id] })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let card = &body["items"][0];
    assert_eq!(card["issue_number"], "3");
    assert_eq!(card["issue_number_alias"], "100");
    assert_eq!(card["display_issue_number"], "3 (100)");
    assert_eq!(card["comicvine_issue_id"], "4000-999");
    assert_eq!(card["provider_issue_number"], "100");
    assert_eq!(card["cover_image_url"], "https://example.test/cover.jpg");
}

#[tokio::test]
async fn issue_patch_can_set_and_clear_alias() {
    let (state, token, csrf, owner_id, _guard) = setup_user("alias-patch").await;
    let conn = state.pool.get().await.unwrap();

    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at, total_issues, reading_progress)
             VALUES ($1, 'Saga', 'Comic', 1, 1, 'active', NOW(), 1, 'in_progress') RETURNING id",
            &[&owner_id],
        )
        .await
        .unwrap()
        .get(0);
    let issue_id: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at)
             VALUES ($1, '3', 1, 'unread', NOW()) RETURNING id",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get(0);

    let (status, body) = send(
        &state,
        authed(
            "PATCH",
            &format!("/api/v2/issues/{issue_id}"),
            &token,
            &csrf,
            Some(json!({
                "idempotency_key": "alias-set-0001",
                "source": "direct",
                "issue_number_alias": "100"
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["issue"]["issue_number_alias"], "100");
    assert_eq!(body["issue"]["display_issue_number"], "3 (100)");

    let (status, body) = send(
        &state,
        authed(
            "PATCH",
            &format!("/api/v2/issues/{issue_id}"),
            &token,
            &csrf,
            Some(json!({
                "idempotency_key": "alias-clear-0001",
                "source": "direct",
                "issue_number_alias": null
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert!(body["issue"]["issue_number_alias"].is_null());
    assert_eq!(body["issue"]["display_issue_number"], "3");
}

/// A7 synthetic fixture (#4652): a five-part series whose provider numbers are
/// 1, 2, 100, 101, 102, plus an adjacent arc in a different provider volume.
/// Authored labels, order, read/rating history and exact provider art must
/// survive mapping; no extra physical/rollable rows may appear.
#[tokio::test]
async fn issue_cards_preserve_mixed_numbering_series_and_adjacent_volume() {
    let (state, token, csrf, owner_id, _guard) = setup_user("mixed-numbering").await;
    let conn = state.pool.get().await.unwrap();

    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at, total_issues, reading_progress)
             VALUES ($1, 'Saga', 'Comic', 5, 1, 'active', NOW(), 5, 'in_progress') RETURNING id",
            &[&owner_id],
        )
        .await
        .unwrap()
        .get(0);
    let arc_thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at, total_issues, reading_progress)
             VALUES ($1, 'Adjacent arc', 'Comic', 1, 2, 'active', NOW(), 1, 'in_progress') RETURNING id",
            &[&owner_id],
        )
        .await
        .unwrap()
        .get(0);

    // Set-based fixture: authored numbers stay 1..5 (plus the adjacent 6);
    // aliases carry the provider's overall numbering 1,2,100,101,102,6.
    let rows = conn
        .query(
            "INSERT INTO issues
                (thread_id, issue_number, issue_number_alias, position, status, read_at, created_at)
             SELECT tid, authored, provider, pos,
                    CASE WHEN provider = '100' THEN 'read' ELSE 'unread' END,
                    CASE WHEN provider = '100' THEN '2026-01-02T03:04:05.123456Z'::timestamptz ELSE NULL END,
                    NOW()
             FROM unnest($1::int[], $2::text[], $3::text[], $4::int[])
                  AS u(tid, authored, provider, pos)
             RETURNING id, issue_number, issue_number_alias, position",
            &[
                &vec![thread_id, thread_id, thread_id, thread_id, thread_id, arc_thread_id],
                &vec!["1", "2", "3", "4", "5", "6"],
                &vec!["1", "2", "100", "101", "102", "6"],
                &vec![1, 2, 3, 4, 5, 6],
            ],
        )
        .await
        .unwrap();
    assert_eq!(rows.len(), 6, "six physical comics must stay six rows");

    // Confirm one exact provider identity per physical issue. The adjacent arc
    // lives in a different provider volume even though its number (6) is next
    // to the ongoing series. Never infer a volume from the issue number.
    conn.execute(
        "WITH provider AS (
             SELECT external_id, split_part(external_id, '-', 2) AS provider_number
             FROM unnest($1::text[]) AS u(external_id)
         ), identities AS (
             INSERT INTO external_identities
                 (provider, entity_type, external_id, metadata_json, created_at, updated_at)
             SELECT 'comicvine', 'issue', p.external_id,
                    jsonb_build_object(
                        'issue_number', p.provider_number,
                        'image_url', 'https://comicvine.test/' || p.external_id || '.jpg'
                    ), NOW(), NOW()
             FROM provider p
             RETURNING id, external_id
         )
         INSERT INTO issue_external_identity_mappings
             (issue_id, external_identity_id, status, confidence, evidence_json, created_at, updated_at)
         SELECT i.id, identities.id, 'confirmed', 1.0, '{}'::jsonb, NOW(), NOW()
         FROM identities
         JOIN provider p ON p.external_id = identities.external_id
         JOIN issues i ON i.issue_number_alias = p.provider_number
           AND i.thread_id IN ($2, $3)",
        &[
            &vec![
                "4050-1", "4050-2", "4050-100", "4050-101", "4050-102", "9000-6",
            ],
            &thread_id,
            &arc_thread_id,
        ],
    )
    .await
    .unwrap();

    // A preserved rating/read history for the third physical comic.
    conn.execute(
        "INSERT INTO events (type, timestamp, rating, issue_id, issue_number, user_id, context)
         SELECT 'rate', NOW(), 4.5, id, issue_number, $1, '{}'::json
         FROM issues WHERE thread_id = $2 AND issue_number_alias = '100'",
        &[&owner_id, &thread_id],
    )
    .await
    .unwrap();

    let requested: Vec<i32> = rows.iter().map(|row| row.get::<_, i32>(0)).rev().collect();
    let volumes = ["4050", "4050", "4050", "4050", "4050", "9000"];
    let expected: Vec<(i32, String, String, String, i32)> = rows
        .iter()
        .rev()
        .enumerate()
        .map(|(index, row)| {
            let provider = row.get::<_, Option<String>>(2).expect("fixture alias");
            let external_id = format!("{}-{}", volumes[volumes.len() - 1 - index], provider);
            (
                row.get::<_, i32>(0),
                row.get::<_, String>(1),
                provider,
                external_id,
                row.get::<_, i32>(3),
            )
        })
        .collect();
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
    let items = body["items"].as_array().expect("cards items");
    assert_eq!(
        items.len(),
        6,
        "every requested physical comic has one card"
    );

    for (index, (id, authored, provider, external_id, position)) in expected.iter().enumerate() {
        let card = &items[index];
        assert_eq!(card["issue_id"], *id);
        assert_eq!(
            card["issue_number"].as_str(),
            Some(authored.as_str()),
            "authored label must not be renumbered"
        );
        assert_eq!(card["issue_number_alias"].as_str(), Some(provider.as_str()));
        let expected_display = if provider == authored {
            authored.clone()
        } else {
            format!("{authored} ({provider})")
        };
        assert_eq!(
            card["display_issue_number"].as_str(),
            Some(expected_display.as_str())
        );
        assert_eq!(
            *position,
            6 - index as i32,
            "authored order is preserved by the mapping"
        );
        assert_eq!(card["has_confirmed_identity"], true);
        assert_eq!(card["mapping_state"].as_str(), Some("confirmed"));
        assert_eq!(
            card["comicvine_issue_id"].as_str(),
            Some(external_id.as_str())
        );
        assert_eq!(
            card["provider_issue_number"].as_str(),
            Some(provider.as_str())
        );
        assert_eq!(
            card["cover_image_url"],
            format!("https://comicvine.test/{external_id}.jpg"),
            "exact provider art must be preserved"
        );
        if provider == "100" {
            assert_eq!(card["status"], "read");
            assert_eq!(card["rating"], 4.5);
        }
    }
    assert_eq!(
        card_count(&conn, &[thread_id, arc_thread_id]).await,
        6,
        "mapping must not create another rollable row"
    );
}

async fn card_count(conn: &tokio_postgres::Client, threads: &[i32]) -> i64 {
    conn.query_one(
        "SELECT count(*) FROM issues WHERE thread_id = ANY($1)",
        &[&threads],
    )
    .await
    .unwrap()
    .get(0)
}

#[tokio::test]
async fn alias_only_patch_replays_identical_key_and_rejects_a_changed_payload() {
    let (state, token, csrf, owner_id, _guard) = setup_user("alias-retry").await;
    let conn = state.pool.get().await.unwrap();
    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at, total_issues, reading_progress)
             VALUES ($1, 'Saga', 'Comic', 1, 1, 'active', NOW(), 1, 'in_progress') RETURNING id",
            &[&owner_id],
        )
        .await
        .unwrap()
        .get(0);
    let issue_id: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at)
             VALUES ($1, '3', 1, 'unread', NOW()) RETURNING id",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get(0);
    let body = json!({
        "idempotency_key": "alias-retry-0001",
        "source": "direct",
        "issue_number_alias": "100"
    });
    let (status, first) = send(
        &state,
        authed(
            "PATCH",
            &format!("/api/v2/issues/{issue_id}"),
            &token,
            &csrf,
            Some(body.clone()),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{first:?}");
    assert_eq!(first["replayed"], false);

    let (status, replay) = send(
        &state,
        authed(
            "PATCH",
            &format!("/api/v2/issues/{issue_id}"),
            &token,
            &csrf,
            Some(body),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{replay:?}");
    assert_eq!(replay["replayed"], true, "an ambiguous retry is idempotent");

    let (status, conflict) = send(
        &state,
        authed(
            "PATCH",
            &format!("/api/v2/issues/{issue_id}"),
            &token,
            &csrf,
            Some(json!({
                "idempotency_key": "alias-retry-0001",
                "source": "direct",
                "issue_number_alias": "101"
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{conflict:?}");
    assert_eq!(
        first["issue"]["issue_number_alias"], "100",
        "the original receipt still records the accepted alias"
    );
    let stored_alias: Option<String> = conn
        .query_one(
            "SELECT issue_number_alias FROM issues WHERE id=$1",
            &[&issue_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        stored_alias.as_deref(),
        Some("100"),
        "a conflicting stale write must not change the stored alias"
    );
}

#[tokio::test]
async fn issue_cards_use_verified_identity_when_candidates_conflict() {
    let (state, token, csrf, owner_id, _guard) = setup_user("conflicting-identity").await;
    let conn = state.pool.get().await.unwrap();
    let thread_id: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at)
             VALUES ($1, 'Saga', 'Comic', 1, 1, 'active', NOW()) RETURNING id",
            &[&owner_id],
        )
        .await
        .unwrap()
        .get(0);
    let issue_id: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, issue_number_alias, position, status, created_at)
             VALUES ($1, '3', '100', 1, 'unread', NOW()) RETURNING id",
            &[&thread_id],
        )
        .await
        .unwrap()
        .get(0);

    // A competing candidate with a higher confidence must not win: only the
    // confirmed provider identity supplies the number, id and cover (#4652).
    conn.batch_execute(
        "INSERT INTO external_identities (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
         VALUES (700, 'comicvine', 'issue', '4050-100',
                 '{\"issue_number\":\"100\",\"image_url\":\"https://comicvine.test/confirmed.jpg\"}'::json, NOW(), NOW()),
                (701, 'comicvine', 'issue', '4050-999',
                 '{\"issue_number\":\"999\",\"image_url\":\"https://comicvine.test/candidate.jpg\"}'::json, NOW(), NOW());",
    )
    .await
    .unwrap();
    conn.execute(
        "INSERT INTO issue_external_identity_mappings
             (id, issue_id, external_identity_id, status, confidence, evidence_json, created_at, updated_at)
         VALUES (800, $1, 700, 'candidate', 0.99, '{}'::json, NOW(), NOW()),
                (801, $1, 701, 'confirmed', 0.80, '{}'::json, NOW(), NOW())",
        &[&issue_id],
    )
    .await
    .unwrap();

    let (status, body) = send(
        &state,
        authed(
            "POST",
            "/api/v2/issues/cards",
            &token,
            &csrf,
            Some(json!({ "issue_ids": [issue_id] })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let card = &body["items"][0];
    assert_eq!(card["issue_number"].as_str(), Some("3"));
    assert_eq!(card["issue_number_alias"].as_str(), Some("100"));
    assert_eq!(card["provider_issue_number"].as_str(), Some("100"));
    assert_eq!(card["comicvine_issue_id"].as_str(), Some("4050-100"));
    assert_eq!(
        card["cover_image_url"].as_str(),
        Some("https://comicvine.test/confirmed.jpg")
    );
    assert_eq!(card["has_confirmed_identity"], true);
    assert_eq!(card["mapping_state"].as_str(), Some("confirmed"));
    assert_eq!(
        card_count(&conn, &[thread_id]).await,
        1,
        "conflicting identities must not create a second physical comic"
    );
}
