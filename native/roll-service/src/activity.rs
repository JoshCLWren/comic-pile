//! Owner-scoped activity history resource.
//!
//! `GET /api/v2/activity` is the native replacement for the legacy session-based
//! History read path. It returns one chronological, owner-scoped activity stream
//! with stable cursor pagination. Events remain durable and are never rewritten;
//! reader-visible logical actions are derived at read time from durable command
//! linkage only — never from timestamp proximity.
//!
//! ## Logical actions and ordering
//!
//! Pagination walks *primary* events in `(timestamp, id)` order. Every owned
//! event is a primary except the two durable command companions below, which
//! are emitted with (or folded into) the primary they belong to:
//!
//! * **Roll offer after a snooze.** `POST /api/v2/roll/offer` writes the snooze
//!   (`context.dice_command_key = "<roll_offer_key>-snooze"`, `clock_timestamp()`)
//!   and the new offer (`context.roll_offer_key`, transaction `NOW()`) in one
//!   transaction, so the roll's timestamp can precede the snooze that caused it.
//!   The snooze is the primary; its roll is emitted directly after it.
//! * **Rating from a Roll offer.** The issue command row
//!   (`context.issue_command_key = K`) and its dice step
//!   (`context.dice_command_key = "roll-rating-<thread_id>-K"`) are one user
//!   action. The issue row is the primary and carries the dice step's die
//!   change; both raw rows stay in the database untouched.
//!
//! Records without these keys (legacy and pre-cutover rows) have no durable
//! linkage, so the deterministic fallback is the raw `(timestamp, id)` order with
//! every row shown on its own: nothing is merged or reordered by guesswork.
//!
//! The cursor is `(primary timestamp, primary id, sub-position)`, so a page can
//! end between a snooze and its roll without omitting or repeating either.
//!
//! ## Ownership
//!
//! Ownership is `events.user_id`. Migration `c44050000001` attributed every
//! historical session-linked row from `sessions.user_id`, and the
//! `trg_assign_event_owner` trigger attributes every new row (including legacy
//! session writers that pass only `session_id`). Rows left with a NULL owner are
//! the ones that migration deliberately quarantined because their references
//! disagree; owner-scoped history must never return them.

use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Query, State},
    Json,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::json;
use std::sync::Arc;

#[derive(Debug, Deserialize)]
pub struct ActivityQuery {
    limit: Option<i64>,
    page_token: Option<String>,
    cursor: Option<String>,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, utoipa::ToSchema)]
struct ActivityItem {
    event_id: i32,
    #[serde(rename = "type")]
    event_type: String,
    timestamp: String,
    die_before: Option<i32>,
    die_after: Option<i32>,
    rating: Option<f64>,
    issue_id: Option<i32>,
    thread_id: Option<i32>,
    thread_title: Option<String>,
    issue_number: Option<String>,
}

#[derive(Debug, serde::Serialize, utoipa::ToSchema)]
pub struct ActivityResponse {
    activities: Vec<ActivityItem>,
    events: Vec<ActivityItem>,
    items: Vec<ActivityItem>,
    next_page_token: Option<String>,
    next_cursor: Option<String>,
}

const DEFAULT_LIMIT: i64 = 50;
const MAX_LIMIT: i64 = 100;
/// Sub-position of a primary event and of the roll emitted after its snooze.
const SUB_PRIMARY: i16 = 0;
const SUB_LINKED_ROLL: i16 = 1;

/// Position of one logical item in the activity stream.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
struct StreamKey {
    micros: i64,
    id: i32,
    sub: i16,
}

fn bad_cursor() -> ApiError {
    ApiError::BadRequest("Invalid activity page token".to_string())
}

/// Decode a client-supplied page token, rejecting anything this endpoint did
/// not issue before it reaches SQL.
fn parse_cursor(token: &str) -> Result<StreamKey, ApiError> {
    let bytes = URL_SAFE_NO_PAD.decode(token).map_err(|_| bad_cursor())?;
    let value: serde_json::Value = serde_json::from_slice(&bytes).map_err(|_| bad_cursor())?;
    let object = value.as_object().ok_or_else(bad_cursor)?;
    if object.len() != 3 {
        return Err(bad_cursor());
    }
    let micros = object
        .get("t")
        .and_then(serde_json::Value::as_i64)
        .ok_or_else(bad_cursor)?;
    let id = object
        .get("id")
        .and_then(serde_json::Value::as_i64)
        .and_then(|id| i32::try_from(id).ok())
        .filter(|id| *id > 0)
        .ok_or_else(bad_cursor)?;
    let sub = object
        .get("s")
        .and_then(serde_json::Value::as_i64)
        .and_then(|sub| i16::try_from(sub).ok())
        .filter(|sub| *sub == SUB_PRIMARY || *sub == SUB_LINKED_ROLL)
        .ok_or_else(bad_cursor)?;
    DateTime::<Utc>::from_timestamp_micros(micros).ok_or_else(bad_cursor)?;
    Ok(StreamKey { micros, id, sub })
}

fn encode_cursor(key: StreamKey) -> String {
    let payload = json!({"t": key.micros, "id": key.id, "s": key.sub});
    URL_SAFE_NO_PAD.encode(payload.to_string())
}

/// One page of primary events with their durable companions resolved.
///
/// The roll-companion predicate (`roll_offer_key || '-snooze'` equals the
/// snooze's `dice_command_key`, roll no later than snooze) and the
/// rating-companion predicate (`'roll-rating-' || dice.thread_id || '-' ||
/// issue_command_key` equals the dice row's `dice_command_key`, same issue) are
/// written identically on both sides: a companion is excluded from the primary
/// stream exactly when its primary will emit it.
const ACTIVITY_PAGE_SQL: &str = r#"
WITH primaries AS (
    SELECT e.id, e.type, e.timestamp, e.die, e.die_after, e.rating, e.issue_id,
           e.issue_number, COALESCE(e.thread_id, e.selected_thread_id) AS thread_id,
           e.context
      FROM events e
     WHERE e.user_id = $1
       AND ($2::timestamptz IS NULL OR (e.timestamp, e.id) >= ($2::timestamptz, $3::int))
       AND NOT (
             e.type = 'roll'
         AND e.context->>'roll_offer_key' IS NOT NULL
         AND EXISTS (
               SELECT 1 FROM events s
                WHERE s.user_id = $1
                  AND s.context->>'dice_command_key' = (e.context->>'roll_offer_key') || '-snooze'
                  AND s.type = 'snooze'
                  AND s.timestamp >= e.timestamp))
       AND NOT (
             e.type = 'rate'
         AND e.issue_id IS NOT NULL
         AND e.thread_id IS NOT NULL
         AND e.context->>'dice_command_key' LIKE 'roll-rating-%'
         AND EXISTS (
               SELECT 1 FROM events i
                WHERE i.type IN ('rate', 'issue_command', 'issue_unread')
                  AND i.issue_id = e.issue_id
                  AND i.user_id = $1
                  AND i.context->>'issue_command_key' IS NOT NULL
                  AND 'roll-rating-' || e.thread_id || '-' || (i.context->>'issue_command_key')
                      = e.context->>'dice_command_key'))
     ORDER BY e.timestamp ASC, e.id ASC
     LIMIT $4
)
SELECT p.id, p.type,
       to_char(p.timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
       (extract(epoch FROM p.timestamp) * 1000000)::bigint,
       p.die, p.die_after, p.rating, p.issue_id, p.issue_number, p.thread_id, pt.title,
       d.die, d.die_after,
       r.id, r.type,
       to_char(r.timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
       r.die, r.die_after, r.rating, r.issue_id, r.issue_number, r.thread_id, rt.title
  FROM primaries p
  LEFT JOIN threads pt ON pt.id = p.thread_id
  LEFT JOIN LATERAL (
        SELECT d.die, d.die_after
          FROM events d
         WHERE p.type IN ('rate', 'issue_command', 'issue_unread')
           AND p.issue_id IS NOT NULL
           AND p.context->>'issue_command_key' IS NOT NULL
           AND d.type = 'rate'
           AND d.issue_id = p.issue_id
           AND d.user_id = $1
           AND d.thread_id IS NOT NULL
           AND d.context->>'dice_command_key' LIKE 'roll-rating-%'
           AND 'roll-rating-' || d.thread_id || '-' || (p.context->>'issue_command_key')
               = d.context->>'dice_command_key'
         ORDER BY d.id
         LIMIT 1) d ON TRUE
  LEFT JOIN LATERAL (
        SELECT r.id, r.type, r.timestamp, r.die, r.die_after, r.rating, r.issue_id,
               r.issue_number, COALESCE(r.thread_id, r.selected_thread_id) AS thread_id
          FROM events r
         WHERE p.type = 'snooze'
           AND p.context->>'dice_command_key' LIKE '%-snooze'
           AND r.user_id = $1
           AND r.timestamp <= p.timestamp
           AND r.type = 'roll'
           AND r.context->>'roll_offer_key' IS NOT NULL
           AND (r.context->>'roll_offer_key') || '-snooze' = p.context->>'dice_command_key'
         ORDER BY r.timestamp DESC, r.id DESC
         LIMIT 1) r ON TRUE
  LEFT JOIN threads rt ON rt.id = r.thread_id
 ORDER BY p.timestamp ASC, p.id ASC
"#;

/// Turn one primary row into its logical items, in stream order.
fn logical_items(row: &tokio_postgres::Row) -> Vec<(StreamKey, ActivityItem)> {
    let id: i32 = row.get(0);
    let micros: i64 = row.get(3);
    let linked_die: Option<i32> = row.get(11);
    let linked_die_after: Option<i32> = row.get(12);
    let rating_pair = linked_die.is_some() || linked_die_after.is_some();
    let primary_type: String = row.get(1);
    let primary_die: Option<i32> = row.get(4);
    let primary_die_after: Option<i32> = row.get(5);
    let primary = ActivityItem {
        event_id: id,
        // The issue receipt of a rating pair can be an idempotent no-op
        // `issue_command`; the dice step proves the user rated.
        event_type: if rating_pair {
            "rate".to_string()
        } else {
            primary_type
        },
        timestamp: row.get(2),
        die_before: if rating_pair { linked_die } else { primary_die },
        die_after: if rating_pair {
            linked_die_after.or(primary_die_after)
        } else {
            primary_die_after
        },
        rating: row.get(6),
        issue_id: row.get(7),
        issue_number: row.get(8),
        thread_id: row.get(9),
        thread_title: row.get(10),
    };
    let mut items = vec![(
        StreamKey {
            micros,
            id,
            sub: SUB_PRIMARY,
        },
        primary,
    )];
    if let Some(roll_id) = row.get::<_, Option<i32>>(13) {
        items.push((
            StreamKey {
                micros,
                id,
                sub: SUB_LINKED_ROLL,
            },
            ActivityItem {
                event_id: roll_id,
                event_type: row.get(14),
                timestamp: row.get(15),
                die_before: row.get(16),
                die_after: row.get(17),
                rating: row.get(18),
                issue_id: row.get(19),
                issue_number: row.get(20),
                thread_id: row.get(21),
                thread_title: row.get(22),
            },
        ));
    }
    items
}

/// Select one page from logical items already in stream order.
///
/// Returns the page and the continuation token, which is the stream key of the
/// last returned item whenever more items exist.
fn paginate(
    items: Vec<(StreamKey, ActivityItem)>,
    after: Option<StreamKey>,
    limit: usize,
) -> (Vec<ActivityItem>, Option<String>) {
    let mut remaining = items
        .into_iter()
        .filter(|(key, _)| after.is_none_or(|after| *key > after));
    let page: Vec<(StreamKey, ActivityItem)> = remaining.by_ref().take(limit).collect();
    let has_more = remaining.next().is_some();
    let token = if has_more {
        page.last().map(|(key, _)| encode_cursor(*key))
    } else {
        None
    };
    (page.into_iter().map(|(_, item)| item).collect(), token)
}

/// `GET /api/v2/activity` — bounded, owner-scoped activity stream.
pub async fn list_activity(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(query): Query<ActivityQuery>,
) -> Result<Json<ActivityResponse>, ApiError> {
    let limit = query.limit.unwrap_or(DEFAULT_LIMIT).clamp(1, MAX_LIMIT);
    let after = query
        .page_token
        .or(query.cursor)
        .as_deref()
        .map(parse_cursor)
        .transpose()?;
    // Each primary yields at least one item and the cursor's own primary yields
    // at most two already-returned items, so `limit + 2` primaries always prove
    // whether another item follows the page.
    let primary_limit = limit + 2;
    let after_timestamp: Option<DateTime<Utc>> = after
        .map(|key| DateTime::<Utc>::from_timestamp_micros(key.micros).ok_or_else(bad_cursor))
        .transpose()?;
    let after_id: Option<i32> = after.map(|key| key.id);

    let connection = db::checkout(&state).await?;
    let rows = connection
        .query(
            ACTIVITY_PAGE_SQL,
            &[&user.id(), &after_timestamp, &after_id, &primary_limit],
        )
        .await
        .map_err(db::query_error)?;

    let items: Vec<(StreamKey, ActivityItem)> = rows.iter().flat_map(logical_items).collect();
    let (items, next_page_token) = paginate(items, after, limit as usize);
    let next_cursor = next_page_token.clone();

    Ok(Json(ActivityResponse {
        activities: items.clone(),
        events: items.clone(),
        items,
        next_page_token,
        next_cursor,
    }))
}

// OpenAPI declaration
#[utoipa::path(
    get,
    path = "/api/v2/activity",
    tag = "activity",
    params(
        ("limit" = Option<i64>, Query, description = "Maximum number of activity rows"),
        ("page_token" = Option<String>, Query, description = "Opaque continuation cursor")
    ),
    responses(
        (status = 200, description = "Owner-scoped activity history", body = ActivityResponse),
        (status = 400, description = "Malformed or unrecognized page token"),
        (status = 401, description = "Not authenticated")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn list_activity_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;

    fn token(value: serde_json::Value) -> String {
        URL_SAFE_NO_PAD.encode(value.to_string())
    }

    #[test]
    fn cursor_round_trips() {
        let key = StreamKey {
            micros: 1_794_150_114_440_000,
            id: 42,
            sub: SUB_LINKED_ROLL,
        };
        assert_eq!(parse_cursor(&encode_cursor(key)).unwrap(), key);
    }

    #[test]
    fn malformed_cursors_are_rejected_before_sql() {
        let rejected = [
            "%%%not-base64".to_string(),
            URL_SAFE_NO_PAD.encode("not json"),
            token(json!([1, 2, 3])),
            token(json!({"id": 1, "s": 0})),
            token(json!({"t": 1, "s": 0})),
            token(json!({"t": 1, "id": 1})),
            token(json!({"t": "2026-11-08T10:01:54Z", "id": 1, "s": 0})),
            token(json!({"t": i64::MAX, "id": 1, "s": 0})),
            token(json!({"t": 1, "id": i64::from(i32::MAX) + 1, "s": 0})),
            token(json!({"t": 1, "id": 0, "s": 0})),
            token(json!({"t": 1, "id": 1, "s": 2})),
            token(json!({"t": 1, "id": 1, "s": 0, "extra": true})),
            token(json!({"ts": "2026-11-08T10:01:54Z", "id": 1})),
        ];
        for value in rejected {
            assert!(
                matches!(parse_cursor(&value), Err(ApiError::BadRequest(_))),
                "{value} must be rejected"
            );
        }
    }

    fn item(event_id: i32) -> ActivityItem {
        ActivityItem {
            event_id,
            event_type: "roll".into(),
            timestamp: String::new(),
            die_before: None,
            die_after: None,
            rating: None,
            issue_id: None,
            thread_id: None,
            thread_title: None,
            issue_number: None,
        }
    }

    #[test]
    fn paginate_resumes_between_a_snooze_and_its_roll() {
        let snooze = StreamKey {
            micros: 10,
            id: 2,
            sub: SUB_PRIMARY,
        };
        let roll = StreamKey {
            sub: SUB_LINKED_ROLL,
            ..snooze
        };
        let items = vec![(snooze, item(2)), (roll, item(1))];
        let (first, token) = paginate(items.clone(), None, 1);
        assert_eq!(first, vec![item(2)]);
        let after = parse_cursor(&token.expect("more")).unwrap();
        let (second, token) = paginate(items, Some(after), 1);
        assert_eq!(second, vec![item(1)]);
        assert!(token.is_none());
    }

    #[test]
    fn activity_openapi_declares_json_response_and_cursor_rejection() {
        let schema = serde_json::to_value(crate::openapi::canonical_openapi()).unwrap();
        let responses = &schema["paths"]["/api/v2/activity"]["get"]["responses"];
        assert!(responses["200"]["content"]["application/json"]["schema"].is_object());
        assert!(responses["400"].is_object());
    }

    #[tokio::test]
    async fn activity_routes_require_authentication_before_database_access() {
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
        for path in ["/api/v2/activity"] {
            let response = app
                .clone()
                .oneshot(Request::builder().uri(path).body(Body::empty()).unwrap())
                .await
                .unwrap();
            assert_eq!(response.status(), StatusCode::UNAUTHORIZED, "{path}");
        }
    }

    // ---- Disposable PostgreSQL: the exact production router handler ----

    /// The November 8, 2026 production sequence for user 1 (America/Chicago
    /// 09:42–10:01, stored as UTC), including the timestamp-inverted
    /// snooze/roll pairs and the two-row rating. Legacy Roll offers are written
    /// with only `session_id`, so the ownership trigger attributes them.
    /// User 2 owns interleaved activity that must never appear for user 1.
    const PRODUCTION_SEQUENCE: &str = r#"
        INSERT INTO users (id, username) VALUES (1, 'reader-1'), (2, 'reader-2');
        INSERT INTO threads
            (id, user_id, title, format, issues_remaining, status,
             queue_position, total_issues, reading_progress)
        VALUES (3153, 1, 'Saga', 'Comic', 3, 'active', 1, 12, '25%'),
               (3469, 1, 'Paper Girls', 'Comic', 3, 'active', 2, 12, '25%'),
               (8417, 1, 'Astro City: Astra', 'Comic', 1, 'active', 3, 2, '50%'),
               (9001, 2, 'Other Reader Series', 'Comic', 3, 'active', 1, 4, '0%');
        INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
        VALUES (1121330, 3153, '4', 'unread', now(), 1),
               (25301, 3469, '7', 'unread', now(), 1),
               (52329, 8417, '2', 'read', now(), 1),
               (90001, 9001, '1', 'unread', now(), 1);
        INSERT INTO sessions (id, user_id, start_die) VALUES (1018133, 1, 6);
        INSERT INTO sessions (id, user_id, start_die) VALUES (2000001, 2, 6);
        INSERT INTO events (id, type, timestamp, session_id, selected_thread_id, die,
                            result, issue_id, issue_number, context)
        VALUES (1050511, 'roll', '2026-11-08 15:42:35.028+00', 1018133, 3153, 6, 2,
                1121330, '4', '{"roll_offer_key":"roll-offer-a1","snoozed_thread_id":null}'),
               (1050513, 'roll', '2026-11-08 15:46:25.467+00', 1018133, 3469, 8, 5,
                25301, '7', '{"roll_offer_key":"roll-offer-b2","snoozed_thread_id":3153}'),
               (1050515, 'roll', '2026-11-08 15:46:34.066+00', 1018133, 8417, 10, 7,
                52329, '2', '{"roll_offer_key":"roll-offer-c3","snoozed_thread_id":3469}');
        INSERT INTO events (id, type, timestamp, user_id, die, die_after, thread_id, context)
        VALUES (1050512, 'snooze', '2026-11-08 15:46:25.515+00', 1, 6, 8, 3153,
                '{"dice_command_key":"roll-offer-b2-snooze"}'),
               (1050514, 'snooze', '2026-11-08 15:46:34.105+00', 1, 8, 10, 3469,
                '{"dice_command_key":"roll-offer-c3-snooze"}');
        INSERT INTO events (id, type, timestamp, user_id, thread_id, issue_id, issue_number,
                            rating, issues_read, die_after, context)
        VALUES (1050517, 'rate', '2026-11-08 16:01:54.388+00', 1, 8417, 52329, '2', 4.5, 1, 8,
                '{"issue_command_key":"rate-key-1","source":"roll"}');
        INSERT INTO events (id, type, timestamp, user_id, die, die_after, thread_id, issue_id,
                            rating, context)
        VALUES (1050516, 'rate', '2026-11-08 16:01:54.440+00', 1, 10, 8, 8417, 52329, 4.5,
                '{"dice_command_key":"roll-rating-8417-rate-key-1"}');
        INSERT INTO events (id, type, timestamp, session_id, selected_thread_id, die,
                            result, issue_id, issue_number, context)
        VALUES (1050518, 'roll', '2026-11-08 15:46:30.000+00', 2000001, 9001, 6, 1,
                90001, '1', '{"roll_offer_key":"roll-offer-b2"}');
        INSERT INTO events (id, type, timestamp, user_id, die, die_after, thread_id, context)
        VALUES (1050519, 'snooze', '2026-11-08 15:46:30.100+00', 2, 6, 8, 9001,
                '{"dice_command_key":"roll-offer-b2-snooze"}');
    "#;

    type Summary<'a> = (i32, &'a str, Option<i32>, Option<i32>, Option<f64>);

    /// (event id, type, die_before, die_after, rating) the owner must see.
    const EXPECTED: [Summary<'static>; 6] = [
        (1050511, "roll", Some(6), None, None),
        (1050512, "snooze", Some(6), Some(8), None),
        (1050513, "roll", Some(8), None, None),
        (1050514, "snooze", Some(8), Some(10), None),
        (1050515, "roll", Some(10), None, None),
        (1050517, "rate", Some(10), Some(8), Some(4.5)),
    ];

    async fn seeded_state(
        statements: &str,
    ) -> (Arc<AppState>, tokio::sync::MutexGuard<'static, ()>) {
        let _admin = crate::test_support::required_test_admin_url();
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let guard = crate::test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("test connection");
        connection
            .batch_execute(statements)
            .await
            .expect("seed canonical schema");
        (state, guard)
    }

    async fn page(
        state: &Arc<AppState>,
        user_id: i32,
        limit: i64,
        page_token: Option<String>,
    ) -> Result<ActivityResponse, ApiError> {
        list_activity(
            State(state.clone()),
            AuthenticatedUser::for_test(user_id),
            Query(ActivityQuery {
                limit: Some(limit),
                page_token,
                cursor: None,
            }),
        )
        .await
        .map(|Json(response)| response)
    }

    async fn all_pages(state: &Arc<AppState>, user_id: i32, limit: i64) -> Vec<ActivityItem> {
        let mut items = Vec::new();
        let mut token = None;
        for _ in 0..50 {
            let response = page(state, user_id, limit, token).await.expect("page");
            assert!(response.items.len() <= limit as usize);
            assert_eq!(response.next_page_token, response.next_cursor);
            items.extend(response.items);
            token = response.next_page_token;
            if token.is_none() {
                return items;
            }
        }
        panic!("pagination did not terminate");
    }

    fn summary(items: &[ActivityItem]) -> Vec<Summary<'_>> {
        items
            .iter()
            .map(|item| {
                (
                    item.event_id,
                    item.event_type.as_str(),
                    item.die_before,
                    item.die_after,
                    item.rating,
                )
            })
            .collect()
    }

    #[tokio::test]
    async fn production_sequence_is_causal_complete_and_stable_across_page_sizes() {
        let (state, _db) = seeded_state(PRODUCTION_SEQUENCE).await;
        for limit in [1, 2, 3, 4, 50] {
            let items = all_pages(&state, 1, limit).await;
            assert_eq!(summary(&items), EXPECTED.to_vec(), "limit={limit}");
        }
        let items = all_pages(&state, 1, 50).await;
        let rating = items.last().unwrap();
        assert_eq!(rating.issue_id, Some(52329));
        assert_eq!(rating.issue_number.as_deref(), Some("2"));
        assert_eq!(rating.thread_title.as_deref(), Some("Astro City: Astra"));
        assert_eq!(rating.timestamp, "2026-11-08T16:01:54.388000Z");
        assert_eq!(items[1].thread_title.as_deref(), Some("Saga"));
        assert_eq!(items[2].thread_title.as_deref(), Some("Paper Girls"));
    }

    #[tokio::test]
    async fn other_readers_never_see_or_link_the_owners_activity() {
        let (state, _db) = seeded_state(PRODUCTION_SEQUENCE).await;
        // User 2 reused the same offer key text: linkage stays owner-scoped,
        // so user 2's roll follows user 2's snooze and nothing of user 1 leaks.
        let items = all_pages(&state, 2, 1).await;
        assert_eq!(
            summary(&items),
            vec![
                (1050519, "snooze", Some(6), Some(8), None),
                (1050518, "roll", Some(6), None, None),
            ]
        );
        assert!(all_pages(&state, 3, 10).await.is_empty());
    }

    #[tokio::test]
    async fn distinct_rating_commands_are_never_merged() {
        let (state, _db) = seeded_state(
            r#"
            INSERT INTO users (id, username) VALUES (1, 'reader-1');
            INSERT INTO threads
                (id, user_id, title, format, issues_remaining, status,
                 queue_position, total_issues, reading_progress)
            VALUES (10, 1, 'Saga', 'Comic', 3, 'active', 1, 12, '25%');
            INSERT INTO issues (id, thread_id, issue_number, status, created_at, position)
            VALUES (100, 10, '1', 'read', now(), 1);
            -- Command A: issue receipt + dice step (one action).
            INSERT INTO events (id, type, timestamp, user_id, thread_id, issue_id, rating,
                                die_after, context)
            VALUES (1, 'rate', '2026-11-08 16:00:00.000+00', 1, 10, 100, 4.5, 8,
                    '{"issue_command_key":"command-a"}');
            INSERT INTO events (id, type, timestamp, user_id, die, die_after, thread_id,
                                issue_id, rating, context)
            VALUES (2, 'rate', '2026-11-08 16:00:00.050+00', 1, 10, 8, 10, 100, 4.5,
                    '{"dice_command_key":"roll-rating-10-command-a"}');
            -- Command B: a separate rating of the same issue and value one
            -- second later, without a receipt pair. It must stay separate.
            INSERT INTO events (id, type, timestamp, user_id, die, die_after, thread_id,
                                issue_id, rating, context)
            VALUES (3, 'rate', '2026-11-08 16:00:01.000+00', 1, 8, 6, 10, 100, 4.5,
                    '{"dice_command_key":"roll-rating-10-command-b"}');
            -- Legacy rating rows with no linkage keys stay separate.
            INSERT INTO events (id, type, timestamp, user_id, thread_id, issue_id, rating)
            VALUES (4, 'rate', '2026-11-08 16:00:01.100+00', 1, 10, 100, 4.5),
                   (5, 'rate', '2026-11-08 16:00:01.200+00', 1, 10, 100, 4.5);
            "#,
        )
        .await;
        for limit in [1, 2, 10] {
            let items = all_pages(&state, 1, limit).await;
            assert_eq!(
                summary(&items),
                vec![
                    (1, "rate", Some(10), Some(8), Some(4.5)),
                    (3, "rate", Some(8), Some(6), Some(4.5)),
                    (4, "rate", None, None, Some(4.5)),
                    (5, "rate", None, None, Some(4.5)),
                ],
                "limit={limit}"
            );
        }
    }

    #[tokio::test]
    async fn malformed_page_tokens_return_bad_request() {
        let (state, _db) = seeded_state(PRODUCTION_SEQUENCE).await;
        for value in [
            "!!".to_string(),
            token(json!({"t": "garbage", "id": 1, "s": 0})),
            token(json!({"t": 1, "id": 4_294_967_296_i64, "s": 0})),
        ] {
            assert!(matches!(
                page(&state, 1, 10, Some(value)).await,
                Err(ApiError::BadRequest(_))
            ));
        }
    }
}
