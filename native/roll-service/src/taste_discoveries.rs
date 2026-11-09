//! Native same-path dismiss for the browser-called taste discoveries family (#4853).
//!
//! Migrates the dismissal subset of `app/api/taste.py` to the native Rust router with identical
//! method/path and wire contract:
//!
//! * `POST /api/v1/taste/discoveries/{signal_id}/dismiss`
//!
//! The discovery listing (`GET /api/v1/taste/discoveries`) stays on Python in this slice: it
//! evaluates the canonical prompt-eligibility engine (thresholds, 14-day cooldown, scoring and
//! creator-role dedup) plus the dismissal-suppression window. Dismissal is the smallest slice that
//! shares only `prompt_suppressed_until`, so Rust writes are visible to the Python listing with no
//! cross-runtime transaction.
//!
//! Wire parity with Python:
//!
//! * `POST .../dismiss` returns `{"dismissed": true}`. It writes only
//!   `prompt_suppressed_until = NOW() + interval '14 days'` and `updated_at = NOW()`; it never
//!   sets `user_verdict` or `verdict_at`. Missing or foreign signals return 404 with the Python
//!   detail text `Taste discovery {signal_id} not found`.
//! * One owner-scoped `UPDATE ... RETURNING` per call; no per-row fan-out.
//!
//! Python handlers remain; deployed ingress in `vercel.json` shadows them after this cutover.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::Serialize;
use std::sync::Arc;
use tokio_postgres::IsolationLevel;

/// Wire parity with Python `{"dismissed": True}`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct TasteDismissResponse {
    pub dismissed: bool,
}

/// Single owner-scoped suppression write. The 14-day window mirrors
/// `DISMISSAL_SUPPRESSION_DAYS` in `app/services/taste_bank.py`; verdict columns are untouched.
const DISMISS_SQL: &str = "UPDATE taste_signals SET prompt_suppressed_until = NOW() + interval '14 days', updated_at = NOW() WHERE id = $1 AND user_id = $2 RETURNING id";

fn not_found(signal_id: i32) -> ApiError {
    ApiError(
        StatusCode::NOT_FOUND,
        format!("Taste discovery {signal_id} not found"),
    )
}

/// `POST /api/v1/taste/discoveries/{signal_id}/dismiss` — suppress without a verdict.
pub async fn dismiss_taste_discovery(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(signal_id): Path<i32>,
) -> Result<Json<TasteDismissResponse>, ApiError> {
    let mut connection = db::checkout(&state).await?;
    let tx = connection
        .build_transaction()
        .isolation_level(IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    let updated = tx
        .query_opt(DISMISS_SQL, &[&signal_id, &user.id()])
        .await
        .map_err(db::query_error)?;
    if updated.is_none() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(not_found(signal_id));
    }
    tx.commit().await.map_err(db::query_error)?;
    Ok(Json(TasteDismissResponse { dismissed: true }))
}

/// Documentation-only operation for the mounted dismiss.
#[utoipa::path(
    post,
    path = "/api/v1/taste/discoveries/{signal_id}/dismiss",
    tag = "taste",
    description = "Dismiss one owner-scoped taste discovery without recording a verdict. Wire parity with Python POST /api/v1/taste/discoveries/{signal_id}/dismiss: writes prompt_suppressed_until = NOW() + 14 days and returns {dismissed: true}. Missing or foreign signals return 404 with the Python detail text.",
    params(("signal_id" = i32, Path, description = "Owned taste signal identifier")),
    responses(
        (status = 200, description = "Dismissed", body = TasteDismissResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Taste discovery not found"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn dismiss_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{db, test_support};
    use serde_json::json;
    use std::sync::Arc;

    async fn database_fixture() -> (
        Arc<AppState>,
        AuthenticatedUser,
        tokio::sync::MutexGuard<'static, ()>,
    ) {
        let state = test_support::test_state(2)
            .await
            .expect("RUST_ROLL_TEST_DATABASE_URL is required");
        let guard = test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username) VALUES (7001, 'taste-dismiss-test'), (7002, 'taste-dismiss-other');
                 INSERT INTO taste_signals (id, user_id, signal_type, external_key, display_name, affinity_estimate, evidence_count, distinct_thread_count, confidence, user_verdict, verdict_at, created_at, updated_at)
                 VALUES (8001, 7001, 'creator', 'creator:writer:alan-moore', 'Alan Moore', 0.9, 5, 3, 0.82, NULL, NULL, NOW(), NOW()),
                        (8002, 7002, 'creator', 'creator:writer:alan-moore', 'Alan Moore', 0.9, 5, 3, 0.82, NULL, NULL, NOW(), NOW());",
            )
            .await
            .expect("seed taste dismiss fixture");
        drop(connection);
        (state, AuthenticatedUser::for_test(7001), guard)
    }

    #[tokio::test]
    async fn dismiss_writes_suppression_to_disposable_postgres() {
        let (state, user, _guard) = database_fixture().await;
        let Json(response) = dismiss_taste_discovery(State(state.clone()), user, Path(8001))
            .await
            .expect("dismiss owned taste discovery");
        assert!(response.dismissed);

        let connection = db::checkout(&state).await.expect("verify connection");
        let row = connection
            .query_one(
                "SELECT prompt_suppressed_until IS NOT NULL, user_verdict, verdict_at IS NOT NULL FROM taste_signals WHERE id = 8001",
                &[],
            )
            .await
            .expect("verify suppression write");
        let suppressed: bool = row.get(0);
        let verdict: Option<String> = row.get(1);
        let verdict_at: bool = row.get(2);
        drop(connection);
        assert!(suppressed, "dismiss must write prompt_suppressed_until");
        assert_eq!(verdict, None, "dismiss must never write user_verdict");
        assert!(!verdict_at, "dismiss must never write verdict_at");
    }

    #[tokio::test]
    async fn dismiss_rejects_missing_and_foreign_signals_without_writing() {
        let (state, user, _guard) = database_fixture().await;
        let missing = dismiss_taste_discovery(State(state.clone()), user, Path(9999))
            .await
            .expect_err("missing signal must 404");
        assert_eq!(missing.0, StatusCode::NOT_FOUND);
        assert_eq!(missing.1, "Taste discovery 9999 not found");

        let foreign = dismiss_taste_discovery(State(state.clone()), user, Path(8002))
            .await
            .expect_err("foreign signal must 404");
        assert_eq!(foreign.0, StatusCode::NOT_FOUND);
        assert_eq!(foreign.1, "Taste discovery 8002 not found");

        let connection = db::checkout(&state).await.expect("verify connection");
        let suppressed: bool = connection
            .query_one(
                "SELECT prompt_suppressed_until IS NOT NULL FROM taste_signals WHERE id = 8002",
                &[],
            )
            .await
            .expect("verify foreign row untouched")
            .get(0);
        drop(connection);
        assert!(!suppressed, "foreign dismiss must not write");
    }

    #[test]
    fn dismiss_wire_matches_python_ack() {
        let value = serde_json::to_value(TasteDismissResponse { dismissed: true })
            .expect("serializable dismiss");
        assert_eq!(value, json!({"dismissed": true}));
    }

    #[test]
    fn dismiss_sql_is_owner_scoped_and_verdict_safe() {
        assert!(DISMISS_SQL.contains("WHERE id = $1 AND user_id = $2"));
        assert!(DISMISS_SQL.contains("prompt_suppressed_until = NOW() + interval '14 days'"));
        assert!(DISMISS_SQL.contains("updated_at = NOW()"));
        assert!(!DISMISS_SQL.contains("user_verdict"));
        assert!(!DISMISS_SQL.contains("verdict_at"));
        assert!(!DISMISS_SQL.contains(';'));
    }

    #[test]
    fn not_found_matches_python_detail_text() {
        let error = not_found(42);
        assert_eq!(error.0, StatusCode::NOT_FOUND);
        assert_eq!(error.1, "Taste discovery 42 not found");
    }

    #[tokio::test]
    async fn taste_dismiss_requires_auth_through_service_router() {
        use crate::{config::Config, router, AppState};
        use axum::{
            body::Body,
            http::{Request, StatusCode},
        };
        use tower::ServiceExt;

        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        })
        .unwrap();
        let app = router(Arc::new(AppState::new(config).unwrap()));
        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/taste/discoveries/7/dismiss")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(
            response.status(),
            StatusCode::UNAUTHORIZED,
            "taste dismiss must require auth through the service router"
        );
    }
}
