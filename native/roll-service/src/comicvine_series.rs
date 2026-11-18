//! Set-based native ComicVine series import.
//!
//! The Python implementation adopts each roster row through the shared provider
//! adoption primitive. This module preserves those outcomes and side effects
//! while loading, inserting, and linking the whole roster in bounded batch SQL.

use crate::{
    auth::AuthenticatedUser,
    comicvine_repair::{normalize_roster_issue_metadata, provider_response},
    comicvine_v2::{
        fetch_provider_roster, insert_into_reading_order, owned_reading_order, provider_failure,
        provider_key, resolve_anchored_position, series_import_error, volume_name,
        ImportSeriesIssueResult, ImportSeriesRequest, ImportSeriesResponse,
    },
    db,
    issue_service::refresh_blocked_threads,
    ApiError, AppState,
};
use axum::{http::StatusCode, Json};
use serde_json::{json, Value};
use std::{cmp::Ordering, collections::HashMap, sync::Arc};
use tokio_postgres::Transaction;

const ADOPTION_EVIDENCE_SOURCE: &str = "comicvine_issue_adoption";

#[derive(Debug, Clone)]
struct RosterIssue {
    comicvine_issue_id: i32,
    issue_number: String,
    external_url: Option<String>,
    metadata: Value,
}

#[derive(Debug, Clone, Copy)]
enum IssueLocator {
    Existing(i32),
    Planned(usize),
}

#[derive(Debug)]
struct PlannedIssue {
    id: Option<i32>,
    issue_number: String,
    original_position: i32,
    position: i32,
    status: String,
    confirmed_comicvine_id: Option<i32>,
}

#[derive(Debug)]
struct PlannedResult {
    comicvine_issue_id: i32,
    issue_number: String,
    issue: IssueLocator,
    outcome: &'static str,
    conflict_detail: Option<String>,
}

#[derive(Debug)]
struct ExistingConfirmed {
    issue_id: i32,
    thread_id: i32,
}

/// Parse an ordinary positive decimal label without imposing a machine-integer
/// limit on provider numbering. Leading zeroes and all irregular labels retain
/// the reader-controlled placement fallback used by Python.
fn ordinary_number(value: &str) -> Option<&str> {
    let mut bytes = value.bytes();
    if !matches!(bytes.next(), Some(b'1'..=b'9')) || !bytes.all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    Some(value)
}

fn compare_ordinary(left: &str, right: &str) -> Ordering {
    left.len().cmp(&right.len()).then_with(|| left.cmp(right))
}

/// Merge one new numeric label into canonical thread order. This is the pure
/// equivalent of `natural_issue_order` for the sequential adoption path.
fn natural_issue_order(existing: &[String], incoming: &str) -> Option<Vec<String>> {
    ordinary_number(incoming)?;
    let existing_numbered: Vec<&str> = existing
        .iter()
        .filter_map(|label| ordinary_number(label))
        .collect();

    if existing_numbered.len() == existing.len() {
        let mut labels = existing.to_vec();
        labels.push(incoming.to_owned());
        labels.sort_by(|left, right| compare_ordinary(left, right));
        return Some(labels);
    }

    if existing_numbered.is_empty()
        || existing_numbered
            .windows(2)
            .any(|pair| compare_ordinary(pair[0], pair[1]) == Ordering::Greater)
    {
        return None;
    }

    let mut labels = existing.to_vec();
    let insertion = labels.iter().position(|label| {
        ordinary_number(label)
            .is_some_and(|number| compare_ordinary(number, incoming) == Ordering::Greater)
    });
    match insertion {
        Some(index) => labels.insert(index, incoming.to_owned()),
        None => labels.push(incoming.to_owned()),
    }
    Some(labels)
}

fn parse_roster(rows: &[Value]) -> Vec<RosterIssue> {
    rows.iter()
        .enumerate()
        .filter_map(|(index, row)| {
            // Python accepts provider integer IDs, not string-coerced identifiers.
            let comicvine_issue_id = row
                .get("id")
                .and_then(Value::as_i64)
                .and_then(|id| i32::try_from(id).ok())?;
            let issue_number = match row.get("issue_number") {
                None | Some(Value::Null) => (index + 1).to_string(),
                Some(Value::String(value)) => value.clone(),
                Some(Value::Number(value)) => value.to_string(),
                Some(Value::Bool(value)) => {
                    if *value {
                        "True".to_owned()
                    } else {
                        "False".to_owned()
                    }
                }
                Some(value) => value.to_string(),
            };
            let external_url = row
                .get("site_detail_url")
                .and_then(Value::as_str)
                .map(str::to_owned);
            Some(RosterIssue {
                comicvine_issue_id,
                issue_number,
                external_url,
                metadata: normalize_roster_issue_metadata(row),
            })
        })
        .collect()
}

async fn provider_series(volume_id: i32) -> Result<(String, Vec<Value>), ApiError> {
    let external_id = volume_id.to_string();
    if let Some((series, roster)) = crate::test_support::lookup_test_volume_roster(&external_id) {
        let series_name = series
            .get("name")
            .and_then(Value::as_str)
            .filter(|name| !name.trim().is_empty())
            .map(str::to_owned)
            .ok_or_else(|| {
                series_import_error(
                    StatusCode::BAD_GATEWAY,
                    "provider_failure",
                    "ComicVine series has no name",
                )
            })?;
        return Ok((series_name, roster));
    }

    let Some(key) = provider_key() else {
        return Err(series_import_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "provider_unavailable",
            "ComicVine is not configured on this server",
        ));
    };
    let volume = provider_response(&format!("volume/4050-{volume_id}"), "", &key)
        .await
        .map_err(|error| provider_failure(error, "ComicVine series"))?;
    if !volume.get("results").is_some_and(Value::is_object) {
        return Err(series_import_error(
            StatusCode::BAD_GATEWAY,
            "provider_failure",
            "ComicVine series response did not contain valid data",
        ));
    }
    let series_name = volume_name(&volume).ok_or_else(|| {
        series_import_error(
            StatusCode::BAD_GATEWAY,
            "provider_failure",
            "ComicVine series has no name",
        )
    })?;
    let roster = fetch_provider_roster(volume_id, &key)
        .await
        .map_err(|error| provider_failure(error, "series issues"))?;
    Ok((series_name, roster))
}

fn locator_issue_id(planned: &[PlannedIssue], locator: IssueLocator) -> Option<i32> {
    match locator {
        IssueLocator::Existing(issue_id) => Some(issue_id),
        IssueLocator::Planned(index) => planned.get(index).and_then(|issue| issue.id),
    }
}

/// Upsert only identities that need a new local mapping. Existing rich metadata
/// is deliberately untouched: sparse roster facts are stored on first creation,
/// never substituted for a previously hydrated document on a retry.
async fn upsert_roster_identities(
    tx: &Transaction<'_>,
    identities: &HashMap<i32, RosterIssue>,
) -> Result<HashMap<i32, i32>, ApiError> {
    if identities.is_empty() {
        return Ok(HashMap::new());
    }
    let mut specs: Vec<&RosterIssue> = identities.values().collect();
    specs.sort_by_key(|issue| issue.comicvine_issue_id);
    let input = Value::Array(
        specs
            .into_iter()
            .map(|issue| {
                json!({
                    "external_id": issue.comicvine_issue_id.to_string(),
                    "external_url": issue.external_url,
                    "metadata_json": issue.metadata,
                })
            })
            .collect(),
    );
    let rows = tx
        .query(
            "INSERT INTO external_identities \
                (provider, entity_type, external_id, external_url, metadata_json, created_at, updated_at) \
             SELECT 'comicvine', 'issue', v.external_id, v.external_url, \
                    COALESCE(v.metadata_json, '{}'::jsonb)::json, now(), now() \
             FROM jsonb_to_recordset($1::jsonb) \
                  AS v(external_id text, external_url text, metadata_json jsonb) \
             ON CONFLICT ON CONSTRAINT uq_external_identity_provider_entity \
             DO UPDATE SET \
                 external_url = COALESCE(EXCLUDED.external_url, external_identities.external_url), \
                 updated_at = CASE WHEN EXCLUDED.external_url IS NOT NULL \
                                   THEN now() ELSE external_identities.updated_at END \
             RETURNING id, external_id",
            &[&input],
        )
        .await
        .map_err(db::query_error)?;
    let mut result = HashMap::new();
    for row in rows {
        let external_id: String = row.get(1);
        if let Ok(comicvine_issue_id) = external_id.parse::<i32>() {
            result.insert(comicvine_issue_id, row.get(0));
        }
    }
    Ok(result)
}

async fn persist_positions_and_issues(
    tx: &Transaction<'_>,
    thread_id: i32,
    planned: &mut [PlannedIssue],
) -> Result<(), ApiError> {
    let position_updates: Vec<(i32, i32)> = planned
        .iter()
        .filter_map(|issue| {
            issue.id.and_then(|id| {
                (issue.original_position != issue.position).then_some((id, issue.position))
            })
        })
        .collect();
    let has_new = planned.iter().any(|issue| issue.id.is_none());
    if has_new || !position_updates.is_empty() {
        tx.batch_execute("SET CONSTRAINTS uq_issue_thread_position DEFERRED")
            .await
            .map_err(db::query_error)?;
    }
    if !position_updates.is_empty() {
        let ids: Vec<i32> = position_updates.iter().map(|(id, _)| *id).collect();
        let positions: Vec<i32> = position_updates
            .iter()
            .map(|(_, position)| *position)
            .collect();
        tx.execute(
            "UPDATE issues i SET position = v.position \
             FROM (SELECT unnest($2::int[]) AS id, unnest($3::int[]) AS position) v \
             WHERE i.id = v.id AND i.thread_id = $1",
            &[&thread_id, &ids, &positions],
        )
        .await
        .map_err(db::query_error)?;
    }
    if !has_new {
        return Ok(());
    }

    let input = Value::Array(
        planned
            .iter()
            .filter(|issue| issue.id.is_none())
            .map(|issue| {
                json!({
                    "issue_number": issue.issue_number,
                    "position": issue.position,
                })
            })
            .collect(),
    );
    let rows = tx
        .query(
            "INSERT INTO issues (thread_id, issue_number, position, status, created_at) \
             SELECT $1, v.issue_number, v.position, 'unread', now() \
             FROM jsonb_to_recordset($2::jsonb) WITH ORDINALITY \
                  AS v(issue_number text, position integer, ordinal bigint) \
             ORDER BY v.ordinal \
             RETURNING id, issue_number",
            &[&thread_id, &input],
        )
        .await
        .map_err(db::query_error)?;
    let ids_by_number: HashMap<String, i32> = rows
        .into_iter()
        .map(|row| (row.get::<_, String>(1), row.get::<_, i32>(0)))
        .collect();
    for issue in planned.iter_mut().filter(|issue| issue.id.is_none()) {
        issue.id = Some(*ids_by_number.get(&issue.issue_number).ok_or_else(|| {
            ApiError::Internal("Batch issue insert did not return an adopted issue".to_owned())
        })?);
    }
    Ok(())
}

async fn confirm_roster_mappings(
    tx: &Transaction<'_>,
    planned: &[PlannedIssue],
    mapping_specs: &[(i32, IssueLocator)],
    identity_ids: &HashMap<i32, i32>,
) -> Result<(), ApiError> {
    if mapping_specs.is_empty() {
        return Ok(());
    }
    let mut input = Vec::with_capacity(mapping_specs.len());
    for (comicvine_issue_id, locator) in mapping_specs {
        let issue_id = locator_issue_id(planned, *locator).ok_or_else(|| {
            ApiError::Internal("Adopted issue has no persisted identifier".to_owned())
        })?;
        let external_identity_id = identity_ids.get(comicvine_issue_id).ok_or_else(|| {
            ApiError::Internal("Adopted identity has no persisted identifier".to_owned())
        })?;
        input.push(json!({
            "issue_id": issue_id,
            "external_identity_id": external_identity_id,
        }));
    }
    tx.execute(
        "INSERT INTO issue_external_identity_mappings \
            (issue_id, external_identity_id, status, evidence_source, evidence_json, \
             confidence, created_at, updated_at) \
         SELECT v.issue_id, v.external_identity_id, 'confirmed', $2, '{}'::json, \
                1.0, now(), now() \
         FROM jsonb_to_recordset($1::jsonb) \
              AS v(issue_id integer, external_identity_id integer) \
         ON CONFLICT ON CONSTRAINT uq_issue_external_identity_mapping \
         DO UPDATE SET status = 'confirmed', evidence_source = $2, confidence = 1.0, \
                       rejection_reason = NULL, updated_at = now()",
        &[&Value::Array(input), &ADOPTION_EVIDENCE_SOURCE],
    )
    .await
    .map_err(db::query_error)?;
    Ok(())
}

/// `POST /api/v2/comicvine/series:import`.
pub(crate) async fn import_series(
    state: Arc<AppState>,
    user: AuthenticatedUser,
    request: ImportSeriesRequest,
) -> Result<(StatusCode, Json<ImportSeriesResponse>), ApiError> {
    if request.comicvine_volume_id <= 0 {
        return Err(ApiError::Unprocessable(
            "Invalid comicvine_volume_id".to_owned(),
        ));
    }
    if request.already_read_count < 0 {
        return Err(ApiError::Unprocessable(
            "Invalid already_read_count".to_owned(),
        ));
    }
    for id in [
        request.reading_order_id,
        request.anchor_before_thread_id,
        request.anchor_after_thread_id,
    ]
    .into_iter()
    .flatten()
    {
        if id <= 0 {
            return Err(ApiError::Unprocessable(
                "Invalid reading order anchor".to_owned(),
            ));
        }
    }

    let volume_id = request.comicvine_volume_id;
    let (series_name, provider_rows) = provider_series(volume_id).await?;
    if provider_rows.is_empty() {
        return Err(series_import_error(
            StatusCode::BAD_REQUEST,
            "no_issues",
            "ComicVine series has no issues",
        ));
    }
    if request.already_read_count as usize > provider_rows.len() {
        return Err(series_import_error(
            StatusCode::BAD_REQUEST,
            "invalid_already_read_count",
            format!(
                "already_read_count cannot exceed the series issue count ({})",
                provider_rows.len()
            ),
        ));
    }
    let roster = parse_roster(&provider_rows);

    let mut connection = db::checkout(&state).await?;
    let tx = connection.transaction().await.map_err(db::query_error)?;
    if let Some(order_id) = request.reading_order_id {
        owned_reading_order(&tx, user.id(), order_id).await?;
    }
    let external_volume_id = volume_id.to_string();
    let reused_thread = tx
        .query_opt(
            "SELECT t.id, t.status, t.next_unread_issue_id, t.total_issues \
             FROM threads t \
             JOIN thread_external_series_mappings m ON m.thread_id = t.id \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE t.user_id = $1 AND m.status = 'confirmed' \
               AND e.entity_type = 'series' AND e.provider = 'comicvine' \
               AND e.external_id = $2 ORDER BY m.id LIMIT 1 FOR UPDATE OF t",
            &[&user.id(), &external_volume_id],
        )
        .await
        .map_err(db::query_error)?;
    let thread_created = reused_thread.is_none();
    let (thread_id, initial_status, initial_next_unread, initial_total) = match reused_thread {
        Some(row) => (
            row.get(0),
            row.get::<_, String>(1),
            row.get::<_, Option<i32>>(2),
            row.get::<_, Option<i32>>(3),
        ),
        None => {
            let next_position: i32 = tx
                .query_one(
                    "SELECT COALESCE(MAX(queue_position), 0) + 1 FROM threads WHERE user_id = $1",
                    &[&user.id()],
                )
                .await
                .map_err(db::query_error)?
                .get(0);
            let id = tx
                .query_one(
                    "INSERT INTO threads \
                        (title, format, issues_remaining, total_issues, queue_position, status, \
                         user_id, created_at, is_test, is_blocked) \
                     VALUES ($1, 'Comic', 0, 0, $2, 'active', $3, now(), false, false) \
                     RETURNING id",
                    &[&series_name.trim(), &next_position, &user.id()],
                )
                .await
                .map_err(db::query_error)?
                .get(0);
            (id, "active".to_owned(), None, Some(0))
        }
    };

    let series_identity_id: i32 = tx
        .query_one(
            "INSERT INTO external_identities \
                (provider, entity_type, external_id, external_url, metadata_json, created_at, updated_at) \
             VALUES ('comicvine', 'series', $1, $2, '{}'::json, now(), now()) \
             ON CONFLICT ON CONSTRAINT uq_external_identity_provider_entity \
             DO UPDATE SET external_url = EXCLUDED.external_url, updated_at = now() \
             RETURNING id",
            &[
                &external_volume_id,
                &format!("https://comicvine.gamespot.com/volume/4050-{volume_id}/"),
            ],
        )
        .await
        .map_err(db::query_error)?
        .get(0);
    tx.execute(
        "INSERT INTO thread_external_series_mappings \
            (thread_id, external_identity_id, status, evidence_source, confidence, \
             created_at, updated_at) \
         VALUES ($1, $2, 'confirmed', 'comicvine_series_import', 1.0, now(), now()) \
         ON CONFLICT ON CONSTRAINT uq_thread_external_series_mapping \
         DO UPDATE SET status = 'confirmed', confidence = 1.0, updated_at = now()",
        &[&thread_id, &series_identity_id],
    )
    .await
    .map_err(db::query_error)?;

    let existing_rows = tx
        .query(
            "SELECT id, issue_number, position, status FROM issues \
             WHERE thread_id = $1 ORDER BY position, id FOR UPDATE",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    let existing_issue_ids: Vec<i32> = existing_rows.iter().map(|row| row.get(0)).collect();
    let external_ids: Vec<String> = roster
        .iter()
        .map(|issue| issue.comicvine_issue_id.to_string())
        .collect();
    let confirmed_rows = tx
        .query(
            "SELECT e.external_id, i.id, i.thread_id \
             FROM external_identities e \
             JOIN issue_external_identity_mappings m ON m.external_identity_id = e.id \
             JOIN issues i ON i.id = m.issue_id \
             JOIN threads t ON t.id = i.thread_id \
             WHERE e.provider = 'comicvine' AND e.entity_type = 'issue' \
               AND e.external_id = ANY($1::text[]) AND m.status = 'confirmed' \
               AND t.user_id = $2 ORDER BY e.external_id, i.id",
            &[&external_ids, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let mut existing_confirmed: HashMap<i32, ExistingConfirmed> = HashMap::new();
    for row in confirmed_rows {
        let external_id: String = row.get(0);
        if let Ok(comicvine_issue_id) = external_id.parse::<i32>() {
            existing_confirmed
                .entry(comicvine_issue_id)
                .or_insert_with(|| ExistingConfirmed {
                    issue_id: row.get(1),
                    thread_id: row.get(2),
                });
        }
    }

    let target_confirmed_rows = tx
        .query(
            "SELECT m.issue_id, e.external_id \
             FROM issue_external_identity_mappings m \
             JOIN external_identities e ON e.id = m.external_identity_id \
             WHERE m.issue_id = ANY($1::int[]) AND m.status = 'confirmed' \
               AND e.provider = 'comicvine' ORDER BY m.issue_id, e.external_id",
            &[&existing_issue_ids],
        )
        .await
        .map_err(db::query_error)?;
    let mut target_confirmed: HashMap<i32, i32> = HashMap::new();
    for row in target_confirmed_rows {
        if let Ok(comicvine_issue_id) = row.get::<_, String>(1).parse::<i32>() {
            target_confirmed
                .entry(row.get(0))
                .or_insert(comicvine_issue_id);
        }
    }

    let mut planned: Vec<PlannedIssue> = existing_rows
        .iter()
        .map(|row| {
            let id = row.get(0);
            PlannedIssue {
                id: Some(id),
                issue_number: row.get(1),
                original_position: row.get(2),
                position: row.get(2),
                status: row.get(3),
                confirmed_comicvine_id: target_confirmed.get(&id).copied(),
            }
        })
        .collect();
    let mut planned_by_number: HashMap<String, usize> = planned
        .iter()
        .enumerate()
        .map(|(index, issue)| (issue.issue_number.clone(), index))
        .collect();
    let mut confirmed_during_import: HashMap<i32, IssueLocator> = HashMap::new();
    let mut identities_to_upsert: HashMap<i32, RosterIssue> = HashMap::new();
    let mut mapping_specs: Vec<(i32, IssueLocator)> = Vec::new();
    let mut planned_results = Vec::with_capacity(roster.len());

    // Pure in-memory adoption planning. No SQL is executed inside this loop.
    for issue in roster {
        let comicvine_issue_id = issue.comicvine_issue_id;
        if let Some(existing) = existing_confirmed.get(&comicvine_issue_id) {
            if existing.thread_id != thread_id {
                planned_results.push(PlannedResult {
                    comicvine_issue_id,
                    issue_number: issue.issue_number,
                    issue: IssueLocator::Existing(existing.issue_id),
                    outcome: "conflict",
                    conflict_detail: Some(format!(
                        "ComicVine issue {comicvine_issue_id} is already confirmed on issue {} of thread {}",
                        existing.issue_id, existing.thread_id
                    )),
                });
            } else {
                planned_results.push(PlannedResult {
                    comicvine_issue_id,
                    issue_number: issue.issue_number,
                    issue: IssueLocator::Existing(existing.issue_id),
                    outcome: "reused",
                    conflict_detail: None,
                });
            }
            continue;
        }
        if let Some(locator) = confirmed_during_import.get(&comicvine_issue_id) {
            planned_results.push(PlannedResult {
                comicvine_issue_id,
                issue_number: issue.issue_number,
                issue: *locator,
                outcome: "reused",
                conflict_detail: None,
            });
            continue;
        }

        identities_to_upsert
            .entry(comicvine_issue_id)
            .or_insert_with(|| issue.clone());
        let (locator, outcome, conflict_detail) =
            if let Some(index) = planned_by_number.get(&issue.issue_number).copied() {
                let locator = if planned[index].id.is_some() {
                    IssueLocator::Existing(planned[index].id.unwrap_or_default())
                } else {
                    IssueLocator::Planned(index)
                };
                if let Some(confirmed_id) = planned[index].confirmed_comicvine_id {
                    if confirmed_id != comicvine_issue_id {
                        (
                            locator,
                            "conflict",
                            Some("issue already has a confirmed comicvine identity".to_owned()),
                        )
                    } else {
                        (locator, "reused", None)
                    }
                } else {
                    (locator, "reused", None)
                }
            } else {
                let mut canonical_indices: Vec<usize> = (0..planned.len()).collect();
                canonical_indices.sort_by_key(|planned_index| {
                    let planned_issue = &planned[*planned_index];
                    (planned_issue.position, planned_issue.id)
                });
                let existing_labels: Vec<String> = canonical_indices
                    .into_iter()
                    .map(|planned_index| planned[planned_index].issue_number.clone())
                    .collect();
                let order = natural_issue_order(&existing_labels, &issue.issue_number);
                let next_position = planned
                    .iter()
                    .map(|planned_issue| planned_issue.position)
                    .max()
                    .unwrap_or(0)
                    + 1;
                let position = order.as_ref().map_or(next_position, |labels| {
                    labels
                        .iter()
                        .position(|label| label == &issue.issue_number)
                        .map_or(next_position, |index| index as i32 + 1)
                });
                let index = planned.len();
                planned.push(PlannedIssue {
                    id: None,
                    issue_number: issue.issue_number.clone(),
                    original_position: 0,
                    position,
                    status: "unread".to_owned(),
                    confirmed_comicvine_id: None,
                });
                planned_by_number.insert(issue.issue_number.clone(), index);
                if let Some(labels) = order {
                    for (position, label) in labels.into_iter().enumerate() {
                        if let Some(planned_index) = planned_by_number.get(&label) {
                            planned[*planned_index].position = position as i32 + 1;
                        }
                    }
                }
                (IssueLocator::Planned(index), "created", None)
            };

        if conflict_detail.is_none() {
            if let IssueLocator::Planned(index) = locator {
                planned[index].confirmed_comicvine_id = Some(comicvine_issue_id);
            }
            mapping_specs.push((comicvine_issue_id, locator));
            confirmed_during_import.insert(comicvine_issue_id, locator);
        }
        planned_results.push(PlannedResult {
            comicvine_issue_id,
            issue_number: issue.issue_number,
            issue: locator,
            outcome,
            conflict_detail,
        });
    }

    let identity_ids = upsert_roster_identities(&tx, &identities_to_upsert).await?;
    persist_positions_and_issues(&tx, thread_id, &mut planned).await?;
    confirm_roster_mappings(&tx, &planned, &mapping_specs, &identity_ids).await?;

    let mut ordered_indices: Vec<usize> = (0..planned.len()).collect();
    ordered_indices.sort_by_key(|index| {
        let issue = &planned[*index];
        (issue.position, issue.id)
    });
    let read_count = (request.already_read_count as usize).min(ordered_indices.len());
    let read_ids: Vec<i32> = ordered_indices
        .iter()
        .take(read_count)
        .filter_map(|index| planned[*index].id)
        .collect();
    if !read_ids.is_empty() {
        tx.execute(
            "UPDATE issues SET status = 'read', read_at = now() \
             WHERE thread_id = $1 AND id = ANY($2::int[])",
            &[&thread_id, &read_ids],
        )
        .await
        .map_err(db::query_error)?;
    }
    for index in ordered_indices.iter().take(read_count) {
        planned[*index].status = "read".to_owned();
    }

    let total_issues = planned.len() as i32;
    let issues_remaining = planned
        .iter()
        .filter(|issue| issue.status == "unread")
        .count() as i32;
    let next_unread = ordered_indices.iter().find_map(|index| {
        let issue = &planned[*index];
        (issue.status == "unread").then_some(issue.id).flatten()
    });
    let reading_progress = if issues_remaining == 0 {
        "completed"
    } else if issues_remaining == total_issues {
        "not_started"
    } else {
        "in_progress"
    };
    let derived_status = if next_unread.is_none() {
        "completed"
    } else {
        "active"
    };

    let created_count = planned_results
        .iter()
        .filter(|result| result.outcome == "created")
        .count() as i32;
    // Provider adoption reactivates a previously completed series at the head
    // of the active queue before the final personal-progress projection.
    if created_count > 0
        && initial_next_unread.is_none()
        && initial_total.is_some()
        && initial_status == "completed"
    {
        tx.execute(
            "UPDATE threads SET queue_position = queue_position + 1 \
             WHERE user_id = $1 AND status = 'active'",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
        tx.execute(
            "UPDATE threads SET queue_position = 1 WHERE id = $1 AND user_id = $2",
            &[&thread_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?;
    }
    if created_count > 0 {
        tx.execute(
            "INSERT INTO events (type, timestamp, thread_id) \
             SELECT 'issues_created', now(), $1 FROM generate_series(1, $2)",
            &[&thread_id, &created_count],
        )
        .await
        .map_err(db::query_error)?;
    }

    tx.execute(
        "UPDATE threads SET total_issues = $2, issues_remaining = $3, \
            next_unread_issue_id = $4, reading_progress = $5, \
            status = CASE WHEN status = 'excluded' THEN status ELSE $6 END, \
            queue_position_is_manual = CASE \
                WHEN status <> 'excluded' AND $6 = 'completed' THEN false \
                ELSE queue_position_is_manual END, \
            is_blocked = CASE WHEN $3 = 0 THEN false ELSE is_blocked END \
         WHERE id = $1 AND user_id = $7",
        &[
            &thread_id,
            &total_issues,
            &issues_remaining,
            &next_unread,
            &reading_progress,
            &derived_status,
            &user.id(),
        ],
    )
    .await
    .map_err(db::query_error)?;
    refresh_blocked_threads(&tx, user.id()).await?;

    let mut issue_results = Vec::with_capacity(planned_results.len());
    let mut issues_adopted = 0;
    let mut issues_skipped = 0;
    let mut issues_conflict = 0;
    for result in planned_results {
        match result.outcome {
            "created" => issues_adopted += 1,
            "reused" => issues_skipped += 1,
            "conflict" => issues_conflict += 1,
            _ => {}
        }
        issue_results.push(ImportSeriesIssueResult {
            comicvine_issue_id: result.comicvine_issue_id,
            issue_number: Some(result.issue_number),
            issue_id: locator_issue_id(&planned, result.issue),
            outcome: result.outcome.to_owned(),
            hydration: "not_attempted".to_owned(),
            conflict_detail: result.conflict_detail,
        });
    }

    let mut response = ImportSeriesResponse {
        thread_id,
        series_name,
        comicvine_volume_id: volume_id,
        total_issues_in_series: provider_rows.len() as i32,
        issues_adopted,
        issues_skipped,
        issues_conflict,
        issue_results,
        reading_order_id: None,
        position: None,
        total_items: None,
        thread_created,
    };
    if let Some(order_id) = request.reading_order_id {
        let items = tx
            .query(
                "SELECT thread_id, position FROM reading_order_items \
                 WHERE reading_order_id = $1 ORDER BY position, id",
                &[&order_id],
            )
            .await
            .map_err(db::query_error)?;
        let mut positions = HashMap::new();
        for row in &items {
            positions.insert(row.get::<_, i32>(0), row.get::<_, i32>(1));
        }
        let target = resolve_anchored_position(
            &positions,
            request.anchor_before_thread_id,
            request.anchor_after_thread_id,
            items.len(),
        );
        insert_into_reading_order(&tx, order_id, thread_id, target).await?;
        response.reading_order_id = Some(order_id);
        response.position = Some(target);
        response.total_items = Some(items.len() as i32 + 1);
    }
    tx.commit().await.map_err(db::query_error)?;
    Ok((StatusCode::CREATED, Json(response)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn natural_order_handles_numeric_mixed_and_irregular_series() {
        assert_eq!(
            natural_issue_order(&["33".to_owned(), "34".to_owned()], "2"),
            Some(vec!["2".to_owned(), "33".to_owned(), "34".to_owned()])
        );
        assert_eq!(
            natural_issue_order(
                &["1".to_owned(), "Annual 1".to_owned(), "3".to_owned()],
                "2"
            ),
            Some(vec![
                "1".to_owned(),
                "Annual 1".to_owned(),
                "2".to_owned(),
                "3".to_owned(),
            ])
        );
        assert_eq!(
            natural_issue_order(&["1".to_owned(), "3".to_owned()], "Annual 2"),
            None
        );
        assert_eq!(natural_issue_order(&["Annual 1".to_owned()], "2"), None);
        assert_eq!(
            natural_issue_order(&["1".to_owned()], "999999999999999999999999"),
            Some(vec!["1".to_owned(), "999999999999999999999999".to_owned()])
        );
    }

    fn import_request(volume_id: i32, already_read_count: i32) -> ImportSeriesRequest {
        ImportSeriesRequest {
            comicvine_volume_id: volume_id,
            reading_order_id: None,
            anchor_before_thread_id: None,
            anchor_after_thread_id: None,
            already_read_count,
        }
    }

    async fn database_fixture() -> (
        Arc<AppState>,
        tokio::sync::MutexGuard<'static, ()>,
        deadpool_postgres::Object,
    ) {
        let state = crate::test_support::test_state(2)
            .await
            .expect("disposable PostgreSQL required");
        let guard = crate::test_support::reset_for_test(&state).await;
        let connection = state.pool.get().await.expect("database connection");
        connection
            .execute(
                "INSERT INTO users (id, username, created_at) VALUES (1, 'series-owner', now())",
                &[],
            )
            .await
            .expect("seed owner");
        (state, guard, connection)
    }

    #[tokio::test]
    async fn fresh_import_is_natural_idempotent_and_preserves_rich_metadata() {
        let (state, _guard, connection) = database_fixture().await;
        let volume_id = 948_350_101;
        crate::test_support::install_test_volume_roster(
            &volume_id.to_string(),
            json!({"name": "Stormwatch"}),
            vec![
                json!({
                    "id": 103,
                    "issue_number": "33",
                    "name": "Thirty Three",
                    "cover_date": "1994-06-01",
                    "image": {"super_url": "https://example.test/33.jpg"}
                }),
                json!({"id": 101, "issue_number": "2", "name": "Two"}),
                json!({"id": 102, "issue_number": "3", "name": "Three"}),
            ],
        );

        let (_, Json(first)) = import_series(
            state.clone(),
            crate::auth::AuthenticatedUser::for_test(1),
            import_request(volume_id, 1),
        )
        .await
        .expect("fresh series import");
        assert!(first.thread_created);
        assert_eq!(first.issues_adopted, 3);
        assert_eq!(first.issues_skipped, 0);
        assert_eq!(first.issues_conflict, 0);
        assert!(first
            .issue_results
            .iter()
            .all(|result| result.hydration == "not_attempted"));

        let rows = connection
            .query(
                "SELECT issue_number, position, status FROM issues \
                 WHERE thread_id = $1 ORDER BY position",
                &[&first.thread_id],
            )
            .await
            .expect("natural issue order");
        let actual: Vec<(String, i32, String)> = rows
            .iter()
            .map(|row| (row.get(0), row.get(1), row.get(2)))
            .collect();
        assert_eq!(
            actual,
            vec![
                ("2".to_owned(), 1, "read".to_owned()),
                ("3".to_owned(), 2, "unread".to_owned()),
                ("33".to_owned(), 3, "unread".to_owned()),
            ]
        );
        let tracking = connection
            .query_one(
                "SELECT t.total_issues, t.issues_remaining, t.reading_progress, t.status, \
                        i.issue_number \
                 FROM threads t JOIN issues i ON i.id = t.next_unread_issue_id \
                 WHERE t.id = $1",
                &[&first.thread_id],
            )
            .await
            .expect("derived thread tracking");
        assert_eq!(tracking.get::<_, i32>(0), 3);
        assert_eq!(tracking.get::<_, i32>(1), 2);
        assert_eq!(tracking.get::<_, String>(2), "in_progress");
        assert_eq!(tracking.get::<_, String>(3), "active");
        assert_eq!(tracking.get::<_, String>(4), "3");

        let metadata: Value = connection
            .query_one(
                "SELECT metadata_json FROM external_identities \
                 WHERE provider = 'comicvine' AND entity_type = 'issue' AND external_id = '103'",
                &[],
            )
            .await
            .expect("roster metadata")
            .get(0);
        assert_eq!(metadata["name"], json!("Thirty Three"));
        assert_eq!(metadata["cover_date"], json!("1994-06-01"));
        assert_eq!(
            metadata["primary_image"],
            json!("https://example.test/33.jpg")
        );
        let evidence: String = connection
            .query_one(
                "SELECT m.evidence_source FROM issue_external_identity_mappings m \
                 JOIN external_identities e ON e.id = m.external_identity_id \
                 WHERE e.external_id = '103' AND m.status = 'confirmed'",
                &[],
            )
            .await
            .expect("adoption provenance")
            .get(0);
        assert_eq!(evidence, ADOPTION_EVIDENCE_SOURCE);

        connection
            .execute(
                "UPDATE external_identities SET metadata_json = $1::json \
                 WHERE provider = 'comicvine' AND entity_type = 'issue' AND external_id = '103'",
                &[&json!({"name": "Fully hydrated", "description": "rich provider facts"})],
            )
            .await
            .expect("seed hydrated metadata");
        let (_, Json(retry)) = import_series(
            state,
            crate::auth::AuthenticatedUser::for_test(1),
            import_request(volume_id, 1),
        )
        .await
        .expect("idempotent retry");
        assert!(!retry.thread_created);
        assert_eq!(retry.thread_id, first.thread_id);
        assert_eq!(retry.issues_adopted, 0);
        assert_eq!(retry.issues_skipped, 3);
        assert!(retry
            .issue_results
            .iter()
            .all(|result| result.outcome == "reused"));
        let preserved: Value = connection
            .query_one(
                "SELECT metadata_json FROM external_identities \
                 WHERE provider = 'comicvine' AND entity_type = 'issue' AND external_id = '103'",
                &[],
            )
            .await
            .expect("preserved metadata")
            .get(0);
        assert_eq!(preserved["name"], json!("Fully hydrated"));
        assert_eq!(preserved["description"], json!("rich provider facts"));
        let issue_count: i64 = connection
            .query_one(
                "SELECT count(*) FROM issues WHERE thread_id = $1",
                &[&first.thread_id],
            )
            .await
            .expect("retry did not duplicate issues")
            .get(0);
        assert_eq!(issue_count, 3);
        crate::test_support::clear_test_volume_roster(&volume_id.to_string());
    }

    #[tokio::test]
    async fn import_reports_cross_thread_and_local_identity_conflicts() {
        let (state, _guard, connection) = database_fixture().await;
        connection
            .batch_execute(
                "INSERT INTO threads \
                    (id, title, format, issues_remaining, total_issues, queue_position, status, \
                     user_id, created_at, is_test, is_blocked) \
                 VALUES (10, 'Existing', 'Comic', 1, 1, 1, 'active', 1, now(), false, false); \
                 INSERT INTO issues (id, thread_id, issue_number, position, status, created_at) \
                 VALUES (20, 10, '1', 1, 'unread', now()); \
                 INSERT INTO external_identities \
                    (id, provider, entity_type, external_id, metadata_json, created_at, updated_at) \
                 VALUES (30, 'comicvine', 'issue', '777', '{}'::json, now(), now()); \
                 INSERT INTO issue_external_identity_mappings \
                    (issue_id, external_identity_id, status, evidence_source, evidence_json, \
                     confidence, created_at, updated_at) \
                 VALUES (20, 30, 'confirmed', 'existing_mapping', '{}'::json, 1.0, now(), now());",
            )
            .await
            .expect("seed confirmed physical issue");
        let volume_id = 948_350_102;
        crate::test_support::install_test_volume_roster(
            &volume_id.to_string(),
            json!({"name": "Conflicts"}),
            vec![
                json!({"id": 777, "issue_number": "1"}),
                json!({"id": 778, "issue_number": "2"}),
                json!({"id": 779, "issue_number": "2"}),
            ],
        );

        let (_, Json(response)) = import_series(
            state.clone(),
            crate::auth::AuthenticatedUser::for_test(1),
            import_request(volume_id, 0),
        )
        .await
        .expect("bounded conflict outcomes");
        assert_eq!(response.issues_adopted, 1);
        assert_eq!(response.issues_skipped, 0);
        assert_eq!(response.issues_conflict, 2);
        assert_eq!(response.issue_results[0].outcome, "conflict");
        assert_eq!(response.issue_results[0].issue_id, Some(20));
        assert!(response.issue_results[0]
            .conflict_detail
            .as_deref()
            .is_some_and(|detail| detail.contains("thread 10")));
        assert_eq!(response.issue_results[1].outcome, "created");
        assert_eq!(response.issue_results[2].outcome, "conflict");
        assert_eq!(
            response.issue_results[2].conflict_detail.as_deref(),
            Some("issue already has a confirmed comicvine identity")
        );
        let local_numbers: Vec<String> = connection
            .query(
                "SELECT issue_number FROM issues WHERE thread_id = $1 ORDER BY position",
                &[&response.thread_id],
            )
            .await
            .expect("only nonconflicting issue adopted")
            .iter()
            .map(|row| row.get(0))
            .collect();
        assert_eq!(local_numbers, vec!["2".to_owned()]);
        let original_evidence: String = connection
            .query_one(
                "SELECT evidence_source FROM issue_external_identity_mappings \
                 WHERE issue_id = 20 AND external_identity_id = 30",
                &[],
            )
            .await
            .expect("original mapping unchanged")
            .get(0);
        assert_eq!(original_evidence, "existing_mapping");
        let duplicate_import = crate::comicvine_v2::import_issue(
            axum::extract::State(state),
            crate::auth::AuthenticatedUser::for_test(1),
            Json(crate::comicvine_v2::ImportIssueRequest {
                title: "Duplicate".to_owned(),
                comicvine_issue_id: 777,
                issue_number: Some("1".to_owned()),
                reading_order_id: None,
                anchor_before_thread_id: None,
                anchor_after_thread_id: None,
            }),
        )
        .await
        .expect_err("duplicate physical issue is structured");
        assert_eq!(duplicate_import.status(), StatusCode::CONFLICT);
        assert_eq!(
            duplicate_import.structured_detail(),
            Some(&json!({
                "code": "duplicate_physical_issue",
                "comicvine_issue_id": 777,
                "existing_issue_id": 20,
                "message": "ComicVine issue 777 already exists as issue 20"
            }))
        );
        crate::test_support::clear_test_volume_roster(&volume_id.to_string());
    }

    #[test]
    fn roster_normalization_preserves_provider_facts() {
        let roster = parse_roster(&[json!({
            "id": 701,
            "issue_number": "7",
            "name": "Issue 701",
            "cover_date": "1994-06-01",
            "store_date": "1994-05-18",
            "image": {"super_url": "https://example.test/701-super.jpg"},
            "site_detail_url": "https://comicvine.gamespot.com/issue/4000-701/"
        })]);
        assert_eq!(roster.len(), 1);
        assert_eq!(roster[0].metadata["name"], json!("Issue 701"));
        assert_eq!(roster[0].metadata["issue_number"], json!("7"));
        assert_eq!(
            roster[0].metadata["primary_image"],
            json!("https://example.test/701-super.jpg")
        );
        assert!(roster[0]
            .metadata
            .get("deep_metadata_refreshed_at")
            .is_none());
    }
}
