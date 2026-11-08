//! Authenticated issue read/rate completion. Option E selects offers, not
//! permissions: this writer applies the exact issue action a reader asked for,
//! and only a Roll-offer rating carries the Roll completion effects.
//! Uses the canonical issues/events schema and the shared PostgreSQL pool.
use crate::{
    auth::AuthenticatedUser,
    db,
    dice_mutation::{self, DiceCommand},
    dice_state, option_inputs, queue, roll_exclusions, ApiError,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use tokio_postgres::Transaction;

/// Upper bound for one visible issue-card group. Keeps the set request bounded
/// instead of degenerating into a per-card or whole-library lookup.
pub(crate) const MAX_CARD_ISSUES: usize = 200;

/// Source of one issue action: a manual read from a Thread row (#3581).
const DIRECT_SOURCE: &str = "direct";

/// Source of one issue action: finishing the issue Roll offered.
const ROLL_OFFER_SOURCE: &str = "roll_offer";

/// Rating at or above this steps the die down and moves the series forward.
///
/// Mirrors the legacy `rating_threshold` default, the frontend
/// `RATING_THRESHOLD` and `dice_state::DiceAction::RollRating`, which all use
/// the same boundary, so the ladder and the queue agree on one threshold.
const ROLL_RATING_THRESHOLD: f64 = 4.0;

/// Rating applied to a new read that arrives without one. Mirrors the legacy
/// Roll default and the direct-read default this writer already used.
const DEFAULT_NEW_READ_RATING: f64 = 3.5;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct IssueReadRateRequest {
    /// Explicit new status. Omit to leave read state unchanged.
    pub status: Option<String>,
    /// Effective issue rating in 0.5-point steps. Omit to keep the stored rating.
    pub rating: Option<f64>,
    /// Client-generated retry key. Same key/payload replays the same receipt.
    pub idempotency_key: String,
    /// Source of the issue action. Omitted or "direct" is a manual read from a
    /// Thread row: it never steps the die and never repositions the queue.
    /// "roll_offer" is a Roll completion: it applies the Roll rating semantics
    /// (die stepping, queue placement, and a link back to the originating offer
    /// event) in the same transaction as the read.
    #[serde(default)]
    pub source: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, utoipa::ToSchema)]
pub struct IssueCard {
    /// Owned issue identifier.
    pub issue_id: i32,
    /// Owning thread identifier.
    pub thread_id: i32,
    /// Display series/run title.
    pub thread_title: String,
    /// Exact issue number within the run.
    pub issue_number: String,
    /// Stored read state (``read`` or ``unread``).
    pub status: String,
    /// UTC read timestamp, when read.
    pub read_at: Option<String>,
    /// Effective per-issue saved rating.
    pub rating: Option<f64>,
    /// Whether a confirmed ComicVine issue mapping exists.
    pub has_confirmed_identity: bool,
    /// Stored mapping state (``confirmed``, ``candidate``, ...).
    pub mapping_state: String,
    /// Confirmed provider issue identifier, never a provisional candidate.
    pub comicvine_issue_id: Option<String>,
    /// Exact provider-supplied CDN URL. Null when unmapped; never image bytes.
    pub cover_image_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct IssueCardsRequest {
    /// Visible issue identifiers requested for one bounded batch.
    pub issue_ids: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, utoipa::ToSchema)]
pub struct IssueCardsResponse {
    /// Owned cards in first-request order; foreign or missing IDs are omitted.
    pub items: Vec<IssueCard>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, utoipa::ToSchema)]
pub struct ThreadProgress {
    pub thread_id: i32,
    pub status: String,
    pub issues_remaining: i32,
    pub next_unread_issue_id: Option<i32>,
    pub reading_progress: Option<String>,
    pub last_rating: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, utoipa::ToSchema)]
pub struct IssueReadRateResponse {
    pub issue: IssueCard,
    pub thread: ThreadProgress,
    pub read_event_created: bool,
    pub rating_event_created: bool,
    pub replayed: bool,
    pub final_rating: Option<f64>,
    /// Die after this rating, when source is "roll_offer". Null for "direct" source.
    pub die_after: Option<i32>,
}

fn invalid(message: &'static str) -> ApiError {
    ApiError::Unprocessable(message.into())
}

/// Resolve the requested action source to its canonical value.
///
/// An omitted source is a direct action, which is what every pre-source client
/// sent. `validate` already rejected any other value, so this only normalizes.
fn rating_source(request: &IssueReadRateRequest) -> Result<&'static str, ApiError> {
    match request.source.as_deref() {
        None | Some(DIRECT_SOURCE) => Ok(DIRECT_SOURCE),
        Some(ROLL_OFFER_SOURCE) => Ok(ROLL_OFFER_SOURCE),
        Some(_) => Err(invalid("Invalid issue action source")),
    }
}

pub(crate) fn validate(request: &IssueReadRateRequest) -> Result<(), ApiError> {
    if !(8..=128).contains(&request.idempotency_key.len())
        || !request
            .idempotency_key
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
    {
        return Err(invalid("Invalid issue idempotency key"));
    }
    if !matches!(
        request.status.as_deref(),
        None | Some("read") | Some("unread")
    ) {
        return Err(invalid("Invalid issue status"));
    }
    if let Some(rating) = request.rating {
        if !rating.is_finite() || !(0.5..=5.0).contains(&rating) || (rating * 2.0).fract() != 0.0 {
            return Err(invalid("Rating must be 0.5 to 5.0 in half steps"));
        }
    }
    if !matches!(
        request.source.as_deref(),
        None | Some(DIRECT_SOURCE) | Some(ROLL_OFFER_SOURCE)
    ) {
        return Err(invalid("Invalid issue action source"));
    }
    if request.source.as_deref() == Some(ROLL_OFFER_SOURCE) && request.rating.is_none() {
        return Err(invalid("A Roll offer rating requires a rating"));
    }
    if request.status.is_none() && request.rating.is_none() {
        return Err(invalid("Provide status or rating"));
    }
    Ok(())
}

pub(crate) fn validate_cards(request: &IssueCardsRequest) -> Result<(), ApiError> {
    if request.issue_ids.is_empty() || request.issue_ids.len() > MAX_CARD_ISSUES {
        return Err(invalid("Provide 1 to 200 issue ids"));
    }
    if request.issue_ids.iter().any(|issue_id| *issue_id <= 0) {
        return Err(invalid("Issue ids must be positive"));
    }
    Ok(())
}

fn card_from_row(row: &tokio_postgres::Row) -> IssueCard {
    // Only a confirmed mapping may expose provider identity or a cover URL.
    // The exact provider-supplied URL is passed through without rewriting.
    let mapping_state: String = row.get(7);
    let confirmed = mapping_state == "confirmed";
    IssueCard {
        issue_id: row.get(0),
        thread_id: row.get(1),
        thread_title: row.get(2),
        issue_number: row.get(3),
        status: row.get(4),
        read_at: row.get(5),
        rating: row.get(6),
        has_confirmed_identity: confirmed,
        mapping_state,
        comicvine_issue_id: if confirmed { row.get(8) } else { None },
        cover_image_url: if confirmed { row.get(9) } else { None },
    }
}

async fn card(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    issue_id: i32,
) -> Result<IssueCard, ApiError> {
    // This is the mutated single owned card; the batch path below uses the
    // same fields and mapping precedence for every visible issue group.
    let row = tx
        .query_one(
            "SELECT i.id, i.thread_id, t.title, i.issue_number, i.status,
                to_char(i.read_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"'),
                (SELECT e.rating FROM events e WHERE e.user_id=$2 AND e.issue_id=i.id
                    AND e.type='rate' AND e.rating IS NOT NULL
                    ORDER BY e.timestamp DESC, e.id DESC LIMIT 1),
                COALESCE(mapping.status, 'unmapped'), mapping.external_id,
                mapping.cover_url
         FROM issues i
         JOIN threads t ON t.id=i.thread_id
         LEFT JOIN LATERAL (
             SELECT m.status, x.external_id,
                 CASE WHEN m.status='confirmed' THEN
                     COALESCE(
                         NULLIF(BTRIM(x.metadata_json->>'image_url'), ''),
                         NULLIF(BTRIM(x.metadata_json->>'primary_image'), ''),
                         NULLIF(BTRIM(x.metadata_json#>>'{image,original_url}'), ''),
                         NULLIF(BTRIM(x.metadata_json#>>'{image,super_url}'), ''),
                         NULLIF(BTRIM(x.metadata_json#>>'{image,medium_url}'), ''),
                         NULLIF(BTRIM(x.metadata_json#>>'{image,small_url}'), ''),
                         NULLIF(BTRIM(x.metadata_json->>'cover_image_url'), '')
                     )
                 ELSE NULL END AS cover_url
             FROM issue_external_identity_mappings m
             JOIN external_identities x ON x.id=m.external_identity_id
             WHERE m.issue_id=i.id AND x.entity_type='issue'
               AND m.status<>'rejected'
               AND lower(x.provider) IN ('comicvine', 'comic_vine')
             ORDER BY (m.status='confirmed') DESC, m.confidence DESC NULLS LAST,
                      m.updated_at DESC, m.id DESC
             LIMIT 1
         ) mapping ON true
         WHERE i.id=$1 AND t.user_id=$2",
            &[&issue_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    Ok(card_from_row(&row))
}

/// Bounded owner-scoped batch card projection for one visible issue group.
/// One set-based query resolves read state, rating, mapping state and the exact
/// stored provider CDN URL. No per-card round trip or provider metadata call.
pub(crate) async fn cards(
    connection: &tokio_postgres::Client,
    user: AuthenticatedUser,
    issue_ids: &[i32],
) -> Result<IssueCardsResponse, ApiError> {
    let mut requested: Vec<i32> = Vec::new();
    for issue_id in issue_ids {
        if !requested.contains(issue_id) {
            requested.push(*issue_id);
        }
    }
    let rows = connection
        .query(
            "SELECT i.id, i.thread_id, t.title, i.issue_number, i.status,
                to_char(i.read_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"'),
                (SELECT e.rating FROM events e WHERE e.user_id=$1 AND e.issue_id=i.id
                    AND e.type='rate' AND e.rating IS NOT NULL
                    ORDER BY e.timestamp DESC, e.id DESC LIMIT 1),
                COALESCE(mapping.status, 'unmapped'), mapping.external_id,
                mapping.cover_url
         FROM issues i
         JOIN threads t ON t.id=i.thread_id
         LEFT JOIN LATERAL (
             SELECT m.status, x.external_id,
                 CASE WHEN m.status='confirmed' THEN
                     COALESCE(
                         NULLIF(BTRIM(x.metadata_json->>'image_url'), ''),
                         NULLIF(BTRIM(x.metadata_json->>'primary_image'), ''),
                         NULLIF(BTRIM(x.metadata_json#>>'{image,original_url}'), ''),
                         NULLIF(BTRIM(x.metadata_json#>>'{image,super_url}'), ''),
                         NULLIF(BTRIM(x.metadata_json#>>'{image,medium_url}'), ''),
                         NULLIF(BTRIM(x.metadata_json#>>'{image,small_url}'), ''),
                         NULLIF(BTRIM(x.metadata_json->>'cover_image_url'), '')
                     )
                 ELSE NULL END AS cover_url
             FROM issue_external_identity_mappings m
             JOIN external_identities x ON x.id=m.external_identity_id
             WHERE m.issue_id=i.id AND x.entity_type='issue'
               AND m.status<>'rejected'
               AND lower(x.provider) IN ('comicvine', 'comic_vine')
             ORDER BY (m.status='confirmed') DESC, m.confidence DESC NULLS LAST,
                      m.updated_at DESC, m.id DESC
             LIMIT 1
         ) mapping ON true
         WHERE t.user_id=$1 AND i.id=ANY($2::int[])",
            &[&user.id(), &requested],
        )
        .await
        .map_err(db::query_error)?;
    let mut by_id: HashMap<i32, IssueCard> = HashMap::with_capacity(rows.len());
    for row in &rows {
        let card = card_from_row(row);
        by_id.insert(card.issue_id, card);
    }
    Ok(IssueCardsResponse {
        items: requested
            .into_iter()
            .filter_map(|issue_id| by_id.remove(&issue_id))
            .collect(),
    })
}

/// Canonical blocked thread ids for one owner, read inside the caller's transaction.
///
/// This is the SQL form of `comic_pile.dependencies._get_blocked_thread_ids_uncached`:
/// a thread is blocked when its current unread frontier issue
/// (`threads.next_unread_issue_id`) has an unread prerequisite over a canonical
/// `dependencies` edge. Historical CBL materialization rows (`cbl-order:%`
/// notes) are inert and never block. Keep the predicate identical rather than
/// introducing a second notion of "blocked".
async fn canonical_blocked_thread_ids(
    tx: &Transaction<'_>,
    user_id: i32,
) -> Result<Vec<i32>, ApiError> {
    let rows = tx
        .query(
            "SELECT DISTINCT target_thread.id
             FROM threads target_thread
             JOIN issues next_unread_issue
               ON next_unread_issue.id = target_thread.next_unread_issue_id
             JOIN dependencies dependency
               ON dependency.target_issue_id = next_unread_issue.id
             JOIN issues source_issue
               ON source_issue.id = dependency.source_issue_id
             JOIN threads source_thread
               ON source_thread.id = source_issue.thread_id
             WHERE target_thread.user_id = $1
               AND source_thread.user_id = $1
               AND target_thread.next_unread_issue_id IS NOT NULL
               AND source_issue.status <> 'read'
               AND next_unread_issue.status <> 'read'
               AND (dependency.note IS NULL OR dependency.note NOT LIKE 'cbl-order:%')",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(rows.iter().map(|row| row.get(0)).collect())
}

/// Refresh the persisted derived `threads.is_blocked` flag for one owner.
///
/// `is_blocked` is denormalized issue-read state, so every writer that changes
/// read state must refresh it in the same transaction. The Roll offer writer and
/// the legacy queue projection both filter on the stored column; a stale value
/// lets a re-blocked thread enter the pool or hides a just-unblocked one.
/// Mirrors `comic_pile.dependencies.refresh_user_blocked_status`.
pub(crate) async fn refresh_blocked_threads(
    tx: &Transaction<'_>,
    user_id: i32,
) -> Result<(), ApiError> {
    let blocked = canonical_blocked_thread_ids(tx, user_id).await?;
    // `id = ANY($2)` is false for an empty array, so this blocks exactly the
    // canonical set and clears every other stale flag in one owner-scoped write.
    tx.execute(
        "UPDATE threads t
         SET is_blocked = (t.id = ANY($2::int[]))
         WHERE t.user_id = $1
           AND t.is_blocked IS DISTINCT FROM (t.id = ANY($2::int[]))",
        &[&user_id, &blocked],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

async fn progress(tx: &Transaction<'_>, thread_id: i32) -> Result<ThreadProgress, ApiError> {
    let row = tx
        .query_one(
            "SELECT id,status,issues_remaining,next_unread_issue_id,reading_progress,last_rating
         FROM threads WHERE id=$1",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    Ok(ThreadProgress {
        thread_id: row.get(0),
        status: row.get(1),
        issues_remaining: row.get(2),
        next_unread_issue_id: row.get(3),
        reading_progress: row.get(4),
        last_rating: row.get(5),
    })
}

/// One Roll-offer rating intent, resolved before the shared transaction began.
struct RollOfferEffects<'a> {
    thread_id: i32,
    issue_id: i32,
    rating: f64,
    remaining: i32,
    idempotency_key: &'a str,
}

/// Apply the Roll completion effects for one offer rating inside the caller's
/// transaction.
///
/// This is the same writer composition the Roll offer command uses: the die
/// steps through the durable dice writer, so the ladder, the queue placement
/// and the rating event all commit or all roll back together. Eligibility is
/// only consulted to decide where a below-threshold rating seats the series; it
/// never gates the rating itself (#4453).
///
/// Returns the die after the step and the id of the roll event that offered
/// this exact issue, when one is recorded.
async fn apply_roll_offer_effects(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    effects: &RollOfferEffects<'_>,
    placement_is_manual: bool,
) -> Result<(i32, Option<i32>), ApiError> {
    // Step the die first: this is the durable dice command, and its returned
    // `die_after` is the die the queue placement below must bound against.
    let dice_key = format!(
        "roll-rating-{}-{}",
        effects.thread_id, effects.idempotency_key
    );
    let stepped = dice_mutation::persist_in_transaction(
        tx,
        user,
        &dice_key,
        &DiceCommand::RollRating {
            thread_id: effects.thread_id,
            issue_id: effects.issue_id,
            rating: effects.rating,
        },
    )
    .await?
    .die_after;

    // Link the rating back to the roll that offered this exact issue, so the
    // completion can be traced to its offer instead of to any roll of the
    // same series.
    let offered_by: Option<i32> = tx
        .query_opt(
            "SELECT id FROM events
             WHERE user_id=$1 AND type='roll' AND issue_id=$2
             ORDER BY timestamp DESC, id DESC LIMIT 1",
            &[&user.id(), &effects.issue_id],
        )
        .await
        .map_err(db::query_error)?
        .map(|row| row.get(0));

    // Every queue writer for this reader takes the queue advisory lock before
    // it reads or rewrites positions, so a concurrent move or shuffle cannot
    // interleave with this placement.
    queue::lock_queue(tx, user.id()).await?;
    if effects.remaining == 0 {
        // A finished series leaves the pool behind the rest of the queue.
        queue::move_to_back(tx, user.id(), effects.thread_id).await?;
    } else if effects.rating >= ROLL_RATING_THRESHOLD {
        // A good rating moves the series to the front.
        queue::move_to_rank(tx, user.id(), effects.thread_id, 1).await?;
    } else if !placement_is_manual {
        // A below-threshold rating seats the series just beyond the die-sized
        // roll pool, so the next roll does not immediately repeat it. A reader
        // who placed this series by hand keeps that placement (#3638).
        let excluded = effective_roll_exclusions(tx, user).await?;
        let eligible = eligible_thread_ids(tx, user).await?;
        if let Some(rank) = queue::safe_position_rank(
            tx,
            user.id(),
            effects.thread_id,
            stepped,
            &excluded,
            &eligible,
        )
        .await?
        {
            queue::move_to_rank(tx, user.id(), effects.thread_id, rank).await?;
        }
    }

    Ok((stepped, offered_by))
}

/// The complete thread exclusion set the next roll would apply (issue #3696):
/// this session's snoozes and skips, durable cross-session snooze backoff, and
/// durable "Remove from Queue" exclusions.
///
/// This is the same union `comic_pile.queue.derive_effective_roll_excluded_thread_ids`
/// builds for the legacy rating path and the native Skip writer builds for its
/// pool, so a below-threshold rating counts exactly the series the next roll
/// cannot select.
async fn effective_roll_exclusions(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
) -> Result<Vec<i32>, ApiError> {
    let session = tx
        .query_opt(
            "SELECT COALESCE(snoozed_thread_ids::text, '[]'),
                    COALESCE(skipped_thread_ids::text, '[]') FROM sessions
             WHERE user_id=$1 AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let mut excluded: Vec<i32> = Vec::new();
    let mut seen: HashSet<i32> = HashSet::new();
    if let Some(session) = session {
        // These columns are SQLAlchemy JSON, not PostgreSQL integer arrays.
        // Decode their stored JSON text, including null as an empty list.
        let snoozed: Vec<i32> =
            serde_json::from_str(&session.get::<_, String>(0)).map_err(|e| {
                tracing::debug!(error = ?e, "preserved underlying error before mapping");
                ApiError::Internal("Invalid snoozed threads".into())
            })?;
        let skipped: Vec<i32> =
            serde_json::from_str(&session.get::<_, String>(1)).map_err(|e| {
                tracing::debug!(error = ?e, "preserved underlying error before mapping");
                ApiError::Internal("Invalid skipped threads".into())
            })?;
        for thread_id in snoozed.into_iter().chain(skipped) {
            if seen.insert(thread_id) {
                excluded.push(thread_id);
            }
        }
    }
    for thread_id in roll_exclusions::durable_snoozed(tx, user.id()).await? {
        if seen.insert(thread_id) {
            excluded.push(thread_id);
        }
    }
    for thread_id in roll_exclusions::excluded_status_ids(tx, user.id()).await? {
        if seen.insert(thread_id) {
            excluded.push(thread_id);
        }
    }
    Ok(excluded)
}

/// The Option E eligible thread ids for one reader, resolved inside the caller's
/// transaction so placement uses the same authority the next Roll offer draws
/// from. Sorted so the SQL parameter array is deterministic.
async fn eligible_thread_ids(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
) -> Result<Vec<i32>, ApiError> {
    let validated = option_inputs::load_validated_contained_in_transaction(tx, user).await?;
    let mut ids: Vec<i32> = queue::evaluated_eligible_ids(&validated)?
        .into_iter()
        .collect();
    ids.sort_unstable();
    Ok(ids)
}

/// One owned thread's queue position and derived blocked flag before an action.
#[derive(Clone, Copy)]
struct ThreadPreState {
    queue_position: i32,
    is_blocked: bool,
}

/// Capture every owned thread's queue position and derived blocked flag.
///
/// Undo restores the queue and blocking changes a rating caused, so the delta
/// snapshot records only the pre-action values that actually differ afterwards.
async fn thread_pre_states(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
) -> Result<HashMap<i32, ThreadPreState>, ApiError> {
    let rows = tx
        .query(
            "SELECT id, queue_position, is_blocked FROM threads WHERE user_id=$1",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    Ok(rows
        .into_iter()
        .map(|row| {
            (
                row.get(0),
                ThreadPreState {
                    queue_position: row.get(1),
                    is_blocked: row.get(2),
                },
            )
        })
        .collect())
}

/// Capture the active reading session's pre-action state for undo.
///
/// The snapshot stores the session fields a rating can change (the pending Roll
/// offer, snoozes, die and ephemeral mode state) so the existing Python undo
/// service can restore them exactly. A direct rating without an active session
/// has no session-keyed undo record, matching the retired Python writer.
async fn active_session_pre_state(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
) -> Result<Option<(i32, Value)>, ApiError> {
    let row = tx
        .query_opt(
            "SELECT id, start_die, manual_die, pending_thread_id, pending_issue_id,
                    pending_thread_updated_at::text, ended_at::text,
                    COALESCE(snoozed_thread_ids::text, 'null'),
                    predicted_bandwidth, active_bandwidth, bandwidth_confidence,
                    bandwidth_source, bandwidth_version, bandwidth_updated_at::text,
                    active_intent, predicted_intent, intent_confidence,
                    intent_source, intent_version
             FROM sessions
             WHERE user_id=$1 AND ended_at IS NULL
             ORDER BY started_at DESC, id DESC LIMIT 1",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let Some(row) = row else {
        return Ok(None);
    };
    let snoozed: Value = row
        .get::<_, Option<String>>(7)
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or(Value::Null);
    let session_state = json!({
        "start_die": row.get::<_, i32>(1),
        "manual_die": row.get::<_, Option<i32>>(2),
        "pending_thread_id": row.get::<_, Option<i32>>(3),
        "pending_issue_id": row.get::<_, Option<i32>>(4),
        "pending_thread_updated_at": row.get::<_, Option<String>>(5),
        "ended_at": row.get::<_, Option<String>>(6),
        "snoozed_thread_ids": snoozed,
        "predicted_bandwidth": row.get::<_, Option<String>>(8),
        "active_bandwidth": row.get::<_, Option<String>>(9),
        "bandwidth_confidence": row.get::<_, Option<f64>>(10),
        "bandwidth_source": row.get::<_, Option<String>>(11),
        "bandwidth_version": row.get::<_, Option<String>>(12),
        "bandwidth_updated_at": row.get::<_, Option<String>>(13),
        "active_intent": row.get::<_, Option<String>>(14),
        "predicted_intent": row.get::<_, Option<String>>(15),
        "intent_confidence": row.get::<_, Option<f64>>(16),
        "intent_source": row.get::<_, Option<String>>(17),
        "intent_version": row.get::<_, Option<String>>(18),
    });
    Ok(Some((row.get(0), session_state)))
}

/// One rating's bounded pre-action undo payload.
struct RatingSnapshot<'a> {
    event_id: i32,
    session_id: i32,
    thread_id: i32,
    thread_state: Value,
    issue_state: Value,
    pre_positions: &'a HashMap<i32, ThreadPreState>,
    session_state: Value,
    pre_die: i32,
}

/// Persist one bounded pre-action undo delta for an issue rating.
///
/// This is the native counterpart of the retired Python rate writer's
/// `snapshot_thread_states` call. The payload is the version-two compact delta
/// the undo service consumes: the rated thread's changed fields, the rated
/// issue's preimage, and only the queue/blocked rows that actually changed.
async fn insert_rating_snapshot(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    snapshot: RatingSnapshot<'_>,
) -> Result<(), ApiError> {
    let after = thread_pre_states(tx, user).await?;
    let mut queue_changes = serde_json::Map::new();
    let mut blocked_changes = serde_json::Map::new();
    for (id, before) in snapshot.pre_positions {
        let Some(now) = after.get(id) else { continue };
        if before.queue_position != now.queue_position {
            queue_changes.insert(id.to_string(), json!(before.queue_position));
        }
        if before.is_blocked != now.is_blocked {
            blocked_changes.insert(id.to_string(), json!(before.is_blocked));
        }
    }

    let mut states = serde_json::Map::new();
    states.insert("_version".into(), json!(2));
    let mut rated = snapshot.thread_state;
    if let Some(object) = rated.as_object_mut() {
        object.insert("issue_changes".into(), json!([snapshot.issue_state]));
    }
    states.insert(snapshot.thread_id.to_string(), rated);
    if !queue_changes.is_empty() {
        states.insert("_queue_changes".into(), Value::Object(queue_changes));
    }
    if !blocked_changes.is_empty() {
        states.insert("_blocked_changes".into(), Value::Object(blocked_changes));
    }
    let mut session_state = snapshot.session_state;
    session_state["current_die"] = json!(snapshot.pre_die);
    tx.execute(
        "INSERT INTO snapshots
         (session_id,event_id,thread_states,session_state,created_at,description,snapshot_kind,schema_version)
         VALUES ($1,$2,$3::text::json,$4::text::json,NOW(),'After rating','delta',2)",
        &[
            &snapshot.session_id,
            &snapshot.event_id,
            &Value::Object(states).to_string(),
            &session_state.to_string(),
        ],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

/// Apply the exact issue action inside an existing owner-serialized transaction.
///
/// A `direct` action only advances the issue and its thread progress. A
/// `roll_offer` action additionally applies the Roll completion effects the
/// legacy `/v1/rate/` route carried: the die steps through the durable dice
/// writer, the series is repositioned in the queue, and the rating event links
/// back to the originating offer event. Eligibility never re-tests the action
/// itself (#4453); it only decides where a low rating seats the series.
pub(crate) async fn persist(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    issue_id: i32,
    request: &IssueReadRateRequest,
) -> Result<IssueReadRateResponse, ApiError> {
    validate(request)?;
    let source = rating_source(request)?;
    // This must be the first DB statement, consistent with the Rust dice writer.
    tx.query_one(
        "SELECT pg_advisory_xact_lock($1::bigint)",
        &[&(user.id() as i64)],
    )
    .await
    .map_err(db::query_error)?;

    let payload = json!({
        "issue_id": issue_id,
        "status": request.status,
        "rating": request.rating,
        "source": source,
    });
    // Lock the owner thread before the issue; owner transfers and concurrent
    // progress writers must not escape the ownership check. The manual-placement
    // flag rides along on the already-locked row: a below-threshold Roll rating
    // must not demote a placement the reader chose by hand (#3638).
    let owner = tx
        .query_opt(
            "SELECT t.id, t.queue_position_is_manual,
                    t.issues_remaining, t.last_rating, t.last_activity_at::text,
                    t.total_issues, t.next_unread_issue_id, t.reading_progress,
                    t.status
             FROM threads t
             JOIN issues i ON i.thread_id=t.id
             WHERE i.id=$1 AND t.user_id=$2 FOR UPDATE OF t,i",
            &[&issue_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError::NotFound("Issue not found".into()))?;
    let thread_id: i32 = owner.get(0);
    let placement_is_manual: bool = owner.get(1);
    let thread_pre_state = json!({
        "issues_remaining": owner.get::<_, i32>(2),
        "last_rating": owner.get::<_, Option<f64>>(3),
        "last_activity_at": owner.get::<_, Option<String>>(4),
        "total_issues": owner.get::<_, Option<i32>>(5),
        "next_unread_issue_id": owner.get::<_, Option<i32>>(6),
        "reading_progress": owner.get::<_, Option<String>>(7),
        "queue_position_is_manual": placement_is_manual,
        "status": owner.get::<_, String>(8),
        "uses_issue_tracking": owner.get::<_, Option<i32>>(5).is_some(),
    });

    // Replays, including a lost response to a no-op, return their original receipt.
    // Same user/key with a different issue or payload is a conflict.
    let existing = tx
        .query_opt(
            "SELECT context::text FROM events
         WHERE user_id=$1 AND context->>'issue_command_key'=$2
         ORDER BY id DESC LIMIT 1",
            &[&user.id(), &request.idempotency_key],
        )
        .await
        .map_err(db::query_error)?;
    if let Some(row) = existing {
        let saved: String = row.get(0);
        let context: Value = serde_json::from_str(&saved).map_err(|e| {
            tracing::debug!(error = ?e, "preserved underlying error before mapping");
            ApiError::Internal("Invalid stored issue receipt".into())
        })?;
        if context.get("issue_command_payload") != Some(&payload) {
            return Err(ApiError::Conflict(
                "Idempotency key reused for different action".into(),
            ));
        }
        let receipt = context
            .get("issue_command_receipt")
            .cloned()
            .ok_or_else(|| ApiError::Internal("Missing stored issue receipt".into()))?;
        let mut result: IssueReadRateResponse = serde_json::from_value(receipt).map_err(|e| {
            tracing::debug!(error = ?e, "preserved underlying error before mapping");
            ApiError::Internal("Invalid stored issue receipt".into())
        })?;
        result.replayed = true;
        return Ok(result);
    }

    let issue = tx
        .query_one(
            "SELECT status, issue_number, position, read_at::text, catalog_issue_id
             FROM issues
             WHERE id=$1 AND thread_id=$2 FOR UPDATE",
            &[&issue_id, &thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let old_status: String = issue.get(0);
    let issue_number: String = issue.get(1);
    let issue_state = json!({
        "id": issue_id,
        "number": issue_number,
        "status": old_status,
        "read_at": issue.get::<_, Option<String>>(3),
        "position": issue.get::<_, i32>(2),
        "catalog_issue_id": issue.get::<_, Option<i64>>(4),
    });

    // Capture the pre-action undo payload before any read/progress/queue write.
    // A direct rating outside an active session has no session-keyed undo row,
    // matching the retired Python writer.
    let pre_session = active_session_pre_state(tx, user).await?;
    let pre_positions = if pre_session.is_some() {
        Some(thread_pre_states(tx, user).await?)
    } else {
        None
    };
    // Mirror `get_current_die_for_session`: an explicit manual die wins over the
    // event-derived ladder, so the undo event records the die the reader saw.
    // Resolve the fallback lazily so a manual-die session does not pay for an
    // unnecessary event query.
    let pre_die = match &pre_session {
        Some((_, state)) => Some(match state["manual_die"].as_i64() {
            Some(die) => die as i32,
            None => dice_state::current_die(tx, user).await?,
        }),
        None => None,
    };
    let old_rating_row = tx
        .query_opt(
            "SELECT rating FROM events
         WHERE user_id=$1 AND issue_id=$2 AND type='rate' AND rating IS NOT NULL
         ORDER BY timestamp DESC,id DESC LIMIT 1",
            &[&user.id(), &issue_id],
        )
        .await
        .map_err(db::query_error)?;
    let old_rating: Option<f64> = old_rating_row.map(|row| row.get(0));
    let newly_read = request.status.as_deref() == Some("read") && old_status != "read";
    let newly_unread = request.status.as_deref() == Some("unread") && old_status == "read";
    let status_changed = newly_read || newly_unread;
    let requested_rating = request.rating.or(if newly_read {
        Some(DEFAULT_NEW_READ_RATING)
    } else {
        None
    });
    let rating_changed = requested_rating.is_some_and(|rating| Some(rating) != old_rating);
    let final_rating = requested_rating.or(old_rating);

    // Track die_after and source_roll_event_id for roll_offer source
    let mut die_after: Option<i32> = None;
    let mut source_roll_event_id: Option<i32> = None;

    if newly_read {
        tx.execute(
            "UPDATE issues SET status='read', read_at=NOW() WHERE id=$1 AND thread_id=$2",
            &[&issue_id, &thread_id],
        )
        .await
        .map_err(db::query_error)?;
    } else if newly_unread {
        tx.execute(
            "UPDATE issues SET status='unread', read_at=NULL WHERE id=$1 AND thread_id=$2",
            &[&issue_id, &thread_id],
        )
        .await
        .map_err(db::query_error)?;
    }

    if status_changed || rating_changed {
        let count_row = tx
            .query_one(
                "SELECT count(*)::int,
                (SELECT id FROM issues WHERE thread_id=$1 AND status='unread'
                 ORDER BY position,id LIMIT 1)
             FROM issues WHERE thread_id=$1 AND status='unread'",
                &[&thread_id],
            )
            .await
            .map_err(db::query_error)?;
        let remaining: i32 = count_row.get(0);
        let next_id: Option<i32> = count_row.get(1);
        let rating_for_thread = if rating_changed {
            requested_rating
        } else {
            None
        };

        if source == ROLL_OFFER_SOURCE {
            // `validate` rejects a Roll offer action without a rating, so the
            // effective rating is always resolved here.
            let rating_value = requested_rating.unwrap_or(DEFAULT_NEW_READ_RATING);
            let effects = RollOfferEffects {
                thread_id,
                issue_id,
                rating: rating_value,
                remaining,
                idempotency_key: &request.idempotency_key,
            };
            let (stepped, offered_by) =
                apply_roll_offer_effects(tx, user, &effects, placement_is_manual).await?;
            die_after = Some(stepped);
            source_roll_event_id = offered_by;
        } else if status_changed && remaining > 0 {
            // Direct source: existing logic for reactivating completed series
            tx.execute(
                "UPDATE threads SET queue_position = (
                     SELECT COALESCE(MAX(other.queue_position), 0) + 1
                     FROM threads other
                     WHERE other.user_id = $1
                       AND other.status = 'active'
                       AND other.queue_position >= 1
                       AND other.id <> $2
                 )
                 WHERE id = $2 AND status = 'completed' AND queue_position < 1",
                &[&user.id(), &thread_id],
            )
            .await
            .map_err(db::query_error)?;
        }

        tx.execute(
            "UPDATE threads SET
                 issues_remaining = CASE WHEN $2 THEN $3 ELSE issues_remaining END,
                 next_unread_issue_id = CASE WHEN $2 THEN $4 ELSE next_unread_issue_id END,
                 reading_progress = CASE WHEN $2
                     THEN CASE WHEN $3=0 THEN 'completed' ELSE 'in_progress' END
                     ELSE reading_progress END,
                 status = CASE WHEN $2 AND status NOT IN ('excluded','inactive')
                     THEN CASE WHEN $3=0 THEN 'completed' ELSE 'active' END ELSE status END,
                 queue_position_is_manual = CASE WHEN $2 AND $3=0 AND status NOT IN ('excluded','inactive')
                     THEN FALSE ELSE queue_position_is_manual END,
                 last_rating = COALESCE($5, last_rating),
                 last_activity_at = NOW()
             WHERE id=$1",
            &[&thread_id, &status_changed, &remaining, &next_id, &rating_for_thread],
        ).await.map_err(db::query_error)?;
    }

    // A direct read/unread changes the prerequisite frontier for this and
    // other owned threads, so refresh the persisted derived flag before the
    // transaction commits. Rating-only corrections cannot change it, but the
    // refresh is a no-op then; keeping it unconditional matches the Python
    // oracle and cannot leave a stale flag behind.
    refresh_blocked_threads(tx, user.id()).await?;

    // An already-read issue with a new rating must create correction history.
    // Every client action records its key, including an otherwise idempotent no-op.
    let event_type = if newly_read || rating_changed {
        "rate"
    } else if newly_unread {
        "issue_unread"
    } else {
        "issue_command"
    };
    let issues_read: i32 = i32::from(newly_read);
    let recorded_rating = if event_type == "rate" {
        final_rating
    } else {
        None
    };
    let context = json!({
        "source": source,
        "issue_command_key": request.idempotency_key,
        "issue_command_payload": payload,
        "source_roll_event_id": source_roll_event_id,
    });
    let event_id: i32 = tx
        .query_one(
            "INSERT INTO events
            (user_id,type,timestamp,thread_id,issue_id,issue_number,
             rating,issues_read,die_after,source_roll_event_id,context)
         VALUES ($1,$2,NOW(),$3,$4,$5,$6,$7,$8,$9,$10::text::json) RETURNING id",
            &[
                &user.id(),
                &event_type,
                &thread_id,
                &issue_id,
                &issue_number,
                &recorded_rating,
                &issues_read,
                &die_after,
                &source_roll_event_id,
                &context.to_string(),
            ],
        )
        .await
        .map_err(db::query_error)?
        .get(0);

    let result = IssueReadRateResponse {
        issue: card(tx, user, issue_id).await?,
        thread: progress(tx, thread_id).await?,
        read_event_created: newly_read,
        rating_event_created: rating_changed,
        replayed: false,
        final_rating,
        die_after,
    };
    let mut saved = context;
    saved["issue_command_receipt"] = serde_json::to_value(&result).map_err(|e| {
        tracing::debug!(error = ?e, "preserved underlying error before mapping");
        ApiError::Internal("Cannot store issue receipt".into())
    })?;
    tx.execute(
        "UPDATE events SET context=$2::text::json WHERE id=$1 AND user_id=$3",
        &[&event_id, &saved.to_string(), &user.id()],
    )
    .await
    .map_err(db::query_error)?;
    // Q17: retire the pending Roll selection when its exact pinned issue is read.
    // Legacy manual picks can pin only the thread, without an issue identity;
    // completing an issue from that same thread must retire that pending pick,
    // while a read from another thread must leave it alone.
    tx.execute(
        "UPDATE sessions SET pending_thread_id=NULL, pending_issue_id=NULL,
             pending_thread_updated_at=NULL
         WHERE user_id=$1 AND ended_at IS NULL
           AND (pending_issue_id=$2 OR (pending_issue_id IS NULL AND pending_thread_id=$3))",
        &[&user.id(), &issue_id, &thread_id],
    )
    .await
    .map_err(db::query_error)?;

    if let (Some((session_id, session_state)), Some(pre_positions), Some(pre_die)) =
        (pre_session, pre_positions, pre_die)
    {
        insert_rating_snapshot(
            tx,
            user,
            RatingSnapshot {
                event_id,
                session_id,
                thread_id,
                thread_state: thread_pre_state,
                issue_state,
                pre_positions: &pre_positions,
                session_state,
                pre_die,
            },
        )
        .await?;
    }
    Ok(result)
}

/// Generated OpenAPI document for the direct issue resource.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(issue_read_rate_documentation, issue_cards_documentation),
    components(schemas(
        IssueReadRateRequest,
        IssueReadRateResponse,
        IssueCardsRequest,
        IssueCardsResponse,
        IssueCard,
        ThreadProgress
    )),
    modifiers(&IssueSecurityAddon)
)]
pub struct IssueApi;

struct IssueSecurityAddon;
impl utoipa::Modify for IssueSecurityAddon {
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

/// Documentation-only operation used to emit the generated PATCH contract.
#[utoipa::path(
    patch,
    path = "/api/v2/issues/{issue_id}",
    tag = "issues",
    params(("issue_id" = i32, Path, description = "Exact owned issue identifier")),
    request_body = IssueReadRateRequest,
    responses(
        (status = 200, description = "Reconciled issue and thread state", body = IssueReadRateResponse),
        (status = 404, description = "Issue not found for this reader"),
        (status = 409, description = "Idempotency key reused for a different action"),
        (status = 422, description = "Invalid status, rating or idempotency key")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn issue_read_rate_documentation() {}

/// Documentation-only operation used to emit the generated batch card contract.
#[utoipa::path(
    post,
    path = "/api/v2/issues/cards",
    tag = "issues",
    request_body = IssueCardsRequest,
    responses(
        (status = 200, description = "Owner-scoped cards in request order", body = IssueCardsResponse),
        (status = 422, description = "Invalid or unbounded issue id list")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn issue_cards_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::StatusCode;
    use utoipa::OpenApi;

    fn request(status: Option<&str>, rating: Option<f64>) -> IssueReadRateRequest {
        IssueReadRateRequest {
            status: status.map(str::to_owned),
            rating,
            idempotency_key: "direct-issue-012345".into(),
            source: None,
        }
    }

    /// One Roll-offer rating: finish the offered issue at `rating` under `key`.
    fn roll_offer(rating: Option<f64>, key: &str) -> IssueReadRateRequest {
        IssueReadRateRequest {
            status: Some("read".into()),
            rating,
            idempotency_key: key.into(),
            source: Some(ROLL_OFFER_SOURCE.into()),
        }
    }

    /// A Roll rating fixture against the real Alembic schema, never a
    /// hand-written approximation. Hold the returned guard through assertions,
    /// since the canonical `public` schema is shared by all native tests.
    async fn roll_offer_fixture(
    ) -> Option<(tokio_postgres::Client, tokio::sync::MutexGuard<'static, ()>)> {
        let state = crate::test_support::test_state(2).await?;
        let guard = crate::test_support::reset_for_test(&state).await;
        let url = crate::test_support::database_url().await;
        let (client, connection) = tokio_postgres::connect(&url, tokio_postgres::NoTls)
            .await
            .expect("canonical test connection");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        // References to next_unread_issue_id and pending_issue_id are linked
        // only after their Issue rows exist: the FKs are not deferrable.
        client
            .batch_execute(
                r#"INSERT INTO users (id, username)
                       VALUES (1, 'roll-reader'), (2, 'other-reader');
                   INSERT INTO threads
                       (id, user_id, title, format, status, issues_remaining,
                        reading_progress, queue_position, queue_position_is_manual,
                        is_blocked, total_issues)
                   VALUES
                       (10,1,'Offered run','Comic','active',2,'in_progress',1,false,false,2),
                       (20,1,'Second run','Comic','active',1,'in_progress',2,false,false,1),
                       (30,1,'Control run','Comic','active',1,'in_progress',3,false,false,1),
                       (40,1,'Blocked run','Comic','active',1,'in_progress',4,false,true,1),
                       (60,2,'Foreign run','Comic','active',1,'in_progress',1,false,false,1);
                   INSERT INTO issues
                       (id, thread_id, issue_number, status, position, created_at)
                   VALUES
                       (101,10,'1','unread',1,now()),
                       (102,10,'2','unread',2,now()),
                       (201,20,'1','unread',1,now()),
                       (301,30,'1','unread',1,now()),
                       (401,40,'1','unread',1,now()),
                       (601,60,'1','unread',1,now());
                   UPDATE threads
                      SET next_unread_issue_id = CASE id
                          WHEN 10 THEN 101 WHEN 20 THEN 201 WHEN 30 THEN 301
                          WHEN 40 THEN 401 WHEN 60 THEN 601 END
                    WHERE id IN (10,20,30,40,60);
                   INSERT INTO sessions
                       (id, user_id, pending_thread_id, pending_issue_id, started_at, start_die)
                   VALUES (1,1,10,101,'2026-10-01T00:00:00Z',6);
                   INSERT INTO dependencies
                       (id,source_issue_id,target_issue_id,origin,created_at)
                   VALUES (1,102,401,'reader',now());
                   INSERT INTO events (user_id,type,rating,die_after)
                   VALUES (1,'rate',4.5,8);
                   INSERT INTO events
                       (user_id,type,session_id,selected_thread_id,die,result,
                        issue_id,issue_number,context)
                   VALUES (1,'roll',1,10,6,1,101,'1','{}'::json);"#,
            )
            .await
            .expect("seed canonical Roll offer fixture");
        Some((client, guard))
    }

    /// Queue positions of one reader's owned threads in id order.
    async fn queue_positions(client: &tokio_postgres::Client, ids: &[i32]) -> Vec<i32> {
        let rows = client
            .query(
                "SELECT id,queue_position FROM threads
                 WHERE id = ANY($1::int[]) ORDER BY id",
                &[&ids],
            )
            .await
            .unwrap();
        rows.iter().map(|row| row.get(1)).collect()
    }

    /// The die the latest stored outcome projects to.
    async fn current_die(client: &tokio_postgres::Client, user_id: i32) -> i32 {
        client
            .query_one(
                "SELECT COALESCE(
                    (SELECT die_after FROM events
                     WHERE user_id=$1
                       AND die_after IN (2,4,6,8,10,12,20,30,50,100)
                     ORDER BY timestamp DESC, id DESC LIMIT 1), 6)",
                &[&user_id],
            )
            .await
            .unwrap()
            .get(0)
    }

    #[test]
    fn validates_status_rating_and_idempotency_without_truncating() {
        for rating in [0.5, 3.5, 5.0] {
            assert!(validate(&request(Some("read"), Some(rating))).is_ok());
        }
        for rating in [0.75, 5.25, -0.5, 0.0, f64::NAN, f64::INFINITY] {
            assert!(validate(&request(Some("read"), Some(rating))).is_err());
        }
        assert!(validate(&request(Some("unread"), None)).is_ok());
        assert!(validate(&request(None, Some(4.5))).is_ok());
        assert!(validate(&request(Some("unknown"), None)).is_err());
        assert!(validate(&request(None, None)).is_err());
        let mut bad = request(Some("read"), None);
        bad.idempotency_key = "short".into();
        assert!(validate(&bad).is_err());
        assert!(validate_cards(&IssueCardsRequest {
            issue_ids: vec![1, 2]
        })
        .is_ok());
        assert!(validate_cards(&IssueCardsRequest { issue_ids: vec![] }).is_err());
        assert!(validate_cards(&IssueCardsRequest {
            issue_ids: vec![1; MAX_CARD_ISSUES + 1]
        })
        .is_err());
        assert!(validate_cards(&IssueCardsRequest { issue_ids: vec![0] }).is_err());
    }

    #[tokio::test]
    async fn direct_read_is_owner_scoped_and_does_not_touch_roll_or_queue() {
        let _admin = crate::test_support::required_test_admin_url();
        let url = crate::test_support::database_url().await;
        let _state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let _db = crate::test_support::reset_for_test(&_state).await;
        let (mut first, connection) = tokio_postgres::connect(&url, tokio_postgres::NoTls)
            .await
            .expect("disposable Postgres");
        tokio::spawn(async move {
            let _ = connection.await;
        });
        first
            .batch_execute(r#"INSERT INTO users (id, username) VALUES (1, 'reader-1'), (2, 'reader-2');
                 INSERT INTO threads
                     (id, user_id, title, format, status, issues_remaining,
                      next_unread_issue_id, reading_progress, last_rating,
                      queue_position, queue_position_is_manual,
                      last_activity_at, is_blocked)
                 VALUES
                     (10, 1, 'Excluded run', 'Comic', 'excluded', 3, NULL,
                      'in_progress', 4.0, 0, true, NULL, false),
                     (20, 2, 'Private run', 'Comic', 'active', 1, NULL,
                      'in_progress', NULL, 1, false, NULL, false),
                     (30, 1, 'Dependent run', 'Comic', 'active', 1, NULL,
                      'in_progress', NULL, 2, false, NULL, true),
                     (40, 1, 'Cbl control run', 'Comic', 'active', 1, NULL,
                      'in_progress', NULL, 3, false, NULL, false),
                     (50, 1, 'Finished run', 'Comic', 'completed', 0, NULL,
                      'completed', NULL, 0, false, NULL, false);
                 INSERT INTO issues
                     (id, thread_id, issue_number, status, position, read_at, created_at)
                 VALUES
                     (101, 10, '1', 'unread', 1, NULL, now()),
                     (102, 10, '2', 'unread', 2, NULL, now()),
                     (110, 10, '10', 'unread', 10, NULL, now()),
                     (201, 20, '1', 'unread', 1, NULL, now()),
                     (301, 30, '1', 'unread', 1, NULL, now()),
                     (401, 40, '1', 'unread', 1, NULL, now()),
                     (501, 50, '1', 'read', 1, NOW(), now());
                 UPDATE threads SET next_unread_issue_id = 101 WHERE id = 10;
                 UPDATE threads SET next_unread_issue_id = 201 WHERE id = 20;
                 UPDATE threads SET next_unread_issue_id = 301 WHERE id = 30;
                 UPDATE threads SET next_unread_issue_id = 401 WHERE id = 40;
                 INSERT INTO dependencies
                     (id, created_at, source_issue_id, target_issue_id, note)
                 VALUES
                     (1, now(), 102, 301, NULL),
                     (2, now(), 101, 401, 'cbl-order:legacy-materialization');
                 INSERT INTO sessions
                     (id, user_id, started_at, start_die, pending_thread_id,
                      pending_issue_id, pending_thread_updated_at, manual_die, ended_at)
                 VALUES (1, 1, now(), 6, 10, 101, NULL, 12, NULL);
                 INSERT INTO external_identities
                     (id, provider, entity_type, external_id, metadata_json,
                      created_at, updated_at)
                 VALUES (50, 'comicvine', 'issue', '4000-42',
                         '{"image":{"medium_url":"https://comicvine.example/covers/issue10.jpg"}}'::json,
                         now(), now()),
                        (51, 'comicvine', 'issue', '4000-43',
                         '{"primary_image":"https://comicvine.example/covers/issue2.jpg"}'::json,
                         now(), now()),
                        (52, 'comicvine', 'issue', '4000-44',
                         '{"image":{"super_url":"https://comicvine.example/covers/dependent.jpg"}}'::json,
                         now(), now());
                 INSERT INTO issue_external_identity_mappings
                     (id, issue_id, external_identity_id, status, evidence_json,
                      created_at, updated_at)
                 VALUES (500, 110, 50, 'confirmed', '{}'::json, now(), now()),
                        (501, 102, 51, 'confirmed', '{}'::json, now(), now()),
                        (502, 301, 52, 'confirmed', '{}'::json, now(), now());"#)
            .await
            .expect("seed canonical schema");
        let user = AuthenticatedUser::for_test(1);
        let mut command = request(Some("read"), Some(4.5));
        let tx = first.transaction().await.unwrap();
        let read = persist(&tx, user, 110, &command).await.unwrap();
        tx.commit().await.unwrap();
        assert!(read.read_event_created);
        assert!(read.rating_event_created);
        // A direct read never touches the Roll die ladder: that state belongs
        // to the Roll flow (issue #3581).
        assert_eq!(read.die_after, None);
        assert_eq!(read.issue.issue_number, "10");
        assert_eq!(read.issue.status, "read");
        assert_eq!(read.issue.rating, Some(4.5));
        assert!(read.issue.has_confirmed_identity);
        assert_eq!(read.issue.comicvine_issue_id.as_deref(), Some("4000-42"));
        assert_eq!(
            read.issue.cover_image_url.as_deref(),
            Some("https://comicvine.example/covers/issue10.jpg")
        );
        assert_eq!(read.thread.status, "excluded");
        assert_eq!(read.thread.issues_remaining, 2);
        assert_eq!(read.thread.next_unread_issue_id, Some(101));
        assert_eq!(
            first
                .query_one("SELECT status FROM issues WHERE id=102", &[])
                .await
                .unwrap()
                .get::<_, String>(0),
            "unread"
        );
        let still_pending = first
            .query_one(
                "SELECT pending_issue_id,manual_die FROM sessions WHERE id=1",
                &[],
            )
            .await
            .unwrap();
        assert_eq!(still_pending.get::<_, i32>(0), 101);
        assert_eq!(still_pending.get::<_, i32>(1), 12);
        let queue = first
            .query_one(
                "SELECT queue_position,queue_position_is_manual FROM threads WHERE id=10",
                &[],
            )
            .await
            .unwrap();
        assert_eq!(queue.get::<_, i32>(0), 0);
        assert!(queue.get::<_, bool>(1));

        let tx = first.transaction().await.unwrap();
        let replay = persist(&tx, user, 110, &command).await.unwrap();
        tx.commit().await.unwrap();
        assert!(replay.replayed);
        assert_eq!(replay.issue, read.issue);
        assert_eq!(replay.thread, read.thread);
        let count: i64 = first
            .query_one("SELECT COUNT(*) FROM events WHERE user_id=1", &[])
            .await
            .unwrap()
            .get(0);
        assert_eq!(count, 1);
        command.rating = Some(3.5);
        let tx = first.transaction().await.unwrap();
        let collision = persist(&tx, user, 110, &command).await.unwrap_err();
        tx.rollback().await.unwrap();
        assert_eq!(collision.status(), StatusCode::CONFLICT);

        let correction = IssueReadRateRequest {
            status: None,
            rating: Some(3.5),
            idempotency_key: "direct-issue-correction-01".into(),
            source: None,
        };
        let tx = first.transaction().await.unwrap();
        let corrected = persist(&tx, user, 110, &correction).await.unwrap();
        tx.commit().await.unwrap();
        assert!(!corrected.read_event_created);
        assert!(corrected.rating_event_created);
        assert_eq!(corrected.issue.rating, Some(3.5));
        assert_eq!(corrected.thread.status, "excluded");
        assert_eq!(
            first
                .query_one("SELECT COUNT(*) FROM events WHERE type='rate'", &[])
                .await
                .unwrap()
                .get::<_, i64>(0),
            2
        );

        // The persisted derived `threads.is_blocked` flag is what native Skip
        // and the legacy queue filter on. A direct read must clear it for every
        // dependent thread; a direct unread must set it again.
        let tx = first.transaction().await.unwrap();
        let unblocked = persist(
            &tx,
            user,
            102,
            &IssueReadRateRequest {
                status: Some("read".into()),
                rating: None,
                idempotency_key: "direct-issue-unblock-01".into(),
                source: None,
            },
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert!(unblocked.read_event_created);
        assert!(
            !first
                .query_one("SELECT is_blocked FROM threads WHERE id=30", &[])
                .await
                .unwrap()
                .get::<_, bool>(0),
            "reading the prerequisite must clear the dependent thread's flag"
        );
        // The undo delta records the pre-action blocked flag so undo re-blocks
        // the dependent series.
        let blocked_snapshot = first
            .query_one(
                "SELECT thread_states::text, session_state::text FROM snapshots
                 WHERE session_id=1 ORDER BY id DESC LIMIT 1",
                &[],
            )
            .await
            .unwrap();
        let blocked_states: Value =
            serde_json::from_str(&blocked_snapshot.get::<_, String>(0)).unwrap();
        assert_eq!(blocked_states["_blocked_changes"]["30"], true);
        let blocked_session: Value =
            serde_json::from_str(&blocked_snapshot.get::<_, String>(1)).unwrap();
        assert_eq!(
            blocked_session["current_die"], 12,
            "the undo event must record the session manual die"
        );
        let tx = first.transaction().await.unwrap();
        let reblocked = persist(
            &tx,
            user,
            102,
            &IssueReadRateRequest {
                status: Some("unread".into()),
                rating: None,
                idempotency_key: "direct-issue-reblock-01".into(),
                source: None,
            },
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert!(!reblocked.read_event_created);
        assert!(
            first
                .query_one("SELECT is_blocked FROM threads WHERE id=30", &[])
                .await
                .unwrap()
                .get::<_, bool>(0),
            "marking the prerequisite unread must restore the blocked flag"
        );
        assert!(
            !first
                .query_one("SELECT is_blocked FROM threads WHERE id=40", &[])
                .await
                .unwrap()
                .get::<_, bool>(0),
            "cbl-order edges must never contribute to the derived blocked flag"
        );

        // A completed series at position 0 is a reachable state (for example a
        // restored fully-read run). A direct unread reactivates it, and the
        // invariant `active => queue_position >= 1` means it must join the
        // queue behind the reader's existing positions without reordering them.
        let tx = first.transaction().await.unwrap();
        let reactivated = persist(
            &tx,
            user,
            501,
            &IssueReadRateRequest {
                status: Some("unread".into()),
                rating: None,
                idempotency_key: "direct-issue-reactivate-01".into(),
                source: None,
            },
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(reactivated.thread.status, "active");
        assert_eq!(reactivated.thread.issues_remaining, 1);
        let reactivated_queue = first
            .query_one("SELECT status,queue_position FROM threads WHERE id=50", &[])
            .await
            .unwrap();
        assert_eq!(reactivated_queue.get::<_, String>(0), "active");
        // max_queue_position(user 1) is 3 (threads 30 and 40); the reactivated
        // series appends at 4 and nothing else moves.
        assert_eq!(reactivated_queue.get::<_, i32>(1), 4);
        let positions: Vec<(i32, i32)> = first
            .query(
                "SELECT id,queue_position FROM threads WHERE user_id=1 AND id IN (30,40) ORDER BY id",
                &[],
            )
            .await
            .unwrap()
            .iter()
            .map(|row| (row.get(0), row.get(1)))
            .collect();
        assert_eq!(positions, vec![(30, 2), (40, 3)]);
        // Canonical active-queue predicate plus the native Skip pool gate
        // (`status='active' AND queue_position>=1 AND is_blocked=false`).
        let eligible: i64 = first
            .query_one(
                "SELECT COUNT(*) FROM threads
                 WHERE id=50 AND status='active' AND queue_position>=1 AND is_blocked=false",
                &[],
            )
            .await
            .unwrap()
            .get(0);
        assert_eq!(
            eligible, 1,
            "a reactivated completed series must regain queue membership"
        );

        let tx = first.transaction().await.unwrap();
        let foreign = persist(&tx, user, 201, &request(Some("read"), None))
            .await
            .unwrap_err();
        tx.rollback().await.unwrap();
        assert_eq!(foreign.status(), StatusCode::NOT_FOUND);
        let tx = first.transaction().await.unwrap();
        let unmapped = persist(
            &tx,
            user,
            101,
            &IssueReadRateRequest {
                status: Some("read".into()),
                rating: None,
                idempotency_key: "direct-issue-default-01".into(),
                source: None,
            },
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(unmapped.issue.rating, Some(3.5));
        assert_eq!(unmapped.issue.mapping_state, "unmapped");
        assert_eq!(unmapped.issue.cover_image_url, None);
        assert_eq!(unmapped.thread.next_unread_issue_id, Some(102));
        // Reading the exact pending issue retires that offer (Q17); the earlier
        // different manual read above left it untouched.
        let cleared = first
            .query_one(
                "SELECT pending_thread_id,pending_issue_id FROM sessions WHERE id=1",
                &[],
            )
            .await
            .unwrap();
        assert_eq!(
            cleared.get::<_, Option<i32>>(0),
            None,
            "pending thread must clear with its selected issue"
        );
        assert_eq!(cleared.get::<_, Option<i32>>(1), None);

        let bounded = cards(&first, user, &[110, 999_999, 110, 201, 101])
            .await
            .unwrap();
        assert_eq!(
            bounded
                .items
                .iter()
                .map(|card| card.issue_id)
                .collect::<Vec<_>>(),
            vec![110, 101]
        );
        assert_eq!(bounded.items[0].thread_title, "Excluded run");
        assert_eq!(bounded.items[0].rating, Some(3.5));
        assert_eq!(bounded.items[0].mapping_state, "confirmed");
        assert_eq!(
            bounded.items[0].cover_image_url.as_deref(),
            Some("https://comicvine.example/covers/issue10.jpg")
        );
        assert_eq!(bounded.items[1].mapping_state, "unmapped");
        assert_eq!(bounded.items[1].cover_image_url, None);

        // Production regression #4722: confirmed ComicVine mappings may have
        // only primary_image, even though Roll displays that stored artwork.
        // The batch and single-card (direct PATCH response) projections agree.
        let covers = cards(&first, user, &[102, 301]).await.unwrap();
        assert_eq!(covers.items.len(), 2);
        assert_eq!(covers.items[0].mapping_state, "confirmed");
        assert_eq!(
            covers.items[0].cover_image_url.as_deref(),
            Some("https://comicvine.example/covers/issue2.jpg")
        );
        assert_eq!(
            covers.items[1].cover_image_url.as_deref(),
            Some("https://comicvine.example/covers/dependent.jpg")
        );
        let tx = first.transaction().await.unwrap();
        let direct = card(&tx, user, 102).await.unwrap();
        assert_eq!(direct.comicvine_issue_id.as_deref(), Some("4000-43"));
        assert_eq!(direct.cover_image_url, covers.items[0].cover_image_url);
        tx.rollback().await.unwrap();
    }

    #[tokio::test]
    async fn roll_offer_rating_steps_the_die_down_and_moves_the_series_forward() {
        let Some((mut client, _db_guard)) = roll_offer_fixture().await else {
            return;
        };
        let user = AuthenticatedUser::for_test(1);

        let tx = client.transaction().await.unwrap();
        let rated = persist(
            &tx,
            user,
            101,
            &roll_offer(Some(4.5), "roll-offer-high-001"),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();

        // A rating at or above the threshold steps the die down from d8 to d6.
        assert!(rated.read_event_created);
        assert!(rated.rating_event_created);
        assert_eq!(rated.die_after, Some(6));
        assert_eq!(rated.final_rating, Some(4.5));
        assert_eq!(rated.thread.issues_remaining, 1);
        assert_eq!(rated.thread.next_unread_issue_id, Some(102));
        assert_eq!(current_die(&client, 1).await, 6);
        // The series moves to the front and every other row shifts back.
        assert_eq!(
            queue_positions(&client, &[10, 20, 30, 40]).await,
            vec![1, 2, 3, 4]
        );
        // The rating links back to the roll event that offered this exact issue.
        let offering_roll: i32 = client
            .query_one(
                "SELECT id FROM events WHERE type='roll' AND issue_id=101",
                &[],
            )
            .await
            .unwrap()
            .get(0);
        let linked = client
            .query_one(
                "SELECT context->>'source', context->>'source_roll_event_id',
                        source_roll_event_id, die_after
                 FROM events
                 WHERE context->>'issue_command_key'='roll-offer-high-001'",
                &[],
            )
            .await
            .unwrap();
        assert_eq!(linked.get::<_, String>(0), "roll_offer");
        assert_eq!(
            linked.get::<_, Option<String>>(1),
            Some(offering_roll.to_string())
        );
        assert_eq!(linked.get::<_, Option<i32>>(2), Some(offering_roll));
        assert_eq!(linked.get::<_, Option<i32>>(3), Some(6));
        // The pending offer for the exact rated issue is retired, so the next
        // roll is a fresh offer rather than a snooze of the finished series.
        let pending = client
            .query_one(
                "SELECT pending_thread_id,pending_issue_id FROM sessions WHERE id=1",
                &[],
            )
            .await
            .unwrap();
        assert_eq!(pending.get::<_, Option<i32>>(0), None);
        assert_eq!(pending.get::<_, Option<i32>>(1), None);

        // The rating writes the version-two undo delta the Python undo service
        // consumes, so the Roll "Undo rating" action still restores this state.
        let snapshot = client
            .query_one(
                "SELECT thread_states::text, session_state::text, description,
                        snapshot_kind, schema_version, event_id
                 FROM snapshots WHERE session_id=1 ORDER BY id DESC LIMIT 1",
                &[],
            )
            .await
            .unwrap();
        assert_eq!(snapshot.get::<_, String>(2), "After rating");
        assert_eq!(snapshot.get::<_, String>(3), "delta");
        assert_eq!(snapshot.get::<_, i32>(4), 2);
        assert!(snapshot.get::<_, Option<i32>>(5).is_some());
        let states: Value = serde_json::from_str(&snapshot.get::<_, String>(0)).unwrap();
        assert_eq!(states["_version"], 2);
        assert_eq!(states["10"]["issues_remaining"], 2);
        assert_eq!(states["10"]["next_unread_issue_id"], 101);
        assert_eq!(states["10"]["issue_changes"][0]["status"], "unread");
        let session_state: Value = serde_json::from_str(&snapshot.get::<_, String>(1)).unwrap();
        assert_eq!(session_state["current_die"], 8);
        assert_eq!(session_state["pending_issue_id"], 101);

        // An identical retry replays the original receipt and never steps the
        // ladder or the queue twice.
        let tx = client.transaction().await.unwrap();
        let replay = persist(
            &tx,
            user,
            101,
            &roll_offer(Some(4.5), "roll-offer-high-001"),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert!(replay.replayed);
        assert_eq!(replay.die_after, Some(6));
        assert_eq!(replay.issue, rated.issue);
        assert_eq!(current_die(&client, 1).await, 6);
        assert_eq!(
            queue_positions(&client, &[10, 20, 30, 40]).await,
            vec![1, 2, 3, 4]
        );
        // Four events: the seeded die outcome and offer, the dice command that
        // steps the ladder, and the issue event that records the read.
        assert_eq!(
            client
                .query_one("SELECT COUNT(*) FROM events WHERE user_id=1", &[])
                .await
                .unwrap()
                .get::<_, i64>(0),
            4
        );
        // A replayed request must not write a second undo point.
        assert_eq!(
            client
                .query_one("SELECT COUNT(*) FROM snapshots WHERE session_id=1", &[])
                .await
                .unwrap()
                .get::<_, i64>(0),
            1
        );
    }

    #[tokio::test]
    async fn roll_offer_low_rating_steps_the_die_up_and_seats_the_series_last() {
        let Some((mut client, _db_guard)) = roll_offer_fixture().await else {
            return;
        };
        let user = AuthenticatedUser::for_test(1);

        let tx = client.transaction().await.unwrap();
        let rated = persist(
            &tx,
            user,
            201,
            &roll_offer(Some(3.0), "roll-offer-low-0001"),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();

        // A below-threshold rating steps the die up, never down.
        assert_eq!(rated.die_after, Some(10));
        assert_eq!(current_die(&client, 1).await, 10);
        // This was the series' only unread issue, so it is completed and seats
        // behind every other queued series; the low rating never promotes it.
        assert_eq!(rated.thread.issues_remaining, 0);
        assert_eq!(rated.thread.status, "completed");
        assert_eq!(
            queue_positions(&client, &[10, 20, 30, 40]).await,
            vec![1, 4, 2, 3]
        );
        assert_eq!(
            client
                .query_one("SELECT status FROM threads WHERE id=20", &[])
                .await
                .unwrap()
                .get::<_, String>(0),
            "completed"
        );
        // The undo delta records the pre-rating queue positions of every row
        // the rating moved, so undo restores the exact queue order.
        let states: Value = serde_json::from_str(
            &client
                .query_one(
                    "SELECT thread_states::text FROM snapshots
                     WHERE session_id=1 ORDER BY id DESC LIMIT 1",
                    &[],
                )
                .await
                .unwrap()
                .get::<_, String>(0),
        )
        .unwrap();
        assert_eq!(states["_queue_changes"]["20"], 2);
        assert_eq!(states["_queue_changes"]["30"], 3);
        assert_eq!(states["_queue_changes"]["40"], 4);
    }

    #[tokio::test]
    async fn roll_offer_completion_moves_the_series_to_the_back() {
        let Some((mut client, _db_guard)) = roll_offer_fixture().await else {
            return;
        };
        let user = AuthenticatedUser::for_test(1);

        // The last unread issue of the front series, rated above threshold:
        // completion wins over the front move, exactly as the legacy writer
        // ordered it.
        let tx = client.transaction().await.unwrap();
        let rated = persist(
            &tx,
            user,
            101,
            &roll_offer(Some(4.5), "roll-offer-done-001"),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(rated.thread.issues_remaining, 1);
        assert_eq!(rated.die_after, Some(6));
        let tx = client.transaction().await.unwrap();
        let finished = persist(
            &tx,
            user,
            102,
            &roll_offer(Some(4.5), "roll-offer-done-002"),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();

        assert_eq!(finished.thread.issues_remaining, 0);
        assert_eq!(finished.thread.status, "completed");
        assert_eq!(
            finished.thread.reading_progress.as_deref(),
            Some("completed")
        );
        assert_eq!(finished.die_after, Some(4));
        assert_eq!(current_die(&client, 1).await, 4);
        // The finished series sits behind every other queued series, and the
        // remaining positions stay dense.
        assert_eq!(
            queue_positions(&client, &[10, 20, 30, 40]).await,
            vec![4, 1, 2, 3]
        );
        // Completing a series clears its reader placement (#3638).
        assert!(!client
            .query_one(
                "SELECT queue_position_is_manual FROM threads WHERE id=10",
                &[]
            )
            .await
            .unwrap()
            .get::<_, bool>(0));
    }

    #[tokio::test]
    async fn roll_offer_rating_of_a_manually_placed_series_keeps_its_position() {
        let Some((mut client, _db_guard)) = roll_offer_fixture().await else {
            return;
        };
        // A second unread issue keeps the series in play after the first
        // rating, and the reader has placed it by hand.
        client
            .batch_execute(
                "INSERT INTO issues
                     (id,thread_id,issue_number,status,position,created_at)
                 VALUES (302,30,'2','unread',2,now());
                 UPDATE threads
                 SET issues_remaining=2, queue_position_is_manual=true WHERE id=30",
            )
            .await
            .unwrap();
        let user = AuthenticatedUser::for_test(1);

        // The reader placed this series by hand, so a below-threshold rating
        // must not demote it (#3638).
        let tx = client.transaction().await.unwrap();
        let rated = persist(
            &tx,
            user,
            301,
            &roll_offer(Some(2.5), "roll-offer-manual-01"),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(rated.die_after, Some(10));
        assert_eq!(rated.thread.issues_remaining, 1);
        assert_eq!(rated.thread.status, "active");
        assert_eq!(
            queue_positions(&client, &[10, 20, 30, 40]).await,
            vec![1, 2, 3, 4],
            "a manual placement survives a below-threshold Roll rating"
        );
        assert!(
            client
                .query_one(
                    "SELECT queue_position_is_manual FROM threads WHERE id=30",
                    &[]
                )
                .await
                .unwrap()
                .get::<_, bool>(0),
            "the same rating keeps the reader's manual placement recorded"
        );

        // Finishing the series is a different transition: completion seats the
        // series behind the queue and clears the manual placement (#3638).
        let tx = client.transaction().await.unwrap();
        let finished = persist(
            &tx,
            user,
            302,
            &roll_offer(Some(4.5), "roll-offer-manual-02"),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(finished.die_after, Some(8));
        assert_eq!(finished.thread.issues_remaining, 0);
        assert_eq!(finished.thread.status, "completed");
        assert_eq!(
            queue_positions(&client, &[10, 20, 30, 40]).await,
            vec![1, 2, 4, 3]
        );
        assert!(
            !client
                .query_one(
                    "SELECT queue_position_is_manual FROM threads WHERE id=30",
                    &[]
                )
                .await
                .unwrap()
                .get::<_, bool>(0),
            "completing a series clears its reader placement"
        );
    }

    #[tokio::test]
    async fn roll_offer_low_rating_never_repositions_a_blocked_series() {
        let Some((mut client, _db_guard)) = roll_offer_fixture().await else {
            return;
        };
        // A second unread issue keeps the blocked series in play, and that
        // remaining issue carries its own unread prerequisite so the series
        // stays outside the rollable set after the first issue is read. The
        // series is also moved to the front of the queue, so a completion move
        // to the back is observable.
        client
            .batch_execute(
                "INSERT INTO issues
                     (id,thread_id,issue_number,status,position,created_at)
                 VALUES (402,40,'2','unread',2,now());
                 INSERT INTO dependencies
                     (id,source_issue_id,target_issue_id,origin,created_at)
                 VALUES (2,102,402,'reader',now());
                 UPDATE threads SET issues_remaining=2 WHERE id=40;
                 UPDATE threads SET queue_position=1 WHERE id=40;
                 UPDATE threads SET queue_position=2 WHERE id=10;
                 UPDATE threads SET queue_position=3 WHERE id=20;
                 UPDATE threads SET queue_position=4 WHERE id=30;",
            )
            .await
            .unwrap();
        let user = AuthenticatedUser::for_test(1);

        // A blocked series is outside the rollable set, so the below-threshold
        // "seat it beyond the die pool" placement is not computed for it.
        let tx = client.transaction().await.unwrap();
        let low = persist(
            &tx,
            user,
            401,
            &roll_offer(Some(3.5), "roll-offer-block-001"),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(low.die_after, Some(10));
        assert_eq!(low.thread.issues_remaining, 1);
        assert_eq!(low.thread.status, "active");
        assert_eq!(
            queue_positions(&client, &[10, 20, 30, 40]).await,
            vec![2, 3, 4, 1],
            "a below-threshold rating leaves a blocked series where it is"
        );

        // Completing it is a different transition: the finished series leaves
        // the pool behind the rest of the queue.
        let tx = client.transaction().await.unwrap();
        let finished = persist(
            &tx,
            user,
            402,
            &roll_offer(Some(4.5), "roll-offer-block-002"),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert_eq!(finished.die_after, Some(8));
        assert_eq!(finished.thread.issues_remaining, 0);
        assert_eq!(finished.thread.status, "completed");
        assert_eq!(
            queue_positions(&client, &[10, 20, 30, 40]).await,
            vec![1, 2, 3, 4]
        );
    }

    #[tokio::test]
    async fn roll_offer_rating_is_not_gated_by_a_changed_frontier_or_queue() {
        let Some((mut client, _db_guard)) = roll_offer_fixture().await else {
            return;
        };
        let user = AuthenticatedUser::for_test(1);

        // #4453: eligibility decides what Roll offers; it never revokes
        // permission to finish the comic that was offered. Reorder the queue,
        // push this series to the back, block it, snooze it, and drop the
        // pending session offer, then rate the exact offered issue.
        client
            .batch_execute(
                "UPDATE threads SET queue_position=4 WHERE id=10;
                 UPDATE threads SET queue_position=1 WHERE id=30;
                 UPDATE threads SET queue_position=2 WHERE id=20;
                 UPDATE threads SET queue_position=3 WHERE id=40;
                 UPDATE threads SET is_blocked=true WHERE id=10;
                 UPDATE sessions SET pending_thread_id=NULL,pending_issue_id=NULL
                     WHERE id=1;
                 INSERT INTO events
                     (user_id,type,rating,die_after,thread_id)
                     VALUES (1,'rate',4.0,12,10);",
            )
            .await
            .unwrap();

        let tx = client.transaction().await.unwrap();
        let rated = persist(
            &tx,
            user,
            101,
            &roll_offer(Some(4.0), "roll-offer-front-001"),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();

        assert!(rated.read_event_created);
        assert_eq!(rated.issue.status, "read");
        // The die was seeded at d12, so a 4.0 rating steps it down to d10.
        assert_eq!(rated.die_after, Some(10));
        assert_eq!(rated.thread.issues_remaining, 1);
        // Reordering other series must not gate this rating: the exact offered
        // issue still rates, and its own high rating still promotes it to the
        // front of the queue the reader built.
        assert_eq!(
            queue_positions(&client, &[10, 20, 30, 40]).await,
            vec![1, 3, 2, 4]
        );
    }

    #[tokio::test]
    async fn roll_offer_rating_correction_creates_no_new_read() {
        let Some((mut client, _db_guard)) = roll_offer_fixture().await else {
            return;
        };
        let user = AuthenticatedUser::for_test(1);

        let tx = client.transaction().await.unwrap();
        let first = persist(
            &tx,
            user,
            101,
            &roll_offer(Some(4.5), "roll-offer-correct-01"),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert!(first.read_event_created);

        // Correcting the rating of an already-read issue creates correction
        // history, not a second read, and it still carries the Roll completion
        // effects the original rating carried.
        let tx = client.transaction().await.unwrap();
        let corrected = persist(
            &tx,
            user,
            101,
            &roll_offer(Some(2.0), "roll-offer-correct-02"),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();

        assert!(!corrected.read_event_created);
        assert!(corrected.rating_event_created);
        assert_eq!(corrected.final_rating, Some(2.0));
        assert_eq!(corrected.issue.rating, Some(2.0));
        assert_eq!(corrected.issue.status, "read");
        // The ladder stepped up from the corrected low rating (d6 to d8).
        assert_eq!(corrected.die_after, Some(8));
        assert_eq!(current_die(&client, 1).await, 8);
        // The already-read issue was never re-read, so the frontier did not
        // advance again and the series keeps its single remaining issue.
        assert_eq!(corrected.thread.issues_remaining, 1);
        assert_eq!(corrected.thread.next_unread_issue_id, Some(102));
        // The correction is a low rating on a series with unread issues, so it
        // seats the series beyond the die-sized roll pool instead of promoting
        // it: d8 leaves only three rollable series, so the series goes last.
        assert_eq!(
            queue_positions(&client, &[10, 20, 30, 40]).await,
            vec![4, 1, 2, 3]
        );
        // One dice event and one issue event per rating, and no repeated
        // read event for the same issue.
        let counts = client
            .query_one(
                "SELECT
                     (SELECT COUNT(*) FROM events WHERE user_id=1 AND type='rate'),
                     (SELECT COUNT(*) FROM events WHERE user_id=1
                        AND issue_id=101 AND context->>'issue_command_key'
                            LIKE 'roll-offer-correct-%')",
                &[],
            )
            .await
            .unwrap();
        // The seeded die outcome, then two dice events and two issue events.
        assert_eq!(counts.get::<_, i64>(0), 5);
        assert_eq!(counts.get::<_, i64>(1), 2);
    }

    #[tokio::test]
    async fn roll_offer_rating_clears_a_thread_only_manual_pending_pick() {
        let Some((mut client, _db_guard)) = roll_offer_fixture().await else {
            return;
        };
        // The legacy manual-picker route can pin a series without pinning its
        // issue. Its successful read must not resurrect the same pending pick.
        client
            .execute("UPDATE sessions SET pending_issue_id=NULL WHERE id=1", &[])
            .await
            .unwrap();
        let tx = client.transaction().await.unwrap();
        let rated = persist(
            &tx,
            AuthenticatedUser::for_test(1),
            101,
            &roll_offer(Some(4.0), "roll-offer-manual-pending-1"),
        )
        .await
        .unwrap();
        tx.commit().await.unwrap();
        assert!(rated.read_event_created);
        let pending = client
            .query_one(
                "SELECT pending_thread_id,pending_issue_id FROM sessions WHERE id=1",
                &[],
            )
            .await
            .unwrap();
        assert_eq!(pending.get::<_, Option<i32>>(0), None);
        assert_eq!(pending.get::<_, Option<i32>>(1), None);
    }

    #[test]
    fn validates_source_and_roll_offer_rating_requirement() {
        assert!(validate(&roll_offer(Some(4.0), "roll-offer-valid-01")).is_ok());
        let no_rating = roll_offer(None, "roll-offer-norating1");
        assert!(validate(&no_rating).is_err());
        let mut bad = roll_offer(Some(4.0), "roll-offer-unknown-01");
        bad.source = Some("scheduled".into());
        assert!(validate(&bad).is_err());
        let mut direct = request(Some("read"), Some(4.0));
        direct.source = Some(DIRECT_SOURCE.into());
        assert!(validate(&direct).is_ok());
    }

    #[test]
    fn checked_in_openapi_contract_is_current() {
        let generated = IssueApi::openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document");
        let checked_in = include_str!("../../../native/contracts/issue-v2.openapi.json");
        assert_eq!(
            checked_in.trim_end(),
            generated.trim_end(),
            "Regenerate native/contracts/issue-v2.openapi.json with \
             cargo run --example issue_openapi"
        );
    }

    #[test]
    fn generated_openapi_declares_both_owner_scoped_issue_operations() {
        let document =
            serde_json::to_value(IssueApi::openapi()).expect("serializable OpenAPI document");
        let patch = &document["paths"]["/api/v2/issues/{issue_id}"]["patch"];
        assert_eq!(patch["security"][0]["HTTPBearer"], serde_json::json!([]));
        assert_eq!(
            patch["requestBody"]["content"]["application/json"]["schema"]["$ref"],
            serde_json::json!("#/components/schemas/IssueReadRateRequest")
        );
        let cards = &document["paths"]["/api/v2/issues/cards"]["post"];
        assert_eq!(cards["security"][0]["HTTPBearer"], serde_json::json!([]));
        assert_eq!(
            cards["requestBody"]["content"]["application/json"]["schema"]["$ref"],
            serde_json::json!("#/components/schemas/IssueCardsRequest")
        );
        assert_eq!(
            document["components"]["securitySchemes"]["HTTPBearer"]["scheme"],
            serde_json::json!("bearer")
        );
    }
}
