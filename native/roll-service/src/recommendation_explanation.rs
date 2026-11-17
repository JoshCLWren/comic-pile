//! Native cutover of the historical roll recommendation explanation read:
//! `GET /api/v1/roll/events/{event_id}/recommendation-explanation` and its
//! shared-handler alias `GET /api/roll/events/{event_id}/recommendation-explanation`.
//!
//! The Python handler (`app/api/roll.py:get_roll_recommendation_explanation`)
//! is the behavioral oracle. This module preserves the owner scope, the 404 for
//! an unknown or foreign event, the 422 for a non-`roll` event, and the
//! deterministic projection from the persisted decision-time context
//! (`app/services/recommendation_explanation.py`). Explanations are derived
//! only from stored data; nothing is recomputed from mutable thread state.
#![forbid(unsafe_code)]
use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

/// Maximum number of explanation factors the projection returns.
pub const MAX_EXPLANATIONS: usize = 5;

/// One human-readable explanation element returned by the API.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, utoipa::ToSchema)]
pub struct ExplainableFactor {
    /// Stable machine-readable code identifying the factor family.
    pub code: String,
    /// Short user-facing description.
    pub label: String,
    /// Optional extended context or sub-note.
    pub detail: Option<String>,
}

/// Aggregate recommendation explanation for a single roll event.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct RecommendationExplanationResponse {
    /// The roll event whose recommendation context was explained.
    pub event_id: i32,
    /// Ordered list of human-readable explanation elements.
    pub factors: Vec<ExplainableFactor>,
}

/// Query/path parameters for the mounted same-path operation.
#[derive(Debug, Deserialize)]
pub struct RecommendationExplanationPath {
    /// Identifier of the roll event to explain.
    pub event_id: i32,
}

/// One `(code, label, detail)` entry from the Python explanation maps.
type ExplanationEntry = (&'static str, &'static str, Option<&'static str>);

const BANDWIDTH_EXPLANATIONS: &[(&str, ExplanationEntry)] = &[
    (
        "band_light",
        ("band_light", "Quick read", Some("~11-minute read")),
    ),
    ("band_balanced", ("band_balanced", "Medium read", None)),
    (
        "band_deep",
        (
            "band_deep",
            "Deep read",
            Some("Settling in for an extended session"),
        ),
    ),
];

const INTENT_EXPLANATIONS: &[(&str, ExplanationEntry)] = &[
    (
        "intent_balanced",
        ("intent_balanced", "Balanced pick", None),
    ),
    (
        "intent_momentum",
        ("intent_momentum", "Recent series momentum", None),
    ),
    (
        "intent_familiar",
        ("intent_familiar", "Creator you confirmed you like", None),
    ),
    (
        "intent_explore",
        ("intent_explore", "Novel but connected to your tastes", None),
    ),
    (
        "intent_random",
        (
            "intent_random",
            "No weighting applied",
            Some("Pure random selection"),
        ),
    ),
];

const SELECTION_EXPLANATIONS: &[(&str, ExplanationEntry)] = &[
    (
        "random",
        ("random", "Pure random", Some("Weighting was bypassed")),
    ),
    (
        "override",
        ("override", "Manual pick", Some("Directly chosen")),
    ),
];

const TASTE_BANK_EXPLANATIONS: &[(&str, ExplanationEntry)] = &[
    (
        "taste_high_affinity",
        ("taste_high_affinity", "Strong affinity", None),
    ),
    (
        "taste_confirmed_creator",
        (
            "taste_confirmed_creator",
            "Creator you confirmed you like",
            None,
        ),
    ),
    (
        "taste_confirmed_character",
        (
            "taste_confirmed_character",
            "Character profile confirmed",
            None,
        ),
    ),
    (
        "taste_confirmed_team",
        ("taste_confirmed_team", "Team profile confirmed", None),
    ),
    (
        "taste_confirmed_era",
        ("taste_confirmed_era", "Era preference confirmed", None),
    ),
    (
        "taste_novel_adjacent",
        (
            "taste_novel_adjacent",
            "Novel but connected to your tastes",
            None,
        ),
    ),
    (
        "taste_series_momentum",
        ("taste_series_momentum", "Recent series momentum", None),
    ),
    (
        "taste_near_completion",
        (
            "taste_near_completion",
            "Near completion — finish strong",
            None,
        ),
    ),
];

const PRIMARY_SCORE_EXPLANATIONS: &[(&str, ExplanationEntry)] = &[
    (
        "score_affinity_strong",
        ("score_affinity_strong", "Strong affinity", None),
    ),
    (
        "score_affinity_moderate",
        ("score_affinity_moderate", "Matches your history", None),
    ),
    (
        "score_recency_boost",
        ("score_recency_boost", "Recently updated", None),
    ),
    (
        "score_staleness_penalty",
        ("score_staleness_penalty", "Less active lately", None),
    ),
    (
        "score_familiar_component",
        ("score_familiar_component", "Familiar component", None),
    ),
    (
        "score_explore_component",
        ("score_explore_component", "Explore component", None),
    ),
];

/// Look up one stable code in an explanation map.
fn lookup(table: &[(&str, ExplanationEntry)], code: &str) -> Option<ExplainableFactor> {
    table
        .iter()
        .find(|(candidate, _)| *candidate == code)
        .map(|(_, (_, label, detail))| ExplainableFactor {
            code: code.to_string(),
            label: (*label).to_string(),
            detail: (*detail).map(str::to_string),
        })
}

/// Translate a persisted bandwidth band code into an explanation.
fn bandwidth_factor(code: &str) -> Option<ExplainableFactor> {
    lookup(BANDWIDTH_EXPLANATIONS, code)
}

/// Translate a persisted intent code into an explanation.
fn intent_factor(code: &str) -> Option<ExplainableFactor> {
    lookup(INTENT_EXPLANATIONS, code)
}

/// Translate a persisted selection-method value into an explanation.
fn selection_factor(code: &str) -> Option<ExplainableFactor> {
    lookup(SELECTION_EXPLANATIONS, code)
}

/// Translate a persisted Taste Bank factor code into an explanation.
fn taste_bank_factor(code: &str) -> Option<ExplainableFactor> {
    lookup(TASTE_BANK_EXPLANATIONS, code)
}

/// Translate a persisted primary-score code into an explanation.
fn primary_score_factor(code: &str) -> Option<ExplainableFactor> {
    lookup(PRIMARY_SCORE_EXPLANATIONS, code)
}

/// Read a non-empty string from one JSON object key.
fn string_field<'a>(context: &'a serde_json::Value, key: &str) -> Option<&'a str> {
    context
        .get(key)
        .and_then(serde_json::Value::as_str)
        .filter(|value| !value.is_empty())
}

/// Translate one persisted Taste Bank entry, which must carry a `code` key.
fn taste_bank_entry(entry: &serde_json::Value) -> Option<ExplainableFactor> {
    let code = entry.get("code").and_then(serde_json::Value::as_str)?;
    if code.is_empty() {
        return None;
    }
    let mut factor = taste_bank_factor(code)?;
    // The Python projection keeps the persisted detail only for entries whose
    // canonical map row has no fixed detail.
    if factor.detail.is_none() {
        factor.detail = entry
            .get("detail")
            .and_then(serde_json::Value::as_str)
            .map(str::to_string);
    }
    Some(factor)
}

/// Project the persisted recommendation context into ordered explanations.
///
/// Mirrors `RecommendationExplanationProjection.project_recommendation_context`:
/// bandwidth, intent, up to two Taste Bank factors, one primary-score factor,
/// affinity notes, then the selection-method factor. Unknown codes are skipped,
/// and the result is bounded to [`MAX_EXPLANATIONS`].
pub fn project_recommendation_context(
    context: Option<&serde_json::Value>,
    selection_method: Option<&str>,
) -> Vec<ExplainableFactor> {
    let empty = serde_json::Value::Null;
    let context = context.unwrap_or(&empty);
    let mut factors: Vec<ExplainableFactor> = Vec::new();

    if let Some(code) = string_field(context, "bandwidth") {
        if let Some(factor) = bandwidth_factor(code) {
            factors.push(factor);
        }
    }

    let intent_code = string_field(context, "intent");
    if let Some(code) = intent_code {
        if let Some(factor) = intent_factor(code) {
            factors.push(factor);
        }
    }

    if let Some(entries) = context.get("taste_bank_factors").and_then(|v| v.as_array()) {
        let mut count = 0;
        for entry in entries {
            if count >= 2 {
                break;
            }
            if let Some(factor) = taste_bank_entry(entry) {
                factors.push(factor);
                count += 1;
            }
        }
    }

    if let Some(primary_score) = context.get("primary_score") {
        if let Some(code) = primary_score
            .get("code")
            .and_then(serde_json::Value::as_str)
        {
            if !code.is_empty() {
                if let Some(factor) = primary_score_factor(code) {
                    factors.push(factor);
                }
            }
        }
    }

    if let Some(notes) = context.get("affinity_notes").and_then(|v| v.as_array()) {
        for note in notes {
            if let Some(code) = note.as_str() {
                if !code.is_empty() {
                    if let Some(factor) = taste_bank_factor(code) {
                        factors.push(factor);
                    }
                }
            }
        }
    }

    // Legacy control rolls recorded `intent_random` without an explicit
    // selection method; the weighting-bypass explanation still applies.
    let mut raw_method = selection_method
        .map(str::to_string)
        .or_else(|| string_field(context, "selection_method").map(str::to_string))
        .unwrap_or_default();
    if raw_method.is_empty() && intent_code == Some("intent_random") {
        raw_method = "random".to_string();
    }
    if !raw_method.is_empty() {
        if let Some(factor) = selection_factor(&raw_method) {
            factors.push(factor);
        }
    }

    factors.truncate(MAX_EXPLANATIONS);
    factors
}

/// Owner-scoped read of one historical roll event's explanation.
pub async fn get_recommendation_explanation(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Path(path): Path<RecommendationExplanationPath>,
) -> Result<Json<RecommendationExplanationResponse>, ApiError> {
    // One owner-scoped statement. `recommendation_context` and the session
    // owner arrive in the same row so the read never needs a second round trip.
    let mut connection = crate::dice_api::Pending::new(db::checkout(&state).await?);
    let result = tokio::time::timeout(state.request_timeout, async {
        let row = connection
            .connection()
            .query_opt(
                "SELECT e.type, e.selection_method, e.recommendation_context, s.user_id
                 FROM events e
                 JOIN sessions s ON s.id = e.session_id
                 WHERE e.id = $1",
                &[&path.event_id],
            )
            .await
            .map_err(db::query_error)?;
        Ok::<_, ApiError>(row)
    })
    .await;
    let row = match result {
        Err(e) => {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            return Err(ApiError::database_unavailable());
        }
        Ok(Err(error)) => return Err(error),
        Ok(Ok(row)) => row,
    };
    let row = match row {
        Some(row) => row,
        None => {
            return Err(ApiError::NotFound(format!(
                "Event {} not found",
                path.event_id
            )))
        }
    };
    let session_user_id: i32 = row.try_get(3).map_err(db::query_error)?;
    if session_user_id != user.id() {
        return Err(ApiError::NotFound(format!(
            "Event {} not found",
            path.event_id
        )));
    }
    let event_type: String = row.try_get(0).map_err(db::query_error)?;
    if event_type != "roll" {
        return Err(ApiError::with_status(
            axum::http::StatusCode::UNPROCESSABLE_ENTITY,
            format!("Event {} is not a roll event", path.event_id),
        ));
    }
    let selection_method: Option<String> = row.try_get(1).map_err(db::query_error)?;
    // `recommendation_context` is a JSON column. Historical rows may hold a
    // JSON string instead of an object; parse string values like Python's
    // `json.loads` path so double-encoded context still projects factors.
    let context: Option<serde_json::Value> = row.try_get(2).map_err(db::query_error)?;
    let context = parse_context_value(context);
    let factors = project_recommendation_context(context.as_ref(), selection_method.as_deref());
    connection.release();
    Ok(Json(RecommendationExplanationResponse {
        event_id: path.event_id,
        factors,
    }))
}

/// Normalize the stored recommendation context.
///
/// A JSON column can carry a JSON-encoded string for historical rows; parse it
/// into the inner object/value. Unparseable or non-object string payloads degrade
/// to `None`, matching Python's graceful handling.
fn parse_context_value(context: Option<serde_json::Value>) -> Option<serde_json::Value> {
    match context {
        Some(serde_json::Value::String(raw)) => serde_json::from_str(&raw).ok(),
        other => other,
    }
}

/// Documentation-only operation for the mounted v1 same-path read.
#[utoipa::path(
    get,
    path = "/api/v1/roll/events/{event_id}/recommendation-explanation",
    tag = "roll",
    params(("event_id" = i32, Path, description = "Roll event identifier")),
    responses(
        (status = 200, description = "Ordered explanation factors for the roll event", body = RecommendationExplanationResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Event does not exist or belongs to another reader"),
        (status = 422, description = "Event is not a roll event")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn recommendation_explanation_documentation() {}

/// Also mount the legacy-handler alias.
#[utoipa::path(
    get,
    path = "/api/roll/events/{event_id}/recommendation-explanation",
    tag = "roll",
    params(("event_id" = i32, Path, description = "Roll event identifier")),
    responses(
        (status = 200, description = "Ordered explanation factors for the roll event", body = RecommendationExplanationResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "Event does not exist or belongs to another reader"),
        (status = 422, description = "Event is not a roll event")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn recommendation_explanation_legacy_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn bandwidth_intent_and_selection_translate_in_python_order() {
        let context = json!({
            "bandwidth": "band_light",
            "intent": "intent_momentum",
            "taste_bank_factors": [{"code": "taste_high_affinity"}],
            "primary_score": {"code": "score_recency_boost"},
            "selection_method": "random",
        });
        let factors = project_recommendation_context(Some(&context), Some("random"));
        let codes: Vec<&str> = factors.iter().map(|f| f.code.as_str()).collect();
        assert_eq!(
            codes,
            vec![
                "band_light",
                "intent_momentum",
                "taste_high_affinity",
                "score_recency_boost",
                "random"
            ]
        );
        assert_eq!(factors[0].label, "Quick read");
        assert_eq!(factors[0].detail.as_deref(), Some("~11-minute read"));
        assert_eq!(factors[4].label, "Pure random");
    }

    #[test]
    fn absent_context_falls_back_to_the_selection_method() {
        let factors = project_recommendation_context(None, Some("random"));
        assert_eq!(factors.len(), 1);
        assert_eq!(factors[0].code, "random");
        assert_eq!(factors[0].detail.as_deref(), Some("Weighting was bypassed"));
    }

    #[test]
    fn unknown_legacy_codes_degrade_to_an_empty_list() {
        let context = json!({
            "bandwidth": "band_future_v2",
            "intent": "intent_unknown",
            "taste_bank_factors": [{"code": "taste_future_metric"}],
            "primary_score": {"code": "score_future_v3", "value": 0.91},
            "affinity_notes": ["taste_ghost_reason"],
            "selection_method": "unknown_method",
        });
        assert!(project_recommendation_context(Some(&context), Some("unknown_method")).is_empty());
    }

    #[test]
    fn legacy_random_intent_without_a_selection_method_still_explains_bypass() {
        let context = json!({"intent": "intent_random"});
        let factors = project_recommendation_context(Some(&context), None);
        // Python appends both the legacy intent factor and the derived
        // weighting-bypass explanation.
        let codes: Vec<&str> = factors.iter().map(|f| f.code.as_str()).collect();
        assert_eq!(codes, vec!["intent_random", "random"]);
        assert_eq!(factors[1].detail.as_deref(), Some("Weighting was bypassed"));
    }

    #[test]
    fn the_projection_is_bounded_to_five_factors() {
        let context = json!({
            "bandwidth": "band_light",
            "intent": "intent_momentum",
            "taste_bank_factors": [
                {"code": "taste_high_affinity"},
                {"code": "taste_series_momentum"},
                {"code": "taste_near_completion"}
            ],
            "primary_score": {"code": "score_recency_boost"},
            "affinity_notes": ["taste_high_affinity"],
            "selection_method": "override"
        });
        let factors = project_recommendation_context(Some(&context), Some("override"));
        assert_eq!(factors.len(), MAX_EXPLANATIONS);
    }

    #[test]
    fn a_json_string_context_is_parsed_before_projection() {
        // Historical rows may store the context as a JSON string; parse it like
        // Python's `json.loads` path so factors are preserved.
        let context = json!("{\"bandwidth\": \"band_light\"}");
        let parsed = parse_context_value(Some(context));
        let factors = project_recommendation_context(parsed.as_ref(), Some("override"));
        let codes: Vec<_> = factors.iter().map(|factor| factor.code.as_str()).collect();
        assert_eq!(codes, vec!["band_light", "override"]);
    }

    #[test]
    fn taste_bank_detail_falls_back_to_the_persisted_detail() {
        let context = json!({
            "taste_bank_factors": [{"code": "taste_high_affinity", "detail": "persisted"}]
        });
        let factors = project_recommendation_context(Some(&context), None);
        // The canonical map row for `taste_high_affinity` carries no fixed
        // detail, so Python keeps the persisted one.
        assert_eq!(factors[0].detail.as_deref(), Some("persisted"));
    }
}
