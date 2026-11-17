#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Emit native contracts for methods/paths retaining their original public URL.
fn main() {
    println!(
        "{}",
        comicpile_roll_service::same_path_openapi::same_path_openapi()
            .to_pretty_json()
            .expect("serializable native same-path contract")
    );
}
