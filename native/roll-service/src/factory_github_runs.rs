//! Status and result of one Rotisserie operator run for the hosted page.
//!
//! Only runs of the two Rotisserie operator workflows in this repository are
//! visible. Any other run answers 404, because 401 and 403 sign the page out.
#![forbid(unsafe_code)]

use crate::{
    factory_github_artifact::{single_file, ArtifactError},
    factory_github_oauth::{
        cors, github_token, read_limited, same_origin, send_github, session_from_headers,
        OPERATOR_WORKFLOWS, REPO,
    },
    outbound::OutboundRequest,
    ApiError, AppState,
};
use axum::{
    extract::{Path, State},
    http::{header, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use serde_json::{json, Value};
use std::sync::Arc;

const MAX_RUN_RESPONSE: usize = 256 * 1024;
pub const MAX_RESULT_BYTES: usize = 1024 * 1024;
const DOWNLOAD_HOST_SUFFIXES: [&str; 2] =
    [".blob.core.windows.net", ".actions.githubusercontent.com"];

fn not_found() -> ApiError {
    ApiError::NotFound("Factory run not found".into())
}

fn github_headers(token: &str) -> Vec<(String, String)> {
    vec![
        ("Accept".into(), "application/vnd.github+json".into()),
        ("Authorization".into(), format!("Bearer {token}")),
        ("User-Agent".into(), "ComicPile-Rotisserie".into()),
        ("X-GitHub-Api-Version".into(), "2026-03-10".into()),
    ]
}

async fn github_get(
    state: &AppState,
    token: &str,
    path: String,
) -> Result<(StatusCode, Option<Value>), ApiError> {
    let response = send_github(
        state,
        "api.github.com",
        OutboundRequest::get(path, github_headers(token)),
    )
    .await?;
    let status = response.status;
    if !status.is_success() {
        return Ok((status, None));
    }
    let bytes = read_limited(response.body, MAX_RUN_RESPONSE)
        .await
        .ok_or_else(|| ApiError::ServiceUnavailable("Invalid GitHub response".into()))?;
    let data = serde_json::from_slice(&bytes)
        .map_err(|_| ApiError::ServiceUnavailable("Invalid GitHub response".into()))?;
    Ok((status, Some(data)))
}

fn unavailable(status: StatusCode) -> ApiError {
    tracing::warn!(
        status = status.as_u16(),
        "Rotisserie run lookup rejected by GitHub"
    );
    ApiError::ServiceUnavailable("GitHub run lookup unavailable".into())
}

/// Accepts only an `https` URL on a GitHub artifact storage host and returns
/// the host and the origin-form path.
pub fn download_target(location: &str) -> Option<(String, String)> {
    let parsed = url::Url::parse(location).ok()?;
    if parsed.scheme() != "https"
        || parsed.port().is_some()
        || !parsed.username().is_empty()
        || parsed.password().is_some()
    {
        return None;
    }
    let host = parsed.host_str()?.to_ascii_lowercase();
    if !DOWNLOAD_HOST_SUFFIXES
        .iter()
        .any(|suffix| host.ends_with(suffix) && host.len() > suffix.len())
    {
        return None;
    }
    let path = match parsed.query() {
        Some(query) => format!("{}?{query}", parsed.path()),
        None => parsed.path().to_owned(),
    };
    Some((host, path))
}

fn artifact_error(error: ArtifactError) -> ApiError {
    ApiError::ServiceUnavailable(error.to_string())
}

async fn result(state: &AppState, token: &str, run_id: u64) -> Result<Value, ApiError> {
    let name = format!("rotisserie-operator-{run_id}");
    let (status, listing) = github_get(
        state,
        token,
        format!("/repos/{REPO}/actions/runs/{run_id}/artifacts?name={name}&per_page=10"),
    )
    .await?;
    let listing = match (status, listing) {
        (_, Some(listing)) => listing,
        (StatusCode::NOT_FOUND, None) => return Ok(Value::Null),
        (status, None) => return Err(unavailable(status)),
    };
    let Some(artifact) = listing
        .get("artifacts")
        .and_then(Value::as_array)
        .and_then(|artifacts| {
            artifacts.iter().find(|artifact| {
                artifact.get("name").and_then(Value::as_str) == Some(name.as_str())
                    && artifact.get("expired").and_then(Value::as_bool) != Some(true)
            })
        })
    else {
        return Ok(Value::Null);
    };
    let artifact_id = artifact
        .get("id")
        .and_then(Value::as_u64)
        .ok_or_else(|| ApiError::ServiceUnavailable("Invalid GitHub response".into()))?;
    if artifact
        .get("size_in_bytes")
        .and_then(Value::as_u64)
        .is_some_and(|size| size > MAX_RESULT_BYTES as u64)
    {
        return Err(artifact_error(ArtifactError::TooLarge));
    }
    let redirect = send_github(
        state,
        "api.github.com",
        OutboundRequest::get(
            format!("/repos/{REPO}/actions/artifacts/{artifact_id}/zip"),
            github_headers(token),
        ),
    )
    .await?;
    if redirect.status == StatusCode::GONE || redirect.status == StatusCode::NOT_FOUND {
        return Ok(Value::Null);
    }
    if redirect.status != StatusCode::FOUND {
        return Err(unavailable(redirect.status));
    }
    let (host, path) = redirect
        .headers
        .get(header::LOCATION)
        .and_then(|value| value.to_str().ok())
        .and_then(download_target)
        .ok_or_else(|| ApiError::ServiceUnavailable("Invalid GitHub artifact location".into()))?;
    let download = send_github(
        state,
        &host,
        OutboundRequest::get(
            path,
            vec![("User-Agent".into(), "ComicPile-Rotisserie".into())],
        ),
    )
    .await?;
    if !download.status.is_success() {
        return Err(unavailable(download.status));
    }
    let archive = read_limited(download.body, MAX_RESULT_BYTES)
        .await
        .ok_or_else(|| artifact_error(ArtifactError::TooLarge))?;
    let content = if archive.starts_with(b"PK") {
        match single_file(&archive, MAX_RESULT_BYTES).map_err(artifact_error)? {
            Some(content) => content,
            None => return Ok(Value::Null),
        }
    } else {
        archive.to_vec()
    };
    serde_json::from_slice(&content)
        .map_err(|_| ApiError::ServiceUnavailable("Factory result is not JSON".into()))
}

async fn run_inner(
    state: Arc<AppState>,
    headers: axum::http::HeaderMap,
    run_id: String,
) -> Result<Value, ApiError> {
    if !same_origin(&headers) {
        return Err(ApiError::Forbidden("Invalid dashboard origin".into()));
    }
    session_from_headers(&state, &headers)?;
    if run_id.is_empty() || run_id.len() > 20 || !run_id.bytes().all(|b| b.is_ascii_digit()) {
        return Err(not_found());
    }
    let run_id: u64 = run_id.parse().map_err(|_| not_found())?;
    let token = github_token()?;
    let (status, run) = github_get(
        &state,
        &token,
        format!("/repos/{REPO}/actions/runs/{run_id}"),
    )
    .await?;
    let run = match (status, run) {
        (_, Some(run)) => run,
        (StatusCode::NOT_FOUND, None) => return Err(not_found()),
        (status, None) => return Err(unavailable(status)),
    };
    let workflow = run.get("path").and_then(Value::as_str).unwrap_or("");
    if run.get("id").and_then(Value::as_u64) != Some(run_id)
        || !OPERATOR_WORKFLOWS
            .iter()
            .any(|name| workflow == format!(".github/workflows/{name}"))
    {
        return Err(not_found());
    }
    let run_status = run.get("status").cloned().unwrap_or(Value::Null);
    let outcome = if run_status == "completed" {
        result(&state, &token, run_id).await?
    } else {
        Value::Null
    };
    Ok(json!({
        "run_id": run_id,
        "run_url": format!("https://github.com/{REPO}/actions/runs/{run_id}"),
        "status": run_status,
        "conclusion": run.get("conclusion").cloned().unwrap_or(Value::Null),
        "result": outcome,
    }))
}

/// Same Origin and session checks as dispatch; GitHub failures never answer
/// 401 or 403.
pub async fn run(
    State(state): State<Arc<AppState>>,
    headers: axum::http::HeaderMap,
    Path(run_id): Path<String>,
) -> Response {
    cors(match run_inner(state, headers, run_id).await {
        Ok(payload) => Json(payload).into_response(),
        Err(error) => error.into_response(),
    })
}

#[cfg(test)]
mod tests {
    use super::download_target;

    #[test]
    fn artifact_downloads_only_follow_https_storage_hosts() {
        assert_eq!(
            download_target("https://productionresultssa1.blob.core.windows.net/a/b.zip?sig=x"),
            Some((
                "productionresultssa1.blob.core.windows.net".into(),
                "/a/b.zip?sig=x".into()
            ))
        );
        for refused in [
            "http://productionresultssa1.blob.core.windows.net/a",
            "https://evil.example/a",
            "https://blob.core.windows.net.evil.example/a",
            "https://.blob.core.windows.net/a",
            "https://user@x.blob.core.windows.net/a",
            "https://x.blob.core.windows.net:8443/a",
            "/relative",
        ] {
            assert_eq!(download_target(refused), None, "{refused}");
        }
    }
}
