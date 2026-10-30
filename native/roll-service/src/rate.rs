//! Rate endpoint implementation for issue ratings.
use crate::{
    auth::AuthenticatedUser,
    db,
    ApiError, AppState,
};
use axum::{
    extract::{Query, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::sync::Arc;

#[derive(Deserialize)]
pub struct RateQuery {
    pub timezone: Option<String>,
}

#[derive(Deserialize)]
pub struct RateRequest {
    pub rating: f64,
    pub finish_session: bool,
    pub issue_number: Option<String>,
    pub thread_id: Option<i32>,
    pub direct: bool,
}

#[derive(Serialize)]
pub struct RateResponse {
    pub id: i32,
    pub title: String,
    pub format: String,
    pub issues_remaining: i32,
    pub queue_position: i32,
    pub status: String,
    pub last_rating: Option<f64>,
    pub last_activity_at: Option<String>,
    pub notes: Option<String>,
    pub is_test: bool,
    pub is_blocked: bool,
    pub created_at: String,
    pub total_issues: Option<i32>,
    pub reading_progress: Option<String>,
    pub next_unread_issue_id: Option<i32>,
    pub next_unread_issue_number: Option<String>,
    pub manual_creator_credits: Option<Value>,
    pub blocking_reasons: Vec<String>,
    pub roll_reconciliation: Option<RollReconciliation>,
}

#[derive(Serialize)]
pub struct RollReconciliation {
    pub last_read: RollLastRead,
}

#[derive(Serialize)]
pub struct RollLastRead {
    pub issue_id: Option<i32>,
    pub issue_number: Option<String>,
    pub thread_id: Option<i32>,
    pub thread_title: Option<String>,
    pub read_at: Option<String>,
}

fn unavailable() -> ApiError {
    ApiError(
        StatusCode::INTERNAL_SERVER_ERROR,
        std::borrow::Cow::Borrowed("Invalid rate response"),
    )
}

/// Thread value for response construction
fn thread_value(row: &tokio_postgres::Row) -> Result<Value, ApiError> {
    let id: i32 = row.try_get(0).map_err(db::query_error)?;
    let title: String = row.try_get(1).map_err(db::query_error)?;
    let format: String = row.try_get(2).map_err(db::query_error)?;
    let last_activity_at: Option<String> = row.try_get(3).map_err(db::query_error)?;
    Ok(json!({
        "id": id,
        "title": title,
        "format": format,
        "last_activity_at": last_activity_at,
        "tags": []
    }))
}

/// Normalize format value to match Python behavior
pub fn normalize_format_value(format: &str) -> String {
    format.to_lowercase().replace(' ', "_")
}

/// Get rating limits from config
pub fn get_rating_limits(state: &AppState) -> (f64, f64, f64) {
    (state.rating_min, state.rating_max, state.rating_threshold)
}

/// Main rate endpoint handler
pub async fn rate(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    Query(_query): Query<RateQuery>,
    Json(rate_request): Json<RateRequest>,
) -> Result<Json<RateResponse>, ApiError> {
    let conn = db::checkout(&state).await?;
    
    // Get rating limits
    let (rating_min, rating_max, rating_threshold) = get_rating_limits(&state);
    
    // Validate rating range
    if rate_request.rating < rating_min || rate_request.rating > rating_max {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            std::borrow::Cow::Owned(format!("Rating must be between {} and {}", rating_min, rating_max)),
        ));
    }
    
    // Find the thread to rate
    let thread_id = if let Some(thread_id) = rate_request.thread_id {
        // Direct thread rating
        if !rate_request.direct {
            return Err(ApiError(
                StatusCode::BAD_REQUEST,
                std::borrow::Cow::Borrowed("thread_id is required for a direct Thread rating"),
            ));
        }
        
        let row = conn
            .query_opt(
                "SELECT id FROM threads WHERE id=$1 AND user_id=$2",
                &[&thread_id, &user.id()],
            )
            .await
            .map_err(db::query_error)?
            .ok_or_else(|| ApiError(
                StatusCode::NOT_FOUND,
                std::borrow::Cow::Owned(format!("Thread {} not found", thread_id)),
            ))?;
        
        row.try_get(0).map_err(db::query_error)?
    } else {
        // Session-based rating - find the current thread
        let session = conn
            .query_opt(
                "SELECT id FROM sessions WHERE user_id=$1 AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
                &[&user.id()],
            )
            .await
            .map_err(db::query_error)?;
        
        let session_id: i32 = match session {
            Some(row) => row.try_get(0).map_err(db::query_error)?,
            None => return Err(ApiError(
                StatusCode::BAD_REQUEST,
                std::borrow::Cow::Borrowed("No active session. Please roll the dice first."),
            )),
        };
        
        // Check for pending thread
        let pending_thread_id = conn
            .query_opt(
                "SELECT pending_thread_id FROM sessions WHERE id=$1",
                &[&session_id],
            )
            .await
            .map_err(db::query_error)?
            .and_then(|row| row.try_get::<_, i32>(0).ok());
        
        if let Some(pending_thread_id) = pending_thread_id {
            pending_thread_id
        } else {
            // Find the latest roll event
            let roll_event = conn
                .query_opt(
                    "SELECT selected_thread_id FROM events 
                     WHERE session_id=$1 AND type='roll' 
                     ORDER BY timestamp DESC, id DESC LIMIT 1",
                    &[&session_id],
                )
                .await
                .map_err(db::query_error)?;
            
            let thread_id = match roll_event {
                Some(row) => {
                    let thread_id: Option<i32> = row.try_get(0).map_err(db::query_error)?;
                    match thread_id {
                        Some(tid) => tid,
                        None => return Err(ApiError(
                            StatusCode::BAD_REQUEST,
                            std::borrow::Cow::Borrowed("No active thread. Please roll the dice first."),
                        )),
                    }
                }
                None => return Err(ApiError(
                    StatusCode::BAD_REQUEST,
                    std::borrow::Cow::Borrowed("No active thread. Please roll the dice first."),
                )),
            };
            thread_id
        }
    };
    
    // Get thread details
    let thread_row = conn
        .query_opt(
            "SELECT id, title, format, issues_remaining, last_rating, last_activity_at, 
                    total_issues, reading_progress, next_unread_issue_id, status, notes, 
                    is_test, is_blocked, created_at, queue_position, queue_position_is_manual
             FROM threads WHERE id=$1 AND user_id=$2",
            &[&thread_id, &user.id()],
        )
        .await
        .map_err(db::query_error)?
        .ok_or_else(|| ApiError(
            StatusCode::NOT_FOUND,
            std::borrow::Cow::Owned(format!("Thread {} not found", thread_id)),
        ))?;
    
    let thread_id_val: i32 = thread_row.try_get(0).map_err(db::query_error)?;
    let title: String = thread_row.try_get(1).map_err(db::query_error)?;
    let format: String = thread_row.try_get(2).map_err(db::query_error)?;
    let issues_remaining: i32 = thread_row.try_get(3).map_err(db::query_error)?;
    let _last_rating: Option<f64> = thread_row.try_get(4).map_err(db::query_error)?;
    let last_activity_at: Option<String> = thread_row.try_get(5).map_err(db::query_error)?;
    let total_issues: Option<i32> = thread_row.try_get(6).map_err(db::query_error)?;
    let _reading_progress: Option<String> = thread_row.try_get(7).map_err(db::query_error)?;
    let _next_unread_issue_id: Option<i32> = thread_row.try_get(8).map_err(db::query_error)?;
    let status: String = thread_row.try_get(9).map_err(db::query_error)?;
    let notes: Option<String> = thread_row.try_get(10).map_err(db::query_error)?;
    let is_test: bool = thread_row.try_get(11).map_err(db::query_error)?;
    let is_blocked: bool = thread_row.try_get(12).map_err(db::query_error)?;
    let created_at: String = thread_row.try_get(13).map_err(db::query_error)?;
    let queue_position: i32 = thread_row.try_get(14).map_err(db::query_error)?;
    let queue_position_is_manual: bool = thread_row.try_get(15).map_err(db::query_error)?;
    
    // Check if thread has issues remaining
    if issues_remaining <= 0 {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            std::borrow::Cow::Owned(format!("Thread {} has no issues remaining", thread_id)),
        ));
    }
    
    // Handle issue tracking or simple decrement
    let mut issues_read = 0;
    let mut rated_issue_id: Option<i32> = None;
    let mut rated_issue_number: Option<String> = None;
    
    if let Some(issue_number) = rate_request.issue_number {
        // Specific issue rating
        let issue_row = conn
            .query_opt(
                "SELECT id, issue_number FROM issues 
                 WHERE thread_id=$1 AND issue_number=$2 AND status='unread'
                 ORDER BY position LIMIT 1",
                &[&thread_id, &issue_number],
            )
            .await
            .map_err(db::query_error)?;
        
        match issue_row {
            Some(row) => {
                let issue_id: i32 = row.try_get(0).map_err(db::query_error)?;
                let issue_num: String = row.try_get(1).map_err(db::query_error)?;
                
                // Mark as read
                conn.execute(
                    "UPDATE issues SET status='read', read_at=NOW() 
                     WHERE id=$1",
                    &[&issue_id],
                ).await.map_err(db::query_error)?;
                
                rated_issue_id = Some(issue_id);
                rated_issue_number = Some(issue_num);
                issues_read = 1;
            }
            None => {
                // Issue not found, try to create it
                let issue_num_int = issue_number.parse::<i32>();
                if let Ok(issue_num_int) = issue_num_int {
                    let total_issues = issue_num_int + issues_remaining - 1;
                    if total_issues > 1000 {
                        return Err(ApiError(
                            StatusCode::BAD_REQUEST,
                            std::borrow::Cow::Owned(format!("Total issues ({}) exceeds reasonable limit", total_issues)),
                        ));
                    }
                    
                    // Create missing issues
                    for position in 1..=total_issues {
                        let issue_status = if position < issue_num_int { "read" } else { "unread" };
                        let read_at = if position < issue_num_int { Some("NOW()") } else { None };
                        
                        conn.execute(
                            "INSERT INTO issues (thread_id, issue_number, status, read_at, position) 
                             VALUES ($1, $2, $3, $4, $5)",
                            &[&thread_id, &position.to_string(), &issue_status, &read_at, &position],
                        ).await.map_err(db::query_error)?;
                    }
                    
                    // Get the created issue
                    let issue_row = conn
                        .query_opt(
                            "SELECT id, issue_number FROM issues 
                             WHERE thread_id=$1 AND issue_number=$2
                             ORDER BY position LIMIT 1",
                            &[&thread_id, &issue_number],
                        )
                        .await
                        .map_err(db::query_error)?;
                    
                    if let Some(row) = issue_row {
                        let issue_id: i32 = row.try_get(0).map_err(db::query_error)?;
                        let issue_num: String = row.try_get(1).map_err(db::query_error)?;
                        
                        rated_issue_id = Some(issue_id);
                        rated_issue_number = Some(issue_num);
                        issues_read = 1;
                    }
                } else {
                    return Err(ApiError(
                        StatusCode::BAD_REQUEST,
                        std::borrow::Cow::Owned(format!("Non-numeric issue '{}' not found in thread. Add it via Edit Thread first.", issue_number)),
                    ));
                }
            }
        }
    } else {
        // Mark first unread issue as read
        let issue_row = conn
            .query_opt(
                "SELECT id, issue_number FROM issues 
                 WHERE thread_id=$1 AND status='unread' 
                 ORDER BY position LIMIT 1",
                &[&thread_id],
            )
            .await
            .map_err(db::query_error)?;
        
        if let Some(row) = issue_row {
            let issue_id: i32 = row.try_get(0).map_err(db::query_error)?;
            let issue_number: String = row.try_get(1).map_err(db::query_error)?;
            
            conn.execute(
                "UPDATE issues SET status='read', read_at=NOW() WHERE id=$1",
                &[&issue_id],
            ).await.map_err(db::query_error)?;
            
            rated_issue_id = Some(issue_id);
            rated_issue_number = Some(issue_number);
            issues_read = 1;
        }
    }
    
    // Update thread state
    let new_issues_remaining = issues_remaining - issues_read;
    let new_reading_progress = if new_issues_remaining > 0 {
        "in_progress"
    } else {
        "completed"
    };
    
    conn.execute(
        "UPDATE threads 
         SET issues_remaining=$1, reading_progress=$2, last_rating=$3, last_activity_at=NOW()
         WHERE id=$4",
        &[&new_issues_remaining, &new_reading_progress, &rate_request.rating, &thread_id],
    ).await.map_err(db::query_error)?;
    
    // Create event record
    let session_id = conn
        .query_opt(
            "SELECT id FROM sessions WHERE user_id=$1 AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?
        .and_then(|row| row.try_get::<_, i32>(0).ok());
    
    if let Some(sid) = session_id {
        conn.execute(
            "INSERT INTO events (type, session_id, thread_id, rating, issues_read, timestamp)
             VALUES ('rate', $1, $2, $3, $4, NOW())",
            &[&sid, &thread_id, &rate_request.rating, &issues_read],
        ).await.map_err(db::query_error)?;
    }
    
    // Update queue position based on rating
    if rate_request.rating >= rating_threshold {
        // High rating - move to front
        conn.execute(
            "UPDATE threads SET queue_position=1 WHERE id=$1",
            &[&thread_id],
        ).await.map_err(db::query_error)?;
    } else if !queue_position_is_manual {
        // Low rating - move to safe position
        let count: i32 = conn
            .query_one(
                "SELECT COUNT(*)::int FROM threads WHERE user_id=$1 AND queue_position > 0",
                &[&user.id()],
            )
            .await
            .map_err(db::query_error)?
            .try_get(0).map_err(db::query_error)?;
        
        let new_position = count + 1;
        conn.execute(
            "UPDATE threads SET queue_position=$1 WHERE id=$2",
            &[&new_position, &thread_id],
        ).await.map_err(db::query_error)?;
    }
    
    // Get next unread issue
    let next_issue_row = conn
        .query_opt(
            "SELECT id, issue_number FROM issues 
             WHERE thread_id=$1 AND status='unread' 
             ORDER BY position LIMIT 1",
            &[&thread_id],
        )
        .await
        .map_err(db::query_error)?;
    
    let next_unread_issue_id = next_issue_row
        .as_ref()
        .and_then(|row| row.try_get::<_, i32>(0).ok());
    let next_unread_issue_number = next_issue_row
        .as_ref()
        .and_then(|row| row.try_get::<_, String>(0).ok());
    
    // Build response
    let response = RateResponse {
        id: thread_id_val,
        title: title.clone(),
        format: normalize_format_value(&format),
        issues_remaining: new_issues_remaining,
        queue_position: queue_position,
        status,
        last_rating: Some(rate_request.rating),
        last_activity_at,
        notes,
        is_test,
        is_blocked,
        created_at,
        total_issues,
        reading_progress: Some(new_reading_progress.to_string()),
        next_unread_issue_id,
        next_unread_issue_number,
        manual_creator_credits: None,
        blocking_reasons: vec![],
        roll_reconciliation: if rated_issue_id.is_some() {
            Some(RollReconciliation {
                last_read: RollLastRead {
                    issue_id: rated_issue_id,
                    issue_number: rated_issue_number,
                    thread_id: Some(thread_id_val),
                    thread_title: Some(title.clone()),
                    read_at: Some("NOW()".to_string()),
                },
            })
        } else {
            None
        },
    };
    
    Ok(Json(response))
}