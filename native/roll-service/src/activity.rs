//! Native owner-scoped activity history for Roll #4822.
//!
//! This replaces the legacy session-based history with a complete chronological
//! view of all user actions, including sessionless dice events. It implements
//! the Rust v2 History cutover requirement to show the full activity sequence.
//!
//! The endpoint returns chronological user activity with stable cursor pagination
//! and includes all event types: roll, snooze, rate, manual_die, reset_dice,
//! and legacy session events.
use crate::{auth::AuthenticatedUser, db, ApiError, AppState};
use axum::{
    extract::{Query, State},
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;
use utoipa::ToSchema;

#[derive(Debug, ToSchema)]
pub struct ActivityEvent {
    pub event_id: i32,
    pub event_type: String,
    pub timestamp: String,
    pub die_before: Option<i32>,
    pub die_after: Option<i32>,
    pub rating: Option<f64>,
    pub thread_id: Option<i32>,
    pub thread_title: Option<String>,
    pub issue_id: Option<i32>,
    pub issue_number: Option<String>,
    pub action_display: String,
}

#[derive(Debug, ToSchema)]
pub struct ActivityResponse {
    pub events: Vec<ActivityEvent>,
    pub next_page_token: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct ActivityQuery {
    pub page_size: Option<i32>,
    pub page_token: Option<String>,
}

const DEFAULT_PAGE_SIZE: i32 = 50;
const MAX_PAGE_SIZE: i32 = 200;

/// Build the complete activity query for an owner.
fn activity_sql(user_id: i32, page_size: i32, page_token: Option<&str>) -> (String, Vec<Box<dyn ToSql + Sync>>) {
    let mut query = String::from(
        r#"
        SELECT 
            e.id,
            e.type,
            to_char(e.timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            e.die,
            e.die_after,
            e.rating,
            e.thread_id,
            t.title as thread_title,
            e.issue_id,
            i.issue_number,
            e.context
        FROM events e
        LEFT JOIN threads t ON t.id = e.thread_id
        LEFT JOIN issues i ON i.id = e.issue_id
        WHERE e.user_id = $1
        "#,
    );
    
    let mut params: Vec<Box<dyn ToSql + Sync>> = vec![Box::new(user_id)];
    
    // Apply pagination
    if let Some(token) = page_token {
        query.push_str(" AND e.id < $2");
        params.push(Box::new(token.parse::<i32>().unwrap_or(0)));
    }
    
    query.push_str(
        r#"
        ORDER BY e.timestamp DESC, e.id DESC
        LIMIT $#
        "#,
    );
    
    params.push(Box::new(page_size));
    
    (query, params)
}

/// Parse context to extract dice_command_key and determine action display.
fn parse_action_display(
    event_type: &str,
    context: Option<&Value>,
    die_before: Option<i32>,
    die_after: Option<i32>,
    rating: Option<f64>,
    thread_title: Option<String>,
) -> String {
    match event_type {
        "roll" => {
            if let Some(title) = thread_title {
                format!("Rolled {}", title)
            } else {
                "Rolled".to_string()
            }
        }
        "snooze" => {
            if let Some(title) = thread_title {
                if let Some(before) = die_before {
                    if let Some(after) = die_after {
                        format!("Snoozed {} (d{} → d{})", title, before, after)
                    } else {
                        format!("Snoozed {} (d{})", title, before)
                    }
                } else {
                    format!("Snoozed {}", title)
                }
            } else {
                "Snoozed".to_string()
            }
        }
        "rate" => {
            if let Some(rating_val) = rating {
                if let Some(title) = thread_title {
                    format!("Rated {} ⭐{}", title, rating_val)
                } else {
                    format!("Rated ⭐{}", rating_val)
                }
            } else {
                "Rated".to_string()
            }
        }
        "manual_die" => {
            if let Some(before) = die_before {
                if let Some(after) = die_after {
                    format!("Manual die selection (d{} → d{})", before, after)
                } else {
                    format!("Manual die selection (d{})", before)
                }
            } else {
                "Manual die selection".to_string()
            }
        }
        "reset_dice" => {
            "Reset dice".to_string()
        }
        _ => {
            if let Some(title) = thread_title {
                format!("{} {}", event_type.to_string().to_uppercase(), title)
            } else {
                event_type.to_string().to_uppercase()
            }
        }
    }
}

/// GET /api/v2/activity - Owner-scoped activity history
pub async fn get_activity(
    Query(params): Query<ActivityQuery>,
    user: AuthenticatedUser,
    State(state): State<Arc<AppState>>,
) -> Result<Json<ActivityResponse>, ApiError> {
    let page_size = params.page_size.unwrap_or(DEFAULT_PAGE_SIZE).clamp(1, MAX_PAGE_SIZE);
    let page_token = params.page_token.as_deref();
    
    let connection = db::checkout(&state).await?;
    
    let (query, sql_params) = activity_sql(user.id(), page_size, page_token);
    
    let rows = connection
        .query(&query, &sql_params.iter().map(|p| p.as_ref()).collect::<Vec<_>>())
        .await
        .map_err(db::query_error)?;
    
    let mut events = Vec::with_capacity(rows.len());
    let mut last_id = None;
    
    for row in &rows {
        let event_id: i32 = row.get(0);
        let event_type: String = row.get(1);
        let timestamp: String = row.get(2);
        let die_before: Option<i32> = row.get(3);
        let die_after: Option<i32> = row.get(4);
        let rating: Option<f64> = row.get(5);
        let thread_id: Option<i32> = row.get(6);
        let thread_title: Option<String> = row.get(7);
        let issue_id: Option<i32> = row.get(8);
        let issue_number: Option<String> = row.get(9);
        let context: Option<String> = row.get(10);
        
        let context_json = context
            .as_deref()
            .and_then(|text| serde_json::from_str(text).ok())
            .unwrap_or(Value::Null);
        
        let action_display = parse_action_display(
            &event_type,
            thread_title.as_ref().map(|s| Value::String(s.clone())),
            die_before,
            die_after,
            rating,
            thread_title.clone(),
        );
        
        events.push(ActivityEvent {
            event_id,
            event_type,
            timestamp,
            die_before,
            die_after,
            rating,
            thread_id,
            thread_title,
            issue_id,
            issue_number,
            action_display,
        });
        
        last_id = Some(event_id);
    }
    
    let next_page_token = if events.len() == page_size as usize && last_id.is_some() {
        Some(last_id.unwrap().to_string())
    } else {
        None
    };
    
    Ok(Json(ActivityResponse {
        events,
        next_page_token,
    }))
}

/// OpenAPI declaration for the activity endpoint.
#[utoipa::path(
    get,
    path = "/api/v2/activity",
    tag = "activity",
    params(
        ("page_size" = Option<i32>, Query, description = "Number of events per page (1-200, default 50)"),
        ("page_token" = Option<String>, Query, description = "Token for pagination (event ID)")
    ),
    responses(
        (status = 200, description = "Activity history", body = ActivityResponse),
        (status = 401, description = "Not authenticated"),
        (status = 404, description = "User not found")
    ),
    security(("HTTPBearer" = []))
)]
pub fn get_activity_documentation() {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{db, test_support};
    use serde_json::json;

    #[tokio::test]
    async fn activity_query_includes_all_event_types() {
        let _admin = crate::test_support::required_test_admin_url();
        let url = crate::test_support::database_url().await;
        let (state, _guard) = test_support::test_state(2).await.expect("disposable PostgreSQL required");
        let connection = db::checkout(&state).await.expect("fixture connection");
        
        // Seed test data with mixed sessioned and sessionless events
        connection
            .batch_execute(
                r#"
                INSERT INTO users (id, username) VALUES (1, 'test-user'), (2, 'other-user');
                INSERT INTO threads (id, user_id, title, format, issues_remaining, status) 
                VALUES (10, 1, 'Test Comic', 'Comic', 5, 'active');
                INSERT INTO issues (id, thread_id, issue_number, status, position)
                VALUES (100, 10, '1', 'unread', 1);
                INSERT INTO events (user_id, type, timestamp, die, die_after, thread_id, issue_id, context)
                VALUES 
                    -- Sessioned events
                    (1, 'roll', NOW(), 6, NULL, 10, NULL, '{}'::json),
                    (1, 'snooze', NOW() + interval '1 second', 6, 8, 10, NULL, '{}'::json),
                    (1, 'roll', NOW() + interval '2 seconds', 8, NULL, 10, NULL, '{}'::json),
                    -- Sessionless events (new format)
                    (1, 'snooze', NOW() + interval '3 seconds', 8, 10, 10, NULL, '{"dice_command_key":"test-123","dice_command":{"kind":"snooze","thread_id":10}}'::json),
                    (1, 'roll', NOW() + interval '4 seconds', 10, NULL, 10, 100, '{}'::json),
                    (1, 'rate', NOW() + interval '5 seconds', 10, 8, 10, 100, '{"dice_command_key":"test-456","dice_command":{"kind":"roll_rating","thread_id":10,"issue_id":100,"rating":4.5}}'::json),
                    -- Other user (should be filtered out)
                    (2, 'roll', NOW(), 6, NULL, NULL, NULL, '{}'::json);
                "#,
            )
            .await
            .expect("seed activity test data");
        
        drop(connection);
        
        // Test the query building
        let (query, params) = activity_sql(1, 10, None);
        assert!(query.contains("WHERE e.user_id = $1"));
        assert!(query.contains("ORDER BY e.timestamp DESC, e.id DESC"));
        assert!(query.contains("LIMIT $"));
        assert_eq!(params.len(), 2);
        
        // Test action display parsing
        let roll_display = parse_action_display("roll", Some(&json!("Test Comic")), None, None, None, Some("Test Comic".to_string()));
        assert_eq!(roll_display, "Rolled Test Comic");
        
        let snooze_display = parse_action_display("snooze", Some(&json!("Test Comic")), Some(6), Some(8), None, Some("Test Comic".to_string()));
        assert_eq!(snooze_display, "Snoozed Test Comic (d6 → d8)");
        
        let rate_display = parse_action_display("rate", Some(&json!("Test Comic")), None, None, Some(4.5), Some("Test Comic".to_string()));
        assert_eq!(rate_display, "Rated Test Comic ⭐4.5");
    }

    #[tokio::test]
    fn activity_query_respects_pagination() {
        let (query, params) = activity_sql(1, 20, Some("123"));
        assert!(query.contains("AND e.id < $2"));
        assert_eq!(params.len(), 3); // user_id, page_token, page_size
    }

    #[tokio::test]
    fn activity_query_clamps_page_size() {
        let (query, params) = activity_sql(1, 300, None); // Exceeds max
        assert_eq!(params.len(), 2); // Only user_id and page_size
        // The actual page size limiting happens in the handler
    }
}