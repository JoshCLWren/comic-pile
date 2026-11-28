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
        // #5715: canonical AIP-136 projection preview and AIP-122 thread
        // reading-order collection. The retained v1 aliases stay in the
        // same-path contract only and must not be published here.
        crate::continuity_plans_project_preview::preview_reading_order_projection_v2_documentation,
        crate::thread_ordering::thread_reading_orders_v2_documentation,
        crate::issue_identity::cbl_adoption_commit_documentation,
        crate::issue_identity::cbl_targeted_adoption_commit_documentation,
        crate::activity::list_activity_documentation,
        crate::bootstrap::bootstrap_documentation,
        crate::bootstrap::initialize_session_documentation,
        crate::dice_api::manual_die_documentation,
        crate::roll_offer::offer_documentation,
        crate::roll_offer::unsnooze_documentation,
        crate::roll_reset::reset_documentation,
        crate::roll_switch_prerequisite::switch_prerequisite_documentation,
        crate::dismiss_pending::dismiss_pending_documentation,
        crate::session_history::list_session_snapshots_documentation,
        crate::session_details::get_session_details_documentation,
        crate::session_list::list_reading_sessions_documentation,
        crate::session_list::get_reading_session_documentation,
        crate::roll_resources::die_state_documentation,
        crate::roll_resources::last_read_documentation,
        crate::roll_resources::recovery_documentation,
        crate::roll_resources::eligible_issue_ids_documentation,
        crate::reading_boundary::reading_boundary_batch_documentation,
        crate::demo::read_demo_roll_documentation,
        crate::metrics::get_metrics_documentation,
        crate::reading_graph::reading_graph_documentation,
        crate::reading_graph::repair_documentation,
        crate::dependencies::create_dependency_documentation,
        crate::dependencies::delete_dependency_documentation,
        crate::dependencies::get_thread_dependencies_documentation,
        crate::legacy_dependencies::blocked_documentation,
        crate::legacy_dependencies::get_documentation,
        crate::legacy_dependencies::update_documentation,
        crate::issue_mutation::create_issues_documentation,
        crate::issue_mutation::delete_issue_documentation,
        crate::issue_mutation::issue_order_documentation,
        crate::issue_mutation::preview_issue_create_documentation,
        crate::issue_mutation::preview_issue_structure_documentation,
        crate::issue_read::get_issue_documentation,
        crate::issue_read::get_issue_dependencies_documentation,
        crate::issue_read::get_thread_issue_dependencies_documentation,
        crate::issue_read::list_thread_issues_documentation,
        crate::issue_read::list_thread_issues_v2_documentation,
        crate::thread_issues::creator_credits_documentation,
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
        crate::reading_mode::get_reading_mode_documentation,
        crate::reading_mode::set_reading_mode_documentation,
        crate::reading_mode::dismiss_reading_mode_suggestion_documentation,
        crate::reading_mode::suggest_reading_mode_documentation,
        crate::preferences::get_user_preferences_documentation,
        crate::preferences::patch_user_preferences_documentation,
        crate::reading_list::list_reading_lists_documentation,
        crate::reading_list::get_reading_list_documentation,
        crate::reading_list::create_reading_list_documentation,
        crate::reading_list::delete_reading_list_documentation,
        crate::reading_list::update_reading_list_documentation,
        crate::reading_list::read_reading_list_documentation,
        crate::reading_plan_recovery::preview_documentation,
        crate::reading_plan_recovery::relink_documentation,
        crate::reading_plan_reader::read_documentation,
        crate::identity_inbox::list_documentation,
        crate::identity_inbox::search_documentation,
        crate::identity_inbox::get_documentation,
        crate::identity_inbox::confirm_documentation,
        crate::identity_inbox::defer_documentation,
        crate::identity_inbox::reject_documentation,
        crate::identity_inbox::skip_documentation,
        crate::continuity_rules::list_documentation,
        crate::continuity_rules::create_documentation,
        crate::continuity_rules::get_documentation,
        crate::continuity_rules::update_documentation,
        crate::continuity_rules::delete_documentation,
        // Same-path v1 continuity-plans operations cut over to native Rust.
        crate::continuity_plans::list_documentation,
        crate::continuity_plans::create_documentation,
        crate::continuity_plans::get_documentation,
        crate::continuity_plans::update_documentation,
        crate::continuity_plans::delete_documentation,
        crate::continuity_plans::adopt_reading_order_documentation,
        crate::continuity_plans::membership_documentation,
        crate::continuity_plans::link_dependency_documentation,
        crate::continuity_plans::unlink_dependency_documentation,
        crate::continuity_plans::project_reading_order_documentation,
        crate::continuity_plans::release_source_create_documentation,
        crate::continuity_plans::release_source_list_documentation,
        crate::continuity_plans::release_source_list_reader_documentation,
        crate::continuity_plans::release_source_update_documentation,
        crate::continuity_plans::release_source_delete_documentation,
        // All five same-path releases operations are documented in this
        // browser-facing native contract: the two public reads plus the
        // writer-authorized source/publish/retract operations, which carry
        // an x-release-writer-token header and keep the wire contract the
        // Python handler previously served.
        crate::releases::list_documentation,
        crate::releases::get_documentation,
        crate::releases::reconcile_documentation,
        crate::releases::publish_documentation,
        crate::releases::retract_documentation,
        crate::comicvine_resolution::series_import_status_documentation,
        crate::comicvine_v2::search_series_documentation,
        crate::comicvine_v2::resolve_input_documentation,
        crate::comicvine_v2::comicvine_series_issues_documentation,
        crate::comicvine_v2::import_series_documentation,
        crate::comicvine_v2::series_import_status_v2_documentation,
        crate::comicvine_v2::import_issue_documentation,
        crate::comicvine_v2::confirm_identity_documentation,
        crate::comicvine_v2::replace_identity_documentation,
        crate::comicvine_v2::remove_identity_documentation,
        crate::comicvine_v2::apply_correction_documentation,
        crate::comicvine_v2::revert_correction_documentation,
        crate::comicvine_v2::refresh_metadata_documentation,
        crate::comicvine_v2::get_issue_identity_documentation,
        crate::comicvine_v2::list_corrections_documentation,
        crate::creators_v2::list_documentation,
        crate::creators_v2::summaries_documentation,
        crate::creators_v2::compare_documentation,
        crate::creators_v2::discoveries_documentation,
        crate::creators_v2::team_chemistry_documentation,
        crate::creators_v2::detail_documentation,
        crate::creators_v2::series_issues_documentation,
        crate::creators_v2::metric_documentation,
        crate::creators_v2::rating_distribution_documentation,
        crate::creators_v2::role_documentation,
        crate::creators_v2::series_documentation,
        // AIP-136 collection custom method for the advisory duplicate lookup (#5705).
        crate::thread_lifecycle::check_potential_duplicates_v2_documentation,
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
        crate::roll_offer::UnsnoozeRequest,
        crate::roll_offer::UnsnoozeResponse,
        crate::roll_reset::ResetDiceRequest,
        crate::roll_reset::ResetDiceResponse,
        crate::roll_resources::RollDieStateResponse,
        crate::roll_resources::RollLastRoll,
        crate::roll_resources::RollLastRead,
        crate::roll_resources::RollRecovery,
        crate::roll_resources::RollRecoveryBlocker,
        crate::roll_resources::RollRecoveryPrerequisite,
        crate::roll_resources::RollRecoveryChainNode,
        crate::roll_resources::RollRecoveryDiagnostic,
        crate::roll_resources::RollEligibleIssueIdsResponse,
        crate::reading_boundary::ReadingBoundaryBatchRequest,
        crate::demo::DemoRoll,
        crate::metrics::StartupMetricsResponse,
        crate::reading_boundary::ReadingBoundaryBatchResponseV2,
        crate::reading_graph::ReadingGraphIssue,
        crate::reading_graph::ReadingGraphEdge,
        crate::reading_graph::ReadingGraphCycle,
        crate::reading_graph::ReadingGraphList,
        crate::reading_graph::ReadingGraphThread,
        crate::reading_graph::ReadingGraphRepairOption,
        crate::reading_graph::ReadingGraphResponse,
        crate::reading_graph::ReadingGraphRepairRequest,
        crate::reading_graph::ReadingGraphRepairResponse,
        crate::frontier_audit::FrontierAuditReport,
        crate::frontier_audit::FrontierAuditFinding,
        crate::frontier_audit::AuditListMembership,
        crate::frontier_audit::AuditEvidenceEdge,
        crate::dependencies::DependencyCreateRequest,
        crate::dependencies::DependencyResponse,
        crate::dependencies::ThreadDependenciesResponse,
        crate::legacy_dependencies::DependencyNoteUpdate,
        crate::issue_mutation::CreateIssuesRequest,
        crate::issue_mutation::IssueMutationItem,
        crate::issue_mutation::IssueListResponse,
        crate::issue_mutation::IssueOrderRequest,
        crate::issue_mutation::PreviewIssuesRequest,
        crate::issue_mutation::PreviewIssueItem,
        crate::issue_mutation::IssueEditPreviewOutcome,
        crate::issue_mutation::IssueEditPreviewResponse,
        crate::issue_mutation::IssueEditAliasOffer,
        crate::issue_mutation::IssuePlacementStrategy,
        crate::reading_list::ReadingListEntryIntent,
        crate::reading_list::ReadingListEntry,
        crate::reading_list::ReadingListSummary,
        crate::reading_list::ReadingList,
        crate::reading_list::ReadingListDependency,
        crate::reading_list::ReadingListBlockerExplanation,
        crate::reading_list::ReadingListReaderEntry,
        crate::reading_list::ReadingListReader,
        crate::reading_list::ReadingListWrite,
        crate::reading_list::ReadingListPredecessorChange,
        crate::reading_plan_recovery::RecoveryStep,
        crate::reading_plan_recovery::RecoveryCandidate,
        crate::reading_plan_recovery::PlanRecoveryPreview,
        crate::reading_plan_recovery::PlanRelinkRequest,
        crate::reading_plan_recovery::PlanRelinkResult,
        crate::reading_plan_reader::PlanReaderBlocker,
        crate::reading_plan_reader::PlanReaderIssue,
        crate::reading_plan_reader::PlanReaderLane,
        crate::reading_plan_reader::PlanReaderProgress,
        crate::reading_plan_reader::PlanReaderSource,
        crate::reading_plan_reader::PlanReleaseSourceStatus,
        crate::reading_plan_reader::PlanReleaseCandidate,
        crate::reading_plan_reader::PlanReaderResponse,
        crate::identity_inbox::IdentityInboxConfirmRequest,
        crate::identity_inbox::IdentityInboxRejectRequest,
        crate::identity_inbox::IdentityInboxCandidate,
        crate::identity_inbox::IdentityInboxItem,
        crate::identity_inbox::IdentityInboxResponse,
        crate::identity_inbox::IdentityInboxSearchResponse,
        crate::identity_inbox::IdentityInboxActionResponse,
        crate::issue_read::IssueDependencyEdge,
        crate::issue_read::IssueDependenciesResponse,
        crate::issue_read::ThreadIssueDependenciesResponse,
        crate::issue_read::ThreadIssueListResponse,
        crate::issue_read::IssueDetailResponse,
        crate::thread_issues::CreatorCredit,
        crate::thread_issues::IssueCreatorsEntry,
        crate::thread_issues::ThreadCreatorCreditsResponse,
        crate::identity_inbox::IdentityInboxSearchResult,
        crate::continuity_rules::ContinuityRuleRequest,
        crate::continuity_rules::ContinuityRuleResponse,
        crate::continuity_rules::ConvergenceTarget,
        crate::continuity_plans::ContinuityPlanLane,
        crate::continuity_plans::ContinuityPlanNode,
        crate::continuity_plans::ContinuityPlanWrite,
        crate::continuity_plans::ContinuityPlanResponse,
        crate::continuity_plans::ContinuityPlanListItem,
        crate::continuity_plans::ReadingOrderProjectionRequest,
        crate::continuity_plans::ReadingOrderProjectionEntry,
        crate::continuity_plans::ReadingOrderProjectionConflict,
        crate::continuity_plans::ReadingOrderProjectionPreview,
        crate::continuity_plans::ReadingOrderProjectionResult,
        crate::continuity_plans::ReadingOrderAdoptRequest,
        // #5715: preview DTOs are shared with the retained v1 alias, while the
        // thread reading-order collection keeps its frozen wire shape.
        crate::continuity_plans_project_preview::ReadingOrderProjectPreviewRequest,
        crate::continuity_plans_project_preview::ReadingOrderProjectPreviewResponse,
        crate::continuity_plans_project_preview::ReadingOrderProjectPreviewEntry,
        crate::continuity_plans_project_preview::ReadingOrderProjectPreviewConflict,
        crate::thread_ordering::ThreadReadingOrdersResponse,
        crate::thread_ordering::ReadingOrderResponse,
        crate::thread_ordering::ReadingOrderItemResponse,
        crate::continuity_plans::ReleaseSourceCreate,
        crate::continuity_plans::ReleaseSourceUpdate,
        crate::continuity_plans::ReleaseSourceResponse,
        crate::continuity_plans::ReadingPlanReleaseSourceStatus,
        crate::continuity_plans::ReadingPlanMemberIssue,
        crate::continuity_plans::ReadingPlanSourceSnapshot,
        crate::continuity_plans::ReadingPlanSourcePlacementView,
        crate::continuity_plans::ReadingPlanProgress,
        crate::continuity_plans::ReadingPlanMembershipResponse,
        crate::continuity_plans::ReadingPlanDependencyLink,
        crate::continuity_plans::ReadingPlanDependencyLinkRequest,
        crate::catalog_commit::CommitRequest,
        crate::catalog_commit::CommitResponse,
        crate::catalog_commit::CommitSeriesMapping,
        // #5716: the preview DTOs are shared by the retained v1 alias, but the
        // canonical v2 custom method must publish them in the v2 contract too.
        crate::catalog_series_mapping_preview::SeriesMappingPreviewRequest,
        crate::catalog_series_mapping_preview::SeriesMappingPreviewResponse,
        crate::catalog_series_mapping_preview::SeriesMappingPreviewRow,
        crate::catalog_series_mapping_preview::SeriesMappingPreviewScope,
        crate::catalog_series_mapping_preview::SeriesMappingPreviewCounts,
        crate::catalog_series_mapping_preview::SeriesMappingPreviewProviderSeries,
        crate::issue_identity::CommitSeriesDecision,
        crate::issue_identity::CommitEntryOverride,
        crate::issue_identity::CblAdoptionCommitRequest,
        crate::issue_identity::ContinuityPlanResponseWire,
        crate::issue_identity::CblAdoptionCommitResponseWire,
        crate::releases::PublicReleaseResponse,
        crate::releases::ReleaseListResponse,
        crate::comicvine_resolution::SeriesImportStatusResponse,
        crate::comicvine_v2::ComicVineSeriesResult,
        crate::comicvine_v2::ComicVineSeriesSearchResponse,
        crate::comicvine_v2::ComicVineResolvedIssue,
        crate::comicvine_v2::ComicVineIssueCandidate,
        crate::comicvine_v2::ComicVineResolveResponse,
        crate::comicvine_v2::ComicVineSeriesIssuesResponse,
        crate::comicvine_v2::ImportSeriesRequest,
        crate::comicvine_v2::ImportSeriesIssueResult,
        crate::comicvine_v2::ImportSeriesResponse,
        crate::comicvine_v2::ImportIssueRequest,
        crate::comicvine_v2::ImportIssueResponse,
        crate::comicvine_v2::MetadataRefreshResponse,
        crate::comicvine_v2::ConfirmIdentityRequest,
        crate::comicvine_v2::ReplaceIdentityRequest,
        crate::comicvine_v2::MetadataCorrectionRequest,
        crate::comicvine_v2::MetadataCorrectionRevertRequest,
        crate::comicvine_v2::IssueIdentityMapping,
        crate::comicvine_v2::IssueIdentityResponse,
        crate::comicvine_v2::CanonicalCorrection,
        crate::comicvine_v2::MetadataCorrectionsResponse,
        crate::creators_v2::CreatorSummaryCoverage,
        crate::creators_v2::CreatorSummaryItem,
        crate::creators_v2::CreatorSummariesResponse,
        crate::creators_v2::CreatorListItem,
        crate::creators_v2::CreatorListResponse,
        crate::creators_v2::CreatorRoleStat,
        crate::creators_v2::CreatorIssueRow,
        crate::creators_v2::CreatorRatingBucket,
        crate::creators_v2::CreatorRatingDistribution,
        crate::creators_v2::CreatorSeriesGroup,
        crate::creators_v2::CreatorSeriesIssueListResponse,
        crate::creators_v2::CreatorIssueInsight,
        crate::creators_v2::CreatorSeriesInsight,
        crate::creators_v2::CreatorInsights,
        crate::creators_v2::CreatorDetailResponse,
        crate::creators_v2::CreatorComparisonRoleStat,
        crate::creators_v2::CreatorComparisonSeriesAggregate,
        crate::creators_v2::CreatorComparisonIssueRef,
        crate::creators_v2::CreatorComparisonItem,
        crate::creators_v2::CreatorComparisonCoverage,
        crate::creators_v2::CreatorComparisonResponse,
        crate::creators_v2::CreatorDiscoveryReason,
        crate::creators_v2::CreatorDiscoveryEntry,
        crate::creators_v2::CreatorDiscoveryView,
        crate::creators_v2::CreatorDiscoveryCoverage,
        crate::creators_v2::CreatorDiscoveryResponse,
        crate::creators_v2::CreatorTeamMember,
        crate::creators_v2::CreatorTeamIssueRef,
        crate::creators_v2::CreatorTeamSeriesRef,
        crate::creators_v2::CreatorTeamPair,
        crate::creators_v2::CreatorTeamCoverage,
        crate::creators_v2::CreatorTeamChemistryResponse,
        crate::creators_v2::CreatorMetricCalculation,
        crate::creators_v2::CreatorMetricIssue,
        crate::creators_v2::CreatorMetricPagination,
        crate::creators_v2::CreatorMetricDrilldown,
        // Advisory duplicate-check DTOs shared with the retained v1 path (#5705).
        crate::thread_lifecycle::CheckDuplicatesRequest,
        crate::thread_lifecycle::CheckDuplicatesResponse,
        crate::thread_lifecycle::PotentialDuplicateMatch,
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

/// Merge every native v2 domain document into one canonical contract.
///
/// `NativeSurfaceApi` is the base so its info block is retained; the existing
/// per-domain documents contribute their paths, component schemas and security
/// scheme. Merge order is deterministic and the surfaces are disjoint.
pub fn canonical_openapi() -> utoipa::openapi::OpenApi {
    let mut openapi = NativeSurfaceApi::openapi()
        .merge_from(crate::queue::QueueApi::openapi())
        .merge_from(crate::threads::ThreadsApi::openapi())
        .merge_from(crate::issue_service::IssueApi::openapi())
        .merge_from(crate::issue_read_state::IssueReadStateApi::openapi())
        .merge_from(crate::comicvine_issue::ComicVineIssueApi::openapi())
        .merge_from(crate::custom_cbl::CustomCblApi::openapi())
        .merge_from(crate::reading_orders::ReadingOrdersApi::openapi())
        .merge_from(crate::reading_plan_sync::ReadingPlanSyncApi::openapi())
        .merge_from(crate::undo_snapshots::UndoSnapshotsApi::openapi())
        .merge_from(crate::undo_apply::UndoApplyApi::openapi())
        // #5711: the six crossover-membership operations are v2-only after the
        // retired `/api/v1` aliases were unmounted. Publish them here so the
        // generated frontend client stays aligned with the live ingress.
        .merge_from(crate::dependency_groups::dependency_groups_v2_openapi())
        // #5710: canonical v2 reading-order-group collection CRUD; the retired
        // v1 paths are no longer part of the deployed contract.
        .merge_from(crate::dependency_groups::reading_order_groups_v2_openapi());
    // The aggregate artifact is the deployed v2 runtime contract. The
    // completed-threads v1 operation has its own same-path contract and must
    // not expand the v2 inventory.
    openapi
        .paths
        .paths
        .remove("/api/v1/threads/completed/threads");
    openapi
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    fn document() -> Value {
        serde_json::to_value(canonical_openapi()).expect("canonical OpenAPI document")
    }

    /// The advisory duplicate check is a v2 AIP-136 collection custom method
    /// (#5705). It must be published with its own operation identity and DTOs,
    /// separate from both the `GET /api/v2/threads` list/filter contract
    /// (AIP-132) and the standard AIP-133 Create on the same collection (#5702).
    #[test]
    fn check_duplicates_custom_method_is_in_v2_contract() {
        let doc = document();
        let operation = &doc["paths"]["/api/v2/threads:checkDuplicates"]["post"];
        assert_eq!(operation["operationId"], "check_duplicates");
        assert_eq!(
            operation["requestBody"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/CheckDuplicatesRequest"
        );
        assert_eq!(
            operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/CheckDuplicatesResponse"
        );
        for schema in ["CheckDuplicatesRequest", "CheckDuplicatesResponse"] {
            assert!(
                doc["components"]["schemas"][schema].is_object(),
                "missing {schema} in v2 contract"
            );
        }
        // The collection read keeps its AIP-132 search/filter parameters, and
        // the collection POST remains the standard Create — neither is
        // overloaded with the advisory custom method.
        let collection = &doc["paths"]["/api/v2/threads"];
        assert!(collection["get"].is_object());
        assert!(collection["get"]["parameters"]
            .as_array()
            .unwrap()
            .iter()
            .any(|p| p["name"] == "search" && p["in"] == "query"));
        assert_eq!(
            collection["post"]["operationId"],
            "create_thread_v2_documentation"
        );
        assert_eq!(
            collection["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ThreadCreateRequest"
        );
    }

    /// #5716: the canonical preview is an AIP-136 stateless collection custom
    /// method on the lowerCamelCase `seriesMappings` collection. It must not be
    /// published as a v1 same-path operation in the v2 contract, and it must
    /// share its DTOs with the retained commit so the idempotency token stays
    /// intelligible end to end.
    #[test]
    fn series_mappings_preview_custom_method_is_in_v2_contract() {
        let doc = document();
        let operation = &doc["paths"]["/api/v2/seriesMappings:preview"]["post"];
        assert_eq!(operation["operationId"], "preview_series_mappings");
        assert_eq!(
            operation["requestBody"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/SeriesMappingPreviewRequest"
        );
        assert_eq!(
            operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/SeriesMappingPreviewResponse"
        );
        for schema in [
            "SeriesMappingPreviewRequest",
            "SeriesMappingPreviewResponse",
            "SeriesMappingPreviewRow",
            "SeriesMappingPreviewScope",
            "SeriesMappingPreviewCounts",
            "SeriesMappingPreviewProviderSeries",
        ] {
            assert!(
                doc["components"]["schemas"][schema].is_object(),
                "missing {schema} in v2 contract"
            );
        }
        assert!(
            doc["paths"]["/api/v1/catalog/series-mappings/preview"].is_null(),
            "v1 preview must not be published in the canonical v2 contract"
        );
        assert!(
            doc["paths"]["/api/v2/series-mapping-commits"]["post"].is_object(),
            "durable v2 commit must stay registered"
        );
    }

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
