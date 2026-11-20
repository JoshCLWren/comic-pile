#![allow(clippy::unwrap_used, clippy::expect_used)]
//! PostgreSQL-backed HTTP regressions for the native read-only
//! `/api/v2/comicvine/*` provider routes (#4835, split chunk A: series
//! search, pasted-URL resolve and a volume's issue roster). Every provider
//! call goes through a fake outbound client; nothing here opens a socket.
//! Requires `RUST_ROLL_TEST_DATABASE_URL` (a disposable local database, used
//! for the authenticated user) and hard-fails without it.

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
};
use bytes::Bytes;
use comicpile_roll_service::outbound::{
    OutboundError, OutboundFuture, OutboundHttp, OutboundRequest, OutboundResponse,
    RecordingFakeOutbound,
};
use comicpile_roll_service::{config::Config, router, test_support, AppState};
use serde_json::{json, Value};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use tower::ServiceExt;

static NEXT_TEST_CLIENT: AtomicUsize = AtomicUsize::new(1);

type Session = (
    Arc<AppState>,
    String,
    String,
    tokio::sync::MutexGuard<'static, ()>,
);

fn unique_suffix() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos()
}

async fn setup_user(prefix: &str) -> Session {
    setup_user_with(prefix, None).await
}

/// Every test holds the `reset_for_test` guard for its whole body, which
/// also serializes the process-wide `COMICVINE_API_KEY` toggled by `set_key`.
async fn setup_user_with(prefix: &str, outbound: Option<Arc<dyn OutboundHttp>>) -> Session {
    let url = test_support::database_url().await;
    let mut app = test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-roll-routes-secret".into()),
            "RUST_ROLL_POOL_SIZE" => Some("2".into()),
            _ => None,
        })
        .unwrap(),
    );
    if let Some(outbound) = outbound {
        app.outbound = outbound;
    }
    let state = Arc::new(app);
    let guard = test_support::reset_for_test(&state).await;
    let username = format!("{prefix}-{}-{}", std::process::id(), unique_suffix());
    let (token, csrf) = register_user(&state, &username).await;
    (state, token, csrf, guard)
}

async fn register_user(state: &Arc<AppState>, username: &str) -> (String, String) {
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
    (token, csrf)
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

fn get(path: &str, token: &str, csrf: &str) -> Request<Body> {
    Request::builder()
        .method("GET")
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"))
        .body(Body::empty())
        .unwrap()
}

fn fake(state: &Arc<AppState>) -> &RecordingFakeOutbound {
    state
        .outbound
        .as_any()
        .downcast_ref::<RecordingFakeOutbound>()
        .expect("test state uses the recording fake outbound client")
}

/// Queue one canned ComicVine envelope (`status_code: 1`) for the next call.
fn provider_ok(state: &Arc<AppState>, mut payload: Value) {
    payload["status_code"] = json!(1);
    payload["error"] = json!("OK");
    fake(state).push_ok(
        http::StatusCode::OK,
        http::HeaderMap::new(),
        Bytes::from(payload.to_string()),
    );
}

fn provider_throttled(state: &Arc<AppState>, retry_after: &str) {
    let mut headers = http::HeaderMap::new();
    headers.insert("retry-after", retry_after.parse().unwrap());
    fake(state).push_ok(http::StatusCode::TOO_MANY_REQUESTS, headers, Bytes::new());
}

fn set_key(present: bool) {
    if present {
        std::env::set_var("COMICVINE_API_KEY", "TESTKEY123");
    } else {
        std::env::remove_var("COMICVINE_API_KEY");
    }
}

const ISSUE_URL: &str =
    "/api/v2/comicvine/resolve?input=https%3A%2F%2Fcomicvine.gamespot.com%2Fissue%2F4000-123%2F";
const VOLUME_URL: &str =
    "/api/v2/comicvine/resolve?input=https%3A%2F%2Fcomicvine.gamespot.com%2Fsaga%2F4050-9%2F";
const RESOLVE_FAILED: &str =
    "We couldn't resolve that ComicVine link right now. Check the link or search by title instead.";

#[tokio::test]
async fn every_read_requires_authentication() {
    let (state, _token, _csrf, _guard) = setup_user("cvv2-auth").await;
    for path in [
        "/api/v2/comicvine/resolve?input=x",
        "/api/v2/comicvine/search/series?q=x",
        "/api/v2/comicvine/series/1/issues",
    ] {
        let request = Request::builder()
            .method("GET")
            .uri(path)
            .body(Body::empty())
            .unwrap();
        let (status, body) = send(&state, request).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED, "{path}: {body:?}");
        assert!(
            fake(&state).calls().is_empty(),
            "{path} reached the provider"
        );
    }
}

#[tokio::test]
async fn malformed_requests_use_the_production_validation_contract() {
    let (state, token, csrf, _guard) = setup_user("cvv2-validation").await;
    set_key(true);
    let expected = json!({"detail": "Validation failed"});
    let long_q = "q".repeat(201);
    let long_input = "i".repeat(1001);
    for path in [
        "/api/v2/comicvine/search/series".to_owned(),
        "/api/v2/comicvine/search/series?q=".to_owned(),
        format!("/api/v2/comicvine/search/series?q={long_q}"),
        "/api/v2/comicvine/search/series?q=saga&limit=0".to_owned(),
        "/api/v2/comicvine/search/series?q=saga&limit=51".to_owned(),
        "/api/v2/comicvine/search/series?q=saga&offset=-1".to_owned(),
        "/api/v2/comicvine/search/series?q=saga&limit=x".to_owned(),
        "/api/v2/comicvine/search/series?q=saga&limit=5.5".to_owned(),
        "/api/v2/comicvine/resolve".to_owned(),
        "/api/v2/comicvine/resolve?input=".to_owned(),
        format!("/api/v2/comicvine/resolve?input={long_input}"),
        "/api/v2/comicvine/series/abc/issues".to_owned(),
        "/api/v2/comicvine/series/1.5/issues".to_owned(),
    ] {
        let (status, got) = send(&state, get(&path, &token, &csrf)).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{path}: {got:?}");
        assert_eq!(got, expected, "{path}");
    }
    assert!(
        fake(&state).calls().is_empty(),
        "rejected requests never reach the provider"
    );
    // Lax ints accepted like Pydantic: "5.0" is 5, a blank query skips the provider.
    let (status, got) = send(
        &state,
        get(
            "/api/v2/comicvine/search/series?q=%20&limit=5.0&offset=0",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{got:?}");
    assert_eq!(
        got,
        json!({"query": " ", "results": [], "total_available": 0, "offset": 0, "limit": 5, "has_more": false, "next_offset": null})
    );
    assert!(fake(&state).calls().is_empty());
}

#[tokio::test]
async fn reads_without_a_provider_key_answer_empty_like_python() {
    let (state, token, csrf, _guard) = setup_user("cvv2-nokey").await;
    set_key(false);
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/search/series?q=saga&limit=5&offset=10",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body,
        json!({"query": "saga", "results": [], "total_available": 0, "offset": 10, "limit": 5, "has_more": false, "next_offset": null})
    );
    let (status, body) = send(
        &state,
        get("/api/v2/comicvine/series/9/issues", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body,
        json!({"comicvine_volume_id": 9, "series_name": "Volume 9", "issues": []})
    );
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/series/9/issues?series_name=Saga",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["series_name"], "Saga");
    let (status, body) = send(&state, get(ISSUE_URL, &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body,
        json!({"input": "https://comicvine.gamespot.com/issue/4000-123/", "kind": "issue",
               "validation_error": "ComicVine is not configured on this server, so pasted links cannot be resolved. Search by title instead.",
               "issue": null, "volume": null, "issues": []})
    );
    assert!(fake(&state).calls().is_empty());
}

#[tokio::test]
async fn search_pages_through_the_provider_like_python() {
    let (state, token, csrf, _guard) = setup_user("cvv2-search").await;
    set_key(true);
    provider_ok(
        &state,
        json!({"number_of_total_results": 25, "results": [
        {"id": 1, "name": "Saga", "publisher": {"name": "Image"}, "start_year": "2012", "count_of_issues": 54,
         "site_detail_url": "https://comicvine.gamespot.com/saga/4050-1/", "image": {"medium_url": "m.jpg", "small_url": "s.jpg"}},
        {"id": "bad", "name": "skipped"}]}),
    );
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/search/series?q=saga%20the&limit=10&offset=0",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body,
        json!({"query": "saga the", "total_available": 25, "offset": 0, "limit": 10,
               "has_more": true, "next_offset": 1, "results": [
            {"comicvine_volume_id": 1, "name": "Saga", "publisher": "Image", "start_year": 2012,
             "issue_count": 54, "site_detail_url": "https://comicvine.gamespot.com/saga/4050-1/", "image_url": "m.jpg"}]})
    );
    let call = fake(&state).calls().last().unwrap().clone();
    assert!(
        call.path.starts_with("/api/search/?")
            && call.path.contains("query=saga+the")
            && call.path.contains("resources=volume")
            && call.path.contains("limit=10")
            && call.path.contains("page=1"),
        "{}",
        call.path
    );

    // offset 20 with limit 10 asks for provider page 3; without a provider
    // total the loaded count is the total.
    provider_ok(&state, json!({"results": [{"id": 2, "name": "Saga 2"}]}));
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/search/series?q=saga&limit=10&offset=20",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        (
            &body["total_available"],
            &body["has_more"],
            &body["next_offset"]
        ),
        (&json!(1), &json!(false), &Value::Null)
    );
    assert!(fake(&state).calls().last().unwrap().path.contains("page=3"));

    // A payload whose `results` is not a list is an empty page with total 0,
    // even when the provider reports a total.
    provider_ok(
        &state,
        json!({"number_of_total_results": 40, "results": {"id": 1}}),
    );
    let (status, body) = send(
        &state,
        get("/api/v2/comicvine/search/series?q=odd", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body,
        json!({"query": "odd", "results": [], "total_available": 0, "offset": 0, "limit": 10, "has_more": false, "next_offset": null})
    );
}

/// The largest accepted offset must not overflow the provider page or the
/// next offset (#4636390843): Python's unbounded ints give page 2^31 and
/// next_offset 2^31.
#[tokio::test]
async fn search_paging_at_the_accepted_offset_bound_does_not_overflow() {
    let (state, token, csrf, _guard) = setup_user("cvv2-search-bound").await;
    set_key(true);
    provider_ok(
        &state,
        json!({"number_of_total_results": 2_147_483_649_i64, "results": [{"id": 1, "name": "Saga"}]}),
    );
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/search/series?q=saga&limit=1&offset=2147483647",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["offset"], json!(2_147_483_647_i64));
    assert_eq!(body["has_more"], json!(true));
    assert_eq!(body["next_offset"], json!(2_147_483_648_i64));
    let path = fake(&state).calls().last().unwrap().path.clone();
    assert!(path.contains("page=2147483648"), "{path}");
    // One past the bound is a validation error, never a wrapped page.
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/search/series?q=saga&limit=1&offset=2147483648",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body:?}");
}

/// Python lets provider errors escape `search_comicvine_series` to the global
/// exception handler: a generic 500 `{"detail": "Internal server error"}`.
#[tokio::test]
async fn search_provider_failures_use_the_python_error_envelope() {
    let (state, token, csrf, _guard) = setup_user("cvv2-search-fail").await;
    set_key(true);
    // No canned response: the fake fails closed like an unreachable network.
    let (status, body) = send(
        &state,
        get("/api/v2/comicvine/search/series?q=down", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR, "{body:?}");
    assert_eq!(body, json!({"detail": "Internal server error"}));
}

#[tokio::test]
async fn browser_provider_calls_are_cached_and_honor_throttle_cooldowns() {
    let (state, token, csrf, _guard) = setup_user("cvv2-limits").await;
    set_key(true);
    provider_ok(
        &state,
        json!({"number_of_total_results": 1, "results": [{"id": 1, "name": "Saga"}]}),
    );
    let search = "/api/v2/comicvine/search/series?q=saga&limit=10&offset=0";
    for _ in 0..3 {
        let (status, body) = send(&state, get(search, &token, &csrf)).await;
        assert_eq!(status, StatusCode::OK, "{body:?}");
        assert_eq!(body["results"][0]["name"], "Saga");
    }
    assert_eq!(
        fake(&state).calls().len(),
        1,
        "repeat searches reuse the cached payload"
    );

    // A 429 starts a cooldown on the bucket: later distinct searches do not
    // reach ComicVine until the requested wait has passed, while the cached
    // search keeps answering.
    provider_throttled(&state, "120");
    let (status, _) = send(
        &state,
        get("/api/v2/comicvine/search/series?q=one", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
    let calls = fake(&state).calls().len();
    for q in ["two", "three"] {
        let (status, _) = send(
            &state,
            get(
                &format!("/api/v2/comicvine/search/series?q={q}"),
                &token,
                &csrf,
            ),
        )
        .await;
        assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
    }
    let (status, body) = send(&state, get(search, &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["results"][0]["name"], "Saga");
    assert_eq!(
        fake(&state).calls().len(),
        calls,
        "cooldown blocks provider calls"
    );
    // The cooldown is per endpoint bucket: roster pages still reach ComicVine.
    provider_ok(
        &state,
        json!({"number_of_total_results": 1, "results": [{"id": 5, "issue_number": "1"}]}),
    );
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/series/9/issues?series_name=Saga",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["issues"][0]["comicvine_issue_id"], 5);
    assert_eq!(fake(&state).calls().len(), calls + 1);
}

#[tokio::test]
async fn resolve_classifies_input_and_resolves_issue_links() {
    let (state, token, csrf, _guard) = setup_user("cvv2-resolve").await;
    set_key(true);
    provider_ok(
        &state,
        json!({"results": {"id": 123, "name": "Pilot", "issue_number": null, "volume": {"id": 9, "name": "Saga"},
        "cover_date": "2012-03-01", "store_date": "", "image": {"small_url": "s.jpg"},
        "site_detail_url": "https://comicvine.gamespot.com/x/4000-123/"}}),
    );
    let (status, body) = send(&state, get(ISSUE_URL, &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body,
        json!({"input": "https://comicvine.gamespot.com/issue/4000-123/", "kind": "issue",
               "validation_error": null, "volume": null, "issues": [],
               "issue": {"comicvine_issue_id": 123, "series_name": "Saga", "volume_id": 9,
                         "issue_number": null, "name": "Pilot", "cover_date": "2012-03-01",
                         "store_date": null, "image_url": "s.jpg",
                         "site_detail_url": "https://comicvine.gamespot.com/x/4000-123/"}})
    );
    let call = fake(&state).calls().last().unwrap().clone();
    assert!(
        call.path.starts_with("/api/issue/4000-123/?")
            && call.path.contains("field_list=id,name,issue_number"),
        "{}",
        call.path
    );

    for (input, kind, error) in [
        (
            "https%3A%2F%2Fexample.com%2Fissue%2F4000-1",
            "search",
            Some("That doesn't look like a ComicVine issue or volume URL. Paste a comicvine.gamespot.com link or search by title instead."),
        ),
        ("batman", "search", None),
        ("%20%20", "search", None),
    ] {
        let (status, body) = send(
            &state,
            get(&format!("/api/v2/comicvine/resolve?input={input}"), &token, &csrf),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{input}: {body:?}");
        assert_eq!(body["kind"], kind, "{input}");
        assert_eq!(body["validation_error"].as_str(), error, "{input}");
        assert_eq!(body["issue"], Value::Null);
    }

    // Provider failure, or an issue payload whose `results` is not an
    // object, keeps 200 with the retry message.
    let failing_issue =
        "/api/v2/comicvine/resolve?input=https%3A%2F%2Fcomicvine.gamespot.com%2Fissue%2F4000-5%2F";
    let (status, body) = send(&state, get(failing_issue, &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        (&body["kind"], &body["validation_error"], &body["issue"]),
        (&json!("issue"), &json!(RESOLVE_FAILED), &Value::Null)
    );
    provider_ok(&state, json!({"results": []}));
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/resolve?input=https%3A%2F%2Fcomicvine.gamespot.com%2Fissue%2F4000-6%2F",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["validation_error"], RESOLVE_FAILED);
}

#[tokio::test]
async fn resolve_volume_links_return_the_volume_and_its_roster() {
    let (state, token, csrf, _guard) = setup_user("cvv2-resolve-volume").await;
    set_key(true);
    provider_ok(
        &state,
        json!({"results": {"id": 9, "name": "Saga", "publisher": {"name": "Image"}, "start_year": "2012",
        "count_of_issues": 2, "site_detail_url": "", "image": {"medium_url": "", "super_url": "super.jpg"}}}),
    );
    provider_ok(
        &state,
        json!({"number_of_total_results": 2, "results": [
            {"id": 51, "issue_number": "1", "name": "", "volume": {"id": 9}},
            {"id": 52, "issue_number": null, "image": {"small_url": "", "thumb_url": "t.jpg"}, "volume": {"id": 9}}]}),
    );
    let (status, body) = send(&state, get(VOLUME_URL, &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body,
        json!({"input": "https://comicvine.gamespot.com/saga/4050-9/", "kind": "volume",
               "validation_error": null, "issue": null,
               "volume": {"comicvine_volume_id": 9, "name": "Saga", "publisher": "Image", "start_year": 2012,
                          "issue_count": 2, "site_detail_url": null, "image_url": "super.jpg"},
               "issues": [
                   {"comicvine_issue_id": 51, "issue_number": "1", "name": "", "cover_date": null,
                    "store_date": null, "image_url": null, "site_detail_url": null},
                   {"comicvine_issue_id": 52, "issue_number": null, "name": null, "cover_date": null,
                    "store_date": null, "image_url": "t.jpg", "site_detail_url": null}]})
    );
    let paths: Vec<String> = fake(&state)
        .calls()
        .iter()
        .map(|c| c.path.clone())
        .collect();
    assert_eq!(paths.len(), 2, "{paths:?}");
    assert!(paths[0].starts_with("/api/volume/4050-9/?"), "{paths:?}");
    assert!(
        paths[1].starts_with("/api/issues/?") && paths[1].contains("filter=volume:9"),
        "{paths:?}"
    );

    // A blank volume name fails the resolve (no roster fetch).
    fake(&state).clear();
    provider_ok(&state, json!({"results": {"id": 10, "name": "  "}}));
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/resolve?input=comicvine.gamespot.com%2Fx%2F4050-10",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        (&body["kind"], &body["validation_error"], &body["volume"]),
        (&json!("volume"), &json!(RESOLVE_FAILED), &Value::Null)
    );
    assert_eq!(fake(&state).calls().len(), 1);
}

#[tokio::test]
async fn series_issues_read_the_roster_and_volume_name() {
    let (state, token, csrf, _guard) = setup_user("cvv2-series").await;
    set_key(true);
    provider_ok(
        &state,
        json!({"number_of_total_results": 2, "results": [
        {"id": 5, "issue_number": "1", "name": "One", "cover_date": "2012-03-01", "image": {"small_url": "s.jpg"},
         "site_detail_url": "https://comicvine.gamespot.com/i/4000-5/", "volume": {"id": 9}},
        {"id": 6, "issue_number": null, "volume": {"id": 9}}]}),
    );
    provider_ok(&state, json!({"results": {"id": 9, "name": "Saga"}}));
    let (status, body) = send(
        &state,
        get("/api/v2/comicvine/series/9/issues", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body,
        json!({"comicvine_volume_id": 9, "series_name": "Saga", "issues": [
            {"comicvine_issue_id": 5, "issue_number": "1", "name": "One", "cover_date": "2012-03-01",
             "store_date": null, "image_url": "s.jpg", "site_detail_url": "https://comicvine.gamespot.com/i/4000-5/"},
            {"comicvine_issue_id": 6, "issue_number": null, "name": null, "cover_date": null,
             "store_date": null, "image_url": null, "site_detail_url": null}]})
    );

    // Each read degrades independently: a failed roster keeps the name, a
    // failed volume read keeps the roster under the generic label.
    fake(&state).clear();
    provider_ok(
        &state,
        json!({"error": "bad", "number_of_total_results": 1}),
    );
    provider_ok(&state, json!({"results": {"id": 10, "name": "Ten"}}));
    let (status, body) = send(
        &state,
        get("/api/v2/comicvine/series/10/issues", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body,
        json!({"comicvine_volume_id": 10, "series_name": "Ten", "issues": []})
    );
    provider_ok(
        &state,
        json!({"number_of_total_results": 1, "results": [{"id": 7, "issue_number": 3, "volume": {"id": 11}}]}),
    );
    let (status, body) = send(
        &state,
        get("/api/v2/comicvine/series/11/issues", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["series_name"], "Volume 11");
    assert_eq!(body["issues"][0]["issue_number"], "3");
}

fn roster_page(volume: i32, first_id: i32, count: i32, total: Option<i32>) -> Value {
    let results: Vec<Value> = (first_id..first_id + count)
        .map(|id| json!({"id": id, "issue_number": id.to_string(), "volume": {"id": volume}}))
        .collect();
    let mut page = json!({ "results": results });
    if let Some(total) = total {
        page["number_of_total_results"] = json!(total);
    }
    page
}

#[tokio::test]
async fn rosters_beyond_one_thousand_rows_are_fetched_completely() {
    let (state, token, csrf, _guard) = setup_user("cvv2-roster").await;
    set_key(true);
    // 1250 rows with a reported total: 13 pages, not 10.
    for page in 0..13 {
        let count = if page == 12 { 50 } else { 100 };
        provider_ok(&state, roster_page(77, page * 100 + 1, count, Some(1250)));
    }
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/series/77/issues?series_name=Big",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["issues"].as_array().unwrap().len(), 1250);
    // Omitted total: walk forward until a short page.
    provider_ok(&state, roster_page(78, 1, 100, None));
    provider_ok(&state, roster_page(78, 101, 30, None));
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/series/78/issues?series_name=NoTotal",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["issues"].as_array().unwrap().len(), 130);
    let offsets: Vec<String> = fake(&state)
        .calls()
        .iter()
        .rev()
        .take(2)
        .map(|c| {
            c.path
                .split("offset=")
                .nth(1)
                .unwrap()
                .split('&')
                .next()
                .unwrap()
                .to_owned()
        })
        .collect();
    assert_eq!(offsets, ["100", "0"]);
}

/// Order-independent fake ComicVine: `/issues` pages are synthesized from the
/// request's `offset`, so concurrent page fetches cannot receive each other's
/// payloads. Every response yields to the scheduler once before resolving,
/// and the fake records the peak number of page requests in flight.
struct PagedComicVine {
    volume: i32,
    total: usize,
    /// Offset whose page is returned without a `results` list.
    malformed_offset: Option<usize>,
    in_flight: Arc<AtomicUsize>,
    peak: AtomicUsize,
    offsets: std::sync::Mutex<Vec<usize>>,
}

impl PagedComicVine {
    fn new(volume: i32, total: usize, malformed_offset: Option<usize>) -> Arc<Self> {
        Arc::new(Self {
            volume,
            total,
            malformed_offset,
            in_flight: Arc::new(AtomicUsize::new(0)),
            peak: AtomicUsize::new(0),
            offsets: std::sync::Mutex::new(Vec::new()),
        })
    }

    fn payload(&self, path: &str) -> Value {
        if path.starts_with(&format!("/api/volume/4050-{}/", self.volume)) {
            return json!({"status_code": 1, "error": "OK", "results": {"id": self.volume, "name": "Paged"}});
        }
        let offset: usize = path
            .split('&')
            .find_map(|part| part.strip_prefix("offset="))
            .unwrap()
            .parse()
            .unwrap();
        self.offsets.lock().unwrap().push(offset);
        if Some(offset) == self.malformed_offset {
            return json!({"status_code": 1, "error": "OK", "number_of_total_results": self.total});
        }
        let end = (offset + 100).min(self.total);
        let results: Vec<Value> = (offset..end)
            .map(|n| json!({"id": 500_000 + n, "issue_number": (n + 1).to_string(), "volume": {"id": self.volume}}))
            .collect();
        json!({"status_code": 1, "error": "OK", "number_of_total_results": self.total, "results": results})
    }
}

impl OutboundHttp for PagedComicVine {
    fn send(&self, _host: &str, request: OutboundRequest) -> OutboundFuture {
        let body = self.payload(&request.path).to_string();
        // Only roster pages count toward the fan-out peak; the overlapping
        // volume read is a separate provider call.
        let page = request.path.starts_with("/api/issues/");
        if page {
            let now = self.in_flight.fetch_add(1, Ordering::SeqCst) + 1;
            self.peak.fetch_max(now, Ordering::SeqCst);
        }
        let counter = Arc::clone(&self.in_flight);
        Box::pin(async move {
            tokio::task::yield_now().await;
            if page {
                counter.fetch_sub(1, Ordering::SeqCst);
            }
            Ok::<_, OutboundError>(OutboundResponse {
                status: http::StatusCode::OK,
                headers: http::HeaderMap::new(),
                body: Body::from(body),
            })
        })
    }

    fn is_fake(&self) -> bool {
        true
    }

    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
}

async fn paged_state(prefix: &str, fake: &Arc<PagedComicVine>) -> Session {
    let outbound: Arc<dyn OutboundHttp> = fake.clone();
    setup_user_with(prefix, Some(outbound)).await
}

fn issue_numbers(body: &Value) -> Vec<String> {
    body.as_array()
        .unwrap()
        .iter()
        .map(|issue| issue["issue_number"].as_str().unwrap().to_owned())
        .collect()
}

/// Python `fetch_volume_issues` fetches the first page alone, then the
/// remaining fixed offsets four at a time. A 1,250-row roster is 13 pages: the
/// 12 remaining pages must overlap (peak 4 in flight, never more), and the
/// rows must come back complete and in offset order on both roster readers
/// (series issues and volume resolve).
#[tokio::test]
async fn roster_pages_are_fetched_four_at_a_time_in_offset_order() {
    let paged = PagedComicVine::new(77, 1250, None);
    let (state, token, csrf, _guard) = paged_state("cvv2-fanout", &paged).await;
    set_key(true);
    let expected: Vec<String> = (1..=1250).map(|n| n.to_string()).collect();
    let (status, body) = send(
        &state,
        get("/api/v2/comicvine/series/77/issues", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["series_name"], "Paged");
    assert_eq!(
        issue_numbers(&body["issues"]),
        expected,
        "pages are assembled in offset order"
    );
    assert_eq!(
        paged.peak.load(Ordering::SeqCst),
        4,
        "remaining pages are fetched concurrently, at most four at a time"
    );
    let mut offsets = paged.offsets.lock().unwrap().clone();
    assert_eq!(offsets[0], 0, "the first page is fetched alone first");
    offsets.sort_unstable();
    assert_eq!(offsets, (0..13).map(|page| page * 100).collect::<Vec<_>>());

    // The volume resolve reads the same roster (served from the cache here,
    // so no further page requests).
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/resolve?input=https%3A%2F%2Fcomicvine.gamespot.com%2Fx%2F4050-77%2F",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["volume"]["name"], "Paged");
    assert_eq!(issue_numbers(&body["issues"]), expected);
    assert_eq!(paged.offsets.lock().unwrap().len(), 13);
}

/// Python `_fetch_volume_issue_page` raises on a page without a `results`
/// list. A malformed later page fails the whole roster rather than
/// truncating it (#4635551195): the browse route degrades to an empty roster
/// (Python catches the error there) instead of answering the first 100 rows.
#[tokio::test]
async fn malformed_roster_pages_fail_the_roster_instead_of_truncating_it() {
    let paged = PagedComicVine::new(88, 200, Some(100));
    let (state, token, csrf, _guard) = paged_state("cvv2-malformed", &paged).await;
    set_key(true);
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/series/88/issues?series_name=Named",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["series_name"], "Named");
    assert_eq!(body["issues"], json!([]));
    let (status, body) = send(
        &state,
        get(
            "/api/v2/comicvine/resolve?input=https%3A%2F%2Fcomicvine.gamespot.com%2Fx%2F4050-88%2F",
            &token,
            &csrf,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["volume"]["name"], "Paged");
    assert_eq!(body["issues"], json!([]));
}
