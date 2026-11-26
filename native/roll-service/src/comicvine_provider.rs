//! Shared ComicVine provider transport, normalization and synchronous hydration.
//!
//! Hydration is request/response work: there is no queue, scheduler, lease,
//! dispatch or background drain here. Every provider call is awaited inside the
//! HTTP request that requested it, already-persisted metadata is preserved on
//! failure, and no detached task outlives the response.
use crate::{
    comicvine_limits::{parse_retry_after, python_envelope_ok},
    db,
    outbound::{OutboundHttp, OutboundRequest},
    ApiError, AppState,
};
use axum::http::StatusCode;
use bytes::Bytes;
use http_body_util::BodyExt;
use serde_json::{json, Map, Value};
use std::{sync::Arc, time::Duration};

const HOST: &str = "comicvine.gamespot.com";
const MAX_BODY: usize = 2_000_000;
const PROVIDER_TIMEOUT: Duration = Duration::from_secs(5);
// Shared with comicvine_issue.rs READ_SQL: complete rows stay fresh 30 days;
// a deep response with empty credits is rechecked after 7 days. The two
// implementations must use the same precise policy (see needs_provider_fetch).
const COMPLETE_FRESH_DAYS: i64 = 30;
const EMPTY_CREDIT_RECHECK_DAYS: i64 = 7;

pub(crate) const FIELDS: &str = "id,name,issue_number,cover_date,store_date,image,volume,person_credits,character_credits,team_credits,story_arc_credits,date_last_updated";
#[derive(Debug)]
pub(crate) enum ProviderFailure {
    RateLimited(u32),
    Unavailable,
    Timeout,
    InvalidPayload,
}

/// Truthful outcome of one bounded, awaited ComicVine metadata hydration.
/// These are terminal results of the current HTTP invocation, not queue states:
/// an interactive caller can distinguish success from a legitimate empty roster
/// and from each provider failure class without waiting for a scheduler.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum HydrationOutcome {
    /// Deep metadata (including creator names and roles) was persisted.
    Complete,
    /// A valid deep payload genuinely has no creator credits. The empty result
    /// is persisted rather than being mistaken for a failure.
    NoCredits,
    /// No confirmed identity for this owned issue, or the identity changed
    /// while the provider was in flight (a late A must never overwrite B).
    NotConfirmed,
    /// `COMICVINE_API_KEY` is absent; distinct from a provider failure.
    NotConfigured,
    /// Provider outage, invalid envelope, or a transport/database failure.
    Unavailable,
    /// Provider throttled the bounded attempt; honour its Retry-After.
    RateLimited { retry_after_seconds: u32 },
    /// The single bounded attempt exceeded the request budget or provider timeout.
    Timeout,
    /// Provider payload was malformed or did not match the confirmed identity.
    InvalidResponse,
}

impl HydrationOutcome {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Complete => "complete",
            Self::NoCredits => "no_credits",
            Self::NotConfirmed => "not_confirmed",
            Self::NotConfigured => "provider_not_configured",
            Self::Unavailable => "provider_unavailable",
            Self::RateLimited { .. } => "rate_limited",
            Self::Timeout => "timeout",
            Self::InvalidResponse => "invalid_response",
        }
    }

    /// True for a terminal complete/no-credits outcome, including reuse of
    /// already-complete cached metadata.
    pub(crate) fn refreshed(self) -> bool {
        matches!(self, Self::Complete | Self::NoCredits)
    }

    pub(crate) fn retry_after_seconds(self) -> Option<i32> {
        match self {
            Self::RateLimited {
                retry_after_seconds,
            } => Some(retry_after_seconds as i32),
            _ => None,
        }
    }
}

impl From<ProviderFailure> for HydrationOutcome {
    fn from(error: ProviderFailure) -> Self {
        match error {
            ProviderFailure::RateLimited(delay) => Self::RateLimited {
                retry_after_seconds: delay,
            },
            ProviderFailure::Unavailable => Self::Unavailable,
            ProviderFailure::Timeout => Self::Timeout,
            ProviderFailure::InvalidPayload => Self::InvalidResponse,
        }
    }
}

/// Persist fetched deep metadata only while the same confirmed identity is
/// still mapped to the same owned issue. The `EXISTS` recheck fences a
/// concurrent A -> B remap: a late A response affects zero rows and can never
/// overwrite B's metadata.
const PERSIST_SYNC: &str = r#"
UPDATE external_identities e
SET metadata_json = (COALESCE(e.metadata_json::jsonb, '{}'::jsonb)
                     || ($2::text)::jsonb)::json,
    external_url = COALESCE($3, e.external_url),
    provider_updated_at = COALESCE(($4::text)::timestamptz, e.provider_updated_at),
    updated_at = now()
WHERE e.id = $1 AND e.provider = 'comicvine' AND e.entity_type = 'issue'
  AND EXISTS (
    SELECT 1 FROM issue_external_identity_mappings m
    JOIN issues i ON i.id = m.issue_id
    JOIN threads t ON t.id = i.thread_id
    WHERE m.external_identity_id = e.id
      AND m.issue_id = $5 AND m.status = 'confirmed'
      AND t.user_id = $6
  )
"#;

pub(crate) async fn hydrate_confirmed_identity_inline(
    state: &AppState,
    user_id: i32,
    issue_id: i32,
    budget: Duration,
    api_key: &str,
    force: bool,
) {
    let _ = hydrate_confirmed_identity_sync(state, user_id, issue_id, budget, api_key, force).await;
}

/// Extract the numeric ComicVine issue id from an external identity id.
fn issue_id_from_external(external_id: &str) -> Option<u32> {
    issue_id(external_id)
}

/// Keep cached creator credits when a fresh fetch did not include a roster.
fn preserve_cached_credits(patch: &mut Value, cached: Option<&Value>) {
    let Some(existing) = cached else {
        return;
    };
    if existing["creator_credits"]
        .as_array()
        .is_some_and(|v| !v.is_empty())
    {
        if let Some(obj) = patch.as_object_mut() {
            obj.insert(
                "creator_credits".to_owned(),
                existing["creator_credits"].clone(),
            );
        }
    } else if existing["raw_provider_payload"]["person_credits"]
        .as_array()
        .is_some_and(|v| !v.is_empty())
    {
        if let Some(obj) = patch.as_object_mut() {
            obj.insert(
                "creator_credits".to_owned(),
                compact_refs(&existing["raw_provider_payload"]["person_credits"]),
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::outbound::{OutboundFuture, OutboundResponse};
    use axum::{body::Body, http::HeaderMap};
    use deadpool_postgres::Object;
    use std::{any::Any, sync::Mutex};

    fn deep_provider_result(issue_id: u32, date_last_updated: &str) -> Value {
        json!({
            "id": issue_id,
            "name": "Going For It",
            "issue_number": "3",
            "cover_date": "1988-03-01",
            "store_date": "1988-03-24",
            "image": {"medium_url": "https://img.example/medium.jpg"},
            "volume": {"id": 4001, "name": "Hellblazer"},
            "person_credits": [{"id": 1, "name": "Writer", "role": "writer"}],
            "character_credits": [],
            "team_credits": [],
            "story_arc_credits": [{"id": 4, "name": "Arc"}],
            "date_last_updated": date_last_updated,
        })
    }

    /// Push a canned provider response into the recording outbound fake.
    fn push_deep_provider_result(state: &AppState, issue_id: u32, date_last_updated: &str) {
        let body = json!({
            "status_code": 1,
            "results": deep_provider_result(issue_id, date_last_updated),
        })
        .to_string();
        state.recording_fake().expect("recording provider").push_ok(
            StatusCode::OK,
            HeaderMap::new(),
            Bytes::from(body),
        );
    }

    /// #5695: `provider_exchange` refuses non-alphanumeric credential bytes
    /// before any round trip, so an untrimmed read used to surface a pasted
    /// dashboard value with a trailing newline as a provider outage in tens of
    /// milliseconds. Normalization must make a padded key indistinguishable
    /// from a clean one, and an all-whitespace value "not configured".
    #[test]
    fn provider_api_key_normalizes_surrounding_whitespace() {
        assert_eq!(
            normalize_provider_api_key("c0ffee1234"),
            Some("c0ffee1234".to_owned())
        );
        assert_eq!(
            normalize_provider_api_key("  c0ffee1234\n"),
            Some("c0ffee1234".to_owned())
        );
        assert_eq!(
            normalize_provider_api_key("\tc0ffee1234 \r\n"),
            Some("c0ffee1234".to_owned())
        );
        assert_eq!(normalize_provider_api_key(""), None);
        assert_eq!(normalize_provider_api_key(" \n\t\r"), None);
    }

    /// #5695: the transport must enforce the same normalization as the read
    /// boundary, even when a future caller supplies a padded key directly.
    /// Blank and malformed credentials must fail before any outbound request.
    #[tokio::test]
    async fn provider_exchange_normalizes_key_before_request() {
        let fake = Arc::new(crate::outbound::RecordingFakeOutbound::new());
        fake.push_ok(
            StatusCode::OK,
            HeaderMap::new(),
            Bytes::from_static(br#"{"status_code":1,"results":{}}"#),
        );
        let outbound: Arc<dyn crate::outbound::OutboundHttp> = fake.clone();

        let exchange = provider_exchange(&outbound, "issue/4000-1", "", " \tTESTKEY123\n")
            .await
            .expect("padded credential must reach the provider");
        assert!(matches!(exchange, Exchange::Payload(_)));

        let calls = fake.calls();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].host, HOST);
        assert_eq!(
            calls[0].path,
            "/api/issue/4000-1/?api_key=TESTKEY123&format=json"
        );

        fake.clear();
        let error = provider_exchange(&outbound, "issue/4000-1", "", " \n\t")
            .await
            .expect_err("blank credential must be unconfigured");
        assert!(matches!(error, ProviderFailure::Unavailable));
        assert!(fake.calls().is_empty());

        let error = provider_exchange(&outbound, "issue/4000-1", "", "TEST KEY123")
            .await
            .expect_err("internal whitespace must remain malformed");
        assert!(matches!(error, ProviderFailure::Unavailable));
        assert!(fake.calls().is_empty());
    }

    /// The inline catalog path runs only after its identity transaction has
    /// committed. Passing another owner's issue id must neither fetch nor
    /// mutate that owner's provider identity, while the requested owner's
    /// sparse identity receives the complete response and UTC revision.
    #[tokio::test]
    async fn post_commit_hydration_is_owner_scoped_and_persists_utc_metadata() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let connection = db::checkout(&state).await.expect("seed connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username) VALUES \
                   (1, 'repair-owner'), (2, 'repair-other'); \
                 INSERT INTO threads \
                   (id, title, format, issues_remaining, queue_position, status, user_id) \
                 VALUES \
                   (11, 'Owned', 'Series', 1, 1, 'active', 1), \
                   (12, 'Other', 'Series', 1, 1, 'active', 2); \
                 INSERT INTO issues \
                   (id, thread_id, issue_number, status, position, created_at) \
                 VALUES \
                   (101, 11, '3', 'unread', 1, now()), \
                   (102, 12, '3', 'unread', 1, now()); \
                 INSERT INTO external_identities \
                   (id, provider, entity_type, external_id, metadata_json, \
                    provider_updated_at, created_at, updated_at) \
                 VALUES \
                   (201, 'comicvine', 'issue', '4000-29319', \
                    '{\"issue_number\":\"3\"}'::json, \
                    TIMESTAMPTZ '2025-01-01 00:00:00+00', now(), now()), \
                   (202, 'comicvine', 'issue', '4000-29320', \
                    '{\"issue_number\":\"other\"}'::json, \
                    TIMESTAMPTZ '2025-02-02 00:00:00+00', now(), now()); \
                 INSERT INTO issue_external_identity_mappings \
                   (issue_id, external_identity_id, status, evidence_source, confidence, \
                    evidence_json, created_at, updated_at) \
                 VALUES \
                   (101, 201, 'confirmed', 'user_series_confirmation', 1.0, \
                    '{}'::json, now(), now()), \
                   (102, 202, 'confirmed', 'user_series_confirmation', 1.0, \
                    '{}'::json, now(), now());",
            )
            .await
            .expect("seed committed owner mappings");
        drop(Object::take(connection));
        push_deep_provider_result(&state, 29319, "2026-11-01 17:33:53");

        hydrate_catalog_commit_with_key(
            &state,
            1,
            &[101, 102],
            Duration::from_secs(5),
            "TESTKEY123",
        )
        .await;

        let connection = db::checkout(&state).await.expect("assert connection");
        let owned = connection
            .query_one(
                "SELECT metadata_json::text, provider_updated_at \
                 FROM external_identities WHERE id = 201",
                &[],
            )
            .await
            .expect("read owned hydration");
        let metadata: Value = serde_json::from_str(owned.get(0)).expect("owned metadata JSON");
        assert_eq!(metadata["creator_credits"][0]["name"], "Writer");
        assert_eq!(metadata["story_arcs"][0]["name"], "Arc");
        assert!(metadata["deep_metadata_refreshed_at"].is_string());
        let provider_updated_at: Option<chrono::DateTime<chrono::Utc>> = owned.get(1);
        assert_eq!(
            provider_updated_at,
            Some(
                chrono::DateTime::parse_from_rfc3339("2026-11-01T17:33:53+00:00")
                    .expect("expected revision")
                    .with_timezone(&chrono::Utc)
            )
        );

        let other = connection
            .query_one(
                "SELECT metadata_json::text, provider_updated_at \
                 FROM external_identities WHERE id = 202",
                &[],
            )
            .await
            .expect("read other owner identity");
        let other_metadata: Value =
            serde_json::from_str(other.get(0)).expect("other owner metadata JSON");
        assert_eq!(other_metadata, json!({"issue_number": "other"}));
        let other_revision: Option<chrono::DateTime<chrono::Utc>> = other.get(1);
        assert_eq!(
            other_revision,
            Some(
                chrono::DateTime::parse_from_rfc3339("2025-02-02T00:00:00+00:00")
                    .expect("original revision")
                    .with_timezone(&chrono::Utc)
            )
        );
        drop(Object::take(connection));

        let calls = state.recording_fake().expect("recording provider").calls();
        assert_eq!(calls.len(), 1, "cross-owner ids must not be fetched");
        assert!(calls[0].path.starts_with("/api/issue/4000-29319/?"));
    }

    /// Seed an owned issue with a freshly `user_confirmed` ComicVine identity
    /// and the pending fallback refresh row written by the enqueue savepoint.
    async fn seed_confirmed_identity(state: &AppState, external_id: &str, metadata: &Value) -> i32 {
        let connection = db::checkout(state).await.expect("seed connection");
        connection
            .batch_execute(
                "INSERT INTO users (id, username, is_admin, created_at) \
                 VALUES (1, 'confirm-owner', false, now()); \
                 INSERT INTO threads \
                   (id, title, format, issues_remaining, queue_position, status, user_id) \
                 VALUES (1, 'Owned', 'Series', 1, 1, 'active', 1); \
                 INSERT INTO issues (id, thread_id, issue_number, status, position, created_at) \
                 VALUES (1, 1, '3', 'unread', 1, now());",
            )
            .await
            .expect("seed owner");
        let identity_id: i32 = connection
            .query_one(
                "INSERT INTO external_identities \
                   (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
                 VALUES ('comicvine', 'issue', $1, ($2::text)::json, now(), now()) \
                 RETURNING id",
                &[&external_id, &metadata.to_string()],
            )
            .await
            .expect("seed identity")
            .get(0);
        connection
            .execute(
                "INSERT INTO issue_external_identity_mappings \
                   (issue_id, external_identity_id, status, evidence_source, confidence, \
                    evidence_json, created_at, updated_at) \
                 VALUES (1, $1, 'confirmed', 'user_confirmed', 1.0, '{}'::json, now(), now())",
                &[&identity_id],
            )
            .await
            .expect("seed mapping");
        drop(Object::take(connection));
        identity_id
    }

    #[tokio::test]
    async fn inline_hydration_persists_creator_names_and_roles_after_confirm() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_confirmed_identity(&state, "4000-29319", &json!({})).await;
        push_deep_provider_result(&state, 29319, "2026-11-01 17:33:53");

        hydrate_confirmed_identity_inline(&state, 1, 1, Duration::from_secs(5), "TESTKEY123", true)
            .await;

        let connection = db::checkout(&state).await.expect("assert connection");
        let metadata: Value = serde_json::from_str(
            connection
                .query_one(
                    "SELECT metadata_json::text FROM external_identities WHERE id = $1",
                    &[&identity_id],
                )
                .await
                .expect("read hydrated metadata")
                .get(0),
        )
        .expect("metadata JSON");
        assert_eq!(metadata["creator_credits"][0]["name"], "Writer");
        assert_eq!(metadata["creator_credits"][0]["role"], "writer");
        assert_eq!(metadata["story_arcs"][0]["name"], "Arc");
        drop(Object::take(connection));
        let calls = state.recording_fake().expect("recording provider").calls();
        assert_eq!(calls.len(), 1);
        assert!(calls[0].path.starts_with("/api/issue/4000-29319/?"));
    }

    #[tokio::test]
    async fn inline_hydration_failure_keeps_mapping_and_stored_metadata() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_confirmed_identity(&state, "4000-29319", &json!({})).await;
        // No canned provider response: the recording fake fails closed.

        hydrate_confirmed_identity_inline(&state, 1, 1, Duration::from_secs(5), "TESTKEY123", true)
            .await;

        let connection = db::checkout(&state).await.expect("assert connection");
        let mapping_status: String = connection
            .query_one(
                "SELECT m.status FROM issue_external_identity_mappings m \
                 WHERE m.external_identity_id = $1",
                &[&identity_id],
            )
            .await
            .expect("mapping kept")
            .get(0);
        assert_eq!(mapping_status, "confirmed");
        let metadata: Value = serde_json::from_str(
            connection
                .query_one(
                    "SELECT metadata_json::text FROM external_identities WHERE id = $1",
                    &[&identity_id],
                )
                .await
                .expect("read metadata")
                .get(0),
        )
        .expect("metadata JSON");
        assert_eq!(
            metadata,
            json!({}),
            "provider failure must not fabricate credits"
        );
        drop(Object::take(connection));
    }

    #[tokio::test]
    async fn inline_hydration_zero_credits_persists_truthful_empty_metadata() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_confirmed_identity(&state, "4000-29319", &json!({})).await;
        let mut empty = deep_provider_result(29319, "2026-11-01 17:33:53");
        empty["person_credits"] = json!([]);
        let body = json!({"status_code": 1, "results": empty}).to_string();
        state.recording_fake().expect("recording provider").push_ok(
            StatusCode::OK,
            HeaderMap::new(),
            Bytes::from(body),
        );

        hydrate_confirmed_identity_inline(&state, 1, 1, Duration::from_secs(5), "TESTKEY123", true)
            .await;

        let connection = db::checkout(&state).await.expect("assert connection");
        let metadata: Value = serde_json::from_str(
            connection
                .query_one(
                    "SELECT metadata_json::text FROM external_identities WHERE id = $1",
                    &[&identity_id],
                )
                .await
                .expect("read metadata")
                .get(0),
        )
        .expect("metadata JSON");
        assert_eq!(metadata["creator_credits"], json!([]));
        assert!(metadata["raw_provider_payload"].is_object());
        drop(Object::take(connection));
    }

    #[tokio::test]
    async fn inline_hydration_empty_roster_preserves_cached_credits() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_confirmed_identity(
            &state,
            "4000-29319",
            &json!({"creator_credits": [{"id": 9, "name": "Cached Writer", "role": "writer"}]}),
        )
        .await;
        let mut empty = deep_provider_result(29319, "2026-11-01 17:33:53");
        empty["person_credits"] = json!([]);
        let body = json!({"status_code": 1, "results": empty}).to_string();
        state.recording_fake().expect("recording provider").push_ok(
            StatusCode::OK,
            HeaderMap::new(),
            Bytes::from(body),
        );

        hydrate_confirmed_identity_inline(&state, 1, 1, Duration::from_secs(5), "TESTKEY123", true)
            .await;

        let connection = db::checkout(&state).await.expect("assert connection");
        let metadata: Value = serde_json::from_str(
            connection
                .query_one(
                    "SELECT metadata_json::text FROM external_identities WHERE id = $1",
                    &[&identity_id],
                )
                .await
                .expect("read metadata")
                .get(0),
        )
        .expect("metadata JSON");
        assert_eq!(metadata["creator_credits"][0]["name"], "Cached Writer");
        drop(Object::take(connection));
    }

    #[test]
    fn only_verified_singular_issue_payload_completes() {
        let result = json!({"id": 29319, "name":"Going For It", "issue_number":"3",
            "cover_date":"1988-03-01", "store_date":"1988-03-24", "image":{},
            "volume":{"id": 4001,"name":"Hellblazer"},
            "person_credits":[{"id":1,"name":"Jamie Delano","api_detail_url":"https://example"}],
            "character_credits":[], "team_credits":[], "story_arc_credits":[],
            "date_last_updated":"2020-01-01T00:00:00+00:00"});
        let (metadata, present, _, _) = normalized_metadata(&result, 29319).unwrap();
        assert!(present);
        assert_eq!(metadata["creator_credits"][0]["name"], "Jamie Delano");
        assert!(normalized_metadata(&result, 29320).is_err());
        let mut incomplete = result;
        incomplete.as_object_mut().unwrap().remove("person_credits");
        assert!(normalized_metadata(&incomplete, 29319).is_err());
    }
    #[test]
    fn provider_timestamp_accepts_rfc3339_and_comicvine_space_format() {
        assert_eq!(
            provider_timestamp(&json!("2020-01-01T00:00:00+00:00")).as_deref(),
            Some("2020-01-01T00:00:00+00:00")
        );
        assert_eq!(
            provider_timestamp(&json!("2020-01-01 00:00:00")).as_deref(),
            Some("2020-01-01T00:00:00+00:00")
        );
        assert!(provider_timestamp(&json!("not-a-timestamp")).is_none());
    }

    #[test]
    fn cached_metadata_requires_all_provider_fields_before_skipping_refresh() {
        let mut fields = Map::new();
        for field in FIELDS.split(',') {
            fields.insert(field.to_string(), Value::Null);
        }
        let mut metadata = json!({"raw_provider_payload": fields});
        assert!(has_complete_provider_payload(&metadata));
        metadata["raw_provider_payload"]
            .as_object_mut()
            .expect("provider payload")
            .remove("image");
        assert!(!has_complete_provider_payload(&metadata));
    }

    #[test]
    fn empty_credits_use_bounded_recheck_not_30_day_lock() {
        let now = chrono::DateTime::parse_from_rfc3339("2026-11-08T15:00:00+00:00")
            .unwrap()
            .with_timezone(&chrono::Utc);
        // Issue 1121330-shaped: deep payload complete, person_credits and
        // creator_credits empty, fetched ~1 day ago.
        let mut fields = Map::new();
        for field in FIELDS.split(',') {
            fields.insert(field.to_string(), Value::Null);
        }
        // Provider revision predates the deep fetch so only age decides.
        fields.insert(
            "date_last_updated".to_owned(),
            json!("2026-11-05T08:37:31Z"),
        );
        fields.insert("person_credits".to_owned(), json!([]));
        let empty_recent = json!({
            "raw_provider_payload": fields,
            "creator_credits": [],
            "deep_metadata_refreshed_at": "2026-11-07T21:09:17.019489+00:00",
        });
        // 1 day old: still within the 7-day empty recheck, no hot loop.
        assert!(!needs_provider_fetch(&empty_recent, now));
        // 8 days old: past the 7-day recheck, must fetch again. Provider
        // revision predates the deep fetch so only age decides.
        let mut old_fields = empty_recent["raw_provider_payload"].clone();
        old_fields.as_object_mut().expect("payload object").insert(
            "date_last_updated".to_owned(),
            json!("2026-10-20T08:37:31Z"),
        );
        let empty_old = json!({
            "raw_provider_payload": old_fields,
            "creator_credits": [],
            "deep_metadata_refreshed_at": "2026-10-26T15:00:00+00:00",
        });
        assert!(needs_provider_fetch(&empty_old, now));
        // Same age but populated (issue #24 shape): 8 days is still fresh.
        let full_old = json!({
            "raw_provider_payload": empty_old["raw_provider_payload"],
            "creator_credits": [{"id": 1, "name": "Creator One"}],
            "deep_metadata_refreshed_at": "2026-10-26T15:00:00+00:00",
        });
        assert!(!needs_provider_fetch(&full_old, now));
        // R1 regression: credits in only one array count as having credits.
        // A row with creator_credits empty but person_credits non-empty uses
        // the 30-day window (not the 7-day recheck), matching cached_has_credits
        // (creator || raw) and comicvine_issue.rs NOT (has credits).
        let mut person_old_fields = empty_old["raw_provider_payload"].clone();
        person_old_fields
            .as_object_mut()
            .expect("payload object")
            .insert(
                "person_credits".to_owned(),
                json!([{"id": 1, "name": "Creator One"}]),
            );
        let person_only_old = json!({
            "raw_provider_payload": person_old_fields,
            "creator_credits": [],
            "deep_metadata_refreshed_at": "2026-10-26T15:00:00+00:00",
        });
        assert!(cached_has_credits(&person_only_old));
        assert!(!needs_provider_fetch(&person_only_old, now));
        // 31 days old populated row is stale under the 30-day window.
        let mut stale_fields = empty_recent["raw_provider_payload"].clone();
        stale_fields
            .as_object_mut()
            .expect("payload object")
            .insert(
                "date_last_updated".to_owned(),
                json!("2026-09-01T08:37:31Z"),
            );
        let full_stale = json!({
            "raw_provider_payload": stale_fields,
            "creator_credits": [{"id": 1, "name": "Creator One"}],
            "deep_metadata_refreshed_at": "2026-10-01T15:00:00+00:00",
        });
        assert!(needs_provider_fetch(&full_stale, now));
        // Provider revision newer than the deep fetch forces a refetch even
        // when the deep timestamp is recent.
        let mut newer_fields = empty_recent["raw_provider_payload"].clone();
        newer_fields
            .as_object_mut()
            .expect("payload object")
            .insert(
                "date_last_updated".to_owned(),
                json!("2026-11-08T10:00:00Z"),
            );
        let provider_newer = json!({
            "raw_provider_payload": newer_fields,
            "creator_credits": [],
            "deep_metadata_refreshed_at": "2026-11-07T21:09:17.019489+00:00",
        });
        assert!(needs_provider_fetch(&provider_newer, now));
        // Missing/incomplete payload or timestamps are stale, never fresh.
        assert!(needs_provider_fetch(&json!({}), now));
        let no_timestamp = json!({
            "raw_provider_payload": empty_recent["raw_provider_payload"],
            "creator_credits": [{"id": 1, "name": "Creator One"}],
        });
        assert!(needs_provider_fetch(&no_timestamp, now));
    }

    #[test]
    fn cached_has_credits_detects_seven_creators_from_issue_24() {
        // Regression test for #4819/#24: verify that cached_has_credits correctly
        // identifies issues with multiple creators, which is used by
        // needs_provider_fetch() and process() for the 7-day recheck window.
        let metadata_with_seven = json!({
            "creator_credits": [
                {"id": 1, "name": "Creator One", "role": "writer"},
                {"id": 2, "name": "Creator Two", "role": "penciler"},
                {"id": 3, "name": "Creator Three", "role": "inker"},
                {"id": 4, "name": "Creator Four", "role": "colorist"},
                {"id": 5, "name": "Creator Five", "role": "letterer"},
                {"id": 6, "name": "Creator Six", "role": "cover"},
                {"id": 7, "name": "Creator Seven", "role": "editor"}
            ],
            "raw_provider_payload": {
                "person_credits": [
                    {"id": 1, "name": "Creator One", "role": "writer"},
                    {"id": 2, "name": "Creator Two", "role": "penciler"},
                    {"id": 3, "name": "Creator Three", "role": "inker"},
                    {"id": 4, "name": "Creator Four", "role": "colorist"},
                    {"id": 5, "name": "Creator Five", "role": "letterer"},
                    {"id": 6, "name": "Creator Six", "role": "cover"},
                    {"id": 7, "name": "Creator Seven", "role": "editor"}
                ]
            }
        });
        assert!(cached_has_credits(&metadata_with_seven));

        // Empty credits should return false.
        let empty_metadata = json!({
            "creator_credits": [],
            "raw_provider_payload": {"person_credits": []}
        });
        assert!(!cached_has_credits(&empty_metadata));

        // One creator should return true.
        let one_creator = json!({
            "creator_credits": [{"id": 1, "name": "One", "role": "writer"}],
            "raw_provider_payload": {"person_credits": []}
        });
        assert!(cached_has_credits(&one_creator));
    }

    /// #5592: ComicVine 420 is a rate limit (Python parity), not provider_unavailable.
    #[tokio::test]
    async fn provider_response_treats_420_as_rate_limited() {
        let fake = Arc::new(crate::outbound::RecordingFakeOutbound::new());
        let mut headers = HeaderMap::new();
        headers.insert("retry-after", "120".parse().unwrap());
        fake.push_ok(StatusCode::from_u16(420).unwrap(), headers, Bytes::new());
        let outbound: Arc<dyn crate::outbound::OutboundHttp> = fake;
        let err = provider_response(&outbound, "issue/4000-1", "", "TESTKEY123")
            .await
            .expect_err("420 must be rate limited");
        assert!(matches!(err, ProviderFailure::RateLimited(120)));
    }

    /// #5592: 403 is a plain provider error (Python parity), not a throttle.
    #[tokio::test]
    async fn provider_response_treats_403_as_unavailable() {
        let fake = Arc::new(crate::outbound::RecordingFakeOutbound::new());
        fake.push_ok(StatusCode::FORBIDDEN, HeaderMap::new(), Bytes::new());
        let outbound: Arc<dyn crate::outbound::OutboundHttp> = fake;
        let err = provider_response(&outbound, "issue/4000-1", "", "TESTKEY123")
            .await
            .expect_err("403 must be unavailable");
        assert!(matches!(err, ProviderFailure::Unavailable));
    }

    /// Minimal ComicVine stand-in: a missing trailing slash on any resource
    /// produces the same 301 the real API returns, and the native transport
    /// never follows it.
    #[derive(Default)]
    struct SlashEnforcingOutbound {
        calls: Mutex<Vec<String>>,
    }

    impl SlashEnforcingOutbound {
        fn paths(&self) -> Vec<String> {
            self.calls
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .clone()
        }
    }

    impl OutboundHttp for SlashEnforcingOutbound {
        fn send(&self, _host: &str, request: OutboundRequest) -> OutboundFuture {
            let path = request.path.clone();
            self.calls
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .push(path.clone());
            let redirect = path
                .split('?')
                .next()
                .is_some_and(|resource| !resource.ends_with('/'));
            let (status, body) = if redirect {
                (StatusCode::MOVED_PERMANENTLY, Bytes::new())
            } else if path.starts_with("/api/issues/") {
                (
                    StatusCode::OK,
                    Bytes::from(
                        r#"{"status_code":1,"number_of_total_results":2,"results":[
                            {"id":5851000,"issue_number":"1","name":"One","volume":{"id":5851001}},
                            {"id":5851001,"issue_number":"2","name":"Two","volume":{"id":5851001}}
                        ]}"#
                        .to_string(),
                    ),
                )
            } else {
                (
                    StatusCode::OK,
                    Bytes::from(
                        r#"{"status_code":1,"results":{"id":5851001,"name":"Nova (2007)",
                            "publisher":{"name":"Marvel"},"start_year":2007,
                            "count_of_issues":2,"site_detail_url":"https://example.test/volume",
                            "image":null}}"#,
                    ),
                )
            };
            Box::pin(async move {
                Ok(OutboundResponse {
                    status,
                    headers: HeaderMap::new(),
                    body: Body::from(body),
                })
            })
        }

        fn as_any(&self) -> &dyn Any {
            self
        }
    }

    /// #5851: ComicVine 301s slash-less singular resources. The preview's
    /// volume/issue roster fetch must request the canonical slash URL on the
    /// first round trip: the native transport never replays a credential on a
    /// redirect.
    #[tokio::test]
    async fn provider_requests_canonical_slash_urls_without_following_redirects() {
        let outbound: Arc<dyn OutboundHttp> = Arc::new(SlashEnforcingOutbound::default());
        let fake = outbound
            .as_any()
            .downcast_ref::<SlashEnforcingOutbound>()
            .expect("slash-enforcing fake");

        for resource in [
            "volume/4050-5851001",
            "issue/4000-5851000",
            "issues",
            "search",
        ] {
            let exchange = provider_exchange(&outbound, resource, "", "TESTKEY123")
                .await
                .expect("canonical URL must not be redirected");
            assert!(matches!(exchange, Exchange::Payload(_)), "{resource}");
        }

        let paths = fake.paths();
        assert_eq!(paths.len(), 4);
        for (path, resource) in paths.iter().zip([
            "volume/4050-5851001",
            "issue/4000-5851000",
            "issues",
            "search",
        ]) {
            assert!(
                path.starts_with(&format!("/api/{resource}/?")),
                "ComicVine requires a trailing slash: {path}"
            );
        }
    }

    /// #5851: the Queue mapping-plan builder must load a real roster through
    /// the canonical provider URLs, with no warm in-process cache to hide the
    /// slash-less redirect.
    #[tokio::test]
    async fn catalog_volume_roster_loads_without_following_provider_redirects() {
        let outbound: Arc<dyn OutboundHttp> = Arc::new(SlashEnforcingOutbound::default());
        let fake = outbound
            .as_any()
            .downcast_ref::<SlashEnforcingOutbound>()
            .expect("slash-enforcing fake");
        let mut previous = std::env::var("COMICVINE_API_KEY").ok();
        std::env::set_var("COMICVINE_API_KEY", "TESTKEY123");

        let limits = crate::comicvine_limits::ComicVineLimits::default();
        let result = catalog_volume_roster(&limits, &outbound, "5851001").await;

        match previous.take() {
            Some(value) => std::env::set_var("COMICVINE_API_KEY", value),
            None => std::env::remove_var("COMICVINE_API_KEY"),
        }
        let (series, roster) = result.expect("roster must load without a redirect");
        assert_eq!(series["id"], "5851001");
        assert_eq!(series["name"], "Nova (2007)");
        assert_eq!(roster.len(), 2);
        let paths = fake.paths();
        assert_eq!(paths.len(), 2, "one volume read and one roster page");
        assert!(paths[0].starts_with("/api/volume/4050-5851001/?"));
        assert!(paths[1].starts_with("/api/issues/?"));
    }
}
