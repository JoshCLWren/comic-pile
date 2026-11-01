//! Emit the native Issue PATCH and batch-card OpenAPI contract.
use comicpile_roll_service::issue_service::IssueApi;
use utoipa::OpenApi;

fn main() {
    println!(
        "{}",
        IssueApi::openapi()
            .to_pretty_json()
            .expect("serializable OpenAPI document")
    );
}
