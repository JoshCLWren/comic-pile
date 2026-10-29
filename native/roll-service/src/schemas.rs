//! Roll v2 bootstrap response schemas matching Python contract.

use serde::{Deserialize, Serialize};
use std::time::Duration;

/// V2 bootstrap response superset with rollable and last_read fields.
#[derive(Serialize, Deserialize, Clone)]
pub struct RollV2BootstrapResponse {
    pub session_id: i64,
    pub user_id: i64,

    pub current_die: i32,
    pub manual_die: Option<i32>,
    pub pending_thread_id: Option<i64>,
    pub last_rolled_result: Option<i32>,

    pub session_mode: SessionMode,
    pub active_thread: Option<ActiveThreadInfo>,
    pub roll_recovery: Option<RollRecoveryInfo>,
    pub bandwidth: SessionBandwidthState,

    pub rollable: Vec<RollableItem>,
    pub last_read: Option<RollLastRead>,

    pub snoozed_threads: Vec<RollableThread>,
    pub snoozed_count: i32,
    pub skipped_thread_ids: Vec<i64>,
    pub skipped_threads: Vec<RollableThread>,
    pub blocked_count: i32,
    pub blocked_threads: Vec<RollableThread>,
    pub stale_thread_count: i32,
    pub stale_thread: Option<RollableThread>,
    pub timezone: Option<String>,
}

/// Thread information for rollable items.
#[derive(Serialize, Deserialize, Clone)]
pub struct RollableThread {
    pub id: i64,
    pub title: String,
    pub format: String,
    pub last_activity_at: Option<String>,
}

/// Issue information for rollable items.
#[derive(Serialize, Deserialize, Clone)]
pub struct RollableIssue {
    pub id: Option<i64>,
    pub number: Option<String>,
    pub canonical_series_title: Option<String>,
    pub cover_url: Option<String>,
}

/// Identity information for rollable items.
#[derive(Serialize, Deserialize, Clone)]
pub struct RollableIdentity {
    pub source: String,
    pub canonical_series_id: Option<String>,
    pub state: String,
    pub series_mapping_state: String,
}

/// Reader context for rollable items.
#[derive(Serialize, Deserialize, Clone)]
pub struct RollableReader {
    pub latest_rating: Option<f64>,
    pub average_rating: Option<f64>,
    pub rating_count: Option<i32>,
    pub read_count: Option<i32>,
    pub issue_count: Option<i32>,
    pub progress_scope: String,
}

/// Route information for rollable items.
#[derive(Serialize, Deserialize, Clone)]
pub struct RollableRoute {
    pub kind: String,
    pub name: String,
}

/// A single rollable candidate thread with issue and context.
#[derive(Serialize, Deserialize, Clone)]
pub struct RollableItem {
    pub thread: RollableThread,
    pub issue: RollableIssue,
    pub identity: RollableIdentity,
    pub reader: RollableReader,
    pub routes: Vec<RollableRoute>,
    pub overflow_routes_count: i32,
}

/// Session-scoped last read information.
#[derive(Serialize, Deserialize, Clone)]
pub struct RollLastRead {
    pub issue_id: Option<i64>,
    pub issue_number: Option<String>,
    pub thread_id: Option<i64>,
    pub thread_title: Option<String>,
    pub read_at: Option<String>,
}

/// Roll recovery information.
#[derive(Serialize, Deserialize, Clone)]
pub struct RollRecoveryInfo {
    pub pending_thread_id: Option<i64>,
    pub pending_thread_title: Option<String>,
    pub excluded_thread_ids: Vec<i64>,
}

/// Session mode state.
#[derive(Serialize, Deserialize, Clone)]
pub struct SessionMode {
    pub active_bandwidth: String,
    pub predicted_bandwidth: String,
    pub bandwidth_confidence: f64,
    pub bandwidth_source: String,
    pub bandwidth_version: String,
    pub active_intent: String,
    pub predicted_intent: String,
    pub intent_confidence: f64,
    pub intent_source: String,
    pub intent_version: String,
    pub session_mode_correction_guidance: Option<String>,
}

/// Active thread information.
#[derive(Serialize, Deserialize, Clone)]
pub struct ActiveThreadInfo {
    pub id: i64,
    pub title: String,
    pub format: String,
    pub last_rolled_result: Option<i32>,
}

/// Session bandwidth state.
#[derive(Serialize, Deserialize, Clone)]
pub struct SessionBandwidthState {
    pub predicted_bandwidth: String,
    pub active_bandwidth: String,
    pub confidence: f64,
    pub source: String,
    pub mode_version: String,
}

impl RollV2BootstrapResponse {
    /// Summary limit for bounded collections.
    pub const SUMMARY_LIMIT: usize = 20;
}

impl RollableThread {
    pub fn new(id: i64, title: String, format: String, last_activity_at: Option<String>) -> Self {
        Self {
            id,
            title,
            format,
            last_activity_at,
        }
    }
}

impl RollableItem {
    pub fn new(
        thread: RollableThread,
        issue: RollableIssue,
        identity: RollableIdentity,
        reader: RollableReader,
        routes: Vec<RollableRoute>,
        overflow_routes_count: i32,
    ) -> Self {
        Self {
            thread,
            issue,
            identity,
            reader,
            routes,
            overflow_routes_count,
        }
    }
}

impl RollLastRead {
    pub fn new(
        issue_id: Option<i64>,
        issue_number: Option<String>,
        thread_id: Option<i64>,
        thread_title: Option<String>,
        read_at: Option<String>,
    ) -> Self {
        Self {
            issue_id,
            issue_number,
            thread_id,
            thread_title,
            read_at,
        }
    }
}
