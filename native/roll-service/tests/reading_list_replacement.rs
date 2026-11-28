#![allow(clippy::unwrap_used, clippy::expect_used)]
//! #4026 DB-backed HTTP regressions for explicit-target CBL replacement.
//!
//! Every test runs the mounted axum router against a disposable PostgreSQL
//! database loaded from the canonical migrations. It proves that the
//! replacement service targets an exact owned list ID, rejects stale/canceled
//! writes atomically, keeps manual extras unless approved, and restores only
//! list membership on Undo without reversing later read events.

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

static NEXT_CLIENT: AtomicUsize = AtomicUsize::new(1);

const SOURCE_LIST_ID: i32 = 4026100;
const TARGET_LIST_ID: i32 = 4026200;
const OTHER_LIST_ID: i32 = 4026201;
const ISSUE_A: i32 = 4026301;
const ISSUE_B: i32 = 4026302;
const ISSUE_MANUAL: i32 = 4026303;
const HASH: &str = "4026-content-hash";
const REVISION: &str = "4026-revision";

struct Fixture {
    state: Arc<AppState>,
    token: String,
    csrf: String,
    _guard: tokio::sync::MutexGuard<'static, ()>,
}

async fn setup() -> Fixture {
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

    let suffix = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let username = format!("replacement-{suffix}");
    let register = Request::builder()
        .method("POST")
        .uri("/api/v2/auth/register")
        .header(
            "x-forwarded-for",
            format!(
                "2001:db8::{:x}",
                NEXT_CLIENT.fetch_add(1, Ordering::Relaxed)
            ),
        )
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            json!({
                "username": username,
                "email": format!("{username}@example.com"),
                "password": "correct-horse-battery",
            })
            .to_string(),
        ))
        .unwrap();
    let response = router(state.clone()).oneshot(register).await.unwrap();
    let status = response.status();
    let csrf = response
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .filter_map(|value| value.to_str().ok())
        .find_map(|value| value.strip_prefix("csrf_token="))
        .and_then(|value| value.split(';').next())
        .unwrap()
        .to_owned();
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    assert_eq!(status, StatusCode::OK, "{body}");
    let token = body["access_token"].as_str().unwrap().to_owned();

    let conn = state.pool.get().await.unwrap();
    let user_id: i32 = conn
        .query_one("SELECT id FROM users WHERE username = $1", &[&username])
        .await
        .unwrap()
        .get(0);

    // Shared CBL source with two resolved occurrences.
    conn.batch_execute(&format!(
        r#"
        INSERT INTO cbl_sources (id, repository, revision_sha, synced_at, created_at, updated_at)
        VALUES (40261, 'JoshCLWren/CBL-ReadingLists', '{REVISION}', NOW(), NOW(), NOW());
        INSERT INTO cbl_source_lists
          (id, source_id, source_path, name, declared_issue_count, content_hash,
           revision_sha, active, created_at, updated_at)
        VALUES ({SOURCE_LIST_ID}, 40261, 'Marvel/AlphaFlight/AlphaFlight.cbl',
                'Alpha Flight', 2, '{HASH}', '{REVISION}', TRUE, NOW(), NOW());
        INSERT INTO external_identities
          (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
        VALUES
          (4026110, 'comicvine', 'issue', '4026-cv-a', '{{}}'::json, NOW(), NOW()),
          (4026111, 'comicvine', 'issue', '4026-cv-b', '{{}}'::json, NOW(), NOW()),
          (4026112, 'comicvine', 'series', '4026-cv-vol', '{{}}'::json, NOW(), NOW());
        INSERT INTO cbl_source_entries
          (id, list_id, "position", series_name, issue_number, volume_year,
           publication_year, external_issue_identity_id, external_series_identity_id, created_at)
        VALUES
          (4026120, {SOURCE_LIST_ID}, 0, 'Alpha Flight', '1', 1983, 1983, 4026110, 4026112, NOW()),
          (4026121, {SOURCE_LIST_ID}, 1, 'Alpha Flight', '2', 1983, 1983, 4026111, 4026112, NOW());

        INSERT INTO threads
          (id, user_id, title, format, issues_remaining, queue_position, status,
           manual_creator_credits, is_test, is_blocked, queue_position_is_manual, created_at)
        VALUES (4026300, {user_id}, 'Alpha Flight', 'Comic', 3, 1, 'active',
                '[]'::json, false, false, false, NOW());
        INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
        VALUES ({ISSUE_A}, 4026300, '1', 'unread', NOW(), 0),
               ({ISSUE_B}, 4026300, '2', 'unread', NOW(), 1),
               ({ISSUE_MANUAL}, 4026300, '3', 'unread', NOW(), 2);
        INSERT INTO issue_external_identity_mappings
          (issue_id, external_identity_id, status, evidence_source, evidence_json, created_at, updated_at)
        SELECT {ISSUE_A}, ei.id, 'confirmed', 'test', '{{}}'::json, NOW(), NOW()
          FROM external_identities ei
          WHERE ei.provider = 'comicvine' AND ei.external_id = '4026-cv-a';
        INSERT INTO issue_external_identity_mappings
          (issue_id, external_identity_id, status, evidence_source, evidence_json, created_at, updated_at)
        SELECT {ISSUE_B}, ei.id, 'confirmed', 'test', '{{}}'::json, NOW(), NOW()
          FROM external_identities ei
          WHERE ei.provider = 'comicvine' AND ei.external_id = '4026-cv-b';

        -- Two identically named owned lists (the #3933 Alpha Flight fixture).
        INSERT INTO custom_cbl_lists
          (id, user_id, name, description, mode, created_at, updated_at, overlap_decisions_updated_at)
        VALUES
          ({TARGET_LIST_ID}, {user_id}, 'Alpha Flight', 'target', 'loose', NOW(), NOW(), NOW()),
          ({OTHER_LIST_ID}, {user_id}, 'Alpha Flight', 'other', 'loose', NOW(), NOW(), NOW());
        INSERT INTO custom_cbl_entries
          (id, list_id, issue_id, position, created_at, is_checkpoint,
           checkpoint_target_issue_ids, gate, skipped)
        VALUES
          (4026400, {TARGET_LIST_ID}, {ISSUE_MANUAL}, 0, NOW(), true, '[]'::json, 'hold', true),
          (4026401, {TARGET_LIST_ID}, {ISSUE_B}, 1, NOW(), false, '[]'::json, 'none', false),
          (4026402, {OTHER_LIST_ID}, {ISSUE_A}, 0, NOW(), false, '[]'::json, 'none', false);
        INSERT INTO custom_cbl_overlap_decisions
          (id, user_id, list_id, continuing_external_identity_id,
           waiting_external_identity_id, created_at, updated_at)
        VALUES (4026410, {user_id}, {TARGET_LIST_ID}, 4026110, 4026111, NOW(), NOW());
        "#
    ))
    .await
    .expect("seed replacement fixture");
    drop(conn);

    Fixture {
        state,
        token,
        csrf,
        _guard: guard,
    }
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

async fn post(fixture: &Fixture, uri: &str, body: Value) -> (StatusCode, Value) {
    send(
        &fixture.state,
        Request::builder()
            .method("POST")
            .uri(uri)
            .header(header::AUTHORIZATION, format!("Bearer {}", fixture.token))
            .header("x-csrf-token", &fixture.csrf)
            .header(header::COOKIE, format!("csrf_token={}", fixture.csrf))
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(body.to_string()))
            .unwrap(),
    )
    .await
}

fn preview_body() -> Value {
    json!({
        "source_list_id": SOURCE_LIST_ID,
        "series_decisions": {},
        "entry_decisions": {},
    })
}

async fn list_ids(state: &Arc<AppState>, list_id: i32) -> Vec<i32> {
    let conn = state.pool.get().await.unwrap();
    conn.query(
        "SELECT issue_id FROM custom_cbl_entries WHERE list_id = $1 ORDER BY position, id",
        &[&list_id],
    )
    .await
    .unwrap()
    .iter()
    .map(|row| row.get::<_, i32>(0))
    .collect()
}

async fn updated_at(state: &Arc<AppState>, list_id: i32) -> String {
    let conn = state.pool.get().await.unwrap();
    conn.query_one(
        "SELECT updated_at::text FROM custom_cbl_lists WHERE id = $1",
        &[&list_id],
    )
    .await
    .unwrap()
    .get(0)
}

#[tokio::test]
async fn preview_is_read_only_and_targets_explicit_owned_list() {
    let fixture = setup().await;
    let before_target = list_ids(&fixture.state, TARGET_LIST_ID).await;
    let before_other = list_ids(&fixture.state, OTHER_LIST_ID).await;

    let (status, body) = post(
        &fixture,
        &format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements:preview"),
        preview_body(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{status} {body}");
    assert_eq!(body["target_list_id"], TARGET_LIST_ID, "{body}");
    assert_eq!(body["source_list_id"], SOURCE_LIST_ID, "{body}");
    assert_eq!(body["content_hash"], HASH, "{body}");
    assert_eq!(body["revision_sha"], REVISION, "{body}");
    assert_eq!(body["before"].as_array().unwrap().len(), 2, "{body}");
    assert_eq!(body["after"].as_array().unwrap().len(), 3, "{body}");
    assert_eq!(
        body["omitted_manual_issue_ids"],
        json!([ISSUE_MANUAL]),
        "{body}"
    );

    // A canceled preview writes nothing at all.
    assert_eq!(
        list_ids(&fixture.state, TARGET_LIST_ID).await,
        before_target
    );
    assert_eq!(list_ids(&fixture.state, OTHER_LIST_ID).await, before_other);
}

#[tokio::test]
async fn commit_targets_one_list_without_touching_same_named_other_list() {
    let fixture = setup().await;
    let token = updated_at(&fixture.state, TARGET_LIST_ID).await;
    let body = json!({
        "source_list_id": SOURCE_LIST_ID,
        "content_hash": HASH,
        "revision_sha": REVISION,
        "expected_updated_at": token,
        "issue_ids": [ISSUE_A, ISSUE_B, ISSUE_MANUAL],
        "idempotency_key": "same-name-alpha-flight",
    });

    let (status, result) = post(
        &fixture,
        &format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements"),
        body,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{status} {result}");
    assert_eq!(result["target_list_id"], TARGET_LIST_ID, "{result}");
    assert!(result["snapshot_id"].as_i64().unwrap() > 0, "{result}");

    assert_eq!(
        list_ids(&fixture.state, TARGET_LIST_ID).await,
        vec![ISSUE_A, ISSUE_B, ISSUE_MANUAL],
        "the explicitly selected list must be replaced in source order"
    );
    assert_eq!(
        list_ids(&fixture.state, OTHER_LIST_ID).await,
        vec![ISSUE_A],
        "an identically named list must never be targeted by name"
    );
}

#[tokio::test]
async fn stale_version_and_stale_source_are_atomic_no_ops() {
    let fixture = setup().await;
    let before = list_ids(&fixture.state, TARGET_LIST_ID).await;

    let (status, body) = post(
        &fixture,
        &format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements"),
        json!({
            "source_list_id": SOURCE_LIST_ID,
            "content_hash": HASH,
            "revision_sha": REVISION,
            "expected_updated_at": "2000-01-01T00:00:00Z",
            "issue_ids": [ISSUE_A],
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{status} {body}");
    assert_eq!(
        body["detail"]["code"], "reading_list_replacement_stale",
        "{body}"
    );

    let token = updated_at(&fixture.state, TARGET_LIST_ID).await;
    let (status, body) = post(
        &fixture,
        &format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements"),
        json!({
            "source_list_id": SOURCE_LIST_ID,
            "content_hash": "stale-hash",
            "revision_sha": REVISION,
            "expected_updated_at": token,
            "issue_ids": [ISSUE_A],
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{status} {body}");
    assert_eq!(
        body["detail"]["code"], "cbl_source_revision_stale",
        "{body}"
    );
    assert_eq!(list_ids(&fixture.state, TARGET_LIST_ID).await, before);
    let conn = fixture.state.pool.get().await.unwrap();
    let snapshots: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM custom_cbl_replacement_snapshots WHERE list_id = $1",
            &[&TARGET_LIST_ID],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(snapshots, 0, "stale commits must not retain a snapshot");
}

#[tokio::test]
async fn omitted_manual_entry_requires_explicit_approval() {
    let fixture = setup().await;
    let token = updated_at(&fixture.state, TARGET_LIST_ID).await;
    let (status, body) = post(
        &fixture,
        &format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements"),
        json!({
            "source_list_id": SOURCE_LIST_ID,
            "content_hash": HASH,
            "revision_sha": REVISION,
            "expected_updated_at": token,
            "issue_ids": [ISSUE_A, ISSUE_B],
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{status} {body}");
    assert_eq!(
        body["detail"]["code"], "manual_entry_removal_requires_confirmation",
        "{body}"
    );
    assert_eq!(
        list_ids(&fixture.state, TARGET_LIST_ID).await,
        vec![ISSUE_MANUAL, ISSUE_B]
    );

    // With explicit approval the reviewed membership is applied exactly.
    let token = updated_at(&fixture.state, TARGET_LIST_ID).await;
    let (status, body) = post(
        &fixture,
        &format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements"),
        json!({
            "source_list_id": SOURCE_LIST_ID,
            "content_hash": HASH,
            "revision_sha": REVISION,
            "expected_updated_at": token,
            "issue_ids": [ISSUE_A, ISSUE_B],
            "confirm_manual_removals": true,
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{status} {body}");
    assert_eq!(
        list_ids(&fixture.state, TARGET_LIST_ID).await,
        vec![ISSUE_A, ISSUE_B]
    );
}

#[tokio::test]
async fn undo_restores_only_list_membership_and_keeps_later_read_event() {
    let fixture = setup().await;
    let token = updated_at(&fixture.state, TARGET_LIST_ID).await;
    let (status, body) = post(
        &fixture,
        &format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements"),
        json!({
            "source_list_id": SOURCE_LIST_ID,
            "content_hash": HASH,
            "revision_sha": REVISION,
            "expected_updated_at": token,
            "issue_ids": [ISSUE_A, ISSUE_B, ISSUE_MANUAL],
            "overlap_decisions": [
                {"continuing_external_identity_id": 4026111, "waiting_external_identity_id": 4026110}
            ],
            "idempotency_key": "undo-flow",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{status} {body}");
    let snapshot_id = body["snapshot_id"].as_i64().unwrap();

    let conn = fixture.state.pool.get().await.unwrap();
    let committed_overlap: i32 = conn
        .query_one(
            "SELECT continuing_external_identity_id FROM custom_cbl_overlap_decisions WHERE list_id = $1",
            &[&TARGET_LIST_ID],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        committed_overlap, 4026111,
        "approved overlap must be committed"
    );
    drop(conn);

    // A read event that happens after the replacement is independent history.
    let conn = fixture.state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO events (id, type, timestamp, issue_id) VALUES (4026500, 'read', NOW(), $1)",
        &[&ISSUE_A],
    )
    .await
    .unwrap();
    drop(conn);

    let token = updated_at(&fixture.state, TARGET_LIST_ID).await;
    let (status, body) = post(
        &fixture,
        &format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements:undo"),
        json!({
            "expected_updated_at": token,
            "snapshot_id": snapshot_id,
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{status} {body}");
    assert_eq!(
        body["restored_issue_ids"],
        json!([ISSUE_MANUAL, ISSUE_B]),
        "{body}"
    );
    assert_eq!(
        list_ids(&fixture.state, TARGET_LIST_ID).await,
        vec![ISSUE_MANUAL, ISSUE_B]
    );
    assert_eq!(
        list_ids(&fixture.state, OTHER_LIST_ID).await,
        vec![ISSUE_A],
        "Undo must not affect another owned list"
    );

    let conn = fixture.state.pool.get().await.unwrap();
    let intent_row = conn
        .query_one(
            "SELECT is_checkpoint, gate, skipped FROM custom_cbl_entries
             WHERE list_id = $1 AND issue_id = $2",
            &[&TARGET_LIST_ID, &ISSUE_MANUAL],
        )
        .await
        .unwrap();
    let restored_intent = (
        intent_row.get::<_, bool>(0),
        intent_row.get::<_, String>(1),
        intent_row.get::<_, bool>(2),
    );
    assert_eq!(
        restored_intent,
        (true, "hold".to_string(), true),
        "Undo must restore exact gating decisions, not just membership"
    );
    let restored_overlap: i32 = conn
        .query_one(
            "SELECT continuing_external_identity_id FROM custom_cbl_overlap_decisions
             WHERE list_id = $1",
            &[&TARGET_LIST_ID],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        restored_overlap, 4026110,
        "Undo must restore the saved overlap choice"
    );

    let events: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM events WHERE issue_id = $1",
            &[&ISSUE_A],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(events, 1, "Undo must not reverse a later read event");
    let undone: bool = conn
        .query_one(
            "SELECT undone_at IS NOT NULL FROM custom_cbl_replacement_snapshots WHERE id = $1",
            &[&(snapshot_id as i32)],
        )
        .await
        .unwrap()
        .get(0);
    assert!(undone, "the snapshot must be consumed exactly once");
}

#[tokio::test]
async fn duplicate_commit_replays_one_snapshot_and_undo_is_stale_guarded() {
    let fixture = setup().await;
    let token = updated_at(&fixture.state, TARGET_LIST_ID).await;
    let body = json!({
        "source_list_id": SOURCE_LIST_ID,
        "content_hash": HASH,
        "revision_sha": REVISION,
        "expected_updated_at": token,
        "issue_ids": [ISSUE_A, ISSUE_B, ISSUE_MANUAL],
        "idempotency_key": "duplicate-submit",
    });
    let (first_status, first) = post(
        &fixture,
        &format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements"),
        body.clone(),
    )
    .await;
    assert_eq!(first_status, StatusCode::OK, "{first_status} {first}");

    // The list version changed, so the identical retry's stale token normally
    // fails; the idempotency replay must win and return the original snapshot.
    let (second_status, second) = post(
        &fixture,
        &format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements"),
        body,
    )
    .await;
    assert_eq!(second_status, StatusCode::OK, "{second_status} {second}");
    assert_eq!(second["replayed"], true, "{second}");
    assert_eq!(
        second["snapshot_id"], first["snapshot_id"],
        "a retry must not create a second replacement"
    );

    let conn = fixture.state.pool.get().await.unwrap();
    let count: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM custom_cbl_replacement_snapshots WHERE list_id = $1",
            &[&TARGET_LIST_ID],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(count, 1, "{count}");
    drop(conn);

    // Undo with the pre-replacement token must fail closed with no writes.
    let (status, body) = post(
        &fixture,
        &format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements:undo"),
        json!({"expected_updated_at": token}),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{status} {body}");
    assert_eq!(body["detail"]["code"], "replacement_undo_stale", "{body}");
    assert_eq!(
        list_ids(&fixture.state, TARGET_LIST_ID).await,
        vec![ISSUE_A, ISSUE_B, ISSUE_MANUAL]
    );
}

#[tokio::test]
async fn duplicate_undo_replays_the_original_restoration() {
    let fixture = setup().await;
    let token = updated_at(&fixture.state, TARGET_LIST_ID).await;
    let (status, commit) = post(
        &fixture,
        &format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements"),
        json!({
            "source_list_id": SOURCE_LIST_ID,
            "content_hash": HASH,
            "revision_sha": REVISION,
            "expected_updated_at": token,
            "issue_ids": [ISSUE_A, ISSUE_B, ISSUE_MANUAL],
            "idempotency_key": "undo-retry-commit",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{status} {commit}");

    let undo_body = json!({
        "expected_updated_at": commit["updated_at"],
        "snapshot_id": commit["snapshot_id"],
        "idempotency_key": "undo-retry-key",
    });
    let uri = format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements:undo");
    let (first_status, first) = post(&fixture, &uri, undo_body.clone()).await;
    assert_eq!(first_status, StatusCode::OK, "{first_status} {first}");
    assert_eq!(first["replayed"], false, "{first}");

    // The first Undo advanced `updated_at`, but an exact retry must replay the
    // stored Undo response rather than fail the stale-version guard.
    let (second_status, second) = post(&fixture, &uri, undo_body).await;
    assert_eq!(second_status, StatusCode::OK, "{second_status} {second}");
    for field in ["snapshot_id", "updated_at", "restored_issue_ids"] {
        assert_eq!(second[field], first[field], "{field}: {first} vs {second}");
    }
    assert_eq!(second["replayed"], true, "{second}");
    assert_eq!(
        list_ids(&fixture.state, TARGET_LIST_ID).await,
        vec![ISSUE_MANUAL, ISSUE_B],
        "a replayed Undo must not write the list again"
    );

    let conn = fixture.state.pool.get().await.unwrap();
    let undone: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM custom_cbl_replacement_snapshots
             WHERE list_id = $1 AND undone_at IS NOT NULL",
            &[&TARGET_LIST_ID],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(undone, 1, "{undone}");
}

#[tokio::test]
async fn sibling_commit_writers_racing_one_key_replay_one_snapshot() {
    let fixture = setup().await;
    let token = updated_at(&fixture.state, TARGET_LIST_ID).await;
    let body = json!({
        "source_list_id": SOURCE_LIST_ID,
        "content_hash": HASH,
        "revision_sha": REVISION,
        "expected_updated_at": token,
        "issue_ids": [ISSUE_A, ISSUE_B, ISSUE_MANUAL],
        "idempotency_key": "concurrent-sibling-writers",
    });
    let uri = format!("/api/v2/reading-lists/{TARGET_LIST_ID}/replacements");

    // The user-row lock must serialize sibling writers and let the loser replay
    // the winner's snapshot instead of racing a second replacement.
    let (first, second) = tokio::join!(
        post(&fixture, &uri, body.clone()),
        post(&fixture, &uri, body)
    );
    assert_eq!(first.0, StatusCode::OK, "{} {}", first.0, first.1);
    assert_eq!(second.0, StatusCode::OK, "{} {}", second.0, second.1);
    assert_eq!(
        first.1["snapshot_id"], second.1["snapshot_id"],
        "both sibling writers must observe one snapshot: {:?} {:?}",
        first.1, second.1
    );
    assert!(
        first.1["replayed"] == true || second.1["replayed"] == true,
        "exactly one sibling must replay the committed snapshot"
    );

    let conn = fixture.state.pool.get().await.unwrap();
    let snapshots: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM custom_cbl_replacement_snapshots WHERE list_id = $1",
            &[&TARGET_LIST_ID],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(snapshots, 1, "{snapshots}");
    assert_eq!(
        list_ids(&fixture.state, TARGET_LIST_ID).await,
        vec![ISSUE_A, ISSUE_B, ISSUE_MANUAL]
    );
}
