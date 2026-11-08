//! Production-shaped regressions for the reading-dependency cycle outage (#4684).
//!
//! Canonical Alembic schema only: `test_support` loads the real `pg_dump`
//! fixture and connects with the DML-only role. The historical incident
//! identities come from `incident_fixtures`, but every row is allocated through
//! `INSERT ... RETURNING` on the disposable database.
//!
//! These tests exercise the real mounted Rust `/api/v2` handlers and the one
//! production Option E validator. They do not build a parallel graph engine or
//! mock validation.

mod incident_fixtures;
use incident_fixtures as fixture;

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, test_support, AppState};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
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
    std::env::set_var("OPTION_E_APPROVED_PREVIEW", "regression-4684");
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

async fn insert_thread(state: &Arc<AppState>, owner: i32, title: &str, queue: i32) -> i32 {
    let conn = state.pool.get().await.unwrap();
    conn.query_one(
        "INSERT INTO threads
           (title, format, issues_remaining, queue_position, status, user_id, created_at)
         VALUES ($1,'comic',0,$2,'active',$3,NOW())
         RETURNING id",
        &[&title, &queue, &owner],
    )
    .await
    .unwrap()
    .get(0)
}

/// Insert a thread with an explicit persisted order and return `label -> id`.
async fn seed_thread(
    state: &Arc<AppState>,
    owner: i32,
    title: &str,
    queue: i32,
    labels: &[&str],
) -> (i32, BTreeMap<String, i32>) {
    let thread = insert_thread(state, owner, title, queue).await;
    let conn = state.pool.get().await.unwrap();
    let mut ids = BTreeMap::new();
    for (position, label) in labels.iter().enumerate() {
        let id: i32 = conn
            .query_one(
                "INSERT INTO issues (thread_id, issue_number, status, created_at, position)
                 VALUES ($1,$2,'unread',NOW(),$3) RETURNING id",
                &[&thread, label, &(position as i32 + 1)],
            )
            .await
            .unwrap()
            .get(0);
        ids.insert((*label).to_string(), id);
    }
    (thread, ids)
}

async fn seed_list(
    state: &Arc<AppState>,
    owner: i32,
    name: &str,
    mode: &str,
    issue_ids: &[i32],
) -> i32 {
    let conn = state.pool.get().await.unwrap();
    let list_id: i32 = conn
        .query_one(
            "INSERT INTO custom_cbl_lists (user_id, name, mode, created_at, updated_at)
             VALUES ($1,$2,$3,NOW(),NOW()) RETURNING id",
            &[&owner, &name, &mode],
        )
        .await
        .unwrap()
        .get(0);
    for (position, issue_id) in issue_ids.iter().enumerate() {
        conn.execute(
            "INSERT INTO custom_cbl_entries (list_id, issue_id, position, created_at)
             VALUES ($1,$2,$3,NOW())",
            &[&list_id, issue_id, &(position as i32)],
        )
        .await
        .unwrap();
    }
    list_id
}

async fn seed_plan(state: &Arc<AppState>, owner: i32, name: &str, source_list_id: i32) -> i32 {
    let conn = state.pool.get().await.unwrap();
    let plan_id: i32 = conn
        .query_one(
            "INSERT INTO continuity_plans
               (user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
             VALUES ($1,$2,'strict_sequential','[]'::json,'[]'::json,NOW(),NOW())
             RETURNING id",
            &[&owner, &name],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO reading_plan_sources
           (plan_id, raw_source_path, custom_cbl_list_id, recorded_at)
         VALUES ($1,$2,$3,NOW())",
        &[&plan_id, &format!("fixture://{name}"), &source_list_id],
    )
    .await
    .unwrap();
    plan_id
}

async fn mark_read_and_rate(
    state: &Arc<AppState>,
    owner: i32,
    issue_id: i32,
    rating: Option<f64>,
) -> i32 {
    let conn = state.pool.get().await.unwrap();
    conn.execute(
        "UPDATE issues SET status='read', read_at=NOW() WHERE id=$1",
        &[&issue_id],
    )
    .await
    .unwrap();
    let event_id: i32 = conn
        .query_one(
            "INSERT INTO events (type, user_id, issue_id, rating, timestamp)
             VALUES ('rate',$1,$2,$3,NOW()) RETURNING id",
            &[&owner, &issue_id, &rating],
        )
        .await
        .unwrap()
        .get(0);
    event_id
}

async fn position_order(state: &Arc<AppState>, thread: i32) -> Vec<(String, i32)> {
    let conn = state.pool.get().await.unwrap();
    conn.query(
        "SELECT issue_number, id FROM issues WHERE thread_id=$1 ORDER BY position, id",
        &[&thread],
    )
    .await
    .unwrap()
    .iter()
    .map(|row| (row.get(0), row.get(1)))
    .collect()
}

fn cycle_edges(graph: &Value) -> BTreeSet<(String, String, String, String, String)> {
    graph["cycles"]
        .as_array()
        .into_iter()
        .flatten()
        .flat_map(|cycle| cycle["edges"].as_array().into_iter().flatten())
        .map(|edge| {
            (
                edge["source"]["series_title"].as_str().unwrap().to_string(),
                edge["source"]["issue_number"].as_str().unwrap().to_string(),
                edge["target"]["series_title"].as_str().unwrap().to_string(),
                edge["target"]["issue_number"].as_str().unwrap().to_string(),
                edge["kind"].as_str().unwrap().to_string(),
            )
        })
        .collect()
}

fn bprd_list_order(ids: &BTreeMap<String, i32>) -> Vec<i32> {
    // The canonical Julix relation that matters here: #142 precedes #130.
    // Additional list entries would add their own adjacent edges; keep the
    // fixture focused on the historical conflicting edge.
    ["142", "130"].iter().map(|label| ids[*label]).collect()
}

#[tokio::test]
async fn confirmed_repair_revalidates_after_waiting_for_a_graph_writer() {
    let Some((state, _db)) = database().await else {
        return;
    };
    let (token, csrf, owner) = register(&state, "repair-race").await;
    let (_, issues) = seed_thread(&state, owner, "Race Series", 1, &["1", "2", "3"]).await;
    // A strict backwards edge (3 -> 1) conflicts with series order (1 -> 2 -> 3).
    let list = seed_list(
        &state,
        owner,
        "Race List",
        "strict",
        &[issues["3"], issues["1"]],
    )
    .await;
    let request = json!({
        "action": "delete_list_entry",
        "list_id": list,
        "issue_id": issues["1"],
    });
    let (preview_status, preview) = send(
        &state,
        (&token, &csrf),
        "POST",
        "/api/v2/reading-graph/repairs",
        Some(request.clone()),
    )
    .await;
    assert_eq!(preview_status, StatusCode::OK, "{preview}");
    assert_eq!(preview["status_before"], "cycle");
    assert!(preview["graph"]["repairs"]
        .as_array()
        .unwrap()
        .iter()
        .any(|option| option["action"] == "delete_list_entry"
            && option["list_id"] == list
            && option["issue_id"] == issues["1"]));

    // Simulate a competing, correctly serialized Reading List writer holding
    // the exact same advisory lock as dependency creation and repair.
    let mut writer = state.pool.get().await.unwrap();
    let writer_tx = writer.transaction().await.unwrap();
    writer_tx
        .execute(
            "SELECT pg_advisory_xact_lock($1,$2)",
            &[&699001_i32, &owner],
        )
        .await
        .unwrap();

    let request = json!({
        "action": "delete_list_entry",
        "list_id": list,
        "issue_id": issues["1"],
        "confirm": true,
    });
    let repair_state = state.clone();
    let task = tokio::spawn(async move {
        send(
            &repair_state,
            (&token, &csrf),
            "POST",
            "/api/v2/reading-graph/repairs",
            Some(request),
        )
        .await
    });

    // Wait for the handler to attempt its reader lock. On the previous
    // implementation its snapshot was already read at this point, so the
    // following graph edit caused an unsafe stale repair. This is a real
    // PostgreSQL lock wait rather than a timing-dependent sleep.
    let observer = state.pool.get().await.unwrap();
    tokio::time::timeout(std::time::Duration::from_secs(8), async {
        loop {
            let waiting: bool = observer
                .query_one(
                    "SELECT EXISTS(SELECT 1 FROM pg_locks
                     WHERE locktype='advisory' AND NOT granted
                       AND classid::integer=$1 AND objid::integer=$2)",
                    &[&699001_i32, &owner],
                )
                .await
                .unwrap()
                .get(0);
            if waiting {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("confirmed repair should block on the writer's advisory lock");

    // The writer resolves the cycle by deleting a *different* list entry.
    // The requested entry still exists, but is no longer an offered repair.
    writer_tx
        .execute(
            "DELETE FROM custom_cbl_entries WHERE list_id=$1 AND issue_id=$2",
            &[&list, &issues["3"]],
        )
        .await
        .unwrap();
    writer_tx.commit().await.unwrap();
    drop(writer);
    drop(observer);

    let (status, response) = task.await.unwrap();
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{response}");
    assert_eq!(
        response["detail"],
        "Repair is not applicable to the current reading graph"
    );

    let reader = state.pool.get().await.unwrap();
    let remaining: Vec<i32> = reader
        .query(
            "SELECT issue_id FROM custom_cbl_entries WHERE list_id=$1 ORDER BY position",
            &[&list],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| row.get(0))
        .collect();
    assert_eq!(
        remaining,
        vec![issues["1"]],
        "stale repair must not delete it"
    );
}

#[tokio::test]
async fn bprd_normal_add_preserves_reader_order_and_return_master_history() {
    let Some((state, _db)) = database().await else {
        return;
    };
    let (token, csrf, owner) = register(&state, "bprd-normal").await;
    let auth = (token.as_str(), csrf.as_str());

    let labels: Vec<&str> = fixture::BPRD_BEFORE_ISSUE_NUMBERS
        .iter()
        .map(|number| Box::leak(number.to_string().into_boxed_str()) as &str)
        .collect();
    let (bprd, bprd_ids) = seed_thread(&state, owner, "B.P.R.D.: Hell on Earth", 1, &labels).await;
    let julix = seed_list(
        &state,
        owner,
        "Mignolaverse — Julix Comics (Unread)",
        "strict",
        &bprd_list_order(&bprd_ids),
    )
    .await;
    // A separate story-arc thread holds the original physical #98–#102 identities.
    let (return_master, master_ids) = seed_thread(
        &state,
        owner,
        "B.P.R.D.: The Return of the Master",
        2,
        &["1", "2", "3", "4", "5"],
    )
    .await;
    let mut protected_events = vec![];
    for label in ["3", "4", "5"] {
        protected_events.push(
            mark_read_and_rate(
                &state,
                owner,
                master_ids[label],
                (label != "3").then_some(fixture::RETURN_MASTER_LATER_RATING as f64),
            )
            .await,
        );
    }
    // A genuinely unrelated healthy series must keep rolling.
    let (_healthy, healthy_ids) = seed_thread(
        &state,
        owner,
        fixture::UNRELATED_FIXTURE_THREAD,
        3,
        &[fixture::UNRELATED_FIXTURE_ISSUE_NO],
    )
    .await;

    let before = position_order(&state, bprd).await;
    let (status, created) = send(
        &state,
        auth,
        "POST",
        &format!("/api/v2/threads/{bprd}/issues"),
        Some(json!({"issue_range": fixture::BPRD_INSERTED_NUMBERS
            .iter()
            .map(u16::to_string)
            .collect::<Vec<_>>()
            .join(",")})),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    assert_eq!(created["issues"].as_array().unwrap().len(), 2);

    // Existing relative order is unchanged; new labels append because the
    // reader-authored series order is intentionally non-monotonic.
    let after = position_order(&state, bprd).await;
    assert_eq!(after[..before.len()], before[..]);
    assert_eq!(
        after[before.len()..]
            .iter()
            .map(|(label, _)| label.as_str())
            .collect::<Vec<_>>(),
        vec!["101", "102"]
    );

    // No global cycle was introduced.
    let (status, graph) = send(&state, auth, "GET", "/api/v2/reading-graph", None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(graph["status"], "ok");

    // The healthy series still rolls, and the added labels are not silent
    // duplicates of the completed Return of the Master chapters.
    let (status, eligible) =
        send(&state, auth, "GET", "/api/v2/roll/eligible-issue-ids", None).await;
    assert_eq!(status, StatusCode::OK, "{eligible}");
    let eligible_ids: Vec<i32> = eligible["issue_ids"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| value.as_i64().unwrap() as i32)
        .collect();
    assert!(eligible_ids.contains(&healthy_ids["1"]));
    assert!(eligible_ids.contains(&bprd_ids["129"]));
    for issue in created["issues"].as_array().unwrap() {
        let id = issue["id"].as_i64().unwrap() as i32;
        assert!(!eligible_ids.contains(&id));
    }

    // Original reads and ratings remain exactly as they were.
    let conn = state.pool.get().await.unwrap();
    let master_rows = conn
        .query(
            "SELECT id, status FROM issues WHERE thread_id=$1 ORDER BY position",
            &[&return_master],
        )
        .await
        .unwrap();
    assert_eq!(
        master_rows.len(),
        5,
        "no issue was auto-created in the arc thread"
    );
    for row in &master_rows {
        let id: i32 = row.get(0);
        if ["3", "4", "5"].iter().any(|label| master_ids[*label] == id) {
            assert_eq!(row.get::<_, String>(1), "read");
        }
    }
    for event_id in protected_events {
        let exists: bool = conn
            .query_one(
                "SELECT EXISTS(SELECT 1 FROM events WHERE id=$1)",
                &[&event_id],
            )
            .await
            .unwrap()
            .get(0);
        assert!(exists, "historical rating event {event_id} was not removed");
    }
    let rated: Vec<(i32, f64)> = conn
        .query(
            "SELECT issue_id, rating FROM events
             WHERE issue_id=ANY($1) ORDER BY issue_id",
            &[&vec![master_ids["4"], master_ids["5"]]],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();
    assert_eq!(
        rated,
        vec![
            (master_ids["4"], fixture::RETURN_MASTER_LATER_RATING as f64),
            (master_ids["5"], fixture::RETURN_MASTER_LATER_RATING as f64),
        ]
    );
    // The source list is unchanged and still references the original PK.
    let list_entries: i64 = conn
        .query_one(
            "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1",
            &[&julix],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(list_entries as usize, bprd_list_order(&bprd_ids).len());
}

#[tokio::test]
async fn bprd_legacy_numeric_reorder_reproduces_exact_cycle_but_reads_survive() {
    let Some((state, _db)) = database().await else {
        return;
    };
    let (token, csrf, owner) = register(&state, "bprd-legacy").await;
    let auth = (token.as_str(), csrf.as_str());

    // The former all-numeric insertion produced this persisted order.
    let broken_labels: Vec<&str> = fixture::BPRD_BROKEN_NUMERIC_ORDER
        .iter()
        .map(|number| Box::leak(number.to_string().into_boxed_str()) as &str)
        .collect();
    let (bprd, ids) =
        seed_thread(&state, owner, "B.P.R.D.: Hell on Earth", 1, &broken_labels).await;
    let julix = seed_list(
        &state,
        owner,
        "Mignolaverse — Julix Comics (Unread)",
        "strict",
        &bprd_list_order(&ids),
    )
    .await;
    let (_healthy, healthy_ids) = seed_thread(
        &state,
        owner,
        fixture::UNRELATED_FIXTURE_THREAD,
        2,
        &[fixture::UNRELATED_FIXTURE_ISSUE_NO],
    )
    .await;

    // Strict authoring preflight sees the exact historical loop and refuses to
    // add another issue. This is the same validator the former read path used,
    // which is why every read returned 500.
    let (status, rejected) = send(
        &state,
        auth,
        "POST",
        &format!("/api/v2/threads/{bprd}/issues"),
        Some(json!({"issue_range": "103"})),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{rejected}");
    let detail = rejected["detail"].as_str().unwrap();
    assert!(detail.contains("Reading constraint cycle"), "{detail}");
    assert!(detail.contains("142"), "{detail}");
    assert!(detail.contains("130"), "{detail}");
    assert!(detail.contains("Nothing was changed"), "{detail}");
    assert!(!position_order(&state, bprd)
        .await
        .iter()
        .any(|(label, _)| label == "103"));

    // A reader session exists for the normal Roll bootstrap read.
    let (status, session) = send(
        &state,
        auth,
        "POST",
        "/api/v2/reading-sessions",
        Some(json!({"timezone": null})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{session}");

    // Read-side containment: the same persisted graph no longer 500s.
    for path in [
        "/api/v2/roll/bootstrap",
        "/api/v2/roll/eligible-issue-ids",
        "/api/v2/roll/die-state",
        "/api/v2/threads",
        "/api/v2/reading-graph",
    ] {
        let (status, body) = send(&state, auth, "GET", path, None).await;
        assert_eq!(status, StatusCode::OK, "{path}: {body}");
    }
    let (_, eligible) = send(&state, auth, "GET", "/api/v2/roll/eligible-issue-ids", None).await;
    let eligible_ids: Vec<i32> = eligible["issue_ids"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| value.as_i64().unwrap() as i32)
        .collect();
    assert_eq!(eligible_ids, vec![healthy_ids["1"]]);

    let (_, graph) = send(&state, auth, "GET", "/api/v2/reading-graph", None).await;
    assert_eq!(graph["status"], "cycle");
    assert!(graph["affected_lists"]
        .as_array()
        .unwrap()
        .iter()
        .any(|list| list["name"] == "Mignolaverse — Julix Comics (Unread)"));
    let edges = cycle_edges(&graph);
    assert!(edges.contains(&(
        "B.P.R.D.: Hell on Earth".into(),
        "142".into(),
        "B.P.R.D.: Hell on Earth".into(),
        "130".into(),
        "strict_order".into(),
    )));
    assert!(edges
        .iter()
        .any(|(source_series, source, target_series, target, kind)| {
            source_series == "B.P.R.D.: Hell on Earth"
                && source == "139"
                && target_series == "B.P.R.D.: Hell on Earth"
                && target == "140"
                && kind == "series_order"
        }));

    // Manual Read/Rate remains available on the affected series.
    let read_target = ids["131"];
    let (status, rated) = send(
        &state,
        auth,
        "PATCH",
        &format!("/api/v2/issues/{read_target}"),
        Some(json!({"status": "read", "rating": 4.0, "idempotency_key": "incident-4684-read"})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{rated}");

    // Repair deletes only the list constraint and restores the affected series.
    let (status, repaired) = send(
        &state,
        auth,
        "POST",
        "/api/v2/reading-graph/repairs",
        Some(json!({"action": "delete_list", "list_id": julix, "confirm": true})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{repaired}");
    assert_eq!(repaired["status_after"], "ok");
    let (_, healthy_graph) = send(&state, auth, "GET", "/api/v2/reading-graph", None).await;
    assert_eq!(healthy_graph["status"], "ok");
    let (_, eligible) = send(&state, auth, "GET", "/api/v2/roll/eligible-issue-ids", None).await;
    let ids_after: Vec<i32> = eligible["issue_ids"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| value.as_i64().unwrap() as i32)
        .collect();
    assert!(!ids_after.is_empty());
    assert!(ids_after.contains(&healthy_ids["1"]));
    // The repaired graph is readable and rollable again. Canonical physical
    // identity for duplicate #101/#102 remains tracked by #4667/#4653; this
    // incident fix does not silently mark or delete those historical rows.
}

#[tokio::test]
async fn referenced_issue_delete_is_refused_and_readding_label_does_not_heal() {
    let Some((state, _db)) = database().await else {
        return;
    };
    let (token, csrf, owner) = register(&state, "qa-morning").await;
    let auth = (token.as_str(), csrf.as_str());
    let (superman, su) = seed_thread(&state, owner, "Superman", 1, &["1", "2", "3"]).await;
    let (_batman, ba) = seed_thread(&state, owner, "Batman", 2, &["1", "2"]).await;
    let list = seed_list(
        &state,
        owner,
        "QA Destructive A",
        "strict",
        &[su["1"], su["2"], su["3"], ba["1"], ba["2"]],
    )
    .await;
    let plan = seed_plan(&state, owner, "QA Destructive A", list).await;
    let original_two = su["2"];
    let history = mark_read_and_rate(&state, owner, su["1"], Some(4.5)).await;

    let (status, rejected) = send(
        &state,
        auth,
        "DELETE",
        &format!("/api/v2/issues/{original_two}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{rejected}");
    let detail = rejected["detail"].as_str().unwrap();
    assert!(detail.contains("QA Destructive A"), "{detail}");
    assert!(detail.contains("nothing was changed"), "{detail}");

    // Nothing was mutated: issue, list entry, plan source and history survive.
    let conn = state.pool.get().await.unwrap();
    let count: i64 = conn
        .query_one("SELECT count(*) FROM issues WHERE id=$1", &[&original_two])
        .await
        .unwrap()
        .get(0);
    assert_eq!(count, 1);
    let entries: i64 = conn
        .query_one(
            "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1 AND issue_id=$2",
            &[&list, &original_two],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(entries, 1);
    let plan_sources: i64 = conn
        .query_one(
            "SELECT count(*) FROM reading_plan_sources WHERE plan_id=$1 AND custom_cbl_list_id=$2",
            &[&plan, &list],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(plan_sources, 1);
    let history_exists: bool = conn
        .query_one(
            "SELECT EXISTS(SELECT 1 FROM events WHERE id=$1)",
            &[&history],
        )
        .await
        .unwrap()
        .get(0);
    assert!(history_exists);

    // Re-adding the same label creates a different PK; the list still points at
    // the original, so the string label alone does not heal anything.
    let (status, created) = send(
        &state,
        auth,
        "POST",
        &format!("/api/v2/threads/{superman}/issues"),
        Some(json!({"issue_range": "2"})),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{created}");
    assert!(created["detail"]
        .as_str()
        .unwrap()
        .contains("already exist"));
    let (status, created_other) = send(
        &state,
        auth,
        "POST",
        &format!("/api/v2/threads/{superman}/issues"),
        Some(json!({"issue_range": "4"})),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created_other}");
    let new_four = created_other["issues"][0]["id"].as_i64().unwrap() as i32;
    let still_original: i64 = conn
        .query_one(
            "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1 AND issue_id=$2",
            &[&list, &original_two],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(still_original, 1);
    let new_four_in_list: i64 = conn
        .query_one(
            "SELECT count(*) FROM custom_cbl_entries WHERE list_id=$1 AND issue_id=$2",
            &[&list, &new_four],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(new_four_in_list, 0);
}

#[tokio::test]
async fn evening_four_edge_cycle_is_repairable_and_two_owners_stay_isolated() {
    let Some((state, _db)) = database().await else {
        return;
    };
    let (token, csrf, owner) = register(&state, "muse-evening").await;
    let auth = (token.as_str(), csrf.as_str());
    let (other_token, other_csrf, other) = register(&state, "muse-second-owner").await;
    let other_auth = (other_token.as_str(), other_csrf.as_str());

    // Exact QA evening identities, allocated fresh.
    let (superman, su) = seed_thread(&state, owner, "Superman", 1, &["1", "2", "3"]).await;
    let (_batman, ba) = seed_thread(&state, owner, "Batman", 2, &["1", "2"]).await;
    let list_a = seed_list(
        &state,
        owner,
        "QA Destructive C",
        "strict",
        &[su["1"], su["2"], su["3"], ba["1"], ba["2"]],
    )
    .await;
    let list_b = seed_list(
        &state,
        owner,
        "QA Destructive B - Tab2",
        "strict",
        &[su["1"], ba["1"], ba["2"], su["2"]],
    )
    .await;
    let (_unrelated, unrelated_ids) = seed_thread(
        &state,
        owner,
        fixture::UNRELATED_FIXTURE_THREAD,
        3,
        &[fixture::UNRELATED_FIXTURE_ISSUE_NO],
    )
    .await;
    let (_other_unrelated, other_ids) =
        seed_thread(&state, other, "Other owner healthy series", 1, &["1"]).await;
    let plan_new = seed_plan(&state, owner, "QA Destructive C plan", list_a).await;
    let plan_prior = seed_plan(&state, owner, "QA Destructive A plan", list_b).await;
    let plan_linked = seed_plan(&state, owner, "QA Destructive C linked view", list_a).await;
    let history = mark_read_and_rate(&state, owner, su["1"], Some(4.0)).await;

    // The exact four-edge cycle exists in the stored graph.
    let (status, graph) = send(&state, auth, "GET", "/api/v2/reading-graph", None).await;
    assert_eq!(status, StatusCode::OK, "{graph}");
    assert_eq!(graph["status"], "cycle");
    let edges = cycle_edges(&graph);
    let expected: BTreeSet<(String, String, String, String, String)> = [
        ("Superman", "3", "Batman", "1", "strict_order"),
        ("Batman", "1", "Batman", "2", "series_order"),
        ("Batman", "2", "Superman", "2", "strict_order"),
        ("Superman", "2", "Superman", "3", "series_order"),
    ]
    .into_iter()
    .map(|(a, b, c, d, kind)| {
        (
            a.to_string(),
            b.to_string(),
            c.to_string(),
            d.to_string(),
            kind.to_string(),
        )
    })
    .collect();
    assert!(expected.is_subset(&edges), "{edges:?}");
    assert_eq!(graph["affected_lists"].as_array().unwrap().len(), 2);

    // A projected edit that would preserve the cycle is rejected before write.
    let (status, rejected) = send(
        &state,
        auth,
        "POST",
        &format!("/api/v2/threads/{superman}/issues"),
        Some(json!({"issue_range": "4"})),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{rejected}");
    assert!(rejected["detail"]
        .as_str()
        .unwrap()
        .contains("Nothing was changed"));

    // Both readers have a session before the bootstrap read.
    for auth in [auth, other_auth] {
        let (status, session) = send(
            &state,
            auth,
            "POST",
            "/api/v2/reading-sessions",
            Some(json!({"timezone": null})),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{session}");
    }

    // Read paths stay available for the affected owner and the second owner.
    for auth in [auth, other_auth] {
        for path in [
            "/api/v2/roll/bootstrap",
            "/api/v2/roll/eligible-issue-ids",
            "/api/v2/threads",
            "/api/v2/reading-graph",
        ] {
            let (status, body) = send(&state, auth, "GET", path, None).await;
            assert_eq!(status, StatusCode::OK, "{path}: {body}");
        }
    }
    let (_, eligible) = send(&state, auth, "GET", "/api/v2/roll/eligible-issue-ids", None).await;
    let eligible_ids: Vec<i32> = eligible["issue_ids"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| value.as_i64().unwrap() as i32)
        .collect();
    assert_eq!(eligible_ids, vec![unrelated_ids["1"]]);
    let (_, other_eligible) = send(
        &state,
        other_auth,
        "GET",
        "/api/v2/roll/eligible-issue-ids",
        None,
    )
    .await;
    assert_eq!(
        other_eligible["issue_ids"].as_array().unwrap()[0]
            .as_i64()
            .unwrap() as i32,
        other_ids["1"]
    );

    // Owner isolation: another reader cannot repair this owner's list.
    let (status, cross_owner) = send(
        &state,
        other_auth,
        "POST",
        "/api/v2/reading-graph/repairs",
        Some(json!({"action": "delete_list", "list_id": list_a, "confirm": true})),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{cross_owner}");

    // Deleting the observed plan does not delete list provenance.
    let conn = state.pool.get().await.unwrap();
    conn.execute("DELETE FROM continuity_plans WHERE id=$1", &[&plan_new])
        .await
        .unwrap();
    let list_still_exists: bool = conn
        .query_one(
            "SELECT EXISTS(SELECT 1 FROM custom_cbl_lists WHERE id=$1)",
            &[&list_a],
        )
        .await
        .unwrap()
        .get(0);
    assert!(list_still_exists);
    let prior_exists: bool = conn
        .query_one(
            "SELECT EXISTS(SELECT 1 FROM continuity_plans WHERE id=$1)",
            &[&plan_prior],
        )
        .await
        .unwrap()
        .get(0);
    assert!(prior_exists);

    // A graph repair must not bypass the same source identity guard as list DELETE.
    let (status, refused) = send(
        &state,
        auth,
        "POST",
        "/api/v2/reading-graph/repairs",
        Some(json!({"action": "delete_list", "list_id": list_a, "confirm": true})),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{refused}");

    // Repair the specific constraint instead of orphaning the plan. The
    // Batman #2 -> Superman #2 edge belongs to this entry of list B.
    let (status, preview) = send(
        &state,
        auth,
        "POST",
        "/api/v2/reading-graph/repairs",
        Some(json!({"action": "delete_list_entry", "list_id": list_b, "issue_id": su["2"]})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preview}");
    assert_eq!(preview["applied"], false);
    assert_eq!(preview["status_after"], "ok");

    let (status, applied) = send(
        &state,
        auth,
        "POST",
        "/api/v2/reading-graph/repairs",
        Some(json!({"action": "delete_list_entry", "list_id": list_b, "issue_id": su["2"], "confirm": true})),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{applied}");
    assert_eq!(applied["status_after"], "ok");

    // All original Plan source identities remain intact.
    let prior_source: Option<i32> = conn
        .query_one(
            "SELECT custom_cbl_list_id FROM reading_plan_sources WHERE plan_id=$1",
            &[&plan_prior],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(prior_source, Some(list_b));
    // The plan is not orphaned by removing a single cyclic constraint.
    let linked_source: Option<i32> = conn
        .query_one(
            "SELECT custom_cbl_list_id FROM reading_plan_sources WHERE plan_id=$1",
            &[&plan_linked],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(linked_source, Some(list_a));
    let linked_plan_exists: bool = conn
        .query_one(
            "SELECT EXISTS(SELECT 1 FROM continuity_plans WHERE id=$1)",
            &[&plan_linked],
        )
        .await
        .unwrap()
        .get(0);
    assert!(linked_plan_exists);

    let (_, graph) = send(&state, auth, "GET", "/api/v2/reading-graph", None).await;
    assert_eq!(graph["status"], "ok");
    let (_, eligible) = send(&state, auth, "GET", "/api/v2/roll/eligible-issue-ids", None).await;
    let eligible_ids: Vec<i32> = eligible["issue_ids"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| value.as_i64().unwrap() as i32)
        .collect();
    assert!(eligible_ids.contains(&unrelated_ids["1"]));
    // List A was deliberately retained as the linked Plan's authority.
    // Batman #1 is still correctly gated by the unread Superman entries,
    // unlike an unrelated Thread which must remain Roll-eligible.
    assert!(!eligible_ids.contains(&ba["1"]));

    // Legitimate history is intact after recovery.
    let history_exists: bool = conn
        .query_one(
            "SELECT EXISTS(SELECT 1 FROM events WHERE id=$1)",
            &[&history],
        )
        .await
        .unwrap()
        .get(0);
    assert!(history_exists);
    let still_read: String = conn
        .query_one("SELECT status FROM issues WHERE id=$1", &[&su["1"]])
        .await
        .unwrap()
        .get(0);
    assert_eq!(still_read, "read");
}

#[tokio::test]
async fn reading_list_resources_contain_cycles_and_reject_cyclic_creation() {
    let Some((state, _db)) = database().await else {
        return;
    };
    let (token, csrf, owner) = register(&state, "reading-list-owner").await;
    let auth = (token.as_str(), csrf.as_str());
    let (_other_token, _other_csrf, _other) = register(&state, "reading-list-other").await;

    let broken_labels: Vec<&str> = fixture::BPRD_BROKEN_NUMERIC_ORDER
        .iter()
        .map(|number| Box::leak(number.to_string().into_boxed_str()) as &str)
        .collect();
    let (_bprd, ids) =
        seed_thread(&state, owner, "B.P.R.D.: Hell on Earth", 1, &broken_labels).await;
    let list = seed_list(
        &state,
        owner,
        "Mignolaverse — Julix Comics (Unread)",
        "strict",
        &bprd_list_order(&ids),
    )
    .await;

    let (status, lists) = send(&state, auth, "GET", "/api/v2/reading-lists", None).await;
    assert_eq!(status, StatusCode::OK, "{lists}");
    assert!(lists
        .as_array()
        .unwrap()
        .iter()
        .any(|row| row["id"] == list));

    let (status, detail) = send(
        &state,
        auth,
        "GET",
        &format!("/api/v2/reading-lists/{list}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{detail}");
    assert_eq!(detail["mode"], "strict");
    assert_eq!(detail["entries"].as_array().unwrap().len(), 2);

    let (status, reader) = send(
        &state,
        auth,
        "GET",
        &format!("/api/v2/reading-lists/{list}/reader"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{reader}");
    assert_eq!(reader["execution_mode"], "option_e");
    assert!(reader["entries"]
        .as_array()
        .unwrap()
        .iter()
        .all(|entry| entry["availability"] != "legacy"));

    // Creating another projection that closes the same cycle is rejected and
    // leaves the existing list count unchanged.
    let (status, rejected) = send(
        &state,
        auth,
        "POST",
        "/api/v2/reading-lists",
        Some(json!({
            "name": "Rejected cycle list",
            "mode": "strict",
            "issue_ids": [ids["142"], ids["130"]]
        })),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{rejected}");
    assert!(rejected["detail"]
        .as_str()
        .unwrap()
        .contains("Nothing was changed"));
    let conn = state.pool.get().await.unwrap();
    let count: i64 = conn
        .query_one(
            "SELECT count(*) FROM custom_cbl_lists WHERE user_id=$1",
            &[&owner],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(count, 1);
}

#[tokio::test]
async fn reading_list_create_rejects_predecessor_confirmation_like_python() {
    let Some((state, _db)) = database().await else {
        return;
    };
    let (token, csrf, owner) = register(&state, "reading-list-confirmation").await;
    let auth = (token.as_str(), csrf.as_str());
    let (status, rejected) = send(
        &state,
        auth,
        "POST",
        "/api/v2/reading-lists",
        Some(json!({
            "name": "Confirmed create",
            "issue_ids": [],
            "confirmed_predecessor_changes": []
        })),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{rejected}");
    let conn = state.pool.get().await.unwrap();
    let count: i64 = conn
        .query_one(
            "SELECT count(*) FROM custom_cbl_lists WHERE user_id=$1",
            &[&owner],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(count, 0);
}

#[tokio::test]
async fn plan_a_orphan_recovery_preserves_history_and_plan_b_authority() {
    let Some((state, _db)) = database().await else {
        return;
    };
    let (token, csrf, owner) = register(&state, "orphan-plan-a").await;
    let auth = (token.as_str(), csrf.as_str());
    let (other_token, other_csrf, _other) = register(&state, "orphan-other").await;
    let other_auth = (other_token.as_str(), other_csrf.as_str());

    let (superman, su) = seed_thread(&state, owner, "Superman", 1, &["1", "2", "3", "4"]).await;
    let (_batman, ba) = seed_thread(&state, owner, "Batman", 2, &["1", "2"]).await;
    let original_two = su["2"];
    let history = mark_read_and_rate(&state, owner, original_two, Some(4.5)).await;
    let conn = state.pool.get().await.unwrap();

    // The real failure was a physical deletion, not a renamed list. The
    // original Superman #2 PK disappears and a same-number issue is allocated.
    conn.execute("DELETE FROM issues WHERE id=$1", &[&original_two])
        .await
        .unwrap();
    let replacement_two: i32 = conn
        .query_one(
            "INSERT INTO issues (thread_id,issue_number,status,created_at,position)
         VALUES ($1,'2','unread',NOW(),2) RETURNING id",
            &[&superman],
        )
        .await
        .unwrap()
        .get(0);
    assert_ne!(original_two, replacement_two);

    // Exact Plan A shape: four surviving historical memberships and NO
    // reading_plan_sources row. This recreates the legacy list-delete cleanup
    // rather than assuming ON DELETE SET NULL always preserved source rows.
    let retained = [su["1"], su["3"], ba["1"], ba["2"]];
    let plan_a: i32 = conn
        .query_one(
            "INSERT INTO continuity_plans
           (user_id,name,ordering_mode,nodes_json,lanes_json,created_at,updated_at)
         VALUES ($1,'QA Destructive A','strict_sequential','[]'::json,'[]'::json,NOW(),NOW())
         RETURNING id",
            &[&owner],
        )
        .await
        .unwrap()
        .get(0);
    for (position, issue_id) in retained.iter().enumerate() {
        let label = ["Superman #1", "Superman #3", "Batman #1", "Batman #2"][position];
        conn.execute(
            "INSERT INTO reading_plan_issues
              (plan_id,occurrence_id,issue_id,lane_id,display_position,label,is_checkpoint)
             VALUES ($1,$2,$3,'main',$4,$5,false)",
            &[
                &plan_a,
                &format!("issue-{issue_id}"),
                issue_id,
                &(position as i32),
                &label,
            ],
        )
        .await
        .unwrap();
    }

    let list_b = seed_list(
        &state,
        owner,
        "QA Destructive B - Tab2",
        "strict",
        &[su["1"], replacement_two, su["4"], ba["1"], ba["2"]],
    )
    .await;
    let plan_b = seed_plan(&state, owner, "QA Destructive B", list_b).await;
    let (status, b_reader) = send(
        &state,
        auth,
        "GET",
        &format!("/api/v2/reading-lists/{list_b}/reader"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{b_reader}");
    assert_eq!(b_reader["entries"].as_array().unwrap().len(), 5);

    let endpoint = format!("/api/v2/continuity-plans/{plan_a}/recovery");
    let (status, foreign) = send(&state, other_auth, "GET", &endpoint, None).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{foreign}");
    let (status, preview) = send(&state, auth, "GET", &endpoint, None).await;
    assert_eq!(status, StatusCode::OK, "{preview}");
    assert_eq!(preview["status"], "orphaned");
    assert_eq!(preview["retained_steps"].as_array().unwrap().len(), 4);
    let candidate = preview["candidates"]
        .as_array()
        .unwrap()
        .iter()
        .find(|item| item["list_id"] == list_b)
        .unwrap();
    assert_eq!(candidate["added_steps"].as_array().unwrap().len(), 2);
    assert_eq!(candidate["added_steps"][0]["issue_id"], replacement_two);
    assert_eq!(candidate["removed_steps"].as_array().unwrap().len(), 1);
    assert_eq!(candidate["removed_steps"][0]["issue_id"], su["3"]);
    assert_eq!(candidate["order_changed"], false);

    let request = json!({
        "list_id": list_b,
        "expected_plan_updated_at": preview["plan_updated_at"],
        "expected_list_updated_at": candidate["list_updated_at"],
        "confirm": true
    });
    let (status, refused) =
        send(&state, other_auth, "POST", &endpoint, Some(request.clone())).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{refused}");
    let (status, missing_confirmation) = send(
        &state,
        auth,
        "POST",
        &endpoint,
        Some(
            json!({"list_id":list_b,"expected_plan_updated_at":preview["plan_updated_at"],
            "expected_list_updated_at":candidate["list_updated_at"],"confirm":false}),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{missing_confirmation}");

    // Read-only preview and cross-owner failures never mutate the source.
    let prior_count: i64 = conn
        .query_one(
            "SELECT count(*) FROM reading_plan_sources WHERE plan_id=$1",
            &[&plan_a],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(prior_count, 0);

    let (status, applied) = send(&state, auth, "POST", &endpoint, Some(request.clone())).await;
    assert_eq!(status, StatusCode::OK, "{applied}");
    assert_eq!(applied["status"], "relinked");
    let (status, retried) = send(&state, auth, "POST", &endpoint, Some(request)).await;
    assert_eq!(status, StatusCode::OK, "{retried}");
    assert_eq!(retried["status"], "already_linked");

    // A linked Plan cannot be silently stranded by ordinary DELETE either.
    let (status, blocked_delete) = send(
        &state,
        auth,
        "DELETE",
        &format!("/api/v2/reading-lists/{list_b}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{blocked_delete}");
    assert!(blocked_delete["detail"]
        .as_str()
        .unwrap()
        .contains("Reading Plan"));

    let source: i32 = conn
        .query_one(
            "SELECT custom_cbl_list_id FROM reading_plan_sources WHERE plan_id=$1",
            &[&plan_a],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(source, list_b);
    let source_count: i64 = conn
        .query_one(
            "SELECT count(*) FROM reading_plan_sources WHERE plan_id=$1",
            &[&plan_a],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(source_count, 1);
    let plan_b_source: i32 = conn
        .query_one(
            "SELECT custom_cbl_list_id FROM reading_plan_sources WHERE plan_id=$1",
            &[&plan_b],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(plan_b_source, list_b);
    let saved: Vec<i32> = conn
        .query(
            "SELECT issue_id FROM reading_plan_issues WHERE plan_id=$1 ORDER BY display_position",
            &[&plan_a],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| row.get(0))
        .collect();
    assert_eq!(saved, retained.to_vec());
    let list_order: Vec<i32> = conn
        .query(
            "SELECT issue_id FROM custom_cbl_entries WHERE list_id=$1 ORDER BY position",
            &[&list_b],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| row.get(0))
        .collect();
    assert_eq!(
        list_order,
        vec![su["1"], replacement_two, su["4"], ba["1"], ba["2"]]
    );
    let event: (String, Option<f64>) = {
        let row = conn
            .query_one("SELECT type,rating FROM events WHERE id=$1", &[&history])
            .await
            .unwrap();
        (row.get(0), row.get(1))
    };
    assert_eq!(event, ("rate".to_string(), Some(4.5)));
}

#[tokio::test]
async fn list_update_requires_exact_predecessor_review_and_preserves_plan_reference() {
    let Some((state, _db)) = database().await else {
        return;
    };
    let (token, csrf, owner) = register(&state, "relink-list-update").await;
    let auth = (token.as_str(), csrf.as_str());
    let (other_token, other_csrf, _) = register(&state, "relink-list-update-foreign").await;
    let other = (other_token.as_str(), other_csrf.as_str());

    let (_superman, su) = seed_thread(&state, owner, "Superman", 1, &["1"]).await;
    let (_batman, ba) = seed_thread(&state, owner, "Batman", 2, &["1"]).await;
    let list_id = seed_list(
        &state,
        owner,
        "Reading List under Plan A",
        "strict",
        &[su["1"], ba["1"]],
    )
    .await;
    let plan_id = seed_plan(&state, owner, "Plan A", list_id).await;
    let event_id = mark_read_and_rate(&state, owner, su["1"], Some(4.0)).await;
    let path = format!("/api/v2/reading-lists/{list_id}");
    let before = json!({
        "name": "Reading List under Plan A",
        "mode": "strict",
        "issue_ids": [ba["1"], su["1"]],
    });

    // A second owner cannot use the v2 editor to mutate this list.
    let (status, foreign) = send(&state, other, "PUT", &path, Some(before.clone())).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{foreign}");
    let (status, needs_ack) = send(&state, auth, "PUT", &path, Some(before.clone())).await;
    assert_eq!(status, StatusCode::CONFLICT, "{needs_ack}");
    assert_eq!(
        needs_ack["detail"]["code"],
        "reading_list_predecessor_confirmation_required"
    );
    let confirmation = needs_ack["detail"]["predecessor_changes"]
        .as_array()
        .unwrap()
        .clone();
    assert_eq!(confirmation.len(), 2);

    // A rejected attempt cannot reorder entries or change the saved source.
    let (status, unchanged) = send(&state, auth, "GET", &path, None).await;
    assert_eq!(status, StatusCode::OK, "{unchanged}");
    assert_eq!(unchanged["entries"][0]["issue_id"], su["1"]);
    let (status, saved_reader) = send(
        &state,
        auth,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}/reader"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{saved_reader}");
    assert_eq!(saved_reader["lanes"][0]["issues"][0]["issue_id"], su["1"]);

    let (status, edited) = send(
        &state,
        auth,
        "PUT",
        &path,
        Some(json!({
            "name": "Reading List under Plan A",
            "mode": "strict",
            "issue_ids": [ba["1"], su["1"]],
            "confirmed_predecessor_changes": confirmation
        })),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{edited}");
    assert_eq!(edited["entries"][0]["issue_id"], ba["1"]);
    let (status, reader_after) = send(
        &state,
        auth,
        "GET",
        &format!("/api/v2/continuity-plans/{plan_id}/reader"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{reader_after}");
    assert_eq!(reader_after["lanes"][0]["issues"][0]["issue_id"], ba["1"]);

    let conn = state.pool.get().await.unwrap();
    let linked_list: i32 = conn
        .query_one(
            "SELECT custom_cbl_list_id FROM reading_plan_sources WHERE plan_id=$1",
            &[&plan_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(linked_list, list_id);
    let history_preserved: bool = conn
        .query_one(
            "SELECT EXISTS(SELECT 1 FROM events WHERE id=$1 AND issue_id=$2)",
            &[&event_id, &su["1"]],
        )
        .await
        .unwrap()
        .get(0);
    assert!(history_preserved);
}

#[tokio::test]
async fn dependency_create_rejects_combined_series_and_strict_list_cycle() {
    let Some((state, _db)) = database().await else {
        return;
    };
    let (token, csrf, owner) = register(&state, "dependency-cycle-owner").await;
    let auth = (token.as_str(), csrf.as_str());

    // Series order alone is acyclic: A1 -> A2 and B1 -> B2. The strict list
    // adds B1 -> A2. A reader prerequisite A2 -> B1 closes a loop that no
    // single constraint family contains; the Python dependency surface only
    // checked dependency edges, so this edge could previously be committed
    // and then outage every read path (#4684 Muse-shaped cycle).
    let (_a, a_ids) = seed_thread(&state, owner, "Alpha", 1, &["1", "2"]).await;
    let (_b, b_ids) = seed_thread(&state, owner, "Beta", 2, &["1", "2"]).await;
    seed_list(
        &state,
        owner,
        "Crossing strict list",
        "strict",
        &[b_ids["1"], a_ids["2"]],
    )
    .await;

    let (status, rejected) = send(
        &state,
        auth,
        "POST",
        "/api/v2/dependencies/",
        Some(json!({
            "source_type": "issue",
            "source_id": a_ids["2"],
            "target_type": "issue",
            "target_id": b_ids["1"]
        })),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{rejected}");
    let detail = rejected["detail"].as_str().unwrap();
    assert!(detail.contains("Reading constraint cycle"), "{detail}");
    assert!(detail.contains("Nothing was changed"), "{detail}");
    assert!(detail.contains("Alpha #2"), "{detail}");
    assert!(detail.contains("Beta #1"), "{detail}");

    // Nothing was persisted and unaffected readers keep working.
    let conn = state.pool.get().await.unwrap();
    let count: i64 = conn
        .query_one(
            "SELECT count(*) FROM dependencies WHERE origin='reader'",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(count, 0);
    for path in ["/api/v2/threads", "/api/v2/reading-graph"] {
        let (status, body) = send(&state, auth, "GET", path, None).await;
        assert_eq!(status, StatusCode::OK, "{path}: {body}");
    }

    // A benign edge that keeps the projected graph acyclic still succeeds.
    let (status, created) = send(
        &state,
        auth,
        "POST",
        "/api/v2/dependencies/",
        Some(json!({
            "source_type": "issue",
            "source_id": a_ids["1"],
            "target_type": "issue",
            "target_id": b_ids["2"]
        })),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    assert_eq!(created["source_label"], "Alpha #1");
    assert_eq!(created["target_label"], "Beta #2");
    assert_eq!(created["is_issue_level"], true);
}

#[tokio::test]
async fn dependency_lifecycle_validation_and_owner_scoped_delete() {
    let Some((state, _db)) = database().await else {
        return;
    };
    let (token, csrf, owner) = register(&state, "dependency-lifecycle-owner").await;
    let auth = (token.as_str(), csrf.as_str());
    let (other_token, other_csrf, _other) = register(&state, "dependency-lifecycle-other").await;
    let other_auth = (other_token.as_str(), other_csrf.as_str());

    let (_a, a_ids) = seed_thread(&state, owner, "Alpha", 1, &["1", "2"]).await;
    let (_b, b_ids) = seed_thread(&state, owner, "Beta", 2, &["1", "2"]).await;

    // Thread-level and mixed requests keep the Python rejection semantics.
    let (status, body) = send(
        &state,
        auth,
        "POST",
        "/api/v2/dependencies/",
        Some(json!({
            "source_type": "thread",
            "source_id": 1,
            "target_type": "thread",
            "target_id": 2
        })),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body}");
    assert!(body["detail"]
        .as_str()
        .unwrap()
        .contains("no longer supported"));

    let (status, body) = send(
        &state,
        auth,
        "POST",
        "/api/v2/dependencies/",
        Some(json!({
            "source_type": "issue",
            "source_id": a_ids["1"],
            "target_type": "issue",
            "target_id": a_ids["1"]
        })),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body}");

    let (status, created) = send(
        &state,
        auth,
        "POST",
        "/api/v2/dependencies/",
        Some(json!({
            "source_type": "issue",
            "source_id": a_ids["1"],
            "target_type": "issue",
            "target_id": b_ids["1"]
        })),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{created}");
    let dependency_id = created["id"].as_i64().unwrap() as i32;

    // Duplicate edges are refused without a second row.
    let (status, body) = send(
        &state,
        auth,
        "POST",
        "/api/v2/dependencies/",
        Some(json!({
            "source_type": "issue",
            "source_id": a_ids["1"],
            "target_type": "issue",
            "target_id": b_ids["1"]
        })),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body}");
    assert_eq!(body["detail"], "Dependency already exists");

    // Another owner's delete sees the same 404 as a missing edge.
    let (status, body) = send(
        &state,
        other_auth,
        "DELETE",
        &format!("/api/v2/dependencies/{dependency_id}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body}");

    let (status, body) = send(
        &state,
        auth,
        "DELETE",
        &format!("/api/v2/dependencies/{dependency_id}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["message"], "Dependency deleted");

    let (status, body) = send(
        &state,
        auth,
        "DELETE",
        &format!("/api/v2/dependencies/{dependency_id}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body}");
}
