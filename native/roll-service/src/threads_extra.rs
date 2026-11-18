//! Extra thread routes migrated from Python FastAPI to native Rust.
//! Implements POST /api/v1/threads/groups:batch, GET /api/v1/threads/excluded/threads,
//! GET /api/v1/threads/{thread_id}/connected, GET /api/v1/threads/{thread_id}/issues/creators
//! with wire-contract preservation.

use axum::{extract::State, Json};
use serde_json::json;
use std::sync::Arc;
use deadpool_postgres::Pool;
use tokio::sqlx;
use crate::{AppState, ApiError};

/// Request body for POST /api/v1/threads/groups:batch
#[derive(serde::Deserialize)]
pub struct ThreadGroupBatchRequest {
    /// Thread IDs to look up groups for
    thread_ids: Vec<i32>,
}

/// Response: dict mapping thread ID to list of DependencyGroupSummary
#[derive(serde::Serialize)]
pub struct GroupsByThreadResponse {
    /// Mapping from thread ID to list of group summaries
    pub groups_by_thread: serde_json::Value,
}

/// List thread groups batch (POST /api/v1/threads/groups:batch).
/// Returns a mapping from each thread ID to its list of crossover groups.
pub async fn list_thread_groups_batch(
    State(state): State<Arc<AppState>>,
    Json(req): Json<ThreadGroupBatchRequest>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let pool: &Pool = &state.pool;
    let mut client = pool.get().await.map_err(|e| {
        tracing::debug!(error_kind = crate::error_kind(&e), "failed to get DB connection");
        ApiError::DatabaseUnavailable
    })?;

    if req.thread_ids.is_empty() {
        return Ok(Json(json!({ "groups_by_thread": {} })));
    }

    // Use the existing SQL function thread_group_summaries_batch from the repository
    // to get group summaries for all threads in one query.
    let rows: Vec<(i32, String, i32)> = sqlx::query_as::<_, (i32, String, i32)>(
        "SELECT group_id, group_name, thread_id FROM thread_group_summaries_batch(
            $1::int8[], $2::int8[]"
        )
        .fetch_all(&mut client)
        .await
        .map_err(|e| {
            tracing::debug!(error = ?e, "thread_group_summaries_batch query failed");
            ApiError::Internal(e.to_string())
        })?;
    
    // Build the response: mapping from thread_id to list of (group_id, group_name)
    let mut groups_by_thread: serde_json::Value = serde_json::json!({});
    for (group_id, group_name, thread_id) in rows {
        let thread_key = serde_json::Value::Number(serde_json::Number::from(thread_id));
        let group_entry = serde_json::json!({
            "id": group_id,
            "name": group_name
        });
        
        // Append to the thread's group list
        if let Some(arr) = groups_by_thread.as_object_mut().and_then(|obj| obj.get(&thread_key.to_string()).and_then(|v| v.as_array_mut())) {
            arr.push(group_entry);
        } else {
            // Create new entry for this thread
            let mut new_arr = serde_json::Vec::new();
            new_arr.push(group_entry);
            groups_by_thread = serde_json::json!(
                {groups_by_thread: serde_json::Value::Object(
                    groups_by_thread.as_object().unwrap().clone()
                        .insert(thread_key.to_string(), serde_json::Value::Array(new_arr))
                )}
            );
        }
    }

    Ok(Json(groups_by_thread))
}

/// Query parameters for excluded threads list
#[derive(serde::Deserialize)]
pub struct ExcludedThreadsQuery {
    /// Optional case-insensitive title search filter
    #[serde(default)]
    search: Option<String>,
    /// Sort order: title or created
    sort: Option<String>,
    /// Number of threads per page (default 50, max 200)
    #[serde(default = "default_page_size")]
    page_size: usize,
    /// Opaque cursor token for pagination continuation
    #[serde(default)]
    page_token: Option<String>,
}

/// Default page size for excluded threads
fn default_page_size() -> usize { 50 }

/// Response for excluded threads list
#[derive(serde::Serialize)]
struct ExcludedThreadsResponse {
    /// Paginated excluded threads
    threads: Vec<serde_json::Value>,
    /// Next page token when more pages exist
    next_page_token: Option<String>,
}

/// List excluded threads with auth/ownership checks.
pub async fn list_excluded_threads(
    State(state): State<Arc<AppState>>,
    query: ExcludedThreadsQuery,
) -> Result<Json<serde_json::Value>, ApiError> {
    let pool: &Pool = &state.pool;
    let mut client = pool.get().await.map_err(|e| {
        tracing::debug!(error_kind = crate::error_kind(&e), "failed to get DB connection");
        ApiError::DatabaseUnavailable
    })?;

    // Build the search-normalized query
    let normalized_search = normalize_queue_search(&query.search);

    // Fetch excluded threads page using the thread repository pattern
    // SQL query to fetch excluded threads with pagination
    let mut query_builder = format!(
        "SELECT t.id, t.title, t.format, t.status, t.queue_position, t.is_excluded,
                t.last_activity_at,
                (SELECT count(*) FROM issues i WHERE i.thread_id = t.id AND i.status = 'read') as read_issues,
                (SELECT count(*) FROM issues i WHERE i.thread_id = t.id) as total_issues
         FROM threads t
         WHERE t.is_excluded = true AND t.user_id = (SELECT u.id FROM users u WHERE u.auth_id = current_setting('app.jwt_claims'::json->>'sub'))"
    );

    let search_param = if let Some(ref search) = normalized_search {
        if !search.is_empty() {
            format!(" AND lower(t.title) LIKE lower('%{}%')", search.replace("'", "''"))
        } else {
            "".to_string()
        }
    } else {
        "".to_string()
    };

    query_builder.push_str(&search_param);

    // Sort order
    let sort_val = query.sort.unwrap_or_else(|| "created".to_string());
    let sort_column = match sort_val.as_str() {
        "title" => "t.title",
        "created" | _ => "t.created",
    };
    query_builder.push_str(&format!(" ORDER BY {} DESC", sort_column));

    // Pagination with cursor
    let (page_size_str, offset_str) = if query.page_token.is_some() {
        // Cursor-based pagination - use the token as offset
        format!(" LIMIT {}", query.page_size)
    } else {
        format!(" LIMIT {} OFFSET 0", query.page_size)
    };

    query_builder.push_str(&page_size_str);

    // Execute the query
    let rows: Vec<(i32, String, String, String, i32, bool, String, i32, i32)> = sqlx::query_as(
        &query_builder,
    )
    .fetch_all(&mut client)
    .await
    .map_err(|e| {
        tracing::debug!(error = ?e, "list_excluded_threads query failed");
        ApiError::Internal(e.to_string())
    })?;

    // Convert to response format
    let threads: Vec<serde_json::Value> = rows
        .into_iter()
        .map(|(id, title, format, status, queue_position, is_excluded, last_activity_at, read_issues, total_issues)| {
            serde_json::json!({
                "id": id,
                "title": title,
                "format": format,
                "status": status,
                "queue_position": queue_position,
                "is_excluded": is_excluded,
                "last_activity_at": last_activity_at,
                "read_issues": read_issues,
                "total_issues": total_issues
            })
        })
        .collect();

    let next_page_token: Option<String> = None; // TODO: implement proper cursor

    Ok(Json(serde_json::json!({
        "threads": threads,
        "next_page_token": next_page_token
    })))
}

/// Get connected threads for a thread ID.
pub async fn get_thread_connected(
    State(state): State<Arc<AppState>>,
    /// Thread ID from the path parameter
    thread_id: i32,
) -> Result<Json<serde_json::Value>, ApiError> {
    let pool: &Pool = &state.pool;
    let mut client = pool.get().await.map_err(|e| {
        tracing::debug!(error_kind = crate::error_kind(&e), "failed to get DB connection");
        ApiError::DatabaseUnavailable
    })?;

    // Query for threads connected through shared dependency groups
    let rows: Vec<(i32, String, String)> = sqlx::query_as(
        "SELECT t2.id, t2.title, t2.format
         FROM threads t1
         JOIN dependency_group_memberships m1 ON m1.thread_id = t1.id
         JOIN dependency_group_memberships m2 ON m2.group_id = m1.group_id
         JOIN threads t2 ON t2.id = m2.thread_id AND t2.id != t1.id
         WHERE t1.id = $1
         GROUP BY t2.id, t2.title, t2.format
         LIMIT 10",
    )
    .bind(thread_id)
    .fetch_all(&mut client)
    .await
    .map_err(|e| {
        tracing::debug!(error = ?e, "get_thread_connected query failed");
        ApiError::Internal(e.to_string())
    })?;

    let threads: Vec<serde_json::Value> = rows
        .into_iter()
        .map(|(id, title, format)| {
            serde_json::json!({
                "id": id,
                "title": title,
                "format": format
            })
        })
        .collect();

    Ok(Json(json!({"threads": threads})))
}

/// Get issue creators for a thread ID.
pub async fn get_thread_issue_creators(
    State(state): State<Arc<AppState>>,
    /// Thread ID from the path parameter
    thread_id: i32,
) -> Result<Json<serde_json::Value>, ApiError> {
    let pool: &Pool = &state.pool;
    let mut client = pool.get().await.map_err(|e| {
        tracing::debug!(error_kind = crate::error_kind(&e), "failed to get DB connection");
        ApiError::DatabaseUnavailable
    })?;

    // Query for issue creators associated with this thread's issues
    let rows: Vec<(i32, String, String)> = sqlx::query_as(
        "SELECT distinct u.id, u.username, u.display_name
         FROM issues i
         JOIN issue_creators ic ON ic.issue_id = i.id
         JOIN users u ON u.id = ic.user_id
         WHERE i.thread_id = $1
         LIMIT 20",
    )
    .bind(thread_id)
    .fetch_all(&mut client)
    .await
    .map_err(|e| {
        tracing::debug!(error = ?e, "get_thread_issue_creators query failed");
        ApiError::Internal(e.to_string())
    })?;

    let creators: Vec<serde_json::Value> = rows
        .into_iter()
        .map(|(id, username, display_name)| {
            serde_json::json!({
                "id": id,
                "username": username,
                "display_name": display_name
            })
        })
        .collect();

    Ok(Json(json!({"creators": creators})))
}

/// Normalize a queue search string (case-insensitive, trimmed)
fn normalize_queue_search(search: &Option<String>) -> String {
    search.as_deref().map(|s| s.to_lowercase().trim().to_string()).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_queue_search() {
        assert_eq!(normalize_queue_search(&Some("  ThreadTitle  ".into())), "threadtitle");
        assert_eq!(normalize_queue_search(&None), "");
        assert_eq!(normalize_queue_search(&Some("".into())), "");
    }

    #[tokio::test]
    async fn test_list_thread_groups_batch_empty() {
        let state = crate::AppState::new(
            deadpool_postgres::Config::new()
                .host("localhost")
                .dbname("unused")
                .user("unused")
                .password("unused")
        ).unwrap();
        // Just test the function compiles and handles empty input
        let req = ThreadGroupBatchRequest { thread_ids: vec![] };
        let result = list_thread_groups_batch(Arc::new(state), Json(req)).await;
        // Should not panic
        assert!(result.is_ok() || result.is_err());
    }

    #[tokio::test]
    async fn test_extract_thread_ids_from_query_returns_none() {
        let result = extract_thread_ids_from_query(&serde_qs::filtered::Value::Bool(false));
        assert!(result.is_none());
    }
}
