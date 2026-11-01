//! Tracked background work for the authentication surface.
//!
//! Some auth work must continue after the HTTP response is produced (currently
//! password-recovery email delivery). A bare `tokio::spawn` is not guaranteed to
//! finish on a serverless runtime: Vercel only keeps the invocation alive for
//! work registered through its `wait_until` tracker, and otherwise the isolate
//! can freeze mid-delivery. Every such future is therefore handed to a
//! [`BackgroundTasks`] registrar. The Vercel ingress binds it to the current
//! invocation; the self-hosted server and tests fall back to a Tokio task.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use axum::extract::FromRequestParts;
use axum::http::request::Parts;

/// A future registered for execution after the response is produced.
type BoxFuture = Pin<Box<dyn Future<Output = ()> + Send + 'static>>;

/// Registers work that must settle after the response has been sent.
#[derive(Clone)]
pub struct BackgroundTasks(Arc<dyn Fn(BoxFuture) + Send + Sync>);

impl Default for BackgroundTasks {
    fn default() -> Self {
        Self(Arc::new(|future| {
            tokio::spawn(future);
        }))
    }
}

impl BackgroundTasks {
    /// Build a handle from a runtime-specific registrar.
    pub fn new(register: impl Fn(BoxFuture) + Send + Sync + 'static) -> Self {
        Self(Arc::new(register))
    }

    /// Hand a future to the registrar.
    pub fn spawn<F>(&self, future: F)
    where
        F: Future<Output = ()> + Send + 'static,
    {
        (self.0)(Box::pin(future));
    }
}

impl<S> FromRequestParts<S> for BackgroundTasks
where
    S: Send + Sync,
{
    type Rejection = std::convert::Infallible;

    async fn from_request_parts(parts: &mut Parts, _state: &S) -> Result<Self, Self::Rejection> {
        Ok(parts
            .extensions
            .get::<BackgroundTasks>()
            .cloned()
            .unwrap_or_default())
    }
}
