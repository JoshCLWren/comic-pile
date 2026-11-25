#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Emit the native same-path reading-order-groups OpenAPI contract.
use comicpile_roll_service::dependency_groups::dependency_groups_openapi;

fn main() {
    println!(
        "{}",
        dependency_groups_openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document")
    );
}
