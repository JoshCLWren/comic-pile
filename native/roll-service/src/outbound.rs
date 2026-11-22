//! Injectable outbound HTTPS seam — fake by default in tests (#5339 follow-up).
//!
//! Every outbound HTTP client in the native service funnels through the
//! [`OutboundHttp`] trait held in [`crate::AppState`]:
//!
//! * GitHub issue creation (`bug_reports.rs`, `api.github.com`)
//! * ComicVine metadata repair / catalog rosters (`comicvine_repair.rs`)
//! * ComicVine release sync (`reading_plan_sync.rs`)
//! * ComicVine identity-inbox search (`identity_inbox.rs`)
//!
//! Production installs [`RealOutboundHttp`], which opens the same TLS socket
//! and speaks the same HTTP/1.1 as before. Test builds and test environments
//! (`cfg(test)`, `TEST_ENVIRONMENT=true`, `ENVIRONMENT=test`, or the
//! `RUST_ROLL_TEST_DATABASE_URL` test harness) install
//! [`RecordingFakeOutbound`], which records every call and never opens a
//! socket, so no test can reach the network. The guard test in this module
//! fails if a test-configured app would construct a real network client.
//!
//! Wire behavior is unchanged: call sites keep their hosts, paths, headers,
//! timeouts, body caps and error strings; only the socket lives behind the
//! seam.

use std::any::Any;
use std::collections::VecDeque;
use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, Mutex, MutexGuard};
use std::task::{Context, Poll};

use axum::body::Body;
use bytes::Bytes;
use http_body_util::Full;
use hyper::body::{Frame, Incoming};
use hyper::client::conn::http1;
use hyper_util::rt::TokioIo;

/// Lock a mutex, recovering from poisoning instead of panicking (production
/// denies `unwrap_used`/`expect_used`).
fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// Failure of one outbound exchange, classified so each call site can keep
/// its exact production error strings.
#[derive(Debug)]
pub enum OutboundError {
    /// TCP connect to `host`:443 failed.
    Connect(String),
    /// The TLS connector could not be constructed.
    TlsSetup(String),
    /// The TLS handshake failed.
    TlsHandshake(String),
    /// The HTTP/1.1 connection handshake failed.
    HttpHandshake(String),
    /// The request could not be built.
    RequestInvalid(String),
    /// Sending the request or reading its response failed.
    Send(String),
}

impl fmt::Display for OutboundError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let detail = match self {
            OutboundError::Connect(detail)
            | OutboundError::TlsSetup(detail)
            | OutboundError::TlsHandshake(detail)
            | OutboundError::HttpHandshake(detail)
            | OutboundError::RequestInvalid(detail)
            | OutboundError::Send(detail) => detail,
        };
        write!(f, "{detail}")
    }
}

impl std::error::Error for OutboundError {}

/// One completed provider response: status, headers and a streaming body.
#[derive(Debug)]
pub struct OutboundResponse {
    pub status: http::StatusCode,
    pub headers: http::HeaderMap,
    pub body: Body,
}

/// One outbound HTTPS request, origin-form (host-relative path).
#[derive(Debug, Clone)]
pub struct OutboundRequest {
    pub method: http::Method,
    pub path: String,
    pub headers: Vec<(String, String)>,
    pub body: Bytes,
}

impl OutboundRequest {
    /// A `GET` with no body and the given extra headers.
    pub fn get(path: impl Into<String>, headers: Vec<(String, String)>) -> Self {
        Self {
            method: http::Method::GET,
            path: path.into(),
            headers,
            body: Bytes::new(),
        }
    }
}

pub type OutboundFuture =
    Pin<Box<dyn Future<Output = Result<OutboundResponse, OutboundError>> + Send>>;

/// The outbound HTTPS transport. `host` is the DNS name; port 443 is implied.
pub trait OutboundHttp: Send + Sync + 'static {
    /// Perform one HTTPS request. The real implementation opens a socket;
    /// fakes must never open one.
    fn send(&self, host: &str, request: OutboundRequest) -> OutboundFuture;
    /// `true` only for the recording fake; the guard test relies on this.
    fn is_fake(&self) -> bool {
        false
    }
    fn as_any(&self) -> &dyn Any;
}

/// A provider connection must not outlive its awaited request. Dropping the
/// guard aborts the HTTP driver task.
struct ConnectionGuard(tokio::task::JoinHandle<()>);

impl Drop for ConnectionGuard {
    fn drop(&mut self) {
        self.0.abort();
    }
}

/// Response body that aborts the connection driver when the body is dropped,
/// matching the previous inline `ConnectionGuard` lifetime.
struct GuardedBody {
    inner: Incoming,
    _guard: ConnectionGuard,
}

impl hyper::body::Body for GuardedBody {
    type Data = Bytes;
    type Error = hyper::Error;

    fn poll_frame(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        Pin::new(&mut self.inner).poll_frame(cx)
    }

    fn is_end_stream(&self) -> bool {
        self.inner.is_end_stream()
    }

    fn size_hint(&self) -> hyper::body::SizeHint {
        self.inner.size_hint()
    }
}

/// Production transport: TCP + TLS + HTTP/1.1 to `host`:443, exactly as the
/// call sites did inline before the seam existed.
pub struct RealOutboundHttp;

impl OutboundHttp for RealOutboundHttp {
    fn send(&self, host: &str, request: OutboundRequest) -> OutboundFuture {
        let host = host.to_owned();
        Box::pin(async move {
            let tcp = tokio::net::TcpStream::connect((host.as_str(), 443))
                .await
                .map_err(|e| OutboundError::Connect(e.to_string()))?;
            let tls = native_tls::TlsConnector::new()
                .map_err(|e| OutboundError::TlsSetup(e.to_string()))?;
            let tls = tokio_native_tls::TlsConnector::from(tls)
                .connect(&host, tcp)
                .await
                .map_err(|e| OutboundError::TlsHandshake(e.to_string()))?;
            let (mut sender, connection) = http1::handshake(TokioIo::new(tls))
                .await
                .map_err(|e| OutboundError::HttpHandshake(e.to_string()))?;
            let guard = ConnectionGuard(tokio::spawn(async move {
                let _ = connection.await;
            }));
            let mut builder = http::Request::builder()
                .method(request.method)
                .uri(request.path)
                .header("host", &host);
            for (name, value) in &request.headers {
                builder = builder.header(name, value);
            }
            let http_request = builder
                .body(Full::new(request.body))
                .map_err(|e| OutboundError::RequestInvalid(e.to_string()))?;
            let response = sender
                .send_request(http_request)
                .await
                .map_err(|e| OutboundError::Send(e.to_string()))?;
            let (parts, incoming) = response.into_parts();
            Ok(OutboundResponse {
                status: parts.status,
                headers: parts.headers,
                body: Body::new(GuardedBody {
                    inner: incoming,
                    _guard: guard,
                }),
            })
        })
    }

    fn as_any(&self) -> &dyn Any {
        self
    }
}

/// One recorded outbound call, for test assertions.
#[derive(Debug, Clone)]
pub struct RecordedRequest {
    pub host: String,
    pub method: String,
    pub path: String,
    pub headers: Vec<(String, String)>,
    pub body: Bytes,
}

/// Test transport: records every call and never opens a socket. Without a
/// canned response it fails closed with [`OutboundError::Send`], so provider
/// paths degrade exactly like an unreachable network.
#[derive(Default)]
pub struct RecordingFakeOutbound {
    calls: Mutex<Vec<RecordedRequest>>,
    canned: Mutex<VecDeque<Result<OutboundResponse, OutboundError>>>,
}

impl RecordingFakeOutbound {
    pub fn new() -> Self {
        Self::default()
    }

    /// Every request recorded so far, in order.
    pub fn calls(&self) -> Vec<RecordedRequest> {
        lock(&self.calls).clone()
    }

    /// Queue a canned successful response for the next call.
    pub fn push_ok(&self, status: http::StatusCode, headers: http::HeaderMap, body: Bytes) {
        lock(&self.canned).push_back(Ok(OutboundResponse {
            status,
            headers,
            body: Body::from(body),
        }));
    }

    /// Queue a canned failure for the next call.
    pub fn push_error(&self, error: OutboundError) {
        lock(&self.canned).push_back(Err(error));
    }

    /// Forget all recorded calls and canned responses.
    pub fn clear(&self) {
        lock(&self.calls).clear();
        lock(&self.canned).clear();
    }
}

impl OutboundHttp for RecordingFakeOutbound {
    fn send(&self, host: &str, request: OutboundRequest) -> OutboundFuture {
        lock(&self.calls).push(RecordedRequest {
            host: host.to_owned(),
            method: request.method.to_string(),
            path: request.path.clone(),
            headers: request.headers.clone(),
            body: request.body.clone(),
        });
        let canned = lock(&self.canned).pop_front();
        Box::pin(async move {
            match canned {
                Some(Ok(response)) => Ok(response),
                Some(Err(error)) => Err(error),
                None => Err(OutboundError::Send(
                    "recording fake outbound client never opens a socket".to_string(),
                )),
            }
        })
    }

    fn is_fake(&self) -> bool {
        true
    }

    fn as_any(&self) -> &dyn Any {
        self
    }
}

/// Whether the current build/environment is a test context that must never
/// construct a real network client: `cfg(test)` unit builds, the
/// `TEST_ENVIRONMENT`/`ENVIRONMENT` test harness, or the disposable-database
/// test harness (`RUST_ROLL_TEST_DATABASE_URL`).
pub fn is_test_context() -> bool {
    cfg!(test)
        || std::env::var("TEST_ENVIRONMENT").is_ok_and(|value| value == "true")
        || std::env::var("ENVIRONMENT").is_ok_and(|value| value == "test")
        || std::env::var_os("RUST_ROLL_TEST_DATABASE_URL").is_some()
}

/// The transport [`crate::AppState`] installs: the recording fake in test
/// contexts, the real client otherwise.
pub fn default_transport() -> Arc<dyn OutboundHttp> {
    if is_test_context() {
        Arc::new(RecordingFakeOutbound::new())
    } else {
        Arc::new(RealOutboundHttp)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;

    fn synthetic_config() -> Config {
        Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        })
        .expect("synthetic config")
    }

    /// Guard: a test-configured app must never construct a real network
    /// client. This fails if `AppState::new` ever installs `RealOutboundHttp`
    /// in a test build.
    #[test]
    fn test_built_app_state_uses_recording_fake_not_a_real_client() {
        assert!(is_test_context(), "cfg(test) must count as a test context");
        let state = crate::AppState::new(synthetic_config()).expect("test app state");
        assert!(
            state.outbound.is_fake(),
            "a test-configured app constructed a real network client"
        );
        assert!(
            state.recording_fake().is_some(),
            "the installed fake must be inspectable for recorded calls"
        );
    }

    #[test]
    fn real_client_is_not_reported_as_fake() {
        let real = RealOutboundHttp;
        assert!(
            !real.is_fake(),
            "the guard relies on distinguishing real from fake"
        );
    }

    #[tokio::test]
    async fn recording_fake_records_calls_and_never_opens_a_socket() {
        let fake = RecordingFakeOutbound::new();
        let request = OutboundRequest {
            method: http::Method::POST,
            path: "/repos/o/r/issues".to_string(),
            headers: vec![("accept".into(), "application/vnd.github+json".into())],
            body: Bytes::from_static(br#"{"title":"t"}"#),
        };
        let error = fake
            .send("api.github.com", request.clone())
            .await
            .expect_err("the fake must fail closed without a canned response");
        assert!(matches!(error, OutboundError::Send(_)));

        let calls = fake.calls();
        assert_eq!(calls.len(), 1, "the fake must record every call");
        assert_eq!(calls[0].host, "api.github.com");
        assert_eq!(calls[0].method, "POST");
        assert_eq!(calls[0].path, "/repos/o/r/issues");
        assert_eq!(calls[0].body, Bytes::from_static(br#"{"title":"t"}"#));

        fake.push_ok(
            http::StatusCode::CREATED,
            http::HeaderMap::new(),
            Bytes::from_static(br#"{"html_url":"https://github.com/o/r/issues/1"}"#),
        );
        let response = fake
            .send("api.github.com", request)
            .await
            .expect("canned response must be returned");
        assert_eq!(response.status, http::StatusCode::CREATED);
        let body = http_body_util::BodyExt::collect(response.body)
            .await
            .expect("canned body")
            .to_bytes();
        assert_eq!(
            body,
            Bytes::from_static(br#"{"html_url":"https://github.com/o/r/issues/1"}"#)
        );
        assert_eq!(fake.calls().len(), 2);
    }
}
