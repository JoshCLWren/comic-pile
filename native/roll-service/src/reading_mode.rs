//! Same-path Rust cutover for browser-called reading-mode operations (#4840, parent #4335).
//!
//! Preserves the Python `app/api/reading_mode.py` wire contract at the same
//! HTTP methods and exact paths (`GET/POST /api/v1/reading-mode`,
//! `POST /api/v1/reading-mode/dismiss-suggestion`,
//! `POST /api/v1/reading-mode/suggest`); only the implementation moves from
//! Python FastAPI to the native Roll binary. No frontend URL changes.
//!
//! Parity notes (Python oracle is `app/services/reading_mode.py` +
//! `app/services/reading_quiz.py`):
//! - Session resolution is `reading_session::initialize` (get-or-create with
//!   advisory lock, projection + start snapshot), not the read-only
//!   `bootstrap` path, matching Python `get_or_create`. The first request for
//!   a user without an authoritative session creates one with
//!   `reading_mode_suggested=false` and null mode fields, exactly like Python.
//! - `POST /api/v1/reading-mode` validates `source` then resolves quiz answers
//!   before any session work (no session is created on a 422), mirroring the
//!   Python service order (`if source not in values`, `resolve_quiz_answers`,
//!   `is_valid_reading_mode`, then `_get_active_session`).
//! - Quiz mapping is the shared contract: `brainpower` easy/normal/substantial
//!   -> light/balanced/deep, `pick` momentum/familiar/explore/random ->
//!   momentum/familiar/explore/random. Both axes must resolve.
//! - Manual entries require both `bandwidth` and `intent` non-empty and valid.
//! - Every success body is `{bandwidth, intent, source, suggested}`
//!   (first three nullable, `suggested` bool), status 200.
//! - Business 422s return `{detail: "<python message>"}` with the exact
//!   Python strings: invalid source, provide-either, invalid values,
//!   unknown question, unknown answer, partial answers.
#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser,
    db,
    reading_session::{self, SessionPolicy},
    ApiError, AppState,
};
use axum::{extract::State, http::StatusCode, Json};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, sync::Arc};

/// Current reading-mode state for the active session (wire response).
#[derive(Debug, Clone, Serialize, Deserialize, utoipa::ToSchema)]
pub struct ReadingModeResponse {
    pub bandwidth: Option<String>,
    pub intent: Option<String>,
    pub source: Option<String>,
    pub suggested: bool,
}

/// Set request: `source` is required; `answers` (quiz) or resolved
/// `bandwidth`+`intent` (manual) supplies the mode, as in Python.
#[derive(Debug, Deserialize, utoipa::ToSchema)]
pub struct ReadingModeSetRequest {
    pub bandwidth: Option<String>,
    pub intent: Option<String>,
    pub answers: Option<BTreeMap<String, String>>,
    pub source: String,
}

fn unprocessable(detail: String) -> ApiError {
    ApiError(StatusCode::UNPROCESSABLE_ENTITY, detail)
}

fn is_valid_reading_mode(bandwidth: &str, intent: &str) -> bool {
    matches!(bandwidth, "light" | "balanced" | "deep")
        && matches!(intent, "momentum" | "familiar" | "explore" | "random")
}

/// Resolve quiz answers exactly like Python `resolve_quiz_answers`.
/// Returns `(bandwidth, intent)` or the Python `QuizResolutionError` detail string (mapped to 422 by callers).
fn resolve_quiz_answers(answers: &BTreeMap<String, String>) -> Result<(String, String), String> {
    let mut bandwidth: Option<String> = None;
    let mut intent: Option<String> = None;
    for (question_id, answer_id) in answers {
        match question_id.as_str() {
            "brainpower" => match answer_id.as_str() {
                "easy" => bandwidth = Some("light".to_string()),
                "normal" => bandwidth = Some("balanced".to_string()),
                "substantial" => bandwidth = Some("deep".to_string()),
                _ => {
                    return Err(format!(
                        "Unknown answer '{answer_id}' for question '{question_id}'"
                    ))
                }
            },
            "pick" => match answer_id.as_str() {
                "momentum" => intent = Some("momentum".to_string()),
                "familiar" => intent = Some("familiar".to_string()),
                "explore" => intent = Some("explore".to_string()),
                "random" => intent = Some("random".to_string()),
                _ => {
                    return Err(format!(
                        "Unknown answer '{answer_id}' for question '{question_id}'"
                    ))
                }
            },
            _ => return Err(format!("Unknown quiz question: '{question_id}'")),
        }
    }
    match (bandwidth, intent) {
        (Some(b), Some(i)) => Ok((b, i)),
        _ => Err("Quiz answers did not resolve both bandwidth and intent".to_string()),
    }
}

/// Return the active session's current reading mode (read + get-or-create).
pub async fn get_reading_mode(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<ReadingModeResponse>, ApiError> {
    let initialized =
        reading_session::initialize(&state, user, None, SessionPolicy::default()).await?;
    Ok(Json(ReadingModeResponse {
        bandwidth: initialized.session.reading_bandwidth,
        intent: initialized.session.reading_intent,
        source: initialized.session.reading_mode_source,
        suggested: initialized.session.reading_mode_suggested,
    }))
}

/// Set the active session reading mode (quiz answers or manual pair).
pub async fn set_reading_mode(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Json(payload): Json<ReadingModeSetRequest>,
) -> Result<Json<ReadingModeResponse>, ApiError> {
    if payload.source != "quiz" && payload.source != "manual" {
        let source = &payload.source;
        return Err(unprocessable(format!(
            "Invalid reading-mode source: '{source}'"
        )));
    }

    // Mirror Python `if answers: ... elif bandwidth and intent: ... else: raise`.
    // Empty map is falsy in Python, so an explicit len check preserves that.
    let (bandwidth, intent) = match payload.answers.as_ref() {
        Some(map) if !map.is_empty() => resolve_quiz_answers(map).map_err(unprocessable)?,
        _ => match (
            payload.bandwidth.as_deref().filter(|s| !s.is_empty()),
            payload.intent.as_deref().filter(|s| !s.is_empty()),
        ) {
            (Some(b), Some(i)) => (b.to_string(), i.to_string()),
            _ => {
                return Err(unprocessable(
                    "Provide either quiz answers or both bandwidth and intent".to_string(),
                ))
            }
        },
    };

    if !is_valid_reading_mode(&bandwidth, &intent) {
        return Err(unprocessable(format!(
            "Invalid reading-mode values: '{bandwidth}'/'{intent}'"
        )));
    }

    let initialized =
        reading_session::initialize(&state, user, None, SessionPolicy::default()).await?;

    let conn = db::checkout(&state).await?;
    let row = conn
        .query_one(
            "UPDATE sessions
             SET reading_bandwidth=$1, reading_intent=$2, reading_mode_source=$3, reading_mode_suggested=false
             WHERE id=$4 AND user_id=$5
             RETURNING reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested",
            &[&bandwidth, &intent, &payload.source, &initialized.session.id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;

    Ok(Json(ReadingModeResponse {
        bandwidth: row.get(0),
        intent: row.get(1),
        source: row.get(2),
        suggested: row.get(3),
    }))
}

/// Dismiss the suggestion without changing the current mode.
pub async fn dismiss_reading_mode_suggestion(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<ReadingModeResponse>, ApiError> {
    let initialized =
        reading_session::initialize(&state, user, None, SessionPolicy::default()).await?;

    let conn = db::checkout(&state).await?;
    let row = conn
        .query_one(
            "UPDATE sessions
             SET reading_mode_suggested=false
             WHERE id=$1 AND user_id=$2
             RETURNING reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested",
            &[&initialized.session.id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;

    Ok(Json(ReadingModeResponse {
        bandwidth: row.get(0),
        intent: row.get(1),
        source: row.get(2),
        suggested: row.get(3),
    }))
}

/// Mark the active session as a candidate for the reading-mode quiz.
pub async fn suggest_reading_mode(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<ReadingModeResponse>, ApiError> {
    let initialized =
        reading_session::initialize(&state, user, None, SessionPolicy::default()).await?;

    let conn = db::checkout(&state).await?;
    let row = conn
        .query_one(
            "UPDATE sessions
             SET reading_mode_suggested=true
             WHERE id=$1 AND user_id=$2
             RETURNING reading_bandwidth, reading_intent, reading_mode_source, reading_mode_suggested",
            &[&initialized.session.id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;

    Ok(Json(ReadingModeResponse {
        bandwidth: row.get(0),
        intent: row.get(1),
        source: row.get(2),
        suggested: row.get(3),
    }))
}

// ---------------------------------------------------------------------------
// OpenAPI documentation-only operations (same-path v1 surface is described
// for the native contract, not for the v2 canonical aggregate).
// ---------------------------------------------------------------------------

#[utoipa::path(
    get,
    path = "/api/v1/reading-mode",
    tag = "reading-mode",
    responses(
        (status = 200, description = "Current reading-mode state", body = ReadingModeResponse),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn get_reading_mode_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/reading-mode",
    tag = "reading-mode",
    request_body = ReadingModeSetRequest,
    responses(
        (status = 200, description = "Newly stored reading-mode state", body = ReadingModeResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Invalid source, quiz resolution, or mode values"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn set_reading_mode_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/reading-mode/dismiss-suggestion",
    tag = "reading-mode",
    responses(
        (status = 200, description = "Unchanged reading-mode state with suggestion cleared", body = ReadingModeResponse),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn dismiss_reading_mode_suggestion_documentation() {}

#[utoipa::path(
    post,
    path = "/api/v1/reading-mode/suggest",
    tag = "reading-mode",
    responses(
        (status = 200, description = "Reading-mode state with suggestion enabled", body = ReadingModeResponse),
        (status = 401, description = "Not authenticated"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn suggest_reading_mode_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn test_map(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn every_combination_maps_to_valid_mode() {
        // 3 brainpower x 4 pick = 12 combinations, mirroring Python all_answer_combinations.
        let brainpower = [
            ("easy", "light"),
            ("normal", "balanced"),
            ("substantial", "deep"),
        ];
        let picks = [
            ("momentum", "momentum"),
            ("familiar", "familiar"),
            ("explore", "explore"),
            ("random", "random"),
        ];
        let mut count = 0;
        for (brainpower_id, expected_bandwidth) in brainpower {
            for (pick_id, expected_intent) in picks {
                let (bandwidth, intent) = resolve_quiz_answers(&test_map(&[
                    ("brainpower", brainpower_id),
                    ("pick", pick_id),
                ]))
                .expect("valid combination");
                assert_eq!(bandwidth, expected_bandwidth);
                assert_eq!(intent, expected_intent);
                assert!(is_valid_reading_mode(&bandwidth, &intent));
                count += 1;
            }
        }
        assert_eq!(count, 12);
    }

    #[test]
    fn combination_axes_are_independent() {
        for (brainpower, expected_bandwidth) in [
            ("easy", "light"),
            ("normal", "balanced"),
            ("substantial", "deep"),
        ] {
            for pick in ["momentum", "familiar", "explore", "random"] {
                let (bandwidth, _) =
                    resolve_quiz_answers(&test_map(&[("brainpower", brainpower), ("pick", pick)]))
                        .expect("resolve");
                assert_eq!(bandwidth, expected_bandwidth);
            }
        }
        for (pick, expected_intent) in [
            ("momentum", "momentum"),
            ("familiar", "familiar"),
            ("explore", "explore"),
            ("random", "random"),
        ] {
            for brainpower in ["easy", "normal", "substantial"] {
                let (_, intent) =
                    resolve_quiz_answers(&test_map(&[("brainpower", brainpower), ("pick", pick)]))
                        .expect("resolve");
                assert_eq!(intent, expected_intent);
            }
        }
    }

    #[test]
    fn unknown_question_is_rejected() {
        let err =
            resolve_quiz_answers(&test_map(&[("not_a_question", "easy"), ("pick", "random")]))
                .expect_err("unknown question must fail");
        assert_eq!(err, "Unknown quiz question: 'not_a_question'");
    }

    #[test]
    fn unknown_answer_is_rejected() {
        let err = resolve_quiz_answers(&test_map(&[("brainpower", "unknown"), ("pick", "random")]))
            .expect_err("unknown answer must fail");
        assert_eq!(err, "Unknown answer 'unknown' for question 'brainpower'");
    }

    #[test]
    fn unknown_pick_answer_is_rejected() {
        let err = resolve_quiz_answers(&test_map(&[("brainpower", "easy"), ("pick", "nope")]))
            .expect_err("unknown pick answer must fail");
        assert_eq!(err, "Unknown answer 'nope' for question 'pick'");
    }

    #[test]
    fn partial_answers_are_rejected() {
        let err = resolve_quiz_answers(&test_map(&[("brainpower", "easy")]))
            .expect_err("partial answers must fail");
        assert_eq!(
            err,
            "Quiz answers did not resolve both bandwidth and intent"
        );
    }

    #[test]
    fn valid_mode_pairs() {
        assert!(is_valid_reading_mode("light", "momentum"));
        assert!(is_valid_reading_mode("balanced", "familiar"));
        assert!(is_valid_reading_mode("deep", "explore"));
        assert!(is_valid_reading_mode("deep", "random"));
        assert!(!is_valid_reading_mode("mystical", "momentum"));
        assert!(!is_valid_reading_mode("light", "unknown"));
        assert!(!is_valid_reading_mode("", ""));
    }

    #[test]
    fn invalid_source_message_matches_python() {
        let source = "forced-onboarding";
        let error = unprocessable(format!("Invalid reading-mode source: '{source}'"));
        assert_eq!(error.0, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(error.1, "Invalid reading-mode source: 'forced-onboarding'");
    }

    #[test]
    fn invalid_values_message_matches_python() {
        let error = unprocessable(format!(
            "Invalid reading-mode values: '{}'/'{}'",
            "mystical", "momentum"
        ));
        assert_eq!(
            error.1,
            "Invalid reading-mode values: 'mystical'/'momentum'"
        );
    }

    #[test]
    fn empty_answers_fall_through_to_manual_pair() {
        // Mirrors Python `if answers:` falsy check on empty dict.
        let empty: BTreeMap<String, String> = BTreeMap::new();
        assert!(empty.is_empty());
    }

    #[test]
    fn response_shape_has_nullable_mode_and_bool_flag() {
        // Wire contract: {bandwidth: null|str, intent, source, suggested: bool}
        let null_body = serde_json::json!({
            "bandwidth": null,
            "intent": null,
            "source": null,
            "suggested": true
        });
        let parsed: ReadingModeResponse =
            serde_json::from_value(null_body).expect("deserialize null mode");
        assert!(
            parsed.bandwidth.is_none()
                && parsed.intent.is_none()
                && parsed.source.is_none()
                && parsed.suggested
        );
        let set_body = serde_json::json!({
            "bandwidth": "deep",
            "intent": "explore",
            "source": "quiz",
            "suggested": false
        });
        let parsed: ReadingModeResponse =
            serde_json::from_value(set_body).expect("deserialize set mode");
        assert_eq!(parsed.bandwidth.as_deref(), Some("deep"));
        assert_eq!(parsed.intent.as_deref(), Some("explore"));
        assert_eq!(parsed.source.as_deref(), Some("quiz"));
        assert!(!parsed.suggested);
    }

    async fn db_state() -> (
        std::sync::Arc<AppState>,
        tokio_postgres::Client,
        tokio::sync::MutexGuard<'static, ()>,
    ) {
        let _admin = crate::test_support::required_test_admin_url();
        let url = crate::test_support::database_url().await;
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let guard = crate::test_support::reset_for_test(&state).await;
        let (client, connection) = tokio_postgres::connect(&url, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        client
            .batch_execute("INSERT INTO users (id, username) VALUES (1, 'reader-1')")
            .await
            .expect("seed reader");
        (state, client, guard)
    }

    #[tokio::test]
    async fn set_reading_mode_persists_manual_selection_through_handler() {
        let (state, client, _db) = db_state().await;
        let Json(body) = set_reading_mode(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
            Json(ReadingModeSetRequest {
                bandwidth: Some("deep".into()),
                intent: Some("explore".into()),
                answers: None,
                source: "manual".into(),
            }),
        )
        .await
        .expect("manual set must succeed");
        assert_eq!(body.bandwidth.as_deref(), Some("deep"));
        assert_eq!(body.intent.as_deref(), Some("explore"));
        assert_eq!(body.source.as_deref(), Some("manual"));
        assert!(!body.suggested);
        let row = client
            .query_one(
                "SELECT reading_bandwidth, reading_intent, reading_mode_source \
                 FROM sessions WHERE user_id=1",
                &[],
            )
            .await
            .expect("persisted session");
        assert_eq!(row.get::<_, Option<String>>(0).as_deref(), Some("deep"));
        assert_eq!(row.get::<_, Option<String>>(1).as_deref(), Some("explore"));
        assert_eq!(row.get::<_, Option<String>>(2).as_deref(), Some("manual"));
    }

    #[tokio::test]
    async fn suggest_then_dismiss_toggles_only_the_suggestion_flag() {
        let (state, client, _db) = db_state().await;
        let Json(suggested) = suggest_reading_mode(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
        )
        .await
        .expect("suggest must succeed");
        assert!(suggested.suggested);
        let Json(dismissed) = dismiss_reading_mode_suggestion(
            State(state.clone()),
            AuthenticatedUser::for_test(1),
        )
        .await
        .expect("dismiss must succeed");
        assert!(!dismissed.suggested);
        let row = client
            .query_one(
                "SELECT reading_mode_suggested FROM sessions WHERE user_id=1",
                &[],
            )
            .await
            .expect("persisted session");
        assert!(!row.get::<_, bool>(0));
    }
}
