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
             VALUES ($1, '3', 0, 'read', '2026-11-05T05:47:59Z', '2026-01-01T00:00:00Z') \
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
             VALUES ($1, '100', 0, 'read', '2026-11-05T05:02:02Z', '2026-11-05T05:11:33Z') RETURNING id",
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
             VALUES ('rate', '2026-11-05T05:47:59Z', $1, $2, 4.5) RETURNING id",
            &[&ctx.user_id, &canonical],
        )
        .await
        .unwrap()
        .get(0);
    let duplicate_rating_event: i32 = conn
        .query_one(
            "INSERT INTO events (type, timestamp, user_id, issue_id, rating) \
             VALUES ('rate', '2026-11-05T06:00:00Z', $1, $2, 4.0) RETURNING id",
            &[&ctx.user_id, &duplicate],
        )
        .await
        .unwrap()
        .get(0);
    // Real read event on the canonical, synthetic placeholder on the duplicate.
    conn.execute(
        "INSERT INTO events (type, timestamp, user_id, issue_id, issue_number) \
         VALUES ('issue_read', '2026-11-05T05:47:59Z', $1, $2, '3')",
        &[&ctx.user_id, &canonical],
    )
    .await
    .unwrap();
    let synthetic_read_event: i32 = conn
        .query_one(
            "INSERT INTO events (type, timestamp, user_id, issue_id, issue_number) \
             VALUES ('issue_read', '2026-11-05T05:02:02Z', $1, $2, '100') RETURNING id",
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
    assert_eq!(group["confidence"], "medium");
    assert!(group["group_key"]
        .as_str()
        .unwrap()
        .contains("story-overall"));
    assert!(group["reason"].as_str().unwrap().contains("364132"));
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
    assert_eq!(
        retried["undo_snapshot_id"], applied["undo_snapshot_id"],
        "an idempotent retry must keep the Undo affordance available"
    );

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

/// Seed the incident shape with configurable timestamps and mapping status.
/// Returns `(canonical, duplicate, external_identity_id)`.
async fn seed_pair(
    ctx: &Ctx,
    canonical_created: &str,
    duplicate_created: &str,
    mapping_status: &str,
) -> (i32, i32, i32) {
    let conn = ctx.state.pool.get().await.unwrap();
    let canonical_thread: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at) \
             VALUES ($1, 'Story', 'comic', 1, 1, 'active', NOW()) RETURNING id",
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
    let canonical: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
             VALUES ($1, '3', 0, 'unread', $2::text::timestamptz) RETURNING id",
            &[&canonical_thread, &canonical_created],
        )
        .await
        .unwrap()
        .get(0);
    let duplicate: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
             VALUES ($1, '100', 0, 'unread', $2::text::timestamptz) RETURNING id",
            &[&duplicate_thread, &duplicate_created],
        )
        .await
        .unwrap()
        .get(0);
    let identity_id: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'issue', '777001', \
                     '{\"volume_id\":4050,\"issue_number\":\"100\",\"story_arc_number\":\"3\"}'::json, \
                     NOW(), NOW()) RETURNING id",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO issue_external_identity_mappings \
         (issue_id, external_identity_id, status, evidence_source, evidence_json, created_at, updated_at) \
         VALUES ($1, $2, $3, 'test', '{}'::json, NOW(), NOW())",
        &[&duplicate, &identity_id, &mapping_status],
    )
    .await
    .unwrap();
    (canonical, duplicate, identity_id)
}

/// A pair with distinct provider numbers so three pairs never cross-match in
/// the story/overall detection rule. Returns `(canonical, duplicate)`.
async fn seed_named_pair(
    ctx: &Ctx,
    cv_id: &str,
    canonical_number: &str,
    canonical_created: &str,
    duplicate_created: &str,
) -> (i32, i32) {
    let conn = ctx.state.pool.get().await.unwrap();
    let cv_issue_number = format!("1{canonical_number}");
    let story_arc_number = canonical_number.to_string();
    let canonical_thread: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at) \
             VALUES ($1, 'Story ' || $2, 'comic', 1, 1, 'active', NOW()) RETURNING id",
            &[&ctx.user_id, &story_arc_number],
        )
        .await
        .unwrap()
        .get(0);
    let duplicate_thread: i32 = conn
        .query_one(
            "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at) \
             VALUES ($1, 'Overall ' || $2, 'comic', 1, 2, 'active', NOW()) RETURNING id",
            &[&ctx.user_id, &cv_issue_number],
        )
        .await
        .unwrap()
        .get(0);
    let canonical: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
             VALUES ($1, $2, 0, 'unread', $3::text::timestamptz) RETURNING id",
            &[&canonical_thread, &canonical_number, &canonical_created],
        )
        .await
        .unwrap()
        .get(0);
    let duplicate: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
             VALUES ($1, $2, 0, 'unread', $3::text::timestamptz) RETURNING id",
            &[&duplicate_thread, &cv_issue_number, &duplicate_created],
        )
        .await
        .unwrap()
        .get(0);
    let metadata: serde_json::Value = serde_json::from_str(&format!(
        "{{\"volume_id\":4050,\"issue_number\":\"{cv_issue_number}\",\"story_arc_number\":\"{story_arc_number}\"}}"
    ))
    .unwrap();
    let identity_id: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'issue', $1, $2, NOW(), NOW()) RETURNING id",
            &[&cv_id, &metadata],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO issue_external_identity_mappings \
         (issue_id, external_identity_id, status, evidence_source, evidence_json, created_at, updated_at) \
         VALUES ($1, $2, 'confirmed', 'test', '{}'::json, NOW(), NOW())",
        &[&duplicate, &identity_id],
    )
    .await
    .unwrap();
    (canonical, duplicate)
}

async fn preview_pair(ctx: &Ctx, canonical: i32, duplicate: i32) -> (StatusCode, Value) {
    send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/issue-duplicate-reconciliation/preview",
            &ctx.token,
            &ctx.csrf,
            Some(json!({
                "canonical_issue_id": canonical,
                "duplicate_issue_ids": [duplicate],
            })),
        ),
    )
    .await
}

#[tokio::test(flavor = "multi_thread")]
async fn candidate_only_mapping_is_not_verified_identity() {
    let ctx = setup("dupr-candidate").await;
    let (canonical, duplicate, _) = seed_pair(
        &ctx,
        "2026-01-01T00:00:00Z",
        "2026-11-05T05:11:33Z",
        "candidate",
    )
    .await;

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
    let groups = detected["groups"].as_array().unwrap();
    assert!(
        groups.iter().all(|group| {
            !group["evidence"]
                .as_array()
                .unwrap()
                .iter()
                .any(|e| e["issue_id"] == canonical || e["issue_id"] == duplicate)
        }),
        "an unreviewed candidate mapping must not be offered as verified identity: {detected:?}"
    );

    let (status, body) = preview_pair(&ctx, canonical, duplicate).await;
    assert_eq!(status, StatusCode::CONFLICT, "{body:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn unrelated_owned_issues_cannot_be_collapsed() {
    let ctx = setup("dupr-unrelated").await;
    let (canonical, duplicate, _) = seed_pair(
        &ctx,
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
        "confirmed",
    )
    .await;
    // Break the story/overall relationship: no metadata number matches this
    // issue number and the two numbers differ.
    let conn = ctx.state.pool.get().await.unwrap();
    conn.execute(
        "UPDATE issues SET issue_number = '999' WHERE id = $1",
        &[&canonical],
    )
    .await
    .unwrap();

    let (status, body) = preview_pair(&ctx, canonical, duplicate).await;
    assert_eq!(status, StatusCode::CONFLICT, "{body:?}");
    let (status, body) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/issue-duplicate-reconciliation/apply",
            &ctx.token,
            &ctx.csrf,
            Some(json!({
                "canonical_issue_id": canonical,
                "duplicate_issue_ids": [duplicate],
                "preview_token": "fabricated-token",
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn suppressed_alias_is_absent_from_roll_candidates() {
    let ctx = setup("dupr-roll-candidate").await;
    let (canonical, duplicate, _) = seed_pair(
        &ctx,
        "2026-01-01T00:00:00Z",
        "2026-11-05T05:11:33Z",
        "confirmed",
    )
    .await;

    let (status, eligible) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v2/roll/eligible-issue-ids",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{eligible:?}");
    let before = eligible["issue_ids"].as_array().unwrap();
    assert!(before.contains(&json!(canonical)), "{eligible:?}");
    assert!(before.contains(&json!(duplicate)), "{eligible:?}");

    let (status, preview) = preview_pair(&ctx, canonical, duplicate).await;
    assert_eq!(status, StatusCode::OK, "{preview:?}");
    let token = preview["preview_token"].as_str().unwrap().to_owned();
    let (status, applied) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/issue-duplicate-reconciliation/apply",
            &ctx.token,
            &ctx.csrf,
            Some(json!({
                "canonical_issue_id": canonical,
                "duplicate_issue_ids": [duplicate],
                "preview_token": token,
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{applied:?}");

    let (status, eligible) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v2/roll/eligible-issue-ids",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{eligible:?}");
    let after = eligible["issue_ids"].as_array().unwrap();
    assert!(after.contains(&json!(canonical)), "{eligible:?}");
    assert!(!after.contains(&json!(duplicate)), "{eligible:?}");

    let conn = ctx.state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO sessions (user_id, started_at, start_die) VALUES ($1, NOW(), 6)",
        &[&ctx.user_id],
    )
    .await
    .unwrap();
    let (status, bootstrap) = send(
        &ctx.state,
        authed("GET", "/api/v2/roll/bootstrap", &ctx.token, &ctx.csrf, None),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{bootstrap:?}");
    let rollable = bootstrap["rollable"].as_array().unwrap();
    assert!(
        rollable
            .iter()
            .any(|row| row["issue"]["id"].as_i64() == Some(i64::from(canonical))),
        "{bootstrap:?}"
    );
    assert!(
        rollable
            .iter()
            .all(|row| row["issue"]["id"].as_i64() != Some(i64::from(duplicate))),
        "{bootstrap:?}"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn mixed_read_events_preview_and_apply_agree_per_event() {
    let ctx = setup("dupr-mixed-reads").await;
    // The duplicate is older than the canonical: its genuine read predates the
    // canonical's creation and must survive the canonical-state reconciliation.
    let (canonical, duplicate, _) = seed_pair(
        &ctx,
        "2026-11-10T00:00:00Z",
        "2026-01-01T00:00:00Z",
        "confirmed",
    )
    .await;
    let conn = ctx.state.pool.get().await.unwrap();
    let synthetic: i32 = conn
        .query_one(
            "INSERT INTO events (type, timestamp, user_id, issue_id, issue_number) \
             VALUES ('issue_read', '2025-12-01T00:00:00Z', $1, $2, '100') RETURNING id",
            &[&ctx.user_id, &duplicate],
        )
        .await
        .unwrap()
        .get(0);
    let genuine: i32 = conn
        .query_one(
            "INSERT INTO events (type, timestamp, user_id, issue_id, issue_number) \
             VALUES ('issue_read', '2026-06-01T00:00:00Z', $1, $2, '100') RETURNING id",
            &[&ctx.user_id, &duplicate],
        )
        .await
        .unwrap()
        .get(0);

    let (status, preview) = preview_pair(&ctx, canonical, duplicate).await;
    assert_eq!(status, StatusCode::OK, "{preview:?}");
    let kinds: Vec<&str> = preview["actions"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a["kind"].as_str().unwrap())
        .collect();
    assert!(
        kinds.contains(&"suppress_synthetic_read_events"),
        "{kinds:?}"
    );
    assert!(kinds.contains(&"move_read_events"), "{kinds:?}");
    let synthetic_evidence = preview["duplicates"][0]["read_events"]
        .as_array()
        .unwrap()
        .iter()
        .find(|event| event["event_id"] == synthetic)
        .unwrap()
        .clone();
    assert_eq!(synthetic_evidence["is_synthetic"], true);
    let genuine_evidence = preview["duplicates"][0]["read_events"]
        .as_array()
        .unwrap()
        .iter()
        .find(|event| event["event_id"] == genuine)
        .unwrap()
        .clone();
    assert_eq!(genuine_evidence["is_synthetic"], false);

    let token = preview["preview_token"].as_str().unwrap().to_owned();
    let (status, applied) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/issue-duplicate-reconciliation/apply",
            &ctx.token,
            &ctx.csrf,
            Some(json!({
                "canonical_issue_id": canonical,
                "duplicate_issue_ids": [duplicate],
                "preview_token": token,
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{applied:?}");
    let moved = applied["moved_event_ids"].as_array().unwrap();
    assert!(moved.contains(&json!(genuine)), "{applied:?}");
    assert!(!moved.contains(&json!(synthetic)), "{applied:?}");
    let read_at: chrono::DateTime<chrono::Utc> = conn
        .query_one("SELECT read_at FROM issues WHERE id = $1", &[&canonical])
        .await
        .unwrap()
        .get(0);
    assert_eq!(read_at.to_rfc3339(), "2026-06-01T00:00:00+00:00");
    let synthetic_owner: i32 = conn
        .query_one("SELECT issue_id FROM events WHERE id = $1", &[&synthetic])
        .await
        .unwrap()
        .get(0);
    assert_eq!(synthetic_owner, duplicate);
}

#[tokio::test(flavor = "multi_thread")]
async fn apply_serializes_with_the_shared_queue_lock_before_row_locks() {
    let ctx = setup("dupr-lock-order").await;
    let (canonical, duplicate, _) = seed_pair(
        &ctx,
        "2026-01-01T00:00:00Z",
        "2026-11-05T05:11:33Z",
        "confirmed",
    )
    .await;
    let (status, preview) = preview_pair(&ctx, canonical, duplicate).await;
    assert_eq!(status, StatusCode::OK, "{preview:?}");
    let token = preview["preview_token"].as_str().unwrap().to_owned();

    // A sibling writer holds the same queue lock every queue/dice writer takes.
    let mut conn = ctx.state.pool.get().await.unwrap();
    let held = conn.build_transaction().start().await.unwrap();
    held.execute(
        "SELECT pg_advisory_xact_lock($1, $2)",
        &[&699001i32, &ctx.user_id],
    )
    .await
    .unwrap();

    let state = ctx.state.clone();
    let token_header = ctx.token.clone();
    let csrf = ctx.csrf.clone();
    let mut apply = Box::pin(async move {
        send(
            &state,
            authed(
                "POST",
                "/api/v2/issue-duplicate-reconciliation/apply",
                &token_header,
                &csrf,
                Some(json!({
                    "canonical_issue_id": canonical,
                    "duplicate_issue_ids": [duplicate],
                    "preview_token": token,
                })),
            ),
        )
        .await
    });
    tokio::select! {
        _ = tokio::time::sleep(std::time::Duration::from_millis(300)) => {}
        result = &mut apply => panic!("apply did not wait for the shared queue lock: {result:?}"),
    }
    held.commit().await.unwrap();
    let (status, applied) = apply.await;
    assert_eq!(status, StatusCode::OK, "{applied:?}");
    let merged: Option<i32> = conn
        .query_one(
            "SELECT merged_into_issue_id FROM issues WHERE id = $1",
            &[&duplicate],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(merged, Some(canonical));
}

#[tokio::test(flavor = "multi_thread")]
async fn three_alias_pairs_leave_one_rollable_identity_and_full_history() {
    let ctx = setup("dupr-three-pairs").await;
    // Pair 1: genuine provider evidence (rating) on the duplicate plus an
    // artificial suppression timestamp; the original has later real history.
    let (c1, d1) = seed_named_pair(
        &ctx,
        "777100",
        "3",
        "2026-01-01T00:00:00Z",
        "2026-11-05T05:11:33Z",
    )
    .await;
    // Pairs 2 and 3: artificial read timestamps on the duplicate and later
    // legitimate reads/ratings on the originals.
    let (c2, d2) = seed_named_pair(
        &ctx,
        "777200",
        "4",
        "2026-01-01T00:00:00Z",
        "2026-11-05T05:11:33Z",
    )
    .await;
    let (c3, d3) = seed_named_pair(
        &ctx,
        "777300",
        "5",
        "2026-01-01T00:00:00Z",
        "2026-11-05T05:11:33Z",
    )
    .await;

    let conn = ctx.state.pool.get().await.unwrap();
    for (canonical, duplicate, canonical_number) in [(c1, d1, "3"), (c2, d2, "4"), (c3, d3, "5")] {
        let number = format!("1{canonical_number}");
        // Artificial suppression timestamp on the alias, before its creation.
        conn.execute(
            "INSERT INTO events (type, timestamp, user_id, issue_id, issue_number) \
             VALUES ('issue_read', '2026-11-05T05:02:02Z', $1, $2, $3)",
            &[&ctx.user_id, &duplicate, &number],
        )
        .await
        .unwrap();
        // Later authentic read/rating history on the original.
        conn.execute(
            "INSERT INTO events (type, timestamp, user_id, issue_id, issue_number) \
             VALUES ('issue_read', '2026-11-06T05:02:02Z', $1, $2, $3)",
            &[&ctx.user_id, &canonical, &number],
        )
        .await
        .unwrap();
        conn.execute(
            "INSERT INTO events (type, timestamp, user_id, issue_id, rating) \
             VALUES ('rate', '2026-11-06T05:02:02Z', $1, $2, 4.5)",
            &[&ctx.user_id, &canonical],
        )
        .await
        .unwrap();
    }
    // Pair 1's duplicate carries genuine rating evidence that must move.
    let genuine_rating: i32 = conn
        .query_one(
            "INSERT INTO events (type, timestamp, user_id, issue_id, rating) \
             VALUES ('rate', '2026-11-06T06:00:00Z', $1, $2, 4.0) RETURNING id",
            &[&ctx.user_id, &d1],
        )
        .await
        .unwrap()
        .get(0);

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
    assert_eq!(
        detected["groups"].as_array().unwrap().len(),
        3,
        "{detected:?}"
    );

    for (canonical, duplicate) in [(c1, d1), (c2, d2), (c3, d3)] {
        let (status, preview) = preview_pair(&ctx, canonical, duplicate).await;
        assert_eq!(status, StatusCode::OK, "{preview:?}");
        assert_eq!(preview["can_apply"], true, "{preview:?}");
        let token = preview["preview_token"].as_str().unwrap().to_owned();
        let (status, applied) = send(
            &ctx.state,
            authed(
                "POST",
                "/api/v2/issue-duplicate-reconciliation/apply",
                &ctx.token,
                &ctx.csrf,
                Some(json!({
                    "canonical_issue_id": canonical,
                    "duplicate_issue_ids": [duplicate],
                    "preview_token": token,
                })),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{applied:?}");
    }

    let rating_owner: i32 = conn
        .query_one(
            "SELECT issue_id FROM events WHERE id = $1",
            &[&genuine_rating],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(rating_owner, c1, "genuine rating moved, never erased");

    let reconciliation_rows: i64 = conn
        .query_one(
            "SELECT count(*) FROM issue_duplicate_reconciliations WHERE user_id = $1 AND undone_at IS NULL",
            &[&ctx.user_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        reconciliation_rows, 3,
        "every alias pair keeps its audit row"
    );

    let (status, eligible) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v2/roll/eligible-issue-ids",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{eligible:?}");
    let ids = eligible["issue_ids"].as_array().unwrap();
    for duplicate in [d1, d2, d3] {
        assert!(!ids.contains(&json!(duplicate)), "{eligible:?}");
    }
    // Each physical comic leaves exactly one unsuppressed identity, with one
    // audit row each; the aliases are marked, not deleted.
    let unmerged: i64 = conn
        .query_one(
            "SELECT count(*) FROM issues \
             WHERE id = ANY($1::int[]) AND merged_into_issue_id IS NULL",
            &[&vec![c1, c2, c3, d1, d2, d3]],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(unmerged, 3, "one canonical identity per physical comic");
    let suppressed: i64 = conn
        .query_one(
            "SELECT count(*) FROM issues \
             WHERE id = ANY($1::int[]) AND merged_into_issue_id IS NOT NULL",
            &[&vec![d1, d2, d3]],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(suppressed, 3, "every alias is suppressed, never deleted");
}

/// A7 synthetic fixture: one five-part series whose provider numbers are
/// 1, 2, 100, 101, 102, plus an adjacent arc in a different provider volume.
/// Each physical issue keeps its authored label, gains an exact provider
/// alias/identity, and remains exactly one rollable owned row. No provider
/// identifier is inferred from a volume or from another issue's number.
#[tokio::test(flavor = "multi_thread")]
async fn five_part_series_maps_provider_numbers_without_renumbering_or_extra_rows() {
    let ctx = setup("dupr-five-part-series").await;
    let conn = ctx.state.pool.get().await.unwrap();
    let unique = unique_suffix();

    struct Physical {
        issue_id: i32,
        authored: &'static str,
        provider: &'static str,
        cv_id: String,
    }
    let mut physical = Vec::new();

    // Ongoing story arc: authored chapters 1-5, exact Comic Vine numbers
    // 1, 2, 100, 101, 102 in one provider volume.
    for (index, (authored, provider)) in [
        ("1", "1"),
        ("2", "2"),
        ("3", "100"),
        ("4", "101"),
        ("5", "102"),
    ]
    .into_iter()
    .enumerate()
    {
        let cv_id = format!("{unique}-4050-{provider}");
        let thread_id: i32 = conn
            .query_one(
                "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at) \
                 VALUES ($1, 'Story arc ' || $2, 'comic', 1, $3, 'active', NOW()) RETURNING id",
                &[&ctx.user_id, &authored, &(index as i32)],
            )
            .await
            .unwrap()
            .get(0);
        let issue_id: i32 = conn
            .query_one(
                "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
                 VALUES ($1, $2, $3, 'unread', NOW()) RETURNING id",
                &[&thread_id, &authored, &(index as i32)],
            )
            .await
            .unwrap()
            .get(0);
        // Only chapters 3-5 carry an explicit story-arc number; chapters 1-2
        // use the provider's own numbering. Nothing is guessed from the volume.
        let story_field = if index < 2 {
            String::new()
        } else {
            format!(",\"story_arc_number\":\"{authored}\"")
        };
        let metadata: Value = serde_json::from_str(&format!(
            "{{\"volume_id\":4050,\"issue_number\":\"{provider}\"{story_field}}}"
        ))
        .unwrap();
        let identity_id: i32 = conn
            .query_one(
                "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
                 VALUES ('comicvine', 'issue', $1, $2, NOW(), NOW()) RETURNING id",
                &[&cv_id, &metadata],
            )
            .await
            .unwrap()
            .get(0);
        conn.execute(
            "INSERT INTO issue_external_identity_mappings \
             (issue_id, external_identity_id, status, evidence_source, evidence_json, created_at, updated_at) \
             VALUES ($1, $2, 'confirmed', 'synthetic-qa-fixture', '{}'::json, NOW(), NOW())",
            &[&issue_id, &identity_id],
        )
        .await
        .unwrap();
        physical.push(Physical {
            issue_id,
            authored,
            provider,
            cv_id,
        });
    }

    // Adjacent arc: same authored labels, different provider volume and exact
    // provider ids. A shared label or volume must never fabricate an identity.
    for (index, authored) in ["1", "2"].into_iter().enumerate() {
        let cv_id = format!("{unique}-4051-{authored}");
        let thread_id: i32 = conn
            .query_one(
                "INSERT INTO threads (user_id, title, format, issues_remaining, queue_position, status, created_at) \
                 VALUES ($1, 'Adjacent arc ' || $2, 'comic', 1, $3, 'active', NOW()) RETURNING id",
                &[&ctx.user_id, &authored, &(index as i32 + 10)],
            )
            .await
            .unwrap()
            .get(0);
        let issue_id: i32 = conn
            .query_one(
                "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
                 VALUES ($1, $2, 0, 'unread', NOW()) RETURNING id",
                &[&thread_id, &authored],
            )
            .await
            .unwrap()
            .get(0);
        let metadata: Value = serde_json::from_str(&format!(
            "{{\"volume_id\":4051,\"issue_number\":\"{authored}\"}}"
        ))
        .unwrap();
        let identity_id: i32 = conn
            .query_one(
                "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
                 VALUES ('comicvine', 'issue', $1, $2, NOW(), NOW()) RETURNING id",
                &[&cv_id, &metadata],
            )
            .await
            .unwrap()
            .get(0);
        conn.execute(
            "INSERT INTO issue_external_identity_mappings \
             (issue_id, external_identity_id, status, evidence_source, evidence_json, created_at, updated_at) \
             VALUES ($1, $2, 'confirmed', 'synthetic-qa-fixture', '{}'::json, NOW(), NOW())",
            &[&issue_id, &identity_id],
        )
        .await
        .unwrap();
        physical.push(Physical {
            issue_id,
            authored,
            provider: authored,
            cv_id,
        });
    }

    for (index, item) in physical.iter().enumerate() {
        let (status, body) = send(
            &ctx.state,
            authed(
                "PATCH",
                &format!("/api/v2/issues/{}", item.issue_id),
                &ctx.token,
                &ctx.csrf,
                Some(json!({
                    "issue_number_alias": item.provider,
                    "idempotency_key": format!("{unique}-alias-{index}"),
                })),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{body:?}");
        assert_eq!(body["issue"]["issue_number"], item.authored, "{body:?}");
        assert_eq!(body["issue"]["issue_number_alias"], item.provider, "{body:?}");
        assert_eq!(body["issue"]["comicvine_issue_id"], item.cv_id, "{body:?}");
    }

    let all_ids: Vec<i32> = physical.iter().map(|item| item.issue_id).collect();
    let (status, cards) = send(
        &ctx.state,
        authed(
            "POST",
            "/api/v2/issues/cards",
            &ctx.token,
            &ctx.csrf,
            Some(json!({ "issue_ids": all_ids })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{cards:?}");
    let items = cards["items"].as_array().unwrap();
    assert_eq!(items.len(), physical.len(), "{cards:?}");
    for (item, card) in physical.iter().zip(items) {
        assert_eq!(card["issue_number"], item.authored, "{cards:?}");
        assert_eq!(card["issue_number_alias"], item.provider, "{cards:?}");
        assert_eq!(card["provider_issue_number"], item.provider, "{cards:?}");
        assert_eq!(card["comicvine_issue_id"], item.cv_id, "{cards:?}");
        assert_eq!(card["has_confirmed_identity"], true, "{cards:?}");
    }

    // No renumbering and no extra rollable rows: each physical issue remains
    // one unmerged row with its authored label intact.
    let row_count: i64 = conn
        .query_one(
            "SELECT count(*) FROM issues \
             WHERE id = ANY($1::int[]) AND merged_into_issue_id IS NULL",
            &[&all_ids],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(row_count, physical.len() as i64);
    let authored_labels: Vec<String> = conn
        .query(
            "SELECT issue_number FROM issues WHERE id = ANY($1::int[]) ORDER BY id",
            &[&all_ids],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| row.get(0))
        .collect();
    assert_eq!(authored_labels, vec!["1", "2", "3", "4", "5", "1", "2"]);

    let (status, eligible) = send(
        &ctx.state,
        authed(
            "GET",
            "/api/v2/roll/eligible-issue-ids",
            &ctx.token,
            &ctx.csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{eligible:?}");
    let rollable = eligible["issue_ids"].as_array().unwrap();
    for id in &all_ids {
        assert!(rollable.contains(&json!(id)), "{eligible:?}");
    }

    // Verified evidence only: a differing volume plus a non-matching story arc
    // must not be reported as a duplicate pair.
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
    assert_eq!(detected["groups"].as_array().unwrap().len(), 0, "{detected:?}");
}
