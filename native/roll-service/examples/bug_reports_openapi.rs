//! Emit the native bug-report same-path OpenAPI contract.
use comicpile_roll_service::bug_reports::BugReportsApi;
use utoipa::OpenApi;

fn main() {
    println!(
        "{}",
        BugReportsApi::openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document")
    );
}
