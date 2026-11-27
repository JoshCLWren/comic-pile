#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Emit the native same-path reading-order-groups contract (#5711).
fn main() {
    println!(
        "{}",
        comicpile_roll_service::dependency_groups::dependency_groups_openapi()
            .to_pretty_json()
            .expect("serializable same-path reading-order-groups contract")
    );
}
