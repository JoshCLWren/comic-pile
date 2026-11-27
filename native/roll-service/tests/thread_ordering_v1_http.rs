#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Handler-level HTTP regressions for the same-path thread ordering and
//! dependency-inspection reads (#4832 part B).
//!
//! Exercises auth, ownership scoping, ordering and error mapping through the
//! mounted router against the canonical disposable PostgreSQL schema. Requires
//! `RUST_ROLL_TEST_DATABASE_URL` and hard-fails without it.

mod incident_fixtures;
use incident_fixtures as fixture;

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, test_support, AppState};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
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
    setup_user_with(prefix, false).await
}

/// `reading_lists` is injected into the state's config; nothing touches the process env.
async fn setup_user_with(
    prefix: &str,
    reading_lists: bool,
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
            "READING_LISTS_ENABLED" if reading_lists => Some("true".into()),
            "READING_LISTS_APPROVED_PREVIEW" if reading_lists => Some("injected-by-test".into()),
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

async fn thread(conn: &Conn, user_id: i32, title: &str) -> i32 {
    conn.query_one(
        "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id) \
         VALUES ($1, 'Comic', 0, 1, 'active', $2) RETURNING id",
        &[&title, &user_id],
    )
    .await
    .unwrap()
    .get(0)
}

async fn issue(conn: &Conn, thread_id: i32, number: &str, position: i32, status: &str) -> i32 {
    conn.query_one(
        "INSERT INTO issues (thread_id, issue_number, status, created_at, position) \
         VALUES ($1, $2, $3, NOW(), $4) RETURNING id",
        &[&thread_id, &number, &status, &position],
    )
    .await
    .unwrap()
    .get(0)
}

async fn issue_run(conn: &Conn, thread_id: i32, numbers: &[&str], status: &str) -> Vec<i32> {
    let mut ids = Vec::with_capacity(numbers.len());
    for (index, number) in numbers.iter().enumerate() {
        ids.push(issue(conn, thread_id, number, index as i32 + 1, status).await);
    }
    ids
}

async fn frontier(conn: &Conn, thread_id: i32, issue_id: i32) {
    conn.execute(
        "UPDATE threads SET next_unread_issue_id = $2 WHERE id = $1",
        &[&thread_id, &issue_id],
    )
    .await
    .unwrap();
}

async fn dependency(conn: &Conn, source: i32, target: i32, note: Option<&str>) -> i32 {
    conn.query_one(
        "INSERT INTO dependencies (created_at, source_issue_id, target_issue_id, note, origin) \
         VALUES (NOW(), $1, $2, $3, 'reader') RETURNING id",
        &[&source, &target, &note],
    )
    .await
    .unwrap()
    .get(0)
}

fn get(path: &str, token: &str, csrf: &str) -> Request<Body> {
    authed("GET", path, token, csrf, None)
}

fn post(path: &str, token: &str, csrf: &str, body: Option<Value>) -> Request<Body> {
    authed("POST", path, token, csrf, body)
}

#[tokio::test]
async fn every_operation_requires_authentication() {
    let (state, _token, _csrf, _user_id, _guard) = setup_user("tord-auth").await;
    for (method, path) in [
        ("POST", "/api/v1/threads/1:getBlockingInfo"),
        ("POST", "/api/v1/threads:getBlockingInfo"),
        ("GET", "/api/v1/threads/1/connected"),
        ("GET", "/api/v1/threads/1/dependency-order-check"),
        ("GET", "/api/v1/threads/1/issues:validateOrder"),
        ("GET", "/api/v1/threads/1/reading-orders"),
        ("GET", "/api/v2/threads/1/readingOrders"),
    ] {
        let (status, body) = send(
            &state,
            Request::builder()
                .method(method)
                .uri(path)
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(json!({"thread_ids": [1]}).to_string()))
                .unwrap(),
        )
        .await;
        assert_eq!(
            status,
            StatusCode::UNAUTHORIZED,
            "{method} {path}: {body:?}"
        );
    }
}

#[tokio::test]
async fn blocking_info_reports_canonical_unread_blockers_with_isolation() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-block").await;
    let (token2, csrf2, user2) = register_extra_user(&state, "tord-block2").await;
    let conn = state.pool.get().await.unwrap();
    let blocked = thread(&conn, user_id, "Blocked Series").await;
    let blocker = thread(&conn, user_id, "Blocker Series").await;
    let free = thread(&conn, user_id, "Free Series").await;
    let blocked_issue = issue(&conn, blocked, "5", 1, "unread").await;
    let blocker_issue = issue(&conn, blocker, "12", 1, "unread").await;
    let free_issue = issue(&conn, free, "1", 1, "unread").await;
    frontier(&conn, blocked, blocked_issue).await;
    frontier(&conn, blocker, blocker_issue).await;
    frontier(&conn, free, free_issue).await;
    dependency(&conn, blocker_issue, blocked_issue, None).await;
    // Historical cbl-order rows are inert and a read source is satisfied.
    let inert_source = issue(&conn, free, "2", 2, "unread").await;
    dependency(&conn, inert_source, blocked_issue, Some("cbl-order:legacy")).await;
    let foreign = thread(&conn, user2, "Foreign Series").await;

    let (status, body) = send(
        &state,
        post(
            &format!("/api/v1/threads/{blocked}:getBlockingInfo"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body,
        json!({
            "is_blocked": true,
            "blocking_reasons": ["Blocked by Blocker Series: #12"],
            "blocking_dependencies": [{
                "thread_id": blocker,
                "thread_title": "Blocker Series",
                "issue_number": "12",
                "label": "Blocked by Blocker Series: #12",
                "issue_id": null
            }]
        })
    );

    let (status, body) = send(
        &state,
        post(
            &format!("/api/v1/threads/{free}:getBlockingInfo"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body,
        json!({"is_blocked": false, "blocking_reasons": [], "blocking_dependencies": []})
    );

    conn.execute(
        "UPDATE issues SET status = 'read' WHERE id = $1",
        &[&blocker_issue],
    )
    .await
    .unwrap();
    let (_, body) = send(
        &state,
        post(
            &format!("/api/v1/threads/{blocked}:getBlockingInfo"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(body["is_blocked"], false, "{body:?}");

    // Missing and foreign threads are indistinguishable 404s.
    for id in [999_999, foreign] {
        let (status, body) = send(
            &state,
            post(
                &format!("/api/v1/threads/{id}:getBlockingInfo"),
                &token,
                &csrf,
                None,
            ),
        )
        .await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
        assert_eq!(body["detail"], format!("Thread {id} not found"));
    }
    let (status, _) = send(
        &state,
        post(
            &format!("/api/v1/threads/{blocked}:getBlockingInfo"),
            &token2,
            &csrf2,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, body) = send(
        &state,
        post("/api/v1/threads/abc:getBlockingInfo", &token, &csrf, None),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
}

#[tokio::test]
async fn blocking_info_contains_reading_lists_cycles_and_preserves_healthy_threads() {
    let (state, token, csrf, user_id, _guard) = setup_user_with("tord-cycle", true).await;
    let conn = state.pool.get().await.unwrap();
    let a = thread(&conn, user_id, "Series A").await;
    let b = thread(&conn, user_id, "Series B").await;
    let healthy = thread(&conn, user_id, "Healthy Series").await;
    let a1 = issue(&conn, a, "1", 1, "unread").await;
    let a2 = issue(&conn, a, "2", 2, "unread").await;
    let b1 = issue(&conn, b, "1", 1, "unread").await;
    let healthy1 = issue(&conn, healthy, "1", 1, "unread").await;
    frontier(&conn, a, a1).await;
    frontier(&conn, b, b1).await;
    frontier(&conn, healthy, healthy1).await;
    // A#2 -> B#1 -> A#1 closes a loop with the required A#1 -> A#2 order.
    dependency(&conn, a2, b1, None).await;
    dependency(&conn, b1, a1, None).await;

    let (status, body) = send(
        &state,
        post(
            &format!("/api/v1/threads/{a}:getBlockingInfo"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["is_blocked"], true, "{body:?}");
    assert_eq!(
        body["blocking_reasons"],
        json!([
            "Reading constraint cycle: waiting on Series A #1",
            "Reading constraint cycle: waiting on Series A #2"
        ]),
        "{body:?}"
    );

    let (status, body) = send(
        &state,
        post(
            &format!("/api/v1/threads/{healthy}:getBlockingInfo"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body,
        json!({"is_blocked": false, "blocking_reasons": [], "blocking_dependencies": []})
    );
}

#[tokio::test]
async fn batch_blocking_info_preserves_request_order_and_validates() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-batch").await;
    let (token2, csrf2, user2) = register_extra_user(&state, "tord-batch2").await;
    let conn = state.pool.get().await.unwrap();
    let a = thread(&conn, user_id, "Alpha").await;
    let b = thread(&conn, user_id, "Beta").await;
    let ai = issue(&conn, a, "1", 1, "unread").await;
    let bi = issue(&conn, b, "3", 1, "unread").await;
    frontier(&conn, a, ai).await;
    frontier(&conn, b, bi).await;
    dependency(&conn, ai, bi, None).await;
    let foreign = thread(&conn, user2, "Foreign").await;

    let path = "/api/v1/threads:getBlockingInfo";
    let request = json!({"thread_ids": [b, a, b]});
    let response = router(state.clone())
        .oneshot(post(path, &token, &csrf, Some(request.clone())))
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), 64 * 1024).await.unwrap();
    let text = String::from_utf8(bytes.to_vec()).unwrap();
    let body: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(body["threads"][b.to_string()]["is_blocked"], true, "{text}");
    assert_eq!(
        body["threads"][b.to_string()]["blocking_reasons"],
        json!(["Blocked by Alpha: #1"])
    );
    assert_eq!(body["threads"][a.to_string()]["is_blocked"], false);
    let first = text.find(&format!("\"{b}\":")).unwrap();
    let second = text.find(&format!("\"{a}\":")).unwrap();
    assert!(first < second, "request order must be preserved: {text}");

    for payload in [
        json!({"thread_ids": []}),
        json!({}),
        json!({"thread_ids": ["x"]}),
        json!({"thread_ids": (1..=501).collect::<Vec<i32>>()}),
    ] {
        let (status, body) = send(&state, post(path, &token, &csrf, Some(payload))).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
    }
    for ids in [vec![a, 999_999], vec![a, foreign]] {
        let (status, body) = send(
            &state,
            post(path, &token, &csrf, Some(json!({"thread_ids": ids}))),
        )
        .await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
        assert_eq!(body["detail"], "One or more threads not found");
    }
    let (status, body) = send(&state, post(path, &token2, &csrf2, Some(request))).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
}

#[tokio::test]
async fn connected_threads_report_direction_and_issue_level_cycles() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-conn").await;
    let (token2, csrf2, user2) = register_extra_user(&state, "tord-conn2").await;
    let conn = state.pool.get().await.unwrap();
    let a = thread(&conn, user_id, "Series A").await;
    let b = thread(&conn, user_id, "Series B").await;
    let c = thread(&conn, user_id, "Series C").await;
    let a1 = issue(&conn, a, "1", 1, "unread").await;
    let a2 = issue(&conn, a, "2", 2, "unread").await;
    let b1 = issue(&conn, b, "1", 1, "unread").await;
    let c1 = issue(&conn, c, "7", 1, "unread").await;
    // A#2 -> B#1 -> A#1 closes a loop with the required A#1 -> A#2 order.
    let blocks_dep = dependency(&conn, a2, b1, None).await;
    dependency(&conn, b1, a1, None).await;
    // C#7 -> A#1 is a plain blocked_by with no cycle.
    let c_dep = dependency(&conn, c1, a1, None).await;

    let (status, body) = send(
        &state,
        get(&format!("/api/v1/threads/{a}/connected"), &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["thread_id"], a);
    assert_eq!(
        body["connected_threads"],
        json!([
            {"thread_id": b, "title": "Series B", "connection_type": "blocks & blocked_by",
             "dependency_id": blocks_dep, "issue_number": "1", "is_circular": true},
            {"thread_id": c, "title": "Series C", "connection_type": "blocked_by",
             "dependency_id": c_dep, "issue_number": "7", "is_circular": false}
        ]),
        "{body:?}"
    );

    // A satisfied prerequisite (read source) drops out of blocked_by.
    conn.execute("UPDATE issues SET status = 'read' WHERE id = $1", &[&c1])
        .await
        .unwrap();
    let (_, body) = send(
        &state,
        get(&format!("/api/v1/threads/{a}/connected"), &token, &csrf),
    )
    .await;
    assert_eq!(
        body["connected_threads"].as_array().unwrap().len(),
        1,
        "{body:?}"
    );

    let lonely = thread(&conn, user_id, "Lonely").await;
    let (status, body) = send(
        &state,
        get(
            &format!("/api/v1/threads/{lonely}/connected"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, json!({"thread_id": lonely, "connected_threads": []}));

    let foreign = thread(&conn, user2, "Foreign").await;
    for (who, id) in [(&token, 999_999), (&token, foreign), (&token2, a)] {
        let csrf_for = if who == &token { &csrf } else { &csrf2 };
        let (status, body) = send(
            &state,
            get(&format!("/api/v1/threads/{id}/connected"), who, csrf_for),
        )
        .await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{body:?}");
        assert_eq!(body["detail"], format!("Thread {id} not found"));
    }
}

#[tokio::test]
async fn order_check_and_validate_order_report_position_conflicts() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-order").await;
    let (token2, csrf2, user2) = register_extra_user(&state, "tord-order2").await;
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Ordered").await;
    let i1 = issue(&conn, t, "1", 1, "unread").await;
    let i2 = issue(&conn, t, "2", 2, "unread").await;
    let i3 = issue(&conn, t, "3", 3, "unread").await;
    dependency(&conn, i2, i1, None).await; // conflict: 2 must precede 1
    dependency(&conn, i1, i3, None).await; // consistent
    let foreign = thread(&conn, user2, "Foreign").await;

    let (status, body) = send(
        &state,
        get(
            &format!("/api/v1/threads/{t}/dependency-order-check"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body,
        json!({
            "thread_id": t,
            "conflicts": [{
                "issue_id": i2,
                "issue_number": "2",
                "position": 2,
                "dependency_requires_before": [{"issue_id": i1, "issue_number": "1", "position": 1}],
                "conflict": "position 2 comes after issue at position 1, but dependency says it must come before"
            }]
        })
    );

    let (status, body) = send(
        &state,
        get(
            &format!("/api/v1/threads/{t}/issues:validateOrder"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body,
        json!({"warnings": ["In thread \"Ordered\", issue #2 (position 2) blocks issue #1 (position 1). Position is canonical for in-thread order."]})
    );

    for path in ["dependency-order-check", "issues:validateOrder"] {
        for (who, who_csrf, id) in [
            (&token, &csrf, 999_999),
            (&token, &csrf, foreign),
            (&token2, &csrf2, t),
        ] {
            let (status, body) = send(
                &state,
                get(&format!("/api/v1/threads/{id}/{path}"), who, who_csrf),
            )
            .await;
            assert_eq!(status, StatusCode::NOT_FOUND, "{path}: {body:?}");
            assert_eq!(body["detail"], format!("Thread {id} not found"));
        }
        let (status, _) = send(
            &state,
            get(&format!("/api/v1/threads/nope/{path}"), &token, &csrf),
        )
        .await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    }
}

#[tokio::test]
async fn thread_reading_orders_are_enriched_ordered_and_owner_scoped() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-ro").await;
    let (token2, csrf2, user2) = register_extra_user(&state, "tord-ro2").await;
    let conn = state.pool.get().await.unwrap();
    let a = thread(&conn, user_id, "Alpha").await;
    let b = thread(&conn, user_id, "Beta").await;
    issue(&conn, a, "1", 1, "read").await;
    issue(&conn, b, "9", 1, "unread").await;
    let order: i32 = conn
        .query_one(
            "INSERT INTO reading_orders (name, description, user_id) VALUES ('Event', 'Big event', $1) RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    for (thread_id, position, number) in [(b, 2, Some("9")), (a, 1, Some("1"))] {
        conn.execute(
            "INSERT INTO reading_order_items (reading_order_id, thread_id, position, issue_number) VALUES ($1,$2,$3,$4)",
            &[&order, &thread_id, &position, &number],
        )
        .await
        .unwrap();
    }
    conn.execute(
        "INSERT INTO reading_orders (name, user_id) VALUES ('Unrelated', $1)",
        &[&user_id],
    )
    .await
    .unwrap();
    let foreign_order: i32 = conn
        .query_one(
            "INSERT INTO reading_orders (name, user_id) VALUES ('Theirs', $1) RETURNING id",
            &[&user2],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO reading_order_items (reading_order_id, thread_id, position) VALUES ($1,$2,1)",
        &[&foreign_order, &a],
    )
    .await
    .unwrap();

    let (status, body) = send(
        &state,
        get(
            &format!("/api/v1/threads/{a}/reading-orders"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let expected = json!({"reading_orders": [{
        "id": order, "name": "Event", "description": "Big event",
        "total_items": 2, "completed_items": 1,
        "items": [
            {"thread_id": a, "thread_title": "Alpha", "position": 1, "issue_number": "1", "is_read": true},
            {"thread_id": b, "thread_title": "Beta", "position": 2, "issue_number": "9", "is_read": false}
        ]
    }]});
    assert_eq!(body, expected);

    // #5715: the canonical v2 collection spelling returns the exact same
    // owner-scoped wire body as the retained v1 alias.
    let (status, v2_body) = send(
        &state,
        get(&format!("/api/v2/threads/{a}/readingOrders"), &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{v2_body:?}");
    assert_eq!(v2_body, expected);

    // Each reader sees only their own order containing the thread.
    let (_, body) = send(
        &state,
        get(
            &format!("/api/v1/threads/{a}/reading-orders"),
            &token2,
            &csrf2,
        ),
    )
    .await;
    assert_eq!(
        body["reading_orders"].as_array().unwrap().len(),
        1,
        "{body:?}"
    );
    assert_eq!(body["reading_orders"][0]["name"], "Theirs");
    assert_eq!(
        body["reading_orders"][0]["items"][0]["thread_title"],
        "Alpha"
    );

    let (_, v2_body) = send(
        &state,
        get(
            &format!("/api/v2/threads/{a}/readingOrders"),
            &token2,
            &csrf2,
        ),
    )
    .await;
    assert_eq!(v2_body["reading_orders"].as_array().unwrap().len(), 1);
    assert_eq!(v2_body["reading_orders"][0]["name"], "Theirs");

    let (status, body) = send(
        &state,
        get("/api/v1/threads/999999/reading-orders", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, json!({"reading_orders": []}));
    let (status, v2_body) = send(
        &state,
        get("/api/v2/threads/999999/readingOrders", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(v2_body, json!({"reading_orders": []}));
    let (status, _) = send(
        &state,
        get("/api/v1/threads/x/reading-orders", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    let (status, _) = send(
        &state,
        get("/api/v2/threads/x/readingOrders", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn thread_detail_queue_position_matches_queue_list_position() {
    // Regression test for issue #5263: position numbers should agree across
    // Queue list, Thread Detail page, and pending Roll label.
    //
    // The display position is computed as row_number() over:
    //   ORDER BY is_blocked ASC, queue_position ASC, id ASC
    // Only threads with status='active' and queue_position >= 1 are in the queue.
    let (state, token, csrf, user_id, _guard) = setup_user("tord-pos").await;
    let conn = state.pool.get().await.unwrap();

    // Create threads with non-sequential stored queue_position values. All are
    // unblocked here, so display order is queue_position then id: Beta (stored
    // 2) ranks first, Gamma (stored 3) second and Alpha (stored 5) third. The
    // sparse stored values prove detail reads the computed display position.
    let alpha = thread(&conn, user_id, "Alpha").await;
    let beta = thread(&conn, user_id, "Beta").await;
    let gamma = thread(&conn, user_id, "Gamma").await;

    // Set non-sequential stored queue positions.
    conn.execute(
        "UPDATE threads SET queue_position = 5 WHERE id = $1",
        &[&alpha],
    )
    .await
    .unwrap();
    conn.execute(
        "UPDATE threads SET queue_position = 2 WHERE id = $1",
        &[&beta],
    )
    .await
    .unwrap();
    conn.execute(
        "UPDATE threads SET queue_position = 3 WHERE id = $1",
        &[&gamma],
    )
    .await
    .unwrap();

    // Fetch queue list (v2) to see the expected display positions.
    let (list_status, list_body) = send(&state, get("/api/v2/threads", &token, &csrf)).await;
    assert_eq!(list_status, StatusCode::OK, "{list_body:?}");

    // Display order is is_blocked ASC, queue_position ASC, id ASC. With every
    // thread unblocked and every queue_position distinct, queue_position alone
    // decides: Beta (2) -> 1, Gamma (3) -> 2, Alpha (5) -> 3.
    let threads = list_body["threads"].as_array().unwrap();
    assert_eq!(threads.len(), 3, "{list_body:?}");

    let beta_list_pos = threads
        .iter()
        .find(|t| t["id"].as_i64().unwrap() == beta as i64)
        .unwrap();
    let gamma_list_pos = threads
        .iter()
        .find(|t| t["id"].as_i64().unwrap() == gamma as i64)
        .unwrap();
    let alpha_list_pos = threads
        .iter()
        .find(|t| t["id"].as_i64().unwrap() == alpha as i64)
        .unwrap();

    let beta_display_pos = beta_list_pos["queue_position"].as_i64().unwrap();
    let gamma_display_pos = gamma_list_pos["queue_position"].as_i64().unwrap();
    let alpha_display_pos = alpha_list_pos["queue_position"].as_i64().unwrap();

    // Verify order: Beta (pos 1), Gamma (pos 2), Alpha (pos 3)
    assert_eq!(
        beta_display_pos, 1,
        "Beta should be position 1 in queue list"
    );
    assert_eq!(
        gamma_display_pos, 2,
        "Gamma should be position 2 in queue list"
    );
    assert_eq!(
        alpha_display_pos, 3,
        "Alpha should be position 3 in queue list"
    );

    // Now fetch each thread's detail and verify the queue_position matches.
    for (thread_id, expected_position) in [(beta, 1i64), (gamma, 2i64), (alpha, 3i64)] {
        let (detail_status, detail_body) = send(
            &state,
            get(&format!("/api/v1/threads/{thread_id}"), &token, &csrf),
        )
        .await;
        assert_eq!(
            detail_status,
            StatusCode::OK,
            "detail body: {detail_body:?}"
        );
        let actual_position = detail_body["queue_position"].as_i64().unwrap();
        assert_eq!(
            actual_position, expected_position,
            "Thread {thread_id} detail queue_position should be {expected_position}, was {actual_position}. Detail body: {detail_body:?}"
        );
    }
}

#[tokio::test]
async fn thread_detail_completed_thread_keeps_stored_position() {
    // A completed thread is outside the active queue, so the canonical
    // display-position subquery yields NULL. Detail must fall back to the
    // stored position instead of panicking on a NULL -> i32 read.
    let (state, token, csrf, user_id, _guard) = setup_user("tord-done").await;
    let conn = state.pool.get().await.unwrap();

    let queued = thread(&conn, user_id, "Queued").await;
    conn.execute(
        "UPDATE threads SET queue_position = 4 WHERE id = $1",
        &[&queued],
    )
    .await
    .unwrap();
    let completed = thread(&conn, user_id, "Completed").await;
    conn.execute(
        "UPDATE threads SET queue_position = 7, status = 'completed' WHERE id = $1",
        &[&completed],
    )
    .await
    .unwrap();

    let (status, body) = send(
        &state,
        get(&format!("/api/v1/threads/{completed}"), &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["queue_position"].as_i64().unwrap(), 7, "{body:?}");

    // An active queued thread still receives its computed display position.
    let (status, body) = send(
        &state,
        get(&format!("/api/v1/threads/{queued}"), &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["queue_position"].as_i64().unwrap(), 1, "{body:?}");
}

#[tokio::test]
async fn thread_detail_blocked_order_matches_queue_list_under_reading_lists() {
    // With the Reading List engine preview active the Queue list groups by evaluated
    // eligibility, not the stored is_blocked flag. Thread Detail must use that
    // same expression or the two views disagree for the same thread.
    let (state, token, csrf, user_id, _guard) = setup_user_with("tord-blk", true).await;
    let conn = state.pool.get().await.unwrap();

    // Stored blocked, but actually eligible (has an unread issue).
    let eligible_low = thread(&conn, user_id, "EligibleLow").await;
    let low_issue = issue(&conn, eligible_low, "1", 1, "unread").await;
    frontier(&conn, eligible_low, low_issue).await;
    conn.execute(
        "UPDATE threads SET queue_position = 5, is_blocked = true, issues_remaining = 1 WHERE id = $1",
        &[&eligible_low],
    )
    .await
    .unwrap();

    // Stored unblocked and actually eligible, with a higher queue position.
    let eligible_high = thread(&conn, user_id, "EligibleHigh").await;
    let high_issue = issue(&conn, eligible_high, "1", 1, "unread").await;
    frontier(&conn, eligible_high, high_issue).await;
    conn.execute(
        "UPDATE threads SET queue_position = 9, issues_remaining = 1 WHERE id = $1",
        &[&eligible_high],
    )
    .await
    .unwrap();

    // Stored unblocked but no unread issue, so not an Reading List engine candidate.
    let no_unread = thread(&conn, user_id, "NoUnread").await;
    conn.execute(
        "UPDATE threads SET queue_position = 1 WHERE id = $1",
        &[&no_unread],
    )
    .await
    .unwrap();

    let (list_status, list_body) = send(&state, get("/api/v2/threads", &token, &csrf)).await;
    assert_eq!(list_status, StatusCode::OK, "{list_body:?}");
    let threads = list_body["threads"].as_array().unwrap();
    assert_eq!(threads.len(), 3, "{list_body:?}");
    let list_position = |id: i32| {
        threads
            .iter()
            .find(|row| row["id"].as_i64() == Some(id as i64))
            .unwrap()["queue_position"]
            .as_i64()
            .unwrap()
    };

    // Both eligible threads are unblocked under Reading List engine despite the stored
    // flag; NoUnread is grouped last despite its lower stored position.
    assert_eq!(list_position(eligible_low), 1, "{list_body:?}");
    assert_eq!(list_position(eligible_high), 2, "{list_body:?}");
    assert_eq!(list_position(no_unread), 3, "{list_body:?}");

    for (id, expected_position, expected_blocked) in [
        (eligible_low, 1i64, false),
        (eligible_high, 2, false),
        (no_unread, 3, true),
    ] {
        let (status, body) =
            send(&state, get(&format!("/api/v1/threads/{id}"), &token, &csrf)).await;
        assert_eq!(status, StatusCode::OK, "{body:?}");
        assert_eq!(
            body["queue_position"].as_i64().unwrap(),
            expected_position,
            "{body:?}"
        );
        assert_eq!(body["is_blocked"], json!(expected_blocked), "{body:?}");
    }
}

#[tokio::test]
async fn julix_strict_order_is_shared_by_roll_queue_reader_and_explanations() {
    // Production regression #3735. Allocate fresh primary keys while retaining
    // the source identities and exact Julix positions 22..=54. In particular,
    // Wild Hunt #1-8 are already read and King of Fear has only that satisfied
    // explicit prerequisite; the temporary Black Goddess -> King production
    // mitigation is deliberately NOT reproduced here.
    let (state, token, csrf, user_id, _guard) = setup_user_with("tord-julix", true).await;
    let conn = state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO sessions (user_id, started_at, start_die) VALUES ($1, NOW(), 6)",
        &[&user_id],
    )
    .await
    .unwrap();

    let dead_thread = thread(&conn, user_id, "B.P.R.D.: The Dead Remembered").await;
    let killing_thread = thread(&conn, user_id, "B.P.R.D.: Killing Ground").await;
    let dark_horse_thread = thread(&conn, user_id, "MySpace Dark Horse Presents").await;
    let witchfinder_thread = thread(&conn, user_id, "Witchfinder: In the Service of Angels").await;
    let warning_thread = thread(&conn, user_id, "B.P.R.D.: The Warning").await;
    let goddess_thread = thread(&conn, user_id, "B.P.R.D.: The Black Goddess").await;
    let wild_hunt_thread = thread(&conn, user_id, "Hellboy: The Wild Hunt").await;
    let king_thread = thread(&conn, user_id, "B.P.R.D.: King of Fear").await;

    let dead_1 = issue(&conn, dead_thread, "1", 1, "read").await;
    let dead_2 = issue(&conn, dead_thread, "2", 2, "unread").await;
    let dead_3 = issue(&conn, dead_thread, "3", 3, "unread").await;
    let killing = issue_run(&conn, killing_thread, &["1", "2", "3", "4", "5"], "unread").await;
    let dark_horse = issue(&conn, dark_horse_thread, "16", 1, "unread").await;
    let witchfinder = issue_run(
        &conn,
        witchfinder_thread,
        &["1", "2", "3", "4", "5"],
        "unread",
    )
    .await;
    let warning = issue_run(&conn, warning_thread, &["1", "2", "3", "4", "5"], "unread").await;
    let goddess = issue_run(&conn, goddess_thread, &["1", "2", "3", "4", "5"], "unread").await;
    let wild_hunt = issue_run(
        &conn,
        wild_hunt_thread,
        &["1", "2", "3", "4", "5", "6", "7", "8"],
        "read",
    )
    .await;
    let king = issue_run(&conn, king_thread, &["1", "2", "3", "4", "5"], "unread").await;

    let generated_by_source = BTreeMap::from([
        (fixture::JULIX_DEAD_REMEMBERED_2_SOURCE_ID, dead_2),
        (fixture::JULIX_BLACK_GODDESS_5_SOURCE_ID, goddess[4]),
        (fixture::JULIX_WILD_HUNT_8_SOURCE_ID, wild_hunt[7]),
        (fixture::JULIX_KING_OF_FEAR_1_SOURCE_ID, king[0]),
    ]);
    let source_threads = BTreeMap::from([
        (fixture::JULIX_DEAD_REMEMBERED_THREAD_SOURCE_ID, dead_thread),
        (fixture::JULIX_KING_OF_FEAR_THREAD_SOURCE_ID, king_thread),
    ]);

    for (thread_id, stored_position, remaining, next_issue, status) in [
        (dead_thread, 1, 2, Some(dead_2), "active"),
        (killing_thread, 25, 5, Some(killing[0]), "active"),
        (dark_horse_thread, 30, 1, Some(dark_horse), "active"),
        (witchfinder_thread, 31, 5, Some(witchfinder[0]), "active"),
        (warning_thread, 36, 5, Some(warning[0]), "active"),
        (goddess_thread, 41, 5, Some(goddess[0]), "active"),
        (wild_hunt_thread, 0, 0, None, "completed"),
        (king_thread, 320, 5, Some(king[0]), "active"),
    ] {
        // Every stored flag starts unblocked, including the stale later
        // frontiers, so these requests cannot pass by trusting Thread.is_blocked.
        conn.execute(
            "UPDATE threads SET queue_position=$2, issues_remaining=$3, \
             next_unread_issue_id=$4, status=$5, is_blocked=false WHERE id=$1",
            &[
                &thread_id,
                &stored_position,
                &remaining,
                &next_issue,
                &status,
            ],
        )
        .await
        .unwrap();
    }

    // The read Wild Hunt #8 prerequisite was the false eligibility signal in
    // production. It remains satisfied and must not suppress strict-list gates.
    dependency(
        &conn,
        wild_hunt[7],
        king[0],
        Some("continuity-rule:1715697"),
    )
    .await;

    let list_id: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, mode, created_at, updated_at) \
             VALUES ($1, 'Mignolaverse — Julix Comics (Unread)', 'strict', NOW(), NOW()) \
             RETURNING id",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    let mut list_entries = vec![
        (dead_1, 22),
        (dead_2, fixture::JULIX_FIRST_UNREAD_POSITION),
        (dead_3, 24),
    ];
    list_entries.extend(killing.iter().copied().zip(25..30));
    list_entries.push((dark_horse, 30));
    list_entries.extend(witchfinder.iter().copied().zip(31..36));
    list_entries.extend(warning.iter().copied().zip(36..41));
    list_entries.extend(goddess.iter().copied().zip(41..46));
    list_entries.extend(wild_hunt.iter().copied().zip(46..54));
    list_entries.push((king[0], fixture::JULIX_KING_OF_FEAR_POSITION));
    assert_eq!(list_entries.len(), 33);
    for (offset, (issue_id, position)) in list_entries.iter().enumerate() {
        assert_eq!(*position, offset as i32 + 22);
        conn.execute(
            "INSERT INTO custom_cbl_entries (list_id, issue_id, position, created_at) \
             VALUES ($1, $2, $3, NOW())",
            &[&list_id, issue_id, position],
        )
        .await
        .unwrap();
    }

    let thread_ids = vec![
        dead_thread,
        killing_thread,
        dark_horse_thread,
        witchfinder_thread,
        warning_thread,
        goddess_thread,
        wild_hunt_thread,
        king_thread,
    ];
    let issue_states_before: Vec<(i32, String)> = conn
        .query(
            "SELECT id, status FROM issues WHERE thread_id=ANY($1::int[]) ORDER BY id",
            &[&thread_ids],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();
    let list_positions_before: Vec<(i32, i32)> = conn
        .query(
            "SELECT issue_id, position FROM custom_cbl_entries \
             WHERE list_id=$1 ORDER BY position, id",
            &[&list_id],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();

    // Both native Roll reads expose only The Dead Remembered #2. A top-die
    // bound, stored queue position, or cached blocked flag cannot resurrect King.
    let (status, eligible) = send(
        &state,
        get("/api/v2/roll/eligible-issue-ids", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{eligible:?}");
    assert_eq!(eligible["issue_ids"], json!([dead_2]));
    assert_eq!(eligible["thread_ids"], json!([dead_thread]));
    assert_eq!(eligible["pool_reason"], "ready");

    let (status, bootstrap) = send(&state, get("/api/v2/roll/bootstrap", &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{bootstrap:?}");
    assert_eq!(bootstrap["rollable"].as_array().unwrap().len(), 1);
    assert_eq!(bootstrap["rollable"][0]["thread"]["id"], json!(dead_thread));
    assert_eq!(bootstrap["rollable"][0]["issue"]["id"], json!(dead_2));
    assert_eq!(
        bootstrap["rollable"][0]["issue"]["id"].as_i64(),
        generated_by_source
            .get(&fixture::JULIX_DEAD_REMEMBERED_2_SOURCE_ID)
            .map(|id| i64::from(*id))
    );

    // Queue and Thread Detail derive the same blocked state despite every
    // stored flag being false. The correct frontier is the only readable row.
    let (status, queue) = send(&state, get("/api/v2/threads?page_size=100", &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{queue:?}");
    let queue_rows = queue["threads"].as_array().unwrap();
    assert_eq!(queue_rows.len(), 7, "{queue:?}");
    let readable: Vec<_> = queue_rows
        .iter()
        .filter(|row| row["is_blocked"] == json!(false))
        .collect();
    assert_eq!(readable.len(), 1, "{queue:?}");
    assert_eq!(readable[0]["id"], json!(dead_thread));
    assert_eq!(readable[0]["queue_position"], 1);
    assert_eq!(readable[0]["next_unread_issue_number"], "2");
    for blocked_thread in [
        killing_thread,
        dark_horse_thread,
        witchfinder_thread,
        warning_thread,
        goddess_thread,
        king_thread,
    ] {
        let row = queue_rows
            .iter()
            .find(|row| row["id"] == json!(blocked_thread))
            .unwrap();
        assert_eq!(row["is_blocked"], true, "{row:?}");
    }

    let (status, king_detail) = send(
        &state,
        get(&format!("/api/v1/threads/{king_thread}"), &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{king_detail:?}");
    assert_eq!(king_detail["is_blocked"], true);
    assert_eq!(king_detail["next_unread_issue_id"], json!(king[0]));
    assert_eq!(king_detail["next_unread_issue_number"], "1");

    // Explanations name every earlier unread list entry, not just the adjacent
    // read Wild Hunt node. The read prerequisite emits no blocker at all.
    let (status, king_info) = send(
        &state,
        post(
            &format!("/api/v1/threads/{king_thread}:getBlockingInfo"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{king_info:?}");
    assert_eq!(king_info["is_blocked"], true);
    let mut read_issues = BTreeSet::from([dead_1]);
    read_issues.extend(wild_hunt.iter().copied());
    let expected_king_blockers: BTreeSet<i32> = list_entries
        .iter()
        .filter(|(issue_id, position)| {
            *position >= fixture::JULIX_FIRST_UNREAD_POSITION
                && *position < fixture::JULIX_KING_OF_FEAR_POSITION
                && !read_issues.contains(issue_id)
        })
        .map(|(issue_id, _)| *issue_id)
        .collect();
    let explained_king_blockers: BTreeSet<i32> = king_info["blocking_dependencies"]
        .as_array()
        .unwrap()
        .iter()
        .map(|dependency| dependency["issue_id"].as_i64().unwrap() as i32)
        .collect();
    assert_eq!(explained_king_blockers, expected_king_blockers);
    assert!(explained_king_blockers.contains(&dead_2));
    assert!(!explained_king_blockers.contains(&wild_hunt[7]));
    let king_reasons = king_info["blocking_reasons"].as_array().unwrap();
    assert!(!king_reasons.is_empty());
    assert!(king_reasons.iter().all(|reason| {
        reason
            .as_str()
            .unwrap()
            .starts_with("Strict order in Mignolaverse — Julix Comics (Unread)")
    }));
    assert!(king_reasons.iter().any(|reason| {
        reason
            .as_str()
            .unwrap()
            .contains("B.P.R.D.: The Dead Remembered #2")
    }));

    let (status, dead_info) = send(
        &state,
        post(
            &format!("/api/v1/threads/{dead_thread}:getBlockingInfo"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{dead_info:?}");
    assert_eq!(dead_info["is_blocked"], false);
    assert_eq!(dead_info["blocking_dependencies"], json!([]));

    // The Reading List reader shares both availability and the exact blocker
    // projection. Killing Ground and Black Goddess stay blocked; Wild Hunt
    // remains read and later issues in an already represented Thread stay later.
    let (status, reader) = send(
        &state,
        get(
            &format!("/api/v2/reading-lists/{list_id}/reader"),
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{reader:?}");
    assert_eq!(reader["execution_mode"], "reading_lists");
    let reader_entries = reader["entries"].as_array().unwrap();
    assert_eq!(reader_entries.len(), 33);
    let reader_entry = |issue_id: i32| {
        reader_entries
            .iter()
            .find(|entry| entry["issue_id"] == json!(issue_id))
            .unwrap()
    };
    assert_eq!(reader_entry(dead_1)["availability"], "read");
    assert_eq!(reader_entry(dead_2)["availability"], "available");
    assert_eq!(reader_entry(dead_3)["availability"], "later");
    assert_eq!(reader_entry(killing[0])["availability"], "blocked");
    assert_eq!(reader_entry(goddess[0])["availability"], "blocked");
    assert_eq!(reader_entry(goddess[4])["availability"], "later");
    assert_eq!(reader_entry(wild_hunt[7])["availability"], "read");
    let king_reader = reader_entry(king[0]);
    assert_eq!(king_reader["availability"], "blocked");
    assert_eq!(king_reader["explanation"]["is_blocked"], true);
    assert_eq!(
        king_reader["explanation"]["blocking_reasons"],
        king_info["blocking_reasons"]
    );
    assert_eq!(
        king_reader["explanation"]["blocking_dependencies"],
        king_info["blocking_dependencies"]
    );
    let available: Vec<i64> = reader_entries
        .iter()
        .filter(|entry| entry["availability"] == "available")
        .map(|entry| entry["issue_id"].as_i64().unwrap())
        .collect();
    assert_eq!(available, vec![i64::from(dead_2)]);

    // With one eligible face the actual write path must select that face. It
    // cannot select King of Fear, and Roll must not mutate reading/list state.
    let (status, offer) = send(
        &state,
        post(
            "/api/v2/roll/offer",
            &token,
            &csrf,
            Some(json!({
                "idempotency_key": "julix-3735-offer-001",
                "snoozed_thread_ids": []
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{offer:?}");
    assert_eq!(offer["thread_id"], json!(dead_thread));
    assert_eq!(offer["issue_id"], json!(dead_2));
    assert_ne!(offer["thread_id"], json!(king_thread));
    assert_eq!(
        source_threads[&fixture::JULIX_DEAD_REMEMBERED_THREAD_SOURCE_ID],
        offer["thread_id"].as_i64().unwrap() as i32
    );

    let issue_states_after: Vec<(i32, String)> = conn
        .query(
            "SELECT id, status FROM issues WHERE thread_id=ANY($1::int[]) ORDER BY id",
            &[&thread_ids],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();
    let list_positions_after: Vec<(i32, i32)> = conn
        .query(
            "SELECT issue_id, position FROM custom_cbl_entries \
             WHERE list_id=$1 ORDER BY position, id",
            &[&list_id],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();
    assert_eq!(issue_states_after, issue_states_before);
    assert_eq!(list_positions_after, list_positions_before);
}

#[tokio::test]
async fn roll_offer_queue_position_matches_queue_and_detail() {
    // The pending Roll offer must forward the canonical display position, not
    // the raw stored queue_position (issue #5263, Roll surface).
    let (state, token, csrf, user_id, _guard) = setup_user("tord-offer").await;
    let conn = state.pool.get().await.unwrap();
    // The Roll offer bootstraps the reader's active session first.
    conn.execute(
        "INSERT INTO sessions (user_id, started_at, start_die) VALUES ($1, NOW(), 6)",
        &[&user_id],
    )
    .await
    .unwrap();

    let early = thread(&conn, user_id, "Early").await;
    let pick = thread(&conn, user_id, "Pick").await;
    let late = thread(&conn, user_id, "Late").await;
    for (id, position) in [(early, 10i32), (pick, 20), (late, 30)] {
        conn.execute(
            "UPDATE threads SET queue_position = $1 WHERE id = $2",
            &[&position, &id],
        )
        .await
        .unwrap();
    }
    // Only "Pick" has an unread issue, so the offer pool contains just it and
    // the selected thread is deterministic.
    let issue_id = issue(&conn, pick, "1", 1, "unread").await;
    frontier(&conn, pick, issue_id).await;
    conn.execute(
        "UPDATE threads SET issues_remaining = 1 WHERE id = $1",
        &[&pick],
    )
    .await
    .unwrap();

    let (list_status, list_body) = send(&state, get("/api/v2/threads", &token, &csrf)).await;
    assert_eq!(list_status, StatusCode::OK, "{list_body:?}");
    let threads = list_body["threads"].as_array().unwrap();
    let pick_list_pos = threads
        .iter()
        .find(|row| row["id"].as_i64() == Some(pick as i64))
        .unwrap()["queue_position"]
        .as_i64()
        .unwrap();

    let (detail_status, detail_body) = send(
        &state,
        get(&format!("/api/v1/threads/{pick}"), &token, &csrf),
    )
    .await;
    assert_eq!(detail_status, StatusCode::OK, "{detail_body:?}");
    let pick_detail_pos = detail_body["queue_position"].as_i64().unwrap();

    let (offer_status, offer_body) = send(
        &state,
        authed(
            "POST",
            "/api/v2/roll/offer",
            &token,
            &csrf,
            Some(json!({
                "idempotency_key": "roll-offer-canonical-001",
                "snoozed_thread_ids": []
            })),
        ),
    )
    .await;
    assert_eq!(offer_status, StatusCode::OK, "{offer_body:?}");
    assert_eq!(
        offer_body["thread_id"].as_i64().unwrap(),
        pick as i64,
        "{offer_body:?}"
    );
    let pick_offer_pos = offer_body["queue_position"].as_i64().unwrap();

    assert_eq!(
        pick_detail_pos, pick_list_pos,
        "detail must match queue list"
    );
    assert_eq!(
        pick_offer_pos, pick_list_pos,
        "roll offer must match queue list"
    );
    assert_ne!(
        pick_list_pos, 20,
        "position must be canonical, not the stored 20"
    );
}

#[tokio::test]
async fn bootstrap_reload_pending_offer_queue_position_matches_queue_and_detail() {
    // Reloading a pending Roll through bootstrap must return the same canonical
    // display position as the Queue list and Thread Detail, not the raw stored
    // queue_position (issue #5263, bootstrap/reload surface).
    let (state, token, csrf, user_id, _guard) = setup_user("tord-boot").await;
    let conn = state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO sessions (user_id, started_at, start_die) VALUES ($1, NOW(), 6)",
        &[&user_id],
    )
    .await
    .unwrap();

    let early = thread(&conn, user_id, "Early").await;
    let pick = thread(&conn, user_id, "Pick").await;
    let late = thread(&conn, user_id, "Late").await;
    for (id, position) in [(early, 10i32), (pick, 20), (late, 30)] {
        conn.execute(
            "UPDATE threads SET queue_position = $1 WHERE id = $2",
            &[&position, &id],
        )
        .await
        .unwrap();
    }
    let issue_id = issue(&conn, pick, "1", 1, "unread").await;
    frontier(&conn, pick, issue_id).await;
    conn.execute(
        "UPDATE threads SET issues_remaining = 1 WHERE id = $1",
        &[&pick],
    )
    .await
    .unwrap();

    let (list_status, list_body) = send(&state, get("/api/v2/threads", &token, &csrf)).await;
    assert_eq!(list_status, StatusCode::OK, "{list_body:?}");
    let threads = list_body["threads"].as_array().unwrap();
    let pick_list_pos = threads
        .iter()
        .find(|row| row["id"].as_i64() == Some(pick as i64))
        .unwrap()["queue_position"]
        .as_i64()
        .unwrap();

    let (detail_status, detail_body) = send(
        &state,
        get(&format!("/api/v1/threads/{pick}"), &token, &csrf),
    )
    .await;
    assert_eq!(detail_status, StatusCode::OK, "{detail_body:?}");
    let pick_detail_pos = detail_body["queue_position"].as_i64().unwrap();

    let (offer_status, offer_body) = send(
        &state,
        authed(
            "POST",
            "/api/v2/roll/offer",
            &token,
            &csrf,
            Some(json!({
                "idempotency_key": "roll-offer-bootstrap-001",
                "snoozed_thread_ids": []
            })),
        ),
    )
    .await;
    assert_eq!(offer_status, StatusCode::OK, "{offer_body:?}");
    assert_eq!(
        offer_body["thread_id"].as_i64().unwrap(),
        pick as i64,
        "{offer_body:?}"
    );
    let pick_offer_pos = offer_body["queue_position"].as_i64().unwrap();

    let (bootstrap_status, bootstrap_body) =
        send(&state, get("/api/v2/roll/bootstrap", &token, &csrf)).await;
    assert_eq!(bootstrap_status, StatusCode::OK, "{bootstrap_body:?}");
    let active = bootstrap_body["active_thread"]
        .as_object()
        .expect("bootstrap should report the pending offer as active_thread");
    assert_eq!(
        active["id"].as_i64().unwrap(),
        pick as i64,
        "{bootstrap_body:?}"
    );
    let pick_bootstrap_pos = active["queue_position"].as_i64().unwrap();

    assert_eq!(
        pick_detail_pos, pick_list_pos,
        "detail must match queue list"
    );
    assert_eq!(
        pick_offer_pos, pick_list_pos,
        "roll offer must match queue list"
    );
    assert_eq!(
        pick_bootstrap_pos, pick_list_pos,
        "bootstrap reload must match queue list"
    );
    assert_ne!(
        pick_bootstrap_pos, 20,
        "bootstrap position must be canonical, not the stored 20"
    );
}

#[tokio::test]
async fn roll_unsnooze_restores_pending_roll_and_reverts_die() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-unsnooze").await;
    let conn = state.pool.get().await.unwrap();

    // The thread that will be snoozed (initially pending).
    let snoozed = thread(&conn, user_id, "Snoozed").await;
    // A replacement thread with an unread issue so the offer has a candidate.
    let replacement = thread(&conn, user_id, "Replacement").await;
    let issue_id = issue(&conn, replacement, "1", 1, "unread").await;
    frontier(&conn, replacement, issue_id).await;
    conn.execute(
        "UPDATE threads SET issues_remaining = 1 WHERE id = $1",
        &[&replacement],
    )
    .await
    .unwrap();

    // Start with the snoozed thread as the pending roll.
    conn.execute(
        "INSERT INTO sessions (user_id, started_at, start_die, pending_thread_id) VALUES ($1, NOW(), 6, $2)",
        &[&user_id, &snoozed],
    )
    .await
    .unwrap();

    // Snooze the pending thread through the native offer; this advances the die
    // and records the snoozed thread on the session.
    let (offer_status, offer_body) = send(
        &state,
        post(
            "/api/v2/roll/offer",
            &token,
            &csrf,
            Some(json!({
                "idempotency_key": "unsnooze-restore-001",
                "snoozed_thread_ids": []
            })),
        ),
    )
    .await;
    assert_eq!(offer_status, StatusCode::OK, "{offer_body:?}");
    assert_eq!(
        offer_body["snoozed_thread_id"].as_i64(),
        Some(snoozed as i64),
        "{offer_body:?}"
    );
    assert_eq!(
        offer_body["thread_id"].as_i64(),
        Some(replacement as i64),
        "{offer_body:?}"
    );

    // Unsnooze must restore the snoozed thread as the pending roll and revert
    // the die to its pre-snooze size.
    let (unsnooze_status, unsnooze_body) = send(
        &state,
        post(
            "/api/v2/roll/unsnooze",
            &token,
            &csrf,
            Some(json!({ "thread_id": snoozed })),
        ),
    )
    .await;
    assert_eq!(unsnooze_status, StatusCode::OK, "{unsnooze_body:?}");
    assert_eq!(
        unsnooze_body["thread_id"].as_i64(),
        Some(snoozed as i64),
        "{unsnooze_body:?}"
    );
    assert_eq!(
        unsnooze_body["die_size"].as_i64(),
        Some(6),
        "{unsnooze_body:?}"
    );

    let pool = state.pool.get().await.unwrap();
    let pending: Option<i32> = pool
        .query_one(
            "SELECT pending_thread_id FROM sessions WHERE user_id = $1",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        pending,
        Some(snoozed),
        "unsnooze must restore the pending roll"
    );

    let snoozed_ids: String = pool
        .query_one(
            "SELECT snoozed_thread_ids::text FROM sessions WHERE user_id = $1",
            &[&user_id],
        )
        .await
        .unwrap()
        .get(0);
    let decoded: Vec<i32> = serde_json::from_str(&snoozed_ids).unwrap_or_default();
    assert!(
        !decoded.contains(&snoozed),
        "unsnooze must remove the thread from snoozed_thread_ids"
    );

    let unsnoozes: i64 = pool
        .query_one(
            "SELECT count(*) FROM events WHERE type = 'unsnooze' AND thread_id = $1",
            &[&snoozed],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(unsnoozes, 1);
}

/// Create `count` rollable threads and return their ids, using set-based
/// statements (no per-series round trips).
async fn rollable_threads(conn: &Conn, user_id: i32, count: usize) -> Vec<i32> {
    let count = count as i32;
    let ids: Vec<i32> = conn
        .query(
            "INSERT INTO threads (title, format, issues_remaining, queue_position, status, user_id) \
             SELECT 'Rollable ' || n, 'Comic', 1, n, 'active', $1 \
             FROM generate_series(1, $2::int) AS n RETURNING id",
            &[&user_id, &count],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| row.get(0))
        .collect();
    conn.execute(
        "INSERT INTO issues (thread_id, issue_number, status, created_at, position) \
         SELECT id, '1', 'unread', NOW(), 1 FROM unnest($1::int[]) AS id",
        &[&ids],
    )
    .await
    .unwrap();
    conn.execute(
        "UPDATE threads t SET next_unread_issue_id = i.id \
         FROM issues i WHERE i.thread_id = t.id AND t.id = ANY($1::int[])",
        &[&ids],
    )
    .await
    .unwrap();
    let mut ordered = ids;
    ordered.sort_unstable();
    ordered
}

#[tokio::test]
async fn bootstrap_displays_browser_snoozes_and_matches_the_scoped_pool() {
    let (state, token, csrf, user_id, _guard) = setup_user_with("roll-cookie", true).await;
    let (_, _, other_user) = register_extra_user(&state, "roll-cookie-other").await;
    let (ids, foreign) = {
        let conn = state.pool.get().await.unwrap();
        let ids = rollable_threads(&conn, user_id, 22).await;
        let foreign = thread(&conn, other_user, "Other reader's series").await;
        conn.execute(
            "INSERT INTO sessions (user_id, started_at, start_die, snoozed_thread_ids)
             VALUES ($1, NOW(), 6, $2::text::json)",
            &[&user_id, &json!([ids[0]]).to_string()],
        )
        .await
        .unwrap();
        (ids, foreign)
    };
    let snoozed = vec![ids[1], ids[3], ids[7], ids[14]];
    let mut cookie_ids = snoozed.clone();
    cookie_ids.push(foreign);
    let query_ids = cookie_ids
        .iter()
        .map(i32::to_string)
        .collect::<Vec<_>>()
        .join(",");
    let cookie = format!(
        "csrf_token={csrf}; comicpile_roll_snoozes={}",
        json!(cookie_ids)
    );

    for (die, count) in [(6, 4), (8, 5), (20, 16)] {
        let (status, body) = send(
            &state,
            post(
                "/api/v2/roll/dice-command",
                &token,
                &csrf,
                Some(json!({
                    "kind": "manual_select",
                    "die": die,
                    "idempotency_key": format!("roll-cookie-die-{die}")
                })),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{body:?}");

        let mut request = get("/api/v2/roll/bootstrap", &token, &csrf);
        request
            .headers_mut()
            .insert(header::COOKIE, cookie.parse().unwrap());
        let (status, bootstrap) = send(&state, request).await;
        assert_eq!(status, StatusCode::OK, "{bootstrap:?}");
        assert_eq!(bootstrap["snoozed_count"], json!(4));
        assert_eq!(bootstrap["snoozed_thread_ids"], json!(snoozed));
        let displayed_snoozes: Vec<_> = bootstrap["snoozed_threads"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| row["id"].as_i64().unwrap() as i32)
            .collect();
        assert_eq!(displayed_snoozes, snoozed);

        let visible: Vec<_> = bootstrap["rollable"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| row["thread"]["id"].as_i64().unwrap() as i32)
            .collect();
        let expected: Vec<_> = ids
            .iter()
            .take(die as usize)
            .filter(|id| !snoozed.contains(id))
            .copied()
            .collect();
        assert_eq!(visible.len(), count);
        assert_eq!(visible, expected);
        assert!(visible.contains(&ids[0]), "legacy session snooze leaked");

        let (status, scoped) = send(
            &state,
            get(
                &format!("/api/v2/roll/eligible-issue-ids?snoozed={query_ids}"),
                &token,
                &csrf,
            ),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{scoped:?}");
        assert_eq!(scoped["thread_ids"], json!(visible));
    }

    let (status, offer) = send(
        &state,
        post(
            "/api/v2/roll/offer",
            &token,
            &csrf,
            Some(json!({
                "idempotency_key": "roll-cookie-offer-001",
                "snoozed_thread_ids": snoozed
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{offer:?}");
    let selected = offer["thread_id"].as_i64().unwrap() as i32;
    assert!(ids[..20].contains(&selected));
    assert!(!snoozed.contains(&selected));

    let (status, reset) = send(
        &state,
        post(
            "/api/v2/roll/reset",
            &token,
            &csrf,
            Some(json!({"idempotency_key": "roll-cookie-reset-001"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{reset:?}");
    assert_eq!(reset["die"], json!(6));
    // The browser clears its cookie after the successful reset response.
    let (status, cleared) = send(&state, get("/api/v2/roll/bootstrap", &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{cleared:?}");
    assert_eq!(cleared["snoozed_count"], json!(0));
    assert_eq!(cleared["snoozed_thread_ids"], json!([]));
    assert_eq!(cleared["rollable"].as_array().unwrap().len(), 6);
    assert!(cleared["pending_thread_id"].is_null());
}

#[tokio::test]
async fn bootstrap_cookie_snoozes_survive_session_turnover_and_no_snooze_case() {
    let (state, token, csrf, user_id, _guard) = setup_user_with("roll-turnover", true).await;
    let (_, _, other_user) = register_extra_user(&state, "roll-turnover-other").await;
    let (ids, foreign) = {
        let conn = state.pool.get().await.unwrap();
        let ids = rollable_threads(&conn, user_id, 8).await;
        let foreign = thread(&conn, other_user, "Other reader's turnover series").await;
        conn.execute(
            "INSERT INTO sessions (user_id, started_at, start_die)
             VALUES ($1, NOW(), 6)",
            &[&user_id],
        )
        .await
        .unwrap();
        (ids, foreign)
    };

    // No snoozes: bootstrap should expose the full bounded pool.
    let (status, clear) = send(&state, get("/api/v2/roll/bootstrap", &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{clear:?}");
    assert_eq!(clear["snoozed_count"], json!(0));
    assert_eq!(clear["snoozed_thread_ids"], json!([]));
    assert_eq!(clear["rollable"].as_array().unwrap().len(), 6);

    // Simulate session turnover: close current session rows and create a fresh session
    // with stale session snoozes that must not be projected as browser snoozes.
    {
        let conn = state.pool.get().await.unwrap();
        conn.execute(
            "UPDATE sessions SET ended_at = NOW() WHERE user_id = $1 AND ended_at IS NULL",
            &[&user_id],
        )
        .await
        .unwrap();
        conn.execute(
            "INSERT INTO sessions (user_id, started_at, start_die, snoozed_thread_ids)
             VALUES ($1, NOW(), 6, $2::text::json)",
            &[&user_id, &json!([ids[0]]).to_string()],
        )
        .await
        .unwrap();
    }

    let cookie_ids = vec![ids[1], ids[2], foreign];
    let cookie = format!(
        "csrf_token={csrf}; comicpile_roll_snoozes={}",
        json!(cookie_ids)
    );
    let mut request = get("/api/v2/roll/bootstrap", &token, &csrf);
    request
        .headers_mut()
        .insert(header::COOKIE, cookie.parse().unwrap());
    let (status, bootstrap) = send(&state, request).await;
    assert_eq!(status, StatusCode::OK, "{bootstrap:?}");

    // Cookie-only snoozes survive turnover; stale session-only and cross-owner IDs do not.
    assert_eq!(bootstrap["snoozed_count"], json!(2));
    assert_eq!(bootstrap["snoozed_thread_ids"], json!([ids[1], ids[2]]));
    let visible: Vec<_> = bootstrap["rollable"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| row["thread"]["id"].as_i64().unwrap() as i32)
        .collect();
    assert!(
        visible.contains(&ids[0]),
        "stale session snooze leaked after turnover"
    );
    assert!(!visible.contains(&ids[1]));
    assert!(!visible.contains(&ids[2]));

    let (status, offer) = send(
        &state,
        post(
            "/api/v2/roll/offer",
            &token,
            &csrf,
            Some(json!({
                "idempotency_key": "roll-turnover-offer-001",
                "snoozed_thread_ids": [ids[1], ids[2]]
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{offer:?}");
    let selected = offer["thread_id"].as_i64().unwrap() as i32;
    assert!(visible.contains(&selected), "offer not in displayed pool");
}

async fn offer_value(
    state: &Arc<AppState>,
    token: &str,
    csrf: &str,
    key: &str,
    expected_pending: Option<i32>,
) -> Value {
    let mut body = json!({ "idempotency_key": key, "snoozed_thread_ids": [] });
    if let Some(expected) = expected_pending {
        body["expected_pending_thread_id"] = json!(expected);
    }
    let (status, body) = send(state, post("/api/v2/roll/offer", token, csrf, Some(body))).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    body
}

async fn session_state(state: &Arc<AppState>, user_id: i32) -> (Option<i32>, Vec<i32>, i32) {
    let conn = state.pool.get().await.unwrap();
    let row = conn
        .query_one(
            "SELECT pending_thread_id, COALESCE(snoozed_thread_ids::text, '[]') FROM sessions WHERE user_id = $1",
            &[&user_id],
        )
        .await
        .unwrap();
    let ids: String = row.get(1);
    let die: i32 = conn
        .query_one(
            "SELECT die_after FROM events WHERE user_id = $1 \
             AND type IN ('rate','snooze','undo','unsnooze','manual_die','reset_dice') \
             ORDER BY timestamp DESC, id DESC LIMIT 1",
            &[&user_id],
        )
        .await
        .map(|row| row.get(0))
        .unwrap_or(6);
    (row.get(0), serde_json::from_str(&ids).unwrap(), die)
}

#[tokio::test]
async fn roll_unsnooze_of_an_older_snooze_keeps_pending_roll_and_die_and_is_idempotent() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-unsnooze-old").await;
    let ids = rollable_threads(&state.pool.get().await.unwrap(), user_id, 4).await;
    state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "INSERT INTO sessions (user_id, started_at, start_die, pending_thread_id) VALUES ($1, NOW(), 6, $2)",
            &[&user_id, &ids[0]],
        )
        .await
        .unwrap();

    let first = offer_value(&state, &token, &csrf, "unsnooze-old-key-001", Some(ids[0])).await;
    let first_snoozed = first["snoozed_thread_id"].as_i64().unwrap() as i32;
    let second_pending = first["thread_id"].as_i64().unwrap() as i32;
    let second = offer_value(
        &state,
        &token,
        &csrf,
        "unsnooze-old-key-002",
        Some(second_pending),
    )
    .await;
    let second_snoozed = second["snoozed_thread_id"].as_i64().unwrap() as i32;
    let final_pending = second["thread_id"].as_i64().unwrap() as i32;
    let (_, before_ids, before_die) = session_state(&state, user_id).await;
    assert_eq!(before_ids, vec![first_snoozed, second_snoozed]);

    // The older snooze (not the latest) is removed without disturbing the
    // newer pending roll or the die.
    for attempt in 0..2 {
        let (status, body) = send(
            &state,
            post(
                "/api/v2/roll/unsnooze",
                &token,
                &csrf,
                Some(json!({ "thread_id": first_snoozed })),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "attempt {attempt}: {body:?}");
        assert_eq!(body["restored"], json!(false), "{body:?}");
        let (pending, snoozed, die) = session_state(&state, user_id).await;
        assert_eq!(pending, Some(final_pending), "attempt {attempt}");
        assert_eq!(snoozed, vec![second_snoozed], "attempt {attempt}");
        assert_eq!(die, before_die, "attempt {attempt}");
    }
}

#[tokio::test]
async fn roll_unsnooze_after_a_later_die_choice_keeps_the_explicit_die() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-unsnooze-die").await;
    let ids = rollable_threads(&state.pool.get().await.unwrap(), user_id, 3).await;
    state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "INSERT INTO sessions (user_id, started_at, start_die, pending_thread_id) VALUES ($1, NOW(), 6, $2)",
            &[&user_id, &ids[0]],
        )
        .await
        .unwrap();
    let offer = offer_value(&state, &token, &csrf, "unsnooze-die-key-001", Some(ids[0])).await;
    let snoozed = offer["snoozed_thread_id"].as_i64().unwrap() as i32;
    let replacement = offer["thread_id"].as_i64().unwrap() as i32;

    let (status, body) = send(
        &state,
        post(
            "/api/v2/roll/dice-command",
            &token,
            &csrf,
            Some(json!({
                "kind": "manual_select",
                "die": 20,
                "idempotency_key": "unsnooze-die-manual-001"
            })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");

    let (status, body) = send(
        &state,
        post(
            "/api/v2/roll/unsnooze",
            &token,
            &csrf,
            Some(json!({ "thread_id": snoozed })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["restored"], json!(false), "{body:?}");
    assert_eq!(body["die_size"], json!(20), "{body:?}");
    let (pending, snoozed_ids, die) = session_state(&state, user_id).await;
    assert_eq!(die, 20, "the explicit d20 choice must survive unsnooze");
    assert_eq!(pending, Some(replacement));
    assert!(snoozed_ids.is_empty());
}

#[tokio::test]
async fn roll_reset_dice_clears_saved_temporary_snoozes() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-unsnooze-reset").await;
    let ids = rollable_threads(&state.pool.get().await.unwrap(), user_id, 3).await;
    state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "INSERT INTO sessions (user_id, started_at, start_die, pending_thread_id) VALUES ($1, NOW(), 6, $2)",
            &[&user_id, &ids[0]],
        )
        .await
        .unwrap();
    offer_value(
        &state,
        &token,
        &csrf,
        "unsnooze-reset-key-001",
        Some(ids[0]),
    )
    .await;
    assert_eq!(session_state(&state, user_id).await.1.len(), 1);
    let (status, body) = send(
        &state,
        post(
            "/api/v2/roll/reset",
            &token,
            &csrf,
            Some(json!({ "idempotency_key": "unsnooze-reset-reset-001" })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let (pending, snoozed, die) = session_state(&state, user_id).await;
    assert_eq!((pending, snoozed, die), (None, vec![], 6));
}

#[tokio::test]
async fn roll_unsnooze_runs_concurrently_with_reset_and_reroll_without_deadlock() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-unsnooze-conc").await;
    let ids = rollable_threads(&state.pool.get().await.unwrap(), user_id, 4).await;
    state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "INSERT INTO sessions (user_id, started_at, start_die, pending_thread_id) VALUES ($1, NOW(), 6, $2)",
            &[&user_id, &ids[0]],
        )
        .await
        .unwrap();
    let offer = offer_value(&state, &token, &csrf, "unsnooze-conc-key-001", Some(ids[0])).await;
    let snoozed = offer["snoozed_thread_id"].as_i64().unwrap() as i32;
    let replacement = offer["thread_id"].as_i64().unwrap() as i32;

    // Overlap unsnooze with Reset Dice and with a reroll of the replacement.
    // Per-reader advisory-lock ordering must let all three finish; the final
    // state must be one of the serial interleavings.
    let unsnooze_request = post(
        "/api/v2/roll/unsnooze",
        &token,
        &csrf,
        Some(json!({ "thread_id": snoozed })),
    );
    let reset_request = post(
        "/api/v2/roll/reset",
        &token,
        &csrf,
        Some(json!({ "idempotency_key": "unsnooze-conc-reset-001" })),
    );
    let reroll_request = post(
        "/api/v2/roll/offer",
        &token,
        &csrf,
        Some(json!({
            "idempotency_key": "unsnooze-conc-key-002",
            "snoozed_thread_ids": [],
            "expected_pending_thread_id": replacement
        })),
    );
    let (
        (unsnooze_status, unsnooze_body),
        (reset_status, reset_body),
        (reroll_status, reroll_body),
    ) = tokio::join!(
        send(&state, unsnooze_request),
        send(&state, reset_request),
        send(&state, reroll_request)
    );
    assert_eq!(unsnooze_status, StatusCode::OK, "{unsnooze_body:?}");
    assert_eq!(reset_status, StatusCode::OK, "{reset_body:?}");
    // The reroll may legitimately lose its pending-selection precondition when
    // reset or unsnooze commits first; it must never hang or 5xx.
    assert!(
        reroll_status == StatusCode::OK || reroll_status == StatusCode::CONFLICT,
        "{reroll_status} {reroll_body:?}"
    );

    let (pending, snoozed_ids, die) = session_state(&state, user_id).await;
    assert!(
        !snoozed_ids.contains(&snoozed) || reroll_status == StatusCode::OK,
        "unsnooze removed the snooze unless a later reroll re-snoozed it: {snoozed_ids:?}"
    );
    assert!(
        [2, 4, 6, 8, 10, 12, 20].contains(&die),
        "final die must be a valid ladder value, got {die}"
    );
    if let Some(pending) = pending {
        assert!(ids.contains(&pending), "pending must be a real thread");
    }
}

#[tokio::test]
async fn roll_unsnooze_after_a_later_manual_pick_keeps_the_picked_roll() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-unsnooze-pick").await;
    let ids = rollable_threads(&state.pool.get().await.unwrap(), user_id, 4).await;
    state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "INSERT INTO sessions (user_id, started_at, start_die, pending_thread_id) VALUES ($1, NOW(), 6, $2)",
            &[&user_id, &ids[0]],
        )
        .await
        .unwrap();
    let offer = offer_value(&state, &token, &csrf, "unsnooze-pick-key-001", Some(ids[0])).await;
    let snoozed = offer["snoozed_thread_id"].as_i64().unwrap() as i32;
    let picked = ids
        .iter()
        .copied()
        .find(|id| *id != snoozed && *id != offer["thread_id"].as_i64().unwrap() as i32)
        .unwrap();
    {
        // A manual pick records a `roll` event and moves the pending selection.
        let conn = state.pool.get().await.unwrap();
        conn.execute(
            "INSERT INTO events (user_id, type, timestamp, die, thread_id) \
             VALUES ($1, 'roll', clock_timestamp(), 8, $2)",
            &[&user_id, &picked],
        )
        .await
        .unwrap();
        conn.execute(
            "UPDATE sessions SET pending_thread_id = $2 WHERE user_id = $1",
            &[&user_id, &picked],
        )
        .await
        .unwrap();
    }
    let (_, _, die_before) = session_state(&state, user_id).await;

    let (status, body) = send(
        &state,
        post(
            "/api/v2/roll/unsnooze",
            &token,
            &csrf,
            Some(json!({ "thread_id": snoozed })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["restored"], json!(false), "{body:?}");
    let (pending, snoozed_ids, die) = session_state(&state, user_id).await;
    assert_eq!(pending, Some(picked), "the manual pick must survive");
    assert!(snoozed_ids.is_empty());
    assert_eq!(die, die_before);
}

#[tokio::test]
async fn roll_unsnooze_after_a_queue_reorder_event_removes_only_the_snooze() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-unsnooze-reorder").await;
    let ids = rollable_threads(&state.pool.get().await.unwrap(), user_id, 3).await;
    state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "INSERT INTO sessions (user_id, started_at, start_die, pending_thread_id) VALUES ($1, NOW(), 6, $2)",
            &[&user_id, &ids[0]],
        )
        .await
        .unwrap();
    let offer = offer_value(
        &state,
        &token,
        &csrf,
        "unsnooze-reorder-key-001",
        Some(ids[0]),
    )
    .await;
    let snoozed = offer["snoozed_thread_id"].as_i64().unwrap() as i32;
    let replacement = offer["thread_id"].as_i64().unwrap() as i32;
    // A queue move records a `reorder` event with a NULL die.
    state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "INSERT INTO events (user_id, type, timestamp, thread_id) \
             VALUES ($1, 'reorder', clock_timestamp(), $2)",
            &[&user_id, &replacement],
        )
        .await
        .unwrap();
    let (_, _, die_before) = session_state(&state, user_id).await;

    let (status, body) = send(
        &state,
        post(
            "/api/v2/roll/unsnooze",
            &token,
            &csrf,
            Some(json!({ "thread_id": snoozed })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["restored"], json!(false), "{body:?}");
    let (pending, snoozed_ids, die) = session_state(&state, user_id).await;
    assert_eq!(pending, Some(replacement));
    assert!(snoozed_ids.is_empty());
    assert_eq!(die, die_before);
}

#[tokio::test]
async fn roll_unsnooze_of_a_removed_series_removes_only_the_snooze() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-unsnooze-removed").await;
    let ids = rollable_threads(&state.pool.get().await.unwrap(), user_id, 3).await;
    state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "INSERT INTO sessions (user_id, started_at, start_die, pending_thread_id) VALUES ($1, NOW(), 6, $2)",
            &[&user_id, &ids[0]],
        )
        .await
        .unwrap();
    let offer = offer_value(
        &state,
        &token,
        &csrf,
        "unsnooze-removed-key-001",
        Some(ids[0]),
    )
    .await;
    let snoozed = offer["snoozed_thread_id"].as_i64().unwrap() as i32;
    let replacement = offer["thread_id"].as_i64().unwrap() as i32;
    // Remove the snoozed series from the Queue (status change, no event).
    state
        .pool
        .get()
        .await
        .unwrap()
        .execute(
            "UPDATE threads SET status = 'excluded' WHERE id = $1",
            &[&snoozed],
        )
        .await
        .unwrap();
    let (_, _, die_before) = session_state(&state, user_id).await;

    let (status, body) = send(
        &state,
        post(
            "/api/v2/roll/unsnooze",
            &token,
            &csrf,
            Some(json!({ "thread_id": snoozed })),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["restored"], json!(false), "{body:?}");
    let (pending, snoozed_ids, die) = session_state(&state, user_id).await;
    assert_eq!(pending, Some(replacement));
    assert!(snoozed_ids.is_empty());
    assert_eq!(die, die_before);
}

#[tokio::test]
async fn bootstrap_active_thread_exposes_authored_alias_and_confirmed_provider_number() {
    let (state, token, csrf, user_id, _guard) = setup_user("tord-alias").await;
    let conn = state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO sessions (user_id, started_at, start_die) VALUES ($1, NOW(), 6)",
        &[&user_id],
    )
    .await
    .unwrap();

    let pick = thread(&conn, user_id, "Mixed numbering").await;
    let issue_id = issue(&conn, pick, "3", 1, "unread").await;
    conn.execute(
        "UPDATE issues SET issue_number_alias = '100' WHERE id = $1",
        &[&issue_id],
    )
    .await
    .unwrap();
    frontier(&conn, pick, issue_id).await;
    let identity_id: i32 = conn
        .query_one(
            "INSERT INTO external_identities
                (provider, entity_type, external_id, metadata_json, created_at, updated_at)
             VALUES ('comicvine', 'issue', '4050-101',
                     '{\"issue_number\": \"101\", \"image_url\": \"https://comicvine.test/4050-101.jpg\"}'::jsonb,
                     NOW(), NOW()) RETURNING id",
            &[],
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

    let (offer_status, offer_body) = send(
        &state,
        authed(
            "POST",
            "/api/v2/roll/offer",
            &token,
            &csrf,
            Some(json!({ "idempotency_key": "roll-offer-alias-001", "snoozed_thread_ids": [] })),
        ),
    )
    .await;
    assert_eq!(offer_status, StatusCode::OK, "{offer_body:?}");

    let (status, body) = send(&state, get("/api/v2/roll/bootstrap", &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let active = body["active_thread"].as_object().expect("pending thread");
    assert_eq!(active["id"].as_i64(), Some(pick as i64), "{body:?}");
    assert_eq!(active["issue_number"].as_str(), Some("3"));
    assert_eq!(active["issue_number_alias"].as_str(), Some("100"));
    assert_eq!(active["provider_issue_number"].as_str(), Some("101"));
}
