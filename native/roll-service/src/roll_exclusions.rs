//! Durable thread exclusions that the roll pool applies on every reader path:
//! cross-session snooze backoff (the legacy Fibonacci schedule) and reader-owned
//! "Remove from Queue" exclusions. Shared by the rating-time exclusion set in
//! `issue_service`; the retired Python-compatible skip handler no longer lives
//! here.
use crate::{db, ApiError};
use std::collections::{HashMap, HashSet};
use tokio_postgres::Transaction;

/// Mirror `comic_pile.snooze_backoff.fibonacci`.
fn fibonacci(n: i64) -> i64 {
    if n <= 0 {
        return 0;
    }
    if n <= 2 {
        return 1;
    }
    let (mut a, mut b) = (1_i64, 1_i64);
    for _ in 3..=n {
        let next = a + b;
        a = b;
        b = next;
    }
    b
}

/// Mirror `comic_pile.snooze_backoff.compute_backoff_sessions`.
fn compute_backoff_sessions(snooze_count: i64) -> i64 {
    if snooze_count <= 0 {
        return 0;
    }
    let pair = (snooze_count + 1) / 2;
    fibonacci(pair + 1)
}

/// Mirror `comic_pile.snooze_backoff.is_eligible`.
fn is_backoff_eligible(snooze_count: i64, later_session_count: i64) -> bool {
    snooze_count <= 0 || later_session_count >= compute_backoff_sessions(snooze_count)
}

/// Durable cross-session snooze backoff, mirroring
/// `derive_cross_session_excluded_thread_ids` in legacy execution.
///
/// Transaction-scoped so any writer that needs the roll pool exclusion set -
/// Skip, and rating-time queue placement - resolves it on its own connection.
pub(crate) async fn durable_snoozed(
    tx: &Transaction<'_>,
    user_id: i32,
) -> Result<HashSet<i32>, ApiError> {
    let rows = tx
        .query(
            "SELECT t.id, extract(epoch FROM t.last_activity_at)::float8, e.type,
                    extract(epoch FROM e.timestamp)::float8, e.id
             FROM threads t
             LEFT JOIN events e ON e.thread_id = t.id
               AND e.type IN ('snooze','unsnooze')
               AND (e.context->>'dice_command_key') IS NULL
             WHERE t.user_id = $1 AND t.status = 'active' AND t.is_blocked = false
             ORDER BY t.id, e.timestamp, e.id",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?;
    let starts: Vec<f64> = tx
        .query(
            "SELECT extract(epoch FROM started_at)::float8 FROM sessions
             WHERE user_id = $1 ORDER BY started_at",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| row.get(0))
        .collect();
    if rows.is_empty() || starts.is_empty() {
        return Ok(HashSet::new());
    }
    struct Row {
        last_activity: Option<f64>,
        kind: Option<String>,
        timestamp: Option<f64>,
    }
    let mut grouped: HashMap<i32, Vec<Row>> = HashMap::new();
    for row in &rows {
        grouped.entry(row.get(0)).or_default().push(Row {
            last_activity: row.get(1),
            kind: row.get(2),
            timestamp: row.get(3),
        });
    }
    let mut excluded = HashSet::new();
    for (thread_id, thread_rows) in grouped {
        let boundary = thread_rows.first().and_then(|row| row.last_activity);
        let after_reset = |row: &Row| match (row.kind.is_some(), row.timestamp, boundary) {
            (true, Some(timestamp), Some(boundary)) => timestamp > boundary,
            (true, Some(_), None) => true,
            _ => false,
        };
        let snoozes: Vec<f64> = thread_rows
            .iter()
            .filter(|row| row.kind.as_deref() == Some("snooze") && after_reset(row))
            .filter_map(|row| row.timestamp)
            .collect();
        if snoozes.is_empty() {
            continue;
        }
        let unsnoozes: Vec<f64> = thread_rows
            .iter()
            .filter(|row| row.kind.as_deref() == Some("unsnooze") && after_reset(row))
            .filter_map(|row| row.timestamp)
            .collect();
        let latest_snooze = snoozes.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        if unsnoozes.iter().copied().fold(f64::NEG_INFINITY, f64::max) > latest_snooze {
            continue;
        }
        let later = starts
            .iter()
            .filter(|start| **start > latest_snooze)
            .count() as i64;
        if !is_backoff_eligible(snoozes.len() as i64, later) {
            excluded.insert(thread_id);
        }
    }
    Ok(excluded)
}

/// Reader-owned durable queue exclusions (`fetch_excluded_thread_ids`).
/// Durable "Remove from Queue" exclusions, reader-owned rather than
/// session-owned: the series stays out of the roll pool across sessions until
/// it is explicitly restored (#3807).
pub(crate) async fn excluded_status_ids(
    tx: &Transaction<'_>,
    user_id: i32,
) -> Result<Vec<i32>, ApiError> {
    Ok(tx
        .query(
            "SELECT id FROM threads WHERE user_id = $1 AND status = 'excluded' ORDER BY id",
            &[&user_id],
        )
        .await
        .map_err(db::query_error)?
        .iter()
        .map(|row| row.get(0))
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backoff_sequence_matches_python() {
        assert_eq!(
            (1..=6).map(compute_backoff_sessions).collect::<Vec<_>>(),
            vec![1, 1, 2, 2, 3, 3]
        );
        assert!(is_backoff_eligible(0, 0));
        assert!(is_backoff_eligible(1, 1));
        assert!(!is_backoff_eligible(3, 1));
        assert!(is_backoff_eligible(3, 2));
    }
}
