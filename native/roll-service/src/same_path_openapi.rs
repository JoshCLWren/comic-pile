//! Generated contracts for native operations retaining their original method/path.
//! These supplement the canonical v2 contract without retaining Python handlers.
use utoipa::OpenApi;

#[derive(utoipa::OpenApi)]
#[openapi(paths(
    crate::reading_mode::get_reading_mode_documentation,
    crate::reading_mode::set_reading_mode_documentation,
    crate::reading_mode::dismiss_reading_mode_suggestion_documentation,
    crate::reading_mode::suggest_reading_mode_documentation,
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
    crate::session_details::get_session_details_documentation,
    crate::undo_snapshots::list_undo_snapshots_documentation,
    crate::undo_apply::undo_to_snapshot_documentation,
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
            "/api/v2/issues/{issue_id}/dependencies",
            "/api/v1/issues/{issue_id}/dependencies",
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

    document
}
