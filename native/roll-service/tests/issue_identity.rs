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
use comicpile_roll_service::{config::Config, router, test_support, AppState};
use serde_json::{json, Value};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use tower::ServiceExt;

static NEXT_CLIENT: AtomicUsize = AtomicUsize::new(1);
/// One private database per test *binary*: every integration test target is a
/// separate process with its own `DB_LOCK`, so a shared database lets parallel
/// binaries truncate and reseed each other's rows mid-assertion. Loading the
/// canonical Alembic fixture into a per-process database keeps schema and data
/// deterministic without retries, timeouts or hand-written DDL.
static PRIVATE_DB: tokio::sync::OnceCell<String> = tokio::sync::OnceCell::const_new();

const MIRROR_REPOSITORY: &str = "/mnt/bigdata/CBL-ReadingLists";
const PUBLIC_REPOSITORY: &str = "JoshCLWren/CBL-ReadingLists";
const MIRROR_SOURCE_PATH: &str =
    "/mnt/bigdata/CBL-ReadingLists/DC/Mister Miracle (1989)/Mister Miracle.cbl";
const PUBLIC_SOURCE_PATH: &str = "DC/Mister Miracle (1989)/Mister Miracle.cbl";
const ISSUE_ID: &str = "4000-123";
const VOLUME_ID: &str = "4050-9";

/// Return a DML-role DSN for a database private to this test process. The admin
/// DSN creates it and loads the checked-in Alembic schema once; every test in
/// this binary then resets (truncates) only this database while holding the
/// crate-wide `DB_LOCK`. Other binaries never touch these rows.
async fn isolated_test_database_url() -> String {
    PRIVATE_DB
        .get_or_init(|| async {
            // Provision the shared DML role and canonical schema first, so the
            // role exists cluster-wide before the private database is granted.
            let dml_shared = comicpile_roll_service::test_support::database_url().await;
            let admin = std::env::var("RUST_ROLL_TEST_DATABASE_URL")
                .expect("RUST_ROLL_TEST_DATABASE_URL is required");
            comicpile_roll_service::test_support::assert_safe_test_database(&admin);
            let with_database = |dsn: &str, database: &str| -> String {
                let (prefix, _) = dsn
                    .rsplit_once('/')
                    .expect("database URL must contain a database name");
                format!("{prefix}/{database}")
            };

            // A stable name keeps at most one private database on disk; each
            // run drops and recreates it. No other integration-test binary uses
            // this name, so parallel binaries stay isolated from one another.
            let db_name = "issue_identity_rust_tests".to_string();
            let (admin_client, connection) = tokio_postgres::connect(&admin, tokio_postgres::NoTls)
                .await
                .unwrap();
            tokio::spawn(async move {
                let _ = connection.await;
            });
            admin_client
                .batch_execute(&format!("DROP DATABASE IF EXISTS {db_name}"))
                .await
                .unwrap();
            admin_client
                .batch_execute(&format!("CREATE DATABASE {db_name}"))
                .await
                .unwrap();
            drop(admin_client);

            let admin_private = with_database(&admin, &db_name);
            let (admin_client, connection) =
                tokio_postgres::connect(&admin_private, tokio_postgres::NoTls)
                    .await
                    .unwrap();
            tokio::spawn(async move {
                let _ = connection.await;
            });
            let schema = std::fs::read_to_string(
                std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("tests/fixtures/schema/public_schema.sql"),
            )
            .expect("canonical Alembic schema fixture");
            admin_client.batch_execute(&schema).await.unwrap();
            admin_client
                .batch_execute(
                    "REVOKE CREATE ON SCHEMA public FROM PUBLIC; \
                     REVOKE CREATE ON SCHEMA public FROM roll_test_dml; \
                     GRANT USAGE ON SCHEMA public TO roll_test_dml; \
                     GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE \
                         ON ALL TABLES IN SCHEMA public TO roll_test_dml; \
                     GRANT USAGE, SELECT, UPDATE \
                         ON ALL SEQUENCES IN SCHEMA public TO roll_test_dml;",
                )
                .await
                .unwrap();
            drop(admin_client);

            with_database(&dml_shared, &db_name)
        })
        .await
        .clone()
}

async fn setup() -> (
    Arc<AppState>,
    String,
    String,
    tokio::sync::MutexGuard<'static, ()>,
) {
    let url = isolated_test_database_url().await;
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

    let (token, csrf) = create_test_user(&state, "issue-identity").await;
    seed_catalog(&state).await;
    (state, token, csrf, guard)
}

/// Mint a valid access token for a reader without the bcrypt/HTTP registration
/// round trip. Auth only needs a `users` row with a matching `sub` claim plus a
/// non-empty `jti` (see `auth::identity::authenticate_claims`).
fn mint_test_token(username: &str, jti: &str) -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;
    let key = jsonwebtoken::EncodingKey::from_secret(
        comicpile_roll_service::test_support::TEST_JWT_SECRET.as_bytes(),
    )
    .unwrap();
    jsonwebtoken::encode(
        &jsonwebtoken::Header::new(jsonwebtoken::Algorithm::HS256),
        &json!({"sub": username, "jti": jti, "type": "access", "exp": now + 3600}),
        &key,
    )
    .unwrap()
}

/// Create an authenticated test user directly in the private database. The
/// CBL route assertions below are unchanged; this only removes a timing-
/// dependent bcrypt registration from setup so parallel/loaded runs are
/// deterministic (no retries and no longer timeouts).
async fn create_test_user(state: &Arc<AppState>, label: &str) -> (String, String) {
    let suffix = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let username = format!("{label}-{suffix}");
    let conn = state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO users (username, created_at) VALUES ($1, NOW())",
        &[&username],
    )
    .await
    .unwrap();
    let token = mint_test_token(&username, &format!("jti-{suffix}"));
    let csrf = format!("csrf-{suffix}");
    (token, csrf)
}

async fn send(state: &Arc<AppState>, request: Request<Body>) -> (StatusCode, Value) {
    let response = router(state.clone()).oneshot(request).await.unwrap();
    let status = response.status();
    // Large adoption responses carry a node per issue (#5522); allow enough
    // body room to assert the full atomic result instead of truncating it.
    let bytes = to_bytes(response.into_body(), 4 * 1024 * 1024)
        .await
        .unwrap();
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

    // Resolve the authenticated user's id from /api/v2/auth/me.
    let (status, me) = get(&state, &token, "/api/v2/auth/me").await;
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
async fn adoption_preview_returns_preview_shape_for_active_list() {
    let (state, token, _csrf, _guard) = setup().await;
    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl/1/adoption-preview",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["source"]["source_list_id"], 1);
    assert_eq!(
        body["source"]["source_path"], MIRROR_SOURCE_PATH,
        "adoption preview must return raw stored source_path like Python"
    );
    assert!(body["total_positions"].as_i64().unwrap() >= 1, "{body}");
    assert!(body["entries"].is_array(), "{body}");
    assert!(body["summary"]["final_adopted_count"].is_number(), "{body}");
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
        "/api/v2/reading-lists/1/adoption-commits",
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
        "/api/v2/reading-lists/1/adoption-commits",
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
async fn adoption_commit_persists_canonical_reading_list_and_plan_projection_issue_5523() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [
                {"cbl_position": 0, "decision": "include"},
                {"cbl_position": 1, "decision": "exclude"}
            ],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{status} {body}");
    let plan_id = body["id"].as_i64().unwrap() as i32;
    assert_eq!(body["created_positions"], json!([0]), "{body}");
    assert_eq!(body["excluded_positions"], json!([1]), "{body}");

    let conn = state.pool.get().await.unwrap();
    let source_row = conn
        .query_one(
            "SELECT custom_cbl_list_id FROM reading_plan_sources
             WHERE plan_id = $1 AND custom_cbl_list_id IS NOT NULL
             ORDER BY id DESC LIMIT 1",
            &[&plan_id],
        )
        .await
        .unwrap();
    let list_id: i32 = source_row.get(0);
    assert!(list_id > 0, "canonical reading list must be created");

    let entries: Vec<(i32, i32)> = conn
        .query(
            "SELECT issue_id, position FROM custom_cbl_entries WHERE list_id = $1 ORDER BY position, id",
            &[&list_id],
        )
        .await
        .unwrap()
        .into_iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();
    assert_eq!(
        entries.len(),
        1,
        "exactly the approved entry should be persisted: {entries:?}"
    );

    let (reader_status, reader_body) = get(
        &state,
        &token,
        &format!("/api/v2/continuity-plans/{plan_id}/reader"),
    )
    .await;
    assert_eq!(reader_status, StatusCode::OK, "{reader_body}");
    assert_eq!(reader_body["progress"]["total_issues"], 1, "{reader_body}");
    assert_eq!(reader_body["progress"]["read_issues"], 0, "{reader_body}");
    let lanes = reader_body["lanes"].as_array().unwrap();
    let issue_count: usize = lanes
        .iter()
        .map(|lane| lane["issues"].as_array().map(|a| a.len()).unwrap_or(0))
        .sum();
    assert_eq!(issue_count, 1, "{reader_body}");

    // Canonical list is discoverable/reopenable by stable ID.
    let (list_status, list_body) =
        get(&state, &token, &format!("/api/v2/reading-lists/{list_id}")).await;
    assert_eq!(list_status, StatusCode::OK, "{list_body}");
    assert_eq!(list_body["id"], list_id, "{list_body}");
    let list_entries = list_body["entries"].as_array().unwrap();
    assert_eq!(list_entries.len(), 1, "{list_body}");

    // Repeat Add/Update keeps same source-linked list ID and no duplicate unrelated legacy plan.
    let plans_before: i64 = conn
        .query_one("SELECT COUNT(*)::bigint FROM continuity_plans WHERE user_id = (SELECT id FROM users WHERE username LIKE 'issue-identity-%' ORDER BY id DESC LIMIT 1)", &[])
        .await
        .unwrap()
        .get(0);
    let (status2, body2) = post_json(
        &state,
        &token,
        &csrf,
        &format!("/api/v2/reading-lists/1/reading-plans/{plan_id}/adoption-commits"),
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [
                {"cbl_position": 0, "decision": "include"},
                {"cbl_position": 1, "decision": "exclude"}
            ],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert_eq!(status2, StatusCode::OK, "{status2} {body2}");
    let source_row2 = conn
        .query_one(
            "SELECT custom_cbl_list_id FROM reading_plan_sources
             WHERE plan_id = $1 AND custom_cbl_list_id IS NOT NULL
             ORDER BY id DESC LIMIT 1",
            &[&plan_id],
        )
        .await
        .unwrap();
    let list_id2: i32 = source_row2.get(0);
    assert_eq!(
        list_id2, list_id,
        "repeat add/update must keep same source-linked list ID"
    );
    let plans_after: i64 = conn
        .query_one("SELECT COUNT(*)::bigint FROM continuity_plans WHERE user_id = (SELECT id FROM users WHERE username LIKE 'issue-identity-%' ORDER BY id DESC LIMIT 1)", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        plans_after, plans_before,
        "repeat add/update must not create duplicate unrelated legacy plan"
    );
}

#[tokio::test]
async fn targeted_adoption_commit_uses_plan_lane_and_reconciles_exclusions_issue_5523() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, me) = get(&state, &token, "/api/v2/auth/me").await;
    assert_eq!(status, StatusCode::OK, "{me}");
    let user_id = me["id"].as_i64().unwrap() as i32;
    let conn = state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO continuity_plans
           (id, user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at)
         VALUES
           (552310, $1, 'Custom lane plan', 'informational',
            '[{\"id\":\"custom-lane\",\"name\":\"Custom\",\"order\":0}]'::jsonb,
            '[]'::jsonb, NOW(), NOW())",
        &[&user_id],
    )
    .await
    .unwrap();
    drop(conn);

    // The plan has a single non-default lane; the committed step must inherit
    // that lane id instead of the hard-coded "default" from the repro.
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/reading-plans/552310/adoption-commits",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [
                {"cbl_position": 0, "decision": "include"},
                {"cbl_position": 1, "decision": "exclude"}
            ],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{status} {body}");
    let nodes = body["nodes"].as_array().unwrap();
    let issue_nodes: Vec<&Value> = nodes
        .iter()
        .filter(|node| node["node_type"] == "issue")
        .collect();
    assert_eq!(issue_nodes.len(), 1, "{body}");
    assert_eq!(issue_nodes[0]["lane_id"], "custom-lane", "{body}");
    let issue_id = issue_nodes[0]["ref_id"].as_i64().unwrap() as i32;

    // The edit-lane projection shows the step too (not just "No steps in lane").
    let (edit_status, edit_body) = get(&state, &token, "/api/v2/continuity-plans/552310").await;
    assert_eq!(edit_status, StatusCode::OK, "{edit_body}");
    let edit_nodes = edit_body["nodes"].as_array().unwrap();
    let lane_nodes: Vec<&Value> = edit_nodes
        .iter()
        .filter(|node| node["node_type"] == "issue" && node["lane_id"] == "custom-lane")
        .collect();
    assert_eq!(lane_nodes.len(), 1, "{edit_body}");

    let (reader_status, reader_body) =
        get(&state, &token, "/api/v2/continuity-plans/552310/reader").await;
    assert_eq!(reader_status, StatusCode::OK, "{reader_body}");
    assert_eq!(reader_body["progress"]["total_issues"], 1, "{reader_body}");

    let conn = state.pool.get().await.unwrap();
    let list_id: i32 = conn
        .query_one(
            "SELECT custom_cbl_list_id FROM reading_plan_sources
             WHERE plan_id = 552310 AND custom_cbl_list_id IS NOT NULL
             ORDER BY id DESC LIMIT 1",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    let entry_count: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM custom_cbl_entries WHERE list_id = $1",
            &[&list_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(entry_count, 1, "only the approved entry may be persisted");

    // A later explicit commit that excludes every source issue must remove the
    // previously adopted entry from the canonical list and its reader projection.
    let (status2, body2) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/reading-plans/552310/adoption-commits",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [
                {"cbl_position": 0, "decision": "exclude"},
                {"cbl_position": 1, "decision": "exclude"}
            ],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert_eq!(status2, StatusCode::OK, "{status2} {body2}");
    let entry_count2: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM custom_cbl_entries WHERE list_id = $1",
            &[&list_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        entry_count2, 0,
        "excluded issue must not survive in the canonical list: {body2}"
    );
    let (reader_status2, reader_body2) =
        get(&state, &token, "/api/v2/continuity-plans/552310/reader").await;
    assert_eq!(reader_status2, StatusCode::OK, "{reader_body2}");
    assert_eq!(
        reader_body2["progress"]["total_issues"], 0,
        "{reader_body2}"
    );

    // Reconciliation only removes list membership: the issue and any reading
    // history survive, and the source-linked list ID stays stable.
    let issue_rows: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM issues WHERE id = $1",
            &[&issue_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        issue_rows, 1,
        "adoption must not delete issues or reading history"
    );
    let list_id2: i32 = conn
        .query_one(
            "SELECT custom_cbl_list_id FROM reading_plan_sources
             WHERE plan_id = 552310 AND custom_cbl_list_id IS NOT NULL
             ORDER BY id DESC LIMIT 1",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        list_id2, list_id,
        "the source-linked list ID must stay stable"
    );
}

async fn crossover_snapshot(
    state: &Arc<AppState>,
) -> Vec<(
    i32,
    i32,
    String,
    Option<i32>,
    Option<i32>,
    Option<i32>,
    Option<i32>,
    Option<i32>,
)> {
    let conn = state.pool.get().await.unwrap();
    conn.query(
        "SELECT g.id, g.user_id, g.name,
                m.id, m.group_id, m.thread_id, m.issue_id, m.sequence_order
         FROM dependency_groups g
         LEFT JOIN dependency_group_memberships m ON m.group_id = g.id
         ORDER BY g.id, m.id",
        &[],
    )
    .await
    .unwrap()
    .iter()
    .map(|row| {
        (
            row.get(0),
            row.get(1),
            row.get(2),
            row.get(3),
            row.get(4),
            row.get(5),
            row.get(6),
            row.get(7),
        )
    })
    .collect()
}

async fn seed_crossover_sentinel(state: &Arc<AppState>, user_id: i32) {
    let conn = state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO threads
          (id, user_id, title, format, issues_remaining, queue_position, status,
           total_issues, reading_progress, created_at)
        VALUES
          (351700, {user_id}, 'Existing crossover thread', 'comic', 1, 90, 'active',
           1, 'not_started', NOW());
        INSERT INTO issues (id, thread_id, issue_number, position, status, created_at)
        VALUES (351701, 351700, '1', 0, 'unread', NOW());
        INSERT INTO dependency_groups (id, user_id, name, created_at)
        VALUES (351702, {user_id}, 'Reader-created crossover', NOW());
        INSERT INTO dependency_group_memberships
          (id, group_id, issue_id, sequence_order)
        VALUES (351703, 351702, 351701, 0);
        "#
    ))
    .await
    .unwrap();
}

fn one_selected_adoption_payload() -> Value {
    json!({
        "entry_decisions": {},
        "series_decisions": [],
        "series_overrides": [
            {"cbl_position": 0, "decision": "include"},
            {"cbl_position": 1, "decision": "exclude"}
        ],
        "content_hash": "h-mm",
        "revision_sha": "rev-1"
    })
}

fn assert_one_selected_adoption(body: &Value, plan_id: i64) {
    assert_eq!(body["id"], plan_id, "{body}");
    assert_eq!(body["created_positions"], json!([0]), "{body}");
    assert_eq!(body["reused_positions"], json!([]), "{body}");
    assert_eq!(body["excluded_positions"], json!([1]), "{body}");
    assert_eq!(body["unresolved_positions"], json!([]), "{body}");
    let nodes = body["nodes"].as_array().unwrap();
    assert_eq!(
        nodes.len(),
        1,
        "only the selected entry belongs in the plan: {body}"
    );
    assert_eq!(nodes[0]["node_type"], "issue", "{body}");
    assert_eq!(nodes[0]["label"], "Mister Miracle #1", "{body}");
    assert!(nodes[0]["ref_id"].as_i64().unwrap() > 0, "{body}");
}

#[tokio::test]
async fn adoption_commit_does_not_create_crossover_event_label_issue_3517() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, me) = get(&state, &token, "/api/v2/auth/me").await;
    assert_eq!(status, StatusCode::OK, "{me}");
    let user_id = me["id"].as_i64().unwrap() as i32;
    seed_crossover_sentinel(&state, user_id).await;
    let before = crossover_snapshot(&state).await;
    assert_eq!(
        before.len(),
        1,
        "the sentinel must make this a non-empty check"
    );

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        one_selected_adoption_payload(),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{status} {body}");
    let plan_id = body["id"].as_i64().expect("plan id");
    assert_one_selected_adoption(&body, plan_id);

    assert_eq!(
        crossover_snapshot(&state).await,
        before,
        "CBL adoption must neither create event labels nor change their memberships (issue #3517): {body}"
    );
}

#[tokio::test]
async fn targeted_adoption_commit_does_not_create_crossover_event_label_issue_3517() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, me) = get(&state, &token, "/api/v2/auth/me").await;
    assert_eq!(status, StatusCode::OK, "{me}");
    let user_id = me["id"].as_i64().unwrap() as i32;
    seed_crossover_sentinel(&state, user_id).await;
    let conn = state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO continuity_plans
           (id, user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at)
         VALUES
           (351710, $1, 'Fresh target plan', 'informational',
            '[{\"id\":\"default\",\"name\":\"Default\",\"order\":0}]'::jsonb,
            '[]'::jsonb, NOW(), NOW())",
        &[&user_id],
    )
    .await
    .unwrap();
    drop(conn);
    let before = crossover_snapshot(&state).await;
    assert_eq!(
        before.len(),
        1,
        "the sentinel must make this a non-empty check"
    );

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/reading-plans/351710/adoption-commits",
        one_selected_adoption_payload(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{status} {body}");
    assert_one_selected_adoption(&body, 351710);

    assert_eq!(
        crossover_snapshot(&state).await,
        before,
        "Targeted CBL adoption must neither create event labels nor change their memberships (issue #3517): {body}"
    );
}

#[tokio::test]
async fn adoption_plan_reports_title_number_ambiguity_statuses() {
    let (state, token, csrf, _guard) = setup().await;

    let (status, me) = get(&state, &token, "/api/v2/auth/me").await;
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
        "/api/v2/reading-lists/30/adoption-commits",
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

/// #5522: the QA repro (Alpha Flight, 228 entries) must commit atomically
/// within the client's 60s timeout and replay the authoritative receipt when
/// the response is lost. No partial plan or dropped entry may be returned.
#[tokio::test]
async fn adoption_commit_large_source_commits_and_replays_receipt_5522() {
    let (state, token, csrf, _guard) = setup().await;

    let conn = state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO cbl_sources (id, repository, revision_sha, synced_at, created_at, updated_at)
        VALUES (9001, '{MIRROR_REPOSITORY}-large', 'rev-1', NOW(), NOW(), NOW());
        INSERT INTO cbl_source_lists
          (id, source_id, source_path, name, declared_issue_count, content_hash,
           revision_sha, active, created_at, updated_at)
        VALUES
          (9001, 9001, 'Marvel/Alpha Flight (1983)/Alpha Flight.cbl',
           'Alpha Flight (1983)', 228, 'h-large', 'rev-1', TRUE, NOW(), NOW());
        INSERT INTO external_identities
          (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
        SELECT 20000 + g, 'comicvine', 'issue', format('4000-large-%s', g), '{{}}'::json, NOW(), NOW()
        FROM generate_series(0, 227) AS g;
        INSERT INTO cbl_source_entries
          (id, list_id, "position", series_name, issue_number, volume_year,
           publication_year, external_issue_identity_id, created_at)
        SELECT 10000 + g, 9001, g, 'Alpha Flight', g::text, 1983, 1983, 20000 + g, NOW()
        FROM generate_series(0, 227) AS g;
        "#
    ))
    .await
    .unwrap();

    let payload = json!({
        "entry_decisions": {},
        "series_decisions": [],
        "series_overrides": [],
        "content_hash": "h-large",
        "revision_sha": "rev-1",
        "idempotency_key": "qa-alpha-flight-228"
    });
    let started = std::time::Instant::now();
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/9001/adoption-commits",
        payload.clone(),
    )
    .await;
    let elapsed = started.elapsed();
    assert_eq!(status, StatusCode::CREATED, "{status} {body}");
    assert!(
        elapsed < std::time::Duration::from_secs(60),
        "large adoption exceeded the 60s client timeout: {elapsed:?}"
    );
    assert_eq!(
        body["created_positions"].as_array().map(Vec::len),
        Some(228),
        "all approved entries must commit in one transaction: {body}"
    );
    assert_eq!(body["unresolved_positions"], json!([]), "{body}");

    let plan_id = body["id"].as_i64().unwrap() as i32;
    let (reader_status, reader_body) = get(
        &state,
        &token,
        &format!("/api/v2/continuity-plans/{plan_id}/reader"),
    )
    .await;
    assert_eq!(reader_status, StatusCode::OK, "{reader_body}");
    assert_eq!(
        reader_body["progress"]["total_issues"], 228,
        "{reader_body}"
    );

    let list_id: i32 = conn
        .query_one(
            "SELECT custom_cbl_list_id FROM reading_plan_sources
             WHERE plan_id = $1 AND custom_cbl_list_id IS NOT NULL
             ORDER BY id DESC LIMIT 1",
            &[&plan_id],
        )
        .await
        .unwrap()
        .get(0);
    let entry_count: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM custom_cbl_entries WHERE list_id = $1",
            &[&list_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        entry_count, 228,
        "the canonical reading list must hold every adopted issue: {body}"
    );

    // A lost response replays the authoritative stored result instead of
    // re-running the adoption or reporting "nothing happened" (#5522).
    let (replay_status, replay_body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/9001/adoption-commits",
        payload,
    )
    .await;
    assert_eq!(
        replay_status,
        StatusCode::CREATED,
        "{replay_status} {replay_body}"
    );
    assert_eq!(replay_body, body, "receipt replay must be byte-identical");
    let plan_count: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM continuity_plans WHERE user_id = (SELECT id FROM users WHERE username LIKE 'issue-identity-%' ORDER BY id DESC LIMIT 1)",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(plan_count, 1, "replay must not create a duplicate plan");
}

#[tokio::test]
async fn adoption_commit_seats_missing_low_issues_in_natural_order_3483() {
    // #3483: adopting a CBL list into an existing series thread that already
    // held #7-#24 must seat #1 and #2 in front of #7, not append them after
    // #24. The ordering is owned by the shared `natural_issue_order` routine
    // used by every insertion path.
    let (state, token, csrf, _guard) = setup().await;

    let conn = state.pool.get().await.unwrap();
    let user_id: i32 = conn
        .query_one(
            "SELECT id FROM users WHERE username LIKE 'issue-identity-%' ORDER BY id DESC LIMIT 1",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    let issues_seed = (7..=24)
        .enumerate()
        .map(|(idx, number)| {
            format!(
                "({}, 34830, '{}', {}, 'unread', NOW())",
                348300 + idx,
                number,
                idx + 1
            )
        })
        .collect::<Vec<_>>()
        .join(",\n          ");
    conn.batch_execute(&format!(
        r#"
        INSERT INTO cbl_sources (id, repository, revision_sha, synced_at, created_at, updated_at)
        VALUES (40, '{MIRROR_REPOSITORY}-3483', 'rev-3483', NOW(), NOW(), NOW());
        INSERT INTO cbl_source_lists
          (id, source_id, source_path, name, declared_issue_count, content_hash,
           revision_sha, active, created_at, updated_at)
        VALUES
          (40, 40, 'Marvel/Ultimate/Ultimate Spider-Man.cbl', 'Ultimate Spider-Man',
           2, 'h-3483', 'rev-3483', TRUE, NOW(), NOW());
        INSERT INTO external_identities
          (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
        VALUES
          (3481, 'comicvine', 'issue', '4000-3483-1', '{{}}'::json, NOW(), NOW()),
          (3482, 'comicvine', 'issue', '4000-3483-2', '{{}}'::json, NOW(), NOW()),
          (3483, 'comicvine', 'series', '4050-3483', '{{}}'::json, NOW(), NOW());
        INSERT INTO cbl_source_entries
          (id, list_id, "position", series_name, issue_number, volume_year,
           publication_year, external_issue_identity_id, external_series_identity_id, created_at)
        VALUES
          (3481, 40, 0, 'Ultimate Spider-Man', '1', 2024, 2024, 3481, 3483, NOW()),
          (3482, 40, 1, 'Ultimate Spider-Man', '2', 2024, 2024, 3482, 3483, NOW());
        INSERT INTO threads
          (id, user_id, title, format, issues_remaining, queue_position, status,
           total_issues, reading_progress, created_at)
        VALUES
          (34830, {user_id}, 'Ultimate Spider-Man', 'comic', 18, 40, 'active',
           18, 'in_progress', NOW());
        INSERT INTO thread_external_series_mappings
          (thread_id, external_identity_id, status, evidence_source, created_at, updated_at)
        VALUES (34830, 3483, 'confirmed', 'test', NOW(), NOW());
        INSERT INTO issues (id, thread_id, issue_number, position, status, created_at)
        VALUES
          {issues_seed};
        "#
    ))
    .await
    .unwrap();

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/40/adoption-commits",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-3483",
            "revision_sha": "rev-3483"
        }),
    )
    .await;
    assert!(
        status == StatusCode::CREATED || status == StatusCode::OK,
        "{status} {body}"
    );
    assert_eq!(body["created_positions"], json!([0, 1]), "{body}");

    let rows = conn
        .query(
            "SELECT issue_number FROM issues WHERE thread_id = 34830 ORDER BY position, id",
            &[],
        )
        .await
        .unwrap();
    let actual: Vec<String> = rows.iter().map(|row| row.get::<_, String>(0)).collect();
    let mut expected: Vec<String> = vec!["1".to_string(), "2".to_string()];
    expected.extend((7..=24).map(|number| number.to_string()));
    assert_eq!(
        actual, expected,
        "CBL-adopted low issues must be natural-ordered"
    );
}

#[tokio::test]
async fn targeted_adoption_commit_route_returns_200() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
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
        &format!("/api/v2/reading-lists/1/reading-plans/{plan_id}/adoption-commits"),
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
        "/api/v2/reading-lists/1/adoption-commits",
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
        "/api/v2/reading-lists/1/reading-plans/1/adoption-commits",
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
            .uri("/api/v2/reading-lists/1/adoption-commits")
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
async fn adoption_commit_routes_require_double_submit_csrf() {
    let (state, token, _csrf, _guard) = setup().await;
    for uri in [
        "/api/v2/reading-lists/1/adoption-commits",
        "/api/v2/reading-lists/1/reading-plans/1/adoption-commits",
    ] {
        // A valid bearer token is not enough: the double-submit CSRF pair is
        // checked before authentication, so a missing pair must be rejected
        // with the same 403 envelope as every other protected mutation.
        let (status, body) = send(
            &state,
            Request::builder()
                .method("POST")
                .uri(uri)
                .header(header::AUTHORIZATION, format!("Bearer {token}"))
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(
                    json!({
                        "entry_decisions": {},
                        "series_decisions": [],
                        "series_overrides": [],
                        "content_hash": "h-mm",
                        "revision_sha": "rev-1",
                    })
                    .to_string(),
                ))
                .unwrap(),
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN, "{uri} -> {body}");
        assert_eq!(
            body["detail"], "CSRF token missing or invalid",
            "{uri} -> {body}"
        );
    }
}

#[tokio::test]
async fn targeted_adoption_commit_other_users_plan_returns_422() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
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

    // A distinct reader must not be able to reach the first reader's plan.
    let (token2, csrf2) = create_test_user(&state, "issue-identity-other").await;

    let (status, body) = post_json(
        &state,
        &token2,
        &csrf2,
        &format!("/api/v2/reading-lists/1/reading-plans/{plan_id}/adoption-commits"),
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
    _username: &str,
    _ip_suffix: usize,
) -> (String, String) {
    // Keep the helper signature stable while avoiding the flaky HTTP/bcrypt
    // registration. `create_test_user` supplies its own short unique suffix;
    // the caller's label already embeds a timestamp and would overflow the
    // 50-character `users.username` column if appended again.
    create_test_user(state, "iid2").await
}

#[tokio::test]
async fn reading_list_candidates_other_user_returns_404() {
    let (state, token, _csrf, _guard) = setup().await;
    let (status, me) = get(&state, &token, "/api/v2/auth/me").await;
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
    let (status, me2) = get(&state, &token2, "/api/v2/auth/me").await;
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
        "/api/v2/reading-lists/1/adoption-commits",
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
        "/api/v2/reading-lists/1/adoption-commits",
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
        "/api/v2/reading-lists/1/adoption-commits",
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
    // #5522: a re-commit with the same fingerprint replays the authoritative
    // stored receipt instead of recomputing the merge. Assert the whole wire
    // response is identical to the original commit (stronger than only
    // checking that no new positions were reported).
    assert_eq!(
        body2, body1,
        "re-commit must replay the authoritative commit result: first={body1} second={body2}"
    );
}

/// #5522: large CBL adoptions must commit atomically and be idempotent on
/// retry/replay. This covers the reported 228-entry shape so the 60s client
/// timeout is backed by a DB-backed regression instead of only small fixtures.
#[tokio::test]
async fn adoption_commit_large_228_entry_commit_and_receipt_replay_is_atomic() {
    let (state, token, csrf, _guard) = setup().await;
    let conn = state.pool.get().await.unwrap();

    let mut entry_rows = Vec::with_capacity(228);
    for i in 0..228i32 {
        let entry_id = 55220 + i;
        let ext_issue_id = 552200 + i;
        let issue_num = (i + 1).to_string();
        let title = format!("Alpha Flight {}", i + 1).replace('\'', "''");
        entry_rows.push(format!(
            "({entry_id}, 5522, {i}, '{title}', '{issue_num}', 1983, 1983, {ext_issue_id}, 55220, NOW())"
        ));
    }
    let mut ext_rows = Vec::with_capacity(228);
    for i in 0..228i32 {
        let ext_issue_id = 552200 + i;
        ext_rows.push(format!(
            "({ext_issue_id}, 'comicvine', 'issue', '4000-5522-{i}', '{{}}'::json, NOW(), NOW())"
        ));
    }

    conn.batch_execute(&format!(
        r#"
        INSERT INTO cbl_sources (id, repository, revision_sha, synced_at, created_at, updated_at)
        VALUES (5522, '{MIRROR_REPOSITORY}-5522', 'rev-5522', NOW(), NOW(), NOW());
        INSERT INTO cbl_source_lists
          (id, source_id, source_path, name, declared_issue_count, content_hash,
           revision_sha, active, created_at, updated_at)
        VALUES
          (5522, 5522, 'Marvel/Alpha Flight/Alpha Flight.cbl', 'Alpha Flight',
           228, 'h-5522', 'rev-5522', TRUE, NOW(), NOW());
        INSERT INTO external_identities
          (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
        VALUES
          (55220, 'comicvine', 'series', '4050-5522', '{{}}'::json, NOW(), NOW()),
          {ext_identities};
        INSERT INTO cbl_source_entries
          (id, list_id, "position", series_name, issue_number, volume_year,
           publication_year, external_issue_identity_id, external_series_identity_id, created_at)
        VALUES
          {entries};
        "#,
        ext_identities = ext_rows.join(",\n          "),
        entries = entry_rows.join(",\n          "),
    ))
    .await
    .unwrap();

    let payload = json!({
        "entry_decisions": {},
        "series_decisions": [],
        "series_overrides": [],
        "content_hash": "h-5522",
        "revision_sha": "rev-5522",
        "idempotency_key": "qa-5522-alpha-flight-commit"
    });

    let (status1, body1) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/5522/adoption-commits",
        payload.clone(),
    )
    .await;
    assert!(
        status1 == StatusCode::CREATED || status1 == StatusCode::OK,
        "{status1} {body1}"
    );
    let plan_id = body1["id"].as_i64().expect("plan id");
    let nodes1 = body1["nodes"].as_array().cloned().unwrap_or_default();
    assert_eq!(
        nodes1.len(),
        228,
        "large adoption must commit all 228 entries atomically: {body1}"
    );
    let created1 = body1["created_positions"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let reused1 = body1["reused_positions"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    assert_eq!(
        created1.len() + reused1.len(),
        228,
        "every entry must be created or reused, never partially dropped: {body1}"
    );
    assert!(
        body1["unresolved_positions"]
            .as_array()
            .is_some_and(|a| a.is_empty()),
        "fixture has no unresolved entries: {body1}"
    );

    // Replaying the same idempotency key/fingerprint must return the same
    // authoritative receipt without duplicating nodes or creating partial state.
    let (status2, body2) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/5522/adoption-commits",
        payload,
    )
    .await;
    assert!(
        status2 == StatusCode::CREATED || status2 == StatusCode::OK,
        "{status2} {body2}"
    );
    assert_eq!(body2["id"], plan_id, "replay must target same plan");
    assert_eq!(
        body2, body1,
        "large adoption replay must return authoritative receipt: first={body1} second={body2}"
    );

    let conn = state.pool.get().await.unwrap();
    let persisted_nodes: i64 = conn
        .query_one(
            "SELECT jsonb_array_length(nodes_json::jsonb)::bigint FROM continuity_plans WHERE id = $1",
            &[&(plan_id as i32)],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        persisted_nodes, 228,
        "replayed large adoption must not duplicate persisted nodes"
    );

    // #5522: the authoritative response must be stored inside the commit
    // transaction, so a lost client response replays the full result instead of
    // reconstructing a partial one from the plan alone.
    let stored_response: Option<String> = conn
        .query_opt(
            "SELECT response_json::text FROM cbl_adoption_receipts WHERE cbl_source_list_id = 5522",
            &[],
        )
        .await
        .unwrap()
        .and_then(|row| row.get(0));
    let stored_response: serde_json::Value = serde_json::from_str(
        &stored_response.expect("large commit must persist its authoritative receipt response"),
    )
    .expect("stored receipt response_json must be valid JSON");
    assert_eq!(
        stored_response, body1,
        "receipt must persist the authoritative large-commit response"
    );
}

/// MQA-CBL-003 / #3933: an untargeted "Add this reading order" must never
/// silently replace (or create an indistinguishable duplicate of) a plan the
/// reader already owns. The adopted content goes into a distinct, suffixed plan
/// and the pre-existing curated plan keeps its id and its nodes.
#[tokio::test]
async fn adoption_commit_dedupes_existing_plan_name_instead_of_replacing_it() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, me) = get(&state, &token, "/api/v2/auth/me").await;
    assert_eq!(status, StatusCode::OK, "{me}");
    let user_id = me["id"].as_i64().unwrap() as i32;

    let conn = state.pool.get().await.unwrap();
    conn.execute(
        r#"
        INSERT INTO continuity_plans
          (id, user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at)
        VALUES
          (950, $1, 'Mister Miracle 1989', 'informational',
           '[{"id":"default","name":"Default","order":0}]'::jsonb,
           '[{"id":"curated-original","node_type":"issue","ref_id":999999,"lane_id":"default","position":0,"label":"Curated original"}]'::jsonb,
           NOW(), NOW())
        "#,
        &[&user_id],
    )
    .await
    .unwrap();
    drop(conn);

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{status} {body}");
    assert_ne!(
        body["id"].as_i64(),
        Some(950),
        "adoption must create a distinct plan, not overwrite the existing one: {body}"
    );
    assert_eq!(
        body["name"], "Mister Miracle 1989 (2)",
        "a same-named existing plan must be disambiguated: {body}"
    );

    let conn = state.pool.get().await.unwrap();
    let row = conn
        .query_one(
            "SELECT name, nodes_json::text FROM continuity_plans WHERE id=950",
            &[],
        )
        .await
        .unwrap();
    assert_eq!(row.get::<_, String>(0), "Mister Miracle 1989");
    let nodes: Value = serde_json::from_str(&row.get::<_, String>(1)).unwrap();
    assert_eq!(
        nodes[0]["label"], "Curated original",
        "the existing curated plan content must survive untouched: {nodes}"
    );
}

#[tokio::test]
async fn adoption_commit_uses_next_suffix_when_dedupe_variants_exist() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, me) = get(&state, &token, "/api/v2/auth/me").await;
    assert_eq!(status, StatusCode::OK, "{me}");
    let user_id = me["id"].as_i64().unwrap() as i32;

    let conn = state.pool.get().await.unwrap();
    conn.execute(
        r#"
        INSERT INTO continuity_plans
          (id, user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at)
        VALUES
          (951, $1, 'Mister Miracle 1989', 'informational', '[]'::jsonb, '[]'::jsonb, NOW(), NOW()),
          (952, $1, 'Mister Miracle 1989 (2)', 'informational', '[]'::jsonb, '[]'::jsonb, NOW(), NOW())
        "#,
        &[&user_id],
    )
    .await
    .unwrap();
    drop(conn);

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{status} {body}");
    assert_eq!(
        body["name"], "Mister Miracle 1989 (3)",
        "every taken name variant must be skipped: {body}"
    );
}

async fn seed_orphaned_adopted_plan(state: &Arc<AppState>, user_id: i32, plan_id: i32) -> Value {
    let nodes = json!([{
        "id": "curated-original",
        "node_type": "issue",
        "ref_id": 999999,
        "lane_id": "default",
        "position": 0,
        "label": "Curated original",
        "source_cbl_placements": [{
            "source_path": MIRROR_SOURCE_PATH,
            "position": 0
        }]
    }]);
    let nodes_json = tokio_postgres::types::Json(&nodes);
    let conn = state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO continuity_plans
           (id, user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at)
         VALUES
           ($1, $2, 'Mister Miracle 1989', 'informational',
            '[{\"id\":\"default\",\"name\":\"Default\",\"order\":0}]'::jsonb,
            $3::jsonb, NOW(), NOW())",
        &[&plan_id, &user_id, &nodes_json],
    )
    .await
    .unwrap();
    // This retained provenance is exactly what deleting an authoritative
    // Reading List leaves behind: the reader returns 409 until recovery.
    conn.execute(
        "INSERT INTO reading_plan_sources (plan_id, raw_source_path, recorded_at)
         VALUES ($1, 'custom-cbl:999999', NOW())",
        &[&plan_id],
    )
    .await
    .unwrap();
    nodes
}

async fn assert_plan_nodes(state: &Arc<AppState>, plan_id: i32) -> Value {
    let conn = state.pool.get().await.unwrap();
    let nodes_text: String = conn
        .query_one(
            "SELECT nodes_json::text FROM continuity_plans WHERE id=$1",
            &[&plan_id],
        )
        .await
        .unwrap()
        .get(0);
    serde_json::from_str(&nodes_text).unwrap()
}

/// #3933's orphan re-adoption report: the source receipt must not make an
/// unusable orphaned Plan the implicit target of another successful commit.
#[tokio::test]
async fn adoption_commit_creates_fresh_plan_instead_of_reusing_orphan() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, me) = get(&state, &token, "/api/v2/auth/me").await;
    assert_eq!(status, StatusCode::OK, "{me}");
    let user_id = me["id"].as_i64().unwrap() as i32;
    let original_nodes = seed_orphaned_adopted_plan(&state, user_id, 960).await;

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;

    assert_eq!(status, StatusCode::CREATED, "{status} {body}");
    assert_ne!(body["id"], 960, "orphan must not be reused: {body}");
    assert_eq!(body["name"], "Mister Miracle 1989 (2)", "{body}");
    assert_eq!(
        assert_plan_nodes(&state, 960).await,
        original_nodes,
        "the orphaned Plan's retained history must remain untouched"
    );
}

/// The collision UI uses the targeted route when it finds the source receipt.
/// That route must apply the same orphan safeguard instead of returning 200
/// for a write that leaves the reader on a persistent 409 recovery screen.
#[tokio::test]
async fn targeted_adoption_commit_creates_fresh_plan_instead_of_updating_orphan() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, me) = get(&state, &token, "/api/v2/auth/me").await;
    assert_eq!(status, StatusCode::OK, "{me}");
    let user_id = me["id"].as_i64().unwrap() as i32;
    let original_nodes = seed_orphaned_adopted_plan(&state, user_id, 961).await;

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/reading-plans/961/adoption-commits",
        json!({
            "entry_decisions": {},
            "series_decisions": [],
            "series_overrides": [],
            "content_hash": "h-mm",
            "revision_sha": "rev-1"
        }),
    )
    .await;

    // Keep the targeted route's established 200 wire contract even though the
    // response identifies the fresh Plan that replaced the unusable target.
    assert_eq!(status, StatusCode::OK, "{status} {body}");
    assert_ne!(body["id"], 961, "orphan must not be updated: {body}");
    assert_eq!(body["name"], "Mister Miracle 1989 (2)", "{body}");
    assert_eq!(
        assert_plan_nodes(&state, 961).await,
        original_nodes,
        "the explicitly selected orphan must remain preserved for recovery"
    );
}

#[tokio::test]
async fn adoption_commit_inactive_list_returns_422() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/3/adoption-commits",
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
    let state = Arc::new(test_support::test_app_state(
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
    ));
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
            .uri("/api/v2/reading-lists/1/adoption-commits")
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

#[tokio::test]
async fn adoption_preview_and_explicit_include_cannot_restore_excluded_volumes() {
    let (state, token, csrf, _guard) = setup().await;
    let conn = state.pool.get().await.unwrap();
    let user_id: i32 = conn
        .query_one("SELECT id FROM users LIMIT 1", &[])
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO collection_exclusions (user_id, provider, external_volume_id, created_at) VALUES ($1, 'comicvine', $2, NOW())",
        &[&user_id, &VOLUME_ID],
    )
    .await
    .unwrap();
    drop(conn);

    let (status, body) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl/1/adoption-preview",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let entries = body["entries"].as_array().unwrap();
    assert!(!entries.is_empty(), "{body}");
    for entry in entries {
        assert_eq!(entry["adoption_decision"], "excluded", "{body}");
        assert_eq!(
            entry["collection_exclusion_reason"], "collection_volume_excluded",
            "{body}"
        );
    }

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        json!({
            "entry_decisions": {"1": "include", "2": "include"},
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
    assert_eq!(body["created_positions"], json!([]), "{body}");
    assert_eq!(
        body["excluded_positions"].as_array().unwrap().len(),
        2,
        "{body}"
    );
}

#[tokio::test]
async fn adoption_commit_rechecks_exclusions_added_after_preview() {
    let (state, token, csrf, _guard) = setup().await;

    let (status, preview) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl/1/adoption-preview",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preview}");
    assert!(
        preview["summary"]["missing_would_create_count"]
            .as_i64()
            .unwrap_or(0)
            >= 1
            || preview["summary"]["final_adopted_count"]
                .as_i64()
                .unwrap_or(0)
                >= 1,
        "preview should be adoptable before exclusion: {preview}"
    );

    let conn = state.pool.get().await.unwrap();
    let user_id: i32 = conn
        .query_one("SELECT id FROM users LIMIT 1", &[])
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO collection_exclusions (user_id, provider, external_volume_id, created_at) VALUES ($1, 'comicvine', $2, NOW())",
        &[&user_id, &VOLUME_ID],
    )
    .await
    .unwrap();
    drop(conn);

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
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
    assert_eq!(body["created_positions"], json!([]), "{body}");
    assert!(
        !body["excluded_positions"].as_array().unwrap().is_empty(),
        "{body}"
    );
}

// ---------------------------------------------------------------------------
// Review previews (#4842): adoption-preview, reading-graph-preview,
// series-mapping preview and project-preview, against seeded PostgreSQL rows.
// ---------------------------------------------------------------------------

async fn me_id(state: &Arc<AppState>, token: &str) -> i32 {
    let (status, me) = get(state, token, "/api/v2/auth/me").await;
    assert_eq!(status, StatusCode::OK, "{me}");
    me["id"].as_i64().unwrap() as i32
}

/// Two series ("Alpha" volume 4050-1000 with a stored start year, "Beta" volume
/// 4050-2000), each with one owned unread issue confirmed against the Comic Vine
/// issue identities that the CBL list 40 names. List order is Beta #1 then
/// Alpha #1, so strict order makes Alpha wait for Beta: one genuine overlap.
/// Ids: threads 940/941, issues 9401 (Alpha #1) / 9411 (Beta #1).
async fn seed_overlap_scenario(state: &Arc<AppState>, user_id: i32) {
    let conn = state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO cbl_sources (id, repository, revision_sha, synced_at, created_at, updated_at)
        VALUES (40, '{MIRROR_REPOSITORY}-ov', 'rev-40', NOW(), NOW(), NOW());
        INSERT INTO cbl_source_lists
          (id, source_id, source_path, name, declared_issue_count, content_hash,
           revision_sha, active, created_at, updated_at)
        VALUES (40, 40, 'DC/Overlap/Overlap.cbl', 'Overlap Event', 3, 'h-ov', 'rev-40', TRUE, NOW(), NOW());
        INSERT INTO external_identities
          (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
        VALUES
          (40, 'comicvine', 'issue', '4000-beta1', '{{}}'::json, NOW(), NOW()),
          (41, 'comicvine', 'issue', '4000-alpha1', '{{}}'::json, NOW(), NOW()),
          (42, 'comicvine', 'series', '4050-1000', '{{"start_year": 1999}}'::json, NOW(), NOW()),
          (43, 'comicvine', 'series', '4050-2000', '{{}}'::json, NOW(), NOW()),
          (44, 'comicvine', 'issue', '4000-ghost', '{{}}'::json, NOW(), NOW());
        INSERT INTO cbl_source_entries
          (id, list_id, "position", series_name, issue_number, volume_year,
           publication_year, external_issue_identity_id, external_series_identity_id, created_at)
        VALUES
          (40, 40, 1, 'Beta', '1', 2001, 2001, 40, 43, NOW()),
          (41, 40, 2, 'Alpha', '1', NULL, 1999, 41, 42, NOW()),
          (42, 40, 3, 'Ghost', '1', 2010, 2010, 44, NULL, NOW());
        INSERT INTO threads (id, user_id, title, format, issues_remaining, queue_position, status, total_issues, reading_progress, created_at)
        VALUES
          (940, {user_id}, 'Alpha', 'comic', 1, 90, 'active', 1, 'in_progress', NOW()),
          (941, {user_id}, 'Beta', 'comic', 1, 91, 'active', 1, 'in_progress', NOW());
        INSERT INTO issues (id, thread_id, issue_number, position, status, created_at)
        VALUES (9401, 940, '1', 1, 'unread', NOW()), (9411, 941, '1', 1, 'unread', NOW());
        INSERT INTO thread_external_series_mappings (thread_id, external_identity_id, status, evidence_source, created_at, updated_at)
        VALUES (940, 42, 'confirmed', 'test', NOW(), NOW()), (941, 43, 'confirmed', 'test', NOW(), NOW());
        INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, evidence_source, evidence_json, created_at, updated_at)
        VALUES (9401, 41, 'confirmed', 'test', '{{}}'::json, NOW(), NOW()),
               (9411, 40, 'confirmed', 'test', '{{}}'::json, NOW(), NOW());
        "#
    ))
    .await
    .unwrap();
}

async fn raw_request(
    state: &Arc<AppState>,
    method: &str,
    uri: &str,
    token: Option<&str>,
    csrf: &str,
    body: &str,
) -> (StatusCode, Value) {
    let mut builder = Request::builder().method(method).uri(uri);
    if let Some(token) = token {
        builder = builder.header(header::AUTHORIZATION, format!("Bearer {token}"));
    }
    send(
        state,
        builder
            .header(header::CONTENT_TYPE, "application/json")
            .header("x-csrf-token", csrf)
            .header(header::COOKIE, format!("csrf_token={csrf}"))
            .body(Body::from(body.to_string()))
            .unwrap(),
    )
    .await
}

fn validation_failed() -> Value {
    json!({"detail": "Validation failed"})
}

#[tokio::test]
async fn adoption_preview_matches_adoption_plan_with_no_decisions() {
    let (state, token, csrf, _guard) = setup().await;
    let user_id = me_id(&state, &token).await;
    seed_overlap_scenario(&state, user_id).await;

    let (status, preview) = get(
        &state,
        &token,
        "/api/v1/issue-identity/cbl/40/adoption-preview",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preview}");
    let (status, plan) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/issue-identity/cbl/40/adoption-plan",
        json!({"series_decisions": {}, "entry_decisions": {}}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{plan}");
    assert_eq!(preview, plan, "preview is the plan with empty decisions");

    assert_eq!(preview["source"]["source_list_id"], 40);
    assert_eq!(preview["source"]["content_hash"], "h-ov");
    assert_eq!(preview["total_positions"], 3);
    let entries = preview["entries"].as_array().unwrap();
    assert_eq!(entries[0]["resolved_issue_id"], 9411, "{preview}");
    assert_eq!(entries[0]["canonical_issue_id"], 9411);
    assert_eq!(entries[0]["read_status"], "unread");
    assert_eq!(entries[0]["adoption_decision"], "included_existing");
    assert_eq!(entries[0]["comicvine_series_id"], "4050-2000");
    assert_eq!(entries[1]["resolved_issue_id"], 9401);
    assert_eq!(entries[2]["adoption_decision"], "would_create_missing");
    assert_eq!(
        preview["summary"]["reused_existing_positions"],
        json!([1, 2])
    );
    assert_eq!(preview["summary"]["final_adopted_order"], json!([1, 2, 3]));
}

#[tokio::test]
async fn adoption_preview_is_owner_scoped_and_read_only() {
    let (state, token, _csrf, _guard) = setup().await;
    let user_id = me_id(&state, &token).await;
    seed_overlap_scenario(&state, user_id).await;
    let (other_token, _) = create_test_user(&state, "other-reader").await;

    let (status, body) = get(
        &state,
        &other_token,
        "/api/v1/issue-identity/cbl/40/adoption-preview",
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    for entry in body["entries"].as_array().unwrap() {
        assert!(
            entry["resolved_issue_id"].is_null(),
            "another reader's issues must never resolve: {body}"
        );
    }
    let conn = state.pool.get().await.unwrap();
    let issues: i64 = conn
        .query_one("SELECT count(*) FROM issues", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(issues, 2, "preview must not create issues");
}

#[tokio::test]
async fn adoption_preview_errors_match_production() {
    let (state, token, _csrf, _guard) = setup().await;
    let (status, _) = get(&state, "", "/api/v1/issue-identity/cbl/1/adoption-preview").await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    // Inactive (3), missing, and beyond-int4 lists are one 404.
    for id in ["3", "999", "99999999999"] {
        let uri = format!("/api/v1/issue-identity/cbl/{id}/adoption-preview");
        let (status, body) = get(&state, &token, &uri).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{id}: {body}");
    }
    for bad in ["abc", "1.5"] {
        let uri = format!("/api/v1/issue-identity/cbl/{bad}/adoption-preview");
        let (status, body) = get(&state, &token, &uri).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{bad}");
        assert_eq!(body, validation_failed(), "{bad}");
    }
}

#[tokio::test]
async fn reading_graph_preview_projects_overlap_with_both_choice_effects() {
    let (state, token, csrf, _guard) = setup().await;
    let user_id = me_id(&state, &token).await;
    seed_overlap_scenario(&state, user_id).await;
    let uri = "/api/v1/issue-identity/cbl/40/reading-graph-preview";

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        uri,
        json!({"included_positions": [1, 2]}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["source_list_id"], 40);
    assert_eq!(body["content_hash"], "h-ov");
    assert_eq!(body["revision_sha"], "rev-40");
    assert_eq!(body["cycle_errors"], json!([]));
    // Real owned issue ids (never source positions): Beta rolls, Alpha waits.
    assert_eq!(body["rollable_issue_ids"], json!([9411]), "{body}");
    assert_eq!(body["waiting_issue_ids"], json!([9401]), "{body}");

    let series = body["series"].as_array().unwrap();
    assert_eq!(series.len(), 2, "{body}");
    assert_eq!(series[0]["series_name"], "Alpha");
    assert_eq!(series[0]["comicvine_volume_id"], "comicvine:1000");
    assert_eq!(series[0]["year"], 1999);
    assert_eq!(series[0]["state"], "waits");
    assert_eq!(series[0]["waits_for_issue_ids"], json!([9411]));
    assert_eq!(series[1]["series_name"], "Beta");
    assert_eq!(series[1]["year"], 2001);
    assert_eq!(series[1]["state"], "continues");
    assert_eq!(series[1]["rollable_count"], 1);

    let issues = body["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 2);
    let alpha = issues.iter().find(|i| i["issue_id"] == 9401).unwrap();
    assert_eq!(alpha["series_name"], "Alpha");
    assert_eq!(alpha["comicvine_volume_id"], "comicvine:1000");
    assert_eq!(alpha["blockers"][0]["kind"], "strict_order");
    assert_eq!(alpha["blockers"][0]["waiting_on_issue_ids"], json!([9411]));
    assert_eq!(
        alpha["blockers"][0]["explanation"],
        "Strict order in Overlap Event: waiting on Beta #1"
    );

    let overlaps = body["overlaps"].as_array().unwrap();
    assert_eq!(overlaps.len(), 1, "{body}");
    let overlap = &overlaps[0];
    assert!(overlap["overlap_id"]
        .as_str()
        .unwrap()
        .starts_with("overlap-"));
    assert_eq!(
        overlap["continuing_series"]["comicvine_volume_id"],
        "comicvine:1000"
    );
    assert_eq!(
        overlap["waiting_series"]["comicvine_volume_id"],
        "comicvine:2000"
    );
    assert_eq!(
        overlap["question"],
        "Should Alpha continue while Beta waits?"
    );
    assert_eq!(overlap["blocked_issue_ids"], json!([9401]));
    assert!(overlap["selected_choice"].is_null());
    assert_eq!(overlap["choices"][0]["choice"], "continue_series");
    assert_eq!(
        overlap["choices"][0]["rollable_issue_ids"],
        json!([9401, 9411])
    );
    assert_eq!(overlap["choices"][0]["waiting_issue_ids"], json!([]));
    assert_eq!(overlap["choices"][1]["choice"], "protect_order");
    assert_eq!(overlap["choices"][1]["rollable_issue_ids"], json!([9411]));
    assert_eq!(overlap["choices"][1]["waiting_issue_ids"], json!([9401]));

    // Answering the overlap relaxes only that pair and echoes the selection.
    let overlap_id = overlap["overlap_id"].clone();
    let (status, answered) = post_json(
        &state,
        &token,
        &csrf,
        uri,
        json!({
            "included_positions": [1, 2],
            "overlap_choices": [{"overlap_id": overlap_id, "choice": "continue_series"}]
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{answered}");
    assert_eq!(
        answered["overlaps"][0]["selected_choice"],
        "continue_series"
    );
    assert_eq!(answered["rollable_issue_ids"], json!([9401, 9411]));
    assert_eq!(answered["waiting_issue_ids"], json!([]));

    // Read-only: no list, entry, or decision was written.
    let conn = state.pool.get().await.unwrap();
    for table in [
        "custom_cbl_lists",
        "custom_cbl_entries",
        "custom_cbl_overlap_decisions",
    ] {
        let count: i64 = conn
            .query_one(&format!("SELECT count(*) FROM {table}"), &[])
            .await
            .unwrap()
            .get(0);
        assert_eq!(count, 0, "{table}");
    }
}

#[tokio::test]
async fn reading_graph_preview_reports_cycle_against_existing_list() {
    let (state, token, csrf, _guard) = setup().await;
    let user_id = me_id(&state, &token).await;
    seed_overlap_scenario(&state, user_id).await;
    let conn = state.pool.get().await.unwrap();
    // An existing strict list orders Alpha before Beta; the proposed list orders
    // Beta before Alpha, so the combined constraint graph has a cycle.
    conn.batch_execute(&format!(
        r#"
        INSERT INTO custom_cbl_lists (id, user_id, name, mode, created_at, updated_at)
        VALUES (500, {user_id}, 'Alpha first', 'strict', NOW(), NOW());
        INSERT INTO custom_cbl_entries (list_id, issue_id, "position", created_at)
        VALUES (500, 9401, 1, NOW()), (500, 9411, 2, NOW());
        "#
    ))
    .await
    .unwrap();
    drop(conn);
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/issue-identity/cbl/40/reading-graph-preview",
        json!({"included_positions": [1, 2]}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let errors = body["cycle_errors"].as_array().unwrap();
    assert_eq!(errors.len(), 1, "{body}");
    assert_eq!(errors[0]["code"], "reading_constraint_cycle");
    let message = errors[0]["message"].as_str().unwrap();
    assert!(
        message.starts_with("Reading constraint cycle: "),
        "{message}"
    );
    assert!(
        message.contains("Alpha #1") && message.contains("Beta #1"),
        "{message}"
    );
}

#[tokio::test]
async fn reading_graph_preview_errors_match_production() {
    let (state, token, csrf, _guard) = setup().await;
    let user_id = me_id(&state, &token).await;
    seed_overlap_scenario(&state, user_id).await;
    let uri = "/api/v1/issue-identity/cbl/40/reading-graph-preview";

    let (status, _) = raw_request(&state, "POST", uri, None, &csrf, "{}").await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        uri,
        json!({"included_positions": [9]}),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["detail"]["code"], "unknown_source_position", "{body}");
    assert_eq!(
        body["detail"]["message"],
        "Source positions are not part of list 40: [9]"
    );

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        uri,
        json!({"included_positions": [3]}),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        body["detail"]["code"], "unresolved_source_position",
        "{body}"
    );

    let bogus = json!({"included_positions": [1, 2], "overlap_choices": [{"overlap_id": "overlap-nope", "choice": "protect_order"}]});
    let (status, body) = post_json(&state, &token, &csrf, uri, bogus).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["detail"]["code"], "unknown_overlap_choice", "{body}");

    let (status, first) = post_json(
        &state,
        &token,
        &csrf,
        uri,
        json!({"included_positions": [1, 2]}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let overlap_id = first["overlaps"][0]["overlap_id"].clone();
    let twice = json!({"included_positions": [1, 2], "overlap_choices": [
        {"overlap_id": overlap_id, "choice": "protect_order"},
        {"overlap_id": overlap_id, "choice": "continue_series"}]});
    let (status, body) = post_json(&state, &token, &csrf, uri, twice).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["detail"]["code"], "duplicate_overlap_choice", "{body}");

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        uri,
        json!({"included_positions": [1, 2], "target_list_id": 777}),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"]["code"], "reading_list_not_found", "{body}");

    for list in ["3", "999"] {
        let uri = format!("/api/v1/issue-identity/cbl/{list}/reading-graph-preview");
        let (status, body) = post_json(&state, &token, &csrf, &uri, json!({})).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{list}");
        assert_eq!(body["detail"]["code"], "cbl_source_not_found", "{body}");
    }

    for bad in [
        json!({"included_positions": [0]}),
        json!({"included_positions": ["x"]}),
        json!({"included_positions": 3}),
        json!({"target_list_id": 0}),
        json!({"overlap_choices": [{"overlap_id": "", "choice": "protect_order"}]}),
        json!({"overlap_choices": [{"overlap_id": "a", "choice": "other"}]}),
    ] {
        let (status, body) = post_json(&state, &token, &csrf, uri, bad.clone()).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{bad}");
        assert_eq!(body, validation_failed(), "{bad}");
    }
    let (status, body) = raw_request(&state, "POST", uri, Some(&token), &csrf, "not json").await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body, validation_failed());
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/issue-identity/cbl/abc/reading-graph-preview",
        json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body, validation_failed());
}

#[tokio::test]
async fn reading_graph_preview_cannot_see_another_readers_issues() {
    let (state, token, csrf, _guard) = setup().await;
    let user_id = me_id(&state, &token).await;
    seed_overlap_scenario(&state, user_id).await;
    let (other_token, other_csrf) = create_test_user(&state, "other-reader").await;
    let (status, body) = post_json(
        &state,
        &other_token,
        &other_csrf,
        "/api/v1/issue-identity/cbl/40/reading-graph-preview",
        json!({"included_positions": [1, 2]}),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"]["code"], "unresolved_source_position");
    // The owner is unaffected.
    let (status, _) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/issue-identity/cbl/40/reading-graph-preview",
        json!({"included_positions": [1, 2]}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
}

#[tokio::test]
async fn series_mapping_preview_validation_auth_and_unavailable_scope() {
    let (state, token, csrf, _guard) = setup().await;
    let user_id = me_id(&state, &token).await;
    seed_overlap_scenario(&state, user_id).await;
    let uri = "/api/v1/catalog/series-mappings/preview";

    let (status, _) = raw_request(&state, "POST", uri, None, &csrf, "{}").await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);

    for bad in [
        json!({"origin_issue_id": 0, "provider": "comicvine", "provider_series_external_id": "4050-1"}),
        json!({"origin_issue_id": 1, "provider": "nope", "provider_series_external_id": "4050-1"}),
        json!({"origin_issue_id": 1, "provider": "comicvine", "provider_series_external_id": ""}),
        json!({"origin_issue_id": 1, "provider": "comicvine", "provider_series_external_id": "x", "scope_mode": "bad"}),
        json!({"provider": "comicvine", "provider_series_external_id": "x"}),
    ] {
        let (status, body) = post_json(&state, &token, &csrf, uri, bad.clone()).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{bad}");
        assert_eq!(body, validation_failed(), "{bad}");
    }

    // An origin issue the reader does not own yields the unavailable scope, no
    // token, and never reveals another reader's rows.
    let (other_token, other_csrf) = create_test_user(&state, "other-reader").await;
    let (status, body) = post_json(
        &state,
        &other_token,
        &other_csrf,
        uri,
        json!({"origin_issue_id": 9401, "provider": "comicvine", "provider_series_external_id": "4050-1000"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["scope"]["status"], "unavailable", "{body}");
    assert!(body["preview_token"].is_null(), "{body}");
    assert_eq!(body["rows"], json!([]));
    assert_eq!(body["counts"]["safe_exact_match"], 0);

    // The owner gets an available, read-only scope and a signed token.
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        uri,
        json!({"origin_issue_id": 9401, "provider": "comicvine", "provider_series_external_id": "4050-1000"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["scope"]["origin_issue_id"], 9401);
    assert!(body["issued_at"].is_number());
    let conn = state.pool.get().await.unwrap();
    let mappings: i64 = conn
        .query_one("SELECT count(*) FROM thread_external_series_mappings", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(mappings, 2, "preview must not write mappings");
}

/// #5716: the canonical v2 custom method has the same read-only wire contract
/// as the retained v1 alias. Exercise the mounted HTTP route, not the handler
/// directly, so an ingress or path regression is caught here too.
#[tokio::test]
async fn series_mappings_preview_v2_http_auth_validation_and_read_only_scope() {
    let (state, token, csrf, _guard) = setup().await;
    let user_id = me_id(&state, &token).await;
    seed_overlap_scenario(&state, user_id).await;
    let uri = "/api/v2/seriesMappings:preview";

    let (status, _) = raw_request(&state, "POST", uri, None, &csrf, "{}").await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);

    for bad in [
        json!({"origin_issue_id": 0, "provider": "comicvine", "provider_series_external_id": "4050-1"}),
        json!({"origin_issue_id": 1, "provider": "nope", "provider_series_external_id": "4050-1"}),
        json!({"origin_issue_id": 1, "provider": "comicvine", "provider_series_external_id": ""}),
        json!({"origin_issue_id": 1, "provider": "comicvine", "provider_series_external_id": "x", "scope_mode": "bad"}),
        json!({"provider": "comicvine", "provider_series_external_id": "x"}),
    ] {
        let (status, body) = post_json(&state, &token, &csrf, uri, bad.clone()).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{bad}");
        assert_eq!(body, validation_failed(), "{bad}");
    }

    // Cross-reader preview stays unavailable and never reveals other rows.
    let (other_token, other_csrf) = create_test_user(&state, "v2-preview-other-reader").await;
    let (status, body) = post_json(
        &state,
        &other_token,
        &other_csrf,
        uri,
        json!({"origin_issue_id": 9401, "provider": "comicvine", "provider_series_external_id": "4050-1000"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["scope"]["status"], "unavailable", "{body}");
    assert!(body["preview_token"].is_null(), "{body}");
    assert_eq!(body["rows"], json!([]));

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        uri,
        json!({"origin_issue_id": 9401, "provider": "comicvine", "provider_series_external_id": "4050-1000"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["scope"]["origin_issue_id"], 9401);
    assert!(body["issued_at"].is_number());

    let conn = state.pool.get().await.unwrap();
    let mappings: i64 = conn
        .query_one("SELECT count(*) FROM thread_external_series_mappings", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(mappings, 2, "v2 preview must not write mappings");
    let receipts: i64 = conn
        .query_one("SELECT count(*) FROM catalog_commit_receipts", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(receipts, 0, "v2 preview must not write commit receipts");
}

// ---------------------------------------------------------------------------
// #5170: safe exact-match preview -> v2 commit round trip on the all-Rust path.
//
// The earlier Python-minted token vectors in `catalog_commit::tests` prove the
// historical digest fix (#5340). These tests exercise the *current* contract:
// a stateless v2 preview mints the token and the same v2 commit endpoint
// revalidates it. The provider roster is an installed fixture, so no test ever
// reaches ComicVine and the whole plan is deterministic.
// ---------------------------------------------------------------------------

const NTT_SERIES_TITLE: &str = "New Teen Titans (1980)";

struct SafeSeriesFixture {
    volume_id: &'static str,
    thread_id: i32,
    first_issue_id: i32,
}

impl SafeSeriesFixture {
    fn new(volume_id: &'static str, thread_id: i32, first_issue_id: i32) -> Self {
        Self {
            volume_id,
            thread_id,
            first_issue_id,
        }
    }

    fn safe_issue_ids(&self) -> Vec<i32> {
        (self.first_issue_id..self.first_issue_id + 33).collect()
    }

    fn safe_row_ids(&self) -> Vec<String> {
        self.safe_issue_ids()
            .into_iter()
            .map(|id| format!("issue:{id}"))
            .collect()
    }

    fn unsafe_issue_id(&self) -> i32 {
        self.first_issue_id + 33
    }

    fn origin_issue_id(&self) -> i32 {
        self.first_issue_id
    }

    fn series_info(&self) -> Value {
        json!({
            "id": self.volume_id,
            "name": NTT_SERIES_TITLE,
            "publisher": "DC Comics",
            "start_year": 1980,
            "count_of_issues": 35,
            "site_detail_url": format!("https://comicvine.gamespot.com/volume/{}", self.volume_id),
            "image": null,
        })
    }

    /// The 33 exact provider matches plus two inventory-only issues (#34/#35).
    /// Both classes must remain unmapped when only the safe rows are approved.
    fn roster(&self) -> Vec<Value> {
        let mut roster = Vec::new();
        for number in 1..=33_i32 {
            let provider_id = 600_000 + number;
            roster.push(json!({
                "issue_id": provider_id,
                "issue_number": number.to_string(),
                "title": format!("Teen Titans #{number}"),
                "thread_id": null,
                "thread_title": null,
                "current_mapping_status": "unresolved",
                "provider": "comicvine",
                "external_id": provider_id.to_string(),
                "classification": "unresolved",
                "_roster_only": true,
                "_provider_metadata": {
                    "name": format!("Teen Titans #{number}"),
                    "issue_number": number.to_string(),
                    "volume": {"name": NTT_SERIES_TITLE},
                },
            }));
        }
        for (number, provider_id) in [(34, 600_034_i32), (35, 600_035_i32)] {
            roster.push(json!({
                "issue_id": provider_id,
                "issue_number": number.to_string(),
                "title": format!("Teen Titans #{number}"),
                "thread_id": null,
                "thread_title": null,
                "current_mapping_status": "unresolved",
                "provider": "comicvine",
                "external_id": provider_id.to_string(),
                "classification": "unresolved",
                "_roster_only": true,
                "_provider_metadata": {
                    "name": format!("Teen Titans #{number}"),
                    "issue_number": number.to_string(),
                    "volume": {"name": NTT_SERIES_TITLE},
                },
            }));
        }
        roster
    }

    fn install(&self) {
        test_support::install_test_volume_roster(self.volume_id, self.series_info(), self.roster());
    }

    fn clear(&self) {
        test_support::clear_test_volume_roster(self.volume_id);
    }

    async fn seed(&self, state: &Arc<AppState>, user_id: i32) {
        let conn = state.pool.get().await.unwrap();
        conn.execute(
            "INSERT INTO threads
             (id, user_id, title, format, issues_remaining, queue_position, status,
              total_issues, reading_progress, created_at)
             VALUES ($1, $2, $3, 'comic', 0, 1, 'active', 34, 'unread', NOW())",
            &[&self.thread_id, &user_id, &NTT_SERIES_TITLE],
        )
        .await
        .unwrap();
        for offset in 0..33_i32 {
            conn.execute(
                "INSERT INTO issues (id, thread_id, issue_number, position, status, created_at)
                 VALUES ($1, $2, $3, $4, 'unread', NOW())",
                &[
                    &(self.first_issue_id + offset),
                    &self.thread_id,
                    &(offset + 1).to_string(),
                    &(offset + 1),
                ],
            )
            .await
            .unwrap();
        }
        // An owned "Annual 1" classifies excluded_special: it must never be
        // bulk-approved, even when the reader sends its row id in the commit.
        conn.execute(
            "INSERT INTO issues (id, thread_id, issue_number, position, status, created_at)
             VALUES ($1, $2, 'Annual 1', 34, 'unread', NOW())",
            &[&self.unsafe_issue_id(), &self.thread_id],
        )
        .await
        .unwrap();
        // `setup()` seeds catalog identities with explicit ids and resets every
        // sequence to 1, so advance the identity sequence the way real inserts
        // would have. Otherwise the commit's first default-id insert collides
        // with the seeded row and fails with an unrelated 23505.
        conn.execute(
            "SELECT setval(pg_get_serial_sequence('external_identities', 'id'),
                           GREATEST((SELECT COALESCE(MAX(id), 1) FROM external_identities), 1))",
            &[],
        )
        .await
        .unwrap();
    }

    fn preview_request(&self) -> Value {
        json!({
            "origin_issue_id": self.origin_issue_id(),
            "provider": "comicvine",
            "provider_series_external_id": self.volume_id,
            "scope_mode": "queue_thread_bootstrap",
        })
    }

    fn commit_request(&self, token: &str, key: &str, approved_row_ids: Vec<String>) -> Value {
        json!({
            "preview_token": token,
            "idempotency_key": key,
            "approved_row_ids": approved_row_ids,
        })
    }

    async fn mapping_count(&self, state: &Arc<AppState>) -> i64 {
        let conn = state.pool.get().await.unwrap();
        conn.query_one(
            "SELECT count(*) FROM issue_external_identity_mappings m
             JOIN issues i ON i.id = m.issue_id
             WHERE i.thread_id = $1",
            &[&self.thread_id],
        )
        .await
        .unwrap()
        .get(0)
    }

    async fn receipt_count(&self, state: &Arc<AppState>) -> i64 {
        let conn = state.pool.get().await.unwrap();
        conn.query_one("SELECT count(*) FROM catalog_commit_receipts", &[])
            .await
            .unwrap()
            .get(0)
    }
}

const PREVIEW_URI: &str = "/api/v2/seriesMappings:preview";
const COMMIT_URI: &str = "/api/v2/series-mapping-commits";

#[tokio::test]
async fn series_mapping_v2_safe_preview_commits_reloads_and_replays() {
    let (state, token, csrf, _guard) = setup().await;
    let user_id = me_id(&state, &token).await;
    let fixture = SafeSeriesFixture::new("4050-5170", 51700, 517001);
    fixture.install();
    fixture.seed(&state, user_id).await;

    // Real v2 preview: stateless, all 33 safe rows selected by default.
    let (status, preview) = post_json(
        &state,
        &token,
        &csrf,
        PREVIEW_URI,
        fixture.preview_request(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preview}");
    assert_eq!(preview["scope"]["status"], "available", "{preview}");
    assert_eq!(preview["counts"]["safe_exact_match"], 33, "{preview}");
    let preview_token = preview["preview_token"]
        .as_str()
        .expect("available scope mints a preview token")
        .to_string();
    let approved = fixture.safe_row_ids();
    let previewed_safe_rows: Vec<&Value> = preview["rows"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|row| row["classification"] == "safe_exact_match")
        .collect();
    assert_eq!(previewed_safe_rows.len(), 33, "{preview}");
    for row in previewed_safe_rows {
        assert!(approved.contains(&row["row_id"].as_str().unwrap().to_string()));
    }
    assert_eq!(
        fixture.mapping_count(&state).await,
        0,
        "preview must not write"
    );
    assert_eq!(
        fixture.receipt_count(&state).await,
        0,
        "preview must not write"
    );

    // Real v2 commit with every safe row approved.
    let key = "qa-5170-safe-ntt";
    let (status, committed) = post_json(
        &state,
        &token,
        &csrf,
        COMMIT_URI,
        fixture.commit_request(&preview_token, key, approved.clone()),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{committed}");
    assert_eq!(
        committed["confirmed_issue_ids"],
        json!(fixture.safe_issue_ids()),
        "{committed}"
    );
    assert_eq!(
        committed["needs_review_issue_ids"],
        json!([fixture.unsafe_issue_id()]),
        "the excluded special issue stays for review: {committed}"
    );
    assert_eq!(
        committed["series_mapping"]["status"], "confirmed",
        "{committed}"
    );
    assert_eq!(
        committed["series_mapping"]["evidence_source"], "user_series_confirmation",
        "{committed}"
    );
    assert_eq!(fixture.mapping_count(&state).await, 33);
    assert_eq!(fixture.receipt_count(&state).await, 1);

    // Reload: a fresh preview request and direct reads both see 33 confirmations,
    // while the unsafe row is still unmapped and the series link survives.
    let (status, reloaded) = post_json(
        &state,
        &token,
        &csrf,
        PREVIEW_URI,
        fixture.preview_request(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{reloaded}");
    assert_eq!(reloaded["counts"]["already_confirmed"], 33, "{reloaded}");
    assert_eq!(reloaded["counts"]["safe_exact_match"], 0, "{reloaded}");
    let conn = state.pool.get().await.unwrap();
    let confirmed: i64 = conn
        .query_one(
            "SELECT count(*) FROM issue_external_identity_mappings m
             JOIN issues i ON i.id = m.issue_id
             WHERE i.thread_id = $1 AND m.status = 'confirmed'",
            &[&fixture.thread_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(confirmed, 33);
    let unsafe_mapped: bool = conn
        .query_one(
            "SELECT EXISTS (SELECT 1 FROM issue_external_identity_mappings WHERE issue_id = $1)",
            &[&fixture.unsafe_issue_id()],
        )
        .await
        .unwrap()
        .get(0);
    assert!(!unsafe_mapped, "ambiguous/special rows stay unmapped");
    let series_link: bool = conn
        .query_one(
            "SELECT EXISTS (
               SELECT 1 FROM thread_external_series_mappings tsm
               JOIN external_identities e ON e.id = tsm.external_identity_id
               WHERE tsm.thread_id = $1 AND tsm.status = 'confirmed'
                 AND e.entity_type = 'series' AND e.external_id = $2
             )",
            &[&fixture.thread_id, &fixture.volume_id],
        )
        .await
        .unwrap()
        .get(0);
    assert!(
        series_link,
        "the confirmed thread-series link survives reload"
    );

    // Same key and same selection replays the receipt: no extra rows.
    let (status, replay) = post_json(
        &state,
        &token,
        &csrf,
        COMMIT_URI,
        fixture.commit_request(&preview_token, key, approved.clone()),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{replay}");
    assert_eq!(replay, committed, "replay returns the same logical result");
    assert_eq!(fixture.mapping_count(&state).await, 33);
    assert_eq!(fixture.receipt_count(&state).await, 1);

    // Same key with a changed material selection conflicts and keeps the receipt.
    let mut shortened = approved.clone();
    shortened.pop();
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        COMMIT_URI,
        fixture.commit_request(&preview_token, key, shortened),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(body["detail"], "idempotency_conflict", "{body}");

    // A previously valid token is stale once the plan has been committed: a
    // fresh key cannot bypass revalidation, and no partial mutation occurs.
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        COMMIT_URI,
        fixture.commit_request(
            &preview_token,
            "qa-5170-stale-after-commit",
            approved.clone(),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(body["detail"], "preview_stale", "{body}");
    assert_eq!(fixture.mapping_count(&state).await, 33);
    assert_eq!(fixture.receipt_count(&state).await, 1);

    fixture.clear();
}

#[tokio::test]
async fn series_mapping_v2_commit_rejects_unsafe_stale_and_foreign_requests_without_writes() {
    let (state, token, csrf, _guard) = setup().await;
    let user_id = me_id(&state, &token).await;
    let fixture = SafeSeriesFixture::new("4050-5171", 51710, 517101);
    fixture.install();
    fixture.seed(&state, user_id).await;

    let (status, preview) = post_json(
        &state,
        &token,
        &csrf,
        PREVIEW_URI,
        fixture.preview_request(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preview}");
    let preview_token = preview["preview_token"]
        .as_str()
        .expect("available scope mints a preview token")
        .to_string();
    let approved = fixture.safe_row_ids();

    // Approving the excluded_special row alongside the safe rows is refused
    // before any write. Unsafe rows are never bulk-confirmed.
    let mut unsafe_selection = approved.clone();
    unsafe_selection.push(format!("issue:{}", fixture.unsafe_issue_id()));
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        COMMIT_URI,
        fixture.commit_request(&preview_token, "qa-5170-unsafe", unsafe_selection),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"], "invalid_approved_row", "{body}");

    // Provider inventory rows are not owned issues and cannot be approved.
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        COMMIT_URI,
        fixture.commit_request(
            &preview_token,
            "qa-5170-inventory",
            vec!["roster:600034".to_string()],
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    assert_eq!(body["detail"], "invalid_approved_row", "{body}");

    // A tampered token fails signature verification.
    let tampered = preview_token.replace("4050-5171", "4050-5172");
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        COMMIT_URI,
        fixture.commit_request(&tampered, "qa-5170-tampered", approved.clone()),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED, "{body}");
    assert_eq!(body["detail"], "invalid_preview_token", "{body}");

    // Cross-owner commit: the token is bound to the reader who previewed.
    let (other_token, other_csrf) = create_test_user(&state, "ntt-other-owner").await;
    let (status, body) = post_json(
        &state,
        &other_token,
        &other_csrf,
        COMMIT_URI,
        fixture.commit_request(&preview_token, "qa-5170-cross-owner", approved.clone()),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED, "{body}");
    assert_eq!(body["detail"], "invalid_preview_token", "{body}");
    let (status, other_preview) = post_json(
        &state,
        &other_token,
        &other_csrf,
        PREVIEW_URI,
        fixture.preview_request(),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{other_preview}");
    assert_eq!(
        other_preview["scope"]["status"], "unavailable",
        "{other_preview}"
    );
    assert!(other_preview["preview_token"].is_null(), "{other_preview}");

    // Changing the underlying plan after preview makes the token stale. The
    // commit is rejected with zero partial mutations, even with a fresh key.
    let conn = state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO issues (id, thread_id, issue_number, position, status, created_at)
         VALUES (517199, 51710, '36', 35, 'unread', NOW())",
        &[],
    )
    .await
    .unwrap();
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        COMMIT_URI,
        fixture.commit_request(&preview_token, "qa-5170-stale-empty", approved.clone()),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(body["detail"], "preview_stale", "{body}");

    assert_eq!(
        fixture.mapping_count(&state).await,
        0,
        "no partial mutation"
    );
    assert_eq!(
        fixture.receipt_count(&state).await,
        0,
        "no receipt on refusal"
    );
    fixture.clear();
}

#[tokio::test]
async fn project_preview_projects_plan_and_enforces_ownership() {
    let (state, token, csrf, _guard) = setup().await;
    let user_id = me_id(&state, &token).await;
    seed_overlap_scenario(&state, user_id).await;
    let conn = state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO continuity_plans (id, user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
        VALUES
          (700, {user_id}, 'Event plan', 'informational',
           '[{{"id":"n1","node_type":"thread","ref_id":941,"lane_id":"main","position":0}},
             {{"id":"n2","node_type":"thread","ref_id":940,"lane_id":"main","position":1}}]'::json,
           '[{{"id":"main","order":0}}]'::json, NOW(), NOW()),
          (701, {user_id}, 'Bad plan', 'informational',
           '[{{"id":"n1","node_type":"thread","ref_id":941,"lane_id":"main","position":0}},
             {{"id":"n2","node_type":"thread","ref_id":941,"lane_id":"main","position":1}},
             {{"id":"n3","node_type":"series","ref_id":5,"lane_id":"main","position":2}}]'::json,
           '[{{"id":"main","order":0}}]'::json, NOW(), NOW());
        INSERT INTO reading_orders (id, name, user_id) VALUES (800, 'My order', {user_id});
        INSERT INTO reading_order_items (reading_order_id, thread_id, "position") VALUES (800, 940, 1);
        "#
    ))
    .await
    .unwrap();
    drop(conn);
    let uri = "/api/v1/continuity-plans/700/reading-orders/project-preview";

    let (status, _) = raw_request(&state, "POST", uri, None, &csrf, "{}").await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);

    let (status, body) =
        post_json(&state, &token, &csrf, uri, json!({"reading_order_id": 800})).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["plan_name"], "Event plan");
    assert_eq!(body["reading_order_name"], "My order");
    assert_eq!(body["conflicts"], json!([]));
    let entries = body["entries"].as_array().unwrap();
    assert_eq!(entries[0]["thread_id"], 941);
    assert_eq!(entries[0]["source"], "added");
    assert_eq!(entries[0]["thread_title"], "Beta");
    assert_eq!(entries[1]["thread_id"], 940);
    assert_eq!(
        entries[1]["source"], "updated",
        "moved from position 1 to 2"
    );
    assert_eq!(body["total_positions"], 2);

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/continuity-plans/701/reading-orders/project-preview",
        json!({"reading_order_id": 800}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let codes: Vec<&str> = body["conflicts"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| c["code"].as_str().unwrap())
        .collect();
    assert_eq!(codes, vec!["duplicate_thread", "non_thread_node"]);
    assert_eq!(body["entries"], json!([]));
    assert_eq!(body["total_positions"], 1);

    // Another reader gets the same 404 as a missing plan or reading order.
    let (other_token, other_csrf) = create_test_user(&state, "other-reader").await;
    let (status, _) = post_json(
        &state,
        &other_token,
        &other_csrf,
        uri,
        json!({"reading_order_id": 800}),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, _) = post_json(
        &state,
        &token,
        &csrf,
        uri,
        json!({"reading_order_id": 9999}),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, _) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/continuity-plans/9999/reading-orders/project-preview",
        json!({"reading_order_id": 800}),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);

    for bad in [
        json!({}),
        json!({"reading_order_id": 0}),
        json!({"reading_order_id": "x"}),
    ] {
        let (status, body) = post_json(&state, &token, &csrf, uri, bad.clone()).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{bad}");
        assert_eq!(body, validation_failed(), "{bad}");
    }
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v1/continuity-plans/abc/reading-orders/project-preview",
        json!({"reading_order_id": 800}),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body, validation_failed());
}

/// #5715: the canonical AIP-136 resource custom method has the same read-only
/// wire contract as the retained v1 preview. It must not write a plan, reading
/// order or item; the durable v2 commit remains the only writer and revalidates
/// the current plan with conflict/idempotency semantics.
#[tokio::test]
async fn v2_reading_order_projection_preview_is_read_only_and_commit_is_idempotent() {
    let (state, token, csrf, _guard) = setup().await;
    let user_id = me_id(&state, &token).await;
    seed_overlap_scenario(&state, user_id).await;
    {
        let conn = state.pool.get().await.unwrap();
        conn.batch_execute(&format!(
            r#"
            INSERT INTO continuity_plans (id, user_id, name, ordering_mode, nodes_json, lanes_json, created_at, updated_at)
            VALUES
              (710, {user_id}, 'Event plan', 'informational',
               '[{{"id":"n1","node_type":"thread","ref_id":941,"lane_id":"main","position":0}},
                 {{"id":"n2","node_type":"thread","ref_id":940,"lane_id":"main","position":1}}]'::json,
               '[{{"id":"main","order":0}}]'::json, NOW(), NOW()),
              (711, {user_id}, 'Bad plan', 'informational',
               '[{{"id":"n1","node_type":"thread","ref_id":941,"lane_id":"main","position":0}},
                 {{"id":"n2","node_type":"thread","ref_id":941,"lane_id":"main","position":1}},
                 {{"id":"n3","node_type":"series","ref_id":5,"lane_id":"main","position":2}}]'::json,
               '[{{"id":"main","order":0}}]'::json, NOW(), NOW());
            INSERT INTO reading_orders (id, name, user_id) VALUES (810, 'My order', {user_id});
            INSERT INTO reading_order_items (reading_order_id, thread_id, "position") VALUES (810, 940, 1);
            "#
        ))
        .await
        .unwrap();
    }
    let preview_uri = "/api/v2/continuityPlans/710:previewReadingOrderProjection";
    let commit_uri = "/api/v2/continuity-plans/710/reading-orders/project";

    let (status, _) = raw_request(&state, "POST", preview_uri, None, &csrf, "{}").await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);

    for bad in [
        json!({}),
        json!({"reading_order_id": 0}),
        json!({"reading_order_id": "x"}),
    ] {
        let (status, body) = post_json(&state, &token, &csrf, preview_uri, bad.clone()).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{bad}");
        assert_eq!(body, validation_failed(), "{bad}");
    }

    let (other_token, other_csrf) = create_test_user(&state, "v2-projection-other-reader").await;
    let (status, _) = post_json(
        &state,
        &other_token,
        &other_csrf,
        preview_uri,
        json!({"reading_order_id": 810}),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, _) = post_json(
        &state,
        &token,
        &csrf,
        preview_uri,
        json!({"reading_order_id": 9999}),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/continuityPlans/abc:previewReadingOrderProjection",
        json!({"reading_order_id": 810}),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body, validation_failed());
    // A different custom-method suffix is never silently treated as a preview.
    let (status, _) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/continuityPlans/710:someOtherMethod",
        json!({"reading_order_id": 810}),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        preview_uri,
        json!({"reading_order_id": 810}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["plan_name"], "Event plan");
    assert_eq!(body["reading_order_name"], "My order");
    assert_eq!(body["conflicts"], json!([]));
    let entries = body["entries"].as_array().unwrap();
    assert_eq!(entries[0]["thread_id"], 941);
    assert_eq!(entries[0]["source"], "added");
    assert_eq!(entries[1]["thread_id"], 940);
    assert_eq!(entries[1]["source"], "updated");

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/continuityPlans/711:previewReadingOrderProjection",
        json!({"reading_order_id": 810}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let codes: Vec<&str> = body["conflicts"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| c["code"].as_str().unwrap())
        .collect();
    assert_eq!(codes, vec!["duplicate_thread", "non_thread_node"]);
    assert_eq!(body["entries"], json!([]));

    // Preview never writes, including when the plan has conflicts.
    {
        let conn = state.pool.get().await.unwrap();
        let rows: Vec<(i32, i32)> = conn
            .query(
                "SELECT thread_id, position FROM reading_order_items
                 WHERE reading_order_id = 810 ORDER BY position",
                &[],
            )
            .await
            .unwrap()
            .iter()
            .map(|row| (row.get(0), row.get(1)))
            .collect();
        assert_eq!(rows, vec![(940, 1)], "preview must not write items");
    }

    // The durable confirmation is the only writer. Replaying it with the same
    // plan keeps every position, proving the commit is idempotent.
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        commit_uri,
        json!({"reading_order_id": 810}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["added_count"], 1);
    assert_eq!(body["updated_count"], 1);
    assert_eq!(body["kept_count"], 0);
    assert_eq!(body["total_positions"], 2);
    let (status, replay) = post_json(
        &state,
        &token,
        &csrf,
        commit_uri,
        json!({"reading_order_id": 810}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{replay}");
    assert_eq!(replay["added_count"], 0);
    assert_eq!(replay["updated_count"], 0);
    assert_eq!(replay["kept_count"], 2);

    // A conflicting plan cannot confirm: 409 projection_conflicts and no write.
    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/continuity-plans/711/reading-orders/project",
        json!({"reading_order_id": 810}),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(body["detail"]["code"], "projection_conflicts");
    {
        let conn = state.pool.get().await.unwrap();
        let rows: Vec<(i32, i32)> = conn
            .query(
                "SELECT thread_id, position FROM reading_order_items
                 WHERE reading_order_id = 810 ORDER BY position",
                &[],
            )
            .await
            .unwrap()
            .iter()
            .map(|row| (row.get(0), row.get(1)))
            .collect();
        assert_eq!(rows, vec![(941, 1), (940, 2)]);
    }
}

// ---------------------------------------------------------------------------
// #4022: source-linked, owner-scoped canonical Reading List adoption.
// Every assertion below runs against real PostgreSQL through the mounted
// router; the legacy continuity Plan is never the adoption identity.
// ---------------------------------------------------------------------------

async fn second_reader(state: &Arc<AppState>, label: &str) -> (String, String, i32) {
    let (token, csrf) = create_test_user(state, label).await;
    let (status, me) = get(state, &token, "/api/v2/auth/me").await;
    assert_eq!(status, StatusCode::OK, "{me}");
    (token, csrf, me["id"].as_i64().unwrap() as i32)
}

fn adoption_body(
    include_positions: &[i32],
    exclude_positions: &[i32],
    revision_sha: &str,
    content_hash: &str,
) -> Value {
    let mut overrides = Vec::new();
    for position in include_positions {
        overrides.push(json!({"cbl_position": position, "decision": "include"}));
    }
    for position in exclude_positions {
        overrides.push(json!({"cbl_position": position, "decision": "exclude"}));
    }
    json!({
        "entry_decisions": {},
        "series_decisions": [],
        "series_overrides": overrides,
        "content_hash": content_hash,
        "revision_sha": revision_sha,
    })
}

#[tokio::test]
async fn adoption_commit_source_link_is_the_canonical_identity_issue_4022() {
    let (state, token, csrf, _guard) = setup().await;
    let body = adoption_body(&[0], &[1], "rev-1", "h-mm");

    let (status, first) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        body.clone(),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{first}");
    let list_id = first["custom_cbl_list_id"].as_i64().unwrap() as i32;
    assert!(
        list_id > 0,
        "commit must return the canonical list ID: {first}"
    );
    assert_eq!(first["list_version"], 1, "{first}");

    let conn = state.pool.get().await.unwrap();
    let link = conn
        .query_one(
            "SELECT custom_cbl_list_id, list_version, source_revision_sha, source_content_hash
             FROM custom_cbl_source_links WHERE cbl_source_list_id = 1",
            &[],
        )
        .await
        .unwrap();
    assert_eq!(link.get::<_, i32>(0), list_id);
    assert_eq!(link.get::<_, i32>(1), 1);
    assert_eq!(link.get::<_, String>(2), "rev-1");
    assert_eq!(link.get::<_, String>(3), "h-mm");

    // An exact retry replays the receipt: same list, same version, no new rows.
    let (status2, retry) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        body,
    )
    .await;
    assert!(
        status2 == StatusCode::CREATED || status2 == StatusCode::OK,
        "{retry}"
    );
    assert_eq!(retry["custom_cbl_list_id"], list_id, "{retry}");
    assert_eq!(retry["list_version"], 1, "{retry}");
    let entry_count: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM custom_cbl_entries WHERE list_id = $1",
            &[&list_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(entry_count, 1, "retry must not duplicate issues: {retry}");
}

#[tokio::test]
async fn adoption_commit_revision_and_list_version_guards_are_atomic_issue_4022() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, first) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        adoption_body(&[0], &[1], "rev-1", "h-mm"),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{first}");
    let list_id = first["custom_cbl_list_id"].as_i64().unwrap() as i32;
    let conn = state.pool.get().await.unwrap();

    // Source revision changed after the preview: reject before any write.
    conn.execute(
        "UPDATE cbl_source_lists SET revision_sha = 'rev-2' WHERE id = 1",
        &[],
    )
    .await
    .unwrap();
    let (stale_status, stale) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        adoption_body(&[], &[0, 1], "rev-1", "h-mm"),
    )
    .await;
    assert_eq!(stale_status, StatusCode::CONFLICT, "{stale}");
    assert_eq!(stale["detail"]["code"], "stale_preview", "{stale}");
    let version: i32 = conn
        .query_one(
            "SELECT list_version FROM custom_cbl_source_links WHERE cbl_source_list_id = 1",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(version, 1, "stale source must not bump the list version");
    let entry_count: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM custom_cbl_entries WHERE list_id = $1",
            &[&list_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(entry_count, 1, "stale source must not create partial rows");

    // Restore the source, then send a stale owned-list version.
    conn.execute(
        "UPDATE cbl_source_lists SET revision_sha = 'rev-1' WHERE id = 1",
        &[],
    )
    .await
    .unwrap();
    let mut changed = adoption_body(&[], &[0, 1], "rev-1", "h-mm");
    changed["list_version"] = json!(0);
    let (version_status, version_body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        changed,
    )
    .await;
    assert_eq!(version_status, StatusCode::CONFLICT, "{version_body}");
    assert_eq!(
        version_body["detail"]["code"], "stale_preview",
        "{version_body}"
    );
    let entry_count: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM custom_cbl_entries WHERE list_id = $1",
            &[&list_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(entry_count, 1, "stale list must not create partial rows");
}

#[tokio::test]
async fn adoption_commit_isolates_readers_and_same_name_sources_issue_4022() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, first) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        adoption_body(&[0], &[1], "rev-1", "h-mm"),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{first}");
    let list_a = first["custom_cbl_list_id"].as_i64().unwrap() as i32;

    // A second reader adopting the same source gets a distinct owner-scoped list.
    let (token_b, csrf_b, user_b) = second_reader(&state, "issue-identity-b").await;
    let (status_b, second) = post_json(
        &state,
        &token_b,
        &csrf_b,
        "/api/v2/reading-lists/1/adoption-commits",
        adoption_body(&[0], &[1], "rev-1", "h-mm"),
    )
    .await;
    assert_eq!(status_b, StatusCode::CREATED, "{second}");
    let list_b = second["custom_cbl_list_id"].as_i64().unwrap() as i32;
    assert_ne!(
        list_a, list_b,
        "readers must not share a source-linked list"
    );

    // Same display name, different source identity: still distinct lists.
    let conn = state.pool.get().await.unwrap();
    conn.batch_execute(
        r#"
        INSERT INTO cbl_source_lists
          (id, source_id, source_path, name, declared_issue_count, content_hash,
           revision_sha, active, created_at, updated_at)
        VALUES (4, 1, 'DC/Duplicate/Mister Miracle.cbl', 'Mister Miracle 1989',
                1, 'h-dup', 'rev-1', TRUE, NOW(), NOW());
        INSERT INTO cbl_source_entries
          (id, list_id, "position", series_name, issue_number, volume_year,
           publication_year, external_issue_identity_id, external_series_identity_id, created_at)
        VALUES (990004, 4, 0, 'Mister Miracle', '3', 1989, 1989, 1, 2, NOW());
        "#,
    )
    .await
    .unwrap();
    drop(conn);
    let (status_dup, duplicate) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/4/adoption-commits",
        adoption_body(&[0], &[], "rev-1", "h-dup"),
    )
    .await;
    assert_eq!(status_dup, StatusCode::CREATED, "{duplicate}");
    let list_dup = duplicate["custom_cbl_list_id"].as_i64().unwrap() as i32;
    assert_ne!(list_a, list_dup, "display name is not adoption identity");
    assert_ne!(list_b, list_dup, "display name is not adoption identity");

    let conn = state.pool.get().await.unwrap();
    let owners: Vec<(i32, i32)> = conn
        .query(
            "SELECT user_id, custom_cbl_list_id FROM custom_cbl_source_links
             WHERE cbl_source_list_id IN (1, 4) ORDER BY cbl_source_list_id, user_id",
            &[],
        )
        .await
        .unwrap()
        .into_iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();
    assert_eq!(owners.len(), 3, "one link per reader+source: {owners:?}");
    assert!(owners
        .iter()
        .any(|(uid, lid)| *uid == user_b && *lid == list_b));
}

#[tokio::test]
async fn adoption_commit_rejects_cross_owner_plan_and_leaves_no_rows_issue_4022() {
    let (state, token, csrf, _guard) = setup().await;
    let (_, _, user_b) = second_reader(&state, "issue-identity-owner").await;
    let conn = state.pool.get().await.unwrap();
    conn.execute(
        "INSERT INTO continuity_plans
           (id, user_id, name, ordering_mode, lanes_json, nodes_json, created_at, updated_at)
         VALUES (40220, $1, 'Other reader plan', 'informational',
                 '[{\"id\":\"default\",\"name\":\"Default\",\"order\":0}]'::jsonb,
                 '[]'::jsonb, NOW(), NOW())",
        &[&user_b],
    )
    .await
    .unwrap();
    drop(conn);

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/reading-plans/40220/adoption-commits",
        adoption_body(&[0], &[1], "rev-1", "h-mm"),
    )
    .await;
    assert!(
        status == StatusCode::NOT_FOUND || status == StatusCode::UNPROCESSABLE_ENTITY,
        "{status} {body}"
    );
    let conn = state.pool.get().await.unwrap();
    let links: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM custom_cbl_source_links WHERE cbl_source_list_id = 1",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        links, 0,
        "cross-owner adoption must not create a source link"
    );
}

#[tokio::test]
async fn adoption_commit_restores_committed_choices_on_reopen_issue_4022() {
    let (state, token, csrf, _guard) = setup().await;
    let mut body = adoption_body(&[0], &[1], "rev-1", "h-mm");
    body["series_decisions"] = json!([
        {"series_name": "provider-series:comicvine:4050-9", "decision": "exclude"}
    ]);
    body["overlap_decisions"] = json!([
        {"continuing_volume_id": "4050-9", "waiting_volume_id": "4050-10"}
    ]);

    let (status, committed) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        body,
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{committed}");
    assert_eq!(
        committed["overlap_decisions"],
        json!([{"continuing_volume_id": "4050-9", "waiting_volume_id": "4050-10"}]),
        "{committed}"
    );
    let list_id = committed["custom_cbl_list_id"].as_i64().unwrap() as i32;

    let (open_status, reopened) =
        get(&state, &token, &format!("/api/v2/reading-lists/{list_id}")).await;
    assert_eq!(open_status, StatusCode::OK, "{reopened}");
    assert_eq!(reopened["list_version"], 1, "{reopened}");
    assert_eq!(reopened["source_revision_sha"], "rev-1", "{reopened}");
    assert_eq!(reopened["source_content_hash"], "h-mm", "{reopened}");
    let selections = &reopened["selections"];
    assert_eq!(
        selections["series_decisions"]["provider-series:comicvine:4050-9"], "exclude",
        "{reopened}"
    );
    assert_eq!(selections["series_overrides"]["0"], "include", "{reopened}");
    assert_eq!(
        reopened["overlap_decisions"][0]["waiting_volume_id"], "4050-10",
        "{reopened}"
    );
}

#[tokio::test]
async fn adoption_commit_revised_selection_keeps_manual_history_issue_4022() {
    let (state, token, csrf, _guard) = setup().await;
    let (status, first) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        adoption_body(&[0], &[1], "rev-1", "h-mm"),
    )
    .await;
    assert_eq!(status, StatusCode::CREATED, "{first}");
    let list_id = first["custom_cbl_list_id"].as_i64().unwrap() as i32;
    let (_, me) = get(&state, &token, "/api/v2/auth/me").await;
    let real_user = me["id"].as_i64().unwrap() as i32;
    let conn = state.pool.get().await.unwrap();

    // A manually added issue and the adopted issue's read history must survive
    // a revised source selection on the same source-linked list.
    conn.execute(
        "INSERT INTO threads
           (id, title, format, issues_remaining, queue_position, status, created_at, user_id)
         VALUES (40221, 'Manual extra', 'issues', 1, 0, 'active', NOW(), $1)",
        &[&real_user],
    )
    .await
    .unwrap();
    conn.execute(
        "INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
         VALUES (40221, 40221, '99', 'unread', NOW(), 0)",
        &[],
    )
    .await
    .unwrap();
    conn.execute(
        "INSERT INTO custom_cbl_entries
           (list_id, issue_id, position, created_at, is_checkpoint,
            checkpoint_target_issue_ids, gate, skipped)
         VALUES ($1, 40221, 99, NOW(), false, '[]'::json, 'none', false)",
        &[&list_id],
    )
    .await
    .unwrap();
    conn.execute(
        "UPDATE issues SET status = 'read', read_at = NOW()
         WHERE id IN (
           SELECT issue_id FROM custom_cbl_entries WHERE list_id = $1 AND issue_id <> 40221
         )",
        &[&list_id],
    )
    .await
    .unwrap();

    // Both source positions resolve to one physical issue: the revised commit
    // must update the same list in place and not duplicate it.
    let mut revised = adoption_body(&[0, 1], &[], "rev-1", "h-mm");
    revised["list_version"] = json!(1);
    let (status2, second) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/1/adoption-commits",
        revised,
    )
    .await;
    assert!(
        status2 == StatusCode::CREATED || status2 == StatusCode::OK,
        "{second}"
    );
    assert_eq!(second["custom_cbl_list_id"], list_id, "{second}");
    assert_eq!(second["list_version"], 2, "{second}");

    let entries: Vec<(i32, i32)> = conn
        .query(
            "SELECT issue_id, position FROM custom_cbl_entries WHERE list_id = $1 ORDER BY position",
            &[&list_id],
        )
        .await
        .unwrap()
        .into_iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect();
    assert_eq!(
        entries.len(),
        2,
        "one adopted issue plus the manual extra: {entries:?}"
    );
    assert!(
        entries.iter().any(|(issue_id, _)| *issue_id == 40221),
        "{entries:?}"
    );
    let manual_status: String = conn
        .query_one("SELECT status FROM issues WHERE id = 40221", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        manual_status, "unread",
        "manual issue must not be marked read"
    );
    let adopted_read: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM issues
             WHERE id IN (
               SELECT issue_id FROM custom_cbl_entries WHERE list_id = $1 AND issue_id <> 40221
             ) AND status = 'read'",
            &[&list_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(adopted_read, 1, "adopted issue read history must survive");
}

#[tokio::test]
async fn adoption_commit_does_not_truncate_large_source_issue_4022() {
    let (state, token, csrf, _guard) = setup().await;
    let (_, me) = get(&state, &token, "/api/v2/auth/me").await;
    let real_user = me["id"].as_i64().unwrap() as i32;
    let conn = state.pool.get().await.unwrap();
    conn.batch_execute(&format!(
        r#"
        INSERT INTO cbl_source_lists
          (id, source_id, source_path, name, declared_issue_count, content_hash,
           revision_sha, active, created_at, updated_at)
        VALUES (5, 1, 'DC/Big/Big.cbl', 'Big Source', 1001, 'h-big', 'rev-1', TRUE, NOW(), NOW());
        INSERT INTO external_identities
          (id, provider, entity_type, external_id, metadata_json, created_at, updated_at)
        SELECT 500000 + g, 'comicvine', 'issue', 'CV-BIG-' || g, '{{}}'::json, NOW(), NOW()
        FROM generate_series(0, 1000) g;
        INSERT INTO threads
          (id, title, format, issues_remaining, queue_position, status, created_at, user_id)
        SELECT 500000 + g, 'Big ' || g, 'issues', 1, g::int, 'active', NOW(), {real_user}
        FROM generate_series(0, 1000) g;
        INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
        SELECT 500000 + g, 500000 + g, (g + 1)::text, 'unread', NOW(), 0
        FROM generate_series(0, 1000) g;
        INSERT INTO issue_external_identity_mappings
          (issue_id, external_identity_id, status, evidence_source, evidence_json, created_at, updated_at)
        SELECT 500000 + g, 500000 + g, 'confirmed', 'cbl_adoption_commit', '{{}}'::json, NOW(), NOW()
        FROM generate_series(0, 1000) g;
        INSERT INTO cbl_source_entries
          (id, list_id, "position", series_name, issue_number, volume_year,
           publication_year, external_issue_identity_id, external_series_identity_id, created_at)
        SELECT 600000 + g, 5, g::int, 'Big Series', (g + 1)::text, 2000, 2000,
               500000 + g, NULL, NOW()
        FROM generate_series(0, 1000) g;
        "#
    ))
    .await
    .unwrap();
    drop(conn);

    let (status, body) = post_json(
        &state,
        &token,
        &csrf,
        "/api/v2/reading-lists/5/adoption-commits",
        adoption_body(&[], &[], "rev-1", "h-big"),
    )
    .await;
    assert_eq!(
        status,
        StatusCode::CREATED,
        "{}",
        String::from_utf8_lossy(&serde_json::to_vec(&body).unwrap_or_default())
    );
    let list_id = body["custom_cbl_list_id"].as_i64().unwrap() as i32;
    let conn = state.pool.get().await.unwrap();
    let count: i64 = conn
        .query_one(
            "SELECT COUNT(*)::bigint FROM custom_cbl_entries WHERE list_id = $1",
            &[&list_id],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(count, 1001, "all 1001 adopted issues must be persisted");
}
