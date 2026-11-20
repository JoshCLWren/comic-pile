//! Per-area route registration (owner directive 2026-11-19: parallel PRs must
//! not share conflict-causing files).
//!
//! A migrated area owns its routes in one module. That module exposes a
//! [`RouteArea`] constant describing:
//!
//! * `ingress`: every `(method, path)` the Vercel outer router
//!   (`api/native_roll.rs`) must forward to native Rust;
//! * `routes`: the Axum handlers for those operations, merged into
//!   [`crate::router`];
//! * `openapi`: the area's `utoipa` document, merged into
//!   [`crate::openapi::canonical_openapi`] (and therefore the same-path
//!   contract).
//!
//! The central router, the canonical contract and the Vercel ingress all fold
//! over [`AREAS`], so adding, changing or removing a route inside an area edits
//! only that area's module. Registering a brand-new area is one sorted line
//! below. The tests here keep the three views of each area identical, so a
//! route can never be documented without being ingressed, or ingressed without
//! being documented.

use crate::AppState;
use axum::{routing::MethodFilter, Router};
use std::sync::Arc;

/// One migrated route area. See the module documentation.
pub struct RouteArea {
    /// Stable area name, used only in test failure messages.
    pub name: &'static str,
    /// Every `(method, path)` the outer Vercel router forwards to Rust.
    pub ingress: &'static [(MethodFilter, &'static str)],
    /// The area's Axum routes (state is attached by [`crate::router`]).
    pub routes: fn() -> Router<Arc<AppState>>,
    /// The area's generated OpenAPI document.
    pub openapi: fn() -> utoipa::openapi::OpenApi,
}

/// Every area registered through this module. Keep one line per area, sorted
/// by module name, so two PRs that add different areas touch different lines.
pub const AREAS: &[&RouteArea] = &[&crate::comicvine_v2::ROUTE_AREA];

/// Merge every area's routes into one stateful router fragment.
pub fn routes() -> Router<Arc<AppState>> {
    AREAS
        .iter()
        .fold(Router::new(), |router, area| router.merge((area.routes)()))
}

/// Merge every area's OpenAPI document onto `base`.
pub fn merge_openapi(base: utoipa::openapi::OpenApi) -> utoipa::openapi::OpenApi {
    AREAS
        .iter()
        .fold(base, |document, area| document.merge_from((area.openapi)()))
}

/// Every `(method, path)` the Vercel ingress must forward for registered areas.
pub fn ingress() -> impl Iterator<Item = (MethodFilter, &'static str)> {
    AREAS.iter().flat_map(|area| area.ingress.iter().copied())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    fn method_name(filter: MethodFilter) -> &'static str {
        [
            (MethodFilter::GET, "get"),
            (MethodFilter::POST, "post"),
            (MethodFilter::PUT, "put"),
            (MethodFilter::PATCH, "patch"),
            (MethodFilter::DELETE, "delete"),
        ]
        .into_iter()
        .find(|(candidate, _)| *candidate == filter)
        .map(|(_, name)| name)
        .unwrap_or_else(|| panic!("unsupported ingress method filter {filter:?}"))
    }

    /// Each area's ingress list and OpenAPI document describe exactly the same
    /// operations, every operation is generated and authenticated, and areas
    /// never overlap one another.
    #[test]
    fn every_area_ingress_matches_its_contract() {
        let mut seen = BTreeSet::new();
        for area in AREAS {
            let document =
                serde_json::to_value((area.openapi)()).expect("serializable area OpenAPI");
            let mut documented = BTreeSet::new();
            for (path, item) in document["paths"].as_object().expect("area paths") {
                for (method, operation) in item.as_object().expect("path item") {
                    assert!(
                        operation["operationId"].as_str().is_some(),
                        "{}: {method} {path} has no operationId",
                        area.name
                    );
                    assert!(
                        operation["responses"]
                            .as_object()
                            .is_some_and(|r| r.keys().any(|code| code.starts_with('2'))),
                        "{}: {method} {path} has no 2xx response",
                        area.name
                    );
                    documented.insert((method.clone(), path.clone()));
                }
            }
            let ingressed: BTreeSet<(String, String)> = area
                .ingress
                .iter()
                .map(|(method, path)| (method_name(*method).to_string(), (*path).to_string()))
                .collect();
            assert_eq!(
                ingressed, documented,
                "{}: ingress and OpenAPI operations differ",
                area.name
            );
            for operation in ingressed {
                assert!(
                    seen.insert(operation.clone()),
                    "{}: {operation:?} is registered by more than one area",
                    area.name
                );
            }
        }
    }

    /// The canonical runtime contract includes every area operation.
    #[test]
    fn canonical_contract_includes_every_area() {
        let document =
            serde_json::to_value(crate::openapi::canonical_openapi()).expect("canonical OpenAPI");
        for (method, path) in ingress() {
            let method = method_name(method);
            assert!(
                document["paths"][path][method].is_object(),
                "{method} {path} missing from the canonical contract"
            );
        }
    }
}
