//! Canonical OpenAPI contract for every native operation that is routed in
//! production under `/api/v2`.
//!
//! This module does not re-declare handlers or payloads by hand. Each
//! documentation-only operation is generated from the same Rust request and
//! response types the mounted handlers use, and the aggregate merges the
//! existing per-domain [`utoipa::OpenApi`] documents (`QueueApi`, `ThreadsApi`,
//! `IssueApi`) with the v2 auth, bootstrap, dice, offer, reset
//! and reading-boundary declarations.
//!
//! The checked-in artifact is `native/contracts/v2-runtime.openapi.json`; see
//! `native/contracts/README.md` for regeneration. `scripts/export_openapi_schema.mjs`
//! merges this runtime contract into the single generated frontend client.

use utoipa::OpenApi;

/// The native `/api/v2` operations that are declared in the auth, bootstrap,
/// dice, offer, reset and reading-boundary modules.
///
/// `QueueApi`, `ThreadsApi` and `IssueApi` already publish the
/// remaining deployed operations and are merged in [`canonical_openapi`].
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
        crate::catalog_commit::commit_documentation,
        // #5716: stateless AIP-136 preview, deliberately separate from the
        // durable commit operation registered above.
        crate::catalog_series_mapping_preview::preview_series_mappings_v2_documentation,
    /// #5715: the canonical projection preview is an AIP-136 custom method on
    /// the lowerCamelCase `continuityPlans` resource, and the thread collection
    /// read is an AIP-122 nested collection. Both publish the frozen wire DTOs;
    /// neither v1 alias leaks into the v2 contract, while the durable v2 commit
    /// stays registered for the confirmation step.
    #[test]
    fn reading_order_v2_operations_are_in_v2_contract() {
        let doc = document();
        let preview = &doc["paths"]
            ["/api/v2/continuityPlans/{plan_id}:previewReadingOrderProjection"]["post"];
        assert_eq!(preview["operationId"], "preview_reading_order_projection");
        assert_eq!(
            preview["requestBody"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ReadingOrderProjectPreviewRequest"
        );
        assert_eq!(
            preview["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ReadingOrderProjectPreviewResponse"
        );
        let thread_orders = &doc["paths"]["/api/v2/threads/{thread_id}/readingOrders"]["get"];
        assert_eq!(thread_orders["operationId"], "list_thread_reading_orders");
        assert_eq!(
            thread_orders["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ThreadReadingOrdersResponse"
        );
        for schema in [
            "ReadingOrderProjectPreviewRequest",
            "ReadingOrderProjectPreviewResponse",
            "ReadingOrderProjectPreviewEntry",
            "ReadingOrderProjectPreviewConflict",
            "ThreadReadingOrdersResponse",
            "ReadingOrderResponse",
            "ReadingOrderItemResponse",
        ] {
            assert!(
                doc["components"]["schemas"][schema].is_object(),
                "missing {schema} in v2 contract"
            );
        }
        assert!(
            doc["paths"]["/api/v1/continuity-plans/{plan_id}/reading-orders/project-preview"]
                .is_null(),
            "v1 preview must not be published in the canonical v2 contract"
        );
        assert!(
            doc["paths"]["/api/v1/threads/{thread_id}/reading-orders"].is_null(),
            "v1 thread read must not be published in the canonical v2 contract"
        );
        assert!(
            doc["paths"]["/api/v2/continuity-plans/{plan_id}/reading-orders/project"]["post"]
                .is_object(),
            "durable v2 projection commit must stay registered"
        );
    }
    /// The issue read-state and reader-context operations moved from their
    /// `/api/v1/issues/{id}:action` URLs to v2 resources. Every method must stay
    /// in both the domain document and the aggregate runtime contract with its
    /// stable operationId and a success response.
    #[test]
    fn issue_read_state_operations_are_in_runtime_contract() {
        let domain = serde_json::to_value(crate::issue_read_state::issue_read_state_openapi())
            .expect("issue read-state OpenAPI");
        let aggregate = document();
        for (path, method, operation_id, success) in [
            (
                "/api/v2/issues/{issue_id}/read-markers",
                "post",
                "issue_read_state_mark_read",
                "204",
            ),
            (
                "/api/v2/issues/{issue_id}/read-markers",
                "delete",
                "issue_read_state_mark_unread",
                "204",
            ),
            (
                "/api/v2/issues/{issue_id}/position",
                "put",
                "issue_read_state_move",
                "204",
            ),
            (
                "/api/v2/issue-read-markers",
                "post",
                "issue_read_state_bulk_mark_read",
                "200",
            ),
            (
                "/api/v2/issue-read-marker-removals",
                "post",
                "issue_read_state_bulk_mark_unread",
                "200",
            ),
            (
                "/api/v2/issue-read-operations/{operation_id}",
                "get",
                "issue_read_operation_get",
                "200",
            ),
            (
                "/api/v2/issue-read-operations/{operation_id}/undo",
                "post",
                "issue_read_operation_undo",
                "200",
            ),
            (
                "/api/v2/issues/{issue_id}/reader-context",
                "get",
                "issue_read_state_reader_context",
                "200",
            ),
        ] {
            for (name, doc) in [("domain", &domain), ("aggregate", &aggregate)] {
                let operation = &doc["paths"][path][method];
                assert!(
                    operation.is_object(),
                    "missing {method} {path} in {name} contract"
                );
                assert_eq!(operation["operationId"], operation_id, "{name}");
                assert!(
                    operation["responses"][success].is_object(),
                    "{method} {path} has no {success} response in {name} contract"
                );
            }
        }
    }

    /// Generated clients must be able to page the inbox, search issue matches
    /// and send the confirm/reject bodies the handlers require.
    #[test]
    fn identity_inbox_operations_declare_runtime_inputs() {
        let doc = document();
        let params = |path: &str| -> Vec<(String, bool)> {
            doc["paths"][path]["get"]["parameters"]
                .as_array()
                .unwrap_or_else(|| panic!("{path} parameters"))
                .iter()
                .map(|p| {
                    (
                        p["name"].as_str().expect("name").to_string(),
                        p["required"].as_bool().unwrap_or(false),
                    )
                })
                .collect()
        };
        assert_eq!(
            params("/api/v2/identity-inbox"),
            vec![("offset".to_string(), false), ("limit".to_string(), false)]
        );
        assert_eq!(
            params("/api/v2/identity-inbox/issue-matches"),
            vec![
                ("q".to_string(), true),
                ("limit".to_string(), false),
                ("issue_id".to_string(), false)
            ]
        );
        for (action, schema, required) in [
            (
                "confirmations",
                "IdentityInboxConfirmRequest",
                vec!["external_identity_id"],
            ),
            (
                "rejections",
                "IdentityInboxRejectRequest",
                vec!["external_identity_id", "rejection_reason"],
            ),
        ] {
            let path = format!("/api/v2/identity-inbox/{{mapping_id}}/{action}");
            let body = &doc["paths"][path.as_str()]["post"]["requestBody"]["content"]
                ["application/json"]["schema"]["$ref"];
            assert_eq!(body, &format!("#/components/schemas/{schema}"));
            let mut declared: Vec<&str> = doc["components"]["schemas"][schema]["required"]
                .as_array()
                .unwrap_or_else(|| panic!("{schema} required"))
                .iter()
                .map(|v| v.as_str().expect("field"))
                .collect();
            declared.sort_unstable();
            assert_eq!(declared, required, "{schema}");
        }
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
    fn every_operation_is_generated_and_documented() {
        let document = document();
        // Discover operations from the generated contract itself. The separate
        // Python parity guard independently compares this contract to the real
        // Axum service, native ingress and deployed Vercel rewrites.
        let operations = operation_set(&document);
        assert!(!operations.is_empty(), "native OpenAPI must not be empty");
        for (method, path) in operations {
            let operation = &document["paths"][path.as_str()][method.as_str()];
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

    /// The same-path continuity-plans cutover must keep its v1 operations and
    /// response schemas in the generated native contract (issue #4838).
    #[test]
    fn continuity_plans_same_path_operations_and_schemas_are_documented() {
        let document = document();
        for path in [
            "/api/v2/continuity-plans/",
            "/api/v2/continuity-plans/from-reading-order",
            "/api/v2/continuity-plans/{plan_id}",
            "/api/v2/continuity-plans/{plan_id}/membership",
            "/api/v2/continuity-plans/{plan_id}/dependencies/{dependency_id}",
            "/api/v2/continuity-plans/{plan_id}/reading-orders/project",
            "/api/v2/continuity-plans/release-sources/",
            "/api/v2/continuity-plans/release-sources/{source_id}",
            "/api/v2/continuity-plans/{plan_id}/release-sources/",
        ] {
            assert!(
                document["paths"].get(path).is_some(),
                "migrated v1 path missing from native contract: {path}"
            );
        }
        for schema in [
            "ContinuityPlanResponse",
            "ContinuityPlanWrite",
            "ContinuityPlanListItem",
            "ReadingPlanDependencyLink",
            "ReadingPlanMembershipResponse",
            "ReleaseSourceCreate",
            "ReleaseSourceUpdate",
            "ContinuityReleaseSourceResponse",
        ] {
            assert!(
                document["components"]["schemas"].get(schema).is_some(),
                "migrated response schema missing from native contract: {schema}"
            );
        }
        assert_fields(
            &document,
            "ContinuityReleaseSourceResponse",
            &[
                "id",
                "plan_id",
                "thread_id",
                "provider_volume_id",
                "enabled",
            ],
        );
    }

    /// The v2 collection CRUD (#5710) must be published with stable operation
    /// ids and no `/detail` action path.
    #[test]
    fn reading_order_groups_v2_operations_are_in_runtime_contract() {
        let document = document();
        for (path, method, operation_id, success) in [
            (
                "/api/v2/readingOrderGroups",
                "get",
                "reading_order_groups_list",
                "200",
            ),
            (
                "/api/v2/readingOrderGroups",
                "post",
                "reading_order_groups_create",
                "201",
            ),
            (
                "/api/v2/readingOrderGroups/{group_id}",
                "get",
                "reading_order_groups_get",
                "200",
            ),
            (
                "/api/v2/readingOrderGroups/{group_id}",
                "patch",
                "reading_order_groups_update",
                "200",
            ),
            (
                "/api/v2/readingOrderGroups/{group_id}",
                "delete",
                "reading_order_groups_delete",
                "204",
            ),
        ] {
            let operation = &document["paths"][path][method];
            assert!(
                operation.is_object(),
                "missing {method} {path} in v2 contract"
            );
            assert_eq!(operation["operationId"], operation_id, "{method} {path}");
            assert!(
                operation["responses"][success].is_object(),
                "{method} {path} missing {success}"
            );
        }
        assert!(
            document["paths"]
                .get("/api/v2/readingOrderGroups/{group_id}/detail")
                .is_none(),
            "v2 must not publish a /detail action path"
        );
        assert_fields(
            &document,
            "DependencyGroupDetailResponse",
            &["id", "name", "created_at", "memberships", "linked_plans"],
        );
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
            document["paths"]["/api/v2/readingSessions"]["post"]["responses"]["200"]["content"]
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
                "snoozed_thread_ids",
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
                "issue_number_alias",
                "provider_issue_number",
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
        assert_fields(
            &document,
            "RollDieStateResponse",
            &["die", "ladder", "default_die", "last_roll"],
        );
        assert_fields(
            &document,
            "RollEligibleIssueIdsResponse",
            &["die", "issue_ids", "thread_ids", "pool_reason"],
        );
    }
}
