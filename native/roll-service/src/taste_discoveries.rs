//! Native same-path browser-called taste discovery surface (#4853).
//!
//! Migrates the browser-called family in `app/api/taste.py` to the native
//! Rust router at the identical HTTP method and path:
//!
//! * `GET /api/v1/taste/discoveries`
//! * `POST /api/v1/taste/discoveries/{signal_id}/dismiss`
//!
//! Wire parity with Python:
//!
//! * `GET .../discoveries` returns the ranked, prompt-eligible signals for the
//!   authenticated reader. It applies the canonical prompt-eligibility gates
//!   (evidence, confidence, absolute affinity, diversity), the 14-day prompting
//!   cooldown, the dismissal-suppression window, and the creator-role dedup.
//!   Surfacing records `last_prompted_at` for exactly the returned signals so
//!   the cooldown applies on the next call.
//! * `POST .../dismiss` returns `{"dismissed": true}`. It writes only
//!   `prompt_suppressed_until = NOW() + interval '14 days'` and `updated_at =
//!   NOW()`; it never sets `user_verdict` or `verdict_at`. Missing or foreign
//!   signals return 404 with the Python detail text
//!   `Taste discovery {signal_id} not found`.
//!
//! Every operation is scoped to the authenticated owner and issues a bounded
//! constant number of statements: one read for the listing plus one bounded
//! `UPDATE ... WHERE id = ANY($1)` only when a discovery was surfaced, and one
//! owner-scoped `UPDATE ... RETURNING` for a dismissal. There is no per-row
//! fan-out.
//!
//! Python handlers remain mounted; deployed ingress in `vercel.json` shadows
//! them after this cutover.

#![forbid(unsafe_code)]

use crate::{
    auth::{self, AuthenticatedUser, VerifiedAccessClaims},
    db, ApiError, AppState,
};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use std::{cmp::Ordering, collections::HashSet, sync::Arc};
use tokio_postgres::IsolationLevel;

/// Upper bound on discoveries returned at once; Roll shows one at a time.
/// Wire parity with `MAX_ACTIVE_DISCOVERIES` in `app/services/taste_bank.py`.
const MAX_ACTIVE_DISCOVERIES: i64 = 3;

/// Canonical prompt-eligibility thresholds from `PromptEligibilityConfig`.
const MIN_EVIDENCE_COUNT: i32 = 3;
const MIN_CONFIDENCE: f64 = 0.6;
const MIN_AFFINITY: f64 = 0.3;
const MIN_DIVERSITY: i32 = 2;
const COOLDOWN_DAYS: i64 = 14;
const MAX_CANDIDATES: usize = 5;

/// Wire parity with Python `{"dismissed": True}`.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct TasteDismissResponse {
    pub dismissed: bool,
}

/// One prompt-eligible inferred taste pattern shown on Roll.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct TasteDiscovery {
    pub id: i32,
    pub signal_type: String,
    pub external_key: String,
    pub display_name: String,
    pub prompt: String,
    pub evidence_count: i32,
    pub distinct_thread_count: i32,
}

/// Ranked prompt-eligible discoveries for the authenticated reader.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct TasteDiscoveryListResponse {
    pub discoveries: Vec<TasteDiscovery>,
    pub generated_at: String,
}

/// Bounded `limit` query parameter, matching the Python `Query(ge=1, le=3)`.
#[derive(Debug, Deserialize)]
pub struct TasteDiscoveryQuery {
    pub limit: Option<i64>,
}

/// One persisted signal row used for eligibility evaluation.
struct SignalRow {
    id: i32,
    signal_type: String,
    external_key: String,
    display_name: String,
    affinity: Option<f64>,
    confidence: Option<f64>,
    evidence_count: i32,
    distinct_thread_count: i32,
    user_verdict: Option<String>,
    prompt_suppressed_until: Option<DateTime<Utc>>,
    last_prompted_at: Option<DateTime<Utc>>,
}

/// An eligible signal with its canonical composite score.
struct RankedSignal {
    id: i32,
    signal_type: String,
    external_key: String,
    display_name: String,
    evidence_count: i32,
    distinct_thread_count: i32,
    score: f64,
}

/// Single owner-scoped suppression write. The 14-day window mirrors
/// `DISMISSAL_SUPPRESSION_DAYS` in `app/services/taste_bank.py`; verdict columns are untouched.
const DISMISS_SQL: &str = "UPDATE taste_signals SET prompt_suppressed_until = NOW() + interval '14 days', updated_at = NOW() WHERE id = $1 AND user_id = $2 RETURNING id";

/// Read every signal owned by the reader in the Python listing order.
const DISCOVERY_LIST_SQL: &str = "SELECT id, signal_type, external_key, display_name, \
     affinity_estimate, confidence, evidence_count, distinct_thread_count, \
     user_verdict, prompt_suppressed_until, last_prompted_at \
     FROM taste_signals WHERE user_id = $1 \
     ORDER BY updated_at DESC, id DESC";

/// Record the prompting for exactly the surfaced signals in one bounded write.
const MARK_PROMPTED_SQL: &str =
    "UPDATE taste_signals SET last_prompted_at = NOW(), updated_at = NOW() WHERE id = ANY($1)";

fn not_found(signal_id: i32) -> ApiError {
    ApiError::with_status(
        StatusCode::NOT_FOUND,
        format!("Taste discovery {signal_id} not found"),
    )
}

/// Python-compatible ISO-8601 timestamp spelling for a UTC `timestamptz`
/// value. The fractional part is omitted on whole seconds, mirroring the
/// projection used by the other native resources.
fn iso_timestamp(value: DateTime<Utc>) -> String {
    if value.timestamp_subsec_micros() == 0 {
        value.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
    } else {
        value.to_rfc3339_opts(chrono::SecondsFormat::Micros, true)
    }
}

/// Whether a creator signal carries a specific role segment.
///
/// Wire parity with `_is_creator_role`: creator keys shaped like
/// ``creator:<role>:<name>`` are role-specific.
fn is_creator_role(signal_type: &str, external_key: &str) -> bool {
    signal_type == "creator" && external_key.split(':').count() >= 3
}

/// Extract the creator name used for generic/role-specific dedup.
fn creator_name(external_key: &str, role_specific: bool) -> Option<&str> {
    let parts: Vec<&str> = external_key.split(':').collect();
    if role_specific {
        parts.get(2).copied()
    } else {
        parts.get(1).copied()
    }
}

/// Remove generic creator signals when a role-specific variant exists.
fn prefer_creator_role_specific(signals: Vec<SignalRow>) -> Vec<SignalRow> {
    let role_specific: HashSet<String> = signals
        .iter()
        .filter(|signal| is_creator_role(&signal.signal_type, &signal.external_key))
        .filter_map(|signal| creator_name(&signal.external_key, true))
        .map(str::to_string)
        .collect();
    let generic: HashSet<String> = signals
        .iter()
        .filter(|signal| {
            signal.signal_type == "creator"
                && !is_creator_role(&signal.signal_type, &signal.external_key)
        })
        .filter_map(|signal| creator_name(&signal.external_key, false))
        .map(str::to_string)
        .collect();
    let redundant: HashSet<String> = role_specific.intersection(&generic).cloned().collect();
    if redundant.is_empty() {
        return signals;
    }
    signals
        .into_iter()
        .filter(|signal| {
            !(signal.signal_type == "creator"
                && !is_creator_role(&signal.signal_type, &signal.external_key)
                && creator_name(&signal.external_key, false)
                    .is_some_and(|name| redundant.contains(name)))
        })
        .collect()
}

/// Composite ranking score from the canonical prompt-eligibility engine.
fn score_signal(signal: &SignalRow) -> f64 {
    let affinity_norm =
        (signal.affinity.unwrap_or(0.0).abs() / (MIN_AFFINITY * 2.0).max(0.01)).min(1.0);
    let confidence_norm = signal.confidence.unwrap_or(0.0);
    let evidence_norm =
        (signal.evidence_count as f64 / (MIN_EVIDENCE_COUNT as f64 * 3.0).max(1.0)).min(1.0);
    let diversity_norm =
        (signal.distinct_thread_count as f64 / (MIN_DIVERSITY as f64 * 3.0).max(1.0)).min(1.0);
    let role_bonus = if is_creator_role(&signal.signal_type, &signal.external_key) {
        1.0
    } else {
        0.0
    };
    0.35 * affinity_norm
        + 0.30 * confidence_norm
        + 0.20 * evidence_norm
        + 0.10 * diversity_norm
        + 0.05 * role_bonus
}

/// Apply the canonical eligibility gates, cooldown, dedup and ranking.
fn ranked_signals(rows: Vec<SignalRow>, now: DateTime<Utc>) -> Vec<RankedSignal> {
    let mut eligible: Vec<SignalRow> = rows
        .into_iter()
        .filter(|signal| {
            if signal.user_verdict.is_some() {
                return false;
            }
            if signal
                .prompt_suppressed_until
                .is_some_and(|until| now < until)
            {
                return false;
            }
            if signal.evidence_count < MIN_EVIDENCE_COUNT
                || signal.confidence.unwrap_or(0.0) < MIN_CONFIDENCE
                || signal.affinity.unwrap_or(0.0).abs() < MIN_AFFINITY
                || signal.distinct_thread_count < MIN_DIVERSITY
            {
                return false;
            }
            !signal.last_prompted_at.is_some_and(|last| {
                last.checked_add_signed(Duration::days(COOLDOWN_DAYS))
                    .is_some_and(|end| now < end)
            })
        })
        .collect();

    eligible = prefer_creator_role_specific(eligible);

    let mut ranked: Vec<RankedSignal> = eligible
        .into_iter()
        .map(|signal| RankedSignal {
            score: score_signal(&signal),
            id: signal.id,
            signal_type: signal.signal_type,
            external_key: signal.external_key,
            display_name: signal.display_name,
            evidence_count: signal.evidence_count,
            distinct_thread_count: signal.distinct_thread_count,
        })
        .collect();

    ranked.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(Ordering::Equal)
            .then_with(|| left.external_key.cmp(&right.external_key))
    });
    ranked.truncate(MAX_CANDIDATES);
    ranked
}

/// Concise human-readable prompt copy for one eligible signal.
fn build_discovery_prompt(signal: &RankedSignal) -> String {
    if signal.signal_type == "creator" {
        let subject = if signal.external_key.contains(":writer:") {
            format!("comics written by {}", signal.display_name)
        } else if signal.external_key.contains(":artist:") {
            format!("comics with art by {}", signal.display_name)
        } else {
            format!("comics involving {}", signal.display_name)
        };
        return format!(
            "You've rated {subject} well above your usual baseline across {} reads. \
             Is {} generally a draw for you?",
            signal.evidence_count, signal.display_name
        );
    }
    format!(
        "You've rated {} issues well above your usual baseline across {} reads. \
         Do you generally enjoy {}?",
        signal.display_name, signal.evidence_count, signal.display_name
    )
}

/// `GET /api/v1/taste/discoveries` — ranked prompt-eligible discoveries.
pub async fn list_taste_discoveries(
    State(state): State<Arc<AppState>>,
    query: Result<Query<TasteDiscoveryQuery>, axum::extract::rejection::QueryRejection>,
    claims: VerifiedAccessClaims,
) -> Result<Json<TasteDiscoveryListResponse>, ApiError> {
    let Query(query) =
        query.map_err(|_| ApiError::Unprocessable("Validation failed".to_string()))?;
    let limit = query.limit.unwrap_or(MAX_ACTIVE_DISCOVERIES);
    if !(1..=MAX_ACTIVE_DISCOVERIES).contains(&limit) {
        return Err(ApiError::Unprocessable("Validation failed".to_string()));
    }
    let user = auth::authenticate_claims(&state, &claims).await?;

    let now = Utc::now();
    let connection = db::checkout(&state).await?;
    let rows = connection
        .query(DISCOVERY_LIST_SQL, &[&user.id()])
        .await
        .map_err(db::query_error)?;

    let signals: Vec<SignalRow> = rows
        .iter()
        .map(|row| SignalRow {
            id: row.get(0),
            signal_type: row.get(1),
            external_key: row.get(2),
            display_name: row.get(3),
            affinity: row.get(4),
            confidence: row.get(5),
            evidence_count: row.get(6),
            distinct_thread_count: row.get(7),
            user_verdict: row.get(8),
            prompt_suppressed_until: row.get(9),
            last_prompted_at: row.get(10),
        })
        .collect();

    let selected: Vec<RankedSignal> = ranked_signals(signals, now)
        .into_iter()
        .take(limit as usize)
        .collect();

    if !selected.is_empty() {
        let ids: Vec<i32> = selected.iter().map(|signal| signal.id).collect();
        connection
            .execute(MARK_PROMPTED_SQL, &[&ids])
            .await
            .map_err(db::query_error)?;
    }

    let discoveries = selected
        .iter()
        .map(|signal| TasteDiscovery {
            id: signal.id,
            signal_type: signal.signal_type.clone(),
            external_key: signal.external_key.clone(),
            display_name: signal.display_name.clone(),
            prompt: build_discovery_prompt(signal),
            evidence_count: signal.evidence_count,
            distinct_thread_count: signal.distinct_thread_count,
        })
        .collect();

    Ok(Json(TasteDiscoveryListResponse {
        discoveries,
        generated_at: iso_timestamp(now),
    }))
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

/// Documentation-only operation for the mounted discovery listing.
#[utoipa::path(
    get,
    path = "/api/v1/taste/discoveries",
    tag = "taste",
    description = "Return ranked prompt-eligible taste discoveries for the authenticated reader. Wire parity with Python GET /api/v1/taste/discoveries: applies evidence/confidence/affinity/diversity gates, the 14-day prompting cooldown, dismissal suppression and creator-role dedup, and records last_prompted_at for exactly the returned signals.",
    params(("limit" = Option<i64>, Query, description = "Maximum discoveries to return (1-3, default 3).")),
    responses(
        (status = 200, description = "Ranked discoveries", body = TasteDiscoveryListResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "limit is outside the allowed range"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_documentation() {}

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

    fn signal(
        id: i32,
        external_key: &str,
        display_name: &str,
        affinity: Option<f64>,
        confidence: Option<f64>,
        evidence_count: i32,
        distinct_thread_count: i32,
    ) -> SignalRow {
        SignalRow {
            id,
            signal_type: "creator".to_string(),
            external_key: external_key.to_string(),
            display_name: display_name.to_string(),
            affinity,
            confidence,
            evidence_count,
            distinct_thread_count,
            user_verdict: None,
            prompt_suppressed_until: None,
            last_prompted_at: None,
        }
    }

    fn strong(id: i32, external_key: &str, display_name: &str) -> SignalRow {
        signal(id, external_key, display_name, Some(0.9), Some(0.82), 5, 3)
    }

    #[test]
    fn threshold_gates_reject_sparse_weak_and_single_thread_signals() {
        let now = Utc::now();
        let rows = vec![
            strong(1, "creator:writer:kept", "Kept"),
            signal(
                2,
                "creator:writer:sparse",
                "Sparse",
                Some(0.9),
                Some(0.9),
                2,
                3,
            ),
            signal(3, "creator:writer:weak", "Weak", Some(0.2), Some(0.9), 5, 3),
            signal(
                4,
                "creator:writer:unsure",
                "Unsure",
                Some(0.9),
                Some(0.4),
                5,
                3,
            ),
            signal(
                5,
                "creator:writer:single",
                "Single",
                Some(0.9),
                Some(0.9),
                5,
                1,
            ),
        ];
        let ranked = ranked_signals(rows, now);
        assert_eq!(
            ranked.iter().map(|item| item.id).collect::<Vec<_>>(),
            vec![1]
        );
    }

    #[test]
    fn explicit_verdicts_and_dismissals_are_never_surfaced() {
        let now = Utc::now();
        let mut verdict = strong(1, "creator:writer:verdict", "Verdict");
        verdict.user_verdict = Some("confirmed".to_string());
        let mut suppressed = strong(2, "creator:writer:suppressed", "Suppressed");
        suppressed.prompt_suppressed_until = Some(now + Duration::days(1));
        let ranked = ranked_signals(vec![verdict, suppressed], now);
        assert!(ranked.is_empty());
    }

    #[test]
    fn cooldown_expires_after_fourteen_days() {
        let now = Utc::now();
        let mut recent = strong(1, "creator:writer:recent", "Recent");
        recent.last_prompted_at = Some(now - Duration::days(1));
        let mut expired = strong(2, "creator:writer:expired", "Expired");
        expired.last_prompted_at = Some(now - Duration::days(15));
        let ranked = ranked_signals(vec![recent, expired], now);
        assert_eq!(
            ranked.iter().map(|item| item.id).collect::<Vec<_>>(),
            vec![2]
        );
    }

    #[test]
    fn generic_creator_is_removed_when_a_role_specific_variant_exists() {
        let now = Utc::now();
        let rows = vec![
            strong(1, "creator:alan-moore", "Alan Moore"),
            strong(2, "creator:writer:alan-moore", "Alan Moore"),
        ];
        let ranked = ranked_signals(rows, now);
        assert_eq!(
            ranked.iter().map(|item| item.id).collect::<Vec<_>>(),
            vec![2]
        );
    }

    #[test]
    fn ranking_is_strongest_first_then_stable_key() {
        let now = Utc::now();
        let rows = vec![
            signal(1, "creator:writer:low", "Low", Some(0.31), Some(0.61), 3, 2),
            signal(2, "creator:writer:mid", "Mid", Some(0.6), Some(0.8), 6, 4),
            signal(3, "creator:writer:top", "Top", Some(1.0), Some(0.9), 9, 6),
        ];
        let ranked = ranked_signals(rows, now);
        assert_eq!(
            ranked.iter().map(|item| item.id).collect::<Vec<_>>(),
            vec![3, 2, 1]
        );
    }

    #[test]
    fn ranking_caps_at_five_candidates() {
        let now = Utc::now();
        let rows: Vec<SignalRow> = (0..7)
            .map(|index| {
                strong(
                    index + 1,
                    &format!("creator:writer:batch-{index}"),
                    &format!("Batch {index}"),
                )
            })
            .collect();
        let ranked = ranked_signals(rows, now);
        assert_eq!(ranked.len(), 5);
    }

    #[test]
    fn creator_prompt_copy_names_the_role_and_evidence() {
        let ranked = RankedSignal {
            id: 1,
            signal_type: "creator".to_string(),
            external_key: "creator:writer:alan-moore".to_string(),
            display_name: "Alan Moore".to_string(),
            evidence_count: 5,
            distinct_thread_count: 3,
            score: 1.0,
        };
        assert_eq!(
            build_discovery_prompt(&ranked),
            "You've rated comics written by Alan Moore well above your usual baseline across 5 reads. Is Alan Moore generally a draw for you?"
        );
    }

    #[test]
    fn artist_prompt_copy_mentions_art() {
        let ranked = RankedSignal {
            id: 1,
            signal_type: "creator".to_string(),
            external_key: "creator:artist:jim-lee".to_string(),
            display_name: "Jim Lee".to_string(),
            evidence_count: 5,
            distinct_thread_count: 3,
            score: 1.0,
        };
        assert!(build_discovery_prompt(&ranked).contains("art by Jim Lee"));
    }

    #[test]
    fn non_creator_prompt_copy_uses_the_display_name() {
        let ranked = RankedSignal {
            id: 1,
            signal_type: "character".to_string(),
            external_key: "character:batman".to_string(),
            display_name: "Batman".to_string(),
            evidence_count: 6,
            distinct_thread_count: 3,
            score: 1.0,
        };
        assert_eq!(
            build_discovery_prompt(&ranked),
            "You've rated Batman issues well above your usual baseline across 6 reads. Do you generally enjoy Batman?"
        );
    }

    #[test]
    fn generated_at_omits_fraction_on_whole_seconds() {
        let whole = DateTime::from_timestamp(1_760_000_000, 0).expect("timestamp");
        assert_eq!(iso_timestamp(whole), "2025-10-09T08:53:20Z");
        let fractional = whole + Duration::microseconds(123_456);
        assert_eq!(iso_timestamp(fractional), "2025-10-09T08:53:20.123456Z");
    }

    #[test]
    fn list_sql_is_owner_scoped_and_ordered() {
        assert!(DISCOVERY_LIST_SQL.contains("WHERE user_id = $1"));
        assert!(DISCOVERY_LIST_SQL.contains("ORDER BY updated_at DESC, id DESC"));
        assert!(!DISCOVERY_LIST_SQL.contains(';'));
    }

    #[test]
    fn mark_prompted_sql_is_bounded_and_preserves_verdicts() {
        assert!(MARK_PROMPTED_SQL.contains("last_prompted_at = NOW()"));
        assert!(MARK_PROMPTED_SQL.contains("updated_at = NOW()"));
        assert!(MARK_PROMPTED_SQL.contains("WHERE id = ANY($1)"));
        assert!(!MARK_PROMPTED_SQL.contains("user_verdict"));
        assert!(!MARK_PROMPTED_SQL.contains("verdict_at"));
    }

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
    async fn list_returns_ranked_discoveries_and_records_prompting() {
        let (state, _user, _guard) = database_fixture().await;
        let Json(first) = list_taste_discoveries(
            State(state.clone()),
            Ok(Query(TasteDiscoveryQuery { limit: None })),
            VerifiedAccessClaims::for_test("taste-dismiss-test", "jti-7001", 0),
        )
        .await
        .expect("list owned taste discoveries");
        assert_eq!(first.discoveries.len(), 1);
        assert_eq!(
            first.discoveries[0].external_key,
            "creator:writer:alan-moore"
        );
        assert!(first.discoveries[0].prompt.contains("Alan Moore"));
        assert!(first.generated_at.ends_with('Z'));

        let connection = db::checkout(&state).await.expect("verify connection");
        let prompted: Option<DateTime<Utc>> = connection
            .query_one(
                "SELECT last_prompted_at FROM taste_signals WHERE id = 8001",
                &[],
            )
            .await
            .expect("verify prompting write")
            .get(0);
        drop(connection);
        assert!(prompted.is_some(), "listing must record last_prompted_at");

        let Json(second) = list_taste_discoveries(
            State(state.clone()),
            Ok(Query(TasteDiscoveryQuery { limit: None })),
            VerifiedAccessClaims::for_test("taste-dismiss-test", "jti-7001", 0),
        )
        .await
        .expect("second list is suppressed by the cooldown");
        assert!(second.discoveries.is_empty());
    }

    #[tokio::test]
    async fn list_bounds_limit_and_hides_other_users() {
        let (state, _user, _guard) = database_fixture().await;
        let Json(limited) = list_taste_discoveries(
            State(state.clone()),
            Ok(Query(TasteDiscoveryQuery { limit: Some(1) })),
            VerifiedAccessClaims::for_test("taste-dismiss-test", "jti-7001", 0),
        )
        .await
        .expect("bounded listing");
        assert_eq!(limited.discoveries.len(), 1);

        let Json(foreign) = list_taste_discoveries(
            State(state.clone()),
            Ok(Query(TasteDiscoveryQuery { limit: None })),
            VerifiedAccessClaims::for_test("taste-dismiss-other", "jti-7002", 0),
        )
        .await
        .expect("foreign owner listing");
        assert_eq!(foreign.discoveries.len(), 1);
        assert_eq!(
            foreign.discoveries[0].external_key,
            "creator:writer:alan-moore"
        );
    }

    #[tokio::test]
    async fn list_rejects_out_of_range_limit_without_database_state() {
        let (state, _user, _guard) = database_fixture().await;
        for limit in [0, 4] {
            let error = list_taste_discoveries(
                State(state.clone()),
                Ok(Query(TasteDiscoveryQuery { limit: Some(limit) })),
                VerifiedAccessClaims::for_test("taste-dismiss-test", "jti-7001", 0),
            )
            .await
            .expect_err("out-of-range limit must 422");
            assert_eq!(error.status(), StatusCode::UNPROCESSABLE_ENTITY);
        }
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
        assert_eq!(missing.status(), StatusCode::NOT_FOUND);
        assert_eq!(missing.detail(), "Taste discovery 9999 not found");

        let foreign = dismiss_taste_discovery(State(state.clone()), user, Path(8002))
            .await
            .expect_err("foreign signal must 404");
        assert_eq!(foreign.status(), StatusCode::NOT_FOUND);
        assert_eq!(foreign.detail(), "Taste discovery 8002 not found");

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
        assert_eq!(error.status(), StatusCode::NOT_FOUND);
        assert_eq!(error.detail(), "Taste discovery 42 not found");
    }

    #[tokio::test]
    async fn taste_routes_require_auth_through_service_router() {
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
        for (method, uri) in [
            ("GET", "/api/v1/taste/discoveries"),
            ("POST", "/api/v1/taste/discoveries/7/dismiss"),
        ] {
            let response = app
                .clone()
                .oneshot(
                    Request::builder()
                        .method(method)
                        .uri(uri)
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .unwrap();
            assert_eq!(
                response.status(),
                StatusCode::UNAUTHORIZED,
                "{method} {uri} must require auth through the service router"
            );
        }
    }

    #[tokio::test]
    async fn invalid_limit_returns_validation_envelope_through_service_router() {
        use crate::{config::Config, router, AppState};
        use axum::{
            body::Body,
            http::{Request, StatusCode},
        };
        use chrono::{Duration, Utc};
        use http_body_util::BodyExt;
        use jsonwebtoken::{encode, Algorithm, EncodingKey, Header};
        use serde::Serialize;
        use tower::ServiceExt;

        #[derive(Serialize)]
        struct Claims {
            sub: &'static str,
            jti: &'static str,
            iat: i64,
            exp: i64,
            #[serde(rename = "type")]
            token_type: &'static str,
            pc: i64,
        }

        let config = Config::from_lookup(|name| match name {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/unused".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic-secret".into()),
            _ => None,
        })
        .unwrap();
        let app = router(Arc::new(AppState::new(config).unwrap()));
        let now = Utc::now();
        let token = encode(
            &Header::new(Algorithm::HS256),
            &Claims {
                sub: "reader-one",
                jti: "test-jti",
                iat: now.timestamp(),
                exp: (now + Duration::minutes(5)).timestamp(),
                token_type: "access",
                pc: 0,
            },
            &EncodingKey::from_secret(b"synthetic-secret"),
        )
        .unwrap();

        for limit in ["abc", "0", "4"] {
            let response = app
                .clone()
                .oneshot(
                    Request::builder()
                        .uri(format!("/api/v1/taste/discoveries?limit={limit}"))
                        .header("authorization", format!("Bearer {token}"))
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .unwrap();

            assert_eq!(
                response.status(),
                StatusCode::UNPROCESSABLE_ENTITY,
                "invalid limit {limit} must return 422 through the service router"
            );
            let body = response.into_body().collect().await.unwrap().to_bytes();
            let payload: serde_json::Value = serde_json::from_slice(&body).unwrap();
            assert_eq!(
                payload,
                json!({"detail": "Validation failed"}),
                "invalid limit {limit} must preserve the FastAPI validation envelope"
            );
        }
    }
}
