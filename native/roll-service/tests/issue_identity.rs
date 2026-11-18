#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Native HTTP regressions for the three read-only CBL source discovery
//! endpoints migrated for #4843.
//!
//! These exercise the mounted router against canonical disposable PostgreSQL
//! rows and lock down the wire contract that the pre-repair placeholders got
//! wrong: real column names, a 1:1 SELECT/`row.get` mapping, reader-safe
//! repository/path projections, paging echoes, 404s, and FastAPI-compatible
//! 422 validation envelopes.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, AppState};
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
const VOLUME_ID: &str = "4050-9";

async fn setup() -> (
    Arc<AppState>,
    String,
    String,
    tokio::sync::MutexGuard<'static, ()>,
) {
    let url = comicpile_roll_service::test_support::database_url().await;
    let state = Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
                "RUST_ROLL_JWT_SECRET" => {
                    Some(comicpile_roll_service::test_support::TEST_JWT_SECRET.into())
                }
                "RUST_ROLL_POOL_SIZE" => Some("2".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    );
    let guard = comicpile_roll_service::test_support::reset_for_test(&state).await;

    let suffix = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let username = format!("issue-identity-{suffix}");
    let response = router(state.clone())
        .oneshot(
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
        .await
        .unwrap();
    let status = response.status();
    let csrf = response
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .find_map(|cookie| {
            let cookie = cookie.to_str().ok()?;
            cookie
                .strip_prefix("csrf_token=")?
                .split(';')
                .next()
                .map(str::to_owned)
        })
        .expect("register sets a CSRF cookie");
    let body_bytes = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&body_bytes).unwrap();
    assert_eq!(status, StatusCode::OK, "{body}");
    let token = body["access_token"].as_str().unwrap().to_owned();
    seed_catalog(&state).await;
    (state, token, csrf, guard)
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
          (3, 1, 'DC/Archived/Dead.cbl', 'Archived', 1, 'h-dead', 'rev-1', FALSE, NOW(), NOW());

        INSERT INTO external_identities
          (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
        VALUES
          (1, 'comicvine', 'issue', '{ISSUE_ID}', '{{}}'::json, NOW(), NOW()),
          (2, 'comicvine', 'series', '{VOLUME_ID}', '{{}}'::json, NOW(), NOW());

        INSERT INTO cbl_source_entries
          (id, list_id, "position", series_name, issue_number, volume_year,
           publication_year, external_issue_identity_id, external_series_identity_id, created_at)
        VALUES
          (1, 1, 0, 'Mister Miracle', '1', 1989, 1989, 1, 2, NOW()),
          (2, 1, 1, 'Mister Miracle', '2', 1989, 1989, 1, 2, NOW()),
          (3, 2, 0, 'Justice League', '1', 1987, NULL, NULL, NULL, NOW());
        "#
    ))
    .await
    .unwrap();
}

#[tokio::test]
async fn discover_lists_active_sources_with_public_repository() {
    let (state, token, _csrf, _guard) = setup().await;
    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources?limit=25",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let items = body.as_array().unwrap();
    assert_eq!(items.len(), 2, "inactive list must be excluded: {body}");
    assert_eq!(items[0]["name"], "JLI");
    assert_eq!(items[1]["name"], "Mister Miracle 1989");
    // Python's discovery response deliberately returns the stored path and the
    // reader-safe repository (never the local mirror repository).
    assert_eq!(items[1]["source_path"], MIRROR_SOURCE_PATH);
    assert_eq!(items[1]["source_repository"], PUBLIC_REPOSITORY);
    assert_eq!(items[1]["declared_issue_count"], 5);
    assert_eq!(items[1]["content_hash"], "h-mm");
    assert_eq!(items[1]["revision_sha"], "rev-1");
}

#[tokio::test]
async fn discover_search_is_case_insensitive_and_bounded() {
    let (state, token, _csrf, _guard) = setup().await;
    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources?q=mister%20miracle&limit=1",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body.as_array().unwrap().len(), 1);
    assert_eq!(body[0]["name"], "Mister Miracle 1989");
}

#[tokio::test]
async fn discover_validation_matches_fastapi_422() {
    let (state, token, _csrf, _guard) = setup().await;
    for (suffix, field, error_type) in [
        ("?limit=abc", "limit", "int_parsing"),
        ("?limit=0", "limit", "greater_than_equal"),
        ("?limit=101", "limit", "less_than_equal"),
    ] {
        let uri = format!("/api/v1/issue-identity/cbl-sources{suffix}");
        let (status, body) = get(&state, &token, &uri).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{uri} -> {body}");
        assert_eq!(body["detail"][0]["type"], error_type, "{uri} -> {body}");
        assert_eq!(body["detail"][0]["loc"], json!(["query", field]));
    }

    let long_q = "x".repeat(201);
    let uri = format!("/api/v1/issue-identity/cbl-sources?q={long_q}");
    let (status, body) = get(&state, &token, &uri).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"][0]["type"], "string_too_long");
    assert_eq!(body["detail"][0]["loc"], json!(["query", "q"]));
    assert_eq!(body["detail"][0]["ctx"]["max_length"], 200);
}

#[tokio::test]
async fn detail_projects_paths_and_echoes_paging() {
    let (state, token, _csrf, _guard) = setup().await;
    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/1?offset=1&limit=1",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["id"], 1);
    assert_eq!(body["name"], "Mister Miracle 1989");
    assert_eq!(body["source_path"], PUBLIC_SOURCE_PATH, "{body}");
    assert_eq!(body["source_repository"], PUBLIC_REPOSITORY);
    assert_eq!(
        body["source_ref"],
        format!("{PUBLIC_REPOSITORY}:{PUBLIC_SOURCE_PATH}")
    );
    assert_eq!(body["entries_total"], 2);
    assert_eq!(body["entries_offset"], 1);
    assert_eq!(body["entries_limit"], 1);
    let entries = body["entries"].as_array().unwrap();
    assert_eq!(entries.len(), 1, "{body}");
    assert_eq!(entries[0]["position"], 1);
    assert_eq!(entries[0]["series_name"], "Mister Miracle");
    assert_eq!(entries[0]["issue_number"], "2");
    assert_eq!(entries[0]["volume_year"], 1989);
    assert_eq!(entries[0]["comicvine_issue_id"], ISSUE_ID);
    assert_eq!(entries[0]["comicvine_volume_id"], VOLUME_ID);
}

#[tokio::test]
async fn detail_missing_or_inactive_list_returns_404() {
    let (state, token, _csrf, _guard) = setup().await;
    for id in [3, 999_999] {
        let uri = format!("/api/v1/issue-identity/cbl-sources/{id}");
        let (status, body) = get(&state, &token, &uri).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{uri} -> {body}");
        assert_eq!(body["detail"], "CBL source list not found");
    }
}

#[tokio::test]
async fn detail_validation_matches_fastapi_422() {
    let (state, token, _csrf, _guard) = setup().await;
    for (suffix, field, error_type) in [
        ("?offset=-1", "offset", "greater_than_equal"),
        ("?limit=0", "limit", "greater_than_equal"),
        ("?limit=2001", "limit", "less_than_equal"),
        ("?limit=abc", "limit", "int_parsing"),
    ] {
        let uri = format!("/api/v1/issue-identity/cbl-sources/1{suffix}");
        let (status, body) = get(&state, &token, &uri).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{uri} -> {body}");
        assert_eq!(body["detail"][0]["type"], error_type, "{uri} -> {body}");
        assert_eq!(body["detail"][0]["loc"], json!(["query", field]));
    }
}

#[tokio::test]
async fn comicvine_lookup_maps_every_selected_column() {
    let (state, token, _csrf, _guard) = setup().await;
    let (status, body) = get(
        &state,
        &token,
        &format!("/api/v1/issue-identity/cbl-sources/by-comicvine-issue/{ISSUE_ID}"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["comicvine_issue_id"], ISSUE_ID);
    assert_eq!(body["occurrences_total"], 2);
    assert_eq!(body["lists_total"], 1);
    assert_eq!(body["occurrences_offset"], 0);
    assert_eq!(body["occurrences_limit"], 50);
    let occurrences = body["occurrences"].as_array().unwrap();
    assert_eq!(occurrences.len(), 2, "{body}");
    // A single off-by-one in the SELECT/`row.get` mapping used to read an int4
    // position into a String and panic here, or read past the last column.
    let first = &occurrences[0];
    assert_eq!(first["list_id"], 1);
    assert_eq!(first["list_name"], "Mister Miracle 1989");
    assert_eq!(first["source_path"], PUBLIC_SOURCE_PATH);
    assert_eq!(first["source_repository"], PUBLIC_REPOSITORY);
    assert_eq!(
        first["source_ref"],
        format!("{PUBLIC_REPOSITORY}:{PUBLIC_SOURCE_PATH}")
    );
    assert_eq!(first["revision_sha"], "rev-1");
    assert_eq!(first["position"], 0);
    assert_eq!(first["series_name"], "Mister Miracle");
    assert_eq!(first["issue_number"], "1");
    assert_eq!(first["volume_year"], 1989);
    assert_eq!(first["publication_year"], 1989);
    assert_eq!(first["comicvine_issue_id"], ISSUE_ID);
    assert_eq!(first["comicvine_volume_id"], VOLUME_ID);
    assert_eq!(occurrences[1]["position"], 1);
}

#[tokio::test]
async fn comicvine_lookup_blank_id_uses_422_plain_detail() {
    let (state, token, _csrf, _guard) = setup().await;
    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl-sources/by-comicvine-issue/%20%20",
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"], "Comic Vine issue ID must not be blank");
}

#[tokio::test]
async fn comicvine_lookup_validation_matches_fastapi_422() {
    let (state, token, _csrf, _guard) = setup().await;
    for (suffix, field, error_type) in [
        ("?offset=-1", "offset", "greater_than_equal"),
        ("?limit=0", "limit", "greater_than_equal"),
        ("?limit=201", "limit", "less_than_equal"),
        ("?limit=abc", "limit", "int_parsing"),
    ] {
        let uri =
            format!("/api/v1/issue-identity/cbl-sources/by-comicvine-issue/{ISSUE_ID}{suffix}");
        let (status, body) = get(&state, &token, &uri).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{uri} -> {body}");
        assert_eq!(body["detail"][0]["type"], error_type, "{uri} -> {body}");
        assert_eq!(body["detail"][0]["loc"], json!(["query", field]));
    }

    let long_id = "x".repeat(101);
    let uri = format!("/api/v1/issue-identity/cbl-sources/by-comicvine-issue/{long_id}");
    let (status, body) = get(&state, &token, &uri).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"][0]["type"], "string_too_long");
    assert_eq!(
        body["detail"][0]["loc"],
        json!(["path", "comicvine_issue_id"])
    );
    assert_eq!(body["detail"][0]["ctx"]["max_length"], 100);
}

async fn post_json(
    state: &Arc<AppState>,
    token: &str,
    csrf: &str,
    uri: &str,
    body: Value,
) -> (StatusCode, Value) {
    send(
        state,
        Request::builder()
            .method("POST")
            .uri(uri)
            .header(header::AUTHORIZATION, format!("Bearer {token}"))
            .header(header::CONTENT_TYPE, "application/json")
            .header("x-csrf-token", csrf)
            .header(header::COOKIE, format!("csrf_token={csrf}"))
            .body(Body::from(body.to_string()))
            .unwrap(),
    )
    .await
}

#[tokio::test]
async fn compare_cbl_sources_ranks_and_validates() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/issue-identity/cbl-sources/compare",
        json!({"comicvine_issue_ids": [ISSUE_ID, "4000-999"]}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["input_total"], 2);
    assert_eq!(body["comicvine_issue_ids"], json!([ISSUE_ID, "4000-999"]));
    assert!(body["candidates_total"].as_i64().unwrap() >= 1, "{body}");
    let first = &body["candidates"][0];
    assert_eq!(first["list_id"], 1);
    assert_eq!(first["matched_input_count"], 1);
    assert_eq!(first["missing_input_ids"], json!(["4000-999"]));

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/issue-identity/cbl-sources/compare?limit=0",
        json!({"comicvine_issue_ids": [ISSUE_ID]}),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"][0]["loc"], json!(["query", "limit"]));
}

#[tokio::test]
async fn reading_list_candidates_reports_gaps_and_ranks() {
    let (state, token, _csrf, _guard) = setup().await;

    // Resolve the authenticated user's id from /api/v1/auth/me.
    let (status, me) = get(&state, &token, "/api/v1/auth/me").await;
    assert_eq!(status, StatusCode::OK, "{me}");
    let user_id = me["id"].as_i64().unwrap() as i32;

    let conn = state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status, total_issues, reading_progress, created_at)
        VALUES (910, {user_id}, 'Owned Series', 'comic', 1, 1, 'active', 2, 'in_progress', NOW());
        INSERT INTO issues (id, thread_id, issue_number, position, status, created_at)
        VALUES (9101, 910, '1', 0, 'unread', NOW()),
               (9102, 910, '2', 1, 'unread', NOW());
        INSERT INTO external_identities (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
        VALUES (911, 'comicvine', 'issue', '{ISSUE_ID}', '{{}}'::json, NOW(), NOW())
        ON CONFLICT DO NOTHING;
        INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, evidence_source, evidence_json, created_at, updated_at)
        SELECT 9101, ei.id, 'confirmed', 'test', '{{}}'::json, NOW(), NOW()
        FROM external_identities ei
        WHERE ei.provider = 'comicvine' AND ei.entity_type = 'issue' AND ei.external_id = '{ISSUE_ID}';
        INSERT INTO custom_cbl_lists (id, user_id, name, description, mode, created_at, updated_at, overlap_decisions_updated_at)
        VALUES (910, {user_id}, 'My List', NULL, 'loose', NOW(), NOW(), NOW());
        INSERT INTO custom_cbl_entries (id, list_id, issue_id, position, created_at, is_checkpoint, checkpoint_target_issue_ids, gate, skipped)
        VALUES (9101, 910, 9101, 0, NOW(), false, '[]'::json, 'none', false),
               (9102, 910, 9102, 1, NOW(), false, '[]'::json, 'none', false);
        "#
    ))
    .await
    .unwrap();

    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/reading-lists/910/cbl-candidates",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["list_id"], 910);
    assert_eq!(body["list_name"], "My List");
    assert_eq!(body["input_entry_count"], 2);
    assert_eq!(body["input_confirmed_total"], 1);
    assert_eq!(body["input_missing_count"], 1);
    assert_eq!(body["input_conflict_count"], 0);
    assert_eq!(body["input_ids"], json!([ISSUE_ID]));
    let entries = body["entries"].as_array().unwrap();
    assert_eq!(entries.len(), 2, "{body}");
    assert_eq!(entries[0]["identity_status"], "confirmed");
    assert_eq!(entries[0]["comicvine_issue_id"], ISSUE_ID);
    assert_eq!(entries[1]["identity_status"], "missing");
    assert!(entries[1]["comicvine_issue_id"].is_null(), "{body}");
    assert!(body["candidates_total"].as_i64().unwrap() >= 1, "{body}");
    let first = &body["candidates"][0];
    assert_eq!(first["list_id"], 1);
    assert_eq!(first["matched_input_count"], 1);
    assert_eq!(first["missing_input_ids"], json!([]));
}

#[tokio::test]
async fn adoption_plan_returns_preview_shape_for_active_list() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/issue-identity/cbl/1/adoption-plan",
        json!({"series_decisions": {}, "entry_decisions": {}}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["source"]["source_list_id"], 1);
    assert_eq!(
        body["source"]["source_path"], MIRROR_SOURCE_PATH,
        "adoption plan must return raw stored source_path like Python"
    );
    assert!(body["total_positions"].as_i64().unwrap() >= 1, "{body}");
    assert!(body["entries"].is_array(), "{body}");
    assert!(body["summary"]["final_adopted_count"].is_number(), "{body}");
}

#[tokio::test]
async fn adoption_commit_rejects_stale_fingerprint() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/cbl/1/adoption-commit",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "wrong",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(body["detail"]["code"], "stale_preview");
}

#[tokio::test]
async fn adoption_commit_creates_plan_with_valid_fingerprint() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/cbl/1/adoption-commit",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert!(
        status == StatusCode::CREATED || status == StatusCode::OK,
        "{status} {body}"
    );
    assert!(body["id"].as_i64().unwrap() > 0, "{body}");
    assert!(body["lanes"].is_array(), "{body}");
    assert!(body["nodes"].is_array(), "{body}");
    assert!(body["reused_positions"].is_array(), "{body}");
    assert!(body["created_positions"].is_array(), "{body}");
    assert!(body["excluded_positions"].is_array(), "{body}");
    assert!(body["unresolved_positions"].is_array(), "{body}");
}

#[tokio::test]
async fn adoption_plan_reports_title_number_ambiguity_statuses() {
    let (state, token, csrf, _guard) = setup().await;

    let (status, me) = get(&state, &token, "/api/v1/auth/me").await;
    assert_eq!(status, StatusCode::OK, "{me}");
    let user_id = me["id"].as_i64().unwrap() as i32;

    let conn = state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO cbl_sources (id, repository, revision_sha, synced_at, created_at, updated_at)
        VALUES (20, '{MIRROR_REPOSITORY}-amb', 'rev-20', NOW(), NOW(), NOW());
        INSERT INTO cbl_source_lists
          (id, source_id, source_path, name, declared_issue_count, content_hash,
           revision_sha, active, created_at, updated_at)
        VALUES
          (20, 20, 'DC/Ambiguous/Ambiguous.cbl', 'Ambiguous', 1, 'h-amb', 'rev-20', TRUE, NOW(), NOW());
        INSERT INTO external_identities
          (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
        VALUES
          (20, 'comicvine', 'issue', '4000-amb', '{{}}'::json, NOW(), NOW()),
          (21, 'comicvine', 'series', '4050-amb', '{{}}'::json, NOW(), NOW());
        INSERT INTO cbl_source_entries
          (id, list_id, "position", series_name, issue_number, volume_year,
           publication_year, external_issue_identity_id, external_series_identity_id, created_at)
        VALUES
          (20, 20, 0, 'Ambiguous Series', '1', 2000, 2000, 20, 21, NOW());

        INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status, total_issues, reading_progress, created_at)
        VALUES
          (920, {user_id}, 'Ambiguous Series', 'comic', 1, 90, 'active', 1, 'in_progress', NOW()),
          (921, {user_id}, 'Ambiguous Series', 'comic', 1, 91, 'active', 1, 'in_progress', NOW());
        INSERT INTO issues (id, thread_id, issue_number, position, status, created_at)
        VALUES
          (9201, 920, '1', 0, 'unread', NOW()),
          (9211, 921, '1', 0, 'unread', NOW());
        INSERT INTO thread_external_series_mappings (thread_id, external_identity_id, status, evidence_source, created_at, updated_at)
        VALUES
          (920, 21, 'confirmed', 'test', NOW(), NOW()),
          (921, 21, 'confirmed', 'test', NOW(), NOW());
        "#
    ))
    .await
    .unwrap();

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/issue-identity/cbl/20/adoption-plan",
        json!({"series_decisions": {}, "entry_decisions": {}}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["total_positions"], 1, "{body}");
    let entry = &body["entries"][0];
    assert_eq!(
        entry["resolution_status"], "ambiguous_title_number_multiple_matches",
        "{body}"
    );
    assert_eq!(entry["adoption_decision"], "unresolved", "{body}");
    assert!(entry["resolved_issue_id"].is_null(), "{body}");
}

#[tokio::test]
async fn adoption_commit_materializes_missing_importable_issue() {
    let (state, token, csrf, _guard) = setup().await;

    let conn = state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO cbl_sources (id, repository, revision_sha, synced_at, created_at, updated_at)
        VALUES (30, '{MIRROR_REPOSITORY}-new', 'rev-30', NOW(), NOW(), NOW());
        INSERT INTO cbl_source_lists
          (id, source_id, source_path, name, declared_issue_count, content_hash,
           revision_sha, active, created_at, updated_at)
        VALUES
          (30, 30, 'DC/New/New.cbl', 'New Importable', 1, 'h-new', 'rev-30', TRUE, NOW(), NOW());
        INSERT INTO external_identities
          (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
        VALUES
          (30, 'comicvine', 'issue', '4000-new', '{{}}'::json, NOW(), NOW())
        ON CONFLICT DO NOTHING;
        INSERT INTO cbl_source_entries
          (id, list_id, "position", series_name, issue_number, volume_year,
           publication_year, external_issue_identity_id, external_series_identity_id, created_at)
        VALUES
          (30, 30, 0, 'Brand New Series', '1', 2024, 2024, 30, NULL, NOW());
        "#
    ))
    .await
    .unwrap();

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/cbl/30/adoption-commit",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-new",
            "revision_sha": "rev-30"
        }),
    )
    .await;
    assert!(
        status == StatusCode::CREATED || status == StatusCode::OK,
        "{status} {body}"
    );
    assert_eq!(body["created_positions"], json!([0]), "{body}");
    assert_eq!(body["unresolved_positions"], json!([]), "{body}");
    assert_eq!(body["excluded_positions"], json!([]), "{body}");
}

#[tokio::test]
async fn targeted_adoption_commit_route_returns_200() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/cbl/1/adoption-commit",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert!(
        status == StatusCode::CREATED || status == StatusCode::OK,
        "{status} {body}"
    );
    let plan_id = body["id"].as_i64().expect("plan id");

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        &format!("/api/v1/cbl/1/reading-plans/{plan_id}/adoption-commit"),
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["id"], plan_id, "{body}");
}

#[tokio::test]
async fn adoption_commit_invalid_decision_returns_422_enum() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/cbl/1/adoption-commit",
        json!({
            "entry_decisions": {"0": "bogus"},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"][0]["type"], "enum", "{body}");
    assert_eq!(
        body["detail"][0]["loc"],
        json!(["body", "entry_decisions", "0"]),
        "{body}"
    );

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/cbl/1/reading-plans/1/adoption-commit",
        json!({
            "series_decisions": [{"series_name": "S", "decision": "nope"}],
            "entry_decisions": {},
            "series_overrides": [],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    // plan 1 may not exist for this user; validation happens before lookup, so still 422 enum
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"][0]["type"], "enum", "{body}");
}

#[tokio::test]
async fn adoption_commit_unauthenticated_returns_401() {
    let (state, _token, _csrf, _guard) = setup().await;
    let (status, _body) = send(
        &state,
        Request::builder()
            .method("POST")
            .uri("/api/v1/cbl/1/adoption-commit")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "entry_decisions": {},
                    "series_decisions": [],
                    "series_overrides": [],
                    "content_hash": "h-mm",
                    "revision_sha": "rev-1"
                })
                .to_string(),
            ))
            .unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED, "{_body}");
}

#[tokio::test]
async fn targeted_adoption_commit_other_users_plan_returns_422() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/cbl/1/adoption-commit",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert!(
        status == StatusCode::CREATED || status == StatusCode::OK,
        "{status} {body}"
    );
    let plan_id = body["id"].as_i64().expect("plan id");

    // register a second user
    let suffix = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let username = format!("issue-identity-other-{suffix}");
    let response = router(state.clone())
        .oneshot(
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
        .await
        .unwrap();
    let csrf2 = response
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .find_map(|cookie| {
            let cookie = cookie.to_str().ok()?;
            cookie
                .strip_prefix("csrf_token=")?
                .split(';')
                .next()
                .map(str::to_owned)
        })
        .expect("register sets a CSRF cookie");
    let body_bytes = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&body_bytes).unwrap();
    let token2 = body["access_token"].as_str().unwrap().to_owned();

    let (status, body) = post_json(
        &state,
        &token2,
        &csrf2,
        &format!("/api/v1/cbl/1/reading-plans/{plan_id}/adoption-commit"),
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(
        body["detail"]["message"], "Reading Plan not found",
        "{body}"
    );
}

async fn register_user(
    state: &Arc<AppState>,
    username: &str,
    ip_suffix: usize,
) -> (String, String) {
    let response = router(state.clone())
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/auth/register")
                .header("x-forwarded-for", format!("2001:db8::{ip_suffix:x}"))
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
    let csrf = response
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .find_map(|cookie| {
            let cookie = cookie.to_str().ok()?;
            cookie
                .strip_prefix("csrf_token=")?
                .split(';')
                .next()
                .map(str::to_owned)
        })
        .expect("register sets a CSRF cookie");
    let body_bytes = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
    let body: Value = serde_json::from_slice(&body_bytes).unwrap();
    let token = body["access_token"].as_str().unwrap().to_owned();
    (token, csrf)
}

#[tokio::test]
async fn reading_list_candidates_other_user_returns_404() {
    let (state, token, _csrf, _guard) = setup().await;
    let (status, me) = get(&state, &token, "/api/v1/auth/me").await;
    assert_eq!(status, StatusCode::OK, "{me}");
    let user_id = me["id"].as_i64().unwrap() as i32;
    let conn = state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO custom_cbl_lists (id, user_id, name, description, mode, created_at, updated_at, overlap_decisions_updated_at)
        VALUES (920, {user_id}, 'Mine', NULL, 'loose', NOW(), NOW(), NOW())
        ON CONFLICT (id) DO NOTHING;
        "#
    ))
    .await
    .unwrap();

    let suffix = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let (token2, _csrf2) = register_user(
        &state,
        &format!("issue-identity-cand-{suffix}"),
        NEXT_CLIENT.fetch_add(1, Ordering::Relaxed),
    )
    .await;

    let (status, body) = get(
        &state,
        &token2,
        "/api/v1/issue-identity/reading-lists/920/cbl-candidates",
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body}");
    assert_eq!(body["detail"], "Custom CBL 920 not found", "{body}");
}

#[tokio::test]
async fn adoption_commit_other_users_thread_not_reused() {
    let (state, token, csrf, _guard) = setup().await;
    let suffix = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let (token2, _csrf2) = register_user(
        &state,
        &format!("issue-identity-thread-{suffix}"),
        NEXT_CLIENT.fetch_add(1, Ordering::Relaxed),
    )
    .await;
    let (status, me2) = get(&state, &token2, "/api/v1/auth/me").await;
    assert_eq!(status, StatusCode::OK, "{me2}");
    let user2 = me2["id"].as_i64().unwrap() as i32;

    let conn = state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status, total_issues, reading_progress, created_at)
        VALUES (930, {user2}, 'CBL: Mister Miracle (1989)', 'comic', 0, 1, 'active', 0, 'not_started', NOW())
        ON CONFLICT (id) DO NOTHING;
        "#
    ))
    .await
    .unwrap();

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/cbl/1/adoption-commit",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert!(
        status == StatusCode::CREATED || status == StatusCode::OK,
        "{status} {body}"
    );

    let row = conn
        .query_one("SELECT COUNT(*)::bigint FROM threads WHERE id = 930", &[])
        .await
        .unwrap();
    let count: i64 = row.get(0);
    assert_eq!(count, 1, "other user's thread must remain untouched");
    let row = conn
        .query_one("SELECT user_id FROM threads WHERE id = 930", &[])
        .await
        .unwrap();
    let owner: i32 = row.get(0);
    assert_eq!(
        owner, user2,
        "other user's thread ownership must not change"
    );
}

#[tokio::test]
async fn adoption_commit_recommit_is_idempotent() {
    let (state, token, csrf, _guard) = setup().await;
    let payload = json!({
        "entry_decisions": {},
        "series_decisions": [],
        "series_overrides": [],
        "content_hash": "h-mm",
        "revision_sha": "rev-1"
    });

    let (status1, body1) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/cbl/1/adoption-commit",
        payload.clone(),
    )
    .await;
    assert!(
        status1 == StatusCode::CREATED || status1 == StatusCode::OK,
        "{status1} {body1}"
    );
    let plan_id = body1["id"].as_i64().expect("plan id");
    let nodes1 = body1["nodes"].as_array().cloned().unwrap_or_default();

    let (status2, body2) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/cbl/1/adoption-commit",
        payload,
    )
    .await;
    assert!(
        status2 == StatusCode::CREATED || status2 == StatusCode::OK,
        "{status2} {body2}"
    );
    assert_eq!(body2["id"], plan_id, "re-commit must target same plan");
    let nodes2 = body2["nodes"].as_array().cloned().unwrap_or_default();
    assert_eq!(
        nodes2.len(),
        nodes1.len(),
        "re-commit must not duplicate nodes: first={body1} second={body2}"
    );
    assert!(
        body2["created_positions"]
            .as_array()
            .map(|a| a.is_empty())
            .unwrap_or(true),
        "re-commit must not create duplicate positions: {body2}"
    );
}

#[tokio::test]
async fn adoption_commit_inactive_list_returns_422() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/cbl/3/adoption-commit",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-dead",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(
        body["detail"]["message"], "CBL source list is not active",
        "{body}"
    );
}

#[tokio::test]
async fn adoption_commit_returns_503_on_database_outage() {
    let secret = comicpile_roll_service::test_support::TEST_JWT_SECRET;
    let state = Arc::new(
        AppState::new(
            Config::from_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => {
                    Some("postgresql://127.0.0.1:1/unreachable?connect_timeout=1".into())
                }
                "RUST_ROLL_JWT_SECRET" => Some(secret.into()),
                "RUST_ROLL_POOL_SIZE" => Some("1".into()),
                "RUST_ROLL_REQUEST_TIMEOUT_MS" => Some("1000".into()),
                _ => None,
            })
            .unwrap(),
        )
        .unwrap(),
    );
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;
    let key = jsonwebtoken::EncodingKey::from_secret(secret.as_bytes()).unwrap();
    let token = jsonwebtoken::encode(
        &jsonwebtoken::Header::new(jsonwebtoken::Algorithm::HS256),
        &json!({
            "sub": "reader",
            "jti": "test-jti",
            "type": "access",
            "exp": now + 3600
        }),
        &key,
    )
    .unwrap();
    let (status, body) = send(
        &state,
        Request::builder()
            .method("POST")
            .uri("/api/v1/cbl/1/adoption-commit")
            .header(header::AUTHORIZATION, format!("Bearer {token}"))
            .header(header::CONTENT_TYPE, "application/json")
            .header("x-csrf-token", "csrf")
            .header(header::COOKIE, "csrf_token=csrf")
            .body(Body::from(
                json!({
                    "entry_decisions": {},
                    "series_decisions": [],
                    "series_overrides": [],
                    "content_hash": "h-mm",
                    "revision_sha": "rev-1"
                })
                .to_string(),
            ))
            .unwrap(),
    )
    .await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE, "{body}");
    assert_eq!(body["error"]["code"], "database_unavailable", "{body}");
}
