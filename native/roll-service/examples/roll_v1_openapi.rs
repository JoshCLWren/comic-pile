#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Emit the native same-path Roll v1 contract for the retained browser URLs.
fn main() {
    println!(
        "{}",
        comicpile_roll_service::roll_v1_openapi::roll_v1_openapi()
            .to_pretty_json()
            .expect("serializable native same-path Roll contract")
    );
}
