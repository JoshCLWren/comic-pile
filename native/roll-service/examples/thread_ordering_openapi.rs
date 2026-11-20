#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Emit the native same-path thread ordering contract for the retained browser URLs.
fn main() {
    println!(
        "{}",
        comicpile_roll_service::thread_ordering::thread_ordering_openapi()
            .to_pretty_json()
            .expect("serializable native same-path thread ordering contract")
    );
}
