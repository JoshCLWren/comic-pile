//! Generated contract for the same-path native Roll v1 operations.
//!
//! These browser-called operations keep their original `/api/v1` and bare
//! `/api` URLs while the implementation moves behind the native Rust ingress
//! (#4850, Part of #4335). They are emitted as their own contract because the
//! Python handlers stay mounted until authenticated production proof, so the
//! merged frontend client schema remains the Python contract for now.
//!
//! `native/contracts/roll-v1.openapi.json` is a gitignored build output written by
//! `node scripts/generate_api_artifacts.mjs` (see `crate::contract_artifacts`).
use utoipa::OpenApi;

#[derive(utoipa::OpenApi)]
#[openapi(
    info(
        title = "ComicPile native same-path Roll v1 API",
        version = "1.0.0",
        description = "Generated contract for the native Roll handlers that retain their original method and path."
    ),
    paths(
        crate::recommendation_explanation::recommendation_explanation_documentation,
        crate::recommendation_explanation::recommendation_explanation_legacy_documentation,
    ),
    components(schemas(
        crate::recommendation_explanation::RecommendationExplanationResponse,
        crate::recommendation_explanation::ExplainableFactor,
    )),
    modifiers(&RollV1SecurityAddon)
)]
pub struct RollV1Api;

struct RollV1SecurityAddon;

impl utoipa::Modify for RollV1SecurityAddon {
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

/// Emit the same-path native Roll v1 contract.
pub fn roll_v1_openapi() -> utoipa::openapi::OpenApi {
    RollV1Api::openapi()
}
