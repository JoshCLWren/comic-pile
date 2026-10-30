//! Batched historical effort and pure bandwidth inference, matching Python's v1 policy.
use crate::{auth::AuthenticatedUser, db, ApiError};
use serde_json::Value;
use std::collections::HashMap;
use tokio_postgres::Transaction;

#[derive(Clone, Copy)]
struct Observation {
    minutes: f64,
    snoozed: bool,
}
fn infer(observations: &[Observation], hour: Option<u32>) -> (&'static str, f64) {
    let effort: Vec<_> = observations.iter().filter(|o| o.minutes > 0.0).collect();
    if effort.len() < 3 {
        return ("balanced", 0.1);
    }
    let mut fractions = [0.0_f64; 3];
    for o in &effort {
        fractions[if o.minutes <= 10.0 {
            0
        } else if o.minutes >= 20.0 {
            2
        } else {
            1
        }] += 1.0;
    }
    for fraction in &mut fractions {
        *fraction /= effort.len() as f64;
    }
    let snoozes = observations.iter().filter(|o| o.snoozed).count();
    let heavy = observations
        .iter()
        .filter(|o| o.snoozed && o.minutes >= 20.0)
        .count();
    let prior: f64 = match hour {
        None | Some(12..=17) => 0.0,
        Some(18..=22) => 0.05,
        _ => 0.10,
    };
    let mut scores = fractions;
    if snoozes > 0 {
        scores[2] = (scores[2] - heavy as f64 / snoozes as f64 * 0.3).max(0.0);
    }
    scores[0] -= prior;
    scores[2] += prior;
    let mut winner = 0;
    for i in 1..3 {
        if scores[i] > scores[winner] {
            winner = i;
        }
    }
    let top = scores[winner];
    let tied = (scores[0] - top).abs() < 1e-9 && (scores[2] - top).abs() < 1e-9;
    if tied {
        winner = 1;
    }
    let mut confidence =
        (fractions[winner] * (effort.len() as f64 / 6.0).min(1.0) + prior * 0.2).min(0.95);
    if fractions.iter().copied().fold(0.0, f64::max) < 0.40 || tied {
        confidence *= 0.6;
    }
    (
        ["light", "balanced", "deep"][winner],
        (confidence * 10000.0).round_ties_even() / 10000.0,
    )
}
fn median(values: Option<&Vec<f64>>) -> Option<f64> {
    let mut v = values.filter(|v| v.len() >= 2)?.clone();
    v.sort_by(f64::total_cmp);
    let mid = v.len() / 2;
    Some(if v.len() % 2 == 0 {
        (v[mid - 1] + v[mid]) / 2.0
    } else {
        v[mid]
    })
}
fn year(metadata: &Value) -> Option<i32> {
    for key in ["cover_date", "store_date"] {
        if let Some(s) = metadata[key].as_str() {
            for b in s.as_bytes().windows(4) {
                if (b.starts_with(b"19") || b.starts_with(b"20"))
                    && b.iter().all(u8::is_ascii_digit)
                {
                    return std::str::from_utf8(b).ok()?.parse().ok();
                }
            }
        }
    }
    None
}
/// No N+1: history and both metadata levels are read once each. Owner joins fence all data.
/// Inference errors are propagated to avoid committing an aborted PostgreSQL transaction.
pub(crate) async fn predict(
    tx: &Transaction<'_>,
    user: AuthenticatedUser,
    started_at: Option<&str>,
) -> Result<(&'static str, f64), ApiError> {
    let rows = tx
        .query(
            "SELECT r.thread_id, r.issue_id, r.session_id, x.type,
      extract(epoch FROM (r.timestamp-x.timestamp))::float8 AS seconds,
      EXISTS(SELECT 1 FROM events z WHERE z.session_id=r.session_id AND z.type='snooze'
         AND z.thread_id=r.thread_id AND z.timestamp>x.timestamp AND z.timestamp<r.timestamp),
      x.selected_thread_id = r.thread_id
      FROM events r JOIN threads t ON t.id=r.thread_id
      LEFT JOIN events x ON x.id=r.source_roll_event_id
      WHERE t.user_id=$1 AND r.type='rate' ORDER BY r.id",
            &[&user.id()],
        )
        .await
        .map_err(db::query_error)?;
    let mut by_thread: HashMap<i32, Vec<f64>> = HashMap::new();
    let mut by_issue: HashMap<(i32, i32), Vec<f64>> = HashMap::new();
    for r in &rows {
        let seconds: Option<f64> = r.get(4);
        let kind: Option<&str> = r.get(3);
        if kind == Some("roll") && r.get::<_, Option<bool>>(6) == Some(true) {
            if let Some(s) = seconds.filter(|s| (60.0..=21600.0).contains(s)) {
                let thread: i32 = r.get(0);
                by_thread.entry(thread).or_default().push(s / 60.0);
                if let Some(issue) = r.get::<_, Option<i32>>(1) {
                    by_issue.entry((thread, issue)).or_default().push(s / 60.0);
                }
            }
        }
    }
    let metadata = tx.query("SELECT kind,target,metadata FROM (
      SELECT 'issue' AS kind,m.issue_id AS target,e.metadata_json::text AS metadata,m.id FROM issue_external_identity_mappings m
      JOIN external_identities e ON e.id=m.external_identity_id JOIN issues i ON i.id=m.issue_id
      JOIN threads t ON t.id=i.thread_id WHERE t.user_id=$1 AND m.status='confirmed'
      UNION ALL SELECT 'thread',m.thread_id,e.metadata_json::text,m.id FROM thread_external_series_mappings m
      JOIN external_identities e ON e.id=m.external_identity_id JOIN threads t ON t.id=m.thread_id
      WHERE t.user_id=$1 AND m.status='confirmed') mappings ORDER BY kind,id", &[&user.id()]).await.map_err(db::query_error)?;
    let mut years = HashMap::new();
    for m in metadata {
        let data: Value = serde_json::from_str(m.get(2)).unwrap_or(Value::Null);
        if let Some(year) = year(&data) {
            years
                .entry((m.get::<_, String>(0), m.get::<_, i32>(1)))
                .or_insert(year);
        }
    }
    // Each sample group is immutable after collection. Sort it once, not once
    // per rating, while the bootstrap transaction holds the user's lock.
    let thread_medians: HashMap<i32, f64> = by_thread
        .into_iter()
        .filter_map(|(thread, samples)| median(Some(&samples)).map(|value| (thread, value)))
        .collect();
    let issue_medians: HashMap<(i32, i32), f64> = by_issue
        .into_iter()
        .filter_map(|(key, samples)| median(Some(&samples)).map(|value| (key, value)))
        .collect();
    let mut observations = Vec::new();
    for r in rows {
        if r.get::<_, Option<i32>>(2).is_none() || r.get::<_, Option<bool>>(6) != Some(true) {
            continue;
        }
        let thread = r.get::<_, i32>(0);
        let issue = r.get::<_, Option<i32>>(1);
        let observed = issue
            .and_then(|i| issue_medians.get(&(thread, i)).copied())
            .or_else(|| thread_medians.get(&thread).copied());
        let publication = issue
            .and_then(|i| years.get(&("issue".into(), i)))
            .or_else(|| years.get(&("thread".into(), thread)));
        let minutes = observed.or_else(|| {
            publication.map(|y| {
                if *y <= 1969 {
                    10.0
                } else if *y < 2000 {
                    14.0
                } else {
                    17.0
                }
            })
        });
        if let Some(minutes) = minutes {
            observations.push(Observation {
                minutes,
                snoozed: r.get(5),
            });
        }
    }
    // Python history reads autoflush new sessions before applying the UTC daypart.
    let hour = started_at
        .and_then(|s| s.get(11..13))
        .and_then(|s| s.parse().ok());
    Ok(infer(&observations, hour))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn inference_and_metadata_boundaries() {
        assert_eq!(infer(&[], Some(8)), ("balanced", 0.1));
        assert_eq!(
            infer(
                &[Observation {
                    minutes: 5.0,
                    snoozed: false
                }; 6],
                None
            ),
            ("light", 0.95)
        );
        assert_eq!(
            infer(
                &[Observation {
                    minutes: 25.0,
                    snoozed: false
                }; 3],
                Some(8)
            ),
            ("deep", 0.52)
        );
        assert_eq!(
            year(&serde_json::json!({"cover_date":"bad","store_date":"c. 1965"})),
            Some(1965)
        );
        assert_eq!(year(&serde_json::json!({"cover_date":1990})), None);
        // A single issue observation cannot supply an issue median; its thread's
        // aggregate remains the fallback, and even-sized samples use the mean.
        assert_eq!(median(Some(&vec![25.0])), None);
        assert_eq!(median(Some(&vec![25.0, 5.0, 15.0])), Some(15.0));
        assert_eq!(median(Some(&vec![25.0, 5.0])), Some(15.0));
    }
}
