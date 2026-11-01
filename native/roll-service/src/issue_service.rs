//! Issue read/rate service for direct issue manipulation.

use crate::{
    auth::AuthenticatedUser,
    config::Config,
    db::{Issue, Thread},
    error::ServiceError,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::Json,
    Extension,
};
use serde::{Deserialize, Serialize};
use sqlx::PgPool;
use std::sync::Arc;
use uuid::Uuid;

/// Request for marking an issue as read and optionally rating it.
#[derive(Debug, Deserialize)]
pub struct IssueReadRateRequest {
    /// Status of the issue. Only "read" is supported for marking as read.
    pub status: Option<String>,
    /// Rating for the issue (0.5-5.0, in 0.5 increments). If None and status is "read",
    /// defaults to 3.5. If status is None, only updates the rating.
    pub rating: Option<f64>,
}

/// Response for issue read/rate operation.
#[derive(Debug, Serialize)]
pub struct IssueReadRateResponse {
    /// The updated issue.
    pub issue: Issue,
    /// The updated thread.
    pub thread: Thread,
    /// Whether this was a new read event (false for rating-only corrections).
    pub read_event_created: bool,
    /// Whether this was a new rating event (false for read-only operations).
    pub rating_event_created: bool,
    /// The final rating value after the operation.
    pub final_rating: Option<f64>,
}

/// Service for handling issue read/rate operations.
pub struct IssueService {
    pool: Arc<PgPool>,
    config: Arc<Config>,
}

impl IssueService {
    /// Create a new issue service.
    pub fn new(pool: Arc<PgPool>, config: Arc<Config>) -> Self {
        Self { pool, config }
    }

    /// Mark an issue as read and optionally rate it.
    ///
    /// This implements the direct issue read/rate command that:
    /// - Validates authenticated ownership of the issue
    /// - Never checks Option E eligibility
    /// - Atomically persists read status and rating
    /// - Updates thread's next unread frontier
    /// - Returns reconciled issue/thread data
    /// - Supports idempotent operations and rating corrections
    pub async fn read_rate_issue(
        &self,
        user: AuthenticatedUser,
        issue_id: i32,
        request: IssueReadRateRequest,
    ) -> Result<IssueReadRateResponse, ServiceError> {
        // Start a transaction for atomic operations
        let mut tx = self.pool.begin().await?;

        // Verify ownership and get the issue
        let issue = sqlx::query_as!(
            Issue,
            r#"
            SELECT i.*, t.user_id
            FROM issues i
            JOIN threads t ON i.thread_id = t.id
            WHERE i.id = $1 AND t.user_id = $2
            "#,
            issue_id,
            user.id
        )
        .fetch_optional(&mut *tx)
        .await?;

        let issue = match issue {
            Some(issue) => issue,
            None => return Err(ServiceError::NotFound("Issue not found or not owned")),
        };

        let thread_id = issue.thread_id;

        // Check if this is a read operation (status is "read")
        let is_read_operation = request.status.as_deref() == Some("read");
        let is_rating_only = request.rating.is_some() && request.status.is_none();

        // Validate rating if provided
        if let Some(rating) = request.rating {
            if rating < 0.5 || rating > 5.0 || (rating * 2.0).fract() != 0.0 {
                return Err(ServiceError::BadRequest(
                    "Rating must be between 0.5 and 5.0 in 0.5 increments",
                ));
            }
        }

        let mut read_event_created = false;
        let mut rating_event_created = false;
        let mut final_rating = issue.rating;

        // Handle read status change
        if is_read_operation {
            if issue.read_at.is_some() {
                // Issue already read - no duplicate read event
            } else {
                // Mark as read
                sqlx::query!(
                    "UPDATE issues SET status = 'read', read_at = NOW() WHERE id = $1",
                    issue_id
                )
                .execute(&mut *tx)
                .await?;

                // Create a read event
                sqlx::query!(
                    r#"
                    INSERT INTO events (id, type, timestamp, thread_id, issue_id, issue_number)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    "#,
                    Uuid::new_v4(),
                    "issue_read",
                    chrono::Utc::now(),
                    thread_id,
                    issue_id,
                    issue.issue_number
                )
                .execute(&mut *tx)
                .await?;

                read_event_created = true;
            }
        }

        // Handle rating change
        if let Some(new_rating) = request.rating {
            if issue.rating != Some(new_rating) {
                // Update the rating
                sqlx::query!(
                    "UPDATE issues SET rating = $1 WHERE id = $2",
                    new_rating,
                    issue_id
                )
                .execute(&mut *tx)
                .await?;

                // Create a rating event if this is not a read operation (read operations create their own events)
                if !is_read_operation || issue.rating.is_none() {
                    sqlx::query!(
                        r#"
                        INSERT INTO events (id, type, timestamp, thread_id, issue_id, issue_number, rating)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        "#,
                        Uuid::new_v4(),
                        "issue_rated",
                        chrono::Utc::now(),
                        thread_id,
                        issue_id,
                        issue.issue_number,
                        new_rating
                    )
                    .execute(&mut *tx)
                    .await?;
                }

                rating_event_created = true;
                final_rating = Some(new_rating);
            }
        }

        // Update thread's next unread frontier
        self.update_thread_next_unread(&mut tx, thread_id).await?;

        // Get the updated issue and thread
        let updated_issue = sqlx::query_as!(
            Issue,
            r#"
            SELECT i.*, t.user_id
            FROM issues i
            JOIN threads t ON i.thread_id = t.id
            WHERE i.id = $1
            "#,
            issue_id
        )
        .fetch_one(&mut *tx)
        .await?;

        let updated_thread = sqlx::query_as!(
            Thread,
            "SELECT * FROM threads WHERE id = $1",
            thread_id
        )
        .fetch_one(&mut *tx)
        .await?;

        // Commit the transaction
        tx.commit().await?;

        Ok(IssueReadRateResponse {
            issue: updated_issue,
            thread: updated_thread,
            read_event_created,
            rating_event_created,
            final_rating,
        })
    }

    /// Update a thread's next unread issue pointer.
    async fn update_thread_next_unread(
        &self,
        tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
        thread_id: i32,
    ) -> Result<(), ServiceError> {
        // Find the first unread issue
        let next_unread = sqlx::query_scalar!(
            r#"
            SELECT id FROM issues
            WHERE thread_id = $1 AND status = 'unread'
            ORDER BY position ASC
            LIMIT 1
            "#,
            thread_id
        )
        .fetch_optional(tx)
        .await?;

        let next_unread_id = next_unread;

        // Update the thread's next unread pointer
        sqlx::query!(
            "UPDATE threads SET next_unread_issue_id = $1 WHERE id = $2",
            next_unread_id,
            thread_id
        )
        .execute(tx)
        .await?;

        // Update thread status based on whether there are unread issues
        let has_unread = sqlx::query_scalar!(
            r#"
            SELECT EXISTS(
                SELECT 1 FROM issues
                WHERE thread_id = $1 AND status = 'unread'
                LIMIT 1
            )
            "#,
            thread_id
        )
        .fetch_one(tx)
        .await?;

        let status = if has_unread { "active" } else { "completed" };
        sqlx::query!(
            "UPDATE threads SET status = $1 WHERE id = $2",
            status,
            thread_id
        )
        .execute(tx)
        .await?;

        Ok(())
    }
}