//! Owner-scoped activity history for the Rust v2 History cutover (#4822).
//!
//! `GET /api/v2/activity` is the one chronological, owner-scoped activity
//! resource that #4405 approved: every action that actually changed the die is
//! visible, including the sessionless dice events the retired session timeline
//! filtered out. One PostgreSQL statement resolves the folded authentication
//! (`FOLDED_AUTH_CTES`) and the whole page, so ownership is enforced inside the
//! statement itself and no second authentication lookup is issued.
//!
//! The statement preserves the causal narrative of the production evidence that
//! reported the defect (2026-11-08, Central time): a roll offer transaction
//! writes its snooze with `clock_timestamp()` and its roll with `NOW()`, so the
//! later snooze row carries an earlier transaction timestamp than the roll it
//! caused. Ordering purely by `(timestamp, id)` therefore showed the roll
//! before its snooze. Instead:
//!
//! * the durable linkage keys pair the rows of one logical action before the
//!   page limit applies — the roll offer key (`roll_offer_key`) links the
//!   snooze whose `dice_command_key` is `<offer>-snooze`, and the
//!   `roll-rating-<thread>-<key>` dice receipt pairs with the issue receipt
//!   whose `issue_command_key` is `<key>`;
//! * the snooze/roll pair is displayed as two rows in write order (snooze,
//!   then the roll it enabled), never reordered back into the inverted
//!   timestamp sequence;
//! * the dice/issue rate pair for one Roll completion collapses into one
//!   rating display, while both audit rows remain persisted — and later
//!   rating corrections with their own command keys stay separate actions;
//! * clusters order by their leader's `(timestamp, id)` — a leader is the
//!   roll or issue receipt of the action — which is causally consistent
//!   because per-reader write transactions serialize;
//! * records without linkage (legacy rows and direct actions) fall back to a
//!   deterministic timestamp-and-id ordering as their own cluster.
//!
//! Cursor pagination encodes both the leader timestamp (epoch microseconds)
//! and its id, and resumes with the same strict ordered-pair comparison, so a
//! timestamp inversion can never skip records between pages. An empty
//! `page_token` behaves like an absent one; a malformed nonempty token is a
//! client error instead of silently filtering on a fabricated id.
use crate::auth::{validate_folded_auth, FoldedAuthRow, VerifiedAccessClaims, FOLDED_AUTH_CTES};
use crate::{db, ApiError, AppState};
use axum::{
    extract::{Query, State},
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::{Arc, OnceLock};

/// One displayed logical action row.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ActivityEvent {
    pub event_id: i32,
    pub event_type: String,
    pub timestamp: String,
    pub die_before: Option<i32>,
    pub die_after: Option<i32>,
    pub rating: Option<f64>,
    pub thread_id: Option<i32>,
    pub thread_title: Option<String>,
    pub issue_id: Option<i32>,
    pub issue_number: Option<String>,
    pub action_display: String,
}

/// One page of the chronological owner-scoped activity history.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ActivityResponse {
    pub events: Vec<ActivityEvent>,
    pub next_page_token: Option<String>,
}

/// Query parameters for `GET /api/v2/activity`.
#[derive(Debug, Default, Deserialize)]
pub struct ActivityQuery {
    pub page_size: Option<i32>,
    pub page_token: Option<String>,
}

const DEFAULT_PAGE_SIZE: i32 = 50;
const MAX_PAGE_SIZE: i32 = 200;

/// Event types the activity resource surfaces: exactly the actions that
/// change or record the die, matching the owner's production verification
/// query for #4822.
const ACTIVITY_EVENT_TYPES: &str = "('roll', 'snooze', 'rate', 'manual_die', 'reset_dice')";

/// The per-event projection: resolved thread reference, saved issue number and
/// the linkage keys that pair one logical action's rows.
///
/// Roll events carry their offered thread in `selected_thread_id`, not
/// `thread_id`; every other event keeps its own `thread_id` meaning. The saved
/// `events.issue_number` wins over the joined issue row because issue deletion
/// nulls `events.issue_id` while the audit row keeps the number.
const SCOPED_EVENTS_CTE: &str = r#"scoped AS (
    SELECT e.id,
           e.type,
           e."timestamp" AS ts,
           e.die,
           e.die_after,
           e.rating,
           CASE WHEN e.type = 'roll' THEN e.selected_thread_id ELSE e.thread_id END AS thread_id,
           e.issue_id,
           COALESCE(e.issue_number, i.issue_number) AS issue_number,
           t.title AS thread_title,
           e.context,
           CASE WHEN e.type = 'roll' THEN e.context->>'roll_offer_key' END AS offer_key,
           CASE
               WHEN e.type = 'snooze'
                    AND e.context->>'dice_command_key' LIKE '%-snooze'
               THEN regexp_replace(e.context->>'dice_command_key', '-snooze$', '')
           END AS snooze_offer_key,
           CASE
               WHEN e.type = 'rate'
                    AND e.context->>'dice_command_key' LIKE 'roll-rating-%'
               THEN substring(
                       e.context->>'dice_command_key'
                       FROM '^roll-rating-[0-9]+-(.+)$'
                   )
           END AS dice_rate_key,
           e.context->>'issue_command_key' AS issue_command_key
    FROM events e
    LEFT JOIN threads t
        ON t.id = CASE WHEN e.type = 'roll'
                  THEN e.selected_thread_id ELSE e.thread_id END
    LEFT JOIN issues i ON i.id = e.issue_id
    WHERE e.user_id = (SELECT user_id FROM me)
      AND e.type IN {ACTIVITY_EVENT_TYPES}
)"#;

/// Pair the rows of one logical action before any page limit.
///
/// The lookup joins are hash joins over the owner's own rows — not per-row
/// scans — and each picks the newest matching row for its key, so a replayed
/// or duplicated audit row cannot split one action into two clusters. Rows
/// without linkage stay their own leader.
const LINKED_EVENTS_CTE: &str = r#"linked AS (
    SELECT s.*,
           COALESCE(roll_pair.roll_id, rate_pair.issue_rate_id, s.id) AS leader_id
    FROM scoped s
    LEFT JOIN (
        SELECT DISTINCT ON (context->>'roll_offer_key')
               id AS roll_id,
               context->>'roll_offer_key' AS offer_key
        FROM scoped
        WHERE type = 'roll' AND context ? 'roll_offer_key'
        ORDER BY context->>'roll_offer_key', id DESC
    ) roll_pair
        ON s.type = 'snooze'
       AND s.snooze_offer_key IS NOT NULL
       AND s.snooze_offer_key = roll_pair.offer_key
    LEFT JOIN (
        SELECT DISTINCT ON (context->>'issue_command_key')
               id AS issue_rate_id,
               context->>'issue_command_key' AS issue_key,
               issue_id
        FROM scoped
        WHERE type = 'rate' AND context ? 'issue_command_key'
        ORDER BY context->>'issue_command_key', id DESC
    ) rate_pair
        ON s.type = 'rate'
       AND s.dice_rate_key IS NOT NULL
       AND s.dice_rate_key = rate_pair.issue_key
       AND s.issue_id IS NOT DISTINCT FROM rate_pair.issue_id
)"#;

/// One row per logical action, ordered from newest to oldest by the leader's
/// `(epoch microseconds, id)` pair, carrying its member payloads in write
/// order. `$4` is the page size; `$5`/`$6` are the absent-or-present cursor.
fn activity_statement() -> &'static str {
    static SQL: OnceLock<String> = OnceLock::new();
    SQL.get_or_init(|| {
        format!(
            "WITH {FOLDED_AUTH_CTES},\n{SCOPED},\n{LINKED},\nclusters AS (\n    SELECT l.leader_id,\n           (extract(epoch FROM leader.ts) * 1000000)::bigint AS ts_us,\n           l.leader_id AS sort_id,\n           jsonb_agg(\n               jsonb_build_object(\n                   'event_id', l.id,\n                   'event_type', l.type,\n                   'timestamp', to_char(l.ts AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),\n                   'die_before', l.die,\n                   'die_after', l.die_after,\n                   'rating', l.rating,\n                   'thread_id', l.thread_id,\n                   'thread_title', l.thread_title,\n                   'issue_id', l.issue_id,\n                   'issue_number', l.issue_number\n               )\n               ORDER BY l.id\n           ) AS members\n    FROM linked l\n    JOIN linked leader ON leader.id = l.leader_id\n    GROUP BY l.leader_id, leader.ts\n)\nSELECT jsonb_build_object(\n    'auth', (SELECT jsonb_build_object(\n        'password_epoch', password_epoch,\n        'revoked', revoked\n    ) FROM auth),\n    'clusters', COALESCE((\n        SELECT jsonb_agg(jsonb_build_object('ts_us', p.ts_us, 'id', p.sort_id, 'events', p.members))\n        FROM (\n            SELECT ts_us, sort_id, members\n            FROM clusters\n            WHERE ($5::bigint IS NULL OR (ts_us, sort_id) < ($5::bigint, $6::int))\n            ORDER BY ts_us DESC, sort_id DESC\n            LIMIT $4\n        ) page\n    ), '[]'::jsonb)\n)::text",
            SCOPED = SCOPED_EVENTS_CTE
                .replace("{ACTIVITY_EVENT_TYPES}", ACTIVITY_EVENT_TYPES),
            LINKED = LINKED_EVENTS_CTE,
        )
    })
}

/// The one-row JSON payload the statement returns.
#[derive(Debug, Deserialize)]
struct ActivityPayload {
    auth: Option<FoldedAuthRow>,
    clusters: Vec<ActivityCluster>,
}

/// One logical action: its leader sort key and its member rows in write order.
#[derive(Debug, Deserialize)]
struct ActivityCluster {
    ts_us: i64,
    id: i32,
    events: Vec<ActivityEventRow>,
}

/// One raw audit row as projected by the statement.
#[derive(Debug, Deserialize)]
struct ActivityEventRow {
    event_id: i32,
    event_type: String,
    timestamp: String,
    die_before: Option<i32>,
    die_after: Option<i32>,
    rating: Option<f64>,
    thread_id: Option<i32>,
    thread_title: Option<String>,
    issue_id: Option<i32>,
    issue_number: Option<String>,
}

/// Parse the `page_token` cursor: `(leader epoch microseconds, leader id)`.
///
/// An empty or absent token means "first page"; anything else must be a
/// server-issued cursor, and a malformed one is a client error rather than a
/// silently-empty history.
fn parse_cursor(token: Option<&str>) -> Result<Option<(i64, i32)>, ApiError> {
    let Some(token) = token.map(str::trim).filter(|token| !token.is_empty()) else {
        return Ok(None);
    };
    let Some((ts_part, id_part)) = token.split_once(':') else {
        return Err(ApiError::BadRequest(
            "Invalid activity page token".to_string(),
        ));
    };
    let ts_us = ts_part
        .parse::<i64>()
        .map_err(|_| ApiError::BadRequest("Invalid activity page token".to_string()))?;
    let id = id_part
        .parse::<i32>()
        .map_err(|_| ApiError::BadRequest("Invalid activity page token".to_string()))?;
    Ok(Some((ts_us, id)))
}

/// `GET /api/v2/activity` — the chronological owner-scoped History resource.
///
/// One statement resolves authentication, ownership and the page.
pub async fn get_activity(
    Query(params): Query<ActivityQuery>,
    claims: VerifiedAccessClaims,
    State(state): State<Arc<AppState>>,
) -> Result<Json<ActivityResponse>, ApiError> {
    let page_size = params
        .page_size
        .unwrap_or(DEFAULT_PAGE_SIZE)
        .clamp(1, MAX_PAGE_SIZE);
    let cursor = parse_cursor(params.page_token.as_deref())?;
    let (cursor_ts, cursor_id): (Option<i64>, Option<i32>) = match cursor {
        Some((ts_us, id)) => (Some(ts_us), Some(id)),
        None => (None, None),
    };

    let username = claims.username().to_string();
    let jti = claims.jti().to_string();
    let expected_epoch = claims.expected_epoch()?;
    let bindings: [&(dyn tokio_postgres::types::ToSql + Sync); 6] = [
        &username,
        &jti,
        &expected_epoch,
        &page_size,
        &cursor_ts,
        &cursor_id,
    ];

    let connection = db::checkout(&state).await?;
    let row = db::query_one_optional(&state, connection, activity_statement(), &bindings)
        .await?
        .ok_or_else(|| ApiError::Internal("Invalid native activity projection".to_string()))?;
    let encoded: String = row.try_get(0).map_err(db::query_error)?;
    let payload: ActivityPayload = serde_json::from_str(&encoded).map_err(|error| {
        tracing::error!(%error, "Invalid native activity projection");
        ApiError::Internal("Invalid native activity projection".to_string())
    })?;
    validate_folded_auth(&claims, payload.auth.as_ref())?;

    let mut events = Vec::new();
    for cluster in &payload.clusters {
        events.extend(coalesce_cluster(cluster));
    }

    let next_page_token = if payload.clusters.len() == page_size as usize {
        payload
            .clusters
            .last()
            .map(|cluster| format!("{}:{}", cluster.ts_us, cluster.id))
    } else {
        None
    };

    Ok(Json(ActivityResponse {
        events,
        next_page_token,
    }))
}

/// Collapse the dice/issue rate pair of one Roll completion into one display
/// row, keeping the snooze/roll pair as its two causal rows.
///
/// A cluster holds two members only when the statement paired them by their
/// durable command keys, so an unpaired rate (a direct rating or a legacy row)
/// keeps its own row and later rating corrections never merge.
fn coalesce_cluster(cluster: &ActivityCluster) -> Vec<ActivityEvent> {
    let rate_pair = cluster.events.len() == 2
        && cluster
            .events
            .iter()
            .all(|event| event.event_type == "rate");
    let displayed: Vec<&ActivityEventRow> = if rate_pair {
        // The issue receipt is the pair leader; the dice receipt supplies the
        // die the rating stepped from. Both audit rows stay persisted; only
        // the display collapses.
        let leader = cluster
            .events
            .iter()
            .find(|event| event.event_id == cluster.id)
            .unwrap_or(&cluster.events[1]);
        let dice = cluster
            .events
            .iter()
            .find(|event| event.event_id != leader.event_id)
            .unwrap_or(&cluster.events[0]);
        vec![leader, dice]
    } else {
        cluster.events.iter().collect()
    };

    let mut events = Vec::with_capacity(displayed.len());
    for (position, row) in displayed.iter().enumerate() {
        let mut event = ActivityEvent {
            event_id: row.event_id,
            event_type: row.event_type.clone(),
            timestamp: row.timestamp.clone(),
            die_before: row.die_before,
            die_after: row.die_after,
            rating: row.rating,
            thread_id: row.thread_id,
            thread_title: row.thread_title.clone(),
            issue_id: row.issue_id,
            issue_number: row.issue_number.clone(),
            action_display: String::new(),
        };
        if rate_pair && position == 0 {
            // One rating display: the die before comes from the dice receipt.
            let dice = displayed[1];
            event.die_before = dice.die_before.or(event.die_before);
            event.die_after = event.die_after.or(dice.die_after);
            event.rating = event.rating.or(dice.rating);
        }
        event.action_display = action_display(&event);
        events.push(event);
    }
    // Write order: the snooze precedes the roll it enabled.
    if displayed.len() == 2 && displayed.iter().all(|row| row.event_type == "snooze" || row.event_type == "roll") {
        events.reverse();
    }
    events
}

/// Build the reader-visible label for one activity row.
///
/// A row whose thread or issue identity is gone keeps a safe historical label;
/// no identifier is ever fabricated.
fn action_display(event: &ActivityEvent) -> String {
    let subject = match (&event.thread_title, &event.issue_number) {
        (Some(title), Some(number)) => format!("{title} #{number}"),
        (Some(title), None) => title.clone(),
        (None, Some(number)) => format!("issue #{number}"),
        (None, None) => "a series that is no longer available".to_string(),
    };
    let die_span = |before: Option<i32>, after: Option<i32>| match (before, after) {
        (Some(before), Some(after)) => format!(" (d{before} → d{after})"),
        (Some(before), None) => format!(" (d{before})"),
        (None, Some(after)) => format!(" (→ d{after})"),
        (None, None) => String::new(),
    };
    match event.event_type.as_str() {
        "roll" => format!("Rolled {subject}"),
        "snooze" => format!("Snoozed {subject}{}", die_span(event.die_before, event.die_after)),
        "rate" => match event.rating {
            Some(rating) => format!("Rated {subject} ⭐{rating}"),
            None => format!("Rated {subject}"),
        },
        "manual_die" => {
            format!("Manual die selection{}", die_span(event.die_before, event.die_after))
        }
        "reset_dice" => "Reset dice".to_string(),
        other => format!("{} {subject}", other.to_uppercase()),
    }
}

/// Documentation-only operation for the mounted v2 activity history.
#[utoipa::path(
    get,
    path = "/api/v2/activity",
    tag = "activity",
    description = "The chronological owner-scoped activity history: every action that changed or recorded the die, with linked snooze/roll pairs kept causal and the dice/issue rate pair of one Roll completion shown once. Cursor pagination encodes the leader timestamp and id.",
    params(
        ("page_size" = Option<i32>, Query, description = "Number of logical actions per page (1-200, default 50)"),
        ("page_token" = Option<String>, Query, description = "Server-issued cursor: leader epoch microseconds and id, e.g. 1731000000000000:1050513")
    ),
    responses(
        (status = 200, description = "One page of chronological owner activity", body = ActivityResponse),
        (status = 400, description = "Malformed page token"),
        (status = 401, description = "Not authenticated"),
        (status = 500, description = "Invalid native activity projection"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn get_activity_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{config::Config, router, test_support};
    use axum::{
        body::Body,
        http::{Request, StatusCode},
    };
    use jsonwebtoken::{encode, EncodingKey, Header};
    use serde_json::{json, Value};
    use tower::ServiceExt;

    fn test_app(state: Arc<AppState>) -> axum::Router {
        router(state)
    }

    fn bearer(username: &str) -> String {
        let claims = json!({"sub": username, "jti": "activity-test-jti", "type": "access"});
        let token = encode(
            &Header::new(jsonwebtoken::Algorithm::HS256),
            &claims,
            &EncodingKey::from_secret(test_support::TEST_JWT_SECRET.as_bytes()),
        )
        .expect("mint test token");
        format!("Bearer {token}")
    }

    async fn get_activity_page(
        app: axum::Router,
        query: &str,
    ) -> (StatusCode, Value) {
        let path = if query.is_empty() {
            "/api/v2/activity".to_string()
        } else {
            format!("/api/v2/activity?{query}")
        };
        let response = app
            .oneshot(
                Request::builder()
                    .method("GET")
                    .uri(&path)
                    .header("authorization", bearer("reader-1"))
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        let status = response.status();
        let body = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .unwrap();
        let value: Value = serde_json::from_slice(&body).unwrap_or(Value::Null);
        (status, value)
    }

    /// Reset, seed the production evidence sequence for #4822 and return the
    /// test app plus the held database guard.
    ///
    /// The seed reproduces the 2026-11-08 Central-time production rows: each
    /// roll-offer transaction writes its snooze with `clock_timestamp()` (later)
    /// and its roll with `NOW()` (earlier), so the timestamp order inverts the
    /// causal write order, and one Roll completion writes two rate rows.
    async fn seeded_app() -> (axum::Router, tokio::sync::MutexGuard<'static, ()>) {
        let state = test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let guard = test_support::reset_for_test(&state).await;
        let connection = crate::db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                r#"
                INSERT INTO users (id, username) VALUES (1, 'reader-1'), (2, 'reader-2');
                INSERT INTO threads
                    (id, user_id, title, format, issues_remaining, status,
                     queue_position, total_issues, reading_progress)
                VALUES (3153, 1, 'First Series', 'Comic', 5, 'active', 1, 10, '10%'),
                       (3469, 1, 'Second Series', 'Comic', 4, 'active', 2, 10, '20%'),
                       (8417, 1, 'Third Series', 'Comic', 3, 'active', 3, 10, '30%');
                INSERT INTO issues
                    (id, thread_id, issue_number, status, created_at, position)
                VALUES (1121330, 3153, '1', 'unread', now(), 1),
                       (25301, 3469, '2', 'unread', now(), 1),
                       (52329, 8417, '2', 'unread', now(), 1);
                -- 09:42:35.028 roll d6 (issue 1121330, thread 3153)
                INSERT INTO events
                    (user_id, type, "timestamp", die, selected_thread_id, issue_id,
                     issue_number, context)
                VALUES (1, 'roll', '2026-11-08 15:42:35.028+00', 6, 3153, 1121330, '1',
                        '{"roll_offer_key":"roll-offer-first"}'::json);
                -- 09:46:25.467 roll d8 — written AFTER the snooze below but
                -- stamped with NOW() (transaction start), so its recorded
                -- timestamp precedes the causal snooze.
                INSERT INTO events
                    (user_id, type, "timestamp", die, selected_thread_id, issue_id,
                     issue_number, context)
                VALUES (1, 'roll', '2026-11-08 15:46:25.467+00', 8, 3469, 25301, '2',
                        '{"roll_offer_key":"roll-offer-second","snoozed_thread_id":3153}'::json);
                -- 09:46:25.515 snooze d6 → d8 — clock_timestamp() mid-transaction.
                INSERT INTO events
                    (user_id, type, "timestamp", die, die_after, thread_id, context)
                VALUES (1, 'snooze', '2026-11-08 15:46:25.515+00', 6, 8, 3153,
                        '{"dice_command_key":"roll-offer-second-snooze","dice_command":{"kind":"reroll","thread_id":3153}}'::json);
                -- 09:46:34.066 roll d10 (issue 52329, thread 8417)
                INSERT INTO events
                    (user_id, type, "timestamp", die, selected_thread_id, issue_id,
                     issue_number, context)
                VALUES (1, 'roll', '2026-11-08 15:46:34.066+00', 10, 8417, 52329, '2',
                        '{"roll_offer_key":"roll-offer-third","snoozed_thread_id":3469}'::json);
                -- 09:46:34.105 snooze d8 → d10
                INSERT INTO events
                    (user_id, type, "timestamp", die, die_after, thread_id, context)
                VALUES (1, 'snooze', '2026-11-08 15:46:34.105+00', 8, 10, 3469,
                        '{"dice_command_key":"roll-offer-third-snooze","dice_command":{"kind":"reroll","thread_id":3469}}'::json);
                -- 10:01:54.440 dice-command rate receipt (die 10 → 8)
                INSERT INTO events
                    (user_id, type, "timestamp", die, die_after, thread_id, issue_id,
                     rating, context)
                VALUES (1, 'rate', '2026-11-08 16:01:54.440+00', 10, 8, 8417, 52329, 4.5,
                        '{"dice_command_key":"roll-rating-8417-rate-issue-25301","dice_command":{"kind":"roll_rating","thread_id":8417,"issue_id":52329,"rating":4.5}}'::json);
                -- 10:01:54.388 issue-command rate receipt — NOW() transaction
                -- start, earlier than the dice receipt above.
                INSERT INTO events
                    (user_id, type, "timestamp", thread_id, issue_id, issue_number,
                     rating, die_after, context)
                VALUES (1, 'rate', '2026-11-08 16:01:54.388+00', 8417, 52329, '2', 4.5, 8,
                        '{"issue_command_key":"rate-issue-25301","source":"roll_offer"}'::json);
                -- Another owner's event must never leak.
                INSERT INTO events
                    (user_id, type, "timestamp", die, selected_thread_id, context)
                VALUES (2, 'roll', '2026-11-08 15:50:00+00', 6, 3153,
                        '{"roll_offer_key":"other-user-key"}'::json);
                "#,
            )
            .await
            .expect("seed activity evidence sequence");
        drop(connection);
        (test_app(state), guard)
    }

    fn event_ids(value: &Value) -> Vec<i32> {
        value["events"]
            .as_array()
            .map(|events| {
                events
                    .iter()
                    .map(|event| event["event_id"].as_i64().unwrap_or(0) as i32)
                    .collect()
            })
            .unwrap_or_default()
    }

    #[tokio::test]
    async fn history_shows_the_reported_die_sequence_in_causal_order() {
        let (app, _guard) = seeded_app().await;
        let (status, body) = get_activity_page(app, "").await;
        assert_eq!(status, StatusCode::OK);

        // Causal narrative: roll d6, snooze d6→d8, roll d8, snooze d8→d10,
        // roll d10, then ONE rating row for the paired receipts. The snooze
        // rows carry later recorded timestamps than the rolls they enabled;
        // write order, not timestamp order, must win inside the pairs.
        assert_eq!(
            event_ids(&body),
            vec![1, 3, 2, 5, 4, 7],
            "snooze precedes its enabled roll despite the timestamp inversion"
        );
        let displays: Vec<&str> = body["events"]
            .as_array()
            .unwrap()
            .iter()
            .map(|event| event["action_display"].as_str().unwrap())
            .collect();
        assert_eq!(
            displays,
            vec![
                "Rolled First Series #1",
                "Snoozed First Series (d6 → d8)",
                "Rolled Second Series #2",
                "Snoozed Second Series (d8 → d10)",
                "Rolled Third Series #2",
                "Rated Third Series #2 ⭐4.5",
            ]
        );
        // The paired rate rows collapse into one display.
        let ratings: Vec<Value> = body["events"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|event| event["event_type"] == "rate")
            .cloned()
            .collect();
        assert_eq!(ratings.len(), 1, "the dice/issue rate pair displays once");
        assert_eq!(ratings[0]["die_before"], 10);
        assert_eq!(ratings[0]["die_after"], 8);
        // Roll events resolve their offered thread from selected_thread_id.
        let roll_8 = &body["events"][2];
        assert_eq!(roll_8["thread_id"], 3469);
        assert_eq!(roll_8["thread_title"], "Second Series");
        // Cross-user isolation.
        assert!(
            !event_ids(&body).contains(&8),
            "another owner's events never leak"
        );
    }

    #[tokio::test]
    async fn activity_cursor_pages_continue_without_skipping_records() {
        let (app, _guard) = seeded_app().await;
        // One cluster per page: each page must return a whole logical action.
        let (first_status, first) = get_activity_page(app.clone(), "page_size=1").await;
        assert_eq!(first_status, StatusCode::OK);
        assert_eq!(event_ids(&first).len(), 2, "first page holds the snooze/roll pair");
        let token = first["next_page_token"].as_str().expect("cursor token");

        let (second_status, second) =
            get_activity_page(app.clone(), &format!("page_size=1&page_token={token}")).await;
        assert_eq!(second_status, StatusCode::OK);
        let second_ids = event_ids(&second);
        assert!(!second_ids.is_empty());
        for id in &second_ids {
            assert!(
                !event_ids(&first).contains(id),
                "a page boundary must never repeat a record"
            );
        }
        // An empty token behaves like no token.
        let (empty_status, empty) = get_activity_page(app.clone(), "page_token=").await;
        assert_eq!(empty_status, StatusCode::OK);
        assert_eq!(event_ids(&empty), event_ids(&first).len().checked_sub(0).map(|_| event_ids(&first)).unwrap_or_default());
        // A malformed token is a client error, not a silently empty page.
        let (bad_status, _) = get_activity_page(app, "page_token=not-a-cursor").await;
        assert_eq!(bad_status, StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn legacy_unlinked_events_fall_back_to_deterministic_order() {
        let state = test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let guard = test_support::reset_for_test(&state).await;
        let connection = crate::db::checkout(&state).await.expect("fixture connection");
        connection
            .batch_execute(
                r#"
                INSERT INTO users (id, username) VALUES (1, 'reader-1');
                INSERT INTO events (user_id, type, "timestamp", die, thread_id)
                VALUES (1, 'snooze', '2026-11-08 15:00:00+00', 6, NULL);
                INSERT INTO events (user_id, type, "timestamp", die)
                VALUES (1, 'manual_die', '2026-11-08 16:00:00+00', 8);
                "#,
            )
            .await
            .expect("seed legacy events");
        drop(connection);
        let app = test_app(state);
        let (status, body) = get_activity_page(app, "").await;
        assert_eq!(status, StatusCode::OK);
        let events = body["events"].as_array().unwrap();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0]["event_type"], "manual_die");
        assert_eq!(events[1]["event_type"], "snooze");
        drop(guard);
    }

    #[test]
    fn cursor_parsing_treats_empty_as_absent_and_rejects_malformed() {
        assert_eq!(parse_cursor(None).unwrap(), None);
        assert_eq!(parse_cursor(Some("")).unwrap(), None);
        assert_eq!(parse_cursor(Some("  ")).unwrap(), None);
        assert_eq!(parse_cursor(Some("1731000000000000:42")).unwrap(), Some((1_731_000_000_000_000, 42)));
        assert!(parse_cursor(Some("junk")).is_err());
        assert!(parse_cursor(Some("12:bad")).is_err());
        assert!(parse_cursor(Some("bad:12")).is_err());
    }

    #[test]
    fn statement_stays_owner_scoped_and_bounded() {
        let statement = activity_statement();
        assert!(statement.contains("WHERE e.user_id = (SELECT user_id FROM me)"));
        assert!(statement.contains("LIMIT $4"));
        assert!(statement.contains("(ts_us, sort_id) < ($5::bigint, $6::int)"));
        assert!(!statement.contains("LIMIT $#" ), "placeholder must be valid SQL");
        // The rate pair and snooze/roll pair both key on durable linkage.
        assert!(statement.contains("roll_offer_key"));
        assert!(statement.contains("issue_command_key"));
        assert!(statement.contains("dice_command_key"));
    }
}
