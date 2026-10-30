//! Focused regression for `POST /api/v1/snooze/` and legacy alias
//! `POST /api/snooze/`. Verifies route registration, auth boundary, and
//! basic response contract without requiring a full production session.
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use comicpile_roll_service::{config::Config, router, AppState};
use std::{collections::HashMap, sync::Arc};
use tower::ServiceExt;

fn values() -> HashMap<&'static str, String> {
    HashMap::from([
        (
            "RUST_ROLL_DATABASE_URL",
            "postgresql://synthetic:private-password@127.0.0.1:1/unused?sslmode=disable".into(),
        ),
        (
            "RUST_ROLL_JWT_SECRET",
            "synthetic-private-jwt-secret".into(),
        ),
    ])
}
fn config() -> Config {
    let values = values();
    Config::from_lookup(|key| values.get(key).cloned()).unwrap()
}

#[tokio::test]
async fn snooze_routes_registered_and_require_auth() {
    let state = Arc::new(AppState::new(config()).unwrap());
    let app = router(state.clone());

    // Both canonical and alias routes must exist.
    for path in ["/api/v1/snooze/", "/api/snooze/"] {
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(path)
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(
            response.status(),
            StatusCode::UNAUTHORIZED,
            "{} must require authentication",
            path
        );
        let body = to_bytes(response.into_body(), 4096).await.unwrap();
        let json = serde_json::from_slice::<serde_json::Value>(&body).unwrap();
        assert!(
            json.get("detail").is_some(),
            "{} must return JSON error detail",
            path
        );
    }

    state.pool.close();
}
