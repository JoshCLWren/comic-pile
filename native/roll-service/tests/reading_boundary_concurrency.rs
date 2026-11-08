//! Single-snapshot concurrency regression for `POST /api/v2/reading-boundaries`
//! (#4347 gap G5).
//!
//! PR #4794 fixed the split-snapshot inconsistency by running boundary labels
//! and Option E eligibility inputs in one `REPEATABLE READ` read-only
//! transaction (`reading_boundary.rs`). No test proved that a concurrent
//! reading-list mutation cannot produce an explanation mixing pre-mutation
//! labels with post-mutation eligibility.
//!
//! Canonical Alembic schema only: `test_support` loads the real `pg_dump`
//! fixture and connects with the DML-only role; every row is allocated through
//! `INSERT ... RETURNING` on the disposable database.
//!
//! The race is deterministic. A writer transaction holds
//! `LOCK TABLE custom_cbl_entries IN ACCESS EXCLUSIVE MODE` and deletes the
//! waiting strict-list entry inside that same transaction. The in-flight
//! boundaries
//! request establishes its repeatable-read snapshot on its first label
//! queries, then blocks on the entries lock (observed through
//! `pg_stat_activity`, never sleeps). The writer commits the mutation while
//! the reader is blocked; the reader must still answer from the
//! pre-mutation snapshot. A split implementation would instead return the
//! post-mutation explanation (available, entry-less) and fail below.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, test_support, AppState};
use serde_json::{json, Value};
use std::sync::Arc;
use tower::ServiceExt;

const PASSWORD: &str = "correct-horse-battery";

fn state(url: &str) -> Arc<AppState> {
    Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.into()),
                "RUST_ROLL_JWT_SECRET" => Some(test_support::TEST_JWT_SECRET.into()),
                "RUST_ROLL_POOL_SIZE" => Some("4".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    )
}

async fn database() -> Option<(Arc<AppState>, tokio::sync::MutexGuard<'static, ()>)> {
    let url = test_support::database_url().await;
    std::env::set_var("OPTION_E_ENABLED", "true");
    std::env::set_var(
        "OPTION_E_APPROVED_PREVIEW",
        "reading-boundary-concurrency-4347-g5",
    );
    let state = state(&url);
    let guard = test_support::reset_for_test(&state).await;
    Some((state, guard))
}

async fn register(state: &Arc<AppState>, username: &str) -> (String, String, i32) {
    use std::sync::atomic::{AtomicU16, Ordering};
    static NEXT_IP: AtomicU16 = AtomicU16::new(1);
    let ip = NEXT_IP.fetch_add(1, Ordering::Relaxed);
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v2/auth/register")
                .header(header::CONTENT_TYPE, "application/json")
                .header("x-forwarded-for", format!("198.51.100.{ip}"))
                .body(Body::from(
                    json!({
                        "username": username,
                        "email": format!("{username}@example.com"),
                        "password": PASSWORD
                    })
                    .to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let csrf = response
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .filter_map(|value| value.to_str().ok())
        .find_map(|cookie| cookie.strip_prefix("csrf_token="))
        .and_then(|rest| rest.split(';').next())
        .expect("register sets a CSRF cookie")
        .to_string();
    let body = to_bytes(response.into_body(), 65536).await.unwrap();
    let value: Value = serde_json::from_slice(&body).unwrap();
    let token = value["access_token"].as_str().unwrap().to_string();
    let id = user_id(state, username).await;
    (token, csrf, id)
}

async fn user_id(state: &Arc<AppState>, username: &str) -> i32 {
    let conn = state.pool.get().await.unwrap();
    conn.query_one("SELECT id FROM users WHERE username=$1", &[&username])
        .await
        .unwrap()
        .get(0)
}

async fn send(
    state: &Arc<AppState>,
    auth: (&str, &str),
    method: &str,
    path: &str,
    body: Option<Value>,
) -> (StatusCode, Value) {
    let (token, csrf) = auth;
    let mut builder = Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"));
    if body.is_some() {
        builder = builder.header(header::CONTENT_TYPE, "application/json");
    }
    let response = router(state.clone())
        .oneshot(
            builder
                .body(body.map_or_else(Body::empty, |value| Body::from(value.to_string())))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), 1 << 20).await.unwrap();
    let value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, value)
}

/// An unread frontier `#2` in each of two threads, where the second thread's
/// next issue sits behind an `after_previous` gate on the first thread's
/// unread frontier in a strict list.
///
/// ```text
/// Fourth World: #1 (read), #2 (unread frontier)
/// JLI:          #1 (read), #2 (unread frontier, after_previous behind Fourth #2)
/// ```
///
/// Returns `(waiting_thread, waiting_issue, list)`.
async fn seed_strict_wait(state: &Arc<AppState>, owner: i32) -> (i32, i32, i32) {
    let conn = state.pool.get().await.unwrap();
    let sources = conn
        .query_one(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, created_at)
             VALUES ($1,'comic',1,1,'active',$2,NOW()) RETURNING id",
            &[&"Fourth World", &owner],
        )
        .await
        .unwrap()
        .get(0);
    let waiting: i32 = conn
        .query_one(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id, created_at)
             VALUES ($1,'comic',1,2,'active',$2,NOW()) RETURNING id",
            &[&"JLI", &owner],
        )
        .await
        .unwrap()
        .get(0);
    let source_read: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, status, read_at, created_at, position)
             VALUES ($1,'1','read',NOW(),NOW(),1) RETURNING id",
            &[&sources],
        )
        .await
        .unwrap()
        .get(0);
    let source_frontier: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, status, created_at, position)
             VALUES ($1,'2','unread',NOW(),2) RETURNING id",
            &[&sources],
        )
        .await
        .unwrap()
        .get(0);
    let waiting_read: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, status, read_at, created_at, position)
             VALUES ($1,'1','read',NOW(),NOW(),1) RETURNING id",
            &[&waiting],
        )
        .await
        .unwrap()
        .get(0);
    let waiting_frontier: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id, issue_number, status, created_at, position)
             VALUES ($1,'2','unread',NOW(),2) RETURNING id",
            &[&waiting],
        )
        .await
        .unwrap()
        .get(0);
    for (thread, frontier) in [(sources, source_frontier), (waiting, waiting_frontier)] {
        conn.execute(
            "UPDATE threads SET next_unread_issue_id=$1 WHERE id=$2",
            &[&frontier, &thread],
        )
        .await
        .unwrap();
    }
    let list: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, mode, created_at, updated_at)
             VALUES ($1,'JLI strict','strict',NOW(),NOW()) RETURNING id",
            &[&owner],
        )
        .await
        .unwrap()
        .get(0);
    for (position, issue, gate) in [
        (1, waiting_read, "none"),
        (2, source_frontier, "none"),
        (3, waiting_frontier, "after_previous"),
    ] {
        conn.execute(
            "INSERT INTO custom_cbl_entries (list_id, issue_id, position, created_at, gate)
             VALUES ($1,$2,$3,NOW(),$4)",
            &[&list, &issue, &position, &gate],
        )
        .await
        .unwrap();
    }
    let _ = source_read;
    (waiting, waiting_frontier, list)
}

/// A concurrent reading-list mutation committed while the boundaries request
/// is in flight must not split labels and eligibility across two snapshots.
#[tokio::test]
async fn concurrent_list_mutation_cannot_split_boundary_snapshot() {
    let Some((state, _db)) = database().await else {
        return;
    };
    let (token, csrf, owner) = register(&state, "boundary-g5-reader").await;
    let (thread, waiting_issue, list) = seed_strict_wait(&state, owner).await;

    let boundaries = |state: Arc<AppState>, token: String, csrf: String| async move {
        send(
            &state,
            (&token, &csrf),
            "POST",
            "/api/v2/reading-boundaries",
            Some(json!({"thread_ids": [thread]})),
        )
        .await
    };

    // Canonical pre-mutation explanation: blocked behind the after_previous
    // gate, with the waiting issue still listed in the strict list's labels.
    let (pre_status, expected_pre) = boundaries(state.clone(), token.clone(), csrf.clone()).await;
    assert_eq!(pre_status, StatusCode::OK, "{expected_pre}");
    let pre_key = thread.to_string();
    let explanation = &expected_pre["threads"][&pre_key];
    assert_eq!(explanation["state"], "blocked", "{expected_pre}");
    assert!(
        explanation["blockers"]
            .as_array()
            .is_some_and(|blockers| blockers
                .iter()
                .any(|blocker| blocker["kind"] == "after_previous")),
        "pre-mutation blockers must include the after_previous gate: {expected_pre}"
    );
    assert_eq!(explanation["next"]["issue"]["issue_id"], waiting_issue);
    assert!(
        explanation["next"]["issue"]["reading_lists"]
            .as_array()
            .is_some_and(|lists| lists.iter().any(|entry| entry["list_id"] == list)),
        "pre-mutation labels must list the waiting issue in the strict list: {expected_pre}"
    );

    // The writer guards the entries table and removes the waiting entry in
    // the same transaction, while the reader is blocked behind the lock.
    let mut writer = state.pool.get().await.unwrap();
    let writer_tx = writer.transaction().await.unwrap();
    writer_tx
        .execute(
            "LOCK TABLE custom_cbl_entries IN ACCESS EXCLUSIVE MODE",
            &[],
        )
        .await
        .unwrap();
    writer_tx
        .execute(
            "DELETE FROM custom_cbl_entries WHERE list_id=$1 AND issue_id=$2",
            &[&list, &waiting_issue],
        )
        .await
        .unwrap();

    let task = tokio::spawn(boundaries(state.clone(), token.clone(), csrf.clone()));

    // Wait for the handler to block on the writer's lock. Its repeatable-read
    // snapshot is already established at this point, so the following commit
    // must stay invisible to it. This is a real PostgreSQL lock wait rather
    // than a timing-dependent sleep.
    let observer = state.pool.get().await.unwrap();
    tokio::time::timeout(std::time::Duration::from_secs(8), async {
        loop {
            let blocked: i64 = observer
                .query_one(
                    "SELECT count(*) FROM pg_stat_activity
                     WHERE wait_event_type='Lock' AND query LIKE '%custom_cbl_entries%'",
                    &[],
                )
                .await
                .unwrap()
                .get(0);
            if blocked > 0 {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("boundaries snapshot must block on the writer's entries lock");

    // Commit the mutation: waiting entry removed. A fresh snapshot sees the
    // available, entry-less explanation; the in-flight reader must not.
    writer_tx.commit().await.unwrap();
    drop(writer);
    drop(observer);

    let (in_flight_status, in_flight) = task.await.unwrap();
    assert_eq!(in_flight_status, StatusCode::OK, "{in_flight}");
    assert_eq!(
        in_flight, expected_pre,
        "a concurrent mutation must not split the boundary snapshot: labels and \
         eligibility must come from the same pre-mutation snapshot"
    );

    let (post_status, expected_post) = boundaries(state.clone(), token, csrf).await;
    assert_eq!(post_status, StatusCode::OK, "{expected_post}");
    assert_eq!(
        expected_post["threads"][&pre_key]["state"], "available",
        "{expected_post}"
    );
    assert_ne!(
        in_flight, expected_post,
        "the in-flight explanation must not be the post-mutation snapshot"
    );
}
