//! Canonical v2 Thread custom methods (issue #5704).
//!
//! The completed-thread "Add Back to Queue" action is a deliberate, rare
//! mutation — it creates new unread issues — so it is modelled as an AIP-136
//! custom method on the Thread resource:
//!
//! * `POST /api/v2/threads/{thread_id}:reactivate` with `{issues_to_add}`
//!
//! It is **not** a status `PATCH` and not an alias of the retired v1
//! `/api/v1/threads/reactivate` aggregate-style operation. The thread id comes
//! from the resource path and the only body field is the requested issue count.
//! The domain write, queue advisory lock, issue numbering and wire response are
//! shared with the retained same-path handler so both URLs stay behaviourally
//! identical. Like the rest of the v2 surface, every statement is scoped to the
//! authenticated reader; a foreign or missing thread is a 404.
//!
//! axum/matchit cannot express a `{thread_id}:{action}` segment, so
//! [`post_thread_v2_action`] is mounted on `/api/v2/threads/{thread_id}` and
//! dispatches on the colon suffix, mirroring the v1 thread-action dispatcher.

#![forbid(unsafe_code)]

use crate::{
    auth::AuthenticatedUser,
    thread_lifecycle::{self, HandlerResult},
    thread_validation::{int_field, parse_body, path_int, require_object, Bounds, Check},
    ApiError, AppState,
};
use axum::{
    body::Bytes,
    extract::{rejection::PathRejection, Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use serde_json::Value;
use std::sync::Arc;
use utoipa::OpenApi;

/// Body of `POST /api/v2/threads/{thread_id}:reactivate`.
#[derive(Debug, serde::Deserialize, utoipa::ToSchema)]
pub struct ReactivateThreadRequest {
    /// Number of new unread issues to create for the completed series.
    #[schema(minimum = 1, maximum = 10_000)]
    pub issues_to_add: i32,
}

/// Dispatch `POST /api/v2/threads/{thread_id}:{action}` operations.
///
/// Unknown actions (and a bare `POST /api/v2/threads/{id}`) are a JSON 404,
/// exactly like any other unrouted path.
pub async fn post_thread_v2_action(
    State(state): State<Arc<AppState>>,
    user: AuthenticatedUser,
    segment: Result<Path<String>, PathRejection>,
    body: Bytes,
) -> Response {
    let Path(segment) = match segment {
        Ok(path) => path,
        Err(_) => return ApiError::BadRequest("Validation failed".to_string()).into_response(),
    };
    match segment.split_once(':') {
        Some((raw_id, "reactivate")) => reactivate_thread(&state, user, raw_id, &body)
            .await
            .into_response(),
        _ => ApiError::NotFound("Not Found".to_string()).into_response(),
    }
}

/// `POST /api/v2/threads/{thread_id}:reactivate`.
///
/// Validation precedes every database write: a non-positive or unbounded
/// count is a 422 and cannot bump queue positions or insert issue rows.
async fn reactivate_thread(
    state: &AppState,
    user: AuthenticatedUser,
    raw_id: &str,
    body: &[u8],
) -> HandlerResult {
    let map = require_object(parse_body(body)?)?;
    let raw_body = Value::Object(map.clone());
    let mut check = Check::default();
    let thread_id = path_int(&mut check, "thread_id", raw_id);
    let thread_id = thread_lifecycle::to_i32(&mut check, &["path", "thread_id"], thread_id);
    let issues_to_add = int_field(
        &mut check,
        &["body", "issues_to_add"],
        map.get("issues_to_add"),
        Bounds {
            gt: Some(0),
            le: Some(thread_lifecycle::MAX_ISSUES_TO_ADD),
            ..Bounds::default()
        },
        false,
        true,
    );
    let issues_to_add =
        thread_lifecycle::to_i32(&mut check, &["body", "issues_to_add"], issues_to_add);
    check.finish(raw_body)?;

    let id = thread_lifecycle::reactivate_once(
        state,
        user,
        thread_id.unwrap_or_default(),
        issues_to_add.unwrap_or_default(),
    )
    .await?;
    thread_lifecycle::respond_thread(state, user, id, StatusCode::OK).await
}

#[utoipa::path(
    post,
    path = "/api/v2/threads/{thread_id}:reactivate",
    tag = "threads",
    operation_id = "reactivate_thread_v2",
    request_body = ReactivateThreadRequest,
    responses(
        // Reuse the canonical typed `ThreadResponse` declared by the thread
        // issue family. The lifecycle DTO derives the same component name from
        // a raw `serde_json::Value`, which would emit `{}` for
        // `manual_creator_credits` and erase the frozen array-of-objects wire
        // type from the generated client (#5704 review finding).
        (status = 200, description = "Completed thread reactivated with the requested unread issues", body = crate::thread_issues::ThreadResponse),
        (status = 400, description = "Thread is not completed"),
        (status = 404, description = "Thread not found for this reader"),
        (status = 422, description = "Validation failed"),
    ),
    params(
        ("thread_id" = i32, Path, description = "Identifier of the completed thread to reactivate"),
    ),
)]
pub fn reactivate_thread_documentation() {}

/// Domain OpenAPI surface for canonical v2 Thread custom methods.
#[derive(utoipa::OpenApi)]
#[openapi(
    info(
        title = "ComicPile native v2 Thread custom methods",
        version = "2.0.0",
        description = "Generated contract for AIP-136 custom methods on v2 Thread resources."
    ),
    paths(reactivate_thread_documentation),
    components(schemas(ReactivateThreadRequest)),
    modifiers(&ThreadsV2SecurityAddon)
)]
pub struct ThreadsV2Api;

struct ThreadsV2SecurityAddon;

impl utoipa::Modify for ThreadsV2SecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme(
                "HTTPBearer",
                utoipa::openapi::security::SecurityScheme::Http(
                    utoipa::openapi::security::Http::new(
                        utoipa::openapi::security::HttpAuthScheme::Bearer,
                    ),
                ),
            );
        }
    }
}

/// Emit the v2 Thread custom-method domain contract.
pub fn threads_v2_openapi() -> utoipa::openapi::OpenApi {
    ThreadsV2Api::openapi()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    #[test]
    fn reactivate_custom_method_is_in_domain_contract() {
        let document = serde_json::to_value(threads_v2_openapi()).expect("v2 threads OpenAPI");
        let operation = &document["paths"]["/api/v2/threads/{thread_id}:reactivate"]["post"];
        assert_eq!(operation["operationId"], "reactivate_thread_v2");
        assert!(operation["responses"]["200"].is_object());
        assert_eq!(
            operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ThreadResponse"
        );
        assert!(document["components"]["schemas"]["ReactivateThreadRequest"].is_object());
        // The canonical component keeps the frozen Python field type: an array
        // of creator-credit objects, never an untyped `{}` schema.
        let credits =
            &document["components"]["schemas"]["ThreadResponse"]["properties"]["manual_creator_credits"];
        assert_eq!(credits["type"], "array");
        assert!(credits["items"].is_object());
    }

    /// The regeneration command for this artifact lives in `native/contracts/README.md`.
    #[test]
    fn checked_in_v2_contract_includes_reactivate_custom_method() {
        let checked_in: Value =
            serde_json::from_str(include_str!("../../contracts/v2-runtime.openapi.json"))
                .expect("checked-in v2 runtime contract");
        let operation = &checked_in["paths"]["/api/v2/threads/{thread_id}:reactivate"]["post"];
        assert_eq!(operation["operationId"], "reactivate_thread_v2");
    }
}
