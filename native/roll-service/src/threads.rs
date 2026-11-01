//! Owner-scoped v2 reader threads collection.
//!
//! `GET /api/v2/threads` replaces the v1 `/api/v1/threads/` collection read
//! with a bounded, resource-oriented projection of the reader's active queue.
//! It preserves the real consumer contract: deterministic cursor pagination for
//! `position`, `title` and `created`, the authoritative whole-queue
//! `active_count`, case-insensitive title search, next-unread issue identity,
//! unread counts, tags, confirmed ComicVine mapping health and the confirmed
//! provider series metadata that distinguishes same-titled runs.
//!
//! Two execution authorities are preserved from the Python service:
//!
//! * Legacy (production default, `OPTION_E_ENABLED` off) uses the stored
//!   `threads.is_blocked` flag for readable/blocked grouping. Authentication,
//!   the page, the whole-queue total, tags, mapping health and series identity
//!   are one PostgreSQL statement, including the token's revocation and
//!   credential-epoch check.
//! * The owner-activated Option E preview evaluates the reading graph in Rust
//!   and uses that result for grouping, availability, frontier and blocking
//!   reasons. It needs the bounded Option E input snapshot in addition to the
//!   page statement, so the default path is the only one-statement path.

use crate::{
    auth::VerifiedAccessClaims, db, option_inputs, reading_eligibility, ApiError, AppState,
};
use axum::{
    extract::{Query, State},
    http::StatusCode,
    Json,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};
use unicode_casefold::UnicodeCaseFold;

/// Page-statement count for this module, so the focused parity test can prove
/// the default collection read is one issued statement including authentication.
pub static PAGE_STATEMENTS_ISSUED: AtomicU64 = AtomicU64::new(0);

const DEFAULT_PAGE_SIZE: i64 = 50;
const MAX_PAGE_SIZE: i64 = 200;

/// One tag visible to the reader.
#[derive(Debug, Clone, Deserialize, Serialize, utoipa::ToSchema)]
pub struct ThreadTag {
    pub id: i32,
    pub name: String,
    pub normalized_name: String,
    pub scope: String,
    pub owner_user_id: Option<i32>,
    pub color: String,
    pub created_at: String,
    pub updated_at: String,
}

/// Compact confirmed ComicVine mapping health for one queue row.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct ComicVineMappingHealth {
    pub status: String,
    pub tracked_issue_count: i32,
    pub confirmed_issue_count: i32,
    pub needs_mapping_count: i32,
    pub needs_review_count: i32,
    pub metadata_missing_count: i32,
}

/// Confirmed provider series metadata for one queue row.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct QueueSeriesMetadata {
    pub year: Option<i32>,
    pub volume: Option<String>,
    pub publisher: Option<String>,
}

/// One reader threads collection item.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ThreadListItem {
    pub id: i32,
    pub title: String,
    pub format: String,
    pub issues_remaining: i32,
    pub queue_position: i32,
    pub status: String,
    pub last_activity_at: Option<String>,
    pub is_blocked: bool,
    pub blocking_reasons: Vec<String>,
    pub total_issues: Option<i32>,
    pub next_unread_issue_number: Option<String>,
    pub notes: Option<String>,
    pub created_at: String,
    pub comicvine_mapping: Option<ComicVineMappingHealth>,
    pub manual_creator_credits: Value,
    pub tags: Vec<ThreadTag>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub series_metadata: Option<QueueSeriesMetadata>,
}

/// Paginated reader threads collection.
#[derive(Debug, Serialize, utoipa::ToSchema)]
pub struct ThreadListResponse {
    pub threads: Vec<ThreadListItem>,
    pub next_page_token: Option<String>,
    pub active_count: i32,
}

/// Query parameters for `GET /api/v2/threads`.
#[derive(Debug, Default, Deserialize)]
pub struct ThreadListQuery {
    pub search: Option<String>,
    pub sort: Option<String>,
    pub page_size: Option<i64>,
    pub page_token: Option<String>,
    /// Retired v1 filter: reject it instead of silently changing its meaning.
    pub collection_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct QueueCursor {
    sort: String,
    search: String,
    values: Vec<String>,
    execution: String,
}

fn bad_request(detail: &str) -> ApiError {
    ApiError(StatusCode::BAD_REQUEST, detail.to_string())
}

fn unprocessable(detail: &str) -> ApiError {
    ApiError(StatusCode::UNPROCESSABLE_ENTITY, detail.to_string())
}

fn normalize_search(search: Option<&str>) -> String {
    search
        .map(|value| value.trim().case_fold().collect::<String>())
        .unwrap_or_default()
}

fn option_e_enabled() -> bool {
    let enabled = std::env::var("OPTION_E_ENABLED")
        .map(|value| {
            matches!(
                value.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "t" | "yes" | "y" | "on"
            )
        })
        .unwrap_or(false);
    enabled
        && std::env::var("OPTION_E_APPROVED_PREVIEW")
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false)
}

fn encode_cursor(cursor: &QueueCursor) -> String {
    let mut payload = BTreeMap::new();
    payload.insert("sort", Value::String(cursor.sort.clone()));
    payload.insert("search", Value::String(cursor.search.clone()));
    payload.insert(
        "values",
        Value::Array(
            cursor
                .values
                .iter()
                .map(|value| Value::String(value.clone()))
                .collect(),
        ),
    );
    if cursor.execution != "legacy" {
        payload.insert("execution", Value::String(cursor.execution.clone()));
    }
    URL_SAFE_NO_PAD.encode(serde_json::to_vec(&payload).expect("serializable cursor"))
}

fn decode_cursor(
    token: &str,
    sort: &str,
    search: &str,
    execution: &str,
) -> Result<QueueCursor, ApiError> {
    let invalid = || bad_request("Invalid Queue page token");
    let padded = token.trim_end_matches('=');
    let raw = URL_SAFE_NO_PAD.decode(padded).map_err(|_| invalid())?;
    let payload: Value = serde_json::from_slice(&raw).map_err(|_| invalid())?;
    let Some(object) = payload.as_object() else {
        return Err(invalid());
    };
    let cursor_sort = object
        .get("sort")
        .and_then(Value::as_str)
        .ok_or_else(invalid)?;
    let cursor_search = object
        .get("search")
        .and_then(Value::as_str)
        .ok_or_else(invalid)?;
    let raw_values = object
        .get("values")
        .and_then(Value::as_array)
        .ok_or_else(invalid)?;
    let cursor_execution = object
        .get("execution")
        .and_then(Value::as_str)
        .unwrap_or("legacy");
    if cursor_execution != execution {
        return Err(bad_request("Queue ordering changed; reload the Queue"));
    }
    if !matches!(cursor_sort, "position" | "title" | "created") {
        return Err(bad_request("Invalid Queue page token sort"));
    }
    let values: Option<Vec<String>> = raw_values
        .iter()
        .map(|value| value.as_str().map(str::to_owned))
        .collect();
    let values = values.ok_or_else(|| bad_request("Invalid Queue page token values"))?;
    let expected = match cursor_sort {
        "position" => 3,
        _ => 2,
    };
    if values.len() != expected
        || (cursor_sort == "position" && !matches!(values[0].as_str(), "0" | "1"))
    {
        return Err(bad_request("Invalid Queue page token values"));
    }
    if cursor_sort != sort || cursor_search != search {
        return Err(bad_request(
            "Queue page token does not match current search or sort",
        ));
    }
    Ok(QueueCursor {
        sort: cursor_sort.to_string(),
        search: cursor_search.to_string(),
        values,
        execution: cursor_execution.to_string(),
    })
}

/// Read one page of the authenticated reader's active threads.
pub async fn list_threads(
    State(state): State<Arc<AppState>>,
    claims: VerifiedAccessClaims,
    Query(query): Query<ThreadListQuery>,
) -> Result<Json<ThreadListResponse>, ApiError> {
    if query.collection_id.is_some() {
        return Err(unprocessable("collection_id is retired"));
    }
    let sort = query.sort.as_deref().unwrap_or("position");
    if !matches!(sort, "position" | "title" | "created") {
        return Err(bad_request("sort must be one of: position, title, created"));
    }
    let page_size = query.page_size.unwrap_or(DEFAULT_PAGE_SIZE);
    if !(1..=MAX_PAGE_SIZE).contains(&page_size) {
        return Err(unprocessable("page_size must be between 1 and 200"));
    }
    let raw_search = query.search.as_deref();
    if raw_search.is_some_and(str::is_empty) {
        return Err(unprocessable("search must be at least 1 character"));
    }
    let search = normalize_search(raw_search);
    let option_e = option_e_enabled();
    let execution = if option_e { "option_e" } else { "legacy" };
    let cursor = query
        .page_token
        .as_deref()
        .filter(|token| !token.is_empty())
        .map(|token| decode_cursor(token, sort, &search, execution))
        .transpose()?;

    // Option E grouping, availability and frontier require the evaluated graph
    // before the page can be ordered or sliced. The legacy/default authority
    // needs no second statement.
    let mut option_e_state = None;
    let mut preauthenticated = None;
    if option_e {
        let user = crate::auth::authenticate_claims(&state, &claims).await?;
        let validated = option_inputs::load_option_inputs(&state, user).await?;
        option_e_state = Some(OptionEProjection::build(&validated)?);
        preauthenticated = Some(user.id());
    }

    let (auth, active_count, list_names, rows) = query_page(
        &state,
        &claims,
        preauthenticated,
        option_e,
        option_e_state.as_ref(),
        search.as_str(),
        sort,
        page_size,
        cursor.as_ref(),
    )
    .await?;
    if option_e_state.is_none() {
        validate_auth(&claims, &auth)?;
    }
    let option_e_reasons = option_e_state
        .as_ref()
        .map(|projection| projection.reasons(&list_names));

    let mut rows = rows;
    let next_page_token = if rows.len() > page_size as usize {
        rows.truncate(page_size as usize);
        let last = rows.last().expect("non-empty page");
        Some(encode_cursor(&QueueCursor {
            sort: sort.to_string(),
            search,
            values: match sort {
                "position" => vec![
                    if option_e_state
                        .as_ref()
                        .map_or(last.is_blocked, |projection| {
                            !projection.candidates.contains(&last.id)
                        })
                    {
                        "1".into()
                    } else {
                        "0".into()
                    },
                    last.stored_position.to_string(),
                    last.id.to_string(),
                ],
                "title" => vec![last.title.clone(), last.id.to_string()],
                // Python's cursor values use ``datetime.isoformat()`` while the
                // response schema serializes ``Z``; keep the opaque token
                // byte-compatible with the oracle that issued earlier cursors.
                _ => vec![
                    last.created_at
                        .strip_suffix('Z')
                        .map(|value| format!("{value}+00:00"))
                        .unwrap_or_else(|| last.created_at.clone()),
                    last.id.to_string(),
                ],
            },
            execution: execution.to_string(),
        }))
    } else {
        None
    };

    let threads: Vec<ThreadListItem> = rows
        .into_iter()
        .map(|row| row.into_item(option_e_state.as_ref(), option_e_reasons.as_ref()))
        .collect::<Result<Vec<_>, ApiError>>()?;

    Ok(Json(ThreadListResponse {
        threads,
        next_page_token,
        active_count,
    }))
}

fn validate_auth(claims: &VerifiedAccessClaims, auth: &Option<AuthRow>) -> Result<(), ApiError> {
    let auth = auth
        .as_ref()
        .ok_or_else(|| ApiError(StatusCode::UNAUTHORIZED, "User not found".to_string()))?;
    if auth.revoked {
        return Err(ApiError(
            StatusCode::UNAUTHORIZED,
            "Token has been revoked".to_string(),
        ));
    }
    if claims.expected_epoch()? < auth.password_epoch {
        return Err(ApiError(
            StatusCode::UNAUTHORIZED,
            "Password changed; please sign in again.".to_string(),
        ));
    }
    Ok(())
}

#[derive(Debug, Deserialize)]
struct AuthRow {
    password_epoch: i64,
    revoked: bool,
}

#[derive(Debug, Deserialize)]
struct ListName {
    id: i32,
    name: String,
}

#[derive(Debug, Deserialize)]
struct MappingHealthRow {
    tracked_issue_count: i32,
    confirmed_issue_count: i32,
    needs_mapping_count: i32,
    needs_review_count: i32,
    metadata_missing_count: i32,
}

#[derive(Debug, Deserialize)]
struct PageRow {
    id: i32,
    title: String,
    format: String,
    issues_remaining: i32,
    queue_position: i32,
    stored_position: i32,
    status: String,
    last_activity_at: Option<String>,
    is_blocked: bool,
    total_issues: Option<i32>,
    next_issue_number: Option<String>,
    notes: Option<String>,
    created_at: String,
    manual_creator_credits: Value,
    tags: Vec<ThreadTag>,
    series_documents: Vec<Value>,
    health: Option<MappingHealthRow>,
}

impl PageRow {
    fn into_item(
        self,
        option_e: Option<&OptionEProjection>,
        reasons: Option<&HashMap<i32, Vec<String>>>,
    ) -> Result<ThreadListItem, ApiError> {
        let mut is_blocked = self.is_blocked;
        let mut blocking_reasons = Vec::new();
        let mut issues_remaining = self.issues_remaining;
        let mut next_unread_issue_number = self.next_issue_number;
        if let Some(projection) = option_e {
            is_blocked = !projection.candidates.contains(&self.id);
            blocking_reasons = reasons
                .and_then(|reasons| reasons.get(&self.id))
                .cloned()
                .unwrap_or_default();
            if is_blocked && blocking_reasons.is_empty() {
                blocking_reasons.push(
                    if projection
                        .frontiers
                        .get(&self.id)
                        .is_some_and(Option::is_some)
                    {
                        "Series is outside the active queue".to_string()
                    } else {
                        "No available unread issue".to_string()
                    },
                );
            }
            issues_remaining = projection.unread_counts.get(&self.id).copied().unwrap_or(0);
            next_unread_issue_number = projection
                .frontiers
                .get(&self.id)
                .copied()
                .flatten()
                .and_then(|issue_id| projection.issue_numbers.get(&issue_id).cloned());
        }
        Ok(ThreadListItem {
            id: self.id,
            title: self.title.clone(),
            format: normalize_format(&self.format),
            issues_remaining,
            queue_position: self.queue_position,
            status: self.status,
            last_activity_at: self.last_activity_at,
            is_blocked,
            blocking_reasons,
            total_issues: self.total_issues,
            next_unread_issue_number,
            notes: self.notes,
            created_at: self.created_at.clone(),
            comicvine_mapping: self.health.as_ref().map(|health| ComicVineMappingHealth {
                status: mapping_status(health, self.total_issues).to_string(),
                tracked_issue_count: health.tracked_issue_count,
                confirmed_issue_count: health.confirmed_issue_count,
                needs_mapping_count: health.needs_mapping_count,
                needs_review_count: health.needs_review_count,
                metadata_missing_count: health.metadata_missing_count,
            }),
            manual_creator_credits: match self.manual_creator_credits {
                Value::Array(values) => Value::Array(values),
                _ => Value::Array(Vec::new()),
            },
            tags: self.tags,
            series_metadata: series_metadata(&self.series_documents, &self.title),
        })
    }
}

fn mapping_status(health: &MappingHealthRow, total_issues: Option<i32>) -> &'static str {
    if health.tracked_issue_count == 0 || total_issues.is_none() {
        "not_applicable"
    } else if health.needs_review_count > 0 {
        "needs_review"
    } else if health.confirmed_issue_count == health.tracked_issue_count
        && health.tracked_issue_count > 0
        && health.metadata_missing_count == 0
    {
        "fully_mapped"
    } else if health.confirmed_issue_count > 0 {
        "partial"
    } else {
        "unresolved"
    }
}

fn normalize_format(format: &str) -> String {
    let trimmed = format.trim();
    match trimmed.to_ascii_lowercase().as_str() {
        "comic" | "comics" => "Comic".to_string(),
        "digital" => "Digital".to_string(),
        _ => trimmed.to_string(),
    }
}

fn cleaned_text(value: Option<&Value>) -> Option<String> {
    let text = value?.as_str()?;
    let collapsed = text.split_whitespace().collect::<Vec<_>>().join(" ");
    (!collapsed.is_empty()).then_some(collapsed)
}

fn publication_year(metadata: &serde_json::Map<String, Value>) -> Option<i32> {
    if let Some(value) = metadata.get("start_year") {
        let year = match value {
            Value::Number(number) => number.as_i64().and_then(|v| i32::try_from(v).ok()),
            Value::String(text)
                if text.trim().len() == 4 && text.trim().chars().all(|c| c.is_ascii_digit()) =>
            {
                text.trim().parse().ok()
            }
            _ => None,
        };
        if year.is_some_and(|year| (1000..=9999).contains(&year)) {
            return year;
        }
    }
    for field in ["cover_date", "store_date"] {
        let Some(text) = metadata.get(field).and_then(Value::as_str) else {
            continue;
        };
        if let Some(matched) = find_year(text) {
            return Some(matched);
        }
    }
    None
}

fn find_year(text: &str) -> Option<i32> {
    let bytes = text.as_bytes();
    let mut index = 0;
    while index + 4 <= bytes.len() {
        if let Some(window) = text.get(index..index + 4) {
            if window.bytes().all(|byte| byte.is_ascii_digit()) {
                if let Ok(year) = window.parse::<i32>() {
                    if (1900..=2099).contains(&year) {
                        return Some(year);
                    }
                }
            }
        }
        index += 1;
    }
    None
}

fn run_label(metadata: &serde_json::Map<String, Value>, title: &str) -> Option<String> {
    let normalized_title = title
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .case_fold()
        .collect::<String>();
    let mut candidates = Vec::new();
    if let Some(volume) = metadata.get("volume") {
        candidates.push(volume.get("name"));
    }
    candidates.push(metadata.get("volume_name"));
    candidates.push(metadata.get("name"));
    for candidate in candidates.into_iter().flatten() {
        if let Some(label) = cleaned_text(Some(candidate)) {
            if label.case_fold().collect::<String>() != normalized_title {
                return Some(label);
            }
        }
    }
    None
}

fn publisher(metadata: &serde_json::Map<String, Value>) -> Option<String> {
    match metadata.get("publisher") {
        Some(Value::Object(value)) => cleaned_text(value.get("name")),
        value => cleaned_text(value),
    }
}

fn series_metadata(documents: &[Value], title: &str) -> Option<QueueSeriesMetadata> {
    let metadata = documents.first()?.as_object()?;
    Some(QueueSeriesMetadata {
        year: publication_year(metadata),
        volume: run_label(metadata, title),
        publisher: publisher(metadata),
    })
}

/// One described blocker gate, detached from the evaluated snapshot.
struct BlockerGate {
    kind: String,
    origin: String,
    list_id: Option<i32>,
    issue_ids: Vec<i32>,
}

/// Evaluated Option E projection for the active queue rows.
struct OptionEProjection {
    candidates: HashSet<i32>,
    unread_counts: HashMap<i32, i32>,
    frontiers: HashMap<i32, Option<i32>>,
    issue_numbers: HashMap<i32, String>,
    issue_threads: HashMap<i32, i32>,
    thread_titles: HashMap<i32, String>,
    gates: HashMap<i32, Vec<BlockerGate>>,
}

impl OptionEProjection {
    fn build(
        validated: &crate::reading_constraints::ValidatedReadingInputs,
    ) -> Result<Self, ApiError> {
        let inputs = validated.inputs();
        let evaluated = reading_eligibility::evaluate(validated)?;
        let queued: HashSet<i32> = inputs
            .core
            .stored
            .iter()
            .filter(|row| row.queue_position > 0)
            .map(|row| row.thread_id)
            .collect();
        let candidates: HashSet<i32> = evaluated
            .iter()
            .filter(|(thread_id, state)| state.eligible && queued.contains(thread_id))
            .map(|(thread_id, _)| *thread_id)
            .collect();
        let mut unread_counts = HashMap::new();
        let mut issue_numbers = HashMap::new();
        let mut issue_threads = HashMap::new();
        let mut thread_titles = HashMap::new();
        for thread in &inputs.core.threads {
            thread_titles.insert(thread.id, thread.title.clone());
        }
        for issue in &inputs.core.issues {
            issue_numbers.insert(issue.id, issue.issue_number.clone());
            issue_threads.insert(issue.id, issue.thread_id);
            if issue.status != "read" && !inputs.excluded_issue_ids.contains(&issue.id) {
                *unread_counts.entry(issue.thread_id).or_insert(0) += 1;
            }
        }
        let mut frontiers = HashMap::new();
        let mut gates = HashMap::new();
        for (thread_id, state) in &evaluated {
            frontiers.insert(*thread_id, state.next_issue_id);
            gates.insert(
                *thread_id,
                crate::reading_blocker_projection::describe_blocker_gates(state.blockers.clone())
                    .into_iter()
                    .map(|gate| BlockerGate {
                        kind: gate.blocker.kind,
                        origin: gate.blocker.origin.unwrap_or_default(),
                        list_id: gate.blocker.list_id,
                        issue_ids: gate.described_issue_ids,
                    })
                    .collect(),
            );
        }
        Ok(Self {
            candidates,
            unread_counts,
            frontiers,
            issue_numbers,
            issue_threads,
            thread_titles,
            gates,
        })
    }

    fn reasons(&self, list_names: &[ListName]) -> HashMap<i32, Vec<String>> {
        let list_names: HashMap<i32, &str> = list_names
            .iter()
            .map(|list| (list.id, list.name.as_str()))
            .collect();
        let mut reasons = HashMap::new();
        for (thread_id, gates) in &self.gates {
            let mut thread_reasons = Vec::new();
            for gate in gates {
                let origin = blocker_origin(gate, &list_names);
                for issue_id in &gate.issue_ids {
                    let label = match (
                        self.issue_threads.get(issue_id),
                        self.issue_numbers.get(issue_id),
                    ) {
                        (Some(thread_id), Some(number)) => format!(
                            "{} #{}",
                            self.thread_titles
                                .get(thread_id)
                                .map(String::as_str)
                                .unwrap_or("Required series"),
                            number
                        ),
                        _ => "required issue".to_string(),
                    };
                    thread_reasons.push(format!("{origin}: waiting on {label}"));
                }
            }
            if self.frontiers.get(thread_id).copied().flatten().is_none() {
                thread_reasons.push("No available unread issue".to_string());
            }
            reasons.insert(*thread_id, thread_reasons);
        }
        reasons
    }
}

fn blocker_origin(gate: &BlockerGate, list_names: &HashMap<i32, &str>) -> String {
    if gate.kind == "prerequisite" {
        return if gate.origin == "reader" {
            "Reader prerequisite".to_string()
        } else {
            "Converted prerequisite".to_string()
        };
    }
    let kind = match gate.kind.as_str() {
        "strict_order" => "Strict order",
        "hold" => "Hold",
        "after_previous" => "Wait for previous",
        other => other,
    };
    let list = gate
        .list_id
        .and_then(|list_id| list_names.get(&list_id).copied())
        .unwrap_or("Reading List");
    format!("{kind} in {list}")
}

#[derive(Debug, Deserialize)]
struct PagePayload {
    auth: Option<AuthRow>,
    active_count: i32,
    list_names: Vec<ListName>,
    rows: Vec<PageRow>,
}

const THREADS_SQL_PREFIX: &str = r#"
WITH auth AS (
    SELECT u.id AS user_id,
           COALESCE(trunc(extract(epoch FROM u.password_changed_at))::bigint, 0) AS password_epoch,
           EXISTS(SELECT 1 FROM revoked_tokens r WHERE r.jti = $2) AS revoked
    FROM users u
    WHERE u.username = $1
    LIMIT 1
),
me AS (
    SELECT COALESCE($6::int, (SELECT user_id FROM auth WHERE NOT revoked AND password_epoch <= $3)) AS user_id
),
ranked AS (
    SELECT t.id,
           row_number() OVER (ORDER BY {blocked}, t.queue_position, t.id)::int AS display_position
    FROM threads t
    JOIN me ON t.user_id = me.user_id
    WHERE t.status = 'active'
),
page AS (
    SELECT t.id, t.title, t.format, t.queue_position, t.status,
           t.last_activity_at, t.is_blocked, t.total_issues, t.notes, t.created_at,
           t.manual_creator_credits,
           r.display_position,
           row_number() OVER (ORDER BY {order})::int AS page_ord,
           CASE WHEN t.total_issues IS NOT NULL
                THEN (SELECT count(*)::int FROM issues i
                      WHERE i.thread_id = t.id AND i.status = 'unread')
                ELSE t.issues_remaining END AS issues_remaining,
           (SELECT i.issue_number FROM issues i WHERE i.id = t.next_unread_issue_id) AS next_issue_number
    FROM threads t
    JOIN me ON t.user_id = me.user_id
    JOIN ranked r ON r.id = t.id
    WHERE t.status = 'active'
      AND ($4 = '' OR t.title ILIKE '%' || $4 || '%')
      {cursor}
    ORDER BY page_ord
    LIMIT $5
),
health AS (
    SELECT p.id AS thread_id,
           COALESCE(state.tracked_issue_count, 0)::int AS tracked_issue_count,
           COALESCE(state.confirmed_issue_count, 0)::int AS confirmed_issue_count,
           COALESCE(state.needs_mapping_count, 0)::int AS needs_mapping_count,
           COALESCE(state.needs_review_count, 0)::int AS needs_review_count,
           COALESCE(state.metadata_missing_count, 0)::int AS metadata_missing_count
    FROM page p
    LEFT JOIN (
        SELECT thread_state.thread_id,
               count(*)::int AS tracked_issue_count,
               (count(*) FILTER (WHERE thread_state.confirmed_count > 0))::int
                   AS confirmed_issue_count,
               (count(*) FILTER (WHERE thread_state.confirmed_count = 0))::int
                   AS needs_mapping_count,
               (count(*) FILTER (WHERE thread_state.confirmed_count > 1))::int
                   AS needs_review_count,
               (count(*) FILTER (WHERE thread_state.metadata_missing_count > 0))::int
                   AS metadata_missing_count
        FROM (
            SELECT i.id, i.thread_id,
                   count(ei.id) AS confirmed_count,
                   count(ei.id) FILTER (
                       WHERE COALESCE(ei.metadata_json->>'issue_number', '') = ''
                          OR COALESCE(ei.metadata_json->'volume'->>'name',
                                      ei.metadata_json->>'volume_name', '') = ''
                   ) AS metadata_missing_count
            FROM issues i
            LEFT JOIN issue_external_identity_mappings m
                   ON m.issue_id = i.id AND m.status = 'confirmed'
            LEFT JOIN external_identities ei
                   ON ei.id = m.external_identity_id AND ei.provider = 'comicvine'
            WHERE i.thread_id IN (SELECT id FROM page WHERE total_issues IS NOT NULL)
            GROUP BY i.id, i.thread_id
        ) thread_state
        GROUP BY thread_state.thread_id
    ) state ON state.thread_id = p.id
    WHERE p.total_issues IS NOT NULL
)
SELECT json_build_object(
    'auth', (SELECT json_build_object(
        'password_epoch', password_epoch,
        'revoked', revoked
    ) FROM auth),
    'active_count', (SELECT count(*)::int FROM threads t
                     JOIN me ON t.user_id = me.user_id
                     WHERE t.status = 'active' AND t.queue_position >= 1),
    'list_names', COALESCE((
        SELECT json_agg(json_build_object('id', l.id, 'name', l.name) ORDER BY l.id)
        FROM custom_cbl_lists l
        JOIN me ON l.user_id = me.user_id
    ), '[]'::json),
    'rows', COALESCE((
        SELECT json_agg(json_build_object(
            'id', p.id,
            'title', p.title,
            'format', p.format,
            'issues_remaining', p.issues_remaining,
            'queue_position', p.display_position,
            'stored_position', p.queue_position,
            'status', p.status,
            'last_activity_at', {activity_timestamp},
            'is_blocked', p.is_blocked,
            'total_issues', p.total_issues,
            'next_issue_number', p.next_issue_number,
            'notes', p.notes,
            'created_at', {created_timestamp},
            'manual_creator_credits', p.manual_creator_credits,
            'tags', COALESCE((
                SELECT json_agg(json_build_object(
                    'id', tg.id,
                    'name', tg.name,
                    'normalized_name', tg.normalized_name,
                    'scope', tg.scope,
                    'owner_user_id', tg.owner_user_id,
                    'color', tg.color,
                    'created_at', {tag_created_timestamp},
                    'updated_at', {tag_updated_timestamp}
                ) ORDER BY tg.scope DESC, tg.normalized_name, ta.target_type)
                FROM tag_assignments ta
                JOIN tags tg ON tg.id = ta.tag_id
                WHERE ta.target_type = 'Thread' AND ta.target_id = p.id
                  AND (tg.scope = 'global'
                       OR tg.owner_user_id = (SELECT user_id FROM me))
            ), '[]'::json),
            'series_documents', COALESCE((
                SELECT json_agg(ei.metadata_json ORDER BY m.confidence DESC NULLS LAST, ei.id)
                FROM thread_external_series_mappings m
                JOIN external_identities ei ON ei.id = m.external_identity_id
                WHERE m.thread_id = p.id AND m.status = 'confirmed'
            ), '[]'::json),
            'health', (SELECT json_build_object(
                'tracked_issue_count', h.tracked_issue_count,
                'confirmed_issue_count', h.confirmed_issue_count,
                'needs_mapping_count', h.needs_mapping_count,
                'needs_review_count', h.needs_review_count,
                'metadata_missing_count', h.metadata_missing_count
            ) FROM health h WHERE h.thread_id = p.id)
        ) ORDER BY p.page_ord)
        FROM page p
    ), '[]'::json)
)::text
"#;

fn iso_timestamp(column: &str) -> String {
    format!(
        "CASE WHEN {column} IS NULL THEN NULL \
         WHEN date_trunc('second', {column}) = {column} \
         THEN to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
         ELSE to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') END"
    )
}

#[allow(clippy::too_many_arguments)]
async fn query_page(
    state: &AppState,
    claims: &VerifiedAccessClaims,
    preauthenticated: Option<i32>,
    option_e: bool,
    projection: Option<&OptionEProjection>,
    search: &str,
    sort: &str,
    page_size: i64,
    cursor: Option<&QueueCursor>,
) -> Result<(Option<AuthRow>, i32, Vec<ListName>, Vec<PageRow>), ApiError> {
    // Reference both mode parameters unconditionally so the statement keeps a
    // stable bind count whether the Option E preview is active or not.
    let blocked = "(CASE WHEN $7::boolean THEN NOT (t.id = ANY($8::int[])) ELSE t.is_blocked END)";
    let order = match sort {
        "title" => "t.title, t.id".to_string(),
        "created" => "t.created_at DESC, t.id DESC".to_string(),
        _ => format!("({blocked}), t.queue_position, t.id"),
    };
    let (cursor_sql, cursor_bindings) = cursor_clause(sort, cursor);
    let sql = THREADS_SQL_PREFIX
        .replace("{order}", &order)
        .replace("{cursor}", &cursor_sql)
        .replace("{blocked}", blocked)
        .replace("{activity_timestamp}", &iso_timestamp("p.last_activity_at"))
        .replace("{created_timestamp}", &iso_timestamp("p.created_at"))
        .replace("{tag_created_timestamp}", &iso_timestamp("tg.created_at"))
        .replace("{tag_updated_timestamp}", &iso_timestamp("tg.updated_at"));

    let expected_epoch = claims.expected_epoch()?;
    let candidates: Vec<i32> = projection
        .map(|projection| {
            let mut ids: Vec<i32> = projection.candidates.iter().copied().collect();
            ids.sort_unstable();
            ids
        })
        .unwrap_or_default();
    let mut params = vec![
        Param::Text(claims.username().to_string()),
        Param::Text(claims.jti().to_string()),
        Param::BigInt(expected_epoch),
        Param::Text(search.to_string()),
        Param::BigInt(page_size + 1),
        Param::OptionalInt(preauthenticated),
        Param::Bool(option_e),
        Param::IntArray(candidates),
    ];
    params.extend(cursor_bindings);
    let bindings: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> =
        params.iter().map(Param::as_sql).collect();

    let connection = db::checkout(state).await?;
    PAGE_STATEMENTS_ISSUED.fetch_add(1, Ordering::Relaxed);
    let row = db::query_one_optional(state, connection, &sql, &bindings)
        .await?
        .ok_or_else(|| {
            ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "Internal Server Error".to_string(),
            )
        })?;
    let payload: String = row.try_get(0).map_err(db::query_error)?;
    let payload: PagePayload = serde_json::from_str(&payload).map_err(|_| {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Internal Server Error".to_string(),
        )
    })?;
    Ok((
        payload.auth,
        payload.active_count,
        payload.list_names,
        payload.rows,
    ))
}

enum Param {
    Text(String),
    Int(i32),
    BigInt(i64),
    Bool(bool),
    IntArray(Vec<i32>),
    OptionalInt(Option<i32>),
}

impl Param {
    fn as_sql(&self) -> &(dyn tokio_postgres::types::ToSql + Sync) {
        match self {
            Param::Text(value) => value,
            Param::Int(value) => value,
            Param::BigInt(value) => value,
            Param::Bool(value) => value,
            Param::IntArray(value) => value,
            Param::OptionalInt(value) => value,
        }
    }
}

fn cursor_clause(sort: &str, cursor: Option<&QueueCursor>) -> (String, Vec<Param>) {
    let Some(cursor) = cursor else {
        return (String::new(), Vec::new());
    };
    match sort {
        "position" => {
            let blocked = cursor.values[0] == "1";
            let position: i32 = cursor.values[1].parse().unwrap_or(0);
            let id: i32 = cursor.values[2].parse().unwrap_or(0);
            (
                "AND (NOT $9::boolean OR (CASE WHEN $10::boolean \
                 THEN ({blocked}) AND (t.queue_position, t.id) > ($11::int, $12::int) \
                 ELSE (((NOT ({blocked})) AND (t.queue_position, t.id) > ($11::int, $12::int)) \
                 OR ({blocked})) END))"
                    .to_string(),
                vec![
                    Param::Bool(true),
                    Param::Bool(blocked),
                    Param::Int(position),
                    Param::Int(id),
                ],
            )
        }
        "title" => {
            let title = cursor.values[0].clone();
            let id: i32 = cursor.values[1].parse().unwrap_or(0);
            (
                "AND (NOT $9::boolean OR (t.title, t.id) > ($10::text, $11::int))".to_string(),
                vec![Param::Bool(true), Param::Text(title), Param::Int(id)],
            )
        }
        _ => {
            let created = cursor.values[0].clone();
            let id: i32 = cursor.values[1].parse().unwrap_or(0);
            (
                "AND (NOT $9::boolean OR t.created_at < ($10::text)::timestamptz \
                 OR (t.created_at = ($10::text)::timestamptz AND t.id < $11::int))"
                    .to_string(),
                vec![Param::Bool(true), Param::Text(created), Param::Int(id)],
            )
        }
    }
}

/// OpenAPI document for the v2 reader threads collection.
#[derive(utoipa::OpenApi)]
#[openapi(
    paths(list_threads_documentation),
    components(schemas(
        ThreadListItem,
        ThreadListResponse,
        ThreadTag,
        ComicVineMappingHealth,
        QueueSeriesMetadata
    )),
    modifiers(&ThreadsSecurityAddon)
)]
pub struct ThreadsApi;

struct ThreadsSecurityAddon;
impl utoipa::Modify for ThreadsSecurityAddon {
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
    get,
    path = "/api/v2/threads",
    tag = "threads",
    params(
        ("search" = Option<String>, Query, description = "Case-insensitive title search"),
        ("sort" = Option<String>, Query, description = "position, title, or created"),
        ("page_size" = Option<i64>, Query, description = "1-200 rows per page (default 50)"),
        ("page_token" = Option<String>, Query, description = "Opaque continuation cursor")
    ),
    responses(
        (status = 200, description = "Owner-scoped active threads page", body = ThreadListResponse),
        (status = 400, description = "Invalid sort or page token"),
        (status = 401, description = "Not authenticated"),
        (status = 422, description = "Invalid bounds or retired collection_id")
    ),
    security(("HTTPBearer" = []))
)]
#[allow(dead_code)]
fn list_threads_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn cursor_round_trip_binds_search_sort_and_execution() {
        let cursor = QueueCursor {
            sort: "position".to_string(),
            search: "saga".to_string(),
            values: vec!["0".into(), "4".into(), "7".into()],
            execution: "legacy".to_string(),
        };
        let token = encode_cursor(&cursor);
        assert_eq!(
            decode_cursor(&token, "position", "saga", "legacy").expect("valid cursor"),
            cursor
        );
        assert_eq!(
            decode_cursor(&token, "title", "saga", "legacy")
                .unwrap_err()
                .1,
            "Queue page token does not match current search or sort"
        );
        assert_eq!(
            decode_cursor(&token, "position", "saga", "option_e")
                .unwrap_err()
                .1,
            "Queue ordering changed; reload the Queue"
        );
    }

    #[test]
    fn cursor_rejects_malformed_values() {
        let token =
            URL_SAFE_NO_PAD.encode(br#"{"search":"","sort":"position","values":["2","1","2"]}"#);
        assert_eq!(
            decode_cursor(&token, "position", "", "legacy")
                .unwrap_err()
                .1,
            "Invalid Queue page token values"
        );
        assert_eq!(
            decode_cursor("not-base64", "position", "", "legacy")
                .unwrap_err()
                .1,
            "Invalid Queue page token"
        );
    }

    #[test]
    fn series_metadata_uses_only_confirmed_values() {
        let documents = vec![json!({
            "start_year": "1995",
            "volume": {"name": "Uncanny X-Men"},
            "publisher": {"name": "Marvel"}
        })];
        let metadata = series_metadata(&documents, "X-Men").expect("metadata");
        assert_eq!(metadata.year, Some(1995));
        assert_eq!(metadata.volume.as_deref(), Some("Uncanny X-Men"));
        assert_eq!(metadata.publisher.as_deref(), Some("Marvel"));
        assert!(series_metadata(&[], "X-Men").is_none());
        assert!(series_metadata(&documents, "Uncanny X-Men")
            .expect("metadata")
            .volume
            .is_none());
    }

    #[test]
    fn format_normalization_matches_the_python_vocabulary() {
        assert_eq!(normalize_format("comics"), "Comic");
        assert_eq!(normalize_format(" digital "), "Digital");
        assert_eq!(normalize_format("Manga"), "Manga");
    }

    #[test]
    fn threads_openapi_documents_the_collection_read() {
        use utoipa::OpenApi;
        let document = serde_json::to_value(ThreadsApi::openapi()).expect("threads OpenAPI");
        let operation = &document["paths"]["/api/v2/threads"]["get"];
        assert_eq!(operation["operationId"], "list_threads_documentation");
        let response = &operation["responses"]["200"]["content"]["application/json"]["schema"];
        assert_eq!(response["$ref"], "#/components/schemas/ThreadListResponse");
    }

    #[test]
    fn checked_in_openapi_contract_is_current() {
        use utoipa::OpenApi;
        let checked_in = include_str!("../../../native/contracts/threads-v2.openapi.json");
        let generated = ThreadsApi::openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document");
        assert_eq!(
            checked_in.trim_end(),
            generated.trim_end(),
            "Regenerate native/contracts/threads-v2.openapi.json with \
             cargo run --example threads_openapi"
        );
    }
}
