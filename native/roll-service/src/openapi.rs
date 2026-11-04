//! Canonical OpenAPI contract for every native operation that is routed in
//! production under `/api/v2`.
//!
//! This module does not re-declare handlers or payloads by hand. Each
//! documentation-only operation is generated from the same Rust request and
//! response types the mounted handlers use, and the aggregate merges the
//! existing per-domain [`utoipa::OpenApi`] documents (`QueueApi`, `ThreadsApi`,
//! `IssueApi`, `AnalyticsApi`) with the v2 auth, bootstrap, dice, offer, reset
//! and reading-boundary declarations.
//!
//! The checked-in artifact is `native/contracts/v2-runtime.openapi.json`; see
//! `native/contracts/README.md` for regeneration. `scripts/export_openapi_schema.py`
//! merges this runtime contract into the single generated frontend client.

use utoipa::OpenApi;

/// The fourteen `/api/v2` operations that are declared in the auth, bootstrap,
/// dice, offer, reset and reading-boundary modules.
///
/// `QueueApi`, `ThreadsApi`, `IssueApi` and `AnalyticsApi` already publish the
/// remaining seven deployed operations and are merged in [`canonical_openapi`].
#[derive(utoipa::OpenApi)]
#[openapi(
    info(
        title = "ComicPile native Roll v2 API",
        version = "2.0.0",
        description = "Generated contract for operations served by the native Rust router."
    ),
    paths(
        crate::auth::dto::register_documentation,
        crate::auth::dto::login_documentation,
        crate::auth::dto::refresh_documentation,
        crate::auth::dto::logout_documentation,
        crate::auth::dto::csrf_documentation,
        crate::auth::dto::me_documentation,
        crate::auth::dto::forgot_password_documentation,
        crate::auth::dto::reset_password_documentation,
        crate::bootstrap::bootstrap_documentation,
        crate::bootstrap::initialize_session_documentation,
        crate::dice_api::manual_die_documentation,
        crate::roll_offer::offer_documentation,
        crate::roll_reset::reset_documentation,
        crate::reading_boundary::reading_boundary_batch_documentation
    ),
    components(schemas(
        crate::auth::dto::RegisterRequest,
        crate::auth::dto::LoginRequest,
        crate::auth::dto::RefreshTokenRequest,
        crate::auth::dto::TokenResponse,
        crate::auth::dto::UserResponse,
        crate::auth::dto::ForgotPasswordRequest,
        crate::auth::dto::ResetPasswordRequest,
        crate::auth::dto::PasswordResetResponse,
        crate::auth::dto::CsrfResponse,
        crate::bootstrap::InitializeSessionRequest,
        crate::dice_api::ManualDieRequest,
        crate::dice_api::DiceCommandReceipt,
        crate::roll_offer::RollOfferRequest,
        crate::roll_offer::RollOfferResponse,
        crate::roll_reset::ResetDiceRequest,
        crate::roll_reset::ResetDiceResponse,
        crate::reading_boundary::ReadingBoundaryBatchRequest,
        crate::reading_boundary::ReadingBoundaryBatchResponseV2
    )),
    modifiers(&NativeSecurityAddon)
)]
pub struct NativeSurfaceApi;

struct NativeSecurityAddon;

impl utoipa::Modify for NativeSecurityAddon {
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

/// Every deployed native `/api/v2` operation as `(method, path)`.
///
/// This is a literal snapshot of the router in `lib.rs` and the ingress in
/// `vercel.json`; `tests/test_api_v2_contract_inventory.py` fails when either
/// source drifts from the generated contract.
pub const DEPLOYED_V2_OPERATIONS: [(&str, &str); 22] = [
    ("get", "/api/v2/analytics/metrics"),
    ("get", "/api/v2/issues/{issue_id}/comicvine"),
    ("get", "/api/v2/auth/csrf"),
    ("get", "/api/v2/auth/me"),
    ("get", "/api/v2/queue-entries/{thread_id}"),
    ("get", "/api/v2/roll/bootstrap"),
    ("get", "/api/v2/threads"),
    ("patch", "/api/v2/issues/{issue_id}"),
    ("patch", "/api/v2/queue-entries/{thread_id}"),
    ("post", "/api/v2/auth/forgot-password"),
    ("post", "/api/v2/auth/login"),
    ("post", "/api/v2/auth/logout"),
    ("post", "/api/v2/auth/refresh"),
    ("post", "/api/v2/auth/register"),
    ("post", "/api/v2/auth/reset-password"),
    ("post", "/api/v2/issues/cards"),
    ("post", "/api/v2/queue-orders"),
    ("post", "/api/v2/reading-boundaries"),
    ("post", "/api/v2/reading-sessions"),
    ("post", "/api/v2/roll/dice-command"),
    ("post", "/api/v2/roll/offer"),
    ("post", "/api/v2/roll/reset"),
];

/// Merge every native v2 domain document into one canonical contract.
///
/// `NativeSurfaceApi` is the base so its info block is retained; the existing
/// per-domain documents contribute their paths, component schemas and security
/// scheme. Merge order is deterministic and the surfaces are disjoint.
pub fn canonical_openapi() -> utoipa::openapi::OpenApi {
    NativeSurfaceApi::openapi()
        .merge_from(crate::queue::QueueApi::openapi())
        .merge_from(crate::threads::ThreadsApi::openapi())
        .merge_from(crate::issue_service::IssueApi::openapi())
        .merge_from(crate::analytics::AnalyticsApi::openapi())
        .merge_from(crate::comicvine_issue::ComicVineIssueApi::openapi())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    fn document() -> Value {
        serde_json::to_value(canonical_openapi()).expect("canonical OpenAPI document")
    }

    fn operation_set(document: &Value) -> Vec<(String, String)> {
        let mut operations = vec![];
        if let Some(paths) = document["paths"].as_object() {
            for (path, item) in paths {
                for method in item.as_object().expect("path item").keys() {
                    operations.push((method.clone(), path.clone()));
                }
            }
        }
        operations.sort();
        operations
    }

    #[test]
    fn covers_every_deployed_native_v2_operation() {
        let expected = DEPLOYED_V2_OPERATIONS
            .iter()
            .map(|(method, path)| ((*method).to_string(), (*path).to_string()))
            .collect::<Vec<_>>();
        assert_eq!(operation_set(&document()), expected);
    }

    #[test]
    fn every_operation_is_generated_and_documented() {
        let document = document();
        for (method, path) in DEPLOYED_V2_OPERATIONS {
            let operation = &document["paths"][path][method];
            assert!(
                operation["operationId"].as_str().is_some(),
                "missing generated operationId for {method} {path}"
            );
            assert!(
                operation["responses"]
                    .as_object()
                    .is_some_and(|responses| responses.keys().any(|code| code.starts_with('2'))),
                "missing 2xx response for {method} {path}"
            );
        }
        assert!(document["components"]["securitySchemes"]["HTTPBearer"].is_object());
    }

    #[test]
    fn checked_in_runtime_contract_is_current() {
        let checked_in = include_str!("../../../native/contracts/v2-runtime.openapi.json");
        let generated = canonical_openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document");
        assert_eq!(
            checked_in.trim_end(),
            generated.trim_end(),
            "Regenerate native/contracts/v2-runtime.openapi.json with \
             cargo run --example v2_openapi"
        );
    }

    fn schema_properties(document: &Value, name: &str) -> Value {
        document["components"]["schemas"][name]["properties"].clone()
    }

    fn assert_fields(document: &Value, name: &str, fields: &[&str]) {
        let properties = schema_properties(document, name);
        for field in fields {
            assert!(
                properties.get(*field).is_some(),
                "known UI field {name}.{field} disappeared from the live contract"
            );
        }
    }

    #[test]
    fn bootstrap_and_reading_session_responses_keep_their_typed_ui_fields() {
        let document = document();
        assert_eq!(
            document["paths"]["/api/v2/roll/bootstrap"]["get"]["responses"]["200"]["content"]
                ["application/json"]["schema"]["$ref"]
                .as_str(),
            Some("#/components/schemas/BootstrapResponseV2")
        );
        assert_eq!(
            document["paths"]["/api/v2/reading-sessions"]["post"]["responses"]["200"]["content"]
                ["application/json"]["schema"]["$ref"]
                .as_str(),
            Some("#/components/schemas/ReadingSessionCreatedResponse")
        );

        assert_fields(
            &document,
            "BootstrapResponseV2",
            &[
                "session_id",
                "user_id",
                "current_die",
                "manual_die",
                "pending_thread_id",
                "last_rolled_result",
                "session_mode",
                "active_thread",
                "roll_recovery",
                "bandwidth",
                "rollable",
                "pool_reason",
                "last_read",
                "snoozed_threads",
                "snoozed_count",
                "skipped_thread_ids",
                "skipped_threads",
                "timezone",
            ],
        );
        assert_fields(
            &document,
            "BootstrapSessionMode",
            &[
                "active_bandwidth",
                "predicted_bandwidth",
                "bandwidth_confidence",
                "bandwidth_source",
                "bandwidth_version",
                "active_intent",
                "predicted_intent",
                "intent_confidence",
                "intent_source",
                "intent_version",
                "session_mode_correction_guidance",
            ],
        );
        assert_fields(
            &document,
            "BootstrapBandwidth",
            &[
                "predicted_bandwidth",
                "active_bandwidth",
                "confidence",
                "source",
                "mode_version",
            ],
        );
        assert_fields(
            &document,
            "BootstrapActiveThread",
            &[
                "id",
                "title",
                "format",
                "issues_remaining",
                "queue_position",
                "last_rolled_result",
                "total_issues",
                "reading_progress",
                "issues_read",
                "last_rating",
                "tags",
                "issue_id",
                "issue_number",
                "next_issue_id",
                "next_issue_number",
            ],
        );
        assert_fields(
            &document,
            "BootstrapLastRead",
            &[
                "issue_id",
                "issue_number",
                "thread_id",
                "thread_title",
                "read_at",
                "cover_url",
            ],
        );
        assert_fields(
            &document,
            "BootstrapThreadSummary",
            &["id", "title", "format", "last_activity_at", "tags"],
        );
        assert_fields(
            &document,
            "BootstrapTag",
            &[
                "id",
                "name",
                "normalized_name",
                "scope",
                "owner_user_id",
                "color",
                "created_at",
                "updated_at",
            ],
        );
        assert_fields(
            &document,
            "BootstrapRollableItem",
            &[
                "thread",
                "issue",
                "identity",
                "reader",
                "routes",
                "overflow_routes_count",
            ],
        );
        assert_fields(
            &document,
            "BootstrapIssueSummary",
            &["id", "number", "canonical_series_title", "cover_url"],
        );
        assert_fields(
            &document,
            "BootstrapIdentitySummary",
            &[
                "source",
                "canonical_series_id",
                "state",
                "series_mapping_state",
            ],
        );
        assert_fields(
            &document,
            "BootstrapReaderStats",
            &[
                "latest_rating",
                "average_rating",
                "rating_count",
                "read_count",
                "issue_count",
                "progress_scope",
            ],
        );
        assert_fields(&document, "BootstrapRoute", &["kind", "name"]);
        assert_fields(
            &document,
            "BootstrapRollRecovery",
            &[
                "original_thread_id",
                "original_thread_title",
                "direct_blockers",
                "readable_prerequisites",
                "chains",
                "diagnostics",
            ],
        );
        assert_fields(
            &document,
            "ReadingSessionCreatedResponse",
            &["session_id", "created"],
        );
    }
}
