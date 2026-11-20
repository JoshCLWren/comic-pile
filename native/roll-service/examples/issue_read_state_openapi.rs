#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Emit the native same-path issue read-state contract for the retained browser URLs.
fn main() {
    println!(
        "{}",
        comicpile_roll_service::issue_read_state::issue_read_state_openapi()
            .to_pretty_json()
            .expect("serializable native same-path issue read-state contract")
    );
}
