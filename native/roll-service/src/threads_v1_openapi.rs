//! Generated contract for the same-path native Thread lifecycle operations.
//!
//! These browser-called operations keep their original `/api/v1/threads` URLs
//! while the implementation moves behind the native Rust ingress (#4832 part A).
//! They are emitted as their own contract because the Python handlers stay
//! mounted until authenticated production proof, so the merged frontend client
//! schema remains the Python contract for now.
//!
//! `native/contracts/threads-v1.openapi.json` is a gitignored build output written by
//! `node scripts/generate_api_artifacts.mjs` (see `crate::contract_artifacts`).
use utoipa::OpenApi;

#[derive(utoipa::OpenApi)]
#[openapi(
    info(
        title = "ComicPile native same-path Thread lifecycle v1 API",
        version = "1.0.0",
        description = "Generated contract for the native Thread lifecycle handlers that retain their original method and path."
    ),
    paths(
        crate::thread_lifecycle::create_thread_documentation,
        crate::thread_lifecycle::update_thread_documentation,
        crate::thread_lifecycle::delete_thread_documentation,
        crate::thread_lifecycle::exclude_thread_documentation,
        crate::thread_lifecycle::restore_thread_documentation,
        crate::thread_lifecycle::reactivate_thread_documentation,
        crate::thread_lifecycle::set_pending_thread_documentation,
        crate::thread_lifecycle::list_stale_threads_documentation,
        crate::thread_lifecycle::list_excluded_threads_documentation,
        crate::thread_lifecycle::check_potential_duplicates_documentation,
        crate::thread_lifecycle::list_thread_groups_batch_documentation,
    ),
    components(schemas(
        crate::thread_lifecycle::ThreadResponse,
        crate::thread_lifecycle::ThreadCreateRequest,
        crate::thread_lifecycle::ThreadUpdateRequest,
        crate::thread_lifecycle::ReactivateRequest,
        crate::thread_lifecycle::SetPendingRequest,
        crate::thread_lifecycle::CheckDuplicatesRequest,
        crate::thread_lifecycle::CheckDuplicatesResponse,
        crate::thread_lifecycle::PotentialDuplicateMatch,
        crate::thread_lifecycle::GroupsBatchRequest,
        crate::thread_lifecycle::DependencyGroupSummary,
        crate::roll_override::RollResponse,
        crate::threads::ThreadListResponse,
        crate::threads::ThreadListItem,
        crate::threads::ThreadTag,
        crate::threads::ComicVineMappingHealth,
        crate::threads::QueueSeriesMetadata,
    )),
    modifiers(&ThreadsV1SecurityAddon)
)]
pub struct ThreadsV1Api;

struct ThreadsV1SecurityAddon;

impl utoipa::Modify for ThreadsV1SecurityAddon {
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

/// Emit the same-path native Thread lifecycle contract.
pub fn threads_v1_openapi() -> utoipa::openapi::OpenApi {
    ThreadsV1Api::openapi()
}
