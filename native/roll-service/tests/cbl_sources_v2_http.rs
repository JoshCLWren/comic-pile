#![allow(clippy::unwrap_used, clippy::expect_used)]
//! DB-backed HTTP regressions for the canonical v2 CBL source catalog (#5712).
//!
//! These exercise the mounted router against the canonical disposable
//! PostgreSQL schema and prove: one List collection serves folder browse and
//! search; ordering is allowlisted; page tokens are opaque and bound to the
//! request; Get and occurrences keep provenance and exact-identity semantics;
//! and reader-owned lists never leak into the shared catalog.

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

const MIRROR_REPOSITORY: &str = "/mnt/bigdata/CBL-ReadingLists";
const PUBLIC_REPOSITORY: &str = "JoshCLWren/CBL-ReadingLists";
const MIRROR_SOURCE_PATH: &str =
    "/mnt/bigdata/CBL-ReadingLists/DC/Mister Miracle (1989)/Mister Miracle.cbl";
const PUBLIC_SOURCE_PATH: &str = "DC/Mister Miracle (1989)/Mister Miracle.cbl";
const ISSUE_ID: &str = "4000-123";

async fn setup() -> (Arc<AppState>, String, tokio::sync::MutexGuard<'static, ()>) {
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
    let username = format!("cbl-sources-v2-{suffix}");
    let (status, body) = send(
        &state,
        Request::builder()
            .method("POST")
            .uri("/api/v1/auth/register")
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
            .unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let token = body["access_token"].as_str().unwrap().to_owned();
    seed_catalog(&state).await;
    (state, token, guard)
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

async fn get(state: &Arc<AppState>, token: &str, uri: &str) -> (StatusCode, Value) {
    send(
        state,
        Request::builder()
            .method("GET")
            .uri(uri)
            .header(header::AUTHORIZATION, format!("Bearer {token}"))
            .body(Body::empty())
            .unwrap(),
    )
    .await
}

async fn seed_catalog(state: &Arc<AppState>) {
    let conn = state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO cbl_sources (id, repository, revision_sha, synced_at, created_at, updated_at)
        VALUES (1, '{MIRROR_REPOSITORY}', 'rev-1', NOW(), NOW(), NOW());

        INSERT INTO cbl_source_lists
          (id, source_id, source_path, name, declared_issue_count, content_hash,
           revision_sha, active, created_at, updated_at)
        VALUES
          (1, 1, '{MIRROR_SOURCE_PATH}', 'Mister Miracle 1989', 5, 'h-mm', 'rev-1', TRUE, NOW(), NOW()),
          (2, 1, 'DC/JLI/JLI.cbl', 'JLI', 10, 'h-jli', 'rev-1', TRUE, NOW(), NOW()),
          (3, 1, 'Special/Percent%List.cbl', 'Percent%List', 1, 'h-pct', 'rev-1', TRUE, NOW(), NOW()),
          (4, 1, 'DC/Archived/Dead.cbl', 'Archived', 1, 'h-dead', 'rev-1', FALSE, NOW(), NOW()),
          -- Root-level lists are the direct children the folder browse page
          -- selects; two of them make the one-item page continue to page two.
          (5, 1, 'Root One.cbl', 'Root One', 1, 'h-root-1', 'rev-1', TRUE, NOW(), NOW()),
          (6, 1, 'Root Two.cbl', 'Root Two', 1, 'h-root-2', 'rev-1', TRUE, NOW(), NOW());

        INSERT INTO external_identities
          (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
        VALUES
          (1, 'comicvine', 'issue', '{ISSUE_ID}', '{{}}'::json, NOW(), NOW()),
          (2, 'comicvine', 'series', '4050-9', '{{}}'::json, NOW(), NOW()),
          (3, 'other-provider', 'issue', '{ISSUE_ID}', '{{}}'::json, NOW(), NOW());

        INSERT INTO cbl_source_entries
          (id, list_id, "position", series_name, issue_number, volume_year,
           publication_year, external_issue_identity_id, external_series_identity_id, created_at)
        VALUES
          (1, 1, 0, 'Mister Miracle', '1', 1989, 1989, 1, 2, NOW()),
          (2, 1, 1, 'Mister Miracle', '2', 1989, 1989, 1, 2, NOW()),
          (3, 2, 0, 'Justice League', '1', 1987, NULL, NULL, NULL, NOW());

        -- A reader-owned list must never appear in the shared catalog.
        INSERT INTO custom_cbl_lists (id, user_id, name, mode, created_at, updated_at)
        VALUES (101, (SELECT id FROM users ORDER BY id DESC LIMIT 1),
                'PRIVATE READER LIST SHOULD NOT LEAK', 'loose', NOW(), NOW());
        "#
    ))
    .await
    .unwrap();
}

#[tokio::test]
async fn list_browses_root_and_continues_with_an_opaque_token() {
    let (state, token, _guard) = setup().await;
    let (status, first) = get(&state, &token, "/api/v2/cblSources?page_size=1").await;
    assert_eq!(status, StatusCode::OK, "{first}");
    assert_eq!(first["scope"], "folder");
    assert_eq!(first["folder"], "");
    assert_eq!(first["page"], 1);
    assert_eq!(first["page_size"], 1);
    assert_eq!(first["catalog_total"], 5, "inactive list must be excluded");
    assert_eq!(
        first["total"], 2,
        "root browse selects direct children only"
    );
    assert_eq!(first["items"].as_array().unwrap().len(), 1);
    assert!(!first["folders"].as_array().unwrap().is_empty());
    assert_eq!(first["breadcrumbs"][0]["name"], "All CBLs");
    assert_eq!(first["has_next"], true);
    let cursor = first["next_page_token"]
        .as_str()
        .expect("a two-item root page must issue a continuation token")
        .to_owned();
    // Tokens are opaque, not a readable page number or SQL fragment.
    assert!(cursor.len() > 4);
    assert_ne!(cursor, "2");
    assert!(!cursor.contains("SELECT"));

    let (status, second) = get(
        &state,
        &token,
        &format!("/api/v2/cblSources?page_size=1&page_token={cursor}"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{second}");
    assert_eq!(second["page"], 2);
    assert_eq!(second["has_previous"], true);
    assert_ne!(
        first["items"][0]["id"], second["items"][0]["id"],
        "continuation must advance the page"
    );
}

#[tokio::test]
async fn root_browser_emitted_page_token_round_trips_to_page_two() {
    let (state, token, _guard) = setup().await;
    // This is the exact opaque token shape encodeSourcePageToken emits for
    // `browse({ page: 2, pageSize: 1 })` at the root folder. Its `f` must be the
    // canonical `folder:` or the server rejects it as an invalid page token.
    const BROWSER_PAGE_TWO: &str = "eyJwIjoyLCJmIjoiZm9sZGVyOiIsIm8iOiJuYW1lIiwicyI6MX0";

    let (status, page) = get(
        &state,
        &token,
        &format!("/api/v2/cblSources?filter=folder:&page_size=1&page_token={BROWSER_PAGE_TWO}"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{page}");
    assert_eq!(page["scope"], "folder");
    assert_eq!(page["folder"], "");
    assert_eq!(page["page"], 2);
    assert_eq!(page["page_size"], 1);
    assert_eq!(page["total"], 2, "root browse selects direct children only");
    assert_eq!(page["items"].as_array().unwrap().len(), 1);
    assert_eq!(page["has_previous"], true);

    // The pre-fix browser emitted `{...,"f":"",...}`, which must stay invalid.
    let legacy = "/api/v2/cblSources?filter=folder:&page_size=1&page_token=eyJwIjoyLCJmIjoiIiwibyI6Im5hbWUiLCJzIjoxfQ";
    let (status, rejected) = get(&state, &token, legacy).await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{rejected}");
}

#[tokio::test]
async fn all_filter_discovers_sources_across_every_folder() {
    let (state, token, _guard) = setup().await;
    let (status, body) = get(&state, &token, "/api/v2/cblSources?filter=all&page_size=50").await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["total"], 5);
    assert_eq!(body["items"].as_array().unwrap().len(), 5);
    // The discovery picker is catalog-wide, not limited to root-level lists.
    assert!(body["items"].to_string().contains("JLI"));
}

#[tokio::test]
async fn search_is_literal_and_never_leaks_a_private_reader_list() {
    let (state, token, _guard) = setup().await;
    // `%` must be a literal character, not a LIKE wildcard.
    let (status, body) = get(&state, &token, "/api/v2/cblSources?filter=q:Percent%25List").await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["scope"], "search");
    assert_eq!(body["query"], "Percent%List");
    assert_eq!(body["total"], 1);
    assert_eq!(body["items"][0]["name"], "Percent%List");

    let (status, private) = get(
        &state,
        &token,
        "/api/v2/cblSources?filter=q:PRIVATE%20READER%20LIST%20SHOULD%20NOT%20LEAK",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{private}");
    assert_eq!(private["items"].as_array().unwrap().len(), 0);
    assert_eq!(private["total"], 0);
}

#[tokio::test]
async fn detail_is_read_only_and_projects_catalog_provenance() {
    let (state, token, _guard) = setup().await;
    let (status, body) = get(&state, &token, "/api/v2/cblSources/1").await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["name"], "Mister Miracle 1989");
    assert_eq!(body["source_path"], PUBLIC_SOURCE_PATH);
    assert!(!body["source_path"]
        .as_str()
        .unwrap()
        .contains("CBL-ReadingLists/DC"));
    assert_eq!(body["source_repository"], PUBLIC_REPOSITORY);
    assert_eq!(
        body["source_ref"],
        "JoshCLWren/CBL-ReadingLists:DC/Mister Miracle (1989)/Mister Miracle.cbl"
    );
    assert_eq!(body["entries_total"], 2);
    assert_eq!(body["entries"].as_array().unwrap().len(), 2);

    let (status, missing) = get(&state, &token, "/api/v2/cblSources/999999").await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{missing}");
}

#[tokio::test]
async fn occurrences_match_only_the_exact_comicvine_issue_identity() {
    let (state, token, _guard) = setup().await;
    let (status, body) = get(
        &state,
        &token,
        &format!("/api/v2/cblOccurrences?filter={ISSUE_ID}"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["comicvine_issue_id"], ISSUE_ID);
    assert_eq!(body["occurrences_total"], 2);
    assert_eq!(body["lists_total"], 1);
    assert_eq!(body["occurrences"].as_array().unwrap().len(), 2);
    assert_eq!(body["occurrences"][0]["comicvine_issue_id"], ISSUE_ID);
    assert_eq!(
        body["occurrences"][0]["source_repository"],
        PUBLIC_REPOSITORY
    );
    // The same external id from another provider must not be counted.
    assert_eq!(body["occurrences_total"], 2);

    let (status, missing) = get(&state, &token, "/api/v2/cblOccurrences?filter=4000-999").await;
    assert_eq!(status, StatusCode::OK, "{missing}");
    assert_eq!(missing["occurrences_total"], 0);
}

#[tokio::test]
async fn query_validation_rejects_bad_filter_order_and_replayed_token() {
    let (state, token, _guard) = setup().await;

    let (status, _) = get(&state, &token, "/api/v2/cblSources?filter=folder:..").await;
    assert_eq!(status, StatusCode::BAD_REQUEST);

    let (status, _) = get(&state, &token, "/api/v2/cblSources?order_by=id%3BDROP").await;
    assert_eq!(status, StatusCode::BAD_REQUEST);

    let (status, _) = get(&state, &token, "/api/v2/cblSources?page_size=101").await;
    assert_eq!(status, StatusCode::BAD_REQUEST);

    let (status, _) = get(&state, &token, "/api/v2/cblOccurrences").await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);

    let (status, first) = get(&state, &token, "/api/v2/cblSources?page_size=1").await;
    assert_eq!(status, StatusCode::OK, "{first}");
    let cursor = first["next_page_token"]
        .as_str()
        .expect("the two-item root page must issue a continuation token");
    let (status, replay) = get(
        &state,
        &token,
        &format!("/api/v2/cblSources?page_size=1&filter=q:JLI&page_token={cursor}"),
    )
    .await;
    assert_eq!(
        status,
        StatusCode::BAD_REQUEST,
        "a token is bound to its filter: {replay}"
    );
}
