//! Authenticated direct issue completion. Option E selects offers, not permissions.
//! Uses the canonical issues/events schema and the shared PostgreSQL pool.
use crate::{auth::AuthenticatedUser, db, ApiError};
use axum::http::StatusCode;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use tokio_postgres::Transaction;

/// Upper bound for one visible issue-card group. Keeps the set request bounded
/// instead of degenerating into a per-card or whole-library lookup.
pub(crate) const MAX_CARD_ISSUES: usize = 200;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub struct IssueReadRateRequest {
    /// Explicit new status. Omit to leave read state unchanged.
    pub status: Option<String>,
    /// Effective issue rating in 0.5-point steps. Omit to keep the stored rating.
    pub rating: Option<f64>,
    /// Client-generated retry key. Same key/payload replays the same receipt.
    pub idempotency_key: String,
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
}

fn invalid(message: &'static str) -> ApiError {
    ApiError(StatusCode::UNPROCESSABLE_ENTITY, message.into())
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
                         NULLIF(x.metadata_json#>>'{image,medium_url}', ''),
                         NULLIF(x.metadata_json#>>'{image,original_url}', ''),
                         NULLIF(x.metadata_json->>'cover_image_url', ''),
                         NULLIF(x.metadata_json->>'image_url', '')
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
                         NULLIF(x.metadata_json#>>'{image,medium_url}', ''),
                         NULLIF(x.metadata_json#>>'{image,original_url}', ''),
                         NULLIF(x.metadata_json->>'cover_image_url', ''),
                         NULLIF(x.metadata_json->>'image_url', '')
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
/// read state must refresh it in the same transaction. Native Skip
/// (`native/roll-service/src/skip.rs`) and the legacy queue projection both
/// filter on the stored column; a stale value lets a re-blocked thread enter the
/// pool or hides a just-unblocked one. Mirrors
/// `comic_pile.dependencies.refresh_user_blocked_status`.
async fn refresh_blocked_threads(tx: &Transaction<'_>, user_id: i32) -> Result<(), ApiError> {
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

/// Apply the exact issue action inside an existing owner-serialized transaction.
/// No Option E, queue-position, die, snooze, prerequisite or session writes.
pub(crate) async fn persist(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    issue_id: i32,
    request: &IssueReadRateRequest,
) -> Result<IssueReadRateResponse, ApiError> {
    validate(request)?;
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
    });
    // Lock the owner thread before the issue; owner transfers and concurrent
    // progress writers must not escape the ownership check.
    let owner = tx
        .query_opt(
            "SELECT t.id FROM threads t JOIN issues i ON i.thread_id=t.id
         WHERE i.id=$1 AND t.user_id=$2 FOR UPDATE OF t,i",
            &[&issue_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError(StatusCode::NOT_FOUND, "Issue not found".into()))?;
    let thread_id: i32 = owner.get(0);

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
        let context: Value = serde_json::from_str(&saved).map_err(|_| {
            ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Invalid stored issue receipt".into(),
            )
        })?;
        if context.get("issue_command_payload") != Some(&payload) {
            return Err(ApiError(
                StatusCode::CONFLICT,
                "Idempotency key reused for different action".into(),
            ));
        }
        let receipt = context
            .get("issue_command_receipt")
            .cloned()
            .ok_or_else(|| {
                ApiError(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "Missing stored issue receipt".into(),
                )
            })?;
        let mut result: IssueReadRateResponse = serde_json::from_value(receipt).map_err(|_| {
            ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Invalid stored issue receipt".into(),
            )
        })?;
        result.replayed = true;
        return Ok(result);
    }

    let issue = tx
        .query_one(
            "SELECT status, issue_number FROM issues
         WHERE id=$1 AND thread_id=$2 FOR UPDATE",
            &[&issue_id, &thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let old_status: String = issue.get(0);
    let issue_number: String = issue.get(1);
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
    let requested_rating = request.rating.or(if newly_read { Some(3.5) } else { None });
    let rating_changed = requested_rating.is_some_and(|rating| Some(rating) != old_rating);
    let final_rating = requested_rating.or(old_rating);

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
        "source": "direct",
        "issue_command_key": request.idempotency_key,
        "issue_command_payload": payload,
    });
    let event_id: i32 = tx
        .query_one(
            "INSERT INTO events
            (user_id,type,timestamp,thread_id,issue_id,issue_number,
             rating,issues_read,context)
         VALUES ($1,$2,NOW(),$3,$4,$5,$6,$7,$8::text::json) RETURNING id",
            &[
                &user.id(),
                &event_type,
                &thread_id,
                &issue_id,
                &issue_number,
                &recorded_rating,
                &issues_read,
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
    };
    let mut saved = context;
    saved["issue_command_receipt"] = serde_json::to_value(&result).map_err(|_| {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Cannot store issue receipt".into(),
        )
    })?;
    tx.execute(
        "UPDATE events SET context=$2::text::json WHERE id=$1 AND user_id=$3",
        &[&event_id, &saved.to_string(), &user.id()],
    )
    .await
    .map_err(db::query_error)?;
    // Q17: retire the pending Roll selection only when this exact issue was the
    // selected one. Reading a different manual issue must leave the offer alone.
    tx.execute(
        "UPDATE sessions SET pending_thread_id=NULL, pending_issue_id=NULL,
             pending_thread_updated_at=NULL
         WHERE user_id=$1 AND pending_issue_id=$2 AND ended_at IS NULL",
        &[&user.id(), &issue_id],
    )
    .await
    .map_err(db::query_error)?;
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
    use utoipa::OpenApi;

    fn request(status: Option<&str>, rating: Option<f64>) -> IssueReadRateRequest {
        IssueReadRateRequest {
            status: status.map(str::to_owned),
            rating,
            idempotency_key: "direct-issue-012345".into(),
        }
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
    async fn scoped_client(url: &str, schema: &str) -> tokio_postgres::Client {
        let (client, connection) = tokio_postgres::connect(url, tokio_postgres::NoTls)
            .await
            .unwrap();
        tokio::spawn(async move {
            let _ = connection.await;
        });
        client
            .batch_execute(&format!("SET search_path TO {schema},public"))
            .await
            .unwrap();
        client
    }

    #[tokio::test]
    async fn direct_read_is_owner_scoped_and_does_not_touch_roll_or_queue() {
        let Ok(url) = std::env::var("RUST_ROLL_TEST_DATABASE_URL") else {
            return;
        };
        let (admin, connection) = tokio_postgres::connect(&url, tokio_postgres::NoTls)
            .await
            .unwrap();
        tokio::spawn(async move {
            let _ = connection.await;
        });
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let schema = format!("direct_issue_{}_{}", std::process::id(), nanos);
        admin
            .batch_execute(&format!(
                "CREATE SCHEMA {schema};
                 CREATE TABLE {schema}.threads (
                     id integer PRIMARY KEY, user_id integer NOT NULL,
                     title text NOT NULL,
                     status text NOT NULL, issues_remaining integer NOT NULL,
                     next_unread_issue_id integer, reading_progress text,
                     last_rating double precision, queue_position integer NOT NULL,
                     queue_position_is_manual boolean NOT NULL,
                     last_activity_at timestamptz,
                     is_blocked boolean NOT NULL DEFAULT false
                 );
                 CREATE TABLE {schema}.dependencies (
                     id integer PRIMARY KEY,
                     source_issue_id integer NOT NULL,
                     target_issue_id integer NOT NULL,
                     note text
                 );
                 CREATE TABLE {schema}.issues (
                     id integer PRIMARY KEY, thread_id integer NOT NULL,
                     issue_number text NOT NULL, status text NOT NULL,
                     position integer NOT NULL, read_at timestamptz
                 );
                 CREATE TABLE {schema}.events (
                     id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                     user_id integer, type text, timestamp timestamptz DEFAULT NOW(),
                     thread_id integer, issue_id integer, issue_number text,
                     rating double precision, issues_read integer, die_after integer,
                     context json
                 );
                 CREATE TABLE {schema}.external_identities (
                     id integer PRIMARY KEY, provider text, entity_type text,
                     external_id text, metadata_json json
                 );
                 CREATE TABLE {schema}.issue_external_identity_mappings (
                     id integer PRIMARY KEY, issue_id integer,
                     external_identity_id integer, status text,
                     confidence double precision,
                     updated_at timestamptz DEFAULT NOW()
                 );
                 CREATE TABLE {schema}.sessions (
                     id integer PRIMARY KEY, user_id integer,
                     pending_thread_id integer, pending_issue_id integer,
                     pending_thread_updated_at timestamptz,
                     manual_die integer, ended_at timestamptz
                 );
                 INSERT INTO {schema}.threads VALUES
                     (10,1,'Excluded run','excluded',3,101,'in_progress',4.0,0,true,NULL,false),
                     (20,2,'Private run','active',1,201,'in_progress',NULL,1,false,NULL,false),
                     (30,1,'Dependent run','active',1,301,'in_progress',NULL,2,false,NULL,true),
                     (40,1,'Cbl control run','active',1,401,'in_progress',NULL,3,false,NULL,false);
                 INSERT INTO {schema}.issues VALUES
                     (101,10,'1','unread',1,NULL),
                     (102,10,'2','unread',2,NULL),
                     (110,10,'10','unread',10,NULL),
                     (201,20,'1','unread',1,NULL),
                     (301,30,'1','unread',1,NULL),
                     (401,40,'1','unread',1,NULL);
                 INSERT INTO {schema}.dependencies VALUES
                     (1,102,301,NULL),
                     (2,101,401,'cbl-order:legacy-materialization');
                 INSERT INTO {schema}.sessions VALUES (1,1,10,101,NULL,12,NULL);
                 INSERT INTO {schema}.external_identities VALUES
                     (50,'comicvine','issue','4000-42',
                      '{{\"image\":{{\"medium_url\":\"https://comicvine.example/covers/issue10.jpg\"}}}}'::json);
                 INSERT INTO {schema}.issue_external_identity_mappings
                     (id,issue_id,external_identity_id,status)
                     VALUES (500,110,50,'confirmed');"
            ))
            .await
            .unwrap();

        let mut first = scoped_client(&url, &schema).await;
        let user = AuthenticatedUser::for_test(1);
        let mut command = request(Some("read"), Some(4.5));
        let tx = first.transaction().await.unwrap();
        let read = persist(&tx, user, 110, &command).await.unwrap();
        tx.commit().await.unwrap();
        assert!(read.read_event_created);
        assert!(read.rating_event_created);
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
        assert_eq!(collision.0, StatusCode::CONFLICT);

        let correction = IssueReadRateRequest {
            status: None,
            rating: Some(3.5),
            idempotency_key: "direct-issue-correction-01".into(),
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
        let tx = first.transaction().await.unwrap();
        let reblocked = persist(
            &tx,
            user,
            102,
            &IssueReadRateRequest {
                status: Some("unread".into()),
                rating: None,
                idempotency_key: "direct-issue-reblock-01".into(),
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

        let tx = first.transaction().await.unwrap();
        let foreign = persist(&tx, user, 201, &request(Some("read"), None))
            .await
            .unwrap_err();
        tx.rollback().await.unwrap();
        assert_eq!(foreign.0, StatusCode::NOT_FOUND);
        let tx = first.transaction().await.unwrap();
        let unmapped = persist(
            &tx,
            user,
            101,
            &IssueReadRateRequest {
                status: Some("read".into()),
                rating: None,
                idempotency_key: "direct-issue-default-01".into(),
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

        admin
            .batch_execute(&format!("DROP SCHEMA {schema} CASCADE"))
            .await
            .unwrap();
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
