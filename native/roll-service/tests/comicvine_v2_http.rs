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

/// `(state, bearer token, csrf token, user id, reset guard)`.
type Session = (
    Arc<AppState>,
    String,
    String,
    i32,
    tokio::sync::MutexGuard<'static, ()>,
);

fn unique_suffix() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos()
}

async fn setup_user(prefix: &str) -> Session {
    setup_user_with(prefix, 2, None).await
}

/// Every test holds the `reset_for_test` guard for its whole body, which
/// also serializes the process-wide `COMICVINE_API_KEY` toggled by `set_key`.
/// `pool_size` above 2 lets lock tests overlap real transactions (a 2-slot
/// pool serialized them, #4631578582).
async fn setup_user_with(
    prefix: &str,
    pool_size: usize,
    outbound: Option<Arc<dyn OutboundHttp>>,
) -> Session {
    let url = test_support::database_url().await;
    let mut app = test_support::test_app_state(
        Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-roll-routes-secret".into()),
            "RUST_ROLL_POOL_SIZE" => Some(pool_size.to_string()),
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
    let (state, _token, _csrf, _user, _guard) = setup_user("cvv2-auth").await;
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
    let (state, token, csrf, _user, _guard) = setup_user("cvv2-validation").await;
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
    let (state, token, csrf, _user, _guard) = setup_user("cvv2-nokey").await;
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
    let (state, token, csrf, _user, _guard) = setup_user("cvv2-search").await;
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
    let (state, token, csrf, _user, _guard) = setup_user("cvv2-search-bound").await;
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
    let (state, token, csrf, _user, _guard) = setup_user("cvv2-search-fail").await;
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
    let (state, token, csrf, _user, _guard) = setup_user("cvv2-limits").await;
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

/// Python `ComicVineClient` throttle statuses (#4637589533): HTTP 420 is a
/// throttle like 429 (a header-less one still cools the bucket down), while
/// 403 is a plain provider error that records no cooldown.
#[tokio::test]
async fn http_420_cools_the_bucket_down_but_403_does_not() {
    let (state, token, csrf, _user, _guard) = setup_user("cvv2-420").await;
    set_key(true);
    fake(&state).push_ok(
        http::StatusCode::FORBIDDEN,
        http::HeaderMap::new(),
        Bytes::new(),
    );
    let (status, _) = send(
        &state,
        get("/api/v2/comicvine/search/series?q=forbidden", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
    provider_ok(&state, json!({"results": [{"id": 3, "name": "After 403"}]}));
    let (status, body) = send(
        &state,
        get("/api/v2/comicvine/search/series?q=after", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "a 403 must not start a cooldown");
    assert_eq!(body["results"][0]["name"], "After 403");

    fake(&state).push_ok(
        http::StatusCode::from_u16(420).unwrap(),
        http::HeaderMap::new(),
        Bytes::new(),
    );
    let (status, _) = send(
        &state,
        get("/api/v2/comicvine/search/series?q=slow", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
    let calls = fake(&state).calls().len();
    let (status, _) = send(
        &state,
        get("/api/v2/comicvine/search/series?q=blocked", &token, &csrf),
    )
    .await;
    assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
    assert_eq!(
        fake(&state).calls().len(),
        calls,
        "a header-less 420 cools the search bucket down"
    );
}

#[tokio::test]
async fn resolve_classifies_input_and_resolves_issue_links() {
    let (state, token, csrf, _user, _guard) = setup_user("cvv2-resolve").await;
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
    let (state, token, csrf, _user, _guard) = setup_user("cvv2-resolve-volume").await;
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
    let (state, token, csrf, _user, _guard) = setup_user("cvv2-series").await;
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
    let (state, token, csrf, _user, _guard) = setup_user("cvv2-roster").await;
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
    setup_user_with(prefix, 2, Some(outbound)).await
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
    let (state, token, csrf, _user, _guard) = paged_state("cvv2-fanout", &paged).await;
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
    let (state, token, csrf, _user, _guard) = paged_state("cvv2-malformed", &paged).await;
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

// ---------------------------------------------------------------------------
// Chunk B: owner-scoped identity and correction reads.
// ---------------------------------------------------------------------------

type Conn = deadpool_postgres::Object;

async fn thread(conn: &Conn, user_id: i32, title: &str) -> i32 {
    conn.query_one(
        "INSERT INTO threads (title, format, issues_remaining, total_issues, queue_position, \
         status, user_id) VALUES ($1, 'Comic', 1, 1, 1, 'active', $2) RETURNING id",
        &[&title, &user_id],
    )
    .await
    .unwrap()
    .get(0)
}

async fn issue(conn: &Conn, thread_id: i32, number: &str, position: i32) -> i32 {
    conn.query_one(
        "INSERT INTO issues (thread_id, issue_number, status, created_at, position) \
         VALUES ($1, $2, 'unread', NOW(), $3) RETURNING id",
        &[&thread_id, &number, &position],
    )
    .await
    .unwrap()
    .get(0)
}

/// Seed one ComicVine identity mapping with a fixed `created_at`.
async fn mapping(
    conn: &Conn,
    issue_id: i32,
    comicvine_id: &str,
    status: &str,
    confidence: Option<f64>,
    created_at: &str,
) -> i32 {
    let identity: i32 = conn
        .query_one(
            "INSERT INTO external_identities \
                (provider, entity_type, external_id, external_url, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'issue', $1, NULL, '{}'::json, now(), now()) \
             ON CONFLICT ON CONSTRAINT uq_external_identity_provider_entity \
             DO UPDATE SET updated_at = now() RETURNING id",
            &[&comicvine_id],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO issue_external_identity_mappings \
            (issue_id, external_identity_id, status, evidence_source, evidence_json, confidence, \
             created_at, updated_at) \
         VALUES ($1, $2, $3, 'seed', '{}'::json, $4, $5::text::timestamptz, now())",
        &[&issue_id, &identity, &status, &confidence, &created_at],
    )
    .await
    .unwrap();
    identity
}

async fn correction(
    conn: &Conn,
    issue_id: i32,
    user_id: i32,
    field: &str,
    created_at: &str,
    reverted: bool,
) -> i32 {
    // `name` rows carry no provider value; others echo the field name.
    let provider_value = (field != "name").then_some(field);
    let canonical = field.to_uppercase();
    conn.query_one(
        "INSERT INTO issue_metadata_corrections \
            (issue_id, field_name, provider_value, canonical_value, provenance, created_by, \
             reverted_at, created_at, updated_at) \
         VALUES ($1, $2, $3, $4, 'user_correction', $5, \
                 CASE WHEN $6 THEN now() END, $7::text::timestamptz, now()) RETURNING id",
        &[
            &issue_id,
            &field,
            &provider_value,
            &canonical,
            &user_id,
            &reverted,
            &created_at,
        ],
    )
    .await
    .unwrap()
    .get(0)
}

#[tokio::test]
async fn identity_state_reads_seeded_mappings_like_python() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-identity-read").await;
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Saga").await;
    let i = issue(&conn, t, "1", 1).await;
    let path = format!("/api/v2/comicvine/issues/{i}/identity");

    let (status, body) = send(&state, get(&path, &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body,
        json!({"issue_id": i, "thread_id": t, "thread_title": "Saga",
               "has_confirmed_identity": false, "comicvine_issue_id": null,
               "confirmed_mappings": [], "candidate_mappings": [], "has_unresolved": false})
    );

    let low = mapping(
        &conn,
        i,
        "300",
        "candidate",
        Some(0.4),
        "2026-01-02T03:04:05Z",
    )
    .await;
    let confirmed = mapping(
        &conn,
        i,
        "100",
        "confirmed",
        Some(1.0),
        "2026-01-02T03:04:05.123456Z",
    )
    .await;
    let unscored = mapping(&conn, i, "400", "candidate", None, "2026-01-02T03:04:05.5Z").await;
    let high = mapping(
        &conn,
        i,
        "200",
        "candidate",
        Some(0.9),
        "2026-01-02T03:04:05Z",
    )
    .await;
    mapping(&conn, i, "500", "unresolved", None, "2026-01-02T03:04:05Z").await;
    mapping(
        &conn,
        i,
        "600",
        "rejected",
        Some(0.1),
        "2026-01-02T03:04:05Z",
    )
    .await;

    let (status, body) = send(&state, get(&path, &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    // Confidence DESC NULLS LAST; Pydantic datetime JSON: `Z`, fraction only
    // when present. Rejected rows are not listed and only `unresolved` sets
    // the flag.
    assert_eq!(
        body,
        json!({"issue_id": i, "thread_id": t, "thread_title": "Saga",
               "has_confirmed_identity": true, "comicvine_issue_id": "100",
               "confirmed_mappings": [
                   {"external_identity_id": confirmed, "provider": "comicvine", "comicvine_id": "100",
                    "status": "confirmed", "confidence": 1.0, "evidence_source": "seed",
                    "created_at": "2026-01-02T03:04:05.123456Z"}],
               "candidate_mappings": [
                   {"external_identity_id": high, "provider": "comicvine", "comicvine_id": "200",
                    "status": "candidate", "confidence": 0.9, "evidence_source": "seed",
                    "created_at": "2026-01-02T03:04:05Z"},
                   {"external_identity_id": low, "provider": "comicvine", "comicvine_id": "300",
                    "status": "candidate", "confidence": 0.4, "evidence_source": "seed",
                    "created_at": "2026-01-02T03:04:05Z"},
                   {"external_identity_id": unscored, "provider": "comicvine", "comicvine_id": "400",
                    "status": "candidate", "confidence": null, "evidence_source": "seed",
                    "created_at": "2026-01-02T03:04:05.500000Z"}],
               "has_unresolved": true})
    );
}

#[tokio::test]
async fn corrections_list_reads_active_rows_oldest_first() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-corrections-read").await;
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Saga").await;
    let i = issue(&conn, t, "1", 1).await;
    let other = issue(&conn, t, "2", 2).await;
    let path = format!("/api/v2/comicvine/issues/{i}/metadata:corrections");

    let (status, body) = send(&state, get(&path, &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body, json!({"issue_id": i, "corrections": []}));

    let later = correction(&conn, i, user_id, "name", "2026-03-01T00:00:00Z", false).await;
    let first = correction(
        &conn,
        i,
        user_id,
        "cover_date",
        "2026-02-01T00:00:00.25Z",
        false,
    )
    .await;
    correction(
        &conn,
        i,
        user_id,
        "store_date",
        "2026-01-01T00:00:00Z",
        true,
    )
    .await;
    correction(&conn, other, user_id, "name", "2026-01-01T00:00:00Z", false).await;

    let (status, body) = send(&state, get(&path, &token, &csrf)).await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(
        body,
        json!({"issue_id": i, "corrections": [
            {"id": first, "field_name": "cover_date", "provider_value": "cover_date",
             "canonical_value": "COVER_DATE", "provenance": "user_correction",
             "created_by": user_id, "created_at": "2026-02-01T00:00:00.250000Z"},
            {"id": later, "field_name": "name", "provider_value": null,
             "canonical_value": "NAME", "provenance": "user_correction",
             "created_by": user_id, "created_at": "2026-03-01T00:00:00Z"}]})
    );
}

/// Python `get_owned_issue_or_404`: another reader's issue and a missing
/// issue are both `404 {"detail": "Issue <id> not found"}`; nothing leaks.
#[tokio::test]
async fn identity_reads_are_owner_scoped() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-identity-owner").await;
    let (other_token, other_csrf, _other) =
        register_extra_user(&state, "cvv2-identity-other").await;
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Mine").await;
    let i = issue(&conn, t, "1", 1).await;
    mapping(
        &conn,
        i,
        "100",
        "confirmed",
        Some(1.0),
        "2026-01-02T03:04:05Z",
    )
    .await;
    correction(&conn, i, user_id, "name", "2026-01-01T00:00:00Z", false).await;
    for suffix in ["identity", "metadata:corrections"] {
        let path = format!("/api/v2/comicvine/issues/{i}/{suffix}");
        let (status, _) = send(&state, get(&path, &token, &csrf)).await;
        assert_eq!(status, StatusCode::OK, "{path}");
        let (status, body) = send(&state, get(&path, &other_token, &other_csrf)).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{path}: {body:?}");
        assert_eq!(body, json!({"detail": format!("Issue {i} not found")}));
        let missing = i + 1000;
        let (status, body) = send(
            &state,
            get(
                &format!("/api/v2/comicvine/issues/{missing}/{suffix}"),
                &token,
                &csrf,
            ),
        )
        .await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{suffix}: {body:?}");
        assert_eq!(
            body,
            json!({"detail": format!("Issue {missing} not found")})
        );
    }
}

#[tokio::test]
async fn identity_reads_require_auth_and_use_the_validation_contract() {
    let (state, token, csrf, _user, _guard) = setup_user("cvv2-identity-contract").await;
    for path in [
        "/api/v2/comicvine/issues/1/identity",
        "/api/v2/comicvine/issues/1/metadata:corrections",
    ] {
        let request = Request::builder()
            .method("GET")
            .uri(path)
            .body(Body::empty())
            .unwrap();
        let (status, body) = send(&state, request).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED, "{path}: {body:?}");
    }
    for path in [
        "/api/v2/comicvine/issues/abc/identity",
        "/api/v2/comicvine/issues/1.5/identity",
        "/api/v2/comicvine/issues/abc/metadata:corrections",
    ] {
        let (status, body) = send(&state, get(path, &token, &csrf)).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{path}: {body:?}");
        assert_eq!(body, json!({"detail": "Validation failed"}), "{path}");
    }
}

// ---------------------------------------------------------------------------
// Chunk C: identity and correction writes.
// ---------------------------------------------------------------------------

fn call(method: &str, path: &str, token: &str, csrf: &str, body: Option<Value>) -> Request<Body> {
    let builder = Request::builder()
        .method(method)
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {token}"))
        .header("x-csrf-token", csrf)
        .header(header::COOKIE, format!("csrf_token={csrf}"));
    match body {
        Some(body) => builder
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(body.to_string()))
            .unwrap(),
        None => builder.body(Body::empty()).unwrap(),
    }
}

#[tokio::test]
async fn identity_writes_require_authentication_and_csrf() {
    let (state, token, _csrf, _user, _guard) = setup_user("cvv2-write-auth").await;
    for (method, path) in [
        ("DELETE", "/api/v2/comicvine/issues/1/identity"),
        ("POST", "/api/v2/comicvine/issues/1/identity:confirm"),
        ("POST", "/api/v2/comicvine/issues/1/identity:replace"),
        ("POST", "/api/v2/comicvine/issues/1/metadata:correct"),
        ("POST", "/api/v2/comicvine/issues/1/metadata:revert"),
        ("POST", "/api/v2/comicvine/issues/1/metadata:refresh"),
    ] {
        // Unauthenticated, with a matching CSRF pair so only auth can reject.
        let request = Request::builder()
            .method(method)
            .uri(path)
            .header("x-csrf-token", "pair")
            .header(header::COOKIE, "csrf_token=pair")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from("{}"))
            .unwrap();
        let (status, body) = send(&state, request).await;
        assert_eq!(
            status,
            StatusCode::UNAUTHORIZED,
            "{method} {path}: {body:?}"
        );
        // Authenticated but missing the CSRF pair: 403 before any handler work.
        let request = Request::builder()
            .method(method)
            .uri(path)
            .header(header::AUTHORIZATION, format!("Bearer {token}"))
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from("{}"))
            .unwrap();
        let (status, body) = send(&state, request).await;
        assert_eq!(status, StatusCode::FORBIDDEN, "{method} {path}: {body:?}");
    }
    let conn = state.pool.get().await.unwrap();
    let written: i64 = conn
        .query_one(
            "SELECT (SELECT count(*) FROM issue_external_identity_mappings) \
                  + (SELECT count(*) FROM issue_metadata_corrections)",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(written, 0, "rejected requests never write");
}

#[tokio::test]
async fn identity_confirm_replace_remove_flow_matches_python() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-identity").await;
    set_key(false);
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Saga").await;
    let i = issue(&conn, t, "1", 1).await;
    let base = format!("/api/v2/comicvine/issues/{i}");

    // Empty state.
    let (status, body) = send(
        &state,
        call("GET", &format!("{base}/identity"), &token, &csrf, None),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["issue_id"], i);
    assert_eq!(body["thread_id"], t);
    assert_eq!(body["thread_title"], "Saga");
    assert_eq!(body["has_confirmed_identity"], false);
    assert_eq!(body["comicvine_issue_id"], Value::Null);
    assert_eq!(body["confirmed_mappings"], json!([]));
    assert_eq!(body["has_unresolved"], false);

    // Removing before confirming: 400 with the Python message.
    let (status, body) = send(
        &state,
        call("DELETE", &format!("{base}/identity"), &token, &csrf, None),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(
        body["detail"],
        format!("No confirmed ComicVine identity mapping found for issue {i}")
    );

    // Confirm.
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/identity:confirm"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 1111})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["has_confirmed_identity"], true);
    assert_eq!(body["comicvine_issue_id"], "1111");
    let mapping = &body["confirmed_mappings"][0];
    assert_eq!(mapping["provider"], "comicvine");
    assert_eq!(mapping["comicvine_id"], "1111");
    assert_eq!(mapping["status"], "confirmed");
    assert_eq!(mapping["confidence"], 1.0);
    assert_eq!(mapping["evidence_source"], "user_confirmed");
    assert!(mapping["created_at"].as_str().unwrap().ends_with('Z'));
    // Confirming queues exactly one deep-metadata refresh for the identity.
    let queued: i64 = conn
        .query_one(
            "SELECT count(*) FROM comicvine_metadata_refresh_requests WHERE state = 'pending'",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(queued, 1);
    // Re-confirming the same id is idempotent and does not queue a second job.
    let (status, _) = send(
        &state,
        call(
            "POST",
            &format!("{base}/identity:confirm"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 1111})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let queued: i64 = conn
        .query_one(
            "SELECT count(*) FROM comicvine_metadata_refresh_requests",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(queued, 1);

    // A different confirmed id on the same issue is a 400, not a silent swap.
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/identity:confirm"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 2222})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(
        body["detail"],
        "issue already has a confirmed comicvine identity"
    );

    // Replace rejects the old mapping (with the reason) and confirms the new one.
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/identity:replace"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 2222, "reason": "wrong volume"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["comicvine_issue_id"], "2222");
    assert_eq!(body["confirmed_mappings"].as_array().unwrap().len(), 1);
    let rejected: (String, Option<String>) = {
        let row = conn
            .query_one(
                "SELECT m.status, m.rejection_reason FROM issue_external_identity_mappings m \
                 JOIN external_identities e ON e.id = m.external_identity_id \
                 WHERE m.issue_id = $1 AND e.external_id = '1111'",
                &[&i],
            )
            .await
            .unwrap();
        (row.get(0), row.get(1))
    };
    assert_eq!(
        rejected,
        ("rejected".to_owned(), Some("wrong volume".to_owned()))
    );

    // Refresh reports the confirmed id.
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/metadata:refresh"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body,
        json!({"issue_id": i, "refreshed": true, "comicvine_issue_id": "2222"})
    );

    // Remove: mapping becomes unresolved with evidence and confidence cleared.
    let (status, body) = send(
        &state,
        call("DELETE", &format!("{base}/identity"), &token, &csrf, None),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["has_confirmed_identity"], false);
    assert_eq!(body["has_unresolved"], true);
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/metadata:refresh"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body,
        json!({"issue_id": i, "refreshed": false, "comicvine_issue_id": null})
    );

    // Replace with the default reason when none is supplied.
    let (status, _) = send(
        &state,
        call(
            "POST",
            &format!("{base}/identity:confirm"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 3333})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let (status, _) = send(
        &state,
        call(
            "POST",
            &format!("{base}/identity:replace"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 4444})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let reason: Option<String> = conn
        .query_one(
            "SELECT m.rejection_reason FROM issue_external_identity_mappings m \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE m.issue_id = $1 AND e.external_id = '3333'",
            &[&i],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(reason.as_deref(), Some("replaced by user"));
}

#[tokio::test]
async fn identity_mutations_are_owner_scoped() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-owner").await;
    set_key(false);
    let (other_token, other_csrf, other_id) = register_extra_user(&state, "cvv2-other").await;
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Mine").await;
    let i = issue(&conn, t, "1", 1).await;
    let base = format!("/api/v2/comicvine/issues/{i}");
    let _ = other_id;
    let missing = format!("Issue {i} not found");
    for (method, path, body) in [
        ("GET", format!("{base}/identity"), None),
        ("DELETE", format!("{base}/identity"), None),
        (
            "POST",
            format!("{base}/identity:confirm"),
            Some(json!({"comicvine_issue_id": 5})),
        ),
        (
            "POST",
            format!("{base}/identity:replace"),
            Some(json!({"comicvine_issue_id": 5})),
        ),
        ("POST", format!("{base}/metadata:refresh"), None),
        (
            "POST",
            format!("{base}/metadata:correct"),
            Some(json!({"field_name": "name", "canonical_value": "x"})),
        ),
        ("GET", format!("{base}/metadata:corrections"), None),
        (
            "POST",
            format!("{base}/metadata:revert"),
            Some(json!({"correction_id": 1})),
        ),
    ] {
        let (status, resp) =
            send(&state, call(method, &path, &other_token, &other_csrf, body)).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{method} {path}: {resp:?}");
        assert_eq!(resp["detail"], missing, "{method} {path}");
    }
    // Nothing was written for the non-owner.
    let count: i64 = conn
        .query_one("SELECT count(*) FROM issue_external_identity_mappings", &[])
        .await
        .unwrap()
        .get(0);
    assert_eq!(count, 0);
    let _ = (token, csrf);
}

#[tokio::test]
async fn concurrent_confirms_leave_exactly_one_confirmed_identity() {
    let (state, token, csrf, user_id, _guard) = setup_user_with("cvv2-race", 8, None).await;
    set_key(false);
    // An 8-connection pool lets the four transactions really overlap; the
    // reader's queue lock is what serializes them (#4631578582).
    let (t, i) = {
        let conn = state.pool.get().await.unwrap();
        let t = thread(&conn, user_id, "Race").await;
        let i = issue(&conn, t, "1", 1).await;
        (t, i)
    };
    let _ = t;
    let path = format!("/api/v2/comicvine/issues/{i}/identity:confirm");
    let mut handles = Vec::new();
    for cv in [7001, 7002, 7003, 7004] {
        let state = state.clone();
        let (token, csrf, path) = (token.clone(), csrf.clone(), path.clone());
        handles.push(tokio::spawn(async move {
            send(
                &state,
                call(
                    "POST",
                    &path,
                    &token,
                    &csrf,
                    Some(json!({"comicvine_issue_id": cv})),
                ),
            )
            .await
        }));
    }
    let mut ok = 0;
    for handle in handles {
        let (status, body) = handle.await.unwrap();
        match status {
            StatusCode::OK => ok += 1,
            StatusCode::BAD_REQUEST => {
                assert_eq!(
                    body["detail"],
                    "issue already has a confirmed comicvine identity"
                )
            }
            other => panic!("unexpected {other}: {body:?}"),
        }
    }
    assert_eq!(ok, 1, "exactly one concurrent confirm may win");
    let conn = state.pool.get().await.unwrap();
    let confirmed: i64 = conn
        .query_one(
            "SELECT count(*) FROM issue_external_identity_mappings WHERE issue_id = $1 AND status = 'confirmed'",
            &[&i],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(confirmed, 1);
}

#[tokio::test]
async fn metadata_corrections_apply_list_revert() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-corr").await;
    set_key(false);
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Corr").await;
    let i = issue(&conn, t, "1", 1).await;
    let identity: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, \
             created_at, updated_at) VALUES ('comicvine', 'issue', '9001', $1, NOW(), NOW()) RETURNING id",
            &[&json!({"name": "Provider Name"})],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, \
         created_at, updated_at, evidence_json) VALUES ($1, $2, 'confirmed', NOW(), NOW(), '{}'::json)",
        &[&i, &identity],
    )
    .await
    .unwrap();
    let base = format!("/api/v2/comicvine/issues/{i}");

    let (status, body) = send(
        &state,
        call(
            "GET",
            &format!("{base}/metadata:corrections"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, json!({"issue_id": i, "corrections": []}));

    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/metadata:correct"),
            &token,
            &csrf,
            Some(json!({"field_name": "name", "canonical_value": "My Name", "reason": "typo"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let correction = &body["corrections"][0];
    assert_eq!(correction["field_name"], "name");
    assert_eq!(correction["provider_value"], "Provider Name");
    assert_eq!(correction["canonical_value"], "My Name");
    assert_eq!(correction["provenance"], "user_correction");
    assert_eq!(correction["created_by"], user_id);
    assert!(correction["created_at"].as_str().unwrap().ends_with('Z'));
    let cid = correction["id"].as_i64().unwrap();

    // A field the provider never supplied stores no provider value.
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/metadata:correct"),
            &token,
            &csrf,
            Some(json!({"field_name": "cover_date", "canonical_value": "2020-01-01"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["corrections"][1]["provider_value"], Value::Null);

    // Revert is soft; a second revert of the same id is a 400.
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/metadata:revert"),
            &token,
            &csrf,
            Some(json!({"correction_id": cid})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["corrections"].as_array().unwrap().len(), 1);
    let (status, body) = send(
        &state,
        call(
            "POST",
            &format!("{base}/metadata:revert"),
            &token,
            &csrf,
            Some(json!({"correction_id": cid})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["detail"], format!("Correction {cid} not found"));
}

#[tokio::test]
async fn identity_removal_and_readd_leave_thread_series_metadata_untouched() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-5487").await;
    set_key(false);
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Superman").await;
    let i = issue(&conn, t, "4", 1).await;
    let metadata = json!({"volume": {"id": 4050, "name": "Superman (2018)"}, "publisher": {"name": "DC Comics"}, "start_year": 2023});
    let series_identity: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, \
             created_at, updated_at) VALUES ('comicvine', 'series', '4050', $1, NOW(), NOW()) RETURNING id",
            &[&metadata],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO thread_external_series_mappings (thread_id, external_identity_id, status, \
         confidence, created_at, updated_at) VALUES ($1, $2, 'confirmed', 1.0, NOW(), NOW())",
        &[&t, &series_identity],
    )
    .await
    .unwrap();
    let snapshot = |conn: Conn| async move {
        let row = conn
            .query_one(
                "SELECT m.status, m.confidence, e.metadata_json FROM thread_external_series_mappings m \
                 JOIN external_identities e ON e.id = m.external_identity_id WHERE m.thread_id = $1",
                &[&t],
            )
            .await
            .unwrap();
        (
            row.get::<_, String>(0),
            row.get::<_, Option<f64>>(1),
            row.get::<_, Value>(2),
        )
    };
    let before = snapshot(state.pool.get().await.unwrap()).await;
    let base = format!("/api/v2/comicvine/issues/{i}/identity");
    for step in 0..2 {
        let (status, _) = send(
            &state,
            call(
                "POST",
                &format!("{base}:confirm"),
                &token,
                &csrf,
                Some(json!({"comicvine_issue_id": 8800 + step})),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        let (status, _) = send(&state, call("DELETE", &base, &token, &csrf, None)).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(snapshot(state.pool.get().await.unwrap()).await, before);
    }
}

type Pending = tokio::task::JoinHandle<(StatusCode, Value)>;

/// Deterministic signal that `expected` requests are blocked on the reader's
/// queue advisory lock: poll `pg_locks` for ungranted waiters on that exact
/// key. No sleeps or deadlines. A writer that skips the queue lock never
/// becomes a waiter and instead runs to completion, which fails the test
/// immediately instead of hanging it.
async fn wait_for_queue_lock_waiters(
    tx: &deadpool_postgres::Transaction<'_>,
    user_id: i32,
    expected: i64,
    pending: &[&Pending],
) {
    loop {
        let waiting: i64 = tx
            .query_one(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted \
                 AND classid = 699001 AND objid = $1::int4::oid",
                &[&user_id],
            )
            .await
            .unwrap()
            .get(0);
        if waiting >= expected {
            return;
        }
        assert!(
            pending.iter().all(|handle| !handle.is_finished()),
            "a writer finished while the reader's queue lock was held: it never took the queue lock"
        );
        tokio::task::yield_now().await;
    }
}

async fn hold_queue_lock(
    conn: &mut deadpool_postgres::Object,
    user_id: i32,
) -> deadpool_postgres::Transaction<'_> {
    let tx = conn.transaction().await.unwrap();
    tx.execute(
        "SELECT pg_advisory_xact_lock($1, $2)",
        &[&699001_i32, &user_id],
    )
    .await
    .unwrap();
    tx
}

fn spawn_send(state: &Arc<AppState>, request: Request<Body>) -> Pending {
    let state = state.clone();
    tokio::spawn(async move { send(&state, request).await })
}

/// Holds the reader's queue advisory lock in one session and proves a request
/// is blocked on it BEFORE it takes any thread/issue row lock (lock order:
/// queue lock first, then row locks; #5398/#5419). While the request waits, a
/// second session must still be able to `FOR UPDATE NOWAIT` the issue row.
async fn assert_queue_lock_precedes_row_locks(
    state: &Arc<AppState>,
    user_id: i32,
    issue_id: i32,
    request: Request<Body>,
) -> (StatusCode, Value) {
    let mut holder = state.pool.get().await.unwrap();
    let tx = hold_queue_lock(&mut holder, user_id).await;
    let pending = spawn_send(state, request);
    wait_for_queue_lock_waiters(&tx, user_id, 1, &[&pending]).await;
    tx.query_one(
        "SELECT id FROM issues WHERE id = $1 FOR UPDATE NOWAIT",
        &[&issue_id],
    )
    .await
    .expect("writer took an issue row lock before the queue lock");
    tx.commit().await.unwrap();
    drop(holder);
    pending.await.unwrap()
}

#[tokio::test]
async fn identity_writers_take_the_queue_lock_before_row_locks() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-lockorder").await;
    set_key(false);
    let (t, i) = {
        let conn = state.pool.get().await.unwrap();
        let t = thread(&conn, user_id, "Locks").await;
        (t, issue(&conn, t, "1", 1).await)
    };
    let _ = t;
    let (status, body) = assert_queue_lock_precedes_row_locks(
        &state,
        user_id,
        i,
        call(
            "POST",
            &format!("/api/v2/comicvine/issues/{i}/identity:confirm"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 9101})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let (status, body) = assert_queue_lock_precedes_row_locks(
        &state,
        user_id,
        i,
        call(
            "POST",
            &format!("/api/v2/comicvine/issues/{i}/identity:replace"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 9102, "reason": "wrong"})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    let (status, body) = assert_queue_lock_precedes_row_locks(
        &state,
        user_id,
        i,
        call(
            "DELETE",
            &format!("/api/v2/comicvine/issues/{i}/identity"),
            &token,
            &csrf,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["has_confirmed_identity"], false);
}
#[tokio::test]
async fn confirmation_reopens_finished_refresh_jobs_instead_of_failing() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-refresh").await;
    set_key(false);
    for (n, finished) in ["failed", "completed", "no_credits"]
        .into_iter()
        .enumerate()
    {
        let cv = 9200 + n as i32;
        let conn = state.pool.get().await.unwrap();
        let t = thread(&conn, user_id, &format!("Refresh {finished}")).await;
        let i = issue(&conn, t, "1", 1).await;
        let identity: i32 = conn
            .query_one(
                "INSERT INTO external_identities (provider, entity_type, external_id, external_url, \
                 metadata_json, created_at, updated_at) \
                 VALUES ('comicvine', 'issue', $1, 'https://comicvine.gamespot.com/', '{}'::jsonb, now(), now()) \
                 RETURNING id",
                &[&cv.to_string()],
            )
            .await
            .unwrap()
            .get(0);
        conn.execute(
            "INSERT INTO comicvine_metadata_refresh_requests \
                (external_identity_id, state, attempts, next_attempt_at, last_error, completed_at, \
                 created_at, updated_at) \
             VALUES ($1, $2, 4, now() + interval '1 day', 'old', now(), now(), now())",
            &[&identity, &finished],
        )
        .await
        .unwrap();
        drop(conn);
        let (status, body) = send(
            &state,
            call(
                "POST",
                &format!("/api/v2/comicvine/issues/{i}/identity:confirm"),
                &token,
                &csrf,
                Some(json!({"comicvine_issue_id": cv})),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{finished}: {body:?}");
        assert_eq!(body["has_confirmed_identity"], true);
        let conn = state.pool.get().await.unwrap();
        let row = conn
            .query_one(
                "SELECT state, attempts, last_error, completed_at IS NULL \
                 FROM comicvine_metadata_refresh_requests WHERE external_identity_id = $1",
                &[&identity],
            )
            .await
            .unwrap();
        assert_eq!(row.get::<_, String>(0), "pending", "{finished}");
        assert_eq!(row.get::<_, i32>(1), 0);
        assert_eq!(row.get::<_, Option<String>>(2), None);
        assert!(row.get::<_, bool>(3));
    }
}

#[tokio::test]
async fn identity_writers_serialize_with_sibling_queue_writers() {
    let (state, token, csrf, user_id, _guard) = setup_user_with("cvv2-siblings", 8, None).await;
    set_key(false);
    let (confirm_issue, deleted_issue) = {
        let conn = state.pool.get().await.unwrap();
        let t = thread(&conn, user_id, "Siblings").await;
        (issue(&conn, t, "1", 1).await, issue(&conn, t, "2", 2).await)
    };
    let mut holder = state.pool.get().await.unwrap();
    let tx = hold_queue_lock(&mut holder, user_id).await;
    let confirm = spawn_send(
        &state,
        call(
            "POST",
            &format!("/api/v2/comicvine/issues/{confirm_issue}/identity:confirm"),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": 9301})),
        ),
    );
    let delete = spawn_send(
        &state,
        call(
            "DELETE",
            &format!("/api/v2/issues/{deleted_issue}"),
            &token,
            &csrf,
            None,
        ),
    );
    wait_for_queue_lock_waiters(&tx, user_id, 2, &[&confirm, &delete]).await;
    tx.commit().await.unwrap();
    drop(holder);
    let (status, body) = confirm.await.unwrap();
    assert_eq!(status, StatusCode::OK, "{body:?}");
    assert_eq!(body["comicvine_issue_id"], "9301");
    let (status, body) = delete.await.unwrap();
    assert_eq!(status, StatusCode::NO_CONTENT, "{body:?}");
    let conn = state.pool.get().await.unwrap();
    let remaining: i64 = conn
        .query_one(
            "SELECT count(*) FROM issues WHERE id = $1",
            &[&deleted_issue],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(remaining, 0, "the sibling issue delete committed");
}
#[tokio::test]
async fn request_coercion_matches_the_python_models() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-lax").await;
    set_key(false);
    let issues: Vec<i32> = {
        let conn = state.pool.get().await.unwrap();
        let t = thread(&conn, user_id, "Lax").await;
        let mut ids = Vec::new();
        for n in 1..=5 {
            ids.push(issue(&conn, t, &n.to_string(), n).await);
        }
        ids
    };
    let confirm = |issue: i32, body: Value| {
        call(
            "POST",
            &format!("/api/v2/comicvine/issues/{issue}/identity:confirm"),
            &token,
            &csrf,
            Some(body),
        )
    };
    for (issue, body, expected_id) in [
        (issues[0], json!({"comicvine_issue_id": "9401"}), "9401"),
        (issues[1], json!({"comicvine_issue_id": 9402.0}), "9402"),
        (issues[2], json!({"comicvine_issue_id": true}), "1"),
        (issues[3], json!({"comicvine_issue_id": 0}), "0"),
    ] {
        let (status, got) = send(&state, confirm(issue, body.clone())).await;
        assert_eq!(status, StatusCode::OK, "{body}: {got:?}");
        assert_eq!(got["comicvine_issue_id"], expected_id, "{body}");
    }
    let (status, got) = send(
        &state,
        call(
            "POST",
            &format!("/api/v2/comicvine/issues/{}.0/identity:replace", issues[3]),
            &token,
            &csrf,
            Some(json!({"comicvine_issue_id": -7})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{got:?}");
    assert_eq!(got["comicvine_issue_id"], "-7");

    let (status, got) = send(
        &state,
        call(
            "POST",
            &format!("/api/v2/comicvine/issues/{}/metadata:correct", issues[4]),
            &token,
            &csrf,
            Some(json!({"field_name": "", "canonical_value": ""})),
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{got:?}");
    assert_eq!(got["corrections"][0]["field_name"], "");

    let expected = json!({"detail": "Validation failed"});
    for (path, body) in [
        (
            format!("/api/v2/comicvine/issues/{}/identity:confirm", issues[4]),
            json!({"comicvine_issue_id": 5.5}),
        ),
        (
            format!("/api/v2/comicvine/issues/{}/identity:confirm", issues[4]),
            json!({"comicvine_issue_id": null}),
        ),
        (
            format!("/api/v2/comicvine/issues/{}/metadata:correct", issues[4]),
            json!({"field_name": "a", "canonical_value": "b", "reason": "x".repeat(501)}),
        ),
        (
            format!("/api/v2/comicvine/issues/{}/identity:replace", issues[4]),
            json!({"comicvine_issue_id": 1, "reason": "x".repeat(501)}),
        ),
        (
            format!("/api/v2/comicvine/issues/{}/identity:confirm", issues[4]),
            json!({}),
        ),
        (
            format!("/api/v2/comicvine/issues/{}/metadata:correct", issues[4]),
            json!({"field_name": "a", "canonical_value": 5}),
        ),
        (
            format!("/api/v2/comicvine/issues/{}/metadata:revert", issues[4]),
            json!({"correction_id": "x"}),
        ),
        (
            format!("/api/v2/comicvine/issues/{}/metadata:correct", issues[4]),
            json!({"field_name": "f".repeat(101), "canonical_value": "b"}),
        ),
    ] {
        let (status, got) = send(
            &state,
            call("POST", &path, &token, &csrf, Some(body.clone())),
        )
        .await;
        assert_eq!(
            status,
            StatusCode::UNPROCESSABLE_ENTITY,
            "{path} {body}: {got:?}"
        );
        assert_eq!(got, expected, "{path} {body}");
    }
}

/// Python `str(metadata_json.get(field, "")) or None` (#4636390879), with
/// the identity metadata stored as raw JSON text so object key order is the
/// document's, as Python's `json.loads` keeps it.
#[tokio::test]
async fn correction_provider_values_use_python_str() {
    let (state, token, csrf, user_id, _guard) = setup_user("cvv2-provider-str").await;
    let conn = state.pool.get().await.unwrap();
    let t = thread(&conn, user_id, "Str").await;
    let i = issue(&conn, t, "1", 1).await;
    let identity: i32 = conn
        .query_one(
            "INSERT INTO external_identities (provider, entity_type, external_id, metadata_json, \
             created_at, updated_at) VALUES ('comicvine', 'issue', '9601', \
             '{\"cover_date\": null, \"flag\": true, \"count\": 3, \"ratio\": 1.0, \
               \"volume\": {\"name\": \"Saga\", \"id\": 9}, \"tags\": [1, \"it''s\", null], \
               \"empty\": \"\", \"name\": \"Pilot\"}'::json, NOW(), NOW()) RETURNING id",
            &[],
        )
        .await
        .unwrap()
        .get(0);
    conn.execute(
        "INSERT INTO issue_external_identity_mappings (issue_id, external_identity_id, status, \
         created_at, updated_at, evidence_json) VALUES ($1, $2, 'confirmed', NOW(), NOW(), '{}'::json)",
        &[&i, &identity],
    )
    .await
    .unwrap();
    drop(conn);
    let path = format!("/api/v2/comicvine/issues/{i}/metadata:correct");
    for (field, expected) in [
        ("cover_date", json!("None")),
        ("flag", json!("True")),
        ("count", json!("3")),
        ("ratio", json!("1.0")),
        ("volume", json!("{'name': 'Saga', 'id': 9}")),
        ("tags", json!("[1, \"it's\", None]")),
        ("empty", Value::Null),
        ("missing", Value::Null),
        ("name", json!("Pilot")),
    ] {
        let (status, body) = send(
            &state,
            call(
                "POST",
                &path,
                &token,
                &csrf,
                Some(json!({"field_name": field, "canonical_value": "x"})),
            ),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{field}: {body:?}");
        let last = body["corrections"]
            .as_array()
            .unwrap()
            .last()
            .unwrap()
            .clone();
        assert_eq!(last["field_name"], field);
        assert_eq!(last["provider_value"], expected, "{field}");
    }
}
