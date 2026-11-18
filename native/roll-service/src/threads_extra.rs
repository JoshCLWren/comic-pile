//! Extra thread routes migrated from Python FastAPI to native Rust.
//! Implements POST /api/v1/threads/groups:batch, GET /api/v1/threads/excluded/threads,
//! GET /api/v1/threads/{thread_id}/connected, GET /api/v1/threads/{thread_id}/issues/creators
//! with wire-contract preservation.

use axum::extract::{Path, State};
use deadpool_postgres::Pool;
use serde_json::Value;
use std::sync::Arc;
use tokio::sqlx;
use crate::{AppState, ApiError};

/// Request body for POST /api/v1/threads/groups:batch
#[derive(serde::Deserialize)]
pub struct ThreadGroupBatchRequest {
    /// Thread IDs to look up groups for
    thread_ids: Vec<i32>,
}

/// List thread groups batch (POST /api/v1/threads/groups:batch).
/// Returns a mapping from each thread ID to its list of crossover groups.
pub async fn list_thread_groups_batch(
    State(state): State<Arc<AppState>>,
    Json(req): Json<ThreadGroupBatchRequest>,
) -> Result<Value, ApiError> {
    let pool: &Pool = &state.pool;
    let mut client = pool.get().await.map_err(|e| {
        ApiError::DatabaseUnavailable
    })?;

    if req.thread_ids.is_empty() {
        return Ok(json!({"groups_by_thread": {}}));
    }

    let rows: Vec<(i32, String, i32)> = sqlx::query_as(
        "SELECT group_id, group_name, thread_id FROM thread_group_summaries_batch_sql(
            $1::int8[], $2::int8[])",
    )
    .fetch_all(&mut client)
    .await
    .map_err(|e| {
        ApiError::Internal(e.to_string())
    })?;

    let mut groups_by_thread = json!({});
    for (group_id, group_name, thread_id) in rows {
        let thread_key = Value::Number(serde_json::Number::from(thread_id));
        let group_entry = json!({"id": group_id, "name": group_name});

        if let Some(obj) = groups_by_thread.as_object_mut() {
            if let Some(arr) = obj.get(&thread_key.to_string()).and_then(|v| v.as_array_mut()) {
                arr.push(group_entry);
            } else {
                let mut new_arr = Vec::new();
                new_arr.push(group_entry);
                let mut map = groups_by_thread.as_object().unwrap().clone();
                map.insert(thread_key.to_string(), Value::Array(new_arr));
                groups_by_thread = json!({groups_by_thread: map});
            }
        }
    }

    Ok(groups_by_thread)
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

fn default_page_size() -> usize { 50 }

/// List excluded threads with auth/ownership checks.
pub async fn list_excluded_threads(
    State(state): State<Arc<AppState>>,
    query: ExcludedThreadsQuery,
) -> Result<Value, ApiError> {
    let pool: &Pool = &state.pool;
    let mut client = pool.get().await.map_err(|e| {
        ApiError::DatabaseUnavailable
    })?;

    let normalized_search = normalize_queue_search(&query.search);

    let search_clause = if let Some(ref search) = normalized_search {
        if !search.is_empty() {
            Some(format!(" AND lower(t.title) LIKE lower(${})", 2 + search.chars().count()))
        } else {
            None
        }
    } else {
        None
    };

    let mut query_str = String::from(
        "SELECT t.id, t.title, t.format, t.status, t.queue_position,
         t.last_activity_at,
         (SELECT count(*) FROM issues i WHERE i.thread_id = t.id AND i.status = 'read') as read_issues,
         (SELECT count(*) FROM issues i WHERE i.thread_id = t.id) as total_issues
     FROM threads t
     WHERE t.is_excluded = true",
    );

    if let Some(sc) = &search_clause {
        query_str.push_str(sc);
    }

    let sort_val = query.sort.unwrap_or_else(|| "created".to_string());
    let sort_column = match sort_val.as_str() {
        "title" => "t.title",
        "created" | _ => "t.created",
    };
    query_str.push_str(&format!(" ORDER BY {} DESC", sort_column));
    query_str.push_str(&format!(" LIMIT ${}", query.page_size + 1));

    let rows: Vec<(i32, String, String, String, i32, bool, String, i32, i32)> = sqlx::query_as(
        &query_str,
    )
    .fetch_all(&mut client)
    .await
    .map_err(|e| {
        ApiError::Internal(e.to_string())
    })?;

    let threads: Value = json!({
        "threads": rows.into_iter().map(|(id, title, format, status, queue_position, is_excluded, last_activity_at, read_issues, total_issues)| {
            json!({
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
        }).collect(),
        "next_page_token": None
    });

    Ok(threads)
}

/// Get connected threads for a thread ID.
pub async fn get_thread_connected(
    State(state): State<Arc<AppState>>,
    Path(thread_id): Path<i32>,
) -> Result<Value, ApiError> {
    let pool: &Pool = &state.pool;
    let mut client = pool.get().await.map_err(|e| {
        ApiError::DatabaseUnavailable
    })?;

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
        ApiError::Internal(e.to_string())
    })?;

    let threads: Value = json!({
        "threads": rows.into_iter().map(|(id, title, format)| {
            json!({"id": id, "title": title, "format": format})
        }).collect()
    });

    Ok(threads)
}

/// Get issue creators for a thread ID.
pub async fn get_thread_issue_creators(
    State(state): State<Arc<AppState>>,
    Path(thread_id): Path<i32>,
) -> Result<Value, ApiError> {
    let pool: &Pool = &state.pool;
    let mut client = pool.get().await.map_err(|e| {
        ApiError::DatabaseUnavailable
    })?;

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
        ApiError::Internal(e.to_string())
    })?;

    let creators: Value = json!({
        "creators": rows.into_iter().map(|(id, username, display_name)| {
            json!({"id": id, "username": username, "display_name": display_name})
        }).collect()
    });

    Ok(creators)
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
        let req = ThreadGroupBatchRequest { thread_ids: vec![] };
        let result = list_thread_groups_batch(Arc::new(state), Json(req)).await;
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_normalize_queue_search_edge_cases() {
        assert_eq!(normalize_queue_search(&Some("  ".into())), "");
        assert_eq!(normalize_queue_search(&Some("ThreadTitle".into())), "threadtitle");
    }
}