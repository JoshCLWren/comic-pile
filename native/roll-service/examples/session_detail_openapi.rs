#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Emit the native single-session same-path OpenAPI contract.
use comicpile_roll_service::session_detail::SessionDetailApi;
use utoipa::OpenApi;

fn main() {
    println!(
        "{}",
        SessionDetailApi::openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document")
    );
}
