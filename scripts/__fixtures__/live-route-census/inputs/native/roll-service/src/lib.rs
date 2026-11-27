// Hermetic router fixture for scripts/generate_live_route_census.test.mjs.
use std::sync::Arc;

pub fn router(state: Arc<AppState>) -> Router {
    Router::new()
        .route(
            "/api/v1/threads/{thread_id}/set-pending",
            post(thread_lifecycle::set_pending_thread),
        )
        .route("/api/v1/threads/stale", get(thread_lifecycle::list_stale_threads))
        .route("/api/v2/threads", get(threads_v2::list_threads))
        .route("/api/v2/threads:preview", post(threads_v2::preview_threads))
        .route("/api/threads/{thread_id}", get(threads::get_thread_detail))
        .route("/health", get(|| async { "ok" }))
}

#[cfg(test)]
mod tests {
    // A fixture-only route string outside router(): never a live registration.
    const FIXTURE_PATH: &str = "/api/v1/threads/7/set-pending";
}
