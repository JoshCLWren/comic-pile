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
