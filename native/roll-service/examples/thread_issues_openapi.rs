#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Emit the native same-path thread issue-management contract for the retained browser URLs.
fn main() {
    println!(
        "{}",
        comicpile_roll_service::thread_issues::thread_issues_openapi()
            .to_pretty_json()
            .expect("serializable native same-path thread issue contract")
    );
}
