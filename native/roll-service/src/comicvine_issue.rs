//! Owner-scoped ComicVine issue intelligence and durable metadata enqueue.
//! A single SQL statement validates authentication, reads the complete display
//! projection and idempotently writes the work record when deep metadata is stale.
use crate::{auth::VerifiedAccessClaims, db, ApiError, AppState};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;

const READ_SQL: &str = r#"
WITH auth AS (
  SELECT u.id AS user_id,
         COALESCE(trunc(extract(epoch FROM u.password_changed_at))::bigint, 0) AS password_epoch,
         EXISTS(SELECT 1 FROM revoked_tokens r WHERE r.jti=$2) AS revoked
  FROM users u WHERE u.username=$1 LIMIT 1
), me AS (
  SELECT user_id FROM auth WHERE NOT revoked AND password_epoch <= $3
), owned AS (
  SELECT i.id FROM issues i JOIN threads t ON t.id=i.thread_id
  JOIN me ON me.user_id=t.user_id WHERE i.id=$4 LIMIT 1
), mapped AS MATERIALIZED (
  SELECT ei.id, ei.external_id, ei.external_url, ei.metadata_json::jsonb AS metadata,
         ei.provider_updated_at, ei.updated_at
  FROM issue_external_identity_mappings iem
  JOIN external_identities ei ON ei.id=iem.external_identity_id
  JOIN owned ON owned.id=iem.issue_id
  WHERE iem.status='confirmed' AND ei.provider='comicvine' AND ei.entity_type='issue'
  ORDER BY iem.confidence DESC NULLS LAST, ei.id LIMIT 1
), freshness AS (
  SELECT m.*,
    CASE
      WHEN NOT COALESCE(
          (m.metadata->'raw_provider_payload') ?& ARRAY[
            'id', 'name', 'issue_number', 'cover_date', 'store_date', 'image',
            'volume', 'person_credits', 'character_credits', 'team_credits',
            'story_arc_credits', 'date_last_updated'
          ], false) THEN TRUE
      -- Provider revision newer than our deep fetch: always stale.
      WHEN m.metadata->>'deep_metadata_refreshed_at' IS NOT NULL
        AND m.metadata->'raw_provider_payload'->>'date_last_updated' IS NOT NULL
        AND LEFT(replace(
          m.metadata->'raw_provider_payload'->>'date_last_updated', ' ', 'T'), 19) >
          LEFT(m.metadata->>'deep_metadata_refreshed_at', 19)
      THEN TRUE
      -- A deep response with empty creator_credits / person_credits is a
      -- genuine fetch but is not permanently healthy: recheck after 7 days,
      -- materially sooner than the 30-day window for complete rows, so a
      -- late-arriving or repaired provider roster is picked up without a
      -- hot loop. Malformed/absent credit arrays count as empty (safe: a
      -- repair is enqueued rather than suppressing it). Mirrors
      -- comicvine_repair::needs_provider_fetch exactly.
      WHEN m.provider_updated_at IS NOT NULL THEN
        (m.metadata->'raw_provider_payload'->>'date_last_updated' IS NOT NULL
          AND LEFT(replace(
            m.metadata->'raw_provider_payload'->>'date_last_updated', ' ', 'T'), 19) <
          to_char(m.provider_updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS'))
        OR (
          NOT (
            (jsonb_typeof(COALESCE(m.metadata->'creator_credits', '[]'::jsonb)) = 'array'
              AND jsonb_array_length(CASE WHEN jsonb_typeof(m.metadata->'creator_credits') = 'array' THEN m.metadata->'creator_credits' ELSE '[]'::jsonb END) > 0)
            OR (jsonb_typeof(m.metadata->'raw_provider_payload'->'person_credits') = 'array'
              AND jsonb_array_length(CASE WHEN jsonb_typeof(m.metadata->'raw_provider_payload'->'person_credits') = 'array' THEN m.metadata->'raw_provider_payload'->'person_credits' ELSE '[]'::jsonb END) > 0)
          )
          AND m.metadata->>'deep_metadata_refreshed_at' IS NOT NULL
          AND LEFT(m.metadata->>'deep_metadata_refreshed_at', 19) <= to_char((now() AT TIME ZONE 'UTC') - interval '7 days', 'YYYY-MM-DD"T"HH24:MI:SS')
        )
        OR (
          NOT (
            (jsonb_typeof(COALESCE(m.metadata->'creator_credits', '[]'::jsonb)) = 'array'
              AND jsonb_array_length(CASE WHEN jsonb_typeof(m.metadata->'creator_credits') = 'array' THEN m.metadata->'creator_credits' ELSE '[]'::jsonb END) > 0)
            OR (jsonb_typeof(m.metadata->'raw_provider_payload'->'person_credits') = 'array'
              AND jsonb_array_length(CASE WHEN jsonb_typeof(m.metadata->'raw_provider_payload'->'person_credits') = 'array' THEN m.metadata->'raw_provider_payload'->'person_credits' ELSE '[]'::jsonb END) > 0)
          )
          AND m.metadata->>'deep_metadata_refreshed_at' IS NULL
        )
        OR (
          m.metadata->>'deep_metadata_refreshed_at' IS NOT NULL
          AND LEFT(m.metadata->>'deep_metadata_refreshed_at', 19) <= to_char((now() AT TIME ZONE 'UTC') - interval '30 days', 'YYYY-MM-DD"T"HH24:MI:SS')
        )
      ELSE
        (
          NOT (
            (jsonb_typeof(COALESCE(m.metadata->'creator_credits', '[]'::jsonb)) = 'array'
              AND jsonb_array_length(CASE WHEN jsonb_typeof(m.metadata->'creator_credits') = 'array' THEN m.metadata->'creator_credits' ELSE '[]'::jsonb END) > 0)
            OR (jsonb_typeof(m.metadata->'raw_provider_payload'->'person_credits') = 'array'
              AND jsonb_array_length(CASE WHEN jsonb_typeof(m.metadata->'raw_provider_payload'->'person_credits') = 'array' THEN m.metadata->'raw_provider_payload'->'person_credits' ELSE '[]'::jsonb END) > 0)
          )
          AND m.updated_at <= now()-interval '7 days'
        )
        OR (
          m.metadata->>'deep_metadata_refreshed_at' IS NOT NULL
          AND LEFT(m.metadata->>'deep_metadata_refreshed_at', 19) <= to_char((now() AT TIME ZONE 'UTC') - interval '30 days', 'YYYY-MM-DD"T"HH24:MI:SS')
        )
        OR (
          NOT (
            (jsonb_typeof(COALESCE(m.metadata->'creator_credits', '[]'::jsonb)) = 'array'
              AND jsonb_array_length(CASE WHEN jsonb_typeof(m.metadata->'creator_credits') = 'array' THEN m.metadata->'creator_credits' ELSE '[]'::jsonb END) > 0)
            OR (jsonb_typeof(m.metadata->'raw_provider_payload'->'person_credits') = 'array'
              AND jsonb_array_length(CASE WHEN jsonb_typeof(m.metadata->'raw_provider_payload'->'person_credits') = 'array' THEN m.metadata->'raw_provider_payload'->'person_credits' ELSE '[]'::jsonb END) > 0)
          )
          AND m.metadata->>'deep_metadata_refreshed_at' IS NULL
        )
    END AS needs_repair
  FROM mapped m
), enqueue AS (
  INSERT INTO comicvine_metadata_refresh_requests (
    external_identity_id, state, attempts, next_attempt_at,
    lease_expires_at, last_error, completed_at, created_at, updated_at
  )
  SELECT f.id, 'pending', 0, now(), NULL, NULL, NULL, now(), now()
  FROM freshness f WHERE f.needs_repair
  ON CONFLICT (external_identity_id) DO UPDATE
    SET state='pending', attempts=0, next_attempt_at=now(),
      lease_expires_at=NULL, last_error=NULL, completed_at=NULL, updated_at=now()
    WHERE (
      comicvine_metadata_refresh_requests.state = 'completed'
      AND (comicvine_metadata_refresh_requests.completed_at IS NULL OR
        comicvine_metadata_refresh_requests.completed_at <= now()-interval '30 days')
    ) OR (
      comicvine_metadata_refresh_requests.state = 'no_credits'
      AND (comicvine_metadata_refresh_requests.completed_at IS NULL OR
        comicvine_metadata_refresh_requests.completed_at <= now()-interval '7 days')
    ) OR (
      comicvine_metadata_refresh_requests.state='failed'
      AND comicvine_metadata_refresh_requests.next_attempt_at <= now()
    )
  RETURNING external_identity_id, state, next_attempt_at
), repair AS (
  SELECT state, next_attempt_at FROM (
    SELECT 0 AS priority, e.state, e.next_attempt_at FROM enqueue e
    UNION ALL
    SELECT 1, r.state, r.next_attempt_at
    FROM comicvine_metadata_refresh_requests r
    JOIN freshness f ON f.id=r.external_identity_id
  ) states ORDER BY priority LIMIT 1
), arc_refs AS (
  SELECT arc_id, reference, ordinality FROM (
    SELECT DISTINCT ON ((arc.value->>'id')::int)
           (arc.value->>'id')::int AS arc_id,
           arc.value AS reference, arc.ordinality
    FROM mapped m
    CROSS JOIN LATERAL jsonb_array_elements(
      CASE WHEN jsonb_typeof(COALESCE(m.metadata->'story_arc_credits',m.metadata->'story_arcs'))='array'
      THEN COALESCE(m.metadata->'story_arc_credits',m.metadata->'story_arcs')
      ELSE '[]'::jsonb END
    ) WITH ORDINALITY AS arc(value, ordinality)
    WHERE (arc.value->>'id') ~ '^[0-9]{1,9}$'
    ORDER BY (arc.value->>'id')::int, arc.ordinality
  ) distinct_arcs
  ORDER BY ordinality LIMIT 10
), related AS (
  SELECT a.arc_id, e.id AS identity_id, e.external_id, e.external_url,
         e.metadata_json::jsonb AS metadata
  FROM arc_refs a
  CROSS JOIN mapped m
  JOIN LATERAL (
    SELECT ei.id, ei.external_id, ei.external_url, ei.metadata_json
    FROM external_identities ei
    WHERE ei.provider='comicvine' AND ei.entity_type='issue'
      AND ei.external_id<>m.external_id AND (
        ei.metadata_json::jsonb @> jsonb_build_object('story_arc_credits',
          jsonb_build_array(jsonb_build_object('id',a.arc_id)))
        OR ei.metadata_json::jsonb @> jsonb_build_object('story_arcs',
          jsonb_build_array(jsonb_build_object('id',a.arc_id)))
      )
    ORDER BY ei.external_id, ei.id LIMIT 60
  ) e ON true
), related_projected AS (
  SELECT r.arc_id, r.external_id, r.external_url, r.metadata,
    COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'issue_id', i.id, 'thread_id', t.id, 'thread_title', t.title,
        'issue_number', i.issue_number, 'status', i.status)
        ORDER BY t.title, i.position, i.id)
      FROM issue_external_identity_mappings em
      JOIN issues i ON i.id=em.issue_id
      JOIN threads t ON t.id=i.thread_id
      JOIN me ON me.user_id=t.user_id
      WHERE em.external_identity_id=r.identity_id AND em.status='confirmed'
    ), '[]'::jsonb) AS comicpile_matches
  FROM related r
), arc_totals AS (
  SELECT a.arc_id,
    (SELECT count(DISTINCT ei.external_id)::int
     FROM external_identities ei
     CROSS JOIN mapped m
     WHERE ei.provider='comicvine' AND ei.entity_type='issue'
       AND ei.external_id<>m.external_id AND (
         ei.metadata_json::jsonb @> jsonb_build_object('story_arc_credits',
           jsonb_build_array(jsonb_build_object('id',a.arc_id)))
         OR ei.metadata_json::jsonb @> jsonb_build_object('story_arcs',
           jsonb_build_array(jsonb_build_object('id',a.arc_id)))
       )) AS total
  FROM arc_refs a
)
SELECT jsonb_build_object(
 'auth', (SELECT jsonb_build_object('password_epoch',password_epoch,'revoked',revoked) FROM auth),
 'owned', EXISTS(SELECT 1 FROM owned),
 'mapped', (SELECT jsonb_build_object(
   'external_id',external_id,'external_url',external_url,
   'metadata',metadata, 'needs_repair',needs_repair) FROM freshness),
 'repair', (SELECT jsonb_build_object('state',state,'next_attempt_at',
   extract(epoch FROM next_attempt_at)) FROM repair),
 'arcs', COALESCE((SELECT jsonb_agg(jsonb_build_object(
   'id',arc_id,'reference',reference,'total',(SELECT total FROM arc_totals t WHERE t.arc_id=a.arc_id))
   ORDER BY ordinality) FROM arc_refs a),'[]'::jsonb),
 'related', COALESCE((SELECT jsonb_agg(jsonb_build_object(
   'arc_id',arc_id,'external_id',external_id,'external_url',external_url,
   'metadata',metadata,'comicpile_matches',comicpile_matches))
   FROM related_projected),'[]'::jsonb)
)::text
"#;

#[derive(Deserialize)]
struct Auth {
    password_epoch: i64,
    revoked: bool,
}

#[derive(Deserialize)]
struct Snapshot {
    auth: Option<Auth>,
    owned: bool,
    mapped: Option<Mapped>,
    repair: Option<Repair>,
    arcs: Vec<ArcReference>,
    related: Vec<Related>,
}

#[derive(Deserialize)]
struct Mapped {
    external_id: String,
    external_url: Option<String>,
    metadata: Value,
}

#[derive(Deserialize)]
struct Repair {
    state: String,
    next_attempt_at: Option<f64>,
}

#[derive(Deserialize)]
struct ArcReference {
    id: i32,
    reference: Value,
    total: i32,
}

#[derive(Deserialize)]
struct Related {
    arc_id: i32,
    external_id: String,
    external_url: Option<String>,
    metadata: Value,
    comicpile_matches: Vec<ComicPileMatch>,
}

/// An issue's credited creator with stable provider identity and merged roles.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct Creator {
    creator_id: Option<i64>,
    name: String,
    roles: Vec<String>,
}

/// Owner-scoped local representations of a related ComicVine issue.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct ComicPileMatch {
    issue_id: i32,
    thread_id: i32,
    thread_title: String,
    issue_number: String,
    status: String,
}

/// Related issue derived from a confirmed explicit story-arc relationship.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct RelatedIssue {
    comicvine_issue_id: String,
    series_name: Option<String>,
    issue_number: Option<String>,
    name: Option<String>,
    cover_date: Option<String>,
    comicvine_url: Option<String>,
    comicpile_matches: Vec<ComicPileMatch>,
}

/// A provider story arc with bounded related issues and a correct total.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct StoryArc {
    comicvine_arc_id: i32,
    name: String,
    comicvine_url: Option<String>,
    related_issues: Vec<RelatedIssue>,
    total_related_count: Option<i32>,
}

/// Wire parity with Python's ComicVineIssueIntelligence.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct IssueIntelligence {
    comicvine_issue_id: String,
    comicvine_url: Option<String>,
    series_name: Option<String>,
    series_id: Option<i64>,
    issue_number: Option<String>,
    name: Option<String>,
    description: Option<String>,
    image_url: Option<String>,
    cover_date: Option<String>,
    store_date: Option<String>,
    creators: Vec<Creator>,
    story_arcs: Vec<StoryArc>,
    metadata_status: String,
    refresh_retry_after_seconds: Option<i64>,
}

/// Convert a JSON value to a string if it's non-empty.
fn as_string(value: &Value) -> Option<String> {
    match value {
        Value::String(s) if !s.trim().is_empty() => Some(s.clone()),
        Value::Number(n) => Some(n.to_string()),
        _ => None,
    }
}

/// Convert a JSON value to an i64 ID if possible.
fn as_id(value: &Value) -> Option<i64> {
    value
        .as_i64()
        .or_else(|| value.as_str().and_then(|s| s.parse::<i64>().ok()))
}

/// Get references from metadata, trying primary field first then fallback.
fn refs<'a>(metadata: &'a Value, primary: &str, fallback: &str) -> &'a [Value] {
    metadata
        .get(primary)
        .or_else(|| metadata.get(fallback))
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[])
}

/// Extract and merge creator credits from metadata.
///
/// Creates a unified list of creators by merging duplicate IDs while
/// preserving all roles. Uses person_credits first, then creator_credits.
fn creators(metadata: &Value) -> Vec<Creator> {
    let mut result: Vec<Creator> = Vec::new();
    for credit in refs(metadata, "person_credits", "creator_credits") {
        let Some(name) = as_string(&credit["name"]) else {
            continue;
        };
        let id = as_id(&credit["id"]);
        let roles: Vec<String> = as_string(&credit["role"])
            .unwrap_or_default()
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
            .collect();
        if let Some(existing) = id.and_then(|key| {
            result
                .iter_mut()
                .find(|person| person.creator_id == Some(key))
        }) {
            for role in roles {
                if !existing.roles.contains(&role) {
                    existing.roles.push(role);
                }
            }
        } else {
            result.push(Creator {
                creator_id: id,
                name,
                roles,
            });
        }
    }
    result
}

/// Extract series ID and name from metadata.
///
/// Handles both modern volume object format and legacy volume_id fields.
fn series(metadata: &Value) -> (Option<i64>, Option<String>) {
    if metadata["volume"].is_object() {
        (
            as_id(&metadata["volume"]["id"]),
            as_string(&metadata["volume"]["name"]),
        )
    } else {
        (
            as_id(&metadata["volume_id"]),
            as_string(&metadata["volume_name"]),
        )
    }
}

/// Extract the best available image URL from metadata.
///
/// Tries image_url, primary_image, then various image sizes in order of preference.
fn image(metadata: &Value) -> Option<String> {
    as_string(&metadata["image_url"])
        .or_else(|| as_string(&metadata["primary_image"]))
        .or_else(|| {
            ["original_url", "super_url", "medium_url", "small_url"]
                .iter()
                .find_map(|key| as_string(&metadata["image"][*key]))
        })
}

/// Convert HTML text to plain text by removing tags and decoding entities.
///
/// Strips HTML tags, decodes HTML entities, and normalizes whitespace.
/// Returns None if the result is empty.
fn plain_text(value: &Value) -> Option<String> {
    let source = value.as_str()?.trim();
    if source.is_empty() {
        return None;
    }
    let mut text = String::new();
    let mut in_tag = false;
    for c in source.chars() {
        match c {
            '<' => in_tag = true,
            '>' if in_tag => {
                in_tag = false;
                text.push(' ');
            }
            _ if !in_tag => text.push(c),
            _ => {}
        }
    }
    let decoded = text
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&#39;", "'");
    let normalized = decoded.split_whitespace().collect::<Vec<_>>().join(" ");
    if normalized.is_empty() {
        None
    } else {
        Some(normalized)
    }
}

/// Determine the metadata status based on repair state and content.
///
/// Returns a status string and optional retry delay in seconds.
/// Priority order: repair state > deep fetch status > credit availability.
fn status(mapped: &Mapped, repair: Option<&Repair>) -> (String, Option<i64>) {
    if let Some(repair) = repair {
        let active = match repair.state.as_str() {
            "pending" => Some("refresh_pending"),
            "running" => Some("refresh_running"),
            "deferred" => Some("refresh_deferred"),
            "failed" => Some("refresh_failed"),
            _ => None,
        };
        if let Some(state) = active {
            let retry = if state == "refresh_deferred" || state == "refresh_failed" {
                repair
                    .next_attempt_at
                    .map(|stamp| (stamp - chrono::Utc::now().timestamp() as f64).max(0.0) as i64)
            } else {
                None
            };
            return (state.to_string(), retry);
        }
    }
    let raw = &mapped.metadata["raw_provider_payload"];
    let deep = [
        "id",
        "name",
        "issue_number",
        "cover_date",
        "store_date",
        "image",
        "volume",
        "person_credits",
        "character_credits",
        "team_credits",
        "story_arc_credits",
        "date_last_updated",
    ]
    .iter()
    .all(|key| raw.get(*key).is_some());
    if !deep {
        ("not_deep_fetched".into(), None)
    } else if creators(&mapped.metadata).is_empty() {
        ("deep_fetched_no_credits".into(), None)
    } else {
        ("complete".into(), None)
    }
}

/// Build the complete issue intelligence response from mapped data.
///
/// Constructs the IssueIntelligence struct by processing metadata,
/// story arcs, and related issues. Sorts and limits related issues.
fn response(
    mapped: Mapped,
    repair: Option<Repair>,
    arcs: Vec<ArcReference>,
    related: Vec<Related>,
) -> IssueIntelligence {
    let mut story_arcs = Vec::new();
    for arc in arcs {
        let Some(name) = as_string(&arc.reference["name"]) else {
            continue;
        };
        let mut issues: Vec<RelatedIssue> = related
            .iter()
            .filter(|item| item.arc_id == arc.id)
            .map(|item| {
                let (_, series_name) = series(&item.metadata);
                RelatedIssue {
                    comicvine_issue_id: item.external_id.clone(),
                    series_name,
                    issue_number: as_string(&item.metadata["issue_number"]),
                    name: as_string(&item.metadata["name"]),
                    cover_date: as_string(&item.metadata["cover_date"]),
                    comicvine_url: item
                        .external_url
                        .clone()
                        .or_else(|| as_string(&item.metadata["site_detail_url"])),
                    comicpile_matches: item.comicpile_matches.clone(),
                }
            })
            .collect();
        issues.sort_by(|left, right| {
            (
                left.cover_date.as_deref().unwrap_or(""),
                left.series_name.as_deref().unwrap_or(""),
                left.issue_number.as_deref().unwrap_or(""),
            )
                .cmp(&(
                    right.cover_date.as_deref().unwrap_or(""),
                    right.series_name.as_deref().unwrap_or(""),
                    right.issue_number.as_deref().unwrap_or(""),
                ))
        });
        issues.truncate(60);
        let total = if arc.total > issues.len() as i32 {
            Some(arc.total)
        } else {
            None
        };
        story_arcs.push(StoryArc {
            comicvine_arc_id: arc.id,
            name,
            comicvine_url: as_string(&arc.reference["site_detail_url"]),
            related_issues: issues,
            total_related_count: total,
        });
    }
    let (series_id, series_name) = series(&mapped.metadata);
    let (metadata_status, refresh_retry_after_seconds) = status(&mapped, repair.as_ref());
    IssueIntelligence {
        comicvine_issue_id: mapped.external_id,
        comicvine_url: mapped
            .external_url
            .or_else(|| as_string(&mapped.metadata["site_detail_url"])),
        series_id,
        series_name,
        issue_number: as_string(&mapped.metadata["issue_number"]),
        name: as_string(&mapped.metadata["name"]),
        description: plain_text(&mapped.metadata["description"]),
        image_url: image(&mapped.metadata),
        cover_date: as_string(&mapped.metadata["cover_date"]),
        store_date: as_string(&mapped.metadata["store_date"]),
        creators: creators(&mapped.metadata),
        story_arcs,
        metadata_status,
        refresh_retry_after_seconds,
    }
}

fn unauthorized(detail: &'static str) -> ApiError {
    ApiError(StatusCode::UNAUTHORIZED, detail.into())
}

/// The only live issue-intelligence read and queue producer. No provider I/O.
pub async fn issue_intelligence(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    Path(issue_id): Path<i32>,
) -> Result<Json<Option<IssueIntelligence>>, ApiError> {
    let username = claims.username().to_owned();
    let jti = claims.jti().to_owned();
    let epoch = claims.expected_epoch().unwrap_or(i64::MAX);
    let connection = db::checkout(&state).await?;
    let row = db::query_one_optional(
        &state,
        connection,
        READ_SQL,
        &[&username, &jti, &epoch, &issue_id],
    )
    .await?
    .ok_or_else(|| {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Internal Server Error".into(),
        )
    })?;
    let payload: String = row.try_get(0).map_err(db::query_error)?;
    let snapshot: Snapshot = serde_json::from_str(&payload).map_err(|_| {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Invalid stored metadata".into(),
        )
    })?;
    let auth = snapshot
        .auth
        .ok_or_else(|| unauthorized("User not found"))?;
    if auth.revoked {
        return Err(unauthorized("Token has been revoked"));
    }
    if claims.expected_epoch()? < auth.password_epoch {
        return Err(unauthorized("Password changed; please sign in again."));
    }
    if !snapshot.owned {
        return Err(ApiError(StatusCode::NOT_FOUND, "Issue not found".into()));
    }
    Ok(Json(snapshot.mapped.map(|metadata| {
        response(metadata, snapshot.repair, snapshot.arcs, snapshot.related)
    })))
}

/// Canonical Rust-derived v2 endpoint documentation.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(issue_intelligence_docs),
    components(schemas(IssueIntelligence, Creator, StoryArc, RelatedIssue, ComicPileMatch)),
    modifiers(&IssueSecurityAddon)
)]
pub struct ComicVineIssueApi;

/// Native same-path alias for the browser-called v1 read (#4845).
///
/// Serves `GET /api/v1/issues/{issue_id}/comicvine` with the identical
/// handler and `IssueIntelligence` wire as the v2 resource; deployed
/// ingress in `vercel.json` shadows the Python v1 handler. The Python v1
/// reader was deliberately read-only (never enqueued a repair); the
/// native cutover adopts the Rust v2 producer, which idempotently queues
/// a refresh only when stored deep metadata is stale, and reports the
/// stored repair state in `metadata_status` exactly as the v2 contract
/// documents.
#[utoipa::path(
    get,
    path="/api/v1/issues/{issue_id}/comicvine",
    params(("issue_id"=i32,Path,description="Owner-scoped ComicPile issue id")),
    tag="issues",
    responses(
        (status=200, description="Stored ComicVine intelligence, or null without a mapping",
            body=Option<IssueIntelligence>),
        (status=401, description="Invalid or revoked access token"),
        (status=404, description="Issue is not owned by the reader")
    ),
    security(("HTTPBearer"=[]))
)]
#[allow(dead_code)]
pub fn issue_intelligence_v1_documentation() {}

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

#[utoipa::path(
    get,
    path="/api/v2/issues/{issue_id}/comicvine",
    params(("issue_id"=i32,Path,description="Owner-scoped ComicPile issue id")),
    tag="issues",
    responses(
        (status=200, description="Stored ComicVine intelligence, or null without a mapping",
            body=Option<IssueIntelligence>),
        (status=401, description="Invalid or revoked access token"),
        (status=404, description="Issue is not owned by the reader")
    ),
    security(("HTTPBearer"=[]))
)]
#[allow(dead_code)]
fn issue_intelligence_docs() {}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn creator_merging_preserves_provider_roles_and_anonymous_rows() {
        let metadata = json!({"creator_credits":[
            {"id":1,"name":"Jamie Delano","role":"writer"},
            {"id":1,"name":"Jamie Delano","role":"writer, co-plotter"},
            {"name":"Unknown","role":"artist"}
        ]});
        let people = creators(&metadata);
        assert_eq!(people.len(), 2);
        assert_eq!(people[0].roles, vec!["writer", "co-plotter"]);
        assert_eq!(people[1].creator_id, None);
    }
    #[test]
    fn queue_is_owner_scoped_and_single_statement() {
        assert!(READ_SQL.contains("JOIN me ON me.user_id=t.user_id"));
        assert!(READ_SQL.contains("ON CONFLICT (external_identity_id) DO UPDATE"));
        assert!(READ_SQL.contains("WHERE f.needs_repair"));
        assert!(!READ_SQL.contains("FOR UPDATE SKIP LOCKED"));
        assert_eq!(as_id(&json!("29319")), Some(29319));
    }
    #[test]
    fn deep_refresh_timestamp_comparisons_use_utc_text_on_both_sides() {
        // Metadata is JSON text, but now() yields timestamptz.
        // Mixing them is a PostgreSQL 42883 error on every intelligence read.
        assert_eq!(
            READ_SQL
                .matches("LEFT(m.metadata->>'deep_metadata_refreshed_at', 19) <= to_char(")
                .count(),
            3,
            "both fallback freshness branches must use UTC text thresholds"
        );
        assert!(
            !READ_SQL.contains("m.metadata->>'deep_metadata_refreshed_at' <= now()"),
            "never compare JSON text directly with a PostgreSQL timestamp"
        );
    }

    #[test]
    fn malformed_credit_fields_never_reach_jsonb_array_length() {
        // PostgreSQL does not guarantee short-circuit evaluation of AND.
        // jsonb_array_length on JSON null, an object, or a scalar raises an
        // error and turns the ComicVine intelligence endpoint into HTTP 500.
        // Every call must receive CASE-normalized arrays, including when
        // provider metadata is missing or malformed.
        assert_eq!(
            READ_SQL
                .matches("jsonb_array_length(CASE WHEN jsonb_typeof(")
                .count(),
            8,
            "all credit-length checks must handle non-array JSON safely"
        );
        assert!(
            !READ_SQL.contains("jsonb_array_length(COALESCE("),
            "COALESCE cannot protect against non-array JSON values"
        );
        assert!(
            !READ_SQL.contains("jsonb_array_length(m.metadata->"),
            "never call array_length directly on untrusted provider JSON"
        );
    }

    #[test]
    fn empty_credits_use_seven_day_recheck_and_provider_revision() {
        // Reader policy must mirror comicvine_repair::needs_provider_fetch.
        assert!(
            READ_SQL.contains("interval '7 days'"),
            "empty credits need a 7-day recheck, not a 30-day lock"
        );
        assert!(READ_SQL.contains("state = 'no_credits'"));
        assert!(
            READ_SQL.contains("state = 'completed'"),
            "completed rows keep the 30-day window"
        );
        assert!(
            READ_SQL.contains("date_last_updated"),
            "provider revision must be compared against the deep fetch"
        );
        // Malformed/absent credit arrays count as empty (safe direction).
        assert!(READ_SQL.contains("jsonb_typeof"));
        // Both freshness branches (provider_updated_at and updated_at) must use
        // the same NOT (has credits) predicate: a row has credits iff either
        // creator_credits or person_credits is non-empty (R1 regression).
        // Two NOT (has credits) sub-conditions per branch x 2 branches = 4.
        assert_eq!(
            READ_SQL.matches("NOT (").count(),
            4,
            "both branches must use NOT (has credits)"
        );
    }
    #[test]
    fn credited_rows_refresh_after_30_days() {
        // Both freshness branches must allow a credited row with a 31-day-old
        // deep_metadata_refreshed_at to be considered stale, i.e., the 30-day
        // window must not be guarded by a NOT(has credits) predicate.
        assert!(
            READ_SQL.contains("m.metadata->>'deep_metadata_refreshed_at' IS NOT NULL\n          AND LEFT(m.metadata->>'deep_metadata_refreshed_at', 19) <= to_char((now() AT TIME ZONE 'UTC') - interval '30 days'"),
            "30-day refresh must apply to credited rows"
        );
        // Count only the deep-metadata freshness branches; the enqueue
        // completed_at window is a separate 30-day retry guard.
        assert_eq!(
            READ_SQL
                .matches("LEFT(m.metadata->>'deep_metadata_refreshed_at', 19) <= to_char((now() AT TIME ZONE 'UTC') - interval '30 days'")
                .count(),
            2,
            "two 30-day freshness branches, one per freshness path"
        );
    }
    #[test]
    fn seven_creators_read_through_production_path() {
        // Issue #24 shape: seven person credits. The production read path is
        // creators() -> response(), not cached_has_credits alone. Confirm all
        // seven creators survive the merge, including role merging.
        let seven = (1..=7)
            .map(|i| json!({"id": i, "name": format!("Creator {i}"), "role": "writer"}))
            .collect::<Vec<_>>();
        let metadata = json!({"person_credits": seven});
        let people = creators(&metadata);
        assert_eq!(people.len(), 7);
        assert_eq!(people[0].name, "Creator 1");
        assert_eq!(people[6].name, "Creator 7");
        assert_eq!(people[6].creator_id, Some(7));
        // Wire projection through response() preserves all seven.
        let mapped = Mapped {
            external_id: "1196188".into(),
            external_url: None,
            metadata: json!({
                "name": "Issue 24", "volume": {"id": 1, "name": "Absolute Superman"},
                "person_credits": seven,
                "cover_date": "2026-01-01", "store_date": "2026-01-01",
                "raw_provider_payload": {"id": 1, "name": "Issue 24", "issue_number": "24",
                    "cover_date": "2026-01-01", "store_date": "2026-01-01", "image": {},
                    "volume": {"id": 1, "name": "Absolute Superman"},
                    "person_credits": seven, "character_credits": [], "team_credits": [],
                    "story_arc_credits": [], "date_last_updated": "2026-01-01T00:00:00+00:00"}
            }),
        };
        let wire = serde_json::to_value(response(mapped, None, vec![], vec![])).unwrap();
        assert_eq!(wire["creators"].as_array().unwrap().len(), 7);
        assert_eq!(wire["metadata_status"], "complete");
    }
    #[test]
    fn render_the_existing_issue_intelligence_shape() {
        let mapped = Mapped {
            external_id: "29319".into(),
            external_url: None,
            metadata: json!({"name":"Going For It","volume":{"id":1,"name":"Hellblazer"},
                "creator_credits":[{"id":1,"name":"Jamie Delano"}],
                "cover_date":"1988-03-01","store_date":"1988-03-24"}),
        };
        let wire = serde_json::to_value(response(
            mapped,
            Some(Repair {
                state: "pending".into(),
                next_attempt_at: None,
            }),
            vec![],
            vec![],
        ))
        .unwrap();
        assert_eq!(wire["creators"][0]["name"], "Jamie Delano");
        assert_eq!(wire["metadata_status"], "refresh_pending");
        assert!(wire["story_arcs"].is_array());
        assert_eq!(wire["series_name"], "Hellblazer");
    }
}
