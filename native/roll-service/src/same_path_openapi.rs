//! Generated contracts for native operations retaining their original method/path.
//! These supplement the canonical v2 contract without retaining Python handlers.
use utoipa::OpenApi;

#[derive(utoipa::OpenApi)]
#[openapi(paths(
    crate::reading_mode::get_reading_mode_documentation,
    crate::reading_mode::set_reading_mode_documentation,
    crate::reading_mode::dismiss_reading_mode_suggestion_documentation,
    crate::reading_mode::suggest_reading_mode_documentation,
    crate::dismiss_pending::dismiss_pending_documentation,
    crate::dismiss_pending::dismiss_pending_legacy_documentation,
    crate::tags::list_tags_documentation,
    crate::tags::create_tag_documentation,
    crate::tags::effective_issue_documentation,
    crate::tags::effective_plan_documentation,
    crate::tags::effective_thread_documentation,
    crate::tags::effective_thread_issues_documentation,
    crate::tags::get_tag_documentation,
    crate::tags::update_tag_documentation,
    crate::tags::delete_tag_documentation,
    crate::tags::assign_tag_documentation,
    crate::tags::bulk_assign_tag_documentation,
    crate::tags::bulk_unassign_tag_documentation,
    crate::tags::unassign_tag_documentation,
    crate::tags::usage_tag_documentation,
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
        .merge_from(crate::session_detail::SessionDetailApi::openapi())
        .merge_from(crate::session_list::SessionListApi::openapi())
        .merge_from(crate::session_details::SessionDetailsApi::openapi())
        .merge_from(crate::undo_snapshots::UndoSnapshotsApi::openapi())
        .merge_from(crate::undo_apply::UndoApplyApi::openapi())
        .merge_from(crate::threads::ThreadsApi::openapi())
        .merge_from(crate::cbl_catalog::CblCatalogApi::openapi())
        .merge_from(crate::issue_identity::IssueIdentityApi::openapi())
        .merge_from(crate::custom_cbl::CustomCblApi::openapi());

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
        (
            "/api/v1/sessions/{session_id}/snapshots",
            "/api/sessions/{session_id}/snapshots",
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
