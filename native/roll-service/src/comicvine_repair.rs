//! Bounded, awaited ComicVine metadata-repair worker.
//! A Vercel request is the lifetime of the work: never spawn and forget a task.
use crate::{db, ApiError, AppState};
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    Json,
};
use bytes::Bytes;
use http_body_util::{BodyExt, Empty};
use hyper::client::conn::http1;
use hyper_util::rt::TokioIo;
use serde::Serialize;
use serde_json::{json, Map, Value};
use std::{sync::Arc, time::Duration};

const HOST: &str = "comicvine.gamespot.com";
const MAX_BODY: usize = 2_000_000;
const BATCH_LIMIT: usize = 8;
const PROVIDER_TIMEOUT: Duration = Duration::from_secs(5);

// A provider connection must not outlive its awaited Vercel request. In
// particular, early return on malformed/oversized provider responses must
// cancel the HTTP driver instead of leaving a detached serverless task.
struct ConnectionGuard(tokio::task::JoinHandle<()>);

impl Drop for ConnectionGuard {
    fn drop(&mut self) {
        self.0.abort();
    }
}

const FIELDS: &str = "id,name,issue_number,cover_date,store_date,image,volume,person_credits,character_credits,team_credits,story_arc_credits,date_last_updated";
const CLAIM: &str = r#"
WITH candidate AS (
  SELECT id FROM comicvine_metadata_refresh_requests
  WHERE (state IN ('pending', 'deferred', 'failed') AND next_attempt_at <= now())
     OR (state = 'running' AND (lease_expires_at IS NULL OR lease_expires_at <= now()))
  ORDER BY next_attempt_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
), claimed AS (
  UPDATE comicvine_metadata_refresh_requests r SET state='running',
    attempts=r.attempts+1, lease_expires_at=now()+interval '120 seconds',
    updated_at=now()
  WHERE r.id=(SELECT id FROM candidate)
  RETURNING r.id, r.external_identity_id, r.attempts
)
SELECT c.id, c.external_identity_id, c.attempts, e.external_id,
       e.provider, e.entity_type, e.metadata_json::text
FROM claimed c LEFT JOIN external_identities e ON e.id=c.external_identity_id
"#;
const SETTLE: &str = r#"
UPDATE comicvine_metadata_refresh_requests
SET state=($4::text)::varchar, lease_expires_at=NULL,
    next_attempt_at=now()+($5::integer * interval '1 second'),
    last_error=$6, completed_at=CASE WHEN ($4::text) IN ('completed','no_credits')
      THEN now() ELSE NULL END, updated_at=now()
WHERE id=$1 AND external_identity_id=$2 AND attempts=$3
  AND state='running' AND lease_expires_at > now()
RETURNING id
"#;
const PERSIST: &str = r#"
WITH lease AS (
  SELECT id FROM comicvine_metadata_refresh_requests
  WHERE id=$2 AND external_identity_id=$1 AND attempts=$3
    AND state='running' AND lease_expires_at > now()
  FOR UPDATE
), hydrated AS (
  UPDATE external_identities e SET
    metadata_json=(e.metadata_json::jsonb || ($4::text)::jsonb)::json,
    external_url=COALESCE($5, e.external_url),
    provider_updated_at=COALESCE(($6::text)::timestamptz, e.provider_updated_at),
    updated_at=now()
  WHERE e.id=$1 AND e.provider='comicvine' AND e.entity_type='issue'
    AND EXISTS (SELECT 1 FROM lease)
  RETURNING e.id
), settled AS (
  UPDATE comicvine_metadata_refresh_requests r
  SET state=$7, lease_expires_at=NULL, next_attempt_at=now(),
    last_error=NULL, completed_at=now(), updated_at=now()
  WHERE r.id=$2 AND EXISTS (SELECT 1 FROM hydrated)
  RETURNING r.id
)
SELECT EXISTS(SELECT 1 FROM settled)
"#;

#[derive(Debug)]
struct Job {
    id: i32,
    identity_id: i32,
    attempt: i32,
    external_id: Option<String>,
    provider: Option<String>,
    entity_type: Option<String>,
    metadata: Option<String>,
}

#[derive(Default, Serialize)]
pub struct DrainReport {
    claimed: u32,
    completed: u32,
    no_credits: u32,
    deferred: u32,
    failed: u32,
    provider_configured: bool,
}

#[derive(Debug)]
enum ProviderFailure {
    RateLimited(u32),
    Unavailable,
    InvalidPayload,
}

fn allowed(headers: &HeaderMap, expected: Option<&str>) -> bool {
    let Some(secret) = expected.filter(|s| s.len() >= 16) else {
        return false;
    };
    let Some(header) = headers.get("authorization").and_then(|h| h.to_str().ok()) else {
        return false;
    };
    let Some(provided) = header.strip_prefix("Bearer ") else {
        return false;
    };
    let a = provided.as_bytes();
    let b = secret.as_bytes();
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b).fold(0_u8, |v, (x, y)| v | (x ^ y)) == 0
}

fn issue_id(external_id: &str) -> Option<u32> {
    let raw = external_id.strip_prefix("4000-").unwrap_or(external_id);
    raw.parse::<u32>().ok().filter(|id| *id > 0)
}

fn compact_refs(value: &Value) -> Value {
    Value::Array(
        value
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|v| {
                let source = v.as_object()?;
                let mut compact = Map::new();
                for field in ["id", "name", "api_detail_url", "site_detail_url", "role"] {
                    if let Some(value) = source.get(field) {
                        compact.insert(field.to_owned(), value.clone());
                    }
                }
                Some(Value::Object(compact))
            })
            .collect(),
    )
}

fn normalized_metadata(
    result: &Value,
    expected_id: u32,
) -> Result<(Value, bool, Option<String>, Option<String>), ProviderFailure> {
    let obj = result.as_object().ok_or(ProviderFailure::InvalidPayload)?;
    if obj.get("id").and_then(Value::as_u64) != Some(u64::from(expected_id)) {
        return Err(ProviderFailure::InvalidPayload);
    }
    for field in [
        "name",
        "issue_number",
        "cover_date",
        "store_date",
        "image",
        "volume",
        "person_credits",
        "character_credits",
        "team_credits",
        "story_arc_credits",
        "date_last_updated",
    ] {
        if !obj.contains_key(field) {
            return Err(ProviderFailure::InvalidPayload);
        }
    }
    let image = obj.get("image").and_then(Value::as_object);
    let cover = image.and_then(|v| {
        ["original_url", "super_url", "medium_url", "small_url"]
            .iter()
            .filter_map(|k| v.get(*k).and_then(Value::as_str))
            .find(|s| !s.is_empty())
    });
    let person = compact_refs(&result["person_credits"]);
    let present = person.as_array().is_some_and(|v| !v.is_empty());
    let patch = json!({
        "name": result["name"],
        "issue_number": result["issue_number"],
        "cover_date": result["cover_date"],
        "store_date": result["store_date"],
        "volume": compact_refs(&json!([result["volume"]])).as_array().and_then(|v|v.first()).cloned(),
        "primary_image": cover,
        "creator_credits": person,
        "characters": compact_refs(&result["character_credits"]),
        "teams": compact_refs(&result["team_credits"]),
        "story_arcs": compact_refs(&result["story_arc_credits"]),
        "raw_provider_payload": result,
        "deep_metadata_refreshed_at": chrono::Utc::now().to_rfc3339(),
    });
    let url = result["site_detail_url"]
        .as_str()
        .filter(|s| s.starts_with("https://comicvine.gamespot.com/"))
        .map(str::to_owned);
    let updated = provider_timestamp(&result["date_last_updated"]);
    Ok((patch, present, url, updated))
}

/// Parse ComicVine's provider revision stamp.
///
/// ComicVine documents RFC 3339 timestamps but the live API commonly returns
/// `YYYY-MM-DD HH:MM:SS` without an offset. Both forms are UTC-equivalent, so
/// accept either instead of silently dropping the provider revision clock.
fn provider_timestamp(value: &Value) -> Option<String> {
    let stamp = value.as_str()?;
    if let Ok(parsed) = chrono::DateTime::parse_from_rfc3339(stamp) {
        return Some(parsed.to_rfc3339());
    }
    let naive = chrono::NaiveDateTime::parse_from_str(stamp, "%Y-%m-%d %H:%M:%S").ok()?;
    Some(
        chrono::DateTime::<chrono::Utc>::from_naive_utc_and_offset(naive, chrono::Utc).to_rfc3339(),
    )
}

async fn provider_issue(id: u32, api_key: &str) -> Result<Value, ProviderFailure> {
    // Fail closed on unexpected credential syntax rather than sending an unescaped secret.
    if api_key.is_empty() || !api_key.bytes().all(|c| c.is_ascii_alphanumeric()) {
        return Err(ProviderFailure::Unavailable);
    }
    let connect = async {
        let tcp = tokio::net::TcpStream::connect((HOST, 443))
            .await
            .map_err(|_| ProviderFailure::Unavailable)?;
        let tls = native_tls::TlsConnector::new().map_err(|_| ProviderFailure::Unavailable)?;
        let tls = tokio_native_tls::TlsConnector::from(tls)
            .connect(HOST, tcp)
            .await
            .map_err(|_| ProviderFailure::Unavailable)?;
        let (mut sender, connection) = http1::handshake(TokioIo::new(tls))
            .await
            .map_err(|_| ProviderFailure::Unavailable)?;
        let _connection_guard = ConnectionGuard(tokio::spawn(async move {
            let _ = connection.await;
        }));
        let path =
            format!("/api/issue/4000-{id}/?api_key={api_key}&format=json&field_list={FIELDS}");
        let request = http::Request::builder()
            .method("GET")
            .uri(path)
            .header("host", HOST)
            .header("accept", "application/json")
            .header("user-agent", "ComicPile/1.0 (metadata repair)")
            .body(Empty::<Bytes>::new())
            .map_err(|_| ProviderFailure::Unavailable)?;
        let mut response = sender
            .send_request(request)
            .await
            .map_err(|_| ProviderFailure::Unavailable)?;
        if response.status() == StatusCode::TOO_MANY_REQUESTS
            || response.status() == StatusCode::FORBIDDEN
        {
            let retry = response
                .headers()
                .get("retry-after")
                .and_then(|h| h.to_str().ok())
                .and_then(|h| h.parse::<u32>().ok())
                .unwrap_or(60)
                .clamp(60, 3600);
            return Err(ProviderFailure::RateLimited(retry));
        }
        if !response.status().is_success() {
            return Err(ProviderFailure::Unavailable);
        }
        if response
            .headers()
            .get("content-length")
            .and_then(|h| h.to_str().ok())
            .and_then(|n| n.parse::<usize>().ok())
            .is_some_and(|n| n > MAX_BODY)
        {
            return Err(ProviderFailure::InvalidPayload);
        }
        let mut data = Vec::new();
        while let Some(frame) = response.body_mut().frame().await {
            let frame = frame.map_err(|_| ProviderFailure::Unavailable)?;
            if let Ok(bytes) = frame.into_data() {
                if data.len() + bytes.len() > MAX_BODY {
                    return Err(ProviderFailure::InvalidPayload);
                }
                data.extend_from_slice(&bytes);
            }
        }
        let payload: Value =
            serde_json::from_slice(&data).map_err(|_| ProviderFailure::InvalidPayload)?;
        if payload["status_code"].as_i64() != Some(1) {
            return Err(ProviderFailure::Unavailable);
        }
        payload
            .get("results")
            .cloned()
            .ok_or(ProviderFailure::InvalidPayload)
    };
    tokio::time::timeout(PROVIDER_TIMEOUT, connect)
        .await
        .map_err(|_| ProviderFailure::Unavailable)?
}

async fn claim(state: &AppState) -> Result<Option<Job>, ApiError> {
    let connection = db::checkout(state).await?;
    let row = connection
        .query_opt(CLAIM, &[])
        .await
        .map_err(db::query_error)?;
    row.map(|row| {
        Ok(Job {
            id: row.try_get(0).map_err(db::query_error)?,
            identity_id: row.try_get(1).map_err(db::query_error)?,
            attempt: row.try_get(2).map_err(db::query_error)?,
            external_id: row.try_get(3).map_err(db::query_error)?,
            provider: row.try_get(4).map_err(db::query_error)?,
            entity_type: row.try_get(5).map_err(db::query_error)?,
            metadata: row.try_get(6).map_err(db::query_error)?,
        })
    })
    .transpose()
}

async fn settle(
    state: &AppState,
    job: &Job,
    status: &str,
    delay: i32,
    error: Option<&str>,
) -> Result<(), ApiError> {
    let connection = db::checkout(state).await?;
    connection
        .query_opt(
            SETTLE,
            &[
                &job.id,
                &job.identity_id,
                &job.attempt,
                &status,
                &delay,
                &error,
            ],
        )
        .await
        .map_err(db::query_error)?;
    Ok(())
}

async fn persist(
    state: &AppState,
    job: &Job,
    patch: &Value,
    has_credits: bool,
    url: &Option<String>,
    updated: &Option<String>,
) -> Result<bool, ApiError> {
    let content = patch.to_string();
    let status = if has_credits {
        "completed"
    } else {
        "no_credits"
    };
    let connection = db::checkout(state).await?;
    let row = connection
        .query_one(
            PERSIST,
            &[
                &job.identity_id,
                &job.id,
                &job.attempt,
                &content,
                url,
                updated,
                &status,
            ],
        )
        .await
        .map_err(db::query_error)?;
    row.try_get(0).map_err(db::query_error)
}

fn failure_transition(error: &ProviderFailure, attempt: i32) -> (&'static str, i32, &'static str) {
    match error {
        ProviderFailure::RateLimited(delay) => {
            ("deferred", (*delay).min(3600) as i32, "rate_limit")
        }
        ProviderFailure::InvalidPayload if attempt >= 3 => {
            ("failed", 21600, "invalid_provider_payload")
        }
        ProviderFailure::InvalidPayload => ("deferred", 300, "invalid_provider_payload"),
        ProviderFailure::Unavailable if attempt >= 3 => ("failed", 21600, "provider_unavailable"),
        ProviderFailure::Unavailable => (
            "deferred",
            if attempt <= 1 { 60 } else { 300 },
            "provider_unavailable",
        ),
    }
}

fn has_complete_provider_payload(metadata: &Value) -> bool {
    metadata["raw_provider_payload"]
        .as_object()
        .is_some_and(|raw| FIELDS.split(',').all(|key| raw.contains_key(key)))
}

async fn process(state: &AppState, job: &Job, key: Option<&str>) -> Result<&'static str, ApiError> {
    if job.provider.as_deref() != Some("comicvine") || job.entity_type.as_deref() != Some("issue") {
        settle(state, job, "failed", 21600, Some("identity_ineligible")).await?;
        return Ok("failed");
    }
    let Some(id) = job.external_id.as_deref().and_then(issue_id) else {
        settle(state, job, "failed", 21600, Some("invalid_external_id")).await?;
        return Ok("failed");
    };
    if let Some(metadata) = job
        .metadata
        .as_deref()
        .and_then(|v| serde_json::from_str::<Value>(v).ok())
    {
        let fetched_at = metadata["deep_metadata_refreshed_at"]
            .as_str()
            .and_then(|v| chrono::DateTime::parse_from_rfc3339(v).ok());
        let deep = has_complete_provider_payload(&metadata);
        if deep
            && fetched_at.is_some_and(|date| {
                chrono::Utc::now().signed_duration_since(date) < chrono::Duration::days(30)
            })
        {
            let has = metadata["creator_credits"]
                .as_array()
                .is_some_and(|v| !v.is_empty());
            settle(
                state,
                job,
                if has { "completed" } else { "no_credits" },
                0,
                None,
            )
            .await?;
            return Ok(if has { "completed" } else { "no_credits" });
        }
    }
    let Some(key) = key else {
        settle(
            state,
            job,
            "deferred",
            21600,
            Some("provider_not_configured"),
        )
        .await?;
        return Ok("deferred");
    };
    match provider_issue(id, key)
        .await
        .and_then(|value| normalized_metadata(&value, id))
    {
        Ok((patch, has, url, updated)) => {
            if persist(state, job, &patch, has, &url, &updated).await? {
                Ok(if has { "completed" } else { "no_credits" })
            } else {
                // Another worker reclaimed the expired lease; its result is authoritative.
                Ok("deferred")
            }
        }
        Err(error) => {
            let (status, delay, code) = failure_transition(&error, job.attempt);
            settle(state, job, status, delay, Some(code)).await?;
            Ok(status)
        }
    }
}

/// CRON_SECRET authenticated, awaited Rust repair batch. No detached task or silent success.
pub async fn drain(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<DrainReport>, ApiError> {
    let secret = std::env::var("CRON_SECRET").ok();
    if !allowed(&headers, secret.as_deref()) {
        return Err(ApiError(StatusCode::UNAUTHORIZED, "Unauthorized".into()));
    }
    let key = std::env::var("COMICVINE_API_KEY").ok();
    let key = key.as_deref().filter(|v| !v.is_empty());
    let mut report = DrainReport {
        provider_configured: key.is_some(),
        ..Default::default()
    };
    for index in 0..BATCH_LIMIT {
        let Some(job) = claim(&state).await? else {
            break;
        };
        report.claimed += 1;
        match process(&state, &job, key).await? {
            "completed" => report.completed += 1,
            "no_credits" => report.no_credits += 1,
            "failed" => report.failed += 1,
            _ => report.deferred += 1,
        }
        if index + 1 < BATCH_LIMIT {
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
    }
    Ok(Json(report))
}

#[cfg(test)]
mod tests {
    use super::*;
    use deadpool_postgres::Object;

    async fn seed_identity(state: &AppState) -> i32 {
        let connection = db::checkout(state).await.expect("seed connection");
        let identity_id: i32 = connection
            .query_one(
                "INSERT INTO external_identities \
                 (provider, entity_type, external_id, metadata_json, created_at, updated_at) \
                 VALUES ('comicvine', 'issue', '4000-29319', '{}'::json, now(), now()) \
                 RETURNING id",
                &[],
            )
            .await
            .expect("seed identity")
            .get(0);
        drop(Object::take(connection));
        identity_id
    }

    async fn seed_request(
        state: &AppState,
        identity_id: i32,
        request_state: &str,
        attempts: i32,
        next_attempt_offset: &str,
        lease_offset: Option<&str>,
    ) {
        let connection = db::checkout(state).await.expect("request connection");
        connection
            .execute(
                "INSERT INTO comicvine_metadata_refresh_requests \
                 (external_identity_id, state, attempts, next_attempt_at, lease_expires_at, \
                  created_at, updated_at) \
                 VALUES ($1, $2, $3, now()+($4::text)::interval, \
                   CASE WHEN $5::text IS NULL THEN NULL \
                        ELSE now()+($5::text)::interval END, \
                   now(), now())",
                &[
                    &identity_id,
                    &request_state,
                    &attempts,
                    &next_attempt_offset,
                    &lease_offset,
                ],
            )
            .await
            .expect("seed request");
        drop(Object::take(connection));
    }

    #[tokio::test]
    async fn expired_lease_is_reclaimed_and_persist_is_fenced() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_identity(&state).await;
        seed_request(
            &state,
            identity_id,
            "running",
            2,
            "-1 hour",
            Some("-1 minute"),
        )
        .await;

        let job = claim(&state)
            .await
            .expect("claim")
            .expect("expired lease job");
        assert_eq!(job.attempt, 3);
        assert_eq!(job.identity_id, identity_id);

        let patch = json!({"creator_credits": [{"id": 1, "name": "Jamie Delano"}]});
        let stale = Job {
            id: job.id,
            identity_id: job.identity_id,
            attempt: job.attempt + 1,
            external_id: job.external_id.clone(),
            provider: job.provider.clone(),
            entity_type: job.entity_type.clone(),
            metadata: job.metadata.clone(),
        };
        assert!(!persist(&state, &stale, &patch, true, &None, &None)
            .await
            .expect("stale persist"));
        assert!(persist(&state, &job, &patch, true, &None, &None)
            .await
            .expect("current persist"));

        let connection = db::checkout(&state).await.expect("assert connection");
        let row = connection
            .query_one(
                "SELECT state, lease_expires_at IS NULL \
                 FROM comicvine_metadata_refresh_requests \
                 WHERE external_identity_id=$1",
                &[&identity_id],
            )
            .await
            .expect("read settled request");
        let request_state: String = row.get(0);
        let lease_cleared: bool = row.get(1);
        assert_eq!(request_state, "completed");
        assert!(lease_cleared);
        drop(Object::take(connection));

        assert!(claim(&state).await.expect("empty claim").is_none());
    }

    #[tokio::test]
    async fn unreleased_lease_is_not_double_claimed_and_settle_is_fenced() {
        let Some(state) = crate::test_support::test_state(2).await else {
            return;
        };
        let _guard = crate::test_support::reset_for_test(&state).await;
        let identity_id = seed_identity(&state).await;
        seed_request(&state, identity_id, "pending", 0, "0 seconds", None).await;

        let job = claim(&state).await.expect("claim").expect("due job");
        assert_eq!(job.attempt, 1);
        assert!(claim(&state).await.expect("leased claim").is_none());

        let stale = Job {
            id: job.id,
            identity_id: job.identity_id,
            attempt: job.attempt + 1,
            external_id: job.external_id.clone(),
            provider: job.provider.clone(),
            entity_type: job.entity_type.clone(),
            metadata: job.metadata.clone(),
        };
        settle(&state, &stale, "deferred", 60, Some("provider_unavailable"))
            .await
            .expect("stale settle");
        let connection = db::checkout(&state).await.expect("assert connection");
        let request_state: String = connection
            .query_one(
                "SELECT state FROM comicvine_metadata_refresh_requests \
                 WHERE external_identity_id=$1",
                &[&identity_id],
            )
            .await
            .expect("read running request")
            .get(0);
        assert_eq!(request_state, "running");

        settle(&state, &job, "deferred", 60, Some("provider_unavailable"))
            .await
            .expect("current settle");
        let request_state: String = connection
            .query_one(
                "SELECT state FROM comicvine_metadata_refresh_requests \
                 WHERE external_identity_id=$1",
                &[&identity_id],
            )
            .await
            .expect("read settled request")
            .get(0);
        assert_eq!(request_state, "deferred");
        drop(Object::take(connection));

        assert!(claim(&state).await.expect("cooled claim").is_none());
    }

    #[test]
    fn cron_auth_fails_closed() {
        let mut headers = HeaderMap::new();
        headers.insert("authorization", "Bearer 1234567890123456".parse().unwrap());
        assert!(allowed(&headers, Some("1234567890123456")));
        assert!(!allowed(&headers, Some("1234567890123457")));
        assert!(!allowed(&headers, Some("short")));
        assert!(!allowed(&headers, None));
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
    fn backoff_does_not_retry_exhausted_jobs_without_cooldown() {
        assert!(CLAIM.contains("FOR UPDATE SKIP LOCKED"));
        // Failed jobs are durable but must retry after their cooldown without
        // requiring a user to reopen the issue to enqueue them again.
        assert!(CLAIM.contains("\'failed\'"));
        assert!(CLAIM.contains("next_attempt_at <= now()"));
        assert!(PERSIST.contains("lease_expires_at > now()"));
        assert_eq!(
            failure_transition(&ProviderFailure::Unavailable, 3).0,
            "failed"
        );
        assert_eq!(
            failure_transition(&ProviderFailure::RateLimited(120), 1).1,
            120
        );
        assert_eq!(issue_id("4000-29319"), Some(29319));
    }
}
