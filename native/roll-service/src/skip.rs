//! Native cutover of `POST /api/v1/roll/skip` and its shared-handler alias
//! `POST /api/roll/skip`.
//!
//! The Python handler is the behavioral oracle. This module preserves the same
//! request contract (no body), authenticated owner scope, status/error JSON,
//! transactional side effects, and legacy (production-default) roll-pool
//! semantics. Selection weighting mirrors the Python momentum/bandwidth
//! policies so an event records the same decision-time context shape.
use crate::{
    auth::AuthenticatedUser,
    db,
    reading_session::{self, ReadingSession, SessionPolicy},
    session_bandwidth, ApiError, AppState,
};
use axum::{extract::State, http::StatusCode, Json};
use deadpool_postgres::Object;
use rand::RngExt;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::{BTreeSet, HashMap, HashSet},
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};
use tokio_postgres::{IsolationLevel, Transaction};

/// Public roll response. Field order and nullability mirror
/// `app.schemas.roll.RollResponse`; the OpenAPI schema is generated from this
/// type and compared with the frozen FastAPI operation.
#[derive(Debug, Serialize, Deserialize, utoipa::ToSchema)]
pub struct RollResponse {
    /// Selected thread identifier.
    pub thread_id: i32,
    /// Thread title.
    pub title: String,
    /// Normalized format label.
    pub format: String,
    /// Remaining unread issues.
    pub issues_remaining: i32,
    /// Dense reader-visible Queue position.
    pub queue_position: i32,
    /// Current die size at roll time.
    pub die_size: i32,
    /// One-based die result.
    pub result: i32,
    /// Number of snoozed series for the offset.
    pub offset: i32,
    /// Number of snoozed series.
    pub snoozed_count: i32,
    /// Selected issue identifier, when issue tracking applies.
    pub issue_id: Option<i32>,
    /// Selected issue number, when issue tracking applies.
    pub issue_number: Option<String>,
    /// Next unread issue identifier.
    pub next_issue_id: Option<i32>,
    /// Next unread issue number.
    pub next_issue_number: Option<String>,
    /// Total issues in the series.
    pub total_issues: Option<i32>,
    /// Stored reading-progress label.
    pub reading_progress: Option<String>,
    /// Reader-facing explanation derived from the persisted reason codes.
    pub explanation: Option<String>,
}

/// OpenAPI document for the skip operation. The handler signature is not
/// annotated directly so axum extractors never become generated parameters.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(skip_roll_documentation),
    components(schemas(RollResponse)),
    modifiers(&SecurityAddon)
)]
pub struct SkipApi;

struct SecurityAddon;
impl utoipa::Modify for SecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme(
                "HTTPBearer",
                utoipa::openapi::security::SecurityScheme::Http(
                    utoipa::openapi::security::Http::new(
                        utoipa::openapi::security::HttpAuthScheme::Bearer,
                    ),
                ),
            );
        }
    }
}

/// Documentation-only operation used to emit the generated OpenAPI contract.
#[utoipa::path(
    post,
    path = "/api/v1/roll/skip",
    tag = "roll",
    responses((status = 200, description = "Successful Response", body = RollResponse)),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn skip_roll_documentation() {}

fn now_seconds() -> Result<f64, ApiError> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| internal())?
        .as_secs_f64())
}

fn internal() -> ApiError {
    ApiError(StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error")
}

fn unavailable() -> ApiError {
    ApiError(
        StatusCode::SERVICE_UNAVAILABLE,
        "Database temporarily unavailable",
    )
}

// ---------------------------------------------------------------------------
// Pure policy helpers (unit tested without a database)
// ---------------------------------------------------------------------------

/// Mirror `app.models.thread.normalize_format_value`.
fn normalize_format(value: &str) -> String {
    let stripped = value.trim();
    match stripped.to_lowercase().as_str() {
        "comic" | "comics" => "Comic".into(),
        "digital" => "Digital".into(),
        _ => stripped.into(),
    }
}

/// Mirror `comic_pile.recommendation_selection.normalize_bandwidth`.
fn normalize_bandwidth(value: Option<&str>) -> &'static str {
    match value {
        Some("light") => "light",
        Some("deep") => "deep",
        _ => "balanced",
    }
}

/// Mirror `comic_pile.recommendation_selection.resolve_selection_mode`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum SelectionMode {
    LegacyUniform,
    PureRandomBypass,
    ContextualWeighted,
    ForcedLegacy,
}
fn resolve_selection_mode(bandwidth: &str, intent: &str, control_mode: &str) -> SelectionMode {
    if control_mode == "legacy" {
        return SelectionMode::ForcedLegacy;
    }
    if intent == "random" {
        return SelectionMode::PureRandomBypass;
    }
    if bandwidth == "balanced" && intent == "balanced" {
        return SelectionMode::LegacyUniform;
    }
    SelectionMode::ContextualWeighted
}

/// Mirror `derive_recorded_selection_method`; returns method plus reason codes.
fn recorded_selection_method(
    mode: SelectionMode,
    bandwidth: &str,
) -> (&'static str, Vec<&'static str>) {
    match mode {
        SelectionMode::ForcedLegacy => ("legacy", vec!["forced_legacy"]),
        SelectionMode::PureRandomBypass => ("random", vec!["pure_random"]),
        SelectionMode::LegacyUniform | SelectionMode::ContextualWeighted => {
            if matches!(bandwidth, "light" | "deep") {
                ("bandwidth", vec!["bandwidth_weighted"])
            } else {
                ("momentum", vec!["momentum_weighted"])
            }
        }
    }
}

/// Mirror `app.services.explanation_projection.get_primary_explanation`.
fn primary_explanation(codes: &[&str]) -> Option<String> {
    let code = *codes.first()?;
    Some(match code {
        "momentum_weighted" => "Weighted by your recent reading momentum".into(),
        "bandwidth_weighted" => "Weighted by your preferred reading effort".into(),
        "pure_random" => "Pure random selection".into(),
        "fallback_random" => "Fallback to random selection".into(),
        other => {
            let mut text = String::new();
            for (index, word) in other.split('_').enumerate() {
                if index > 0 {
                    text.push(' ');
                }
                let mut chars = word.chars();
                if let Some(first) = chars.next() {
                    text.extend(first.to_uppercase());
                    text.push_str(chars.as_str());
                }
            }
            text
        }
    })
}

/// Mirror `comic_pile.snooze_backoff.fibonacci`.
fn fibonacci(n: i64) -> i64 {
    if n <= 0 {
        return 0;
    }
    if n <= 2 {
        return 1;
    }
    let (mut a, mut b) = (1_i64, 1_i64);
    for _ in 3..=n {
        let next = a + b;
        a = b;
        b = next;
    }
    b
}

/// Mirror `comic_pile.snooze_backoff.compute_backoff_sessions`.
fn compute_backoff_sessions(snooze_count: i64) -> i64 {
    if snooze_count <= 0 {
        return 0;
    }
    let pair = (snooze_count + 1) / 2;
    fibonacci(pair + 1)
}

/// Mirror `comic_pile.snooze_backoff.is_eligible`.
fn is_backoff_eligible(snooze_count: i64, later_session_count: i64) -> bool {
    snooze_count <= 0 || later_session_count >= compute_backoff_sessions(snooze_count)
}

/// Mirror `app.momentum.compute_momentum_breakdown` for one candidate.
fn momentum_weight(
    last_rating: Option<f64>,
    last_activity_epoch: Option<f64>,
    now: f64,
    streak_depth: i64,
) -> (f64, Vec<&'static str>) {
    let Some(rating) = last_rating else {
        return (1.0, vec![]);
    };
    if rating < 4.0 {
        return (1.0, vec![]);
    }
    let staleness_hours = last_activity_epoch
        .map(|epoch| ((now - epoch) / 3600.0).max(0.0))
        .unwrap_or(f64::INFINITY);
    let decay = if staleness_hours.is_finite() && staleness_hours >= 0.0 {
        2_f64.powf(-staleness_hours / 48.0)
    } else {
        0.0
    };
    let base_bonus = ((rating - 4.0) * 0.5).min(1.0);
    let rating_component = base_bonus * decay;
    let depth = streak_depth.min(4);
    let streak_component = (depth as f64 * 0.25).min(1.0) * decay.max(0.25);
    let total = (rating_component + streak_component).min(2.0);
    let mut factors = Vec::new();
    if rating_component > 0.0 {
        factors.push("recent_high_rating");
    }
    if streak_component > 0.0 {
        factors.push("same_thread_momentum");
    }
    (1.0 + total, factors)
}

/// Mirror `comic_pile.recommendation_weights.classify_effort_band`.
fn classify_effort_band(minutes: Option<f64>) -> Option<&'static str> {
    let minutes = minutes.filter(|value| value.is_finite() && *value >= 0.0)?;
    if minutes < 12.0 {
        Some("light")
    } else if minutes < 18.0 {
        Some("medium")
    } else {
        Some("heavy")
    }
}

/// Mirror `comic_pile.recommendation_weights.WEIGHTS_BY_MODE_AND_BAND` and the
/// aligned reason-code table for one candidate.
fn bandwidth_weight(bandwidth: &str, minutes: Option<f64>) -> (f64, Option<&'static str>) {
    let Some(band) = classify_effort_band(minutes) else {
        return (1.0, None);
    };
    match (bandwidth, band) {
        ("light", "light") => (1.5, Some("bandwidth_light_favors_low_effort")),
        ("light", "medium") => (1.0, Some("bandwidth_light_medium_effort_neutral")),
        ("light", "heavy") => (0.75, Some("bandwidth_light_dampens_high_effort")),
        ("deep", "light") => (0.9, Some("bandwidth_deep_dampens_low_effort")),
        ("deep", "medium") => (1.0, Some("bandwidth_deep_medium_effort_neutral")),
        ("deep", "heavy") => (1.25, Some("bandwidth_deep_permits_high_effort")),
        _ => (1.0, Some("bandwidth_balanced_neutral")),
    }
}

/// Python `round(value, digits)` for the values this endpoint records.
fn python_round(value: f64, digits: i32) -> f64 {
    if !value.is_finite() {
        return value;
    }
    let scale = 10_f64.powi(digits);
    (value * scale).round_ties_even() / scale
}

// ---------------------------------------------------------------------------
// Query models and database work
// ---------------------------------------------------------------------------

struct PoolRow {
    id: i32,
    title: String,
    format: String,
    queue_position: i32,
    last_rating: Option<f64>,
    last_activity_epoch: Option<f64>,
    last_activity_text: Option<String>,
    total_issues: Option<i32>,
    reading_progress: Option<String>,
    next_unread_issue_id: Option<i32>,
    unread_count: i32,
    issue_number: Option<String>,
}

/// One candidate's resolved reading-effort estimate, matching
/// `app.services.reading_effort.EffortEstimate`.
#[derive(Clone, Debug)]
struct EffortEstimate {
    minutes: Option<f64>,
    band: &'static str,
    source: &'static str,
    confidence: f64,
    sample_count: i32,
}

impl EffortEstimate {
    fn neutral() -> Self {
        Self {
            minutes: None,
            band: "unknown",
            source: "unknown",
            confidence: 0.0,
            sample_count: 0,
        }
    }
    fn observed(minutes: Option<f64>, source: &'static str, sample_count: i32) -> Self {
        Self {
            minutes,
            band: resolve_effort_band(minutes),
            source,
            confidence: (0.5 + 0.1 * (sample_count - 2) as f64).min(0.95),
            sample_count,
        }
    }
    fn era(minutes: f64) -> Self {
        Self {
            minutes: Some(minutes),
            band: resolve_effort_band(Some(minutes)),
            source: "era_prior",
            confidence: 0.25,
            sample_count: 0,
        }
    }
}

/// Mirror `app.services.reading_effort.resolve_effort_band`.
fn resolve_effort_band(minutes: Option<f64>) -> &'static str {
    let Some(minutes) = minutes else {
        return "unknown";
    };
    if minutes < 12.0 {
        "light"
    } else if minutes >= 18.0 {
        "deep"
    } else {
        "balanced"
    }
}

/// Mirror `app.services.reading_effort.era_prior_minutes`.
fn era_prior_minutes(year: Option<i32>) -> Option<f64> {
    let year = year?;
    Some(if year <= 1969 {
        10.0
    } else if year < 2000 {
        14.0
    } else {
        17.0
    })
}

/// Mirror `app.services.reading_effort.resolve_effort_estimate`.
fn resolve_effort_estimate(
    issue_median: Option<(f64, i32)>,
    thread_median: Option<(f64, i32)>,
    era_minutes: Option<f64>,
) -> EffortEstimate {
    if let Some((minutes, samples)) = issue_median.filter(|(_, samples)| *samples >= 2) {
        return EffortEstimate::observed(Some(minutes), "observed_issue", samples);
    }
    if let Some((minutes, samples)) = thread_median.filter(|(_, samples)| *samples >= 2) {
        return EffortEstimate::observed(Some(minutes), "observed_thread", samples);
    }
    if let Some(minutes) = era_minutes {
        return EffortEstimate::era(minutes);
    }
    EffortEstimate::neutral()
}

/// Python isoformat for a PostgreSQL `timestamp with time zone` text value.
fn python_timestamp(value: &str) -> String {
    let Some((date, time)) = value.split_once(' ') else {
        return value.to_owned();
    };
    let offset_start = time
        .char_indices()
        .rev()
        .find(|(index, character)| *index >= 8 && matches!(character, '+' | '-'))
        .map(|(index, _)| index);
    let time = match offset_start {
        Some(index) => {
            let (clock, offset) = time.split_at(index);
            let (sign, offset) = offset.split_at(1);
            let offset = offset.trim();
            let normalized = if offset.contains(':') {
                offset.to_owned()
            } else if offset.len() == 2 {
                format!("{offset}:00")
            } else if offset.len() == 4 {
                format!("{}:{}", &offset[..2], &offset[2..])
            } else {
                offset.to_owned()
            };
            format!("{clock}{sign}{normalized}")
        }
        None => time.to_owned(),
    };
    format!("{date}T{time}")
}

const POOL_SQL: &str = r#"
SELECT t.id, t.title, t.format, t.queue_position,
       t.last_rating::double precision, extract(epoch FROM t.last_activity_at)::float8,
       t.last_activity_at::text, t.total_issues, t.reading_progress,
       t.next_unread_issue_id, COALESCE(u.unread_count, 0)::int, i.issue_number
FROM threads t
LEFT JOIN (
    SELECT thread_id, count(*) AS unread_count
    FROM issues WHERE status = 'unread' GROUP BY thread_id
) u ON u.thread_id = t.id
LEFT JOIN issues i ON i.id = t.next_unread_issue_id AND i.status = 'unread'
WHERE t.user_id = $1 AND t.status = 'active' AND t.queue_position >= 1
  AND t.is_blocked = false AND t.id <> ALL($2::int[])
ORDER BY t.queue_position
"#;

async fn load_pool(
    tx: &Transaction<'_>,
    user_id: i32,
    excluded: &[i32],
) -> Result<Vec<PoolRow>, ApiError> {
    let rows = tx
        .query(POOL_SQL, &[&user_id, &excluded])
        .await
        .map_err(db::query_error)?;
    rows.iter()
        .map(|row| {
            Ok(PoolRow {
                id: row.try_get(0).map_err(db::query_error)?,
                title: row.try_get(1).map_err(db::query_error)?,
                format: row.try_get(2).map_err(db::query_error)?,
                queue_position: row.try_get(3).map_err(db::query_error)?,
                last_rating: row.try_get(4).map_err(db::query_error)?,
                last_activity_epoch: row.try_get(5).map_err(db::query_error)?,
                last_activity_text: row.try_get(6).map_err(db::query_error)?,
                total_issues: row.try_get(7).map_err(db::query_error)?,
                reading_progress: row.try_get(8).map_err(db::query_error)?,
                next_unread_issue_id: row.try_get(9).map_err(db::query_error)?,
                unread_count: row.try_get(10).map_err(db::query_error)?,
                issue_number: row.try_get(11).map_err(db::query_error)?,
            })
        })
        .collect()
}

/// Durable cross-session snooze backoff, mirroring
/// `derive_cross_session_excluded_thread_ids` in legacy execution.
async fn durable_snoozed(tx: &Transaction<'_>, user_id: i32) -> Result<HashSet<i32>, ApiError> {
    let rows = tx
        .query(
            "SELECT t.id, extract(epoch FROM t.last_activity_at)::float8, e.type,
                    extract(epoch FROM e.timestamp)::float8, e.id
             FROM threads t
             LEFT JOIN events e ON e.thread_id = t.id AND e.type IN ('snooze','unsnooze')
             WHERE t.user_id = $1 AND t.status = 'active' AND t.is_blocked = false
             ORDER BY t.id, e.timestamp, e.id",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?;
    let starts: Vec<f64> = tx
        .query(
            "SELECT extract(epoch FROM started_at)::float8 FROM sessions
             WHERE user_id = $1 ORDER BY started_at",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| row.get(0))
        .collect();
    if rows.is_empty() || starts.is_empty() {
        return Ok(HashSet::new());
    }
    struct Row {
        last_activity: Option<f64>,
        kind: Option<String>,
        timestamp: Option<f64>,
    }
    let mut grouped: HashMap<i32, Vec<Row>> = HashMap::new();
    for row in &rows {
        grouped.entry(row.get(0)).or_default().push(Row {
            last_activity: row.get(1),
            kind: row.get(2),
            timestamp: row.get(3),
        });
    }
    let mut excluded = HashSet::new();
    for (thread_id, thread_rows) in grouped {
        let boundary = thread_rows.first().and_then(|row| row.last_activity);
        let after_reset = |row: &Row| {
            row.kind.is_some()
                && row.timestamp.is_some()
                && (boundary.is_none() || row.timestamp.unwrap() > boundary.unwrap())
        };
        let snoozes: Vec<f64> = thread_rows
            .iter()
            .filter(|row| row.kind.as_deref() == Some("snooze") && after_reset(row))
            .filter_map(|row| row.timestamp)
            .collect();
        if snoozes.is_empty() {
            continue;
        }
        let unsnoozes: Vec<f64> = thread_rows
            .iter()
            .filter(|row| row.kind.as_deref() == Some("unsnooze") && after_reset(row))
            .filter_map(|row| row.timestamp)
            .collect();
        let latest_snooze = snoozes.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        if unsnoozes.iter().copied().fold(f64::NEG_INFINITY, f64::max) > latest_snooze {
            continue;
        }
        let later = starts
            .iter()
            .filter(|start| **start > latest_snooze)
            .count() as i64;
        if !is_backoff_eligible(snoozes.len() as i64, later) {
            excluded.insert(thread_id);
        }
    }
    Ok(excluded)
}

/// Reader-owned durable queue exclusions (`fetch_excluded_thread_ids`).
async fn excluded_status_ids(tx: &Transaction<'_>, user_id: i32) -> Result<Vec<i32>, ApiError> {
    Ok(tx
        .query(
            "SELECT id FROM threads WHERE user_id = $1 AND status = 'excluded' ORDER BY id",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| row.get(0))
        .collect())
}

/// Effort estimates for every candidate, matching
/// `compute_effort_estimates_batch` (linked observations plus confirmed
/// publication metadata).
async fn effort_estimates(
    tx: &Transaction<'_>,
    user_id: i32,
    candidates: &[(i32, Option<i32>)],
) -> Result<HashMap<(i32, Option<i32>), EffortEstimate>, ApiError> {
    let mut by_thread: HashMap<i32, Vec<f64>> = HashMap::new();
    let mut by_issue: HashMap<(i32, i32), Vec<f64>> = HashMap::new();
    if !candidates.is_empty() {
        let rows = tx
            .query(
                "SELECT r.thread_id, r.issue_id,
                        extract(epoch FROM (r.timestamp - x.timestamp))::float8
                 FROM events r
                 JOIN events x ON x.id = r.source_roll_event_id
                 JOIN threads t ON t.id = r.thread_id
                 WHERE r.type = 'rate' AND x.type = 'roll'
                   AND x.selected_thread_id = r.thread_id AND t.user_id = $1
                 ORDER BY r.id",
                &[&user_id],
            )
            .await
            .map_err(db::query_error)?;
        for row in rows {
            let thread_id: i32 = row.get(0);
            let issue_id: Option<i32> = row.get(1);
            let seconds: Option<f64> = row.get(2);
            let Some(seconds) = seconds.filter(|value| (60.0..=21600.0).contains(value)) else {
                continue;
            };
            let minutes = seconds / 60.0;
            by_thread.entry(thread_id).or_default().push(minutes);
            if let Some(issue_id) = issue_id {
                by_issue
                    .entry((thread_id, issue_id))
                    .or_default()
                    .push(minutes);
            }
        }
    }
    let thread_medians: HashMap<i32, (f64, i32)> = by_thread
        .into_iter()
        .filter_map(|(thread_id, samples)| {
            let samples_count = samples.len() as i32;
            session_bandwidth::median(Some(&samples))
                .map(|value| (thread_id, (value, samples_count)))
        })
        .collect();
    let issue_medians: HashMap<(i32, i32), (f64, i32)> = by_issue
        .into_iter()
        .filter_map(|(key, samples)| {
            let samples_count = samples.len() as i32;
            session_bandwidth::median(Some(&samples)).map(|value| (key, (value, samples_count)))
        })
        .collect();

    let unique_threads: Vec<i32> = candidates
        .iter()
        .map(|(thread, _)| *thread)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let unique_issues: Vec<i32> = candidates
        .iter()
        .filter_map(|(_, issue)| *issue)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let mut years: HashMap<(String, i32), i32> = HashMap::new();
    let metadata = tx
        .query(
            "SELECT 'issue' AS kind, m.issue_id AS target, e.metadata_json::text, m.id
             FROM issue_external_identity_mappings m
             JOIN external_identities e ON e.id = m.external_identity_id
             JOIN issues i ON i.id = m.issue_id
             JOIN threads t ON t.id = i.thread_id
             WHERE t.user_id = $1 AND m.status = 'confirmed' AND m.issue_id = ANY($2::int[])
             UNION ALL
             SELECT 'thread', m.thread_id, e.metadata_json::text, m.id
             FROM thread_external_series_mappings m
             JOIN external_identities e ON e.id = m.external_identity_id
             JOIN threads t ON t.id = m.thread_id
             WHERE t.user_id = $1 AND m.status = 'confirmed' AND m.thread_id = ANY($3::int[])
             ORDER BY kind, id",
            &[&user_id, &unique_issues, &unique_threads],
        )
        .await
        .map_err(db::query_error)?;
    for row in metadata {
        let metadata: Value = row
            .try_get::<_, Option<String>>(2)
            .map_err(db::query_error)?
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or(Value::Null);
        if let Some(year) = session_bandwidth::year(&metadata) {
            years
                .entry((row.get::<_, String>(0), row.get::<_, i32>(1)))
                .or_insert(year);
        }
    }

    let mut estimates = HashMap::new();
    for (thread_id, issue_id) in candidates {
        let issue_median =
            issue_id.and_then(|issue| issue_medians.get(&(*thread_id, issue)).copied());
        let thread_median = thread_medians.get(thread_id).copied();
        let publication_year = issue_id
            .and_then(|issue| years.get(&("issue".into(), issue)).copied())
            .or_else(|| years.get(&("thread".into(), *thread_id)).copied());
        estimates.insert(
            (*thread_id, *issue_id),
            resolve_effort_estimate(
                issue_median,
                thread_median,
                era_prior_minutes(publication_year),
            ),
        );
    }
    Ok(estimates)
}

/// Session events for momentum streak depth (`fetch_session_events`).
async fn session_streak(
    tx: &Transaction<'_>,
    session_id: i32,
) -> Result<HashMap<i32, i64>, ApiError> {
    let rows = tx
        .query(
            "SELECT thread_id, count(*) FROM events
             WHERE session_id = $1 AND type = 'rate' AND thread_id IS NOT NULL
             GROUP BY thread_id
             UNION ALL
             SELECT selected_thread_id, count(*) FROM events
             WHERE session_id = $1 AND type = 'roll' AND selected_thread_id IS NOT NULL
             GROUP BY selected_thread_id",
            &[&session_id],
        )
        .await
        .map_err(db::query_error)?;
    let mut streaks: HashMap<i32, i64> = HashMap::new();
    for row in rows {
        let thread_id: Option<i32> = row.get(0);
        if let Some(thread_id) = thread_id {
            *streaks.entry(thread_id).or_default() += row.get::<_, i64>(1);
        }
    }
    Ok(streaks)
}

/// Dense reader-visible Queue ordinal, matching legacy `dense_positions`.
async fn display_position(
    tx: &Transaction<'_>,
    user_id: i32,
    thread_id: i32,
) -> Result<i32, ApiError> {
    let rows = tx
        .query(
            "SELECT id FROM threads WHERE user_id = $1 AND status = 'active'
             ORDER BY is_blocked, queue_position, id",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(rows
        .iter()
        .position(|row| row.get::<_, i32>(0) == thread_id)
        .map(|index| index as i32 + 1)
        .unwrap_or(0))
}

/// Fallback issue lookup used when the pool's joined frontier is unexpectedly
/// absent, mirroring the Python legacy branch.
async fn unread_issue(
    tx: &Transaction<'_>,
    issue_id: i32,
) -> Result<Option<(i32, String)>, ApiError> {
    Ok(tx
        .query_opt(
            "SELECT id, issue_number FROM issues WHERE id = $1 AND status = 'unread'",
            &[&issue_id],
        )
        .await
        .map_err(db::query_error)?
        .map(|row| (row.get(0), row.get(1))))
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

// Discard a connection on outer cancellation, query timeout, or aborted transaction.
struct Pending(Option<Object>);
impl Drop for Pending {
    fn drop(&mut self) {
        if let Some(connection) = self.0.take() {
            drop(connection);
        }
    }
}

fn conflict() -> ApiError {
    ApiError(StatusCode::CONFLICT, "No pending roll to skip. Roll first.")
}

fn empty_pool() -> ApiError {
    ApiError(
        StatusCode::BAD_REQUEST,
        "No alternative threads available to skip to",
    )
}

/// Skip the session's pending candidate and advance to another eligible thread.
pub async fn skip_roll(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
) -> Result<Json<RollResponse>, ApiError> {
    let now = now_seconds()?;
    // Reuse the native session bootstrap so session/die resolution, bandwidth
    // initialization, and timezone capture remain identical to the GET path.
    let active = reading_session::bootstrap(&state, user, None, SessionPolicy::default()).await?;
    let session = active.session;
    let Some(skipped_thread_id) = session.pending_thread_id else {
        return Err(conflict());
    };

    let mut pending = Pending(Some(db::checkout(&state).await?));
    let result = tokio::time::timeout(
        state.request_timeout,
        mutate(
            &state,
            user,
            &session,
            skipped_thread_id,
            active.current_die,
            now,
            pending.0.as_mut().unwrap(),
        ),
    )
    .await;
    match result {
        Err(_) => Err(unavailable()),
        Ok(Ok(response)) => {
            drop(pending.0.take());
            Ok(Json(response))
        }
        Ok(Err(error)) => Err(error),
    }
}

#[allow(clippy::too_many_arguments)]
async fn mutate(
    _state: &AppState,
    user: AuthenticatedUser,
    session: &ReadingSession,
    skipped_thread_id: i32,
    current_die: i32,
    now: f64,
    connection: &mut Object,
) -> Result<RollResponse, ApiError> {
    let tx = connection
        .build_transaction()
        .isolation_level(IsolationLevel::ReadCommitted)
        .start()
        .await
        .map_err(db::query_error)?;
    tx.batch_execute("SET LOCAL TIME ZONE 'UTC'")
        .await
        .map_err(db::query_error)?;

    let snoozed_ids = session.snoozed_thread_ids.clone().unwrap_or_default();
    let mut skipped_ids = session.skipped_thread_ids.clone().unwrap_or_default();

    // derive_effective_roll_excluded_thread_ids: session snoozes, session
    // skips, durable backoff, then durable "Remove from Queue" exclusions.
    let mut excluded: Vec<i32> = Vec::new();
    let mut seen: HashSet<i32> = HashSet::new();
    for id in snoozed_ids
        .iter()
        .copied()
        .chain(skipped_ids.iter().copied())
        .chain(durable_snoozed(&tx, user.id()).await?.into_iter())
    {
        if seen.insert(id) {
            excluded.push(id);
        }
    }
    for id in excluded_status_ids(&tx, user.id()).await? {
        if seen.insert(id) {
            excluded.push(id);
        }
    }
    excluded.push(skipped_thread_id);

    let mut pool = load_pool(&tx, user.id(), &excluded).await?;
    if pool.is_empty() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(empty_pool());
    }
    pool.truncate(current_die.max(0) as usize);
    if pool.is_empty() {
        tx.rollback().await.map_err(db::query_error)?;
        return Err(empty_pool());
    }

    let bandwidth = session
        .active_bandwidth
        .as_deref()
        .filter(|value| !value.is_empty())
        .unwrap_or("balanced");
    let intent = session
        .active_intent
        .as_deref()
        .filter(|value| !value.is_empty())
        .unwrap_or("balanced");
    let control_mode = std::env::var("RECOMMENDATION_CONTROL_MODE")
        .ok()
        .filter(|value| value == "legacy" || value == "contextual")
        .unwrap_or_else(|| "contextual".into());
    let algorithm_version = if control_mode == "legacy" {
        "legacy"
    } else {
        "v1-contextual"
    };
    let mode = resolve_selection_mode(bandwidth, intent, &control_mode);
    let (_, reason_codes) = recorded_selection_method(mode, bandwidth);

    // Effort is always resolved for the audit payload, even under balanced
    // bandwidth where it cannot bias the draw.
    let candidates: Vec<(i32, Option<i32>)> = pool
        .iter()
        .map(|row| {
            let issue_id = row.total_issues.and(row.next_unread_issue_id);
            (row.id, issue_id)
        })
        .collect();
    let effort = effort_estimates(&tx, user.id(), &candidates).await?;

    let streaks = session_streak(&tx, session.id).await?;
    let mut weights_applied = false;
    let mut weights: Vec<(i32, f64, Vec<&'static str>)> = Vec::with_capacity(pool.len());
    for row in &pool {
        match mode {
            SelectionMode::ForcedLegacy | SelectionMode::PureRandomBypass => {
                weights.push((row.id, 1.0, vec![]));
            }
            SelectionMode::LegacyUniform | SelectionMode::ContextualWeighted => {
                let (momentum, mut factors) = momentum_weight(
                    row.last_rating,
                    row.last_activity_epoch,
                    now,
                    streaks.get(&row.id).copied().unwrap_or(0),
                );
                let minutes = effort
                    .get(&(row.id, row.total_issues.and(row.next_unread_issue_id)))
                    .and_then(|estimate| estimate.minutes);
                let (bandwidth_factor, bandwidth_reason) = if matches!(bandwidth, "light" | "deep")
                {
                    bandwidth_weight(bandwidth, minutes)
                } else {
                    (1.0, None)
                };
                let combined = momentum * bandwidth_factor;
                if (combined - 1.0).abs() > 1e-9 {
                    weights_applied = true;
                }
                if (bandwidth_factor - 1.0).abs() > 1e-9 {
                    if let Some(reason) = bandwidth_reason {
                        if !factors.contains(&reason) {
                            factors.push(reason);
                        }
                    }
                }
                weights.push((row.id, combined, factors));
            }
        }
    }

    let selected_index = draw_index(&weights);
    let selected = &pool[selected_index];
    let selected_issue = effective_issue(&tx, selected).await?;
    let selected_effort = effort
        .get(&(
            selected.id,
            selected.total_issues.and(selected.next_unread_issue_id),
        ))
        .cloned()
        .unwrap_or_else(EffortEstimate::neutral);

    let json_weights: Option<Vec<Value>> = if weights.is_empty() {
        None
    } else {
        Some(
            weights
                .iter()
                .map(|(candidate_id, weight, factors)| {
                    json!({
                        "candidate_id": candidate_id,
                        "weight": python_round(*weight, 4),
                        "reasons": factors,
                        "factors": factors,
                    })
                })
                .collect(),
        )
    };
    let selected_weight = weights.get(selected_index).map(|entry| entry.1);
    let recommendation_context = json!({
        "context_version": 2,
        "selected_candidate": {
            "thread_id": selected.id,
            "issue_id": selected_issue.as_ref().map(|issue| issue.0),
            "issue_number": selected_issue.as_ref().map(|issue| issue.1.clone()),
            "effort_minutes": selected_effort.minutes.map(|value| python_round(value, 2)),
            "effort_band": selected_effort.band,
            "effort_source": selected_effort.source,
            "effort_confidence": python_round(selected_effort.confidence, 3),
            "effort_sample_count": selected_effort.sample_count,
        },
        "candidate_weights": json_weights,
        "selected_weight": selected_weight.map(|value| python_round(value, 4)),
        "bandwidth": normalize_bandwidth(Some(bandwidth)),
        "bandwidth_source": session.bandwidth_source.clone().unwrap_or_else(|| "default".into()),
        "bandwidth_confidence": python_round(session.bandwidth_confidence.unwrap_or(0.0), 3),
        "random_bypass": !weights_applied,
        "balanced_neutrality": !weights_applied,
        "algorithm_version": algorithm_version,
        "control_mode": control_mode,
    });
    let rolling_context = json!({
        "schema_version": 1,
        "algorithm_version": algorithm_version,
        "control_mode": control_mode,
        "die_size": current_die,
        "selected_queue_position": selected.queue_position,
        "bounded_candidate_ids": pool.iter().map(|row| row.id).collect::<Vec<_>>(),
        "selected_index": selected_index,
        "selection_method": "skip",
        "session_timezone": session.timezone.clone(),
        "local_hour": local_hour(session.timezone.as_deref(), now),
        "selected_thread_last_rating": selected.last_rating,
        "selected_thread_last_activity_at": selected.last_activity_text.as_deref().map(python_timestamp),
        "effort_estimate": selected_effort.band,
    });

    // Record the skip event before the replacement roll event. Readers order by
    // (timestamp, id), so the earlier id keeps the skip attributed to the
    // original pending thread. Both events share one captured timestamp; the
    // event-id order preserves the ordering Python gets from its insert order.
    let event_now = now_seconds()?;
    tx.query_one(
        "INSERT INTO events (type, timestamp, session_id, thread_id)
         VALUES ('rolled_but_skipped', to_timestamp($1), $2, $3) RETURNING id",
        &[&event_now, &session.id, &skipped_thread_id],
    )
    .await
    .map_err(db::query_error)?;

    let codes: Vec<String> = reason_codes.iter().map(|code| (*code).into()).collect();
    let event_id: i32 = tx
        .query_one(
            "INSERT INTO events (type, timestamp, session_id, selected_thread_id, die,
                result, selection_method, recommendation_reason_codes,
                recommendation_context, issue_id, issue_number,
                rolling_recommendation_context)
             VALUES ('roll', to_timestamp($1), $2, $3, $4, $5, 'skip', $6::text[],
                $7::json, $8, $9, $10::json) RETURNING id",
            &[
                &event_now,
                &session.id,
                &selected.id,
                &current_die,
                &(selected_index as i32 + 1),
                &codes,
                &recommendation_context.to_string(),
                &selected_issue.as_ref().map(|issue| issue.0),
                &selected_issue.as_ref().map(|issue| issue.1.clone()),
                &rolling_context.to_string(),
            ],
        )
        .await
        .map_err(db::query_error)?
        .get(0);

    let candidate_factors: Option<Vec<Value>> = json_weights.as_ref().map(|weights| {
        weights
            .iter()
            .zip(effort_for_pool(&pool, &effort))
            .map(|(weight, estimate)| {
                json!({
                    "candidate_id": weight["candidate_id"],
                    "factors": weight["factors"],
                    "weight": weight["weight"],
                    "effort_minutes": estimate.minutes.map(|value| python_round(value, 2)),
                    "effort_band": estimate.band,
                    "effort_source": estimate.source,
                    "effort_confidence": python_round(estimate.confidence, 3),
                    "effort_sample_count": estimate.sample_count,
                })
            })
            .collect()
    });
    tx.execute(
        "INSERT INTO recommendation_contexts (event_id, schema_version, created_at,
            intent, intent_source, intent_confidence, bandwidth, bandwidth_source,
            bandwidth_confidence, candidate_factors, final_weight, random_bypass,
            balanced_neutrality, effort_minutes, effort_band, effort_source,
            effort_confidence, effort_sample_count)
         VALUES ($1, 2, to_timestamp($2), $3, $4, $5, $6, $7, $8, $9::json,
            $10, $11, $12, $13, $14, $15, $16, $17)",
        &[
            &event_id,
            &event_now,
            &normalize_intent(Some(intent)),
            &session
                .intent_source
                .clone()
                .unwrap_or_else(|| "default".into()),
            &if session.active_intent.is_some() {
                1.0_f64
            } else {
                0.0
            },
            &normalize_bandwidth(Some(bandwidth)),
            &session
                .bandwidth_source
                .clone()
                .unwrap_or_else(|| "default".into()),
            &session.bandwidth_confidence.unwrap_or(0.0),
            &candidate_factors.map(|value| Value::Array(value).to_string()),
            &selected_weight,
            &(!weights_applied),
            &(!weights_applied),
            &selected_effort.minutes.map(|value| python_round(value, 2)),
            &selected_effort.band,
            &selected_effort.source,
            &python_round(selected_effort.confidence, 3),
            &selected_effort.sample_count,
        ],
    )
    .await
    .map_err(db::query_error)?;

    if !skipped_ids.contains(&skipped_thread_id) {
        skipped_ids.push(skipped_thread_id);
    }
    let pending_updated_at = now_seconds()?;
    tx.execute(
        "UPDATE sessions SET skipped_thread_ids = $2::json,
            pending_thread_id = $3, pending_thread_updated_at = to_timestamp($4)
         WHERE id = $1 AND user_id = $5",
        &[
            &session.id,
            &serde_json::to_string(&skipped_ids).map_err(|_| internal())?,
            &selected.id,
            &pending_updated_at,
            &user.id(),
        ],
    )
    .await
    .map_err(db::query_error)?;

    let queue_position = display_position(&tx, user.id(), selected.id).await?;
    tx.commit().await.map_err(db::query_error)?;

    Ok(RollResponse {
        thread_id: selected.id,
        title: selected.title.clone(),
        format: normalize_format(&selected.format),
        issues_remaining: selected.unread_count,
        queue_position,
        die_size: current_die,
        result: selected_index as i32 + 1,
        offset: snoozed_ids.len() as i32,
        snoozed_count: snoozed_ids.len() as i32,
        issue_id: selected_issue.as_ref().map(|issue| issue.0),
        issue_number: selected_issue.as_ref().map(|issue| issue.1.clone()),
        next_issue_id: selected_issue.as_ref().map(|issue| issue.0),
        next_issue_number: selected_issue.as_ref().map(|issue| issue.1.clone()),
        total_issues: selected.total_issues,
        reading_progress: selected.reading_progress.clone(),
        explanation: primary_explanation(&reason_codes),
    })
}

fn effort_for_pool(
    pool: &[PoolRow],
    effort: &HashMap<(i32, Option<i32>), EffortEstimate>,
) -> Vec<EffortEstimate> {
    pool.iter()
        .map(|row| {
            effort
                .get(&(row.id, row.total_issues.and(row.next_unread_issue_id)))
                .cloned()
                .unwrap_or_else(EffortEstimate::neutral)
        })
        .collect()
}

/// Mirror the legacy Python frontier branch for the selected candidate.
async fn effective_issue(
    tx: &Transaction<'_>,
    row: &PoolRow,
) -> Result<Option<(i32, String)>, ApiError> {
    let Some(frontier) = row.next_unread_issue_id else {
        return Ok(None);
    };
    if row.total_issues.is_none() {
        return Ok(None);
    }
    if row.unread_count > 0 {
        if let Some(number) = row.issue_number.clone() {
            return Ok(Some((frontier, number)));
        }
    }
    unread_issue(tx, frontier).await
}

/// Mirror `comic_pile.recommendation_selection.normalize_intent`.
fn normalize_intent(value: Option<&str>) -> &'static str {
    match value {
        Some("momentum") => "momentum",
        Some("familiar") => "familiar",
        Some("explore") => "explore",
        Some("random") => "random",
        _ => "balanced",
    }
}

/// Local hour for the rolling recommendation context. Invalid or unavailable
/// timezones are a soft failure in Python and resolve to `None` here too.
fn local_hour(timezone: Option<&str>, now: f64) -> Option<u32> {
    let timezone = timezone?;
    let tz: chrono_tz::Tz = timezone.parse().ok()?;
    let utc = chrono::DateTime::<chrono::Utc>::from_timestamp(now as i64, 0)?;
    Some(chrono::Timelike::hour(&utc.with_timezone(&tz)))
}

/// Weighted chooser matching `select_from_pool`/`select_bandwidth_weighted`.
fn draw_index(weights: &[(i32, f64, Vec<&'static str>)]) -> usize {
    let pool_size = weights.len();
    let mut rng = rand::rng();
    let total: f64 = weights.iter().map(|entry| entry.1).sum();
    if !total.is_finite() || total <= 0.0 {
        return rng.random_range(0..pool_size);
    }
    let pick = rng.random::<f64>() * total;
    let mut cumulative = 0.0;
    let mut selected = pool_size - 1;
    for (index, entry) in weights.iter().enumerate() {
        cumulative += entry.1;
        if pick < cumulative {
            selected = index;
            break;
        }
    }
    selected
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn format_intent_and_bandwidth_normalization_match_python() {
        assert_eq!(normalize_format("  COMICS "), "Comic");
        assert_eq!(normalize_format("digital"), "Digital");
        assert_eq!(normalize_format(" Manga "), "Manga");
        assert_eq!(normalize_bandwidth(Some("light")), "light");
        assert_eq!(normalize_bandwidth(Some("unknown")), "balanced");
        assert_eq!(normalize_intent(Some("explore")), "explore");
        assert_eq!(normalize_intent(None), "balanced");
    }

    #[test]
    fn selection_modes_and_reason_codes_follow_the_python_control_path() {
        assert_eq!(
            resolve_selection_mode("balanced", "balanced", "contextual"),
            SelectionMode::LegacyUniform
        );
        assert_eq!(
            resolve_selection_mode("balanced", "random", "contextual"),
            SelectionMode::PureRandomBypass
        );
        assert_eq!(
            resolve_selection_mode("light", "balanced", "contextual"),
            SelectionMode::ContextualWeighted
        );
        assert_eq!(
            resolve_selection_mode("balanced", "balanced", "legacy"),
            SelectionMode::ForcedLegacy
        );
        assert_eq!(
            recorded_selection_method(SelectionMode::LegacyUniform, "balanced"),
            ("momentum", vec!["momentum_weighted"])
        );
        assert_eq!(
            recorded_selection_method(SelectionMode::ContextualWeighted, "deep"),
            ("bandwidth", vec!["bandwidth_weighted"])
        );
        assert_eq!(
            primary_explanation(&["forced_legacy"]).as_deref(),
            Some("Forced Legacy")
        );
        assert_eq!(
            primary_explanation(&["bandwidth_weighted"]).as_deref(),
            Some("Weighted by your preferred reading effort")
        );
    }

    #[test]
    fn effort_bands_and_weights_match_the_central_table() {
        assert_eq!(classify_effort_band(Some(11.9)), Some("light"));
        assert_eq!(classify_effort_band(Some(12.0)), Some("medium"));
        assert_eq!(classify_effort_band(Some(18.0)), Some("heavy"));
        assert_eq!(classify_effort_band(Some(-1.0)), None);
        assert_eq!(classify_effort_band(None), None);
        assert_eq!(
            bandwidth_weight("light", Some(5.0)),
            (1.5, Some("bandwidth_light_favors_low_effort"))
        );
        assert_eq!(
            bandwidth_weight("light", Some(20.0)),
            (0.75, Some("bandwidth_light_dampens_high_effort"))
        );
        assert_eq!(
            bandwidth_weight("deep", Some(5.0)),
            (0.9, Some("bandwidth_deep_dampens_low_effort"))
        );
        assert_eq!(
            bandwidth_weight("deep", Some(20.0)),
            (1.25, Some("bandwidth_deep_permits_high_effort"))
        );
        assert_eq!(bandwidth_weight("light", None), (1.0, None));
        assert_eq!(bandwidth_weight("deep", None), (1.0, None));
    }

    #[test]
    fn momentum_matches_caps_thresholds_and_decay() {
        // No rating or a low rating contributes no positive momentum.
        assert_eq!(momentum_weight(None, None, 0.0, 4), (1.0, vec![]));
        assert_eq!(momentum_weight(Some(3.9), Some(0.0), 1.0, 4), (1.0, vec![]));
        // A fresh 5.0 rating yields a capped 0.5 rating bonus plus a streak bonus.
        let (weight, factors) = momentum_weight(Some(5.0), Some(0.0), 0.0, 4);
        assert!((weight - 2.5).abs() < 1e-9, "{weight}");
        assert_eq!(factors, vec!["recent_high_rating", "same_thread_momentum"]);
        // One 48-hour half-life halves the rating component.
        let (weight, _) = momentum_weight(Some(5.0), Some(-48.0 * 3600.0), 0.0, 0);
        assert!((weight - 1.25).abs() < 1e-9, "{weight}");
    }

    #[test]
    fn backoff_sequence_matches_python() {
        assert_eq!(
            (1..=6).map(compute_backoff_sessions).collect::<Vec<_>>(),
            vec![1, 1, 2, 2, 3, 3]
        );
        assert!(is_backoff_eligible(0, 0));
        assert!(is_backoff_eligible(1, 1));
        assert!(!is_backoff_eligible(3, 1));
        assert!(is_backoff_eligible(3, 2));
    }

    #[test]
    fn timestamp_and_rounding_match_python_text_forms() {
        assert_eq!(
            python_timestamp("2026-10-30 12:34:56.123456+00"),
            "2026-10-30T12:34:56.123456+00:00"
        );
        assert_eq!(
            python_timestamp("2026-10-30 12:34:56+00"),
            "2026-10-30T12:34:56+00:00"
        );
        assert_eq!(
            python_timestamp("2026-10-30 12:34:56.5-05"),
            "2026-10-30T12:34:56.5-05:00"
        );
        assert_eq!(python_round(1.23456, 4), 1.2346);
        assert_eq!(python_round(1.5, 0), 2.0);
    }

    #[test]
    fn weighted_draw_stays_inside_the_pool() {
        let weights = vec![(1, 0.75, vec![]), (2, 1.0, vec![]), (3, 1.25, vec![])];
        for _ in 0..256 {
            assert!(draw_index(&weights) < weights.len());
        }
        assert_eq!(draw_index(&[(1, 1.0, vec![])]), 0);
        // Collapsed or non-finite totals fall back to a uniform in-pool draw.
        assert!(draw_index(&[(1, 0.0, vec![]), (2, 0.0, vec![])]) < 2);
    }
}
