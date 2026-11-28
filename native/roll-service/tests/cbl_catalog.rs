#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Native HTTP regressions for the shared CBL catalog browse/folders endpoints.
//!
//! Exercises the mounted router against canonical disposable PostgreSQL rows:
//! root/nested folder navigation, literal LIKE metacharacter searches, missing
//! folder 404s, FastAPI-compatible 422 envelopes, and extreme pagination parity
//! (including page=2^63 echo with correct totals/empty page).

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

async fn setup() -> (Arc<AppState>, String, tokio::sync::MutexGuard<'static, ()>) {
    let url = comicpile_roll_service::test_support::database_url().await;
    let state = Arc::new(test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => {
                Some(comicpile_roll_service::test_support::TEST_JWT_SECRET.into())
            }
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .unwrap(),
    ));
    let guard = comicpile_roll_service::test_support::reset_for_test(&state).await;

    let suffix = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let username = format!("cbl-catalog-{suffix}");
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
                    "password": "correct-horse-battery"
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
    conn.batch_execute(
        "INSERT INTO cbl_sources (repository, revision_sha, synced_at, created_at, updated_at)
         VALUES ('JoshCLWren/CBL-ReadingLists', 'abc123', NOW(), NOW(), NOW());
         INSERT INTO cbl_source_lists
           (source_id, source_path, name, declared_issue_count, content_hash, revision_sha, active, created_at, updated_at)
         VALUES
           (1, 'DC/Mister Miracle (1989)/Mister Miracle.cbl', 'Mister Miracle 1989', 5, 'h-mm', 'abc123', TRUE, NOW(), NOW()),
           (1, 'DC/Mister Miracle (1989)/unsorted/Annual.cbl', 'Mister Miracle Annual', 1, 'h-mma', 'abc123', TRUE, NOW(), NOW()),
           (1, 'DC/JLI/JLI.cbl', 'JLI', 10, 'h-jli', 'abc123', TRUE, NOW(), NOW()),
           (1, 'Marvel/Events/Secret Wars.cbl', 'Secret Wars', 12, 'h-sw', 'abc123', TRUE, NOW(), NOW()),
           (1, 'Marvel/Events/Tie-ins/Crossovers.cbl', 'Secret Wars Crossovers', 3, 'h-swc', 'abc123', TRUE, NOW(), NOW()),
           (1, 'Root Reading List.cbl', 'Root Reading List', 2, 'h-root', 'abc123', TRUE, NOW(), NOW()),
           (1, 'DC/Mister Miracle (1989)/Archived.cbl', 'Archived Mister Miracle', 1, 'h-arch-mm', 'abc123', FALSE, NOW(), NOW()),
           (1, 'Archived Only/Dead.cbl', 'Archived Only', 1, 'h-arch-only', 'abc123', FALSE, NOW(), NOW()),
           (1, 'Special/Percent%List.cbl', 'Percent%List', 1, 'h-pct', 'abc123', TRUE, NOW(), NOW()),
           (1, 'Special/Under_score.cbl', 'Under_score', 1, 'h-und', 'abc123', TRUE, NOW(), NOW());
        ",
    )
    .await
    .unwrap();
}

#[tokio::test]
async fn folders_root_lists_active_children_with_breadcrumbs() {
    let (state, token, _guard) = setup().await;
    let (status, body) = get(&state, &token, "/api/v1/issue-identity/cbl-sources/folders").await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["folder"], "");
    assert_eq!(
        body["breadcrumbs"],
        json!([{ "name": "All CBLs", "path": "" }])
    );
    assert_eq!(body["direct_list_count"], 1);
    let folder_names: Vec<_> = body["folders"]
        .as_array()
        .unwrap()
        .iter()
        .map(|f| f["name"].as_str().unwrap().to_string())
        .collect();
    assert!(folder_names.contains(&"DC".to_string()), "{folder_names:?}");
    assert!(
        folder_names.contains(&"Marvel".to_string()),
        "{folder_names:?}"
    );
    assert!(
        folder_names.contains(&"Special".to_string()),
        "{folder_names:?}"
    );
    assert!(
        !folder_names.contains(&"Archived Only".to_string()),
        "inactive-only folders must not appear: {folder_names:?}"
    );
}

#[tokio::test]
async fn folders_nested_and_missing_folder_404() {
    let (state, token, _guard) = setup().await;
    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/folders?folder=DC/Mister%20Miracle%20(1989)",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["folder"], "DC/Mister Miracle (1989)");
    assert_eq!(body["direct_list_count"], 1);
    assert_eq!(body["folders"][0]["name"], "unsorted");

    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/folders?folder=Does/Not/Exist",
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body}");
    assert_eq!(body["detail"]["code"], "folder_not_found");
}

#[tokio::test]
async fn browse_missing_folder_404_and_literal_like_search() {
    let (state, token, _guard) = setup().await;
    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/browse?folder=Does/Not/Exist",
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body}");
    assert_eq!(body["detail"]["code"], "folder_not_found");

    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/browse?q=Percent%25List",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["scope"], "search");
    assert_eq!(body["total"], 1);
    assert_eq!(body["items"][0]["name"], "Percent%List");

    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/browse?q=Under_score",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["total"], 1);
    assert_eq!(body["items"][0]["name"], "Under_score");
}

#[tokio::test]
async fn browse_reports_filtered_and_whole_catalog_totals() {
    let (state, token, _guard) = setup().await;

    let (status, root) = get(&state, &token, "/api/v1/issue-identity/cbl-sources/browse").await;
    assert_eq!(status, StatusCode::OK, "{root}");
    assert_eq!(root["total"], 1);
    assert_eq!(root["catalog_total"], 8);

    let (status, filtered) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/browse?q=Mister%20Miracle&page_size=1",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{filtered}");
    assert_eq!(filtered["total"], 2);
    assert_eq!(filtered["catalog_total"], 8);
    assert_eq!(filtered["items"].as_array().unwrap().len(), 1);

    let (_, zero) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/browse?q=Archived",
    )
    .await;
    assert_eq!(zero["total"], 0);
    assert_eq!(zero["catalog_total"], 8);
    assert_eq!(zero["items"], json!([]));

    let (_, folder) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/browse?folder=Special",
    )
    .await;
    assert_eq!(folder["total"], 2);
    assert_eq!(folder["catalog_total"], 8);
}

#[tokio::test]
async fn browse_invalid_pagination_returns_fastapi_422_envelope() {
    let (state, token, _guard) = setup().await;

    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/browse?page=abc",
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"][0]["type"], "int_parsing");
    assert_eq!(body["detail"][0]["loc"], json!(["query", "page"]));

    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/browse?page=0",
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"][0]["type"], "greater_than_equal");

    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/browse?page_size=101",
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"][0]["type"], "less_than_equal");
    assert_eq!(body["detail"][0]["loc"], json!(["query", "page_size"]));
}

#[tokio::test]
async fn browse_extreme_page_clamps_without_overflow() {
    let (state, token, _guard) = setup().await;
    let extreme = "9223372036854775808"; // 2^63
    let uri =
        format!("/api/v1/issue-identity/cbl-sources/browse?q=JLI&page={extreme}&page_size=100");
    let (status, body) = get(&state, &token, &uri).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["total"], 1);
    assert_eq!(body["total_pages"], 1);
    assert_eq!(body["page"], 1);
    assert_eq!(body["has_next"], false);
    assert_eq!(body["has_previous"], false);
    let names: Vec<_> = body["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| i["name"].as_str().unwrap())
        .collect();
    assert_eq!(names, vec!["JLI"], "{body}");
}

#[tokio::test]
async fn browse_out_of_range_page_clamps_to_last_page_with_results() {
    let (state, token, _guard) = setup().await;
    // 2 matches, all on one page: requesting page 2 must clamp to page 1 and
    // return the matching sources (issue #5381).
    let uri = "/api/v1/issue-identity/cbl-sources/browse?q=Secret%20Wars&page=2&page_size=50";
    let (status, body) = get(&state, &token, uri).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["scope"], "search");
    assert_eq!(body["total"], 2);
    assert_eq!(body["total_pages"], 1);
    assert_eq!(body["page"], 1);
    assert_eq!(body["has_next"], false);
    assert_eq!(body["has_previous"], false);
    let names: Vec<_> = body["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| i["name"].as_str().unwrap())
        .collect();
    assert_eq!(
        names,
        vec!["Secret Wars", "Secret Wars Crossovers"],
        "{body}"
    );
}

fn folder_item_names(body: &Value) -> Vec<String> {
    body["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| i["name"].as_str().unwrap().to_string())
        .collect()
}

#[tokio::test]
async fn browse_folder_out_of_range_page_clamps_to_true_last_page() {
    let (state, token, _guard) = setup().await;
    // Folder mode (no `q`): "Special" has 2 direct lists; page_size=1 gives 2
    // pages. Page 9 must select page 2 (the last), not reset to page 1.
    let uri = "/api/v1/issue-identity/cbl-sources/browse?folder=Special&page=9&page_size=1";
    let (status, body) = get(&state, &token, uri).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["scope"], "folder");
    assert_eq!(body["total"], 2);
    assert_eq!(body["total_pages"], 2);
    assert_eq!(body["page"], 2);
    assert_eq!(body["has_next"], false);
    assert_eq!(body["has_previous"], true);
    assert_eq!(folder_item_names(&body), vec!["Under_score"], "{body}");
}

#[tokio::test]
async fn browse_folder_in_range_page_is_not_clamped() {
    let (state, token, _guard) = setup().await;
    let uri = "/api/v1/issue-identity/cbl-sources/browse?folder=Special&page=1&page_size=1";
    let (status, body) = get(&state, &token, uri).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["page"], 1);
    assert_eq!(body["has_next"], true);
    assert_eq!(body["has_previous"], false);
    assert_eq!(folder_item_names(&body), vec!["Percent%List"], "{body}");
}

#[tokio::test]
async fn browse_root_out_of_range_page_clamps_to_single_page() {
    let (state, token, _guard) = setup().await;
    let uri = "/api/v1/issue-identity/cbl-sources/browse?page=7&page_size=50";
    let (status, body) = get(&state, &token, uri).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["total"], 1);
    assert_eq!(body["page"], 1);
    assert_eq!(body["has_next"], false);
    assert_eq!(body["has_previous"], false);
    assert_eq!(
        folder_item_names(&body),
        vec!["Root Reading List"],
        "{body}"
    );
}

/// Add a synthetic 130-list corpus on top of the small canonical catalog so
/// paging, totals and discovery parity are measured against more than 100
/// active source lists (#4171). The insert is one set-based statement.
async fn seed_large_corpus(state: &Arc<AppState>) {
    let conn = state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO cbl_source_lists
            (source_id, source_path, name, declared_issue_count, content_hash,
             revision_sha, active, created_at, updated_at)
         SELECT 1,
                'DC/Bulk/Bulk List ' || lpad(n::text, 3, '0') || '.cbl',
                'Bulk List ' || lpad(n::text, 3, '0'),
                1, 'bulk-hash-' || n, 'abc123', TRUE, NOW(), NOW()
         FROM generate_series(1, 130) AS n",
        &[],
    )
    .await
    .unwrap();
}

#[tokio::test]
async fn large_corpus_has_stable_totals_and_a_real_second_page() {
    let (state, token, _guard) = setup().await;
    seed_large_corpus(&state).await;

    let (status, root) = get(&state, &token, "/api/v1/issue-identity/cbl-sources/browse").await;
    assert_eq!(status, StatusCode::OK, "{root}");
    // 8 canonical active lists + 130 synthetic lists, independent of paging.
    assert_eq!(root["catalog_total"], 138);
    assert_eq!(root["total"], 1);

    let (status, second) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/browse?folder=DC/Bulk&page=2&page_size=50",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{second}");
    assert_eq!(second["scope"], "folder");
    assert_eq!(second["folder"], "DC/Bulk");
    assert_eq!(second["total"], 130);
    assert_eq!(second["catalog_total"], 138);
    assert_eq!(second["total_pages"], 3);
    assert_eq!(second["page"], 2);
    assert_eq!(second["has_next"], true);
    assert_eq!(second["has_previous"], true);
    assert_eq!(second["items"].as_array().unwrap().len(), 50);
    assert_eq!(folder_item_names(&second)[0], "Bulk List 051");

    let (_, third) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/browse?folder=DC/Bulk&page=3&page_size=50",
    )
    .await;
    assert_eq!(third["total"], 130);
    assert_eq!(third["catalog_total"], 138);
    assert_eq!(third["page"], 3);
    assert_eq!(third["has_next"], false);
    assert_eq!(third["items"].as_array().unwrap().len(), 30);

    let (status, folders) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/folders?folder=DC",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{folders}");
    assert_eq!(folders["total_list_count"], 133);
    let bulk = folders["folders"]
        .as_array()
        .unwrap()
        .iter()
        .find(|folder| folder["name"] == "Bulk")
        .unwrap();
    assert_eq!(bulk["direct_list_count"], 130);
    assert_eq!(bulk["total_list_count"], 130);
}

#[tokio::test]
async fn large_corpus_search_is_case_insensitive_and_matches_discovery() {
    let (state, token, _guard) = setup().await;
    seed_large_corpus(&state).await;

    let (status, partial) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/browse?q=bulk%20list%20012",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{partial}");
    assert_eq!(partial["scope"], "search");
    assert_eq!(partial["total"], 1);
    assert_eq!(partial["catalog_total"], 138);
    assert_eq!(folder_item_names(&partial), vec!["Bulk List 012"]);

    let (status, browse) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/browse?q=BULK%20LIST&page_size=25",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{browse}");
    assert_eq!(browse["total"], 130);
    assert_eq!(browse["catalog_total"], 138);
    assert_eq!(browse["total_pages"], 6);
    assert_eq!(browse["items"].as_array().unwrap().len(), 25);

    let (status, discovered) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources?q=BULK%20LIST&limit=25",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{discovered}");
    let browse_items = browse["items"].as_array().unwrap();
    let discovered_items = discovered.as_array().unwrap();
    assert_eq!(discovered_items.len(), browse_items.len());
    for (browse_item, discovered_item) in browse_items.iter().zip(discovered_items) {
        for field in ["id", "name", "source_path", "content_hash", "revision_sha"] {
            assert_eq!(
                browse_item[field], discovered_item[field],
                "discovery/browse parity failed for {field}: {browse_item} vs {discovered_item}"
            );
        }
    }
}
