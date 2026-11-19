//! Generated contracts for native operations retaining their original method/path.
//! These supplement the canonical v2 contract without retaining Python handlers.
use utoipa::OpenApi;

#[derive(utoipa::OpenApi)]
#[openapi(paths(
    crate::dismiss_pending::dismiss_pending_documentation,
    crate::dismiss_pending::dismiss_pending_legacy_documentation,
    crate::session_history::list_session_snapshots_documentation,
    crate::session_list::list_sessions_documentation,
    crate::session_list::list_sessions_v1_documentation,
    crate::session_details::get_session_details_documentation,
    crate::session_details::get_session_details_v1_documentation,
    crate::undo_snapshots::list_undo_snapshots_documentation,
    crate::undo_snapshots::list_undo_snapshots_v1_documentation,
    crate::undo_apply::undo_to_snapshot_documentation,
    crate::undo_apply::undo_to_snapshot_v1_documentation,
    crate::issue_read::get_issue_documentation,
    crate::issue_read::get_issue_dependencies_documentation,
    crate::threads::get_thread_detail_documentation,
    crate::threads::get_bare_thread_detail_documentation,
    crate::taste_discoveries::list_documentation,
    crate::taste_discoveries::dismiss_documentation,
    crate::creators::list_creators_documentation,
    crate::creators::get_summaries_documentation,
    crate::catalog_series_mapping_preview::documentation,
    crate::continuity_plans_project_preview::documentation,
    crate::issue_identity_adoption_preview::documentation,
    crate::issue_identity_cbl_reading_graph_preview::documentation,
))]
struct SamePathApi;

/// Preserve shared DTOs while giving each mounted alias its own operation ID.
fn alias_item(
    mut item: utoipa::openapi::path::PathItem,
    alias: &str,
) -> utoipa::openapi::path::PathItem {
    let suffix: String = alias
        .chars()
        .map(|ch| if ch.is_ascii_alphanumeric() { ch } else { '_' })
        .collect();
    for operation in [
        &mut item.get,
        &mut item.put,
        &mut item.post,
        &mut item.delete,
        &mut item.options,
        &mut item.head,
        &mut item.patch,
        &mut item.trace,
    ]
    .into_iter()
    .flatten()
    {
        if let Some(id) = operation.operation_id.as_mut() {
            id.push_str("__");
            id.push_str(&suffix);
        }
    }
    item
}

/// Generate the same-path native contract from the handler DTO documentation.
pub fn same_path_openapi() -> utoipa::openapi::OpenApi {
    let mut document = crate::openapi::canonical_openapi()
        .merge_from(SamePathApi::openapi())
        .merge_from(crate::preferences::PreferencesApi::openapi())
        .merge_from(crate::bug_reports::BugReportsApi::openapi())
        .merge_from(crate::reading_orders::ReadingOrdersApi::openapi())
        .merge_from(crate::reading_plan_sync::ReadingPlanSyncApi::openapi())
        .merge_from(crate::undo_snapshots::UndoSnapshotsApi::openapi())
        .merge_from(crate::undo_apply::UndoApplyApi::openapi())
        .merge_from(crate::threads::ThreadsApi::openapi())
        .merge_from(crate::cbl_catalog::CblCatalogApi::openapi())
        .merge_from(crate::issue_identity::IssueIdentityApi::openapi())
        .merge_from(crate::custom_cbl::CustomCblApi::openapi())
        // The browser still calls these v1 thread dependency URLs, which now
        // run in Rust. Publishing their contract here keeps the generated TS
        // client types after the shadowed Python handlers retire (#5440).
        .merge_from(crate::thread_ordering::ThreadOrderingApi::openapi())
        .merge_from(crate::thread_issues::ThreadIssuesApi::openapi())
        .merge_from(crate::issue_read_state::IssueReadStateApi::openapi())
        .merge_from(crate::dependency_groups::DependencyGroupsApi::openapi());

    // Each alias is mounted to the identical handler in the native router.
    // Copying that handler's generated contract avoids a second DTO definition.
    for operation in [
        "register",
        "login",
        "refresh",
        "logout",
        "csrf",
        "me",
        "forgot-password",
        "reset-password",
    ] {
        let source = format!("/api/v2/auth/{operation}");
        if let Some(item) = document.paths.paths.get(&source).cloned() {
            for prefix in ["/api/v1/auth", "/api/auth"] {
                let alias = format!("{prefix}/{operation}");
                document
                    .paths
                    .paths
                    .insert(alias.clone(), alias_item(item.clone(), &alias));
            }
        }
    }
    for (source, alias) in [
        (
            "/api/v2/issues/{issue_id}/comicvine",
            "/api/v1/issues/{issue_id}/comicvine",
        ),
        (
            "/api/v2/threads/{thread_id}/dependencies",
            "/api/v1/threads/{thread_id}/dependencies",
        ),
        (
            "/api/v2/threads/{thread_id}/issue-dependencies",
            "/api/v1/threads/{thread_id}/issue-dependencies",
        ),
    ] {
        if let Some(item) = document.paths.paths.get(source).cloned() {
            document
                .paths
                .paths
                .insert(alias.to_string(), alias_item(item, alias));
        }
    }
    // utoipa's `schema_with` supplies the full `limit` schema but suppresses the
    // parameter-level description. Restore the Python `Query(description=...)`
    // text so the generated client contract matches the retired FastAPI route.
    if let Some(item) = document.paths.paths.get_mut("/api/v1/taste/discoveries") {
        if let Some(operation) = item.get.as_mut() {
            for parameter in operation.parameters.iter_mut().flatten() {
                if let utoipa::openapi::RefOr::T(parameter) = parameter {
                    if parameter.name == "limit" {
                        parameter.description = Some("Maximum discoveries to return.".to_string());
                    }
                }
            }
        }
    }
    document
        .paths
        .paths
        .retain(|path, _| !path.starts_with("/api/v2/"));
    document.info.title = "ComicPile native same-path API".to_string();
    document
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn checked_in_contract_is_current() {
        let expected = include_str!("../../contracts/same-path-runtime.openapi.json");
        let generated = same_path_openapi()
            .to_pretty_json()
            .expect("serializable contract");
        assert_eq!(expected.trim_end(), generated.trim_end());
    }

    /// The thread dependency operations moved to native Rust but their browser
    /// URLs stay on v1. Their response component schemas must stay in the
    /// same-path document so retiring the Python handlers does not erase the
    /// `components['schemas'][...]` aliases in the generated TS client (#5440).
    #[test]
    fn same_path_contract_documents_thread_dependency_schemas() {
        let document = serde_json::to_value(same_path_openapi()).expect("OpenAPI");
        let schemas = document["components"]["schemas"]
            .as_object()
            .expect("schemas");
        for name in [
            "BatchBlockingExplanationResponse",
            "ConnectedThreadInfo",
            "ThreadConnectedResponse",
        ] {
            assert!(
                schemas[name].is_object(),
                "missing {name} in same-path contract schemas"
            );
        }
        let paths = document["paths"].as_object().expect("paths");
        for (path, method) in [
            ("/api/v1/threads/{thread_id}:getBlockingInfo", "post"),
            ("/api/v1/threads:getBlockingInfo", "post"),
            ("/api/v1/threads/{thread_id}/dependency-order-check", "get"),
            ("/api/v1/threads/{thread_id}/connected", "get"),
        ] {
            assert!(
                paths[path][method]["responses"]["200"].is_object(),
                "missing native 200 response for {method} {path}"
            );
        }
    }

    /// Every issue-identity / CBL-adoption operation routed to native Rust
    /// must keep its wire contract in the same-path document so the generated
    /// TypeScript client does not lose those methods when the Python handlers
    /// retire (#4843).
    #[test]
    fn same_path_contract_documents_all_issue_identity_operations() {
        let document = serde_json::to_value(same_path_openapi()).expect("OpenAPI");
        let paths = document["paths"].as_object().expect("paths");
        for (path, method) in [
            ("/api/v1/issue-identity/cbl-sources", "get"),
            ("/api/v1/issue-identity/cbl-sources/{list_id}", "get"),
            (
                "/api/v1/issue-identity/cbl-sources/by-comicvine-issue/{comicvine_issue_id}",
                "get",
            ),
            ("/api/v1/issue-identity/cbl-sources/compare", "post"),
            (
                "/api/v1/issue-identity/reading-lists/{list_id}/cbl-candidates",
                "get",
            ),
            (
                "/api/v1/issue-identity/cbl/{list_id}/adoption-preview",
                "get",
            ),
            ("/api/v1/issue-identity/cbl/{list_id}/adoption-plan", "post"),
            ("/api/v1/cbl/{list_id}/adoption-commit", "post"),
            (
                "/api/v1/cbl/{list_id}/reading-plans/{plan_id}/adoption-commit",
                "post",
            ),
        ] {
            let operation = &paths[path][method];
            assert!(
                operation.is_object(),
                "missing {method} {path} in same-path contract"
            );
            assert!(
                operation["responses"]["200"].is_object()
                    || operation["responses"]["201"].is_object(),
                "{method} {path} has no success response"
            );
        }
    }

    /// The six same-path thread issue-management operations (#4832 part D)
    /// must keep their wire contract in the same-path document so the
    /// generated TypeScript client keeps those methods when the retained
    /// Python declarations retire.
    #[test]
    fn same_path_contract_documents_all_thread_issue_operations() {
        let document = serde_json::to_value(same_path_openapi()).expect("OpenAPI");
        let paths = document["paths"].as_object().expect("paths");
        for (path, method, success) in [
            ("/api/v1/threads/{thread_id}/issues", "post", "201"),
            ("/api/v1/threads/{thread_id}/issues/creators", "get", "200"),
            ("/api/v1/threads/{thread_id}/issues:reorder", "post", "204"),
            ("/api/v1/threads/{thread_id}:migrateToIssues", "post", "200"),
            (
                "/api/v1/threads/{thread_id}:migrateToIssuesSimple",
                "post",
                "200",
            ),
            ("/api/v1/threads/{thread_id}:setCurrentIssue", "post", "200"),
        ] {
            let operation = &paths[path][method];
            assert!(
                operation.is_object(),
                "missing {method} {path} in same-path contract"
            );
            assert!(
                operation["responses"][success].is_object(),
                "{method} {path} has no {success} response"
            );
        }
    }

    /// The issue read-state and reader-context cutover (#4832 part C) keeps its
    /// original v1 URLs, so every operation must stay in the same-path document
    /// to survive retirement of the shadowed Python handlers.
    #[test]
    fn same_path_contract_documents_issue_read_state_operations() {
        let document = serde_json::to_value(same_path_openapi()).expect("OpenAPI");
        let paths = document["paths"].as_object().expect("paths");
        for (path, method, operation_id) in [
            (
                "/api/v1/issues/{issue_id}:markRead",
                "post",
                "issue_read_state_mark_read",
            ),
            (
                "/api/v1/issues/{issue_id}:markUnread",
                "post",
                "issue_read_state_mark_unread",
            ),
            (
                "/api/v1/issues/{issue_id}:move",
                "post",
                "issue_read_state_move",
            ),
            (
                "/api/v1/issues:bulkMarkRead",
                "post",
                "issue_read_state_bulk_mark_read",
            ),
            (
                "/api/v1/issues:bulkMarkUnread",
                "post",
                "issue_read_state_bulk_mark_unread",
            ),
            (
                "/api/v1/issues/{issue_id}/reader-context",
                "get",
                "issue_read_state_reader_context",
            ),
        ] {
            let operation = &paths[path][method];
            assert!(operation.is_object(), "missing {method} {path} in contract");
            assert_eq!(operation["operationId"], operation_id);
            assert!(
                operation["responses"]["204"].is_object()
                    || operation["responses"]["200"].is_object(),
                "{method} {path} has no success response"
            );
        }
    }

    #[test]
    fn same_path_contract_claims_reading_plan_sync_status() {
        let document = same_path_openapi();
        let item = document
            .paths
            .paths
            .get("/api/v1/reading-plan-sync/status")
            .expect("native reading-plan-sync status operation in same-path contract");
        let operation = item.get.as_ref().expect("GET status operation");
        assert_eq!(
            operation.operation_id.as_deref(),
            Some("reading_plan_sync_status")
        );
    }

    /// The generated frontend client declares one property per operation id, so
    /// reusing a function name (for example `documentation`) for several preview
    /// handlers would produce duplicate TypeScript identifiers. Keep each
    /// preview operation id unique and identical to the Python wire contract.
    #[test]
    fn preview_operations_keep_unique_python_operation_ids() {
        let document = same_path_openapi();
        let expected = [
            (
                "/api/v1/catalog/series-mappings/preview",
                "preview_series_mapping_api_v1_catalog_series_mappings_preview_post",
            ),
            (
                "/api/v1/continuity-plans/{plan_id}/reading-orders/project-preview",
                "preview_plan_projection_api_v1_continuity_plans__plan_id__reading_orders_project_preview_post",
            ),
            (
                "/api/v1/issue-identity/cbl/{list_id}/adoption-preview",
                "api_cbl_adoption_preview_api_v1_issue_identity_cbl__list_id__adoption_preview_get",
            ),
            (
                "/api/v1/issue-identity/cbl/{list_id}/reading-graph-preview",
                "preview_cbl_reading_graph_api_v1_issue_identity_cbl__list_id__reading_graph_preview_post",
            ),
        ];
        let mut seen = std::collections::HashSet::new();
        for (path, operation_id) in expected {
            let item = document
                .paths
                .paths
                .get(path)
                .unwrap_or_else(|| panic!("missing native preview path {path}"));
            let operation = item
                .get
                .as_ref()
                .or(item.post.as_ref())
                .unwrap_or_else(|| panic!("missing preview operation for {path}"));
            assert_eq!(operation.operation_id.as_deref(), Some(operation_id));
            assert!(
                seen.insert(operation_id),
                "duplicate preview operation id {operation_id}"
            );
        }
    }

    /// Both browser-called taste-discovery operations (#4853) must keep their
    /// wire contract in the native same-path document. Without the GET listing
    /// here, retiring the shadowed Python handler would drop it from the
    /// generated TypeScript client contract.
    #[test]
    fn same_path_contract_documents_both_taste_discovery_operations() {
        let document = serde_json::to_value(same_path_openapi()).expect("OpenAPI");
        let paths = document["paths"].as_object().expect("paths");

        let listing = &paths["/api/v1/taste/discoveries"]["get"];
        assert_eq!(listing["operationId"], "taste_discoveries_list");
        assert!(listing["responses"]["200"].is_object());
        assert_eq!(
            listing["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/TasteDiscoveryListResponse"
        );
        let params = listing["parameters"].as_array().expect("limit param");
        let limit = params
            .iter()
            .find(|param| param["name"] == "limit" && param["in"] == "query")
            .expect("GET listing must document its bounded limit query parameter");
        assert_eq!(limit["description"], "Maximum discoveries to return.");
        assert_eq!(limit["schema"]["type"], "integer");
        assert_eq!(limit["schema"]["title"], "Limit");
        assert_eq!(limit["schema"]["minimum"], 1);
        assert_eq!(limit["schema"]["maximum"], 3);
        assert_eq!(limit["schema"]["default"], 3);

        let dismiss = &paths["/api/v1/taste/discoveries/{signal_id}/dismiss"]["post"];
        assert_eq!(dismiss["operationId"], "dismiss_documentation");
        assert!(dismiss["responses"]["200"].is_object());
        assert!(dismiss["responses"]["404"].is_object());
        assert_eq!(
            dismiss["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/TasteDismissResponse"
        );

        let schemas = document["components"]["schemas"]
            .as_object()
            .expect("schemas");
        let list_response = &schemas["TasteDiscoveryListResponse"];
        assert_eq!(
            list_response["required"],
            serde_json::json!(["discoveries", "generated_at"])
        );
        let discovery = &schemas["TasteDiscovery"];
        for field in [
            "id",
            "signal_type",
            "external_key",
            "display_name",
            "prompt",
            "evidence_count",
            "distinct_thread_count",
        ] {
            assert!(
                discovery["required"]
                    .as_array()
                    .is_some_and(|required| required.iter().any(|name| name == field)),
                "TasteDiscovery must keep required wire field {field}"
            );
        }
    }
}
