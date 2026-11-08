//! Scoped native Roll v2 resources: the die state and the ordered eligible ids.
//!
//! `GET /api/v2/roll/die-state` and `GET /api/v2/roll/eligible-issue-ids`
//! replace the whole-library Roll bootstrap projection with two bounded reads:
//!
//! * the reader's current logical die, the approved d2-d20 ladder and the last
//!   recorded roll, and
//! * the ordered eligible issue identifiers for that die.
//!
//! Both reads issue exactly one PostgreSQL statement, including the token's
//! revocation and credential-epoch check, and both reuse the Option E
//! evaluator and the [`crate::roll_pool`] top-die bound that
//! `POST /api/v2/roll/offer` uses. The reported identifiers are therefore
//! exactly the set the next offer can select: a reader never sees a face the
//! roll cannot produce, and the roll never picks a face the reader could not
//! see.
//!
//! Temporary snoozes stay browser-owned. The server never reconstructs them
//! from stored state: the browser passes its snoozed thread identifiers in the
//! `snoozed` query parameter and the resource applies exactly those, so the
//! reported pool and the offer's pool stay identical for the same browser
//! state.
//!
//! An unacted-on offer is server-owned state, so it is never trusted from the
//! query string. The read folds the same session resolution the offer uses and
//! projects the snooze the offer would record next: the die steps up and the
//! pending thread leaves the pool. That projection is read-only; nothing is
//! persisted until the browser actually posts an offer.
use crate::{
    auth::{validate_folded_auth, FoldedAuthRow, VerifiedAccessClaims, FOLDED_AUTH_CTES},
    db,
    dice_state::{self, DiceAction, LATEST_DIE_CTE},
    option_inputs,
    reading_session::SessionPolicy,
    roll_pool::{offer_frontiers, MAX_TEMPORARY_SNOOZES},
    ApiError, AppState,
};
use axum::{
    extract::{Query, State},
    Json,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashSet,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, OnceLock,
    },
};

/// Handler-level query count for the die-state read.
///
/// This counts the query the handler itself issues, so the focused parity
/// runner can prove the request is one round trip including authentication. It
/// is not a server-side statement total: connection-pool recycling and session
/// bookkeeping are outside this counter.
pub static DIE_STATEMENTS_ISSUED: AtomicU64 = AtomicU64::new(0);

/// Handler-level query count for the eligible-identifier read.
///
/// Same caveat as [`DIE_STATEMENTS_ISSUED`]: it counts this handler's query, not
/// every statement the server may execute for the connection.
pub static ELIGIBLE_STATEMENTS_ISSUED: AtomicU64 = AtomicU64::new(0);

/// The most recent Roll recorded for this reader.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct RollLastRoll {
    /// The rolled thread.
    pub thread_id: Option<i32>,
    /// The rolled issue.
    pub issue_id: Option<i32>,
    /// The rolled issue number.
    pub issue_number: Option<String>,
    /// The recorded roll result.
    pub result: Option<i32>,
    /// The die that produced the roll.
    pub die: Option<i32>,
    /// When the roll was recorded.
    pub rolled_at: Option<String>,
}

/// The reader's current logical die and the approved ladder.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct RollDieStateResponse {
    /// The current logical die.
    pub die: i32,
    /// The approved dice ladder, smallest to largest.
    pub ladder: Vec<i32>,
    /// The die an explicit reset returns to.
    pub default_die: i32,
    /// The most recent recorded roll, when the reader has rolled.
    pub last_roll: Option<RollLastRoll>,
}

/// The ordered eligible issue identifiers for the current die.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct RollEligibleIssueIdsResponse {
    /// The logical die that bounded the list.
    pub die: i32,
    /// The eligible issue identifiers, in queue order.
    pub issue_ids: Vec<i32>,
    /// The owning thread identifiers, parallel to `issue_ids`.
    pub thread_ids: Vec<i32>,
    /// Why an empty in-play pool has no faces, when it does.
    /// Derived from the already-loaded Option E inputs and the eligible
    /// frontiers before the die bound and browser snoozes, exactly as
    /// `GET /api/v2/roll/bootstrap` reports it. `ready` means at least one
    /// frontier is eligible; the other variants name why an empty pool has
    /// no in-play faces (`no_series`, `all_blocked`, `all_completed`,
    /// `all_out_of_pool`). It never carries a list or whole-library report.
    pub pool_reason: crate::reading_constraints::PoolReason,
}

/// Query parameters for `GET /api/v2/roll/eligible-issue-ids`.
#[derive(Debug, Default, Deserialize)]
pub struct EligibleIssueIdsQuery {
    /// Browser-owned temporary snoozed thread identifiers, comma separated.
    pub snoozed: Option<String>,
}

#[derive(Debug, Deserialize)]
struct LastRollRow {
    thread_id: Option<i32>,
    issue_id: Option<i32>,
    issue_number: Option<String>,
    result: Option<i32>,
    die: Option<i32>,
    rolled_at: Option<String>,
}

impl From<LastRollRow> for RollLastRoll {
    fn from(row: LastRollRow) -> Self {
        Self {
            thread_id: row.thread_id,
            issue_id: row.issue_id,
            issue_number: row.issue_number,
            result: row.result,
            die: row.die,
            rolled_at: row.rolled_at,
        }
    }
}

#[derive(Debug, Deserialize)]
struct DiePayload {
    auth: Option<FoldedAuthRow>,
    die_after: Option<i32>,
    last_roll: Option<LastRollRow>,
}

#[derive(Debug, Deserialize)]
struct EligiblePayload {
    auth: Option<FoldedAuthRow>,
    snapshot: option_inputs::SnapshotRows,
    die_after: Option<i32>,
    pending_thread_id: Option<i32>,
}

fn invalid_projection() -> ApiError {
    ApiError::Internal("Invalid native Roll projection".to_string())
}

fn invalid_snoozes() -> ApiError {
    ApiError::Unprocessable("Invalid temporary snooze identifiers".to_string())
}

/// The last recorded roll, with the same owner source and ordering as the die.
const LAST_ROLL_CTE: &str = r#"last_roll AS (
    SELECT selected_thread_id, issue_id, issue_number, result, die,
           to_char(timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS rolled_at
    FROM events
    WHERE user_id = (SELECT user_id FROM me) AND type = 'roll'
    ORDER BY timestamp DESC, id DESC
    LIMIT 1
)"#;

/// The die-state projection of the one owner-scoped statement.
const DIE_SELECT: &str = r#"SELECT jsonb_build_object(
    'auth', (SELECT jsonb_build_object(
        'password_epoch', password_epoch,
        'revoked', revoked
    ) FROM auth),
    'die_after', (SELECT die_after FROM die_state),
    'last_roll', (SELECT jsonb_build_object(
        'thread_id', selected_thread_id,
        'issue_id', issue_id,
        'issue_number', issue_number,
        'result', result,
        'die', die,
        'rolled_at', rolled_at
    ) FROM last_roll)
)::text"#;

/// The caller's pending offer, resolved by the same shared session rule.
///
/// `POST /api/v2/roll/offer` re-reads `pending_thread_id` under its write lock
/// and, when it is present, records a snooze that steps the die up and excludes
/// that thread before selecting. The read must project the same effective die
/// and the same pool, so it folds the same resolution into its own statement.
/// `$4` is the read clock and `$5` the session gap in hours.
fn pending_offer_cte() -> &'static str {
    static SQL: OnceLock<String> = OnceLock::new();
    SQL.get_or_init(|| {
        format!(
            "pending_offer AS (\n    SELECT s.pending_thread_id\n    {}\n)",
            crate::reading_session::session_resolution_body("(SELECT user_id FROM me)", "$4", "$5",)
        )
    })
}

/// The eligible-identifier projection of the one owner-scoped statement.
const ELIGIBLE_SELECT: &str = r#"SELECT jsonb_build_object(
    'auth', (SELECT jsonb_build_object(
        'password_epoch', password_epoch,
        'revoked', revoked
    ) FROM auth),
    'snapshot', (SELECT value FROM snapshot),
    'die_after', (SELECT die_after FROM die_state),
    'pending_thread_id', (SELECT pending_thread_id FROM pending_offer)
)::text"#;

/// One statement: the folded authentication, the current die and the last roll.
///
/// The die CTE is the same owner-scoped predicate `dice_state::current_die`
/// uses inside the offer's write transaction, so the read and the roll can
/// never disagree about which outcome is current.
fn die_statement() -> &'static str {
    static SQL: OnceLock<String> = OnceLock::new();
    SQL.get_or_init(|| {
        format!("WITH {FOLDED_AUTH_CTES},\n{LATEST_DIE_CTE},\n{LAST_ROLL_CTE}\n{DIE_SELECT}")
    })
}

/// One statement: the folded authentication, the Option E snapshot, the die and
/// the pending offer.
///
/// The snapshot CTEs and their projection are the same owner-scoped
/// constraints the pre-authenticated loader uses; only the owner source
/// differs, so the eligible identifiers can never diverge from the offer's
/// eligibility for the same reader.
fn eligible_statement() -> &'static str {
    static SQL: OnceLock<String> = OnceLock::new();
    SQL.get_or_init(|| {
        format!(
            "WITH {FOLDED_AUTH_CTES},\n{SNAPSHOT_CTES},\n{SNAPSHOT_PROJECTION},\n{LATEST_DIE_CTE},\n{pending}\n{ELIGIBLE_SELECT}",
            pending = pending_offer_cte(),
            SNAPSHOT_CTES = option_inputs::SNAPSHOT_CTES,
            SNAPSHOT_PROJECTION = option_inputs::SNAPSHOT_PROJECTION,
        )
    })
}

/// Read the folded authentication, die and last roll in one statement.
async fn load_die_payload(
    state: &AppState,
    claims: &VerifiedAccessClaims,
) -> Result<DiePayload, ApiError> {
    let expected_epoch = claims.expected_epoch()?;
    let username = claims.username().to_string();
    let jti = claims.jti().to_string();
    let bindings: [&(dyn tokio_postgres::types::ToSql + Sync); 3] =
        [&username, &jti, &expected_epoch];
    let connection = db::checkout(state).await?;
    DIE_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed);
    let row = db::query_one_optional(state, connection, die_statement(), &bindings)
        .await?
        .ok_or_else(invalid_projection)?;
    let encoded: String = row.try_get(0).map_err(db::query_error)?;
    let payload: DiePayload = serde_json::from_str(&encoded).map_err(|error| {
        tracing::error!(%error, "Invalid native Roll die projection");
        invalid_projection()
    })?;
    validate_folded_auth(claims, payload.auth.as_ref())?;
    Ok(payload)
}

/// Read the folded authentication, Option E snapshot, die and pending offer in
/// one statement.
async fn load_eligible_payload(
    state: &AppState,
    claims: &VerifiedAccessClaims,
) -> Result<EligiblePayload, ApiError> {
    let expected_epoch = claims.expected_epoch()?;
    let username = claims.username().to_string();
    let jti = claims.jti().to_string();
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|e| {
            tracing::debug!(error = ?e, "preserved underlying error before mapping");
            invalid_projection()
        })?
        .as_secs_f64();
    let gap_hours = SessionPolicy::default().gap_hours;
    let bindings: [&(dyn tokio_postgres::types::ToSql + Sync); 5] =
        [&username, &jti, &expected_epoch, &now, &gap_hours];
    let connection = db::checkout(state).await?;
    ELIGIBLE_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed);
    let row = db::query_one_optional(state, connection, eligible_statement(), &bindings)
        .await?
        .ok_or_else(invalid_projection)?;
    let encoded: String = row.try_get(0).map_err(db::query_error)?;
    let payload: EligiblePayload = serde_json::from_str(&encoded).map_err(|error| {
        tracing::error!(%error, "Invalid native Roll eligible-ids projection");
        invalid_projection()
    })?;
    validate_folded_auth(claims, payload.auth.as_ref())?;
    Ok(payload)
}

/// Parse the browser's temporary snooze hints.
///
/// The hints are exclusion hints only: they can remove a thread from the
/// reported pool and can never add one, grant an issue, or change an
/// owner-scoped reading constraint.
fn parse_snoozed(raw: Option<&str>) -> Result<HashSet<i32>, ApiError> {
    let Some(raw) = raw else {
        return Ok(HashSet::new());
    };
    let mut snoozed = HashSet::new();
    let mut count = 0usize;
    for part in raw.split(',') {
        let part = part.trim();
        if part.is_empty() {
            continue;
        }
        let thread_id: i32 = part.parse().map_err(|e| {
            tracing::debug!(error = ?e, "preserved underlying error before mapping");
            invalid_snoozes()
        })?;
        if thread_id <= 0 {
            return Err(invalid_snoozes());
        }
        count += 1;
        if count > MAX_TEMPORARY_SNOOZES {
            return Err(ApiError::Unprocessable(
                "Too many temporary snoozes".to_string(),
            ));
        }
        snoozed.insert(thread_id);
    }
    Ok(snoozed)
}

/// Select the eligible identifiers the next offer can draw from.
///
/// The die bounds the pool and the browser's temporary snoozes leave the queue
/// before that bound, exactly as [`crate::roll_pool::offer_frontiers`] does for
/// `POST /api/v2/roll/offer`. When the reader has an unacted-on offer, the next
/// offer snoozes it first: that steps the die up and excludes the pending
/// thread, so the read projects the same outcome without persisting an event.
fn select_eligible(
    inputs: option_inputs::OptionInputs,
    die_after: Option<i32>,
    pending_thread_id: Option<i32>,
    snoozed: &HashSet<i32>,
) -> Result<RollEligibleIssueIdsResponse, ApiError> {
    let validated = option_inputs::validated_contained(inputs)?;
    let candidates = validated.eligible_frontiers().map_err(|e| {
        tracing::debug!(error = ?e, "preserved underlying error before mapping");
        ApiError::Internal("Invalid reading constraints".to_string())
    })?;
    let current_die = dice_state::projected_die(die_after);
    let (die, mut excluded) = match pending_thread_id {
        Some(thread_id) => (
            dice_state::apply_action(current_die, DiceAction::Reroll).map_err(|e| {
                tracing::debug!(error = ?e, "preserved underlying error before mapping");
                invalid_projection()
            })?,
            HashSet::from([thread_id]),
        ),
        None => (current_die, HashSet::new()),
    };
    excluded.extend(snoozed.iter().copied());
    let pool = offer_frontiers(&candidates, &excluded, die);
    // A single reason, derived from the same validated inputs, keeps the
    // empty pool state truthful without re-materializing whole-library
    // diagnostics and without adding database work. It intentionally uses
    // `candidates` before the die bound and browser snoozes, so a pool that
    // is empty only because every face was snoozed still reports `ready`
    // and the frontend's snoozed copy owns the explanation.
    let pool_reason = crate::reading_constraints::pool_reason(validated.inputs(), &candidates);
    Ok(RollEligibleIssueIdsResponse {
        die,
        issue_ids: pool.iter().map(|item| item.issue_id).collect(),
        thread_ids: pool.iter().map(|item| item.thread_id).collect(),
        pool_reason,
    })
}

/// Read the reader's current logical die, the ladder and the last roll.
pub async fn die_state(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
) -> Result<Json<RollDieStateResponse>, ApiError> {
    let payload = load_die_payload(&state, &claims).await?;
    Ok(Json(RollDieStateResponse {
        die: dice_state::projected_die(payload.die_after),
        ladder: dice_state::DICE_LADDER.to_vec(),
        default_die: dice_state::DEFAULT_DIE,
        last_roll: payload.last_roll.map(RollLastRoll::from),
    }))
}

/// Read the ordered eligible issue identifiers for the current die.
pub async fn eligible_issue_ids(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    Query(query): Query<EligibleIssueIdsQuery>,
) -> Result<Json<RollEligibleIssueIdsResponse>, ApiError> {
    let snoozed = parse_snoozed(query.snoozed.as_deref())?;
    let payload = load_eligible_payload(&state, &claims).await?;
    let inputs = option_inputs::assemble_snapshot(payload.snapshot)?;
    Ok(Json(select_eligible(
        inputs,
        payload.die_after,
        payload.pending_thread_id,
        &snoozed,
    )?))
}

/// Documentation-only operation for the mounted v2 Roll die-state read.
#[utoipa::path(
    get,
    path = "/api/v2/roll/die-state",
    tag = "roll",
    description = "The published response is the actual handler DTO, so the current logical die, approved d2-d20 ladder, default die and last roll stay in the live contract.",
    responses(
        (status = 200, description = "Current logical die, approved ladder and last roll", body = RollDieStateResponse),
        (status = 401, description = "Not authenticated"),
        (status = 500, description = "Invalid native Roll projection"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn die_state_documentation() {}

/// Documentation-only operation for the mounted v2 eligible-identifier read.
#[utoipa::path(
    get,
    path = "/api/v2/roll/eligible-issue-ids",
    tag = "roll",
    description = "The ordered eligible issue identifiers for the current die. Temporary snoozes are passed as a query parameter and applied exactly as the offer does.",
    params(
        ("snoozed" = Option<String>, Query, description = "Comma-separated browser-owned temporary snoozed thread identifiers")
    ),
    responses(
        (status = 200, description = "Ordered eligible issue identifiers for the current die", body = RollEligibleIssueIdsResponse),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Invalid temporary snooze identifiers"),
        (status = 500, description = "Invalid native Roll projection"),
        (status = 503, description = "Database temporarily unavailable")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
pub fn eligible_issue_ids_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{db, router, test_support};
    use axum::{
        body::{to_bytes, Body},
        http::{Request, StatusCode},
        Router,
    };
    use deadpool_postgres::Object;
    use serde_json::Value;
    use tower::ServiceExt;

    /// The credential epoch both fixture tokens carry.
    const STORED_EPOCH: i64 = 1_767_225_600;
    const TEST_SECRET: &str = test_support::TEST_JWT_SECRET;

    /// Two readers with disjoint libraries, distinct dice and one dangling
    /// credential, so every owner-scoped filter has something to exclude.
    ///
    /// The tables come from the canonical Alembic fixture; only rows are seeded
    /// here, so a production-only column or constraint difference fails instead
    /// of hiding behind an approximation.
    const SEED_ROWS: &str = r#"
        INSERT INTO users (id, username, password_changed_at) VALUES
            (1, 'reader-one', to_timestamp({STORED_EPOCH})),
            (2, 'reader-two', to_timestamp({STORED_EPOCH})),
            (3, 'reader-empty', to_timestamp({STORED_EPOCH}));
        INSERT INTO revoked_tokens (user_id, jti, expires_at)
            VALUES (1, 'revoked-jti', NOW() + interval '1 day');
        -- Reader one: six active threads, one completed thread, a d4 die.
        INSERT INTO threads
            (id, user_id, title, format, issues_remaining, queue_position,
             total_issues, reading_progress, status, is_blocked)
        VALUES
            (10, 1, 'Saga', 'Comic', 3, 1, 12, '25%', 'active', false),
            (20, 1, 'Watchmen', 'Graphic Novel', 1, 2, 12, '8%', 'active', false),
            (30, 1, 'Batman', 'Comic', 5, 3, 20, '15%', 'active', false),
            (40, 1, 'Sandman', 'Graphic Novel', 2, 4, 10, '20%', 'active', false),
            (50, 1, 'Hellboy', 'Comic', 4, 5, 15, '30%', 'active', false),
            (60, 1, 'Y: The Last Man', 'Graphic Novel', 6, 6, 12, '50%', 'active', false),
            (70, 1, 'Finished', 'Comic', 0, 7, 4, '100%', 'completed', false);
        -- Reader two: two active threads, a legacy d50 outcome and one
        -- reader prerequisite that holds the second thread behind the first.
        INSERT INTO threads
            (id, user_id, title, format, issues_remaining, queue_position,
             total_issues, reading_progress, status, is_blocked)
        VALUES
            (110, 2, 'Bone', 'Comic', 3, 1, 10, '30%', 'active', false),
            (120, 2, 'Lucifer', 'Comic', 5, 2, 11, '45%', 'active', false);
        INSERT INTO issues
            (id, thread_id, position, status, issue_number, created_at)
        VALUES
            (100, 10, 1, 'unread', '1', NOW()),
            (200, 20, 1, 'unread', '1', NOW()),
            (300, 30, 1, 'unread', '1', NOW()),
            (400, 40, 1, 'unread', '1', NOW()),
            (500, 50, 1, 'unread', '1', NOW()),
            (600, 60, 1, 'unread', '1', NOW()),
            (700, 70, 1, 'unread', '1', NOW()),
            (1100, 110, 1, 'unread', '1', NOW()),
            (1200, 120, 1, 'unread', '1', NOW());
        -- The canonical fixture's pointer forward-reference is non-deferrable,
        -- so it is set after the issues exist.
        UPDATE threads SET next_unread_issue_id = id * 10;
        INSERT INTO dependencies
            (created_at, source_issue_id, target_issue_id, origin, provenance)
        VALUES (NOW(), 1100, 1200, 'reader', 'reader approved');
        INSERT INTO events
            (user_id, type, die_after, timestamp)
        VALUES
            (1, 'manual_die', 4, '2026-10-01 09:00:00+00'),
            (2, 'rate', 50, '2026-10-02 09:00:00+00');
        INSERT INTO events
            (user_id, type, selected_thread_id, die, result, issue_id,
             issue_number, timestamp)
        VALUES
            (1, 'roll', 20, 4, 2, 200, '1', '2026-10-05 09:00:00+00'),
            (1, 'roll', 30, 4, 3, 300, '1', '2026-11-01 10:00:00+00');
    "#;

    struct Fixture {
        state: Arc<AppState>,
        app: Router,
        /// Serializes this test with every other canonical-schema test.
        _db: tokio::sync::MutexGuard<'static, ()>,
    }

    impl Fixture {
        /// Reset the canonical schema, seed rows and mount the router, or skip
        /// when no disposable PostgreSQL is configured.
        async fn start() -> Option<Self> {
            let state = test_support::test_state(2).await?;
            let guard = test_support::reset_for_test(&state).await;
            let connection = db::checkout(&state).await.expect("seed connection");
            connection
                .batch_execute(&SEED_ROWS.replace("{STORED_EPOCH}", &STORED_EPOCH.to_string()))
                .await
                .expect("seed canonical rows");
            drop(Object::take(connection));
            let app = router(state.clone());
            Some(Self {
                state,
                app,
                _db: guard,
            })
        }

        /// Give one reader an unacted-on offer on `thread_id`.
        async fn seed_pending_offer(&self, user_id: i32, thread_id: i32, issue_id: i32) {
            let connection = db::checkout(&self.state).await.expect("session seed");
            connection
                .execute(
                    "INSERT INTO sessions
                        (user_id, start_die, pending_thread_id, pending_issue_id,
                         pending_thread_updated_at)
                     VALUES ($1, 6, $2, $3, NOW())",
                    &[&user_id, &thread_id, &issue_id],
                )
                .await
                .expect("seed pending offer");
            drop(Object::take(connection));
        }

        /// Mint an access token the mounted router accepts.
        fn token(&self, username: &str, jti: &str, password_epoch: i64) -> String {
            let claims = crate::auth::dto::Claims::access(username, jti, password_epoch, 15);
            jsonwebtoken::encode(
                &jsonwebtoken::Header::default(),
                &claims,
                &jsonwebtoken::EncodingKey::from_secret(TEST_SECRET.as_bytes()),
            )
            .expect("signed access token")
        }

        /// Drive one mounted request and decode its JSON body.
        async fn get(&self, uri: &str, token: Option<&str>) -> (StatusCode, Value) {
            let mut builder = Request::builder().method("GET").uri(uri);
            if let Some(token) = token {
                builder = builder.header("authorization", format!("Bearer {token}"));
            }
            let response = self
                .app
                .clone()
                .oneshot(builder.body(Body::empty()).unwrap())
                .await
                .unwrap();
            let status = response.status();
            let bytes = to_bytes(response.into_body(), 4096).await.unwrap();
            let body: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
            (status, body)
        }
    }

    fn ints(body: &Value, field: &str) -> Vec<i32> {
        body[field]
            .as_array()
            .expect("array field")
            .iter()
            .map(|value| value.as_i64().expect("integer element") as i32)
            .collect()
    }

    fn frontier(thread_id: i32) -> crate::reading_constraints::EligibleFrontier {
        crate::reading_constraints::EligibleFrontier {
            thread_id,
            issue_id: thread_id * 100,
            queue_position: thread_id,
        }
    }

    #[test]
    fn snooze_hints_are_bounded_positive_and_never_invent_a_thread() {
        assert!(parse_snoozed(None).unwrap().is_empty());
        assert!(parse_snoozed(Some("")).unwrap().is_empty());
        assert_eq!(
            parse_snoozed(Some("2, 7,2")).unwrap(),
            HashSet::from([2, 7]),
            "duplicate hints collapse into one exclusion"
        );
        for invalid in ["0", "-1", "abc", "1,x", "1.5"] {
            assert!(
                parse_snoozed(Some(invalid)).is_err(),
                "{invalid} must not become a thread exclusion"
            );
        }
        let too_many = (1..=MAX_TEMPORARY_SNOOZES + 1)
            .map(|id| id.to_string())
            .collect::<Vec<_>>()
            .join(",");
        assert_eq!(
            parse_snoozed(Some(&too_many)).unwrap_err().status(),
            StatusCode::UNPROCESSABLE_ENTITY
        );
    }

    #[test]
    fn the_reported_pool_is_the_offer_pool() {
        let candidates: Vec<_> = (1..=8).map(frontier).collect();
        let snoozed = HashSet::from([2, 3]);
        let offer = offer_frontiers(&candidates, &snoozed, 4);
        let offer_ids: Vec<i32> = offer.iter().map(|item| item.issue_id).collect();
        assert_eq!(offer_ids, vec![100, 400, 500, 600]);
        assert_eq!(
            offer_ids,
            candidates
                .iter()
                .filter(|item| !snoozed.contains(&item.thread_id))
                .take(4)
                .map(|item| item.issue_id)
                .collect::<Vec<_>>(),
            "the offer leaves the snoozed queue before the die bound"
        );
    }

    #[test]
    fn each_resource_read_is_one_statement_including_authentication() {
        for statement in [die_statement(), eligible_statement()] {
            assert!(
                !statement.trim_end().trim_end_matches(';').contains(';'),
                "one resource read must issue one statement"
            );
            assert!(statement.contains("revoked_tokens"));
            assert!(statement.contains("(SELECT user_id FROM me)"));
        }
        assert!(die_statement().contains("'roll'"));
        // The pending offer is resolved by the shared session rule, not a
        // second statement and not a second copy of the predicate.
        assert!(eligible_statement().contains("pending_offer"));
        assert!(
            eligible_statement().contains(&crate::reading_session::session_resolution_body(
                "(SELECT user_id FROM me)",
                "$4",
                "$5",
            ))
        );
    }

    #[test]
    fn session_resolution_has_one_definition() {
        let body = crate::reading_session::session_resolution_body("$1", "$2", "$3");
        assert!(body.contains("s.user_id = $1"));
        assert!(body.contains("to_timestamp($2)"));
        assert!(body.contains("make_interval(hours => $3)"));
        assert!(
            !body.contains('{'),
            "every placeholder must be filled from the one template"
        );
        assert_eq!(
            body.matches("s.pending_thread_id IS NOT NULL").count(),
            3,
            "the activity expression appears in the filter and the ordering, \
             plus the pending-first ordering key"
        );
    }

    #[tokio::test]
    async fn die_state_and_eligible_ids_are_the_same_faces_the_offer_can_pick() {
        let Some(fixture) = Fixture::start().await else {
            return;
        };
        let token = fixture.token("reader-one", "reader-one-jti", STORED_EPOCH);

        let (status, die) = fixture.get("/api/v2/roll/die-state", Some(&token)).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(die["die"], 4);
        assert_eq!(die["default_die"], 6);
        assert_eq!(ints(&die, "ladder"), vec![2, 4, 6, 8, 10, 12, 20]);
        assert_eq!(die["last_roll"]["thread_id"], 30);
        assert_eq!(die["last_roll"]["issue_id"], 300);
        assert_eq!(die["last_roll"]["issue_number"], "1");
        assert_eq!(die["last_roll"]["result"], 3);
        assert_eq!(die["last_roll"]["die"], 4);
        assert_eq!(die["last_roll"]["rolled_at"], "2026-11-01T10:00:00.000Z");

        // The offer's own pool for the same reader, die and browser snoozes.
        let user = crate::auth::AuthenticatedUser::for_test(1);
        let snoozed = HashSet::from([20, 30]);
        let validated = option_inputs::load_option_inputs(&fixture.state, user)
            .await
            .unwrap();
        let offer = offer_frontiers(
            &validated.eligible_frontiers().unwrap(),
            &snoozed,
            die["die"].as_i64().unwrap() as i32,
        );
        let expected_ids: Vec<i32> = offer.iter().map(|item| item.issue_id).collect();
        let expected_threads: Vec<i32> = offer.iter().map(|item| item.thread_id).collect();

        let (status, eligible) = fixture
            .get("/api/v2/roll/eligible-issue-ids", Some(&token))
            .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(eligible["die"], 4);
        assert_eq!(eligible["pool_reason"], "ready");
        assert_eq!(ints(&eligible, "issue_ids"), vec![100, 200, 300, 400]);
        assert_eq!(ints(&eligible, "thread_ids"), vec![10, 20, 30, 40]);

        let (status, snoozed_eligible) = fixture
            .get(
                "/api/v2/roll/eligible-issue-ids?snoozed=20,30",
                Some(&token),
            )
            .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            ints(&snoozed_eligible, "issue_ids"),
            expected_ids,
            "the reported pool is the offer pool for the same browser snoozes"
        );
        assert_eq!(ints(&snoozed_eligible, "thread_ids"), expected_threads);
        assert_eq!(
            ints(&snoozed_eligible, "issue_ids"),
            vec![100, 400, 500, 600]
        );
        assert_eq!(ints(&snoozed_eligible, "thread_ids"), vec![10, 40, 50, 60]);

        // A pool that is empty only because every eligible thread was
        // browser-snoozed still reports `ready`, from the candidates before
        // the snoozes, so the frontend snoozed copy owns that explanation
        // rather than a blocked/completed empty-pool message.
        let (status, all_snoozed) = fixture
            .get(
                "/api/v2/roll/eligible-issue-ids?snoozed=10,20,30,40,50,60",
                Some(&token),
            )
            .await;
        assert_eq!(status, StatusCode::OK);
        assert!(ints(&all_snoozed, "issue_ids").is_empty());
        assert_eq!(all_snoozed["pool_reason"], "ready");
    }

    #[tokio::test]
    async fn a_pending_offer_reports_the_die_and_pool_the_next_offer_will_use() {
        let Some(fixture) = Fixture::start().await else {
            return;
        };
        let token = fixture.token("reader-one", "reader-one-jti", STORED_EPOCH);
        // The reader has an unacted-on offer on the first queue entry.
        fixture.seed_pending_offer(1, 10, 100).await;

        let (status, eligible) = fixture
            .get("/api/v2/roll/eligible-issue-ids", Some(&token))
            .await;
        assert_eq!(status, StatusCode::OK);
        // The next offer snoozes the pending thread first: d4 steps up to d6
        // and thread 10 leaves the pool, exactly as the offer's write path does.
        assert_eq!(eligible["die"], 6, "the pending snooze steps the die up");
        assert_eq!(eligible["pool_reason"], "ready");
        assert_eq!(
            ints(&eligible, "thread_ids"),
            vec![20, 30, 40, 50, 60],
            "the pending offer's thread is not selectable again"
        );
        assert_eq!(ints(&eligible, "issue_ids"), vec![200, 300, 400, 500, 600]);

        // Browser snoozes still leave the queue before the die bound.
        let (status, snoozed) = fixture
            .get("/api/v2/roll/eligible-issue-ids?snoozed=20", Some(&token))
            .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(ints(&snoozed, "thread_ids"), vec![30, 40, 50, 60]);

        // The die-state read stays a plain projection and never snoozes.
        let (status, die) = fixture.get("/api/v2/roll/die-state", Some(&token)).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(die["die"], 4);
    }

    #[tokio::test]
    async fn empty_library_reports_no_series_at_eligible_ids() {
        let Some(fixture) = Fixture::start().await else {
            return;
        };
        let token = fixture.token("reader-empty", "reader-empty-jti", STORED_EPOCH);

        let (status, eligible) = fixture
            .get("/api/v2/roll/eligible-issue-ids", Some(&token))
            .await;
        assert_eq!(status, StatusCode::OK);
        assert!(ints(&eligible, "issue_ids").is_empty());
        assert!(ints(&eligible, "thread_ids").is_empty());
        assert_eq!(
            eligible["pool_reason"], "no_series",
            "a reader with no series must explain the empty pool, not claim ready"
        );
    }

    #[tokio::test]
    async fn two_readers_never_see_the_other_readers_die_threads_or_rolls() {
        let Some(fixture) = Fixture::start().await else {
            return;
        };
        let one = fixture.token("reader-one", "reader-one-jti", STORED_EPOCH);
        let two = fixture.token("reader-two", "reader-two-jti", STORED_EPOCH);

        let (status, die_one) = fixture.get("/api/v2/roll/die-state", Some(&one)).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(die_one["die"], 4);

        let (status, die_two) = fixture.get("/api/v2/roll/die-state", Some(&two)).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            die_two["die"], 20,
            "a legacy d50 outcome projects to the approved d20"
        );
        assert!(die_two["last_roll"].is_null());

        let (status, eligible_one) = fixture
            .get("/api/v2/roll/eligible-issue-ids", Some(&one))
            .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(ints(&eligible_one, "thread_ids"), vec![10, 20, 30, 40]);

        let (status, eligible_two) = fixture
            .get("/api/v2/roll/eligible-issue-ids", Some(&two))
            .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            ints(&eligible_two, "issue_ids"),
            vec![1100],
            "the reader prerequisite holds thread 120 behind issue 1100"
        );
        assert_eq!(ints(&eligible_two, "thread_ids"), vec![110]);
        assert!(!ints(&eligible_two, "thread_ids").contains(&70));
    }

    #[tokio::test]
    async fn a_rejected_credential_never_reaches_an_owner_scoped_row() {
        let Some(fixture) = Fixture::start().await else {
            return;
        };
        let (status, _) = fixture.get("/api/v2/roll/die-state", None).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);

        let unknown = fixture.token("reader-unknown", "unknown-jti", STORED_EPOCH);
        let (status, _) = fixture.get("/api/v2/roll/die-state", Some(&unknown)).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);

        let revoked = fixture.token("reader-one", "revoked-jti", STORED_EPOCH);
        let (status, _) = fixture.get("/api/v2/roll/die-state", Some(&revoked)).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);

        let stale = fixture.token("reader-one", "reader-one-jti", STORED_EPOCH - 1);
        let (status, _) = fixture.get("/api/v2/roll/die-state", Some(&stale)).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);

        let stale = fixture.token("reader-one", "reader-one-jti", STORED_EPOCH - 1);
        let (status, _) = fixture
            .get("/api/v2/roll/eligible-issue-ids", Some(&stale))
            .await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);

        let malformed = fixture.token("reader-one", "reader-one-jti", STORED_EPOCH);
        let (status, _) = fixture
            .get(
                "/api/v2/roll/eligible-issue-ids?snoozed=abc",
                Some(&malformed),
            )
            .await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    }
}
