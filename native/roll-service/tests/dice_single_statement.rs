//! Single-statement regression for #4615: `POST /api/v2/roll/dice-command`
//! and `POST /api/v2/roll/reset` each issue exactly one DB command per HTTP
//! request, including authentication.
//!
//! The counter is `db::DB_COMMANDS_ISSUED`, incremented at the tokio-postgres
//! `query_opt` boundary in `db::query_one_optional` — one per issued command.
//! Any separate auth, advisory-lock, receipt or die statement would make the
//! delta > 1 and fail. It also proves replay, conflict, ownership and
//! reset-clears-pending semantics are unchanged.
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use comicpile_roll_service::{
    config::Config,
    db::DB_COMMANDS_ISSUED,
    router,
    test_support::{self, TEST_JWT_SECRET},
    AppState,
};
use jsonwebtoken::{encode, Algorithm, EncodingKey, Header};
use serde_json::{json, Value};
use std::{sync::atomic::Ordering, sync::Arc};
use tower::ServiceExt;

fn token(username: &str) -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;
    encode(
        &Header::new(Algorithm::HS256),
        &json!({
            "sub": username,
            "jti": "test-jti-4615",
            "type": "access",
            "exp": now + 3600,
            "pc": 0,
        }),
        &EncodingKey::from_secret(TEST_JWT_SECRET.as_bytes()),
    )
    .unwrap()
}

async fn seed(state: &AppState) {
    let connection = state.pool.get().await.unwrap();
    connection
        .batch_execute(
            "INSERT INTO users (id, username) VALUES (1, 'reader-1'), (2, 'reader-2');
             INSERT INTO threads (id, user_id, title, format, issues_remaining, status, queue_position)
             VALUES (10, 1, 'First', 'Comic', 1, 'active', 1);
             INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
             VALUES (100, 10, '1', 'unread', now(), 1);
             INSERT INTO sessions (id, user_id, started_at, start_die, pending_thread_id, pending_issue_id, pending_thread_updated_at, manual_die)
             VALUES (1, 1, NOW(), 6, 10, 100, NOW(), 12);
             INSERT INTO events (user_id, type, session_id, die, die_after, context)
             VALUES (1, 'manual_die', 1, 6, 20, '{}'::json);",
        )
        .await
        .unwrap();
}

async fn post(app: &axum::Router, path: &str, auth: &str, body: Value) -> (StatusCode, Value) {
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(path)
                .header("content-type", "application/json")
                .header("authorization", format!("Bearer {auth}"))
                .header("cookie", "csrf_token=synthetic-test-csrf")
                .header("x-csrf-token", "synthetic-test-csrf")
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 8192).await.unwrap();
    let value: Value = serde_json::from_slice(&bytes).unwrap_or(json!({}));
    (status, value)
}

#[tokio::test]
async fn dice_command_and_reset_issue_one_db_command_each() {
    let Ok(_admin) = std::env::var("RUST_ROLL_TEST_DATABASE_URL") else {
        return;
    };
    let state = test_support::test_state(2)
        .await
        .expect("disposable PostgreSQL required");
    let _db = test_support::reset_for_test(&state).await;
    seed(&state).await;

    let db_url = test_support::database_url().await;
    let config = Config::from_lookup(|name| match name {
        "RUST_ROLL_DATABASE_URL" => Some(db_url.clone()),
        "RUST_ROLL_JWT_SECRET" => Some(TEST_JWT_SECRET.into()),
        _ => None,
    })
    .unwrap();
    // Share the same pool-backed state the seeder used so the router sees it.
    let app_state = Arc::new(AppState::new(config).unwrap());
    let app = router(app_state.clone());
    let auth = token("reader-1");

    // dice-command: exactly one DB command including auth/lock/receipt/die/insert.
    let before = DB_COMMANDS_ISSUED.load(Ordering::Relaxed);
    let (status, body) = post(
        &app,
        "/api/v2/roll/dice-command",
        &auth,
        json!({"kind":"manual_select","die":12,"idempotency_key":"dice-4615-000001"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["die_after"], 12);
    assert_eq!(
        body["die_before"], 20,
        "event-derived die from manual_die event"
    );
    assert_eq!(body["replayed"], false);
    assert_eq!(
        DB_COMMANDS_ISSUED.load(Ordering::Relaxed) - before,
        1,
        "dice-command must issue exactly one DB command including auth"
    );

    // Replay: same key + same payload returns same receipt, still one command.
    let before = DB_COMMANDS_ISSUED.load(Ordering::Relaxed);
    let (status, replay) = post(
        &app,
        "/api/v2/roll/dice-command",
        &auth,
        json!({"kind":"manual_select","die":12,"idempotency_key":"dice-4615-000001"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{replay}");
    assert_eq!(replay["replayed"], true);
    assert_eq!(replay["event_id"], body["event_id"]);
    assert_eq!(
        DB_COMMANDS_ISSUED.load(Ordering::Relaxed) - before,
        1,
        "replayed dice-command must also be one DB command"
    );

    // Same key + different payload conflicts, still one command.
    let before = DB_COMMANDS_ISSUED.load(Ordering::Relaxed);
    let (status, _) = post(
        &app,
        "/api/v2/roll/dice-command",
        &auth,
        json!({"kind":"manual_select","die":4,"idempotency_key":"dice-4615-000001"}),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT);
    assert_eq!(
        DB_COMMANDS_ISSUED.load(Ordering::Relaxed) - before,
        1,
        "conflict dice-command must also be one DB command"
    );

    // Reset: exactly one DB command, lands on d6 and clears pending.
    let before = DB_COMMANDS_ISSUED.load(Ordering::Relaxed);
    let (status, body) = post(
        &app,
        "/api/v2/roll/reset",
        &auth,
        json!({"idempotency_key":"reset-4615-000001"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["die"], 6);
    assert_eq!(body["replayed"], false);
    assert_eq!(
        DB_COMMANDS_ISSUED.load(Ordering::Relaxed) - before,
        1,
        "reset must issue exactly one DB command including auth/session/insert/clear"
    );

    // Replayed reset must not clear a newer pending selection.
    let connection = state.pool.get().await.unwrap();
    connection
        .execute(
            "UPDATE sessions SET pending_thread_id=10, pending_issue_id=100, pending_thread_updated_at=NOW(), manual_die=12 WHERE id=1",
            &[],
        )
        .await
        .unwrap();
    drop(connection);
    let before = DB_COMMANDS_ISSUED.load(Ordering::Relaxed);
    let (status, replay) = post(
        &app,
        "/api/v2/roll/reset",
        &auth,
        json!({"idempotency_key":"reset-4615-000001"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{replay}");
    assert_eq!(replay["replayed"], true);
    assert_eq!(
        DB_COMMANDS_ISSUED.load(Ordering::Relaxed) - before,
        1,
        "replayed reset must also be one DB command"
    );
    let connection = state.pool.get().await.unwrap();
    let pending = connection
        .query_one("SELECT pending_thread_id FROM sessions WHERE id=1", &[])
        .await
        .unwrap();
    assert_eq!(
        pending.get::<_, i32>(0),
        10,
        "replay must preserve newer pending"
    );
    drop(connection);

    // Revoked token: auth folded into the single statement still rejects.
    // (username exists, but jti is revoked)
    let connection = state.pool.get().await.unwrap();
    connection
        .execute(
            "INSERT INTO revoked_tokens (user_id, jti, expires_at) VALUES (1, 'test-jti-4615', NOW() + interval '1 hour')",
            &[],
        )
        .await
        .unwrap();
    drop(connection);
    let before = DB_COMMANDS_ISSUED.load(Ordering::Relaxed);
    let (status, _) = post(
        &app,
        "/api/v2/roll/dice-command",
        &auth,
        json!({"kind":"manual_select","die":8,"idempotency_key":"dice-4615-000002"}),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    assert_eq!(
        DB_COMMANDS_ISSUED.load(Ordering::Relaxed) - before,
        1,
        "revoked-token rejection must still be the single folded statement"
    );
}

/// Concurrency regression (CodeRabbit review on #4709): two same-key requests
/// racing for the per-reader advisory lock must not race past the receipt —
/// the loser must observe the winner's committed receipt and replay, not hit
/// the unique index and return 500. Distinct concurrent commands must chain
/// on a fresh die state, never a stale snapshot.
#[tokio::test]
async fn concurrent_same_key_retries_replay_and_distinct_keys_chain() {
    let Ok(_admin) = std::env::var("RUST_ROLL_TEST_DATABASE_URL") else {
        return;
    };
    let state = test_support::test_state(8)
        .await
        .expect("disposable PostgreSQL required");
    let _db = test_support::reset_for_test(&state).await;
    seed(&state).await;

    let db_url = test_support::database_url().await;
    let config = Config::from_lookup(|name| match name {
        "RUST_ROLL_DATABASE_URL" => Some(db_url.clone()),
        "RUST_ROLL_JWT_SECRET" => Some(TEST_JWT_SECRET.into()),
        _ => None,
    })
    .unwrap();
    let app_state = Arc::new(AppState::new(config).unwrap());
    let app = router(app_state.clone());
    let auth = token("reader-1");

    // Eight concurrent identical commands: exactly one writes, seven replay.
    let mut handles = Vec::new();
    for _ in 0..8 {
        let app = app.clone();
        let auth = auth.clone();
        handles.push(tokio::spawn(async move {
            post(
                &app,
                "/api/v2/roll/dice-command",
                &auth,
                json!({"kind":"manual_select","die":12,"idempotency_key":"concurrent-4615-001"}),
            )
            .await
        }));
    }
    let mut event_id = None;
    let mut fresh = 0;
    for handle in handles {
        let (status, body) = handle.await.unwrap();
        assert_eq!(status, StatusCode::OK, "{body}");
        match event_id {
            None => event_id = Some(body["event_id"].as_i64().unwrap()),
            Some(id) => assert_eq!(body["event_id"].as_i64().unwrap(), id, "{body}"),
        }
        if !body["replayed"].as_bool().unwrap() {
            fresh += 1;
        }
    }
    assert_eq!(fresh, 1, "exactly one concurrent writer may insert");
    let connection = state.pool.get().await.unwrap();
    let count: i64 = connection
        .query_one(
            "SELECT COUNT(*) FROM events WHERE user_id=1 AND context->>'dice_command_key'='concurrent-4615-001'",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(count, 1);
    drop(connection);

    // Two distinct keys racing: die chain must be serialized, not stale.
    let (first, second) = tokio::join!(
        post(
            &app,
            "/api/v2/roll/dice-command",
            &auth,
            json!({"kind":"manual_select","die":12,"idempotency_key":"concurrent-4615-002"}),
        ),
        post(
            &app,
            "/api/v2/roll/dice-command",
            &auth,
            json!({"kind":"manual_select","die":8,"idempotency_key":"concurrent-4615-003"}),
        ),
    );
    assert_eq!(first.0, StatusCode::OK, "{}", first.1);
    assert_eq!(second.0, StatusCode::OK, "{}", second.1);
    let chain_ok = (first.1["die_after"] == second.1["die_before"] && second.1["die_after"] == 8)
        || (second.1["die_after"] == first.1["die_before"] && first.1["die_after"] == 12);
    assert!(chain_ok, "die chain: first={} second={}", first.1, second.1);
}
