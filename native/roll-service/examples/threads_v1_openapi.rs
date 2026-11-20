#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Emit the native same-path Thread lifecycle contract for the retained browser URLs.
fn main() {
    println!(
        "{}",
        comicpile_roll_service::threads_v1_openapi::threads_v1_openapi()
            .to_pretty_json()
            .expect("serializable native same-path Thread lifecycle contract")
    );
}
