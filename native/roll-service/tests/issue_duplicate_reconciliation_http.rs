#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Handler-level HTTP regressions for guided canonical duplicate reconciliation (#4653).
//!
//! Exercises the mounted router against the canonical disposable PostgreSQL
//! schema. The fixture reproduces theincident shape without production IDs:
//! one canonical issue with a real read/rating and list membership, plus a
//! synthetic overall issue mapped to the same Comic Vine identity whose
//! `read_at` predates its own creation. Reconciliation must move the mapping
//! and real events, suppress (not erase) the synthetic placeholder, preserve
//! the canonical's real read timestamp, and be idempotent and undoable.
//!
//! Hard-fails without `RUST_ROLL_TEST_DATABASE_URL`.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
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

struct Ctx {
    state: Arc<AppState>,
    token: String,
    csrf: String,
    user_id: i32,
    _guard: tokio::sync::MutexGuard<'static, ()>,
}

async fn setup(prefix: &str) -> Ctx {
    let url = comicpile_roll_service::test_support::database_url().await;
    let state = Arc::new(test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-duplicate-reconciliation-secret".into()),
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .unwrap(),
    ));
    let guard = comicpile_roll_service::test_support::reset_for_test(&state).await;
    let username = format!("{prefix}-{}-{}", std::process::id(), unique_suffix());
    let (token, csrf, user_id) = register_user(&state, &username).await;
    Ctx {
        state,
        token,
        csrf,
        user_id,
        _guard: guard,
    }
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
        .unwrap_or_else(|| panic!("csrf cookie missing (status {status})"))
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
    let bytes = to_bytes(response.into_body(), 128 * 1024).await.unwrap();
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
    if let Some(payload) = body {
        builder
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(payload.to_string()))
            .unwrap()
    } else {
        builder.body(Body::empty()).unwrap()
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn detect_preview_apply_and_undo_preserve_real_history() {
    let ctx = setup("dupr").await;
    let conn = ctx.state.pool.get().await.unwrap();

    let canonical_thread: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at) \
             VALUES ($1, 'Return of the Master', 'comic', 2, 1, 'active', NOW()) RETURNING id",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    let duplicate_thread: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at) \
             VALUES ($1, 'Overall', 'comic', 1, 2, 'active', NOW()) RETURNING id",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);

    // Canonical #3: real read and 4.0 rating, belongs to a saved list.
    let canonical: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, read_at, created_at) \
             VALUES ($1, '3', 0, 'read', NOW() - interval '1 hour', NOW() - interval '2 days') \
             RETURNING id",
            &[&canonical_thread],
        )
        .await
        .unwrap()
        .get(0);
    // Synthetic overall #100: read_at predates its own creation (invalid).
    let duplicate: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, read_at, created_at) \
             VALUES ($1, '100', 0, 'read', NOW() - interval '1 hour', NOW()) RETURNING id",
            &[&duplicate_thread],
        )
        .await
        .unwrap()
        .get(0);

    let canonical_read_at: chrono::DateTime<chrono::Utc> = conn
        .query_one("SELECT read_at FROM issues WHERE id = $1", &[&canonical])
        .await
        .unwrap()
        .get(0);

    let identity_id: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'issue', '364132', \
                     '{\"volume_id\":4050,\"issue_number\":\"100\",\"story_arc_number\":\"3\"}'::json, \
                     NOW(), NOW()) RETURNING id",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    // Only the synthetic overall issue carries the Comic Vine identity; the
    // original story issue is linked by the explicit story/overall relationship
    // in the mapping metadata (`story_arc_number = 3`).
    conn.execute(
        "INSERT INTO issue_external_identity_mappings \
         (issue_id, external_identity_id, status, evidence_source, evidence_json, created_at, updated_at) \
         VALUES ($1, $2, 'confirmed', 'test', '{}'::json, NOW(), NOW())",
        &[&duplicate, &identity_id],
    )
    .await
    .unwrap();

    // Real 4.0 rating on the canonical and on the duplicate (must be moved,
    // never erased or double-counted).
    let canonical_rating_event: i32 = conn
        .query_one(
            "INSERT INTO events (type, timestamp, user_id, issue_id, rating) \
             VALUES ('rate', NOW() - interval '1 day', $1, $2, 4.0) RETURNING id",
            &[&ctx.user_id, &canonical],
        )
        .await
        .unwrap()
        .get(0);
    let duplicate_rating_event: i32 = conn
        .query_one(
            "INSERT INTO events (type, timestamp, user_id, issue_id, rating) \
             VALUES ('rate', NOW() - interval '30 minutes', $1, $2, 4.0) RETURNING id",
            &[&ctx.user_id, &duplicate],
        )
        .await
        .unwrap()
        .get(0);
    // Real read event on the canonical, synthetic placeholder on the duplicate.
    conn.execute(
        "INSERT INTO events (type, timestamp, user_id, issue_id, issue_number) \
         VALUES ('issue_read', NOW() - interval '1 hour', $1, $2, '3')",
        &[&ctx.user_id, &canonical],
    )
    .await
    .unwrap();
    let synthetic_read_event: i32 = conn
        .query_one(
            "INSERT INTO events (type, timestamp, user_id, issue_id, issue_number) \
             VALUES ('issue_read', NOW() - interval '1 hour', $1, $2, '100') RETURNING id",
            &[&ctx.user_id, &duplicate],
        )
        .await
        .unwrap()
        .get(0);

    let list_id: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, description, mode, created_at, updated_at, overlap_decisions_updated_at) \
             VALUES ($1, 'Julix', NULL, 'loose', NOW(), NOW(), NOW()) RETURNING id",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    let membership_entry: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_entries (list_id, issue_id, position, created_at, is_checkpoint, checkpoint_target_issue_ids, gate, skipped) \
             VALUES ($1, $2, 0, NOW(), false, '[]'::json, 'none', false) RETURNING id",
            &[&list_id, &canonical],
        )
        .await
        .unwrap()
        .get(0);
    // The synthetic duplicate also appears in a different saved list; its exact
    // entry must move to the canonical without losing list identity or position.
    let duplicate_list_id: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, description, mode, created_at, updated_at, overlap_decisions_updated_at) \
             VALUES ($1, 'Overall', NULL, 'loose', NOW(), NOW(), NOW()) RETURNING id",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    let duplicate_membership_entry: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_entries (list_id, issue_id, position, created_at, is_checkpoint, checkpoint_target_issue_ids, gate, skipped) \
             VALUES ($1, $2, 3, NOW(), false, '[]'::json, 'none', false) RETURNING id",
            &[&duplicate_list_id, &duplicate],
        )
        .await
        .unwrap()
        .get(0);

    // --- Detect: exact provider identity, with full evidence and uncertainty.
    let (status, detected) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v2/issue-duplicate-reconciliation/detect",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{detected:?}");
    let group = detected["groups"]
        .as_array()
        .unwrap()
        .iter()
        .find(|g| {
            g["evidence"]
                .as_array()
                .is_some_and(|items| items.iter().any(|e| e["issue_id"] == canonical))
        })
        .expect("canonical issue appears in a detected group")
        .clone();
    assert_eq!(group["confidence"], "high");
    assert!(group["group_key"].as_str().unwrap().contains("364132"));
    let dup_evidence = group["evidence"]
        .as_array()
        .unwrap()
        .iter()
        .find(|e| e["issue_id"] == duplicate)
        .expect("duplicate appears in the same group")
        .clone();
    assert_eq!(dup_evidence["is_synthetic_placeholder_read"], true);
    assert_eq!(dup_evidence["comicvine_issue_id"], "364132");
    assert_eq!(dup_evidence["comicvine_volume_id"], 4050);
    assert_eq!(dup_evidence["rating_events"].as_array().unwrap().len(), 1);
    assert_eq!(dup_evidence["read_events"].as_array().unwrap().len(), 1);
    assert_eq!(group["suggested_canonical_issue_id"], canonical);

    // --- Preview: explicit safe actions and warnings, no destructive delete.
    let (status, preview) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/issue-duplicate-reconciliation/preview",
            &ctx.token,
            &ctx.csrf,
            Some(json!({"canonical_issue_id": canonical, "duplicate_issue_ids": [duplicate]})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preview:?}");
    assert_eq!(preview["can_apply"], true, "{preview:?}");
    let kinds: Vec<&str> = preview["actions"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a["kind"].as_str().unwrap())
        .collect();
    for expected in [
        "move_comicvine_mapping",
        "move_rating_events",
        "suppress_synthetic_read_events",
        "move_list_memberships",
        "suppress_duplicate",
    ] {
        assert!(kinds.contains(&expected), "missing {expected} in {kinds:?}");
    }
    assert!(preview["warnings"]
        .as_array()
        .unwrap()
        .iter()
        .any(|w| w.as_str().unwrap().contains("synthetic placeholder")));
    let token = preview["preview_token"].as_str().unwrap().to_owned();
    assert!(!token.is_empty());

    // --- Apply: move mapping and real events, suppress synthetic placeholder.
    let apply_body = json!({
        "canonical_issue_id": canonical,
        "duplicate_issue_ids": [duplicate],
        "preview_token": token,
    });
    let (status, applied) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/issue-duplicate-reconciliation/apply",
            &ctx.token,
            &ctx.csrf,
            Some(apply_body.clone()),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{applied:?}");
    assert_eq!(applied["merged_issue_ids"], json!([duplicate]));
    assert_eq!(
        applied["suppressed_duplicate_issue_ids"],
        json!([duplicate])
    );
    assert!(!applied["moved_mapping_ids"].as_array().unwrap().is_empty());
    let moved_events = applied["moved_event_ids"].as_array().unwrap();
    assert!(moved_events.contains(&json!(duplicate_rating_event)));
    assert!(!moved_events.contains(&json!(synthetic_read_event)));
    let moved_entries = applied["moved_list_entry_ids"].as_array().unwrap();
    assert!(moved_entries.contains(&json!(duplicate_membership_entry)));

    let merged_into: Option<i32> = conn
        .query_one(
            "SELECT merged_into_issue_id FROM issues WHERE id = $1",
            &[&duplicate],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(merged_into, Some(canonical));

    let mapping_owner: i32 = conn
        .query_one(
            "SELECT issue_id FROM issue_external_identity_mappings WHERE external_identity_id = $1",
            &[&identity_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(mapping_owner, canonical);

    let rating_owner: i32 = conn
        .query_one(
            "SELECT issue_id FROM events WHERE id = $1",
            &[&duplicate_rating_event],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(rating_owner, canonical);
    let synthetic_owner: i32 = conn
        .query_one(
            "SELECT issue_id FROM events WHERE id = $1",
            &[&synthetic_read_event],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        synthetic_owner, duplicate,
        "synthetic read is retained as provenance"
    );
    let canonical_rating_owner: i32 = conn
        .query_one(
            "SELECT issue_id FROM events WHERE id = $1",
            &[&canonical_rating_event],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(canonical_rating_owner, canonical);

    let canonical_status: String = conn
        .query_one("SELECT status FROM issues WHERE id = $1", &[&canonical])
        .await
        .unwrap()
        .get(0);
    let read_at_after: chrono::DateTime<chrono::Utc> = conn
        .query_one("SELECT read_at FROM issues WHERE id = $1", &[&canonical])
        .await
        .unwrap()
        .get(0);
    assert_eq!(canonical_status, "read");
    assert_eq!(
        read_at_after, canonical_read_at,
        "real read timestamp preserved"
    );

    // --- Idempotent retry with the same preview token returns the prior result.
    let (status, retried) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/issue-duplicate-reconciliation/apply",
            &ctx.token,
            &ctx.csrf,
            Some(apply_body),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{retried:?}");
    assert_eq!(retried["merged_issue_ids"], json!([duplicate]));

    // --- Undo restores explicit alias state, mapping and event ownership.
    let undo_id = applied["undo_snapshot_id"].as_i64().unwrap() as i32;
    let (status, undone) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/issue-duplicate-reconciliation/undo",
            &ctx.token,
            &ctx.csrf,
            Some(json!({"reconciliation_id": undo_id})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{undone:?}");
    assert_eq!(undone["undone"], true);

    let merged_after_undo: Option<i32> = conn
        .query_one(
            "SELECT merged_into_issue_id FROM issues WHERE id = $1",
            &[&duplicate],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(merged_after_undo, None);
    let mapping_after_undo: i32 = conn
        .query_one(
            "SELECT issue_id FROM issue_external_identity_mappings WHERE external_identity_id = $1",
            &[&identity_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(mapping_after_undo, duplicate);
    let rating_after_undo: i32 = conn
        .query_one(
            "SELECT issue_id FROM events WHERE id = $1",
            &[&duplicate_rating_event],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(rating_after_undo, duplicate);
    let canonical_status_after_undo: String = conn
        .query_one("SELECT status FROM issues WHERE id = $1", &[&canonical])
        .await
        .unwrap()
        .get(0);
    assert_eq!(canonical_status_after_undo, "read");

    // The list entry already on the canonical was never moved or erased, and
    // the duplicate's own entry is restored to its exact original issue.
    let entry_owner: i32 = conn
        .query_one(
            "SELECT issue_id FROM custom_cbl_entries WHERE id = $1",
            &[&membership_entry],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(entry_owner, canonical);
    let duplicate_entry_owner: i32 = conn
        .query_one(
            "SELECT issue_id FROM custom_cbl_entries WHERE id = $1",
            &[&duplicate_membership_entry],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(duplicate_entry_owner, duplicate);
}

#[tokio::test(flavor = "multi_thread")]
async fn stale_preview_token_and_cross_owner_issue_are_rejected() {
    let ctx = setup("duprguard").await;
    let other_username = format!("other-{}", unique_suffix());
    let (_other_token, _other_csrf, other_user_id) =
        register_user(&ctx.state, &other_username).await;
    let conn = ctx.state.pool.get().await.unwrap();
    let own_thread: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at) \
             VALUES ($1, 'Mine', 'comic', 1, 1, 'active', NOW()) RETURNING id",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    let foreign_thread: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at) \
             VALUES ($1, 'Theirs', 'comic', 1, 2, 'active', NOW()) RETURNING id",
            &[&other_user_id],
        )
        .await
        .unwrap()
        .get(0);
    let canonical: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
             VALUES ($1, '1', 0, 'unread', NOW()) RETURNING id",
            &[&own_thread],
        )
        .await
        .unwrap()
        .get(0);
    let foreign: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
             VALUES ($1, '2', 0, 'unread', NOW()) RETURNING id",
            &[&foreign_thread],
        )
        .await
        .unwrap()
        .get(0);

    let (status, body) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/issue-duplicate-reconciliation/apply",
            &ctx.token,
            &ctx.csrf,
            Some(json!({
                "canonical_issue_id": canonical,
                "duplicate_issue_ids": [foreign],
                "preview_token": "not-a-real-token",
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");

    let (status, body) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/issue-duplicate-reconciliation/preview",
            &ctx.token,
            &ctx.csrf,
            Some(json!({"canonical_issue_id": canonical, "duplicate_issue_ids": [canonical]})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body:?}");
}
