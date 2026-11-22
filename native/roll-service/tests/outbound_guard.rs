#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Guard tests for the outbound HTTP seam (#5339): a test-configured app must
//! never construct a real network client, and the recording fake must record
//! calls without opening sockets.

use bytes::Bytes;
use comicpile_roll_service::{
    config::Config,
    outbound::{OutboundHttp, OutboundRequest, RealOutboundHttp, RecordingFakeOutbound},
    test_support,
};
use std::sync::Arc;

fn synthetic_config() -> Config {
    Config::from_lookup(|name| match name {
        "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
        "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
        _ => None,
    })
    .expect("synthetic config")
}

/// A test-harness-constructed app must hold the recording fake, never a real
/// network client. Fails if `test_support::test_app_state` (or the underlying
/// `AppState` construction path) ever installs `RealOutboundHttp` in a test.
#[test]
fn test_configured_app_uses_recording_fake_outbound_client() {
    let state = test_support::test_app_state(synthetic_config());
    assert!(
        state.outbound.is_fake(),
        "a test-configured app constructed a real network client"
    );
    assert!(
        state.recording_fake().is_some(),
        "the recording fake must be inspectable for recorded calls"
    );
}

/// The database-backed test harness (`test_state`) must also install the fake.
#[tokio::test]
async fn database_test_harness_state_uses_recording_fake_outbound_client() {
    let Some(state) = test_support::test_state(2).await else {
        return; // no disposable database in this environment
    };
    assert!(
        state.outbound.is_fake(),
        "the database test harness constructed a real network client"
    );
    assert!(state.recording_fake().is_some());
}

/// The guard must be able to tell the real client apart from the fake.
#[test]
fn real_outbound_client_is_not_fake() {
    let real = RealOutboundHttp;
    assert!(!real.is_fake());
    assert!(real.as_any().downcast_ref::<RealOutboundHttp>().is_some());
    let fake = RecordingFakeOutbound::new();
    assert!(fake
        .as_any()
        .downcast_ref::<RecordingFakeOutbound>()
        .is_some());
    assert!(fake.as_any().downcast_ref::<RealOutboundHttp>().is_none());
}

/// The fake records every call and fails closed without opening a socket.
#[tokio::test]
async fn recording_fake_never_opens_a_socket() {
    let fake = Arc::new(RecordingFakeOutbound::new());
    let request = OutboundRequest {
        method: http::Method::POST,
        path: "/repos/owner/repo/issues".to_string(),
        headers: vec![(
            "accept".to_string(),
            "application/vnd.github+json".to_string(),
        )],
        body: Bytes::from_static(br#"{"title":"Bug","body":"Details","labels":["bug"]}"#),
    };
    let error = fake
        .send("api.github.com", request)
        .await
        .expect_err("the fake must fail closed without a canned response");
    assert!(matches!(
        error,
        comicpile_roll_service::outbound::OutboundError::Send(_)
    ));
    let calls = fake.calls();
    assert_eq!(calls.len(), 1);
    assert_eq!(calls[0].host, "api.github.com");
    assert_eq!(calls[0].method, "POST");
    assert_eq!(calls[0].path, "/repos/owner/repo/issues");

    // A canned response is returned to the caller and still recorded.
    fake.push_ok(
        http::StatusCode::CREATED,
        http::HeaderMap::new(),
        Bytes::from_static(br#"{"html_url":"https://github.com/owner/repo/issues/7"}"#),
    );
    let response = fake
        .send(
            "api.github.com",
            OutboundRequest::get("/repos/owner/repo/issues", vec![]),
        )
        .await
        .expect("canned response");
    assert_eq!(response.status, http::StatusCode::CREATED);
    assert_eq!(fake.calls().len(), 2);
}
