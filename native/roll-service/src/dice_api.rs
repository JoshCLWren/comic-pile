//! Authenticated native HTTP entry for user-selected logical dice.
//!
//! Rerolls and ratings require Option E and progress validation within their
//! enclosing transaction; do not expose them through this standalone route.
use crate::{
    auth::AuthenticatedUser,
    db,
    dice_mutation::{self, DiceCommand},
    ApiError, AppState,
};
use axum::{extract::State, Json};
use deadpool_postgres::Object;
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ManualDieRequest {
    ManualSelect { die: i32, idempotency_key: String },
}

#[derive(Debug, Serialize)]
pub struct DiceCommandReceipt {
    event_id: i32,
    die_before: i32,
    die_after: i32,
    replayed: bool,
}

// A cancelled PostgreSQL command must never return a possibly busy
// connection to the pool. Only completed commits can recycle it.
pub(crate) struct Pending(Option<Object>);
impl Drop for Pending {
    fn drop(&mut self) {
        if let Some(connection) = self.0.take() {
            drop(Object::take(connection));
        }
    }
}

impl Pending {
    pub(crate) fn new(connection: Object) -> Self {
        Self(Some(connection))
    }

    pub(crate) fn connection(&mut self) -> &mut Object {
        self.0.as_mut().expect("checked-out PostgreSQL client")
    }

    /// Return a completed connection to the pool instead of discarding it.
    pub(crate) fn release(&mut self) {
        drop(self.0.take());
    }
}

pub async fn manual_die(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(request): Json<ManualDieRequest>,
) -> Result<Json<DiceCommandReceipt>, ApiError> {
    let (die, key) = match request {
        ManualDieRequest::ManualSelect {
            die,
            idempotency_key,
        } => (die, idempotency_key),
    };
    let mut pending = Pending::new(db::checkout(&state).await?);
    let receipt = dice_mutation::execute_standalone(
        pending.connection(),
        user,
        &key,
        &DiceCommand::ManualSelect { die },
    )
    .await?;
    pending.release();
    Ok(Json(DiceCommandReceipt {
        event_id: receipt.event_id,
        die_before: receipt.die_before,
        die_after: receipt.die_after,
        replayed: receipt.replayed,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{config::Config, router};
    use axum::{
        body::Body,
        http::{Request, StatusCode},
    };
    use tower::ServiceExt;

    #[test]
    fn does_not_expose_composite_dice_commands_or_untrusted_owners() {
        assert!(serde_json::from_str::<ManualDieRequest>(
            r#"{"kind":"manual_select","die":2,"idempotency_key":"client-command-123"}"#
        )
        .is_ok());
        for invalid in [
            r#"{"kind":"reset","idempotency_key":"client-command-123"}"#,
            r#"{"kind":"reroll","thread_id":4,"idempotency_key":"client-command-123"}"#,
            r#"{"kind":"roll_rating","thread_id":4,"issue_id":8,"rating":4,"idempotency_key":"client-command-123"}"#,
            r#"{"kind":"manual_select","die":6,"idempotency_key":"client-command-123","user_id":9}"#,
        ] {
            assert!(serde_json::from_str::<ManualDieRequest>(invalid).is_err());
        }
    }

    #[tokio::test]
    async fn manual_die_requires_authentication_before_database_access() {
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
                    .uri("/api/v2/roll/dice-command")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"kind":"manual_select","die":12,"idempotency_key":"client-command-123"}"#,
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }
}
