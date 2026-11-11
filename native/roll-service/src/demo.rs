//! Identity-free, read-only guest Roll sample.

use axum::Json;
use serde::Serialize;

/// The product-owned deterministic guest Roll fixture.
#[derive(Serialize, utoipa::ToSchema)]
pub struct DemoRoll {
    pub thread_id: i32,
    pub title: &'static str,
    pub format: &'static str,
    pub issues_remaining: i32,
    pub queue_position: i32,
    pub die_size: i32,
    pub result: i32,
    pub offset: i32,
    pub snoozed_count: i32,
    pub issue_id: Option<i32>,
    pub issue_number: Option<&'static str>,
    pub next_issue_id: Option<i32>,
    pub next_issue_number: Option<&'static str>,
    pub total_issues: Option<i32>,
    pub reading_progress: Option<&'static str>,
    pub explanation: Option<&'static str>,
}

/// Return a fixed sample without authentication, state or database access.
pub async fn read_demo_roll() -> Json<DemoRoll> {
    Json(DemoRoll {
        thread_id: 999,
        title: "Sample: The Dark Knight Returns (Demo)",
        format: "comic",
        issues_remaining: 3,
        queue_position: 1,
        die_size: 6,
        result: 4,
        offset: 0,
        snoozed_count: 0,
        issue_id: Some(1001),
        issue_number: Some("#4"),
        next_issue_id: Some(1002),
        next_issue_number: Some("#5"),
        total_issues: Some(12),
        reading_progress: Some("Late in arc — the final act is building."),
        explanation: Some("Demo roll: seeded sample data, no account state."),
    })
}

/// Generated contract for the public guest sample.
#[utoipa::path(
    get,
    path = "/api/v2/demo-roll",
    tag = "demo",
    responses((status = 200, description = "Deterministic sample Roll", body = DemoRoll))
)]
pub fn read_demo_roll_documentation() {}

#[cfg(test)]
mod tests {
    use super::read_demo_roll;

    #[tokio::test]
    async fn guest_sample_is_deterministic_and_has_no_identity() {
        let first = serde_json::to_value(read_demo_roll().await.0).unwrap();
        let second = serde_json::to_value(read_demo_roll().await.0).unwrap();
        assert_eq!(first, second);
        assert_eq!(first["title"], "Sample: The Dark Knight Returns (Demo)");
        assert_eq!(first["die_size"], 6);
        assert_eq!(first["result"], 4);
        assert_eq!(
            first["reading_progress"],
            "Late in arc — the final act is building."
        );
        for key in ["user_id", "session_id", "account_id"] {
            assert!(first.get(key).is_none());
        }
    }
}
